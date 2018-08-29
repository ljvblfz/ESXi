#!/usr/bin/python -u
########################################################################
#
# Description: Module for osfs IPC functionality
#
########################################################################

#
# This module should not import any test-esx specific Python modules,
# so that it can be used from utility scripts outside of 'test-esx'.
#
from __future__ import print_function
import errno
import socket
import struct
from ctypes import create_string_buffer
import time
import sys

PY3 = sys.version_info > (3,)
# ----------------------------------------------------------------------------
# IPC stuff

#
# from bora/public/osfs/ipc.h
#
OSFSD_IPC_OP_CREATENS      = 0
OSFSD_IPC_OP_DELETENS      = 1
OSFSD_IPC_OP_MOUNTNS       = 2
OSFSD_IPC_OP_UMOUNTNS      = 3
OSFSD_IPC_OP_PRIVATE       = 4
OSFSD_IPC_OP_UPDATENS      = 5
OSFSD_IPC_OP_RENAMENS      = 6
OSFSD_IPC_OP_RESIGNATURENS = 7
OSFSD_IPC_OP_LISTPROVIDERS = 8

OSFSD_IPC_ERR_SUCCESS = 0
OSFSD_IPC_ERR_FAIL    = 1
OSFSD_IPC_ERR_EEXIST  = 0xbad0005
OSFSD_IPC_ERR_ENOENT  = 0xbad0003
OSFSD_IPC_ERR_VERSION = 2

VOB_CTX_HANDLE        = 0xFFFFFFFFFFFFFFFF


class IpcResult:
   def __init__(self, error, uuid=None, opID=None, privateBuffer=None):
      self.error = error
      self.uuid = uuid
      self.opID = opID
      self.privateBuffer = privateBuffer

#
# Namespace IPC call
#
def NSIpc(action,
          entryName,
          objectUuid,
          providerID,
          containerID,
          bufferSize = 0x0,
          buffer = None,
          force = False):
   # we were not given an opid, so generate a new one
   opID = "osfsIpc-%s" % time.time()
   return NSIpcWithOpID(action, entryName, objectUuid, providerID, containerID,
                        opID, bufferSize, buffer, force)


