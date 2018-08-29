#! /usr/bin/env python

from __future__ import print_function

import select
import signal
import os
import os.path
import re
import sys
import errno
import tarfile
import gzip
import os.path
import time

import logging

from subprocess import PIPE
from subprocess import Popen

from weasel.log import log
from weasel.exception import HandledError

import vmkctl
import esxclipy

import json

STDIN = 0
STDOUT = 1
STDERR = 2

class ExecError(Exception):
    def __init__(self, command, output, status):
        Exception.__init__(self, "Command '%s' exited with status %d" % (
                command, status))

        self.command = command
        self.output = output
        self.status = status

def truncateString(fullString, length):
    '''Truncate a string to a desired length if it's too long.

       >>> myString = 'myreallylongstring'
       >>> truncateString(myString, 5)
       'my...'
    '''
    if len(fullString) > length and length >= 3:
        return fullString[:length - 3] + '...'
    return fullString

def getfd(filespec, readOnly=False):
    if isinstance(filespec, int):
        return filespec
    if filespec == None:
        filespec = "/dev/null"

    flags = os.O_RDWR | os.O_CREAT
    if (readOnly):
        flags = os.O_RDONLY
    return os.open(filespec, flags)


class FunctionList(list):
   def __init__(self):
      list.__init__(self)

   def append(self, func, *args, **kwargs):
      list.append(self, (func, args, kwargs))

   def run(self):
      for (func, args, kwargs) in self:
         func(*args, **kwargs)

def chroot(root):
    os.chroot(root)
    os.chdir('/')


def execLocalcliCommand(command):
    """ Calls into execCommand to execute a localcli call that outputs the
    json formatted output.  The output then gets parsed into python structures
    that will get returned.
    """

    localcliPre = "localcli --formatter=json"

    rc, stdout, stderr = execCommand(localcliPre + ' ' + command)

    if rc:
        log.error("localcli call failed: %s" % stderr)
        return None

    output = json.loads(stdout)
    return output


def execCommand(command, input=None, root='/', ignoreSignals=False, level=logging.INFO,
                raiseException=False):
   '''execCommand(command, root='/', ignoreSignals=False, level=logging.INFO)
   command: string - The command you wish to execute
   input: string - input to stdin for the subprocess
   root: string - The environment root (will chroot to this path before execution)
   ignoreSignals: bool - Should we ignore SIGTSTP and SIGINT
   level: logging level - The logging level that should be used
   raiseException: bool - Raise an ExecError exception if the commands exit code
     is non-zero.
   '''

   def ignoreStopAndInterruptSignals():
      signal.signal(signal.SIGTSTP, signal.SIG_IGN)
      signal.signal(signal.SIGINT, signal.SIG_IGN)

   env = {}
   commandEnvironmentSetupFunctions = FunctionList()

   env['PATH'] = '/sbin:/bin:/usr/sbin:/usr/bin:/usr/bin/vmware'

   if root and root != '/':
      commandEnvironmentSetupFunctions.append(chroot, root)

   if ignoreSignals:
      commandEnvironmentSetupFunctions.append(ignoreStopAndInterruptSignals)

   log.debug('Executing: %s' % command)
   process = Popen(command, shell=True, env=env,
                   preexec_fn=commandEnvironmentSetupFunctions.run,
                   stdin=PIPE, stdout=PIPE, stderr = PIPE, close_fds = True)
   stdout = None; stderr = None

   if input and sys.version_info[0] >=3:
        input = input.encode()

   try:
      (stdout, stderr) = process.communicate(input)
   except OSError as e:
      log.error("%s failed to execute: (%d): %s\n"
                % (command, e.errno, e.strerror))

   if stderr:
      log.info("stderr: %s\n" % (stderr,))
   else:
      log.log(level, stdout)

   if process.returncode and raiseException:
       raise ExecError(
           command,
           "Standard Out:\n%s\n\nStandard Error:\n%s" % (stdout, stderr),
           process.returncode)

   if sys.version_info[0] >=3:
        stdout = stdout.decode()

   return (process.returncode, stdout, stderr)


