#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

import os
import shutil

from pluginApi import GenericProfile
from pluginApi import log, ParameterMetadata
from pluginApi import FixedPolicyOption, UserInputRequiredOption
from pluginApi import Policy, ProfileComplianceChecker
from pluginApi import TASK_LIST_RES_OK, CreateLocalizedMessage
from pluginApi import CreateComplianceFailureValues, PARAM_NAME, MESSAGE_KEY
from pluginApi import nodeputil
from pluginApi.extensions import SimpleConfigProfile, ComplianceCheckDisabled
from pyVim.account import CreatePosixUser, RemoveUser
from pyVmomi import vim, Vim
from pluginApi import CheckUserPassword
from .SecurityProfileUtils import RoleIdMap, RoleNameMap
from .SecurityProfileUtils import USERACCOUNT_BASE
from .RoleProfile import RoleProfile, ROLE
from pyEngine.profile import Profile
from vmware import runcommand

USERNAME = 'name'
PASSWORD = 'password'
DESCRIPTION = 'description'
POSIX_ID = 'posixId'
SHELL_ACCESS = 'shellAccess'
SSH_KEY = "sshKey"

AUTH_DIR = '/etc/ssh/'
AUTH_ROOT_DIR = '/etc/ssh/keys-root'
AUTH_FILE = 'authorized_keys'

complianceErrorBase = '%sComplianceError.' % USERACCOUNT_BASE
gtlBase = '%sGenerateTaskList.' % USERACCOUNT_BASE

BLACKLISTED_USERS = ['vpxuser', 'dcui']
DEFAULT_ACCOUNTS = ['root']

DEL_USERS = 'delUsers'
MODIFY_USERS = 'modifyUsers'
ADD_USERS = 'addUsers'
DEL_PERMISSIONS = 'delPermissions'
ADD_PERMISSIONS = 'addPermissions'
DEL_AUTHKEYS = 'delAuthKeys'
ADD_AUTHKEYS = 'addAuthKeys'

ADD_USER_CMD = '/usr/lib/vmware/auth/bin/adduser'

def getExistingUsers(hostServices):
   si = hostServices.hostServiceInstance
   userDir = si.content.userDirectory
   return userDir.RetrieveUserGroups(searchStr='', exactMatch=False,
                                     findUsers=True, findGroups=False)

def getExistingPermissions(hostServices):
   si = hostServices.hostServiceInstance
   return si.content.authorizationManager.RetrieveAllPermissions()

def ReadKeyFile(f):
   ''' Read and return the contents of the public key
      file.
   '''
   pubKeyInFile = ''
   try:
      with open(f, 'r') as fileHandle:
         # NOTE: This file will have only one entry which translates
         # to one line. So a read() of the file should get all the
         # contents this profile is interested in.
         pubKeyInFile = fileHandle.read()
      pubKeyInFile = pubKeyInFile.rstrip('\n')
   except Exception as e:
      log.exception('Failed to read ssh public key (%s): %s' % (f, e))
   return pubKeyInFile

def GetKeyDirPath(user):
   ''' Given a username return /etc/ssh/keys-username.
   '''
   return os.path.join(AUTH_DIR, 'keys-%s' % user)

def GetKeyFilePath(user):
   ''' Given a username return /etc/ssh/keys-username/authorized_keys
   '''
   return os.path.join(GetKeyDirPath(user), AUTH_FILE)

def GtlNewUser(user, addUsers, addPermissions, addAuthKeys):
   ''' Processes a new user and determines if a new permission
      and/or an ssh public key need to be created.
   '''
   user[PASSWORD] = user[PASSWORD].value
   addUsers.append(user)
   if user[ROLE]:
      addPermissions.append((user[USERNAME], user[ROLE]))
   if user[SSH_KEY]:
      addAuthKeys.append((user[USERNAME], user[SSH_KEY]))

