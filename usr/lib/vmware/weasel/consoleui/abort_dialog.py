# -*- coding: utf-8 -*-

import urwid

from .consts import REBOOT_BUTTON_FOOTER
from .core.dialogs import NonModalDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog

class AbortDialog(NonModalDialog):
    """AbortDialog
    This dialog is used if there is a serious error encountered
    preventing the install/upgrade from continuing.
    """

    def __init__(self, errorMsg, hdrMsg, parent=None, data=None,
                 width=65, height=16):
        self.data = data
        NonModalDialog.__init__(self, [errorMsg], hdrMsg,
                             REBOOT_BUTTON_FOOTER,
                             width=width, height=height)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(ConfirmRebootDialog(self, self.data))
        return None
