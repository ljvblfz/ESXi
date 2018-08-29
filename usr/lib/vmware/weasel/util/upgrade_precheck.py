#! /usr/bin/python

###############################################################################
# Copyright (c) 2008-2010, 2016 VMware, Inc.
#
# This file is part of Weasel.
#
# Weasel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# version 2 for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#

# autotest: doctest

from __future__ import print_function

import sys
if sys.version_info[0] <=2:
    from commands import getoutput, getstatusoutput
else:
    from subprocess import getoutput, getstatusoutput
import json
import operator
import os
import optparse
import re
import vmkctl
import socket
import xml.etree.ElementTree as etree


TASKNAME = 'Precheck'
TASKDESC = 'Preliminary checks'

# Directory where this file is running. Script expects data files, helper
# utilities to exist here.
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))

# Allow us to ship extra Python modules in a zip file.
sys.path.insert(0, os.path.join(SCRIPT_DIR, "esximage.zip"))

# the new ramdisk (resource pool) where we will copy the ISO to
RAMDISK_NAME = '/upgrade_scratch'

ESX_CONF_PATH = '/etc/vmware/esx.conf'

try:
    import logging
    logging.basicConfig(level=logging.DEBUG)
    log = logging.getLogger()
except ImportError:
    class logger:
        def write(self, *args):
            sys.stderr.write(args[0] % args[1:])
            sys.stderr.write("\n")
        debug = write
        error = write
        info = write
        warn = write
        warning = write
        def log(self, level, *args):
            sys.stderr.write(*args)
    log = logger()

SIZE_MiB = 1024 * 1024

class Result:
    ERROR = "ERROR"
    WARNING = "WARNING"
    SUCCESS = "SUCCESS"

    def __init__(self, name, found, expected,
                 comparator=operator.eq, errorMsg="", mismatchCode=None):
        """Parameters:
              * name         - A string, giving the name of the test.
              * found        - An object or sequence of objects. Each object
                               will be converted to a string representation, so
                               the objects should return an appropriate value
                               via their __str__() method.
              * expected     - Follows the same conventions as the found
                               parameter, but represents the result(s) that the
                               test expected.
              * comparator   - A method use to compare the found and expected
                               parameters. If comparator(found, expected) is
                               True, the value of the object's code attribute
                               will be Result.SUCCESS. Otherwise, the value of
                               the mismatchCode is returned, if specified, or
                               Result.ERROR.
              * errorMsg     - A string, describing the error.
              * mismatchCode - If not None, specifies a code to be assigned to
                               this object's result attribute when
                               comparator(found, expected) is False.
        """
        if not mismatchCode:
            mismatchCode = Result.ERROR

        self.name = name
        self.found = found
        self.expected = expected
        self.errorMsg = errorMsg
        if comparator(self.found, self.expected):
            self.code = Result.SUCCESS
        else:
            self.code = mismatchCode

    def __nonzero__(self):
        """For python2"""
        return self.code == Result.SUCCESS

    def __bool__(self):
        """For python3"""
        return self.__nonzero__()

    def __str__(self):
        if self.name == "MEMORY_SIZE":
            return ('<%s %s: This host has %s of RAM. %s are needed>'
                    % (self.name, self.code,
                     formatValue(self.found[0]), formatValue(self.expected[0])))
        elif self.name == "SPACE_AVAIL_ISO":
            return ('<%s %s: Only %s available for ISO files. %s are needed>'
                    % (self.name, self.code,
                     formatValue(self.found[0]), formatValue(self.expected[0])))
        elif self.name == "UNSUPPORTED_DEVICES":
            return ('<%s %s: This host has unsupported devices %s>'
                    % (self.name, self.code, self.found))
        elif self.name == "CPU_CORES":
            return ('<%s %s: This host has %s cpu core(s) which is less '
                   'than recommended %s cpu cores>'
                    % (self.name, self.code, self.found, self.expected))
        elif self.name == "HARDWARE_VIRTUALIZATION":
            return ('<%s %s: Hardware Virtualization is not a '
                   'feature of the CPU, or is not enabled in the BIOS>'
                    % (self.name, self.code))
        elif self.name == "VALIDATE_HOST_HW":
            # Prepare the strings.
            prepStrings = []
            for match, vibPlat, hostPlat in self.found:
                hostStr = "%s VIB for %s found, but host is %s" % \
                          (match, vibPlat, hostPlat)
                prepStrings.append(hostStr)

                return '<%s %s: %s>' % (self.name, self.code, ', '.join(prepStrings))
        elif self.name == "CONFLICTING_VIBS":
            return ('<%s %s: %s %s>'
                    % (self.name, self.code, self.errorMsg, self.found))
        elif self.name == "UPGRADE_PATH":
            return ('<%s %s: %s>'
                    % (self.name, self.code, self.errorMsg))
        elif self.name == "CPU_SUPPORT":
            return ('<%s %s: %s>'
                    % (self.name, self.code, self.errorMsg))
        elif self.name == "VMFS_VERSION":
            return ('<%s %s: %s>'
                    % (self.name, self.code, self.errorMsg))
        elif self.name == "NO_NICS_DETECTED":
            return ('<%s %s: %s>'
                    % (self.name, self.code, self.errorMsg))
        elif self.name == "LIMITED_DRIVERS":
            return ('<%s %s: %s>'
                    % (self.name, self.code, self.errorMsg))
        elif self.name == "IMAGEPROFILE_SIZE":
            return ('<%s %s: %s: '
                    'Target image profile size is %s MB,  but maximum '
                    'supported size is %s MB>'
                    % (self.name, self.code, self.errorMsg,
                       self.found, self.expected))
        else:
            return ('<%s %s: Found=%s Expected=%s %s>'
                    % (self.name, self.code,
                       self.found, self.expected, self.errorMsg))
    __repr__ = __str__


class PciInfo:
    '''Class to encapsulate PCI data'''
    #
    # TODO: this technique probably won't be sufficient.  I'll need to
    #       check the subdevice info as well.  The easy approach is probably
    #       to import pciidlib.py and extend it with these __eq__ and __ne__
    #       functions.  Also, I'll have to check that pciidlib works on both
    #       ESX and ESXi
    #

    def __init__(self, vendorId, deviceId, subsystem=None, description=""):
        '''Construct a PciInfo object with the given values: vendorId and
        deviceId should be strings with the appropriate hex values.  Description
        is an english description of the PCI device.'''

        self.vendorId = vendorId.lower()
        self.deviceId = deviceId.lower()
        if subsystem:
            self.subsystem = subsystem.lower()
        else:
            self.subsystem = subsystem
        self.description = description

    # XXX WARNING: The 'ne' operator is wider than 'eq' operator.  Note that
    # 'ne' explitcly compares all properties for inequality.  Equality will only
    # compare the vendorId and deviceId if any of the inputs don't define a
    # subsystem.
    def __eq__(self, rhs):
        if self.subsystem is None or rhs.subsystem is None:
            return (self.vendorId == rhs.vendorId and
                    self.deviceId == rhs.deviceId)
        else:
            return (self.vendorId == rhs.vendorId and
                    self.deviceId == rhs.deviceId and
                    self.subsystem == rhs.subsystem)

    def __ne__(self, rhs):
        return (self.vendorId != rhs.vendorId or
                self.deviceId != rhs.deviceId or
                self.subsystem != rhs.subsystem)

    def __str__(self):
        return "%s [%s:%s %s]" % (self.description, self.vendorId,
                                  self.deviceId, self.subsystem)

    def __repr__(self):
        return "<PciInfo '%s'>" % str(self)

UNSUPPORTED_PCI_IDE_DEVICE_LIST = [
    # eg: PciInfo("10b9", "5228", "ALi15x3"),
    ]

