#!/usr/bin/python

# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential

# Wrapper on python version of feature state library that is used by the
# shell version of the library (feature-state-.sh) to get the feature state
# info. If there is an error while getting the feature state value it causes
# the apllication using the library to stop.

import sys
import traceback
import featureState

def main():
   try:
      featureState.init(enableLogging=False)
      retVal = 'enabled'
      state = featureState.__dict__['get%s' % sys.argv[1]]()
      if not state:
         retVal = 'disabled'
      print(retVal)
   except Exception as exc:
      print("\nFatal error while getting feature state for '%s'" %
            (sys.argv[1]))
      excStr = traceback.format_exc()
      print("%s" % excStr)
      print("Exiting with error code 71")
      sys.exit(71)
   sys.exit(0)


if __name__ == '__main__':
   main()
