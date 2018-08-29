#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import ipaddress

from .iscsiCommonUtils import *
from .iscsiPolicies import *
from hpCommon.utilities import VersionLessThan, VersionGreaterThanEqual
from pluginApi import PARAM_NAME, MESSAGE_KEY


# To support maxint of python2
try:
   sys.maxint
except AttributeError:
   sys.maxint = sys.maxsize

# Generate a IQN name
def IscsiGenerateIqn(hostServices, baseName=None):
   iqnString=''

   status, output = RunEsxCli(hostServices, GET_HOST_NAME_CMD, True)
   if status:
      return iqnString

   hostname=output['Host Name']
   randNum=random.randint(1, sys.maxint)
   if not baseName:
      baseName = 'iqn.1998-01.com.vmware'

   iqnString = '%s:%s-%x' % (baseName, hostname, randNum)

   IscsiLog(3, 'Generated IQN: %s' % (iqnString))

   return iqnString

# Rescan all adapters
def IscsiRescanAllAdapters(cls, clsParent, hostServices, configData, doRediscovery):
   for hba in configData.iscsiHbaList:
      if hba.enabled == True:
         if doRediscovery:
            RunEsxCli(hostServices, ISCSI_INITIATOR_CONFIG_DO_REDISCOVERY_CMD % { 'hba': hba.name}, True)

         RunEsxCli(hostServices, ISCSI_RESCAN_ADAPTER_LUNS % {'hba': hba.name}, True)

def CheckIscsiFirewall(profileInstances, hostServices, tasks):
   # We need firewall port to be opened if we have a dependent or (enabled) software-iscsi
   needFirewall = False
   for profInst in profileInstances:
      for subProfInst in profInst.subprofiles:
         if subProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_DEPENDENT:
            needFirewall = True
            break
         elif subProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_SOFTWARE:
            if not subProfInst.IscsiSoftwareInitiatorSelectionPolicy.policyOption.disabled:
               needFirewall = True
               break

   if not needFirewall:
      return True

   status, output = RunEsxCli(hostServices, FIREWALL_LIST_CMD, True)

   # If the command fails, most likely the esxfw module is not loaded,
   # in that case firewall is wide open
   if status != 0:
      return True

   # default to not enabled
   iscsiFirewallStatus = False

   # Check the iSCSI ruleset
   iscsiFirewallRuleset = [fw for fw in output if fw['Name'] == 'iSCSI']
   if iscsiFirewallRuleset:
      # If there is a rule for iSCSI, see if it is enabled
      iscsiFirewallStatus = iscsiFirewallRuleset[0]['Enabled']
      if iscsiFirewallStatus == True:
         return True

   # If we can't find the rule or if it is in disabled state, traffic is denied
   if tasks != None:
      # Since firewall ruleset is not associated with any adapter, setting
      # FirewallRuleSet as profileInstance.
      tasks.append(
         {'task': 'ISCSI_INITIATOR_CONFIG_OPEN_FIREWALL',
          'comparisonIdentifier': 'iSCSI',
          'complianceValueOption': PARAM_NAME,
          'hostValue': iscsiFirewallStatus,
          'profileValue': '',
          'profileInstance': 'FirewallRuleset'})

   return False

# Given the vmkernel chap option, return Policy Option name
def ChapTypeMapVmk2Policy(vmkChapTypeString):
   # Check if settable is false
   if vmkChapTypeString[2] == False:
      return 'SettingNotSupported'

   # Check if inherit is true
   if vmkChapTypeString[1] == True:
      return 'InheritFromParent'

   # If not inherit, get the policy option name of the vmkernel name,
   # including the 'default'
   for policyStr in chapPolicyOptionsMap:
      if chapPolicyOptionsMap[policyStr][0] == vmkChapTypeString[0].lower():
         return policyStr

   assert()
   return None

# Given the vmkernel digest option, return Policy Option name
def DigestMapVmk2Policy(vmkDigestString):
   # Check if settable is false
   if vmkDigestString[2] == False:
      return ('SettingNotSupported', vmkDigestString[0], \
              vmkDigestString[3], vmkDigestString[1])

   # First, check if inherit is true
   if vmkDigestString[1] == True:
      return ('InheritFromParent', vmkDigestString[0], \
              vmkDigestString[3], vmkDigestString[1])

   # If not inherit, get the policy option name of the vmkernel name,
   # including the 'default'
   for policyStr in digestPolicyOptionsMap:
      if digestPolicyOptionsMap[policyStr][0] == vmkDigestString[0].lower():
         return (policyStr, vmkDigestString[0], \
                 vmkDigestString[3], vmkDigestString[1])

   assert()
   return None

# Common attributes for HBA, SendTarget and Target
class IscsiCommon:
   def __init__(self, initiatorChapType,
                initiatorChapName, initiatorChapSecret, targetChapType, targetChapName,
                targetChapSecret, headerDigest, dataDigest, maxR2T, firstBurstLength,
                maxBurstLength, maxRecvSegLength, noopOutInterval, noopOutTimeout,
                recoveryTimeout, loginTimeout, delayedAck):
      self.initiatorChapType = initiatorChapType
      self.initiatorChapName = initiatorChapName
      self.initiatorChapSecret = initiatorChapSecret
      self.targetChapType = targetChapType
      self.targetChapName = targetChapName
      self.targetChapSecret = targetChapSecret

      self.params = {
         HEADER_DIGEST:       headerDigest,
         DATA_DIGEST:         dataDigest,
         MAX_R2T:             maxR2T,
         FIRST_BURST_LENGTH:  firstBurstLength,
         MAX_BURST_LENGTH:    maxBurstLength,
         MAX_RECV_SEG_LENGTH: maxRecvSegLength,
         NOOP_OUT_INTERVAL:   noopOutInterval,
         NOOP_OUT_TIMEOUT:    noopOutTimeout,
         RECOVERY_TIMEOUT:    recoveryTimeout,
         LOGIN_TIMEOUT:       loginTimeout,
         DELAYED_ACK:         delayedAck
      }

# Attributes for HBA
class IscsiHba(IscsiCommon):
   def __init__(self, hbaName, hbaType, enabled, caps, pciSlotInfo, macAddress, driverName,
                vendorId, iqn, alias, ipv4Address, ipv4Netmask, ipv4Gateway,
                arpRedirection, jumboFrame, initiatorChapType, initiatorChapName,
                initiatorChapSecret, targetChapType, targetChapName, targetChapSecret,
                headerDigest, dataDigest, maxR2T, firstBurstLength, maxBurstLength,
                maxRecvSegLength, noopOutInterval, noopOutTimeout, recoveryTimeout, loginTimeout,
                delayedAck, ipv4Config, ipv6Config, linklocalConfig, ipCaps):
      self.name = hbaName
      self.pciSlotInfo = pciSlotInfo
      self.macAddress = macAddress
      self.driverName = driverName
      self.vendorId = vendorId
      self.type = hbaType
      self.enabled = enabled
      self.caps = caps
      self.iqn = iqn
      self.alias = alias
      self.ipv4Config = ipv4Config
      self.ipv6Config = ipv6Config
      self.linklocalConfig = linklocalConfig
      self.ipCaps = ipCaps
      self.ipv4Address = ipv4Address
      self.ipv4Netmask = ipv4Netmask
      self.ipv4Gateway = ipv4Gateway
      self.ipv6Address = ''
      self.ipv6Prefix = 0
      self.arpRedirection = arpRedirection
      self.jumboFrame = jumboFrame
      self.sendTargetDiscoveryList = []
      self.staticTargetList = []
      self.discoveredTargetList = []
      self.boundVnicList = []
      IscsiCommon.__init__(self, initiatorChapType,
                initiatorChapName, initiatorChapSecret, targetChapType, targetChapName,
                targetChapSecret, headerDigest, dataDigest, maxR2T, firstBurstLength,
                maxBurstLength, maxRecvSegLength, noopOutInterval, noopOutTimeout,
                recoveryTimeout, loginTimeout, delayedAck)

   def GetName(self):
      if self.name == SOFTWARE_ISCSI_ADAPTER_PLACE_HOLDER:
         return SOFTWARE_ISCSI_ADAPTER_DESCRIPTION
      return self.name

   # Given 2 same type distinct objects, method copies the contents from source to dest
   def Copy(self, srcObj):
      for __attr in dir(self):
         try:
            setattr(self, __attr, getattr(srcObj, __attr))
         except AttributeError:
            # Ignore __weakref__ in python3
            pass

# Helper routine to print the hba selections for the given list of profile instances
def PrintHbaSelections(profileInstances):
   for profInst in profileInstances:
      PrintProfileInstances([profInst])
      print('Selected HBA Instances for' + profInst.__class__.__name__)
      for hba in profInst.selectedHbaInstances:
         print("\t" + hba.name)

def UpdateIscsiHbaData(hostServices, configData, driverName, pciSlotInfo, macAddress):
   if driverName:
      hbaInstances = FindIscsiHbaByDriverName(configData, driverName, macAddress)
      assert(len(hbaInstances) == 1)

      hbaList = GetIscsiHbaList(hostServices,
                                filters = {'driverName' : driverName,
                                           'macAddress' : macAddress
                                           }
                               )
      assert(len(hbaList) == 1)

      hbaInstances[0].Copy(hbaList[0])
   elif pciSlotInfo:
      assert()
      hbaInstances = FindIscsiHbaByPciSlotInfo(configData, pciSlotInfo, macAddress)
   else:
      assert()

def AssignIscsiHbaSelection(cls, parent, hostServices, configData, validationErrors):

   #EnterDebugger()

   # We actually need to walk thru all the profile instances and assign/verify the HBA.
   subProfs = parent.subprofiles

   # initialize the buckets
   workingProfileInstances = dict([('ByPciSlotInfo', []),
                                   ('ByDriverName', []),
                                   ('ByVendorId', []),
                                   ('WithMacAddress', []),
                                  ])

   # Categorize the profiles so we can prioritize the assignments
   for profInst in subProfs:
      profInst.selectedHbaInstances = []

      # Software iscsi is always by driver name
      if profInst.iscsiProfileType == ISCSI_HBA_PROFILE_SOFTWARE:
         workingProfileInstances['ByDriverName'].append(profInst)
      else:
         # Let's see what is the selection policy for others
         hbaSelectionPolicyInst = profInst.IscsiHardwareInitiatorSelectionPolicy

         # Make sure we atleast have empty macAddress param
         if (not hasattr(hbaSelectionPolicyInst.policyOption, 'macAddress')) or \
            hbaSelectionPolicyInst.policyOption.macAddress == None:
            IscsiUpdatePolicyOptParam(hbaSelectionPolicyInst.policyOption, 'macAddress', '')

         # Put them is appropriate bucket
         if len(hbaSelectionPolicyInst.policyOption.macAddress) > 0 :
            workingProfileInstances['WithMacAddress'].append(profInst)
         elif isinstance(hbaSelectionPolicyInst.policyOption, IscsiInitiatorSelectionMatchByPciSlotInfo):
            workingProfileInstances['ByPciSlotInfo'].append(profInst)
         elif isinstance(hbaSelectionPolicyInst.policyOption, IscsiInitiatorSelectionMatchByDriverName):
            workingProfileInstances['ByDriverName'].append(profInst)
         elif isinstance(hbaSelectionPolicyInst.policyOption, IscsiInitiatorSelectionMatchByVendorId):
            workingProfileInstances['ByVendorId'].append(profInst)

   # Verify and Assign hba's for profile instances that have already have mac Address
   for profInst in workingProfileInstances['WithMacAddress']:
      hbaSelectionPolicyInst = profInst.IscsiHardwareInitiatorSelectionPolicy
      (result, hbaInstances) = FindIscsiHbaBySelectionPolicy(configData,
                                                             parent,
                                                             subProfs,
                                                             profInst,
                                                             True)
      if result != ISCSI_HBA_SELECTION_OK or \
         len(hbaInstances) != 1 or \
         hbaInstances[0].type != profInst.iscsiProfileType:
         IscsiLog(3,
                  'AssignIscsiHbaSelection(WithMacAddress): Failed to assign HBA for %s:%s' \
                  %(profInst.__class__.__name__, id(profInst)))
         continue

      profInst.selectedHbaInstances = hbaInstances
      IscsiUpdatePolicyOptParam(profInst.IscsiHardwareInitiatorSelectionPolicy.policyOption,
                                'macAddress',
                                hbaInstances[0].macAddress)

   # Assign hba's for profile instances that have PCI info policyOption
   for profInst in workingProfileInstances['ByPciSlotInfo']:
      hbaSelectionPolicyInst = profInst.IscsiHardwareInitiatorSelectionPolicy
      (result, hbaInstances) = FindIscsiHbaBySelectionPolicy(configData, parent, subProfs, profInst, False)

      if result != ISCSI_HBA_SELECTION_OK or \
         len(hbaInstances) != 1 or \
         hbaInstances[0].type != profInst.iscsiProfileType:
         IscsiLog(3,
                  'AssignIscsiHbaSelection(ByPciSlotInfo): Failed to assign HBA for %s:%s' \
                  %(profInst.__class__.__name__, id(profInst)))
         continue

      # Check if the hbaInstance is already selected for any other profile instances
      if hbaInstances in [selectedHbaInst for selectedHbaInst in [p.selectedHbaInstances for p in subProfs]]:
         IscsiLog(3,
                  'AssignIscsiHbaSelection(ByPciSlotInfo): Failed to assign HBA for ' + \
                  '%s:%s -- duplicate assignment found' \
                  %(profInst.__class__.__name__, id(profInst)))
         continue

      profInst.selectedHbaInstances = hbaInstances
      IscsiUpdatePolicyOptParam(profInst.IscsiHardwareInitiatorSelectionPolicy.policyOption,
                                'macAddress',
                                hbaInstances[0].macAddress)

   # Assign the hba's for the ones without MAC address
   for profInst in workingProfileInstances['ByDriverName']+workingProfileInstances['ByVendorId']:
      (result, hbaInstances) = FindIscsiHbaBySelectionPolicy(configData, parent, subProfs, profInst, False)
      if result != ISCSI_HBA_SELECTION_OK:
         IscsiLog(3,
                  'AssignIscsiHbaSelection(ByDriverName or ByVendorId): Failed to assign HBA ' + \
                  'for %s:%s, result %d' %(profInst.__class__.__name__, id(profInst), result))
         continue

      for hbaInst in hbaInstances:
         if hbaInst.type == profInst.iscsiProfileType and \
            [hbaInst] not in [selectedHbaInst for selectedHbaInst in [p.selectedHbaInstances for p in subProfs]]:
            profInst.selectedHbaInstances = [hbaInst]
            break

      # make sure one and only one instance
      if len(profInst.selectedHbaInstances) != 1:
         IscsiLog(3,
                  'AssignIscsiHbaSelection(ByDriverName or ByVendorId): Failed to assign HBA for ' + \
                  '%s:%s -- zero or multiple selections' %(profInst.__class__.__name__, id(profInst)))
         continue

      # For non-software iscsi, update the profile with macAddress association
      if profInst.iscsiProfileType != ISCSI_HBA_PROFILE_SOFTWARE:
         IscsiUpdatePolicyOptParam(profInst.IscsiHardwareInitiatorSelectionPolicy.policyOption,
                                   'macAddress',
                                   profInst.selectedHbaInstances[0].macAddress)

   return True

