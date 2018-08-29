#!/usr/bin/python
# **********************************************************
# Copyright 2010-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, \
                      CreateLocalizedMessage, \
                      CreateLocalizedException
from pluginApi import log, ProfileComplianceChecker, TASK_LIST_RES_OK
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_MANAGED_AGENT_CONFIG, \
                      RELEASE_VERSION_2016
from hpCommon.utilities import VersionLessThan
from pluginApi.extensions import SimpleConfigProfile, RangeValidator, \
                                 ChoiceValidator
from pyEngine.simpleConfigProfile import SimpleProfileChecker
from . import sfcbConstants as consts
import os
import copy
from pyEngine.genericProfile import ProfileTaskList



def ProcessProfileData(profileInstances, profileData):
   ''' PR 1985043: SSLv3 is no longer supported in sfcb so we
       always set it to default when performing hostprofile operations.

       If the host profile's version is before 6.5 set
       parameters added in this release to None in the profileData.
       Before editing the profileData we make a copy of it in oldProfileData
       and return oldProfileData in this case.
   '''

   prof = profileInstances[0]
   pv = prof.SfcbConfigProfilePolicy.policyOption.paramValue
   paramDict = dict(pv)
   if consts.SSLv3 in paramDict:
      pv.remove((consts.SSLv3, paramDict[consts.SSLv3]))
      pv.append((consts.SSLv3, consts.SSL_DEFAULT))


   if VersionLessThan(prof.version, RELEASE_VERSION_2016):
      oldProfileData = copy.deepcopy(profileData)
      profileData = profileData.GetLazyObjectWrapperData()
      for k in consts.NEW_PARAM_KEYS:
         profileData[k] = None
      return oldProfileData

   else:
      return


def RunEsxcli(hostServices, cmd):
   """ Wrapper function to execute a given esxcli command.
   """
   log.debug('Running cmd: %s' % cmd)
   errCode, output = hostServices.ExecuteEsxcli(cmd)

   if errCode != 0:
      log.error('SFCB command "%s" failed with error: %s' % (cmd, output))
      raise Exception('Esxcli wbem command failed with error: %s' % output)

   return output


def AddSSLConfig(sfcbConfig):
   """ If any of the SSL parameters are not part of the config, add them with
       their default value.
   """
   for x in consts.SSL_KEYS:
      if not x in sfcbConfig:
         sfcbConfig[x] = consts.SSL_DEFAULT

def ReadSfcbConfig(hostServices):
   """Helper function that reads the SFCB config file and returns a map
      of parameter names and  values.
   """
   sfcbConfig = {}
   with open(consts.SFCB_CONFIG_FILE, 'r') as sfcbConfigFile:
      for line in sfcbConfigFile:
         paramName, sep, paramVal = line.strip().partition(':')
         if sep:
            paramVal = paramVal.strip()
            paramName = paramName.strip()
            # Read only the older parameters and SSL parameters from the file.
            if paramName not in consts.OLD_PARAM_KEYS + consts.SSL_KEYS:
               continue
            try:
               # Treat parameters that can be converted into integers as int
               # values.
               paramIntVal = int(paramVal)
               sfcbConfig[paramName] = paramIntVal
            except:
               # Keep it as a string
               if paramName in consts.SSL_KEYS:
                  if paramVal.lower() == 'true':
                     paramVal = consts.SSL_ENABLED
                  elif paramVal.lower() == 'false':
                     paramVal = consts.SSL_DISABLED
                  else:
                     paramVal = consts.SSL_DEFAULT
               sfcbConfig[paramName] = paramVal

   # Add default SSL values if not present.
   AddSSLConfig(sfcbConfig)

   # Read the rest of the parameters from esxcli.
   cmd = '%s %s' % (consts.ESXCLI_SFCB_NS, consts.ESXCLI_SFCB_GET)
   output = RunEsxcli(hostServices, cmd)

   for key, val in output.items():
      if key in consts.labelMap:
         # Map the label returned by esxcli to the parameter name.
         sfcbConfig[consts.labelMap[key]] = val

   # Get the disabled providers list.
   output = RunEsxcli(hostServices, consts.ESXCLI_PROVIDER_LIST)
   disabledProvList = []
   for prov in output:
      if not prov['Enabled']:
         disabledProvList.append(prov['Name'])
   sfcbConfig[consts.DISABLED_PROVIDERS] = disabledProvList

   # Read the key in the certificate store.
   try:
      with open(consts.CERTIFICATE_STORE_PATH, 'r') as f:
         sfcbConfig[consts.CERTIFICATE_STORE] = f.read()
   except IOError as e:
      sfcbConfig[consts.CERTIFICATE_STORE] = ''

   return sfcbConfig


