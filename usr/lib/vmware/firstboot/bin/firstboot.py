#!/usr/bin/env python
########################################################################
# Copyright 2016 VMware, Inc.  All rights reserved.
# -- VMware Confidential
########################################################################

"""Script for applying first boot configuration.

   The firstboot data is captured by the installer and provided by
   a json file. This script is designed to run on every boot, but it will
   apply configuration only if the data file is available. This script is
   currently used to supply firstboot data captured by the installer.

"""

import sys
import os
import json
import esxclipy
import time
import subprocess
import datetime
import tarfile
import stat
import shutil
import vmware.vsi as vsi
from argparse import ArgumentParser
import re

configPath = "/var/lib/vmware/firstboot/firstboot.json"
licenseFile = "/etc/vmware/vmware.lic"
licenseCfgFile = "/etc/vmware/license.cfg"

clipy = None
def esxcli(*cmd):
   """Run an esxcli command

      Parameters:
         * cmd - the command to run

      Returns:
         Output of the command
   """
   global clipy
   if clipy == None:
      clipy = esxclipy.EsxcliPy(True)
   status, output = clipy.Execute(cmd)
   if status != 0:
      raise RuntimeError(output)
   return eval(output)


def timestamp():
   """Generate a timestamp in a standard format for logging.

      See Util_FormatTimestampUTC for format spec.

      Returns:
         The timestamp
   """
   dt = datetime.datetime.utcnow()
   return "%04u-%02u-%02uT%02u:%02u:%02u.%03uZ" % \
      (dt.year,
       dt.month,
       dt.day,
       dt.hour,
       dt.minute,
       dt.second,
       dt.microsecond/1000)


def log(message):
   """Log a message

      Parameters:
         * message - the message to log

      Returns:
         None
   """
   logFileName = "/var/log/firstboot.log"
   try:
      # reset log if log is bigger than 1 MB
      if os.path.exists(logFileName):
         statinfo = os.stat(logFileName)
         if statinfo.st_size > 1024 * 1024:
            os.remove(logFileName)

      logFile = open(logFileName, "a+")
      logFile.write(timestamp() + ": " + message + "\n")
      logFile.close()
   except Exception as e:
      # Do not panic because of logging errors
      pass


def runLocalcli(command, message):
   """Run a cli command

      Parameters:
         * command - The command to run
         * message - custom message to be written to log, along with
                     the command output/error
      Returns:
         None
   """
   output, error = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE).communicate()
   if output:
      log("%s: %s" % (message, output))
   if error:
      log("%s: %s" % (message, error))


def updateFile(filePath, content):
   """Replace the contents of a file

      Parameters:
         * content - The content to be written to the file

      Returns:
         None
   """
   with open(filePath, "w") as f:
      f.write(content)


def replacePassword(password):
   """Replace the password on the system

      Parameters:
         * password - The password that should be added
           to the shadow file.

      Returns:
         None
   """
   fp = open('/etc/shadow')
   lines = fp.readlines()
   fp.close()

   replacement = ":%s:" % password
   pattern = ':[^:]*:'
   fp = open('/etc/shadow', 'w')
   for line in lines:
      if line.startswith('root:'):
         line = re.sub(pattern, replacement, line, count=1)
      fp.write(line)
   fp.close()


def removeOnetimetgz(bootCfgPath):
   """Remove onetime.tgz from boot.cfg

      Parameters:
         * bootCfg - full path to boot.cfg

      Returns:
         None
   """
   fp = open(bootCfgPath)
   lines = fp.readlines()
   fp.close()

   # erase the onetime.tgz file
   fp = open(bootCfgPath, 'w')
   verification = ''
   for line in lines:
      if line.startswith('modules='):
         line = line.replace(' --- onetime.tgz', '')
      fp.write(line)
      verification += line
   fp.close()

   # verify file write in case of failed USB writes
   fp = open(bootCfgPath)
   contents = fp.read()
   fp.close()
   if contents != verification:
      sys.exit(2) # TODO: IS THIS THE RIGHT CODE??? IMPROVE THIS


def copyConfigFiles(keyVals):
   """Copy over the required config files

      Parameters:
         * keyVals - src to dst file paths.

      Returns:
         None
   """
   for val in keyVals:
      try:
         makeSticky = False
         dstPath = keyVals[val]
         if os.path.exists(dstPath):
            mode = os.stat(dstPath).st_mode
            if mode & stat.S_ISVTX:
               # add sticky bit only to files that already have the sticky bit
               makeSticky = True
         shutil.copyfile(val, dstPath)
         if makeSticky:
            os.chmod(dstPath, mode | stat.S_ISVTX)
      except Exception as e:
         message = "Firstboot, failed to copy to %s: %s" %\
                   (str(os.path.basename(dstPath)), e)
         log(message)


def setKeyboardMap(keyMap):
   """Set the keyboard layout

      Parameters:
         * keyMap - the layout of keyboard

      Returns:
         None
   """
   esxcli("system","settings", "keyboard", "layout", "set", "--layout", str(keyMap))


