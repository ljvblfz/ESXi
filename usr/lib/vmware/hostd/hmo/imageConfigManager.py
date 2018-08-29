#!/usr/bin/env python
"""
Copyright 2016-2017 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

from pyVmomi import vim, vmodl
from pyVmomi import VmomiSupport
import common
from syslog import *
from optparse import OptionParser
from contrib.vorb import VmomiOrb
import subprocess as sb
from vmware.esximage import HostImage
from vmware.esximage import Vib
from vmware.esximage import Version
import datetime

ESXIMG_LEVEL_TO_VMODL = {
   Vib.ArFileVib.ACCEPTANCE_CERTIFIED:
      vim.host.ImageConfigManager.AcceptanceLevel.vmware_certified,
   Vib.ArFileVib.ACCEPTANCE_ACCEPTED:
      vim.host.ImageConfigManager.AcceptanceLevel.vmware_accepted,
   Vib.ArFileVib.ACCEPTANCE_PARTNER:
      vim.host.ImageConfigManager.AcceptanceLevel.partner,
   Vib.ArFileVib.ACCEPTANCE_COMMUNITY:
      vim.host.ImageConfigManager.AcceptanceLevel.community,
   }

VMODL_TO_ESXIMG_LEVEL = dict((v, k) for k, v in ESXIMG_LEVEL_TO_VMODL.items())


def lmsg(s):
   return vmodl.LocalizableMessage(message=str(s))


# Implementation of the vim.host.ImageConfigManager managed object
#
# TODO: Integrate with DMS and EsxCLI (see cpuSchedulerSystem.py).
# Today that isn't possible since esximage stuff uses pyJack and is not
# integrated into the local CLI.   -evan 6/16/10
#
class ImageConfigManagerImpl(common.ExtensibleMOImpl,
                             vim.host.ImageConfigManager):
   def __init__(self, moId='ha-image-config-manager-py'):
      common.ExtensibleMOImpl.__init__(self)
      vim.host.ImageConfigManager.__init__(self, moId)
      self.himg = HostImage.HostImage()

   def QueryHostAcceptanceLevel(self):
      """@see vim.host.ImageConfigManager.queryHostAcceptanceLevel """
      level = self.himg.GetHostAcceptance()
      try:
         return ESXIMG_LEVEL_TO_VMODL[level]
      except:     # level is None, invalid host config
         msg = "Invalid host acceptance level configuration"
         raise vim.fault.HostConfigFault(faultMessage=[lmsg(msg)])

   def QueryHostImageProfile(self):
      """@see vim.host.ImageConfigManager.queryHostImageProfile """
      prof = self.himg.GetProfile()
      ipinfo = vim.host.ImageConfigManager.ImageProfileSummary()
      if prof:
         ipinfo.name = prof.name
         ipinfo.vendor = prof.creator
      else:
         ipinfo.name = "<Unknown - no profile defined>"
         ipinfo.vendor = "<Unknown>"
      return ipinfo

   def UpdateAcceptanceLevel(self, newAcceptanceLevel):
      """Sets the new host acceptance level setting.
         @see vim.host.ImageConfigManager.updateAcceptanceLevel
      """
      if newAcceptanceLevel not in VMODL_TO_ESXIMG_LEVEL:
         msg = "Cannot set acceptance level to illegal value '%s'" % (newAcceptanceLevel)
         raise vim.fault.HostConfigFault(faultMessage=[lmsg(msg)])
      try:
         self.himg.SetHostAcceptance(VMODL_TO_ESXIMG_LEVEL[newAcceptanceLevel])
      except Exception as e:
         raise vim.fault.HostConfigFault(faultMessage=[lmsg(e)])

   def _ToVmomiStringArray(self, values):
      """Return VMOMI array of strings.
      """
      if values is None or not len(values):
         return None
      else:
         ArrayOfString = VmomiSupport.GetVmodlType('string[]')
         return ArrayOfString([str(item) for item in values])

   def _SetContraint(self, operator):
      """Convert constraing operator between esximage and vmodl.
      """
      if operator == "=":
        return "equals"
      elif operator == "<<":
        return "lessThan"
      elif operator == "<=":
        return "lessThanEquals"
      elif operator == ">=":
        return "greaterThanEquals"
      elif operator == ">>":
        return "greaterThan"

   def _SetRelationArray(self, rules):
      """Return array of predicates that must be true for this package.
      """
      if rules is None or not len(rules):
         return None
      out = []
      for item in rules:
          rel = vim.host.SoftwarePackage.Relation()
          rel.name = item.name
          ident = str(item.version)
          if ident and ident != 'None':
             rel.version = ident
          rel.constraint = self.SetConstraint(item.relation)
          out.append(rel)
      return out

   def FetchSoftwarePackages(self):
      """Return the list of software packages (vibs) installed.
         @see vim.host.ImageConfigManager.fetchSoftwarePackages
      """
      vibs = self.himg.GetInventory(database = self.himg.DB_VISORFS)
      packages = []
      for key,value in vibs.items():
         package = vim.host.SoftwarePackage()
         package.name = value.name
         package.version = value.versionstr
         package.type = value.vibtype
         package.vendor = value.vendor
         try:
            package.acceptanceLevel = \
               ESXIMG_LEVEL_TO_VMODL[value.acceptancelevel]
         except:
            package.acceptanceLevel = value.acceptancelevel
         package.summary = value.summary
         package.description = value.description
         urls = []
         for k,v in value.urls.items():
            if k is not None and v is not None:
               urls.append("%s=%s" % (k,v))
         package.referenceURL = self._ToVmomiStringArray(urls)
         if value.installdate is not None:
            package.creationDate = value.installdate
         package.depends = self._SetRelationArray(value.depends)
         package.conflicts = self._SetRelationArray(value.conflicts)
         package.replaces = self._SetRelationArray(value.replaces)
         package.provides = self._ToVmomiStringArray(value.provides)
         package.maintenanceModeRequired = value.maintenancemode.install
         package.hardwarePlatformsRequired = \
            self._ToVmomiStringArray(value.hwplatforms)
         package.capability = vim.host.SoftwarePackage.Capability()
         package.capability.liveInstallAllowed = value.liveinstallok
         package.capability.liveRemoveAllowed = value.liveremoveok
         package.capability.statelessReady = value.statelessready
         package.capability.overlay = value.overlay
         package.tag = self._ToVmomiStringArray(value.swtags)
         package.payload = self._ToVmomiStringArray(value.payloads)
         packages.append(package)
      return packages

   def InstallDate(self):
      """Return this systems initial installation date as reported by CLI:
         esxcli system stats installtime get
         2016-02-27T22:12:50
         @see vim.host.ImageConfigManager.installDate
      """
      when = sb.check_output(["/bin/localcli", "system", "stats", "installtime",
                              "get"]).strip()
      return datetime.datetime.strptime(when.decode('utf-8'), "%Y-%m-%dT%H:%M:%S")


# Create and register managed objects
def RegisterManagedObjects(vorb):
   imgConfigImpl = ImageConfigManagerImpl()
   vorb.RegisterObject(imgConfigImpl)
   syslog(LOG_INFO, "Registered %s\n" % imgConfigImpl)
if __name__ == '__main__':
   openlog("hostd-icm", LOG_PID, LOG_DAEMON)
   vorb=common.InitVorb()
   RegisterManagedObjects(vorb)
   vorb.RunServer()
