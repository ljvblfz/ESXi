#!/usr/bin/env python

########################################################################
# Copyright 2016 VMware, Inc.  All rights reserved.
# -- VMware Confidential
########################################################################

if __name__ == '__main__':
   import sys
   from vmware.secureboot import secureBootCheck
   sys.exit(secureBootCheck.main())
