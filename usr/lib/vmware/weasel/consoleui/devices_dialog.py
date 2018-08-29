# -*- coding: utf-8 -*-

import urwid

from .core.display import launchDialog
from .core.dialogs import SelectionDialog, ModalDialog, NonModalDialog
from .core.confirm_reboot_dialog import ConfirmRebootDialog
from weasel.consts import PRODUCT_SHORT_STRING
from weasel.util import isNOVA
from .abort_dialog import AbortDialog

from .devices_confirmation_dialog import OverwriteDialog, \
                                        EsxiAndVmfsFoundDialog, \
                                        EsxiFoundDialog, \
                                        VmfsFoundDialog, \
                                        OldEsxAndVmfsCannotPreserveDialog, \
                                        VmfsCannotPreserveDialog, \
                                        VsanMagneticDiskClaimedDialog, \
                                        VsanSsdClaimedDialog, \
                                        VsanClearDiskGroupDialog, \
                                        OldEsxFoundDialog

from weasel import devices, upgrade, userchoices, thin_partitions
from weasel.log import log
from weasel.partition import ScanError

from weasel.util import truncateString, \
                        missingDeviceDrivers, \
                        nominalDeviceDrivers, \
                        getMissingDevices
from weasel.util.units import formatValue
import featureState

DEVICESCANNING_MESSAGE = ['Scanning for available devices. This may take a few seconds.',]
DEVICESCANNING_HEADER = 'Scanning...'

DEVICE_SELECTION_HEADER = 'Select a Disk to %s'
DEVICE_SELECTION_FOOTER = '(Esc) Cancel    (F1) Details    (F5) Refresh    (Enter) Continue'

DISK_DETAILS_HEADER = 'Disk Details'
DISK_DETAILS_FOOTER = '(Enter) OK'

STORAGE_HEADING = "Storage Device"
CAP_HEADING = "Capacity"

BB_DISK_HEADER = " @ Contains an upgradable boot bank"
VMFS_DISK_HEADER = " * Contains a VMFS partition"
VSAN_DISK_HEADER = " # Claimed by VMware vSAN"


DEVMODEL_LENGTH = 36
DEVNAME_LENGTH = 23
DEV_DESC_LENGTH = DEVMODEL_LENGTH + DEVNAME_LENGTH

CAP_LENGTH = 10

KEY_DETAILS_LENGTH = 16
VALUE_DETAILS_LENGTH = 42

