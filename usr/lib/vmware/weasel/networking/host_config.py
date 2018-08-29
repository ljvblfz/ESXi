#! /usr/bin/env python
'''
networking.host_config module

The sole interface to this module is the `config` identifier.

Note, the proxy settings will be for every protocol that urllib2
serves.  That means HTTP and FTP.

>>> from weasel.networking import host_config
>>> host_config.config.hostname
''
>>> host_config.config.hostname = 'localhost'
>>> host_config.config.hostname
'localhost'
>>> host_config.config.gateway
'0.0.0.0'
>>> host_config.config.nameservers
<NameServerCollection []>
>>> host_config.config.nameservers.append('123.123.123.1')
>>> host_config.config.nameservers += ['123.123.123.2', '123.123.123.3']
>>> host_config.config.nameservers
<NameServerCollection ['123.123.123.1', '123.123.123.2', '123.123.123.3']>
>>> host_config.config.setupProxy('proxy.example.com', 3128)
>>> host_config.config.useProxy = True
'''

import vmkctl
from . import gateway
import sys
if sys.version_info[0] >= 3:
    from urllib.request import build_opener, install_opener, ProxyHandler
else:
    from urllib2 import build_opener, install_opener, ProxyHandler

from weasel.log import log
from .networking_base import wrapHostCtlExceptions


#------------------------------------------------------------------------------
_dnsConfigImpl = None
def _getDnsConfigImpl():
    '''The constructor vmkctl.DnsConfigImpl() has side effects, even
    though it is a singleton.  Thus we have to be extra careful.
    '''
    global _dnsConfigImpl
    if _dnsConfigImpl == None:
        _dnsConfigImpl = vmkctl.DnsConfigImpl()
    return _dnsConfigImpl


#------------------------------------------------------------------------------
class NameServerCollection(object):
    ''' An iterable and somewhat list-like collection of name servers
    Using instances of NameServerCollection will affect vmkctl.DnsConfig
    Note: One can not address a name server by index.  Indexes
    are not presumed to be the same between calls to dnsConfig.GetNameServers()
    '''
    @wrapHostCtlExceptions
    def _getNameServers(self):
        dnsConfig = _getDnsConfigImpl()
        return [ns.GetStringAddress() for ns in dnsConfig.GetNameServers()]

    def __contains__(self, item):
        return item in self._getNameServers()

    def __eq__(self, foreignList):
        return set(self._getNameServers()) == set(foreignList)

    def __ne__(self, foreignList):
        return not self.__eq__(foreignList)

    def __iadd__(self, foreignList):
        self.extend(foreignList)
        return self

    def __iter__(self):
        return iter(self._getNameServers())

    def __len__(self):
        return len(self._getNameServers())

    def __str__(self):
        return str(self._getNameServers())

    def __repr__(self):
        return '<NameServerCollection %s>' % repr(self._getNameServers())

    @wrapHostCtlExceptions
    def _save(self):
        dnsConfig = _getDnsConfigImpl()
        dnsConfig.SaveConfig()
        self.refresh()

    @wrapHostCtlExceptions
    def append(self, ipAddress, deferSaving=False):
        '''Works like list.append.
        Optionally use deferSaving when doing "batches"
        '''
        # TODO: I am trusting here that ipAddress has been previously
        #       sanity-checked perhaps I should be less trusting
        if ipAddress in self:
            return #don't add duplicate name servers
        log.info('Adding nameserver %s' % ipAddress)
        dnsConfig = _getDnsConfigImpl()
        if ":" in ipAddress:
            dnsConfig.AddNameServer(vmkctl.Ipv6Address(ipAddress))
        else:
            dnsConfig.AddNameServer(vmkctl.Ipv4Address(ipAddress))
        if not deferSaving:
            self._save()

    @wrapHostCtlExceptions
    def extend(self, iterable):
        '''Works like list.extend'''
        # TODO: I am trusting here that it has been previously sanity-checked
        #       perhaps I should be less trusting
        for ipAddress in iterable:
            self.append(ipAddress, deferSaving=True)
        self._save()

    @wrapHostCtlExceptions
    def remove(self, ipAddress):
        dnsConfig = _getDnsConfigImpl()
        if ipAddress not in self:
            return ValueError('NameServerCollection.remove(x): x not present')
        log.info('Removing nameserver %s' % ipAddress)
        dnsConfig.RemoveNameServer(vmkctl.Ipv4Address(ipAddress))
        self._save()

    @wrapHostCtlExceptions
    def refresh(self):
        '''Allows the current process to pick up any changes that have been
        made to the DNS configuration files.
        '''
        dnsConfig = _getDnsConfigImpl()
        # Refresh() calls res_init() to reset the DNS resolver for this process
        dnsConfig.Refresh()



