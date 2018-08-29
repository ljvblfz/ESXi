from pprint import pformat

'''
userchoices abstracts all the choices a user can make during the installation
process.  It is accessed as a singleton from gui.py and from each of the
screens.  It provides getter and setter methods for the various choices
available to a user.

This module's API is basically a collection of get* and set* functions.

The get* functions return _copies_ of the data, to maintain encapsulation.

Usage:
from weasel import userchoices
userchoices.setMyProperty( foo='bar' )
...
myProp = userchoices.getMyProperty()
if not myProp:
   # handle unset property condition
else:
   # do something with myProp['foo']


IMPORTANT: this must always be imported in one of the following 2 ways:

from weasel import userchoices
import weasel; weasel.userchoices

If a module in the weasel package uses the INCORRECT syntax

import userchoices #WRONG! DON'T DO THIS!

a new module object will be created.  Since the whole point of userchoices
is to be a singleton, this will cause strange, head-scratch inducing effects.
You can easily convince yourself of this
import userchoices; import weasel
print userchoices == weasel.userchoices
'''

# ----------------------------------------------------------------------------
# Section 1: Simple boolean toggles
# ----------------------------------------------------------------------------

__toggles = {
    'paranoid': False,
    'debug': False,
    'upgrade': False,
    'reboot': False,
    'noEject': False,
    'acceptEULA': True,
    'dryrun': False,
    'showInstallMethod': False,
    'driversLoaded': False,
    'addVmPortGroup': True,
    'install': False,
    'installorupgrade': False,
    'preservevmfs': False,
    'preservevsan': True,
    'partitionEmbed': False,
    'createVmfsOnDisk': True, # Defaults to True, only set False if the user wants it so
    'ignorePrereqWarnings': False,
    'ignorePrereqErrors': False,
    'forceMigrate': False,
    'vumEnvironment': False,
    'ignoressd': False,
    'largerCoreDumpPart': False,
}

def setParanoid(paranoid):
    global __toggles
    __toggles['paranoid'] = paranoid

def getParanoid():
    return __toggles['paranoid']

def setDebug(debug):
    global __toggles
    __toggles['debug'] = debug

def getDebug():
    return __toggles['debug']

def setUpgrade(upgrade):
    global __toggles
    __toggles['upgrade'] = upgrade

def getUpgrade():
    return __toggles['upgrade']

def setReboot(reboot):
    global __toggles
    __toggles['reboot'] = reboot

def getReboot():
    return __toggles['reboot']

def setNoEject(noEject):
    global __toggles
    __toggles['noEject'] = noEject

def getNoEject():
    return __toggles['noEject']

def setAcceptEULA(acceptEULA):
    global __toggles
    __toggles['acceptEULA'] = acceptEULA

def getAcceptEULA():
    return __toggles['acceptEULA']

def setDryrun(dryrun):
    global __toggles
    __toggles['dryrun'] = dryrun

def getDryrun():
    return __toggles['dryrun']

def setAddVmPortGroup(addVmPortGroup):
    global __toggles
    __toggles['addVmPortGroup'] = addVmPortGroup

def getAddVmPortGroup():
    return __toggles['addVmPortGroup']

def setInstall(install):
    global __toggles
    __toggles['install'] = install

def getInstall():
    return __toggles['install']

def setInstallOrUpgrade(installorupgrade):
    global __toggles
    __toggles['installorupgrade'] = installorupgrade

def getInstallOrUpgrade():
    return __toggles['installorupgrade']

def setPreserveVmfs(preserve):
    global __toggles
    __toggles['preservevmfs'] = preserve

def getPreserveVmfs():
    return __toggles['preservevmfs']

def setPreserveVsan(preserveVsan):
    global __toggles
    __toggles['preservevsan'] = preserveVsan

def getPreserveVsan():
    return __toggles['preservevsan']

def setPartitionEmbed(partitionEmbed):
    global __toggles
    __toggles['partitionEmbed'] = partitionEmbed

def getPartitionEmbed():
    return __toggles['partitionEmbed']

def setCreateVmfsOnDisk(create):
    global __toggles
    __toggles['createVmfsOnDisk'] = create

def getCreateVmfsOnDisk():
    return __toggles['createVmfsOnDisk']

def setIgnorePrereqWarnings(ignorePrereqWarnings):
    global __toggles
    __toggles['ignorePrereqWarnings'] = ignorePrereqWarnings

def getIgnorePrereqWarnings():
    return __toggles['ignorePrereqWarnings']

def setIgnorePrereqErrors(ignorePrereqErrors):
    global __toggles
    __toggles['ignorePrereqErrors'] = ignorePrereqErrors

def getIgnorePrereqErrors():
    return __toggles['ignorePrereqErrors']

def setForceMigrate(forceMigrate):
    global __toggles
    __toggles['forceMigrate'] = forceMigrate

def getForceMigrate():
    return __toggles['forceMigrate']

def setVumEnvironment(vumEnvironment):
    global __toggles
    __toggles['vumEnvironment'] = vumEnvironment

