#! /usr/bin/env python
"""
networking/utils.py module

Utility functions for universal use.  Mainly for checking / manipulating
IP Addresses and hostnames.
"""
from __future__ import print_function

import re
import string
import socket
import struct
import sys
if sys.version_info[0] >= 3:
    from urllib.parse import quote, unquote
    from urllib.parse import urlparse, urlunparse
else:
    from urllib import quote, unquote
    from urlparse import urlparse, urlunparse

try:
    from weasel.log import log
except ImportError:
    import sys
    import logging
    log = logging.getLogger()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter('%(message)s'))
    stdout_handler.setLevel(logging.DEBUG)
    log.addHandler(stdout_handler)
    log.setLevel(logging.DEBUG)


def stringToOctets(ipString):
    '''Turn an IP Address-like string into a list of ints.
    "123.123.123.123" -> [123,123,123,123]
    '''
    octets = ipString.split(".")
    try:
        octets = [int(x) for x in octets]
    except ValueError:
        raise ValueError("IP string had non-numeric characters")
    return octets

def sanityCheckHostname(hostname):
    '''Check to see if the input string is a valid hostname.
    Refer to RFC 1034, section 3.5 page 7 for the rules.
    Raise a ValueError if it is not.

    >>> sanityCheckHostname("foobar")
    >>> sanityCheckHostname("foobar.com")
    >>> sanityCheckHostname("123foobar.com") #will log a warning
    >>> sanityCheckHostname("-foobar.com")
    Traceback (most recent call last):
      . . .
    ValueError: Hostname labels must begin with a letter.
    >>> sanityCheckHostname("foo.-bar.com")
    Traceback (most recent call last):
      . . .
    ValueError: Hostname labels must begin with a letter.
    >>> sanityCheckHostname("foobar.com-")
    Traceback (most recent call last):
      . . .
    ValueError: Hostname labels must end with either a letter or digit, not a '-'.
    >>> sanityCheckHostname("foobar..com")
    Traceback (most recent call last):
      . . .
    ValueError: Hostname labels must not be empty.
    >>> sanityCheckHostname("f*bar.com")
    Traceback (most recent call last):
      . . .
    ValueError: Hostname labels must only contain letters, digits, and hyphens.
    '''
    if len(hostname) < 1:
        raise ValueError("Hostname must be at least one character.")

    if len(hostname) > 255:
        raise ValueError("Hostname must be less than 256 characters.")

    hostname = hostname.rstrip('.') # remove usually implicit trailing dot
    for label in hostname.split('.'):
        if label == '': # see RFC 1035, ping example.com. works.
            raise ValueError("Hostname labels must not be empty.")

        if len(label) > 63:
            raise ValueError("Hostname labels must be less than 64 characters.")
        if label[0] not in string.ascii_letters:
            if label[0] in string.digits:
                # hostnames starting with digits exist in the wild, so just warn
                log.warn('Hostname label (%s) starts with a digit.' % label)
            else:
                raise ValueError("Hostname labels must begin with a letter.")
        if label[-1] not in string.ascii_letters + string.digits:
            raise ValueError("Hostname labels must end with either a letter or digit, not a '%s'." % label[-1])
        allowedLabelChars = string.ascii_letters + string.digits + "-"
        for item in label[1:-1]:
            if item not in allowedLabelChars:
                raise ValueError("Hostname labels must only contain letters, digits, and hyphens.")


def isAddrLoopback(af, addr):
    '''af is address family, addr is packed binary ip address '''
    if af == socket.AF_INET:
        lba = struct.pack("!I", socket.INADDR_LOOPBACK)
        return addr == lba
    elif af == socket.AF_INET6:
        sub = struct.unpack("!4I", addr)
        return (sub[0] == 0 and sub[1] == 0 and sub[2] == 0 and sub[3] == 1)
    else:
        raise ValueError("Unsupported address family")

def isAddrMulticast(af, addr):
    '''af is address family, addr is packed binary ip address '''
    if af == socket.AF_INET:
        sub = struct.unpack("4B", addr)
        return sub[0] == 224
    elif af == socket.AF_INET6:
        sub = struct.unpack("16B", addr)
        return sub[0] == 0xff
    else:
        raise ValueError("Unsupported address family")