def ProfilesToHba(profileInstances, configData, parent, complianceErrors=None):
   #EnterDebugger()
   failed = False

   for profInst in profileInstances:
      (result, hbaInstances) = FindIscsiHbaBySelectionPolicy(configData,
                                                             parent,
                                                             profileInstances,
                                                             profInst,
                                                             True)

      if result == ISCSI_HBA_SELECTION_OK:
         profInst.selectedHbaInstances = hbaInstances
      else:
         #EnterDebugger()
         failed = True
         if complianceErrors != None:
            IscsiCreateLocalizedMessage(profInst,
                                        ISCSI_ERROR_NO_HBA_SELECTED,
                                        {'profKey': profInst.GetKey()},
                                        complianceErrors)
         IscsiLog(3, 'Did not find any iSCSI HBA for profile instance %s:%s, error %d' % \
            (profInst.__class__.__name__, id(profInst), result), 'ProfilesToHba:')

   return failed == False

def SubProfilesToHba(profileInstances, configData, parent, complianceErrors=None):
   #EnterDebugger()
   failed = False

   for profInst in profileInstances:
      result = ProfilesToHba(profInst.subprofiles, configData, profInst, complianceErrors)
      if result is False and failed is False:
         failed = True

   return failed == False

def FindIscsiHbaByHbaName(configData, hbaName):
   iscsiHbaList = configData.iscsiHbaList

   for hbaInst in iscsiHbaList:
      if hbaInst.name == hbaName:
         return hbaInst

   return None

def ParsePCISbdfString(sbdfString):
   """ Parses PCI SBDF string of form seg:bus:dev.func or bus:dev.func
       to get seg, bus, dev, func values.
       If given SBDF string does not contain seg (i.e string is just
       b:d.f), then seg = 0 is assumed.
   """
   sb = sbdfString.split(':')
   if len(sb) == 2:
      s = 0
      b = int(sb[0], 16)
      df = sb[1].split('.')
      d, f =  [int(x, 16) for x in df]
   elif len(sb) == 3:
      df = sb[2].split('.')
      s, b = [int(x, 16) for x in sb[0:2]]
      d, f =  [int(x, 16) for x in df]
   else:
      return (0, 0, 0, 0)

   return (s, b, d, f)

def MatchPCISbdfStrings(sbdfString1, sbdfString2):
   if sbdfString1 == None or sbdfString2 == None:
      return False

   sbdf1 = ParsePCISbdfString(sbdfString1)
   sbdf2 = ParsePCISbdfString(sbdfString2)

   for i,val in enumerate(sbdf1):
      if val != sbdf2[i]:
         return False

   return True

def FindIscsiHbaByPciSlotInfo(configData, pciSlotInfo, macAddress):
   hbaInstances = []
   iscsiHbaList = configData.iscsiHbaList

   for hbaInst in iscsiHbaList:
      if MatchPCISbdfStrings(hbaInst.pciSlotInfo, pciSlotInfo) == True and \
         (len(macAddress) == 0 or hbaInst.macAddress == macAddress):
         hbaInstances.append(hbaInst)

   return hbaInstances

def FindIscsiHbaByDriverName(configData, driverName, macAddress):
   hbaInstances = []
   iscsiHbaList = configData.iscsiHbaList

   for hbaInst in iscsiHbaList:
      if hbaInst.driverName == driverName and \
         (macAddress == None or len(macAddress) == 0 or hbaInst.macAddress == macAddress) :
         hbaInstances.append(hbaInst)

   return hbaInstances

def FindIscsiHbaByVendorId(configData, vendorId, macAddress):
   hbaInstances = []
   iscsiHbaList = configData.iscsiHbaList

   for hbaInst in iscsiHbaList:
      if hbaInst.vendorId == vendorId and \
         (len(macAddress) == 0 or hbaInst.macAddress == macAddress):
         hbaInstances.append(hbaInst)

   return hbaInstances

def FindIscsiHbaBySelectionPolicy(configData, parent, profInstances, curProfInst, macRequired):

   # Profile instance has to be one of software / dependent / independent
   assert ((curProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_SOFTWARE or \
           curProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_DEPENDENT or \
           curProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_INDEPENDENT)), \
          'Invalid Profile Instance passed'

   hbaInstances = []

   if curProfInst.iscsiProfileType == ISCSI_HBA_PROFILE_SOFTWARE:
      policyInst = curProfInst.IscsiSoftwareInitiatorSelectionPolicy
      hbaInstances = FindIscsiHbaByDriverName(configData, 'iscsi_vmk', None)
   else:
      policyInst = curProfInst.IscsiHardwareInitiatorSelectionPolicy
      # If MAC Address is required but not present, return with failure
      if macRequired and \
         (not hasattr(policyInst.policyOption, 'macAddress') or \
          policyInst.policyOption.macAddress is None or \
          len(policyInst.policyOption.macAddress) == 0):
         return (ISCSI_HBA_NO_MACADDRESS, [])
      elif isinstance(policyInst.policyOption, IscsiInitiatorSelectionMatchByPciSlotInfo):
         hbaInstances = FindIscsiHbaByPciSlotInfo(configData,
                                                  policyInst.policyOption.pciSlotInfo,
                                                  policyInst.policyOption.macAddress)

      elif isinstance(policyInst.policyOption, IscsiInitiatorSelectionMatchByDriverName):
         hbaInstances = FindIscsiHbaByDriverName(configData,
                                                 policyInst.policyOption.driverName,
                                                 policyInst.policyOption.macAddress)

      elif isinstance(policyInst.policyOption, IscsiInitiatorSelectionMatchByVendorId):
         hbaInstances = FindIscsiHbaByVendorId(configData,
                                               policyInst.policyOption.vendorId,
                                               policyInst.policyOption.macAddress)
      else:
         assert()

   if len(hbaInstances) == 0:
      return (ISCSI_HBA_NOTFOUND_AT_ADDRESS, [])
   elif hbaInstances in [selectedHbaInst for selectedHbaInst in
         [p.selectedHbaInstances for p in profInstances if p != curProfInst]]:
      return (ISCSI_HBA_ALREADY_ASSIGNED, [])
   else:
      return (ISCSI_HBA_SELECTION_OK, hbaInstances)

