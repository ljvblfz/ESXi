#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import GenericProfile
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SECURITY_SETTING, \
                      RELEASE_VERSION_CURRENT
from pluginApi import TASK_LIST_RES_OK
from pluginApi import CreateLocalizedMessage
from pluginApi import log
from .ADPermissionProfile import ActiveDirectoryPermissionProfile
from .ADPermissionProfile import PRINCIPAL
from .RoleProfile import RoleProfile
from .RoleProfile import ROLE
from .UserAccountProfile import UserAccountProfile, USERNAME, \
                                DEFAULT_ACCOUNTS, BLACKLISTED_USERS, \
                                DefaultAccountPasswordUnchangedOption
from .SecurityProfileUtils import GetDefaultRoles, INVALID_ROLE, \
                                  DUPLICATE_PRINCIPAL, DELETE_DEFAULT_ROLE, \
                                  DELETE_DEFAULT_ACCOUNT, \
                                  EDIT_DEFAULT_USER_ROLE, \
                                  EDIT_BLACKLISTEDUSER, PASSWORD_REQUIRED, \
                                  INVALID_PRINCIPAL


def VerifyUser(user, validationErrors, roleUserDict, userRoles, userNames):
   ''' Verify that the user is not attempting to change the role
       for a default account or attempting to edit the vpxuser
   '''
   retVal = True
   paramDict = dict(user.policies[0].policyOption.paramValue)
   passwordOption = user.policies[1].policyOption
   if isinstance(passwordOption, DefaultAccountPasswordUnchangedOption) and \
     paramDict[USERNAME] not in DEFAULT_ACCOUNTS:
         log.error('Password must be set for non default account: %s.'
                   % paramDict[USERNAME])
         validationErrors.append(CreateLocalizedMessage(None,
                        PASSWORD_REQUIRED, {USERNAME: paramDict[USERNAME]},
                        paramId=USERNAME, policy=user.policies[0],
                        profile=user))
         retVal = False

   log.info('Verify user called for: %s.' % paramDict[USERNAME])

   if paramDict[USERNAME] in BLACKLISTED_USERS:
      log.error('Cannot edit vpxuser')
      validationErrors.append(CreateLocalizedMessage(None,
                        EDIT_BLACKLISTEDUSER, {USERNAME: paramDict[USERNAME]},
                        paramId=USERNAME, policy=user.policies[0],
                        profile=user))
      retVal = False

   if paramDict[USERNAME] in DEFAULT_ACCOUNTS and paramDict[ROLE] != 'Admin':
      log.error('Cannot edit permissions for default user account: %s' %
                paramDict)
      validationErrors.append(CreateLocalizedMessage(None,
                        EDIT_DEFAULT_USER_ROLE,
                        {'name': paramDict[USERNAME]},
                        paramId=USERNAME, policy=user.policies[0],
                        profile=user))
      retVal = False

   if paramDict[USERNAME] in userNames:
      log.error('Duplicate user: %s' % paramDict[USERNAME])
      validationErrors.append(CreateLocalizedMessage(None, DUPLICATE_PRINCIPAL,
                              {'principal': paramDict[USERNAME]},
                              paramId=USERNAME, policy=user.policies[0],
                              profile=user))
      retVal = False
   else:
      userNames.add(paramDict[USERNAME])

   if paramDict[ROLE]:
      userRoles.add(paramDict[ROLE])
      if paramDict[ROLE] not in roleUserDict:
         roleUserDict[paramDict[ROLE]] = [user]
      else:
         roleUserDict[paramDict[ROLE]].append(user)
   return retVal

def VerifyUserRoles(userRoles, roleList, validationErrors, roleUserDict):
   ''' Verify that roles referenced in user account profile are in the role
       profile.
   '''
   log.debug('Roles in the user account profile: %s' % userRoles)
   log.debug('Roles in the role profile: %s' % roleList)
   if not userRoles.issubset(roleList):
      log.error('Invalid role name used in user account profile: %s %s' %
                (userRoles, roleList))
      invalidRoleList = list(userRoles - roleList)
      for r in invalidRoleList:
         for s in roleUserDict[r]:
            validationErrors.append(CreateLocalizedMessage(None,
                                    INVALID_ROLE, {'roleName': r},
                                    paramId=ROLE, policy=s.policies[0],
                                    profile=s))
      return False
   return True

def VerifyRoles(roleList, defaultRoles, adRoles, adPermissionMap, userRoles,
                roleUserDict, validationErrors):
   ''' Verify that we don't delete default roles and that the roles used in AD
       permissions are valid.
   '''
   retVal = True
   if not defaultRoles.issubset(roleList):
      defaultDeletedRoles = defaultRoles - roleList
      log.error('Cannot delete default roles: %s' % defaultDeletedRoles)
      for r in defaultDeletedRoles:
         validationErrors.append(CreateLocalizedMessage(None,
                                 DELETE_DEFAULT_ROLE, {ROLE: r}))
      retVal = False
      roleList.update(defaultRoles)

   if not adRoles.issubset(roleList):
      invalidRoles = adRoles - roleList
      log.error('Invalid role used in AD permission: %s' % invalidRoles)
      for r in invalidRoles:
         for p in adPermissionMap[r]:
            validationErrors.append(CreateLocalizedMessage(None,
                                 INVALID_ROLE, {'roleName': r},
                                 paramId=ROLE, policy=p.policies[0],
                                 profile=p))
      retVal = False

   return VerifyUserRoles(userRoles, roleList,
                            validationErrors,
                            roleUserDict) and retVal

