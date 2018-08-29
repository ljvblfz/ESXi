#! /usr/bin/env python

'''
Process End - decide what to do at the end of the Scripted Boot process

If an installation was done, reboot, else hand off to the DCUI
'''
from __future__ import print_function

import sys
import time

import consts
import visor_cdrom
from weasel import util
from weasel import userchoices # always import via weasel.
from weasel import task_progress
from weasel.log import log, LOGLEVEL_UI_ALERT

TASKNAME = 'PROCESS_END'
TASKDESC = 'Ending the process'

def hostAction():
#    try:
#        tidy.doit() # Always cleanup our mess.
#    except Exception as ex:
#        log.exception('An non-fatal exception was encountered while cleaning up')

    if userchoices.getInstall() or userchoices.getUpgrade():
        if userchoices.getReboot():
            reboot()
        else:
            log.info('Done install, prompting for reboot')
    else:
        handOffToDCUI()


def reboot():
    task_progress.taskStarted(TASKNAME, 1, taskDesc=TASKDESC)
    task_progress.taskProgress(TASKNAME, 1, 'Rebooting...')
    if not userchoices.getNoEject():
        visor_cdrom.ejectCdroms()
    log.log(LOGLEVEL_UI_ALERT, 'reboot') # give the UI a chance to clean up
    log.info('giving other processes a few seconds to clean up')
    time.sleep(4)
    log.info('rebooting')
    util.execCommand('/sbin/reboot')

def handOffToDCUI():
    task_progress.taskStarted(TASKNAME, taskDesc=TASKDESC)
    task_progress.taskProgress(TASKNAME, 1, 'Handing Off to DCUI...')
    sys.exit(consts.ExitCodes.END_NICELY)


if __name__ == '__main__':
    userchoices.setInstall(True)
    userchoices.setReboot(True)
    userchoices.setNoEject(False)

    oldExecCommand = util.execCommand
    def fauxExecCommand(*args):
        if 'reboot' in args[0]:
            print('not actually executing %s' % args)
            return
        return oldExecCommand(*args)
    util.execCommand = fauxExecCommand

    hostAction()
