#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import CreateLocalizedMessage, log


from .vsanConstants import *
from .vsanUtils import *



###
### VSAN Nic Profile method on all profiles
###

# Ancillary routine to gather nic sets from the networking profile
def VSANNicAllProfilesGatherNWNics(nics, nwSet, nwVsanSet):

   # XXX Hardcoded policy references to the networking profile
   if nics is not None:
      for nic in nics:
         nicName = None
         vsanOn = False
         for pol in nic.policies:
            if pol.__class__.__name__ == 'VirtualNICNamePolicy':
               nicName = pol.policyOption.vmkNicName
               log.debug('found legacy %s' % nicName)
            elif pol.__class__.__name__ == 'VirtualNICTypePolicy':
               if hasattr(pol.policyOption, 'nicType'):
                  nicTypes = pol.policyOption.nicType
                  log.debug('with tag %s' % nicTypes)
                  if nicTypes is not None and 'vsan' in nicTypes:
                     vsanOn = True
               else:
                  # The profile left this as a user provided option, treat it
                  # the same as not VSAN enabled. If there is a corresponding
                  # VSAN nic, this will cause the profile to fail validation.
                  log.debug('left unspecified')
         if nicName is not None:
            nwSet.add(nicName)
            if vsanOn:
               nwVsanSet.add(nicName)

# Find matching network hostport profile and policies from network configuration for provided nic
def VSANGetNicProfile(nicName, nics):
   if nicName is not None and nics is not None:
      foundNic = None
      nicNamePolicy = None
      for nic in nics:
         nicTypePolicy = None
         for pol in nic.policies:
            if pol.__class__.__name__ == 'VirtualNICNamePolicy' and \
                  pol.policyOption.vmkNicName == nicName:
               foundNic = pol.policyOption.vmkNicName
               nicNamePolicy = pol
            elif pol.__class__.__name__ == 'VirtualNICTypePolicy':
               if hasattr(pol.policyOption, 'nicType'):
                  nicTypePolicy = pol
         if foundNic is not None:
            return [foundNic, nic, nicTypePolicy, nicNamePolicy]
   return [None, None, None, None]

#
def VSANNicAllProfilesVerify(parent, profileInstances, hostServices, \
                                                profileData, validationErrors):

   log.debug('in nic verify ALL profiles')

   theResult = True

   # First verify that there is no duplicate nics
   # XXX

   # We need to verify the profile consistency as far as vmknic go, i.e.
   # a nic present in this vsan nic profile is also present in the
   # networking profile with the vsan tag and conversely a nic in the
   # networking profile with the vsan tag must be here.
   #
   # !!! This is a side effect of not being able to hang the vsan nic
   # profile off the legacy nic profile.
   #
   # NOTE: Even though we specify networkprofile as a dependency, it does
   # not guarantee order here, however the profile should already be fully
   # formed so we can check consistency.

   # NOTE: XXX We have to hardcode deep in the hierarchy
   #
   # Since we are located under storage profile under root, we find root by
   # going up three two steps
   root = parent.parentProfile.parentProfile

   # From there, we have to look in two places, the legacy portgroups and
   # the DVS portgroups.
   legacyNics = root.network.hostPortGroup
   dvsNics = root.network.dvsHostNic

   # Construct set of all nics present in networking profile and of only
   # the ones with the vsan tag
   nwSet = set()
   nwVsanSet = set()
   VSANNicAllProfilesGatherNWNics(legacyNics, nwSet, nwVsanSet)
   VSANNicAllProfilesGatherNWNics(dvsNics, nwSet, nwVsanSet)
   log.debug('nwSet is %s, nwVsanSet is %s' % (nwSet, nwVsanSet))

   # Now construct the set of all the vsan nics
   vsanSet = set([nic.VSANNicPolicy.policyOption.VmkNicName \
                                                   for nic in profileInstances])
   log.debug('vsanSet is %s' % vsanSet)

   # First vsan nics that are not even system nics
   extraVsanSet = vsanSet - nwSet
   for nic in extraVsanSet:
      log.debug('vsan nic %s is not in system' % nic)
      msg = CreateLocalizedMessage(None, VSAN_NIC_EXTRA_ERROR_KEY,
                                   {'VmkNicName': nic})
      # Get the vsan nic profile instance matching this nic from storage configuration
      for nicProfile in profileInstances:
         if nicProfile.VSANNicPolicy.policyOption.VmkNicName == nic:
            msg.SetRelatedPathInfo(profile = nicProfile,
                                   policy = nicProfile.VSANNicPolicy,
                                   paramId = 'VmkNicName')
      validationErrors.append(msg)
      theResult = False

   vsanSet -= extraVsanSet

   # Then vsan nics that are system nics but not tagged as such there
   noTagSet = vsanSet - nwVsanSet
   for nic in noTagSet:
      log.debug('vsan nic %s is in system but not tagged' % nic)
      # Get the nic profile from the legacy hostport groups network configuration
      foundNic, nicProfile, nicTypePolicy, nicNamePolicy = VSANGetNicProfile(nic, legacyNics)
      if foundNic is None:
         # If nic is not found in legacy hostport groups look out in dvs hostports
         foundNic, nicProfile, nicTypePolicy, nicNamePolicy = VSANGetNicProfile(nic, dvsNics)
      msg = CreateLocalizedMessage(None, VSAN_NIC_NOVSANTAG_ERROR_KEY, \
                                   {'VmkNicName': nic})
      if foundNic is not None and nicProfile is not None:
         log.debug('Found matching nic in hostport groups: %s' % foundNic)
         if nicTypePolicy is not None:
            msg.SetRelatedPathInfo(profile = nicProfile,
                                   policy = nicTypePolicy,
                                   paramId = 'nicType')
         elif nicNamePolicy is not None:
            msg.SetRelatedPathInfo(profile = nicProfile,
                                   policy = nicNamePolicy,
                                   paramId = 'vmkNicName')
      validationErrors.append(msg)
      theResult = False

   vsanSet -= noTagSet

   # Finally system nics that are tagged but are not vsan nics
   missingSet = nwVsanSet - vsanSet
   for nic in missingSet:
      log.debug('system nic %s is tagged but not a vsan nic' % nic)
      # Get the nic profile from the legacy hostport groups network configuration
      foundNic, nicProfile, nicTypePolicy, nicNamePolicy = VSANGetNicProfile(nic, legacyNics)
      if foundNic is None:
         # If nic is not found in legacy hostport groups look out in dvs hostports
         foundNic, nicProfile, nicTypePolicy, nicNamePolicy = VSANGetNicProfile(nic, dvsNics)
      msg = CreateLocalizedMessage(None, VSAN_NIC_MISSING_ERROR_KEY, \
                                   {'VmkNicName': nic})
      if foundNic is not None and nicProfile is not None:
         log.debug('Found matching nic in hostport groups: %s' % foundNic)
         if nicTypePolicy is not None:
            msg.SetRelatedPathInfo(profile = nicProfile,
                                   policy = nicTypePolicy,
                                   paramId = 'nicType')
         elif nicNamePolicy is not None:
            msg.SetRelatedPathInfo(profile = nicProfile,
                                   policy = nicNamePolicy,
                                   paramId = 'vmkNicName')
      validationErrors.append(msg)
      theResult = False

   return theResult
