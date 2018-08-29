# -*- coding: utf-8 -*-

from .welcome_dialog import WelcomeDialog
from .eula_dialog import EULADialog
from .devices_dialog import DeviceScanningDialog
from .devices_dialog import DeviceSelectionDialog
from .keyboard_dialog import KeyboardDialog
from .password_dialog import PasswordDialog
from .warnerr_dialog import SystemScanningDialog
from .warnerr_dialog import WarnErrDialog
from .confirm_dialog import ConfirmDialog
from .write_dialog import WriteDialog
from .complete_dialog import CompleteDialog

from .core.display import launchDialog
from .core.console_exceptions import RebootException

from weasel import applychoices
from weasel import dd
from weasel import devices
from weasel import datastore
from weasel import userchoices

from weasel.consts import EULA_FILENAME
from weasel.log import log
from weasel.util import upgrade_precheck
from weasel.util import setAutomounted

def welcomeStep(data):
    """ Welcome users to the install! """
    return launchDialog(WelcomeDialog(data))

def eulaStep(data):
    """ Prompt users with the EULA then they have to accept it. """
    data['eulaFile'] = EULA_FILENAME
    return launchDialog(EULADialog(data))

def deviceScanningStep(data):
    """ Please wait while we scan your storage devices. """
    return launchDialog(DeviceScanningDialog(data))

def deviceSelectStep(data):
    """ Users must select a disk to install to. """
    if 'Rescan' in data:
        setAutomounted(False)
        disks = devices.DiskSet(True, probePartitions=False)
        vmfsVols = datastore.DatastoreSet(True)
        del data['Rescan']
    else:
        disks = devices.DiskSet(probePartitions=False)
        vmfsVols = datastore.DatastoreSet()

    return launchDialog(DeviceSelectionDialog(data, disks, vmfsVols))

def keyboardStep(data):
    """ Offer users the option to change their keyboard mappings. """
    return launchDialog(KeyboardDialog(data))

def passwordStep(data):
    """ Users must set the root password. """
    return launchDialog(PasswordDialog(data))

def warnErrStep(data):
    """ If we get warnings/errors, show the user a dialog. """
    warningMsg = None
    errorMsg = None

    launchDialog(SystemScanningDialog(data))

    if userchoices.getUpgrade():
       errorMsg, warningMsg = upgrade_precheck.upgradeAction()
    elif userchoices.getInstall():
       errorMsg, warningMsg = upgrade_precheck.installAction()

    if errorMsg or warningMsg:
        data = launchDialog(WarnErrDialog(errorMsg, warningMsg, data))

    return data

def confirmStep(data):
    """ We make sure the user actually wants to peform the install. """
    return launchDialog(ConfirmDialog(data))

def writeStep(data):
    """ We show a tempearture bar to users for how far long we are writing the dd. """
    log.debug("In writeStep.")
    launchDialog(WriteDialog(data))

    log.debug("Starting to write stuff.")
    applychoices.doit()
    log.debug("And we're done!")

    return data

def completeStep(data):
    """ Congrats!  You've finished installing ESXi. """
    launchDialog(CompleteDialog(data))

    return data

