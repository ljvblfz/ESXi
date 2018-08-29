# -*- coding: utf-8 -*-

import urwid

from .core.dialogs import SelectionDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog

from weasel.consoleui.consts import OTHER_BUTTON_FOOTER

from weasel import userchoices
from weasel import keyboard
from weasel.log import log

KEYBOARD_HEADER = "Please select a keyboard layout"
KEYBOARD_BODY = "Use the arrow keys to scroll.\n"

class KeyboardDialog(SelectionDialog):
    def __init__(self, data=None):
        self.data = data
        self.width = 45

        keyboards = keyboard.getVisorKeymaps()

        wrappedBoards = []
        for kb in keyboards:
            keyboardWidget = KeyboardWidget(kb)
            wrappedBoards.append(keyboardWidget)

        urwidDisplayList = [ urwid.AttrMap(w, 'normal text', 'selected text')
                             for w in wrappedBoards ]

        SelectionDialog.__init__(self, urwidDisplayList, KEYBOARD_HEADER, OTHER_BUTTON_FOOTER,
                                 KEYBOARD_BODY, width=self.width)

        # Get the current keyboard from vmkctl, if that fails, hardcode it.
        kbrdName = keyboard.getCurrentLayout()
        if not kbrdName:
            kbrdName = "US Default"

        # Restore the user's selection.
        kbrdChoice = userchoices.getKeyboard()
        if 'name' in kbrdChoice:
            kbrdName = kbrdChoice['name']

        kbrdWidget = KeyboardWidget(kbrdName)
        kbrdIndx = wrappedBoards.index(kbrdWidget)
        self.listbox.set_focus(kbrdIndx)

    def keypress(self, size, key):
        """
        Select on (Enter), quit on (Esc), go back to disk selection on
        (f9)
        """

        if key == 'enter':
            (widget, pos) = self.listbox.get_focus()
            layout = widget.original_widget.kbrdLayout

            log.debug("Setting keymap to '%s'." % layout)
            userchoices.setKeyboard(layout)
            keyboard.hostAction()

            self.terminate = True
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        elif key == 'f9':
            self.data['StepForward'] = False
            self.terminate = True
        else:
            return self.listbox.keypress(size, key)


class KeyboardWidget(urwid.Text):
    """
    A wrapper around an urwid.Text widget that represents a keyboard layout.
    """
    def __eq__(self, other):
        return (self.kbrdLayout == other.kbrdLayout)

    def __hash__(self):
        return hash((self.kbrdLayout))

    def __init__(self, kbrdLayout):
        self.kbrdLayout = kbrdLayout
        self._selectable = True

        urwid.Text.__init__(self, kbrdLayout)

    def keypress(self, size, key):
        return key

    def selectable(self):
        return self._selectable
