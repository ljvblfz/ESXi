#!/usr/bin/env python ++group=host/vim/vmvisor/vmsupport -u

# Copyright 2017 VMware, Inc.
# All rights reserved. -- VMware Confidential

"""vm-support wrapper for ESXi to make sure it runs in its own resource pool.
"""

import sys
import logging
from vmsupport.main import run, getArgumentParser

if __name__ == "__main__":

   parser = getArgumentParser()
   options = parser.parse_args(sys.argv[1:])
   try:
      run(options)
   except KeyboardInterrupt:
      logging.critical("%s interrupted", sys.argv[0])
      sys.exit(1)
   except Exception as ex:
      logging.exception("%s encountered an exception: %s", sys.argv[0], ex)
      sys.exit(1)
