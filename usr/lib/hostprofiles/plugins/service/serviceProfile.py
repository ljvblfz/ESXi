#!/usr/bin/python
# **********************************************************
# Copyright 2012-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile, FixedPolicyOption, Policy, log, \
                      ParameterMetadata, CreateLocalizedMessage, \
                      CreateLocalizedException, ProfileComplianceChecker, \
                      TASK_LIST_RES_OK
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SERVICE_SETTING
from pluginApi import FIREWALL_PORT_INBOUND, FIREWALL_PORT_OUTBOUND, FIREWALL_PORT_INOUT
from pluginApi import GetFirewallRuleById, IsFirewallBlockedByDefault
from pluginApi import CreateComplianceFailureValues, PARAM_NAME, POLICY_NAME, \
                      FindClassWithMatchingAttr

# TBD: We should get this from the pluginApi module, not directly from pyVmomi
from pyVmomi import Vim

MODULE_MSG_KEY_BASE = 'com.vmware.profile.serviceConfig'
SETTING_SERVICE_POLICY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingServiceStartupPolicy')
SETTING_SERVICE_RUNNING = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingServiceRunningStatus')
SERVICE_UPDATE_POLICY_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'updateServicePolicyFail')
SERVICE_START_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'startServiceFail')
SERVICE_UPDATE_RUNNING_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'updateServiceRunningFail')
SERVICE_STARTUP_POLICY_MISMATCH = '%s.%s' % (MODULE_MSG_KEY_BASE, 'startupPolicyMismatch')
SERVICE_STATUS_MISMATCH_WITH_ON_IN_OFF_POLICY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'statusMismatchWithOnInOffPolicy')
SERVICE_STATUS_MISMATCH_WITH_OFF_IN_OFF_POLICY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'statusMismatchWithOffInOffPolicy')
FIREWALL_DISABLED_FOR_SERVICE = '%s.%s' % (MODULE_MSG_KEY_BASE, 'firewallDisabledForService')

SERVICE_FILTER = [
'vmware-fdm',
'snmpd',
'lwsmd',
'vpxa',
]

TASK_SET_POLICY = 1
TASK_SET_RUNNING = 2

# The dictionary maps from serviceId to (ruleId list, port direction), where port
# direction is the direction of ports defined in the rule. If a rule contains only
# INBOUND (or OUTBOUND) ports, then it is tagged as FIREWALL_PORT_INBOUND (or
# FIREWALL_PORT_OUTBOUND). If a rule contains both INBOUND and OUTBOUND ports, it is
# tagged as FIREWALL_PORT_INOUT. If a service is "on", we first need to check if the
# firewall is blocked by default for the port direction. If true, we must make sure
# the rule is enabled in the firewall. If false, we don't need to check the rule.
# Note: The Validate method does not have access to hostInfo. Otherwise, we can
# compute the direction of each rule based on hostInfo.firewall.ruleset. As the rule
# configuration is static, so it is fine to predefine it.
SERVICE_FIREWALL = {
'ntpd'      : ( ('ntpClient',), FIREWALL_PORT_OUTBOUND ),
'TSM-SSH'   : ( ('sshServer',), FIREWALL_PORT_INBOUND ),
'lsassd'    : ( ('activeDirectoryAll',), FIREWALL_PORT_OUTBOUND ),
'lwiod'     : ( ('activeDirectoryAll',), FIREWALL_PORT_OUTBOUND ),
'netlogond' : ( ('activeDirectoryAll',), FIREWALL_PORT_OUTBOUND ),
'sfcbd-watchdog' : ( ('CIMHttpServer', 'CIMHttpsServer', 'CIMSLP'), FIREWALL_PORT_INOUT )
}

def _GetFirewallRuleDescription(serviceId):
   if serviceId in SERVICE_FIREWALL:
      return SERVICE_FIREWALL[serviceId]
   return (None, None)

def _GetServiceConfigFromProfile(profileInstance):
   serviceId = profileInstance.ServiceNamePolicy.policyOption.serviceId
   configPolicyOpt = profileInstance.ServiceConfigPolicy.policyOption
   startupPolicy = configPolicyOpt.STARTUP_POLICY
   runningStatus = None
   if startupPolicy == 'off':
      runningStatus = configPolicyOpt.status
   return (serviceId, startupPolicy, runningStatus)


