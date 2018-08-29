#!/usr/bin/python

"""
Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

import argparse
import json
import os
import sys

from collections import OrderedDict

try:
   from pluginApi import log
except:
   log = None

# The current path
SCRIPTPATH = os.path.dirname(os.path.realpath(__file__))

# The absolute path of the subprofile deifinition file
DEFAULT_DEFINITION_FILE = \
   os.path.join(SCRIPTPATH, 'SimpleExtensionsDefinition.json')

# The element names in the definition
GETPROGRAM_KEY = 'getProgram'
SETPROGRAM_KEY = 'setProgram'
GETPROGRAMBINARY_KEY = 'getProgramBinary'
SETPROGRAMBINARY_KEY = 'setProgramBinary'
DEFINITION_KEY = 'definition'
DEPENDENTS_KEY = 'dependents'
DEPENDENCIES_KEY = 'dependencies'
REQUIREMENT_KEY = 'requirement'
SELFINSTALL_KEY = 'selfInstall'
I18NMESSAGES_KEY = 'i18nMessages'


def PythonVersion3():
   ''' Test the current python is version 3 and above or not
   '''

   version = sys.version_info
   return version[0] >= 3


def PrintString(s, indent=0, level='debug'):
   ''' Helper function to print out the information/warning/error
       messages to either log or stdout.
   '''

   # Add indent to output
   if log:
      # map the message type to log level and log it.
      levelMap = {'debug':log.debug, 'warning':log.warning, 'error':log.error}

      s = ('\t'*indent) + s
      levelMap[level](s)
   else:
      # Print the message using print command or print function
      # based on the python version
      #
      # For stdout as output, add message type.
      headMap = {'debug': '', 'warning':'WARNING', 'error':'ERROR'}
      head = headMap[level]
      if head:
         s = headMap[level] + ': ' + s
      s = ('\t'*indent) + s
      print(s)

def PrintError(s, indent=0):
   ''' Print an error message.
   '''

   PrintString(s, indent, 'error')


def PrintWarning(s, indent):
   ''' Print a warning message.
   '''

   PrintString(s, indent, 'warning')


def TypeString(a):
   ''' Return the type name of the input object.
   '''

   return type(a).__name__


def ToPythonType(t):
   ''' Convert the parameter type name to python type:
       string -> str
       int[] or string[] -> list
       others, keep unchanged
   '''

   if t == 'string':
      return 'str'

   if '[]' in t:
      return 'list'

   return t


class JsonProfile:
   ''' A helper class to validate the profile definition.
   '''

   # The key names for define a parameter
   KEYS = ['type', 'default', 'min', 'max']

   # The none parameter objects in the profile definition, and its type
   NON_PARAM_ATTR = {
                     SETPROGRAM_KEY : 'str',
                     GETPROGRAM_KEY : 'str',
                     DEPENDENTS_KEY   : 'list',
                     DEPENDENCIES_KEY : 'list',
                     REQUIREMENT_KEY  : 'str',
                     SELFINSTALL_KEY : 'bool',
                     I18NMESSAGES_KEY : 'OrderedDict'
                    }


   def HasSetProgram(self):
      ''' Check set program exists or not.'''

      return SETPROGRAM_KEY in self.theDict


   def HasGetProgram(self):
      ''' Check get program exists ot not.'''

      return GETPROGRAM_KEY in self.theDict


   def __init__(self, name, theDict):
      ''' Set name and dict, generate parameter count'''

      self.name = name
      self.theDict = theDict
      self.parameterNum = len(theDict)
      for key in theDict.keys():
         if key in self.NON_PARAM_ATTR:
            self.parameterNum -= 1


   def CheckParameter(self, paramName, param, Errors, Warnings):
      ''' CheckParameter:
             param has to have its map
             param should not be empty
             param has to have a type
             param members have to match the type
      '''

      if not isinstance(param, dict):
         Errors.append('Wrong parameter definition for %s' % paramName)
         return

      if not param:
         Warnings.append('Empty parameter %s' % paramName)
         return

      KEYS = self.__class__.KEYS
      if KEYS[0] not in param:
         Errors.append('Type for parameter %s is not defined' % paramName)

      for key in param.keys():
         if key not in KEYS:
            Warnings.append('Invalid attribute %s will be ignored in %s' %\
                            (key, paramName))

      for i in range(1, 4):
         if KEYS[i] in param:
            paramType = ToPythonType(param[KEYS[0]])

            if TypeString(param[KEYS[i]]) != paramType:
               Errors.append('"%s" has a wrong type in %s' %
                             (KEYS[i], paramName))
            elif paramType == 'list':
               elementType = ToPythonType(param[KEYS[0]].split('[')[0].strip())
               values = param[KEYS[i]]
               for element in values:
                  if TypeString(element) != elementType:
                     Errors.append('"%s" has a wrong type in %s:%s' %
                                   (element, paramName, KEYS[i]))


   def CheckElements(self):
      ''' Check profile elements:
             Either have both set/get programs or not
             parameter number is 0 is only valid when have set/get programs
             non parameter members have proper type
             parameter definition should be valid
      '''

      Errors = []
      Warnings = []

      if self.HasSetProgram() != self.HasGetProgram():
         Errors.append('SetProgram/getProgram Should be both defined or not.')

      if not self.HasSetProgram() and not self.HasGetProgram() \
         and self.parameterNum == 0:
         Warnings.append(('Potential empty profile "%s" unless a ' + \
            'set/get program will be installed at the default location' \
            )% self.name)

      for key in self.theDict.keys():
         if key in self.__class__.NON_PARAM_ATTR:
            if TypeString(self.theDict[key]) != \
               self.__class__.NON_PARAM_ATTR[key]:
               Errors.append('The type of "%s" is wrong: %s' % \
                             (key, TypeString(self.theDict[key])))
         else:
            self.CheckParameter(key, self.theDict[key], Errors, Warnings)

      if not Errors:
         if not Warnings:
            PrintString('The definition of %s is valid' % self.name, 1)
            return True
         PrintString('Warnings in the validation of %s' % self.name, 1)

         for warning in Warnings:
            PrintWarning(warning, 2)
         return False
      else:
         PrintString('Errors in the validation of %s' % self.name, 1)
         for error in Errors:
            PrintError(error, 2)
         return False


def TranscodeType(data):
   '''Recursively transcode from unicode to string.'''

   # Make python 3 compatible.
   try:
      isUnicode = isinstance(data, unicode)
   except NameError:
      isUnicode = isinstance(data, str)

   if isUnicode:
      return data.encode('utf-8')

   if isinstance(data, list):
      return [TranscodeType(x) for x in data]

   if isinstance(data, dict):
      od = OrderedDict()

      for key in data.keys():
         od[TranscodeType(key)] = TranscodeType(data[key])
      return od
   return data


def LoadJsonFile(fileName):
   ''' Load json file.'''

   definitionJson = None
   try:
      with open(fileName) as definitionFile:
         definitionJson = json.load(definitionFile,
                                    object_pairs_hook=OrderedDict)
   except Exception as exc:
      PrintError(str(exc))

   return TranscodeType(definitionJson)


def WriteJsonFile(fileName, definitions):
   ''' Write definition into json file.'''

   with open(fileName, 'w') as definitionFile:
      try:
         json.dump(definitions, definitionFile, indent=2)
      except Exception as exc:
         PrintError(str(exc))


def ValidateDefinition(name, definition):
   ''' Validation the definition of a profile.'''

   return JsonProfile(name, definition).CheckElements()


def ValidateDefinitions(fileName):
   ''' Validate the profile definition in the file 'file'. '''

   try:
      definitionJson = LoadJsonFile(fileName)
   except IOError as esc:
      PrintError('IO issue: %s' % str(esc))
      return None

   PrintString('Found definition for the following profiles:')

   for key in definitionJson.keys():
      PrintString(key, 1)

   for key in definitionJson.keys():
      PrintString('Checking definition for the profile %s' % key)
      ValidateDefinition(key, definitionJson[key])
   return definitionJson


class ValidationAction(argparse.Action):
   '''The validation action for arg parser.'''

   def __call__(self, parser, namespace, values, option_string=None):
      ValidateDefinitions(namespace.validate)


class MergeAction(argparse.Action):
   ''' The merge action for arg parser:
          Merges the definitions from two files into the fist one.
          This is useful at extension profile installation.
   '''


   def __call__(self, parser, namespace, values, option_string=None):
      file1 = values[0]
      file2 = values[1]
      definitions1 = ValidateDefinitions(file1)
      definitions2 = ValidateDefinitions(file2)
      if definitions1 and definitions2:
         definitions1 = OrderedDict(list(definitions1.items()) +
                                    list(definitions2.items()))
         WriteJsonFile(file1, definitions1)
         sys.exit(0)
      else:
         sys.exit(1)


if __name__ == "__main__":
   argparser = \
      argparse.ArgumentParser(description='Simple Extension Profile utilities.')
   argparser.add_argument('-validate', '-V', default=DEFAULT_DEFINITION_FILE,
                          nargs='?', action=ValidationAction,
                          help='Validate sub profile definition file.')
   argparser.add_argument('-merge', '-M',
                          nargs=2, action=MergeAction,
                          help='Merge two sub profile definition files.')

   args = argparser.parse_args()
