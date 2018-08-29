# -*- coding: utf-8 -*-

from weasel.consoleui.core.console_exceptions import RebootException
from .display import launchDialog
from .dialogs import ModalDialog

CONFIRM_REBOOT_HEADER = "Confirm Cancel"
CONFIRM_REBOOT_BODY = 'Are you sure you want to @cancel@ the %s?\n\nCancelling the %s will reboot your server.'
CONFIRM_REBOOT_BUTTON_FOOTER='(F9) No      (F11) Yes'

class ConfirmRebootDialog(ModalDialog):
    """ConfirmRebootDialog
    Dialog provides the user with a final confirmation to reboot the server"""
    def __init__(self, parent, data=None):

        if data == None:
            self.data = {}
        else:
            self.data = data

        opType = 'installation'

        ModalDialog.__init__(self, parent, [CONFIRM_REBOOT_BODY % (opType, opType)], \
                             CONFIRM_REBOOT_HEADER, \
                             CONFIRM_REBOOT_BUTTON_FOOTER, height=8, width=54)

    def keypress(self, size, key):
        """keypress
        Reboots if the confirmation is affermative and terminates if negative"""
        if key in ['f11']:
            raise RebootException("Reboot requested.")
        elif key in ['f9']:
            launchDialog(self.parent)
        else:
            return key