def diskToDisplayString(disk, datastoreSet):
    """
    >>> from weasel import devices
    >>> from weasel import datastore
    >>> from weasel.fsset import vmfs5FileSystem
    >>> class Foo: pass
    >>> partitions = [Foo()]
    >>> partitions[0].fsType = vmfs5FileSystem()
    >>> ds1 = datastore.Datastore("datastore1", driveName="vmx.fake.drive")
    >>> ds2 = datastore.Datastore("datastore2", driveName="vmx.fake.drive.reallylongstring")
    >>> dSet = datastore.DatastoreSet(scan=False)
    >>> dSet.entries.append(ds1)
    >>> dSet.entries.append(ds2)
    >>> disk = devices.DiskDev(
    ...          "vmx.fake.drive", device=None, path=None, consoleDevicePath=None,
    ...          vendor="Dr Vendor", model="My Model", size=9001, sectorSize=512, sizeUnit='KB',
    ...          deviceExists=True, probePartitions=False, driverName=None,
    ...          pathIds=None, vmkLun=None,
    ...          supportsVmfs=False, local=True)
    >>> disk._partitions = partitions
    >>> diskToDisplayString(disk, dSet)
    (' * Dr Vendor My Model (vmx.fake.drive)', '4 MiB')

    >>> disk1 = devices.DiskDev(
    ...          "vmx.fake.drive.reallylongstring", device=None, path=None, consoleDevicePath=None,
    ...          vendor="Dr Vendor-something-long", model="My Model-something-more", size=9001, sectorSize=512, sizeUnit='KB',
    ...          deviceExists=True, probePartitions=False, driverName=None,
    ...          pathIds=None, vmkLun=None,
    ...          supportsVmfs=False, local=True)
    >>> disk1._partitions = partitions
    >>> output = diskToDisplayString(disk1, dSet)
    >>> output
    (' * Dr Vendor-something-long My Mo... (vmx.fake.drive.re...)', '4 MiB')
    >>> len(output[0])
    59
    """
    # We subtract from the lengths to offset for the use of spaces that prepend
    # the text.
    venModText = truncateString(disk.getVendorModelString(), DEVMODEL_LENGTH - 3)
    newDevNameLength = DEVNAME_LENGTH
    # We're short on screen space, so lets take advantage of as much as we can.
    if len(venModText) <= (DEVMODEL_LENGTH - 3):
        newDevNameLength = (DEVMODEL_LENGTH - 3 - len(venModText)) + DEVNAME_LENGTH

    # We subtract from the length to offset for the use of the space and parenthesis
    nameText = truncateString(disk.name, newDevNameLength - 1 - 2)

    foundVMFS = False
    # Check for any VMFS partitions on the disk...
    try:
        datastores = datastoreSet.getEntriesByDriveName(disk.name)
        if datastores:
            foundVMFS = True
    except ScanError:
        pass

    deviceText = "%s (%s)" % (venModText, nameText)

    canUpgradeToNOVA = False
    if isNOVA():
        canUpgradeToNOVA = disk.canUpgradeToNOVA()

    # So far, vSAN and VMFS can't exist on the same device...
    if canUpgradeToNOVA:
        deviceText = " @ " + deviceText
    elif foundVMFS:
        deviceText = " * " + deviceText
    elif disk.vsanClaimed:
        deviceText = " # " + deviceText
    else:
        deviceText = "   " + deviceText

    capInBytes = disk.size * disk.sectorSize
    capText = formatValue(B=capInBytes)

    return (deviceText, capText)


def generateDetails(disk, datastoreSet):
    """
    'disk' should be a Device from weasel.devices
    'datastoreSet' should be a DatastoreSet from weasel.datastore

    >>> from weasel import devices
    >>> from pprint import pprint
    >>> from weasel import datastore
    >>> ds = devices.DiskSet()
    >>> datastoreSet = datastore.DatastoreSet()
    >>> disk = ds[ds.keys()[0]]
    >>> pprint(generateDetails(disk, datastoreSet))
    [('Model/Vendor: ', 'ATA WDC FKE1600'),
     ('Full Disk Name: ', 'vml.0000'),
     ('Interface Type: ', 'sata'),
     ('LUN ID: ', '0'),
     ('Target ID: ', '0'),
     ('Capacity: ', '75.00 GiB'),
     ('Path: ', '/vmfs/devices/disks/vml.0000'),
     ('ESX(i) Found: ', 'No'),
     ('SSD Device: ', 'False'),
     ('Datastores: ', 'Storage 1')]
    """

    datastores = datastoreSet.getEntriesByDriveName(disk.name)
    datastores = [ d.name for d in datastores ]

    versionString = disk.containsEsx.getPrettyString()

    if not versionString:
        versionString = "No"

    # Order matters; it determines placement on the details dialog.
    details = [
        ("Model/Vendor: ", disk.getVendorModelString()),
        ("Full Disk Name: ", disk.name),
        ("Interface Type: ", disk.interfaceType),
        ("LUN ID: ", str(disk.pathIds[devices.PATHID_LUN])),
        ("Target ID: ", str(disk.pathIds[devices.PATHID_TARGET])),
        # ([num sectors] * [sector size in bytes])
        ("Capacity: ", formatValue(B=disk.size * disk.sectorSize)),
        ("Path: ", disk.path),
        ("ESX(i) Found: ", versionString),
        ("SSD Device: ", str(disk.isSSD))
    ]
    if not datastores:
        details.append(("Datastores: ", "(none)"))
    else:
        details.append(("Datastores: ", ", ".join(datastores)))

    if disk.vsanClaimed:
        details.append(("vSAN UUID: ", disk.vsanClaimed))

    return details


