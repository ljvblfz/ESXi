# -*- coding: utf-8 -*-

from .consts import REBOOT_BUTTON_FOOTER
from .core.dialogs import SelectionDialog, ModalDialog, NonModalDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog
from weasel.log import log
from weasel.consts import PRODUCT_STRING
from weasel.util import checkNICsDetected, NO_NIC_MSG, isNOVA, missingDeviceDrivers
import urwid

WELCOME_HEADER = 'Welcome to the ' + PRODUCT_STRING + ' Installation'
WELCOME_MESSAGE = [ PRODUCT_STRING + ' installs on most systems but only systems on VMware\'s Compatibility Guide are supported.',
        'Consult the VMware Compatibility Guide at:\nhttp://www.vmware.com/resources/compatibility', 'Select the operation to perform.', ]
WELCOME_BUTTON_FOOTER = '(Esc) Cancel      (Enter) Continue'
MISSING_DEVICE_MSG = ('No network adapters were detected. '
                      'Installation cannot continue.')
MISSING_DRIVER_MSG = ('This hardware contains devices for which '
                      'there are no available drivers in this system image.')
POSSIBLE_MISSING_MSG = ('This system image may lack the necessary drivers '
                        'to support this hardware.  If the problem persists, '
                        'consult the VMware Knowledge Base.')


class NoNICsDetectedDialog(ModalDialog):
    """Notifies the user that the system has no NICs (therefore the vmfs
    driver can not be loaded).
    """
    def __init__(self, parent, data=None):
        self.data = data
        ModalDialog.__init__(self, parent, [NO_NIC_MSG],
                             "No Network Adapters",
                             REBOOT_BUTTON_FOOTER,
                             width=80, height=17)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(ConfirmRebootDialog(self, self.data))
        return None


class NoOrMissingNicDialog(NonModalDialog):
    """NoOrMissingNicDialog

    Notifies the user that either the system has no NICs or that
    they are missing.  This is a more informative version of
    class NoNICsDetectedDialog above for the NOVA case, where
    we wish to list the KB article number, plus list exactly
    which devices are missing drivers

    If the missing map doesn't detect which drivers are missing
    it means that the driver addendum doesn't have the driver either.
    So we drop back to a non-specific message.
    """
    def __init__(self, parent, data=None):
        self.data = data
        missingDrivers = missingDeviceDrivers()
        body = [urwid.Divider()]
        msg1 = (MISSING_DRIVER_MSG if len(missingDrivers) else
                POSSIBLE_MISSING_MSG)
        msg2 = MISSING_DEVICE_MSG
        body += [urwid.Text(('normal text', msg1))]
        if len(missingDrivers):
           body += [urwid.Divider()]
           body += [urwid.Text(('normal text', 'Devices:'))]
           kb = ''
           for device in missingDrivers:
               name = device['Device']
               desc = device['Description']
               if device['KB Article']:
                  kb = device['KB Article']
               body += [urwid.Text(('standout text',
                                    '     %-15s %s' % (name, desc)))]
           if kb:
               body += [urwid.Divider()]
               body += [urwid.Text(('normal text', 'See details at:'))]
               body += [urwid.Text(('standout text', 'http://%s' % kb),
                                    align='center')]
        body += [urwid.Divider()]
        body += [urwid.Text(('normal text', msg2), align='center')]

        width=80
        approxHeight = (5 + len(body) +
                        (len(msg1) + width - 1) // width +
                        (len(msg2) + width - 1) // width)

        ModalDialog.__init__(self, parent, body,
                             "#No Network Adapters or Missing Drivers#",
                             REBOOT_BUTTON_FOOTER,
                             width=width, height=approxHeight,
                             isBodyText=False)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(ConfirmRebootDialog(self, self.data))
        return None

class WelcomeDialog(NonModalDialog):
    def __init__(self, data=None):
        self.data = data
        NonModalDialog.__init__(self, WELCOME_MESSAGE, WELCOME_HEADER,
                                WELCOME_BUTTON_FOOTER, height=13, width=60)

        if not checkNICsDetected():
            if isNOVA():
               launchDialog(NoOrMissingNicDialog(self, self.data))
            else:
               launchDialog(NoNICsDetectedDialog(self, self.data))

    def keypress(self, size, key):
        """keypress
        Method handles exit and continue keystrokes"""
        if key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        elif key == 'enter':
            self.terminate = True

        return None

