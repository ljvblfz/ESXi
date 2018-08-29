#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pyEngine.simpleConfigProfile import SimpleProfileChecker

from pluginApi import ParameterMetadata, log, ProfileComplianceChecker
from pluginApi import CreateLocalizedException
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_COREDUMP_CONFIG
from pluginApi.extensions import SimpleConfigProfile
from pyEngine.networkprofile import NetworkProfile
from pyEngine.nodeputil import IpAddressValidator, RangeValidator

ND_BASE_KEY = 'com.vmware.profile.netdump'
ND_INVALID_PARAM_KEY = '%s.invalid.param' % (ND_BASE_KEY)
ND_INVALID_SERVERIP_KEY = '%s.invalid.serverIp' % (ND_BASE_KEY)
ND_NETWORK_UNAVAIL_KEY = '%s.network.unavailable' % (ND_BASE_KEY)
DEFAULT_NETDUMP_PORT = 6500


class NetdumpIpValidator(IpAddressValidator):
    @staticmethod
    def Validate(obj, argName, arg, errors):
        if arg is None or arg == '':
            return True
        else:
            return IpAddressValidator.Validate(obj, argName, arg, errors)


class NetdumpRangeValidator(RangeValidator):
    # Our init can just call the base class. We do our own validate anyway
    # which handles the special case.

    def Validate(self, obj, argName, arg, errors):
        if arg is None or arg == 0:
            return True
        else:
            return RangeValidator.Validate(self, obj, argName, arg, errors)

def ProcessNetdumpProfile(profileInstances):
    polOpt = profileInstances[0].NetdumpProfilePolicy.policyOption
    if polOpt.NetworkServerIP and not polOpt.NetworkServerPort:
        polOpt.NetworkServerPort = DEFAULT_NETDUMP_PORT

class NetdumpProfileChecker(SimpleProfileChecker):
    def CheckProfileCompliance(self, profileInstances,
                               hostServices, profileData, parent):
        ProcessNetdumpProfile(profileInstances)
        return SimpleProfileChecker.CheckProfileCompliance(self,
                                                           profileInstances,
                                                           hostServices,
                                                           profileData, parent)

class NetdumpProfile(SimpleConfigProfile):
    """A Host Profile that manages configuration of network coredump on ESX hosts.
    """
    #
    # Define required class attributes
    #
    parameters = [ParameterMetadata('Enabled', 'bool', False),
                  ParameterMetadata('HostVNic', 'string', True),
                  ParameterMetadata('NetworkServerIP', 'string', True,
                                    paramChecker=NetdumpIpValidator),
                  ParameterMetadata('NetworkServerPort', 'int', True,
                                    paramChecker=NetdumpRangeValidator(1, 65535))]

    singleton = True

    category = CATEGORY_GENERAL_SYSTEM_SETTING
    component = COMPONENT_COREDUMP_CONFIG

    # Make this profile as a subprofile for NetworkProfile.
    parentProfiles = [NetworkProfile]

    @classmethod
    def _GetCurrentConfig(cls, hostServices):
        """Internal method that will invoke esxcli to get the the current
        configuration.
        """
        cliNamespace, cliApp, cliOp = 'system', 'coredump', 'network get'
        status, output = hostServices.ExecuteEsxcli(
            cliNamespace, cliApp, cliOp)
        if status != 0:
            log.error('Failed to execute "esxcli system coredump network get" ' +
                      'command. Status = %d, Error = %s' % (status, output))
            exc = CreateLocalizedException(None, ND_INVALID_PARAM_KEY)
            raise exc

        return output

    @classmethod
    def _SetGivenConfig(cls, hostServices, configInfo):
        """Internal method that will invoke esxcli to set the netudmp configuration.
        """
        config = configInfo[0]

        if config['Enabled'] == True:
            # Set Server related information.
            portStr = ''
            if config['NetworkServerPort'] != 0:
                portStr = '--server-port %s' % (config['NetworkServerPort'])

            netdumpServer = config['NetworkServerIP']
            ifaceName = config['HostVNic']

            if not hostServices.WaitForNetworkAvailability(ifaceName):
                log.info('IPv4 address not available for ' +
                         'interface %s. Now trying IPv6' % str(ifaceName))
                if not hostServices.WaitForNetworkAvailability(ifaceName,
                                                               useIpv4=False):
                    log.error('No network available for interface %s'
                              % str(ifaceName))
                    exc = CreateLocalizedException(None,
                                                   ND_NETWORK_UNAVAIL_KEY,
                                                   config)
                    raise exc

            # '--server-ip' argument accepts both IPv4 and IPv6 values
            serverIpArg = '--server-ip'

            cliNamespace, cliApp, cliOp = 'system', 'coredump', 'network set'
            optionStrNet = '--interface-name %s %s %s %s' % \
                (ifaceName, serverIpArg, netdumpServer, portStr)

            status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp,
                                                        optionStrNet)
            if status:
                log.error('Failed to execute "esxcli system coredump network set' +
                          '%s". Status = %d, Error = %s.' %
                          (optionStrNet, status, output))
                exc = CreateLocalizedException(None, ND_INVALID_PARAM_KEY)
                raise exc

        # Enable or disable anyhow.
        cliNamespace, cliApp, cliOp = 'system', 'coredump', 'network set'
        optionStr = '--enable %s ' % ("true" if config['Enabled']
                                      else "false")

        status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp,
                                                    optionStr)
        if status:
            log.error('Failed to execute "esxcli system coredump network set --enable' +
                      '%s". Status = %d, Error = %s.' %
                      (optionStr, status, output))
            exc = CreateLocalizedException(None, ND_INVALID_PARAM_KEY)
            raise exc

    @classmethod
    def ExtractConfig(cls, hostServices):
        """For current config just execute the required esxcli
        """
        # implementation of extract config is pretty easy with ExecuteEsxcli.
        # That already returns output as a dict. We just need to translate
        # the data a little bit.
        #import pdb
        #config = pdb.runcall(cls._GetCurrentConfig, hostServices)
        config = cls._GetCurrentConfig(hostServices)
        ndInfo = dict([(ndKey.replace(' ', ''), ndVal)
                       for ndKey, ndVal in config.items()])

        # PR 1216175: With IPv6 support, the command:
        #   esxcli system coredump network get
        # outputs one new line as "Is Using IPv6: false/true".
        # From this line, a wrongly defined parameter IsUsingIPv6
        # is generated which causes performance issue when get metadata
        # for a host profile.  The following code removes IsUsingIPv6
        # from the config list
        paramNames = [param.paramName for param in cls.parameters]
        ndInfo = {k: ndInfo[k] for k in paramNames if k in ndInfo}
        return ndInfo

    @classmethod
    def SetConfig(cls, config, hostServices):
        """For the Netudmper profile, the config parameter should contain
        a list of dicts (list will have one element), where the dict contains
        the parameters needed to enable/configure.
        """

        #import pdb
        #config = pdb.runcall(cls._SetGivenConfig, hostServices, config)
        config = cls._SetGivenConfig(hostServices, config)

    @classmethod
    def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                         profileData, validationErrors):
        ProcessNetdumpProfile(profileInstances)
        return super(NetdumpProfile, cls).GenerateTaskList(profileInstances,
                                                           taskList,
                                                           hostServices,
                                                           profileData,
                                                           validationErrors)

NetdumpProfile.complianceChecker = NetdumpProfileChecker(NetdumpProfile)