#!/usr/bin/env python

"""
Copyright 2015-2016 VMware, Inc.  All rights reserved.
-- VMware Confidential
This is a stand alone script to kill ghost Vms
"""
__author__ = "VMware, Inc"

import sys
import time
import errno
import fcntl
import logging
import logging.handlers
import argparse


# Create a connection to the local hostd. Returns service instance,
# si.content and the conn objects.
def ConnectToLocalHostd():
   import pyVmomi
   from pyVmomi import vim, vmodl
   from pyVmomi import Csi
   import ssl
   version = "vim.version.version10"
   port = 443
   host = 'localhost'
   # NOTE: limited test with python 3 due to PR 1603030 still open at the time of this change
   sslContext = ssl.create_default_context()
   sslContext.check_hostname = False
   sslContext.verify_mode = ssl.CERT_NONE
   conn = pyVmomi.SoapStubAdapter(host=host, port=port,
                                  version=version, path='/sdk',
                                  sslContext=sslContext)
   si = vim.ServiceInstance("ServiceInstance", conn)
   content = si.RetrieveServiceContent()
   sm = content.sessionManager
   localTicket = sm.AcquireLocalTicket('root')
   pw = open(localTicket.passwordFilePath, 'r').read()
   sm.Login(localTicket.userName, pw)
   return (si, content, conn)


# Create a connection to the local hostd.
# If connection fails, make several retry attempts before exit
def ConnectToLocalHostdWithRetry():
   import time
   MAX_RETRY_TIME = 6
   SLEEP_TIME = 3
   retry_times = 0
   while True:
      try:
         return ConnectToLocalHostd()
      except Exception as ex:
         retry_times += 1
         log.debug("Retry the connection to local hostd..")
         if retry_times == MAX_RETRY_TIME:
            raise
         time.sleep(SLEEP_TIME)


# Check if all objects of a VM are on a vsanDatastore. This is done
# by checking all the datastores in the vm.datastore object
def AreAllVmObjectsOnVsan(vm):
   for ds in vm.datastore:
      if ds.summary.type != "vsan":
         return false
   return True


# Wrapper for Property Collector.
def CollectMultiple(si, objects, parameters, handleNotFound=True):
   import pyVmomi
   from pyVmomi import vim, vmodl
   if len(objects) == 0:
      return {}
   result = None
   pc = si.content.propertyCollector
   propSet = [vim.PropertySpec(
      type=objects[0].__class__,
      pathSet=parameters
   )]

   options = vmodl.Query.PropertyCollector.RetrieveOptions()
   while result == None and len(objects) > 0:
      try:
         objectSet = []
         for obj in objects:
            objectSet.append(vim.ObjectSpec(obj=obj))
         specSet = [vim.PropertyFilterSpec(objectSet=objectSet, propSet=propSet)]
         retrieveRes = pc.RetrievePropertiesEx(specSet=specSet, options=options)
         if retrieveRes:
            result = retrieveRes.objects
            token = retrieveRes.token
            while token:
               retrieveRes = pc.ContinueRetrievePropertiesEx(token)
               result.extend(retrieveRes.objects)
               token = retrieveRes.token
         else:
            break
      except vim.ManagedObjectNotFound as ex:
         objects.remove(ex.obj)
         result = None

   out = {}
   if result is not None:
      for x in result:
         out[x.obj] = {}
         for y in x.propSet:
            out[x.obj][y.name] = y.val
   return out


# Get a list of all VSAN object UUIDs for a VM. Returns a dict of objUuid,
# pathToObject key value pairs.
def GetVmObjUuids(vm, vmsProps):
   import pyVmomi
   from pyVmomi import vim, vmodl
   objUuids = {}
   devices = []
   if 'config.hardware.device' in vmsProps[vm]:
      devices = vmsProps[vm]['config.hardware.device']
   disks = vmsProps[vm]['disks'] = \
      [disk for disk in devices if isinstance(disk, vim.vm.device.VirtualDisk)]
   for disk in disks:
      backing = disk.backing
      while backing:
         objUuids[backing.backingObjectId] = backing.fileName
         backing = backing.parent
   layoutEx = vmsProps[vm]['layoutEx.file']
   for l in layoutEx:
      if l.type == 'config':
         pathName = l.name
         namespaceUuid = vmsProps[vm]['namespaceUuid'] = \
            pathName.split("] ")[1].split("/")[0]
         objUuids[namespaceUuid] = pathName

   log.debug("A list of objects for VM: %s" % vmsProps[vm]['name'])
   log.debug(objUuids)
   return objUuids