def getVumEnvironment():
    return __toggles['vumEnvironment']

def setIgnoreSSD(ignoressd):
    global __toggles
    __toggles['ignoressd'] = ignoressd

def getIgnoreSSD():
    return __toggles['ignoressd']

def setLargerCoreDumpPart(largerPart):
    global __toggles
    __toggles['largerCoreDumpPart'] = largerPart

def getLargerCoreDumpPart():
    return __toggles['largerCoreDumpPart']

# ----------------------------------------------------------------------------
# Section 2: Data stored as dicts
# ----------------------------------------------------------------------------

__runMode = {}

RUNMODE_TEXT = 'text'
RUNMODE_SCRIPTED = 'scripted'
#RUNMODE_STOAT = 'stoat'
RUNMODE_DEBUG = 'debug'

def setRunMode(runMode):
    global __runMode
    __runMode = locals()

def getRunMode():
    return __runMode.copy()

__keyboard = {}

def setKeyboard(name):
    global __keyboard
    # NOTE using locals() is hackish, but saves coding.
    # Don't add anything to local scope in this function, either
    # before or after the assignment, otherwise it will screw up
    # the data in the __foo module-level variable
    __keyboard = locals()

def getKeyboard():
    return __keyboard.copy()

def isCombinedBootAndRootForUpgrade():
    return getUpgrade()# and __bootUUID and (__bootUUID == __rootUUID)

__clearPartitions = {}

CLEAR_PARTS_ALL = 'all'
CLEAR_PARTS_NOVMFS = 'novmfs'

def setClearPartitions( drives=[], whichParts=CLEAR_PARTS_ALL ):
    global __clearPartitions
    __clearPartitions = locals()

def getClearPartitions():
    return __clearPartitions.copy()


# Map of drive names to a set of strings that described how the drive is being
# used by the installer.  For example, addDriveUse('foo', 'kickstart') means
# that the drive contains the kickstart file.
__driveUses = {}

def addDriveUse(driveName, useName):
    useSet = __driveUses.get(driveName, set())
    useSet.add(useName)
    __driveUses[driveName] = useSet

def delDriveUse(driveName, useName):
    if driveName in __driveUses and useName in __driveUses[driveName]:
        __driveUses[driveName].remove(useName)
        if not __driveUses[driveName]:
            del __driveUses[driveName]

def getDrivesInUse():
    return list(__driveUses.keys())


__mediaProxy = {}

def setMediaProxy(server, port, username='', password=''):
    global __mediaProxy
    __mediaProxy = locals()

def getMediaProxy():
    return __mediaProxy.copy()

def unsetMediaProxy():
    global __mediaProxy
    __mediaProxy = {}


__debugPatchLocation = {}

def setDebugPatchLocation(debugPatchLocation):
    global __debugPatchLocation
    __debugPatchLocation = locals()

def getDebugPatchLocation():
    return __debugPatchLocation.copy()


__rootPassword = {}

ROOTPASSWORD_TYPE_CRYPT = 'crypt'
ROOTPASSWORD_TYPE_MD5 = 'md5'
ROOTPASSWORD_TYPE_SHA512 = 'sha512'

def setRootPassword(password, passwordType, crypted=True):
    global __rootPassword
    __rootPassword = locals()

def getRootPassword():
    return __rootPassword.copy()

def clearRootPassword():
    global __rootPassword
    __rootPassword = {}


__timedate = {}

def setTimedate(ntpServer=None):
    # to set the time & date, just change the os date so that it keeps
    # ticking forward.  If the time the user entered was kept in the
    # userchoices object, it would be frozen, and there would be a
    # significant delta between when they entered it and when applychoices
    # got called
    global __timedate
    __timedate = locals()

def getTimedate():
    return __timedate.copy()


__vmLicense = {}

VM_LICENSE_MODE_SERVER = 'server'
VM_LICENSE_MODE_FILE = 'file'

def setVMLicense(mode, features, edition, server=None):
    global __vmLicense
    __vmLicense = locals()

def getVMLicense():
    return __vmLicense.copy()


__lang = None

def setLang(lang):
    global __lang
    __lang = locals()

def getLang():
    return __lang.copy()


__langSupport = None

def setLangSupport(lang, default):
    global __langSupport
    __langSupport = locals()

def getLangSupport():
    return __langSupport.copy()


__downloadNetwork = {}
__vmkNetwork = {}

NETWORK_DEFAULT_GATEWAY = ''
NETWORK_DEFAULT_NAMESERVER = ''
NETWORK_DEFAULT_HOSTNAME = ''

def setDownloadNetwork(gateway, nameserver1, nameserver2, hostname):
    global __downloadNetwork
    __downloadNetwork = locals()

def getDownloadNetwork():
    return __downloadNetwork.copy()


def setVmkNetwork(gateway, nameserver1, nameserver2, hostname):
    """ For iSCSI only, for now """
    global __vmkNetwork
    __vmkNetwork = locals()