class ServiceNamePolicyOption(FixedPolicyOption):
   """Policy Option type containing the service name.
   """
   paramMeta = [ ParameterMetadata('serviceId', 'string', False,
                    mappingAttributePath={'vim' : 'key'},
                    mappingIsKey={'vim' : True}) ]


class ServiceNamePolicy(Policy):
   """Define a policy for the service name.
   """
   possibleOptions = [ ServiceNamePolicyOption ]


class StartupPolicyOn(FixedPolicyOption):
   """Policy Option type for startup policy 'on'.
   """
   STARTUP_POLICY = "on"
   paramMeta = []

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'policy' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='on')
   }


class StartupPolicyAutomatic(FixedPolicyOption):
   """Policy Option type for startup policy 'automatic'.
   """
   STARTUP_POLICY = "automatic"
   paramMeta = []

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'policy' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='automatic')
   }


class StartupPolicyOff(FixedPolicyOption):
   """Policy Option type for startup policy 'off'.
   """
   STARTUP_POLICY = "off"
   paramMeta = [ ParameterMetadata('status', 'bool', False,
                    mappingAttributePath = { 'vim' : 'running' }) ]

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'policy' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='off')
   }


class ServiceConfigPolicy(Policy):
   """Define a policy for the service configuration.
   """
   possibleOptions = [ StartupPolicyOn, StartupPolicyAutomatic, StartupPolicyOff ]


class ServiceConfigChecker(ProfileComplianceChecker):
   """Checks whether the service configuration in the system is same with profile.
   """
   @classmethod
   def CheckProfileCompliance(cls, profiles, hostServices, profileData, parent):
      """Checks for profile compliance.
      """
      complianceFailures = []
      configInfo = hostServices.hostConfigInfo.config
      services = configInfo.service.service
      serviceDict = {}
      if services:
         for service in services:
            serviceDict[service.key] = (service.policy, service.running)

      for profInst in profiles:
         key, policy, running = _GetServiceConfigFromProfile(profInst)
         # ignore the services that are not supposed to be managed by HostProfile
         if key in SERVICE_FILTER:
            continue
         if key in serviceDict:
            if policy != serviceDict[key][0]:
               msgData = { 'serviceId' : key, 'startupPolicy': policy }
               complyFailMsg = CreateLocalizedMessage(None,
                                 SERVICE_STARTUP_POLICY_MISMATCH, msgData)
               profileValue = \
                  profInst.ServiceConfigPolicy.policyOption.__class__.__name__
               hostValue = FindClassWithMatchingAttr(
                  profInst.ServiceConfigPolicy.possibleOptions,
                  'STARTUP_POLICY', serviceDict[key][0])
               assert hostValue is not None

               comparisonValues = CreateComplianceFailureValues(
                  'ServiceConfigPolicy', POLICY_NAME, hostValue = hostValue,
                  profileValue = profileValue, profileInstance = key)
               complianceFailures.append((complyFailMsg, [comparisonValues]))

            if policy == 'off' and running != serviceDict[key][1]:
               msgData = { 'serviceId' : key, 'runningStatus': str(running) }
               if running:
                  complyFailMsg = CreateLocalizedMessage(None,
                     SERVICE_STATUS_MISMATCH_WITH_ON_IN_OFF_POLICY, msgData)
               else:
                  complyFailMsg = CreateLocalizedMessage(None,
                     SERVICE_STATUS_MISMATCH_WITH_OFF_IN_OFF_POLICY, msgData)
               comparisonValues = CreateComplianceFailureValues(
                  'status', PARAM_NAME, hostValue = serviceDict[key][1],
                  profileValue = running, profileInstance = key)
               complianceFailures.append((complyFailMsg, [comparisonValues]))
      return (len(complianceFailures) == 0, complianceFailures)


