#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import log
import os
import re
import shutil

PAM_PASSWORD_FILE = '/etc/pam.d/passwd'
PAM_PASSWORD_FILE_BACKUP = '%s.%s' % (PAM_PASSWORD_FILE, 'hostprofile')
PAM_INTERFACE_LIST = [ 'auth', 'account', 'password', 'session' ]

# A valid PAM entry format is "interface control module arguments",
# where control can be predefined word or customized in the format "[...]",
# and arguments is an optional list of arguments separated by space
pattern = r"""
   (\w+)                   # module interface, group(1) in match result
   \s+
   (?:(\[[^\]]+\])|(\w+))  # module control, group(2) or group(3) in match result
   \s+
   ([^\s]+)                # module path, group(4) in match result
   \s*
   (.*)                    # module arguments, optional, group(5) in match result
   $
   """

class PasswordPAMManager:
   """Configuration containing the password PAM settings.
   """
   def __init__(self):
      """Initalize password PAM manager
      """
      self.conf = {}
      for interface in PAM_INTERFACE_LIST:
         self.conf[interface] = []

   def Read(self):
      """Read passwd PAM configuration from file
      """
      self.conf = {}
      for interface in PAM_INTERFACE_LIST:
         self.conf[interface] = []

      try:
         with open(PAM_PASSWORD_FILE, "r") as fsock:
            for line in fsock.readlines():
               line = line.strip()
               if len(line) == 0 or line.startswith('#'):
                  # Ignore empty or comment line
                  continue

               parser = re.compile(pattern, re.VERBOSE)
               matches = parser.match(line)
               if matches is None:
                  log.warning("Illegally formatted entry in configuration file %s." \
                              "Ignore it in host profile." % PAM_PASSWORD_FILE)
                  continue

               interface = matches.group(1)
               if interface not in PAM_INTERFACE_LIST:
                  log.warning("Unknown PAM interface type %s in configuration file %s." \
                              "Ignore it in host profile." % (interface, PAM_PASSWORD_FILE))
                  continue
               if matches.group(2) is None:
                  control = matches.group(3)
               else:
                  control = matches.group(2)
               module = matches.group(4)
               arguments = matches.group(5)

               self.conf[interface].append((control, module, arguments))
         return True
      except IOError:
         log.error("Failed to read configuration file %s" % PAM_PASSWORD_FILE)
         return False

   def Commit(self, hostServices):
      """Write the password PAM configuration into file.
      """
      # Create a backup of the original file so that we can restore it later.
      # Right now, not deleting the backup file from the filesystem.
      try:
         shutil.copy2(PAM_PASSWORD_FILE, PAM_PASSWORD_FILE_BACKUP)
      except IOError:
         log.error('Failed to backup configuration file %s' % PAM_PASSWORD_FILE)
         return False

      try:
         with open(PAM_PASSWORD_FILE, "w") as fsock:
            for interface in PAM_INTERFACE_LIST:
               for entry in self.conf[interface]:
                  if entry[2]:
                     fsock.write("{0:10} {1:12} {2} {3}\n".format(interface, entry[0], entry[1], entry[2]))
                  else:
                     fsock.write("{0:10} {1:12} {2}\n".format(interface, entry[0], entry[1]))
               if len(self.conf[interface]) > 0:
                  fsock.write("\n")

         # Sync the advanced option parameter Security.PasswordQualityControl
         # which is disabled in option profile since it duplicates with
         # the password setting in this profile.
         si = hostServices.hostServiceInstance
         hostFolder = si.content.rootFolder.childEntity[0].hostFolder
         host = hostFolder.childEntity[0].host[0]
         from pyVmomi import Vim
         option = Vim.Option.OptionValue()
         option.key = 'Security.PasswordQualityControl'
         option.value = self.conf['password'][0][2]
         host.configManager.advancedOption.UpdateValues([option])
         return True
      except IOError:
         os.rename(PAM_PASSWORD_FILE_BACKUP, PAM_PASSWORD_FILE)
         log.error("Failed to write configuration file %s" % PAM_PASSWORD_FILE)
         return False

   def GetConfig(self):
      """Get the password PAM configuration.
      """
      return self.conf

   def SetConfig(self, conf):
      """Set the password PAM configuration.
      """
      self.conf = conf
