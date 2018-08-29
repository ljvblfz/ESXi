#!/usr/bin/python
"""
Copyright 2014-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

from argparse import ArgumentParser
from pyVmomi import vim, vmodl
from pyVim.connect import SmartConnect, Disconnect

import xml.dom.minidom
import atexit
import os
import sys

ESXCLI_NS = "http://www.vmware.com/Products/ESX/5.0/esxcli/"


#
# Append a field element to the specified structure element.
#
# <field name="name">
#    <string>val</string>
# </field>
#

def AppendStructField(doc, structEl, name, val, fieldType="string"):
   fieldEl = doc.createElementNS(ESXCLI_NS, "field")
   fieldEl.setAttribute("name", name)
   structEl.appendChild(fieldEl)
   stringEl = doc.createElementNS(ESXCLI_NS, fieldType)
   fieldEl.appendChild(stringEl)
   stringEl.appendChild(doc.createTextNode(val))


#
# Append to the specified list element a new structure element
# containing information about the given permission (ACE).
#
# <structure typeName="ACE">
#    ...
# </structure>
#

def AppendPermissionStruct(doc, listEl, ace):
   structEl = doc.createElementNS(ESXCLI_NS, "structure")
   structEl.setAttribute("typeName", "Permission")
   listEl.appendChild(structEl)
   AppendStructField(doc, structEl, "Principal", ace.principal)
   isGroupStr = "true" if ace.group else "false"
   AppendStructField(doc, structEl, 'Is Group', isGroupStr, "bool")

   # Role and role description
   accessMode = ace.accessMode
   role = ""
   roleDescription = ""
   if accessMode == "accessAdmin":
      role = "Admin"
      roleDescription = "Full access rights"
   elif accessMode == "accessReadOnly":
      role = "ReadOnly"
      roleDescription = "See details of objects, but not make changes"
   elif accessMode == "accessNoAccess":
      role = "NoAccess"
      roleDescription = "Explicit access restriction"
   elif accessMode == "accessOther":
      role = "Custom"
      roleDescription = \
         "User-defined roles or roles on non-root inventory objects"

   AppendStructField(doc, structEl, "Role", role)
   AppendStructField(doc, structEl, "Role Description", roleDescription)


#
# Print as XML the specified list of permissions.
#
# <output>
#    <list>
#       ...
#    </list>
# </output>
#

def PrintPermissionListXml(aces):
   doc = xml.dom.minidom.Document()
   outputEl = doc.createElementNS(ESXCLI_NS, "output")
   outputEl.setAttribute("xmlns", ESXCLI_NS)
   doc.appendChild(outputEl)
   listEl = doc.createElementNS(ESXCLI_NS, "list")
   listEl.setAttribute("type", "structure")
   outputEl.appendChild(listEl)
   for ace in aces:
      AppendPermissionStruct(doc, listEl, ace)
   print(doc.toxml())


#
# Print success XML.
#
# <output>
#    <bool>true</bool>
# </output>
#

def PrintSuccessXml():
   doc = xml.dom.minidom.Document()
   outputEl = doc.createElementNS(ESXCLI_NS, "output")
   outputEl.setAttribute("xmlns", ESXCLI_NS)
   doc.appendChild(outputEl)
   boolEl = doc.createElementNS(ESXCLI_NS, "bool")
   outputEl.appendChild(boolEl)
   boolEl.appendChild(doc.createTextNode("true"))
   print(doc.toxml())


#
# List permissions.
#

def ListPermissions(args, accessMgr):
   aces = accessMgr.RetrieveHostAccessControlEntries()
   PrintPermissionListXml(aces)


#
# Set permission.
#

def SetPermission(args, accessMgr):
   accessMode = ""
   if args.role == "Admin":
      accessMode = "accessAdmin"
   elif args.role == "ReadOnly":
      accessMode = "accessReadOnly"
   elif args.role == "NoAccess":
      accessMode = "accessNoAccess"
   else:
      print("ERROR: Invalid role specified.")
      return

   # ESXi local groups are not supported
   if args.group:
      #
      # Domain users can be specified like this:
      #   DOMAIN\user
      #   user@DOMAIN
      #
      if args.id.find('\\') == -1 and args.id.find('@') == -1:
         print("ERROR: ESXi local groups are not supported.")
         return

   accessMgr.ChangeAccessMode(args.id, args.group, accessMode)
   PrintSuccessXml()


#
# Remove permission.
#

def RemovePermission(args, accessMgr):
   accessMgr.ChangeAccessMode(args.id, args.group, 'accessNone')
   PrintSuccessXml()



#
# Main entry point.
#

def main():
   parser = ArgumentParser(
      description='Manage permissions for accessing the ESXi host.')
   subparsers = parser.add_subparsers()

   # parser for command "list"
   parser_list = subparsers.add_parser('list',
      help='List permissions defined on the host.')
   parser_list.set_defaults(func=ListPermissions)

   # parser for command "set"
   parser_set = subparsers.add_parser('set',
      help='Set permission for a user or group.')
   parser_set.add_argument('--id', required=True,
                              help="ID of user or group")
   parser_set.add_argument('--group', action="store_true",
                              help="Specifies that --id refers to a group")
   parser_set.add_argument('--role', required=True,
                           help="Name of role that specifies user access "\
                                "rights. [Admin, ReadOnly, NoAccess].")
   parser_set.set_defaults(func=SetPermission)

   # parser for command "remove"
   parser_remove = subparsers.add_parser('remove',
      help='Remove permission for a user or group.')
   parser_remove.add_argument('--id', required=True,
                              help="ID of user or group")
   parser_remove.add_argument('--group', action="store_true",
                              help="Specifies that --id refers to a group")
   parser_remove.set_defaults(func=RemovePermission)


   # parse command line arguments
   args = parser.parse_args()

   # Connect as the user specified in VI_USERNAME environment variable
   userName = os.getenv('VI_USERNAME', '')
   try:
      si = SmartConnect(host='localhost', user=userName)
      rootFolder = si.content.rootFolder
      host = rootFolder.childEntity[0].hostFolder.childEntity[0].host[0]
      accessMgr = host.configManager.hostAccessManager
      atexit.register(Disconnect, si)
      args.func(args, accessMgr)
   except vmodl.MethodFault as e:
      print('ERROR: %s' % e.msg)
   except Exception as e:
      print('ERROR: %s' % e)


if __name__ == '__main__':
    main()

