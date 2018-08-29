
# -*- coding: utf-8 -*-

import urwid

from .core.dialogs import SelectionDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog

from weasel import userchoices
from weasel.consoleui.consts import OTHER_BUTTON_FOOTER
from weasel.users import sanityCheckPassword

PASSWORD_DIALOG_HEADER = "Enter a root password"

PASSWORD_REQUEST_TEXT = "Please enter a password."

class PasswordDialog(SelectionDialog):
    """
    Generates two text entry fields and dynamically checks password sanity.
    """

    def __init__(self, data=None):
        self.data = data

        # If the user set a password, restore it to the text boxes.
        pwd = ""
        curPwd = userchoices.getRootPassword()
        if curPwd and not curPwd['crypted']:
            pwd = curPwd['password']

        firstEntry = MaskedEdit(('normal text', "   Root password: "), '*', pwd)
        secondEntry = MaskedEdit(('normal text', "Confirm password: "), '*', pwd)
        emptyText = urwid.Text("")
        self.matchText = urwid.Text(PASSWORD_REQUEST_TEXT, align="center")

        self.content = urwid.SimpleListWalker([firstEntry, secondEntry, emptyText, self.matchText])

        def sanityCheckPasswords(edit, new_edit_text):
            firstPass = firstEntry.internalText
            secondPass = secondEntry.internalText

            if not firstPass and not secondPass:
                self.matchText.set_text(PASSWORD_REQUEST_TEXT)
            else:
                try:
                    # run basic tests only when user is typing
                    sanityCheckPassword(firstPass)
                except ValueError as msg:
                    self.matchText.set_text(str(msg))
                else:
                    if firstPass == secondPass:
                        self.matchText.set_text("Passwords match.")
                    else:
                        self.matchText.set_text("Passwords do not match.")

        urwid.connect_signal(firstEntry, 'change', sanityCheckPasswords)
        urwid.connect_signal(secondEntry, 'change', sanityCheckPasswords)

        SelectionDialog.__init__(self, self.content, PASSWORD_DIALOG_HEADER,
                                 OTHER_BUTTON_FOOTER, None, height=12, width=50)

    def keypress(self, size, key):
        """
        Confirm on (Enter), quit on (Esc)
        """

        firstPass = self.listbox.body[0].internalText
        secondPass = self.listbox.body[1].internalText

        if key == 'enter':
            try:
                # run full test before proceed
                sanityCheckPassword(firstPass, pwqcheck=True)
            except ValueError as msg:
                self.matchText.set_text(str(msg))
            else:
                if firstPass == secondPass:
                    userchoices.setRootPassword(firstPass,
                                                userchoices.ROOTPASSWORD_TYPE_SHA512,
                                                crypted=False)
                    self.terminate = True
        elif key == 'f9':
            self.data['StepForward'] = False
            self.terminate = True
        elif key == 'tab':
            # Make the 'tab' key alternate between the input boxes.
            focusedEntry = self.listbox.get_focus()[0]
            if focusedEntry == self.listbox.body[0]:
                self.listbox.keypress(size, 'down')
            elif focusedEntry == self.listbox.body[1]:
                self.listbox.keypress(size, 'up')
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        else:
            self.listbox.keypress(size, key)

        return (size, key)


class MaskedEdit(urwid.Edit):
    maskedChar = ''
    __internalText = ""

    def __init__(self, caption="", maskedChar='*', curPwd=""):
        """
        (arg)caption -- caption markup (defaults to "")
        (arg)maskedChar -- character to mask with (defaults to "*")
        (arg)curPwd -- the current password, if was set previously
        """

        self.maskedChar = maskedChar
        self.__internalText = curPwd
        self.__super.__init__(caption, maskedChar * len(curPwd))

    def keypress(self, size, key):
        (maxcol,) = size

        self.set_edit_text(self.__internalText)

        unhandled = urwid.Edit.keypress(self, (maxcol,), key)

        self.__internalText = self.get_edit_text()
        self.set_edit_text(self.maskedChar * len(self.__internalText))

        return unhandled

    def __getInternalText(self):
        return self.__internalText

    internalText = property(__getInternalText)