def execWithCapture(command, argv, searchPath=False, root='/', stdin=STDIN,
                    catchfdList=None, closefd=-1, returnStatus=False,
                    timeoutInSecs=0, raiseException=False):
    '''This is borrowed from Anaconda
    '''

    if catchfdList is None:
        catchfdList = [STDOUT]

    normCmdPath = os.path.join('/', root, command.lstrip('/'))

    if not os.access(normCmdPath, os.X_OK):
        raise RuntimeError(command + " can not be run")

    (read, write) = os.pipe()

    childpid = os.fork()
    if not childpid:
        if root and root != '/':
            chroot(root)

        # Make the child the new group leader so we can killpg it on a timeout
        # and it'll take down the shell and all its children.
        os.setsid()

        for catchfd in catchfdList:
            os.dup2(write, catchfd)
        os.close(write)
        os.close(read)

        if closefd != -1:
            os.close(closefd)

        if stdin:
            os.dup2(stdin, STDIN)
            os.close(stdin)

        if searchPath:
            os.execvp(command, argv)
        else:
            os.execv(command, argv)

        sys.exit(1)

    os.close(write)

    def timeoutHandler(_signum, _frame):
        try:
            os.killpg(childpid, signal.SIGKILL) # SIGKILL to harsh?
        except:
            log.exception("timeoutHandler: kill")
        return

    if timeoutInSecs:
        oldHandler = signal.signal(signal.SIGALRM, timeoutHandler)
        signal.alarm(timeoutInSecs)

    rc = ""
    s = "1"
    while (s):
        try:
            select.select([read], [], [])
        except select.error as e:
            errNum, errStr = e
            if errNum == errno.EINTR:
                # We'll get an EINTR on timeout...
                continue
            log.error("select -- %s" % errStr)
            raise
        s = os.read(read, 1000)

        if sys.version_info[0] >=3:
           s = s.decode()

        rc = rc + s
    os.close(read)

    status = -1
    try:
        (_pid, status) = os.waitpid(childpid, 0)
        if timeoutInSecs:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, oldHandler)
    except OSError as e:
        print("%s waitpid: %s" % (__name__, e.strerror))

    if status and raiseException:
        raise ExecError(" ".join(argv), rc, status)

    if returnStatus:
        return (rc, status)
    else:
        return rc

def execWithLog(command, argv, root='/', level=logging.INFO,
                timeoutInSecs=0, raiseException=False):
    '''Execute the given command and log its output.'''

    cmdline = " ".join(argv)
    log.debug("executing: %s" % cmdline)
    (output, status) = execWithCapture(command, argv,
                                       root=root,
                                       returnStatus=True,
                                       catchfdList=[STDOUT, STDERR],
                                       timeoutInSecs=timeoutInSecs,
                                       raiseException=False)

    log.debug("command exited with status %d" % status)

    if status:
        log.error(output)
        if raiseException:
            raise ExecError(cmdline, output, status)
    else:
        log.log(level, output)

    return status

def mount(device, mountPoint, readOnly=False, bindMount=False, loopMount=False, isUUID=False, options=None, fsTypeName=None):
    if not os.path.exists(mountPoint):
        os.makedirs(mountPoint)

    args = ["/usr/bin/mount"]

    if device.startswith("UUID="):
        # Be nice and accept a device name in the UUID=XXXXX format.
        isUUID = True
        device = device.replace("UUID=", '', 1)

    if readOnly:
        args.append("-r")

    if bindMount:
        args.append("--bind")

    allOptions = []
    if loopMount:
        allOptions += ["loop"]

    if options:
        allOptions += options

    if allOptions:
        args.extend(["-o", ",".join(allOptions)])

    if fsTypeName:
        args.extend(["-t", fsTypeName])

    if isUUID:
        uuid = device
        device = uuidToDevicePath(uuid)
        if not device:
            return 1

    args += [device, mountPoint]

    status = execWithLog(args[0], args, level=logging.DEBUG)

    return status

def umount(mountPoint):
    args = ["/usr/bin/umount", mountPoint]

    status = execWithLog(args[0], args, level=logging.DEBUG)

    return status

def splitInts(stringWithNumbers):
    '''Break up a string with numbers so it can be sorted in natural order.

    >>> splitInts("foo")
    ['foo']
    >>> splitInts("foo 123")
    ['foo', 123]
    '''

    def attemptIntConversion(obj):
        try:
            return int(obj)
        except ValueError:
            return obj

    retval = []
    for val in re.split(r'(\d+)', stringWithNumbers):
        if not val:
            # Ignore empty strings
            continue

        retval.append(attemptIntConversion(val.strip()))

    return retval

