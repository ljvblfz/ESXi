#**********************************************************
# * Copyright 2012-2014 VMware, Inc. All rights reserved. -- VMware Confidential
# * **********************************************************

#
# cmmdsAnalyzer.py --
#
#      Analyze cmmds dump for some interesting information automatically.
#

import sys
from optparse import OptionParser, SUPPRESS_HELP
import subprocess
import json

IMAGE_APP_PATH="/sbin/"
LOCALCLI_PY="/sbin/localcli --formatter=python "
LOCALCLI="/sbin/localcli "
cmmdsDir = None

# pythonMode indicates that the vsan epxression for each entry is in python format,
# otherwise it is considered to be json format.
pythonMode = False

UNAVAIL = "Value not available"
UNKNOWN = "Value unknown"

#
# Some static keywords that are used while displaying the information with 
# this tool.
#
KW_CONFIG_NAME = 'Configuration'
KW_COMP_COUNT  = 'ComponentCount'
KW_COMPS       = 'Components'
KW_COMP_UUID   = 'Uuid'
KW_DISK_UUID   = 'DiskUuid'
KW_NODE_UUID   = 'HostNodeUuid'
KW_NODE_HEALTH = 'Health'
KW_HOST        = 'HostAddress'
KW_HOST_ADDR   = 'IP Address'
KW_HOST_HEALTH = 'Interface Health'
KW_OBJ_UUID    = 'Object'
KW_OBJ_HEALTH  = 'ObjectHealth'
KW_ATTRIBUTES  = 'Attributes'

#
# Convenient wrapper for localcli python formatter command
#
def LocalCliPy(cmd):
   return '%s %s' % (LOCALCLI_PY, cmd)

#
# Convenient wrapper for localcli command
#
def LocalCli(cmd):
   return '%s %s' % (LOCALCLI, cmd)

#
# Execute the given command and return the >returnCode, std output result> tuple.
#
def ExecuteCmd(cmd, silent=False):
   if not silent:
      print("Executing %s" % cmd)
      
   p = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   result = p.communicate()[0]

   if not silent:
      print("Executing %s returned %d" % (cmd, p.returncode))

   if (p.returncode != 0):
      return p.returncode, result

   return 0, result

#
# Run the cmmds-tool. Evaluate the result to be as it is some valid python object.
#
def RunCmmdsTool(cmd, noeval = False):
   ret, res = ExecuteCmd('/sbin/cmmds-tool %s' % cmd)
   if (ret != 0):
      raise Exception('Failed to execute cmd /sbin/cmmds-tool %s' % cmd)

   if not noeval:
      res = eval(res)
      
   return res

#
# Run the cmmds-tool. Don't evaluate the o/p, just return as it is.
#
def RunCmmdsToolNoEval(cmd):
   return RunCmmdsTool(cmd, noeval = True)

#
# Read the cmmds directory content off either the binary dump file
# of a json formatted dump file, or a python formatted dump file.
#
def GetCmmdsDirFromDumpfile(dumpfile, isjson, ispython):
   cmmds = None

   # Read a json format directory file (as from the content of vm-support)
   if isjson:
      cmmds = json.load(open(dumpfile))
      cmmds = cmmds['entries']
   elif ispython:
      f = open(dumpfile)
      cmmds = eval(f.read())
      
      # strip the header if the dump has it.
      if 'magic' in cmmds[0] and 'major' in cmmds[0]:
         cmmds = cmmds[1:]

   else:
      cmmds = RunCmmdsToolNoEval('-f json readdump -d %s' % dumpfile)

   return cmmds

#
# Read the cmmds directory content from live system.
# Assumes that cmmds is enabled.
#
def GetCmmdsDirLive():
   return RunCmmdsTool('-f python find')


#
# A simple memoization wrapper. (stole from modules/vmkernel/tracing/traceEntry.py)
#
class memoized(object):
   def __init__(self, function):
      self.function = function
      self.cache = {}

   def __call__(self, *args):
      try:
         return self.cache[args]
      except KeyError:
         result = self.function(*args)
         self.cache[args] = result
         return result

#
# Define some exceptions of our own.
#
class ObjectNotFoundException(Exception):
   def __init__(self, objectuuid):
      self.objectuuid = objectuuid

   def __str__(self):
      return "Failed to find object %s" % self.objectuuid

class ComponentNotFoundException(Exception):
   def __init__(self, cuuid):
      self.cuuid = cuuid

   def __str__(self):
      return "Failed to find component with uuid %s" % self.cuuid
   
class LocationNotFoundException(Exception):
   def __init__(self, nodeuuid):
      self.nodeuuid = nodeuuid

   def __str__(self):
      return "Failed to find location (ip addresses) for node (%s)" % self.nodeuuid

