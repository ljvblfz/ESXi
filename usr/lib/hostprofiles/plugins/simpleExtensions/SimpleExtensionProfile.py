#!/usr/bin/python
"""
Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

import base64
import json
import os

from pluginApi import ParameterMetadata, log, CreateLocalizedMessage
from pluginApi import AppendMessages
from pluginApi import TASK_LIST_REQ_MAINT_MODE, TASK_LIST_REQ_REBOOT
from pluginApi.extensions import SimpleConfigProfile, RangeValidator
from .SimpleExtensionUtils import TranscodeType
from .SimpleExtensionUtils import DEFAULT_DEFINITION_FILE
from .SimpleExtensionUtils import GETPROGRAM_KEY, SETPROGRAM_KEY, \
   GETPROGRAMBINARY_KEY, SETPROGRAMBINARY_KEY, DEFINITION_KEY, DEPENDENTS_KEY, \
   DEPENDENCIES_KEY, REQUIREMENT_KEY, SELFINSTALL_KEY, I18NMESSAGES_KEY

# The category and component name for the subprofiles
CATEGORY_EXTENSION = 'Extensions'
COMPONENT_SIMPLE_EXTENSION = 'SimpleExtensions'

# The localization message key base
SIMPLE_EXTENSION_BASE =\
   'com.vmware.vim.profile.Extensions.SimpleExtensions.'


def LoadDefinitionFile():
   ''' Load the subprofile definition file from
       the file SimpleExtensionsDefinition.json at the
       current directory
   '''

   from .SimpleExtensionUtils import LoadJsonFile

   definitionJson = LoadJsonFile(DEFAULT_DEFINITION_FILE)
   if definitionJson is None:
      log.error("Cannot load definition file: %s", DEFAULT_DEFINITION_FILE)

   return definitionJson


def GetModule(name):
   '''Parse the module name from the type name; then
      retrieve the module and return it.
   '''

   import sys
   if not '.' in name:
      name = sys.modules[__name__].__name__

   moduleName = name[0 : name.rfind('.')]
   try:
      return sys.modules[moduleName]
   except:
      return None


def ProcessError(key, name=None):
   '''Log the error message. '''

   if name:
      key = name + '.' + key
   key = SIMPLE_EXTENSION_BASE + key
   errorMsg = CreateLocalizedMessage(None, key, None, profile=name)
   log.error(str(errorMsg))
   return errorMsg


def needQuotes(typeName):
   '''For string type parameters when add their values
      into the set program command string, add quotes around them so
      they will be safely pass into the set program
   '''

   return ('[]' in typeName) or ('string' == typeName)


class SimpleExtensionProfile(SimpleConfigProfile):
   '''The base class for the subprofiles in the component
      'simpleExtensions of the category 'extensions'.
      It is a sub class of SimpleConfigProfile so it implements
      ExtractConfig and SetConfig.
   '''

   TYPE_KEY = 'type'
   DEFAULT_KEY = 'default'
   MIN_KEY = 'min'
   MAX_KEY = 'max'

   selfInstall = False

   @classmethod
   def Initialize(cls, definition):
      '''Initialize the class variable:
            definition (dictionary)
            parameter list as empty
            category and component
            dependents if any
            dependencies if any
            requirement if any
      '''

      cls.definition = definition
      cls.parameters = []
      cls.category = CATEGORY_EXTENSION
      cls.component = COMPONENT_SIMPLE_EXTENSION

      if DEPENDENTS_KEY in definition:
         cls.dependents = definition[DEPENDENTS_KEY]

      if DEPENDENCIES_KEY in definition:
         cls.dependencies = definition[DEPENDENCIES_KEY]

      if REQUIREMENT_KEY in definition:
         requirement = definition[REQUIREMENT_KEY]
         if requirement == 'maintenance_mode':
            cls.setConfigReq = TASK_LIST_REQ_MAINT_MODE
         elif requirement == 'reboot':
            cls.setConfigReq = TASK_LIST_REQ_REBOOT
         else:
            log.error('Invalid requirement "%s" for profile "%s"',
                      requirement, cls.__name__)

      if SELFINSTALL_KEY in definition:
         cls.selfInstall = definition[SELFINSTALL_KEY]


   @classmethod
   def ConvertToTypes(cls, typeNames, name):
      '''Find the types with the type names in the typeNames
         and return the types.
      '''

      types = []
      for item in typeNames:
         if not isinstance(item, str):
            continue
         module = GetModule(item)
         item = item.split('.')[-1]
         if module is None or not hasattr(module, item):
            log.warning('The class of %s, a "%s" of "%s" cannot be found.',
                        item, name, cls.__name__)
            continue

         types.append(getattr(module, item))
      return types


   @classmethod
   def ProcessDependents(cls):
      ''' After all the profiles registered into pyEngine,
          use this method to convert the dependents from class names
          to types.
      '''

      if hasattr(cls, DEPENDENTS_KEY):
         cls.dependents = \
            cls.ConvertToTypes(cls.dependents, DEPENDENTS_KEY)


   @classmethod
   def ProcessDependencies(cls):
      ''' After all the profiles registered into pyEngine,
          use this method to convert the dependencies from class names
          to types.
      '''

      if hasattr(cls, DEPENDENCIES_KEY):
         cls.dependencies = \
            cls.ConvertToTypes(cls.dependencies, DEPENDENCIES_KEY)


   @classmethod
   def _AddParameter(cls, paramName):
      ''' Add a parameter definition to the parameter list of the
          sub profile class.
      '''
      cls.parameters.append(ParameterMetadata(paramName, 'string', False))


   @classmethod
   def CreateParameters(cls):
      '''Creates the parameters defined in 'definition' dictionary.
         If 'min' and 'max' are defined (for integer type parameter),
         set a RangeValidator as paramChecker.
      '''

      for key in cls.definition:
         param = cls.definition[key]
         if isinstance(param, dict):
            # ignore the localization message dictionary
            if key == I18NMESSAGES_KEY:
               continue

            paramType = param[cls.TYPE_KEY]
            defaultValue = None
            if cls.DEFAULT_KEY in param:
               defaultValue = param[cls.DEFAULT_KEY]
            minVal = None
            maxVal = None
            if cls.MIN_KEY in param:
               minVal = param[cls.MIN_KEY]
            if cls.MAX_KEY in param:
               maxVal = param[cls.MAX_KEY]
            paramChecker = None
            if minVal != None and maxVal != None:
               paramChecker = RangeValidator(minVal, maxVal)
            cls.parameters.append(ParameterMetadata(key,
                                                    paramType,
                                                    False,
                                                    defaultValue=defaultValue,
                                                    paramChecker=paramChecker))

      if cls.selfInstall:
         # import pdb; pdb.set_trace()
         cls.parameters.append(ParameterMetadata(SELFINSTALL_KEY,
                                                 'bool', False))
         cls._AddParameter(GETPROGRAMBINARY_KEY)
         cls._AddParameter(SETPROGRAMBINARY_KEY)
         cls._AddParameter(DEFINITION_KEY)

      cls.alwaysRemediate = not len(cls.parameters)


   @classmethod
   def __checkFile(cls, fileName, errorKey):
      '''Check file existence.'''

      if not os.path.isfile(fileName):
         error = ProcessError(errorKey, cls.__name__)
         # XXX propogate error
         return False
      return True


   @classmethod
   def ReplaceProgram(cls, name, contents, definition):
      '''Replace the set/get program 'name' using the provided 'contents'.
      '''

      programMap = {SETPROGRAMBINARY_KEY : SETPROGRAM_KEY,
                    GETPROGRAMBINARY_KEY : GETPROGRAM_KEY}

      if not contents or not isinstance(contents, str) or \
         name not in programMap:
         return

      try:
         binaryVersion = base64.b64decode(contents)
      except TypeError:
         log.error('The %s program binary is not valid', name)
         return

      fileName = definition[programMap[name]]

      if fileName != None:
         dirName = os.path.dirname(fileName)
         if not os.path.exists(dirName):
            try:
               os.makedirs(dirName, 0o755)
            except IOError:
               pass
         if os.path.exists(dirName):
            try:
               with open(fileName, 'wb') as fileObj:
                  fileObj.write(binaryVersion)
                  return True
            except IOError as e:
               log.error('Error to create/write file: %s', fileName)
         else:
            log.error('Dir %s does not exist', dirName)

      return False


   @classmethod
   def MergeI18NMessage(cls, messages, name):
      ''' Merge the new localization message into profile.vmsg.'''

      # The variable 'messages' is a dictionary contains the I18N messages for
      # multiple language.  The outer loop goes through the languages as the
      # inner loop to retrieve the I18N message: if it is already loaded, it
      # is ignored for merging.
      for loc in messages:
         locMsgs = messages[loc]
         for s in locMsgs:
            try:
               key, value = s.split('=')
               if CreateLocalizedMessage(None, key.strip(), None, \
                                         profile=cls.__name__):
                  locMsgs.remove(s)
            except:
               log.warning('Invalid I18N message %s', s)
               pass

      # merge new messages into i18nmgr and profile.vmsg
      return AppendMessages(name, messages)


   @classmethod
   def SetConfig(cls, config, hostServices):
      '''The implementation of the interface method inherited from the
         parent SimpleConfigProfile.  This method is inherited by all
         the concrete subprofile classes automatically generated from
         the json definition file.
      '''

      log.info("SetConfig for %s", cls.__name__)
      setProgram = cls.definition[SETPROGRAM_KEY]
      if not cls.__checkFile(setProgram, 'MissingSetProgram'):
         return

      #
      # Create an argument string from parameter name and values.
      # For string type or array type, the values are embraced with
      # quotes, and an escape is added before the quote for strings
      # in a string array is .  For example:
      #   stringParam="YetAnotherString With Space 24"
      #   stringArrayParam='["String 1", "S2"]'
      #
      arguments = " "
      if len(config):
         params = config[0]
         for param in cls.parameters:
            if param.paramName in params:
               name = param.paramName

               # We don't expect the definition and selfInstall
               # change for the same subprofile.
               if name == DEFINITION_KEY or \
                  name == SELFINSTALL_KEY:
                  continue

               # For program binary we reinstall it when they are different
               if name == GETPROGRAMBINARY_KEY or \
                  name == SETPROGRAMBINARY_KEY:
                  cls.ReplaceProgram(name, params[name], cls.definition)
                  continue

               paramType = param.paramType
               paramValue = params[name]
               if 'bool' == paramType:
                  paramValue = str(paramValue).lower()

               log.info("paramValue: %s", str(paramValue))
               if 'string[]' == paramType:
                  paramValue = ','.join(paramValue)
                  paramValue = paramValue.replace('\'', '\"')

               if needQuotes(paramType):
                  paramValue = '\'' + paramValue + '\''

               arguments = arguments + ' ' + name + '=' + str(paramValue)

      setProgram = cls.definition[SETPROGRAM_KEY] + arguments

      # import pdb; pdb.set_trace()

      log.debug('SetProgram: %s', str(setProgram))

      from vmware import runcommand
      status, output = runcommand.runcommand(setProgram)
      try:
         faultMessages = json.loads(output, object_hook=TranscodeType)
         # Process faultMessages
         for fault in faultMessages:
            ProcessError(fault, cls.__name__)
      except:
         pass


   @classmethod
   def _AddDefinition(cls, params):
      '''Add the profile definition into parameter map.'''

      name = cls.__name__.split('_')
      completeDef = {name[1]:cls.definition}
      params[DEFINITION_KEY] = json.dumps(completeDef, indent=2)


   @classmethod
   def _AddProgramBinary(cls, params, name):
      '''Add the program executable into the parameter map.'''

      nameForBinary = name + 'Binary'
      params[nameForBinary] = ''
      if name in cls.definition:
         fileName = cls.definition[name]
         import os.path
         if os.path.isfile(fileName):
            try:
               with open(fileName, 'rb') as fileObj:
                  binaryVersion = fileObj.read()
                  params[nameForBinary] = base64.b64encode(binaryVersion)
            except IOError as e:
               log.error('Error when read %s', fileName)
         else:
            log.error('File %s does not exist.', fileName)


   @classmethod
   def ExtractConfig(cls, hostServices):
      ''' This is the implementation of the interface method from
          SimpleConfigProfiel and is shared by all the concrete
          subprofile classes.

          When the get program is not availble or the output
          of the get program is not in json format, return
          a empty config map; otherwise, parse the json data
          from the output of get program and return it.
      '''

      emptyConfigMap = [{}]

      # import pdb; pdb.set_trace()

      getProgram = cls.definition[GETPROGRAM_KEY]
      if not cls.__checkFile(getProgram, 'MissingGetProgram'):
         return emptyConfigMap

      from vmware import runcommand
      status, output = runcommand.runcommand(getProgram)
      try:
         params = json.loads(output, object_hook=TranscodeType)
         if cls.selfInstall:
            params[SELFINSTALL_KEY] = cls.selfInstall
            cls._AddProgramBinary(params, SETPROGRAM_KEY)
            cls._AddProgramBinary(params, GETPROGRAM_KEY)
            cls._AddDefinition(params)

         return [params]
      except:
         ProcessError('GetProgramError', cls.__name__)
         return emptyConfigMap

# The objects required when the subprofile is self installable.
SelfInstallParamMap = {DEFINITION_KEY : None, \
                       GETPROGRAMBINARY_KEY : None, \
                       SETPROGRAMBINARY_KEY : None, \
                       SELFINSTALL_KEY : None}
