
###############################################################################
# Copyright (c) 2008-2009 VMware, Inc.
#
# This file is part of Weasel.
#
# Weasel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# version 2 for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
from __future__ import print_function

import string
import sys
import traceback
import os
import signal

DEBUG = False

class HandledError(Exception):
    '''Base class which can be picked up to trap errors correctly
       in the UI'''
    def __init__(self, shortMessage, longMessage=''):
        self.shortMessage = shortMessage
        self.longMessage = longMessage

    def __str__(self):
        return 'Error (see log for more info):\n%s\n%s' % \
               (self.shortMessage, self.longMessage)

class InstallationError(Exception):
    def __init__(self, actionMsg, innerException=None):
        Exception.__init__(self, str(innerException))

        self.actionMsg = actionMsg
        self.innerException = innerException
        if innerException:
            _, _, self.innerTrace = sys.exc_info()

def handleException(installMethod, exceptType, value, trace,
                    traceInDetails=True):

    sys.excepthook = sys.__excepthook__

    details = ''.join(
        traceback.format_exception(exceptType, value, trace))

    if hasattr(installMethod, 'exceptionDialog'):
        installMethod.exceptionDialog(details)

    print(details)

    import pdb
    pdb.pm()

    os.kill(os.getpid(), signal.SIGKILL)

class StayOnScreen(Exception):
    def __init__(self):
        self.args = ()

class InstallCancelled(Exception):
    pass
