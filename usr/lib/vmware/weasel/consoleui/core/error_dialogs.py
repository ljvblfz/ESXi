import urwid
from weasel.consoleui.consts import REBOOT_BUTTON_FOOTER, \
                            STANDARD_BUTTON_FOOTER
from .dialogs import NonModalDialog
from .display import launchDialog
from .reboot_dialog import RebootDialog

class FatalErrorDialog(NonModalDialog):
    def __init__(self, msg, data=None):
        HEADER    = 'Operation #failed#.'
        BODY_PRE  = 'This program has encountered an error:'
        KEYHINT   = '(Use the arrows keys to scroll)'
        BODY_POST = ('The preceding information will assist the VMware Support'
             ' team with your problem. Please @record@ @this@ @information@'
             ' before proceeding.')
        self.data = data
        bodyLines = [BODY_PRE, KEYHINT, (msg, 0), BODY_POST]
        NonModalDialog.__init__(self, bodyLines, HEADER,
                                REBOOT_BUTTON_FOOTER,
                                width=70, height=30)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(RebootDialog())
        else:
            return self._listBox.keypress(size, key)

class WarningDialog(NonModalDialog):
    def __init__(self, msg, data=None):
        HEADER = 'Warning!'
        self.data = data
        bodyLines = [ (msg, 0), ]
        NonModalDialog.__init__(self, bodyLines, HEADER,
                                STANDARD_BUTTON_FOOTER,
                                height=45)

    def keypress(self, size, key):
        if key == 'enter':
            self.terminate = True
        else:
            return key