def CreateInitiatorConfigTaskFromConfigData(profileVer, hbaType, currHbaData, newHbaData, forGtl):
   tasks = []

   if Compare(newHbaData.iqn, currHbaData.iqn):
      tasks.append(
         {'task': 'ISCSI_INITIATOR_CONFIG_IQN_SET',
          'iqn' : newHbaData.iqn,
          'hba' : newHbaData.name,
          'comparisonIdentifier' : 'Iqn',
          'hostValue' : currHbaData.iqn,
          'profileValue' : newHbaData.iqn,
          'complianceValueOption' : PARAM_NAME
         })

   if Compare(newHbaData.alias, currHbaData.alias):
      tasks.append(
         {'task': 'ISCSI_INITIATOR_CONFIG_ALIAS_SET',
          'alias' : newHbaData.alias,
          'hba' : newHbaData.name,
          'comparisonIdentifier' : 'Alias',
          'hostValue' : currHbaData.alias,
          'profileValue' : newHbaData.alias,
          'complianceValueOption' : PARAM_NAME
         })

   # ipv4Address, ipv4Netmask, ipv4Gateway are obsolete from release 2015.
   # These are here for compatibility with older releases.
   if hbaType == ISCSI_HBA_PROFILE_INDEPENDENT and VersionLessThan(profileVer, '5.1.0'):
      assert(currHbaData.ipv4Config is not None)
      if currHbaData.ipv4Config.useDhcp == True or \
         currHbaData.ipv4Config.enabled == False or \
         Compare(newHbaData.ipv4Address, currHbaData.ipv4Address) or \
         Compare(newHbaData.ipv4Netmask, currHbaData.ipv4Netmask) or \
         Compare(newHbaData.ipv4Gateway, currHbaData.ipv4Gateway):
         cmdStr = ''
         if currHbaData.ipv4Config.enabled == False:
            cmdStr += '--enable 1 '
         if currHbaData.ipv4Config.useDhcp == True:
            cmdStr += '--enable-dhcpv4 0 '
         if Compare(newHbaData.ipv4Address, currHbaData.ipv4Address):
            cmdStr += '--ip ' + newHbaData.ipv4Address + ' '
         if Compare(newHbaData.ipv4Netmask, currHbaData.ipv4Netmask):
            cmdStr += '--subnet ' + newHbaData.ipv4Netmask + ' '
         if Compare(newHbaData.ipv4Gateway, currHbaData.ipv4Gateway) and \
            ipaddress.ip_address('0.0.0.0') != \
               ipaddress.ip_address(newHbaData.ipv4Gateway):
            cmdStr += '--gateway ' + newHbaData.ipv4Gateway

         ipConfig = {'task': 'ISCSI_INITIATOR_CONFIG_IPCONFIG_SET',
                     'cmd' : cmdStr,
                     'hba' : newHbaData.name}
         tasks.append(ipConfig)

   # Process ipv4Config
   if hbaType == ISCSI_HBA_PROFILE_INDEPENDENT and \
      VersionGreaterThanEqual(profileVer, '5.1.0'):

      # Creating aliases to variable name length.
      # To fit into 80 chars per line standard.
      newIp4 = newHbaData.ipv4Config
      curIp4 = currHbaData.ipv4Config
      # Check if user wants to ignore IPv4 configuration
      if newIp4.ignore == True:
         pass # dont do anything
      # Check if user wants to disable IPv4
      elif newIp4.enabled == False:
         if curIp4.enabled == True:
            cmdStr = '--enable 0'
            tasks.append(
               {'task': 'ISCSI_INITIATOR_CONFIG_IPCONFIG_SET',
                'cmd' : cmdStr,
                'hba' : newHbaData.name,
                'comparisonIdentifier' : 'Ipv4Cofig',
                'hostValue' : curIp4.enabled,
                'profileValue' : newIp4.enabled,
                'complianceValueOption' : PARAM_NAME
               })

      # Check if user wants to use DHCP
      elif newIp4.useDhcp == True:
         if curIp4.enabled == False or \
            Compare(newIp4.useDhcp, curIp4.useDhcp):
            cmdStr = ''
            if curIp4.enabled == False:
               cmdStr += '--enable 1 '
            if Compare(newIp4.useDhcp, curIp4.useDhcp):
               cmdStr += '--enable-dhcpv4 1'
            tasks.append(
               {'task': 'ISCSI_INITIATOR_CONFIG_IPCONFIG_SET',
                'cmd' : cmdStr,
                'hba' : newHbaData.name,
                'comparisonIdentifier' : 'Ipv4Cofig',
                'hostValue' : curIp4.useDhcp,
                'profileValue' : newIp4.useDhcp,
                'complianceValueOption' : PARAM_NAME
              })
      # For manual configuration dhcp should be set off
      else:
         if curIp4.useDhcp == True or \
            curIp4.enabled == False or \
            Compare(newIp4.address, curIp4.address) or \
            Compare(newIp4.subnet, curIp4.subnet) or \
            Compare(newIp4.gateway, curIp4.gateway):
            cmdStr = ''
            hostValue = ''
            profileValue = ''
            if curIp4.enabled == False:
               cmdStr += '--enable 1 '
            if curIp4.useDhcp == True:
               cmdStr += '--enable-dhcpv4 0 '
            if Compare(newIp4.address, curIp4.address):
               cmdStr += '--ip ' + newIp4.address + ' '
               hostValue += 'ipv4:%s' % (curIp4.address)
               profileValue += 'ipv4:%s' % (newIp4.address)
            if Compare(newIp4.subnet, curIp4.subnet):
               cmdStr += '--subnet ' + newIp4.subnet + ' '
               hostValue += ' subnet:%s' % (curIp4.subnet)
               profileValue += ' subnet:%s' % (newIp4.subnet)
            if Compare(newIp4.gateway, curIp4.gateway):
               cmdStr += '--gateway ' + newIp4.gateway
               hostValue += ' gateway:%s' % (curIp4.gateway)
               profileValue += ' gateway:%s' % (newIp4.gateway)

            newConfig = {'task': 'ISCSI_INITIATOR_CONFIG_IPCONFIG_SET',
                         'cmd' : cmdStr,
                         'hba' : newHbaData.name,
                         'comparisonIdentifier' : 'Ipv4Cofig',
                         'hostValue' : hostValue,
                         'profileValue' : profileValue,
                         'complianceValueOption' : PARAM_NAME
                         }
            tasks.append(newConfig)

   # Process IPv6 and link-local config only if ipv6 is supported by that adapter
   if hbaType == ISCSI_HBA_PROFILE_INDEPENDENT and \
      VersionGreaterThanEqual(profileVer, '5.1.0') and \
      currHbaData.ipv6Config.supported == True:
      configSetCmdStr = ''
      addressSetCmdStr = ''
      hostValue = ''
      profileValue = ''
      # Creating aliases to reduce variable name length.
      # To fit into 80 char per line standard.
      curIp6 = currHbaData.ipv6Config
      newIp6 = newHbaData.ipv6Config
      # check if IPv6 is being ignored
      if newIp6.ignore == True:
         pass # do nothing
      # check if IPv6 is being disabled
      elif newIp6.enabled == False:
         if curIp6.enabled == True:
            configSetCmdStr += '--enable 0 '
            hostValue += 'ipv6ConfigEnabled:%s' % (curIp6.enabled)
            profileValue += 'ipv6ConfigEnabled:%s' % (newIp6.enabled)

      # check if user wants to enable routerAdv
      elif newIp6.useRouterAdv == True:
         if curIp6.enabled == False or \
            curIp6.useRouterAdv == False:
            if curIp6.enabled == False:
               configSetCmdStr += '--enable 1 '
            if curIp6.useRouterAdv == False:
               configSetCmdStr += '--enable-router-advertisement 1 '
            hostValue += ' ipv6ConfigUseRouterAdv:%s' % (curIp6.useRouterAdv)
            profileValue += 'ipv6ConfigUseRouterAdv:%s' % (newIp6.useRouterAdv)

      # manual configuration
      else:
         if curIp6.useRouterAdv == True or \
            curIp6.enabled == False or \
            Compare(newIp6.gateway6, curIp6.gateway6):
            if curIp6.enabled == False:
               configSetCmdStr += '--enable 1 '
            if curIp6.useRouterAdv == True:
               configSetCmdStr += '--enable-router-advertisement 0 '
            if Compare(newIp6.gateway6, curIp6.gateway6):
               configSetCmdStr += '--gateway6 ' + newIp6.gateway6 + ' '

         if Compare(newIp6.ipv6AddressModified, curIp6.ipv6AddressModified):
            # Removes all existing routable addresses and then add the new one
            if newIp6.ipv6AddressOriginal == "":
               # remove all addresses
               addressSetCmdStr += '-r'
            else:
               ipv6List = newIp6.ipv6AddressOriginal.split(",")
               # remove all existing and add the new addresses specified by user
               addressSetCmdStr += '-r '
               for x in ipv6List:
                  addressSetCmdStr += '-a ' + x + ' '
            profileValue += 'ipv6:%s' % (newIp6.ipv6AddressOriginal)
            hostValue += 'ipv6:%s' % (curIp6.ipv6AddressOriginal)
         if Compare(newIp6.gateway6, curIp6.gateway6):
            hostValue += ' gateway6:%s' % (curIp6.gateway6)
            profileValue += ' gateway6:%s' % (newIp6.gateway6)

      # Process linklocal Configuration
      # Don't process link-local configuration if IPv6 is being disabled
      if newIp4.enabled == True:

         #Creating aliases so that variable name can be reduced.
         # To fit into 80 chars per line.
         newConf = newHbaData.linklocalConfig
         curConf = currHbaData.linklocalConfig
         # check if user wants to ignore link-local configuration
         if newConf.ignore == True:
            pass # don't do anything
         # check if user wants to enable link local auto configuration
         elif newConf.useLinklocalAutoConf == True:
            if curConf.useLinklocalAutoConf == False:
               configSetCmdStr += '--enable-linklocal-autoconfiguration 1 '
               hostValue += ' useLinklocalAutoConf:%s' % \
                            (curConf.useLinklocalAutoConf)
               profileValue += ' useLinklocalAutoConf:%s' % \
                               (newConf.useLinklocalAutoConf)

         # manual configuration of linklocal address
         else:
            if curConf.useLinklocalAutoConf == True or \
               Compare(newConf.linklocalAddr, curConf.linklocalAddr):
               if curConf.useLinklocalAutoConf == True:
                  configSetCmdStr += '--enable-linklocal-autoconfiguration 0 '

               if Compare(newConf.linklocalAddr, curConf.linklocalAddr):
                  addressSetCmdStr += '-a ' + newConf.linklocalAddr + '/' + '64'
                  hostValue += ' LinklocalAddr:%s' % (curConf.linklocalAddr)
                  profileValue += 'LinklocalAddr:%s' % (newConf.linklocalAddr)
      else:
         IscsiLog(3,
            'skipping linklocal configuration for %s as IPv6 is being disabled'
            % (newHbaData.name))

      # append the task
      if len(configSetCmdStr) > 0:
         tasks.append(
            {'task': 'ISCSI_INITIATOR_CONFIG_IPV6CONFIG_SET',
             'cmd' : configSetCmdStr,
             'hba' : newHbaData.name,
             'comparisonIdentifier' : 'Ipv6Cofig',
             'hostValue' : hostValue,
             'profileValue' : profileValue,
             'complianceValueOption' : PARAM_NAME

            })
      if len(addressSetCmdStr) > 0:
         tasks.append(
            {'task': 'ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_ADD',
             'cmd' : addressSetCmdStr,
             'hba' : newHbaData.name,
             'comparisonIdentifier' : 'Ipv6Config',
             'hostValue' : hostValue,
             'profileValue' : profileValue,
             'complianceValueOption' : PARAM_NAME
            })

   if Compare(newHbaData.arpRedirection, currHbaData.arpRedirection):
      tasks.append(
         {'task': 'ISCSI_INITIATOR_CONFIG_ARPRED_SET',
          'arpRedirection' : int(newHbaData.arpRedirection),
          'hba' : newHbaData.name,
          'comparisonIdentifier' : 'ArpRedirection',
          'hostValue' : currHbaData.arpRedirection,
          'profileValue' : newHbaData.arpRedirection,
          'complianceValueOption' : PARAM_NAME
         })

   if Compare(newHbaData.jumboFrame, currHbaData.jumboFrame):
      tasks.append(
         {'task': 'ISCSI_INITIATOR_CONFIG_MTU_SET',
          'jumboFrame' : newHbaData.jumboFrame,
          'hba' : newHbaData.name,
          'comparisonIdentifier' : 'JumboFrame',
          'hostValue' : currHbaData.jumboFrame,
          'profileValue' : newHbaData.jumboFrame,
          'complianceValueOption' : PARAM_NAME
         })

   # Update the parameters
   authCmd = {
      'task':'ISCSI_INITIATOR_CONFIG_CHAP_SET',
      'hba': newHbaData.name,
   }

   parmCmd = {
      'task' : 'ISCSI_INITIATOR_CONFIG_PARM_SET',
      'hba' : newHbaData.name,
   }

   tasks.extend(CreateConfigTaskForParams(currHbaData, currHbaData,
      newHbaData, authCmd, parmCmd, False, forGtl))

   if len(tasks) > 0:
      tasks.append(
         {'task' : 'ISCSI_INITIATOR_CONFIG_DO_REDISCOVERY',
          'hba': newHbaData.name,
          'noCC': True,
          'failOK': True
         })

   return tasks