#
# Defines the base class for an object configuration.
#
class ObjectConfig(object):
   def __init__(self, comptree, indentlevel = 0):
      self.indent = indentlevel
      self.tree = comptree
      self.name = self.tree['type']
      self.components = ExploreConfig(self.tree, indentlevel + 2)
      self.attributes = self.tree['attributes']
      self.args = {}
      self.args.update({KW_ATTRIBUTES : self.attributes})
      self.args.update({KW_CONFIG_NAME : self.name})
      self.args.update({KW_COMP_COUNT : len(self.components)})
      self.args.update({KW_COMPS : [eval(str(c)) for c in self.components]})

   def SetAttrs(self, **kwargs):
      for kw in kwargs.keys():
         self.args.update({kw : kwargs[kw]})
         if kw == KW_NODE_UUID:
            self.args.update({ KW_HOST : GetLocationForNode(kwargs[kw])})

   def __str__(self):
      self.representation = json.dumps(self.args, sort_keys = True, indent=self.indent)
      return self.representation

#
# Root object.
#
class RootObjectConfig(ObjectConfig):
   def __init__(self, comptree, indentlevel):
      assert(comptree['type'] == 'Configuration')

      # Root object is the object, i.e. we can explore the configuration
      # tree for this object just the way we would when we are looking for
      # components of an object, but we'll always get only one component.
      comps = ExploreConfig(comptree)
      assert(len(comps) == 1)
      self.objectConfig = comps[0]

   def SetAttrs(self, **kwargs):
      self.objectConfig.SetAttrs(**kwargs)

   def __str__(self):
      return str(self.objectConfig)

#
# Inner object (not root, not leaf). This is same as the ObjectConfig.
#
class InnerObjectConfig(ObjectConfig):
   def __init__(self, comptree, indentlevel):
      ctype = comptree['type']
      assert(ctype != 'Configuration' and ctype != 'Component')
      super(InnerObjectConfig, self).__init__(comptree, indentlevel)


#
# Get the components of the object whose configuration is flat
#
class LeafObjectConfig(ObjectConfig):
   def __init__(self, comptree, indentlevel):
      assert(comptree['type'] == 'Component')
      super(LeafObjectConfig, self).__init__(comptree, indentlevel)

      cnuuid, cnhealth = GetComponentInfo(self.tree['componentUuid'])

      self.SetAttrs(**{KW_COMP_UUID : self.tree['componentUuid'],
                       KW_DISK_UUID : self.tree['diskUuid'],
                       KW_NODE_UUID : cnuuid,
                       KW_NODE_HEALTH : cnhealth})
      
      #
      # LEAF object doens't have any components. Assert that and then
      # remove those fields.
      #
      assert(len(self.components) == 0)
      assert(self.args[KW_COMP_COUNT] == 0)
      
      del(self.args[KW_COMP_COUNT])
      del(self.args[KW_COMPS])

#
# Traverses the configuration tree looking for various object
# configurations.
#
def ExploreConfig(configtree, indentlevel = 0):
   numConfigs = 1
   configObjs = []
   while True:
      keyConfigI = 'child-%d' % numConfigs
      try:
         configI = configtree[keyConfigI]
         numConfigs = numConfigs + 1
         configIType = configI['type']
         
         configObject = None
         if configIType == 'Configuration':
            configObject = RootObjectConfig(configI, indentlevel)
         elif configIType == 'Component':
            configObject = LeafObjectConfig(configI, indentlevel)
         else:
            configObject = InnerObjectConfig(configI, indentlevel)

         assert (configObject != None)
         configObjs.append(configObject)

      except KeyError as e:
         break
   
   return configObjs

#
# Define some vsan expression classes of our own. 
# For every specific expression, the expression class should implement the getters
# for interesting items in that expression. 
#
class VsanExpr(object):
   def __init__(self, expression):
      expr = expression
      if pythonMode:
         expr = eval(expression)
      self.items = expr
   
   def __str__(self):
      return str(self.items)

class NetInterfaceExpr(VsanExpr):
   def getIpAddr(self):
      # sample expression: ['1', ['10.114.169.242', '255.255.224.0', '224.2.3.4', '224.1.2.3'], '23451', '12345', '5', '0', '000000000000']
      # Note the ip address field.
      return self.items[1][0]

class ConfigurationExpr(VsanExpr):
   def getConfigObject(self):
      # Make sure we are looking at the object configuration expression.
      assert (isinstance(self.items, dict))
      assert (self.items['type'] == 'Configuration')
      return RootObjectConfig(self.items, 0)
      #return Traverse(self.items)[0]

#
# Get the information (owner uuid and configuration as vsan expression) for
# the given object, either based on the uuid (in which case directory will
# be traversed, otherwise directly from the entry already fetched from the
# directory.
#
def GetInfoForObject(objectuuid):
   for e in cmmdsDir:
      if e['type'] == 'DOM_OBJECT' and e['uuid'] == objectuuid:
         return e['owner'], e['content'], e['health']
   
   return UNAVAIL
   
