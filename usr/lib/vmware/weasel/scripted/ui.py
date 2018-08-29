#! /usr/bin/env python

###############################################################################
# Copyright (c) 2008-2009 VMware, Inc.
#
# This file is part of Weasel.
#
# Weasel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# version 2 for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
'''
Scripted User Interface
'''
from __future__ import print_function

import sys
import logging
import readline # needed for raw_input to work on tty6

# from weasel import media
from weasel import exception
from weasel import networking
from weasel import process_end
from weasel import applychoices
from weasel import userchoices
from weasel import task_progress
from weasel import visor_cdrom
from weasel.consts import ExitCodes
from weasel.log import log, formatterForHuman, LOGLEVEL_HUMAN
from weasel.util import prompt


noNICMessage = '''\
No network adapters were detected. Either no network adapters are physically
connected to the system, or a suitable driver could not be located. A third
party driver may be required.

Ensure that there is at least one network adapter physically connected to
the system before attempting installation / upgrade again. If the problem
persists, consult the VMware Knowledge Base.
'''

class MountMediaDelegate:
    def mountMediaNoDrive(self):
        prompt("error: The CD drive was not detected on boot up and "
               "you have selected CD-based installation.\n"
               "Press <enter> to reboot...")

    def mountMediaNoPackages(self):
        prompt("Insert the ESX Installation media.\n"
               "Press <enter> when ready...")

# media.MOUNT_MEDIA_DELEGATE = MountMediaDelegate()

class StdoutProgressReporter(object):
    '''task_progress listener that writes to stdout.'''

    def __init__(self):
        self.lastMessages = {}
        task_progress.addNotificationListener(self)

    def __del__(self):
        task_progress.removeNotificationListener(self)

    def notifyTaskStarted(self, taskTitle):
        self.report(taskTitle)
    def notifyTaskFinished(self, taskTitle):
        self.report(taskTitle)
    def notifyTaskProgress(self, taskTitle, amountCompleted):
        self.report(taskTitle)


    def report(self, taskTitle):
        """Prepare status message for installer delivery.
        """
        task = task_progress.getTask(taskTitle)
        if taskTitle == 'install':
            return
        taskMsg = "(%s) " % (taskTitle[:8])
        if task.desc:
            taskMsg += task.desc[:40]

        detail = task.lastMessage
        if detail:
            taskMsg += ' - ' + detail
        amountDone = task.estimatedTotal - task.amountRemaining
        taskMsg = '%s (%s / %s)\n' % (taskMsg, amountDone, task.estimatedTotal)
        if taskMsg == self.lastMessages.get(taskTitle):
            return      # Don't repeat identical message.
        self.lastMessages[taskTitle] = taskMsg
        sys.stdout.write(taskMsg)

        try:
            masterTask = task_progress.getTask('install')
        except KeyError:
            # The "install" task doesn't exist.  This can happen at the very
            # beginning, or the very end (eg, process_end)
            sys.stdout.flush()
            return

        masterAmtDone = masterTask.estimatedTotal - masterTask.amountRemaining
        pctComplete = '%.1f' % (100.0 - masterTask.percentRemaining())
        totMsg = '[Total: %s%% (%s / %s)]\n' % (pctComplete,
                                int(masterAmtDone), masterTask.estimatedTotal)
        totMsg = totMsg.rjust(80)
        sys.stdout.write(totMsg)

        sys.stdout.flush()



class Scui:
    '''Class used to do a scripted install.'''

    def __init__(self, script):
        # Setup error handling stuff first so any errors during
        # the main bits gets handled correctly.

        #origExceptHook = sys.excepthook
        sys.excepthook = lambda type, value, tb: \
                         exception.handleException(self, type, value, tb,
                                                   traceInDetails=False)

        try:
            # The ui uses logging to write out user-visible output so we need
            # another logger for tty6.
            tty6Handler = logging.StreamHandler(open('/dev/tty6', "w"))
            tty6Handler.setFormatter(formatterForHuman)
            tty6Handler.setLevel(LOGLEVEL_HUMAN)
            log.addHandler(tty6Handler)
        except IOError:
            #Could not open for writing.  Probably not the root user
            pass

        if script != None:
            self._execute(script)
        #sys.excepthook = origExceptHook

    def _execute(self):
        from .preparser import ScriptedInstallPreparser
        from .util import Result

        errors = None
        installCompleted = False

        scriptDict = userchoices.getRootScriptLocation()

        if not scriptDict:
            msg = 'Script location has not been set.'
            longMsg = 'An install script is required. Check your ks option.'
            log.error(msg)
            raise exception.HandledError(msg, longMsg)

        script = scriptDict['rootScriptLocation']

        if not self.checkNICsDetected():
            self.exceptionWindow(noNICMessage, None) #dies with sys.exit()

        try:

            self.sip = ScriptedInstallPreparser(script)

            (result, errors, warnings) = self.sip.parseAndValidate()
            if warnings:
                log.warn("\n".join(warnings))
            if errors:
                log.error("\n".join(errors))
                userchoices.setReboot(False)
            if result != Result.FAIL:
                # Bring up whatever is needed for the install to happen.  For
                # example, get the network going for non-local installs.
                errors, warnings = self._runtimeActions()

                if warnings:
                    log.warn("\n".join(warnings))
                if errors:
                    log.error("\n".join(errors))
                    userchoices.setReboot(False)

                if not errors:
                    if userchoices.getDebug():
                        log.info(userchoices.dumpToString())

                    if not userchoices.getDryrun():
                        stdoutReporter = StdoutProgressReporter()
                        applychoices.doit()
                        installCompleted = True

                if not userchoices.getNoEject():
                    visor_cdrom.ejectCdroms()
        except IOError as e:
            log.error("error: cannot open file -- %s\n" % str(e))
            raise

        if not installCompleted:
            log.error("installation aborted")
            msg = ('The system was not installed correctly.'
                   ' Press <enter> to reboot...')
            prompt(msg)

        elif not userchoices.getReboot():
            msg = "Press <enter> to reboot..."
            prompt(msg)
        try:
            process_end.reboot()
        except exception.HandledError as e:
            self.displayHandledError(e)

    def destroy(self):
        pass

    def displayHandledError(self, e):
        print('\n' * 2)
        print(str(e))
        print('\n' * 2)
        raise e

    def checkNICsDetected(self):
        pnics = networking.getPhysicalNics()
        return len(pnics) > 0

    def exceptionWindow(self, desc, details):
        log.error("") # Just a separator from the other output.
        if details:
            log.error(details)
        log.error(desc)
        log.error("See /var/log/esx_install.log for more information.")

        prompt("Press <enter> to reboot...")

        sys.exit(ExitCodes.IMMEDIATELY_REBOOT)

    def _runtimeActions(self):
        errors = []
        warnings = []

        return (errors, warnings)