def GetIscsiHbaList(hostServices, filters=None):
   iscsiHbaList = []

   swiscsiHbaFound = False

   IscsiLog(3, 'Start Gathering HBA info')

   # Get list of iSCSI adapters
   status, cliOut = GetHostData(hostServices,
                       ISCSI_STORAGE_CORE_ADAPTER_LIST_CMD)

   storageHbaList = dict([(hba['HBA Name'],hba['Driver']) for hba in cliOut])

   # Get list of iSCSI adapters
   status, tmpIscsiHbaList = GetHostData(hostServices,
                             ISCSI_INITIATOR_CONFIG_ADAPTER_LIST_CMD)

   # filter the HBA's for passed in driver
   if filters is not None:
      tmpIscsiHbaList = [hba for hba in tmpIscsiHbaList \
         if storageHbaList[hba['Adapter']] == filters['driverName']]

   # Get list of PCI devices
   status, pciList = RunEsxCli(hostServices, HARDWARE_PCI_LIST_CMD)

   # Gather PNP List
   status, pnpList = RunEsxCli(hostServices, ISCSI_INITIATOR_CONFIG_PNP_LIST_CMD)

   # Gather iSCSI adapter details
   for iscsiHba in tmpIscsiHbaList:
      hbaName = iscsiHba['Adapter']
      hbaCapabilities = dict()

      # get the adapter params
      status, hbaParams = GetHostData(hostServices,
                          ISCSI_INITIATOR_CONFIG_PARM_GET_CMD,
                          hbaName)
      # construct a dict with only required fields
      hbaCurrentParams=dict([(p['Name'], (p['Current'], p['Inherit'], p['Settable'], p['Default'])) for p in hbaParams])

      # get the hba uni-directional chap settings
      status, hbaChapParams = GetHostData(hostServices,
                                 ISCSI_INITIATOR_CONFIG_CHAP_UNI_GET_CMD,
                                 hbaName)
      # get the hba bi-directional chap settings
      status, hbaMutualChapParams = GetHostData(hostServices,
                                       ISCSI_INITIATOR_CONFIG_CHAP_MUTUAL_GET_CMD,
                                       hbaName)
      # get the hba capabilities and other info
      status, hbaCaps = GetHostData(hostServices,
                        ISCSI_INITIATOR_CONFIG_GET_CAPS_CMD,
                        hbaName)

      status, hbaInfo = GetHostData(hostServices,
                        ISCSI_INITIATOR_CONFIG_GET_CMD,
                        hbaName)
      pciAddress = None
      macAddress = None
      vendorName = None
      hbaIpv4Config = Ipv4Config()
      hbaIpv6Config = Ipv6Config()
      hbaLinklocalConfig = LinklocalConfig()
      hbaIpCaps = IpCapabilties()
      hbaIpv4Address = None
      hbaIpv4Netmask = None
      hbaIpv4Gateway = None
      arpRedirection = None
      jumboFrame = None

      # get the hba IQN and alias
      hbaIqn = hbaInfo[0]['Name']
      hbaAlias = hbaInfo[0]['Alias']

      # construct the hba capabilities
      hbaCapabilities['mutualChapSupported'] = \
         hbaCaps[0]['Mutual Authentication Supported']

      hbaCapabilities['uniChapSupported'] = \
         hbaCaps[0]['CHAP Authorization Supported']

      hbaCapabilities['mtuSettable'] = \
         hbaCaps[0]['MTU Settable']

      hbaCapabilities['arpRedirectSettable'] = \
         hbaCaps[0]['ARP Redirect Settable']

      hbaCapabilities['targetLevelUniAuthSupported'] = \
         hbaCaps[0]['Target Level Authentication Supported']

      hbaCapabilities['targetLevelMutualAuthSupported'] = \
         hbaCaps[0]['Target Level Mutual Authentication Supported']

      hbaCapabilities['inheritanceSupported'] = \
         hbaCaps[0]['Inheritance Supported']

      supportedChapLevels = {
         'hba':
            {
               'uni':
                  {
                     'SettingNotSupported'                  : hbaCapabilities['uniChapSupported'],
                     'DoNotUseChap'                         : True,
                     'DoNotUseChapUnlessRequiredByTarget'   : hbaCapabilities['uniChapSupported'],
                     'UseChapUnlessProhibitedByTarget'      : hbaCapabilities['uniChapSupported'],
                     'UseChap'                              : hbaCapabilities['uniChapSupported'],
                  },
               'mutual':
                  {
                     'SettingNotSupported'                  : hbaCapabilities['mutualChapSupported'],
                     'DoNotUseChap'                         : True,
                     'DoNotUseChapUnlessRequiredByTarget'   : hbaCapabilities['mutualChapSupported'],
                     'UseChapUnlessProhibitedByTarget'      : hbaCapabilities['mutualChapSupported'],
                     'UseChap'                              : hbaCapabilities['mutualChapSupported'],
                  },
            },
         'target':
            {
               'uni':
                  {
                     'SettingNotSupported'                  : hbaCapabilities['targetLevelUniAuthSupported'],
                     'DoNotUseChap'                         : True,
                     'DoNotUseChapUnlessRequiredByTarget'   : hbaCapabilities['targetLevelUniAuthSupported'],
                     'UseChapUnlessProhibitedByTarget'      : hbaCapabilities['targetLevelUniAuthSupported'],
                     'UseChap'                              : hbaCapabilities['targetLevelUniAuthSupported'],
                  },
               'mutual':
                  {
                     'SettingNotSupported'                  : hbaCapabilities['targetLevelMutualAuthSupported'],
                     'DoNotUseChap'                         : True,
                     'DoNotUseChapUnlessRequiredByTarget'   : False,
                     'UseChapUnlessProhibitedByTarget'      : False,
                     'UseChap'                              : hbaCapabilities['targetLevelMutualAuthSupported'],
                  },
            },
      }

      hbaCapabilities['supportedChapLevels'] = supportedChapLevels

      if hbaInfo[0]['Using ISCSI Offload Engine'] == 'true':
         pnp = [pnp for pnp in pnpList if pnp['Adapter'] == hbaName]
         assert(len(pnp) == 1)

         if hbaInfo[0]['Is NIC'] == 'true':
            hbaType = ISCSI_HBA_PROFILE_DEPENDENT
            vmkName = pnp[0]['Vmnic']
         else:
            hbaType = ISCSI_HBA_PROFILE_INDEPENDENT
            vmkName = hbaName

            # Special handling for qlogic driver
            if storageHbaList[hbaName] == ISCSI_QLOGIC_DRIVER:
               for chapParams in [('hba', 'uni'), ('hba', 'mutual'), ('target', 'uni'), ('target', 'mutual')]:
                  supportedChapLevels[chapParams[0]][chapParams[1]]['DoNotUseChapUnlessRequiredByTarget'] = False
                  supportedChapLevels[chapParams[0]][chapParams[1]]['UseChap'] = False
                  supportedChapLevels[chapParams[0]][chapParams[1]]['SettingNotSupported'] = False

            status, hbaIpConfig = GetHostData(hostServices,
                                  ISCSI_INITIATOR_CONFIG_IPCONFIG_GET_CMD,
                                  hbaName)
            hbaIpv4Config.enabled = hbaIpConfig[0]['IPv4Enabled']
            hbaIpv4Config.useDhcp = hbaIpConfig[0]['UseDhcpv4']
            hbaIpv4Config.address = hbaIpConfig[0]['IPv4']
            hbaIpv4Config.subnet = hbaIpConfig[0]['IPv4SubnetMask']
            hbaIpv4Config.gateway = hbaIpConfig[0]['Gateway']

            hbaIpv4Address = hbaIpConfig[0]['IPv4']
            hbaIpv4Netmask = hbaIpConfig[0]['IPv4SubnetMask']
            hbaIpv4Gateway = hbaIpConfig[0]['Gateway']

            status, ipv6Conf = GetHostData(hostServices,
                               ISCSI_INITIATOR_CONFIG_IPV6CONFIG_GET_CMD,
                               hbaName
                               )
            hbaIpv6Config.supported = ipv6Conf['IPv6 Supported']
            hbaIpv6Config.enabled = ipv6Conf['IPv6 Enabled']
            hbaIpv6Config.useRouterAdv = ipv6Conf['Use IPv6 Router Advertisement']
            hbaIpv6Config.useDhcp6 = ipv6Conf['Use Dhcpv6']
            hbaIpv6Config.gateway6 = ipv6Conf['Gateway6']
            hbaLinklocalConfig.useLinklocalAutoConf = ipv6Conf['Use Link Local Auto Configuration']

            hbaIpCaps.ipv4Enable = hbaCaps[0]['IPv4 Enable Settable']
            hbaIpCaps.ipv6Enable = hbaCaps[0]['IPv6 Enable Settable']
            hbaIpCaps.ipv6RouterAdv = hbaCaps[0]['IPv6 Router Advertisement Configuration Method Settable']
            hbaIpCaps.dhcpv6 = hbaCaps[0]['IPv6 DHCP Configuration Method Settable']
            hbaIpCaps.linklocalAuto = hbaCaps[0]['IPv6 Linklocal Auto Configuration Method Settable']
            hbaIpCaps.prefixLen = hbaCaps[0]['IPv6 Prefix Length Settable']
            hbaIpCaps.maxIpv6AddrSupported = int(ipv6Conf['IPv6 Max Static Address Supported'])
            hbaIpCaps.fixedPrefixLen = int(ipv6Conf['IPv6 Prefix Length'])

            if hbaIpv6Config.supported == True:
               status, hbaIpAddr = GetHostData(hostServices,
                                   ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_GET_CMD,
                                   hbaName
                                   )
               globalAddrCount = 0
               for tmpAddr6 in hbaIpAddr:
                  # check if linklocal
                  addr6 = tmpAddr6['Address']
                  ipaddr6 = ipaddress.ip_address(addr6)
                  if ipaddr6.is_link_local:
                     # only one link local address will be present
                     hbaLinklocalConfig.linklocalAddr = addr6
                  else:
                     # save the first global address
                     if globalAddrCount == 0:
                        # addresses are stored in format addr1/prefix1,addr2/prefix2
                        hbaIpv6Config.ipv6AddressOriginal += \
                           ''.join([tmpAddr6['Address'],
                              '/',
                              str(tmpAddr6['IPv6PrefixLength'])])
                        hbaIpv6Config.ipv6AddressModified += \
                           ''.join([str(int(ipaddress.ip_address(tmpAddr6['Address']))),
                              '/',
                              str(tmpAddr6['IPv6PrefixLength'])])
                     else:
                        hbaIpv6Config.ipv6AddressOriginal += \
                           ''.join([',',
                              tmpAddr6['Address'],
                              '/',
                              str(tmpAddr6['IPv6PrefixLength'])])
                        hbaIpv6Config.ipv6AddressModified += \
                           ''.join([',',
                              str(int(ipaddress.ip_address(tmpAddr6['Address']))),
                              '/',
                              str(tmpAddr6['IPv6PrefixLength'])])
                     globalAddrCount += 1
               hbaIpv6Config.globalAddrCount = globalAddrCount
               # sort the modified address string
               if hbaIpv6Config.ipv6AddressModified:
                  addrList = hbaIpv6Config.ipv6AddressModified.split(",")
                  if len(addrList) > 0:
                     addrList.sort()
                     hbaIpv6Config.ipv6AddressModified = ''
                     for x in addrList:
                        if not hbaIpv6Config.ipv6AddressModified:
                           hbaIpv6Config.ipv6AddressModified += x
                        else:
                           hbaIpv6Config.ipv6AddressModified += ',' + x
            # if ipv6 not supported ignore ipv6 configuration
            else:
               hbaIpv6Config.ignore = True
               hbaLinklocalConfig.ignore = True

            status, tmpParams = GetHostData(hostServices,
                                ISCSI_INITIATOR_CONFIG_PNP_PARM_GET_CMD,
                                hbaName
                                )
            hbaPnpParams = dict([(p['Option'],p['Value']) for p in tmpParams])

            arpRedirection = bool(hbaPnpParams['ArpRedirect'])
            jumboFrame = hbaPnpParams['MTU']
            hbaCapabilities['mutualChapSupported'] = False

         macAddress = pnp[0]['MAC Address']

         for pci in pciList:
            if pci['VMkernel Name'] == vmkName:
               pciAddress = pci['Address']
               vendorName = pci['Vendor Name']
      else:
            swiscsiHbaFound = True
            hbaType = ISCSI_HBA_PROFILE_SOFTWARE
            pciAddress=''
            macAddress=''
            vendorName = 'VMware'

      assert(pciAddress != None)
      assert(macAddress != None)
      assert(vendorName != None)

      iscsiHbaList.append(
         IscsiHba(hbaName,
                  hbaType,
                  True,
                  hbaCapabilities,
                  pciAddress,
                  macAddress,
                  storageHbaList[hbaName],
                  vendorName,
                  hbaIqn,
                  hbaAlias,
                  hbaIpv4Address,
                  hbaIpv4Netmask,
                  hbaIpv4Gateway,
                  arpRedirection,
                  jumboFrame,
                  ChapTypeMapVmk2Policy((hbaChapParams[0]['Level'],
                                         False, True)),
                  hbaChapParams[0]['Name'],
                  '',
                  ChapTypeMapVmk2Policy((hbaMutualChapParams[0]['Level'],
                                         False,
                                         hbaCapabilities['mutualChapSupported'])),
                  hbaMutualChapParams[0]['Name'],
                  '',
                  DigestMapVmk2Policy(hbaCurrentParams[HEADER_DIGEST]),
                  DigestMapVmk2Policy(hbaCurrentParams[DATA_DIGEST]),
                  ParamToInt(hbaCurrentParams[MAX_R2T]),
                  ParamToInt(hbaCurrentParams[FIRST_BURST_LENGTH]),
                  ParamToInt(hbaCurrentParams[MAX_BURST_LENGTH]),
                  ParamToInt(hbaCurrentParams[MAX_RECV_SEG_LENGTH]),
                  ParamToInt(hbaCurrentParams[NOOP_OUT_INTERVAL]),
                  ParamToInt(hbaCurrentParams[NOOP_OUT_TIMEOUT]),
                  ParamToInt(hbaCurrentParams[RECOVERY_TIMEOUT]),
                  ParamToInt(hbaCurrentParams[LOGIN_TIMEOUT]),
                  ParamToBool(hbaCurrentParams[DELAYED_ACK]),
                  hbaIpv4Config,
                  hbaIpv6Config,
                  hbaLinklocalConfig,
                  hbaIpCaps))

   for hba in iscsiHbaList:
      IscsiLog(3, 'Gathering sendtarget discovery info for: %s' % (hba.name))
      hba.sendTargetDiscoveryList = GetIscsiSendTargetsDiscoveryList(hba, hostServices)

      IscsiLog(3, 'Gathering discovered target info for: %s' % (hba.name))
      hba.discoveredTargetList = GetDiscoveredIscsiTargetList(hba, hostServices)

      IscsiLog(3, 'Gathering static target info for: %s' % (hba.name))
      hba.staticTargetList = GetStaticIscsiTargetList(hba, hostServices)

      IscsiLog(3, 'Gathering vnic binding info for: %s' % (hba.name))
      hba.boundVnicList = GetIscsiBoundVnicList(hba, hostServices)

   if swiscsiHbaFound == False:
      IscsiLog(3, 'Creating dummy software iscsi hba')

      iscsiHbaList.append(IscsiHba('@@iscsi_vmk@@',
                                   ISCSI_HBA_PROFILE_SOFTWARE,
                                   False,
                                   SOFTWARE_ISCSI_CAPS,
                                   None,
                                   None,
                                   'iscsi_vmk',
                                   'VMware',
                                   IscsiGenerateIqn(hostServices),
                                   '',
                                   None,
                                   None,
                                   None,
                                   None,
                                   None,
                                   ChapTypeMapVmk2Policy(('prohibited', False, True)),
                                   '',
                                   '',
                                   ChapTypeMapVmk2Policy(('prohibited', False, True)),
                                   '',
                                   '',
                                   DigestMapVmk2Policy((ISCSI_DEFAULT_HEADERDIGEST, False, True, ISCSI_DEFAULT_HEADERDIGEST)),
                                   DigestMapVmk2Policy((ISCSI_DEFAULT_DATADIGEST, False, True, ISCSI_DEFAULT_DATADIGEST)),
                                   ParamToInt((ISCSI_DEFAULT_MAXR2T, False, True, ISCSI_DEFAULT_MAXR2T)),
                                   ParamToInt((ISCSI_DEFAULT_FIRSTBURSTLENGTH, False, True, ISCSI_DEFAULT_FIRSTBURSTLENGTH)),
                                   ParamToInt((ISCSI_DEFAULT_MAXBURSTLENGTH, False, True, ISCSI_DEFAULT_MAXBURSTLENGTH)),
                                   ParamToInt((ISCSI_DEFAULT_MAXRECVSEGLENGTH, False, True, ISCSI_DEFAULT_MAXRECVSEGLENGTH)),
                                   ParamToInt((ISCSI_DEFAULT_NOOPOUTINTERVAL, False, True, ISCSI_DEFAULT_NOOPOUTINTERVAL)),
                                   ParamToInt((ISCSI_DEFAULT_NOOPOUTTIMEOUT, False, True, ISCSI_DEFAULT_NOOPOUTTIMEOUT)),
                                   ParamToInt((ISCSI_DEFAULT_RECOVERYTIMEOUT, False, True, ISCSI_DEFAULT_RECOVERYTIMEOUT)),
                                   ParamToInt((ISCSI_DEFAULT_LOGINTIMEOUT, False, True, ISCSI_DEFAULT_LOGINTIMEOUT)),
                                   ParamToInt((ISCSI_DEFAULT_DELAYEDACK, False, True, ISCSI_DEFAULT_DELAYEDACK)),
                                   Ipv4Config(),
                                   Ipv6Config(),
                                   LinklocalConfig(),
                                   None))

   IscsiLog(3, 'Done Gathering HBA info')
   return iscsiHbaList

