#!/usr/bin/env python

########################################################################
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential
########################################################################


if __name__ == '__main__':

   from sys import exit, argv
   from logging import exception

   from vmware.loadesx import precheck

   try:
      exit(precheck.main(argv[1:]))
   except Exception as e:
      exception(e)
