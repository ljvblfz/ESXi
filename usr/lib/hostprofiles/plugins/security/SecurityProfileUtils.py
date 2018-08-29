#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."


SECURITY_PREFIX = 'com.vmware.vim.profile.Profile.security.' \
                  'SecurityProfile.SecurityConfigProfile'
INVALID_ROLE = '%s.VerifyProfileError.InvalidRoleName.label' % SECURITY_PREFIX
INVALID_PERMISSION_PRINCIPAL = \
    '%s.VerifyProfileError.InvalidADPermissionPrincipal.label' % SECURITY_PREFIX

ROLE_PREFIX = 'com.vmware.vim.profile.Profile.security.RoleProfile.RoleProfile'
ROLE_CREATE_FAILURE = '%s.ApplyProfileError.CreateRoles.label' % ROLE_PREFIX
ROLE_REMOVE_FAILURE = '%s.ApplyProfileError.RemoveRoles.label' % ROLE_PREFIX

DUPLICATE_PRINCIPAL = 'com.vmware.vim.profile.host.ExecuteError.' \
                      'DuplicatePermissionPrincipal.label'

USERACCOUNT_BASE = 'com.vmware.vim.profile.Profile.security.' \
                   'UserAccountProfile.UserAccountProfile.'
DELETE_DEFAULT_ROLE = '%sVerifyProfileError.DeleteDefaultRole.label' % \
                       USERACCOUNT_BASE
DELETE_DEFAULT_ACCOUNT = '%sVerifyProfileError.DeleteDefaultAccount.label' % \
                         USERACCOUNT_BASE
EDIT_DEFAULT_USER_ROLE = '%sVerifyProfileError.EditDefaultUserRole.label' % \
                         USERACCOUNT_BASE
EDIT_BLACKLISTEDUSER = '%sVerifyProfileError.EditBlacklistedUser.label' % \
                       USERACCOUNT_BASE
PASSWORD_REQUIRED = '%sVerifyProfileError.PasswordRequired.label' % \
                    USERACCOUNT_BASE
ADPERMISSION_BASE = 'com.vmware.vim.profile.Profile.security.' \
                    'ADPermissionProfile.ActiveDirectoryPermissionProfile.'
INVALID_PRINCIPAL = '%sVerifyProfileError.InvalidPrincipal.label' % \
                    ADPERMISSION_BASE

def RoleIdMap(hostServices):
    '''
    Return a dictionary mapping roleId's to roleName's.
    '''
    authMgr = hostServices.hostServiceInstance.content.authorizationManager
    idMap = {}
    for r in authMgr.roleList:
        idMap[r.roleId] = r.name
    return idMap


def GetDefaultRoles(hostServices):
    '''
    Return a set of all the default roles, the roles with negative
    id's.
    '''
    idMap = RoleIdMap(hostServices)
    return set([v for k, v in idMap.items() if k < 0])


def RoleNameMap(hostServices):
    '''
    Return a dictionary mapping roleName's to roleId's
    '''
    roleIdMap = RoleIdMap(hostServices)
    return dict(zip(roleIdMap.values(), roleIdMap.keys()))