def GetParams(sfcbConfig):
   """ Helper function to create the arguments to be passed to the esxcli
       command.
   """
   args = []
   for key in consts.NEW_PARAM_KEYS:
      if sfcbConfig[key] is not None:
         if key in [consts.CERTIFICATE_STORE, consts.DISABLED_PROVIDERS]:
            continue
         if key in [consts.CIM_SERVICE, consts.WSMAN_SERVICE]:
            sfcbConfig[key] = int(sfcbConfig[key])
         args.append('--%s %s' % (key, sfcbConfig[key]))
   return args


def SetProviderState(hostServices, profileConfig, hostConfig):
   """ Executes esxcli commands to enable/disable the providers.
   """
   if profileConfig is None:
      profileConfig = []
   if hostConfig is None:
      hostConfig = []
   # Enable providers which are in the host list but not the profile list.
   providersToEnable = set(hostConfig) - set(profileConfig)
   for prov in providersToEnable:
      cmd = '%s --name=%s --enable true' % (consts.ESXCLI_PROVIDER_SET, prov)
      RunEsxcli(hostServices, cmd)

   # Disable providers which are in the profile list but not in the host list.
   providersToDisable = set(profileConfig) - set(hostConfig)
   for prov in providersToDisable:
      cmd = '%s --name=%s --enable false' % (consts.ESXCLI_PROVIDER_SET, prov)
      RunEsxcli(hostServices, cmd)


def WriteSfcbConfig(configParams, hostServices):
   """Helper function that writes out the supplied configuration settings
      to the sfcb config file. Note that any settings that are not supplied
      in the configParams parameter will be carried over from the current
      configuration file.
   """
   # Get the current configuration
   sfcbConfig = ReadSfcbConfig(hostServices)
   disabledProvCopy = sfcbConfig[consts.DISABLED_PROVIDERS]

   # Overwrite any settings supplied in the configParams parameter.
   sfcbConfig.update(configParams)

   with open(consts.SFCB_CONFIG_FILE, 'r') as sfcbConfigFile:
      lines = sfcbConfigFile.readlines()

   newFile = []
   for line in lines:
      paramKey = line.split(':')[0].strip()
      if paramKey in consts.OLD_PARAM_KEYS and paramKey in sfcbConfig:
         paramEntry = '%s: %s\n' % (paramKey, sfcbConfig[paramKey])
         newFile.append(paramEntry)
      elif paramKey in consts.SSL_KEYS:
         # These will be handled after this for loop.
         continue
      else:
         # Append existing line.
         newFile.append(line)

   # Process the SSL keys.
   for key, val in sfcbConfig.items():
      if key in consts.SSL_KEYS:
         if val in [consts.SSL_DEFAULT, None]:
            # Skip this line if value is default or None.
            continue
         paramEntry = '%s: %s\n' % (key, val)
         newFile.append(paramEntry)

   with open(consts.SFCB_CONFIG_FILE, 'w') as sfcbConfigFile:
      sfcbConfigFile.write(''.join(newFile))

   # Write out the certificate store first.
   if sfcbConfig[consts.CERTIFICATE_STORE] is not None:
      try:
         with open(consts.CERTIFICATE_STORE_PATH, 'w') as f:
            f.write(sfcbConfig[consts.CERTIFICATE_STORE])
            os.chmod(consts.CERTIFICATE_STORE_PATH, 0o600)
      except IOError as e:
         log.exception('Failed to write to certificate store: %s' % e)

   # Let's disable the service first and then make required changes.
   cmd = '%s %s -e 0' % (consts.ESXCLI_SFCB_NS, consts.ESXCLI_SFCB_SET)
   RunEsxcli(hostServices, cmd)

   # Other params are set through esxcli.
   params = GetParams(sfcbConfig)
   if params:
      cmd = ' '.join([consts.ESXCLI_SFCB_NS, consts.ESXCLI_SFCB_SET])
      cmd = cmd + ' ' + ' '.join(params)
      RunEsxcli(hostServices, cmd)

   # Disable required providers and enable the rest.
   SetProviderState(hostServices, sfcbConfig[consts.DISABLED_PROVIDERS],
                    disabledProvCopy)

