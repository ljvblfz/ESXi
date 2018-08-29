#! /usr/bin/env python

# These units are in bytes.  All of them.
# We should make sure that most units use the lowest denomination, a byte ...
SIZE_KiB = (1024.0)
SIZE_MiB = (SIZE_KiB * 1024)
SIZE_GiB = (SIZE_MiB * 1024)
SIZE_TiB = (SIZE_GiB * 1024)

def formatValue(KiB=None, MiB=None, B=None):
    '''Takes an int value defined by one of the keyword args and returns a
    nicely formatted string like "2.6 GiB".  Defaults to taking in kibibytes.
    >>> formatValue(1048576)
    '1.00 GiB'
    >>> formatValue(MiB=66048)
    '64.50 GiB'
    >>> formatValue(KiB=66048)
    '64 MiB'
    >>> formatValue(B=1048576)
    '1 MiB'
    >>> formatValue(MiB=1048576)
    '1.00 TiB'
    '''
    # Convert to bytes ..
    assert len([x for x in [KiB, MiB, B] if x != None]) == 1

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
        return "%d MiB" % (value / SIZE_MiB)
    else:
        return "0 MiB"

def valueInMebibytesFromUnit(value, unit):
    '''
    >>> valueInMebibytesFromUnit(2, "GiB")
    2048.0
    '''
    assert unit in ["TiB", "GiB", "MiB", "KiB"]

    if unit == "TiB":
        return value * SIZE_TiB / SIZE_MiB
    elif unit == "GiB":
        return value * SIZE_GiB / SIZE_MiB
    elif unit == "KiB":
        return value * SIZE_KiB / SIZE_MiB
    else:
        return value

def getValueInSectorsFromMebibytes(value, sectorSize=512):
    return (value * SIZE_MiB) / sectorSize

def getValueInMebibytesFromSectors(value, sectorSize=512):
    return (value * sectorSize) / SIZE_MiB

def getValueInKibibytesFromSectors(value, sectorSize=512):
    return (value * sectorSize) / SIZE_KiB

