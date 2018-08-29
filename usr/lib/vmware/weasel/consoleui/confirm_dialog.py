# -*- coding: utf-8 -*-

import urwid

from .core.dialogs import NonModalDialog
from .core.dialogs import colorizeTokenize
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog
from weasel.consts import PRODUCT_SHORT_STRING
from weasel.consoleui.consts import CONFIRM_BACK_BUTTON_FOOTER

from weasel import devices
from weasel import userchoices

class ConfirmDialog(NonModalDialog):
    """ConfirmDialog
    Dialog presents the user with one last chance to cancel the installation or
    change the disk that will be written to by backing up to a previous step"""
    def __init__(self, data=None):
        self.data = data

        # We default 'modify' to True to mean that we will have to modify the
        # partition table.  'noRollback' means we can't rollback to ESXi 4.x
        modify = True
        noRollback = False

        summaryString = "The installer is configured to %s"

        if userchoices.getInstall():
            actionString = "Install"
            summaryString = summaryString % ("@install@ %s on:" % PRODUCT_SHORT_STRING)
        elif userchoices.getUpgrade():
            actionString = userchoices.getActionString()
            if not actionString:
                actionString = "Upgrade"

            disk = userchoices.getEsxPhysicalDevice()
            diskSet = devices.DiskSet()

            diskDev = diskSet[disk]
            if diskDev.containsEsx.esxi and diskDev.containsEsx.version < (5,):
                noRollback = True

            if diskDev.containsEsx.esxi:
                modify = False

            verStr = diskDev.containsEsx.getPrettyString()
            summaryString = summaryString % ("@%s@ your\nsystem from %s to %s on:" %
                                             (actionString.lower(),
                                              verStr,
                                              PRODUCT_SHORT_STRING)
                                            )

        CONFIRM_HEADER = 'Confirm %s' % actionString
        bodyItems = []
        height = 9

        bodyItems.append(urwid.Divider())
        summaryTokens = colorizeTokenize(summaryString)
        bodyItems.append(urwid.Text(summaryTokens, align='center'))
        line = userchoices.getEsxPhysicalDevice() + '.'
        bodyItems.append(urwid.Text(('normal text', line), align='center'))
        bodyItems.append(urwid.Divider())

        if modify:
            partString = "Warning: This disk will be repartitioned."
            bodyItems.append(urwid.Text(('normal text', partString), align='center'))
            bodyItems.append(urwid.Divider())
            height += 2

        if noRollback:
            noRollbackString = "Rollback to your previous ESXi instance is not supported."
            bodyItems.append(urwid.Text(('error text', noRollbackString), align='center'))
            bodyItems.append(urwid.Divider())
            height += 2

        NonModalDialog.__init__(self, bodyItems, CONFIRM_HEADER,
                                CONFIRM_BACK_BUTTON_FOOTER % actionString,
                                height=height, width=65,
                                isBodyText=False)

    def keypress(self, size, key):
        """keypress
        Confirm Dialog accepts the keystrokes 'f9', 'esc',
        Pg Up and Down and 'f11'."""

        if key == 'f9':
            self.data['StepForward'] = False
            self.terminate = True
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        elif key in ['f11', '|']:
            self.terminate = True
        else:
            return self.body.keypress(size, key)