# Check if object is accessible from the specified host. Object Accessibility
# is checked by forming a CMMDS query of type CONFIG_STATUS
def IsObjectAccessible(host, obj):
   import pyVmomi
   from pyVmomi import vim, vmodl
   import json
   vis = host.configManager.vsanInternalSystem
   cmmdsQuery = vim.host.VsanInternalSystem.CmmdsQuery()
   cmmdsQuery.type = 'CONFIG_STATUS'
   cmmdsQuery.uuid = obj
   try:
      result = json.loads(vis.QueryCmmds([cmmdsQuery]))
   except Exception as ex:
      log.debug("Failed to check CMMDS state for object %s: %s" %
                (obj, str(ex)))
      # In case of cmmds error, we cannot assume object is inaccessible
      # as it may end up killing some healthy VMs.
      return True
   log.debug(result)
   if not result['result']:
      return False
   if result['result'][0]['health'] != "Healthy":
      return False
   state = result['result'][0]['content']['state']
   if state & 3 == 3:
      return True
   else:
      return False

# Check and find inaccessible VMs
def CheckAndFindInaccessibleVms(si, host, vms):
   vmsAccessibility, vmsProps = IsVmFullyInaccessible(si, host, vms)
   inaccessibleVms = []
   accessibleVms = []
   for vm in vmsAccessibility:
      for k, v in list(vm.items()):
         if v:
            inaccessibleVms.append(k)
         #elseif for unknown accessibility information
         else:
            accessibleVms.append(k)
   return inaccessibleVms


# Check if all objects of a VM are inaccessible
def IsVmFullyInaccessible(si, host, vms):
   try:
      properties = ['name', 'datastore', 'config.hardware.device',\
                    'layoutEx.file']
      vmsProps = CollectMultiple(si, vms, properties)
      vmInAccessible = []
      for vm in vms:
         try:
            vmObjUuids = list(GetVmObjUuids(vm, vmsProps).keys())
            if not AreAllVmObjectsOnVsan(vm):
               log.debug("Some object(s) is not backed by VSAN for VM: %s" \
                         % vmsProps[vm]['name'])
               vmInAccesible.append({vm : False})
            else:
               inaccessible = True
               for obj in vmObjUuids:
                  if IsObjectAccessible(host, obj):
                     inaccessible = False
                     break
               vmInAccessible.append({vm : inaccessible})
         except Exception as ex:
            log.warning("Unable to get vmAccessibility information for VM: %s" \
                        " on object: %s" \
                        % (vmsProps[vm]['name'], obj))
            log.exception(ex)
            vmInAccessible.append({vm : False})

      return vmInAccessible, vmsProps
   except Exception as ex:
      log.error("Failed to get accessibility information for vms: %s" % ex)
      raise Exception("Failed to get accessibility information for vms: %s"
                      % str(ex))


# Get vm metadata info from local disk
def GetVmMetadataFromDisk():
   import os
   import xml.etree.ElementTree as ET

   VM_METADATA_TMP_FILE_PATH = "/tmp/vmmetadata.txt"
   VM_METADATA_XML_TMP_FILE_PATH = "/tmp/vmmetadataXml.txt"

   READ_FDM_VM_METADATA_TO_FILE_CMD = "/opt/vmware/fdm/fdm/readCompressed -e \
      /etc/opt/vmware/fdm/vmmetadata > %s" % VM_METADATA_TMP_FILE_PATH
   # Skip 1st line(it's a number)
   REMOVE_1st_LINE_FROM_FILE_CMD = "/bin/tail -n +2 %s > %s" \
      % (VM_METADATA_TMP_FILE_PATH, VM_METADATA_XML_TMP_FILE_PATH)
   REMOVE_VM_METADATA_TMP_FILE_CMD = "/bin/rm %s" % VM_METADATA_TMP_FILE_PATH
   REMOVE_VM_METADATA_XML_TMP_FILE_CMD = "/bin/rm %s" \
                                         % VM_METADATA_XML_TMP_FILE_PATH

   DICTIONARY_ELEM_NAME = "{urn:csi}dictionary"
   DICTIONARY_VM_ELEM_NAME = "{urn:csi}vms"
   DICTIONARY_VM_NAME_ELEM_NAME = '{urn:csi}name'

   log.info("Get vm metadata from disk")
   os.system(READ_FDM_VM_METADATA_TO_FILE_CMD)
   os.system(REMOVE_1st_LINE_FROM_FILE_CMD)

   tree = ET.parse(VM_METADATA_XML_TMP_FILE_PATH)
   root = tree.getroot()
   dictElem = root.find(DICTIONARY_ELEM_NAME)
   haProtectedVmxNames = []
   for dictChild in dictElem:
      if dictChild.tag == DICTIONARY_VM_ELEM_NAME:
         vmNameElem = dictChild.find(DICTIONARY_VM_NAME_ELEM_NAME)
         haProtectedVmxNames.append(vmNameElem.text.split("/")[-1])

   # clean up the temporary files
   os.system(REMOVE_VM_METADATA_TMP_FILE_CMD)
   os.system(REMOVE_VM_METADATA_XML_TMP_FILE_CMD)

   return haProtectedVmxNames


