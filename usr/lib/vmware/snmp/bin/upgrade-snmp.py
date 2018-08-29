#!/bin/python
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Upgrade script for /etc/vmware/snmp.xml

import sys
import os
from lxml import etree
from syslog import *

cfg = '/etc/vmware/snmp.xml'

#
# Any changes to these routines should also be made in C++ version
# in bora/lib/vmkctl/util/ToolUtils.cpp
#
def Is3rdPartyPort(port):
   '''See C++ version in bora/lib/vmkctl/util/ToolUtils.cpp '''
   return port >= 32768 and port <= 40959

def PortsFor3rdPartyToString():
   return "32768 to 40959"

def check_poll_port():
   '''Starting with 6.0U1 3rd party code may use tcp/udp ports in range 32768-4095.
      Check and disable snmp agent if it uses a port in restricted range, log to syslog.
   '''
   doc = etree.parse(cfg)
   items = doc.findall('/snmpSettings/port')
   if not items:
       syslog(LOG_WARN, 'SNMP agent config file did not specify port, agent defaults to 161.')
       return 0
   port = int(items[0].text)
   if Is3rdPartyPort(port):
        syslog(LOG_ERR, 'SNMP agent configured with restricted UDP port range %s inclusive.' % PortsFor3rdPartyToString())
        nodes = doc.findall('/snmpSettings/enable')
        if nodes:
          syslog(LOG_ERR, 'SNMP agent has been disabled until port has been changed.')
          nodes[0].text = 'false'
          doc.write(cfg)
          return 1
   return 0

def main():
   try:
      openlog("upgrade-snmp", LOG_PID|LOG_PERROR, LOG_DAEMON)
      sys.exit(check_poll_port())
   except Exception as err:
      import traceback
      syslog(LOG_ERR,'Caught unexpected exception: %s' % err)
      syslog(LOG_ERR, traceback.format_exc())

if __name__ == '__main__':
    main()
