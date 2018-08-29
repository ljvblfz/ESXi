#! /usr/bin/env python

#--------------------------------------------------------------------
# When using these consts, be sure to perform the import the following way:
#
# "from weasel import consts"
#
# This makes sure that you are using this specific consts file.
# There is another consts file that exists for the consoleui, to access that one
# use:
#
# "from weasel.consoleui import consts"
#--------------------------------------------------------------------

# class DialogResponses:
#     #
#     # Dialog responses not covered by the gtk.RESPONSE_* family.
#     #
#     BACK           = 1001
#     NEXT           = 1002
#     CANCEL         = 1003
#     FINISH         = 1004
#     STAYONSCREEN   = 1005

class ExitCodes:
    '''Exit codes used to signal the weasel script created by vmk-initrd.sh'''
    IMMEDIATELY_REBOOT = 0
    WAIT_THEN_REBOOT = 1
    DO_NOTHING = 2
    END_NICELY = 3

SYSTEM_MANUFACTURER = "generic"
PRODUCT_STRING = "VMware ESXi 6.7.0"
PRODUCT_SHORT_STRING = "ESXi 6.7.0"
PRODUCT_TITLE = "Installer"
PRODUCT_VERSION_NUMBER = "6.7.0".split('.')

# Label for the root partition.  Useful for cases where using the UUID would be
# inconvenient, see pr 230869.
# ESX_ROOT_LABEL = 'esx-root'

# WEASEL_DATA_DIR = '/etc/vmware/weasel'

EULA_FILENAME = '/usr/lib/vmware/weasel/EULA'

VMFS6 = "VMFS6"

