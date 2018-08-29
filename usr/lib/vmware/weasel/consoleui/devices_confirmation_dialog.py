# -*- coding: utf:8 -*-
import urwid

from .core.display import launchDialog
from .core.dialogs import ModalDialog, RadioModalDialog

from weasel import userchoices

CONFIRM_SELECTION_BUTTON_FOOTER = '(Esc) Cancel      (Enter) OK'
ONLY_INSTALL_FOOTER = "(Esc) Cancel      (Enter) Install"

CONFIRM_OVERWRITE_HEADER = 'Confirm Disk Selection'
OVERWRITE_MESSAGE = ['You have selected a disk that contains '
                     'at least one partition with @existing data@.',
 'If you continue the selected @disk will be overwritten@.',]

CUSTOM_VIBS_WARNING = "Your system has custom VIBs (shown on" \
                      " next screen). Proceeding with migration" \
                      " could cause it to not boot, experience" \
                      " instability, or needed features may not be" \
                      " present. You can use ImageBuilder to create an" \
                      " ISO with VIBs that replace your custom VIBs."


class OverwriteDialog(ModalDialog):
    """
    Forces the user to verify that they wish to continue using a disk that has
    any existing data that is neither ESX(i) nor a VMFS partition.
    """

    def __init__(self, parent, data=None):
        self.data = data
        ModalDialog.__init__(self, parent, OVERWRITE_MESSAGE,
                             CONFIRM_OVERWRITE_HEADER, CONFIRM_SELECTION_BUTTON_FOOTER,
                             width=60, height=10)

    def keypress(self, size, key):
        """An 'esc' keystroke will force the parent window to be redrawn while
        an 'enter' keystroke will terminate the dialog allowing the next
        step to be executed
        """
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)
            self.terminate = True
        elif key == 'esc':
            self.terminate = True
            launchDialog(self.parent)
        else:
            return key


ESXI_AND_VMFS_HEADER = "ESXi and VMFS Found"
ESXI_AND_VMFS_MESSAGE = ["The selected storage device contains an installation "
 "of ESXi and a VMFS datastore.  Choose from the following option(s)."]

class EsxiAndVmfsFoundDialog(RadioModalDialog):
    """
    Prompts the user to select whether to migrate/preserve vmfs, preserve vmfs,
    or to perform a clean install.
    """

    def __init__(self, parent, data=None,
                 allowInstall=True, allowUpgrade=True,
                 warningMsg=None, allowPreserveVmfs=True):
        self.data = data

        body = [ESXI_AND_VMFS_MESSAGE[:]]
        height = 17
        if warningMsg:
            label = "Force Migrate ESXi, preserve VMFS datastore *"
            body.append("\n* " + CUSTOM_VIBS_WARNING)
            userchoices.setActionString('Force Migrate')
            height = 23
        else:
            label = "Upgrade ESXi, preserve VMFS datastore"
            userchoices.setActionString('Upgrade')

        assert(allowInstall or allowUpgrade)
        self.options = []
        if allowUpgrade:
           self.options.append((label,
                [(userchoices.setInstall, False),
                 (userchoices.setUpgrade, True),
                 (userchoices.setPreserveVmfs, True)]))

        if allowInstall:
            if allowPreserveVmfs:
                self.options.append(
                   ("Install ESXi, preserve VMFS datastore",
                    [(userchoices.setInstall, True),
                     (userchoices.setUpgrade, False),
                     (userchoices.setPreserveVmfs, True)]))
            self.options.append(
                   ("Install ESXi, overwrite VMFS datastore",
                    [(userchoices.setInstall, True),
                     (userchoices.setUpgrade, False),
                     (userchoices.setPreserveVmfs, False)]))

        RadioModalDialog.__init__(self, parent, body,
                ESXI_AND_VMFS_HEADER, CONFIRM_SELECTION_BUTTON_FOOTER, height)


ESXI_FOUND_HEADER = "ESXi Found"
ESXI_FOUND_MESSAGE = ["The selected storage device contains an "
 "installation of ESXi.  Choose from the following option(s)."]