UNSUPPORTED_PCI_DEVICE_LIST = UNSUPPORTED_PCI_IDE_DEVICE_LIST + [
    # Any other devices we want to warn about?
    # eg: PciInfo("8086", "1229", "Ethernet Pro 100"),
    PciInfo("0e11", "b060", "0e11:4070", "5300"),
    PciInfo("0e11", "b178", "0e11:4080", "5i"),
    PciInfo("0e11", "b178", "0e11:4082", "532"),
    PciInfo("0e11", "b178", "0e11:4083", "5312"),
    PciInfo("0e11", "0046", "0e11:4091", "6i"),
    PciInfo("0e11", "0046", "0e11:409A", "641"),
    PciInfo("0e11", "0046", "0e11:409B", "642"),
    PciInfo("0e11", "0046", "0e11:409C", "6400"),
    PciInfo("0e11", "0046", "0e11:409D", "6400 EM"),
    PciInfo("1000", "0060", None       , "LSI MegaRAID SAS 1078 Controller"),
    PciInfo("1000", "0407", None       , "LSI MegaRAID 320-2x"),
    PciInfo("1000", "0408", None       , "LSI Logic MegaRAID"),
    PciInfo("1000", "1960", None       , "LSI Logic MegaRAID"),
    PciInfo("1000", "9010", None       , "LSI Logic MegaRAID"),
    PciInfo("1000", "9060", None       , "LSI Logic MegaRAID"),
    PciInfo("1014", "002e", None       , "SCSI RAID Adapter (ServeRAID) 4Lx"),
    PciInfo("1014", "01bd", None       , "ServeRAID Controller 6i"),
    PciInfo("103c", "3220", "103c:3225", "P600"),
    PciInfo("103c", "3230", "103c:3223", "P800"),
    PciInfo("103c", "3230", "103c:3225", "P600"),
    PciInfo("103c", "3230", "103c:3234", "P400"),
    PciInfo("103c", "3230", "103c:3235", "P400i"),
    PciInfo("103c", "3230", "103c:3237", "E500"),
    PciInfo("103c", "3238", "103c:3211", "E200i"),
    PciInfo("103c", "3238", "103c:3212", "E200"),
    PciInfo("103c", "3238", "103c:3213", "E200i"),
    PciInfo("103c", "3238", "103c:3214", "E200i"),
    PciInfo("103c", "3238", "103c:3215", "E200i"),
    PciInfo("1077", "2300", None       , "QLA2300 64-bit Fibre Channel Adapter"),
    PciInfo("1077", "2312", None       , "ISP2312-based 2Gb Fibre Channel to PCI-X HBA"),
    PciInfo("1077", "2322", None       , "ISP2322-based 2Gb Fibre Channel to PCI-X HBA"),
    PciInfo("1077", "4022", "0000:0000", "iSCSI device"),
    PciInfo("1077", "4022", "1077:0122", "iSCSI device"),
    PciInfo("1077", "4022", "1077:0124", "iSCSI device"),
    PciInfo("1077", "4022", "1077:0128", "iSCSI device"),
    PciInfo("1077", "4022", "1077:012e", "iSCSI device"),
    PciInfo("1077", "4032", "1077:014f", "iSCSI device"),
    PciInfo("1077", "4032", "1077:0158", "iSCSI device"),
    PciInfo("1077", "5432", None       , "SP232-based 4Gb Fibre Channel to PCI Express HBA"),
    PciInfo("1077", "6312", None       , "SP202-based 2Gb Fibre Channel to PCI-X HBA"),
    PciInfo("1077", "6322", None       , "SP212-based 2Gb Fibre Channel to PCI-X HBA"),
    PciInfo("1095", "0643", None       , "CMD643 IDE/PATA Controller"),
    PciInfo("1095", "0646", None       , "CMD646 IDE/PATA Controller"),
    PciInfo("1095", "0648", None       , "CMD648 IDE/PATA Controller"),
    PciInfo("1095", "0649", None       , "CMD649 IDE/PATA Controller"),
    PciInfo("1095", "0240", None       , "Adaptec AAR-1210SA SATA HostRAID Controller"),
    PciInfo("1095", "0680", None       , "Sil0680A - PCI to 2 Port IDE/PATA Controller"),
    PciInfo("1095", "3112", None       , "SiI 3112 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("1095", "3114", None       , "SiI 3114 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("1095", "3124", None       , "SiI 3124 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("1095", "3132", None       , "SiI 3132 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("1095", "3512", None       , "SiI 3512 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("1095", "3531", None       , "SiI 3531 [SATALink/SATARaid] Serial ATA Controller"),
    PciInfo("10df", "e100", None       , "LPev12000"),
    PciInfo("10df", "e131", None       , "LPev12002"),
    PciInfo("10df", "e180", None       , "LPev12000"),
    PciInfo("10df", "f095", None       , "LP952 Fibre Channel Adapter"),
    PciInfo("10df", "f098", None       , "LP982 Fibre Channel Adapter"),
    PciInfo("10df", "f0a1", None       , "LP101 2Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "f0a5", None       , "LP1050 2Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "f0d5", None       , "LP1150 4Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "f0e5", None       , "Fibre channel HBA"),
    PciInfo("10df", "f800", None       , "LP8000 Fibre Channel Host Adapter"),
    PciInfo("10df", "f900", None       , "LP9000 Fibre Channel Host Adapter"),
    PciInfo("10df", "f980", None       , "LP9802 Fibre Channel Adapter"),
    PciInfo("10df", "fa00", None       , "LP10000 2Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "fc00", None       , "LP10000-S 2Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "fc10", "10df:fc11", "LP11000-S 4Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "fc10", "10df:fc12", "LP11002-S 4Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "fc20", None       , "LPE11000S"),
    PciInfo("10df", "fd00", None       , "LP11000 4Gb Fibre Channel Host Adapter"),
    PciInfo("10df", "fe00", "103c:1708", "Fibre channel HBA"),
    PciInfo("10df", "fe00", "10df:fe00", "Fibre channel HBA"),
    PciInfo("10df", "fe00", "10df:fe22", "Fibre channel HBA"),
    PciInfo("10df", "fe05", None       , "Fibre channel HBA"),
    PciInfo("10df", "fe12", None       , "Cisco UCS CNA M71KR-Emulex"),
    PciInfo("101e", "1960", None       , "MegaRAID"),
    PciInfo("101e", "9010", None       , "MegaRAID 428 Ultra RAID Controller"),
    PciInfo("101e", "9060", None       , "MegaRAID 434 Ultra GT RAID Controller"),
    PciInfo("1022", "209a", None       , "AMD CS5536 IDE/PATA Controller"),
    PciInfo("1022", "7401", None       , "AMD Cobra 7401 IDE/PATA Controller"),
    PciInfo("1022", "7409", None       , "AMD Viper 7409 IDE/PATA Controller"),
    PciInfo("1022", "7411", None       , "AMD Viper 7411 IDE/PATA Controller"),
    PciInfo("1022", "7441", None       , "AMD 7441 OPUS IDE/PATA Controller"),
    PciInfo("1022", "7469", None       , "AMD 8111 IDE/PATA Controller"),
    PciInfo("1028", "000e", None       , "Dell PowerEdge Expandable RAID Controller"),
    PciInfo("1028", "000f", None       , "Dell PERC 4"),
    PciInfo("1028", "0013", None       , "Dell PERC 4E/Si/Di"),
    PciInfo("105a", "1275", None       , "PDC20275 Ultra ATA/133 IDE/PATA Controller"),
    PciInfo("105a", "3318", None       , "PDC20318 (SATA150 TX4)"),
    PciInfo("105a", "3319", None       , "PDC20319 (FastTrak S150 TX4)"),
    PciInfo("105a", "3371", None       , "PDC20371 (FastTrak S150 TX2plus)"),
    PciInfo("105a", "3373", None       , "PDC20378 (FastTrak 378/SATA 378)"),
    PciInfo("105a", "3375", None       , "PDC20375 (SATA150 TX2plus)"),
    PciInfo("105a", "3376", None       , "PDC20376 (FastTrak 376)"),
    PciInfo("105a", "3515", None       , "PDC40719 (FastTrak TX4300/TX4310)"),
    PciInfo("105a", "3519", None       , "PDC40519 (FastTrak TX4200)"),
    PciInfo("105a", "3570", None       , "PDC20771 (FastTrak TX2300)"),
    PciInfo("105a", "3571", None       , "PDC20571 (FastTrak TX2200)"),
    PciInfo("105a", "3574", None       , "PDC20579 SATAII 150 IDE Controller"),
    PciInfo("105a", "3577", None       , "PDC40779 (FastTrak TX2300)"),
    PciInfo("105a", "3d17", None       , "PDC40718 (SATA 300 TX4)"),
    PciInfo("105a", "3d18", None       , "PDC20518/PDC40518 (SATAII 150 TX4)"),
    PciInfo("105a", "3d73", None       , "PDC40775 (SATA 300 TX2plus)"),
    PciInfo("105a", "3d75", None       , "PDC20575 (SATAII150 TX2plus)"),
    PciInfo("105a", "4d68", None       , "PDC20268 Ultra ATA/100 IDE/PATA Controller"),
    PciInfo("105a", "4d69", None       , "PDC20269 (Ultra133 TX2) IDE/PATA Controller"),
    PciInfo("105a", "5275", None       , "PDC20276 Ultra ATA/133 IDE/PATA Controller"),
    PciInfo("105a", "6268", None       , "PDC20270 Ultra ATA/100 IDE/PATA Controller"),
    PciInfo("105a", "6269", None       , "PDC20271 Ultra ATA/133 IDE/PATA Controller"),
    PciInfo("105a", "6629", None       , "PDC20619 (FastTrak TX4000)"),
    PciInfo("105a", "7275", None       , "PDC20277 Ultra ATA/133 IDE/PATA Controller"),
    PciInfo("17d5", "5831", None       , "Xframe I 10 GbE Server/Storage adapter"),
    PciInfo("17d5", "5832", None       , "Xframe II 10 GbE Server/Storage adapter"),
    PciInfo("10de", "0035", None       , "nvidia NForce MCP04 IDE/PATA Controller"),
    PciInfo("10de", "0036", None       , "MCP04 Serial ATA Controller"),
    PciInfo("10de", "003e", None       , "MCP04 Serial ATA Controller"),
    PciInfo("10de", "0053", None       , "nvidia NForce CK804 IDE/PATA Controller"),
    PciInfo("10de", "0054", None       , "CK804 Serial ATA Controller"),
    PciInfo("10de", "0055", None       , "CK804 Serial ATA Controller"),
    PciInfo("10de", "0056", None       , "nvidia NForce Pro 2200 Network Controller"),
    PciInfo("10de", "0057", None       , "nvidia NForce Pro 2200 Network Controller"),
    PciInfo("10de", "0065", None       , "nvidia NForce2 IDE/PATA Controller"),
    PciInfo("10de", "0085", None       , "nvidia NForce2S IDE/PATA Controller"),
    PciInfo("10de", "008e", None       , "nForce2 Serial ATA Controller"),
    PciInfo("10de", "00d5", None       , "nvidia NForce3 IDE/PATA Controller"),
    PciInfo("10de", "00e3", None       , "CK8S Serial ATA Controller (v2.5)"),
    PciInfo("10de", "00ee", None       , "CK8S Serial ATA Controller (v2.5)"),
    PciInfo("10de", "00e5", None       , "nvidia NForce3S IDE/PATA Controller"),
    PciInfo("10de", "01bc", None       , "nvidia NForce IDE/PATA Controller"),
    PciInfo("10de", "0265", None       , "nvidia NForce MCP51 IDE/PATA Controller"),
    PciInfo("10de", "0266", None       , "MCP51 Serial ATA Controller"),
    PciInfo("10de", "0267", None       , "MCP51 Serial ATA Controller"),
    PciInfo("10de", "0268", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0269", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "036e", None       , "nvidia NForce MCP55 IDE/PATA Controller"),
    PciInfo("10de", "0372", None       , "nvidia NForce Pro 3600 Network Controller"),
    PciInfo("10de", "0373", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "037e", None       , "MCP55 SATA Controller"),
    PciInfo("10de", "037f", None       , "MCP55 SATA Controller"),
    PciInfo("10de", "03e7", None       , "MCP61 SATA Controller"),
    PciInfo("10de", "03ec", None       , "nvidia NForce MCP61 IDE/PATA Controller"),
    PciInfo("10de", "03f6", None       , "MCP61 SATA Controller"),
    PciInfo("10de", "03f7", None       , "MCP61 SATA Controller"),
    PciInfo("10de", "0448", None       , "nvidia NForce MCP65 IDE/PATA Controller"),
    PciInfo("10de", "045c", None       , "MCP65 SATA Controller"),
    PciInfo("10de", "045d", None       , "MCP65 SATA Controller"),
    PciInfo("10de", "045e", None       , "MCP65 SATA Controller"),
    PciInfo("10de", "045f", None       , "MCP65 SATA Controller"),
    PciInfo("10de", "054c", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "054d", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "054e", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "054f", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0550", None       , "MCP67 AHCI Controller"),
    PciInfo("10de", "0551", None       , "MCP67 SATA Controller"),
    PciInfo("10de", "0552", None       , "MCP67 SATA Controller"),
    PciInfo("10de", "0553", None       , "MCP67 SATA Controller"),
    PciInfo("10de", "0560", None       , "nvidia NForce MCP67 IDE/PATA Controller"),
    PciInfo("10de", "056c", None       , "nvidia NForce MCP73 IDE/PATA Controller"),
    PciInfo("10de", "0759", None       , "nvidia NForce MCP77 IDE/PATA Controller"),
    PciInfo("10de", "0760", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0761", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0762", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0763", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "07dc", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "07dd", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "07de", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "07df", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0ab0", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0ab1", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0ab2", None       , "nvidia NForce Network Controller"),
    PciInfo("10de", "0ab3", None       , "nvidia NForce Network Controller"),
    PciInfo("1103", "0004", None       , "HPT 366 (rev 06) IDE/PATA Controller"),
    PciInfo("1103", "0005", None       , "HPT 372 (rev 02) IDE/PATA Controller"),
    PciInfo("1103", "0006", None       , "HPT 302/302N (rev 02) IDE/PATA Controller"),
    PciInfo("1103", "0007", None       , "HPT 371/371N (rev 02) IDE/PATA Controller"),
    PciInfo("1103", "0009", None       , "HPT 372N IDE/PATA Controller"),
    PciInfo("1106", "5324", None       , "VX800 SATA/EIDE Controller"),
    PciInfo("1166", "0211", None       , "Serverworks OSB4 IDE/PATA Controller"),
    PciInfo("1166", "0212", None       , "Serverworks CSB5 IDE/PATA Controller"),
    PciInfo("1166", "0213", None       , "Serverworks CSB6 IDE/PATA Controller"),
    PciInfo("1166", "0214", None       , "Serverworks HT1000 IDE/PATA Controller"),
    PciInfo("1166", "0215", None       , "Serverworks HT1100 IDE/PATA Controller"),
    PciInfo("1166", "0217", None       , "Serverworks CSB6IDE2 IDE/PATA Controller"),
    PciInfo("1166", "0240", None       , "K2 SATA"),
    PciInfo("1166", "0241", None       , "RAIDCore RC4000"),
    PciInfo("1166", "0242", None       , "RAIDCore RC4000"),
    PciInfo("1166", "024a", None       , "BCM5785 [HT1000] SATA (Native SATA Mode)"),
    PciInfo("1166", "024b", None       , "BCM5785 [HT1000] SATA (PATA/IDE Mode)"),
    PciInfo("1166", "0410", None       , "BroadCom HT1100 SATA Controller (NATIVE SATA Mode)"),
    PciInfo("1166", "0411", None       , "BroadCom HT1100 SATA Controller (PATA/IDE Mode)"),
    PciInfo("19a2", "0700", "10df:e602", "FCoE CNA"),
    PciInfo("19a2", "0704", "10df:e630", "FCoE CNA"),
    PciInfo("19a2", "0704", "1137:006e", "FCoE CNA"),
    PciInfo("4040", "0001", None       , "10G Ethernet PCI Express"),
    PciInfo("4040", "0001", "103c:7047", "HP NC510F PCIe 10 Gigabit Server Adapter"),
    PciInfo("4040", "0002", None       , "10G Ethernet PCI Express CX"),
    PciInfo("4040", "0002", "103c:7048", "HP NC510C PCIe 10 Gigabit Server Adapter"),
    PciInfo("4040", "0004", None       , "IMEZ 10 Gigabit Ethernet"),
    PciInfo("4040", "0005", None       , "HMEZ 10 Gigabit Ethernet"),
    PciInfo("4040", "0100", None       , "1G/10G Ethernet PCI Express"),
    PciInfo("4040", "0100", "103c:171b", "HP NC522m Dual Port 10GbE Multifunction BL-c Adapter"),
    PciInfo("4040", "0100", "103c:1740", "HP NC375T PCI Express Quad Port Gigabit Server Adapter"),
    PciInfo("4040", "0100", "103c:3251", "HP NC375i 1G w/NC524SFP 10G Module"),
    PciInfo("4040", "0100", "103c:705a", "HP NC375i Integrated Quad Port Multifunction Gigabit Server Adapter"),
    PciInfo("4040", "0100", "103c:705b", "HP NC522SFP Dual Port 10GbE Server Adapter"),
    PciInfo("4040", "0100", "152d:896b", "Quanta SFP+ Dual Port 10GbE Adapter"),
    PciInfo("4040", "0100", "4040:0123", "Dual Port 10GbE CX4 Adapter"),
    PciInfo("4040", "0100", "4040:0124", "QLE3044 (NX3-4GBT) Quad Port PCIe 2.0 Gigabit Ethernet Adapter"),
    PciInfo("4040", "0100", "4040:0125", "NX3-IMEZ 10 Gigabit Ethernet"),
    PciInfo("4040", "0100", "4040:0126", "QLE3142 (NX3-20GxX) Dual Port PCIe 2.0 10GbE SFP+ Adapter"),
    PciInfo("8086", "1001", None       , "82543GC Gigabit Ethernet Controller (Fiber)"),
    PciInfo("8086", "1004", None       , "82543GC Gigabit Ethernet Controller (Copper)"),
    PciInfo("8086", "1008", None       , "82544EI Gigabit Ethernet Controller (Copper)"),
    PciInfo("8086", "1009", None       , "82544EI Gigabit Ethernet Controller (Fiber)"),
    PciInfo("8086", "100c", None       , "82544GC Gigabit Ethernet Controller (Copper)"),
    PciInfo("8086", "100d", None       , "82544GC Gigabit Ethernet Controller (LOM)"),
    PciInfo("8086", "100e", None       , "82540EM Gigabit Ethernet Controller"),
    PciInfo("8086", "1011", None       , "82545EM Gigabit Ethernet Controller (Fiber)"),
    PciInfo("8086", "1012", None       , "82546EM Gigabit Ethernet Controller (Fiber)"),
    PciInfo("8086", "1013", None       , "82541EI Gigabit Ethernet Controller"),
    PciInfo("8086", "1014", None       , "82541ER Gigabit Ethernet Controller"),
    PciInfo("8086", "1015", None       , "82540EM Gigabit Ethernet Controller (LOM)"),
    PciInfo("8086", "1016", None       , "82540EP Gigabit Ethernet Controller"),
    PciInfo("8086", "1017", None       , "82540EP Gigabit Ethernet Controller"),
    PciInfo("8086", "1018", None       , "82541EI Gigabit Ethernet Controller"),
    PciInfo("8086", "1019", None       , "82547EI Gigabit Ethernet Controller"),
    PciInfo("8086", "101a", None       , "82547EI Gigabit Ethernet Controller"),
    PciInfo("8086", "101d", None       , "82546EB Gigabit Ethernet Controller"),
    PciInfo("8086", "101e", None       , "82540EP Gigabit Ethernet Controller"),
    PciInfo("8086", "1026", None       , "82545GM Gigabit Ethernet Controller"),
    PciInfo("8086", "1027", None       , "82545GM Gigabit Ethernet Controller"),
    PciInfo("8086", "1028", None       , "82545GM Gigabit Ethernet Controller"),
    PciInfo("8086", "1075", None       , "82547GI Gigabit Ethernet Controller"),
    PciInfo("8086", "1076", None       , "82541GI Gigabit Ethernet Controller"),
    PciInfo("8086", "1077", None       , "82541GI Gigabit Ethernet Controller"),
    PciInfo("8086", "1078", None       , "82541ER Gigabit Ethernet Controller"),
    PciInfo("8086", "1079", None       , "82546EB Gigabit Ethernet Controller"),
    PciInfo("8086", "107a", None       , "82546GB Gigabit Ethernet Controller"),
    PciInfo("8086", "107b", None       , "82546GB Gigabit Ethernet Controller"),
    PciInfo("8086", "107c", None       , "82541PI Gigabit Ethernet Controller"),
    PciInfo("8086", "108a", None       , "82546GB Gigabit Ethernet Controller"),
    PciInfo("8086", "1098", "1458:0000", "NIC Goshan"),
    PciInfo("8086", "1099", None       , "82546GB Gigabit Ethernet Controller (Copper)"),
    PciInfo("8086", "10b5", None       , "82546GB Gigabit Ethernet Controller (Copper)"),
    PciInfo("8086", "10c7", "8086:a16f", "Intel 10 Gigabit XF SR Server Adapter"),
    PciInfo("8086", "1960", "101e:0438", "MegaRAID 438 Ultra2 LVD RAID Controller"),
    PciInfo("8086", "1960", "101e:0466", "MegaRAID 466 Express Plus RAID Controller"),
    PciInfo("8086", "1960", "101e:0467", "MegaRAID 467 Enterprise 1500 RAID Controller"),
    PciInfo("8086", "1960", "101e:09a0", "PowerEdge Expandable RAID Controller 2/SC"),
    PciInfo("8086", "1960", "1028:0467", "PowerEdge Expandable RAID Controller 2/DC"),
    PciInfo("8086", "1960", "1028:1111", "PowerEdge Expandable RAID Controller 2/SC"),
    PciInfo("8086", "1960", "103c:03a2", "MegaRAID"),
    PciInfo("8086", "1960", "103c:10c6", "MegaRAID 438, HP NetRAID-3Si"),
    PciInfo("8086", "1960", "103c:10c7", "MegaRAID T5, Integrated HP NetRAID"),
    PciInfo("8086", "1960", "103c:10cc", "MegaRAID, Integrated HP NetRAID"),
    PciInfo("9005", "0250", None       , "ServeRAID Controller"),
    PciInfo("9005", "0410", None       , "AIC-9410"),
    PciInfo("9005", "0411", None       , "AIC-9410"),
    PciInfo("9005", "0412", None       , "AIC-9410"),
    PciInfo("9005", "041e", None       , "AIC-9410"),
    PciInfo("9005", "041f", None       , "AIC-9410"),
    PciInfo("9005", "8000", None       , "ASC-29320A U320"),
    PciInfo("9005", "800f", None       , "AIC-7901 U320"),
    PciInfo("9005", "8010", None       , "ASC-39320 U320"),
    PciInfo("9005", "8011", None       , "39320D Ultra320 SCSI"),
    PciInfo("9005", "8011", "0e11:00ac", "ASC-32320D U320"),
    PciInfo("9005", "8011", "9005:0041", "ASC-39320D U320"),
    PciInfo("9005", "8012", None       , "ASC-29320 U320"),
    PciInfo("9005", "8013", None       , "ASC-29320B U320"),
    PciInfo("9005", "8014", None       , "ASC-29320LP U320"),
    PciInfo("9005", "8015", None       , "AHA-39320B"),
    PciInfo("9005", "8016", None       , "AHA-39320A"),
    PciInfo("9005", "801c", None       , "AHA-39320DB / AHA-39320DB-HP"),
    PciInfo("9005", "801d", None       , "AIC-7902B U320 OEM"),
    PciInfo("9005", "801e", None       , "AIC-7901A U320"),
    PciInfo("9005", "801f", None       , "AIC-7902 U320, AIC-7902 Ultra320 SCSI"),
    PciInfo("9005", "8094", None       , "ASC-29320LP U320 w/HostRAID"),
    PciInfo("9005", "809e", None       , "AIC-7901A U320 w/HostRAID"),
    PciInfo("9005", "809f", None       , "AIC-7902 U320 w/HostRAID"),
    ]
class SystemProbe(object):

    def vmkfstoolsDashP(self, path):
        cmd = 'vmkfstools -P %s' % path
        log.info('Running %s' % cmd)
        status, rawPartitionInfo = getstatusoutput(cmd)
        if status != 0:
            log.error('vmkfstools returned status %d' % status)
            return ''
        return rawPartitionInfo

    #Can't do a staticmethod, because it runs on ESX3.5 (Py2.3)
    def parseVmkfstoolsDashP(self, rawPartitionInfo):
        '''Return a dictionary with the following keys:
        fsType, totalBytes, freeBytes, uuid, diskHBAName, partNum
        with string values that are the result of scraping the output of the
        command `vmkfstools -P path`
        rawPartitionInfo will look something like this:
        >>> info = os.linesep.join([
        ... 'vfat-0.04 file system spanning 1 partitions.',
        ... 'File system label (if any): Hypervisor1',
        ... 'Mode: private',
        ... 'Capacity 261853184 (63929 file blocks * 4096), 164687872 (40207 blocks) avail',
        ... 'UUID: 96f2ab7c-e353fc5f-cc7b-5ca987e270a4',
        ... 'Partitions spanned (on "disks"):',
        ... '   mpx.vmhba1:C0:T0:L0:5']
        ... )
        >>> s = SystemProbe()
        >>> sorted(s.parseVmkfstoolsDashP(info).items())
        [('diskHBAName', 'mpx.vmhba1:C0:T0:L0'), ('freeBytes', '164687872'), ('fsType', 'vfat-0.04'), ('partNum', '5'), ('totalBytes', '261853184'), ('uuid', '96f2ab7c-e353fc5f-cc7b-5ca987e270a4')]
        '''

        pattern = re.compile(r'''
        (?P<fsType>\S+).file.system.spanning     # vfat-0.04 file system spanning
        .*?                                      # eat some stuff
        Capacity\s(?P<totalBytes>\d+)            # Capacity 261853184
        .\([^\)]*\),                             #  (63929 file blocks * 4096),
        .(?P<freeBytes>\d+)                      #  164687872
        .*?                                      # eat some stuff
        UUID:.(?P<uuid>\S+)                      # UUID: 96f2ab7c-e....87e270a4
        .*?                                      # eat some stuff
        \s*(?P<diskHBAName>\S*):(?P<partNum>\d)  #    mpx.vmhba1:C0:T0:L0:5
        ''', re.VERBOSE | re.MULTILINE | re.DOTALL)

        match = pattern.search(rawPartitionInfo)
        if match:
            return match.groupdict()
        else:
            log.error('Could not parse vmkfstools output:')
            log.error('"%s"' % rawPartitionInfo)
            return {}

    def partitionInfo(self, path):
        return self.parseVmkfstoolsDashP(self.vmkfstoolsDashP(path))

class SystemProbeESXi(SystemProbe):
    def __init__(self, version):
        '''query relevant info about the ESXi system'''
        self.product = 'esxi'
        self.version = version
        self.vibCheckPath = '/'
        self.weaselMode = False
        self._systemUUID = None

        log.info('Running esxcfg-info')
        self.esxnwinfo = getoutput("/usr/sbin/esxcfg-info -n -F xml")

        self.pciinfo = self.parsePciInfo()

        self.bootDiskVMHBAName = self.getBootDiskVMHBAName()
        if self.bootDiskVMHBAName:
            self.bootDiskPath = '/vmfs/devices/disks/' + self.bootDiskVMHBAName
        else:
            # if we can't find bootdisk then bootDiskPath is empty. That
            # happens when it's a stateless (PXE booted) host
            self.bootDiskPath = ''

        self.esxconfNonempty = bool(os.path.exists(ESX_CONF_PATH)
                                    and os.path.getsize(ESX_CONF_PATH))

        from vmware.esximage import Vib
        from vmware.esximage.Utils import HostInfo
        vendor, model = HostInfo.GetBiosVendorModel()
        self.hostHws = [Vib.HwPlatform(vendor, model)]
        if getattr(HostInfo, 'GetBiosOEMStrings', None):
            for vendor in HostInfo.GetBiosOEMStrings():
                self.hostHws.append(Vib.HwPlatform(vendor, model=''))

    def getBootDiskVMHBAName(self):
        bootuuid = vmkctl.SystemInfoImpl().GetBootFileSystem()
        if not bootuuid:
            return ''
        if hasattr(bootuuid, 'get'):
           bootuuid = bootuuid.get()

        bootVolume = '/vmfs/volumes/' + bootuuid.GetUuid()

        resultDict = self.partitionInfo(bootVolume)
        diskHBAName = resultDict.get('diskHBAName')
        if diskHBAName:
            return diskHBAName
        else:
            log.error('Disk name not found in vmkfstools output')
            return ''

    def getSystemUUID(self):
        if self._systemUUID != None:
            return self._systemUUID

        sysuuid = vmkctl.SystemInfoImpl().GetSystemUuid().uuidStr
        if not sysuuid:
            log.error('could not get system uuid')
        else:
            self._systemUUID = sysuuid

        return self._systemUUID

    #Can't do a staticmethod, because it runs on ESX3.5 (Py2.3)
    def parsePciInfo(self):
        '''
        >>> sysprobe = SystemProbeESXi([4, 1, 0])
        >>> sysprobe.parsePciInfo(os.linesep.join([
        ...        'Bus:S1.F Vend:Dvid Subv:Subd ISA/irq/Vec P M Module       Name',
        ...        '00:00.00 8086:7190 15ad:1976               V',
        ...        '00:07.03 8086:7113 15ad:1976 255/   /     @ V ide          vmhba0',
        ...        '02:00.00 8086:100f 15ad:0750 10/ 10/0x91 A V e1000        vmnic0'
        ...        ]))
        [<PciInfo ' [8086:7190 15ad:1976]'>, <PciInfo ' [8086:7113 15ad:1976]'>, <PciInfo ' [8086:100f 15ad:0750]'>]
        '''
        retval = []

        pciDevices = vmkctl.PciInfoImpl().GetAllPciDevices()
        for dev in pciDevices:
            if hasattr(dev, 'get'):
                dev = dev.get()
            vendor = '{0:04x}'.format(dev.GetVendorId())
            device = '{0:04x}'.format(dev.GetDeviceId())
            subven = '{0:04x}'.format(dev.GetSubVendorId())
            subdev = '{0:04x}'.format(dev.GetSubDeviceId())
            retval.append(PciInfo(vendor, device, subven + ':' + subdev))

        return retval

class IsoMetadata(object):
    def __init__(self):
        self.vibs = []
        self.profile = None
        if systemProbe.weaselMode:
            self._loadVibDatabase()
        else:
            self._loadVibMetadata()
        self.novaImage = self._isNovaImage()
        self._calcIsoSize()

    def _loadVibDatabase(self):
        # Loads VIBs from esximage database on Visor FS.
        from vmware.esximage import Database
        d = Database.Database("/var/db/esximg", dbcreate=False)
        d.Load()
        self.vibs = list(d.vibs.values())
        self.profile = d.profile

    def _loadVibMetadata(self):
        from vmware.esximage import Metadata
        m = Metadata.Metadata()
        m.ReadMetadataZip(os.path.join(SCRIPT_DIR, "metadata.zip"))

        if len(m.profiles) != 1:
            raise Exception("Multiple or no image profiles in metadata!")

        self.profile = list(m.profiles.values())[0]
        self.vibs = [m.vibs[vid] for vid in self.profile.vibIDs]
        self.profile.vibs = m.vibs
        self.identifyNativeDevices()

    def _calcIsoSize(self):
        # The Metadata instance doesn't have any statistics about the size of the image
        # so we need to interate over all of the payloads to properly calculate.
        totalSize = 0
        for vib in self.vibs:
            for payload in vib.payloads:
                totalSize += payload.size

        # The total space for the ISO is estimated at the total payload size plus a 10MB
        # fudge factor to account for additional bits on the ISO that aren't strickly
        # reported in the VIB
        self.sizeOfISO = totalSize + (10 * SIZE_MiB)

    def identifyNativeDevices(self):
       """identifyNativeDevices

       Find all devices which are supported by the native drivers in
       a NOVA image.

       First, read out the PCI tags from the driver VIBs.
       Note that only native drivers built with a NativeDDK
       from the 6.5 release or later exhibit PCIID tags in
       this fashion.

       Then scan the output of 'localcli hardware pci list'
       to determine which of the PCI devices present on this
       system are directly supported by the native drivers
       in the ISO image (by matching PCIID tags).

       There are additional storage devices with adapter names
       such as vmhba32, vmhba33, ... which don't correspond to
       PCI aliases - and thus won't shop up in the pci list.
       For these, we will scan the output of:

          localcli storage core adapter list

       These devices are are supported if one of these two
       criteria are met:

          => If the driver's uid begins with "uid."

          => If the base PCI device has a vmhba<N> alias and
             it is supported by a native driver.

       Case 1 is used to pick up vmkusb devices.

       Case 2 is used to pick up supported vmk_ahci and vmkata devices.

       This algorithm excludes the CNA cases supported by vmklinux drivers
       such as "bnx2i", "bnx2fc" and "fcoe" - since the base device will
       be a nic.
       """
       pciDriverTags = []
       pciTagRegex = re.compile(r"PCIID\s+(?P<id>[0-9a-z.]*)\s*\Z")
       for vib in self.profile.vibs.values():
          if (hasattr(vib, 'swtags')):
             for tag in vib.swtags:
                m = pciTagRegex.match(tag)
                if m:
                   pciDriverTags.append(m.group('id'))

       #
       # Now find which of the vmhba(s) and vmnic(s) which
       # will have native drivers.  We record the devices by
       # their sbdfAddress because we will need to match that
       # up with the output from 'localcli storage core adapter list'.
       #
       # Luckily, all of the sbdf address(es) emitted by esxcli
       # in 5.5 and beyond are in lower case hex, so that base
       # conversion is not required (as might be the case with
       # older versions).  Nor do we need to force lower case.
       #
       self.nativeDevices = []
       deviceNames = re.compile(r"(vmhba|vmnic)(0|([1-9][0-9]*))\Z")
       cmd = 'localcli --formatter=json hardware pci list'
       log.debug('Running %s' % cmd)
       pciDevList = []
       status, output = getstatusoutput(cmd)
       if status != 0:
          log.error("Failed to obtain PCI info")
       else:
          try:
             pciDevList = json.loads(output)
          except ValueError as e:
             log.error("Failed to parse output of %s: %s" % (cmd, e))
       for device in pciDevList:
          name = device['VMkernel Name']
          if deviceNames.match(name):
             vendId = device['Vendor ID']
             devId = device['Device ID']
             subVendId = device['SubVendor ID']
             subDevId = device['SubDevice ID']
             pciClass = device['Device Class']
             pgmIf = device['Programming Interface']
             hwId = '%04x%04x%04x%04x%04x%02x' % (vendId,
                   devId, subVendId, subDevId, pciClass, pgmIf)

             #
             # Note that class drivers have the '.' characters at the
             # beginning or in the middle of the device specification
             # (driverTag).  Use re's match function to evaluate
             # the '.' characters as wildcards.
             #
             for driverTag in pciDriverTags:
                if re.match(driverTag, hwId):
                   log.debug('%s: identified native driver for '
                             'device' % name)
                   self.nativeDevices.append(name)

       #
       # Now find additional devices (i.e. usb, sata, fcoe and iscsi)
       # that have native drivers, but cannot be matched by PCIID.  We
       # find them by the sbdfAddress by scraping the description
       # field in the output from 'esxcli storage core adapter list'
       #
       # Admittedly, this method is a bit fragile.  Moreover, the
       # sbdf address changed from decimal in 5.5ga to hex later on.
       # We tolerate both forms by using string comparison within the
       # single command 'localcli storage core adapter list'.
       #
       sbdfRegex = re.compile(r"\((?P<sbdf>[0-9A-Fa-f:.]+)\)")
       usbRegex = re.compile(r"usb\.")
       cmd = 'localcli --formatter=json storage core adapter list'
       log.debug('Running %s' % cmd)
       adapterList = []
       status, output = getstatusoutput(cmd)
       if status != 0:
          log.error("Failed to obtain adapter info, status = %d" % status)
       else:
          try:
             adapterList = json.loads(output)
          except ValueError as e:
             log.error("Failed to parse output of %s: %s" % (cmd, e))

          #
          # Identify the mapping (sbdf -> device) for known native
          # driver supported devices.  This only find the sbd addresses
          # for the HBAs.
          #
          nativeSbdfIndex = {}
          for adapter in adapterList:
            name = adapter['HBA Name']
            description = adapter['Description']
            m = sbdfRegex.match(description)
            if m:
               sbdfAddress = m.group('sbdf')
               if name in self.nativeDevices:
                  nativeSbdfIndex[sbdfAddress] = name
                  log.debug("%s: identified sbdf '%s' for a native supported "
                            "device using description '%s'" %
                            (name, sbdfAddress, description))

          #
          # Now look for native supported devices in the localcli
          # output.
          #
          for adapter in adapterList:
            name = adapter['HBA Name']
            uid = adapter['UID']
            description = adapter['Description']

            #
            # case 1: To find usb devices (we assume all are supported
            #         by native).
            #
            if usbRegex.match(uid):
               log.debug("%s: found usb device with uid '%s' - "
                         "assuming native support" % (name, uid))
               self.nativeDevices.append(name)
               continue

            #
            # case 2: Find vmkata/vmk_ahci devices supported by native.
            #         We assume that if the base PCI device is supported
            #         by a native driver then the others are as well.
            #
            if name not in self.nativeDevices:
               m = sbdfRegex.match(description)
               if m:
                  sbdfAddress = m.group('sbdf')
                  if sbdfAddress in nativeSbdfIndex.keys():
                     baseName = nativeSbdfIndex[sbdfAddress]
                     log.debug("%s: found base native driver '%s' for "
                               "non-pciiid device with sbdfAddress '%s'" %
                               (name, baseName, sbdfAddress))
                     self.nativeDevices.append(name)
                  else:
                     log.debug("%s: rejected for native driver support "
                               "non-pciiid device with sbdfAddress '%s' "
                               "and description '%s'" %
                                  (name, sbdfAddress, description))

    def _isNovaImage(self):
        vmklinuxPath = 'usr/lib/vmware/vmkmod/vmklinux_9'
        return len([v for v in self.vibs
                    if vmklinuxPath in v.filelist]) == 0

# -----------------------------------------------------------------------------
def run(cmd):
    # commands.getoutput causes problems with esxcfg-advcfg
    # so invoke os.popen instead.
    log.info('Running command %s' % cmd)
    p = os.popen(cmd, 'r')
    output = p.read()
    returncode = p.close()
    if returncode == None:
        returncode = 0
    if returncode != 0:
        raise Exception('Command %s exited with code %s'
                        % (cmd, str(returncode)))
    return output

def formatValue(B=None, KiB=None, MiB=None):
    '''Takes an int value defined by one of the keyword args and returns a
    nicely formatted string like "2.6 GiB".  Defaults to taking in bytes.
    >>> formatValue(B=1048576)
    '1.00 MiB'
    >>> formatValue(MiB=1048576)
    '1.00 TiB'
    '''
    SIZE_KiB = (1024.0)
    SIZE_MiB = (SIZE_KiB * 1024)
    SIZE_GiB = (SIZE_MiB * 1024)
    SIZE_TiB = (SIZE_GiB * 1024)

    assert len([x for x in [KiB, MiB, B] if x != None]) == 1

    # Convert to bytes ..
    if KiB:
        value = KiB * SIZE_KiB
    elif MiB:
        value = MiB * SIZE_MiB
    else:
        value = B

    if value >= SIZE_TiB:
        return "%.2f TiB" % (value / SIZE_TiB)
    elif value >= SIZE_GiB:
        return "%.2f GiB" % (value / SIZE_GiB)
    elif value >= SIZE_MiB:
        return "%.2f MiB" % (value / SIZE_MiB)
    else:
        return "%s bytes" % (value)


# See http://kb.vmware.com/kb/1011712 for explanation
HV_ENABLED       = 3

# This should work on all ESX(i) 4.x and ESXi 5.x platforms.. hopefully.
def _getCpuExtendedFeatureBits():
    cpuRegs = getoutput('localcli --formatter=json hardware cpu cpuid get --cpu=0')
    regs = json.loads(cpuRegs)
    for reg in regs:
        if reg['Level'] == 0x80000001:
            return (reg['ECX'], reg['EDX'])
    return (0, 0)


EDX_LONGMODE_MASK = 0x20000000
ECX_LAHF64_MASK   = 0x00000001

def _parseLAHFSAHF64bitFeatures():
    # Get the extended feature bits.
    id81ECXValue, id81EDXValue = _getCpuExtendedFeatureBits()

    lahf64 = id81ECXValue & ECX_LAHF64_MASK
    longmode = id81EDXValue & EDX_LONGMODE_MASK

    k8ext = False

    cpu = vmkctl.CpuInfoImpl().GetCpus()[0]
    if hasattr(cpu, 'get'):
       cpu = cpu.get()
    vendor = cpu.GetVendorName()

    if vendor == 'AuthenticAMD':
        famValue = cpu.GetFamily()
        modValue = cpu.GetModel()

        # family == 15 and extended family == 0
        # extended model is 4-bit left shifted and added to model, must not be 0
        k8ext = (famValue == 0xF and ((modValue & 0xF0) > 0))

    # This should probably have deMorgan's applied to it...
    retval = not(not longmode or \
                 (not lahf64 and not (amd and k8ext)))
    return int(retval)

# NX-bit is bit-20 of EDX.
EDX_NX_MASK = 0x00100000

def _parseNXbitCpuFeature():
    # Get the extended features bits.
    id81ECXValue, id81EDXValue = _getCpuExtendedFeatureBits()

    nx_set = bool(id81EDXValue & EDX_NX_MASK)

    return int(nx_set)


def _parseVmwareVersion():
    output = getoutput("vmware -v")
    # result should be something like
    # "VMware ESX 4.0.0 build-123" or "VMware ESXi 4.1.0 build-123"
    pattern = re.compile(r'\s(ESXi?) (\d+\.\d+\.\d+)')
    match = pattern.search(output)
    if not match:
        msg = 'Could not parse VMware version (%s)' % output
        log.error(msg)
        raise Exception(msg)

    product = match.group(1)
    version = [int(x) for x in match.group(2).split('.')]
    return product, version

def allocateRamDisk(dirname, sizeInBytes):
    if os.path.exists(dirname):
        deallocateRamDisk(dirname)

    os.makedirs(dirname)
    resGroupName = 'upgradescratch'
    sizeInMegs = sizeInBytes // (1024*1024)
    sizeInMegs += 1 # in case it got rounded down by the previous division

    cmd = '/sbin/localcli system visorfs ramdisk add' + \
          ' -M %s' % sizeInMegs + \
          ' -m %s' % sizeInMegs + \
          ' -n %s' % resGroupName + \
          ' -t %s' % dirname + ' -p 01777'

    log.info('Running %s' % cmd)
    status, output = getstatusoutput(cmd)
    if status != 0:
        log.error('Creating ramdisk failed: (%s) %s' % (str(status), output))
        return False
    return True

def deallocateRamDisk(dirname):
    if not os.path.exists(dirname):
        return # already removed

    cmd = '/sbin/localcli system visorfs ramdisk remove -t %s' % dirname
    log.info('Running %s' % cmd)
    status, output = getstatusoutput(cmd)
    try:
        os.rmdir(dirname)
    except Exception as ex:
        log.warn('Could not remove %s: %s' % (dirname, ex))


#------------------------------------------------------------------------------
def memorySizeComparator(found, expected):
    '''Custom memory size comparator
    Let minimum memory go as much as 3.125% below MEM_MIN_SIZE.
    See PR 1229416 for more details.
    '''
    return operator.ge(found[0], expected[0] - (0.03125 * expected[0]))

def checkMemorySize():
    '''Check that there is enough memory
    '''
    mem = vmkctl.HardwareInfoImpl().GetMemoryInfo()
    if hasattr(mem, 'get'):
       mem = mem.get()
    found = mem.GetPhysicalMemory()

    MEM_MIN_SIZE = (4 * 1024) * SIZE_MiB
    return Result("MEMORY_SIZE", [found], [MEM_MIN_SIZE],
                  comparator=memorySizeComparator,
                  errorMsg="The memory is less than recommended",
                  mismatchCode = Result.ERROR)

#------------------------------------------------------------------------------
def checkNICsDetected():
    ''' For NOVA, we check the presence of a NIC at this late stage, as we
    must know if this is a fresh install or an upgrade. A fresh install cannot
    proceed, but an upgrade should. We assume that for upgrades, the old system
    must already have a vmklinux driver for the NIC, so we just issue a warning.
    '''
    from weasel.util import checkNICsDetected as _checkNICsDetected
    from weasel.util import NO_NIC_MSG
    from weasel import userchoices

    found = _checkNICsDetected()
    expected = True

    if userchoices.getInstall():
        mismatchCode = Result.ERROR
    else:
        mismatchCode = Result.WARNING

    return Result("NO_NICS_DETECTED", found, expected,
            errorMsg=NO_NIC_MSG,
            mismatchCode = mismatchCode)


#------------------------------------------------------------------------------
def upgradePathComparator(newVersion, installedVersion):
    '''
    Compartor used by checkUpgradePath method to check if we can upgrade.
    '''

    # Don't allow downgrades.
    # Downgrades between update releases are allowed (5.1U2 to 5.1U1).
    if newVersion < installedVersion:
        return False

    # Don't allow upgrades from 5.5 or prior version.
    if tuple(installedVersion) < ('6', '0',):
        return False

    return True


def checkUpgradePath():
    '''Check that the upgrade from the installed version to new version
    is allowed.
    '''

    from weasel import devices, userchoices
    from weasel.consts import PRODUCT_SHORT_STRING, PRODUCT_VERSION_NUMBER

    deviceName = userchoices.getEsxPhysicalDevice()
    ds = devices.DiskSet()
    device = ds[deviceName]

    return Result("UPGRADE_PATH", PRODUCT_VERSION_NUMBER,
                  [str(i) for i in device.containsEsx.version],
                  comparator=upgradePathComparator,
                  errorMsg="Upgrading from %s to %s is not supported." %
                            (device.containsEsx.getPrettyString(),
                             PRODUCT_SHORT_STRING),
                  mismatchCode=Result.ERROR)

#------------------------------------------------------------------------------
def checkHardwareVirtualization():
    '''Check that the system has Hardware Virtualization enabled
    '''
    hv = vmkctl.HardwareInfoImpl().GetCpuInfo()
    if hasattr(hv, 'get'):
       hv = hv.get()
    found = hv.GetHVSupport()

    return Result("HARDWARE_VIRTUALIZATION", [found], [HV_ENABLED],
                  errorMsg=("Hardware Virtualization is not a feature of"
                            " the CPU, or is not enabled in the BIOS"),
                  mismatchCode=Result.WARNING)

#------------------------------------------------------------------------------
def checkLAHFSAHF64bitFeatures():
    '''Check that the system is 64-bit with support for LAHF/SAHF in longmode
    '''

    found = _parseLAHFSAHF64bitFeatures()

    return Result("64BIT_LONGMODESTATUS", [found], [1],
                  errorMsg=("ESXi requires a 64-bit CPU with support for"
                            " LAHF/SAHF in long mode."),
                  mismatchCode=Result.ERROR)

#------------------------------------------------------------------------------
def checkNXbitCpuFeature():
    '''Check that the system has the NX bit enabled
    '''

    found = _parseNXbitCpuFeature()

    return Result("NXBIT_ENABLED", [found], [1],
                  errorMsg=("ESXi requires a CPU with NX/XD supported and"
                            " enabled."),
                  mismatchCode=Result.ERROR)

#------------------------------------------------------------------------------
def checkCpuSupported():
    '''Check if the host CPU is supported.

    For unsupported CPU models:
    Put an error message to inform the user the CPU is not supported in this
    release and stops install/upgrade.

    For CPU models to be deprecated:
    Put a warning message to inform the user the CPU will not be supported
    in future ESXi release and continues install/upgrade.

    Please refer to PR 1806085 for background
    '''

    cpu = vmkctl.CpuInfoImpl().GetCpus()[0]
    if hasattr(cpu, 'get'):
        cpu = cpu.get()

    vendor = cpu.GetVendorName()
    family = cpu.GetFamily()
    model =  cpu.GetModel()

    found = False
    errorMsg = ''
    mismatchCode = Result.SUCCESS

    CPU_ERROR = ("The CPU in this host is not supported by ESXi "
                 "6.7.0. Please refer to the VMware "
                 "Compatibility Guide (VCG) for the list of supported CPUs.")
    CPU_WARNING = ("The CPU in this host may not be supported in future "
                   "ESXi releases. Please plan accordingly.")


    # When NewCPUDeprecation is not set, use 6.5 spec to check support
    try:
        import featureState
        featureState.init()
        useNewSpec = featureState.NewCPUDeprecation
    except:
        # New deprecation spec is fully activated, we will enforce it on
        # previous releases
        useNewSpec = True
    if not useNewSpec:
        # Previous deprecation spec is only used with ISO install or B2B
        # VUM upgrade from 6.6.x, with NewCPUDeprecation feature off
        log.info('NewCPUDeprecation feature switch is not enabled, checking '
                 'host CPU against 6.5 deprecation list.')
        if (vendor, family) in [("AuthenticAMD", 0x0f), ("GenuineIntel", 0x0f)]\
            or (vendor, family) == ("GenuineIntel", 0x06) and model < 0x17:
            errorMsg=("The CPU in this host is not supported by ESXi 6.5."
                      "Please refer to the VMware Compatibility Guide (VCG) "
                      "for the list of supported CPUs.")
            mismatchCode=Result.ERROR

        # For GeniuneIntel case, we generate warnings on:"Penryn, Dunnington,
        # NHM-EP, Lynnfield, Clarksdale, WSM-EP, NHM-EX", but not "WSM-EX, SNB"

        elif (vendor, family) == ("GenuineIntel", 0x06) and model < 0x2f and \
            model not in [0x2a, 0x2d] or vendor == "AuthenticAMD" and \
            family < 0x15:

            # For VUM upgrade case, as long as the current host CPU is supported
            # it will pass without user intervention.

            found = True if vumEnvironment else False
            errorMsg=("The CPU in this host may not be supported in future ESXi"
                      " releases. Please plan accordingly.")
            mismatchCode=Result.WARNING

        return Result('CPU_SUPPORT', [found], [True], errorMsg=errorMsg,
                      mismatchCode=mismatchCode)

    log.info('NewCPUDeprecation feature switch is enabled, checking '
             'host CPU against 6.7.0 deprecation list.')


    if vendor == "GenuineIntel":
        if family == 0x06 and model in [0x2a, 0x2c, 0x2f]:
            # Warn for SNB-DT(2A), WSM-EX(2F) and WSM-EP(2C), not SNB-EP(2D)

            # Note: technically ESXi release notes and VCG will list WSM-EP(2C)
            # as not supported, but internally WSM-EP is still supported,
            # so we just warn for WSM-EP.

            # VUM upgrade check will pass as long as the current host CPU is
            # still supported
            found = True if vumEnvironment else False

            errorMsg = CPU_WARNING
            mismatchCode=Result.WARNING
        elif family == 0x0f or (family == 0x06 and model <= 0x36 and model != 0x2d):
            # Block install on Family F and all other remaining Family 6
            # processors with model <= 0x36 except SNB-EP(2D)
            errorMsg = CPU_ERROR
            mismatchCode=Result.ERROR
    elif vendor == "AuthenticAMD" and family < 0x15:
        # Block everything before Bulldozer (Family 0x15)
        errorMsg = CPU_ERROR
        mismatchCode=Result.ERROR

    return Result('CPU_SUPPORT', [found], [True], errorMsg=errorMsg,
                   mismatchCode=mismatchCode)

#------------------------------------------------------------------------------
def checkCpuCores():
    '''Check that there are atleast 2 cpu cores
    '''
    found = vmkctl.CpuInfoImpl().GetNumCpuCores()

    CPU_MIN_CORE = 2
    return Result("CPU_CORES", [found], [CPU_MIN_CORE],
                  comparator=operator.ge,
                  errorMsg="The host has less than %s CPU cores" % CPU_MIN_CORE,
                  mismatchCode = Result.ERROR)


#------------------------------------------------------------------------------
def checkInitializable():
    name = 'PRECHECK_INITIALIZE'
    sanityChecks = ['version']
    passedSanityChecks = []
    try:
        product, version = _parseVmwareVersion()
    except Exception:
        return Result(name, passedSanityChecks, sanityChecks)
    passedSanityChecks.append('version')

    sanityChecks.append('esx.conf')
    if os.path.exists(ESX_CONF_PATH):
        passedSanityChecks.append('esx.conf')

    # ... I'm sure more sanity tests will be added here ...

    return Result(name, passedSanityChecks, sanityChecks)

#------------------------------------------------------------------------------
def checkAvailableSpaceForISO():
    '''Check for space for the ESXi ISO contents in a resource pool
    '''
    expected = metadata.sizeOfISO
    if not systemProbe.bootDiskPath:
        return Result("SPACE_AVAIL_ISO", [0], [expected],
                      comparator=operator.ge)
    assert systemProbe.product == 'esxi'
    # First, we need to make sure the ISO can be copied to the ramdisk
    if allocateRamDisk(RAMDISK_NAME, expected):
        found = expected
    else:
        found = 0
    # Second, we need to make sure the VIBs can be copied into the bootbank
    return Result("SPACE_AVAIL_ISO", [found], [expected],
                  comparator=operator.ge)

#------------------------------------------------------------------------------
def checkSaneEsxConf():
    '''Check that esx.conf is nonempty.
    '''
    expected = True
    success = (systemProbe.esxconfNonempty
               and systemProbe.getSystemUUID() != None)
    return Result("SANE_ESX_CONF", [success], [expected])

#------------------------------------------------------------------------------
def checkVMFSVersion():
    '''VMFS-3 volumes are deprecated.
       Warn the user if VMFS-3 is found.
    '''
    found = False
    expected = False
    cmd = '/sbin/localcli --formatter=json storage filesystem list'
    log.debug('Running %s' % cmd)
    status, output = getstatusoutput(cmd)
    if status != 0:
        log.error("Skipping VMFS version check. Couldn't get filesystem list: (%s) %s" % (str(status), output))
    else:
        try:
            output = json.loads(output)
        except ValueError as e:
            log.error("Skipping VMFS version check. Couldn't parse output of %s: %s" % (cmd, e))
            output = []
        for info in output:
            if info['Type'] == 'VMFS-3':
                found = True
                break
    return Result("VMFS_VERSION", [found], [expected],
                  errorMsg="One or more VMFS-3 volumes have been detected."
                           " They are going to be automatically upgraded to VMFS-5.",
                  mismatchCode = Result.WARNING)

#------------------------------------------------------------------------------
def checkUnsupportedDevices():
    '''Check for any unsupported hardware via a PCI blacklist'''
    found = []

    for device in systemProbe.pciinfo:
        if device in UNSUPPORTED_PCI_DEVICE_LIST:
            # The check before we append is a bit relaxed, so let's refine it a
            # bit.
            if not device.subsystem:
                # If the device we've probed out doesn't have a defined
                # subsystem, check if that also matches to an unsupported PCI ID
                # with an undefined subsystem.  For devices with an undefined
                # subsystem, there has to be an exact match in the unsupported
                # list.
                unsprtMatch = [ pci.subsystem for pci in
                        UNSUPPORTED_PCI_DEVICE_LIST if device == pci ]

                # Since the host's device has 'None' as its subsystem, it could
                # match anything in the unsupported list.  Make sure we find a
                # 'None' in that list.
                if None not in unsprtMatch:
                    continue

            found.append(device)

    return Result("UNSUPPORTED_DEVICES", found, [],
                  mismatchCode=Result.WARNING,
                  errorMsg="Unsupported devices are found")

def checkHostHw():

    if not vumEnvironment:
        # Get the currently booted profile.
        import vmware.esximage.Transaction
        imgProf = vmware.esximage.Transaction.Transaction().GetProfile()
    else:
        # Otherwise, get the one from metadata.zip
        imgProf = metadata.profile

    hwProblems = []
    for imgHw in imgProf.GetHwPlatforms():
        for hw in systemProbe.hostHws:
            prob = imgHw.MatchProblem(hw)
            if prob is None:
                # We have a match, forget any other mismatches
                hwProblems = []
                break
            hwProblems.append(prob)
        else:
            continue
        break # break out of the outer loop

    return Result("VALIDATE_HOST_HW", hwProblems, [],
                  mismatchCode=Result.ERROR,
                  errorMsg="VIBs without matching host hardware found")

_hostvibs = None
def _getHostVibs():
    from vmware.esximage import VibCollection, Database

    global _hostvibs

    if _hostvibs is not None:
        return _hostvibs

    if vumEnvironment:
        esx5vibs = "/var/db/esximg/vibs"
    else:
        # for weasel. systemProbe.vibCheckPath is /altbootbank
        log.debug('weasel environment')
        esx5vibs = os.path.join(systemProbe.vibCheckPath,
                                   "imgdb.tgz")

    _hostvibs = VibCollection.VibCollection()

    log.debug("sysprobe's path is " + systemProbe.vibCheckPath)
    log.debug('for 5x, vibs.xml path will be ' + os.path.normpath(esx5vibs))

    if vumEnvironment and os.path.isdir(esx5vibs):
        log.debug('5x vibs.xml path exists')
        _hostvibs.FromDirectory(esx5vibs, ignoreinvalidfiles=True)
        for vib in _hostvibs.values():
            vib.thirdparty = False
            log.debug('VIB name: %s vers: %s ThirdParty: %s'
                     %(vib.name, vib.version, vib.thirdparty))
    elif not vumEnvironment and os.path.isfile(esx5vibs):
        log.debug('5.x imgdb.tgz exists')
        hostdb = Database.TarDatabase(dbpath=esx5vibs, dbcreate=False)
        hostdb.Load()
        _hostvibs += hostdb.vibs
        # set thirdparty to False so we dont have to check for this attr
        for vib in _hostvibs.values():
            vib.thirdparty = False
        log.debug('Loaded %d host vibs' % len(_hostvibs))
    return _hostvibs

_imageprofile = None

def _setImageProfile(version=None):
    ''' Get the image profile of the host after intall/upgrade operation.
        - For fresh install, version=None.
        - Only support upgrade from 5.5 and up. If the host version is
          not None, merge VIBs from host into Image Profile in the metadata.
    '''
    from vmware.esximage import Database, VibCollection

    global _imageprofile

    oldvibs = VibCollection.VibCollection()

    if version:
        oldvibs = _getHostVibs()

    # get the metadata profile and vibs
    _imageprofile = metadata.profile
    for vib in metadata.vibs:
        _imageprofile.vibs.AddVib(vib)

    (up, down, new, existing) = _imageprofile.ScanVibs(oldvibs)

    # merge vibs
    for vib in (new | up):
        _imageprofile.AddVib(oldvibs[vib], True)

def checkVibConflicts():
    ''' This check should run in weasel as well as vum-environment.
        - Validate the profile.
        - Report any conflicting Vibs.
    '''
    from vmware.esximage.ImageProfile import ConflictingVIB
    confvibs = []

    log.debug("Running vib conflicts check.")

    problems = _imageprofile.Validate(noacceptance=True, noextrules=True)

    # Perform the vib confliction check.
    for prob in problems:
        # Profile.Validate should return a type->problem map
        # for now we'll use isinstance.
        if isinstance(prob, ConflictingVIB):
            log.debug("Conflicts: %s" % str(prob))
            confvibs.append(', '.join(prob.vibids))

    rc = Result("CONFLICTING_VIBS", confvibs, [], mismatchCode=Result.ERROR,
         errorMsg="Vibs on the host are conflicting with vibs in metadata.  "
                  "Remove the conflicting vibs or use Image Builder "
                  "to create a custom ISO providing newer versions of the "
                  "conflicting vibs. ")

    if not confvibs:
        rc.code = Result.SUCCESS

    return rc

def checkVibDependencies():
    ''' This check should run in weasel as well as vum-environment.
        - Validate the profile.
        - Report any missing dependency Vibs.
    '''
    from vmware.esximage.ImageProfile import MissingDependency
    depvibs = []

    log.debug("Running vib dependency check.")

    problems = _imageprofile.Validate(noacceptance=True, noextrules=True)

    # Perform the vib dependency check
    for prob in problems:
        # Profile.Validate should return a type->problem map
        # for now we'll use isinstance.
        if isinstance(prob, MissingDependency):
            log.debug("Dependency check: %s" % str(prob))
            depvibs.append(prob.vibid)

    rc = Result("MISSING_DEPENDENCY_VIBS", depvibs, [], mismatchCode=Result.ERROR,
         errorMsg="These vibs on the host are missing dependency if continue to upgrade. "
                  "Remove these vibs before upgrade or use Image Builder  "
                  "to resolve this missing dependency issue.")

    if not depvibs:
        rc.code = Result.SUCCESS

    return rc

def checkImageProfileSize():
    ''' Calculate the installation size of the imageprofile.
        This needs to be consistent with CheckInstallationSize() in
        bora/apps/pythonroot/vmware/esximage/Installer/BootBankInstaller.py.
    '''
    from vmware.esximage.Installer.BootBankInstaller import BootBankInstaller

    totalsize = 0
    for vibid in _imageprofile.vibIDs:
        vib = _imageprofile.vibs[vibid]
        if vib.vibtype in BootBankInstaller.SUPPORTED_VIBS:
            for payload in vib.payloads:
                if payload.payloadtype in BootBankInstaller.SUPPORTED_PAYLOADS:
                   totalsize += payload.size

    totalsize_MB = totalsize // (1024*1024) + 1
    maximum_MB = 250 - BootBankInstaller.BOOTBANK_PADDING_MB - 1
    log.info("Image size: %d MB, Maximum size: %d MB"
             % (totalsize_MB, maximum_MB))
    if totalsize_MB > maximum_MB:
        rc = Result("IMAGEPROFILE_SIZE", [totalsize_MB], [maximum_MB],
                     mismatchCode=Result.ERROR,
                     errorMsg="The image profile size is too large" )

        log.error('The target image profile requires %d MB space, however '
                  'the maximum supported size is %d MB.' % (totalsize_MB,
                  maximum_MB))
    else:
        rc = Result("IMAGEPROFILE_SIZE", [], [])
    return rc

def checkPackageCompliance():
    # This is used by VUM to validate that the expected VIBs have been
    # installed. Note that we only check the list of VIB IDs, not any other
    # attributes (name, acceptance level, etc.) of the image profile.

    expected = set([vib.id for vib in metadata.vibs])
    newvibnames = set([vib.name for vib in metadata.vibs])
    issuevib = []

    try:
        from vmware.esximage import Database, Scan, VibCollection
        bootbankdb = Database.TarDatabase("/bootbank/imgdb.tgz", False)
        bootbankdb.Load()
        try:
            lockerdb = Database.Database("/locker/packages/var/db/locker",
                                         False)
            lockerdb.Load()
            hostvibs = bootbankdb.vibs + lockerdb.vibs
        except Exception as e:
            log.error('Failed to load locker vib database: %s' % e)
            hostvibs = bootbankdb.vibs
        hostvibids = set([vib.id for vib in hostvibs.values()])
        hostvibnames = set([vib.name for vib in hostvibs.values()])

        # Log all vibs ids and unique VIBs from host and baseline
        log.info('VIBs from host: %s' % str(sorted(hostvibids)))
        log.info('VIBs from baseline: %s' % str(sorted(expected)))
        olddelta = sorted([name for name in hostvibnames if not name in
                           newvibnames])
        log.info('Unique VIBs from host: %s' % str(olddelta))
        newdelta = sorted([name for name in newvibnames if not name in
                           hostvibnames])
        log.info('Unique VIBs from baseline: %s' % str(newdelta))

        # Now scan to check versioning/replaces.
        allvibs = VibCollection.VibCollection()
        for vib in hostvibs.values():
            allvibs.AddVib(vib)
        for vib in metadata.vibs:
            allvibs.AddVib(vib)
        scanner = Scan.VibScanner()
        scanner.Scan(allvibs)
        # Each VIB in expected must either be on the host or be replaced by
        # something on the host.
        for vibid in expected:
            vibsr = scanner.results[vibid]
            if vibid not in hostvibids and not vibsr.replacedBy & hostvibids:
                issuevib.append(vibid)
    except Exception as e:
        msg = "Couldn't load esximage database to scan package compliance: " \
              "%s. Host may be of incorrect version." % e
        log.error(msg)
        # Scan did not succeed, make the error as an issue so the host will
        # not be marked compliant incorrectly.
        issuevib.append(msg)

    # If found >= expected is true, then everything in expected is also in
    # found. (If there are extra things in found, we are still compliant.)
    result = Result("PACKAGE_COMPLIANCE", issuevib, [],
                    mismatchCode=Result.ERROR)
    return result

def checkUpdatesPending():
    # Make sure that there are not Visor updates pending a reboot.
    expected = False
    found = False

    if os.path.exists("/altbootbank/boot.cfg"):
        f = open("/altbootbank/boot.cfg")
        for line in f:
            try:
                name, value = [word.strip() for word in line.split("=")]
                value = int(value)
                if name == "bootstate" and value == 1:
                    found = bool(int(value))
                    break
            except:
                continue
        f.close()

    return Result("UPDATE_PENDING", [found], [expected])

def nativeDriverPresentInImage(device):
    """ Determines if a native driver is available for the
        given device in the new image
    """
    assert(vumEnvironment)
    return bool(device and device in metadata.nativeDevices)

def getPackedIP(ipStr):
    """ If ipStr is a valid IP, returns packed string representation
        of the IP. Raises socket.error otherwise.
    """
    import socket
    if ':' in ipStr:
        af = socket.AF_INET6
    else:
        af = socket.AF_INET
    return socket.inet_pton(af, ipStr)

def getUplinks(xmlTree, portGroupName):
    """ Returns the list of conifgured uplinks for the Management
        Network portgroup.
    """
    pgPath = '/'.join(['virtual-switch-info', 'virtual-switches',
                       'virtual-switch', 'port-groups',
                       'port-group'])
    portGroups = xmlTree.findall(pgPath)
    for portGroup in portGroups:
        for value in portGroup.findall('value'):
            if (value.get('name') == 'name' and
                value.text == portGroupName):
                break
        else:
            continue
        values = portGroup.findall('configured-teaming-policy/value')
        for value in values:
            if value.get('name') == 'uplink-order':
                return [nic.strip() for nic in value.text.split(',')]

    # This will most likely not happen
    log.error("Failed to determine the uplinks for port group %s." %
              portGroupName)
    return [None]

def vmknicHasIpAddress(vmknic, ipAddress):
    """ Checks whether a vmknic has the give ip.
    """
    ipPaths = ['actual-ip-settings/ipv4-settings/value',
               'actual-ip-settings/ipv6-settings/value',
               'configured-ip-settings/ipv4-settings/value',
               'configured-ip-settings/ipv6-settings/value']
    values = []
    for p in ipPaths:
        values.extend(vmknic.findall(p))

    for value in values:
        valueName = value.get('name')
        if (valueName in ('ipv4-address', 'ipv6-address')):
            try:
                if valueName == 'ipv6-address':
                    # Get rid of the trailing netmask from v6 addresses
                    foundIP = value.text.split('/')[0]
                else:
                    foundIP = value.text
                foundIP = getPackedIP(foundIP)
                if foundIP == ipAddress:
                    return True
            except socket.error as e:
                log.warn("Failed to get packed string for ip %s: %s" %
                         (value.text, e))

    return False

def getVmknicWithIP(xmlTree, ipAddress):
    """ Finds the vmknic that has the given ip.
    """
    vmknicName = vmknicMac = vmknicPg = None
    pgPath = '/'.join(['vmkernel-nic-info', 'kernel-nics',
                       'vmkernel-nic'])
    vmknics = xmlTree.findall(pgPath)
    for vmknic in vmknics:
        if vmknicHasIpAddress(vmknic, ipAddress):
            for value in vmknic.findall('value'):
                if value.get('name') == 'interface':
                    vmknicName = value.text
                elif value.get('name') == 'port-group':
                    vmknicPg = value.text
                elif value.get('name') == 'mac-address':
                    vmknicMac = value.text
    return vmknicName, vmknicPg, vmknicMac

def getBootNic(ipAddress):
    """ Figure out the vmnic that has the given ip.
    """
    xmlTree = etree.fromstring(systemProbe.esxnwinfo)
    vmknic, pgName, macAddr = getVmknicWithIP(xmlTree, ipAddress)
    if pgName is None:
        log.error("Could not find a nic configured with the given "
                  "ip address %s." % options.ip)
        return None
    else:
        return getUplinks(xmlTree, pgName)[0]

def checkBootNicIsNative():
    """ Checks to see that a native NIC is available for the
        management traffic.
    """
    expected = True
    found = True
    if vumEnvironment and metadata.novaImage:
        if not options.ip:
            log.error("Upgrading to native only image requires "
                      "the boot ip to be passed in.")
            found = False
        else:
            try:
                vmnic = getBootNic(getPackedIP(options.ip))
            except socket.error as e:
                log.error("Failed to determine the NIC with ip: %s." % e)
                found = False
            else:
                found = nativeDriverPresentInImage(vmnic)

    return Result("NATIVE_BOOT_NIC", [found], [expected],
             errorMsg="Boot NIC is either missing or has no "
                      "native driver available.")

def getDiskAdapterName(device):
    """ Get the adapter associated with the given disk device.
    """
    vmhba = None
    cmd = "localcli --formatter=json  storage core path list"
    log.debug('Running %s' % cmd)
    status, output = getstatusoutput(cmd)
    if status == 0:
        try:
            disks = json.loads(output)
        except ValueError as e:
            log.error("Failed to parse output of %s: %s" % (cmd, e))
        else:
            for disk in disks:
                if disk["Device"] == device:
                    vmhba = disk["Adapter"]
    if vmhba is None:
        log.error("Failed to determine vmhba for disk %s." % device)
    return vmhba

def checkBootbankDeviceIsNative():
    """ When installing/upgrading to a native only NOVA image,
        the bootbank storage device needs to be native.
    """
    expected = True
    found = True
    if vumEnvironment and metadata.novaImage:
        vmhba = getDiskAdapterName(systemProbe.bootDiskVMHBAName)
        found = nativeDriverPresentInImage(vmhba)

    return Result("NATIVE_BOOTBANK", [found], [expected],
                  errorMsg="Native drivers are missing for bootbank "
                           "storage device.")

def _getHostAcceptanceLevel():
    """Get acceptance level of the host"""
    from vmware.esximage import Vib
    from vmware.esximage.Utils.Misc import byteToStr
    CMD = '/sbin/esxcfg-advcfg -U host-acceptance-level -G'
    try:
        out = run(CMD)
    except Exception as e:
       log.error('Unable to get host acceptance level: %s' % str(e))
       return ''
    hostaccept = byteToStr(out).strip()
    if hostaccept in Vib.ArFileVib.ACCEPTANCE_LEVELS:
       return hostaccept
    else:
       log.error("Received unknown host acceptance level '%s'"
                 % (hostaccept))
       return ''

def checkHostAcceptance():
    """Check host acceptance level with incoming imageprofile"""
    from vmware.esximage import Vib
    from vmware.esximage.ImageProfile import AcceptanceChecker
    TRUST_ORDER = AcceptanceChecker.TRUST_ORDER
    hostAcceptance = _getHostAcceptanceLevel()
    # if the response is empty, we have an error
    if not hostAcceptance:
        return Result("HOST_ACCEPTANCE", [False], [True],
                      errorMsg="Failed to get valid host acceptance level.")
    hostAcceptanceValue = [v for k, v in TRUST_ORDER.items()
                           if k == hostAcceptance][0]
    targetAcceptance = metadata.profile.acceptancelevel
    targetAcceptanceValue = [v for k, v in TRUST_ORDER.items()
                             if k == targetAcceptance][0]
    log.info('Host acceptance level is %s, target acceptance level is %s'
               % (hostAcceptance, targetAcceptance))
    # acceptance level cannot go down during upgrade
    if hostAcceptanceValue > targetAcceptanceValue:
        err = 'Acceptance level of the host has to change from %s to %s ' \
              'to match with the new imageprofile and proceed with ' \
              'upgrade.' % (hostAcceptance, targetAcceptance)
        log.error(err)
        return Result('HOST_ACCEPTANCE', [False], [True], errorMsg=err)
    # new imageprofile has a higher level, current level will be retained
    elif hostAcceptanceValue < targetAcceptanceValue:
        # no need to stop the upgrade, only log an info
        log.info('Host acceptance level %s will be retained after '
                 'upgrade.' % hostAcceptance)
    return Result('HOST_ACCEPTANCE', [True], [True])

RESULT_XML = '''\
    <test>
      <name>%(name)s</name>
      <expected>
        %(expected)s
      </expected>
      <found>
        %(found)s
      </found>
      <result>%(code)s</result>
    </test>
'''

def _marshalResult(result):
    intermediate = {
        'name': result.name,
        'expected': '\n        '.join([('<value>%s</value>' % str(exp))
                                       for exp in result.expected]),
        'found': '\n        '.join([('<value>%s</value>' % str(fnd))
                                    for fnd in result.found]),
        'code': result.code,
        }

    return RESULT_XML % intermediate

def resultsToXML(results):
    return '\n'.join([_marshalResult(result) for result in results])

output_xml = '''\
<?xml version="1.0"?>
<precheck>
 <info>
%(info)s
 </info>
 <tests>
%(tests)s
 </tests>
</precheck>
'''

systemProbe = None
metadata = None
vumEnvironment = None

def init(product, version):
    global systemProbe, metadata

    if product == 'ESXi':
        systemProbe = SystemProbeESXi(version)
        metadata = IsoMetadata()
    else:
        raise Exception('product not recognized')


class StaticSystemProbe(SystemProbe):
        '''This is a SystemProbe object to be used by Weasel.  It does not
        dynamically populate any of its settings.
        '''
        def __init__(self, product=None, bootDiskPath=None):

            import vmware.esximage.HostImage

            self.product = product
            self.version = [5, 0, 0, 'assumed']
            self.pciinfo = []
            self.bootDiskPath = bootDiskPath
            self.vibCheckPath = '/tmp/vibcheck'
            self.weaselMode = True
            self._systemUUID = None
            hi = vmware.esximage.HostImage.HostImage()
            self.hostHws = hi.GetHostHwPlatform()

def upgradeAction():
    '''This function is called during the Weasel process in the install
    environment.  It runs through the checks that would make sense there.
    returns None if everything went smoothly, or a string containing all
    the errors if not.
    '''
    global systemProbe, metadata, log
    # These modules are expected to be unavailable when upgrade_precheck
    # is run from the command line, so import them only when inside the
    # upgradeAction function - it is invoked by Weasel code, so Weasel
    # modules will be available.

    from weasel import userchoices
    from weasel import devices
    from weasel.exception import HandledError
    from weasel.log import log as weaselLog
    from weasel.log import LOGLEVEL_UI_ALERT
    from weasel import cache
    from weasel.util import isNOVA

    global log
    log = weaselLog
    log.info('Starting the precheck tests')

    deviceName = userchoices.getEsxPhysicalDevice()
    if not deviceName:
        raise HandledError('No disk chosen. Precheck can not be run')
    ds = devices.DiskSet()
    device = ds[deviceName]

    if device.containsEsx.version < (6, 0,):
        raise HandledError('ESXi 6.0 (or greater) not found on device (%s)'
                           % deviceName)

    if device.containsEsx.esxi:
        product = 'ESXi'
        systemProbe = StaticSystemProbe(product, device.consoleDevicePath)
        deviceName = userchoices.getEsxPhysicalDevice()
        c = cache.Cache(deviceName)
        systemProbe.vibCheckPath = c.altbootbankPath
    else:
        raise HandledError('Unknown ESXi variant (%s)' % device.containsEsx)

    esxiProbe = SystemProbeESXi('5.0.0')
    systemProbe.pciinfo = esxiProbe.pciinfo

    try:
        metadata = IsoMetadata()
    except Exception as ex:
        msg = 'Error initializing metadata. (%s)' % str(ex)
        log.error(msg)
        log.log(LOGLEVEL_UI_ALERT, msg)
        return

    _setImageProfile(device.containsEsx.version)

    log.debug('running prereqs check')
    tests = [
        checkUpgradePath,
        checkMemorySize,
        checkCpuSupported,
        checkCpuCores,
        checkHostHw,
        checkUnsupportedDevices,
        checkVMFSVersion,
        checkImageProfileSize,
        ]

    if isNOVA():
        tests.insert(0, checkNICsDetected)

    # only check for vib conflicts if force migrate has not been selected
    if not userchoices.getForceMigrate():
        tests.append(checkVibConflicts)
        tests.append(checkVibDependencies)

    results = [testFn() for testFn in tests]
    return humanReadableResultBlurbs(results)

def installAction():
    '''This function is called during the Weasel process in the install
    environment.  It runs through the checks that would make sense there.
    returns None if everything went smoothly, or a string containing all
    the errors if not.
    '''
    global systemProbe, metadata, log
    # These modules are expected to be unavailable when upgrade_precheck
    # is run from the command line, so import them only when inside the
    # installAction function - it is invoked by Weasel code, so Weasel
    # modules will be available.
    from weasel import userchoices
    from weasel.util import isNOVA
    from weasel.log import log as weaselLog
    from weasel.log import LOGLEVEL_UI_ALERT

    global log
    log = weaselLog
    log.info('Starting the precheck tests')

    product, version = _parseVmwareVersion()
    systemProbe = StaticSystemProbe(product)

    esxiProbe = SystemProbeESXi('5.0.0')
    systemProbe.pciinfo = esxiProbe.pciinfo

    try:
        metadata = IsoMetadata()
    except Exception as ex:
        msg = 'Error initializing metadata. (%s)' % str(ex)
        log.error(msg)
        log.log(LOGLEVEL_UI_ALERT, msg)
        return

    _setImageProfile()

    tests = [
         checkMemorySize,
         checkCpuSupported,
         checkHardwareVirtualization,
         checkCpuCores,
         checkLAHFSAHF64bitFeatures,
         checkNXbitCpuFeature,
         checkHostHw,
         checkUnsupportedDevices,
         checkVMFSVersion,
         checkImageProfileSize,
        ]

    if isNOVA():
        tests.insert(0, checkNICsDetected)

    results = [testFn() for testFn in tests]
    return humanReadableResultBlurbs(results)

def humanReadableResultBlurbs(results):

    warningFailures = ''
    errorFailures = ''
    errorNewLineNeeded = False
    warningNewLineNeeded = False

    for result in results:
        if not result:
            if result.code == Result.ERROR:
                if errorNewLineNeeded:
                    errorFailures += '\n\n'
                errorFailures += str(result)
                errorNewLineNeeded = True
            else:
                if warningNewLineNeeded:
                    warningFailures += '\n\n'
                warningFailures += str(result)
                warningNewLineNeeded = True

    if errorFailures != '':
        log.error('Precheck Error(s). \n %s' % errorFailures)
    if warningFailures != '':
        log.warn('Precheck Warnings(s). \n %s' % warningFailures)
    return errorFailures, warningFailures

def main(argv):

    global options
    parser = optparse.OptionParser()
    parser.add_option('--ip', dest='ip', default='',
                      help=('The IP address that the host should bring up'
                            ' after rebooting.'))

    options, args = parser.parse_args()

    global vumEnvironment
    vumEnvironment = True

    results = [checkInitializable()]

    if not results[0]:
        testsSection = resultsToXML(results)
        print(output_xml % {
                            'info': '',
                            'tests': testsSection,
                           })
        return 0

    product, version = _parseVmwareVersion()
    init(product, version)
    _setImageProfile(version)


    tests = [
        checkAvailableSpaceForISO,
        checkMemorySize,
        checkCpuSupported,
        checkCpuCores,
        checkSaneEsxConf,
        checkUnsupportedDevices,
        checkPackageCompliance,
        checkHostHw,
        checkUpdatesPending,
        checkVMFSVersion,
        checkBootNicIsNative,
        checkBootbankDeviceIsNative,
        checkVibConflicts,
        checkVibDependencies,
        checkImageProfileSize,
        checkHostAcceptance,
        ]

    results += [testFn() for testFn in tests]

    anyFailures = [result for result in results if not result]
    if anyFailures:
        deallocateRamDisk(RAMDISK_NAME)

    testsSection = resultsToXML(results)

    print(output_xml % {
                        'info': '',
                        'tests': testsSection,
                        })

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
    #import doctest
    #doctest.testmod()
