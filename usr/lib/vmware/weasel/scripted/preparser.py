#! /usr/bin/env python

'''Parser for ESX kickstart files.

This module parses files in a kickstart-like format and inserts the data into
the userchoices module.

See grammar.py
'''

import os
import sys
import re
import shlex
import itertools
from collections import defaultdict
import vmkctl
from .grammar import GrammarDetail, \
                    GrammarDefinition, \
                    ArgumentOrientation
from .util import logStuff, \
                 Result, \
                 makeResult, \
                 interpreters
from weasel.util import getMissingDevices, \
                        getNominalDevices
from . import kickstartfile

from weasel.consts import PRODUCT_SHORT_STRING, VMFS6
from weasel.exception import HandledError
from weasel.script import Script, FirstBootScript
from weasel.log import log
from weasel.remote_files import isURL
from weasel.users import cryptPassword, sanityCheckPassword
from weasel.devices import DiskSet
from weasel.datastore import DatastoreSet, checkForClearedVolume
from weasel.util.regexlocator import RegexLocator
from weasel.util import \
     execCommand, \
     loadVfatModule, \
     rescanVmfsVolumes, \
     diskfilter, \
     missingDeviceDrivers, \
     nominalDeviceDrivers, \
     isNOVA
from weasel.partition import \
     PartitionRequest, \
     PartitionRequestSet, \
     ScanError
from weasel import fsset
from weasel import userchoices
from weasel import networking
from weasel import upgrade
from weasel import esxlicense
from weasel import keyboard
from weasel import task_progress
from weasel import thin_partitions
import featureState

def findBootDiskVFAT():
    '''This only works when booted from a disk, it does NOT work when booted
    from a CD or otherwise from a dd image

    returns a devices.DiskDev object
    '''

    loadVfatModule()
    rescanVmfsVolumes()
    # TODO This should be put in a findBootDisk() function accessible
    #      to all the other Weasel modules

    bootDiskUUID = vmkctl.SystemInfoImpl().GetBootFileSystem()
    if hasattr(bootDiskUUID, 'get'):
        bootDiskUUID = bootDiskUUID.get()
    if bootDiskUUID == None:
        raise HandledError('Bootdisk UUID is not detected.')

    bootDiskUUID = bootDiskUUID.GetUuid()

    log.debug("Got bootDiskUUID: '%s'" % bootDiskUUID)

    si = vmkctl.StorageInfoImpl()
    vfats = [ptr.get() for ptr in si.GetVFATFileSystems()]

    bootFS = None
    for vfat in vfats:
        if vfat.GetUuid() == bootDiskUUID:
            bootFS = vfat
            break
    if not bootFS:
        raise HandledError('Could not find boot partition')

    bootPart = bootFS.GetHeadPartition().get()
    diskName = bootPart.GetDeviceName()
    log.debug("VUM Upgrade: Found boot disk: %s" % diskName)
    diskSet = DiskSet()
    return diskSet[diskName]

def makeDiskAliases(disks):
   '''Return a dictionary mapping common disk aliases to a canonical disk
   name.  The "disks" argument should be a weasel.devices.DiskSet instance

   example return value:
   { '/vmfs/devices/disks/mpx.vmhba1:C0:T0:L0': 'mpx.vmhba1:C0:T0:L0',
     'mpx.vmhba1:C0:T0:L0': 'mpx.vmhba1:C0:T0:L0',
     'vml.000000034211234': 'mpx.vmhba1:C0:T0:L0',
     ...
   }
   '''
   diskAliases = {}
   for disk in disks.values():
      diskAliases[disk.name] = disk.name
      if disk.path:
         diskAliases[disk.path] = disk.name
      if disk.consoleDevicePath:
         diskAliases[disk.consoleDevicePath] = disk.name
         m = re.match(r'/dev/(.+)', disk.consoleDevicePath)
         if m:
            diskAliases[m.group(1)] = disk.name
      for uid in disk.vmkLun.GetUids():
         diskAliases[uid] = disk.name
   return diskAliases

