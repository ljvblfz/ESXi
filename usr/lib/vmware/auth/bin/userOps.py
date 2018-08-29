#!/usr/bin/python
"""
Copyright 2014-2017 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

from argparse import ArgumentParser
from pyVmomi import vim, vmodl
from pyVim.connect import Connect, Disconnect

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

def AppendUserField(doc, structEl, name, val):
   fieldEl = doc.createElementNS(ESXCLI_NS, "field")
   fieldEl.setAttribute("name", name)
   structEl.appendChild(fieldEl)
   stringEl = doc.createElementNS(ESXCLI_NS, "string")
   fieldEl.appendChild(stringEl)
   stringEl.appendChild(doc.createTextNode(val))


#
# Append to the specified list element a new structure element
# containing information about the given user.
#
# <structure typeName="UserInfo">
#    ...
# </structure>
#

def AppendUserStruct(doc, listEl, user):
   structEl = doc.createElementNS(ESXCLI_NS, "structure")
   structEl.setAttribute("typeName", "UserInfo")
   listEl.appendChild(structEl)
   AppendUserField(doc, structEl, "User ID", user.principal)
   AppendUserField(doc, structEl, 'Description', user.fullName)


#
# Print as XML the specified list of users.
#
# <output>
#    <list>
#       ...
#    </list>
# </output>
#

def PrintUserListXml(userList):
   doc = xml.dom.minidom.Document()
   outputEl = doc.createElementNS(ESXCLI_NS, "output")
   outputEl.setAttribute("xmlns", ESXCLI_NS)
   doc.appendChild(outputEl)
   listEl = doc.createElementNS(ESXCLI_NS, "list")
   listEl.setAttribute("type", "structure")
   outputEl.appendChild(listEl)
   for user in userList:
      AppendUserStruct(doc, listEl, user)
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
# List user accounts.
#

def ListUsers(args, si):
   userDir = si.content.userDirectory
   userList = userDir.RetrieveUserGroups(searchStr='', exactMatch=False,
                                         findUsers=True, findGroups=False)
   PrintUserListXml(userList)


#
# Create or change a user account.
#

def SetUser(args, si):
   accMgr = si.content.accountManager
   spec = vim.host.LocalAccountManager.PosixAccountSpecification()
   spec.id = args.id

   if args.description is not None:
      spec.description = args.description

   if args.password is not None:
      if args.password_confirmation is None:
         print("ERROR: Password confirmation expected")
         return
      if args.password != args.password_confirmation:
         print("ERROR: The specified passwords do not match")
         return
      spec.password = args.password

   if args.create:
      accMgr.CreateUser(spec)
   else:
      accMgr.UpdateUser(spec)

   PrintSuccessXml()


#
# Delete a user account.
#

def RemoveUser(args, si):
   accMgr = si.content.accountManager
   spec = vim.host.LocalAccountManager.PosixAccountSpecification()
   spec.id = args.id

   accMgr.RemoveUser(args.id)
   PrintSuccessXml()



#
# Main entry point.
#

def main():
   parser = ArgumentParser(description='User account operations.')

   subparsers = parser.add_subparsers(dest='cmd_name')

   # parser for command "set"
   parser_add = subparsers.add_parser('set',
                                      help='Create or change a user account')
   parser_add.add_argument('--create',
                           action="store_true",
                           help="Create the account")
   parser_add.add_argument('--id', required=True, help="User ID")
   parser_add.add_argument('--description', help="User description")

   parser_add.add_argument(
      '--stdin', action="store_true",
      help="Read additional arguments from stdin.\n"
           "This avoids the need to supply passwords on the command line.\n"
           "Each argument must be on a separate line in format --arg=value.\n"
           "Supported arguments: --description=DESCRIPTION, --password=SECRET, "
           "--password-confirmation=SECRET.")

   parser_add.set_defaults(func=SetUser)

   # parser for command "list"
   parser_list = subparsers.add_parser('list', help='List user accounts')
   parser_list.set_defaults(func=ListUsers)

   # parser for command "remove"
   parser_remove = subparsers.add_parser('remove', help='Delete a user account')
   parser_remove.add_argument('--id', required=True, help="User ID")
   parser_remove.set_defaults(func=RemoveUser)


   args = parser.parse_args()

   # Add these attributes, since they are not defined with add_argument().
   args.password = None
   args.password_confirmation = None

   # support for passing the arguments as stdin
   if args.cmd_name == 'set' and args.stdin:
      for line in sys.stdin:
         line = line.lstrip()
         line = line.rstrip('\n') # a password may end with spaces
         if line.startswith("--id="):
            args.id = line[len("--id="):]
         elif line.startswith("--description="):
            args.description = line[len("--description="):]
         elif line.startswith("--password="):
            args.password = line[len("--password="):]
         elif line.startswith("--password-confirmation="):
            args.password_confirmation = line[len("--password-confirmation="):]

   userName = os.getenv('VI_USERNAME', '')
   try:
      si = Connect(host='localhost', user=userName)
      atexit.register(Disconnect, si)
      args.func(args, si)
   except vmodl.MethodFault as e:
      print('ERROR: %s' % e.msg)
   except Exception as e:
      print('ERROR: %s' % e)


if __name__ == '__main__':
    main()

