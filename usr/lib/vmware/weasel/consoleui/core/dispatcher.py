# -*- coding: utf-8 -*-

FIRST_STEP = 0
DISPATCH_NEXT = 1
DISPATCH_PREVIOUS = -1

class Dispatcher(object):
    def __init__(self):
        self.__direction = DISPATCH_NEXT
        self.__step = None

        self.__setCurrentStep(FIRST_STEP)

    def stepBack(self):
        self.__direction = DISPATCH_PREVIOUS
        self.moveStep()

    def stepForward(self):
        self.__direction = DISPATCH_NEXT
        self.moveStep()

    def moveStep(self):
        if self.__step == FIRST_STEP and \
            self.__direction == DISPATCH_PREVIOUS:
            pass
        else:
            self.__step = self.__step + self.__direction

    def __getCurrentStep(self):
        return self.__step

    def __setCurrentStep(self, step):
        self.__step = step

    currentStep = property(__getCurrentStep, __setCurrentStep)

