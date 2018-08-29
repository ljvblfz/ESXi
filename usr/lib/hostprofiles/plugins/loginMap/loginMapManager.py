#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import log
import os
import shutil

PAM_LOGIN_MAP_FILE = '/etc/security/login.map'
PAM_LOGIN_MAP_FILE_BACKUP = '%s.%s' % (PAM_LOGIN_MAP_FILE, 'hostprofile')
DEFAULT_USERS = '*'

class LoginMapManager:
   """Configruation containing the login map
   """
   def __init__(self):
      """Initialize login map manager
      """
      self.conf = {}

   def Read(self):
      """Read login map configuration from file
      """
      self.conf = {}
      try:
         with open(PAM_LOGIN_MAP_FILE, "r") as fsock:
            for line in fsock.readlines():
               line = line.rstrip('\n')
               key, sep, value = line.partition(':')
               if sep:
                  key = key.strip()
                  value = value.strip()
                  if key:
                     self.conf[key] = value
         return True
      except IOError:
         log.error("Failed to read configuration file %s" % PAM_LOGIN_MAP_FILE)
         return False

   def Commit(self):
      """Write the login map configuration into file.
      """
      # Create a backup of the original file so that we can restore it later.
      # Right now, not deleting the backup file from the filesystem.
      try:
         shutil.copy2(PAM_LOGIN_MAP_FILE, PAM_LOGIN_MAP_FILE_BACKUP)
      except IOError:
         log.error('Failed to backup configuration file %s' % PAM_LOGIN_MAP_FILE)
         return False

      try:
         with open(PAM_LOGIN_MAP_FILE, "w") as fsock:
            for key, value in self.conf.items():
               if key != DEFAULT_USERS:
                  fsock.write("%s : %s\n" % (key, value))
            # the default rule must be the last line
            if DEFAULT_USERS in self.conf:
               fsock.write("%s : %s\n" % (DEFAULT_USERS, self.conf[DEFAULT_USERS]))
         return True
      except IOError:
         os.rename(PAM_LOGIN_MAP_FILE_BACKUP, PAM_LOGIN_MAP_FILE)
         log.error("Failed to write configuration file %s" % PAM_LOGIN_MAP_FILE)
         return False

   def GetConfig(self):
      """Get the login map configuration
      """
      return self.conf

   def SetConfig(self, conf):
      """Set the login map configuration
      """
      self.conf = conf

   def Add(self, user, path):
      """Add a user/path mapping
      """
      if user not in self.conf:
         self.conf[user] = path
         return True
      return False

   def Edit(self, user, path):
      """Change a user/path mapping
      """
      if user in self.conf:
         self.conf[user] = path
         return True
      return False

   def Remove(self, user):
      """Delete a user/path mapping
      """
      if user in self.conf:
         del self.conf[user]
         return True
      return False

   def SetDefault(self, path):
      """Set the mapping for default users
      """
      self.conf[DEFAULT_USERS] = path