class ServiceConfigProfile(GenericProfile):
   """Host profile containing the service configuration.
   """
   singleton = False
   policies = [ ServiceNamePolicy, ServiceConfigPolicy ]
   complianceChecker = ServiceConfigChecker

   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SERVICE_SETTING

   # vCM Mapping data
   mappingBasePath = { 'vim': 'config.service.service' }

   @classmethod
   def _CreateProfileInst(cls, key, policy, running):
      """helper method that creates a service profile instance.
      """
      nameParam = [ 'serviceId', key ]
      namePolicy = ServiceNamePolicy(True, ServiceNamePolicyOption([nameParam]))

      if policy == 'on':
         policyOpt = StartupPolicyOn([])
      elif policy == 'automatic':
         policyOpt = StartupPolicyAutomatic([])
      else: # must be 'off'
         statusParam = [ 'status', running ]
         policyOpt = StartupPolicyOff([statusParam])
      configPolicy = ServiceConfigPolicy(True, policyOpt)

      policies = [ namePolicy, configPolicy ]
      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns a list of service profile instances.
      """
      configInfo = hostServices.hostConfigInfo.config
      services = configInfo.service.service

      serviceProfList = []
      if services:
         for service in services:
            # ignore the services that are not supposed to be managed by HostProfile
            if service.key in SERVICE_FILTER:
               continue
            serviceProfInst = cls._CreateProfileInst(service.key,
                              service.policy, service.running)
            serviceProfList.append(serviceProfInst)
      return serviceProfList

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verify if the service profile is valid or not.
      """
      retVal = True
      firewallProf = profileInstance.parentProfile.firewall
      serviceId, startupPolicy, runningStatus =\
         _GetServiceConfigFromProfile(profileInstance)

      # We check if the running state of the service is True or if the policy
      # is 'on' and if the corresponding firewall rule is enabled.
      if ((startupPolicy == "on" or runningStatus)
           and firewallProf and firewallProf.enabled):
         # make sure firewall configuration is correct
         ruleIdList, direction = _GetFirewallRuleDescription(serviceId)
         if ruleIdList and direction:
            if IsFirewallBlockedByDefault(firewallProf, direction):
               # the rules should be enabled for this service
               for ruleId in ruleIdList:
                  rule = GetFirewallRuleById(firewallProf.ruleset, ruleId)
                  if rule and not rule.policies[0].policyOption.ruleEnabled:
                     msgData = { 'serviceId' : serviceId, 'ruleId' : ruleId }
                     msg = CreateLocalizedMessage(
                        None, FIREWALL_DISABLED_FOR_SERVICE, msgData)
                     msg.SetRelatedPathInfo(
                        profile=profileInstance,
                        policy=profileInstance.ServiceConfigPolicy)
                     validationErrors.append(msg)
                     retVal = False
      return retVal

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for service configuration changes.
      """
      configInfo = hostServices.hostConfigInfo.config
      services = configInfo.service.service
      serviceDict = {}
      if services:
         for service in services:
            serviceDict[service.key] = (service.policy, service.running)

      for profInst in profileInstances:
         (key, policy, running) = _GetServiceConfigFromProfile(profInst)
         # ignore the services that are not supposed to be managed by HostProfile
         if key in SERVICE_FILTER:
            continue
         # only add task if the service is known on the host
         if key in serviceDict:
            if policy != serviceDict[key][0]:
               msgData = { 'serviceId' : key, 'startupPolicy' : policy }
               taskMsg = CreateLocalizedMessage(None, SETTING_SERVICE_POLICY, msgData)
               taskList.addTask(taskMsg, (TASK_SET_POLICY, key, policy))
            if running is not None and running != serviceDict[key][1]:
               msgData = { 'serviceId' : key, 'state' : running and 'on' or 'off' }
               taskMsg = CreateLocalizedMessage(None, SETTING_SERVICE_RUNNING, msgData)
               taskList.addTask(taskMsg, (TASK_SET_RUNNING, key, running))
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current service configuration.
      """
      serviceMgr = hostServices.hostSystemService.configManager.serviceSystem
      for op, key, value in taskList:
         if op == TASK_SET_POLICY:
            try:
               serviceMgr.UpdatePolicy(key, value)
            except Exception as err:
               log.warn('Failed to apply startup policy "%s" for service "%s": %s' % \
                        (value, key, str(err)))
               msgData = { 'serviceId' : key, 'startupPolicy' : value }
               raise CreateLocalizedException(None, SERVICE_UPDATE_POLICY_FAIL,
                                              msgData)

            try:
               if value == 'on':
                  serviceMgr.Start(key)
            except Exception as err:
               log.warn('Failed to start service %s: %s' % \
                        (key, str(err)))
               msgData = {'serviceId' : key}
               raise CreateLocalizedException(None, SERVICE_START_FAIL, msgData)
         elif op == TASK_SET_RUNNING:
            try:
               if value:
                  serviceMgr.Start(key)
               else:
                  serviceMgr.Stop(key)
            except Exception as err:
               log.warn('Failed to start or stop service "%s" : %s' % (key, str(err)))
               msgData = { 'serviceId' : key, 'runningStatus' : str(value) }
               raise CreateLocalizedException(None, SERVICE_UPDATE_RUNNING_FAIL, msgData)