# Get clusterconfig info from local disk
def GetClusterConfigFromDisk(poweredOnVms, vmsProps):
   import os
   import xml.etree.ElementTree as ET

   CLUSTER_CONFIG_TMP_FILE_PATH = "/tmp/clusterconfig.txt"
   CLUSTER_CONFIG_XML_TMP_FILE_PATH = "/tmp/clusterconfigXml.txt"

   READ_FDM_CLUSTER_CONFIG_TO_FILE_CMD = "/opt/vmware/fdm/fdm/readCompressed -e\
      /etc/opt/vmware/fdm/clusterconfig > %s" % CLUSTER_CONFIG_TMP_FILE_PATH
   # Skip 1st line(it's a number)
   REMOVE_1st_LINE_FROM_FILE_CMD = "/bin/tail -n +2 %s > %s" \
      % (CLUSTER_CONFIG_TMP_FILE_PATH, CLUSTER_CONFIG_XML_TMP_FILE_PATH)
   REMOVE_CLUSTER_CONFIG_TMP_FILE_CMD = "/bin/rm %s" \
                                           % CLUSTER_CONFIG_TMP_FILE_PATH
   REMOVE_CLUSTER_CONFIG_XML_TMP_FILE_CMD = "/bin/rm %s" \
                                            % CLUSTER_CONFIG_XML_TMP_FILE_PATH

   DASCONFIG_ELEM_NAME = "{urn:csi}dasConfig"
   DASCONFIG_DEFAULTVMSETTINGS_ELEM_NAME = "{urn:csi}defaultVmSettings"
   DASCONFIG_DEFAULTVMSETTINGS_RESTARTPRIORITY_ELEM_NAME =\
      "{urn:csi}restartPriority"
   DASVMCONFIG_ELEM_NAME = "{urn:csi}dasVmConfig"
   DASVMCONFIG_CFGFILEPATH_ELEM_NAME = "{urn:csi}cfgFilePath"
   DASVMCONFIG_DASSETTINGS_ELEM_NAME = "{urn:csi}dasSettings"
   DASVMCONFIG_RESTARTPRIORITY_ELEM_NAME = "{urn:csi}restartPriority"

   os.system(READ_FDM_CLUSTER_CONFIG_TO_FILE_CMD)
   os.system(REMOVE_1st_LINE_FROM_FILE_CMD)

   tree = ET.parse(CLUSTER_CONFIG_XML_TMP_FILE_PATH)
   root = tree.getroot()

   # Get cluster level vm restart priority
   dasConfigElem = root.find(DASCONFIG_ELEM_NAME)
   dasConfigDefaultVmSettingsElem = dasConfigElem.find(
      DASCONFIG_DEFAULTVMSETTINGS_ELEM_NAME)
   dasConfigDefaultVmSettingsRestartPriorityElem =\
      dasConfigDefaultVmSettingsElem.find(
         DASCONFIG_DEFAULTVMSETTINGS_RESTARTPRIORITY_ELEM_NAME)
   clusterRestartPriority = dasConfigDefaultVmSettingsRestartPriorityElem.text
   log.info("Cluster level restart priority setting: %s"
            % clusterRestartPriority)

   haDisabledVmxNames = set()
   HA_RESTART_PRIORITY_DISABLED = "disabled"

   if clusterRestartPriority.lower() == HA_RESTART_PRIORITY_DISABLED:
      log.info("Default vm policy is HA disabled.")
      for vm in poweredOnVms:
         haDisabledVmxNames.add(GetVmxName(vm, vmsProps))

   # Get a list of HA disabled vms according to restart priority
   # By default, the VM restart priority for all VMs is set to medium.
   # VM's restart priorities can be overridden by DAS VM settings.
   # If a VM level override has been configured for a certain VM,
   # dasVmConfig field will be present in the HA cluster config file.
   # Please see PR 2001952 update #43 for details.
   log.debug("A list of vm config name along with its restart priority.")
   for child in root.getchildren():
      if child.tag == DASVMCONFIG_ELEM_NAME:
         # Get VM config path and vmx name
         dasVmConfigCfgFilePathElem = child.find(
            DASVMCONFIG_CFGFILEPATH_ELEM_NAME)
         vmConfigPath = dasVmConfigCfgFilePathElem.text
         vmxName = vmConfigPath.split("/")[-1]

         # Get VM restart priority
         dasVmConfigRestartPriorityElem = child.find(
            DASVMCONFIG_RESTARTPRIORITY_ELEM_NAME)
         # If vmRestartPriority cannot be found under dasVmConfig,
         # get vmRestartPriority under dasSettings.
         if dasVmConfigRestartPriorityElem is None:
            dasVmConfigDasSettings = child.find(
               DASVMCONFIG_DASSETTINGS_ELEM_NAME)
            dasVmConfigRestartPriorityElem = dasVmConfigDasSettings.find(
               DASVMCONFIG_RESTARTPRIORITY_ELEM_NAME)
         vmRestartPriority = dasVmConfigRestartPriorityElem.text

         if vmRestartPriority == HA_RESTART_PRIORITY_DISABLED:
            if vmxName not in haDisabledVmxNames:
               haDisabledVmxNames.add(vmxName)
         else: # per vm level HA enabled
            if vmxName in haDisabledVmxNames:
               haDisabledVmxNames.remove(vmxName)

         log.debug("\tVM config: %s, restartPriority: %s"
                   % (vmxName, vmRestartPriority))

   # clean up the temporary files
   os.system(REMOVE_CLUSTER_CONFIG_TMP_FILE_CMD)
   os.system(REMOVE_CLUSTER_CONFIG_XML_TMP_FILE_CMD)

   return haDisabledVmxNames