class ScriptedInstallPreparser:
   def __init__(self, fileName):

      self.grammarDefinition = GrammarDefinition()
      self._bind_to_grammar()

      self.numCommands = 0
      self.bumpTree = {}
      self.scriptedinstallFiles = []
      self.currentScriptedinstallFile = None

      self.mountPoints = []

      self.vmfsVolumes = {}
      self.vmdkDeviceName = None
      self.vmdkDevice = None

      self.unknownCommands = [] # keep track of any unknown commands

      # make multiple passes. On each pass, just parse commands from
      # one of the groups in self.commandOrder
      self.commandOrder = [ ['%pre'],
                            ['%include', 'include'],
                            ['install', 'upgrade', 'installorupgrade'],
                          ]
      # add the rest of the commands as their own group to commandOrder
      remaining = list(self.grammarDefinition.getScriptedInstallGrammar().keys())
      for command in itertools.chain(*self.commandOrder):
         remaining.remove(command)
      self.commandOrder.append(remaining)

      # track the command groups (as in self.commandOrder) as they're preparsed
      self.seenCommandGroups = []

      # a mapping from each scriptedinstallFile to the command groups that
      # have yet to be preparsed in it
      self.scriptedinstallFileToCatchUpCommands = defaultdict(lambda: [])

      self.disks = DiskSet(forceReprobe=True)
      self.installClaimedDisks = {} #for the 'partition' and 'install' commands
      self.partClaimedDisks = {} #for the 'partition' and 'install' commands
      self.diskAliases = makeDiskAliases(self.disks)

      task_progress.taskStarted(kickstartfile.TASKNAME, 1,
                                taskDesc=kickstartfile.TASKDESC)
      self.addKickstartFile(fileName)

   def parseAndValidate(self):
      r'''Combines the preParse() and overall validation into a single method.

      >>> ks = StringIO("install --disk=vml.0040")
      >>> sip = ScriptedInstallPreparser(ks)
      >>> result, errors, warnings = sip.parseAndValidate()
      >>> result == Result.FAIL
      True
      >>> errors
      [...vmaccepteula command was not specified...]

      >>> ks = StringIO('vmaccepteula\nrootpw password')
      >>> sip = ScriptedInstallPreparser(ks)
      >>> result, errors, warnings = sip.parseAndValidate()
      >>> errors
      []

      '''
      #>>> assert 'vmaccepteula command was not specified' in ''.join(errors)
      #>>> assert 'network command not specified' in ''.join(warnings)
      #>>> assert 'installation method not specified' in ''.join(warnings)

      (result, errors, warnings) = self.preParse()
      if result == Result.FAIL:
         return makeResult(errors, warnings)

      (result, validateErrors, validateWarnings) = self.validate(
                     self.grammarDefinition.grammar, list(self.bumpTree.keys()))

      return makeResult(errors + validateErrors, warnings + validateWarnings)


   def _bind_to_grammar(self):
      '''Inserts callbacks we use into the grammar definition.'''

      gd = self.grammarDefinition
      gd.bindCallback("clearpart", "environmentAction", self.doClearpart)
      gd.bindCallback("dryrun", "environmentAction", self.doDryrun)
      gd.bindCallback("install", "environmentAction", self.doInstall)
      gd.bindCallback("installorupgrade", "environmentAction", self.doInstallOrUpgrade)
      gd.bindCallback("keyboard", "environmentAction", self.doKeyboard)
      gd.bindCallback("network", "environmentAction", self.doNetwork)
      gd.bindCallback("paranoid", "environmentAction", self.doParanoid)
      gd.bindCallback("part", "environmentAction", self.doPartition)
      gd.bindCallback("partition", "environmentAction", self.doPartition)
      gd.bindCallback("reboot", "environmentAction", self.doReboot)
      gd.bindCallback("rootpw", "environmentAction", self.doRootpw)
      gd.bindCallback("upgrade", "environmentAction", self.doUpgrade)
      gd.bindCallback("accepteula", "environmentAction", self.doVMAcceptEULA)
      gd.bindCallback("vmaccepteula", "environmentAction", self.doVMAcceptEULA)
      gd.bindCallback("serialnum", "environmentAction", self.doVMSerialNum)
      gd.bindCallback("vmserialnum", "environmentAction", self.doVMSerialNum)
      gd.bindCallback("%pre", "environmentAction", self.doPreSection)
      gd.bindCallback("%post", "environmentAction", self.doPostSection)
      gd.bindCallback("%firstboot", "environmentAction", self.doFirstBootSection)

      gd.bindCallback("%include", "environmentAction", self.doInclude)
      gd.bindCallback("include", "environmentAction", self.doInclude)

   def addKickstartFile(self, fileName):
      '''Open a kickstart file and append it to self.scriptedinstallFiles.'''
      sFile = kickstartfile.KickstartFile(fileName)
      self.scriptedinstallFiles.append(sFile)
      seenCmdGroupsCopy = self.seenCommandGroups[:]
      self.scriptedinstallFileToCatchUpCommands[sFile] = seenCmdGroupsCopy
      return sFile


   def postValidate(self):
      '''Perform some extra global validation.'''

      errors = []
      warnings = []

      anUpgrade = userchoices.getUpgrade()

      if "network" not in self.bumpTree and not anUpgrade:
         warnings += [
            'network command not specified. Defaulting to DHCP.']

      if "vmaccepteula" not in self.bumpTree and not anUpgrade:
         errors += [
            'vmaccepteula command was not specified. You must read and accept '
            'the VMware ESX End User License Agreement by including '
            'the command in the scripted install script.']

      installOptions = ['install' in self.bumpTree,
                        'upgrade' in self.bumpTree,
                        'installorupgrade' in self.bumpTree]

      if installOptions.count(True) > 1:
         errors += ["More than one of 'install', 'upgrade', or "
                    "'installorupgrade' was specified. There can be only one."]

      return makeResult(errors, warnings)


   def preParse(self):
      '''Validates and loads a file into an in-memory structure
      that will be used to produce dispatchers for a scripted
      operation.
      '''

      assert len(self.scriptedinstallFiles) > 0

      errorsBuffer = []
      warningsBuffer = []

      def accum(newErrors, newWarnings):
         errorsBuffer.extend(newErrors)
         warningsBuffer.extend(newWarnings)

      self.seenCommandGroups = []

      # Note, this is tricky.  self.scriptedinstallFiles can get modified
      # by doInclude -- ie, a new file can be appended to the end.
      for currentGroup in self.commandOrder:
         log.info('Parsing commands: ' + str(currentGroup))
         for sFile in self.scriptedinstallFiles:
            log.info('Using ScriptedInstall file: ' + sFile.fileName)
            self.currentScriptedinstallFile = sFile

            # if the sFile was just added (eg, via %include), it will need
            # to preparse all the commands we've already been through, so
            # it needs to catch up
            catchUpCommands = self.scriptedinstallFileToCatchUpCommands[sFile]
            for cmdGroup in catchUpCommands + [currentGroup]:
               status, errors, warnings = self.singlePass(cmdGroup)
               accum(errors, warnings)
            self.scriptedinstallFileToCatchUpCommands[sFile] = []

         self.seenCommandGroups.append(currentGroup)

      # We've gotten to the end of all the scripted install files
      self.currentScriptedinstallFile = None
      if not errors:
         (_status, errors, warnings) = self.postValidate()
         accum(errors, warnings)

      warningsBuffer = ['warning:' + x for x in warningsBuffer]
      errorsBuffer = ['error:' + x for x in errorsBuffer]

      if userchoices.getParanoid() and warningsBuffer:
         errorsBuffer.append('error: got warnings during paranoid mode')

      return makeResult(errorsBuffer, warningsBuffer)

   def singlePass(self, onlyCommands):
      '''Scan through each line in the file, but only preparse the
      commands found in onlyCommands.  Just skip any others
      '''
      status = Result.SUCCESS
      errors = []
      warnings = []

      sFile = self.currentScriptedinstallFile # shorthand

      def decorateMessage(msg):
         # decorate the warnings and errors with the filename and linenumber
         return '%s:line %d: %s' % (sFile.fileName,
                                    sFile.lineNumber,
                                    msg)

      sFile.reset()

      for line in sFile:
         try:
            tokens = self.tokenizeLine(line)
         except Exception as msg:
            status = Result.FAIL
            errors.append(decorateMessage(str(msg)))
            break

         if not tokens:
            continue
         #just a simple check to see if it's ascii as expected.
         try:
            line.decode('ascii')
         except UnicodeDecodeError:
            msg = 'script file contains a non-ASCII character'
            warnings.append(decorateMessage(msg))

         if not self.grammarDefinition.isCommand(tokens[0]):
            # keep track of unknown commands so we don't repeat the warning
            if tokens[0] not in self.unknownCommands:
                warnings += ['unknown command "%s"' % tokens[0]]
                self.unknownCommands.append(tokens[0])
            continue

         if tokens[0] not in onlyCommands:
            continue

         status, newErrors, newWarnings = self.preParseCommandTokens(tokens)

         warnings += [decorateMessage(warning) for warning in newWarnings]
         errors += [decorateMessage(error) for error in newErrors]

         # don't keep going if we're in a failure state
         if errors or (userchoices.getParanoid() and warnings):
            break

      return status, errors, warnings


   def tokenizeLine(self, line):
      '''Method pulls line apart into tokens using shlex

      The command is always the first group of word characters
      found on the line.
      '''
      assert line is not None
      tokens = shlex.split(line.decode(), True)
      if tokens and self.grammarDefinition.isMultiline(tokens[0]):
         body = self.currentScriptedinstallFile.getLinesUntilNextKeyword()
         tokens.append(body.decode())
      return tokens


   def preParseCommandTokens(self, tokens):
      '''
      Dispatch to the correct parsing method based on the
      command
      '''
      command = tokens.pop(0)

      errors = []
      warnings = []

      log.debug('preparsing command: ' + command)
      self.numCommands += 1

      if self.numCommands > 256:
         errors += ['more than 256 commands were included in the'
                    ' kickstart file(s)']
         return makeResult(errors, warnings)

      if self.grammarDefinition.isDeprecated(command):
         warnings += ['command "%s" is deprecated and should not be used.' %\
                      command]
         return makeResult(errors, warnings)

      if self.grammarDefinition.isUnused(command):
         warnings += ['command "%s" is currently unused.' % command]
         return makeResult(errors, warnings)

      if self.grammarDefinition.isInvalidated(command):
         warnings += ['command "%s" is invalidated.' % command]

      commandGrammar = self.grammarDefinition.getCommandGrammar(command)
      assert commandGrammar
      assert commandGrammar['id'] in self.grammarDefinition.grammar

      (result, errors, warnings) = self.addBranch(commandGrammar, tokens)

      if errors:
         return makeResult(errors, warnings)

      if 'environmentAction' in self.grammarDefinition.grammar[command]:
         (result, errors, newWarnings) = \
             self.grammarDefinition.grammar[command]['environmentAction']()
         warnings += newWarnings

      return makeResult(errors, warnings)


   def addBranch(self, commandGrammar, args):
      '''Builds a bumpTree branch object and validates it against a known
      grammar.

      If a duplicate branch has been built for the same bumpTree the new
      branch is ignored.
      '''

      assert commandGrammar is not None
      assert args is not None

      (branch, (result, errors, warnings)) = \
         self.buildBranch( commandGrammar, args )

      warningBuffer = warnings

      if not result:
         return (Result.FAIL, errors, warningBuffer)

      (result, errors, warnings) \
                    = self.validate(commandGrammar['args'], branch, 'argument')

      warningBuffer += warnings

      if not result:
         return (Result.FAIL, errors, warningBuffer)

      cmdname = commandGrammar['id']
      options = self.grammarDefinition.grammar[cmdname].get('options', [])
      onDup = self.grammarDefinition.grammar[cmdname].get('onDuplicate', 'warn')

      if 'multiple' in options:
         if cmdname not in self.bumpTree:
            self.bumpTree[cmdname] = []
         self.bumpTree[cmdname].append(branch)
      else:
         if cmdname in self.bumpTree:
            msg = 'command "%s" was already specified.' % cmdname
            if onDup == 'warn':
               warningBuffer.append(msg + ' Using the latest value.')
            else:
               errors.append(msg)
               result = Result.FAIL
         self.bumpTree[cmdname] = branch

      return (result, errors, warningBuffer)


   def validate(self, args, branch, grammarDesc='command'):
      '''Method validates the constraints of a grammar against a specified
      branch.
      '''

      errors = []
      warnings = []

      keys = list(args.keys())
      keys.sort()
      for option in keys:
         definition = args[option]
         detail = definition['detail']

         log.debug('Validating ' + grammarDesc + ": " + option)

         if 'alias' in definition and option != definition['alias']:
            alias = definition['alias']
         else:
            alias = None

         optionPresent = (option in branch) or (alias and alias in branch)

         assert (detail != GrammarDetail.UNUSED) or (not optionPresent)

         if detail == GrammarDetail.REQUIRED and not optionPresent:
            msg = grammarDesc +' "%s" required but not found' % (option)
            errors.append(msg)
            log.debug(msg)
         elif optionPresent:
            if detail == GrammarDetail.DEPRECATED:
               msg = option + ' is deprecated'
               warnings.append(msg)
               log.debug(msg)
            elif detail == GrammarDetail.OPTIONAL:
               log.debug(grammarDesc + ' is optional')

            if 'requires' in definition:
               requires = definition['requires']
               for r in requires:
                  log.debug('Requires: ' + r)
                  if r not in branch:
                     msg = definition.get(
                        'requiresMsg',
                        '%(grammarDesc)s "%(option)s" requires '
                        '%(grammarDesc)s: "%(dep)s".')
                     errors.append(msg % {
                        'grammarDesc': grammarDesc,
                        'option': option,
                        'dep': r,
                     })
            if 'invalids' in definition:
               invalids = definition['invalids']
               for other in invalids:
                  if other in branch and option in branch:
                     # if "other" has an "invalids" list with "option" in it,
                     # we would get two near-duplicate error msgs, which
                     # is ugly for the user.  So sort the args, making the
                     # errors duplicate.  Duplicates are filtered out later.
                     arg1, arg2 = sorted((option, other))
                     errors.append(grammarDesc +
                                   (' "%s" is invalid when used with argument'
                                   ' "%s".') % (arg1, arg2))
      # filter out duplicates, keep only unique errors
      errors = list(set(errors))
      return makeResult(errors, warnings)

   def buildBranch( self, commandGrammar, args ):
      '''Method iterates over the arguments passed and adds them
      to a hash of hashes based on their validity. The following
      rules are checked...

         1) The argument must exist in the commands grammar
         2) The value of an argument must exist if a valueRegex
            is specified in the commands grammar
         3) Duplicate arguments or aliases to arguments are ignored
      '''

      errors = []
      warnings = []
      branch = {}

      def _partitionArguments(args):
         '''Partition the given argument list into a list of tuples for each
         recognized flag argument and a list of any extra arguments.
         '''

         argTuples = []
         extraArgs = []

         for index, arg in enumerate(args):
            assert arg is not None

            key = arg
            value = None

            if '=' in arg:
               key, value = arg.split('=', 1)

            if key not in commandGrammar['args']:
               extraArgs.append((index, arg))
               continue

            argTuples.append((key, value, commandGrammar['args'][key]))

         return (argTuples, extraArgs)

      def _collectHangingArgs(argTuples, extraArgs):
         '''Process the hanging args from the grammar given the arguments left
         over after the flags have been pulled out.
         '''

         if 'hangingArg' not in commandGrammar:
            return

         orientationMsg = ('Expected to find %s argument to command "%s" at'
                           ' the %s of the argument list. Using value "%s"'
                           ' found at position %d instead.')
         hangingArgs = commandGrammar['hangingArg']

         for extarg in extraArgs[:]:
            index, arg = extarg
            if arg in hangingArgs:
               if hangingArgs[arg]['detail'] == GrammarDetail.DEPRECATED:
                  warnings.append(arg + ' is deprecated for ' +
                                commandGrammar['id'] + ' command.')
                  extraArgs.remove(extarg)

         for arg in hangingArgs:
            if hangingArgs[arg]['detail'] == GrammarDetail.DEPRECATED:
               continue
            try:
               if hangingArgs[arg]['orientation'] == ArgumentOrientation.FRONT:
                  index, value = extraArgs.pop(0)
                  if index != 0:
                     warnings.append(orientationMsg %
                                     (arg, commandGrammar['id'], 'front',
                                     value, index))
               else:
                  index, value = extraArgs.pop()
                  if index != len(args) - 1:
                     warnings.append(orientationMsg %
                                     (arg, commandGrammar['id'], 'end',
                                     value, index))

               argTuples.append((arg, value, hangingArgs[arg]))
            except IndexError:
               if hangingArgs[arg]['detail'] == GrammarDetail.REQUIRED:
                  errors.append(arg + ' not specified for ' +
                                commandGrammar['id'] + ' command.')
                  continue


      argTuples, extraArgs = _partitionArguments(args)

      _collectHangingArgs(argTuples, extraArgs)

      for index, arg in extraArgs:
         msg = 'unknown argument "' + arg + \
               '" to command "' + commandGrammar['id'] \
               + '"'
         if commandGrammar['id'] == 'installorupgrade' and arg == '--ignoressd':
            errors.append(msg)
         else:
            log.warn('bogus token found: "' + arg + '"')
            warnings.append(msg)

      for key, value, argGrammar in argTuples:
         #TODO: break the body of this down some more

         hasValueRegex = ('valueRegex' in argGrammar)
         hasValueValidator = ('valueValidator' in argGrammar)
         if value is None:
            value = argGrammar.get('noneValue')

         if (not value) and (hasValueRegex or hasValueValidator):
            log.warn('valid token found but no valid value was set: ' + key)
            msg = ('argument "%s" to command "%s" is missing a value.'
                   % (key, commandGrammar['id']))

            if argGrammar.get('onMissingValue', 'warn') == 'warn':
               warnings.append(msg)
            else:
               errors.append(msg)
            continue

         if value and not (hasValueRegex or hasValueValidator):
            log.warn('token does not take a value: ' + key)
            msg = ('argument "%s" to command "%s" does not take a value.'
                   % (key, commandGrammar['id']))

            if argGrammar.get('onSuperfluous', 'warn') == 'warn':
               warnings.append(msg)
            else:
               errors.append(msg)
            continue

         if (hasValueRegex):
            regex = argGrammar['valueRegex']
            match = re.match( '^(' + regex + ')$',
                              value,
                              argGrammar.get('regexFlags', 0))

            if not match:
               log.warn('invalid token value set: %s=%s' % (key, repr(value)))
               fmt = argGrammar.get(
                  'regexMsg',
                  'argument "%(key)s" to command "%(command)s" set but an '
                  'invalid value was specified.')
               msg = fmt % {
                  'key' : key,
                  'command' : commandGrammar['id'],
                  'value' : value
               }

               if argGrammar.get('onRegexMismatch', 'warn') == 'warn':
                  warnings.append(msg)
               else:
                  errors.append(msg)

               if 'defaultValue' in argGrammar:
                  value = argGrammar['defaultValue']
               else:
                  continue

         if hasValueValidator:
            (_result, verrors, vwarnings) = argGrammar['valueValidator'](
               key, value)
            errors += verrors
            warnings += vwarnings

         #
         # key is in grammar and value is valid (set or None)
         #

         alias = argGrammar.get('alias', None)

         if (key in branch) or (alias and (alias in branch)):
            if alias:
               display = '(%s or %s)' % (key, alias)
            else:
               display = '"%s"' % key
            msg = ('duplicate argument %s specified for command "%s".'
                   % (display, commandGrammar['id']))

            if argGrammar.get('onDuplicate', 'warn') == 'warn':
               warnings.append(msg)
            else:
               errors.append(msg)
         else:
            branch[key] = value

      # careful not to expose passwords
      if commandGrammar['id'] not in ["rootpw", "bootloader"]:
         log.debug('Branch Created: ' + str(branch))

      return (branch, makeResult(errors, warnings))

   def doInclude(self):
      errors = []
      warnings = []

      ksTask = task_progress.getTask(kickstartfile.TASKNAME)
      ksTask.reviseEstimate(ksTask.estimatedTotal + 1)
      lastFileName = self.currentScriptedinstallFile.fileName

      branch = self.bumpTree['include'][-1]

      filename = branch['filename']


      if not isURL(filename) and filename[0] not in ['/', '.']:
         # stay compatible with the way 3.5 did it
         log.warn('implicit relative paths get rewritten as paths from the '
                  ' root of the local disk')
         filename = '/' + filename
      elif filename[0] == '.':
         filename = os.path.join(os.path.dirname(lastFileName), filename)
      try:
         sFile = self.addKickstartFile(filename)
      except (IOError, HandledError) as e:
         errors += [str(e)]

      return makeResult(errors, warnings)


   ##################################################################
   ##################################################################
   #         Environment setup for specific commands                #
   ##################################################################
   ##################################################################

   def doClearpart(self):
      errors = []
      warnings = []

      branch = self.bumpTree['clearpart'][-1]

      specifiedDiskNames = list(self.disks.keys())

      for disk in self.disks.values():
         if disk.isControllerOnly():
            specifiedDiskNames.remove(disk.name)

      whichParts = userchoices.CLEAR_PARTS_ALL

      if isNOVA():
         novaWarningMsg = self.getMissingWarning('vmhba')
      else:
         novaWarningMsg = None

      if '--ignoredrives' in branch:
         for diskName in branch['--ignoredrives'].split(','):
             diskName = diskName.strip()
             if diskName not in self.diskAliases:
                errors.append('clearpart --ignoredrives= specified, but'
                              ' drive "' + diskName + '" was not found on'
                              ' the system.')
                if novaWarningMsg:
                  warnings.append(novaWarningMsg)
             elif self.diskAliases[diskName] not in specifiedDiskNames:
                warnings.append('clearpart --ignoredrives= specified, but'
                                ' drive "%s" was already given.' % diskName)
             else:
                specifiedDiskNames.remove(self.diskAliases[diskName])
      elif '--drives' in branch:
         specifiedDiskNames = []
         for diskName in branch['--drives'].split(','):
            diskName = diskName.strip()
            if diskName not in self.diskAliases:
               errors.append('clearpart --drives= specified, but'
                             ' drive "' + diskName + '" was not found on'
                             ' the system.')
               if novaWarningMsg:
                   warnings.append(novaWarningMsg)
            elif self.diskAliases[diskName] in specifiedDiskNames:
               warnings.append('clearpart --drives= specified, but'
                               ' drive "%s" was already given.' % diskName)
            elif self.diskAliases[diskName] in userchoices.getDrivesInUse():
               errors.append('clearpart --drives= specified, but'
                             ' clearing drive "%s" is not allowed.' % diskName)
            else:
               specifiedDiskNames.append(self.diskAliases[diskName])
      elif '--alldrives' in branch:
         # We'll trim out any USB disks if they're with 'loop'.
         # This check is a bit generic and will cause false positives when a
         # user has more than one USB stick connected, has a bootable installer
         # USB, and wishes to 'clearpart' on all disks.  In that case, we won't
         # 'clearpart' any of the USB disks.
         for diskName in specifiedDiskNames:
            diskDev = self.disks[diskName]
            if diskDev.isUSB and \
               diskDev.getPartitionSet().partedPartsTableType == 'loop':
               log.info("Not clearing USB disk: '%s'" % diskName)
               specifiedDiskNames.remove(diskName)
         pass
      elif '--firstdisk' in branch:
         filterList = diskfilter.getDiskFilters(branch['--firstdisk'])
         firstDisk = self._firstDisk(filterList)
         if not firstDisk:
            errors.append('clearpart --firstdisk specified, but no suitable'
                          ' disk was found.')
         else:
            specifiedDiskNames = [firstDisk.name]
            log.info("clearpart --firstdisk == %s" % str(firstDisk))
      else:
         errors.append('clearpart requires one of the following arguments:'
                       ' --alldrives, --firstdisk, --ignoredrives=, --drives=')

      if '--overwritevmfs' not in branch:
         for diskName in specifiedDiskNames:
            try:
               partSet = self.disks[diskName].getPartitionSet()
            except ScanError as ex:
               log.warn('Partition scanning error on disk %s (%s)' %
                        (diskName, str(ex)))
               partSet = None
            if partSet:
               for part in partSet:
                  if isinstance(part.getFileSystem(), fsset.vmfsFileSystem):
                     errors.append('clearpart --overwritevmfs not specified and'
                                   ' partition %d on %s is of type VMFS' %
                                   (part.partitionId, diskName))
            else:
               errors.append('clearpart --overwritevmfs not specified and'
                             ' partitions on %s could not be scanned' %
                             (diskName))

      if errors:
         return (Result.FAIL, errors, warnings)

      prevChoice = userchoices.getClearPartitions()
      if prevChoice:
         specifiedDiskNames += prevChoice['drives']
      userchoices.setClearPartitions(specifiedDiskNames, whichParts)

      return makeResult([], warnings)


   def doDryrun(self):
      userchoices.setDryrun(True)
      return (Result.SUCCESS, [], [])


   def validateInstallArgs(self, branch, key):
      errors = []
      warnings = []

      log.debug("validating install: %s" % branch)

      if isNOVA():
         warningMsg = self.getCombinedWarning()
         if warningMsg:
            errors.append('%s specified, but the operation is not supported '
                          'on this system. There are devices which either '
                          'have no drivers available or have a driver '
                          'with limited functionality.' % key)
            warnings.append(warningMsg)

      diskName = None
      if '--drive' in branch:
         diskName = branch['--drive']
      elif '--disk' in branch:
         diskName = branch['--disk']
      elif '--firstdisk' in branch:
         if '--ignoressd' in branch:
            userchoices.setIgnoreSSD(True)
         else:
            userchoices.setIgnoreSSD(False)

         filterList = diskfilter.getDiskFilters(branch['--firstdisk'])
         firstDisk = self._firstDisk(filterList)
         if not firstDisk:
            errors.append('%s --firstdisk specified, but no suitable '
                          'disk was found.' % key)
         else:
            diskName = firstDisk.name
            log.info("%s --firstdisk == %s" % (key, str(firstDisk)))

      if not diskName and not errors:
         errors.append('%s requires --disk or --firstdisk' % key)

      if diskName and diskName not in self.diskAliases:
         if '--drive' in branch:
            diskOrDrive = '--drive'
         else:
            diskOrDrive = '--disk'

         availableDisks = "\n".join([k.name for k in self.disks.values()])

         errors.append('%s %s= specified, but drive "%s" was not '
                       'found on the system. \n\nThe available disk(s) are:\n\n%s'
                       % (key, diskOrDrive, diskName, availableDisks))

      if '--ignoreprereqwarnings' in branch:
         userchoices.setIgnorePrereqWarnings(True)
      else:
         userchoices.setIgnorePrereqWarnings(False)

      if '--ignoreprereqerrors' in branch:
         userchoices.setIgnorePrereqErrors(True)
      else:
         userchoices.setIgnorePrereqErrors(False)

      return diskName, errors, warnings

   def doInstall(self):
      branch = self.bumpTree['install']
      diskName, errors, warnings = self.validateInstallArgs(branch, 'install')
      if errors:
         return makeResult(errors, warnings)

      return self.chooseInstall('install', diskName, branch)

   def chooseInstall(self, key, diskName, branch):
      errors = []
      warnings = []

      userchoices.setInstall(True)

      canonicalName = self.diskAliases[diskName]
      drive = self.disks[canonicalName]

      upgrade.checkForPreviousInstalls(drive)

      if '--preservevmfs' in branch:
         userchoices.setPreserveVmfs(True)
         if not drive.vmfsLocation:
            warnings.append('%s --preservevmfs specified but no VMFS '
                            'partition found on %s.' % (key, diskName))
         else:
            if not drive.canSaveVmfs:
               errors.append('%s --preservevmfs specified but VMFS '
                             'partition on %s cannot be saved.'
                             % (key, diskName))

      elif '--overwritevmfs' not in branch:
         userchoices.setPreserveVmfs(False)
         if drive.vmfsLocation:
            errors.append('%s --overwritevmfs not specified but'
                          ' %s contains a VMFS partition'
                          % (key, diskName))

      if '--overwritevsan' in branch:
          userchoices.setPreserveVsan(False)
          if not drive.vsanClaimed:
              errors.append('%s --overwritevsan specified but disk %s is not'
                              'claimed by vSAN.' % (key, diskName))

      if '--novmfsondisk' in branch:
          userchoices.setCreateVmfsOnDisk(False)
          userchoices.setPreserveVmfs(False)
          if drive.vmfsLocation and '--overwritevmfs' not in branch:
             errors.append('%s --overwritevmfs not specified but'
                           ' %s contains a VMFS partition and --novmfsondisk'
                           ' specified'
                           % (key, diskName))

      if errors:
         return makeResult(errors, warnings)

      MIN_INSTALL_DISK_SIZE = thin_partitions.MIN_EMBEDDED_SIZE

      if drive.getSizeInMebibytes() < MIN_INSTALL_DISK_SIZE:
         errors.append("The disk (%s) specified in %s is too small"
                        % (diskName, key))

      if not drive.supportsVmfs and '--novmfsondisk' not in branch:
         warnings.append("The disk (%s) specified in %s does not"
                       " support VMFS" % (diskName, key))

      if drive.name in self.partClaimedDisks:
         errors.append('The same disk has been chosen for part and %s.'
                       ' Disk %s claimed by branch %s.' %
                       (key, drive, self.partClaimedDisks[drive.name]))

      self.installClaimedDisks = {drive.name:branch} #there can be only one!
      userchoices.setEsxPhysicalDevice(drive.name)

      log.debug('chooseInstall branch: '+str(branch))

      return makeResult(errors, warnings)


   def doKeyboard(self):
      '''The keyboardtype value can be either the human-readable name
      or the filename.  eg, 'Dvorak' or 'dvorak.map.gz'
      '''
      branch = self.bumpTree['keyboard']
      keyboardStr = branch['keyboardtype']

      for key in keyboard.Keymaps.keys():
         if key == keyboardStr or keyboard.Keymaps.get(key) == keyboardStr:
            keyName = keyboard.Keymaps.get(key)
            userchoices.setKeyboard(keyName)
            break
      else:
         return (Result.WARN,
                 [],
                 ['invalid keyboard type "%s" was specified. Using default.' %
                  keyboardStr])

      return (Result.SUCCESS, [], [])


   def doNetwork(self):
      warnings = []
      errors = []
      branch = self.bumpTree['network']

      if isNOVA():
         novaWarningMsg = self.getMissingWarning('vmnic')
      else:
         novaWarningMsg = None

      if '--bootproto' not in branch:
         warnings.append('no bootproto set. Defaulting to DHCP.')
         bootproto = userchoices.NIC_BOOT_DHCP
      else:
         bootproto = branch['--bootproto']

      if bootproto == userchoices.NIC_BOOT_DHCP:
         if '--ip' in branch:
            errors.append('bootproto was set to DHCP but "--ip=" was set.')
         if '--netmask' in branch:
            errors.append('bootproto was set to DHCP but "--netmask=" was set.')
         if '--gateway' in branch:
            errors.append('bootproto was set to DHCP but "--gateway=" was set.')
      else:
         if '--ip' not in branch:
            errors.append('bootproto was set to static but "--ip=" was not set.')

      if '--device' in branch:
         deviceName = branch['--device'].strip()
         if ':' in deviceName:
            # assume it is a MAC address
            device = networking.findPhysicalNicByMacAddress(deviceName)
         else:
            device = networking.findPhysicalNicByName(deviceName)
         if not device:
            errors.append('bootproto --device= specified, but'
                          ' "%s" was not found on the system.' % deviceName)
            if novaWarningMsg:
               warnings.append(novaWarningMsg)
         elif not device.IsLinkUp():
            warnings.append('bootproto --device=%s specified, but the'
                            ' link was not active.  Check that the cable'
                            ' is plugged in.'
                            % deviceName)
      else:
         log.info('No NIC specified.')
         netInfo = vmkctl.NetworkInfoImpl()
         device = netInfo.GetBootNic().get()
         if not device:
            log.info('Boot NIC (BOOTIF) was not set.')
            devices = networking.getPhysicalNics()
            if not devices:
               errors.append('No network adapters were found.')
               if novaWarningMsg:
                  warnings.append(novaWarningMsg)
            else:
               device = networking.getPluggedInPhysicalNic()
               if not device:
                  msg = 'No plugged in network adapters were found.'
                  log.warn(msg)
                  warnings.append(msg)
                  if novaWarningMsg:
                     warnings.append(novaWarningMsg)
               device = devices[0]

      if errors:
         return makeResult(errors, warnings)


      hostname = nameserver1 = nameserver2 = gateway = netmask = ip = None
      if bootproto == userchoices.NIC_BOOT_DHCP:
         if '--hostname' in branch:
            warnings.append('bootproto was set to DHCP but'
                            ' "--hostname=" was set. Hostnames are'
                            ' ignored with DHCP.')
         if '--nameserver' in branch:
            warnings.append('bootproto was set to DHCP but'
                            ' "--nameserver=" was set. Nameservers'
                            ' are ignored with DHCP.')

      else:

         ip = branch['--ip'].strip()

         if '--hostname' not in branch:
            warnings.append('bootproto was set to static but "--hostname=" '
                            'was not set. Hostname will be set automatically.')
            hostname = 'localhost'
         else:
            hostname = branch['--hostname'].strip()

         if '--nameserver' not in branch:
            warnings.append('bootproto was set to static but "--nameserver="'
                            ' was not set. Not using a nameserver.')
         else:
            nameserver = branch['--nameserver'].split(',')
            nameserver1 = nameserver[0].strip()
            if len(nameserver) > 1:
               nameserver2 = nameserver[1].strip()

         if '--netmask' not in branch:
            netmask = networking.utils.calculateNetmask(ip)
            warnings.append('--bootproto was set to static but'
                            ' "--netmask=" was not set. Setting'
                            ' netmask to %s.' % netmask)
         else:
            netmask = branch['--netmask'].strip()

         if '--gateway' not in branch:
            gateway = networking.utils.calculateGateway(ip, netmask)
            warnings.append('bootproto was set to static but'
                            ' "--gateway=" was not set. Setting'
                            ' gateway to %s.' % gateway)
         else:
            gateway = branch['--gateway'].strip()

         try:
            networking.utils.sanityCheckIPSettings(ip, netmask, gateway)
         except ValueError as ex:
            raise HandledError(str(ex))

      vlanID = 0
      if '--vlanid' in branch:
         vlanID = branch['--vlanid'].strip()

      if '--addvmportgroup' in branch:
         addVmPortGroup = branch['--addvmportgroup'].lower().strip()
         userchoices.setAddVmPortGroup(addVmPortGroup in ['1', 'true'])

      userchoices.setVmkNetwork(gateway, nameserver1, nameserver2, hostname)

      for vmknicChoice in userchoices.getVmkNICs():
         if vmknicChoice['device'].GetName() == device.GetName():
            userchoices.delVmkNIC(vmknicChoice)

      userchoices.addVmkNIC(device, vlanID, bootproto, ip, netmask)

      return makeResult(errors, warnings)


   def doParanoid(self):
      userchoices.setParanoid(True)
      return (Result.SUCCESS, [], [])


   def _firstDisk(self, filterList, isUpgrade=False):
      '''Return the first disk in the list produced by running the given
      list of filter functions over the list of eligible disks.

      Must always give the same output given the same input, otherwise
      clearpart --firstdisk=... and partition --onfirstdisk=... will not
      work together.
      '''

      esxFilter = diskfilter.getDiskFilters('esx')[0]
      ssdFilter = lambda disk: not disk.isSSD
      eligibleDisks = thin_partitions.getEligibleDisks()

      cache = {}
      for diskFilter in filterList:
         filteredDisks = diskFilter(eligibleDisks, cache)

         # We have additional checks to do if the user wants to ignore SSD
         # disks.
         if userchoices.getIgnoreSSD():
            filteredDisks = [disk for disk in filteredDisks if ssdFilter(disk)]

         # Now, if we're upgrading, we want to also check if the disk has any
         # variant of ESX, and return only the list of disks that are valid for
         # upgrade.
         if isUpgrade:
            filteredDisks = esxFilter(filteredDisks, cache)

         if filteredDisks:
            log.debug("First disk found: %s" % str(filteredDisks[0]))
            return filteredDisks[0]

      log.debug("First disk not found")
      return None


   def doPartition(self):
      errors = []
      warnings = []

      branch = self.bumpTree['part'][-1]
      mntPoint = branch['mountpoint']

      if '--ondisk' in branch:
         onDisk = branch['--ondisk']
      elif '--ondrive' in branch:
         onDisk = branch['--ondrive']
      elif '--onfirstdisk' in branch:
         filterList = diskfilter.getDiskFilters(branch['--onfirstdisk'])
         firstDisk = self._firstDisk(filterList)
         if not firstDisk:
            errors.append('part --onfirstdisk specified, but no suitable '
                          'disk was found.')
         else:
            onDisk = firstDisk.name
            log.info("part firstdisk == %s" % str(firstDisk))
      else:
         errors.append('"--ondisk", "--ondrive", or "--onfirstdisk" required,'
                       ' but not found.')

      if errors:
         return makeResult(errors, warnings)

      if onDisk not in self.diskAliases:
         if '--ondrive' in branch:
            diskOrDrive = '--ondrive'
         else:
            diskOrDrive = '--ondisk'
         if isNOVA():
            warningMsg = self.getMissingWarning('vmhba')
            if warningMsg:
               warnings.append(warningMsg)
         errors.append('part "%s=" specified, but drive "%s" was not '
                       'found on the system.' % (diskOrDrive, onDisk))
      else:
         onDisk = self.diskAliases[onDisk]

      if errors:
         return makeResult(errors, warnings)

      log.info("Scripted: Disk is going to be partitioned with VMFS6")
      fsType = 'vmfs6'

      fsTypeObj = fsset.getVmfsFileSystemInstance(fsType)

      # We'll only partition the disk if either it's already empty or if it is
      # ordered to be cleared
      clearedDriveNames = userchoices.getClearPartitions().get('drives', [])

      # XXX not sure what all the constraints are on a volume name
      try:
         #mntPoint = mntPoint.strip()
         fsset.vmfsFileSystem.sanityCheckVolumeLabel(mntPoint)

         datastoreSet = DatastoreSet()
         existingDS = datastoreSet.getEntryByName(mntPoint)
         DSIsCleared = checkForClearedVolume(clearedDriveNames,
                                             datastoreSet,
                                             mntPoint)

         if (mntPoint in self.vmfsVolumes
             or (existingDS and not DSIsCleared)):
            errors.append('VMFS volume (%s) already exists.' % mntPoint)
         else:
            self.vmfsVolumes[mntPoint] = onDisk
            fsTypeObj.volumeName = mntPoint
      except ValueError as msg:
         errors.append(str(msg))

      mntPoint = None

      if not errors and mntPoint:
         self.mountPoints.append(mntPoint)

      if errors:
         return makeResult(errors, warnings)

      if not self.disks[onDisk].supportsVmfs:
         errors.append('vmfs is not supported on drive "%s"' % onDisk)
         return makeResult(errors, warnings)

      disk = self.disks[onDisk]
      try:
         partSet = disk.getPartitionSet()
      except ScanError as ex:
         partSet = None
         warnings.append('Partition scanning error on disk %s (%s)' %
                         (disk, ex))

      if disk.name in self.installClaimedDisks:
         errors.append('The same disk has been chosen for part and install.'
                       ' Disk %s claimed by branch %s.' %
                       (disk, self.installClaimedDisks[disk.name]))

      # VMFS is the only allowed partition type and you can't have > 1 VMFS
      # part on a disk, so don't allow the user to put 2 parts.
      if disk.name in self.partClaimedDisks:
         errors.append('The same disk has been chosen twice for part'
                       ' Disk %s claimed by branch %s.' %
                       (disk, self.partClaimedDisks[disk.name]))

      # Error if the disk already has a partition
      if (disk.name not in clearedDriveNames
          and partSet
          and len(partSet.getPartitions(showFreeSpace=False)) > 0):
         errors.append('The chosen disk (%s) already has partitions.'
                       ' The disk must either have clearpart set or have no'
                       ' partitions.' % disk)

      if userchoices.checkPhysicalPartitionRequestsHasDevice(onDisk):
         reqset = userchoices.getPhysicalPartitionRequests(onDisk)
      else:
         reqset = PartitionRequestSet(deviceName=disk.name)
         userchoices.setPhysicalPartitionRequests(onDisk, reqset)

