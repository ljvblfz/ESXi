#!/bin/python
# **********************************************************************
# Copyright 2015 VMware, Inc.  All rights reserved. VMware Confidential.
# **********************************************************************
import sys
import os
import click
import importlib

CMD_DIR = '/lib64/python3.5/site-packages/netdbg/'
sys.path.append('/lib64')

NETDBG_PYTHON_PATH = '/lib64/python3.5/site-packages/netdbg/'

@click.group()
def RootCommandGroup():
    """
       Command line interface to access settings on ESX datapath
    """
    pass


if __name__ == '__main__':
   sys.path.append(CMD_DIR)
   dir_path = os.path.dirname(NETDBG_PYTHON_PATH)
   for subDir in os.listdir(CMD_DIR):
      if os.path.isdir(os.path.join(CMD_DIR, subDir)):
         # each subcommand should have py same as directory name. 
         subCommand = '{}.{}'.format(subDir, subDir)
         mod = importlib.import_module(subCommand)
         mod.AddToCommandGroup(RootCommandGroup)
   RootCommandGroup()