def GetVmxName(vm, vmsProps):
   layoutEx = vmsProps[vm]['layoutEx.file']
   for l in layoutEx:
      if l.type == 'config':
         vmPath = l.name
         vmxName = vmPath.split("/")[-1]
         return vmxName
   return ""


# Return a list of all powered on VMs running on VSAN
# and protected by HA
def FilterOutVms(si, dc):
   import pyVmomi
   from pyVmomi import vim, vmodl
   try:
      vsanDs = None
      datastores = dc.datastore

      # Check if VSAN datastore is mounted on host
      dsProps = CollectMultiple(si, datastores, ['summary.type'])
      for ds in datastores:
         if dsProps[ds]['summary.type'] == 'vsan':
            vsanDs = ds
            break

      if not vsanDs:
         return []

      # Get powered-on vms
      vms = vsanDs.vm
      vmsProps = CollectMultiple(si, vms, ['runtime.powerState',
                                           'layoutEx.file'])
      poweredOnVms = [vm for vm in vms if \
                      vmsProps[vm]['runtime.powerState'] == "poweredOn"]
      log.debug("Following VMs are found running on this host.")
      log.debug("\t* %s" % [vm.name for vm in poweredOnVms])

      # Get HA disabled vms
      haClusterUnprotectedVmxNames = \
         GetClusterConfigFromDisk(poweredOnVms, vmsProps)
      log.debug("Following VMs are NOT HA protected at cluster wide.")
      log.debug("\t* %s" % haClusterUnprotectedVmxNames)

      # Filter out HA protected vms on the host
      haHostProtectedVms = [vm for vm in poweredOnVms   \
                            if GetVmxName(vm, vmsProps) \
                            not in haClusterUnprotectedVmxNames]

      return haHostProtectedVms
   except Exception as ex:
      log.error("Could not get list of vms: %s " % str(ex))
      log.exception(ex)
      raise


# Check if VSAN is enabled on specified host.
def IsVsanEnabledOnHost(si, host):
   try:
      vs = host.configManager.vsanSystem
      return vs.config.enabled
   except Exception as ex:
      log.error("Could not get vsan info on host: %s" % str(ex))
      log.exception(ex)
      exit(1)


# Check if HA is enabled on host.
def IsHaEnabledOnHost(si, host):
   haEnabled = False
   try:
      serviceProps = CollectMultiple(si, [host], ['config.service'])
      for svc in serviceProps[host]['config.service'].service:
         if svc.key == "vmware-fdm":
            haEnabled = svc.running
            break
      return haEnabled
   except Exception as ex:
      log.error("Could not get HA info on host: %s" % str(ex))
      log.exception(ex)
      exit(1)