class EsxiFoundDialog(RadioModalDialog):
    """
    Prompts the user that the installer has found an ESXi install on the
    selected disk, and no VMFS partition.  Asks the user whether they want to
    perform a fresh install or whether they want to upgrade.
    """

    def __init__(self, parent, data=None,
                 allowInstall=True, allowUpgrade=True,
                 warningMsg=None):
        self.data = data

        body = [ESXI_FOUND_MESSAGE[:]]
        height = 14
        if warningMsg:
            label = "Force Migrate *"
            body.append("\n* " + CUSTOM_VIBS_WARNING)
            userchoices.setActionString('Force Migrate')
            height = 20
        else:
            label = "Upgrade"
            userchoices.setActionString('Upgrade')

        assert(allowInstall or allowUpgrade)
        self.options = []

        if allowUpgrade:
            self.options.append(
                   (label,
                    [(userchoices.setInstall, False),
                     (userchoices.setUpgrade, True),
                     (userchoices.setPreserveVmfs, False)])
                  )

        if allowInstall:
            self.options.append(("Install",
                        [(userchoices.setInstall, True),
                         (userchoices.setUpgrade, False),
                         (userchoices.setPreserveVmfs, False)]))

        RadioModalDialog.__init__(self, parent, body,
                ESXI_FOUND_HEADER, CONFIRM_SELECTION_BUTTON_FOOTER, height)

OLD_ESX_VMFS_FOUND_HEADER = "ESX(i) And VMFS Found"
OLD_ESX_VMFS_FOUND_MESSAGE = ["The selected storage device does not contain"
 " ESXi 6.0 or later.  Upgrading from this version is not supported.  A VMFS"
 " datastore was also found on the device. Choose whether to preserve or"
 " overwrite the existing VMFS datastore."]

VMFS_FOUND_HEADER = "VMFS Found"
VMFS_FOUND_MESSAGE = ["The selected storage device contains a VMFS datastore.  "
 "Choose whether to preserve or overwrite the existing VMFS datastore."]

class VmfsFoundDialog(RadioModalDialog):
    """
    Prompts the user that the installer has found a VMFS partition on the
    selected disk and provides the user with an option to preserve it.
    """

    options = [("Install ESXi, preserve VMFS datastore",
                [(userchoices.setInstall, True),
                 (userchoices.setUpgrade, False),
                 (userchoices.setPreserveVmfs, True)]),
               ("Install ESXi, overwrite VMFS datastore",
                [(userchoices.setInstall, True),
                 (userchoices.setUpgrade, False),
                 (userchoices.setPreserveVmfs, False)]),
              ]

    def __init__(self, parent, data=None, previousInstall=False):
        self.data = data

        # When previous install is found, we will notify the user that
        # we cannot upgrade.
        if previousInstall:
            RadioModalDialog.__init__(self, parent, OLD_ESX_VMFS_FOUND_MESSAGE,
                                      OLD_ESX_VMFS_FOUND_HEADER,
                                      CONFIRM_SELECTION_BUTTON_FOOTER,
                                      height=14)
        # Else we have found only VMFS
        else:
            RadioModalDialog.__init__(self, parent, VMFS_FOUND_MESSAGE,
                                      VMFS_FOUND_HEADER,
                                      CONFIRM_SELECTION_BUTTON_FOOTER,
                                      height=14)


OLD_ESX_VMFS_CANNOT_PRESERVE_HEADER = \
    "ESX(i) Found and VMFS Cannot Be Preserved"
OLD_ESX_VMFS_CANNOT_PRESERVE_MESSAGE = ["The selected storage device does not"
 " contain ESXi 6.0 or later.  Upgrading from this version is not supported.  A"
 " VMFS datastore was also found on the device, but it cannot be preserved."
 " Only an installation is possible.  Continuing with installation will cause"
 " the VMFS datastore to be wiped completely."]

class OldEsxAndVmfsCannotPreserveDialog(ModalDialog):
    """
    Prompts the user that the installer found a version of ESX that we cannot
    upgrade from as well as that the VMFS volume cannot be preserved.
    """

    def __init__(self, parent, data=None):
        self.data = data

        ModalDialog.__init__(self, parent, OLD_ESX_VMFS_CANNOT_PRESERVE_MESSAGE,
                             OLD_ESX_VMFS_CANNOT_PRESERVE_HEADER,
                             CONFIRM_SELECTION_BUTTON_FOOTER, width=60,
                             height=11)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)

            self.terminate = True
        elif key == 'esc':
            launchDialog(self.parent)
        else:
            return self.child.body.keypress(size, key)

VMFS_CANNOT_PRESERVE_HEADER = "VMFS Cannot Be Preserved"
VMFS_CANNOT_PRESERVE_MESSAGE = ["The selected storage device contains a VMFS "
 "datastore which cannot be preserved.\n\nTo preserve the data on this VMFS "
 "datastore, move the data to another datastore.\n\nContinuing with the "
 "installation will overwrite the VMFS datastore, which will also modify "
 "the partitions and delete all existing data."]

