# -*- coding: utf-8 -*-

import urwid
import logging

from weasel import userchoices

from .core.dialogs import ModalDialog, NonModalDialog
from .core.display import redraw, launchDialog

from weasel import task_progress
from weasel.log import log, formatterForHuman, LOGLEVEL_UI_ALERT
from weasel.consts import PRODUCT_SHORT_STRING
from weasel.consoleui.consts import PROGRESS_MAX_VALUE, PROGRESS_MIN_VALUE, \
                                    CONTINUE_BUTTON_FOOTER


class AlertDialog(ModalDialog):
    """A simple text dialog that must be dismissed"""
    def __init__(self, parent, msg, data=None):
        self.data = data
        ModalDialog.__init__(self, parent, [msg],
                             "Alert",
                             CONTINUE_BUTTON_FOOTER,
                             width=46, height=10)

    def keypress(self, size, key):
        if key == 'enter':
            self.terminate = True
        return None

class AlertHandler(logging.Handler):
    def __init__(self, owner):
        logging.Handler.__init__(self, level=LOGLEVEL_UI_ALERT)
        self.setFormatter(formatterForHuman)
        self.owner = owner

    def emit(self, record):
        if record.levelno != LOGLEVEL_UI_ALERT:
            return
        if record.msg == 'reboot':
            # ignore - special message to wipe the screen during scripted mode
            return
        self.owner.alert(record.msg)


class WriteDialog(NonModalDialog):
    def __init__(self, data=None):

        if userchoices.getUpgrade():
            FLASH_HEADER = "Upgrading to "
        else:
            FLASH_HEADER = "Installing "

        FLASH_HEADER = FLASH_HEADER + PRODUCT_SHORT_STRING

        self.data = data
        self.progressBar = urwid.ProgressBar('pg normal', 'pg complete',
                                                 current=PROGRESS_MIN_VALUE,
                                                 done=PROGRESS_MAX_VALUE)

        self.NoInput = True
        self.lastUpdated = 0

        task_progress.addNotificationListener(self)
        self.alertHandler = AlertHandler(self)
        log.addHandler(self.alertHandler)

        NonModalDialog.__init__(self, None, FLASH_HEADER, self.progressBar, height=5)

    def alert(self, msg):
        launchDialog(AlertDialog(self, msg, self.data))
        launchDialog(self)

    def __del__(self):
        task_progress.removeNotificationListener(self)

    def notifyTaskStarted(self, taskTitle):
        pass

    def notifyTaskFinished(self, taskTitle):
        pass

    def notifyTaskProgress(self, taskTitle, progress):
        self.redrawProgress()

    def redrawProgress(self):
        try:
            masterTask = task_progress.getTask("install")
        except KeyError:
            pass
        else:
            pctComplete = 100 - masterTask.percentRemaining()
            self.progressBar.set_completion(pctComplete)
            redraw()