def GtlExistingUser(user, currUserDict, modifyUsers, delPermissions,
                    addPermissions, delAuthKeys, addAuthKeys):
   ''' Processes an existing user to determine if they need be modified (change
      password/description) and determine any changes to the user's ssh public
      key or role.
   '''
   if isinstance(user[PASSWORD], Vim.PasswordField):
      user[PASSWORD] = user[PASSWORD].value
      if not CheckUserPassword(user[USERNAME], user[PASSWORD]):
         # CheckUserPassword returns true if the username, password
         # successfully authenticates the user (If not the password needs
         # to be updated).
         if user[DESCRIPTION] == currUserDict[user[USERNAME]][DESCRIPTION]:
            del user[DESCRIPTION]
         modifyUsers.append(user)

   elif user[DESCRIPTION] != currUserDict[user[USERNAME]][DESCRIPTION]:
      user.pop(PASSWORD)
      modifyUsers.append(user)

   if user[USERNAME] not in DEFAULT_ACCOUNTS:
      if user[ROLE] != currUserDict[user[USERNAME]][ROLE]:
         if not user[ROLE]:
            delPermissions.append(user[USERNAME])
         else:
            addPermissions.append((user[USERNAME], user[ROLE]))
   if user[SSH_KEY] != currUserDict[user[USERNAME]][SSH_KEY]:
      if not user[SSH_KEY]:
         delAuthKeys.append(user[USERNAME])
      else:
         addAuthKeys.append((user[USERNAME], user[SSH_KEY]))

def CreatePermission(user, roleId, group=False):
   p = Vim.AuthorizationManager.Permission()
   p.principal = user
   p.group = group
   p.roleId = roleId
   p.propagate = True
   return p

def CreateUserSpec(config):
   spec = vim.host.LocalAccountManager.AccountSpecification()
   spec.id = config[USERNAME]
   if DESCRIPTION in config:
      spec.description = config[DESCRIPTION]
   if PASSWORD in config:
      spec.password = config[PASSWORD]
   return spec

def AddAuthKey(user, key):
   ''' Write the ssh public key for the specified user.
   '''
   sshKeyDir = GetKeyDirPath(user)
   sshKeyFile = GetKeyFilePath(user)
   try:
      if not os.path.exists(sshKeyDir):
         os.makedirs(sshKeyDir, 0o755)
      with open(sshKeyFile, 'w') as fileHandle:
         fileHandle.write(key + '\n')
   except Exception as e:
      log.exception('Failed to set ssh public key (%s): %s' %
                    (c[USERNAME], e))

def GetCurrentUserDict(profileData):
   return {dict(x)[USERNAME]: dict(x) for x in profileData}

def CreateCompFailureVal(ident, profVal, hostVal, t=PARAM_NAME, inst=None):
   return CreateComplianceFailureValues(ident, t, profVal, hostVal,
                                        inst)

def ProcessUserAccountPolicies(policies):
   d = {'passwordPolicy' : None, 'userPolicy' : None}
   for p in policies:
      if isinstance(p, PasswordPolicy):
         d['passwordPolicy'] = p.policyOption
      if isinstance(p, UserPolicy):
         d['userPolicy'] = p.policyOption
   return d

