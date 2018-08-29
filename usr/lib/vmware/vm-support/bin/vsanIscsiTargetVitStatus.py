#!/bin/python
#
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# This script will collect some information about vit status.

import subprocess
import json

rawOutput = '=' * 20 + 'RAW OUTPUT' +  '=' * 20 + '\n'
errorMsg = '!ERROR! Please check raw output for more detail.'
uuidHostnameMap = {}

def printTargetAliasWithOwnersHostname():
   cmd = 'localcli --formatter json vsan iscsi target list'
   print('>' * 3 + "iscsi target: <alias, owner's hostname>")
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      print(errorMsg)
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   output = json.loads(output)
   for entry in output:
      print(entry['Alias'] + '\t' + uuidHostnameMap[entry['I/O Owner UUID']])

def appendToRawOutput(cmd, output):
   global rawOutput
   rawOutput += '-' * 50 + '\n'
   rawOutput += '>' + cmd + '\n'
   rawOutput += output

def getUuidHostnameMap():
   cmd = 'cmmds-tool find -t HOSTNAME -f json'
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return {}
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   uuidMap = {}
   output = json.loads(output)
   for entry in output['entries']:
      uuidMap[entry['uuid']] = entry['content']['hostname']
   return uuidMap

def getOwnerUuid(childUuid):
   cmd = 'cmmds-tool find -u {} -f json'.format(childUuid)
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return None
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   output = json.loads(output)
   #Get owner's uuid from fisrt record
   try:
      return output['entries'][0]['owner']
   except Exception as e:
      print(e)
      return None

def decorateTargetConfig():
   cmd = 'cmmds-tool find -t VSAN_ISCSI_TARGET_CONFIG -f json'
   print('>' * 3 + cmd)
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      print(errorMsg)
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   output = json.loads(output)
   for entry in output['entries']:
      ownerUuid = getOwnerUuid(entry['uuid'])
      if ownerUuid:
         entry['ownerUuid'] = ownerUuid
         entry['ownerHostname'] = uuidHostnameMap[ownerUuid]
      else:
         entry['ownerUuid'] = 'NOT_FOUND'
         entry['ownerHostname'] = 'NOT_FOUND'
      print(entry)

def dumpTargetNetIfAddress():
   cmd = 'cmmds-tool find -t VSAN_ISCSI_TARGET_NET_IF_ADDRESS -f json'
   print('>' * 3 + cmd)
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      print(errorMsg)
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   output = json.loads(output)
   if len(output['entries']) != 0:
      print(output)

def dumpNamespaceGet():
   cmd = 'localcli --formatter json vsan iscsi homeobject get'
   print('>' * 3 + cmd)
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as e:
      print(errorMsg)
      appendToRawOutput(cmd, e.output.decode('utf-8'))
      return
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   print(output)

def isIscsiEnabled():
   cmd = 'localcli --formatter json vsan iscsi status get'
   try:
      output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
   except subprocess.CalledProcessError as cpe:
      print(errorMsg)
      appendToRawOutput(cmd, cpe.output.decode('utf-8'))
      return False
   output = output.decode('utf-8')
   appendToRawOutput(cmd, output)
   output = json.loads(output)
   return output['Enabled']

def main():
   try:
      if isIscsiEnabled():
         global uuidHostnameMap
         uuidHostnameMap = getUuidHostnameMap()
         printTargetAliasWithOwnersHostname()
         decorateTargetConfig()
         dumpTargetNetIfAddress()
         dumpNamespaceGet()
      else:
         print('!vsan iscsi not enabled!')
   except Exception as e:
      ##Print any exceptiont to stdout, so that we can log it into file
      print(e)
   print(rawOutput)

if __name__ == "__main__":
   main()