# SendTarget related
class IscsiSendTarget(IscsiCommon):
   def __init__(self, ipAddress, portNumber, initiatorChapType, initiatorChapName,
                initiatorChapSecret, targetChapType, targetChapName, targetChapSecret,
                headerDigest, dataDigest, maxR2T, firstBurstLength, maxBurstLength,
                maxRecvSegLength, noopOutInterval, noopOutTimeout, recoveryTimeout, loginTimeout,
                delayedAck):
      self.ipAddress = ipAddress
      self.portNumber = portNumber
      IscsiCommon.__init__(self, initiatorChapType,
                initiatorChapName, initiatorChapSecret, targetChapType, targetChapName,
                targetChapSecret, headerDigest, dataDigest, maxR2T, firstBurstLength,
                maxBurstLength, maxRecvSegLength, noopOutInterval, noopOutTimeout,
                recoveryTimeout, loginTimeout, delayedAck)

def FindSendTargetDiscovery(hba, ipAddress, portNumber, createNullStFlag):
   # Return if we find one
   for stInst in hba.sendTargetDiscoveryList:
      if stInst.ipAddress == ipAddress and \
         stInst.portNumber == portNumber:
            return stInst

   # If we don't find one, and the caller indicated that he wants a null sendTarget instance,
   # so, create one and return it.
   if createNullStFlag == True:
      return IscsiSendTarget(None, # ipAddress
                             None, # portNumber
                             None, # initiatorChapType
                             None, # initiatorChapName
                             None, # initiatorChapSecret
                             None, # targetChapType
                             None, # targetChapName
                             None, # targetChapSecret
                             None, # headerDigest
                             None, # dataDigest
                             None, # maxR2T
                             None, # firstBurstLength
                             None, # maxBurstLength
                             None, # maxRecvSegLength
                             None, # noopOutInterval
                             None, # noopOutTimeout
                             None, # recoveryTimeout
                             None, # loginTimeout
                             None  # delayedAck
                            )
   else:
      return None

def CreateSendTargetDiscoveryTaskFromConfigData(hba, currStdData, newStdData, forGtl):
   tasks = []
   reason = ISCSI_REASON_UPDATE
   parmPreRequisite = ''
   authPreRequisite = ''

   # Create a new sendtarget record if it does not exist
   if currStdData.ipAddress == None and \
      currStdData.portNumber == None:
      reason = ISCSI_REASON_ADD
      authPreRequisite = 'ISCSI_SENDTARGET_AUTH_ISSETTABLE'
      parmPreRequisite = 'ISCSI_SENDTARGET_PARAM_ISSETTABLE'
      tasks.append({'task': 'ISCSI_INITIATOR_CONFIG_SENDTARGET_ADD',
                   'ip': newStdData.ipAddress,
                   'port': newStdData.portNumber,
                   'hba': hba.name,
                   'postTaskFunc': 'IscsiAddSendTargetProfData'
                   })

   # Update the parameters
   authCmd = {
      'task': 'ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_SET',
      'hba': hba.name,
      'ip': newStdData.ipAddress,
      'port': newStdData.portNumber,
      'taskPreRequisite': authPreRequisite,
      'reason': reason,
   }

   parmCmd = {
      'task' : 'ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_SET',
      'hba' : hba.name,
      'ip' : newStdData.ipAddress,
      'port': newStdData.portNumber,
      'taskPreRequisite': parmPreRequisite,
      'reason': reason,
   }

   # Update the parameters
   tasks.extend(CreateConfigTaskForParams(hba, currStdData, newStdData,
      authCmd, parmCmd, False, forGtl))

   if len(tasks) > 0:
      if hba.type == ISCSI_HBA_PROFILE_INDEPENDENT:
         tasks.append(
            {'task' : 'ISCSI_INITIATOR_CONFIG_DO_REDISCOVERY',
             'hba': hba.name,
             'ip' : newStdData.ipAddress,
             'port': newStdData.portNumber,
             'noCC': True,
             'failOK': True
            })
      else:
         tasks.append(
            {'task': 'ISCSI_INITIATOR_CONFIG_SENDTARGET_ADD',
             'ip': newStdData.ipAddress,
             'port': newStdData.portNumber,
             'hba': hba.name,
             'noCC': True,
             'failOK': True
            })


   return tasks

def GetIscsiSendTargetsDiscoveryList(hba, hostServices, filters=None):
   iscsiSendTargetsList = []

   status, sendTargetDiscoveryAddrList = GetHostData(hostServices,
                                         ISCSI_INITIATOR_CONFIG_SENDTARGET_LIST_CMD,
                                         hba.name)
   if filters:
      sendTargetDiscoveryAddrList = [stdr for stdr in sendTargetDiscoveryAddrList \
                                       if stdr['Sendtarget'] == filters['targetAddress']]

   for addrInst in sendTargetDiscoveryAddrList:
      sendTargetAddr = addrInst['Sendtarget'].rpartition(':')
      status, params = GetHostData(hostServices,
                          ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_GET_CMD,
                          hba.name,
                          sendTargetAddr[0],
                          sendTargetAddr[2])
      currentParams=dict([(p['Name'], (p['Current'], p['Inherit'], p['Settable'], p['Default'])) for p in params])

      status, chapParams = GetHostData(hostServices,
                           ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_UNI_GET_CMD,
                           hba.name,
                           ip=sendTargetAddr[0],
                           port=sendTargetAddr[2]
                           )

      status, mutualChapParams = GetHostData(hostServices,
                                 ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_MUTUAL_GET_CMD,
                                 hba.name,
                                 ip= sendTargetAddr[0],
                                 port=sendTargetAddr[2]
                                 )
      chapType = (chapParams[0]['Level'], chapParams[0]['Inheritance'],
                  hba.caps['targetLevelUniAuthSupported'])

      mutualChapType = (mutualChapParams[0]['Level'],
                        mutualChapParams[0]['Inheritance'],
                        hba.caps['targetLevelMutualAuthSupported'])

      sendTargetInst = IscsiSendTarget(
                           sendTargetAddr[0], # ipAddress
                           sendTargetAddr[2], # portNumber
                           ChapTypeMapVmk2Policy(chapType), # initiatorChapType
                           chapParams[0]['Name'], # initiatorChapName
                           '', # initiatorChapSecret
                           ChapTypeMapVmk2Policy(mutualChapType), # targetChapType
                           mutualChapParams[0]['Name'], # targetChapName
                           '', # targetChapSecret
                           DigestMapVmk2Policy(currentParams[HEADER_DIGEST]), # headerDigest
                           DigestMapVmk2Policy(currentParams[DATA_DIGEST]), # dataDigest
                           ParamToInt(currentParams[MAX_R2T]), # maxR2T
                           ParamToInt(currentParams[FIRST_BURST_LENGTH]), # firstBurstLength
                           ParamToInt(currentParams[MAX_BURST_LENGTH]), # maxBurstLength
                           ParamToInt(currentParams[MAX_RECV_SEG_LENGTH]), # maxRecvSegLength
                           ParamToInt(currentParams[NOOP_OUT_INTERVAL]), # noopOutInterval
                           ParamToInt(currentParams[NOOP_OUT_TIMEOUT]), # noopOutTimeout
                           ParamToInt(currentParams[RECOVERY_TIMEOUT]), # recoveryTimeout
                           ParamToInt(currentParams[LOGIN_TIMEOUT]), # loginTimeout
                           ParamToBool(currentParams[DELAYED_ACK]) # delayedAck
                          )

      iscsiSendTargetsList.append(sendTargetInst)

   return iscsiSendTargetsList

def CreateRemoveSendTargetsDiscoveryFromConfigData(configData, parent, profInstances):
   tasks = []

   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return tasks

   # Build a list of send target addresses in the profile
   discoveryList = []
   for profInst in profInstances:
      ipAddress = ExtractPolicyOptionValue(profInst,
                                       IscsiSendTargetsDiscoveryIdentityPolicy,
                                       [
                                        ([IscsiSendTargetsDiscoveryIdentityPolicyOption],
                                         FROM_ATTRIBUTE, 'discoveryAddress'),
                                       ],
                                       True)
      portNumber = ExtractPolicyOptionValue(profInst,
                                       IscsiSendTargetsDiscoveryIdentityPolicy,
                                       [
                                        ([IscsiSendTargetsDiscoveryIdentityPolicyOption],
                                         FROM_ATTRIBUTE, 'discoveryPort'),
                                       ],
                                       True)

      discoveryList.append((ipAddress, portNumber))

   # Remove all the send target addresses that are not in the profile
   tasks.extend([                                                       \
         {                                                              \
          'task' : 'ISCSI_INITIATOR_CONFIG_SENDTARGET_REM',             \
          'ip': discoveryAddr.ipAddress,                                \
          'port': discoveryAddr.portNumber,                             \
          'hba' : hba.name                                              \
         } for discoveryAddr in hba.sendTargetDiscoveryList             \
            if (discoveryAddr.ipAddress, discoveryAddr.portNumber)      \
               not in discoveryList                                     \
   ])

   return tasks

# Target related
class IscsiTarget(IscsiCommon):
   def __init__(self, ipAddress, portNumber, iqn, targetType, bootTarget,
                initiatorChapType, initiatorChapName, initiatorChapSecret,
                targetChapType, targetChapName, targetChapSecret, headerDigest,
                dataDigest, maxR2T, firstBurstLength, maxBurstLength,
                maxRecvSegLength, noopOutInterval, noopOutTimeout,
                recoveryTimeout, loginTimeout, delayedAck):
      self.ipAddress = ipAddress
      self.portNumber = portNumber
      self.iqn = iqn
      self.targetType = targetType
      self.bootTarget = bootTarget
      IscsiCommon.__init__(self, initiatorChapType,
                initiatorChapName, initiatorChapSecret, targetChapType, targetChapName,
                targetChapSecret, headerDigest, dataDigest, maxR2T, firstBurstLength,
                maxBurstLength, maxRecvSegLength, noopOutInterval, noopOutTimeout,
                recoveryTimeout, loginTimeout, delayedAck)

