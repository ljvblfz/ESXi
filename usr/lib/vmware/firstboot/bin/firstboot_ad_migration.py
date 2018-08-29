#!/usr/bin/env python
########################################################################
# Copyright 2016 VMware, Inc.  All rights reserved.
# -- VMware Confidential
########################################################################

import os

class Configuration(dict):
   def __init__(self, path):
      with open(path, "r") as fsock:
         for line in fsock.readlines():
            line = line.rstrip('\n')
            if line.find('=') != -1:
               key, value = line.split('=', 1)
               key = key.strip()
               value = value.strip(' "')
               if key:
                  self[key] = value

conf = Configuration("/etc/vmware/vmwauth/authentication.conf")
if conf.get("remote-authentication-store",None) == "Active Directory":
   os.system("/sbin/localcli network firewall ruleset set --ruleset-id activeDirectoryAll --enabled true")
   os.system("/sbin/localcli network firewall refresh")
   os.system("/sbin/chkconfig --add lwsmd")
   os.system("/etc/init.d/lwsmd status > /dev/null || /etc/init.d/lwsmd start")
   if os.path.exists("/etc/likewise/db/pstore.filedb"):
      try:
         os.system("/usr/lib/vmware/likewise/bin/lwsm stop lsass")
         os.system("/usr/lib/vmware/likewise/bin/conf2reg --pstore-filedb /etc/likewise/db/pstore.filedb")
      finally:
         os.system("/usr/lib/vmware/likewise/bin/lwsm restart lsass")
