#!/bin/env python
# Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential

""" Hostd stats store management script

Use empirically derived per VM stats store disk usage estimate of 500k. The
disk usage for host object is about 10 times that the VM's. Since powered
off VMs also take up space, we could estimate the ratio of powered on to
powered off to 1 to 4 (See PR 967621).
"""

__author__ = "VMware, Inc."

import os, sys

from syslog import openlog, syslog, LOG_PID, LOG_DAEMON, LOG_ERR
openlog("create-statsstore", LOG_PID, LOG_DAEMON)


def HandleException(typ, value, trace):
    sys.excepthook = sys.__excepthook__
    syslog(LOG_ERR, "Unhandled exception: %s" % str(value))

    import traceback
    details = ''.join(traceback.format_exception(typ, value, trace))
    syslog(LOG_ERR, details)

sys.excepthook = HandleException

import pyvsilib as vsi
MAX_SUPPORTED_VM_FOR_POWER_ON = max(int(vsi.get('/system/supportedVMs')), 1)
MAX_SUPPORTED_VM_FOR_REGISTER = MAX_SUPPORTED_VM_FOR_POWER_ON * 4
MAX_SUPPORTED_RESOURCE_POOL = 1000

syslog("Initiating hostd statsstore ramdisk size (re)evaluation.")
syslog("Maximum number of virtual machines supported for powering-on %d. "
       "Maximum number of virtual machines supported for register %d. "
       "Maximum number of resource pools %d." % (
           MAX_SUPPORTED_VM_FOR_POWER_ON,
           MAX_SUPPORTED_VM_FOR_REGISTER,
           MAX_SUPPORTED_RESOURCE_POOL))

import esxclipy
executor = esxclipy.EsxcliPy(False)  # do not loadInternalPlugins


def Esxcli(*args):
    args = [str(a) for a in args]
    status, output = executor.Execute(args)
    if status != 0:
        raise RuntimeError(
            "Esxcli command '%s' returned non-zero exit status (%d) and "
            "output:\n%s" % (' '.join(args), status, output))
    return eval(output)

RAMDISK_NAME = 'hostdstats'
RAMDISK_ADVANCED_CONFIG_OPTION = '/UserVars/HostdStatsstoreRamdiskSize'
RAMDISK_MOUNT_POINT = '/var/lib/vmware/hostd/stats'

ramdiskConfigSize = None  # in MB
try:
    option = Esxcli('system', 'settings', 'advanced', 'list',
                    '--option', RAMDISK_ADVANCED_CONFIG_OPTION)
    option = option[0]
    ramdiskConfigSize = max(int(option['Int Value']), 0)
    if ramdiskConfigSize:
        syslog("Using configured statsstore ramdisk size %dMB." %
               ramdiskConfigSize)
except:
    syslog("Ignoring exception while reading the value of the '%s' advanced "
           "config option." % RAMDISK_ADVANCED_CONFIG_OPTION)


ramdiskCurrentSize = None  # in MB
for ramdisk in Esxcli('system', 'visorfs', 'ramdisk', 'list'):
    if ramdisk['Ramdisk Name'] == RAMDISK_NAME:
        ramdiskCurrentSize = int(ramdisk['Maximum']) // 1024
        syslog("Found existing statsstore ramdisk of size %dMB." %
               ramdiskCurrentSize)
        break

ramdiskEstimateSize = (  # in MB
    (MAX_SUPPORTED_VM_FOR_REGISTER + 10) * 500 +
    MAX_SUPPORTED_RESOURCE_POOL * 50) // 1024
syslog("Estimating statsstore ramdisk of size %dMB will be needed." %
       ramdiskEstimateSize)

ramdiskTargetSize = ramdiskConfigSize or ramdiskEstimateSize

if not ramdiskCurrentSize or ramdiskCurrentSize != ramdiskTargetSize:
    if ramdiskCurrentSize:
        syslog("Removing existing statsstore ramdisk.")
        Esxcli('system', 'visorfs', 'ramdisk', 'remove',
               '--target', RAMDISK_MOUNT_POINT)
    else:
        syslog("Creating statsstore ramdisk mount point %s." %
               RAMDISK_MOUNT_POINT)
        try:
            os.makedirs(RAMDISK_MOUNT_POINT)
        except OSError as e:
            if e.errno != os.errno.EEXIST or \
               not os.path.isdir(RAMDISK_MOUNT_POINT):
                raise

    syslog("Creating new statsstore ramdisk with %dMB." % ramdiskTargetSize)
    Esxcli('system', 'visorfs', 'ramdisk', 'add',
           '--name', RAMDISK_NAME,
           '--min-size', 0,
           '--max-size', ramdiskTargetSize,
           '--permissions', '0755',
           '--target', RAMDISK_MOUNT_POINT)
else:
    syslog("No further action is required.")