def isAddrUnspecified(af, addr):
    '''af is address family, addr is packed binary ip address '''
    if af == socket.AF_INET:
        sub = struct.unpack("!1I", addr)
        return sub[0] == 0
    elif af == socket.AF_INET6:
        sub = struct.unpack("!4I", addr)
        return (sub[0] == 0 and sub[1] == 0 and sub[2] == 0 and sub[3] == 0)
    else:
        raise ValueError("Unsupported address family")

def isAddrBroadcast(addr):
    ''' applies to IPv4 addresses only. Python 2.6.1 socket.INADDR_BROADCAST
    returns signed integer so first convert it to unsigned. socket.INADDR_BROADCAST
    is unsigned in later releases (2.6.4 tested)
    '''
    mask = socket.INADDR_BROADCAST & 0xffffffff
    bcst = struct.pack("!I", mask)
    return bcst == addr

def isScopeLocal(addr):
    ''' applies to IPv6 addresses only'''
    sub = struct.unpack("!4I", addr)
    return (sub[0] & 0xffc00000) == 0xfe800000

def sanityCheckIPString(ipString):
    '''Check to see if the input string is a valid IP unicast address that
    is not the loopback address. Raise a ValueError if it is not.
    '''
    if not len(ipString):
        raise ValueError("IP string can not be empty.")
    if ':' in ipString:
        af = socket.AF_INET6
    else:
        af = socket.AF_INET
    try:
        addr = socket.inet_pton(af, ipString)
    except socket.error as err:
        raise ValueError("IP address '%s' is invalid." % ipString)
    if isAddrLoopback(af, addr):
        raise ValueError("IP address cannot be in the loopback network.")
    if isAddrMulticast(af, addr):
        raise ValueError("IP address cannot be in the multicast network.")
    if isAddrUnspecified(af, addr):
        raise ValueError("IP address cannot be all zeros (unspecified) network.")

    # Address family specific checks
    if af == socket.AF_INET: # IPv6 removed broadcast
        if isAddrBroadcast(addr):
            raise ValueError("IP address cannot be the broadcast network.")

        octets = stringToOctets(ipString)
        if octets[0] < 1:
            raise ValueError("IP string contains an invalid first octet.")

    if af == socket.AF_INET6:
        if "." in ipString:
            raise ValueError("IP address cannot be a mapped IPv4 in IPv6 address.")
        if isScopeLocal(addr):
            raise ValueError("IP address cannot be a scope local IPv6 address.")

def sanityCheckIPorHostname(ipOrHost):
    '''Check to see if the input string is a valid IP address or hostname.
    Raise a ValueError if it is not.
    '''
    try:
        sanityCheckIPString(ipOrHost)
    except ValueError:
        return sanityCheckHostname(ipOrHost)



def sanityCheckGatewayString(gwString):
    '''Check to see if the input string is a valid IP address that can
    be used as a gateway.
    Raise a ValueError if it is not.
    '''
    sanityCheckIPString(gwString)


def sanityCheckNetmaskString(nmString):
    '''Check to see if the input string is a valid netmask or prefix.
    Raise a ValueError if it is not. The format can be either
    dotted-quad or an ordinal number. addressFamily may be inet or inet6
    '''
    if '.' in nmString:
        octets = stringToOctets(nmString)
        if len(octets) != 4:
            raise ValueError("Netmask (%s) did not contain four octets." % nmString)
        if not octets[0]:
            raise ValueError("First octet was empty.")
        foundZero = False
        for octet in octets:
            for x in reversed(list(range(8))):
                if not octet >> x & 1:
                    foundZero = True
                if octet >> x & 1 and foundZero:
                    raise ValueError("Netmask (%s) is invalid." % nmString)
    else:
        val = int(nmString)
        if val < 0:
            raise ValueError("Netmask must be a positive value (%d)" % val)

def sanityCheckNetmaskOrdinal(numBits, addressFamily):
    '''Check if number of bits is within range for given Address Family'''
    try:
        val = int(numBits)
    except ValueError:
        raise ValueError("Netmask must be a positive ordinal (%s)" % numBits)
    if addressFamily == 'inet':
        maxBits = 32
    elif addressFamily == 'inet6':
        maxBits = 128
    else:
        raise ValueError (
         "Invalid address family (%s) expected inet or inet6" % addressFamily)
    if val < 0 or val > maxBits:
        raise ValueError(
            "Netmask (%s) must be a value between 0 and %d for %s" \
              % (numBits, maxBits, addressFamily))


