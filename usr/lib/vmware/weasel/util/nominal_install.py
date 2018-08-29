#! /usr/bin/python

###############################################################################
# Copyright (c) 2016 VMware, Inc.
#
# This file is part of Weasel.
#
# Weasel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# version 2 for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#

from __future__ import print_function

import os
import sys
sys.path.append('/usr/lib/vmware/')
from weasel.log import log
from os.path import dirname, join

TASKNAME = 'NominalInstall'
TASKDESC = 'Install Nominal Drivers if present in Weasel'


def symlinkDirs(source, target):
   """symlinkDirs

   Create symbolic links for every file in the source directory
   in the target directory.

   Creates the target directory if it doesn't exist.
   """
   try:
       if not os.path.exists(target):
           os.makedirs(target)
   except OSError as err:
       log.warning('%s: %s' % (err.strerror, target))
       return err.errno

   for fileName in os.listdir(source):
      status = 0
      try:
          fullSrc = join(source, fileName)
          fullTarget = join(target, fileName)
          if os.path.exists(fullTarget):
              os.remove(fullTarget)
          os.symlink(fullSrc, fullTarget)
      except OSError as err:
          log.warning('%s: %s' % (err.strerror, fullTarget))
          status = err.errno
          break

   return status


def main(argv):
    # Directory where this file is running.
    # If present, nominal drivers are located beneath an adjacent directory.
    scriptDir = os.path.abspath(os.path.dirname(__file__))
    nominalDir = join(dirname(scriptDir), 'nominal')
    nominalModulesDir = join(nominalDir, 'vmkmod')
    nominalMapsDirs = join(nominalDir, 'fallback.map.d')
    nominalPciidsDir = join(nominalDir, 'fallback.pciids.d')
    NOMINAL_TAGS_DIR = join(nominalDir, 'fallback.tags.d')

    # System install locations:
    #         This script will create symbolic links in these locations
    #         to conserve space.
    systemModulesDir = '/usr/lib/vmware/vmkmod/'
    systemMapsDir = '/etc/vmware/fallback.map.d/'
    systemPciidsDir = '/usr/share/hwdata/fallback.pciids.d/'
    systemTagsDir = '/usr/share/hwdata/fallback.tags.d/'

    # Location of the vmklinux module
    VMKLINUX = join(systemModulesDir, 'vmklinux_9')

    if os.path.exists(VMKLINUX):
       #
       # vmklinux_9 is present in the combined and classic images.
       # Don't use nominal drivers when vmklinux is present.
       #
       log.info('Vmklinux module %s found, skipping nominal driver'
                'installation' % VMKLINUX)
       return 0

    if not os.path.exists(nominalDir):
       #
       # vmklinux is not present ***and*** the nominal drivers
       # are not present.  This is wrong for the foreseeable future,
       # because we expect the NOVA image to contain the missing
       # driver even after all the 'nominal' drivers are replaced
       # by certified driver equivalents.
       #
       log.warning('Nominal drivers are missing from the NOVA '
                   'installer')
       return 1

    log.info('Installing nominal drivers for the NOVA installer.')
    if os.path.exists(nominalModulesDir):
       status = symlinkDirs(nominalModulesDir, systemModulesDir)
    if status == 0 and os.path.exists(nominalPciidsDir):
       status = symlinkDirs(nominalPciidsDir, systemPciidsDir)
    if status == 0 and os.path.exists(NOMINAL_TAGS_DIR):
       status = symlinkDirs(NOMINAL_TAGS_DIR, systemTagsDir)
    if status == 0 and os.path.exists(nominalMapsDirs):
       status = symlinkDirs(nominalMapsDirs, systemMapsDir)

    if (status == 0):
       log.info('All nominal driver files sucessfully linked.')
    else:
       log.warning('Nominal driver installation failed.')

    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