#      primaryPartition = ('--asprimary' in branch)

      reqset.append(PartitionRequest(mountPoint=mntPoint,
                                     fsType=fsTypeObj,
                                     drive=disk))

      self.partClaimedDisks[disk.name] = branch

      return makeResult(errors, warnings)


   def validateUpgradeArgs(self, branch, key):
      errors = []
      warnings = []

      log.debug("validating upgrade: %s" % branch)

      if '--ignoreprereqwarnings' in branch:
         userchoices.setIgnorePrereqWarnings(True)
      else:
         userchoices.setIgnorePrereqWarnings(False)

      if '--ignoreprereqerrors' in branch:
         userchoices.setIgnorePrereqErrors(True)
      else:
         userchoices.setIgnorePrereqErrors(False)

      if '--forcemigrate' in branch:
         userchoices.setForceMigrate(True)
      else:
         userchoices.setForceMigrate(False)

      diskNameError = False
      diskName = None
      diskOrDrive = None
      if '--drive' in branch:
         diskName = branch['--drive']
         diskOrDrive = '--drive'
      elif '--disk' in branch:
         diskName = branch['--disk']
         diskOrDrive = '--disk'
      elif '--firstdisk' in branch:
         diskOrDrive = '--firstdisk'

         if isNOVA():
            warningMsg = self.getMissingWarning('vmhba')
            if (warningMsg):
               msg = ('%s --firstdisk specified, but there are missing '
                      'HBA driver(s) in this installer.  The --firstdisk '
                      'option cannot be used because disk enumeration '
                      'may not be reliable.' % key)
               warnings.append(warningMsg)
               errors.append(msg)
               diskNameError = True

         if not diskNameError:
            filterList = diskfilter.getDiskFilters(branch['--firstdisk'])
            firstDisk = self._firstDisk(filterList, isUpgrade=True)

            if not firstDisk:
               if not filterList:
                  msg = ('%s --firstdisk specified, but no suitable'
                         ' disk was found.' % key)
               else:
                  msg = ('%s --firstdisk specified, but no suitable'
                         ' disk for filter "%s" was found.'
                         % (key, branch['--firstdisk']))

               errors.append(msg)
               diskNameError = True
            else:
               diskName = firstDisk.name

            if diskNameError and key == 'installorupgrade':
               # TODO: Make a custom HandledError just for this case.
               raise HandledError(msg)
      elif '--diskBootedFrom' in branch:
         userchoices.setVumEnvironment(True)
         diskOrDrive = '--diskBootedFrom'
         if '--bootDiskMarker' in branch:
            # TODO: extend the bootDiskMarker feature to ESXi as well.  This
            #       will involve getting mtools into the install environment
            #       so that we can read files off the VFAT partitions
            log.info('VUM Upgrade.  Finding the ESX Classic boot disk')
            try:
               raise HandledError('--bootDiskMarker option not implemented')
            except Exception as ex:
               errors.append(str(ex))
               diskNameError = True
         else: # upgrading from ESXi
            log.info('VUM Upgrade.  Finding the ESXi boot disk')
            try:
               saveBootbank = branch['--savebootbank']
               log.debug("Saving bootbank: %s" % saveBootbank)
               userchoices.setSaveBootbankUUID(saveBootbank)

               bootDisk = findBootDiskVFAT()
               bootDisk.containsEsx.esxi = True
               diskName = bootDisk.name
            except Exception as ex:
               errors.append(str(ex))
               diskNameError = True

      if not diskOrDrive:
         errors.append('%s requires --drive, --disk, or --firstdisk'
                       % key)
      elif not diskName and not diskNameError:
         errors.append('%s %s specified, but disk name could not be determined'
                       % (key, diskOrDrive))
      elif diskName and diskName not in self.diskAliases:
         availableDisks = "\n".join([k.name for k in self.disks.values()])

         errors.append('%s %s= specified, but drive "%s" was not '
                       'found on the system. \n\nThe available disk(s) are:\n\n%s'
                       % (key, diskOrDrive, diskName, availableDisks))
         if isNOVA():
            warningMsg = self.getMissingWarning('vmhba')
            if warningMsg:
               warnings.append(warningMsg)
      return diskName, errors, warnings

   def getMissingWarning(self, aliasType):
      warningMsg = None
      deviceList = getMissingDevices(aliasType)
      if deviceList:
         warningMsg = ('\n\nThis system image lacks drivers '
                       'for these device(s):\n\n    %s'
                       '\n\nYou may need to use an installer image '
                       'containing the necessary driver(s).\n\n' %
                       deviceList)
         log.debug(warningMsg)

      return warningMsg

   def getCombinedWarning(self):
      warningMsg = None
      nominalDeviceList = getNominalDevices()
      missinglDeviceList = getMissingDevices()
      if nominalDeviceList or missinglDeviceList:
         nominalMsg = missingMsg = ''
         if nominalDeviceList:
            nominalMsg = ('\n\nThis system image contains drivers '
                          'with limited functionality for these '
                          'devices(s):\n\n    %s' % nominalDeviceList)
         if missinglDeviceList:
            missingMsg = ('\n\nThis system lacks drivers '
                          'for these ' 'devices(s):\n\n    %s' %
                          missinglDeviceList)
         warningMsg = nominalMsg + missingMsg
         log.debug(warningMsg)

      return warningMsg

   def chooseUpgrade(self, key, diskName):
      errors = []
      warnings = []

      userchoices.setUpgrade(True)
      userchoices.setPreserveVmfs(True)

      canonicalName = self.diskAliases[diskName]
      drive = self.disks[canonicalName]

      userchoices.setEsxPhysicalDevice(drive.name)

      upgrade.checkForPreviousInstalls(drive, forceRecheck=True)

      # First check if there is any install of ESXi 5.x, if not, we bail.
      if not drive.containsEsx:
         errors.append("%s specified, but no versions of ESXi were found on disk:"
                        " %s" % (key, diskName))
      elif isNOVA() and not drive.containsEsx.bootbankIsRecent:
         # When upgrading to native only builds, we also need to validate
         # that the bootbank has valid state.
         errors.append("%s specified, but the bootbank on disk %s is not "
                       "valid." % (key, diskName))
      elif drive.containsEsx.version < (6, 0,):
         errors.append("{0} specified, but ESXi of version 6.0 or greater was"
                       " not found on disk: {1}. A direct upgrade from ESX/ESXi"
                       " on this system to {2} is not supported. \n\n A"
                       " fresh {2} install is required, which includes the"
                       " option to preserve the VMFS datastore or overwrite the"
                       " VMFS datastore. Or, first upgrade to ESXi 6.0 or later"
                       " then upgrade to {2}.".format(key,
                                                      diskName,
                                                      PRODUCT_SHORT_STRING))

      if not drive.canSaveVmfs and drive.vmfsLocation is not None:
         loc = drive.vmfsLocation[0]
         errors.append("%s specified, but cannot save VMFS partition. "
                       "Start sector of VMFS is %s" % (key, loc))

      # update the grammar
      # upgrades allow/disallow different commands from installs
      invalid = GrammarDetail.INVALIDATED
      for command in ['install', 'rootpw', 'network', 'keyboard',
                      'vmserialnum', 'clearpart', 'part',
                     ]:
         self.grammarDefinition.grammar[command]['detail'] = invalid

      return makeResult(errors, warnings)

   def doUpgrade(self):
      branch = self.bumpTree['upgrade']
      diskName, errors, warnings = \
            self.validateUpgradeArgs(branch, 'upgrade')

      if errors:
         userchoices.setUpgrade(True)
         return makeResult(errors, warnings)

      resultType, errors, moreWarnings = self.chooseUpgrade('upgrade', diskName)
      warnings += moreWarnings

      return makeResult(errors, warnings)


   def doInstallOrUpgrade(self):
      userchoices.setInstallOrUpgrade(True)
      branch = self.bumpTree['installorupgrade']
      upgrading = True
      errors = warnings = []

      try:
         diskName, errors, warnings = \
                  self.validateUpgradeArgs(branch, 'installorupgrade')
      # Ideally, we'll only have this exception raised from validateUpgradeArgs
      # if we couldn't find a firstdisk, then it and only it, can be caught here.
      except HandledError as ex:
         log.debug("validating upgrade for installorupgrade failed, trying"
                   " install (%s)" % str(ex))
         splitDiskOpts = branch['--firstdisk'].split(',')
         firstDiskOpts = [ opt.strip() for opt in splitDiskOpts ]
         # If it's empty, pass in any defaults.
         if not firstDiskOpts:
             firstDiskOpts = ['local', 'remote', 'usb']
         branch['--firstdisk'] = ','.join(firstDiskOpts)
         upgrading = False

      if errors:
         log.debug('validating upgrade for installorupgrade failed '
                   'with errors. Not trying install.')
         return makeResult(errors, warnings)

      if upgrading:
         canonicalName = self.diskAliases[diskName]
         drive = self.disks[canonicalName]
         upgrade.checkForPreviousInstalls(drive, forceRecheck=True)

      if (upgrading and
          ((not isNOVA() and drive.containsEsx) or
           (isNOVA() and drive.canUpgradeToNOVA()))):

         log.debug('choosing upgrade for installorupgrade')
         subResult = self.chooseUpgrade('installorupgrade', diskName)
         warnings += subResult[2]

         return makeResult(subResult[1], warnings)
      else:
         if upgrading:
            log.debug('installorupgrade specified, but upgrade cannot be '
                      'performed. Hence trying install.')
         diskName, errors, warnings = self.validateInstallArgs(
                                             branch,
                                             'installorupgrade')
         if errors:
            return makeResult(errors, warnings)

         return self.chooseInstall('installorupgrade', diskName, branch)


   def doReboot(self):
      branch = self.bumpTree['reboot']
      userchoices.setReboot(True)
      userchoices.setNoEject('--noeject' in branch)

      return (Result.SUCCESS, [], [])


   def doRootpw(self):

      branch = self.bumpTree['rootpw']
      password = branch['password']

      errors = []
      warnings = []

      crypted = False
      if '--iscrypted' in branch:
         crypted = True

      if crypted:
         # If the password is encrypted ...
         # if not (md5 compliant
         #         or sha512 compliant
         #         or crypted compliant):
         #     do stuffs.
         if not ((re.match('^(' + RegexLocator.md5 + ')$', password) is not None)
                 or (re.match('^(' + RegexLocator.sha512 + ')$', password) is not None)
                 or (not password.startswith(('$1$', '$6$'),) and len(password) == 13)):
            errors.append('crypted password is not valid.')

      if not crypted:
         try:
            sanityCheckPassword(password, pwqcheck=True)
         except ValueError as msg:
            errors.append(str(msg))

      if errors:
         return (Result.FAIL, errors, warnings)

      if not crypted:
         password = cryptPassword(password, userchoices.ROOTPASSWORD_TYPE_SHA512)

      if password.startswith('$1$'):
         userchoices.setRootPassword(password, \
                                     userchoices.ROOTPASSWORD_TYPE_MD5)
      elif password.startswith('$6$'):
         userchoices.setRootPassword(password, \
                                     userchoices.ROOTPASSWORD_TYPE_SHA512)
      else:
         userchoices.setRootPassword(password, \
                                     userchoices.ROOTPASSWORD_TYPE_CRYPT)

      if warnings:
         return (Result.WARN, [], warnings)

      return (Result.SUCCESS, [], [])


   def doVMAcceptEULA(self):
      userchoices.setAcceptEULA(True)
      return (Result.SUCCESS, [], [])

   def doVMSerialNum(self):
      warnings = []
      errors = []
      branch = self.bumpTree['vmserialnum']

      serialNumber = branch['--esx']
      try:
         esxlicense.checkSerialNumber(serialNumber)
      except esxlicense.LicenseException as e:
         errors.append(str(e))
         return makeResult(errors, warnings)

      userchoices.setSerialNumber(serialNumber)
      return makeResult(errors, warnings)

   def doPreSection(self):
      preScript, result = self.doMultilineCommand('%pre')
      _success, errors, warnings = result
      if preScript:
         userchoices.addPreScript(preScript)

         log.debug('Running pre script: %s' % str(preScript))
         # %pre scripts cause errors even if --ignorefailure=true
         exMsg = None
         try:
             retval = preScript.run()
         except Exception as ex:
             retval = None
             exMsg = str(ex)
             log.exception(ex)
         if retval != 0:
             errors.append('"%pre" script returned with an error.')
             if exMsg:
                errors.append('Exception message: '+ exMsg)

         # The %pre script may have added new devices.
         self.disks = DiskSet(forceReprobe=True)
         self.diskAliases = makeDiskAliases(self.disks)
      return makeResult(errors, warnings)

   def doPostSection(self):
      postScript, result = self.doMultilineCommand('%post')
      if postScript:
         userchoices.addPostScript(postScript)

      return result


   def doMultilineCommand(self, cmd):
      branch = self.bumpTree[cmd][-1]

      assert branch is not None, 'internal error: branch is None'

      errors = []
      warnings = []
      if '--interpreter' in branch:
         interp = interpreters[branch['--interpreter']]
      else:
         warnings.append('interpreter not defined. Defaulting to busybox')
         interp = interpreters['busybox']

      if 'script' in branch.keys():
         script = branch['script']
      else:
         script = ''

      if len(script) > 0:
         inChroot = False

         timeoutInSecs = 0
         if cmd == '%post' and '--timeout' in branch:
            try:
               timeoutInSecs = int(branch['--timeout'])
            except ValueError:
               errors.append('invalid timeout value for %post')

         ignoreFailure = False
         if (cmd == '%post' and
             branch.get('--ignorefailure', 'false').lower() == 'true') or \
             cmd == '%pre':
            ignoreFailure = True

         group = None
         if cmd == '%post':
            group = 'post'
         elif cmd == '%pre':
            group = 'pre'

         scriptFile = Script(script,
                             interp,
                             inChroot,
                             timeoutInSecs,
                             ignoreFailure,
                             group)
      else:
         scriptFile = None

      log.debug('scripts: ' + repr(scriptFile))

      return (scriptFile, makeResult(errors, warnings))


   def doFirstBootSection(self):
      branch = self.bumpTree['%firstboot'][-1]

      assert branch is not None, 'internal error: branch is None'

      errors = []
      warnings = []

      if '--interpreter' not in branch:
         warnings.append('interpreter not defined. Defaulting to busybox')
      interpName = branch.get('--interpreter', 'busybox')
      interp = interpreters[interpName]

      script = branch['script']

      if len(script) < 1:
         log.debug('No script found for %%firstboot in %s'
                   % str(self.currentScriptedInstallFile))
         return makeResult(errors, warnings)

      scriptFile = FirstBootScript(script, interp)

      log.debug('scripts: ' + repr(scriptFile))

      userchoices.addFirstBootScript(scriptFile)
      return makeResult(errors, warnings)