def sanityCheckIPandNetmask(ipString, nmString, addrDesc="IP"):
    '''Check to make sure the IPv4 address is not the network address and is not
    the network broadcast address.

    >>> sanityCheckIPandNetmask('192.168.2.1', '255.255.255.255')
    >>> sanityCheckIPandNetmask('192.168.2.1', '255.255.255.0')
    >>> sanityCheckIPandNetmask('192.168.2.255', '255.255.255.0')
    Traceback (most recent call last):
      . . .
    ValueError: IP address corresponds to the broadcast address.
    >>> sanityCheckIPandNetmask('192.168.2.0', '255.255.255.0')
    Traceback (most recent call last):
      . . .
    ValueError: IP address corresponds to the network address.
    >>> sanityCheckIPandNetmask('192.168.2.255', '255.255.252.0')

    '''
    ip = ipStringToNumber(ipString)
    nm = ipStringToNumber(nmString)
    if nm == socket.INADDR_BROADCAST:
        # There is only a single host in the "network", the remaining tests
        # don't apply.
        return
    # Is 'ip' the network address?
    if (ip & nm) == ip:
        raise ValueError("%s address corresponds to the network address." %
                         addrDesc)
    # Is 'ip' the (ones) broadcast address?
    if (ip & (~nm)) == (socket.INADDR_BROADCAST & (~nm)):
        raise ValueError("%s address corresponds to the broadcast address." %
                         addrDesc)


def sanityCheckIPSettings(ipString, nmString, gwString):
    '''Check to make sure all of the given settings are sane.  The IPv4 and
    gateway need to be valid wrt the netmask and they need to be in the same
    network. VmkCtl does all sanity checks for IPv6 which should happen only if
    DAD has completed for the static address installed.

    >>> sanityCheckIPSettings('192.168.2.2', '255.255.255.0', '192.168.2.1')
    >>> sanityCheckIPSettings('192.168.3.2', '255.255.255.0', '192.168.2.1')
    Traceback (most recent call last):
      . . .
    ValueError: IP and Gateway are not on the same network.

    '''

    sanityCheckIPString(ipString)
    sanityCheckNetmaskString(nmString)
    sanityCheckIPString(gwString)
    if "." in ipString:
        ip = ipStringToNumber(ipString)
        nm = ipStringToNumber(nmString)
        gw = ipStringToNumber(gwString)
        sanityCheckIPandNetmask(ipString, nmString)
        sanityCheckIPandNetmask(gwString, nmString, "Gateway")
        # Do they lie on the same network?
        if (ip & nm) != (gw & nm):
            raise ValueError("IP and Gateway are not on the same network.")


def sanityCheckVlanID(vlanID):
    '''Check to see if the input string is a valid VLAN ID.
       Raise a ValueError if it is not.
    '''
    try:
        int(vlanID)
    except ValueError:
        raise ValueError("Vlan ID must be a number from 0 to 4095.")

    if not 0 <= int(vlanID) <= 4095:
        raise ValueError("Vlan ID must be a number from 0 to 4095.")


def sanityCheckMultipleIPsString(multipleIPString):
    '''Check to see if the input string contains two or more valid IP addreses.
       Raise a ValueError if it is not.
    '''
    ips = re.split(',', multipleIPString)
    for ip in ips:
        sanityCheckIPString(ip)


def sanityCheckPortNumber(portNum):
    '''Check to see if the input string is a valid port number.
       Raise a ValueError if it is not.
    '''
    # NB - this can be 49151 or 65535.  49152-65535 are unassigned but it is
    #      possible to use them

    highestPort = 65535
    try:
        int(portNum)
    except ValueError:
        raise ValueError("Port number must be a number from 1 to %d."
                         % highestPort)

    if not 1 <= int(portNum) <= highestPort:
        raise ValueError("Port number must be a number from 1 to %d."
                         % highestPort)


