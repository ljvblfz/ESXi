# -*- coding: utf-8 -*-

import urwid
from weasel.log import log

from weasel.consoleui.core.console_exceptions import RebootException, \
                                                     VMVisorInstallerException

from consoleui.consts import StepType
from consoleui.core.install import Install
from consoleui.core.display import launchDialog, releaseDisplay
from consoleui.core.error_dialogs import FatalErrorDialog
from consoleui.core.reboot_dialog import RebootDialog
from consoleui.install_steps import welcomeStep, \
                                    eulaStep, \
                                    deviceScanningStep, \
                                    deviceSelectStep, \
                                    keyboardStep, \
                                    passwordStep, \
                                    warnErrStep, \
                                    confirmStep, \
                                    writeStep, \
                                    completeStep

from weasel.process_end import reboot

class ConsoleInstall(Install):
    """ConsoleInstall
    The ESXi Console Installer"""

    # steps contains a list of pairs, the first value being the class for the
    # step, the second being whether the step is used for install, upgrade, or
    # both.
    steps = [(welcomeStep, StepType.usersel),
             (eulaStep, StepType.usersel),
             (deviceScanningStep, StepType.usersel),
             (deviceSelectStep, StepType.usersel),
             (keyboardStep, StepType.install),
             (passwordStep, StepType.install),
             (warnErrStep, StepType.info),
             (confirmStep, StepType.usersel),
             (writeStep, StepType.usersel),
             (completeStep, StepType.usersel),
            ]

    def _execute(self, data=None):
        if not data:
            data = {}

        log.debug("Starting console installer ...")
        Install.start(self, data)

    def destroy(self):
        log.debug('Cleaning up urwid / curses ...')
        releaseDisplay()

    def displayHandledError(self, ex):
        if isinstance(ex, RebootException):
            log.debug("Caught a reboot request ... rebooting.")
            launchDialog(RebootDialog())
        elif isinstance(ex, VMVisorInstallerException):
            log.error("Caught fatal exception: %s" % str(ex))
            launchDialog(FatalErrorDialog(str(ex)))
        else:
            log.error("Caught an exception: %s" % str(ex))
            launchDialog(FatalErrorDialog(str(ex)))