class UserAccountProfileChecker(ProfileComplianceChecker):
   @staticmethod
   def _checkComplianceUserRole(user, profileUserDict, currPermissions,
                                roleIdMap, complianceFailures):
      ''' Add any compliance failures for user roles.
      '''

      # The root user's role is always extracted as Admin
      # and when the host is in lockdown mode there is no Role
      # for the root user, so adding this check to avoid throwing
      # a compliance failure.
      # TODO: Remove such checks once lockdown mode is added to host profiles.
      if user in DEFAULT_ACCOUNTS:
         return

      if not profileUserDict[user][ROLE] and user in currPermissions:
         roleName = roleIdMap[currPermissions[user].roleId]
         log.error('User profile does not contain role(%s) that is present '
                   'on host for: %s' % (roleName, user))
         complianceFailures.append(
            (CreateLocalizedMessage(None,
               '%sUserRoleNotInProfile.label' % complianceErrorBase,
               {USERNAME: user, ROLE: roleName}),
            [CreateCompFailureVal(ROLE, None, roleName)]))

      elif profileUserDict[user][ROLE]:
         if user not in currPermissions:
            roleName = profileUserDict[user][ROLE]
            log.error('User on host does not contain role(%s) that is present '
                    'in profile for: %s' % (roleName, user))
            complianceFailures.append(
               (CreateLocalizedMessage(None,
                  '%sUserRoleNotOnHost.label' % complianceErrorBase,
                  {USERNAME: user, ROLE: roleName}),
               [CreateCompFailureVal(ROLE, roleName, None)]))
         elif profileUserDict[user][ROLE] != \
           roleIdMap[currPermissions[user].roleId]:
            hostRole = roleIdMap[currPermissions[user].roleId]
            profileRole = profileUserDict[user][ROLE]
            log.error('User role on host(%s) does not match profile(%s) for %s'
                    % (profileRole, hostRole, user))
            complianceFailures.append(
               (CreateLocalizedMessage(None,
                  '%sUserRoleMismatch.label' % complianceErrorBase,
                  {USERNAME: user, 'hostRole': hostRole,
                   'profileRole': profileRole}),
               [CreateCompFailureVal(ROLE, profileRole, hostRole, user)]))

   @staticmethod
   def _checkComplianceAuthKey(user, profileUserDict, complianceFailures):
      ''' Add any compliance failures for ssh public keys.
      '''
      userKeyFile = GetKeyFilePath(user)
      if not profileUserDict[user][SSH_KEY] and os.path.exists(userKeyFile) \
        and ReadKeyFile(userKeyFile):
         log.error('SSH public key on host not present in profile: %s'
                 % user)
         complianceFailures.append(
            (CreateLocalizedMessage(None,
            '%sPublicKeyNotInProfile.label' % complianceErrorBase,
            {USERNAME: user}), [CreateCompFailureVal(SSH_KEY, None,
            'SSH Public Key on Host', user)]))

      elif profileUserDict[user][SSH_KEY]:
         if not os.path.exists(userKeyFile):
            log.error('SSH public key in profile not present on host: %s'
                    % user)
            complianceFailures.append(
               (CreateLocalizedMessage(None,
               '%sPublicKeyNotOnHost.label' % complianceErrorBase,
               {USERNAME: user}), [CreateCompFailureVal(SSH_KEY,
               'SSH Public Key in Profile', None, user)]))
         else:
            keyFileContent = ReadKeyFile(userKeyFile)
            if profileUserDict[user][SSH_KEY] != keyFileContent:
               log.error('SSH public key on host does not match profile.')
               complianceFailures.append(
                  (CreateLocalizedMessage(None,
                  '%sPublicKeyMismatch.label' % complianceErrorBase,
                  {USERNAME: user}), [CreateCompFailureVal(SSH_KEY,
                  'SSH Public Key in Profile', 'SSH Public Key on host',
                  user)]))

   @staticmethod
   def _checkCompliancePassword(user, complianceFailures):
      if user[PASSWORD]:
         if not CheckUserPassword(user[USERNAME], user[PASSWORD].value):
            complianceFailures.append(CreateLocalizedMessage(None,
                  '%sPasswordMismatch.label' % complianceErrorBase,
                  {USERNAME: user[USERNAME]}))

   @classmethod
   def CheckProfileCompliance(cls, profileInstances,
                        hostServices, profileData, parent):
      log.info('Check Compliance for User Account Profile')
      currUserDict = GetCurrentUserDict(profileData)
      profileUserDict = {}
      userNameProfInst = {}
      disabledUsers = []
      for x in profileInstances:
         policyDict = ProcessUserAccountPolicies(x.policies)
         passwordOption = policyDict['passwordPolicy']
         passwordDict = {PASSWORD : ''}
         if not isinstance(passwordOption, \
           DefaultAccountPasswordUnchangedOption):
            passwordDict[PASSWORD] = dict(passwordOption.paramValue)[PASSWORD]
         userDict = dict(policyDict['userPolicy'].paramValue)
         userDict.update(passwordDict)
         profileUserDict[userDict[USERNAME]] = userDict
         userNameProfInst[userDict[USERNAME]] = x
         if ComplianceCheckDisabled(x):
            disabledUsers.append(userDict[USERNAME])

      complianceFailures = []

      currUsers = set(currUserDict.keys()) - set(disabledUsers)
      profileUsers = set(profileUserDict.keys()) - set(disabledUsers)
      msgKey = '%slabel' % USERACCOUNT_BASE

      if currUsers - profileUsers:
         users = currUsers - profileUsers
         log.error('Users: %s not present in profile' % users)
         for x in users:
            complianceFailures.append(
               (CreateLocalizedMessage(None,
               '%sUserNotInProfile.label' % complianceErrorBase,
               {USERNAME: x}), [CreateCompFailureVal(msgKey, '', x,
                                                     t=MESSAGE_KEY)]))

      elif profileUsers - currUsers:
         users = profileUsers - currUsers
         log.error('Users: %s not present on host' % users)
         for x in users:
            complianceFailures.append(
               (CreateLocalizedMessage(None,
               '%sUserNotOnHost.label' % complianceErrorBase,
               {USERNAME: x}), [CreateCompFailureVal(msgKey, x, '',
                                                     t=MESSAGE_KEY)]))

      commonUsers = currUsers & profileUsers
      currPermissions = \
         {x.principal: x for x in getExistingPermissions(hostServices)}
      roleIdMap = RoleIdMap(hostServices)
      for user in commonUsers:
         UserAccountProfileChecker._checkCompliancePassword(
            profileUserDict[user], complianceFailures)
         UserAccountProfileChecker._checkComplianceUserRole(user,
            profileUserDict, currPermissions, roleIdMap,
            complianceFailures)
         UserAccountProfileChecker._checkComplianceAuthKey(user,
            profileUserDict, complianceFailures)
      return (not bool(complianceFailures), complianceFailures)

