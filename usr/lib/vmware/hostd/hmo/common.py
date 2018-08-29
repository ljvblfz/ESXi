#!/usr/bin/env python

import logging

from optparse import OptionParser
from contrib.vorb import VmomiOrb
from contrib.logUtils import LoggingFactory

from pyVmomi import Vmodl

def InitVorb():
   parser = OptionParser()
   LoggingFactory.AddOptions(parser)

   VmomiOrb.AddOptions(parser, defaultSoapPort=8300)
   (options, args) = parser.parse_args()
   LoggingFactory.ParseOptions(options)
   vorbOptions = VmomiOrb.ProcessOptions(options, args)

   vorb = VmomiOrb()
   vorb.InitializeServer(vorbOptions)
   return vorb

class ExtensibleMOImpl:
   """
   Implementation of Vim.ExtensibleManagedObject methods
   """
   def __init__(self):
       pass

   @property
   def availableField(self):
      return []

   @property
   def value(self):
      return []

   def setCustomValue(self):
      raise Vmodl.Fault.NotSupported()