class DeviceTextWidget(urwid.Text):
    """
    A simple wrapper around a standard Urwid Text widget that can store a DiskLun
    target along with the pretty text associated with the Urwid ListBox Row
    item
    """
    def __init__(self, prettyName, device):
        self.__device = device
        self.__devicePrettyName = prettyName
        self.__super.__init__((prettyName))
        self._selectable = True

    def __getDevice(self):
        return self.__device

    device = property(__getDevice)

    def __getDevicePrettyName(self):
        return self.__devicePrettyName

    devicePrettyName = property(__getDevicePrettyName)

    def keypress(self, size, key):
        # We just want to pass this up to the handler for the list.
        return key

    def selectable(self):
        return self._selectable


class DeviceScanningDialog(NonModalDialog):
    def __init__(self, data=None):
        self.data = data
        self.NoInput = True

        NonModalDialog.__init__(self, DEVICESCANNING_MESSAGE, DEVICESCANNING_HEADER,
                                None, height=5, width=65)


SELECTEDDEVICE_MESSAGE = ['Gathering additional information from the selected device.',
                          'This will take a few moments.',]
SELECTEDDEVICE_HEADER = 'Scanning...'

class SelectedDeviceScanningDialog(ModalDialog):
    def __init__(self, parent, data=None):
        self.data = data
        self.NoInput = True

        bodyItems = []

        bodyItems.append(urwid.Divider())

        for line in SELECTEDDEVICE_MESSAGE:
            bodyItems.append(urwid.Text(('normal text', line), align="center"))

        ModalDialog.__init__(self, parent, bodyItems, SELECTEDDEVICE_HEADER,
                             None, height=6, width=65, isBodyText=False)

DRIVER_DIALOG_FOOTER='(Esc) Cancel     (Enter) Continue with Upgrade'
MISSING_DRIVER_MESSAGE = 'This system contains devices for which ' \
                         'there are no available drivers. ' \
                         'Installing %s on such a system is not supported. ' \
                         'Upgrade is supported, but the device you wish to ' \
                         'upgrade to %s might not be available. ' \
                         % (PRODUCT_SHORT_STRING, PRODUCT_SHORT_STRING)

MISSING_DRIVER_HEADER = '#Missing Device Drivers#'

NOMINAL_DRIVER_MESSAGE = 'This system contains devices for which ' \
                         'drivers have limited functionality. ' \
                         'Installing %s on such a system is not supported. ' \
                         % PRODUCT_SHORT_STRING

NOMINAL_DRIVER_HEADER = '#Limited Device Drivers#'

class DeviceDriverDialog(ModalDialog):
    """
    Warns the user about missing or nominal device drivers.
    """

    def __init__(self, parent, header, message, devices, nextDlog=None,
            data=None):
        self._nextDlog = nextDlog
        self.data = data

        body  = [urwid.Divider()]
        body += [urwid.Text(('normal text', message))]
        body += [urwid.Divider()]
        body += [urwid.Text(('normal text', 'Devices:'))]

        kb = ''
        for device in devices:
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

        width=80
        approxHeight = 5 + len(body) + (len(message) + width - 1) // width

        ModalDialog.__init__(self, parent, body, header,
                             DRIVER_DIALOG_FOOTER,
                             width=width, height=approxHeight,
                             isBodyText=False)

    def keypress(self, size, key):
        """An 'esc' keystroke will force the parent window to be redrawn while
        an 'enter' keystroke will terminate the dialog allowing the next
        step to be executed
        """
        if key == 'enter':
            if self._nextDlog:
                launchDialog(self._nextDlog)
            self.terminate = True
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self))
        else:
            return key

