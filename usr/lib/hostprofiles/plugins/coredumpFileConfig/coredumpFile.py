#!/usr/bin/python
# **********************************************************
# Copyright 2014-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import os
import sys
import pipes
import vmkctl

from pluginApi import ParameterMetadata, log
from pluginApi import CreateLocalizedException
from pluginApi.extensions import SimpleConfigProfile
from pyEngine.nodeputil import RangeValidator
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_COREDUMP_CONFIG
from hpCommon.constants import RELEASE_VERSION_2017


ESXCLI_NAMESPACE = 'system'
ESXCLI_APP = 'coredump file'

# Define constants for the parameters add command
CF_ADD_CMD = 'add'
CF_ADD_PATH_OPT = '-p %s'
CF_ADD_DATASTORE_OPT = '-d %s'
CF_ADD_SIZE_OPT = '-s %s'

# Define constants for the parameters get command
CF_GET_CMD = 'get'
CF_ACTIVE_FIELD = 'Active'
CF_CONFIGURED_FIELD = 'Configured'

# Define constants for the parameters set command
CF_SET_CMD = 'set'
CF_ENABLE_OPT = '-e true'
CF_DISABLE_OPT = '-e false'

# Define constants for the parameters list command
CF_LIST_CMD = 'list'
CF_LIST_PATH_FIELD = 'Path'
CF_LIST_SIZE_FIELD = 'Size'

# Define constants for the parameters remove command
CF_REMOVE_CMD = 'remove'
CF_REMOVE_FILE_OPT = '-f %s'

# Define error message keys
CF_MSG_KEY_BASE = 'com.vmware.profile.coredumpFile'
CLI_ERROR_KEY = '%s.%s' % (CF_MSG_KEY_BASE, 'cliError')

# Message keys for module parameter validation
CF_ADD_ENABLE_FAILED = '%s.%s' % (CF_MSG_KEY_BASE, 'addEnableFailed')
CF_REMOVE_FAILED = '%s.%s' % (CF_MSG_KEY_BASE, 'removeFailed')
CF_ACTIVATE_FAILED = '%s.%s' % (CF_MSG_KEY_BASE, 'activateFailed')
CF_DEACTIVATE_FAILED = '%s.%s' % (CF_MSG_KEY_BASE, 'deactivateFailed')

# Coredump file constants
CF_PATH_PREFIX = '/vmfs/volumes/'
CF_SUFFIX = '.dumpfile'
CF_DIAG_FILE_EXISTS_MSG = "Diagnostic File already exists"
CF_MIN_SIZE = 100


#
# Helper functions
#
def isString(arg):
   """Check if the argument is a string
   """
   if sys.version_info.major >= 3:
      return isinstance(arg, str)
   else:
      return isinstance(arg, basestring)

def ExecuteEsxcliCF(hostServices, command, *opts):
   """Helper function for executing esxcli coredump file command.
   """
   log.debug('Coredump File provider invoking esxcli command %s %s' % \
             (command, str(opts)))
   return hostServices.ExecuteEsxcli(
                           ESXCLI_NAMESPACE, ESXCLI_APP, command, *opts)


def RaiseExcEsxcliCF(output, command, opts):
   """Helper function to raise localized exceptions on esxcli command
   execution failures.
   """
   if not isString(output):
      log.warning('ESXCLI error output not a string for coredump '
                  'file command %s with options %s' % (command, str(opts)))
   errMsgData = { 'error': output }
   errMsg = 'Coredump File Provider: Error issuing esxcli ' + \
            'command %s with options %s: %s' % \
            (command, str(opts), str(output))
   log.error(errMsg)
   raise CreateLocalizedException(None, CLI_ERROR_KEY, errMsgData)


def InvokeEsxcliCF(hostServices, command, *opts):
   """Helper function for invoking esxcli and processing errors.
   """
   status, output = ExecuteEsxcliCF(hostServices, command, *opts)
   if status != 0:
      RaiseExcEsxcliCF(output, command, opts)
   return output


