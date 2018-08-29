#! /usr/bin/env python

'''
Asynchronous, decoupled notification module
'''

from weasel.log import log
from weakref import WeakKeyDictionary

_listeners = WeakKeyDictionary()
_runningTasks = {}
_lock = False # not threadsafe, of course.
_pendingEvents = []

#------------------------------------------------------------------------------
def taskStarted(taskTitle, estimatedAmount=None, taskDesc=''):
    if taskTitle not in _runningTasks:
        newTask = Task(taskTitle, estimatedAmount, taskDesc)
        _runningTasks[taskTitle] = newTask
    else:
        log.warn('Running task restarting (%s)' % taskTitle)
        newTask = _runningTasks[taskTitle]
        newTask.restart()
        if estimatedAmount != None:
            newTask.reviseEstimate(estimatedAmount)
    _broadcastTaskStarted(newTask.title)

#------------------------------------------------------------------------------
def subtaskStarted(taskTitle, supertaskTitle, estimatedAmount=None,
                   share=0, taskDesc=''):
    if taskTitle not in _runningTasks:
        newTask = Task(taskTitle, estimatedAmount, taskDesc)
        _runningTasks[taskTitle] = newTask
    else:
        log.warn('Running task restarting (%s)' % taskTitle)
        newTask = _runningTasks[taskTitle]
        newTask.restart()
        if estimatedAmount != None:
            newTask.reviseEstimate(estimatedAmount)
    if supertaskTitle not in _runningTasks:
        log.warn('no supertask found for subtask')
        return
    else:
        supertask = _runningTasks[supertaskTitle]
        supertask.addSubtask(newTask, share)
    _broadcastTaskStarted(newTask.title)

#------------------------------------------------------------------------------
def reviseEstimate(taskTitle, estimate):
    if taskTitle not in _runningTasks:
        log.warn('No task found. Could not revise estimate.')
        return
    task = _runningTasks[taskTitle]
    task.reviseEstimate(estimate)

#------------------------------------------------------------------------------
def taskProgress(taskTitle, amountCompleted=1, msg=None):
    if taskTitle not in _runningTasks:
        log.debug('Progress happened on a task that has not started')
        return
    task = _runningTasks[taskTitle]
    task.progress(amountCompleted, msg)

#------------------------------------------------------------------------------
def taskFinished(taskTitle):
    if taskTitle not in _runningTasks:
        log.warn('A task finished that has not started')
        return
    task = _runningTasks[taskTitle]
    task.finish()

#------------------------------------------------------------------------------
def getTask(taskTitle):
    return _runningTasks[taskTitle]

#------------------------------------------------------------------------------
def getAmountOfWorkRemaining(taskTitle=None):
    if taskTitle == None:
        total = 0
        for task in _runningTasks:
            total += task.amountRemaining
        return total
    if taskTitle not in _runningTasks:
        log.warn('Can not get amount of work remaining for unknown task')
        return 0
    return _runningTasks[taskTitle].amountRemaining

#------------------------------------------------------------------------------
def getPercentageOfWorkRemaining(taskTitle=None):
    if taskTitle == None:
        total = 0
        remaining = 0
        for task in _runningTasks:
            remaining += task.amountRemaining
            total += task.estimatedTotal
        return float(remaining)/total
    if taskTitle not in _runningTasks:
        log.warn('Can not get percentage of work remaining for unknown task')
        return 0
    return _runningTasks[taskTitle].percentRemaining()


#------------------------------------------------------------------------------
def addNotificationListener(listener):
    enqueueEvent('_addNotificationListener', (listener,))
    consumeEvents()

def _addNotificationListener(listener):
    global _listeners
    _listeners[listener] = 1

#------------------------------------------------------------------------------
def removeNotificationListener(listener):
    enqueueEvent('_removeNotificationListener', (listener,))
    consumeEvents()

def _removeNotificationListener(listener):
    global _listeners
    try:
        del _listeners[listener]
    except KeyError:
        pass

#------------------------------------------------------------------------------
def _broadcastTaskStarted(taskTitle):
    enqueueEvent('notifyTaskStarted', (taskTitle,))
    consumeEvents()

#------------------------------------------------------------------------------
def _broadcastTaskProgress(taskTitle, amountCompleted):
    enqueueEvent('notifyTaskProgress', (taskTitle, amountCompleted))
    consumeEvents()

#------------------------------------------------------------------------------
def _broadcastTaskFinished(taskTitle):
    enqueueEvent('notifyTaskFinished', (taskTitle,))
    consumeEvents()

#------------------------------------------------------------------------------
def consumeEvents():
    global _lock
    global _pendingEvents
    if _lock:
        # tried to recursively enter consumeEvents
        return

    listenerMethods = ['notifyTaskStarted',
                       'notifyTaskProgress',
                       'notifyTaskFinished']
    _lock = True
    while _pendingEvents:
        currentEvents = list(_pendingEvents)
        _pendingEvents = []
        for funcName, args in currentEvents:
            if funcName in listenerMethods:
                # copy to ensure size doesn't change during iteration
                listenersCopy = list(_listeners.keys())
                for listener in listenersCopy:
                    method = getattr(listener, funcName)
                    method(*args)
            else: #else it is a module function
                func = globals()[funcName]
                func(*args)

            # Delete the task from _runningTasks only AFTER the listeners have
            # been notified.  This way if they call getTask() it will succeed.
            if funcName == 'notifyTaskFinished':
                taskTitle = args[0]
                global _runningTasks
                del _runningTasks[taskTitle]

    _lock = False

