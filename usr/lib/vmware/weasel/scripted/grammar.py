import re
import sys

from .util import makeResult
from weasel.util.regexlocator import RegexLocator
from weasel.networking.utils import \
     sanityCheckIPString, \
     sanityCheckHostname, \
     sanityCheckIPorHostname, \
     sanityCheckGatewayString, \
     sanityCheckNetmaskString, \
     sanityCheckMultipleIPsString, \
     sanityCheckVlanID#, \
#     sanityCheckUrl

class GrammarDetail:
   REQUIRED, OPTIONAL, DEPRECATED, UNUSED, ALIAS, INVALIDATED = list(range(6))


class ArgumentOrientation:
   '''
   Enumeration used to specify where non-flag arguments are located.

   FRONT    The argument is the first one after the command, flag arguments
            will follow afterward.
   BACK     The argument is the last.

   '''
   FRONT, BACK = list(range(2))

def validateSize(flagName, size):
   '''Test whether a string is a valid size value (i.e. a number greater than
   zero).

   >>> validateSize('test', '100')
   (1, [], [])
   >>> validateSize('test', 'foo')
   (0, ['"test=" is not a number.'], [])
   >>> validateSize('test', '0')
   (0, ['"test=" must be a value greater than zero.'], [])
   >>> validateSize('test', '-100')
   (0, ['"test=" must be a value greater than zero.'], [])
   '''
   errors = []

   try:
      size = int(size)
      if size <= 0:
         errors.append('"%s=" must be a value greater than zero.' % flagName)
   except ValueError:
      errors.append('"%s=" is not a number.' % flagName)

   return makeResult(errors, [])


def adaptToValidator(sanityFunction):
   r'''Adapt a sanityCheck function so it can be used as a valueValidator.

   The sanityCheck function should take a single argument and throw a
   ValueError exception if the argument is invalid.

   >>> validator = adaptToValidator(sanityCheckHostname)
   >>> validator('test', '-localhost')
   (0, ['"test=" Hostname labels must begin with a letter.'], [])
   '''

   def validator(flagName, value):
      errors = []

      try:
         sanityFunction(value)
      except ValueError as msg:
         errors.append('"%s=" %s' % (flagName, str(msg)))

      return makeResult(errors, [])

   return validator

# Create validators for network-related data.
validateHostname = adaptToValidator(sanityCheckHostname)
validateIPString = adaptToValidator(sanityCheckIPString)
validateIPorHostname = adaptToValidator(sanityCheckIPorHostname)
validateGatewayString = adaptToValidator(sanityCheckGatewayString)
validateNetmaskString = adaptToValidator(sanityCheckNetmaskString)
validateMultipleIPsString = adaptToValidator(sanityCheckMultipleIPsString)
validateVlanID = adaptToValidator(sanityCheckVlanID)

def validateScript(*args):
    '''Can't solve Halting problem yet, so just accept anything'''
    return makeResult([], [])

