#!/usr/bin/python
# ***************************************************************************
# Copyright 2015 VMware, Inc.  All rights reserved. VMware Confidential.
# ***************************************************************************

__author__ = "VMware, Inc."

import os
import re
from pluginApi.extensions import KeyValueConfigProfile
from pluginApi import GetParameters

class VmwareConfigProfile(KeyValueConfigProfile):
   '''A host profile plugin that manages the /etc/vmware/config file.
   '''
   filePath = os.path.join('/etc', 'vmware', 'config')
   delim = '='
   # PR 1543692
   blackListedKeys = ['messageBus.tunnelEnabled',
                      'vGPU.consolidation',
                      'featureCompat.evc.completeMasks']
   blackListedRegs = [re.compile('^featMask.evc.*')]

   parameters = GetParameters(filePath, delim, blackList=blackListedKeys,
                              blackListReg=blackListedRegs)