def sanityCheckUrl(url, expectedProtocols=None):
    '''Try to determine whether a given url string is valid or not.
       expectedProtocols is a list.  Generally ['http','https'] or ['ftp'].
    '''
    protocol, _, _, host, port, _ = parseFileResourceURL(url)

    if not protocol or not host:
        raise ValueError("The specified URL was malformed.")

    if port:
        sanityCheckPortNumber(port)

    if expectedProtocols and protocol not in expectedProtocols:
        raise ValueError("Expected a url of type %s but got '%s'."
                         % (expectedProtocols, protocol))

    sanityCheckIPorHostname(host)


def parseFileResourceURL(url):
    '''Parse out all of the relevant fields that identify a file resource,
    it returns all information about params, queries, and anchors as part of
    the "path".

    url -> protocol, username, password, host, port, path
    >>> parseFileResourceURL('http://1.2.3.4')
    ('http', '', '', '1.2.3.4', '', '')
    >>> parseFileResourceURL('http://user:pass@1.2.3.4:80/foo')
    ('http', 'user', 'pass', '1.2.3.4', '80', '/foo')
    >>> parseFileResourceURL('http://example.com/foo/bar?a=1&b=2#anchor')
    ('http', '', '', 'example.com', '', '/foo/bar?a=1&b=2#anchor')
    >>> input = 'http://u:p@example.com:80/fo%20o.txt'
    >>> output = parseFileResourceURL(input)
    >>> input == unparseFileResourceURL(*output)
    True
    '''
    parseResult = urlparse(url)
    protocol, netloc, path, params, query, fragment = parseResult
    path = urlunparse(('', '', path, params, query, fragment))
    username = ''
    password = ''
    if '@' in netloc:
        userpass, hostport = netloc.split('@', 1)
        if ':' in userpass:
            username, password = userpass.split(':', 1)
        else:
            username = userpass
    else:
        hostport = netloc
    if ':' in hostport:
        host, port = hostport.rsplit(':', 1)
    else:
        host = hostport
        port = ''

    username = unquote(username)
    password = unquote(password)
    path = unquote(path)
    return protocol, username, password, host, port, path


def unparseFileResourceURL(protocol, username, password, host, port, path):
    '''
    >>> unparseFileResourceURL('http', '', '', '1.2.3.4', '', '')
    'http://1.2.3.4/'
    >>> unparseFileResourceURL('http', 'user', 'pass', '1.2.3.4', '80', '/foo')
    'http://user:pass@1.2.3.4:80/foo'
    '''
    username = quote(username, '')
    password = quote(password, '')
    path = quote(path)
    if not path.startswith('/'):
        path = '/' + path
    if port:
        hostport = host +':'+ port
    else:
        hostport = host
    if password:
        userpass = username +':'+ password
    else:
        userpass = username
    if userpass:
        netloc = userpass +'@'+ hostport
    else:
        netloc = hostport
    return protocol +'://'+ netloc + path


def cookPasswordInFileResourceURL(url):
    '''Parse url to find password, and if it exists, make it opaque.

    >>> cookPasswordInFileResourceURL('http://user:pass@1.2.3.4:80/foo')
    'http://user:XXXXXXXX@1.2.3.4:80/foo'
    >>> cookPasswordInFileResourceURL('http://1.2.3.4:/foo/bar')
    'http://1.2.3.4/foo/bar'
    '''
    protocol, username, password, host, port, path = parseFileResourceURL(url)
    if password:
        password = 'XXXXXXXX'
    newurl = unparseFileResourceURL(protocol, username,
                                    password, host, port, path)
    return newurl


def formatIPString(ipString):
    '''Get rid of any preceding zeroes'''
    if ':' in ipString:
        af = socket.AF_INET6
    else:
        af = socket.AF_INET

        octets = ["%s" % (int(x)) for x in ipString.split('.')]
        if len(octets) == 4:
            ipString = string.join(octets, '.')
        else:
            return ""
    return socket.inet_ntop(af, socket.inet_pton(af, ipString))


def calculateNetmask(ipString):
    '''return a netmask string (a guess of what the netmask would be)
    for the given IP address string. This assumes classful routing.
    '''
    sanityCheckIPString(ipString)
    if ":" in ipString: # common prefix length for host systems
        return "64"

    octets = stringToOctets(ipString)
    if octets[0] < 128:
        netmask = "255.0.0.0"
    elif octets[0] < 192:
        netmask = "255.255.0.0"
    else:
        netmask = "255.255.255.0"
    return netmask