class HostConfig(object):
    '''Simple container for conveniently and log-iffically getting/setting
    these attributes:
    * hostname
    * nameservers
    * gateway
    '''

    def __init__(self):
        self.nameservers = NameServerCollection()
        self._useProxy = False
        # null handler turns proxy off
        self._noProxyHandler = ProxyHandler({})
        self._proxyHandler = None

    @wrapHostCtlExceptions
    def _getHostname(self):
        dnsConfig = _getDnsConfigImpl()
        return dnsConfig.GetHostname()

    @wrapHostCtlExceptions
    def _setHostname(self, newFQDN):
        # TODO: I am trusting here that it has been previously sanity-checked
        #       perhaps I should be less trusting
        dnsConfig = _getDnsConfigImpl()
        oldHostname = dnsConfig.GetHostname()
        if oldHostname and oldHostname != newFQDN:
            log.info('Changing hostname from %s to %s'
                     % (oldHostname, newFQDN))
        else:
            log.info('Setting hostname to %s' % newFQDN)
        headAndTail = newFQDN.split('.', 1)
        dnsConfig.SetHostname(headAndTail[0])
        if len(headAndTail) > 1:
            domain = headAndTail[1]
            dnsConfig.SetDomain(domain)
            if domain != 'localdomain':
                dnsConfig.SetSearchDomainsString(domain)
        else:
            dnsConfig.SetDomain('')
            dnsConfig.SetSearchDomainsString('')
        dnsConfig.SaveConfig()
    hostname = property(_getHostname, _setHostname)

    @wrapHostCtlExceptions
    def _getGateway(self):
        return gateway.getGateway()

    @wrapHostCtlExceptions
    def _setGateway(self, newGateway):
        oldGateway = gateway.getGateway()
        defaultGateway = gateway.DEFAULT_GATEWAY
        if oldGateway and oldGateway not in [defaultGateway, newGateway]:
            log.info('Changing gateway from %s to %s'
                     % (oldGateway, newGateway))
        else:
            log.info('Setting gateway to %s' % newGateway)
        gateway.setGateway(newGateway)
    gateway = property(_getGateway, _setGateway)

    def setupProxy(self, host, port, username=None, password=None):
        if password:
            passwordString = ':'+ password
        else:
            passwordString = ''
        if username:
            userpassString = username + passwordString + '@'
        else:
            userpassString = ''
        url = 'http://%s%s:%s' % (userpassString, host, str(port))
        # NOTE: this will not work with HTTPS
        self._proxyHandler = ProxyHandler({'http': url, 'ftp': url})

    def _getUseProxy(self):
        return self._useProxy
    def _setUseProxy(self, val):
        if not val:
            if self._useProxy:
                log.debug('Turning off installer proxy server support')
                opener = build_opener(self._noProxyHandler)
                install_opener(opener)
                self._useProxy = False
            # elif self._useProxy was already False, just return
            return

        if not self._proxyHandler:
            raise ValueError('Can not turn on proxy before it has been set up')
        log.debug('Turning on installer proxy server support')
        opener = build_opener(self._proxyHandler)
        install_opener(opener)
        self._useProxy = True

    useProxy = property(_getUseProxy, _setUseProxy)


# create an instance for use as part of the API for the networking package
config = HostConfig()