class GrammarDefinition:
   '''
   Container for the scripted installation grammar definition, which consists
   of a set of commands and their arguments.  The syntax is a command name
   followed by zero or more required or optional arguments.
   '''

   def __init__(self):
      self.grammar = self.getScriptedInstallGrammar()
      self._self_check()

   def _self_check(self):
      '''
      Check the grammar to make sure it is sane.
      '''

      for command, value in self.grammar.items():
         assert 'detail' in value
         if self.isDeprecated(command) or self.isUnused(command):
            continue

         assert 'descr' in value, "'descr' missing from %s" % command
         assert 'grammar' in value, "'grammar' missing from %s" % command
         assert set(value.keys()).issubset([
            'descr',
            'detail',
            'grammar',
            'alias',
            'options',
            'multiline',
            'onDuplicate',
            'requiresMsg',
            'requires']), \
            "'%s' has extra attributes" % command

         cmdGrammar = self.getCommandGrammar(command)
         assert 'id' in cmdGrammar, "'id' missing from %s" % command
         assert 'args' in cmdGrammar, "'args' missing from %s" % command
         for arg, argGrammar in cmdGrammar['args'].items():
            assert 'detail' in argGrammar
            assert set(argGrammar.keys()).issubset([
               'detail',
               'valueRegex',
               'regexFlags',
               'valueValidator',
               'regexMsg',
               'noneValue',
               'defaultValue',
               'invalids',
               'requires',
               'alias',
               'requiresMsg',
               'onRegexMismatch',
               'onMissingValue',
               'onSuperfluous',
               'onDuplicate',
               ]), \
               "'%s.%s' has extra attributes" % (command, arg)

   def isCommand(self, command):
      return command in self.grammar

   def isMultiline(self, command):
      if command not in self.grammar:
         return False
      return self.grammar[command].get('multiline', False)

   def isDeprecated(self, command):
      '''
      Return true if a command in the grammar is deprecated.

      >>> gd = GrammarDefinition()
      >>> gd.isDeprecated("firstboot")
      True
      >>> gd.isDeprecated("clearpart")
      False
      '''

      assert command in self.grammar
      assert 'detail' in self.grammar[command]

      return self.grammar[command]['detail'] == GrammarDetail.DEPRECATED

   def isUnused(self, command):
      '''
      Return true if a command in the grammar is unused, meaning we will
      support it in the future.

      >>> gd = GrammarDefinition()
      >>> gd.isUnused("lang")
      True
      >>> gd.isUnused("clearpart")
      False
      '''

      assert command in self.grammar
      assert 'detail' in self.grammar[command]

      return self.grammar[command]['detail'] == GrammarDetail.UNUSED

   def isInvalidated(self, command):
      '''
      Return true if a command in the grammar is invalidated, meaning
      it is normally acceptable, but some other command has invalidated
      it in this case
      '''
      assert command in self.grammar
      assert 'detail' in self.grammar[command]
      return self.grammar[command]['detail'] == GrammarDetail.INVALIDATED

   def addRequirement(self, command, requirement):
      if command not in self.grammar:
         return False

      if requirement not in self.grammar:
         return False

      requirements = self.grammar[command].get('requires', [])
      requirements.append(requirement)
      # set it incase get() returned []
      self.grammar[command]['requires'] = requirements

      return True


   def getCommandGrammar(self, command):
      '''
      Return the grammar for the given command.

      >>> gd = GrammarDefinition()
      >>> gd.getCommandGrammar("reboot")
      {'args': {'--noeject': {'detail': 1}}, 'id': 'reboot'}
      '''

      assert command in self.grammar
      assert 'grammar' in self.grammar[command]

      return self.grammar[command]['grammar']()

   def bindCallback(self, command, action, func):
      '''
      Insert a callback into the grammar.

      >>> gd = GrammarDefinition()
      >>> cb = lambda: "Hello, World!"
      >>> gd.bindCallback("install", "environmentAction", cb)
      >>> gd.grammar["install"]["environmentAction"]()
      'Hello, World!'
      '''

      self.grammar[command][action] = func

   def getScriptedInstallGrammar(self):
      '''
      Returns a dictionary containing all of the commands in the grammar mapped
      to their definitions.  The command grammar definition consists of a
      dictionary with the following keys:

        descr        English description of the command.
        detail       The type of command (see GrammarDetail).
        grammar      A function that will return the argument grammar
                     definition for this command.
        alias        The command this command is an alias for.
        options      Tuple of strings that denote optional flags:
                      "multiple" -- the command can be used more than once.
        multiline    Indicates this command is followed by a multiline script
        onDuplicate  "error" or "warn" if this command is found twice
        requires     This command requires another command to be given.
        requiresMsg  Error message to use when a required command is not given.

      The "grammar" function for a supported command returns a dictionary with
      an "args" key that describe the arguments supported by the command.  The
      value for the "args" key is a dictionary with the following keys:

        valueRegex   Indicates that the argument should take a value and it
                     should match this regular expression.
        valueValidator
                     A function that does further validation on the argument
                     value.
        regexMsg     The error/warning message to use when a value does
                     not match.
        onRegexMismatch
                     Set to either "error" or "warn" to indicate what to do
                     in case a value does not match the valueRegex.
                     Defaults to "warn".
        onMissingValue
                     Set to either "error" or "warn" to indicate
                     in the case of an argument that SHOULD take a value,
                     what to do if a value is missing.
        onSuperfluous
                     Set to either "error" or "warn" to indicate
                     in the case of an argument that SHOULD NOT take a value,
                     what to do if a value is given.
        onDuplicate
                     Set to either "error" or "warn" to indicate what to do
                     when an argument is repeated
        noneValue    The default value is none is given by the user.
        defaultValue
                     When a valueRegex mismatch is detected and it is not an
                     error, this value should be used.
        invalids     A list of other arguments that become invalid when this
                     argument is used.
        requires     A list of other arguments that need to be used with this
                     argument.
        requiresMsg  Error message to use when a required argument is not
                     given.
        alias        This argument is an alias for another.

      >>> gd = GrammarDefinition()
      >>> sig = gd.getScriptedInstallGrammar()
      >>> sig["paranoid"]["detail"] == GrammarDetail.OPTIONAL
      True
      '''

      return {
         'auth': dict( detail=GrammarDetail.DEPRECATED ),
         'authconfig': dict( detail=GrammarDetail.DEPRECATED ),
         'autopart': dict( detail=GrammarDetail.DEPRECATED ),
         'autostep': dict( detail=GrammarDetail.DEPRECATED ),
         'bootloader': dict( detail=GrammarDetail.DEPRECATED ),
         'clearpart': dict(
            descr='Clear existing partitions on the disk',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getClearpartGrammar,
            options=['multiple'],
            requires=['install'],
         ),
         'cmdline': dict( detail=GrammarDetail.DEPRECATED ),
         'device': dict( detail=GrammarDetail.DEPRECATED ),
         'deviceprobe': dict( detail=GrammarDetail.DEPRECATED ),
         'dryrun': dict(
            descr='Do not actually perform the install',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getDryrunGrammar,
         ),
         'esxlocation': dict( detail=GrammarDetail.DEPRECATED ),
         'firewall': dict( detail=GrammarDetail.DEPRECATED ),
         'firewallport': dict( detail=GrammarDetail.DEPRECATED ),
         'firstboot': dict( detail=GrammarDetail.DEPRECATED ),
         'harddrive': dict( detail=GrammarDetail.DEPRECATED ),
         'ignoredisk': dict( detail=GrammarDetail.DEPRECATED ),
         'install': dict(
            descr='performs an installation on the disk with the default partition scheme',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getInstallGrammar,
            onDuplicate='error',
         ),
         'installorupgrade': dict(
            descr='try to perform an upgrade first, if unable, perform an install',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getInstallOrUpgradeGrammar,
            onDuplicate='error',
         ),
         'interactive': dict(detail=GrammarDetail.DEPRECATED),
         'keyboard': dict(
            descr='specify a keyboard type for the system',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getKeyboardGrammar,
         ),
         'lang': dict(detail=GrammarDetail.UNUSED,),
         'langsupport': dict(detail=GrammarDetail.UNUSED,),
         'lilo': dict(detail=GrammarDetail.DEPRECATED,),
         'lilocheck': dict(detail=GrammarDetail.DEPRECATED,),
         'logvol': dict(detail=GrammarDetail.DEPRECATED,),
         'mouse': dict(detail=GrammarDetail.DEPRECATED,),
         'network': dict(
            descr='setup a network address for ESXi',
            detail=GrammarDetail.OPTIONAL,
            grammar = self.getNetworkGrammar,
         ),
         'part': dict(
            descr='setup partioning for physical disks',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getPartitionGrammar,
            alias='partition',
            options=['multiple'],
            requires=['install'],
         ),
         'partition': dict(
            descr='setup partitioning for physical disks',
            detail=GrammarDetail.ALIAS,
            grammar=self.getPartitionGrammar,
            alias='part',
            options=['multiple'],
            requires=['install'],
         ),
         'paranoid': dict(
            descr='fail on warnings',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getParanoidGrammar,
         ),
         'partitionembed': dict(
            descr='use autopartitioning behavior like in ESXi Embedded',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getPartitionEmbedGrammar,
            requires=['install'],
         ),
         'raid': dict(detail=GrammarDetail.DEPRECATED,),
         'reboot': dict(
            descr='reboot the machine after the install is finished',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getRebootGrammar,
         ),
         'rootpw': dict(
            descr='setup the Root Password for the system',
            detail=GrammarDetail.REQUIRED,
            grammar=self.getRootpwGrammar,
         ),
         'skipx': dict(detail=GrammarDetail.DEPRECATED,),
         'text': dict(detail=GrammarDetail.DEPRECATED),
         'timezone': dict(detail=GrammarDetail.DEPRECATED),
         'upgrade': dict(
            descr='only perform an upgrade on the machine',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getUpgradeGrammar,
            onDuplicate='error',
            ),
         'virtualdisk': dict(detail=GrammarDetail.DEPRECATED),
         'vmaccepteula': dict(
            descr='Accept the VMware EULA',
            detail=GrammarDetail.REQUIRED,
            grammar=self.getVMAcceptEULAGrammar,
            alias='accepteula',
         ),
         'accepteula': dict(
            descr='Accept the VMware EULA',
            detail=GrammarDetail.ALIAS,
            grammar=self.getVMAcceptEULAGrammar,
            alias='vmaccepteula',
         ),
         'vmserialnum': dict(
            descr='Setup licensing for ESX',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getVMSerialNumGrammar,
            alias='serialnum',
         ),
         'serialnum': dict(
            descr='Setup licensing for ESX',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getVMSerialNumGrammar,
            alias='vmserialnum',
         ),
         'vnc': dict(detail=GrammarDetail.DEPRECATED),
         'volgroup': dict(detail=GrammarDetail.DEPRECATED),
         'xconfig': dict(detail=GrammarDetail.DEPRECATED),
         'xdisplay': dict(detail=GrammarDetail.DEPRECATED),
         'vmlicense': dict(detail=GrammarDetail.DEPRECATED),
         'zerombr': dict(detail=GrammarDetail.DEPRECATED),
         #
         # Special scriptedinstall keywords
         #
         '%include': dict(
            descr='Include a seperate scriptedinstall file',
            detail=GrammarDetail.OPTIONAL,
            grammar=self.getIncludeGrammar,
            alias='include',
            options=['multiple'],
         ),
         'include': dict(
            descr='Include a seperate scriptedinstall file',
            detail=GrammarDetail.ALIAS,
            grammar=self.getIncludeGrammar,
            alias='%include',
            options=['multiple'],
         ),
         '%packages': dict(detail=GrammarDetail.DEPRECATED),
         '%pre': dict(
            descr='Special commands to be executed pre-configuration' + \
                  ' and installation',
            detail=GrammarDetail.OPTIONAL,
            multiline=True,
            grammar=self.getPreSectionGrammar,
            options=['multiple'],
         ),
         '%post': dict(
            descr='Special commands to be executed post installation',
            detail=GrammarDetail.OPTIONAL,
            multiline=True,
            grammar=self.getPostSectionGrammar,
            options=['multiple'],
         ),
         '%firstboot': dict(
            descr='Special commands to be executed on first boot',
            detail=GrammarDetail.OPTIONAL,
            multiline=True,
            grammar=self.getFirstBootSectionGrammar,
            options=['multiple'],
         ),
         '%vmlicense_text': dict(detail=GrammarDetail.DEPRECATED),
      }


   def getClearpartGrammar(self):
      return {
         'id': 'clearpart',
         'args': {
                     '--all': dict(
                                  detail=GrammarDetail.OPTIONAL,
                               ),
                     '--alldrives': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     invalids=('--drives',
                                               '--firstdisk'),
                                     ),
                     '--drives': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     valueRegex='.+',
                                     invalids=('--ignoredrives', '--alldrives',
                                               '--firstdisk'),
                                     onDuplicate='error',
                                  ),
                     '--firstdisk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--alldrives', '--drives',
                                              '--ignoredrives',),
                                    noneValue='local,remote',
                                    valueRegex='.+',
                                    onDuplicate='error',
                                 ),
                     '--ignoredrives': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     valueRegex='.+',
                                     invalids=('--drives',
                                               '--firstdisk'),
                                  ),
                     '--initlabel': dict(
                                  detail=GrammarDetail.DEPRECATED,
                                     ),
                     '--overwritevmfs': dict(
                                   detail=GrammarDetail.OPTIONAL,
                                   ),
                  },
      }


   def getDryrunGrammar(self):
      return dict(id='dryrun', args={})


   def getIncludeGrammar(self):
      return {
         'id': 'include',
         'args': {},
         'hangingArg': {
            'filename': dict(
               detail=GrammarDetail.REQUIRED,
               valueRegex='.+',
               orientation=ArgumentOrientation.BACK)
            }}


   def getKeyboardGrammar(self):
      return {
         'id': 'keyboard',
         'args': {},
         'hangingArg': {
                           'keyboardtype': dict(
                              detail=GrammarDetail.REQUIRED,
                              valueRegex='.+',
                              orientation=ArgumentOrientation.BACK,
                            ),
                        },
      }


   def getInstallGrammar(self):
      return {
         'id': 'install',
         'args': {
                     '--drive': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    valueRegex='.+',
                                    alias='--disk',
                                    invalids=('--firstdisk',),
                                    onDuplicate='error',
                                 ),
                     '--disk': dict(
                                    detail=GrammarDetail.ALIAS,
                                    valueRegex='.+',
                                    alias='--drive',
                                    invalids=('--firstdisk',),
                                    onDuplicate='error',
                                 ),
                     '--firstdisk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--disk', '--drive',),
                                    noneValue='local,remote,usb',
                                    valueRegex='.+',
                                    onDuplicate='error',
                                 ),
                     '--overwritevmfs': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--preservevmfs'),
                                   ),
                     '--preservevmfs': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--overwritevmfs'),
                                   ),
                     '--overwritevsan': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--novmfsondisk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--preservevmfs'),
                                   ),
                     '--ignoressd': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--disk', '--drive'),
                                   ),
                     '--ignoreprereqwarnings': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--ignoreprereqerrors': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--server': dict(
                                  detail=GrammarDetail.DEPRECATED,
                                     ),
                     '--dir': dict(
                                  detail=GrammarDetail.DEPRECATED,
                                     ),
                  },
         'hangingArg': {
                           'cdrom': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'usb': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'nfs': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'url': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                        },
      }


   def getInstallOrUpgradeGrammar(self):
      return {
         'id': 'installorupgrade',
         'args': {
                     '--drive': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    valueRegex='.+',
                                    alias='--disk',
                                    invalids=('--firstdisk',),
                                    onDuplicate='error',
                                 ),
                     '--disk': dict(
                                    detail=GrammarDetail.ALIAS,
                                    valueRegex='.+',
                                    alias='--drive',
                                    invalids=('--firstdisk',),
                                    onDuplicate='error',
                                 ),
                     '--firstdisk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--disk', '--drive',),
                                    noneValue='local,remote,usb',
                                    valueRegex='.+',
                                    onDuplicate='error',
                                 ),
                     '--overwritevmfs': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--overwritevsan': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--ignoreprereqwarnings': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--ignoreprereqerrors': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--forcemigrate': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--server': dict(
                                  detail=GrammarDetail.DEPRECATED,
                                     ),
                     '--dir': dict(
                                  detail=GrammarDetail.DEPRECATED,
                                     ),
                  },
         'hangingArg': {
                           'cdrom': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'usb': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'nfs': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                           'url': dict(
                              detail=GrammarDetail.DEPRECATED,
                            ),
                        },
      }


   def getNetworkGrammar(self):
      return {
         'id': 'network',
         'args': {
                     '--bootproto': dict(
                                        detail=GrammarDetail.OPTIONAL,
                                        valueRegex=RegexLocator.networkproto
                                     ),
                     '--device': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     valueRegex='.+',
                                  ),
                     '--ip': dict(
                                 detail=GrammarDetail.OPTIONAL,
                                 valueValidator=validateIPString,
                              ),
                     '--gateway': dict(
                                      detail=GrammarDetail.OPTIONAL,
                                      valueValidator=validateGatewayString,
                                   ),
                     '--nameserver': dict(
                                   detail=GrammarDetail.OPTIONAL,
                                   valueValidator=validateMultipleIPsString,
                                      ),
                     '--nodns': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                 ),
                     '--netmask': dict(
                                      detail=GrammarDetail.OPTIONAL,
                                      valueValidator=validateNetmaskString,
                                   ),
                     '--hostname': dict(
                                 detail=GrammarDetail.OPTIONAL,
                                 valueValidator=validateHostname,
                                    ),
                     '--vlanid': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     valueValidator=validateVlanID
                                  ),
                     '--addvmportgroup': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     valueRegex=r'(0|1|true|false)',
                                     regexFlags=re.IGNORECASE,
                                  ),
                  },
      }



   def getPartitionGrammar(self):
      return {
         'id': 'part',
         'args': {
                     '--size': dict(
                                   detail=GrammarDetail.DEPRECATED,
                                   valueValidator=validateSize,
                                ),
                     '--grow': dict(
                                   detail=GrammarDetail.DEPRECATED,
                                ),
                     '--maxsize': dict(
                                      detail=GrammarDetail.DEPRECATED,
                                      valueValidator=validateSize,
                                   ),
                     '--ondisk': dict(
                                     detail=GrammarDetail.OPTIONAL,
                                     alias='--ondrive',
                                     valueRegex='.+',
                                     onDuplicate='error',
                                     invalids=('--onfirstdisk',),
                     ),
                     '--ondrive': dict(
                                      detail=GrammarDetail.ALIAS,
                                      alias='--ondisk',
                                      valueRegex='.+',
                                      onDuplicate='error',
                                      invalids=('--onfirstdisk',),
                                   ),
                     '--onfirstdisk': dict(
                                      detail=GrammarDetail.OPTIONAL,
                                      invalids=('--ondisk',),
                                      noneValue='local,remote',
                                      valueRegex='.+',
                                      onDuplicate='error',
                                   ),
                     '--fstype': dict(
                                     detail=GrammarDetail.DEPRECATED,
                                  ),
                  },
         'hangingArg': {
                           'mountpoint': dict(
                              detail=GrammarDetail.REQUIRED,
                              valueRegex=RegexLocator.mountpoint,
                              orientation=ArgumentOrientation.FRONT,
                              onRegexMismatch='error',
                           )
                        },
      }


   def getPartitionEmbedGrammar(self):
      return dict(id='partitionembed', args={})


   def getParanoidGrammar(self):
      return dict(id='paranoid', args={})


   def getPreSectionGrammar(self):
      return {
         'id': '%pre',
         'args': {
                     '--interpreter': dict(
                                          detail=GrammarDetail.OPTIONAL,
                                          valueRegex=RegexLocator.preInterpreter,
                                          regexMsg='interpreter "%(value)s" not found.',
                                          onRegexMismatch='error',
                               ),
                  },
         'hangingArg': {
                           'script': dict(
                               orientation=ArgumentOrientation.BACK,
                               detail=GrammarDetail.REQUIRED,
                               valueValidator=validateScript,
                            )
                        }
      }


   def getPostSectionGrammar(self):
      return {
         'id': '%post',
         'args': {
                     '--interpreter': dict(
                                          detail=GrammarDetail.OPTIONAL,
                                          valueRegex=RegexLocator.postInterpreter,
                                          regexMsg='interpreter "%(value)s" not found.',
                                          onRegexMismatch='error',
                                       ),
                     '--timeout': dict(
                                          detail=GrammarDetail.OPTIONAL,
                                          valueRegex='\d+',
                                    ),
                     '--ignorefailure': dict(
                                          detail=GrammarDetail.OPTIONAL,
                                          valueRegex='(true|false)',
                                          regexFlags=re.IGNORECASE,
                                    )
                  },
         'hangingArg': {
                           'script': dict(
                               orientation=ArgumentOrientation.BACK,
                               detail=GrammarDetail.REQUIRED,
                               valueValidator=validateScript,
                            )
                        }

      }

   def getFirstBootSectionGrammar(self):
      return {
         'id': '%firstboot',
         'args': {
                     '--interpreter': dict(
                                          detail=GrammarDetail.OPTIONAL,
                                          valueRegex=RegexLocator.firstBootInterpreter,
                                          regexMsg='interpreter "%(value)s" not found.',
                                          onRegexMismatch='error',
                                       ),
                  },
         'hangingArg': {
                           'script': dict(
                               orientation=ArgumentOrientation.BACK,
                               detail=GrammarDetail.REQUIRED,
                               valueValidator=validateScript,
                            )
                        }
      }


   def getRebootGrammar(self):
      return {
         'id': 'reboot',
         'args': {
                     '--noeject': dict(
                                      detail=GrammarDetail.OPTIONAL,
                                   ),
                  },
      }


   def getRootpwGrammar(self):
      return {
         'id': 'rootpw',
         'args': {
                     '--iscrypted': dict(
                        detail=GrammarDetail.OPTIONAL,
                     ),
                  },
         'hangingArg': {
                           'password': dict(
                               orientation=ArgumentOrientation.BACK,
                               detail=GrammarDetail.REQUIRED,
                               valueRegex='.*',
                            )
                        }

      }


   def getUpgradeGrammar(self):
      return {
         'id': 'upgrade',
         'args': {
                     '--drive': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    valueRegex='.+',
                                    alias='--disk',
                                    invalids=('--firstdisk', '--diskBootedFrom'),
                                    onDuplicate='error',
                                 ),
                     '--disk': dict(
                                    detail=GrammarDetail.ALIAS,
                                    valueRegex='.+',
                                    alias='--drive',
                                    invalids=('--firstdisk', '--diskBootedFrom'),
                                    onDuplicate='error',
                                 ),
                     '--firstdisk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--disk', '--drive', '--diskBootedFrom'),
                                    noneValue='local,remote,usb',
                                    valueRegex='.+',
                                    onDuplicate='error',
                                 ),
                     '--diskBootedFrom': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    invalids=('--disk', '--drive', '--firstdisk'),
                                   ),
                     '--overwritevmfs': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--savebootbank': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    valueRegex='.+',
                                    onDuplicate='error',
                                   ),
                     '--bootDiskMarker': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                    valueRegex='.+',
                                   ),
                     '--deletecosvmdk': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--ignoreprereqwarnings': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--ignoreprereqerrors': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                     '--forcemigrate': dict(
                                    detail=GrammarDetail.OPTIONAL,
                                   ),
                  },
      }


   def getVMAcceptEULAGrammar(self):
      return dict(id='vmaccepteula', args={})

   def getVMSerialNumGrammar(self):
      return {
         'id': 'vmserialnum',
         'args': {
                     '--esx': dict(
                                  detail=GrammarDetail.REQUIRED,
                                  valueRegex=RegexLocator.serialnum,
                                  regexMsg='serialnum / vmserialnum --esx value requires five five-character tuples separated by dashes',
                                  onRegexMismatch='error',
                               ),
                  },
      }




if __name__ == "__main__": #pragma: no cover
   import doctest
   doctest.testmod()