class DeviceSelectionDialog(SelectionDialog):
    """
    A Dialog that presents a list of storage targets in an Urwid ListBox.
    User input is collected by the listbox and their corresponding actions
    are intuitive to what you would expect in a list selection dialog.
    ie. Up, Down, PageUp, PageDown
    """

    NO_DISKS_MSG = '''No storage disks eligible for %s were detected.
Only a disk containing a valid and recently used ESXi
bootbank is eligible for upgrade.
%s
If the problem persists, consult the VMware Knowledge Base.
'''

    def __init__(self, data=None, targets=None, datastoreSet=None):
        self.data = data
        self.datastoreSet = datastoreSet

        self.disks = targets

        urwidWidgetList = self.generateDevicesBody()

        additionalHeaderText = [('normal text',
                                 '\n' + VMFS_DISK_HEADER +
                                 '\n' + VSAN_DISK_HEADER)]

        dlgHdr = DEVICE_SELECTION_HEADER % 'Install or Upgrade\n (any existing VMFS-3 will be automatically upgraded to VMFS-5)'
        iType = 'upgrade or install'
        if isNOVA():
            additionalHeaderText.insert(0, ('normal text',
                '\n' + BB_DISK_HEADER))
            if self._novaUpgradeOnly:
                # only upgrades
                dlgHdr = DEVICE_SELECTION_HEADER % 'Upgrade'
                iType = 'upgrade'
            elif self._novaUpgradableDisks == 0:
                # only installs
                dlgHdr = DEVICE_SELECTION_HEADER % 'Install'
                iType = 'install'

        additionalHeader = urwid.Text(additionalHeaderText, align="left")
        SelectionDialog.__init__(self, urwidWidgetList, dlgHdr,
                                 DEVICE_SELECTION_FOOTER, height=19, width=70,
                                 additionalHeaderWidget=additionalHeader)

        '''Detect missing and/or nominal device drivers and let user know.
        '''
        missingDrivers = missingDeviceDrivers()
        if len(missingDrivers):
            missingDriversDlog = DeviceDriverDialog(self,
                                                    MISSING_DRIVER_HEADER,
                                                    MISSING_DRIVER_MESSAGE,
                                                    missingDrivers)
        else:
            missingDriversDlog = None

        nominalDrivers = nominalDeviceDrivers()
        if len(nominalDrivers):
            nominalDriversDlog = DeviceDriverDialog(self,
                                                    NOMINAL_DRIVER_HEADER,
                                                    NOMINAL_DRIVER_MESSAGE,
                                                    nominalDrivers,
                                                    missingDriversDlog)
        else:
            nominalDriversDlog = None

        if nominalDriversDlog:
            launchDialog(nominalDriversDlog)
        elif missingDriversDlog:
            launchDialog(missingDriversDlog)

        if isNOVA():
            if self._novaNoEligibleDisks:
               warningMsg = ''
               deviceList = getMissingDevices('vmhba')
               if deviceList:
                  warningMsg = ('\nThis installer lacks drivers '
                                'for these device(s):\n\n    %s\n' %
                                 deviceList)
               dialogMsg = self.NO_DISKS_MSG % (iType, warningMsg)
               launchDialog(AbortDialog(dialogMsg,
                                        '#No Eligible Disks Found#',
                                        width=66, height=16))

    def generateDevicesBody(self):
        """
        This parses the disks given to us and returns a set of widgets which
        will be the body of the dialog.
        """
        textList = []

        textString = "%%-%ds%%%ds" % (DEV_DESC_LENGTH + 1, CAP_LENGTH)

        headerText = urwid.Text(textString % (STORAGE_HEADING, CAP_HEADING))
        headerText._selectable = False
        textList.append(headerText)

        divider = urwid.Divider('-')
        divider._selectable = False
        textList.append(divider)

        localDisks = []
        remoteDisks = []

        ''' For NOVA, we do not support a fresh install if we lack fully
        featured device drivers for this system.
        '''
        self._novaUpgradeOnly = False
        if isNOVA():
            allDisks = []
            self._novaUpgradableDisks = 0
            self._novaNoEligibleDisks = False
            self._novaUpgradeOnly = bool(missingDeviceDrivers() or
                                         nominalDeviceDrivers())
            for curDisk in list(self.disks.values()):
                canUpgrade = curDisk.canUpgradeToNOVA()
                self._novaUpgradableDisks += int(canUpgrade)
                if not self._novaUpgradeOnly or canUpgrade:
                    allDisks += [curDisk]

            if self._novaUpgradeOnly:
                log.warning('Missing/Nominal devices detected. Only upgrades '
                            'are allowed on this host to the native only '
                            'image.')
            if not allDisks:
                log.error('No disks eligigle for install/upgrade are '
                          'detected.')
                self._novaNoEligibleDisks = True
        else:
            allDisks = list(self.disks.values())

        for curDisk in allDisks:
            diskString = (textString %
                          diskToDisplayString(curDisk, self.datastoreSet))

            if curDisk.local:
                localDisks.append(DeviceTextWidget(diskString, curDisk))
            else:
                remoteDisks.append(DeviceTextWidget(diskString, curDisk))


        noneText = urwid.Text("   (none)")
        noneText._selectable = False
        if not localDisks:
            localDisks.append(noneText)
        if not remoteDisks:
            remoteDisks.append(noneText)

        localString = urwid.Text(textString % ("Local:", ""))
        localString._selectable = False

        remoteString = urwid.Text(textString % ("Remote:", ""))
        remoteString._selectable = False

        textList.append(localString)
        textList.extend(localDisks)
        textList.append(remoteString)
        textList.extend(remoteDisks)

        found = False
        diskName = userchoices.getEsxPhysicalDevice()
        if diskName:
            for index, item in enumerate(textList):
                if isinstance(item, DeviceTextWidget):
                    if diskName == item.device.name:
                        found = True
                        break

        deviceList = urwid.SimpleListWalker([ urwid.AttrMap(w, 'normal lun text', 'selected text')
                                        for w in textList ])

        if found:
            deviceList.set_focus(index)

        return deviceList

    def keypress(self, size, key):
        if not self.listbox:
            return key

        if key == 'enter':
            (widget, pos) = self.listbox.get_focus()

            try:
                disk = widget.original_widget.device
            except AttributeError as msg:
                log.exception("No disks ...")
                return size, key

            log.debug("Setting disk to: %s" % disk.name)
            userchoices.setEsxPhysicalDevice(disk.name)

            # XXX: The behavior here is really bad.  Any changes done to the
            # 'data' dictionary after any of the ModalDialogs pop up do not
            # affect 'data' once it is passed down to the next screen because of
            # the way the stack is generated.  The devices dialog calls
            # confirmoverwrite, which will call LaunchDialog on the devices
            # dialog which can also affect data.  Once that second devices
            # dialog returns, the stack collapses and the first devices dialog
            # is the only one that has the real effect on 'data'.

            if disk.getSizeInMebibytes() < thin_partitions.MIN_EMBEDDED_SIZE:
                log.debug("  Dialog: Disk too small!")
                launchDialog(DeviceTooSmallDialog(self, self.data))

            datastores = self.datastoreSet.getEntriesByDriveName(disk.name)
            if datastores:
                log.debug("Found vmfs volume on disk %s." % disk.name)
                # There should only be one.
                if datastores[0].unscannable:
                    log.debug("  Dialog: Found an unscannable volume.")
                    # Uh-oh, something went wrong while scanning the VMFS
                    # volume...
                    launchDialog(VolumeErrorDialog(self, self.data))

            # Throw up a "please wait" message
            scanningDialog = SelectedDeviceScanningDialog(self, self.data)
            launchDialog(scanningDialog)

            try:
                partSet = disk.getPartitionSet()
            except ScanError:
                partSet = None

            warnMsg = None
            if partSet and partSet.getPartitions():
                # We have some non-freespace partitions on this disk

                # Do some checks here for what we can find...
                upgrade.checkForPreviousInstalls(disk)

                log.debug("  Dialog: Raising screens for %s." % disk.containsEsx)

                # Not being able to save the VMFS takes priority.
                # Note: vSAN VMFS partitions are not considered to be used as
                # 'VMFS'.
                if disk.canSaveVmfs == False:
                    if disk.containsEsx and disk.containsEsx.version < (6, 0,):
                        log.debug("  Dialog: ESX(i) and VMFS found,"
                                  " can't upgrade or preserve VMFS")
                        modalWindow = OldEsxAndVmfsCannotPreserveDialog(self,
                                          self.data)
                    else:
                        log.debug("  Dialog: Can't preserve VMFS")
                        modalWindow = VmfsCannotPreserveDialog(self, self.data)
                # Check to see if it's upgradable...
                elif disk.containsEsx and disk.containsEsx.version < (6, 0,):
                    if disk.vmfsLocation:
                        log.debug("  Dialog: old ESX(i) and VMFS found,"
                                  " can't upgrade but can preserve VMFS")
                        modalWindow = VmfsFoundDialog(self, self.data,
                                                      previousInstall=True)
                    else:
                        log.debug("  Dialog: old ESX(i) found, can't upgrade")
                        modalWindow = OldEsxFoundDialog(self, self.data)

                elif disk.containsEsx.esxi:
                    upgradableDisk = not isNOVA() or disk.canUpgradeToNOVA()
                    if disk.vmfsLocation:
                        log.debug("  Dialog: esxi and vmfs (%s)" %
                                   str(disk.vmfsLocation))

                        allowPreserveVmfs = True

                        modalWindow = EsxiAndVmfsFoundDialog(self, self.data,
                                                             not self._novaUpgradeOnly,
                                                             upgradableDisk,
                                                             allowPreserveVmfs=allowPreserveVmfs)
                    else:
                        log.debug("  Dialog: only esxi, no vmfs")
                        modalWindow = EsxiFoundDialog(self, self.data,
                                                      not self._novaUpgradeOnly,
                                                      upgradableDisk)

                # If all we found was a VMFS ...
                elif disk.vmfsLocation:
                    log.debug("  Dialog: only vmfs (%s)" % str(disk.vmfsLocation))
                    modalWindow = VmfsFoundDialog(self, self.data)
                # If the disk is claimed by a vSAN disk group ...
                elif disk.vsanClaimed:
                    log.debug("Disk is claimed by a vSAN disk group: %s" %
                            disk.vsanClaimed)
                    # Get the disks in the vSAN disk group
                    diskSet = devices.DiskSet()
                    diskGroup = [x for x in list(diskSet.values())
                                 if x.vsanClaimed == disk.vsanClaimed]

                    # If it's SSD, don't bother with any other prompt
                    if disk.isSSD:
                        modalWindow = VsanSsdClaimedDialog(self, self.data,
                                disk.vsanClaimed)
                    elif len(diskGroup) > 2:
                        modalWindow = VsanMagneticDiskClaimedDialog(self,
                                self.data, disk.vsanClaimed)
                    else:
                        ssdDisk = list(filter(lambda x: x.isSSD, diskGroup))[0]
                        modalWindow = VsanClearDiskGroupDialog(self, self.data,
                                disk.name, ssdDisk.name)
                # Otherwise, we know something is on the disk, but not what ...
                else:
                    log.debug("  Dialog: We found something, but what?")
                    modalWindow = OverwriteDialog(self, self.data)
                # Clobber the "please wait" message with a new dialog
                self.data = launchDialog(modalWindow)
            else:
                # We have a blank disk. (or there was a part scan error)
                log.debug("We have a blank disk.")
                userchoices.setInstall(True)
                userchoices.setUpgrade(False)
                userchoices.setPreserveVmfs(False)
                # Dismiss the "please wait" message
                scanningDialog.terminate = True

            log.debug("User chose disk: %s to install to." % disk.name)
            self.terminate = True
        elif key == 'f1':
            (widget, pos) = self.listbox.get_focus()
            try:
                disk = widget.original_widget.device
            except AttributeError as msg:
                log.exception("No disks ...")
                return size, key

            launchDialog(SelectedDeviceScanningDialog(self, self.data))
            upgrade.checkForPreviousInstalls(disk)

            data = launchDialog(DeviceDetailsDialog(self, disk))
        elif key == 'f5':
            log.debug("Rescanning disks...")
            self.data['StepForward'] = False
            self.data['Rescan'] = True
            self.terminate = True
        elif key == 'esc':
            launchDialog(ConfirmRebootDialog(self, self.data))
        else:
            return self.listbox.keypress(size, key)


