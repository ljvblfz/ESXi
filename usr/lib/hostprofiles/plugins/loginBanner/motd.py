#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import codecs
import copy
from pluginApi import ParameterMetadata, \
                      CreateLocalizedMessage, \
                      CreateLocalizedException, \
                      RELEASE_VERSION_2015
from pluginApi import log, IsString
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_CONSOLE_CONFIG
from pluginApi.extensions import SimpleConfigProfile

#
# Define some constants first
#
BASE_MSG_KEY = 'com.vmware.profile.Profile.motd'
MOTD_FILE_NAME = '/etc/motd'
MESSAGE_PARAM = 'message'

#
# Define the localization message catalog keys used by this profile
FAILED_TO_SAVE_MSG_KEY = '%s.FailedToSaveMotd' % BASE_MSG_KEY
FAILED_TO_READ_MSG_KEY = '%s.FailedToReadMotd' % BASE_MSG_KEY




class MotdProfile(SimpleConfigProfile):
   """A Host Profile that manages the login banner on an ESX host.
   """

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015
   enableDeprecatedVerify = True
   enableDeprecatedApply = True
   supersededBy = "The Config.Etc.motd in Advanced config option"


   #
   # Define required class attributes
   #
   parameters = [
      # Parameter for the profile
      ParameterMetadata(MESSAGE_PARAM, 'string', True) ]

   singleton = True

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_CONSOLE_CONFIG
   
   # Need to define some common parent for random system config stuff?
   #parentProfiles = [ ]

   @classmethod
   def ExtractConfig(cls, hostServices):
      """For the MotdProfile, the extract reads the /etc/motd file to get the
         login banner.
      """
      motdConfig = {}
      try:
         motdFile = codecs.open(MOTD_FILE_NAME, 'r', 'utf-8')
         motdContents = motdFile.read()
         motdFile.close()
         # Flatted the message for now since we don't have a multi-line field
         # in host profiles.
         motd = " ".join(motdContents.split())

         # There's a funny sequence in the default motd that the SoapAdapter
         # doesn't like: \x1b[00m
         motd = motd.replace('\x1b[00m', '').rstrip()
         if len(motd) > 0:
            motdConfig[MESSAGE_PARAM] = motd
      except Exception as exc:
         log.error('Failed to read login banner message (motd): %s' % str(exc))
         fault = CreateLocalizedException(
                    None, FAILED_TO_READ_MSG_KEY)
         raise fault

      return motdConfig

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Nothing much to verify here, except to trim any leading and trailing
         whitespaces for the profile instance since that is done during extract
      """
      configPolicyOption = profileInstance.MotdProfilePolicy.policyOption
      motdValue = configPolicyOption.paramValue[0][1]
      # If the motd parameter is not a string, that will be caught by an
      # infrastructure type-check
      if IsString(motdValue):
         # trim the leading/trailing whitespaces, if the motd is
         # not an empty string
         if motdValue:
            trimmedMotd = motdValue.strip()
            updatedTuple = (MESSAGE_PARAM, trimmedMotd)
            configPolicyOption.paramValue[0] = updatedTuple
      return True

   @classmethod
   def SetConfig(cls, config, hostServices):
      """For the MotdProfile, the config parameter should contain a list of
         dicts with a single entry, and that entry should have a single
         parameter containing the message for the login screen.
      """
      assert len(config) == 1 and MESSAGE_PARAM in config[0], \
             'Unexpected config passed into SetConfig for MotdProfile'
      motd = config[0][MESSAGE_PARAM]
      if motd is None:
         motd = ''
      try:
         motdFile = codecs.open(MOTD_FILE_NAME, 'w', 'utf-8')
         motdFile.write(motd + '\n')
         motdFile.close()
      except Exception as exc:
         log.error('Failed to save login banner message (motd): %s' % str(exc))
         fault = CreateLocalizedException(None, FAILED_TO_SAVE_MSG_KEY)
         raise fault
      # End of SetConfig()

