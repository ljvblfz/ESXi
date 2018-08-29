#!/usr/bin/python
# Copyright 2010-2017 VMware, Inc.  All rights reserved.
"""
This module upgrades /etc/sfcb/sfcb.cfg from version to version.
"""
from __future__ import print_function

__author__ = "VMware, Inc"

import os
import sys
import optparse
import shutil
import fileinput
import re
import subprocess
import traceback
import glob
from syslog import *

VMWARE_BIN = "/bin/vmware"
CONFIG_BASE_NAME = "sfcb.cfg"
ROOT_CFG = "etc/sfcb"
SFCB_CFG_PATH = "%s/%s" % (ROOT_CFG, CONFIG_BASE_NAME)
rx = re.compile(r'^\s*#\s+VMware\sESXi\s+([\d\.]+).*')
pgmrx = re.compile(r'^VMware\sESXi\s+([\d\.]+).*')

def getCurrentVMwareVersion():
  '''Return version number and update global with full version string'''
  VMWARE_V = subprocess.check_output([VMWARE_BIN, '-v'])
  return pgmrx.match(VMWARE_V.decode('utf-8')).group(1)


def processArgs():
   parser = optparse.OptionParser()
   parser.add_option('--config-stage', dest='stageroot', metavar='PATH',
         help='Path to root of staged configuration files.')
   parser.add_option('--check-enable', dest='checkEnable', action="store_true",
         help='this option auto enables sfcbd based on providers installed')
   options, args = parser.parse_args()
   return options


def getProperties(fn):
   '''Read the files version and key/values from fn
    '''
   version = ""
   properties = {}
   with open(fn) as fp:
      for line in fp:
          # ignore comments
          if line.startswith("#"):
             rslt = rx.match(line)
             if rslt:
                version = rslt.group(1)
                continue
          (n, c, v) = line.strip().partition(':')
          if v:
             properties[n.strip()] = v
   if version == "0.0.0":   # magic value, use current system value
      version = None
   return (properties, version)


def setPermissions(target, removesticky=False):
   # can't use stat values as they don't have a macro
   # for setting the sticky bit
   # 0x3A4 (hex) -> 1644 (octal)
   # 0x124 (hex) -> 444 (octal)
   if removesticky:
      os.chmod(target, 0x124)
   else:
      os.chmod(target, 0x3A4)

# removing explicit operator configuration entries, must vob
sfcbobsoletes = ['providerDirs', 'registrationDir' ]
vobOn = ['enableSSLv3', 'enableTLSv1', 'enableTLSv1_1']
sfcbobsoletes.extend(vobOn)

sfcbupdates = ['basicAuthLib',
               'certificateAuthLib',
               'sslClientCertificate',
               'sslClientTrustStore',
               'sslCertificateFilePath',
               'sslKeyFilePath']

def set_enabled_state(nps, priorVersion):
   '''Keep sfcbd running for 5.x and 6.0 releases, otherwise its disabled'''
   if priorVersion is None:
     return
   if priorVersion.startswith("5"):
        nps['enabled'] = 'true'
   if priorVersion.startswith("6.0"):
        nps['enabled'] = 'true'
   syslog(LOG_INFO, "Administrative state of sfcbd after upgrade from '%s' is %s" % (priorVersion, nps['enabled'].strip()))

def sendVob(cfgTokens):
   '''report upgrade removed user configuration '''
   cmd = ["/usr/lib/vmware/vob/bin/addvob", "vob.user.weak.ssl.protocol"]
   try:
      subprocess.check_call(cmd)
   except subprocess.CalledProcessError:
      syslog(LOG_ERR, "Raise VOB (%s) failed" % cmd)

