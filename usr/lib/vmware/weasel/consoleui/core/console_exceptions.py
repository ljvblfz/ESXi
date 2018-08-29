# -*- coding: utf-8 -*-

from weasel.consts import PRODUCT_STRING
from weasel.exception import HandledError

class VMVisorInstallerException(HandledError):
    """VMVisorInstallerException
    The base exception class for the exceptions used in the VMVisor Installer
    framework"""
    def __init__(self, message = None):
        if not message:
            message = "Unknown exception occured in VMVisor Installer"
        HandledError.__init__(self, message)

class CommandNotFoundException(VMVisorInstallerException):
    """CommandNotFoundException
    Exception raised when a command was not found on the system path"""
    def __init__(self, cmd):
        VMVisorInstallerException.__init__(self, "Unable to find required executable (%s) in current environment" % (cmd,))

class CommandFailureException(VMVisorInstallerException):
    """CommandFailureException
    Exception raised when the execution of a command failed"""
    def __init__(self, cmd, rc):
        VMVisorInstallerException.__init__(self, "Execution of command (%s) failed with error code: %s" % (cmd, rc))

class ImageNotFoundException(VMVisorInstallerException):
    """ImageNotFoundException
    Exception raised when the VMvisor Image is not found"""
    def __init__(self, image):
        VMVisorInstallerException.__init__(self, "The image file (%s) was not found at the specified path" % image)

class InvalidStateException(VMVisorInstallerException):
    """InvalidStateException
    Exception raised when the installer is in an invalid state.  This may be
    because a previous step did not correctly update the environment or some
    other unknown error occurred."""
    def __init__(self, msg):
        VMVisorInstallerException.__init__(self, "Unable to proceed because the installer is in an invalid state: %s" % (msg, ))

class NoValidDevicesException(VMVisorInstallerException):
    """NoValidDevicesException
    Exception raised when there are no supported devices found to which the
    installation would take place."""
    def __init__(self):
        VMVisorInstallerException.__init__(self, "Unable to find a supported device to write the " + PRODUCT_STRING + " image to.")

class InvalidTargetException(VMVisorInstallerException):
    """InvalidTargetException
    Exception raised when a target appears to be malformed through the inspection of the values of its properties."""
    def __init__(self):
        VMVisorInstallerException.__init__(self, "One or more Targets contain invalid values.")

class TooManyDevicesException(VMVisorInstallerException):
    """TooManyDevicesException
    Exception raised when there is more than one device connected to the system."""
    def __init__(self):
        VMVisorInstallerException.__init__(self, "There is more than one USB device connected to the system. Please disconnect all external USB storage devices and try again.")

class RebootException(HandledError):
    """RebootException
    Exception raised to signal the installer that it should reboot the
    machine."""
    pass