class DeviceDetailsDialog(urwid.WidgetWrap):
    """
    Pops up a modal dialog that will show more information about the selected
    disk (model/vendor, fulldiskname, lunid, targetid, capacity, path,
    datastore, etc.)
    We don't directly inherit ModalDialog because it doesn't do what we want
    correctly.  We generate our own way to do it here.
    """

    def __init__(self, parent, selectedDisk):
        self.terminate = False
        self.parent = parent
        self.detailsList = generateDetails(selectedDisk, parent.datastoreSet)

        minDialogHeight = 15

        detailsTextList = urwid.SimpleListWalker([])

        # 16 wide for the key, 42 wide for the values
        detailsString = "%%-%ds%%-%ds" % (KEY_DETAILS_LENGTH, VALUE_DETAILS_LENGTH)

        detailsTextList.append(urwid.Divider())

        for (label, detail) in self.detailsList:
            # Make sure that we indent correctly if the string overflows.
            remaining = detail[VALUE_DETAILS_LENGTH:]
            detail = detail[:VALUE_DETAILS_LENGTH]
            detailsTextList.append(urwid.Text(detailsString % (label, detail)))
            while remaining:
                detail = remaining[:VALUE_DETAILS_LENGTH]
                remaining = remaining[VALUE_DETAILS_LENGTH:]
                detailsTextList.append(urwid.Text(detailsString % ('', detail)))
                minDialogHeight += 1

        allItems = []
        for detail in detailsTextList:
            if isinstance(detail, urwid.widget.Text):
                text, attr = detail.get_text()
                if text.startswith('ESX(i) Found'):
                    allItems.append(urwid.AttrMap(detail, 'standout text'))
                else:
                    allItems.append(urwid.AttrMap(detail, 'normal text'))
        urwidTextList = urwid.SimpleListWalker(allItems)


        self.listbox = urwid.ListBox(urwidTextList)
        header = urwid.Text(('normal text', DISK_DETAILS_HEADER), align="center")
        footer = urwid.Text(('frame box', DISK_DETAILS_FOOTER), align="center")

        frame = urwid.Frame(self.listbox, header=header, footer=footer)
        border = urwid.LineBox(frame)
        wrap = urwid.AttrWrap(border, 'frame box')

        overlay = urwid.Overlay(wrap, self.parent, 'center',
                                KEY_DETAILS_LENGTH + VALUE_DETAILS_LENGTH + 2, 'middle',
                                minDialogHeight)

        urwid.WidgetWrap.__init__(self, overlay)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(self.parent)
        else:
            return self.listbox.keypress(size, key)