def migrateSfcbConfig(options):
   '''
   Migrate an SFCB Config to the current format. Config properties in obsoletes list will be
   dropped in new config file. Config properties in updates list will be updated with the
   value in updated config file. Other customer config properties will be kept unchanged.
   New config properties in update config file will be added.
   '''
   # c: customer u: update n: new
   cfile = os.path.join(options.stageroot, SFCB_CFG_PATH)
   ufile = os.path.join(options.stageroot, "%s.new" % SFCB_CFG_PATH)

   if not os.path.isfile(ufile):
      syslog(LOG_ERR, "Upgrade sfcb config failed, factory setting file '%s' missing" % ufile)
      return False

   if not os.path.isfile(cfile) or os.path.getsize(cfile) == 0:
      syslog(LOG_WARNING, "file %s is missing/empty, reverting to factory." % cfile)
      version = getCurrentVMwareVersion()
      shutil.copy(ufile, cfile)
      cnt = 0
      # replace 2nd line with version reported by this system
      for line in fileinput.input(cfile, inplace = 1):
           cnt += 1
           if cnt == 2:
              line = '# VMware ESXi %s' % version
           print(line, end=' ')
      setPermissions(cfile)
      return True

   # ensure permissions are correct
   setPermissions(cfile)

   cps, priorVersion = getProperties(cfile)
   if priorVersion is None:
      syslog(LOG_ERR, "version of %s is not readable, turning sfcbd administratively off." % cfile)
   ups, newVersion = getProperties(ufile)
   if newVersion is None: # get value from sfcbd program itself
      newVersion = getCurrentVMwareVersion()

   if priorVersion == newVersion:
        syslog(LOG_INFO, "new install or upgrade previously completed, no changes made at version %s" % newVersion)
        return True
   nps = {}

   # remove obsolete directives
   vobTokens = []
   for p in cps:
      if p not in sfcbobsoletes:
         nps[p] = cps[p]
      else:
        if p in vobOn:
          vobTokens.append(p)

   # don't overwrite existing directives if not required
   for p in ups:
      if p not in cps or p in sfcbupdates:
         nps[p] = ups[p]
   # set enabled state off only for new installs
   set_enabled_state(nps, priorVersion)

   if os.path.isfile(cfile):
      # make a backup of the old config just in case we screw something up
      backup = cfile + '.old'
      shutil.move(cfile, backup)
      syslog(LOG_INFO, "Backup of original config file here: %s" % backup)
      setPermissions(backup, removesticky = True)

   f = open(cfile, 'w')
   f.write('# Generated by sfcb-config.py. Do not modify this header.\n')
   f.write('# VMware ESXi %s\n' % getCurrentVMwareVersion())
   f.write('#\n')
   for p in sorted(nps.keys()):
      f.write('%s:%s\n' % (p, nps[p]))
   f.close()
   setPermissions(cfile)
   if vobTokens:
     syslog(LOG_CRIT,
            "Upgrade detected weak SSL protocols which were removed.")
     syslog(LOG_CRIT, "SFCB configuration tokens removed were: %s." % \
              ",".join(vobTokens))
     sendVob(vobTokens)
   return True

def CheckAndEnable():
   '''Check for 3rd party cim providers and if found set sfcb state to enabled'''
   cfg_file = '/etc/sfcb/sfcb.cfg'
   tmp_file = '/etc/sfcb/sfcb.cfg.tmp'
   boxed = {'/var/lib/sfcb/registration/vmw_base-providerRegister' : None,
            '/var/lib/sfcb/registration/sfcb_base-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_pci-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_omc-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_iodmProvider-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_vi-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_hdr-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_hhrcwrapper-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_sfcbrInterop-providerRegister' : None,
            '/var/lib/sfcb/registration/vmw_kmodule-providerRegister' : None,
            }
   have3rd = False
   modified = False
   for regFile in glob.glob('/var/lib/sfcb/registration/*-providerRegister'):
       if regFile not in boxed:
           have3rd = True
           break
   if not have3rd:
      syslog(LOG_INFO, "No third party cim providers installed")
      return 0
   with open(cfg_file, 'r') as fp:
       with open(tmp_file, 'w') as out:
           for line in fp:
               entry = line.split(':')
               if entry[0].strip() == 'enabled' and entry[1].strip() == 'false':
                   out.write('enabled: true\n')
                   modified = True
               else:
                   out.write(line)
   if modified:
       try:
           os.rename(tmp_file, cfg_file)
           syslog(LOG_INFO, "updated %s sfcbd enabled" % cfg_file)
       except Exception as err:
           syslog(LOG_ERR, "update %s with %s failed %s" % (cfg_file, tmp_file,
                  str(err)))
       return 1
   else:
     syslog(LOG_DEBUG, "Configuration not changed, already enabled")
   return 0

def main():
   EXIT_SUCCESS = 0
   EXIT_FAILURE = 1
   flags = LOG_PID
   # only write to stderr if run interactively, otherwise write to syslog
   if os.isatty(sys.stdin.fileno()):
     flags |=  LOG_PERROR
   openlog('sfcbd-config', flags, LOG_DAEMON)
   options = processArgs()
   if options.stageroot:
     if migrateSfcbConfig(options):
       syslog(LOG_INFO, "file /etc/sfcb/sfcb.cfg update completed.")
     else:
       syslog(LOG_ERR, "upgrade failed, see prior error msgs.")
       sys.exit(EXIT_FAILURE)
   elif options.checkEnable:
     sys.exit(CheckAndEnable())
   else:
     syslog(LOG_ERR, "expected command line flags, failing command.")
     sys.exit(EXIT_FAILURE)
   sys.exit(EXIT_SUCCESS)

if __name__ == '__main__':
   try:
      sys.exit(main())
   except SystemExit:
      pass
   except Exception as err:
      syslog(LOG_ERR, "upgrade failed, unexpected exception is:")
      syslog(LOG_ERR, 'Unexpected exception: %s -- %s' % (err, traceback.format_exc()))
