# -*- coding: utf-8 -*-

from .core.dialogs import NonModalDialog
from .core.display import launchDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog
from weasel.consts import PRODUCT_SHORT_STRING
from weasel.consoleui.consts import CONFIRM_BUTTON_FOOTER

PARTITION_CORRUPT_MESSAGE = [PRODUCT_SHORT_STRING + ' installer has detected that the selected disk contains an @invalid@ or @corrupt@ partition table.  Please @verify@ that the disk you have selected contains an ' + PRODUCT_SHORT_STRING + ' installation before proceeding.',
 'If you are certain that the disk selected is the disk that contains ' + PRODUCT_SHORT_STRING + ' you can continue. Doing so will result in a fully bootable and functional ' + PRODUCT_SHORT_STRING + ' system. However, any VMFS partitions that exist on the disk will not be immediately available.' ]
PARTITION_CORRUPT_HEADER = 'Disk Geometry Warning'

class PartitionTableCorruptDialog(NonModalDialog):
    def __init__(self, data=None):
        self.data = data
        NonModalDialog.__init__(self, PARTITION_CORRUPT_MESSAGE,
                                PARTITION_CORRUPT_HEADER, CONFIRM_BUTTON_FOOTER,
                                height=16, width=60)

    def keypress(self, size, key):
        """keypress
        Handle continue and cancel"""
        if key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        elif key in ['f11', '|']:
            self.terminate = True