DEVICETOOSMALL_HEADER = 'The selected disk does not meet the minimum space requirements for ' + PRODUCT_SHORT_STRING + '. Please select a disk that has a capacity greater than %s.'
DEVICETOOSMALL_BUTTON_FOOTER = '(Enter) Continue'

class DeviceTooSmallDialog(ModalDialog):
    """DeviceTooSmallDialog
    A Modal Dialog that notifies the user that the selected disk is too small."""

    def __init__(self, parent, data=None):
        self.data = data
        ModalDialog.__init__(self, parent, None, DEVICETOOSMALL_HEADER % formatValue(MiB=thin_partitions.MIN_EMBEDDED_SIZE),
                             DEVICETOOSMALL_BUTTON_FOOTER, width=60, height=7)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(self.parent)
        else:
            return key


VOLUME_ERROR_HEADER = "The selected disk has a VMFS volume which cannot be scanned.  It may be corrupted or disconnected.  Please select a different disk or correct the issue."
VOLUME_ERROR_FOOTER = "(Enter) Continue"

class VolumeErrorDialog(ModalDialog):
    """VolumeErrorDialog
    A dialog that informs the user that for some reason, we were unable to scan
    the VMFS volume for more information."""

    def __init__(self, parent, data=None):
        self.data = data
        ModalDialog.__init__(self, parent, None, VOLUME_ERROR_HEADER,
                             VOLUME_ERROR_FOOTER, width=60, height=7)

    def keypress(self, size, key):
        if key == 'enter':
            launchDialog(self.parent)
        else:
            return key


if __name__ == "__main__":
    import doctest
    doctest.testmod()
