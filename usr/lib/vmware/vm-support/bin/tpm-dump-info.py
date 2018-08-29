#!/bin/python
#
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# Dump relevant TPM data for vm-support.

from subprocess import (
   check_call,
)
from vmware.vsi import (
   get as getVsi,
)


TPM2_DUMPCAPS = "/usr/lib/vmware/tpm/bin/tpm2_dump_capability"
TPM2_NVLIST = "/usr/lib/vmware/tpm/bin/tpm2_nvlist"
TPM2_LISTPERSIST = "/usr/lib/vmware/tpm/bin/tpm2_listpersistent"


def isTpmPresent():
   """Check if a TPM is present in the system."""
   return getVsi("/hardware/tpm/present")


def isTpm2():
   """Check if the TPM is of family 2."""
   return getVsi("/hardware/tpm/version") == 2


def main():
   """Execute programs dumping TPM related information to standard out."""
   if not isTpmPresent() or not isTpm2():
      return

   check_call([TPM2_DUMPCAPS, "-c", "commands"])
   check_call([TPM2_DUMPCAPS, "-c", "algorithms"])
   check_call([TPM2_DUMPCAPS, "-c", "properties-fixed"])
   check_call([TPM2_DUMPCAPS, "-c", "properties-variable"])
   check_call([TPM2_NVLIST])
   check_call([TPM2_LISTPERSIST])


if __name__ == "__main__":
   main()
