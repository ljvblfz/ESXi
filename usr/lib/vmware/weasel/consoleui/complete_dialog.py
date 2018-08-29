# -*- coding: utf-8 -*-
# pylint: disable-msg=C0103

'''
User interface class for console UI completion dialog at the
end of installation
'''

from weasel.consoleui.core.console_exceptions import RebootException
from .core.dialogs import NonModalDialog
from weasel.consoleui.consts import REBOOT_BUTTON_FOOTER
from weasel.util import completion_msg

class CompleteDialog(NonModalDialog):
    '''
    This class creates the dialog to present the 'finish' dialog
    to the user at the completion of installation or upgrade
    '''
    def __init__(self, data=None):
        self.data = data

        [introMsg, licenseMsg, usageMsg, removeDiscMsg, \
         rebootMsg] = completion_msg.getCompletionDialog()
        removeDiscMsg = '@' + removeDiscMsg + '@'

        completionMsgBody = [introMsg, licenseMsg, usageMsg, \
                             removeDiscMsg, rebootMsg]
        completionMsgHdr = completion_msg.getCompletionHeader()
        NonModalDialog.__init__(self, completionMsgBody, completionMsgHdr,
                                REBOOT_BUTTON_FOOTER, height=19, width=60)

    def keypress(self, size, key):
        """The CompletionDialog will terminate on enter and pass to the next
        install step which should handle Rebooting the server
        """
        if key == 'enter':
            self.terminate = True
            raise RebootException("Install Complete.")
