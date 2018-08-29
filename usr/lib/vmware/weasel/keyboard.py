#! /usr/bin/env python

'''
Keyboard module
---------------

The keyboard layouts for ESXi are changed by running `loadkmap` under busybox.
The loadkmap command takes as input through stdin the contents of a keymap
file.  These keymap files are stored in /usr/share/keymaps/

 $ ls /usr/share/keymaps
us.map.gz  fr.map.gz  dvorak.map.gz  list

Above are listed the keymap files such as us.map.gz.  It would be loaded
from the command line like so:

 $ zcat /usr/share/keymaps/us.map.gz | loadkmap

A mapping of human-readable names to keymap file names is stored in a "list"
file in the keymaps directory:

 $ cat /usr/share/keymaps/list
US Default us.map.gz
French fr.map.gz
Dvorak dvorak.map.gz

The filename of the currently loaded keymap must always be stored
in /etc/keymap.

'''
import os
from . import util
from . import script

from weasel import userchoices # always import via weasel.
from weasel.log import log

import vmkctl

TASKNAME = 'KEYBOARD'
TASKDESC = 'Setting the keyboard keymap'

KEYMAP_FILE = "/usr/share/keymaps/list"

# Keymap to use. Its value will be calculated from INSTALLSCRIPT and the values
# in userchoices
_keyMap = None

class Keymaps(object):
    '''A map of keymap filenames to user-readable names.
    '''
    _keymaps = {}

    @classmethod
    def readKeymaps(cls):
        '''the list file should be space-separated pairs of human-readable
        names and keymap gz filenames.  eg:
        US Default us.map.gz
        French fr.map.gz
        Dvorak dvorak.map.gz
        '''

        # We need to rely on vmkctl to give us the valid layouts.
        validLayouts = getVisorKeymaps()

        # Then we need to get the mappings from filenames as well.
        infile = open(KEYMAP_FILE, 'r')

        for line in infile:
            pair = line.rsplit(' ', 1)
            if len(pair) == 2:
                hrName = pair[0].strip()
                fName = pair[1].strip()

                if hrName in validLayouts:
                    cls._keymaps[fName] = hrName
                    cls._keymaps[hrName] = hrName
                else:
                    log.debug("Ignoring line '%s' from /usr/share/keymaps/list,"
                              " layout not recognized." % line)
            else:
                log.warn('Malformed line (%s) in %s' % (line, KEYMAP_FILE))

        infile.close()

    @classmethod
    def keys(cls):
        if not cls._keymaps:
            cls.readKeymaps()
        return list(cls._keymaps.keys())

    @classmethod
    def contains(cls, key):
        if not cls._keymaps:
            cls.readKeymaps()
        return cls._keymaps.__contains__(key)

    @classmethod
    def get(cls, key):
        if not cls._keymaps:
            cls.readKeymaps()
        return cls._keymaps.get(key)


def getCurrentLayout():
    '''Get the current layout as determined by vmkctl.
    '''
    try:
        return vmkctl.SystemInfoImpl().GetKeyboardLayout()
    except vmkctl.HostCtlException:
        log.error("Unable to get the current layout.")
        return None


def getVisorKeymaps():
    return vmkctl.SystemInfoImpl().GetKeyboardLayouts()


def getKeymapFromUserchoice():
    keybdChoice = userchoices.getKeyboard()
    if 'name' not in keybdChoice:
        return None

    keybdName = keybdChoice['name']

    validMaps = getVisorKeymaps()
    if keybdName not in validMaps:
        raise Exception('Keymap (%s) not found' % keybdName)

    return keybdName


def hostAction():
    keymapName = getKeymapFromUserchoice()
    if keymapName == None:
        log.info('User has not chosen a keymap. Doing nothing.')
        return

    vmkctl.SystemInfoImpl().LoadKeyboardMappings(keymapName)


def installAction():
    global _keyMap
    keymapName = getKeymapFromUserchoice()
    if keymapName == None:
        log.info('User has not chosen a keymap. Doing nothing.')
        return

    # hostd might not be completely ready by the time esxcli command is run.
    # Hence using localcli.
    cmd = "/sbin/localcli system settings keyboard layout set --layout \"%s\""

    log.info('Creating the install script for keymap (%s)' % keymapName)

    _keyMap = keymapName


def getFirstBootVals():
   keyVals = {}
   if _keyMap:
      keyVals["keyboard"] = _keyMap
   return keyVals


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    userchoices.setInstall(False)
    userchoices.setKeyboard('Dvorak')
