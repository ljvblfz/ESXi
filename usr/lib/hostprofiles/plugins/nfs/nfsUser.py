#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import ParameterMetadata, \
                      log

from pluginApi import COMPONENT_NAS_STORAGE,  \
                      CATEGORY_STORAGE, \
                      TASK_LIST_REQ_MAINT_MODE
from pluginApi.extensions import SimpleConfigProfile

from pyEngine import storageprofile

from pyVmomi import Vmodl, Vim
import vmkctl

NFS_USER_KEY = 'nfs-user'
NFS_PW_KEY = 'nfs-password'
NFS_PW_ALT_KEY = 'nfs-alt-password'

class NfsUserProfile(SimpleConfigProfile):
   """A Host Profile that manages NFS user settings on ESX hosts."""

   # Required class attributes
   parameters = [ParameterMetadata(NFS_USER_KEY, 'string', True),
                 ParameterMetadata(NFS_PW_KEY, 'Vim.PasswordField', True,
                                   securitySensitive=True),
                 ParameterMetadata(NFS_PW_ALT_KEY, 'Vim.PasswordField', True,
                                   securitySensitive=True)]

   parentProfiles = [ storageprofile.StorageProfile ]
   singleton = True
   #setConfigReq = TASK_LIST_REQ_MAINT_MODE

   dependencies = [storageprofile.StorageProfile]

   category = CATEGORY_STORAGE
   component = COMPONENT_NAS_STORAGE

   _storageInfo = vmkctl.StorageInfoImpl()
   _storageInfo.PreferenceInit()

   @staticmethod
   def ToVimPassword(passwd):
      return Vim.PasswordField(value=passwd)

   # External interface
   @classmethod
   def ExtractConfig(c, h):
      """Gets NFS user information on host"""

      usrPw = c._storageInfo.GetV41NetworkFileSystemDefaultCredentialPy()
      user = None
      if len(usrPw) > 0:
         user = usrPw[0]
         pws = usrPw[1:]
      config = {}
      if user:
         config[NFS_USER_KEY] = user
         if len(pws) > 0:
            config[NFS_PW_KEY] = c.ToVimPassword(pws[0])
         if len(pws) > 1:
            config[NFS_PW_ALT_KEY] = c.ToVimPassword(pws[1])
      return [config]


   @classmethod
   def SetConfig(c, config, h):
      """Sets NFS user information on host."""

      if len(config) != 1:
         log.error('NFS user config has %d instead of 1 entry' % len(config))
         return

      config = config[0]
      if NFS_USER_KEY in config and config[NFS_USER_KEY]:
         usr = config[NFS_USER_KEY]
         pws = []
         if NFS_PW_KEY in config and config[NFS_PW_KEY]:
            pws.append(config[NFS_PW_KEY].value)
         if NFS_PW_ALT_KEY in config and config[NFS_PW_ALT_KEY]:
            pws.append(config[NFS_PW_ALT_KEY].value)
         c._storageInfo.SetV41NetworkFileSystemDefaultCredential(usr, pws)
      else:
         c._storageInfo.ClearV41NetworkFileSystemDefaultCredential()
      return
