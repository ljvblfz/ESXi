"""
Copyright 2017 VMware, Inc.  All rights reserved.
-- VMware Confidential
# This file is similar to cmmds-tool find --format json --mangle
# but specifically only outputs and obfuscates entries which
# cmmds-tool can't handle.
#
"""
__author__ = "VMware, Inc"

import pyCMMDS
import hashlib
import json


def ObfuscateKV(e, keys):
   for key in keys:
      if key in e:
         e[key] = hashlib.sha1(e[key].encode()).hexdigest()
   return e

def ObfuscatePolicy(e):
   return ObfuscateKV(e, ['spbmProfileName'])

def ObfuscateHostname(e):
   return ObfuscateKV(e, ['hostname'])

def ObfuscateDomOsfsName(e):
   return ObfuscateKV(e, ['ufn'])

def ObfuscateFd(e):
   return ObfuscateKV(e, ['faultDomainName'])

def ObfuscateHaMetadata(e):
   e[0] = hashlib.sha1(e[0].encode()).hexdigest()
   return e

# Unmarshal, obfuscate and json-dump the contents of a CMMDS entry
def ObfuscateBinary(entry, type):
   content = pyCMMDS.BinToTextPolicy(entry.dataStr, True, pyCMMDS.CmmdsTypeToExprType(type))
   content = eval(content)
   if type == pyCMMDS.CMMDS_TYPE_POLICY:
      fn = ObfuscatePolicy
   if type == pyCMMDS.CMMDS_TYPE_HOSTNAME:
      fn = ObfuscateHostname
   if type == pyCMMDS.CMMDS_TYPE_DOM_NAME:
      fn = ObfuscateDomOsfsName
   if type == pyCMMDS.CMMDS_TYPE_OSFS_NAME:
      fn = ObfuscateDomOsfsName
   if type == pyCMMDS.CMMDS_TYPE_HA_METADATA:
      fn = ObfuscateHaMetadata
   if type == pyCMMDS.CMMDS_TYPE_NODE_FAULT_DOMAIN:
      fn = ObfuscateFd

   content = fn(content)
   return json.dumps(content)

# Dump all entries of one type, in obfuscated manner
def DumpType(typeStr):
   wildcards = {'anyUUID': 1, 'anyOwner': 1, 'anyRevision': 1}
   query = pyCMMDS.CMMDSQuery()
   query.type = pyCMMDS.__dict__['CMMDS_TYPE_' + typeStr];
   query.wildcards = wildcards
   entry = pyCMMDS.FindEntry(query, pyCMMDS.CMMDS_FIND_FLAG_NONE, True)
   i = 0
   while entry:
      content = ObfuscateBinary(entry, query.type)
      e = {'uuid': entry.uuid, 'owner': entry.owner,
           'revision': entry.revision, 'type': 'CMMDS_TYPE_' + typeStr,
           'content': content}
      print(json.dumps(e) + ("," if i > 0 else ""))
      entry = pyCMMDS.FindEntry(query, pyCMMDS.CMMDS_FIND_FLAG_NEXT, True)
      i += 1

# Currently all entries other than POLICY are nicely handled by
# cmmds-tool find --mangle
# So we only handle POLICY. Whats special about POLICY is that we
# want to keep most strings un-obfuscated, but obfuscate a subset.
types = [
   "POLICY"
]
print("[")
for typeStr in types:
   DumpType(typeStr)
print("]")
