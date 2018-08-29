from weasel.log import log


scannedDisks = set()

def _getEsxScannedDisk(disk):
    """Helper function that scans the disk object and ensures that it is only
       scanned once.
    """
    global scannedDisks
    if disk not in scannedDisks:
        # Now scan the disk for previous installs.
        # This modifies the disk in place
        try:
            log.info('Scanning disk for previous installs: %s' % disk.name)
            from weasel import upgrade
            upgrade.checkForPreviousInstalls(disk)
            scannedDisks.add(disk)
        except Exception as ex:
            log.warn("Issues checking '%s' for any previous installation (%s)."
                     % (disk.name, str(ex)))
    else:
        log.debug("Disk: %s has already scanned. Skipping the scan."
                  % disk.name)
    return disk


def getDiskFilters(names):
    def _findEsx(disks):
        for disk in disks:
            if _getEsxScannedDisk(disk).containsEsx:
                return [disk]
        return []

    def localFilter(disks, cache):
        if 'local' in cache:
            log.debug("cache has 'local' disks.")
            localDisks = cache.get('local')
        else:
            localDisks = [disk for disk in disks if disk.local]
            cache['local'] = localDisks
        return localDisks

    def localEsxFilter(disks, cache):
        localDisks = localFilter(disks, cache)
        return _findEsx(localDisks)

    def remoteFilter(disks, cache):
        if 'remote' in cache:
            log.debug("cache has 'remote' disks.")
            remoteDisks = cache.get('remote')
        else:
            remoteDisks = [disk for disk in disks if not disk.local]
            cache['remote'] = remoteDisks
        return remoteDisks

    def remoteEsxFilter(disks, cache):
        remoteDisks = remoteFilter(disks, cache)
        return _findEsx(remoteDisks)

    def esxFilter(disks, cache):
        localEsxDisk = localEsxFilter(disks, cache)
        if localEsxDisk:
            log.debug("'esx' disk is found at local disk.")
            return localEsxDisk
        remoteEsxDisk = remoteEsxFilter(disks, cache)
        if remoteEsxDisk:
            log.debug("'esx' disk is found at remote disk.")
        else:
            log.debug("'esx' disk not found.")
        return remoteEsxDisk

    def usbFilter(disks, _cache):
        return [disk for disk in disks if disk.isUSB]

    def makeUsbDisksFilter(name):
        """
        Filter the USB disk with filter name as one of:

        - vmkusb: usb native driver name
        - usb-storage: usb legacy storage driver name
        - umass: usb native storage driver name

        Meanwhile, the filter name is not the driver name, since
        the driver name has already checked in makeGenericFilter.
        """
        def _usbDisksFilter(disks, _cache):
            return [disk for disk in disks if disk.isUSB and
                    name is not disk.driverName.strip().lower() and
                    name in ("vmkusb", "umass", "usb-storage")]

        return _usbDisksFilter

    def makeGenericFilter(name):
        def _genericFilter(disks, _cache):
            return [disk for disk in disks if name in
                    (disk.vendor.strip().lower(),
                     disk.model.strip().lower(),
                     disk.driverName.strip().lower())]

        return _genericFilter

    filterList = []

    filterMap = {
        'local': localFilter,
        'localesx': localEsxFilter,
        'remote': remoteFilter,
        'remoteesx': remoteEsxFilter,
        'esx': esxFilter,
        'usb': usbFilter,
    }

    nameList = [x.strip() for x in names.split(',')]

    for name in nameList:
        name = name.lower()
        filterList.append(filterMap.get(name, makeGenericFilter(name)))
        filterList.append(makeUsbDisksFilter(name))

    return filterList