def NSIpcWithOpID(action,
                  entryName,
                  objectUuid,
                  providerID,
                  containerID,
                  opID,
                  bufferSize = 0x0,
                  buffer = None,
                  force = False):

   uuid = None
   returnValue = 1

   #
   # Sanity asserts for the variable-length policy and container context.
   #
   if (buffer is not None):
      assert(bufferSize != 0)

   if (bufferSize > 0):
      assert buffer is not None
      OsfsdIpcBuffer = "%ds" % bufferSize
      bufferPayload = create_string_buffer(bufferSize)
      if PY3:
         struct.pack_into(OsfsdIpcBuffer, bufferPayload, 0, bytes(buffer, 'utf-8'))
      else:
         struct.pack_into(OsfsdIpcBuffer, bufferPayload, 0, buffer)

   #
   # Keep in-sync with struct IpcRequest in bora/public/osfs/ipc.h.
   #
   OSFSD_IPC_REQUEST_SIZE = (434 + 8)
   IpcVersion = int(0x00000001)

   #
   # See http://docs.python.org/library/struct.html
   #
   OsfsdIpcEntry = "128s64s64s8s16sQ129sQQB"
   OsfsdIpcRequest = "=II%s" % (OsfsdIpcEntry)
   assert(struct.calcsize(OsfsdIpcRequest) == OSFSD_IPC_REQUEST_SIZE)

   #
   # Pack the payload buffer
   #
   payload = create_string_buffer(OSFSD_IPC_REQUEST_SIZE)
   forceFlag = int(0x00)
   if force:
      forceFlag = int(0x01)

   if PY3:
      if isinstance(containerID, str):
         containerID = bytes(containerID, 'utf-8')
      struct.pack_into(OsfsdIpcRequest,
                       payload,
                       0,
                       IpcVersion,
                       action,
                       bytes(entryName, 'utf-8'),
                       bytes(objectUuid, 'utf-8'),
                       #
                       # dummy VmUuid
                       #
                       bytes("12345678-1234-1234-1234-123456789012", 'utf-8'),
                       bytes(providerID, 'utf-8'),
                       containerID,
                       VOB_CTX_HANDLE,
                       bytes(opID, 'utf-8'),
                       0,
                       bufferSize,
                       forceFlag)
   else:
      struct.pack_into(OsfsdIpcRequest,
                       payload,
                       0,
                       IpcVersion,
                       action,
                       entryName,
                       objectUuid,
                       #
                       # dummy VmUuid
                       #
                       "12345678-1234-1234-1234-123456789012",
                       providerID,
                       containerID,
                       VOB_CTX_HANDLE,
                       opID,
                       0,
                       bufferSize,
                       forceFlag)

   #
   # Create socket connection
   #
   s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
   s.connect("OSFSD_IPC")

   #
   # Send the payload
   #
   bytesSent = 0
   while (bytesSent < OSFSD_IPC_REQUEST_SIZE):
      try:
         bytesSent += s.send(payload[bytesSent:])
      except socket.error as err:
         if (err.errno != errno.EINTR):
            raise

   if (buffer is not None):
      bytesSent = 0
      while (bytesSent < bufferSize):
         try:
            bytesSent += s.send(bufferPayload[bytesSent:])
         except socket.error as err:
            if (err.errno != errno.EINTR):
               raise

   ##
   ## For debugging...
   ##
   #sent = struct.unpack_from(OsfsdIpcRequest, payload, 0)
   #print "Sent this payload:\n%s" % str(sent)

   # Try receiving response
   try:
      # First receive the IPC request structure
      recvd = 0
      payload = b"" if PY3 else ""
      while (recvd < OSFSD_IPC_REQUEST_SIZE):
         try:
            chunk = s.recv(OSFSD_IPC_REQUEST_SIZE - recvd)
            recvd += len(chunk)
            if (chunk == b""):
               #print "Received zero length message, assume hung up"
               break
            else:
               #print "Received a message len %d" % len(chunk)
               payload = payload + chunk
         except socket.error as err:
            if (err.errno != errno.EINTR):
               raise

      if (len(payload) != OSFSD_IPC_REQUEST_SIZE):
         returnValue = 1
         return IpcResult(returnValue, None, opID)

      # Unpack the IPC request
      result = struct.unpack_from(OsfsdIpcRequest, payload, 0)
      if (result[1] == OSFSD_IPC_ERR_SUCCESS):
         returnValue = 0
      elif (result[1] == int(OSFSD_IPC_ERR_EEXIST)):
         returnValue = 2
      elif (result[1] == int(OSFSD_IPC_ERR_ENOENT)):
         returnValue = 3
      else:
         returnValue = 1


      # return uuid for create operations
      # return it as a C-style NULL-terminated string
      # as the callers expect it like that
      if (action == OSFSD_IPC_OP_CREATENS):
         if PY3:
            uuid = result[3].split(b'\x00', 1)[0].decode('utf-8')
         else:
            uuid = result[3].split('\x00', 1)[0]

      # Receive the variable-length private response buffer
      payload = None
      if (result[10] != 0):
         recvd = 0
         payload = b""
         emptyBytes = b"" if PY3 else ""
         while (recvd < result[7]):
            try:
               chunk = s.recv(result[10] - recvd)
               recvd += len(chunk)
               if (chunk == emptyBytes):
                  break
               else:
                  payload += chunk
            except socket.error as err:
               if (err.errno != errno.EINTR):
                  raise

         # Error if we didn't receive all of response private buffer
         if (recvd != result[10]):
            returnValue = 1

   except KeyboardInterrupt:
      #print "Keyboard interrupt, exiting"
      pass

   try:
      s.close()
   except Exception as e:
      print("Error: %s" % str(e))

   return IpcResult(returnValue, uuid, opID, payload)
