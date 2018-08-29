#!/bin/python
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential

from argparse import ArgumentParser
import os
import sys
from lxml import objectify
from lxml.etree import SubElement, XMLParser

fipsXPath = 'vmacore/ssl/fips'
parser = None

def RHTTPProxyFIPS140Get(tree):
   """
   Get fips config option from config.
   @tree: etree instance of the config file.

   returns: True if fips is set to true, False otherwise
   """

   # Note that it requires that the node exist and have true or false.
   fips = tree.find(fipsXPath)
   if fips is None or fips.text is None:
      raise Exception("Invalid FIPS mode at node {0}".format(fipsXPath))

   if fips.text.strip() == "true":
      return True
   elif fips.text.strip() == "false":
      return False
   else:
      raise Exception("Invalid FIPS mode at node {0}".format(fipsXPath))

def RHTTPProxyGetOrCreateNode(tree, xpath):
   """
   Recursively find or create elements in XML tree.
   @tree: etree representing service configuration
   @xpath: str representing the xml path

   returns: Element from tree represented by xpath
   """
   if not xpath:
      return tree.getroot()

   elem = tree.find(xpath)
   if elem is None:
      parent_xpath, _, elem_name = xpath.rpartition('/')
      parent = RHTTPProxyGetOrCreateNode(tree, parent_xpath)
      if not elem_name:
         return parent
      elem = SubElement(parent, elem_name)

   return elem

def RHTTPProxyFIPS140Set(tree, enable, configFilePath):
   """
   Set fips config to true or false.
   @enable: Boolean True or False
   @configFilePath: config file path

   returns: Nothing.
   """

   fips = RHTTPProxyGetOrCreateNode(tree, fipsXPath)
   if fips is None:
      raise Exception("Failed to obtain {0} node".format(fipsXPath))

   nodeValue = "true" if enable else "false"

   # Check if the value is already as required.
   if fips.text == nodeValue:
      return

   fips.text = nodeValue

   # First write to a temp file to make the write atomic.
   configFilePathTemp = configFilePath + ".tmp"
   tree.write(configFilePathTemp)
   os.rename(configFilePathTemp, configFilePath)

def RHTTPProxyFIPS140LoadConfigFile(configFilePath):
   """
   Load config file and parse it.

   returns: tree as returned by objectify.parse()
   """

   if not os.path.exists(configFilePath):
      raise Exception("{0} not found.".format(configFilePath))

   # Do not remove comments from the XML config file.
   parser = XMLParser(remove_comments = False)
   tree = objectify.parse(configFilePath, parser = parser)

   return tree

def RHTTPProxyFIPS140ParseArgs(args):
   """
   Parse and configure arguments

   returns - options as returned by ArgumentParser.parse_args()
   """
   global parser

   parser = ArgumentParser(description="Tool for enabling/disabling FIPS140 mode")

   group = parser.add_mutually_exclusive_group(required=True)
   group.add_argument("--get", "-g", action='store_true', help="Get FIPS140 mode")
   group.add_argument("--enable", "-e", choices=["true", "false"], help="Enable/Disable FIPS140 mode")

   parser.add_argument("config", help="Path to config file")

   options = parser.parse_args(args)

   return options

if __name__ == '__main__':
   """
   Get or Set FIPS mode for rhttpproxy.

   Output:
   In case of get, True or False is printed to stdout without a newline.
   In case of set, no output is printed.
   """

   options = RHTTPProxyFIPS140ParseArgs(sys.argv[1:])

   try:
      tree = RHTTPProxyFIPS140LoadConfigFile(options.config)
      if options.get:
         print(RHTTPProxyFIPS140Get(tree), end='')
      elif options.enable:
         enable = options.enable == "true"
         RHTTPProxyFIPS140Set(tree, enable, options.config)
      else:
         parser.print_usage()
         sys.exit(1)
      sys.exit(0)
   except Exception as e:
      print("An error occured: {0}".format(str(e)))
      sys.exit(1)