def InvokeLocalcli(hostServices, *args):
   """Helper function for invoking localcli and processing errors.
   """
   if args is None:
      return None
   log.debug('Coredump File provider invoking localcli command %s' % (str(args)))
   status, output = hostServices.ExecuteLocalEsxcli(*args)
   if status != 0:
      if not isString(output):
         log.warning('LOCALCLI error output not a string for arguments '
                     '%s' % (str(args)))
      errMsgData = { 'error': output }
      errMsg = 'Coredump File Provider: Error issuing localcli ' + \
               'with arguments %s: %s' % (str(args), str(output))
      log.error(errMsg)
      raise CreateLocalizedException(None, CLI_ERROR_KEY, errMsgData)
   return output


def GetSizeInMB(sizeInBytes):
   """Convert bytes to MB.
   """
   return int(sizeInBytes / (1024 * 1024))


def GetDatastoreFromPath(hostServices, filePath):
   """Extract and return the datastore name from given file path.

   filePath is of the format:
   /vmfs/volumes/<datastoreName>/...
   """
   datastorePath = os.sep.join(filePath.split(os.sep)[:4])
   ss = hostServices.hostSystemService.configManager.storageSystem
   for d in ss.fileSystemVolumeInfo.mountInfo:
      if CompareFilePaths(d.mountInfo.path, datastorePath):
         log.info("Datastore found=%s" % (d.volume.name))
         return d.volume.name
   log.error('Datastore not found with path %s' % datastorePath)
   return None


def CompareFilePaths(filePath1, filePath2):
   """Compare two paths by resolving symlinks if necessary. Returns True
   if paths are the same.
   """
   if filePath1 == filePath2:
      return True
   return os.path.realpath(filePath1) == os.path.realpath(filePath2)


class CoredumpFileSizeValidator(RangeValidator):
   """Class to validate the minimum size of a coredump file.
   """
   def Validate(self, obj, argName, arg, errors):
      if not arg:
         return True
      else:
         return RangeValidator.Validate(self, obj, argName, arg, errors)