class VmfsCannotPreserveDialog(ModalDialog):
    """
    Prompts the user that the installer has found a VMFS partition on the
    selected disk, but we cannot preserve it due to some circumstance.
    """

    def __init__(self, parent, data=None):
        self.data = data

        ModalDialog.__init__(self, parent, VMFS_CANNOT_PRESERVE_MESSAGE,
                             VMFS_CANNOT_PRESERVE_HEADER, CONFIRM_SELECTION_BUTTON_FOOTER,
                             width=60, height=16)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)

            self.terminate = True
        elif key == 'esc':
            launchDialog(self.parent)
        else:
            return self.child.body.keypress(size, key)


OLD_ESX_HEADER = "ESX(i) Found"
OLD_ESX_MESSAGE = ["The selected storage device does not contain ESXi 6.0 "
                   "or later.  Upgrading from this version is not supported.  "
                   "Only installation is possible."]

class OldEsxFoundDialog(ModalDialog):
    """
    Prompts the user that the installer has found some (old) version of ESX that
    we can't support upgrades from.  The user can choose whether to install
    or cancel.
    """

    def __init__(self, parent, data=None):
        self.data = data

        ModalDialog.__init__(self, parent, OLD_ESX_MESSAGE,
                OLD_ESX_HEADER, ONLY_INSTALL_FOOTER, height=8)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)

            self.terminate = True
        elif key == 'esc':
            launchDialog(self.parent)
        else:
            return self.child.body.keypress(size, key)


VSAN_MAGNETIC_DISK_HEADER = "vSAN Claimed Magnetic Disk"
VSAN_MAGNETIC_DISK_MESSAGE = "The selected device is claimed by a vSAN disk" \
 "group: %s.  Continuing will wipe the disk."

class VsanMagneticDiskClaimedDialog(ModalDialog):
    """
    Prompts the user that the SSD disk they've chosen to install to will be
    wiped as well as all magnetic disks in the same disk group.
    """

    def __init__(self, parent, data=None, vsanDiskGroup=None):
        self.data = data

        ModalDialog.__init__(self, parent, [VSAN_MAGNETIC_DISK_MESSAGE %
                vsanDiskGroup], VSAN_MAGNETIC_DISK_HEADER, ONLY_INSTALL_FOOTER,
                height=10)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)
            userchoices.setPreserveVsan(False)
            self.terminate = True
        elif key == 'esc':
            self.terminate = True
            launchDialog(self.parent)
        else:
            return key


VSAN_SSD_HEADER = "vSAN Claimed SSD"
VSAN_SSD_MESSAGE = "The selected SSD storage device is currently claimed by a" \
 " vSAN disk group (%s).  This device and all magnetic disks in the same disk" \
 " group will be wiped."

class VsanSsdClaimedDialog(ModalDialog):
    """
    Prompts the user that the SSD disk they've chosen to install to will be
    wiped as well as all magnetic disks in the same disk group.
    """

    def __init__(self, parent, data=None, vsanDiskGroup=None):
        self.data = data

        ModalDialog.__init__(self, parent, [VSAN_SSD_MESSAGE % vsanDiskGroup],
                VSAN_SSD_HEADER, ONLY_INSTALL_FOOTER, height=10)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)
            userchoices.setPreserveVsan(False)
            self.terminate = True
        elif key == 'esc':
            self.terminate = True
            launchDialog(self.parent)
        else:
            return key


VSAN_DISK_GROUP_HEADER = "vSAN Claimed Disk Group"
VSAN_DISK_GROUP_MESSAGE = "The selected storage device is the only remaining" \
 " magnetic disk in a vSAN disk group.  This device (%s) and the SSD (%s) in" \
 " the associated disk group will be wiped."

class VsanClearDiskGroupDialog(ModalDialog):
    """
    Prompts the user that the magnetic disk they've selected cannot be wiped
    without the associated SSD being wiped as well, as disk group with one SSD
    and one MD cannot exist without one device or the other.
    """
    def __init__(self, parent, data=None, mdDisk=None, ssdDisk=None):
        self.data = data

        ModalDialog.__init__(self, parent, [VSAN_DISK_GROUP_MESSAGE % (mdDisk,
            ssdDisk)], VSAN_DISK_GROUP_HEADER, ONLY_INSTALL_FOOTER, height=11)

    def keypress(self, size, key):
        if key == 'enter':
            userchoices.setInstall(True)
            userchoices.setUpgrade(False)
            userchoices.setPreserveVmfs(False)
            userchoices.setPreserveVsan(False)
            self.terminate = True
        elif key == 'esc':
            self.terminate = True
            launchDialog(self.parent)
        else:
            return key
