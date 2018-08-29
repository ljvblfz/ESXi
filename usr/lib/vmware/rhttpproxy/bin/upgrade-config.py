#!/bin/python

#
# Copyright 2011-2013 VMware, Inc.  All rights reserved.
#
# Migrate rhttpproxy config files by preserving certain changes made to the files.
#
# Currently only config.xml is handled as follows:
#  - the new config entries are always loaded from default-config.xml file.
#  - existing entries are pulled from config.xml file.
#  - the result is written to config.xml.
#

import sys
import os
from lxml import etree
from optparse import OptionParser
import logging, logging.handlers

def CreateConfigEntry(toDoc, entry):
    items = entry.split('/')[2:]
    toE = toDoc.getroot()
    for item in items:
        toTemp = toE.xpath(item)
        if len(toTemp) > 0:
            toE = toTemp[0]
        else:
            # Try to find if such an element is commented out
            # and insert the newly created element just before the comment.
            # This is not really useful because Vmacore will remove all comments
            # when writing hostd's config.xml file, but is useful for diff.
            nodes = toE.iter(etree.Comment)
            comment = None
            for n in nodes:
                if n.text.strip().startswith('<' + item):
                    comment = n
                    break
            if comment != None:
                el = etree.Element(item)
                toE.insert(toE.index(comment), el)
                toE = el
            else:
                toE = etree.SubElement(toE, item)
    return toE

def setupLogging():
    handler = logging.handlers.SysLogHandler(address='/dev/log')
    formatter = '%(name)s:%(levelname)s: %(message)s'
    handler.setFormatter(logging.Formatter(formatter))

    global log
    log = logging.getLogger('rhttpproxy-upgrade-config')
    for h in log.handlers:
        log.removeHandler(h)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

def IsSameVersion(fromDoc, toDoc):
    fromNode = fromDoc.xpath('/config/version')
    toNode = toDoc.xpath('/config/version')

    if len(toNode) < 1:
        log.warning('Default config file does not contain version entry')
        return False

    if len(fromNode) < 1:
        log.info('Existing config file does not contain version entry')
        return False

    if fromNode[0].text.strip().lower() == toNode[0].text.strip().lower():
        log.debug('From and to doc are on the same version')
        return True

    log.debug('From and to doc are on different versions [existing: %s, new: %s]'
          % (fromNode[0].text, toNode[0].text))
    return False

class RhttpproxyMigrate:
    def __init__(self):
        pass

    def preserveConfig(self, force):
        # prepare list of all config files from which config entries need
        # to be preserved. For now we only need to do this for config.xml
        # [<existing>, <new>, <destination>, [<config entries>]]
        files = [['/etc/vmware/rhttpproxy/config.xml',
                  '/etc/vmware/rhttpproxy/default-config.xml',
                  '/etc/vmware/rhttpproxy/config.xml',
                  ['/config/workingDir',
                   '/config/log/directory',
                   '/config/log/name',
                   '/config/log/outputToConsole',
                   '/config/log/outputToFiles',
                   '/config/log/maxFileSize',
                   '/config/log/maxFileNum',
                   '/config/log/level',
                   '/config/log/outputToSyslog',
                   '/config/log/syslog/ident',
                   '/config/log/syslog/facility',
                   '/config/ssl/privateKey',
                   '/config/ssl/certificate',
                   '/config/vmacore/ssl/doVersionCheck',
                   '/config/vmacore/ssl/fips',
                   '/config/vmacore/ssl/protocols',
                   '/config/vmacore/ssl/libraryPath',
                  ]
                 ],
                ]

        for fromFile, newFile, destFile, carryEntries in files:
            self.preserveSingleConfig(fromFile, newFile, destFile, carryEntries, force)

    def preserveSingleConfig(self, fromFile, newFile, destFile, carryEntries, force):
        log.info('Carrying some config entries from file "%s" to file "%s" [force=%s]' \
               % (fromFile, destFile, force))
        # read the old version from the existing file
        fromDoc = None
        try:
            fromDoc = etree.parse(fromFile)
        except Exception as e:
            log.warning('Failed to parse config file %s: %s' % (fromFile, e))

        # read the new version from the default file.
        toDoc = None
        try:
            toDoc = etree.parse(newFile)
        except Exception as e:
            log.error('Failed to parse config file %s: %s' % (newFile, e))
            return
        if toDoc is None:
            log.error('Failed to parse default config file: %s' % newFile)
            return

        # if the existing config.xml file got messed up, we replace it with the default.
        if fromDoc is None:
            log.warning('Failed to load existing config file: %s' % fromFile)
            log.warning('Replacing %s with default config %s' % (destFile, newFile))
            try:
                toDoc.write(destFile)
            except Exception as e:
                log.error('Failed to write to config file %s: %s' % (destFile, e))
            return

        # if force is not true, we only migrate if the version in the from file and
        # the new file is different.
        if not force and IsSameVersion(fromDoc, toDoc):
            log.debug('Skip migrating since the version of the new file is the same as the version of the existing file')
            return

        # go through each config entry that we want to keep
        for entry in carryEntries:
            fromE = fromDoc.xpath(entry)
            toE = toDoc.xpath(entry)

            # check existing config entry
            fromVal = ""
            if len(fromE) > 0 and fromE[0].text != None:
                  fromVal = fromE[0].text

            if len(fromVal.strip()) == 0:
                # nothing to carry over
                log.debug('Node "%s" from config file "%s" is empty' %\
                         (entry, fromFile))
                continue

            # check default config entry
            if len(toE) < 1:
                # add the config element so that we can put existing values.
                log.info('Creating text node "%s" for "%s"' % (entry, fromVal))
                toE = CreateConfigEntry(toDoc, entry)
                toE.text = fromVal
                continue

            toVal = ""
            if toE[0].text != None:
                toVal = toE[0].text

            # compare existing and new, update if different
            if fromVal.strip().lower() != toVal.strip().lower():
                log.info('Updating "%s" from "%s" to "%s"' %
                         (entry, toE[0].text, fromE[0].text))
                toE[0].text = fromE[0].text

        # write the updated xml doc to the target.
        tmpFile = destFile + ".tmp"
        log.info('Writing updated config to temporary file %s' % tmpFile)
        try:
            toDoc.write(tmpFile)
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
    migrator = RhttpproxyMigrate()
    migrator.preserveConfig(force = False)
except Exception as e:
    log.warning('Caught unexpected exception: %s' % e)
    import traceback
    log.warning(traceback.print_stack())