#####################################################################
#                  Launcher code for Debugging                      #
#####################################################################
#####################################################################

class Usage(Exception): #pragma: no cover
   def __init__(self, msg):
      self.msg = msg


def main(argv=None): #pragma: no cover
   import getopt
   if not argv:
      argv = sys.argv
   try:
      try:
         opts, args = getopt.getopt(argv[1:], "f", ["file"])
      except getopt.error as msg:
         raise Usage(msg)

      scriptedinstall = ScriptedInstallPreparser(args[0])

      log.info('Preparsing ...')
      (result, errors, warnings) = scriptedinstall.preParse()
      logStuff(result, errors, warnings, 'Preparse problems...')
      log.info('Completed parsing all scriptedinstall files')

      if not result:
         log.error('Load failed due to previous errors')
      else:
         log.info('Validating ...')
         (result, errors, warnings) = \
            scriptedinstall.validate(scriptedinstall.grammarDefinition.grammar,
                                     list(scriptedinstall.bumpTree.keys()))

         logStuff(result, errors, warnings, 'Validation problems...')

         if not result:
            log.error('Validation failed due to previous errors')

      log.debug(list(scriptedinstall.bumpTree.items()))

      scriptedinstall = ScriptedInstallPreparser(args[0])
      scriptedinstall.parseAndValidate()

   except Usage as err:
      log.error(err.msg)
      return 2


if __name__ == "__main__": #pragma: no cover
   import weasel.util
   weasel.util.init(log)

   log.info('Doing doctests...')
   import doctest
   doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE|doctest.ELLIPSIS)

   sys.exit(main())