class SfcbProfileChecker(SimpleProfileChecker):
   ''' We added parameters to this profile in 6.5. So we ignore
       these parameters during compliance checking a profile whose
       version is below 6.5.
   '''
   def CheckProfileCompliance(self, profileInstances,
                              hostServices, profileData, parent):
      ProcessProfileData(profileInstances, profileData)
      return SimpleProfileChecker.CheckProfileCompliance(self,
                                                         profileInstances,
                                                         hostServices,
                                                         profileData,
                                                         parent)

class SfcbConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages SFCB Configuration settings on ESX hosts.
   """
   #
   # Define required class attributes
   #
   isOptional = True

   parameters = [
      ParameterMetadata(consts.PROV_PROCS, 'int', isOptional,
                        paramChecker=RangeValidator(0, 1024)),
      ParameterMetadata(consts.THREAD_POOL_SIZE, 'int', isOptional,
                        paramChecker=RangeValidator(3, 25)),
      ParameterMetadata(consts.REQ_QUEUE_SIZE, 'int', isOptional,
                        paramChecker=RangeValidator(0, 30)),
      ParameterMetadata(consts.PORT, 'int', isOptional),
      ParameterMetadata(consts.LOG_LEVEL, 'string', isOptional,
                        paramChecker=ChoiceValidator(consts.LOGLEVEL_CHOICES)),
      ParameterMetadata(consts.AUTH, 'string', isOptional,
                        paramChecker=ChoiceValidator(consts.AUTH_CHOICES)),
      ParameterMetadata(consts.CIM_SERVICE, 'bool', isOptional),
      ParameterMetadata(consts.WSMAN_SERVICE, 'bool', isOptional),
      ParameterMetadata(consts.CERTIFICATE_STORE, 'string', isOptional),
      ParameterMetadata(consts.DISABLED_PROVIDERS, 'string[]', isOptional),

      # SSL/TLS configuration parameters.
      ParameterMetadata(consts.SSLv3, 'string', isOptional=False,
         paramChecker=ChoiceValidator(consts.SSL_CHOICES),
         defaultValue=consts.SSL_DEFAULT),
      ParameterMetadata(consts.TLSv1, 'string', isOptional=False,
         paramChecker=ChoiceValidator(consts.SSL_CHOICES),
         defaultValue=consts.SSL_DEFAULT),
      ParameterMetadata(consts.TLSv1_1, 'string', isOptional=False,
         paramChecker=ChoiceValidator(consts.SSL_CHOICES),
         defaultValue=consts.SSL_DEFAULT),
      ParameterMetadata(consts.TLSv1_2, 'string', isOptional=False,
         paramChecker=ChoiceValidator(consts.SSL_CHOICES),
         defaultValue=consts.SSL_DEFAULT),
      ]

   singleton = True

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_MANAGED_AGENT_CONFIG



   @classmethod
   def ExtractConfig(cls, hostServices):
      """Reads the SFCB config file and retrieves the public parameters from
         that file.
      """
      paramList = [ param.paramName for param in cls.parameters ]
      try:
         sfcbConfig = ReadSfcbConfig(hostServices)
         publicConfig = {}
         for paramName, paramVal in sfcbConfig.items():
            if paramName in paramList:
               publicConfig[paramName] = paramVal
         log.debug('SFCB config: %s' % publicConfig)
         return publicConfig
      except Exception as exc:
         log.exception('Failed to read SFCB config: %s' % exc)
         fault = CreateLocalizedException(
                 None, consts.FAILED_TO_READ_MSG_KEY)
         raise fault


   @classmethod
   def SetConfig(cls, config, hostServices):
      """Sets the public configuration settings for SFCB.
      """
      sfcbConfig = config
      if isinstance(config, list):
         assert len(config) == 1
         sfcbConfig = config[0]

      try:
         WriteSfcbConfig(sfcbConfig, hostServices)
      except Exception as exc:
         log.exception('Failed to save SFCB config: %s' % str(exc))
         fault = CreateLocalizedException(
                 None, consts.FAILED_TO_SAVE_MSG_KEY)
         raise fault

      # Should we restart all the time?
      hostServices.RequestCimRestart()
      # End of SetConfig()

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices,
                     profileData, validationErrors):
      '''Function to validate the SFCB configuration.
      '''
      isValid = True

      # CertificateStore is required if auth method is certificate.
      policyOpt = profileInstance.policies[0].policyOption
      if (getattr(policyOpt, consts.AUTH) == 'certificate' and
          not getattr(policyOpt, consts.CERTIFICATE_STORE)):
         invalidCertificateMsg = CreateLocalizedMessage(
                                    None, consts.NO_CERTIFICATE_STORE_PRESENT)
         invalidCertificateMsg.SetRelatedPathInfo(profile=profileInstance,
            policy=profileInstance.policies[0],
            paramId=consts.CERTIFICATE_STORE)
         validationErrors.append(invalidCertificateMsg)
         log.error('[SFCB plugin] Certificate store is required when ' \
                   'authorization mode is "certificate".')
         isValid = False

      # Validate the list of disabled providers.
      provList = getattr(policyOpt, consts.DISABLED_PROVIDERS)
      if provList:
         output = RunEsxcli(hostServices, consts.ESXCLI_PROVIDER_LIST)
         validProviders = [ x['Name'] for x in output ]
         if not set(provList).issubset(set(validProviders)):
            invalidEntries = ', '.join(set(provList) - set(validProviders))
            invalidProviderListMsg = CreateLocalizedMessage(
               None, consts.INVALID_PROVIDERS_LIST,
               {'invalidEntries' : invalidEntries})
            invalidProviderListMsg.SetRelatedPathInfo(profile=profileInstance,
               policy=profileInstance.policies[0],
               paramId=consts.DISABLED_PROVIDERS)
            validationErrors.append(invalidProviderListMsg)
            log.error('[SFCB plugin] Invalid entries in provider list: %s. ' \
                      'Providers not present on host.' % invalidEntries)
            isValid = False

      return isValid

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      ''' We need to process the profileData as parameters were added in 6.5
          and we should not have tasks for these parameters with a profile whose
          version is less than 6.5.
      '''
      oldProfileData = ProcessProfileData(profileInstances, profileData)
      superClassGtl = super(SfcbConfigProfile, cls).GenerateTaskList
      if VersionLessThan(profileInstances[0].version, RELEASE_VERSION_2016):
         tempTaskList = ProfileTaskList()
         retVal = superClassGtl(profileInstances, tempTaskList, hostServices,
                                profileData, parent)
         # During apply the configuration that is being edited is searched for
         # so we need to replace the currentConfig portion of the taskList with
         # the oldProfileData.
         for task0 in tempTaskList:
            msg, (task, (_, newData), version) = task0
            taskList.addTask(msg, (task, (oldProfileData, newData), version))
            break
      else:
         retVal = superClassGtl(profileInstances, taskList, hostServices,
                                profileData, parent)
      return retVal

SfcbConfigProfile.complianceChecker = SfcbProfileChecker(SfcbConfigProfile)