def ipStringToNumber(ipString):
    '''Get a numerical value from an IPv4 address-like string
    Arguments:
    ipString - is a string in dotted-quad format.  It does not have to be
               a valid IP Address.  eg, it can also be a netmask string
    '''
    if ":" in ipString: # common prefix length for host systems
        raise ValueError("Expected IPv4, received an IPv6 address")
    octets = stringToOctets(ipString)

    if len(octets) != 4:
        raise ValueError('IPv4 string is invalid.')

    multipliers = (24, 16, 8, 0)
    ipNumber = 0
    for i, octet in enumerate(octets):
        ipNumber += octet << multipliers[i]
    return ipNumber


def ipNumberToString(ipNumber):
    '''Get an IPv4 address-like string from a numerical value.
    '''
    # XXX todo verify ipNumber range, >0 && < MAX_UINT32
    ipString = "%d.%d.%d.%d" % (
        (ipNumber >> 24) & 0x000000ff,
        (ipNumber >> 16) & 0x000000ff,
        (ipNumber >> 8) & 0x000000ff,
        ipNumber & 0x000000ff)
    return ipString


def calculateGateway(ipString, netmaskString):
    '''return an IPv4 address aa a string as the last
    assignable host in the subnetwork guessing that is where
    the default router for this subnet exists.
    '''
    ipNumber = ipStringToNumber(ipString)
    netmaskNumber = ipStringToNumber(netmaskString)

    netaddress = ipNumber & netmaskNumber
    broadcast = netaddress | ~netmaskNumber

    return ipNumberToString(broadcast - 1)


def calculateNameserver(ipString, netmaskString):
    '''return a IPv4 address as a string which is the
    first assignable host in the subnetwork guessing that it is where a DNS server
    is reachable given IP address and netmask strings.
    '''
    ipNumber = ipStringToNumber(ipString)
    netmaskNumber = ipStringToNumber(netmaskString)

    netaddress = ipNumber & netmaskNumber
    return ipNumberToString(netaddress + 1)