# Check if host is in stretched cluster.
def IsHostInStretchedCluster(si, host):
   import pyVmomi
   from pyVmomi import vim, DynamicTypeManagerHelper
   try:
      ESXCLI_VSAN_CLUSTER_UNICASTAGENT_MOID =\
         'ha-cli-handler-vsan-cluster-unicastagent'
      ti = pyVmomi.DynamicTypeManagerHelper.DynamicTypeImporter(host._stub,
                                                                host)
      ti.ImportTypes("vim.EsxCLI.vsan.cluster")
      ti.ImportTypes("vim.EsxCLI.vsan.cluster.unicastagent")
      ti.ImportTypes("vim.EsxCLI.CLIFault")
      mo = vim.EsxCLI.vsan.cluster.unicastagent(
              ESXCLI_VSAN_CLUSTER_UNICASTAGENT_MOID,
              si._stub)
      uaList = mo.List()
      if uaList:
         hasWitness = 0
         for ua in uaList:
            hasWitness = hasWitness or ua.IsWitness
         return hasWitness
      else:
         return False
   except Exception as ex:
      log.error("Caught exception while querying unicast agent: %s."
                % str(ex))
      log.exception(ex)
      exit(1)


# Terminate specified VMs using the vm.TerminateVM() api
def TerminateVms(vms):
   log.info("Start terminating VMs.")
   for vm in vms:
      try:
         vm.TerminateVM()
         log.info("Successfully terminated inaccessible VM: %s" % vm.name)
      except Exception as ex:
         log.exception("Failed to terminate VM: %s" % vm.name)
         log.exception("Exception %s" % ex)


# Check if script is run in auto-mode
def IsAutoModeOn():
   return args.auto


# Main function for the terminateInaccessibleVms script
def DoWork():
   si, content, conn = ConnectToLocalHostdWithRetry()
   dc = si.content.rootFolder.childEntity[0]
   host = dc.hostFolder.childEntity[0].host[0]

   try:
      if not IsVsanEnabledOnHost(si, host):
         log.error("VSAN not enabled on host. Exiting..")
         exit(0) # normal exit
      if not IsHaEnabledOnHost(si, host):
         log.error("HA is not enabled on host. Exiting..")
         exit(0) # normal exit
      if not IsHostInStretchedCluster(si, host):
         log.error("Host is not in stretched cluster. Exiting..")
         exit(0) # normal exit

      vms = FilterOutVms(si, dc)
      log.info("Following VMs are powered on and HA protected in this host.")
      log.info("\t* %s" % [vm.name for vm in vms])

      if len(vms) == 0:
         log.info("Could not find any VMs running on VSAN that are "
                  "powered on and HA protected. Exiting...")
         exit(0) # normal exit

      # Issue multiple rounds of check for inaccessible VMs to avoid the false
      # kills in case some inaccessible VM come back when the cluster is not
      # stable. (c.f. PR#1674567)
      numRounds = 0
      inaccessibleVms = []
      inaccessibleVmsCandidate = vms
      while True:
         inaccessibleVms = CheckAndFindInaccessibleVms(si, host,
                                                       inaccessibleVmsCandidate)
         if len(inaccessibleVms) == 0:
            log.info("Could not find any VMs running on VSAN with all "
                     "objects inaccessible. Exiting...")
            exit(0) # normal exit
         inaccessibleVmsCandidate = inaccessibleVms
         log.info("List inaccessible VMs at round %d" % (numRounds + 1))
         log.info("\t* %s" % inaccessibleVms)
         numRounds += 1
         if numRounds == MAX_ITR_ROUNDS:
            break
         time.sleep(APD_TIME_OUT_SEC)

      log.info("Following VMs are found to have all objects inaccessible, "
               "and will be terminated.")
      log.info("\t* %s" % inaccessibleVms)

      # Give user prompt if manual mode is on
      if not IsAutoModeOn():
         msg = ("The VM's listed above have all of their objects inaccessible"
                " on VSAN. If these VM's are vSphere HA protected and if there"
                " are enough resources in the cluster, these VM's will be"
                " powered on by vSphere HA. Please ensure these VM's have been"
                " protected by vSphere HA before proceeding. Terminate will"
                " uncleanly power off these VM's.")
         log.info(msg)
         answer = raw_input('Proceed to terminate?(y/[n]): ')
         if answer.lower() != "y":
            log.info("Exiting...")
            exit(0) # user abort

      TerminateVms(inaccessibleVms)
   finally:
      content.sessionManager.Logout()