def rawInputWithTimeout(promptMsg, timeoutInSecs):
    class TimeoutException(Exception):
        pass

    def timeoutHandler(_signum, _frame):
        raise TimeoutException()

    oldHandler = signal.signal(signal.SIGALRM, timeoutHandler)
    signal.alarm(timeoutInSecs)

    try:
        retval = prompt(promptMsg)
    except TimeoutException:
        retval = None
    signal.alarm(0)
    signal.signal(signal.SIGALRM, oldHandler)

    return retval

def rawInputCountdown(promptMsg, totalTimeout):
    try:
        for seconds in range(totalTimeout):
            retval = rawInputWithTimeout(promptMsg % (totalTimeout - seconds),
                                         1)
            if retval is not None:
                return retval
    finally:
        sys.stdout.write("\n")

    return None

def vmkctlLoadModule(moduleName):
    moduleImpl = vmkctl.ModuleImpl(moduleName)
    if not moduleImpl.IsLoaded():
        moduleImpl.Load()

def loadVmfsModule():
    vmkctlLoadModule('vmfs3')

def loadFiledriverModule():
    vmkctlLoadModule('filedriver')

def loadVfatModule():
    vmkctlLoadModule('vfat')

# flag to indicate whether automount is done
_Automounted = False

def setAutomounted(automounted):
    global _Automounted
    _Automounted = automounted

def getAutomounted():
    global _Automounted
    return _Automounted

def mountVolumes():
    # Mounts volumes for which the drivers have been loaded.
    cmd = "localcli storage filesystem automount"

    rc, stdout, stderr = execCommand(cmd)

    if rc:
        log.warn("localcli may have failed to remount...")
        setAutomounted(False)
    else:
        setAutomounted(True)

def rescanVmfsVolumes(automount=True):
    vmkctl.StorageInfoImpl().RescanVmfs()
    # if automount is done before, don't do automount again
    if automount and not getAutomounted():
        import time
        mountVolumes()
        # XXX wait for vmfs volumes to settle down, six is the magic number.
        time.sleep(6)

def verifyFileWrite(fpath, expected):
    '''check that the expected has been written to the file at fpath'''
    fp = open(fpath)
    contents = fp.read()
    fp.close()
    if contents != expected:
        raise IOError('expected (%s), got (%s)' % (expected, contents))

def verifyGzWrite(filePath, expected):
    try:
        fp = gzip.GzipFile(filePath)
        if fp.read() != expected:
           raise
        fp.close()
    except Exception as ex:
        raise IOError('Bad write of gzipped file %s' % filePath)

def linearBackoff(tries=3, backoff=2):
    '''"A decorator that retries the given function.  It will retry if the
    decorated function raises any subclass of Exception.
    '''
    def decoBackoff(fn):
        def fnBackoff(*args, **kwargs):
            import time
            count = 1

            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as ex:
                    log.exception("Executing '%s' failed (%s).  Attempt %d." %
                                  (fn.__name__, ex, count))

                if count == tries:
                    raise HandledError("Unable to successfully execute '%s'"
                                       " after %d tries.  Installation cannot"
                                       " continue." % (fn.__name__, count))

                time.sleep(backoff * count)
                count += 1

        return fnBackoff
    return decoBackoff


NO_NIC_MSG = \
'No network adapters were detected. Either no network adapters are physically '\
'connected to the system, or a suitable driver could not be located. A third '\
'party driver may be required.\n'\
'Ensure that there is at least one network adapter physically connected to '\
'the system before attempting installation. If the problem persists, consult '\
'the VMware Knowledge Base.'


def checkNICsDetected():
    from weasel import networking
    pnics = networking.getPhysicalNics()
    return len(pnics) > 0


_previousFirewallState = None
def ensureFirewallOpen():
    global _previousFirewallState
    cli = esxclipy.EsxcliPy()
    if _previousFirewallState == None:
        # Save the old firewall state so we can restore it later
        status, output = cli.Execute('network firewall get'.split())
        if status != 0:
            errDetail = output
        else:
            log.info('Previous firewall status: %s' % output)
            try:
                rvDict = eval(output)
                _previousFirewallState = rvDict['Enabled']
            except Exception as ex:
                errDetail = str(ex) + '\nFrom esxcli output:\n' + output

        if _previousFirewallState == None:
            msg = 'Could not query firewall status'
            log.warn(msg)
            log.warn(errDetail)
            raise HandledError(msg, errDetail)

    log.info('Turning off firewall')
    rv = cli.Execute('network firewall set --enabled=false'.split())
    log.debug('Result: %s' % str(rv))

