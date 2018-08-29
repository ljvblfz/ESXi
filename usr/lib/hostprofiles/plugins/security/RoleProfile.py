#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

import copy
import sys
import time

from pyEngine.simpleConfigProfile import SimpleProfileChecker

from pluginApi.extensions import SimpleConfigProfile
from pluginApi import log, ParameterMetadata, CreateLocalizedException, \
                      CreateLocalizedMessage, RELEASE_VERSION_CURRENT
from pyVim.account import CreateRole, RemoveRole
from pyVmomi import VmomiSupport
from pluginApi import nodeputil, HostServices, ProfileComplianceChecker
from .SecurityProfileUtils import RoleNameMap, ROLE_CREATE_FAILURE, \
   ROLE_REMOVE_FAILURE, GetDefaultRoles

ROLE = "roleName"
# Default roles have a negative roleId, all non default roles
# will have a roleId higher than this.
DEFAULT_ROLEID_CONST = -1
DEFAULT_PRIVILEGES = ["System.Anonymous", "System.Read", "System.View"]
STRLIST_TYPE = VmomiSupport.GetVmodlType('string[]')

def OverwriteDefRoles(hostServices, profileInstances, profileData):
   ''' Overwrite the profile data for default roles with the data
       from the host as we should not have compliance failures or
       task lists for default roles.
   '''
   defaultRoles = GetDefaultRoles(hostServices)
   hostDataMap = {k[ROLE] : k for k in profileData}
   defRolesInProf = []
   for p in profileInstances:
      opt = p.RoleProfilePolicy.policyOption
      rName = opt.roleName
      if rName in defaultRoles:
         OverwriteRole(opt, hostDataMap[rName])
         defRolesInProf.append(rName)
   for d in defaultRoles - set(defRolesInProf):
      profileData.remove(hostDataMap[d])


def OverwriteRole(opt, hostData=None):
   newParams = []
   if hostData:
      hostData.clear()
      hostData[ROLE] = opt.roleName
   for k, v in opt.paramValue:
      if k != ROLE:
         if hostData:
            hostData[k] = []
         newParams.append((k, None))
   opt.SetParameter(newParams)

def ProcessProfile(p, hostDataMap):
   ''' This function sets the System privilege list to
       empty. This is due to the fact that there are three
       default privileges that always get added to a profile
       instance.
   '''
   opt = p.RoleProfilePolicy.policyOption
   if 'System' not in hostDataMap[opt.roleName] or \
     not hostDataMap[opt.roleName]['System']:
      opt.System = None

def InitPrivList():
   if '--earlybootinit' in sys.argv:
      log.debug('Skipping privilege list initialization during early boot.')
      return []

   log.info('Setting up priv list.')
   postBoot = '--postbootinit' in sys.argv

   # Hostd may not be fully up when host profiles start to load
   # during postboot, so we retry connecting to hostd.
   maxRetries = 24
   waitTime = 5
   count = 0
   while True:
      try:
         # Get the privilege list to populate the parameters and valid input
         # values for the privilege category parameters.
         hsi = HostServices().hostServiceInstance
         privList = hsi.content.authorizationManager.privilegeList
         log.info('Successfully initialized privilege list.')
         return privList
      except Exception as e:
         log.warning('Failed to initialize privList: %s' % e)
         if postBoot and count < maxRetries:
            time.sleep(waitTime)
            count += 1
            log.info("Trying to connect to hostd (%d)" % count)
            continue
         log.error('Failed to connect to hostd to initialize privilege list.')
         return []

def GenerateParams(privList, privGroupDict, privConfig):
   privDict = {}
   for priv in privList:
      privGroupDict['.'.join([priv.privGroupName, priv.name])] = \
         priv.privGroupName
      if priv.privGroupName not in privDict:
         privDict[priv.privGroupName] = []
      privDict[priv.privGroupName].append(priv.privId)
      privConfig[priv.privGroupName] = []

   # Set up the paramters(role, privileges) for the Role Profile.
   # A parameter is created for the role name and each privilege group on the
   # host.
   params = [
      ParameterMetadata(ROLE, 'string', False,
         paramChecker=nodeputil.StringNonEmptyValidator())
   ]
   for k, v in privDict.items():
      defaultValue = None
      # As new roles will always be created with the default privileges
      # we set the defaultValue of the System privilege list to be the
      # default privileges.
      if k == 'System':
         defaultValue = STRLIST_TYPE(DEFAULT_PRIVILEGES)
      params.append(
         ParameterMetadata(k, 'string[]', True,
            paramChecker=nodeputil.ChoiceArrayValidator(v),
            defaultValue=defaultValue)
      )
   return params

class RoleProfileChecker(SimpleProfileChecker):
   ''' When a non default role is created it gets default privileges
       even if they aren't specified as part of the profile. Adjusting
       the compliance checker to handle this.
   '''
   def CheckProfileCompliance(self, profileInstances,
                              hostServices, profileData, parent):
      log.info('Checking compliance for the Role Profile.')
      OverwriteDefRoles(hostServices, profileInstances, profileData)
      return SimpleProfileChecker.CheckProfileCompliance(self, profileInstances,
                                                         hostServices,
                                                         profileData, parent)

