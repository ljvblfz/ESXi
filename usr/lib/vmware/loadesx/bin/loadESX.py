#!/usr/bin/env python ++group=host/vim/vmvisor/loadESX

########################################################################
# Copyright 2015-2017 VMware, Inc.  All rights reserved. -- VMware Confidential
########################################################################


if __name__ == '__main__':

   from sys import exit, argv
   from logging import exception

   from vmware.loadesx import runLoadEsx

   try:
      exit(runLoadEsx.main(argv[1:]))
   except Exception as e:
      exception(e)
