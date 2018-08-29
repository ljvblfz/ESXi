#!/bin/python
#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Migrate ssh/sshd config files by preserving certain changes made to the files.
#
# Currently sshd_config and ssh_config are handled by full clobber on upgrade.
#

import sys
import os
import logging, logging.handlers

def setupLogging():
    handler = logging.handlers.SysLogHandler(address='/dev/log')
    formatter = '%(name)s:%(levelname)s: %(message)s'
    handler.setFormatter(logging.Formatter(formatter))

    global log
    log = logging.getLogger('ssh-upgrade-config')
    for h in log.handlers:
        log.removeHandler(h)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

def IsSameVersion(fromConf, toConf):
    VERSION_PREFIX = '# Version '

    if not toConf[0].lower().startswith(VERSION_PREFIX.lower()):
        log.warning('Default config file does not contain version entry')
        return False

    if not fromConf[0].lower().startswith(VERSION_PREFIX.lower()):
        log.info('Existing config file does not contain version entry')
        return False

    if fromConf[0].strip().lower() == toConf[0].strip().lower():
        log.debug('From and to config are on the same version')
        return True

    log.debug('From and to config are on different versions [existing: %s, new: %s]'
          % (fromConf[0][len(VERSION_PREFIX):].strip(),
             toConf[0][len(VERSION_PREFIX):].strip()))
    return False

class SshdMigrate:
    def __init__(self):
        pass

    def preserveConfig(self, force):
        # prepare list of all config files from which config entries need
        # to be manipulated.
        files = ['/etc/ssh/sshd_config',
                 '/etc/ssh/ssh_config',
                ]

        for origFile in files:
            self.preserveSingleConfig(origFile, force=force)

    def preserveSingleConfig(self, origFile, defFile=None, destFile=None,
                             force=False):
        if defFile is None:
            # visorFS provides the VIB's original as .#filename
            defFile = os.path.join(os.path.dirname(origFile),
                                   '.#' + os.path.basename(origFile))
        if destFile is None:
            destFile = origFile

        # check if the file has been changed away from the default
        if not os.path.exists(defFile):
            log.info('File "%s" unmodified, upgrade does not apply' % (origFile))
            return

        # read the old version from the existing file
        fromConf = None
        try:
            fromConf = open(origFile, 'r').readlines()
        except Exception as e:
            log.warning('Failed to parse config file %s: %s' % (origFile, e))

        # read the new version from the default file.
        toConf = None
        try:
            toConf = open(defFile, 'r').readlines()
        except Exception as e:
            log.error('Failed to parse config file %s: %s' % (defFile, e))
            return
        if toConf is None:
            log.error('Failed to parse default config file: %s' % defFile)
            return

        if fromConf is None:
            # if the existing sshd_config file got messed up, we replace it with the default.
            log.warning('Failed to load existing config file: %s' % origFile)
            log.warning('Replacing %s with default config %s' % (destFile, defFile))
        elif not force and IsSameVersion(fromConf, toConf):
            # if force is not true, we only migrate if the version in the from file and
            # the new file is different.
            log.debug('Skip migrating since the version of the new file is the same as the version of the existing file')
            return
        else:
            # With the 6.6.2 FIPS upgrades, force a clobber.
            # We can't tell which pre-existing settings are "secure".
            # Log fragment below would be useful if non-clobber upgrade is impl.
            # log.info('Carrying some config entries from file "%s" to file "%s" [force=%s]' \
            #        % (origFile, destFile, force))
            pass

        # write the updated config to the target.
        tmpFile = destFile + ".tmp"
        log.info('Writing updated config to temporary file %s' % tmpFile)
        try:
            with open(tmpFile, 'w') as f:
               f.writelines(toConf)
        except Exception as e:
            log.error('Failed to write to temporary file %s: %s' % (tmpFile, e))
            return

        # rename the temporary file
        log.info('Renaming file %s to %s' % (tmpFile, destFile))
        try:
            os.rename(tmpFile, destFile)
        except Exception as e:
            log.error('Failed to rename file %s to %s: %s' % (tmpFile, destFile, e))

setupLogging()
try:
    migrator = SshdMigrate()
    migrator.preserveConfig(force = False)
except Exception as e:
    log.warning('Caught unexpected exception: %s' % e)
    import traceback
    log.warning(traceback.print_stack())
