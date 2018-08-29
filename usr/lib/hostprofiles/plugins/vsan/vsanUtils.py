#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import log, CreateLocalizedException
from pluginApi import TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_REQ_MAINT_MODE, \
                      TASK_LIST_RES_OK
from vmware import runcommand
import json
from .vsanConstants import VSAN_GET_PREFERREDFD_FAIL_KEY
import six

def _runcmd(cmd):
   status, output = runcommand.runcommand(cmd.split())
   return output

def _cmmds_find(params):
   result = _runcmd("/bin/cmmds-tool find --format=python %s" % (params, ))
   entries = eval(result)
   for entry in entries:
      try:
         entry['content'] = json.loads(entry['content'])
      except:
         pass
   return entries

#
def VSANUtilEsxcliGeneric(hostServices, p0, p1, p2, p3, failKey, failDict=None):

   status, output = hostServices.ExecuteEsxcli(p0, p1, p2, p3)
   if status != 0:
      log.error('"%s %s %s %s" failed with %d, %s'%(p0,p1,p2,p3,status,output))
      raise CreateLocalizedException(None, failKey, failDict)

   return output

#
def VSANUtilEsxcli(hostServices, p1, p2, p3, failKey, failDict=None):

   return VSANUtilEsxcliGeneric(hostServices,'vsan',p1,p2,p3,failKey,failDict)


def VSANUtilRemoteEsxcli(hostServices, p1, p2, p3, failKey, failDict=None):

   status, output = hostServices.ExecuteRemoteEsxcli('vsan', p1, p2, p3)
   if status != 0:
      log.error('"vsan %s %s %s" failed with %d, %s'%(p1,p2,p3,status,output))
      raise CreateLocalizedException(None, failKey, failDict)

   return output

#
def VSANUtilGetStretchedInfo(vsanEnabled):

   CMMDS_NODE_FLAG_WITNESS_NODE = 1 << 1
   info = {'stretchedEnabled': False}
   witness = None

   if not vsanEnabled:
      return info

   nodes = _cmmds_find("-t NODE")
   for node in nodes:
      if 'health' not in node or node['health'] != 'Healthy':
         continue
      # The 'flags' is new in u1 and missed in 6.0 GA. If there are mix hosts
      # of 6.0 GA and u1, an exception will be raised when trying to read the
      # flags from the content.
      if 'content' in node \
         and 'flags' in node['content'] \
         and node['content']['flags'] & CMMDS_NODE_FLAG_WITNESS_NODE:

         witness = node
         break

   if witness is None:
      return info

   info['stretchedEnabled'] = True

   selfUuid = _runcmd("/bin/cmmds-tool whoami").rstrip()
   if six.PY3:
      selfUuid = selfUuid.decode()
   info['isWitness'] = (witness['uuid'] == selfUuid)

   if not info['isWitness']:
      return info

   preferredFdNodes = _cmmds_find("-t PREFERRED_FAULT_DOMAIN")
   if preferredFdNodes is None:
      raise CreateLocalizedException(None, VSAN_GET_PREFERREDFD_FAIL_KEY, None)

   info['preferredFD'] = preferredFdNodes[0]['content']['faultDomainName']

   return info

#
def VSANUtilComputeTaskListRes(old, new):

   if new == TASK_LIST_REQ_REBOOT or old == TASK_LIST_REQ_REBOOT:
      return TASK_LIST_REQ_REBOOT
   elif new == TASK_LIST_REQ_MAINT_MODE:
      return TASK_LIST_REQ_MAINT_MODE
   else:
      return old
