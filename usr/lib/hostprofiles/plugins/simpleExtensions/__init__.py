#!/usr/bin/python

"""
Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

import json
import os
import sys

from pluginApi import log
from .SimpleExtensionProfile import LoadDefinitionFile
from .SimpleExtensionUtils import ValidateDefinition, TranscodeType
from .SimpleExtensionUtils import DEFAULT_DEFINITION_FILE
from .SimpleExtensionUtils import SELFINSTALL_KEY, DEFINITION_KEY, \
   SETPROGRAMBINARY_KEY, GETPROGRAMBINARY_KEY, I18NMESSAGES_KEY

def IsFeatureEnabled():
   try:
      with open('/etc/vmware/hp_kill_switch.conf') as f:
         killSwitches = {k.strip(): v.strip()
                         for k, v in [line.split('=') for line in f]}
         return killSwitches['enableExtensionPlugins'] == 'true'
   except:
      pass

   return False


def GetSelfInstallParamMap():
   ''' Get a dictionary of the self-installed parameters
       with no values.
   '''

   from .SimpleExtensionProfile import SelfInstallParamMap
   return SelfInstallParamMap


def InstallNewProfile(selfInstallDict):
   from .SimpleExtensionProfile import SimpleExtensionProfile

   TMP_DEFINITION_FILE = '/tmp/simpleextension_tmp.json'

   # Check the existance of the required elements
   if SELFINSTALL_KEY not in selfInstallDict:
      return False

   if not selfInstallDict[SELFINSTALL_KEY]:
      return False

   if DEFINITION_KEY not in selfInstallDict:
      return False

   # import pdb; pdb.set_trace()

   # Load the json string version of definition; convert it to dict
   definition = selfInstallDict[DEFINITION_KEY]
   definition = json.loads(definition)

   # Write the definition to a temp file
   try:
      with open(TMP_DEFINITION_FILE, 'w') as file:
         json.dump(definition, file, indent = 2)
   except Exception as e:
      log.error('Cannot write file /tmp/simpleextension_tmp.json')
      return False

   # Merge the definition into the center subprofile definition file.
   from vmware import runcommand
   currentDir = os.path.dirname(os.path.realpath(__file__))
   command = ' '.join([currentDir + '/SimpleExtensionUtils.py -M',
                       DEFAULT_DEFINITION_FILE,
                       TMP_DEFINITION_FILE])
   status, output = runcommand.runcommand(command)
   if status:
      log.error('Simple extension definition merge failed: %s.', output)
      return False

   # install set/get program
   className = list(definition.keys())[0]
   definition = definition[className]
   program = SETPROGRAMBINARY_KEY
   if not SimpleExtensionProfile.ReplaceProgram(program,
                                                selfInstallDict[program],
                                                definition):
      return False

   program = GETPROGRAMBINARY_KEY
   if not SimpleExtensionProfile.ReplaceProgram(program,
                                                selfInstallDict[program],
                                                definition):
      return False

   # Add new I18N messages
   return SimpleExtensionProfile.MergeI18NMessage(definition[I18NMESSAGES_KEY],
                                                  className)


def SimpleExtensionsProfileSubclassFactory(name, argnames, BaseClass):
   ''' A helper method to dynamically generate a subprofile
       of SimpleExtensionProfile.
   '''

   try:
      newclass = type(name, (BaseClass,), {'__init__': BaseClass.__init__})
      return newclass
   except:
      log.warning('The subprofile $s is not created', name)
      return None


def GetCurrentModule():
   ''' Get the current module object'''

   return sys.modules[__name__]


def CreateSimpleExtensionProfileSubclass(name, definition, baseClass):
   '''
      Dynamically create the subprofile class from the provided name
      and definition. Register them into this module.
   '''

   # Validate the definition
   if not ValidateDefinition(name, definition):
      log.warning(('Definition of the subprofile "%s" isnot valid' + \
                   'so it is ignored'), name)
      return

   # Create a new sub class of SimpleExtensionProfile using
   # the definition
   newSubclass = SimpleExtensionsProfileSubclassFactory(name,
                    None,
                    BaseClass = baseClass)

   if newSubclass:
      #
      # After new class is created, initialize it using the
      # definition; create parameters and add this class
      # to the current module so that host profile plugin
      # manager will add this profile into pyEngine
      #
      newSubclass.Initialize(definition)
      newSubclass.CreateParameters()
      log.info('Profile "%s" is added in the component SimpleExtensions', name)
      setattr(GetCurrentModule(), name, newSubclass)


#
# Load SimpleEXtensions subprofile definitions from json file;
# Create the subprofiles classes
#
def LoadProfiles():
   from . import SimpleExtensionProfile
   profileModule = SimpleExtensionProfile
   baseClass = getattr(profileModule, 'SimpleExtensionProfile')
   definitionDict = LoadDefinitionFile()
   if definitionDict != None:
      for key in definitionDict:
         CreateSimpleExtensionProfileSubclass(key,
                                              definitionDict[key],
                                              baseClass)

if IsFeatureEnabled():
   LoadProfiles()
