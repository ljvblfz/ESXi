#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import os.path
from pluginApi import log, CreateLocalizedException, \
                      CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_HOSTSPEC_CONFIG
from pluginApi.extensions import SimpleConfigProfile
import pyVmomi
from pyVmomi import Vim, Vmodl, types, SoapAdapter
from hpCommon.utilities import IsFeatureEnabled

dvsManager = None

HOSTSPEC_CONFIG_LOCATION = '/etc/vmware/hostspec/'
dvsVersionDict = {'1':'5.0.0',
                  '2':'5.1.0',
                  '3':'5.5.0',
                  '4':'6.0.0',
                  '5':'6.5.0',
                  '6':'6.6.0'}

class HostSpecConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages creation of DVS on ESX at post boot time.
   """
   # Define required class attributes
   parameters = []
   singleton = True
   alwaysRemediate = False

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_HOSTSPEC_CONFIG

   @classmethod
   def GetDVPortGroupSpecs(cls, dvsPortGroupSpec):
      """Given the spec read from hostSpec framework,
         form the dvs portgroup config spec
      """
      cfg = \
         Vim.Dvs.HostDistributedVirtualSwitchManager.DVPortgroupConfigSpec()
      cfg.SetKey(dvsPortGroupSpec.key)
      cfg.SetOperation('add')
      # Generate the spec.
      dvPgspec = Vim.Dvs.DistributedVirtualPortgroup.ConfigSpec()
      dvPgspec.SetName(dvsPortGroupSpec.specification.name)
      dvPgspec.SetType(dvsPortGroupSpec.specification.type)
      policy = Vim.Dvs.DistributedVirtualPortgroup.PortgroupPolicy(
                  blockOverrideAllowed=False,
                  livePortMovingAllowed=True,
                  portConfigResetAtDisconnect=False,
                  shapingOverrideAllowed=False,
                  vendorConfigOverrideAllowed=False)
      dvPgspec.SetNumPorts(16)
      dvPgspec.SetPolicy(policy)
      cfg.SetSpecification(dvPgspec)
      return cfg

   @classmethod
   def ConfigureDvsOnHost(cls, dvsConfigSpec):
      status = True
      try:
         dvsManager.ApplyDvs([dvsConfigSpec])
      except Vmodl.MethodFault as e:
         log.error('ApplyDvs(' + dvsConfigSpec.uuid + ') fail in hostd: [' \
                   + str(e) + '].')
         status = False
      except Exception as e:
         log.error('ApplyDvs(' + dvsConfigSpec.uuid + ') failed in hostd: [' \
                   + e.__class__.__name__ + ":" + str(e) + '].')
         status = False
      except:
         log.error('ApplyDvs(' + dvsConfigSpec.uuid + ') failed ' \
                   'in hostd: [unknown exception].')
         status = False
      return status

   @classmethod
   def ConfigureSubSpecDataOnHost(cls, dvsVersion, dvsSpec, dvsPortSpec,
                                  dvsPortGroupSpec, vendorId):
      if not dvsSpec:
         log.error('Error configuring host spec: dvsSpec is empty.')
         return

      if not dvsPortSpec:
         log.warn('DVPort spec is empty, no ports to add.')
         return

      if dvsVersion not in dvsVersionDict:
         log.info('DVS version %s not support, vendorId %s' % \
                  (dvsVersion, vendorId))
         return
      # Frame the dvs create spec from dvsSpec
      testProductSpec = Vim.Dvs.ProductSpec(
                        forwardingClass=vendorId,
                        vendor="VMware",
                        version=dvsVersionDict[dvsVersion]
      )

      # For older versions of dvs, the ports need to be
      # created first time while creating the DVS itself.
      # hence just create the port at this time and later
      # apply properties via ApplyDVPort()
      dvPorts = []
      for dvPort in dvsPortSpec:
         dvPorts.append(dvPort)

      testDvsSpec = Vim.Dvs.HostDistributedVirtualSwitchManager.DVSCreateSpec(
         uuid=dvsSpec.uuid,
         name=dvsSpec.name,
         backing = Vim.Dvs.HostMember.PnicBacking(),
         port = dvPorts,
         uplinkPortKey=dvsSpec.uplinkPortKey,
         uplinkPortgroupKey=dvsSpec.uplinkPortgroupKey,
         maxProxySwitchPorts=dvsSpec.maxProxySwitchPorts,
         switchIpAddress=dvsSpec.switchIpAddress,
         vendorSpecificDvsConfig=dvsSpec.vendorSpecificDvsConfig,
         vendorSpecificHostMemberConfig =
            dvsSpec.vendorSpecificHostMemberConfig,
         healthCheckConfig=dvsSpec.healthCheckConfig,
         vmwareSetting=dvsSpec.vmwareSetting,
         enableNetworkResourceManagement =
            dvsSpec.enableNetworkResourceManagement,
         networkResourcePoolKeys=dvsSpec.networkResourcePoolKeys,
         modifyVendorSpecificDvsConfig=True,
         uplinkPortResourceSpec=dvsSpec.uplinkPortResourceSpec,
         hostInfrastructureTrafficResource =
            dvsSpec.hostInfrastructureTrafficResource,
         networkResourceControlVersion = dvsSpec.networkResourceControlVersion,
         pnicCapacityRatioForReservation =
            dvsSpec.pnicCapacityRatioForReservation,
         status=dvsSpec.status,
         statusDetail=dvsSpec.statusDetail,
         modifyVendorSpecificHostMemberConfig=True,
         productSpec=testProductSpec,
         keyedOpaqueDataList=dvsSpec.keyedOpaqueDataList,
         hostOpaqueDataList=dvsSpec.hostOpaqueDataList,
         dvsOpaqueDataList=dvsSpec.dvsOpaqueDataList
      )

      # step 1: create the dvs using the newly created spec
      status = cls.ConfigureDvsOnHost(testDvsSpec)
      if not status:
         log.error('DVS creation failed first time [%s].', dvsSpec.uuid)
         return

      # step 2: create portgroups on the host
      dvPGSpec = []
      if not dvsPortGroupSpec or not dvsPortGroupSpec[0]:
         log.info('DVPortgroup spec is empty, no ports to add.')
      else:
         for spec in dvsPortGroupSpec[0]:
            dvPGSpec.append(cls.GetDVPortGroupSpecs(spec))
         try:
            dvsManager.ApplyDVPortgroup(dvsSpec.uuid, dvPGSpec)
         except Vmodl.MethodFault as e:
            log.error('ApplyDVPortgroup(' + dvsSpec.uuid + ') failed in: ' \
                      'hostd [' + str(e) + '].')
         except Exception as e:
            log.error('ApplyDVPortgroup(' + dvsSpec.uuid + ') failed in ' \
                      'hostd: [' + e.__class__.__name__ + ':' + str(e) + '].')
         except:
            log.error('ApplyDVPortgroup(' + dvsSpec.uuid + ') failed in ' \
                      'hostd [unknown exception].')

      # step 3: configure dv ports on the host
      if not dvsPortSpec:
         log.info('DVPort spec is empty, no ports to add.')
         return
      try:
         dvsManager.ApplyDVPort(dvsSpec.uuid, dvsPortSpec)
      except Vmodl.MethodFault as e:
         log.error('ApplyDVPort(' + dvsSpec.uuid + ') failed in hostd: [' \
                   + str(e) + '].')
      except Exception as e:
         log.error('ApplyDVPort(' + dvsSpec.uuid + ') failed in hostd: [' \
                   + e.__class__.__name__ + ':' + str(e) + '].')
      except:
         log.error('ApplyDVPort(' + dvsSpec.uuid + ') failed in' \
                   ' hostd: [unknown exception].')

      # step 4: update the dvs config spec with newly configured port and
      # portgroup info
      dvsSpecConfig = Vim.Dvs.HostDistributedVirtualSwitchManager.DVSCreateSpec(
         uuid = dvsSpec.uuid,
         uplinkPortKey=dvsSpec.uplinkPortKey,
         uplinkPortgroupKey=dvsSpec.uplinkPortgroupKey,
         productSpec=testProductSpec,
      )
      status = cls.ConfigureDvsOnHost(dvsSpecConfig)
      if not status:
         log.error('DVS [%s] creation failed.', dvsSpec.uuid)
         return

   @classmethod
   def _SetGivenConfig(cls, hostServices):
      """Internal method that will read the hostspec config for
         every dvs and configure on the host.
      """
      global dvsManager
      status = None
      try:
         internalContent = hostServices._si.RetrieveInternalContent()
         dvsManager = internalContent.hostDistributedVirtualSwitchManager
      except:
         log.error('Unable to get dvs manager from hostd. Returning')
         return

      # step.1 check if there are any hostSpec saved, if not, exit
      try:
         fileList = os.listdir(HOSTSPEC_CONFIG_LOCATION)
         if not fileList:
            log.info('HostSpecConfig: no host sub specs found, returning.')
            return

         for subSpecFile in fileList:
            # Read the entire content
            fd = open(os.path.join(HOSTSPEC_CONFIG_LOCATION,subSpecFile), 'r')
            # step 2: Read the contents and configure the host
            # Each individual specs that can be configured separately
            # are separated by a tag <hostsubspec> in the subspec file
            dvsSpec_arr = fd.read().split("<hostsubspec>")
            if not dvsSpec_arr:
               log.warn('Empty dvs spec for %s' % subSpecFile)
               continue

            dvsSpec = None
            dvsPortSpec = []
            dvsPortGroupSpec = []
            # the last parsed value is always vendorId
            # For old version hostSpec didn't save vendorId
            # Use the default vendorId "etherswitch"
            vendorId = 'etherswitch'

            # the first parsed value is always version
            dvsVersion = dvsSpec_arr[0]
            for dvsSpecObj in dvsSpec_arr:
               if "HostDVSConfigSpec" in dvsSpecObj:
                  dvsSpec = SoapAdapter.Deserialize(dvsSpecObj)
               elif "HostDVSPortData" in dvsSpecObj:
                  dvsPortSpec.append(SoapAdapter.Deserialize(dvsSpecObj))
               elif "HostDVPortgroupConfigSpec" in dvsSpecObj:
                  dvsPortGroupSpec.append(SoapAdapter.Deserialize(dvsSpecObj))
               elif "forwardingClass:" in dvsSpecObj:
                  vendorId = dvsSpecObj[dvsSpecObj.find(':') + 1:]

            log.info("DVS version %s, vendorId %s" % (dvsVersion, vendorId))
            cls.ConfigureSubSpecDataOnHost(dvsVersion, dvsSpec, dvsPortSpec,
               dvsPortGroupSpec, vendorId)
            fd.close()
      except Exception as e:
         log.error('Failed to parse hostspec: ' +  e.__class__.__name__ + \
                   ': ' + str(e))
         return

   @classmethod
   def ExtractConfig(cls, hostServices):
      """Execute is no-op for this profile
      """
      # implementation of extract config is no-op since this
      # profile is used only at post boot
      return dict()

   @classmethod
   def SetConfig(cls, config, hostServices):
      """For the hostspec profile, the config parameter can be ignored.
         It is read from /etc/vmware/hostspec/* files.
      """
      if not hostServices.postBoot:
         log.debug('HostSpecConfig plugin invoked only for post boot apply')
         return
      config = cls._SetGivenConfig(hostServices)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      if hostServices.postBoot:
         cls.alwaysRemediate = True
      else:
         cls.alwaysRemediate = False
      super(HostSpecConfigProfile, cls).GenerateTaskList(profileInstances,
         taskList, hostServices, profileData, parent)