# Non-blocking lock
class NbLock:
   def __init__(self, lockfile):
      self.lockfile = lockfile
      self.fd = open(self.lockfile, 'w')

   def acquire(self):
      fcntl.lockf(self.fd, fcntl.LOCK_EX|fcntl.LOCK_NB)

   def release(self):
      fcntl.lockf(self.fd, fcntl.LOCK_UN)

   def __del__(self):
      self.fd.close()


# Blocking lock with a timeout
class TimeoutLock:
   def __init__(self, lockfile, timeout):
      self.lockfile = lockfile
      self.fd = open(self.lockfile, 'w')
      self.timeout = timeout

   def acquire(self):
      for i in range(self.timeout):
         try:
            fcntl.lockf(self.fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            return # lock is freed
         except IOError:
            pass
         time.sleep(1) # sleep UNIT
      raise IOError("Timeout acquiring the lock %s" % self.lockfile)

   def release(self):
      fcntl.lockf(self.fd, fcntl.LOCK_UN)

   def __del__(self):
      self.fd.close()


if __name__ == '__main__':

   # Parse passed-in args
   desc = """Terminate fully inaccessible VMs on VSAN datastore.
             This script is used to specifically handle the ghost vm scenario
             in stretched cluster. Please find more details in KB:
             http://kb.vmware.com/kb/2135952"""
   parser = argparse.ArgumentParser(description=desc)
   autoDesc = "Terminate ghost vms without user prompt"
   parser.add_argument('--auto', action='store_true', help = autoDesc)
   args = parser.parse_args()

   # Setup Loggers
   log = logging.getLogger('TerminateGhostVms')
   log.level = logging.INFO

   # Add syslog handler
   shFormatter = logging.Formatter('%(filename)s [%(levelname)s]: %(message)s')
   sh = logging.handlers.SysLogHandler(address='/dev/log')
   sh.setLevel(logging.INFO)
   sh.setFormatter(shFormatter)
   log.addHandler(sh)

   if not IsAutoModeOn():
      # Add Strem handler
      chFormatter = logging.Formatter('%(message)s')
      ch = logging.StreamHandler()
      ch.setLevel(logging.INFO)
      ch.setFormatter(chFormatter)
      log.addHandler(ch)

   WAIT_TIME = 20
   INIT_TIME = 10
   LOCK_TIMEOUT = 300
   WAIT_LOCK_NAME = "/var/run/ghost-vm.wl"
   RUN_LOCK_NAME = "/var/run/ghost-vm.rl"
   MAX_ITR_ROUNDS = 2
   APD_TIME_OUT_SEC = 30

   try:
      if IsAutoModeOn():
         # Phase I - wait to batch the events
         wl = NbLock(WAIT_LOCK_NAME)
         try:
            wl.acquire()
            log.info("Start batching process")
            time.sleep(WAIT_TIME)
            log.info("Waited for %d seconds" % WAIT_TIME)
         except Exception as ex:
            if isinstance(ex, IOError) and \
               (ex.errno == errno.EACCES or ex.errno == errno.EAGAIN):
               log.warning("Another instance is holding wait lock, "
                           "and will scan/terminate fully inaccessible VMs, "
                           "so this script does not need to run.")
               sys.exit(0) # normal exit when retrying the lock
            else:
               log.error("Failed to wait the events because of "
                         "unknown reasons: %s" % str(ex))
               log.exception(ex)
               sys.exit(2) # unknown failure
         finally:
            wl.release()

         # Phase II - run the script
         rl = TimeoutLock(RUN_LOCK_NAME, LOCK_TIMEOUT)
         try:
            rl.acquire()
            log.info("Start init process")
            time.sleep(INIT_TIME)
            log.info("Inited for %d seconds" % INIT_TIME)
            log.info("Start to kill the ghost vms if any")
            DoWork()
            log.info("Finished killing the ghost vms")
         except Exception as ex:
            log.error("Failed to kill the ghost vms: %s" % str(ex))
            log.exception(ex)
            sys.exit(3) # unknown failure
         finally:
            rl.release()
      else:
         # Script run in manual-mode
         DoWork()
   except Exception as ex:
      log.info("Caught failure while running the script: %s" % str(ex))
      log.exception(ex)
      sys.exit(1) # unkown failure

