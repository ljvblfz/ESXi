#!/usr/bin/python
# **********************************************************
# Copyright 2016 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from .RoleProfile import ROLE

from pluginApi.extensions import SimpleConfigProfile
from pyEngine.simpleConfigProfile import SimpleProfileChecker
from pluginApi import log, ParameterMetadata, ProfileComplianceChecker
from pluginApi import nodeputil

from .UserAccountProfile import getExistingUsers, getExistingPermissions, \
                                CreatePermission
from .SecurityProfileUtils import RoleIdMap, RoleNameMap

PRINCIPAL = 'principal'
IS_GROUP = 'isGroup'

advOptPrefix = 'Config.HostAgent.plugins.hostsvc.'

def ProcessData(hostServices, profileInstances, profileData):
    ''' Remove the esx admins group permission from the profile and host data.
    '''
    profInsts = profileInstances
    esxAdmins = GetEsxAdmins(hostServices)

    profInsts = []
    for p in profileInstances:
        opt = p.ActiveDirectoryPermissionProfilePolicy.policyOption
        parsedPrincipal = ParseADPrincipal(opt.principal)
        if not IsEsxAdmin(esxAdmins, parsedPrincipal):
            opt.principal = parsedPrincipal
            profInsts.append(p)

    profileData = [x for x in profileData \
                   if not IsEsxAdmin(esxAdmins, x[PRINCIPAL])]
    return (profInsts, profileData)

def NormalizeUserGroup(name):
    ''' Convert the user/group name to lowercase and replace
        spaces with ^.
    '''
    return name.lower().replace(' ', '^')

def NormalizeDomain(name):
    ''' Take the first part of the AD domain hostname and capitalize
        this.
    '''
    if '.' in name:
        name = name.split('.')[0]
    return name.upper()

def ParseADPrincipal(principal):
    ''' Convert the AD principal fullname to a standard format:
        DOMAIN\\user or DOMAIN\\group.

        Valid user provided principals are:
        DOMAIN\\user or DOMAIN\\group
        or
        user@DOMAIN or group@DOMAIN
    '''
    if '\\' in principal:
        index = principal.find('\\')
        userGroup = principal[index + 1:]
        domain = principal[:index]
    else:
        lastIndex = principal.rfind('@')
        userGroup = principal[:lastIndex]
        domain = principal[lastIndex + 1:]
    userGroup = NormalizeUserGroup(userGroup)
    domain = NormalizeDomain(domain)
    return '%s\\%s' % (domain, userGroup)

def IsEsxAdmin(esxAdmins, principal):
    ''' Check if a the given principal corresponds to an esx admin.
    '''
    return esxAdmins and esxAdmins in principal

def GetEsxAdmins(hostServices):
    ''' If the esx admins auto add advanced option is enabled return
        the esx admins group name.
    '''
    host = hostServices.hostSystemService
    opts = host.configManager.advancedOption.QueryOptions(advOptPrefix)
    esxAdminsGroup = ''
    esxAdminsGroupToAdd = False
    for opt in opts:
        if '%sesxAdminsGroupAutoAdd' % advOptPrefix == opt.key:
            esxAdminsGroupToAdd = opt.value
        elif '%sesxAdminsGroup' % advOptPrefix == opt.key:
            esxAdminsGroup = NormalizeUserGroup(opt.value)
    if esxAdminsGroupToAdd:
        return esxAdminsGroup
    return

def GetADPermissions(hostServices):
    ''' Get all the current AD Permissions on the system (All
        non local account permissions are AD Permissions).
    '''
    localUsers = [x.principal for x in getExistingUsers(hostServices)]
    permissions = getExistingPermissions(hostServices)
    return [p for p in permissions if p.principal not in localUsers]

class ADPermissionProfileChecker(SimpleProfileChecker):
    ''' Remove ignored principals from the profileData. esxi admins
        group gets a default Admin permission when a domain is joined
        that has esxi admins and the user used to join the domain is part
        of the esxi admins group. Therefore we don't want to have compliance
        failures relating to esxi admins.
    '''
    def CheckProfileCompliance(self, profileInstances,
                              hostServices, profileData, parent):
        profileInstances, profileData = ProcessData(hostServices,
                                                    profileInstances,
                                                    profileData)
        return SimpleProfileChecker.CheckProfileCompliance(self,
                                                           profileInstances,
                                                           hostServices,
                                                           profileData,
                                                           parent)

class ActiveDirectoryPermissionProfile(SimpleConfigProfile):
    ''' Host Profile implementation to capture AD users/groups.
    '''
    singleton = False
    isOptional = False
    idConfigKeys = [PRINCIPAL]
    parameters = [ParameterMetadata(ROLE, 'string', isOptional,
                    paramChecker=nodeputil.StringNonEmptyValidator()),
                  ParameterMetadata(PRINCIPAL, 'string', isOptional,
                    paramChecker=nodeputil.StringNonEmptyValidator()),
                  ParameterMetadata(IS_GROUP, 'boolean', isOptional)
                 ]
    @classmethod
    def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                         profileData, parent):
        profileInstances, profileData = ProcessData(hostServices,
                                                    profileInstances,
                                                    profileData)
        return super(ActiveDirectoryPermissionProfile, cls).GenerateTaskList(
            profileInstances, taskList, hostServices, profileData, parent)


    @classmethod
    def ExtractConfig(cls, hostServices):
        configList = []
        adPermissions = GetADPermissions(hostServices)
        roleIdMap = RoleIdMap(hostServices)
        for p in adPermissions:
            configList.append({
                ROLE : roleIdMap[p.roleId],
                PRINCIPAL : p.principal,
                IS_GROUP : p.group
            })
        return configList

    @classmethod
    def SetConfig(cls, configList, hostServices):
        # Return when reapply req. as we skip AD domain join when reapply req.
        if nodeputil.WillDVSReApply(hostServices):
            log.info('Skipping AD permission creation when reapply required.')
            return
        roleIdMap = RoleIdMap(hostServices)
        roleNameMap = RoleNameMap(hostServices)
        esxAdmins = GetEsxAdmins(hostServices)
        addPermissions = []
        currPermissions = { p.principal: p for p in
                                GetADPermissions(hostServices) }
        for config in configList:
            config[PRINCIPAL] = ParseADPrincipal(config[PRINCIPAL])

            roleId = roleNameMap[config[ROLE]]

            if config[PRINCIPAL] not in currPermissions:
                newPerm = CreatePermission(config[PRINCIPAL],
                                           roleId,
                                           config[IS_GROUP])
                addPermissions.append(newPerm)
            else:
                editP = currPermissions[config[PRINCIPAL]]
                permChanged = False
                if roleId != editP.roleId:
                    editP.roleId = roleId
                    permChanged = True
                if config[IS_GROUP] != editP.group:
                    editP.group = not editP.group
                    permChanged = True
                if permChanged:
                    addPermissions.append(editP)
                del currPermissions[config[PRINCIPAL]]

        authMgr = hostServices.hostServiceInstance.content.authorizationManager
        rootFolder = hostServices.hostServiceInstance.content.rootFolder
        for key, val in currPermissions.items():
            if not IsEsxAdmin(esxAdmins, key):
                authMgr.RemoveEntityPermission(rootFolder, key, val.group)
        if addPermissions:
            authMgr.SetEntityPermissions(rootFolder, addPermissions)

ActiveDirectoryPermissionProfile.complianceChecker = \
    ADPermissionProfileChecker(ActiveDirectoryPermissionProfile)