passwordParam = ParameterMetadata(PASSWORD, 'Vim.PasswordField', False,
                                  securitySensitive=True,
                                  paramChecker=
                                    nodeputil.LocalAccountPasswordValidator)

class UserPolicyOption(FixedPolicyOption):
   paramMeta = [
      ParameterMetadata(USERNAME, 'string', False),
      ParameterMetadata(DESCRIPTION, 'string', True),
      ParameterMetadata(POSIX_ID, 'int', True),
      ParameterMetadata(SSH_KEY, 'string', True, securitySensitive=True),
      ParameterMetadata(ROLE, 'string', True)]

class UserInputPasswordConfigOption(UserInputRequiredOption):
   userInputParamMeta = [passwordParam]
   complianceChecker = None

class DefaultAccountPasswordUnchangedOption(FixedPolicyOption):
   paramMeta = []
   complianceChecker = None

class FixedPasswordConfigOption(FixedPolicyOption):
   paramMeta = [passwordParam]
   complianceChecker = None

class UserPolicy(Policy):
   possibleOptions = [UserPolicyOption]

class PasswordPolicy(Policy):
   possibleOptions = [UserInputPasswordConfigOption, FixedPasswordConfigOption,
                      DefaultAccountPasswordUnchangedOption]
   _defaultOption = FixedPasswordConfigOption([])

   def PrepareExport(self):
      if isinstance(self.policyOption, FixedPasswordConfigOption):
         self.policyOption = UserInputPasswordConfigOption([])