def getVmkNetwork():
    return __vmkNetwork.copy()

def clearVmkNetwork():
    global __vmkNetwork
    __vmkNetwork = {}


__rootScriptLocation = {}

def setRootScriptLocation(rootScriptLocation):
    global __rootScriptLocation
    __rootScriptLocation = locals()

def getRootScriptLocation():
    return __rootScriptLocation.copy()


# ----------------------------------------------------------------------------
# Section 3: User choices that are multiple
# ----------------------------------------------------------------------------


__preScripts = []

def addPreScript(script):
    global __preScripts
    __preScripts.append(locals())

def clearPreScripts():
    global __preScripts
    __preScripts = []

def getPreScripts():
    return __preScripts

__postScripts = []

def addPostScript(script):
    global __postScripts
    __postScripts.append(locals())

def clearPostScripts():
    global __postScripts
    __postScripts = []

def getPostScripts():
    return __postScripts

__firstBootScripts = []

def addFirstBootScript(script):
    global __firstBootScripts
    __firstBootScripts.append(locals())

def clearFirstBootScripts():
    global __firstBootScripts
    __firstBootScripts = []

def getFirstBootScripts():
    return __firstBootScripts

__downloadNic = {}
__vmkNics = []

NIC_BOOT_DHCP = 'dhcp'
NIC_BOOT_STATIC = 'static'

def setDownloadNic(device, vlanID, bootProto=NIC_BOOT_DHCP, ip='', netmask=''):
    global __downloadNic
    __downloadNic = locals()

def getDownloadNic():
    return __downloadNic.copy()

# ip and netmask default to '' for the sake of brevity on the caller's side
def addVmkNIC(device, vlanID, bootProto=NIC_BOOT_DHCP, ip='', netmask=''):
    __vmkNics.append(locals())

def delVmkNIC(nic):
    """To delete a item, you will have to first get a reference
    to it from getNIC() so that you can uniquely identify it
    Throws: ValueError when the item is not in the list.
    """
    __vmkNics.remove(nic)

def getVmkNICs():
    return __vmkNics[:]

def setVmkNICs(newVmkNics):
    global __vmkNics
    __vmkNics = newVmkNics[:]


# place where we're going to install ESXi
__esxPhysicalDevice = ''

def setEsxPhysicalDevice(device):
    global __esxPhysicalDevice
    __esxPhysicalDevice = device

def getEsxPhysicalDevice():
    return __esxPhysicalDevice


# compression level to be used while compressing vmtar files
__compresslevel = 9

def setCompresslevel(compresslevel):
    global __compresslevel
    __compresslevel = compresslevel

def getCompresslevel():
    return __compresslevel


'''
action String. If user chooses upgrade then it is possibility
that it is migration from ESX to ESXi. Also if custom VIBs are
present then it is force migration. To record special case of
upgrade scenario, we use actionString
'''

__actionString = ''

def setActionString(actionString):
    global __actionString
    __actionString = actionString

def getActionString():
    return __actionString


__saveBootbankUUID = ''

def setSaveBootbankUUID(uuid):
    global __saveBootbankUUID
    __saveBootbankUUID = uuid

def getSaveBootbankUUID():
    return __saveBootbankUUID

__partitionPhysicalRequests = {}

def checkPhysicalPartitionRequestsHasDevice(device):
    return device in __partitionPhysicalRequests

def setPhysicalPartitionRequests(device, requests):
    global __partitionPhysicalRequests
    __partitionPhysicalRequests[device] = requests

def addPhysicalPartitionRequests(device, requests):
    if not checkPhysicalPartitionRequestsHasDevice(device):
        setPhysicalPartitionRequests(device, requests)
    else:
        __partitionPhysicalRequests[device] += requests

def getPhysicalPartitionRequests(device):
    return __partitionPhysicalRequests[device]

def getPhysicalPartitionRequestsDevices():
    return list(__partitionPhysicalRequests.keys())

def delPhysicalPartitionRequests(device):
    del __partitionPhysicalRequests[device]

def clearPhysicalPartitionRequests():
    global __partitionPhysicalRequests
    __partitionPhysicalRequests = {}


__serialNumber = {}

def setSerialNumber(esx):
    global __serialNumber
    __serialNumber = locals()

def getSerialNumber():
    return __serialNumber.copy()

def clearLicense():
    global __serialNumber
    __serialNumber = {}

# ----------------------------------------------------------------------------
# dumpToString
# ----------------------------------------------------------------------------
def dumpToString():
    '''Dump all of the interesting attributes in the userchoices module
    to a string
    '''
    def isNonMagicNonUppercaseData(name, obj):
        return not (
               (name.startswith('__') and name.endswith('__'))
               or name.upper() == name
               or callable(obj)
               )
    items = list(globals().items())
    strings = [pformat(item) for item in items
               if isNonMagicNonUppercaseData(*item)]
    strings.sort()
    dump = '\n'.join(strings)
    return dump
