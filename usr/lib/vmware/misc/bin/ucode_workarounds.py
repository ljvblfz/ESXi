#!/bin/python

from __future__ import print_function
import re
from vmware import vsi

"""Inform the monitor of any required workarounds for this machine's
CPU and microcode version, by adding line(s) to /etc/vmware/config.
Conversely, if a workaround is not required but its config lines are
found in /etc/vmware/config (i.e., the workaround was added
previously, either by this script or manually by a user), remove the
lines.

A workaround has the following format:

   "issue" is a name for the issue (used for logging).

   "config" is a string to be added to the config file (a newline is
   appended automatically).

   "regexp" is a regular expression that matches "config" and variants
   of "config" that a user might have manually placed in the file.

   "processors" is a list of affected processors; each entry contains
   the vendor string, family/model/stepping (in hex), platform ID
   bits (meaningful only for Intel), and the range of microcode
   versions that need the workaround.  The range is expressed as (bad,
   good), where bad > good, and revision r needs the workaround if and
   only if bad >= r > good.

"workarounds" is a tuple that can contain multiple workarounds (the
Python code supports it), but currently there is only one.

"""

workarounds = (
   {
      'issue': 'IBRS instability',
      'config': 'cpuid.7.edx = "----:00--:----:----:----:----:----:----"',
      'regexp': r'^cpuid\.7\.edx *= *"----:00--:----:----:----:----:----:----" *$\n?',

      # Updated from Intel "Microcode Revision Guidance" dated
      # 1/23/2018 (which unfortunately has multiple typos), plus all
      # other available information.  Further updated 2/6/2018.
      'processors': (
         # Vendor name    Plat   F/M/S     Bad if <=   Good if <=   Product
         ('GenuineIntel', 0x32, '06/3c/3', 0x23,       0x22,       'Haswell'),
         ('GenuineIntel', 0xc0, '06/3d/4', 0x28,       0x25,       'Broadwell U/Y'),
         ('GenuineIntel', 0xed, '06/3e/4', 0x42a,      0x428,      'Ivy Bridge E, EN, EP'),
         ('GenuineIntel', 0x6f, '06/3f/2', 0x3b,       0x3a,       'Haswell E, EP'),
         ('GenuineIntel', 0x80, '06/3f/4', 0x10,       0xf,        'Haswell EX'),
         ('GenuineIntel', 0x72, '06/45/1', 0x21,       0x20,       'Haswell ULT'),
         ('GenuineIntel', 0x32, '06/46/1', 0x18,       0x17,       'Haswell Perf Halo'),
         ('GenuineIntel', 0x22, '06/47/1', 0x1b,       0x17,       'Broadwell H 43e'),
         ('GenuineIntel', 0xef, '06/4f/1', 0x0b000025, 0x0b000022, 'Broadwell E, EP, EP4S, EX'),
         ('GenuineIntel', 0xb7, '06/55/4', 0x0200003c, 0x02000039, 'Skylake Server'),
         ('GenuineIntel', 0x10, '06/56/2', 0x14,       0x11,       'Broadwell DE'),
         ('GenuineIntel', 0x10, '06/56/3', 0x07000011, 0x0700000e, 'Broadwell DE'),
         ('GenuineIntel', 0xc0, '06/8e/9', 0x80,       0x70,       'Kaby Lake U/Y, U23e'),
         ('GenuineIntel', 0xc0, '06/8e/a', 0x80,       0x70,       'Coffee Lake U43e, KBL-R U'),
         ('GenuineIntel', 0x2a, '06/9e/9', 0x80,       0x70,       'Kaby Lake H/S/X, Xeon E3'),
         ('GenuineIntel', 0x22, '06/9e/a', 0x80,       0x70,       'Coffee Lake H/S (S 6+2)'),
         ('GenuineIntel', 0x02, '06/9e/b', 0x80,       0x72,       'Coffee Lake S (4+2)'),
      )
   },
)

# Persistent configuration file
configName = '/etc/vmware/config'

def getHostProcessor():
   """Return a dict containing, among other things, the host CPU's vendor
   (as 'name'), family, model, stepping, platformID (0 for AMD), and
   microcode revision (as 'curRevision').
   """
   host = vsi.get('/hardware/cpu/cpuList/0')
   if host['name'] == 'GenuineIntel':
      host['platformID'] = (vsi.get('/hardware/msr/pcpu/0/addr/0x17') >> 50) & 7
   else:
      host['platformID'] = -1
   return host

def match(host, affected):
   """Check whether the given host processor, from getHostProcessor()
   matches the given affected processor, from workarounds[]['processors'].
   """
   # Do vendor, family, model, and stepping match?
   a = {}
   a['name'] = affected[0]
   a['family'], a['model'], a['stepping'] = \
      [int(x, 16) for x in affected[2].split('/')]
   for key in a.keys():
      if host[key] != a[key]:
         return False

   # Does microcode apply to this platform?
   if (host['platformID'] != -1 and
       ((1 << host['platformID']) & affected[1]) == 0):
      return False
   
   # Is microcode revision in the bad range?
   bad = affected[3]
   good = affected[4]
   cur = host['curRevision']
   if cur > good and cur <= bad:
      return True
   return False

def applyWorkarounds(workarounds, host):
   """Check for applicable workarounds and apply/remove as needed."""
   for w in workarounds:

      # Check if workaround is required on this machine
      required = False
      for affected in w['processors']:
         if match(host, affected):
            required = True
            break

      # Read existing config and check if workaround is present
      try:
         with open(configName, 'r') as f:
            config = f.read()
            present = re.search(w['regexp'], config, flags=re.M) is not None
      except IOError:
         config = ''
         present = False

      if required and present:
         print('Found vmm workaround for issue "%s" on CPU "%s"' %
               (w['issue'], affected[5]))

      if required and not present:
         # Workaround is required; add if not present
         print('Adding vmm workaround for issue "%s" on CPU "%s"' %
               (w['issue'], affected[5]))
         with open(configName, 'a') as f:
            print(w['config'], file=f)

      if not required and present:
         # Workaround is not required; remove it if present in
         # persistent config.
         newConfig = re.sub(w['regexp'], '', config, flags=re.M)
         print('Removing vmm workaround for issue "%s"' % w['issue'])
         with open(configName, 'w') as f:
            f.write(newConfig)

def main():
   host = getHostProcessor()
   applyWorkarounds(workarounds, host)

if __name__ == '__main__':
   main()