def ProcessADPrincipal(paramDict, validationErrors, s):
   ''' Verify that the AD principal string contains an \\
       or an @.
   '''
   if not '\\' in paramDict[PRINCIPAL] and \
     not '@' in paramDict[PRINCIPAL]:
      log.error('Invalid principal (%s) for AD permission.' %
                paramDict[PRINCIPAL])
      validationErrors.append(CreateLocalizedMessage(None,
                              INVALID_PRINCIPAL, None,
                              paramId=PRINCIPAL, policy=s.policies[0],
                              profile=s))
      return False
   return True

def VerifyDelDefAccount(userNames, validationErrors):
   ''' Verify that we do not delete a default account.
   '''
   if not set(DEFAULT_ACCOUNTS).issubset(userNames):
      defaultDeletedUsers = set(DEFAULT_ACCOUNTS) - userNames
      log.error('Cannot delete default user account: %s' %
                                       defaultDeletedUsers)
      for user in defaultDeletedUsers:
         validationErrors.append(CreateLocalizedMessage(None,
                                 DELETE_DEFAULT_ACCOUNT, {'name': user}))
      return False
   return True

def ProcessADPermission(paramDict, adPrincipals, adRoles, adPermissionMap, s):
   ''' Bookkeep the roles used in AD permissions.
   '''
   role = paramDict[ROLE]
   adPrincipals.add(paramDict[PRINCIPAL])
   adRoles.add(role)
   if role not in adPermissionMap:
      adPermissionMap[role] = []
   adPermissionMap[role].append(s)

def VerifyDuplicateRole(s, roleList, validationErrors):
   ''' Verify that there are no duplicate roles.
   '''
   paramDict =  dict(s.policies[0].policyOption.paramValue)
   retVal = True
   if paramDict[ROLE] in roleList:
      log.error('Duplicate role in profile: %s' % paramDict)
      validationErrors.append(CreateLocalizedMessage(None,
                              DUPLICATE_PRINCIPAL,
                              {'principal': paramDict[ROLE]},
                              paramId=ROLE, policy=s.policies[0],
                              profile=s))
      retVal = False
   roleList.add(paramDict[ROLE])
   return retVal

def VerifyDuplicateADPermPrincipal(s, adPrincipals, adRoles, adPermissionMap,
                                   validationErrors):
   ''' Verify that there are no permissions with the same principal.
   '''
   paramDict =  dict(s.policies[0].policyOption.paramValue)

   retVal = ProcessADPrincipal(paramDict, validationErrors, s)

   if paramDict[PRINCIPAL] in adPrincipals:
      log.error('Duplicate principal (%s) for AD permission.' %
                paramDict[PRINCIPAL])
      validationErrors.append(CreateLocalizedMessage(None,
                              DUPLICATE_PRINCIPAL,
                              {PRINCIPAL: paramDict[PRINCIPAL]},
                              paramId=PRINCIPAL, policy=s.policies[0],
                              profile=s))
      retVal = False
   ProcessADPermission(paramDict, adPrincipals, adRoles,
                       adPermissionMap, s)
   return retVal

class SecurityConfigProfile(GenericProfile):
   singleton = True
   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SECURITY_SETTING
   subprofiles = [RoleProfile, UserAccountProfile,
                  ActiveDirectoryPermissionProfile]

   @classmethod
   def GatherData(cls, hostServices):
      return {}


   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      return cls(policies=[])

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      '''
      Validate input of sub profiles.
      '''
      if hostServices.earlyBoot:
         return True

      defaultRoles = GetDefaultRoles(hostServices)
      roleList = set()
      userNames = set()
      userRoles = set()

      adPermissionMap = {}
      adRoles = set()
      adPrincipals = set()

      roleUserDict = {}
      retVal = True
      sameVersion = profileInstance.version == RELEASE_VERSION_CURRENT

      for s in profileInstance.subprofiles:
         if isinstance(s, RoleProfile):
            retVal = VerifyDuplicateRole(s, roleList, validationErrors) and \
                     retVal

         elif isinstance(s, UserAccountProfile):
            retVal = VerifyUser(s, validationErrors, roleUserDict,
                                userRoles, userNames) and retVal
         elif isinstance(s, ActiveDirectoryPermissionProfile):
            retVal = VerifyDuplicateADPermPrincipal(s, adPrincipals, adRoles,
                                                    adPermissionMap,
                                                    validationErrors) and \
                     retVal
         else:
            log.error('Invalid sub profile instance: %s' % s)

      if sameVersion:
         retVal = VerifyRoles(roleList, defaultRoles, adRoles, adPermissionMap,
                              userRoles, roleUserDict, validationErrors) \
                  and retVal

      return VerifyDelDefAccount(userNames, validationErrors) and retVal


   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      return TASK_LIST_RES_OK


   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      return
