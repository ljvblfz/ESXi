#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import glob
import os
import shutil

from pluginApi import ParameterMetadata, \
                      CreateLocalizedException
from pluginApi import log
from pluginApi.extensions import SimpleConfigProfile
from .SecurityProfileUtils import AUTHKEY_EXTRACT_FAIL, AUTHKEY_APPLY_FAIL

AUTH_DIR = '/etc/ssh/'
AUTH_ROOT_DIR = '/etc/ssh/keys-root'
AUTH_FILE = 'authorized_keys'
USERNAME_PARAM = 'username'
KEY_PARAM = 'key'

class AuthorizedKeysProfile(SimpleConfigProfile):
   """ A Host Profile that manages the authorized keys settings.
   """
   parameters = [
      ParameterMetadata(USERNAME_PARAM, 'string', False),
      ParameterMetadata(KEY_PARAM, 'string', True, securitySensitive=True) ]

   singleton = False
   idConfigKeys = [USERNAME_PARAM]

   @classmethod
   def ExtractConfig(cls, hostServices):
      """ For this profile, the extract reads the
          /etc/ssh/keys-<username>/authorized_keys file to get the public key
          of the user.
      """
      authKeyList = []
      if os.path.exists(AUTH_DIR):
         for f in glob.glob(os.path.join(AUTH_DIR, 'keys-*', AUTH_FILE)):
            try:
               authKeyConfig = { USERNAME_PARAM : f.split('/')[3].split('-')[1],
                                 KEY_PARAM : '' }
               pubKeyInFile = ''
               with open(f, 'r') as fileHandle:
                  # NOTE: This file will have only one entry which translates
                  # to one line. So a read() of the file should get all the
                  # contents this profile is interested in.
                  pubKeyInFile = fileHandle.read()
               pubKeyInFile = pubKeyInFile.rstrip('\n')
               authKeyConfig[KEY_PARAM] = pubKeyInFile
               authKeyList.append(authKeyConfig)
            except Exception as e:
               log.error('Failed to read ssh public key (%s): %s' % (f, e))
               raise CreateLocalizedException(None, AUTHKEY_EXTRACT_FAIL)
      return authKeyList


   @classmethod
   def SetConfig(cls, config, hostServices):
      """ Sets the ssh public key for a given user based
          on the config. All non root user ssh public keys
          are removed and then new keys are set based on the
          config.
      """
      for f in glob.glob(os.path.join(AUTH_DIR, 'keys-*')):
         if f != os.path.join(AUTH_ROOT_DIR):
            shutil.rmtree(f)
      for a in config:
         try:
            dirName = os.path.join(AUTH_DIR, 'keys-%s' % a[USERNAME_PARAM])
            if a[USERNAME_PARAM] != 'root' or not os.path.exists(dirName):
               os.makedirs(dirName, 0o755)
            with open(os.path.join(dirName, AUTH_FILE), 'w') as fileHandle:
               fileHandle.write(a[KEY_PARAM] + '\n')
         except Exception as e:
            log.error("Failed to set ssh public key (%s): %s" % (a, e))
            raise CreateLocalizedException(None, AUTHKEY_APPLY_FAIL)
