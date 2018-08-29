#!/usr/bin/python

########################################################################
# Copyright (C) 2017 VMWare, Inc.                                      #
# All Rights Reserved                                                  #
########################################################################

'''Mount a tardisk from a vib securely with signature and checksum checked.
   Used by esximage library to live enable a vib during install/upgrade.
'''

import os
import sys
import shutil
import logging

from vmware.esximage import Errors
from vmware.esximage.HostImage import HostImage
from vmware.esximage.Installer import LiveImageInstaller, BootBankInstaller
from vmware.esximage.Utils import HashedStream

log = logging.getLogger('SecureMount')

def VerifyTardiskChecksum(tardiskpath, checksum):
   '''Verify tardisk checksum against payload metadata.
   '''
   BUFFER_SIZE = 4096

   hashalgo = checksum.checksumtype.replace('-', '')
   with open(tardiskpath, 'rb') as sourcefp:
      hashfp = HashedStream.HashedStream(sourcefp, checksum.checksum, hashalgo)
      inbytes = hashfp.read(BUFFER_SIZE)
      while inbytes:
         inbytes = hashfp.read(BUFFER_SIZE)

def FindVibInDB(vibid):
   '''Locate Vib object in staging databases.
   '''
   # Try staged LiveImage first, live vibs being installed should be there
   liveImage = LiveImageInstaller.LiveImage()
   if liveImage.stagedatabase and vibid in liveImage.stagedatabase.vibs:
      return liveImage.stagedatabase.vibs[vibid]

   # Otherwise it should be bootloader payload in esx-base, used in bootbank
   # installer, it will be in bootbank staging area
   stageBootBankPath = BootBankInstaller.BootBankInstaller.STAGEBOOTBANK
   if os.path.exists(stageBootBankPath):
      stageBootBank = BootBankInstaller.BootBank(stageBootBankPath)
      stageBootBank.Load(raiseerror = False)
      if vibid in stageBootBank.db.vibs:
         return stageBootBank.db.vibs[vibid]

   raise Exception('Unable to find vib %s in staging databases' % (vibid))

def VerifyVibAndPayload(vibid, payload, tardiskpath):
   '''Verify vib signature and payload checksum accociated with the payload.
   '''
   vib = FindVibInDB(vibid)

   # Verify vib acceptance and signature

   # A VIB can be installed with --no-sig-check or --force, log and warn
   # in case of validation errors.

   log.info('Verifying acceptance and signature for vib %s' % (vib.name))
   try:
      vib.VerifyAcceptanceLevel()
   except Errors.VibSignatureError as e:
      log.warn('Failed to verify signature for vib %s: %s' % (vib.name, e))
      HostImage.SendConsoleMsg('Attempting to mount a tardisk from a vib '
                               'without valid signature, this may result '
                               'in security breach.')
   except Errors.VibValidationError as e:
      log.warn('Failed to validate metadata against schema for vib %s: %s' %
               (vib.name, e))
      HostImage.SendConsoleMsg('Attempting to mount a tardisk from a vib '
                               'that failed metadata schema check, this may '
                               'result in package conflict or security '
                               'breach.')

   # Verify tardisk checksum
   for payloadObj in vib.payloads:
      if payloadObj.name == payload:
         # Only uncompressed checksum can be used for tardisk
         checksum = payloadObj.GetPreferredChecksum(verifyprocess='gunzip')
         if not checksum:
            raise Exception('Tardisk checksum is not found for payload %s' %
                            (payload))
         log.info('Verifying checksum on tardisk %s, expected hash %s' %
                  (payloadObj.name, checksum.checksum))
         VerifyTardiskChecksum(tardiskpath, checksum)
         return
   raise Exception('Payload %s not found in vib %s' % (payload, vib.name))

def MountTardisk(vibid, payload, tardiskpath, destname=None):
   '''Mount tardisk in live system.
   '''
   log.info("Mounting payload %s in vib %s, tardisk path %s" %
            (payload, vibid, tardiskpath))
   VerifyVibAndPayload(vibid, payload, tardiskpath)
   if not destname:
      shutil.move(tardiskpath, "/tardisks/")
   else:
      dest = "/tardisks/%s" % destname
      shutil.move(tardiskpath, dest)

if __name__ == "__main__":
   argvlen = len(sys.argv)
   try:
      if argvlen not in [4, 5]:
         msg = "Usage: secureMount.py <VIBID> <Payload> <Tardisk path> " \
               "[Dest name]"
         raise Exception(msg)
      if argvlen == 4:
         MountTardisk(sys.argv[1], sys.argv[2], sys.argv[3])
      else:
         MountTardisk(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
   except Exception as e:
      logging.exception("Failed to mount: %s" % str(e))
      sys.exit(-1)