def restoreFirewallState():
    cli = esxclipy.EsxcliPy()
    if _previousFirewallState == None:
        # State was never successfully queried, so do nothing
        return
    if _previousFirewallState == True:
        cli.Execute('network firewall set --enabled=true'.split())
    else:
        cli.Execute('network firewall set --enabled=false'.split())

def prompt(msg):
    '''Python 2 and 3 compatible input function'''
    if sys.version_info[0] >= 3:
        return input(msg)
    else:
        return raw_input(msg)


_isNOVA = None
def isNOVA():
    ''' Test if this is a NOVA system. To qualify as a NOVA system,
        the vmklinux module must not be installed.
    '''
    global _isNOVA
    if _isNOVA is None:
        _isNOVA = not os.path.exists('/usr/lib/vmware/vmkmod/vmklinux_9')
    return _isNOVA


_deviceDriverList = None
def deviceDriverList():
    ''' Wrapper for localcli to get list of devices and drivers.
    Output of the localcli is cached.
    '''
    global _deviceDriverList
    if _deviceDriverList is None:
        if isNOVA():
            cli = esxclipy.EsxcliPy()
            status,output = cli.Execute('device driver list'.split())
            err = None
            if status == 0:
                try:
                    _deviceDriverList = eval(output)
                    log.debug("Device driver list:")
                    for d in _deviceDriverList:
                        log.debug(str(d))
                except Exception as ex:
                    err = str(ex) + '\nFrom esxcli output:\n' + output
            else:
                err = output
            if err is not None:
                raise HandledError('Could not query device list', err)
        else:
            _deviceDriverList = []
    return _deviceDriverList

_deviceDescription = None
def getDeviceDescription(name):
    """Get the PCI device description for a device.
    """
    global _deviceDescription
    if _deviceDescription is None:
        pciInfo = execLocalcliCommand('hardware pci list')
        if pciInfo is None:
           raise HandledError('Could not get pci hardware information')
        _deviceDescription = {}
        for dev in pciInfo:
            _deviceDescription[dev['VMkernel Name']] = dev['Device Name']

    if name in _deviceDescription.keys():
       desc = _deviceDescription[name]
    else:
       desc = '<unknown device>'

    return desc

_missingDeviceDrivers = None
def missingDeviceDrivers():
    ''' Get list of devices with missing device driver.
    '''
    global _missingDeviceDrivers
    if _missingDeviceDrivers is None:
        _missingDeviceDrivers = []
        for device in deviceDriverList():
            if device['Status'] == 'missing':
                _missingDeviceDrivers += [device]
                device['Description'] = getDeviceDescription(
                                              device['Device'])
    return _missingDeviceDrivers

_nominalDeviceDrivers = None
def nominalDeviceDrivers():
    ''' Get list of devices with nominal drivers.
    '''
    global _nominalDeviceDrivers
    if _nominalDeviceDrivers is None:
        _nominalDeviceDrivers = []
        for device in deviceDriverList():
            if device['Status'] == 'nominal':
                _nominalDeviceDrivers += [device]
                device['Description'] = getDeviceDescription(
                                              device['Device'])
    return _nominalDeviceDrivers

def isBootbankRecent(bootbankPath):
    """
    Checks if the geven bootbank was recently used.

    The chosen heuristic is to verify that state.tgz was
    updated within the last 48 hrs.
    """
    statePath = os.path.join(bootbankPath, "state.tgz")
    if not os.path.exists(statePath):
        return False

    stateMTime = os.path.getmtime(statePath)
    log.debug("state.tgz was last modified at %s" %
              time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stateMTime)))

    validAfterTS = time.time() - (48 * 60 * 60) # 48 hrs ago
    return stateMTime > validAfterTS

def getNominalDevices(aliasType=None):
   """getNominalDevices

   Returns a common separated list of device aliases for
   which the native driver is nominal.
   """
   devList = []
   for d in nominalDeviceDrivers():
       if not aliasType or d['Device'].startswith(aliasType):
           devList.append(d['Device'])
   return ', '.join(devList)

def getMissingDevices(aliasType=None):
   """getMissingDevices

   Returns a common separated list of device aliases for
   which the native driver is missing.
   """
   devList = []
   for d in missingDeviceDrivers():
       if not aliasType or d['Device'].startswith(aliasType):
           devList.append(d['Device'])
   return ', '.join(devList)

if __name__ == "__main__":
    args = ["/bin/echo", "foo"]
    x = execWithCapture(args[0], args)
    print("x = %s" % x)
