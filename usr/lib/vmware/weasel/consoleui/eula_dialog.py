# -*- coding: utf-8 -*-

import urwid
from textwrap import wrap
import io
import sys

from .core.dialogs import SelectionDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog

from weasel import userchoices

EULA_HEADER = 'End User License Agreement (EULA)'
EULA_BUTTON_FOOTER = '(ESC) Do not Accept      (F11) Accept and Continue'
EULA_BODY = 'Use the arrow keys to scroll the EULA text\n'

class EULADialog(SelectionDialog):
    def __init__(self, data=None):
        self.data = data
        self.accepted = False
        self.width = 60

        urwidTextList = self.CreateEULATextWidgets(data['eulaFile'])

        SelectionDialog.__init__(self, urwidTextList, EULA_HEADER,
                                 EULA_BUTTON_FOOTER, EULA_BODY, height=23,
                                 width=self.width)


    def CreateEULATextWidgets(self, fileName):
        """CreateEULATextWidgets
        Construct a list of Urwid Text widgets suitable for display within an
        Urwid ListBox"""

        # For some type of builds, the EULA file may not encoded in the right way,
        # this causes weasel installer to throw exceptions and halts install, let's
        # put errors='ignore' options to ignore these cases, this change only for 
        # python 3 and we keep the same for python 2.

        if sys.version_info[0] >= 3:
            fhandle = open(fileName, errors='ignore')
        else:
            fhandle = open(fileName)

        urwidTextList = []

        for line in fhandle:
            textWidget = urwid.Text(line.rstrip('\n'))
            urwidTextList.append(urwid.AttrWrap(textWidget, 'normal text'))

        fhandle.close()
        return urwidTextList

    def keypress(self, size, key):
        """keypress
        Continue on F11 and Quit on esc.
        """

        key = self.body.keypress(size, key)

        if key in ['f11', '|']:
            userchoices.setAcceptEULA(True)
            self.terminate = True
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))

