# Copyright 2015 VMware, Inc.
# All rights reserved. -- VMware Confidential

"""featureSwitch.py module -- feature state switch support

Our function is to assist in propataging the boot command line options
from from the installer's boot loader command line to the boot loader
command line of the installed image.

This module is invoked from multiple world contexts.  It follows that
the feature switch needs to be saved in a temporary file in one context
and fetched out of there in another.
"""

from weasel.log import log


_table = {}
_switch_filename = "/tmp/collectedFeatureSwitches"


def AddFeatureSwitch(switchName, enabled):
    """AddFeatureSwitch -- add a feature switch to our table
    """
    _table[switchName] = "enabled" if enabled else "disabled"
    log.info("FeatureSwitch '%s' is %s" % (switchName, _table[switchName]))


def CollectAllFeatureSwitches():
    """GetAllFeatures -- return the feature swtich parameters

    This function returns all of the feature switch parameters
    passed in through AddFeatureSwitch() in a single string
    suitable for use in a boot loader command line.
    """
    switchParams = ''
    for sw in _table:
        switchParams += ' FeatureState.%s=%s' % (sw, _table[sw])
    log.info("FeatureSwitch params are '%s'" % switchParams)
    try:
       with open(_switch_filename, "w") as fd:
          fd.write(switchParams)
    except IOError as e:
       log.warn("Unable to write feature switch temporary file: %s" % str(e))


def ReturnFeatureSwitchString():
    try:
       with open(_switch_filename, "r") as fd:
          line = fd.readline()
    except IOError as e:
       log.warn("Unable to read feature switch temporary file: %s" % str(e))
       return ''
    log.info("Read featureSwitch params are '%s'" % line)
    return line
