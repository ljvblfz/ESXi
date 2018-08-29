############################################################################
# shaved_weasel
# a trimmed-down weasel
#
from __future__ import print_function

import getopt
import sys
import time
import traceback

import vmkctl

from weasel import userchoices # always import via weasel.
from weasel.exception import HandledError
from weasel.log import log
from weasel.util import prompt
from consts import ExitCodes
import process_end
import boot_cmdline

sys.path.append("scripted")

def dumpExceptionInfo(ex):
    log.debug('An exceptional situation was encountered.'
              ' Weasel does not know how to handle this.'
              ' Terminating.')
    log.debug('The class of the exception was: %s' % str(ex.__class__))
    log.debug('The exception was: %s' % str(ex))
    log.debug('Dumping userchoices')
    log.debug(userchoices.dumpToString())
    log.debug('\n************* UNHANDLED WEASEL EXCEPTION **************')
    log.debug(traceback.format_exc())
    log.debug('**************************************************\n')

def parseArgsToUserChoices(argv):
    try:
        (opts, args) = getopt.getopt(argv[1:], "htds:p:",
                          ['help', 'debug', 'debugui',
                           'script=', 'debugpatch='])
    except getopt.error as e:
        sys.stderr.write("error: %s\n" % str(e))
        sys.exit(ExitCodes.WAIT_THEN_REBOOT)

    # let shell options go last so they may override boot cmdline options
    opts = list(boot_cmdline.getOptionDict().items()) + opts

    log.debug('command line options: %s' % str(opts))

    for opt, arg in opts:
        runMode = userchoices.getRunMode().get('runMode') # default is None
        if (opt == '-t' or opt == '--text'):
            userchoices.setRunMode(userchoices.RUNMODE_TEXT)
        elif (opt == '--debugui'):
            # interactive UI beats debug UI
            if runMode != userchoices.RUNMODE_TEXT:
                userchoices.setRunMode(userchoices.RUNMODE_DEBUG)
        elif (opt == '-d' or opt == '--debug'):
            userchoices.setDebug(True)
        elif (opt == '-s' or opt == '--script'):
            userchoices.setRootScriptLocation(arg)
            # debug UI beats scripted UI
            if runMode != userchoices.RUNMODE_DEBUG:
                userchoices.setRunMode(userchoices.RUNMODE_SCRIPTED)
        elif (opt == '--debugpatch'):
            userchoices.setDebugPatchLocation(arg)
        elif (opt == '--compresslevel'):
            userchoices.setCompresslevel(arg)

userInterface = None
def main(argv):
    global userInterface

    try:
        if time.time() < 0:
            raise HandledError('System (BIOS) time is set to unsupported value',
                               'System time should be set to the current date')

        parseArgsToUserChoices(argv)

        if userchoices.getDebug():
            # Only import debugging if specified
            # We want to ensure that the debugging module has minimal impact
            # because debug mode is not a supported installation method
            import debugging
            debugging.init()

        runModeChoice = userchoices.getRunMode()
        if not runModeChoice:
            log.warn("User has not chosen a Weasel run mode.")
            log.info("Weasel run mode defaulting to Text.")
            runMode = userchoices.RUNMODE_TEXT
        else:
            runMode = runModeChoice['runMode']

        if runMode == userchoices.RUNMODE_TEXT:
            import console_install
            userInterface = console_install.ConsoleInstall()
        elif runMode == userchoices.RUNMODE_DEBUG:
            from scripted import ui
            userInterface = ui.Scui(None)
        elif runMode == userchoices.RUNMODE_SCRIPTED:
            from scripted import cursed_ui
            userInterface = cursed_ui.Scui(None)
        else:
            msg = "Weasel run mode set to invalid value (%s)" % runMode
            log.error(msg)
            raise HandledError(msg)

        userInterface._execute()

    except SystemExit:
        raise # pass it on
    except HandledError as ex:
        if userInterface:
            # spit out a traceback, unless it is an expected RebootException
            if not ex.__class__.__name__ == 'RebootException':
                log.exception("The %s UI encountered an error ..."
                              % userchoices.getRunMode())
            userInterface.displayHandledError(ex)
            userInterface.destroy()
            process_end.reboot()
        else:
            print('\n' * 5)
            print('-' * 79)
            print('Error encountered before the user interface was initialized')
            print('-' * 79)
            print('%s\n\n' % ex)
        return 1
    except (vmkctl.HostCtlException, Exception) as ex:
        log.error("Unhandled exception. (%s)" % str(ex))
        dumpExceptionInfo(ex)
        if userInterface:
            try:
                userInterface.destroy()
            except:
                pass
        print("------ An unexpected error occurred ------")
        ei = sys.exc_info() # used for pdb debugging sessions
        try:
            # Sometimes, all we get from users are screenshots.  :(
            # We can't print out a traceback on an exception because those
            # distress the user. So, print out a "code" that won't distress
            # the user, but that can be consumed from a screenshot to generate
            # a (partial) traceback
            import base64
            tbList = traceback.format_exception(*ei)
            tbList = tbList[:-1] # don't need last line - it's printed below
            tbStr = ''.join(tbList)
            ciphertext = base64.b64encode(tbStr)[-100:]
            # To reconstruct the message, you might have to correct for
            # 'Incorrect padding' errors due to the slicing of the last 100
            # chars.  To do this run b64decode(ciphertext[x:-y]), iterating
            # through the permutations of x and y.
            print('Error code: %s' % ciphertext)
        except:
            pass
        raise ex

    return 0



if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        pass
    except Exception as ex:
        ei = sys.exc_info()
        if userchoices.getDebug():
            import pdb
            traceback.print_exception(*ei)
            print('')
            print('To inspect the state of the error, pdb.post_mortem(ei[2])')
            print('')
            pdb.set_trace()
        else:
            print('See logs for details')
            print('')
            log.error(traceback.format_exception(*ei))
            s = traceback.format_exception(*ei)
            print(s[-1])
            prompt("")