def CreateTargetConfigTaskFromConfigData(hba, currTargetData, newTargetData, forGtl):
   tasks = []

   authPreRequisite = ''
   parmPreRequisite = ''

   reason = ISCSI_REASON_UPDATE
   targetAddress = newTargetData.ipAddress

   # Add the port number
   targetAddress = '%s:%s' %(newTargetData.ipAddress, newTargetData.portNumber)

   # Format the input params for the 'target' ops
   inputParams = {'hba': hba.name,
                  'targetAddress': targetAddress,
                  'iqn': newTargetData.iqn
                 }

   # Create a new statictarget record if it does not exist
   if currTargetData.ipAddress == None and \
      currTargetData.portNumber == None and \
      currTargetData.iqn == None:
      reason = ISCSI_REASON_ADD
      if newTargetData.targetType == ISCSI_SEND_TARGETS and forGtl == False:
         tasks.append(CopyDictAndUpdate(inputParams,
                                    {'task': 'ISCSI_INITIATOR_CONFIG_DISCOVEREDTARGET_MISSING',
                                    }))
      elif newTargetData.targetType == ISCSI_STATIC_TARGETS:
         tasks.append(CopyDictAndUpdate(inputParams,
                                    {'task': 'ISCSI_INITIATOR_CONFIG_STATICTARGET_ADD',
                                     'postTaskFunc': 'IscsiAddStaticTargetProfData',
                                    }))
         authPreRequisite = 'ISCSI_STATICTARGET_AUTH_ISSETTABLE'
         parmPreRequisite = 'ISCSI_STATICTARGET_PARAM_ISSETTABLE'

   # In case of CC and the op is missing record, we do not have to generate the
   # parameter updates
   if forGtl == False and reason == ISCSI_REASON_ADD:
      return tasks

   # Update the parameters
   authCmd = CopyDictAndUpdate(inputParams,
                               {'task': 'ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_SET',
                                'taskPreRequisite': authPreRequisite,
                                'reason': reason})

   parmCmd = CopyDictAndUpdate(inputParams,
                               {'task' : 'ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_SET',
                                'taskPreRequisite': parmPreRequisite,
                                'reason': reason})

   tasks.extend(CreateConfigTaskForParams(hba,
      currTargetData, newTargetData, authCmd, parmCmd,
      newTargetData.targetType == ISCSI_SEND_TARGETS, forGtl))

   return tasks

#
# Return if the chap params are different b/n the system config and profile
#
def IsChapParamsDifferent(forGtl, currChapType, newChapType, currChapName, newChapName):
   if forGtl == True:
      #  For 'gtl', we treat params as different in case the chap types are
      #  different or chap type in the profile is not one of 'DoNotUseChap'
      #  and 'InheritFromParent'. We do not check chap name and secret.
      if IsSettable(currChapType) and IsSettable(newChapType) and \
         (Compare(newChapType, currChapType) or \
          newChapType not in ['DoNotUseChap', 'InheritFromParent']):
         return True
   else:
      #  For CC, we treat params as different, in case the chap types are different
      #  or chapName is different and chap type in the profile is not one of
      #  'DoNotUseChap' and 'InheritFromParent'. We ignore chap secret from
      #  checking.
      if IsSettable(currChapType) and IsSettable(newChapType) and \
         (Compare(newChapType, currChapType) or \
         (Compare(newChapName, currChapName) and \
          newChapType not in ['DoNotUseChap', 'InheritFromParent'])):
         return True

   return False

def IsSettingNeeded(reason, paramValue):
   if reason == ISCSI_REASON_ADD and paramValue[0] == 'InheritFromParent':
      return False

   return True

