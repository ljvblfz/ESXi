# -*- coding:utf-8 -*-

from weasel.consoleui.consts import REBOOT_HEADER, REBOOT_BODY
from .dialogs import NonModalDialog

class RebootDialog(NonModalDialog):
    def __init__(self, data=None):
        self.data = data
        self.NoInput = True
        NonModalDialog.__init__(self, REBOOT_BODY, REBOOT_HEADER, None, height=8,
        width=50)