class RoleProfile(SimpleConfigProfile):
   '''
   Host Profile implementation to capture Roles (A set of security privileges).
   '''

   isOptional = True
   singleton = False
   idConfigKeys = [ROLE]
   privGroupDict = {}
   privConfig = {}
   parameters = GenerateParams(InitPrivList(), privGroupDict,
                               privConfig)

   @classmethod
   def ExtractConfig(cls, hostServices):
      configList = []
      try:
         roles = hostServices.hostConfigInfo.role
         for role in roles:
            config = copy.deepcopy(cls.privConfig)
            config[ROLE] = role.name
            for priv in role.privilege:
               config[cls.privGroupDict[priv]].append(priv)
            configList.append(config)
      except:
         log.exception('Failed to extract roles.')
      return configList


   @classmethod
   def SetConfig(cls, config, hostServices):
      config = cls._flattenConfig(config)
      cls._removeRoles(config, hostServices)
      defaultRoles = GetDefaultRoles(hostServices)
      for roleName, rolePrivs in config.items():
         if roleName not in defaultRoles:
            try:
               log.info('Creating role: %s with privileges: %s' %
                        (roleName, rolePrivs))
               CreateRole(roleName, privsToAdd=rolePrivs)
            except Exception as e:
               log.exception('Failed to create Role %s: %s' % (roleName, e))
               raise CreateLocalizedException(None, ROLE_CREATE_FAILURE)


   @classmethod
   def _removeRoles(cls, config, hostServices):
      """ Delete non default roles that are either not in the config
          or exist with different privileges than specified in the config.
      """
      si = hostServices.hostServiceInstance
      roles = si.content.authorizationManager.roleList
      roleNameMap = RoleNameMap(hostServices)
      for role in roles:
         if roleNameMap[role.name] > -1:
            if role.name in config and \
               set(role.privilege) == set(config[role.name] + DEFAULT_PRIVILEGES):
               del config[role.name]
            else:
               log.info('Removing role: %s with roleID: %s' %
                        (role.name, role.roleId))
               try:
                  RemoveRole(role.roleId, False)
               except Exception as e:
                  log.exception("Failed to remove Role %s: %s" % (role.name, e))
                  raise CreateLocalizedException(None, ROLE_REMOVE_FAILURE)


   @classmethod
   def _flattenConfig(cls, config):
      """ Create a mapping from role name to privileges from the config
          @config: a list of dictionaries with the following structure:
            {
             "Role" : "RoleName",
             "Alarm" : ["Alarm.Acknowledge", "Alarm.Create",...],
             "Host.Config" : ["Host.Config.Power"],
             ...
            }
      """
      flatConfig = {}
      for c in config:
         privs = []
         name = ""
         for k, v in c.items():
            if k == ROLE:
               name = v
            elif v:
               privs.extend(v)
         if len(name):
            flatConfig[name] = privs
      return flatConfig

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      ''' Verify the following:
          -System.View, System.Anonymous and System.Read are default privileges.
           Throwing a validation error if the user tries to remove these from
           a new role.
          -Default roles are not edited.
      '''
      if profileInstance.version != RELEASE_VERSION_CURRENT:
         # Remove role privileges to avoid throwing privilege
         # validation errors when the host/profile are not at the same
         # version.
         opt = profileInstance.RoleProfilePolicy.policyOption
         hostDataMap = {k[ROLE] : k for k in profileData}
         OverwriteRole(opt)
         return True

      errorPrefix = 'com.vmware.vim.profile.Profile.RoleProfile.'\
                    'VerifyProfileError.'
      deleteDefaultPrivsError = '%sRemovingDefaultPrivileges.label' % \
                                errorPrefix
      editDefaultRoleError = '%sEditDefaultRole.label' % errorPrefix

      defaultRoles = GetDefaultRoles(hostServices)
      opt = profileInstance.RoleProfilePolicy.policyOption
      retVal = True

      if opt.roleName in defaultRoles:
         if profileData:
            hostDataMap = {k[ROLE] : k for k in profileData }
            ProcessProfile(profileInstance, hostDataMap)
            profParamDict = dict(opt.paramValue)
            for k, v in profParamDict.items():
               if v is None:
                  profParamDict[k] = []

            retVal = (hostDataMap[opt.roleName] == profParamDict)
            if not retVal:
               validationErrors.append(
                  CreateLocalizedMessage(None, editDefaultRoleError,
                                         paramId=ROLE,
                                         policy=profileInstance.RoleProfilePolicy,
                                         profile=profileInstance))

      else:
         if not opt.System or not set(DEFAULT_PRIVILEGES) <= set(opt.System):
            validationErrors.append(
               CreateLocalizedMessage(None, deleteDefaultPrivsError,
                                      paramId='System',
                                      policy=profileInstance.RoleProfilePolicy,
                                      profile=profileInstance))
            retVal = False

      return retVal and super(RoleProfile, cls).VerifyProfile(profileInstance,
                                                              hostServices,
                                                              profileData,
                                                              validationErrors)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, validationErrors):
      ''' When a non default role is created it gets default privileges
          even if they aren't specified as part of the profile. Adjusting
          generatetasklist to handle this.
      '''
      OverwriteDefRoles(hostServices, profileInstances, profileData)
      return super(RoleProfile, cls).GenerateTaskList(profileInstances,
                                                      taskList,
                                                      hostServices,
                                                      profileData,
                                                      validationErrors)


RoleProfile.complianceChecker = RoleProfileChecker(RoleProfile)