def main():
    try:
        log.info("Starting weasel.networking.utils test")
        log.info("sanityCheckHostname() starting")
        good_hostnames = [ "localhost", # this probably should be in the bad list would be user error to set normally?
                           "www.vmware.com.",
                           "www.vmware.com",
                           "123foobar.com",
                           "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.com",
                           "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.com",
                           "aa.bb.cc.dd.ee.ff.gg.hh.ii.jj.kk.ll.mm.nn.oo.pp.qq.rr.ss.tt.uu.vv.ww.xx.yy.zz.com",
                           "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.cccccccccccccccccccccccccccccc.dddddddddddddddddddddddddddddd.eeeeeeeeeeeeeeeeeeeeeeeeeeeeee.ffffffffffffffffffffffffffffff.ggggggggggg.hh.ii.jj.kk.ll.mm.nn.oo.pp.qq.rr.ss.tt.uu.vv.ww.xx.yy.zzz"
                           ]
        bad_hostnames = [
            "",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.cccccccccccccccccccccccccccccc.dddddddddddddddddddddddddddddd.eeeeeeeeeeeeeeeeeeeeeeeeeeeeee.ffffffffffffffffffffffffffffff.ggggggggggg.hh.ii.jj.kk.ll.mm.nn.oo.pp.qq.rr.ss.tt.uu.vv.ww.xx.yy.zzzz",
            ".foobar.com",
            "-foobar.com",
            "_foobar.com",
            "foobar_.com",
            "_foobar.com_",
            "foobar.com-",
            "foobar..com",
            "f*bar.com" ]

        for dname in good_hostnames:
            sanityCheckHostname(dname)

        for dname in bad_hostnames:
            try:
                sanityCheckHostname(dname)
                log.error("sanityCheckHostname() failed for input '%s'" % dname)
                return 1
            except ValueError:
                pass
        log.info("sanityCheckHostname() complete")

        # test IPv4 input
        log.info("sanityCheckIPString(ip-version-4) starting")
        good_ipv4 = ["192.0.2.1", "192.168.1.1", "10.100.200.254"]
        for ip in good_ipv4:
            sanityCheckIPString(ip)
        bad_ipv4 = ["", "0.0.0.0", "127.0.0.1", "255.255.255.255", "224.0.0.1", "1.2", "10.a.1.2", "10.1.1.256"]
        for ip in bad_ipv4:
            try:
                sanityCheckIPString(ip)
                log.error("sanityCheckIPString() failed for input '%s'" % ip)
                return 1
            except ValueError:
                pass
        log.info("sanityCheckIPString(ip-version-4) complete")

        # test IPv6 input
        log.info("sanityCheckIPString(ip-version-6) starting")
        good_ipv6 = ["2001:db8::ff", "fc00:10:20:100::1", ]
        for ip in good_ipv6:
            sanityCheckIPString(ip)
        bad_ipv6 = ["", "::1", "ff02::1", "fe80::218:8bff:fe76:ea79", "::ffff:192.0.2.128", "123", "1:2:3:4:5:6:7:8:9" ] # ipv4 has no bcast
        for ip in bad_ipv6:
            try:
                sanityCheckIPString(ip)
                log.error("sanityCheckIPString() failed for input '%s'" % ip)
                return 1
            except ValueError:
                pass
        log.info("sanityCheckIPString(ip-version-6) complete")

        # test sanityCheckIPorHostname()
        log.info("sanityCheckIPorHostname() starting")
        for ip in good_ipv4:
            sanityCheckIPorHostname(ip)
        for ip in good_ipv6:
            sanityCheckIPorHostname(ip)
        for ip in good_hostnames:
            sanityCheckIPorHostname(ip)
        log.info("sanityCheckIPorHostname() complete")

        # test formatIPString()
        log.info("formatIPString() starting")
        for ip in good_ipv4:
            print(formatIPString(ip))
        for ip in good_ipv6:
            print(formatIPString(ip))
        log.info("formatIPString() complete")

        # test Netmask or prefix checking
        log.info("sanityCheckNetmaskString() starting")
        good_ipv4_netmask = ["255.0.0.0", "255.255.252.0", "255.255.255.255", "1", "12", "24", "32"]
        good_ipv6_prefix = ["1", "64", "128"]
        bad_ipv4_netmask = ["0.0.0.0", "0.", "255.0.255.0", "116.0.0.0", "-1", "64"]
        bad_ipv6_prefix = ["-1", "129" ]
        for nm in good_ipv4_netmask:
            sanityCheckNetmaskString(nm)
        for nm in good_ipv6_prefix:
            sanityCheckNetmaskString(nm)
        for nm in bad_ipv4_netmask:
            try:
                if not "." in bad_ipv4_netmask:
                    sanityCheckNetmaskOrdinal(nm, "inet")
                sanityCheckNetmaskString(nm)
                log.error("sanityCheckNetmaskString() failed for input '%s'" % nm)
                return 1
            except ValueError:
                pass
        for nm in bad_ipv6_prefix:
            try:
                sanityCheckNetmaskOrdinal(nm, "inet6")
                sanityCheckNetmaskString(nm)
                log.error("sanityCheckNetmaskString() failed for input '%s'" % nm)
                return 1
            except ValueError:
                pass
        log.info("sanityCheckNetmaskString() complete")

        # sanityCheckGatewayString(gwString):

        log.info("Finished weasel.networking.utils test")
        return 0
    except Exception as er:
        print("test failed on exception: %s" % str(er))

    # XXX todo test following routines
    # sanityCheckIPandNetmask(ipString, nmString, addrDesc="IP"):
    # sanityCheckIPSettings(ipString, nmString, gwString):

    # sanityCheckMultipleIPsString(multipleIPString):
    # sanityCheckUrl(url, expectedProtocols=None):
    # parseFileResourceURL(url):
    # unparseFileResourceURL(protocol, username, password, host, port, path):
    # calculateNetmask(ipString):    # need to add test for IPv6, returns /64
    #
    # These two routines only take Ipv4
    # ipStringToNumber(ipString):
    # ipNumberToString(ipNumber):
    # calculateGateway(ipString, netmaskString):
    # calculateNameserver(ipString, netmaskString):
    #
    # sanityCheckVlanID(vlanID):
    # sanityCheckPortNumber(portNum):
    # cookPasswordInFileResourceURL(url):


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        pass
