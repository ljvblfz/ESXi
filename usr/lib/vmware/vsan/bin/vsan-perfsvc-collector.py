#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Copyright 2016 VMware, Inc.  All rights reserved.
-- VMware Confidential

This is the controller entry point of perf stats collector
"""

__author__ = 'VMware, Inc'

import sys
import os
import socket
import pyVmomi
from pyVmomi import vim
import vsanPerfPyMo

## Parse arguments
#

def ParseArguments(argv):
   """ Parse arguments """

   from optparse import OptionParser, make_option

   # Internal cmds supported by this handler
   _STR_USAGE = '%prog [start|stop]'

   # Get command line options
   cmdParser = OptionParser(usage=_STR_USAGE)

   # Parse arguments
   (options, args) = cmdParser.parse_args(argv)
   try:

      # optparser does not have a destroy() method in older python
      cmdParser.destroy()
   except Exception:
      pass
   del cmdParser
   return (options, args)


## Main
#

def main():
   """ Main """

   (options, cmdArgs) = ParseArguments(sys.argv[1:])
   command = cmdArgs and cmdArgs[0] or 'start'

   #Set the global default socket timeout to avoid infinite blocking.
   socket.setdefaulttimeout(90)

   try:
      stubAdapter = pyVmomi.SoapStubAdapter(
         'localhost', 80,
         version='vim.version.version10',
         sslProxyPath='/vsanperf',
         certKeyFile='/etc/vmware/ssl/rui.key',
         certFile='/etc/vmware/ssl/rui.crt')

      vpm = vim.cluster.VsanPerformanceManager(
         "vsan-performance-manager",
         stubAdapter)

      methods = {
         'start': 'StartStatsCollector',
         'stop': 'StopStatsCollector',
      }

      getattr(vpm, methods[command])()
   except:
      sys.exit(1)

   sys.exit(0)

if __name__ == '__main__':
   main()
