# -*- coding: utf-8 -*-

from .dispatcher import Dispatcher

from .console_exceptions import CommandNotFoundException, VMVisorInstallerException

from weasel import userchoices
from weasel.log import log

class Install(object):
    """Install
    This is the base class from which all installs inherit.  The child class
    should override the Steps variable, which is an ordered list of the steps
    which the installer will perform."""

    steps = []

    def __init__(self):
        if self.__class__ == Install:
            raise VMVisorInstallerException("Trying to instantiate abstract class Install")

        self._Dispatcher = Dispatcher()

    def start(self, data = None):
        """start
        Begin executing the installation steps.  It will step through each step
        listed in the Steps member variable, terminating once the last step has
        executed."""
        # We'll use the 'data' just for stepping forward and any other
        # information relating to the UI, all installer choices should be placed
        # into the userchoices singleton.
        if data:
            if 'StepForward' not in data:
                data['StepForward'] = True
        else:
            data = { 'StepForward' : True }

        while True:
            # XXX: This whole part of deciding whether to skip the step or not
            # should be refactored.  Perhaps adding some callback to the
            # StepType would help.
            try:
                # Are we upgrading?
                upgradeChoice = userchoices.getUpgrade()

                if self._Dispatcher.currentStep == len(self.steps):
                    break

                curStep, stepType = self.steps[self._Dispatcher.currentStep]

                # If the user isn't upgrading and the current step is used for
                # upgrade, skip it.
                if upgradeChoice and not stepType['upgrade']:
                    log.debug("User is upgrading and encountered a non upgrade"
                              " step, skipping step %s" % self._Dispatcher.currentStep)

                    if data['StepForward']:
                        self._Dispatcher.stepForward()
                        continue
                    else:
                        # Step back until we're good.
                        self._Dispatcher.stepBack()
                        continue

                # If the user is stepping back, make sure they aren't hitting
                # any warning/error screens again.
                if stepType['info'] and not data['StepForward']:
                    self._Dispatcher.stepBack()
                    continue

                # Make sure that we step forward from now.
                data['StepForward'] = True

                log.debug("Dispatching step %i" % (self._Dispatcher.currentStep))

                data = curStep(data)

                log.debug("'data' dict contains: %s" % data)

                if data['StepForward']:
                    self._Dispatcher.stepForward()
                else:
                    self._Dispatcher.stepBack()

            except KeyboardInterrupt:
                # trap ^C
                log.debug("Received Interrupt Signal - Ignored")
                continue
            except EOFError:
                # trap ^D
                log.debug("Received EOF Signal - Ingored")
                continue

    def modifyInstallSteps(self, data):
        """modifyInstallSteps
        Examines the data dictionary for the ModifyInstallSteps key then parses
        the value for an options dictionary that will be used to guide the
        modification of the Install Steps."""
        pass

