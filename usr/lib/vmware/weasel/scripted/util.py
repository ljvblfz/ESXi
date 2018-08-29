#! /usr/bin/env python

import sys
from weasel.log import log


# TODO: this should probably be somewhere else
interpreters = {
   # The -l should not be here.  However, there is a certain class of customers
   # who will not include absolute path names for executables in their firstboot
   # scripts and GSS will get the call when this doesn't work
   'busybox': '/bin/sh -l',
   'python': '/usr/bin/python',
}

class Result:
   FAIL = 0
   SUCCESS = 1
   WARN = 2

def makeResult(errors, warnings):
   '''
   Return a tuple containing the appropriate result code, a list of errors, and
   a list of warnings.

   >>> makeResult([], [])
   (1, [], [])
   >>> makeResult(["error: the computer is on fire"], [])
   (0, ['error: the computer is on fire'], [])
   >>> makeResult(["error: something bad"], ["warning: power failure"])
   (0, ['error: something bad'], ['warning: power failure'])
   >>> makeResult([], ["warning: power failure"])
   (2, [], ['warning: power failure'])
   '''

   if len(errors) > 0:
      return (Result.FAIL, errors, warnings)

   if len(warnings) > 0:
      return (Result.WARN, [], warnings)

   return (Result.SUCCESS, [], [])

# TODO: Once I am done debugging I can remove this
def logStuff(result, errors, warnings, desc='Unknown'): #pragma: no cover
   if not result or errors:
      logElements( (errors,), log.error, desc)

   if result == Result.WARN or warnings:
      logElements( (warnings,), log.warning, desc)


# TODO: Once I am done debugging I can remove this
def logElements(elements, func, desc='Unknown'): #pragma: no cover
   log.debug(desc)

   for element in elements:
      typeStr = type( element )
      func(str(typeStr) + ':' + str(element))

if __name__ == "__main__": #pragma: no cover
   import doctest
   doctest.testmod()
