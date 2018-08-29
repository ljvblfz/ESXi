#!/bin/python
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential

from argparse import ArgumentParser
import os
import sys
import re

pattern = re.compile(r'^(?P<prefix>[#\s]*)FipsMode\s(?P<mode>.*)$',
                     re.IGNORECASE)
parser = None

def SSHFIPS140Get(content):
   """
   Get fips config option from config.
   @content: Content of the config file.

   returns: True if FipsMode is set to "yes" explicitly or nothing is set,
            False if set to "no",
   Throws Exception if set to different values simultaneously or invalid value.
   """
   global pattern

   lines = content.splitlines()

   # Either yes or no must be present but not both or none.
   yesFound = False
   noFound = False

   for line in lines:
      line = line.decode("utf-8")
      match = pattern.match(line)
      if match:
         if '#' not in match.group('prefix'):
            # The mode value of yes/no is case-sensitive.
            if match.group('mode').strip() == 'yes':
               yesFound = True
            elif match.group('mode').strip() == 'no':
               noFound = True
            else:
               raise Exception("FipsMode invalid")

   if yesFound and noFound:
      raise Exception("FipsMode invalid")
   if yesFound:
      return True
   if noFound:
      return False

   return True

def SSHFIPS140Set(content, enable, configFilePath):
   """
   Set fips config option for SSH in the config file.

   returns: Nothing
   """

   global pattern

   enableStr = "yes" if enable else "no"

   current = SSHFIPS140Get(content)
   if current is None:
      with open(configFilePath, "a") as fd:
         fd.write("\nFipsMode {0}\n".format(enableStr))
      return
   elif current == enable:
      return

   currentStr = "yes" if current else "no"

   lines = content.splitlines()
   newlines = []
   for line in lines:
      line = line.decode("utf-8")
      match = pattern.match(line)
      if match:
         if '#' not in match.group('prefix'):
            if match.group('mode').strip() == currentStr:
               continue
      newlines.append(line)
   newContent = '\n'.join(newlines).encode()

   # Write to a temp file first to make the file write atomic.
   tempConfigFilePath = configFilePath + ".tmp"
   with open(tempConfigFilePath, "wb") as fd:
      fd.write(newContent)
      fd.write("\nFipsMode {0}\n".format(enableStr).encode())

   os.rename(tempConfigFilePath, configFilePath)

def SSHFIPS140LoadConfigFile(configFilePath):
   """
   Load config file.

   returns: bytes which is the content of the given file.
   """

   fileSize = os.stat(configFilePath).st_size

   with open(configFilePath, "rb") as fd:
      content = fd.read()

   if not content or len(content) != fileSize:
      raise Exception("Failed to read {0}".format(configFilePath))

   return content

def SSHFIPS140ParseArgs(args):
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
   Get or Set FIPS mode for SSH.

   Output:
   In case of get, True or False is printed to stdout without a newline.
   In case of set, no output is printed.
   """
   options = SSHFIPS140ParseArgs(sys.argv[1:])

   try:
      content = SSHFIPS140LoadConfigFile(options.config)
      if options.get:
         print(SSHFIPS140Get(content), end='')
      elif options.enable:
         enable = options.enable == "true"
         SSHFIPS140Set(content, enable, options.config)
      else:
         parser.print_usage()
         sys.exit(1)
      sys.exit(0)
   except Exception as e:
      print("An error occured: {0}".format(str(e)))
      sys.exit(1)