def fixupGPTTables():
   """Run the script to fixup GPT tables.
      Remove frstbt.tgz from boot.cfg

      Parameters:
         * None

      Returns:
         None
   """
   try:
      log("Firstboot: fixing up GPT tables")
      runLocalcli("/usr/lib/vmware/firstboot/bin/firstboot_fixup_gpt_tables.sh",
                  "Fixup GPT Tables")
   except Exception as e:
      message = "Firstboot: Failed to fixup GPT tables: %s" % e
      log(message)
   try:
      log("Firstboot: removing frstbt from boot.cfg")
      runLocalcli("/usr/lib/vmware/firstboot/bin/firstboot_remove_frstbt_bootcfg.sh",
                  "Removing frstbt entry")
   except Exception as e:
      message = "Firstboot: Failed to remove frstbt.tgz from boot.cfg: %s" % e
      log(message)


def loadConfig():
   """Load the configuration from the json data file

      Parameters:
         * None

      Returns:
         The json object if the data file is available.
         None if the file does not exist.
         Exception on any error
   """
   try:
      if os.path.exists(configPath):
         with open(configPath, mode='r') as f:
            retval = json.load(f)
            return retval
      else:
         return None
   except Exception as e:
      message = "Failed to load firstboot configuration: %s" % e
      raise RuntimeError(message)


def applyEarlyConfig(data):
   """Function thats called very early in the boot process.
      (before jumpstart).

      Parameters:
         * data - The json object which has the firstboot data

      Returns:
         0
   """
   if "copyFiles" in data:
      log("Firstboot: update config files")
      try:
         copyConfigFiles(data['copyFiles'])
      except Exception as e:
         message = "Firstboot: Failed to copy config files: %s" % e
         log(message)
   return 0


def applyLateConfig(data):
   """Function thats called very late in the boot process.
      (after jumpstart)

      If we fail to update any configuration, we just log the
      error and proceed.

      Parameters:
         * data - The json object which has the firstboot data

      Returns:
         0
   """
   if "password" in data:
      log("Firstboot: updating password")
      try:
         replacePassword(data['password'])
      except Exception as e:
         message = "Firstboot: Failed to update password: %s" % e
         log(message)

   if "keyboard" in data:
      log("Firstboot: setting keyboard layout")
      try:
         setKeyboardMap(data['keyboard'])
      except Exception as e:
         message = "Firstboot: Failed to set keyboard layout: %s" % e
         log(message)

   if "licenseFile" in data:
      log("Firstboot: updating license file")
      try:
         updateFile(licenseFile, data['licenseFile'])
      except Exception as e:
         message = "Firstboot: Failed to update the license file: %s" % e
         log(message)

   if "licenseCfgFile" in data:
      log("Firstboot: updating license cfg file")
      try:
         updateFile(licenseCfgFile, data['licenseCfgFile'])
      except Exception as e:
         message = "Firstboot: Failed to update the license cfg file: %s" % e
         log(message)

   if "acceptanceLevel" in data:
      log("Firstboot: setting acceptance level")
      try:
         runLocalcli("/usr/lib/vmware/firstboot/bin/firstboot_acceptancelevel.py",
                     "Acceptance Level")
      except Exception as e:
         message = "Firstboot: Failed to set acceptance level: %s" % e
         log(message)

   if "AD" in data:
      log("Firstboot: updating AD config if applicable")
      try:
         runLocalcli("/usr/lib/vmware/firstboot/bin/firstboot_ad_migration.py",
                     "Active Directory")
      except Exception as e:
         message = "Firstboot: Failed to update AD config: %s" % e
         log(message)

   if "vsanWitness" in data:
      log("Firstboot: VSAN Witness Virtual Appliance Configuration")
      try:
         cmds = [
            (('/bin/sh', '/usr/lib/vmware/vsan/witnessovf/firstboot/late/003.firstboot_genkeys.sh'), 'SSH/SSL Keys'),
            (('/bin/python', '/usr/lib/vmware/vsan/witnessovf/firstboot/late/004.passwd_update.pyc'), 'Password Update'),
         ]
         for cmd in cmds:
            runLocalcli(*cmd)
      except Exception as e:
         message = "Firstboot: VSAN Witness Virtual Appliance Configuration failed: %s" % e
         log(message)

   if "bootCfgPath" in data:
      log("Firstboot: removing onetime.tgz from boot.cfg")
      try:
         removeOnetimetgz(data['bootCfgPath'])
      except Exception as e:
         message = "Firstboot: Failed to remove onetime.tgz: %s" % e
         log(message)

   try:
      if "fixupGPT" in data:
         fixupGPTTables()
   except Exception as e:
      message = "Firstboot: Failed to fixup GPT tables: %s" % e
      log(message)

   return 0


def main(argv=None):
   argv = argv or sys.argv

   parser = ArgumentParser()
   exclusive = parser.add_mutually_exclusive_group()
   exclusive.add_argument(
      '-e', '--early', action='store_true', default=False,
      dest='early',
      help="Apply early firstboot configuration",
   )
   exclusive.add_argument(
      '-l', '--late', action='store_true', default=False,
      dest='late',
      help="Apply late firstboot configuration",
   )
   options = parser.parse_args(argv[1:])

   data = loadConfig()
   if data is None:
      return 0

   log("firstboot configuration found")

   try:
      if options.early:
         log("Applying early firstboot configuration")
         return applyEarlyConfig(data)
      elif options.late:
         log("Applying late firstboot configuration")
         return applyLateConfig(data)
      else:
         return 0
   except Exception as e:
      message = "Failed to apply firstboot configuration: %s" % e
      log(message)
      return 1

if __name__ == '__main__':
   sys.exit(main())
