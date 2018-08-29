#!/bin/python

#
# Copyright 2014 VMware, Inc.  All rights reserved.
#
# Fixes configrules to reject some host specific special paths.
#
import os, tempfile
import vmware.vsi

# Helper to replace the text between lines that contain startTag and endTag.
def ReplaceLines(fileName, startTag, endTag, newText):
   tmp = tempfile.NamedTemporaryFile(
      dir=os.path.dirname(fileName), delete=False)
   copy = True
   success = True

   try:
      with open(fileName, 'r') as f:
         for line in f:
            if copy:
               tmp.write(line)
               if line.find(startTag) != -1:
                  copy = False
                  success = False # Reset if endTag is found.
                  tmp.write(newText)
            else:
               if line.find(endTag) != -1:
                  tmp.write(line)
                  copy = True
                  success = True
   except:
      success = False

   tmp.close()
   if success:
      sr = os.stat(fileName)
      os.chown(tmp.name, sr.st_uid, sr.st_gid)
      os.chmod(tmp.name, sr.st_mode)
      os.rename(tmp.name, fileName)
   else:
      os.unlink(tmp.name)

def VolumesByFilesystemType(fsType):
   dsRoot = '/vmfs/volumes/'
   vsiVolRoot = '/system/fsSwitch/volumes/'

   for node in vmware.vsi.list(vsiVolRoot):
      vol = vmware.vsi.get(vsiVolRoot + node)
      if vol['fsType'].lower() == fsType.lower():
         yield os.path.join(dsRoot, vol['volumeName'], '')

def GetScratchPath():
   return os.path.join(os.path.realpath('/scratch'), '')

rejects = ['  reject regex_case "^{0}"'.format(d)
           for d in VolumesByFilesystemType('vfat')]
rejects.append('  reject regex_case "^{0}"'.format(GetScratchPath()))

ReplaceLines('/etc/vmware/configrules',
             'SPECIAL_PATHS_START_TAG',
             'SPECIAL_PATHS_END_TAG',
             '\n'.join(rejects) + '\n')
