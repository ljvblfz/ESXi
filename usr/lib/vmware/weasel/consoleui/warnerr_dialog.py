# -*- coding: utf-8 -*-

import urwid

from .core.dialogs import NonModalDialog
from .core.dialogs import SelectionDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog
from weasel.consoleui.consts import OTHER_BUTTON_FOOTER

WARNERR_HEADER = 'Error(s)/Warning(s) Found During System Scan'
ERROR_FOOTER = "(F9) Back     (F11) Reboot"

class WarnErrDialog(SelectionDialog):
    """WarnErrDialog
    This dialog is used if there are any warnings or errors encounted by the
    system precheck scans.  Otherwise, this dialog is skipped.
    """

    def __init__(self, errorMsg=None, warningMsg=None, data=None):
        self.data = data
        self.errorMsg = errorMsg

        bodyItems = []

        SCROLL_MSG = 'Use the arrow keys to scroll\n'

        ADDITIONAL_MESSAGE = "The system encountered the following "
        if warningMsg and errorMsg:
            ADDITIONAL_MESSAGE += "warning(s) and error(s)."
        elif warningMsg:
            ADDITIONAL_MESSAGE += "warning(s)."
        elif errorMsg:
            ADDITIONAL_MESSAGE += "error(s)."

        addHeader = urwid.Text(('normal text', '\n' +
                                ADDITIONAL_MESSAGE),
                                align="left")

        if errorMsg:
            errorHeader = "Error(s)"
            bodyItems.append(urwid.Text(('normal text', errorHeader), align='center'))
            bodyItems.append(urwid.Text(('normal text', ""), align='center'))
            bodyItems.append(urwid.Text(('normal text', errorMsg), align='left'))
            bodyItems.append(urwid.Text(('normal text', ""), align='center'))
        if warningMsg:
            warningHeader = "Warning(s)"
            bodyItems.append(urwid.Text(('normal text', warningHeader), align='center'))
            bodyItems.append(urwid.Text(('normal text', ""), align='center'))
            bodyItems.append(urwid.Text(('normal text', warningMsg), align='left'))
        bodyItems.append(urwid.Divider())
        height = 20

        if errorMsg:
            SelectionDialog.__init__(self, bodyItems, WARNERR_HEADER,
                                 ERROR_FOOTER,
                                 SCROLL_MSG, height=height,
                                 width=65, additionalHeaderWidget=addHeader)
        elif warningMsg:
            SelectionDialog.__init__(self, bodyItems, WARNERR_HEADER,
                                 OTHER_BUTTON_FOOTER,
                                 SCROLL_MSG, height=height,
                                 width=65, additionalHeaderWidget=addHeader)

    def keypress(self, size, key):
        """keypress
        Confirm Dialog accepts the keystrokes 'f9', 'esc',
        'enter', and 'f11'."""

        if self.errorMsg:
            if key == 'f11':
                launchDialog(ConfirmRebootDialog(self, self.data))
            elif key == 'f9':
                self.data['StepForward'] = False
                self.terminate = True
            else:
                return self.body.keypress(size, key)
        else:
            if key == 'f9':
                self.data['StepForward'] = False
                self.terminate = True
            elif key == 'esc':
                launchDialog(ConfirmRebootDialog(self, self.data))
            elif key == 'enter':
                self.terminate = True
            else:
                return self.body.keypress(size, key)


SYSTEM_SCANNING_MESSAGE = ['Gathering additional system information. This may take a few moments.',]
SYSTEM_SCANNING_HEADER = 'Scanning system...'

class SystemScanningDialog(NonModalDialog):
    def __init__(self, data=None):
        self.data = data
        self.NoInput = True

        NonModalDialog.__init__(self, SYSTEM_SCANNING_MESSAGE,
                                SYSTEM_SCANNING_HEADER,
                                None, height=5, width=72)
