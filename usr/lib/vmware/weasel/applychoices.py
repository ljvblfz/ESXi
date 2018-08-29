#! /usr/bin/env python

'''
Performs the actual installation/boot based on the data in userchoices.
'''
from __future__ import print_function

from . import exception
from weasel import userchoices # always import via weasel.
from weasel import task_progress
from weasel.log import log
from weasel.util import prompt

def _installSteps():
    '''Returns a list of steps needed to perform a complete installation.'''

    from . import thin_partitions
    from . import dd
    from . import cache
    from . import users
    from . import script
    from . import keyboard
    from . import partition
    from . import esxlicense
    from . import networking
    from . import process_end

    # Map of installation steps.  Each step has a name and a tuple conntaining
    # the following values:
    #
    #   portion     The units-of-work done by this step, relative to the others
    #   desc        A human-readable description of what the step is doing.
    #   msgID       A machine-readable description of the step.
    #   func        The function that implements the step.
    retval = [
        (10, partition.TASKDESC_CLEAR,
             partition.TASKNAME_CLEAR, partition.hostActionClearPartitions),
        (10, thin_partitions.TASKDESC_PART,
             thin_partitions.TASKNAME_PART, thin_partitions.installAction),
        (10, dd.TASKDESC_WRITELDR,
             dd.TASKNAME_WRITELDR, dd.installActionDDSyslinux),
        (10, dd.TASKDESC_WRITEBP,
             dd.TASKNAME_WRITEBP, dd.installActionDDBootPart),
        (2, dd.TASKDESC_WRITEGUID,
            dd.TASKNAME_WRITEGUID, dd.installActionWriteGUID),
        (100, cache.TASKDESC,
              cache.TASKNAME, cache.installAction),
        (5, users.TASKDESC,
             users.TASKNAME, users.installAction),
        (5, keyboard.TASKDESC,
             keyboard.TASKNAME, keyboard.installAction),
        (5, esxlicense.TASKDESC,
             esxlicense.TASKNAME, esxlicense.installAction),
        (10, networking.TASKDESC,
             networking.TASKNAME, networking.hostAction),
    ]

    retval += [
        # Script MUST go after network settings have been made
        (5, script.TASKDESC,
             script.TASKNAME, script.hostAction),
        (10, partition.TASKDESC_WRITE,
             partition.TASKNAME_WRITE,
             partition.hostActionPartitionPhysicalDevices),
        (1, script.TASKDESC_POST,
            script.TASKNAME, script.postScriptAction),
        (1, process_end.TASKDESC,
            process_end.TASKNAME, process_end.hostAction),
    ]

    return retval


def _upgradeSteps():

    from . import migrate
    from . import thin_partitions
    from . import dd
    from . import cache
    from . import esxlicense
    from . import script
    from . import process_end

    # Map of installation steps.  Each step has a name and a tuple containing
    # the following values:
    #
    #   portion     The units-of-work done by this step, relative to the others
    #   desc        A human-readable description of what the step is doing.
    #   msgID       A machine-readable description of the step.
    #   func        The function that implements the step.
    retval = [
        (10, thin_partitions.TASKDESC_PART,
             thin_partitions.TASKNAME_PART, thin_partitions.installAction),
        (10, dd.TASKDESC_WRITELDR,
             dd.TASKNAME_WRITELDR, dd.installActionDDSyslinux),
        (10, dd.TASKDESC_WRITEBP,
             dd.TASKNAME_WRITEBP, dd.installActionDDBootPart),
        (2, dd.TASKDESC_WRITEGUID,
            dd.TASKNAME_WRITEGUID, dd.installActionWriteGUID),
        (100, cache.TASKDESC,
              cache.TASKNAME, cache.upgradeAction),
        (20, migrate.TASKDESC_MIGRATE,
             migrate.TASKNAME_MIGRATE, migrate.migrateAction),
        (5, esxlicense.TASKDESC,
            esxlicense.TASKNAME, esxlicense.upgradeAction),
        (5, script.TASKDESC,
             script.TASKNAME, script.hostAction),
        (1, script.TASKDESC_POST,
            script.TASKNAME, script.postScriptAction),
        (1, process_end.TASKDESC,
            process_end.TASKNAME, process_end.hostAction),
    ]

    return retval


def doit(stepListType='install'):
    '''Executes the steps needed to do the actual install or boot.'''

    if userchoices.getInstall():
        steps = _installSteps()
    elif userchoices.getUpgrade():
        steps = _upgradeSteps()
    else:
        raise exception.HandledError("Install method not set.", "Neither the "
                "install nor the upgrade userchoice was set.")

    try:
        task_progress.taskStarted('install', sum([step[0] for step in steps]),
                                  taskDesc='Installing to disk')
        for portion, desc, msgID, func in steps:
            log.info(' * STEP '+ msgID)
            task_progress.subtaskStarted(msgID, 'install', portion, portion,
                                         taskDesc=desc)
            func()
            task_progress.taskFinished(msgID)
        task_progress.taskFinished('install')

        log.info("installation complete")
    except exception.InstallCancelled:
        pass

    return

if __name__ == "__main__":
    from . import doctest
    doctest.testmod()

    from . import networking
    userchoices.setInstall(True)
    userchoices.setEsxPhysicalDevice('mpx.vmhba1:C0:T0:L0')

    userchoices.setVmkNetwork('172.16.221.1', '', '', 'localhost')
    device = networking.findPhysicalNicByName('vmnic0')
    userchoices.addVmkNIC(device, None, userchoices.NIC_BOOT_DHCP,
                          ip=None, netmask=None)


    print('\nWARNING\n')
    result = prompt('This may dd the image to mpx.vmhba1:C0:T0:L0'
                    ' Are you sure? ')
    if result.lower() == 'y':
        doit()