#
# Given a component uuid, find the entry for this component and then get
# the owner node uuid and health info for that component. 
#
def GetComponentInfo(compuuid):
   for e in cmmdsDir:
      if e['type'] == 'LSOM_OBJECT' and e['uuid'] == compuuid:
         return e['owner'], e['health']
   
   return UNAVAIL, UNAVAIL

#
# Get all the objects in the system.
#
def GetAllObjects(cmmdsDir):
   assert len(cmmdsDir) != 0

   objects = []
   for e in cmmdsDir:
      if e['type'] == 'DOM_OBJECT':
         objects.append(e)
   
   return objects

#
# Get the IP addresses in use by VSAN of the host with the given uuid.
#
@memoized
def GetLocationForNode(nodeuuid):
   # There may be multiple interfaces.
   addresses = []
   for e in cmmdsDir:
      if e['type'] == 'NET_INTERFACE':
         if e['owner'] == nodeuuid:
            location = NetInterfaceExpr(e['content'])
            ifacehealth = e['health']
            addresses.append({KW_HOST_ADDR : location.getIpAddr(), 
                              KW_HOST_HEALTH : ifacehealth})

   if not len(addresses):
      return [{KW_HOST_ADDR: UNAVAIL, KW_HOST_HEALTH: UNKNOWN}]

   return addresses


def GetAllInfoForObjectInt(ownernode, contents, health, objectuuid):

   c = ConfigurationExpr(contents)
   objectConfig = c.getConfigObject()

   objectConfig.SetAttrs(**{KW_OBJ_HEALTH : health,
                            KW_OBJ_UUID : objectuuid,
                            KW_NODE_UUID: ownernode})

   return str(objectConfig)
   
#
# Get all the information for this object uuid. Things that we are interested in are:
# Onwer uuid of the object.
# IP address of the host thats' the owner.
# # of components:
# For each component, the host ip which has the component and the state of the comp.
#
def GetAllInfoForObject(objEntry):
   return GetAllInfoForObjectInt(objEntry['owner'], 
                                 objEntry['content'], 
                                 objEntry['health'], 
                                 objEntry['uuid'])

def GetAllInfoForObjectWithUuid(objectuuid):
   ownernode, contents, health = GetInfoForObject(objectuuid)
   return GetAllInfoForObjectInt(ownernode, contents, health, objectuuid)


def main():
    usageStr = 'Usage: %s [options]' % sys.argv[0]

    parser = OptionParser(usageStr)
    uuidhelp = "uuid of the object that needs to be located"
    parser.add_option("-u", "--uuid", dest="objectuuid", default = None, 
                      type="string", help=uuidhelp)

    dumpfileHelp = '''Optional: read cmmds content off the specified dump 
file. If not provided, live cmmds directory will be read from the system. 
The dumpfile could be a binary dump, or a structured o/p formatted
file (like in json/python). See --json/--python options'''
    parser.add_option("-d", "--dumpfile", dest="dumpfile", default = None, 
                      type="string", help=dumpfileHelp)

    inJsonHelp = '''If dumpfile is provided, then read the content
as json formatted. By default the content is considered to be in binary. 
A JSON formatted dump file could be what's produced by vm-support, for example.'''

    parser.add_option("-j", "--json", dest="json", default = False, 
                      action = "store_true", help=inJsonHelp)

    inPythonHelp = '''If dumpfile is provided, then read the content 
as python formatted. By default the content is considered to be in 
binary. A python formatted dump file could be what's produced as a 
result of manually reading off a binary dump file into a python 
dictionary of entries.  --json/--python are exclusive'''
    parser.add_option("-p", "--python", dest="python", default = False, 
                      action = "store_true", help=inPythonHelp)
        
    opts, args = parser.parse_args()
    allobjects = False
    
    # If not looking for specific uuid. Print info for all the objects.
    if opts.objectuuid == None:
       allobjects = True

    if opts.json and opts.python:
       parser.print_help()
       return -1

    global pythonMode
    pythonMode = opts.python

    global cmmdsDir
    cmmdsDir = []
    if (opts.dumpfile != None):
       cmmdsDir = GetCmmdsDirFromDumpfile(opts.dumpfile, opts.json, opts.python)
    else:
       cmmdsDir = GetCmmdsDirLive()

    if len(cmmdsDir) == 0:
       print("Failed to get the cmmds directory content")
       return -1

    if allobjects:
       objects = GetAllObjects(cmmdsDir)
       
       objInfo = []
       for o in objects:
          objInfo.append(eval(GetAllInfoForObject(o)))

       print(json.dumps(objInfo, sort_keys = True, indent = 2))
          
    else:
       assert (opts.objectuuid != None)
       objInfo = eval(GetAllInfoForObjectWithUuid(opts.objectuuid))
       print(json.dumps(objInfo, sort_keys = True, indent = 2))
          
    return 0

if __name__ == "__main__":
   sys.exit(main())