def CreateConfigTaskForParams(hba, currAuthAndParmsData, newAuthAndParmsData,
                              authCmd, parmCmd, failOK, forGtl):
   tasks = []

   reason = authCmd.get('reason')

   # Initiator Chap
   #
   # Since we can't validate if chap secret is same or different, we ignore that
   # for CC operation
   #
   if IsChapParamsDifferent(forGtl,
                            currAuthAndParmsData.initiatorChapType,
                            newAuthAndParmsData.initiatorChapType,
                            currAuthAndParmsData.initiatorChapName,
                            newAuthAndParmsData.initiatorChapName):
      if chapPolicyOptionsMap[newAuthAndParmsData.initiatorChapType][0] == 'InheritFromParent':
         if reason != ISCSI_REASON_ADD:
            tasks.append(CopyDictAndUpdate(authCmd,
                                           {'direction': 'uni',
                                           'keyValue': '--inherit',
                                           'failOK': failOK,
                                          }))

      elif chapPolicyOptionsMap[newAuthAndParmsData.initiatorChapType][0] == ISCSI_INITIATOR_DEFAULT_VALUE:
         tasks.append(CopyDictAndUpdate(authCmd,
                                        {'direction': 'uni',
                                        'keyValue': '--default',
                                        'failOK': failOK,
                                       }))
      else:
         chapName = newAuthAndParmsData.initiatorChapName
         chapSecret = newAuthAndParmsData.initiatorChapSecret
         chapLevel = chapPolicyOptionsMap[newAuthAndParmsData.initiatorChapType][0]

         keyValue = {
            'level' : chapLevel,
            'authname': chapName,
            'secret': chapSecret
         }

         tasks.append(CopyDictAndUpdate(authCmd,
                                        {'direction': 'uni',
                                        'keyValue': keyValue,
                                        'failOK': failOK,
                                       }))
   # Target Chap
   #
   # Since we can't validate if chap secret is same or different, we ignore that
   # for CC operation
   #
   if IsChapParamsDifferent(forGtl,
                            currAuthAndParmsData.targetChapType,
                            newAuthAndParmsData.targetChapType,
                            currAuthAndParmsData.targetChapName,
                            newAuthAndParmsData.targetChapName):
      if chapPolicyOptionsMap[newAuthAndParmsData.targetChapType][0] == 'InheritFromParent':
         if reason != ISCSI_REASON_ADD:
            tasks.append(CopyDictAndUpdate(authCmd,
                                            {'direction': 'mutual',
                                            'keyValue': '--inherit',
                                            'failOK': failOK,
                                           }))

      elif chapPolicyOptionsMap[newAuthAndParmsData.targetChapType][0] == ISCSI_INITIATOR_DEFAULT_VALUE:
         tasks.append(CopyDictAndUpdate(authCmd,
                                        {'direction': 'mutual',
                                        'keyValue': '--default',
                                        'failOK': failOK,
                                       }))

      else:
         chapName = newAuthAndParmsData.targetChapName
         chapSecret = newAuthAndParmsData.targetChapSecret
         chapLevel = chapPolicyOptionsMap[newAuthAndParmsData.targetChapType][0]

         keyValue = {
            'level' : chapLevel,
            'authname': chapName,
            'secret': chapSecret
         }

         tasks.append(CopyDictAndUpdate(authCmd,
                                        {'direction': 'mutual',
                                        'keyValue': keyValue,
                                        'failOK': failOK,
                                       }))

   # Header Digest
   if IsSettable(currAuthAndParmsData.params[HEADER_DIGEST]) and \
      IsSettable(newAuthAndParmsData.params[HEADER_DIGEST]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[HEADER_DIGEST]) and \
      IscsiParamCompare(newAuthAndParmsData.params[HEADER_DIGEST], \
                        currAuthAndParmsData.params[HEADER_DIGEST]):
      keyValue = ValueToOption(digestPolicyOptionsMap[newAuthAndParmsData.params[HEADER_DIGEST][0]][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': HEADER_DIGEST,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'HeaderDigest',
                                     'hostValue' : currAuthAndParmsData.params[HEADER_DIGEST],
                                     'profileValue' : newAuthAndParmsData.params[HEADER_DIGEST],
                                     'complianceValueOption' : PARAM_NAME
                                    }))


   # Data Digest
   if IsSettable(currAuthAndParmsData.params[DATA_DIGEST]) and \
      IsSettable(newAuthAndParmsData.params[DATA_DIGEST]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[DATA_DIGEST]) and \
      IscsiParamCompare(newAuthAndParmsData.params[DATA_DIGEST],
                        currAuthAndParmsData.params[DATA_DIGEST]):
      keyValue = ValueToOption(digestPolicyOptionsMap[newAuthAndParmsData.params[DATA_DIGEST][0]][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': DATA_DIGEST,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'DataDigest',
                                     'hostValue' : currAuthAndParmsData.params[DATA_DIGEST],
                                     'profileValue' : newAuthAndParmsData.params[DATA_DIGEST],
                                     'complianceValueOption' : PARAM_NAME
                                    }))


   # MaxOutstandingR2T
   if IsSettable(currAuthAndParmsData.params[MAX_R2T]) and \
      IsSettable(newAuthAndParmsData.params[MAX_R2T]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[MAX_R2T]) and \
      IscsiParamCompare(newAuthAndParmsData.params[MAX_R2T], \
                        currAuthAndParmsData.params[MAX_R2T]):
      keyValue = ValueToOption(newAuthAndParmsData.params[MAX_R2T][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': MAX_R2T,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'MaxOutstandingR2T',
                                     'hostValue' : currAuthAndParmsData.params[MAX_R2T],
                                     'profileValue' : newAuthAndParmsData.params[MAX_R2T],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # First Burst Length
   if IsSettable(currAuthAndParmsData.params[FIRST_BURST_LENGTH]) and \
      IsSettable(newAuthAndParmsData.params[FIRST_BURST_LENGTH]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[FIRST_BURST_LENGTH]) and \
      IscsiParamCompare(newAuthAndParmsData.params[FIRST_BURST_LENGTH], \
                        currAuthAndParmsData.params[FIRST_BURST_LENGTH]):
      keyValue = ValueToOption(newAuthAndParmsData.params[FIRST_BURST_LENGTH][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': FIRST_BURST_LENGTH,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'FirstBurstLength',
                                     'hostValue' : currAuthAndParmsData.params[FIRST_BURST_LENGTH],
                                     'profileValue' : newAuthAndParmsData.params[FIRST_BURST_LENGTH],
                                     'complianceValueOption': PARAM_NAME
                                    }))

   # Max Burst Length
   if IsSettable(currAuthAndParmsData.params[MAX_BURST_LENGTH]) and \
      IsSettable(newAuthAndParmsData.params[MAX_BURST_LENGTH]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[MAX_BURST_LENGTH]) and \
      IscsiParamCompare(newAuthAndParmsData.params[MAX_BURST_LENGTH], \
                        currAuthAndParmsData.params[MAX_BURST_LENGTH]):
      keyValue = ValueToOption(newAuthAndParmsData.params[MAX_BURST_LENGTH][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': MAX_BURST_LENGTH,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'MaxBurstLength',
                                     'hostValue' : currAuthAndParmsData.params[MAX_BURST_LENGTH],
                                     'profileValue' : newAuthAndParmsData.params[MAX_BURST_LENGTH],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # Max Recv Segment Length
   if IsSettable(currAuthAndParmsData.params[MAX_RECV_SEG_LENGTH]) and \
      IsSettable(newAuthAndParmsData.params[MAX_RECV_SEG_LENGTH]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[MAX_RECV_SEG_LENGTH]) and \
      IscsiParamCompare(newAuthAndParmsData.params[MAX_RECV_SEG_LENGTH], \
                        currAuthAndParmsData.params[MAX_RECV_SEG_LENGTH]):
      keyValue = ValueToOption(newAuthAndParmsData.params[MAX_RECV_SEG_LENGTH][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': MAX_RECV_SEG_LENGTH,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'MaxRecvDataSegment',
                                     'hostValue' : currAuthAndParmsData.params[MAX_RECV_SEG_LENGTH],
                                     'profileValue' : newAuthAndParmsData.params[MAX_RECV_SEG_LENGTH],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # NOOP Out Interval
   if IsSettable(currAuthAndParmsData.params[NOOP_OUT_INTERVAL]) and \
      IsSettable(newAuthAndParmsData.params[NOOP_OUT_INTERVAL]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[NOOP_OUT_INTERVAL]) and \
      IscsiParamCompare(newAuthAndParmsData.params[NOOP_OUT_INTERVAL], \
                        currAuthAndParmsData.params[NOOP_OUT_INTERVAL]):
      keyValue = ValueToOption(newAuthAndParmsData.params[NOOP_OUT_INTERVAL][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': NOOP_OUT_INTERVAL,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'NoopOutInterval',
                                     'hostValue' : currAuthAndParmsData.params[NOOP_OUT_INTERVAL],
                                     'profileValue' : newAuthAndParmsData.params[NOOP_OUT_INTERVAL],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # NOOP Out Timeout
   if IsSettable(currAuthAndParmsData.params[NOOP_OUT_TIMEOUT]) and \
      IsSettable(newAuthAndParmsData.params[NOOP_OUT_TIMEOUT]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[NOOP_OUT_TIMEOUT]) and \
      IscsiParamCompare(newAuthAndParmsData.params[NOOP_OUT_TIMEOUT], \
                        currAuthAndParmsData.params[NOOP_OUT_TIMEOUT]):
      keyValue = ValueToOption(newAuthAndParmsData.params[NOOP_OUT_TIMEOUT][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': NOOP_OUT_TIMEOUT,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'NoopOutTimeout',
                                     'hostValue' : currAuthAndParmsData.params[NOOP_OUT_TIMEOUT],
                                     'profileValue' : newAuthAndParmsData.params[NOOP_OUT_TIMEOUT],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # Recovery Timeout
   if IsSettable(currAuthAndParmsData.params[RECOVERY_TIMEOUT]) and \
      IsSettable(newAuthAndParmsData.params[RECOVERY_TIMEOUT]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[RECOVERY_TIMEOUT]) and \
      IscsiParamCompare(newAuthAndParmsData.params[RECOVERY_TIMEOUT], \
                        currAuthAndParmsData.params[RECOVERY_TIMEOUT]):
      keyValue = ValueToOption(newAuthAndParmsData.params[RECOVERY_TIMEOUT][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': RECOVERY_TIMEOUT,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'RecoveryTimeout',
                                     'hostValue' : currAuthAndParmsData.params[RECOVERY_TIMEOUT],
                                     'profileValue' : newAuthAndParmsData.params[RECOVERY_TIMEOUT],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # Login Timeout
   if IsSettable(currAuthAndParmsData.params[LOGIN_TIMEOUT]) and \
      IsSettable(newAuthAndParmsData.params[LOGIN_TIMEOUT]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[LOGIN_TIMEOUT]) and \
      IscsiParamCompare(newAuthAndParmsData.params[LOGIN_TIMEOUT], \
                        currAuthAndParmsData.params[LOGIN_TIMEOUT]):
      keyValue = ValueToOption(newAuthAndParmsData.params[LOGIN_TIMEOUT][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': LOGIN_TIMEOUT,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'LoginTimeout',
                                     'hostValue' : currAuthAndParmsData.params[LOGIN_TIMEOUT],
                                     'profileValue' : newAuthAndParmsData.params[LOGIN_TIMEOUT],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   # Delayed Ack
   if IsSettable(currAuthAndParmsData.params[DELAYED_ACK])  and \
      IsSettable(newAuthAndParmsData.params[DELAYED_ACK]) and \
      IsSettingNeeded(reason, newAuthAndParmsData.params[DELAYED_ACK]) and \
      IscsiParamCompare(newAuthAndParmsData.params[DELAYED_ACK], \
                        currAuthAndParmsData.params[DELAYED_ACK]):
      keyValue = ValueToOption(newAuthAndParmsData.params[DELAYED_ACK][0])
      tasks.append(CopyDictAndUpdate(parmCmd,
                                    {'key': DELAYED_ACK,
                                     'keyValue': keyValue,
                                     'failOK': failOK,
                                     'comparisonIdentifier' : 'DelayedAck',
                                     'hostValue' : currAuthAndParmsData.params[DELAYED_ACK],
                                     'profileValue' : newAuthAndParmsData.params[DELAYED_ACK],
                                     'complianceValueOption' : PARAM_NAME
                                    }))

   return tasks

def FindTarget(targetType, hba, ipAddress, portNumber, iqn, createNullTgtFlag):
   if targetType == ISCSI_STATIC_TARGETS:
      targetList = hba.staticTargetList
   else:
      targetList = hba.discoveredTargetList

   # Return if we find one
   for targetInst in targetList:
      if targetInst.ipAddress == ipAddress and \
         targetInst.portNumber == portNumber and \
         targetInst.iqn == iqn:
            return targetInst

   # If we don't find one, and the caller indicated that he wants a null IscsiTarget instance,
   # so, create one and return it.
   if createNullTgtFlag == True:
      return IscsiTarget(None, # ipAddress
                         None, # portNumber
                         None, # iqn
                         targetType, # targetType
                         'false', # bootTarget
                         None, # initiatorChapType
                         None, # initiatorChapName
                         None, # initiatorChapSecret
                         None, # targetChapType
                         None, # targetChapName
                         None, # targetChapSecret
                         None, # headerDigest
                         None, # dataDigest
                         None, # maxR2T
                         None, # firstBurstLength
                         None, # maxBurstLength
                         None, # maxRecvSegLength
                         None, # noopOutInterval
                         None, # noopOutTimeout
                         None, # recoveryTimeout
                         None, # loginTimeout
                         None  #delayedAck
                        )
   else:
      return None

def GetStaticIscsiTargetList(hba, hostServices, filters=None):
   return GetIscsiTargetList(hba, hostServices, ISCSI_STATIC_TARGETS, filters)

def GetDiscoveredIscsiTargetList(hba, hostServices, filters=None):
   return GetIscsiTargetList(hba, hostServices, ISCSI_SEND_TARGETS, filters)

def GetIscsiTargetList(hba, hostServices, targetType, filters=None):
   iscsiTargetList = []

   # check if some iscsi boot device configured
   status, ibftOutput = hostServices.ExecuteEsxcli('iscsi', 'ibftboot', 'get')
   IscsiLog(2, 'Checking for static boot targets, Ignore ibftboot errors')
   runEsxcli = True if status == 0 else False

   # Get the list of static targets
   status, cliOutput = GetHostData(hostServices,
                          ISCSI_INITIATOR_CONFIG_STATICTARGET_LIST_CMD,
                          hba.name,
                          runEsxcli=runEsxcli)

   # Assuption is each target portal has different IP address and
   # we do not need to check the port number.
   staticTargetList=dict(
      [('%s,%s' %(t['Target Name'], t['Target Address'].rpartition(':')[0]), t) \
         for t in cliOutput])

   inputParams = {'hba': hba.name,
                  'targetAddress': 'all',
                  'iqn': 'all'
                 }

   # Get chap params for all targets -- uni
   status, allChapParams = GetHostData(hostServices,
                           ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_UNI_GET_CMD,
                           hba.name, targetAddress='all', iqn='all')
   # Get chap params for all targets -- mutual
   status, allMutualChapParams = GetHostData(hostServices,
                                 ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_MUTUAL_GET_CMD,
                                 hba.name, targetAddress='all', iqn='all')
   # Arrange the uni chap params indexed by target portal
   allChapParamDict = {}
   for cp in allChapParams:
      idx = '%s,%s' %(cp['TargetName'], cp['Address'])
      allChapParamDict[idx] = [cp]

   # Arrange the mutual chap params indexed by target portal
   allMutualChapParamDict = {}
   for cp in allMutualChapParams:
      idx = '%s,%s' %(cp['TargetName'], cp['Address'])
      allMutualChapParamDict[idx] = [cp]

   # Get target params for all the targets
   status, allTargetParams = GetHostData(hostServices,
                             ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_GET_CMD,
                             hba.name, targetAddress='all', iqn='all')
   # Arrange the target params indexed by target portal
   targetPortals = {}
   for targetParams in allTargetParams:
      tp = targetPortals.get(targetParams['ID'])
      if not tp:
         targetPortals[targetParams['ID']] = [targetParams]
      else:
         targetPortals[targetParams['ID']].append(targetParams)

   for tp in targetPortals:
      params = targetPortals[tp]
      idStr = tp.split(',')

      portal = {}
      portal['Target'] = idStr[0]
      portal['IP'] = idStr[1].rpartition(':')[0]
      portal['Port'] = idStr[1].rpartition(':')[2]

      targetPortal = '%s,%s' %(portal['Target'], portal['IP'])

      # Skip the irrelevent portals. i.e when called for dynamic
      # discovered targets, skip the static ones.
      if targetPortal not in staticTargetList:
         if targetType == ISCSI_STATIC_TARGETS:
            continue
      else:
         if targetType != ISCSI_STATIC_TARGETS:
            continue

      if targetType == ISCSI_STATIC_TARGETS:
         bootTarget = staticTargetList[targetPortal]['Boot'].lower()
      else:
         bootTarget = 'false'

      targetAddress = portal['IP']

      # Add the port number if available
      if portal['Port'].upper() == 'NA':
         portal['Port'] = ISCSI_DEFAULT_PORT_NUMBER

      targetAddress = '%s:%s' %(targetAddress, portal['Port'])

      chapParams = allChapParamDict[tp]
      mutualChapParams = allMutualChapParamDict[tp]

      if filters:
         if not (targetAddress == filters['targetAddress'] and \
            portal['Target'] == filters['iqn']):
            continue

      # Extract param name, current value and inheritance status from params list
      currentParams=dict(
         [(p['Name'], (p['Current'], p['Inherit'], p['Settable'], p['Default'])) \
            for p in params])


      # Build the target object from the data gathered above
      chapType = (chapParams[0]['Level'],
                  chapParams[0]['Inheritance'],
                  hba.caps['targetLevelUniAuthSupported'])

      mutualChapType = (mutualChapParams[0]['Level'],
                        mutualChapParams[0]['Inheritance'],
                        hba.caps['targetLevelMutualAuthSupported'])

      targetInst = IscsiTarget(portal['IP'], # ipAddress
                              str(portal['Port']), # portNumber
                              portal['Target'], # iqn
                              targetType, # targetType
                              bootTarget, # bootTarget
                              ChapTypeMapVmk2Policy(chapType), # initiatorChapType
                              chapParams[0]['Name'], # initiatorChapName
                              '', # initiatorChapSecret
                              ChapTypeMapVmk2Policy(mutualChapType), # targetChapType
                              mutualChapParams[0]['Name'], # targetChapName
                              '', # targetChapSecret
                              DigestMapVmk2Policy(currentParams[HEADER_DIGEST]), # headerDigest
                              DigestMapVmk2Policy(currentParams[DATA_DIGEST]), # dataDigest
                              ParamToInt(currentParams[MAX_R2T]), # maxR2T
                              ParamToInt(currentParams[FIRST_BURST_LENGTH]), # firstBurstLength
                              ParamToInt(currentParams[MAX_BURST_LENGTH]), # maxBurstLength
                              ParamToInt(currentParams[MAX_RECV_SEG_LENGTH]), # maxRecvSegLength
                              ParamToInt(currentParams[NOOP_OUT_INTERVAL]), # noopOutInterval
                              ParamToInt(currentParams[NOOP_OUT_TIMEOUT]), # noopOutTimeout
                              ParamToInt(currentParams[RECOVERY_TIMEOUT]), # recoveryTimeout
                              ParamToInt(currentParams[LOGIN_TIMEOUT]), # loginTimeout
                              ParamToBool(currentParams[DELAYED_ACK]) # delayedAck
                             )

      iscsiTargetList.append(targetInst)

   return iscsiTargetList

def CreateRemoveTargetConfigTaskFromConfigData(configData, parent, profInstances):
   tasks = []

   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if  hba is None:
      return tasks

   targetList = []
   for profInst in profInstances:
      policyInst = profInst.IscsiTargetIdentityPolicy
      assert isinstance(policyInst.policyOption, IscsiTargetIdentityPolicyOption), \
         'Target Profile %u does not have IscsiTargetIdentityPolicyOption policy option' % (id(profInst))

      ipAddress = policyInst.policyOption.targetAddress
      portNumber = policyInst.policyOption.targetPort
      iqn = policyInst.policyOption.targetIqn

      targetList.append((ipAddress, portNumber, iqn))

   # Remove the static targets that are not in the profile
   tasks.extend([                                                    \
      {                                                              \
       'task': 'ISCSI_INITIATOR_CONFIG_STATICTARGET_REM',            \
       'hba' : hba.name,                                             \
       'targetAddress': '%s:%s' %(st.ipAddress, st.portNumber),      \
       'iqn': st.iqn                                                 \
      } for st in hba.staticTargetList                               \
         if (st.ipAddress, st.portNumber, st.iqn) not in targetList  \
            and st.bootTarget == 'false'                             \
   ])

   return tasks

def IscsiDoPortBindingTasks(cls, hostServices, configData, taskDict,
                            searchString, replaceString, failOK, logLevel):

   if searchString and taskDict.get('hba'):
      taskDict['hba'] = taskDict['hba'].replace(searchString, replaceString)

   hbaName = taskDict['hba']

   hba = FindIscsiHbaByHbaName(configData, hbaName)
   assert hba != None, 'Could not find the iSCSI adapter instance %s on the system' % hbaName

   vnics = []

   for  policyOpt in taskDict['taskData']:
      if policyOpt['policyOption'] == 'BindVnicByDevice':
         vnics.append(policyOpt['device'])
      elif policyOpt['policyOption'] == 'BindCompatibleVnics':
         vnics.extend(FindCompatibleVnics(hba,
                                          hostServices,
                                          policyOpt['all'],
                                          policyOpt['portgroups']))
      elif policyOpt['policyOption'] == 'BindVnicByIpv4Subnet':
         vnics.extend(FindVnicsByIpv4Subnet(hba,
                                            hostServices,
                                            policyOpt['all'],
                                            policyOpt['ipv4Address'],
                                            policyOpt['ipv4Netmask']))
      elif policyOpt['policyOption'] == 'BindVnicByIpv6Subnet':
         vnics.extend(FindVnicsByIpv6Subnet(hba,
                                            hostServices,
                                            policyOpt['all'],
                                            policyOpt['ipv6Address'],
                                            policyOpt['ipv6Prefix']))
      else:
         assert()

   currVnicList = [vnic for vnic, policyClass, policyArg in hba.boundVnicList]

   newVnicList = vnics

   # if preboot, skip compatiblity check.
   if hostServices.earlyBoot == False:
      newVnicList = EliminateIncompatibleVnics(hba, hostServices, [], vnics)

   # add force flag to bind incompatible vmnic.
   taskSet = CreateBindingConfigTaskFromConfigData(hba, currVnicList, newVnicList,
                                                   hostServices.earlyBoot)

   ExecuteTask(cls, hostServices, configData, taskSet, searchString, replaceString)

   return (0, [])

def EliminateIncompatibleVnics(hba, hostServices, vnicsByDevice, compatibleVnics):
   prunedVnics = []

   # First remove duplicates
   prunedVnics = list(set(compatibleVnics))

   # Should happen only for software iscsi
   if hba.name is None or \
      hba.enabled == False:
      return prunedVnics

   status, lnpList = RunEsxCli(hostServices,
                               ISCSI_INITIATOR_CONFIG_LNP_LIST_CMD % {'hba': hba.name})

   # if postBoot, dvs uplink can still be incompitible, skip checking
   lnpList = [lnp for lnp in lnpList if lnp['Compliant'] == True or \
              hostServices.postBoot == True]

   tmpPrunedVnics = prunedVnics
   prunedVnics = []

   for vnic in tmpPrunedVnics:
      if vnic in [candidateVnics['Vmknic'] for candidateVnics in lnpList]:
            prunedVnics.append(vnic)

   prunedVnics.extend(vnicsByDevice)
   prunedVnics = list(set(prunedVnics))

   return prunedVnics

def GetIscsiBoundVnicList(hba, hostServices):
   iscsiBoundVnicList = []

   status, nps = RunEsxCli(hostServices,
                           ISCSI_INITIATOR_CONFIG_NP_LIST_CMD % {'hba': hba.name})

   for np in nps:
      iscsiBoundVnicList.append((np['Vmknic'], 'BindVnicByDevice', ''))

   return iscsiBoundVnicList

def CreateBindingConfigTaskFromConfigData(hba, currVnicList, newVnicList, earlyBoot):
   tasks = []
   force = "false"

   if earlyBoot == True:
      force = "true"

   # Add the vnics that are in the profile but are not bound to hba
   for vnic in newVnicList:
      if vnic not in currVnicList:
         tasks.append({
               'task': 'ISCSI_INITIATOR_CONFIG_NP_ADD',
               'hba': hba.name,
               'vnic': vnic,
               'force': force,
               'failOK': True,
               'comparisonIdentifier' : ISCSI_PROFILE_PORT_BINDING_PROFILE,
               'hostValue': '',
               'profileValue' : vnic,
               'complianceValueOption' : MESSAGE_KEY
            })

   # Remove the vnics that are not in the profile but are bound to hba
   for vnic in currVnicList:
      if vnic not in newVnicList:
         tasks.append({
               'task': 'ISCSI_INITIATOR_CONFIG_NP_REM',
               'hba': hba.name,
               'vnic': vnic,
               'failOK': True,
               'comparisonIdentifier' : ISCSI_PROFILE_PORT_BINDING_PROFILE,
               'hostValue' : vnic,
               'profileValue' : '',
               'complianceValueOption' : MESSAGE_KEY
            })

   return tasks

def FindCompatibleVnics(hba, hostServices, all, portgroups):
   vnics = []

   if portgroups:
      portgroupList = portgroups.split(',')
   else:
      portgroupList = []

   status, allVnics = RunEsxCli(hostServices, NETWORK_INTERFACE_LIST)

   status, lnpList = RunEsxCli(hostServices,
                               ISCSI_INITIATOR_CONFIG_LNP_LIST_CMD % {'hba': hba.name})

   lnpList = [lnp for lnp in lnpList if lnp['Compliant'] == True]

   for vnic in allVnics:
      if (not portgroups) or vnic['Portgroup'] in portgroupList:
         if vnic['Name'] in [candidateVnics['Vmknic'] for candidateVnics in lnpList]:
            vnics.append(vnic['Name'])
            if all is not True:
               break

   return vnics

def FindVnicsByIpv4Subnet(hba, hostServices, all, ipv4Address, ipv4Netmask):
   vnics = []

   status, output = RunEsxCli(hostServices, NETWORK_GETIPV4_INTERFACES)

   for intf in output:
      if NetworkAddress(intf['IPv4 Address'], intf['IPv4 Netmask']) == \
         NetworkAddress(ipv4Address, ipv4Netmask):
         vnics.append(intf['Name'])
         if all is not True:
            break

   return vnics

def FindVnicsByIpv6Subnet(hba, hostServices, all, ipv6Address, ipv6Prefix):
   vnics = []

   status, output = RunEsxCli(hostServices, NETWORK_GETIPV6_INTERFACES)

   for intf in output:
      if NetworkAddress6(intf['Address'], str(intf['Netmask'])) == \
         NetworkAddress6(ipv6Address, ipv6Prefix):
         vnics.append(intf['Interface'])
         if all is not True:
            break

   return vnics

ISCSI_STATICTARGET_AUTH_ISSETTABLE = 'IsSettableStaticTargetAuth'
ISCSI_STATICTARGET_PARAM_ISSETTABLE = 'IsSettableStaticTargetParam'

ISCSI_DISCOVEREDTARGET_AUTH_ISSETTABLE = 'IsSettableDiscoveredTargetAuth'
ISCSI_DISCOVEREDTARGET_PARAM_ISSETTABLE = 'IsSettableDiscoveredTargetParam'

ISCSI_SENDTARGET_AUTH_ISSETTABLE = 'IsSettableSendTargetAuth'
ISCSI_SENDTARGET_PARAM_ISSETTABLE = 'IsSettableSendTargetParam'

ISCSI_ADAPTER_AUTH_ISSETTABLE = 'IsSettableHbaAuth'
ISCSI_ADAPTER_PARAM_ISSETTABLE = 'IsSettableHbaParam'

def IsSettableHbaParam(cls, hostServices, profileData, keyDict):
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   param = keyDict['key']
   return IsSettable(hba.params[param])

def IsSettableSendTargetParam(cls, hostServices, profileData, keyDict):
   param = keyDict['key']

   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])

   sendTarget = FindSendTargetDiscovery(hba, keyDict['ip'], keyDict['port'], False)

   return IsSettable(sendTarget.params[param])

def IsSettableDiscoveredTargetParam(cls, hostServices, profileData, keyDict):
   return IsSettableTargetParam(cls, hostServices, profileData, keyDict, ISCSI_SEND_TARGETS)

def IsSettableStaticTargetParam(cls, hostServices, profileData, keyDict):
   return IsSettableTargetParam(cls, hostServices, profileData, keyDict, ISCSI_STATIC_TARGETS)

def IsSettableTargetParam(cls, hostServices, profileData, keyDict, targetType):
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])

   ipAddress = keyDict['targetAddress'].rpartition(':')[0]
   portNumber = keyDict['targetAddress'].rpartition(':')[2]
   iqn = keyDict['iqn']
   param = keyDict['key']

   target = FindTarget(targetType, hba, ipAddress, portNumber, iqn, False)

   return IsSettable(target.params[param])

def IsSettableHbaAuth(cls, hostServices, profileData, keyDict):
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   if keyDict['uni']:
      return hba.caps['uniChapSupported']
   elif keyDict['mutual']:
      return hba.caps['mutualChapSupported']

def IsSettableSendTargetAuth(cls, hostServices, profileData, keyDict):
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   sendTarget = FindSendTargetDiscovery(hba, keyDict['ip'], keyDict['port'], False)
   if keyDict['direction'] == 'uni':
      return hba.caps['targetLevelUniAuthSupported']
   elif keyDict['direction'] == 'mutual':
      return hba.caps['targetLevelMutualAuthSupported']

def IsSettableDiscoveredTargetAuth(cls, hostServices, profileData, keyDict):
   return IsSettableTargetAuth(cls, hostServices, profileData, keyDict, ISCSI_SEND_TARGETS)

def IsSettableStaticTargetAuth(cls, hostServices, profileData, keyDict):
   return IsSettableTargetAuth(cls, hostServices, profileData, keyDict, ISCSI_STATIC_TARGETS)

def IsSettableTargetAuth(cls, hostServices, profileData, keyDict, targetType):
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   ipAddress = keyDict['targetAddress'].rpartition(':')[0]
   portNumber = keyDict['targetAddress'].rpartition(':')[2]
   iqn = keyDict['iqn']
   target = FindTarget(targetType, hba, ipAddress, portNumber, iqn, False)
   if keyDict['direction'] == 'uni':
      return hba.caps['targetLevelUniAuthSupported']
   elif keyDict['direction'] == 'mutual':
      return hba.caps['targetLevelMutualAuthSupported']

# Validate if te task should be run or not
def ValidateExecuteTaskPreRequisite(cls, hostServices, profileData, taskDict):
   status = True

   preRequisite = taskDict.get('taskPreRequisite')
   if preRequisite:
      preRequisiteFunc=eval(preRequisite)
      status = eval(preRequisiteFunc)(cls, hostServices, profileData, taskDict)

   return status

def IscsiAddSendTargetProfData(cls, hostServices, profileData, keyDict):
   IscsiLog(4, keyDict, 'IscsiAddSendTargetProfData: ')
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   tmpSendTarget = FindSendTargetDiscovery(hba, keyDict['ip'], keyDict['port'], False)
   if not tmpSendTarget:
      targetAddress = '%s:%s' %(keyDict['ip'], keyDict['port'])
      sendTarget = GetIscsiSendTargetsDiscoveryList(hba, hostServices, {'targetAddress' : targetAddress})
      hba.sendTargetDiscoveryList.extend(sendTarget)
      IscsiLog(4, 'Added: ' + str(keyDict), 'IscsiAddSendTargetProfData: ')

def IscsiAddStaticTargetProfData(cls, hostServices, profileData, keyDict):
   IscsiLog(3, keyDict, 'IscsiAddStaticTargetProfData: ')
   hba = FindIscsiHbaByHbaName(profileData, keyDict['hba'])
   ipAddress = keyDict['targetAddress'].rpartition(':')[0]
   portNumber = keyDict['targetAddress'].rpartition(':')[2]
   iqn = keyDict['iqn']
   tmpTarget = FindTarget(ISCSI_STATIC_TARGETS, hba, ipAddress, portNumber, iqn, False)
   if not tmpTarget:
      target = GetStaticIscsiTargetList(hba, hostServices,
                                           {'iqn' : iqn,
                                            'targetAddress': keyDict['targetAddress']})
      hba.staticTargetList.extend(target)
      IscsiLog(3, 'Added: ' + str(keyDict), 'IscsiAddStaticTargetProfData: ')

# Execute the ESXCLI task present in the Generate Task List
def ExecuteTaskFromDict(cls, hostServices, profileData, taskDict,
                        searchString, replaceString, logLevel):

   taskFunc = taskDict.get('taskFunc')
   failOK = taskDict.get('failOK')

   IscsiLog(logLevel, taskDict, 'ExecuteTaskFromDict: ')

   if not taskFunc:
      newTaskDict = ExpandKeyValues(taskDict)

      if searchString and newTaskDict.get('hba'):
         newTaskDict['hba'] = newTaskDict['hba'].replace(searchString, replaceString)

      if ValidateExecuteTaskPreRequisite(cls, hostServices, profileData, newTaskDict):
         cliCmd = eval(newTaskDict.get('task')+'_CMD') % newTaskDict
         status, output = RunEsxCli(hostServices, cliCmd, failOK == True, logLevel)
         if status == 0:
            postTaskFunc = newTaskDict.get('postTaskFunc')
            if postTaskFunc:
               eval(postTaskFunc)(cls, hostServices, profileData, newTaskDict)
      else:
         IscsiLog(logLevel, 'ExecuteTaskFromDict: Pre Requisite validation result notOK')
   else:
      func = eval(taskFunc)
      status, output = func(cls, hostServices, profileData, taskDict,
                            searchString, replaceString, failOK == True,
                            logLevel)

   return

# Execute the ESXCLI task present in the Generate task list task set
def ExecuteTask(cls, hostServices, profileData, taskSet,
                searchString=None, replaceString=None):

   if len(taskSet) == 0:
      return

   for task in taskSet:
      if isinstance(task, dict):
         ExecuteTaskFromDict(cls, hostServices, profileData, task, searchString, replaceString, 4)
      else:
         assert False, 'ExecuteTask: Encountered invalid task encoding'

   return
