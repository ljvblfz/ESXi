#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, \
                      CreateLocalizedMessage, \
                      CreateLocalizedException
from pluginApi import log
from pluginApi.extensions import SimpleConfigProfile
from pyEngine import securityprofile
from hpCommon.constants import RELEASE_VERSION_2016
import os

#
# Define some constants first
#
BASE_MSG_KEY = 'com.vmware.profile.Profile.authKeys'
ROOT_AUTH_KEYS_FILE_NAME = '/etc/ssh/keys-root/authorized_keys'
KEY_PARAM = 'key'

#
# Define the localization message catalog keys used by this profile
FAILED_TO_SAVE_ROOT_USER_MSG_KEY = '%s.FailedToSaveRootUserAuthKeys' % BASE_MSG_KEY
FAILED_TO_READ_ROOT_USER_MSG_KEY = '%s.FailedToReadRootUserAuthKeys' % BASE_MSG_KEY


class RootAuthorizedKeys(SimpleConfigProfile):
   """A Host Profile that manages the authorized keys settings for root user.
   """
   #
   # Define required class attributes
   #
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2016
   enableDeprecatedVerify = True
   enableDeprecatedApply = True
   supersededBy = 'security.authKeys.AuthorizedKeysProfile'
   parameters = [
      # Parameter for the profile
      ParameterMetadata(KEY_PARAM, 'string', True) ]

   singleton = True

   # Need to define some common parent
   parentProfiles = [securityprofile.SecurityProfile]


   @classmethod
   def ExtractConfig(cls, hostServices):
      """For this profile, the extract reads the /etc/ssh/keys-root/authorized_keys
         file to get the public key of root user.
      """
      authKeyConfig = {}
      try:
         pubKeyInFile = ''
         if os.path.exists(ROOT_AUTH_KEYS_FILE_NAME):
            with open(ROOT_AUTH_KEYS_FILE_NAME, 'r') as fileHandle:
               # NOTE: This file will have only one entry which translates to one
               # line. So a read() of the file should get all the contents this
               # profile is interested in.
               pubKeyInFile = fileHandle.read()
               pubKeyInFile = pubKeyInFile.rstrip('\n')

         if len(pubKeyInFile) > 0:
            authKeyConfig[KEY_PARAM] = pubKeyInFile
      except Exception as exc:
         log.error('Failed to read %s for authorized keys for root: %s' %
                  (ROOT_AUTH_KEYS_FILE_NAME, str(exc)))
         fault = CreateLocalizedException(None, FAILED_TO_READ_ROOT_USER_MSG_KEY)
         raise fault

      return authKeyConfig


   @classmethod
   def SetConfig(cls, config, hostServices):
      """For this, the config parameter should contain a list of
         dicts with a single entry, and that entry should have a single
         parameter containing the ssh key for root user
      """
      assert len(config) == 1 and KEY_PARAM in config[0], \
             'Unexpected config passed into SetConfig for AuthorizedKeys \
             profile'
      authKey = config[0][KEY_PARAM]
      if authKey is None:
         authKey = ''
      try:
         with open(ROOT_AUTH_KEYS_FILE_NAME, 'w') as fileHandle:
            fileHandle.write(authKey + '\n')
      except Exception as exc:
         log.error('Failed to save authorized keys for root in %s: %s' %
                  (ROOT_AUTH_KEYS_FILE_NAME, str(exc)))
         fault = CreateLocalizedException(None, FAILED_TO_SAVE_ROOT_USER_MSG_KEY)
         raise fault

