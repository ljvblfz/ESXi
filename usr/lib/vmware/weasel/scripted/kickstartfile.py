#! /usr/bin/env python

from __future__ import print_function

import re
import sys
from itertools import takewhile

from weasel.log import log
from weasel.remote_files import isURL, remoteOpen
from weasel.exception import HandledError
from weasel.task_progress import taskProgress

TASKNAME = 'KICKSTART'
TASKDESC = 'Reading installation script'

class KickstartFile:

   def __init__(self, fileOrFilename):
      if hasattr(fileOrFilename, 'readlines'):
         self.lines = fileOrFilename.readlines()
         self.fileName = '<in-memory object>'
      else:
         self.fileName = fileOrFilename
         if isURL(self.fileName):
            taskProgress(TASKNAME, 1, 'Downloading file')
            log.info("Downloading file: %s", self.fileName)
            fp = remoteOpen(self.fileName)
            self.lines = fp.readlines()
            fp.close()
         else:
            taskProgress(TASKNAME, 1, 'Reading local file')
            try:
                log.info("Reading local file: %s", self.fileName)
                fp = open(self.fileName,'rb')
                self.lines = fp.readlines()
                fp.close()
            except IOError as ex:
                raise HandledError('Could not open file %s' % self.fileName,
                                   str(ex))

      self.lines = [line.replace(b'\r\n', b'\n') for line in self.lines]
      self.index = -1
      self.keyWords = ['%post', '%pre', '%packages',
                       '%vmlicense_text', '%firstboot', '%include', 'include']

   def __iter__(self):
      return self

   def getLineNumber(self):
      return self.index + 1
   lineNumber = property(getLineNumber)

   def next(self):
      '''
      Iterate over the lines in the file.
      Raises StopIteration when it reaches the end-of-file.
      '''

      self.index += 1
      try:
         return self.lines[self.index]
      except IndexError:
         self.index -= 1
         raise StopIteration()

   def __next__(self):
      '''Same as next(), for python3'''
      return self.next()

   def reset(self):
      '''Reset the file pointer to the beginning of the file.
      '''
      self.index = -1

   def _doesNotStartWithAKeyword(self, line):
      for keyword in self.keyWords:
         if line.decode().startswith(keyword):
            return False
      return True

   def getLinesUntilNextKeyword(self):
      r'''
      Return a string containing all the lines in the file up to the next
      keyword or end-of-file.  Possible keywords are:

        %post
        %pre
        %packages
        %vmlicense_text
        %firstboot
        %include
        include
      '''

      section = b''

      for line in takewhile(self._doesNotStartWithAKeyword, self):
         section += line

      if self.index < len(self.lines) - 1:
         self.index -= 1

      log.debug('section-contents: ' + repr(section))

      return section

if __name__ == "__main__": #pragma: no cover
   k = KickstartFile('example.ks')
   print(list(k))
   import doctest
   doctest.testmod()