#
# The main profile class
#
class CoredumpFileProfile(SimpleConfigProfile):
   """A Host Profile that manages the coredump file configuration on ESX hosts.

   The plugin provides three configuration parameters:
   a. Enabled - boolean flag to enable or disable the coredump file for the
   attached host/cluster.
   b. Datastore - name of datastore where coredump file should be stored.
   c. Size - size in MB of the coredump file. Should be a minimum of 100 MB.

   Both Datastore and Size can be left unspecified to represent default values.
   For default values, the host automatically decides on a suitable datastore
   and creates file of recommended size for a given host.

   Configuration extraction always reports datastore as default and the size
   is returned only when it differs from the recommended value, so that a host
   profile can be conveniently extracted and subsequently applied without the
   need to be edited in between.

   Compliance check performs comparison between the paramater values provided by
   the Host Profile against those extracted from the host. Given default
   datastore, any current datastore is compliant. Given default size, the
   current size of file should be greater than or equal to the recommended size
   of the dump file for the host.
   """
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2017
   enableDeprecatedVerify = True
   enableDeprecatedApply = True
   supersededBy = 'coredumpFileConfig.coredumpFileProfile.CoredumpFile'

   #
   # Define required class attributes
   #
   parameters = [ ParameterMetadata('Enabled', 'bool', False),
                  ParameterMetadata('Datastore', 'string', True),
                  ParameterMetadata('Size', 'int', True,
                           paramChecker=CoredumpFileSizeValidator(CF_MIN_SIZE))]

   singleton = True

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_COREDUMP_CONFIG

   # cached results of command invocations
   getCmdRes = None
   listCmdRes = None
   coredumpDefaultSize = None

   @classmethod
   def _GetFilePath(cls, hostServices, fileType, cached=True):
      """Return the path of the active or configured coredump file.
      """
      if (not cached) or (cls.getCmdRes is None):
         cls.getCmdRes = InvokeEsxcliCF(hostServices, CF_GET_CMD)
      return cls.getCmdRes[fileType]

   @classmethod
   def _IsFileSet(cls, hostServices, fileType, cached=True):
      """Check if there is an active or configured coredump file.
      """
      filePath = cls._GetFilePath(hostServices, fileType, cached)
      return len(filePath) > 0

   @classmethod
   def _IsFilePresent(cls, hostServices, filePath, fileType=None, cached=True):
      """Check if given file is listed. If fileType is specified, it is verified
      against the listed entry.
      """
      if (not cached) or (cls.listCmdRes is None):
         cls.listCmdRes = InvokeEsxcliCF(hostServices, CF_LIST_CMD)
      if not cls.listCmdRes:
         return False

      for fileEntry in cls.listCmdRes:
         if CompareFilePaths(filePath, fileEntry[CF_LIST_PATH_FIELD]):
            # Check fileType if requested
            if fileType and fileEntry[fileType] == False:
               return False
            return True

      return False

   @classmethod
   def _IsFileValid(cls, hostServices, fileType, cached=True):
      """Check if the active or configured file is valid. A valid file
      is 'list'ed as a coredump file.

      We check both get and list commands since they can get out of sync.
      But the list command is authoritative.
      """
      filePath = cls._GetFilePath(hostServices, fileType, cached)
      if not filePath:
         return False

      return cls._IsFilePresent(hostServices, filePath, fileType, cached)

   @classmethod
   def _AddEnableFile(cls, hostServices, datastore, size):
      """Create a coredump file on the host on the given datastore and of
      the given size and activate it.

      If we find that a suitable dump file already exists, it is activated.
      If not, a new dump file is created to replace the old one.
      """
      # Add datastore (quote string to handle possible spaces in it)
      dsOpt = CF_ADD_DATASTORE_OPT % (pipes.quote(datastore)) if datastore else ''
      # Add size
      szOpt = CF_ADD_SIZE_OPT % (size) if size else ''
      # Invoke command
      opts = [dsOpt, szOpt, CF_ENABLE_OPT]
      status, output = ExecuteEsxcliCF(hostServices, CF_ADD_CMD, *opts)

      if status != 0 and (CF_DIAG_FILE_EXISTS_MSG in output):
         # Extract the file path out of the error message
         startIdx, endIdx = output.find(CF_PATH_PREFIX), output.find(CF_SUFFIX)
         assert (startIdx != -1 and endIdx != -1), \
                'Failed to extract filePath from error message'
         filePath = output[startIdx:endIdx] + CF_SUFFIX
          # Quote the filepath to handle possible spaces in it
         quotedFilePath = pipes.quote(filePath)

         _, curSize = cls._GetFileEntry(hostServices, filePath)
         # If file is of required size, enable it (using filepath)
         if (size and curSize == size) or \
            (not size and curSize >= cls._GetCoredumpFileDefaultSize(hostServices)):
            cls._ActivateFile(hostServices, quotedFilePath)
            status = 0
         else:
         # If not of required size, remove current file (using filepath)
         # and then create new file
            # Deactivate file before removing. Do not use --force option for
            # remove as we don't want to remove a file from which the dump has
            # not been extracted yet.
            if CompareFilePaths(filePath,
                                cls._GetFilePath(hostServices, CF_ACTIVE_FIELD)):
               cls._DeactivateFile(hostServices)
            cls._RemoveFile(hostServices, quotedFilePath)
            status, output = ExecuteEsxcliCF(hostServices, CF_ADD_CMD, *opts)

      if status != 0:
         RaiseExcEsxcliCF(output, CF_ADD_CMD, opts)

      # Verify that operation succeeded
      if not cls._IsFileValid(hostServices, CF_ACTIVE_FIELD, cached=False):
         errMsgData = { 'DatastoreName' : datastore }
         raise CreateLocalizedException(None, CF_ADD_ENABLE_FAILED, errMsgData)

   @classmethod
   def _RemoveFile(cls, hostServices, filePath=None):
      """Remove the configured coredump file from the host. If filePath is
      not provided, it is assumed that the file is active and/or configured.
      """
      filePathOpt = ''
      if filePath:
         filePathOpt = CF_REMOVE_FILE_OPT % filePath
      else:
         # Get configured file path (which is same as the active file path)
         filePath = cls._GetFilePath(hostServices, CF_CONFIGURED_FIELD)
         assert filePath, 'Configured file not found'

      InvokeEsxcliCF(hostServices, CF_REMOVE_CMD, filePathOpt)

      # Verify if the operation succeeded
      if cls._IsFilePresent(hostServices, filePath, cached=False):
         errMsgData = { 'CoredumpFilePath' : filePath }
         raise CreateLocalizedException(None, CF_REMOVE_FAILED, errMsgData)

   @classmethod
   def _ActivateFile(cls, hostServices, filePath=None):
      """Enable the current configured coredump file. If filePath is
      not provided, it is assumed that the file is configured.
      """
      if filePath:
         InvokeEsxcliCF(hostServices, CF_SET_CMD, CF_ADD_PATH_OPT % filePath)
      else:
         filePath = cls._GetFilePath(hostServices, CF_CONFIGURED_FIELD)
         assert filePath, 'Configured file not found'
         InvokeEsxcliCF(hostServices, CF_SET_CMD, CF_ENABLE_OPT)

      # Verify if file is activated
      if not cls._IsFileValid(hostServices, CF_ACTIVE_FIELD, cached=False):
         errMsgData = { 'CoredumpFilePath' : filePath }
         raise CreateLocalizedException(None, CF_ACTIVATE_FAILED, errMsgData)

   @classmethod
   def _DeactivateFile(cls, hostServices):
      """Disable the current active coredump file.

      Note that the file still exists, but is listed as inactive.
      """
      InvokeEsxcliCF(hostServices, CF_SET_CMD, CF_DISABLE_OPT)

      # Verify if file is deactivated
      if cls._IsFileSet(hostServices, CF_ACTIVE_FIELD, cached=False):
         errMsgData = { 'CoredumpFilePath' :
                        cls._GetFilePath(hostServices, CF_ACTIVE_FIELD) }
         raise CreateLocalizedException(None, CF_DEACTIVATE_FAILED, errMsgData)

   @classmethod
   def _GetCoredumpFileDefaultSize(cls, hostServices):
      """Returns size of the active coredump file in MB.
      """
      if not cls.coredumpDefaultSize:
         storage = vmkctl.StorageInfoImpl()
         cls.coredumpDefaultSize = storage.GetRecommendedDumpSize()/(1024*1024)
         assert cls.coredumpDefaultSize, '_GetCoredumpFileDefaultSize failed'
      return cls.coredumpDefaultSize

   @classmethod
   def _CheckAndUpdateFile(cls, hostServices, datastore, size,
                           curDatastore, curSize):
      """Compare the given datastore and size parameters against the
      current values and update the coredump file, if required.
      """
      # If datastore or size is given, compare against current values
      # If size is not provided, check if current size is equal to or
      # more than the recommended size.
      if (datastore and curDatastore != datastore) or \
         (size and curSize != size) or \
         (not size and curSize < cls._GetCoredumpFileDefaultSize(hostServices)):
         cls._AddEnableFile(hostServices, datastore, size)
         return True

      return False

   @classmethod
   def _GetFileEntry(cls, hostServices, filePath):
      """Return datastore and size of a listed active or configured
      coredump file.

      It is assumed that the given filePath is valid.
      """
      if not cls.listCmdRes:
         cls.listCmdRes = InvokeEsxcliCF(hostServices, CF_LIST_CMD)
      for fileEntry in cls.listCmdRes:
         if CompareFilePaths(fileEntry[CF_LIST_PATH_FIELD], filePath):
            datastore = GetDatastoreFromPath(hostServices,
                                             fileEntry[CF_LIST_PATH_FIELD])
            assert datastore, 'Invalid file path: %s' % filePath
            size = GetSizeInMB(fileEntry[CF_LIST_SIZE_FIELD])
            return (datastore, size)
      assert False, '_GetFileEntry failed'

   #
   #  Config get, set and compare method implementations
   #
   @classmethod
   def CompareConfig(cls, hostServices, profileConfig, curConfig, **kwargs):
      """Compare user-provided config vs. current config and
      return TRUE if they match.

      User doesn't need to provide any values for datastore or size; this
      is considered as default. Given default datastore, any existing
      datastore ensures compliance. Given default size, the current size
      of the coredump file should be above the recommended minimum for
      the host.
      """
      # Do a quick compare on the most basic configuration
      if profileConfig['Enabled'] != curConfig['Enabled']:
         return False
      # If disabled, ignore the rest
      if not curConfig['Enabled']:
         return True

      profDatastore, profSize = profileConfig['Datastore'], profileConfig['Size']
      # curConfig is obtained using ExtractConfig which doesn't return
      # the actual datastore or the size (depending on its value)
      filePath = cls._GetFilePath(hostServices, CF_ACTIVE_FIELD)
      curDatastore, curSize = cls._GetFileEntry(hostServices, filePath)

      # If profile does not specify datastore(default), then any
      # datastore is compliant
      if profDatastore and profDatastore != curDatastore:
         return False

      # For default size (profSize == 0 or None), we see if the
      # current size is above the required minimum. If not, we
      # are non-compliant
      if (profSize and profSize != curSize) or \
         (not profSize and curSize < cls._GetCoredumpFileDefaultSize(hostServices)):
            return False

      return True

   @classmethod
   def ExtractConfig(cls, hostServices):
      """Check if we have coredump file enabled and return size of
      the coredump file if it differs from the recommended size. Datastore
      is always reported as default.
      """
      size = None
      enabled = cls._IsFileValid(hostServices, CF_ACTIVE_FIELD)

      if enabled:
         filePath = cls._GetFilePath(hostServices, CF_ACTIVE_FIELD)
         _, size = cls._GetFileEntry(hostServices, filePath)
         if size == cls._GetCoredumpFileDefaultSize(hostServices):
            size = None

      return { 'Enabled'   : enabled,
               'Datastore' : None,
               'Size'      : size }

   @classmethod
   def SetConfig(cls, configInfo, hostServices):
      """For the coredump file profile, the configInfo parameter should contain
      a list of dicts (list will have one element), where the dict contains
      three parameters Enabled, Datastore and Size.

      The coredump file settings can be in three states:
      1. Active and configured         [ ENABLED]
      2. Inactive but configured       [DISABLED]
      3. Neither active nor configured [DISABLED]
      """
      # Get the config dictionary
      config = configInfo[0]

      if config['Enabled']:
         # Enable coredump file
         datastore = config['Datastore']
         size      = config['Size']
         # *** 1. Active and configured [ENABLED] ***
         if cls._IsFileValid(hostServices, CF_ACTIVE_FIELD):
            # Get current datastore and size values
            filePath = cls._GetFilePath(hostServices, CF_ACTIVE_FIELD)
            curDatastore, curSize = cls._GetFileEntry(hostServices, filePath)

            cls._CheckAndUpdateFile(hostServices, datastore, size,
                                    curDatastore, curSize)
         else:
            # *** 2. Inactive but configured [DISABLED] ***
            if cls._IsFileValid(hostServices, CF_CONFIGURED_FIELD):
               filePath = cls._GetFilePath(hostServices, CF_CONFIGURED_FIELD)
               curDatastore, curSize = cls._GetFileEntry(hostServices, filePath)
               updated = cls._CheckAndUpdateFile(hostServices, datastore, size,
                                                 curDatastore, curSize)
               if not updated:
                  cls._ActivateFile(hostServices)
            else:
               # *** 3. Neither active nor configured [DISABLED] ***
               # Add a file in given datastore of the given size and activate it
               cls._AddEnableFile(hostServices, datastore, size)
      else:
         # Disable coredump file
         if cls._IsFileSet(hostServices, CF_ACTIVE_FIELD):
            cls._DeactivateFile(hostServices)

      return True