class UserAccountProfile(GenericProfile):
   '''
   Host Profile implementation of non default user accounts.
   '''
   policies = [UserPolicy, PasswordPolicy]
   singleton = False
   complianceChecker = UserAccountProfileChecker()
   dependencies = [RoleProfile]

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                   profileData, parent):
      pols = [ProcessUserAccountPolicies(x.policies) for x in profileInstances]
      pols = [(dict(x['userPolicy'].paramValue),
                    x['passwordPolicy']) for x in pols]

      # Handle adding non default users during early boot.
      if hostServices.earlyBoot:
         for s, p in pols:
            if s[USERNAME] not in DEFAULT_ACCOUNTS:
               s[PASSWORD] = dict(p.paramValue)[PASSWORD].value
               taskList.addTask(CreateLocalizedMessage(None, '%saddUser.label'
                  % gtlBase, {USERNAME: s[USERNAME]}), (ADD_USERS,
                                                        CreateUserSpec(s)))
         return TASK_LIST_RES_OK

      currUserDict = GetCurrentUserDict(profileData)
      delUsers = set(currUserDict.keys())
      addUsers = []
      modifyUsers = []
      addPermissions = []
      addAuthKeys = []
      delPermissions = []
      delAuthKeys = []

      for s, p in pols:
         log.info('[GTL] Processing user account policy for user: %s' %
                  s[USERNAME])
         s[PASSWORD] = ''
         if not isinstance(p, DefaultAccountPasswordUnchangedOption):
            s[PASSWORD] = dict(p.paramValue)[PASSWORD]
         delUsers.discard(s[USERNAME])

         if s[USERNAME] not in currUserDict:
            GtlNewUser(s, addUsers, addPermissions, addAuthKeys)
         elif s != currUserDict[s[USERNAME]]:
            GtlExistingUser(s, currUserDict, modifyUsers, delPermissions,
                        addPermissions, delAuthKeys, addAuthKeys)

      if addUsers:
         for x in addUsers:
            log.info('Adding user: %s' % x[USERNAME])
            taskList.addTask(CreateLocalizedMessage(None, '%saddUser.label'
               % gtlBase, {USERNAME: x[USERNAME]}), (ADD_USERS,
               CreateUserSpec(x)))
      if modifyUsers:
         for x in modifyUsers:
            log.info('Modifying user: %s' % x[USERNAME])
            taskList.addTask(CreateLocalizedMessage(None, '%smodifyUser.label'
               % gtlBase, {USERNAME: x[USERNAME]}), (MODIFY_USERS,
               CreateUserSpec(x)))
      if delUsers:
         for user in delUsers:
            log.info('Deleting user: %s' % user)
            if os.path.exists(GetKeyFilePath(user)):
               delAuthKeys.append(user)
            taskList.addTask(CreateLocalizedMessage(None, '%sdelUser.label'
               % gtlBase, {USERNAME: user}), (DEL_USERS, user))
      if addPermissions:
         for (user, role) in addPermissions:
            log.info('Adding permission: %s %s' % (user, role))
            taskList.addTask(CreateLocalizedMessage(None,
               '%saddPermission.label' % gtlBase, {USERNAME: user}),
               (ADD_PERMISSIONS, (user, role)))
      if addAuthKeys:
         for (user, key) in addAuthKeys:
            log.info('Adding ssh public key for user: %s' % user)
            taskList.addTask(CreateLocalizedMessage(None, '%saddAuthKey.label'
               % gtlBase, {USERNAME: user}), (ADD_AUTHKEYS, (user,
               Vim.PasswordField(value=key))))
      if delPermissions:
         for user in delPermissions:
            log.info('Deleting permission for user: %s' % user)
            taskList.addTask(CreateLocalizedMessage(None,
               '%sdelPermission.label' % gtlBase, {USERNAME: user}),
               (DEL_PERMISSIONS, user))
      if delAuthKeys:
         for user in delAuthKeys:
            log.info('Deleting ssh public keys for user: %s' % user)
            taskList.addTask(CreateLocalizedMessage(None, '%sdelAuthKey.label'
               % gtlBase, {USERNAME: user}), (DEL_AUTHKEYS, user))

      return TASK_LIST_RES_OK

   @classmethod
   def GatherData(cls, hostServices):
      configList = []
      if hostServices.earlyBoot:
         return configList
      existingUsers = getExistingUsers(hostServices)
      userRoleMap = {}
      roleIdMap = RoleIdMap(hostServices)
      for p in getExistingPermissions(hostServices):
         userRoleMap[p.principal] = roleIdMap[p.roleId]
      for user in existingUsers:
         if user.principal in BLACKLISTED_USERS:
            continue
         roleStr = None
         # When the host is in lockdown mode the root user's Role
         # is not Admin. We need the root user's Role to always be Admin
         # in host profiles so hard coding this here.
         if user.principal in DEFAULT_ACCOUNTS:
            roleStr = 'Admin'
         elif user.principal in userRoleMap:
            roleStr = userRoleMap[user.principal]
         sshKey = ''
         sshKeyFile = GetKeyFilePath(user.principal)
         if os.path.exists(sshKeyFile):
            sshKey = ReadKeyFile(sshKeyFile)
         config = \
            [(USERNAME, user.principal),
             (DESCRIPTION, user.fullName), (POSIX_ID, user.id),
             (SSH_KEY, sshKey), (ROLE, roleStr)]
         configList.append(config)
      return configList

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      profileList = []
      for c in profileData:
         if dict(c)[USERNAME] in DEFAULT_ACCOUNTS:
            profileList.append(cls(
               [UserPolicy(True, UserPolicyOption(c)),
                PasswordPolicy(True,
                  DefaultAccountPasswordUnchangedOption([]))]
            ))
         else:
            profileList.append(cls(
               [UserPolicy(True, UserPolicyOption(c)),
                PasswordPolicy(True, UserInputPasswordConfigOption([]))]
            ))
      return profileList

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      if hostServices.earlyBoot:
         for task in taskList:
            _, taskObj = task
            log.info('[EARLYBOOT] Adding user: %s' % taskObj.id)
            runcommand.runcommand('%s %s -D -H -g %s' % (ADD_USER_CMD,
                                                         taskObj.id,
                                                         taskObj.description))
         return

      authMgr = hostServices.hostServiceInstance.content.authorizationManager
      rootFolder = hostServices.hostServiceInstance.content.rootFolder
      addPermissions = []
      for task in taskList:
         taskType, taskObj = task
         if taskType == DEL_USERS:
               RemoveUser(taskObj)

         elif taskType == ADD_USERS:
            CreatePosixUser(taskObj.id, password=taskObj.password,
                            description=taskObj.description)

         elif not hostServices.postBoot and taskType == MODIFY_USERS:
            si = hostServices.hostServiceInstance
            si.content.accountManager.UpdateUser(taskObj)

         elif taskType == ADD_PERMISSIONS:
            roleNameMap = RoleNameMap(hostServices)
            (user, role) = taskObj
            addPermissions.append(CreatePermission(user,
               roleNameMap[role]))

         elif taskType == DEL_PERMISSIONS:
            roleNameMap = RoleNameMap(hostServices)
            authMgr.RemoveEntityPermission(rootFolder, taskObj, False)

         elif taskType == ADD_AUTHKEYS:
            (user, key) = taskObj
            AddAuthKey(user, key.value)

         elif taskType == DEL_AUTHKEYS:
            sshKeyDir = GetKeyDirPath(taskObj)
            if taskObj != 'root' and os.path.exists(sshKeyDir):
               shutil.rmtree(sshKeyDir)
      if addPermissions:
         authMgr.SetEntityPermissions(rootFolder, addPermissions)