#------------------------------------------------------------------------------
def enqueueEvent(methodName, args):
    _pendingEvents.append((methodName, args))

#------------------------------------------------------------------------------
class Task(object):
    def __init__(self, title, estimatedTotal=None, desc=''):
        '''create a Task
        estimatedTotal is "number of work units" any arbitrary number will
        do, or leave as None
        '''
        self.title = title
        self.desc = desc
        self.subtasks = {}
        self.subtaskShares = {} #maps the subtask name to amount
        self.subtaskSharesRemaining = {}
        if estimatedTotal != None:
            assert estimatedTotal > 0, 'estimated total work must be > 0'
        self.estimatedTotal = estimatedTotal
        self._amountRemaining = estimatedTotal
        self.lastMessage = None

    def restart(self):
        self._amountRemaining = self.estimatedTotal
        self.subtaskSharesRemaining = self.subtaskShares.copy()

    def reviseEstimate(self, newEstimate):
        '''New information can cause estimated total work units to be revised
        '''
        self._amountRemaining = self.fractionRemaining() * newEstimate
        self.estimatedTotal = newEstimate
        _broadcastTaskProgress(self.title, 0)

    def addSubtask(self, subtask, share=0):
        '''Add a subtask.  The share is how many of the supertask's work units
        the subtask is responsible for
        '''
        if self.estimatedTotal == None:
            # previously there was no estimated total, so this share is our new
            # best estimate
            self.estimatedTotal = share
            self._amountRemaining = share
        assert share <= self._amountRemaining
        addNotificationListener(self)
        self.subtasks[subtask.title] = subtask
        self.subtaskShares[subtask.title] = share
        self.subtaskSharesRemaining[subtask.title] = share
        self._amountRemaining -= share

    def notifyTaskStarted(self, taskTitle):
        '''A subtask has started'''
        if taskTitle not in self.subtasks:
            return
        self.progress(0) # "touch" myself

    def notifyTaskProgress(self, taskTitle, amountCompleted):
        '''Progress has been made on a subtask'''
        if taskTitle not in self.subtasks:
            return
        subtask = self.subtasks[taskTitle]
        if taskTitle in self.subtaskShares:
            share = self.subtaskShares[taskTitle]
            shareRemaining = share * subtask.fractionRemaining()
            localAmount = self.subtaskSharesRemaining[taskTitle] -\
                          shareRemaining
            _broadcastTaskProgress(self.title, localAmount)
            self.subtaskSharesRemaining[taskTitle] = shareRemaining
        else:
            # "touch" myself
            _broadcastTaskProgress(self.title, 0)

    def notifyTaskFinished(self, taskTitle):
        '''A subtask has completed'''
        if taskTitle not in self.subtasks:
            return
        subtask = self.subtasks[taskTitle]
        if taskTitle in self.subtaskShares:
            # note, the subtask has already "claimed" (removed) it's share
            # from this task's original _amountRemaining, so we don't need
            # to remove any more from _amountRemaining.  Just deleting
            # the subtask from self.subtaskSharesRemaining will suffice.
            # but call self.progress(0) just to "touch" self.
            self.progress(0)
            del self.subtasks[taskTitle]
            del self.subtaskShares[taskTitle]
            del self.subtaskSharesRemaining[taskTitle]
            if not self.subtasks:
                removeNotificationListener(self)

    def progress(self, amountCompleted=1, msg=None):
        if self._amountRemaining != None and amountCompleted:
            self._amountRemaining -= amountCompleted
        _broadcastTaskProgress(self.title, amountCompleted)
        if msg:
            self.lastMessage = msg

    def finish(self):
        self._amountRemaining = 0
        _broadcastTaskFinished(self.title)
        if self.subtasks:
            self.subtasks = None
            removeNotificationListener(self)

    def fractionRemaining(self):
        '''returns a float between 0.0 and 1.0'''
        if self.estimatedTotal in (None, 0):
            return 1.0 # 100% remaining
        assert self.amountRemaining >= 0
        return float(self.amountRemaining)/self.estimatedTotal

    def percentRemaining(self):
        '''returns a float between 0.0 and 100.0'''
        return 100.0 * self.fractionRemaining()

    def getAmountRemaining(self):
        if self.estimatedTotal == None:
            return 1 # just one more thing to do: the whole task.

        # sum up the shares of work the subtasks are responsible for and
        # add it to the amount owned by this task itself
        sumRemaining = self._amountRemaining +\
                       sum(self.subtaskSharesRemaining.values())
        if sumRemaining <= 0:
            return 0 # 0 work units remaining (neg. work units makes no sense)
        else:
            return sumRemaining
    amountRemaining = property(getAmountRemaining)

