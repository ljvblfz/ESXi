'''
User interface classes for Scripted
'''

import curses
import locale
import logging
import string
import sys
import time

import vmkctl
from .preparser import ScriptedInstallPreparser
from weasel.util import NO_NIC_MSG, checkNICsDetected
from weasel.util.units import formatValue
from weasel.util import  completion_msg
from weasel import userchoices
from weasel.log import log, formatterForHuman, LOGLEVEL_UI_ALERT
from weasel import task_progress
from weasel import applychoices
from weasel import process_end
from weasel.util import upgrade_precheck
from weasel.exception import HandledError

locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

DEBUG = True

VMWARE_BUILD_TEXT = "VMware ESXi 6.7.0"
VMWARE_VERSION_TEXT = "VMware, Inc. VMware Virtual Platform"

# global for keeping track of whether we're running in ESX or not
ESX_TERMINAL = True

WARNING_TEXT = \
"""The following warnings were encountered while
parsing the installation script\n\n"""

ERROR_TEXT = \
"""An error has occurred while parsing the installation
script\n\n"""

INCOMPLETE_TEXT = \
"""The system was not installed correctly."""

WARNING_TIMEOUT = 30 # seconds

class AlertHandler(logging.Handler):
    def __init__(self, scui):
        logging.Handler.__init__(self, level=LOGLEVEL_UI_ALERT)
        self.setFormatter(formatterForHuman)
        self.scui = scui

    def emit(self, record):
        if record.levelno != LOGLEVEL_UI_ALERT:
            return
        if record.msg == 'reboot':
            self.scui.wipeClean()
            return
        self.scui.collectedWarnings.append(record.msg)

class Color:
    CURSES_COLOR = 0

    color_table = {
        'white': (curses.COLOR_WHITE, (999, 999, 999),),
        'black': (curses.COLOR_BLACK, (0, 0, 0),),
        'golden_esx': (curses.COLOR_YELLOW, (999, 800, 0),),
        'light_grey': (curses.COLOR_GREEN, (666, 666, 666),),
        'dark_grey': (curses.COLOR_CYAN, (333, 333, 333),),
    }

    pairs = [
        ('white', 'dark_grey'),
        ('white', 'golden_esx'),
        ('light_grey', 'dark_grey'),
        ('black', 'golden_esx'),
        ('dark_grey', 'golden_esx'),
    ]

    @classmethod
    def init(cls):
        global ESX_TERMINAL
        curses.use_default_colors()

        # most terminals can not change the rgb values for individual colors,
        # however this does work with the ESX terminal.
        try:
            if curses.can_change_color():
                for color, (idx, rgb) in cls.color_table.items():
                    curses.init_color(idx, *rgb)
        except:
            # this prevents the installer from crapping out in caged eagle
            ESX_TERMINAL = False

        # build up the foreground/background color pairs which can be
        # used by curses

        count = 1
        for pair in cls.pairs:
            fg, bg = pair
            curses.init_pair(count,
                cls.color_table[fg][cls.CURSES_COLOR],
                cls.color_table[bg][cls.CURSES_COLOR])
            count += 1

    @classmethod
    def find_color_pair(cls, fg, bg):
        return cls.pairs.index((fg, bg))

class Screen:
    def __init__(self):
        self.stdscr = curses.initscr()
        curses.start_color()
        curses.cbreak()
        curses.noecho()

        self.cursor_state = False
        curses.curs_set(0)

        Color.init()

    def restore_screen(self):
        curses.echo()
        curses.nocbreak()
        curses.endwin()

    def get_cursor(self):
        return self.cursor_state

    def set_cursor(self, state):
        self.cursor_state = state
        curses.curs_set(int(state))

    cursor = property(get_cursor, set_cursor)

class Window:
    def __init__(self, screen, height=25, width=80, color_id=1, offset=(0, 0),
                 box=False):
        '''Base window class

           screen               - main screen object
           height               - height of screen in chars
           width                - width of screen in chars
           color_id             - colour pair for fg/bg of the screen
           offset               - height, row tuple
           box                  - boolean variable for drawing a box
        '''
        self.screen = screen
        self.offset = offset
        self.height = height
        self.width = width
        self.color_id = color_id
        self.box = box

        y, x = self.offset
        self.window = self.screen.stdscr.subwin(self.height, self.width, y, x)

    def handle_keys(self, timeout=None):
        if timeout is None:
            curses.cbreak()
            retval = self.window.getch()
        elif timeout == 0:
            self.window.nodelay(1)
            retval = self.window.getch()
        else:
            curses.halfdelay(10)
            while timeout > 0:
                retval = self.window.getch()
                if retval != curses.ERR:
                    break
                timeout -= 1

        return retval

    def draw(self, clear=False, refresh=False):
        if clear:
            self.window.clear()

        if refresh:
            self.window.bkgd(' ', curses.color_pair(self.color_id))

            if self.box:
                self.window.box()

        self.window.noutrefresh()


class Dialog(Window):

    if sys.version_info[0] <= 2:
        alignDict = {
            'left': string.ljust,
            'center': string.center,
            'right': string.rjust,
        }
    else:
       alignDict = {
            'left': str.ljust,
            'center': str.center,
            'right': str.rjust,
       }

    def __init__(self, screen, text, height, width, color_id=0, offset=(0, 0),
                 align='left', center=False):

        offsetY, offsetX = offset

        if center:
            y, x = screen.stdscr.getmaxyx()

            offsetY = y // 2 - height // 2 + offsetY
            offsetX = x // 2 - width // 2 + offsetX

        # do some bounds checking to make sure we're not going to
        # display something off of the screen

        if offsetY < 0 or offsetY + height > y or \
           offsetX < 0 or offsetX + width > x:
            raise ValueError("Dialog cannot be drawn off of the screen")

        offset = (offsetY, offsetX)

        Window.__init__(self, screen, height, width, color_id, offset=offset,
                        box=True)

        self.cursor = 0
        self.prevKey = None
        self.labels = []

        self.statusLine = {
            'text' : 'Press <Enter> to continue',
            'align' : 'center'
        }

        self.textLines = self._formatText(text, self.width - 4, align)
        self.scrollPadding = 0
        if len(self.textLines) > self.height - 4:
            self.scrollPadding = 1
        self._buildLabels()

    def _buildLabels(self):
        for count, line in enumerate(self.textLines):
            if count < self.cursor:
                continue

            if count >= self.cursor + self.height - 4 - self.scrollPadding:
                break

            self.labels.append(
                Label(self, line, offset=(count + 1 - self.cursor, 2)))


    def _formatText(self, text, lineLength=50, align='left'):
        '''Split text into lines for our dialog

           text                 - string to format
           lineLength           - length in chars
           align                - can be 'left', 'right' or 'center'
                                  to justify the string
        '''
        # XXX - this should really be replaced by the textwrap module,
        #       however it removes the indented code which is bad
        lines = []
        buf = ''
        textCount = 0
        bufCount = 0

        while True:
            if textCount >= len(text):
                lines.append(buf)
                break

            if bufCount >= lineLength:
                lines.append(buf)
                buf = ''
                bufCount = 0
            if text[textCount] == '\n':
                lines.append(buf)
                buf = ''
                bufCount = 0
            else:
                buf += text[textCount]

            textCount += 1
            bufCount += 1

        # justify the lines correctly
        lines = [self.alignDict[align](x, lineLength) for x in lines]

        return lines


    def draw(self):
        self._drawSingleIteration()

    def loop(self, timeout=None):
        exit = False
        while not exit:
            if timeout:
                # TODO: display seconds left in the timeout
                self.statusLine['text'] = "Wait or press <Enter> to continue"
            else:
                self.statusLine['text'] = "Press <Enter> to continue"
            self._drawSingleIteration()
            curses.doupdate()
            key = self.handle_keys(timeout)
            if key == curses.ERR or key == curses.KEY_ENTER or key == ord('\n'):
                exit = True
            elif key == curses.KEY_DOWN or key in [ord('z'), ord('j')]:
                if self.cursor < len(self.textLines) - \
                        (self.height - 4 - self.scrollPadding):
                    self.cursor += 1
                    self._buildLabels()
            elif key == curses.KEY_UP or key in [ord('a'), ord('k')]:
                if self.cursor > 0:
                    self.cursor -= 1
                    self._buildLabels()
            elif self.prevKey == ord('`') and key == ord('='):
                # allow the user to drop into the debugger if they hit ` then =
                self.screen.restore_screen()
                import pdb
                pdb.set_trace()
            # The user is at the console, reset the timeout so we do not
            # automatically continue.
            timeout = None
            self.prevKey = key

        Window.draw(self, clear=True, refresh=False)
        curses.doupdate()

    def _drawSingleIteration(self):
        Window.draw(self, clear=True, refresh=True)
        for label in self.labels:
            label.draw()

        statusAlign = self.statusLine['align']
        statusText = self.alignDict[statusAlign](self.statusLine['text'],
                                                 self.width-4)

        scrollable = False
        if self.cursor > 0:
            scrollable = True
        if len(self.textLines) > self.height:
            scrollable = True

        if scrollable:
            wstr = (u"\u251c%s\u2524" % (u"\u2500" * (self.width - 2))).encode("utf-8")
            self.window.addstr(self.height - 4,
                            0,
                            wstr)
            text = "Press j/k to scroll up/down"
            self.window.addstr(self.height - 3,
                               (self.width - len(text)) // 2,
                               text)
        Label(self, statusText, offset=(self.height-2, 2)).draw()


class ProgressBar:
    def __init__(self, window, width=75, color_id=-1, offset=(8, 2)):
        self.window = window
        self.progress = 0
        self.offset = offset
        self.width = width

        # set the color pair to whatever the base window is set to
        self.color_id = color_id
        if color_id == -1:
            self.color_id = window.color_id

    def draw(self):
        # check if the amount is even or odd
        width = self.width
        if self.width % 2:
            width -= 1

        if ESX_TERMINAL:
            block = u"\u2588".encode("utf-8")
            colorPair = curses.color_pair(self.color_id)
        else:
            block = ' '
            colorPair = curses.color_pair(self.color_id) | curses.A_REVERSE

        fillLength = int((self.progress / 100.0) * self.width)

        # draw base bar
        for x in range(0, width):
            if x % 2:
                # odds get a blank
                self.window.window.addstr(
                    self.offset[0],
                    self.offset[1] + x,
                    ' ', colorPair)
            else:
                # evens get a filled block
                self.window.window.addstr(
                    self.offset[0],
                    self.offset[1] + x,
                    block, colorPair)

        # fill in the blanks
        self.window.window.addstr(
                self.offset[0],
                self.offset[1],
                block * fillLength,
                colorPair)

class Label:
    def __init__(self, window, text, color_id=-1, offset=(1, 2)):
        self.window = window
        self.text = text
        self._max_text = len(text)
        self.offset = offset

        # set the color pair to whatever the base window is set to
        self.color_id = color_id
        if color_id == -1:
            self.color_id = window.color_id

        if len(self.text) > self.window.width - offset[1]:
            raise ValueError("Label: text label is too big for the window")

    def draw(self):
        # overwrite any previous strings with spaces
        self._max_text = max(self._max_text, len(self.text))
        self.window.window.addstr(
            self.offset[0],
            self.offset[1],
            ' ' * self._max_text)

        self.window.window.addstr(
            self.offset[0],
            self.offset[1],
            self.text,
            curses.color_pair(self.color_id))


class TopWindow(Window):
    def __init__(self, screen, height, width):
        Window.__init__(self, screen, height=height, width=width,
                        color_id=1, box=False)

        # TODO:  These need to be populated correctly

        cpuInfo = vmkctl.CpuInfoImpl()
        memInfo = vmkctl.MemoryInfoImpl()
        memStr = formatValue(memInfo.GetPhysicalMemory()/1024)

        self.labels = [
            Label(self, VMWARE_BUILD_TEXT, offset=(4, 14), color_id=1),
            Label(self, VMWARE_VERSION_TEXT, offset=(6, 14), color_id=1),
            Label(self, cpuInfo.GetModelName(), offset=(8, 14), color_id=3),
            Label(self, memStr, offset=(9, 14), color_id=3)
        ]

    def draw(self, refresh=False):
        Window.draw(self, refresh=refresh)
        for label in self.labels:
            label.draw()
        self.window.noutrefresh()

class BottomWindow(Window):
    def __init__(self, screen, height, width, offset):
        Window.__init__(self, screen, height=height, width=width,
                        color_id=2, offset=offset, box=False)

        self.progress = ProgressBar(self,
                                    color_id=5,
                                    width=width-4,
                                    offset=(height-2, 3))

        # TODO:  Add proper strings here

        self.text = 'About to install...'
        self.label = Label(self, self.text, offset=(1, 14), color_id=4)

        self.subText = ''
        self.subLabel = Label(self, self.subText, offset=(3, 14), color_id=5)

    def draw(self, refresh=False):
        Window.draw(self, refresh=refresh)
        self.label.draw()
        self.subLabel.draw()
        self.progress.draw()
        self.window.noutrefresh()


class ProgressReporter(object):
    '''Observer for task_progress that updates the curses screen'''

    def __init__(self, uiHook):
        self.lastmsg = None
        self.lastProgressUpdate = 0
        task_progress.addNotificationListener(self)

        self.uiHook = uiHook

    def __del__(self):
        task_progress.removeNotificationListener(self)

    def notifyTaskStarted(self, taskTitle):
        task = task_progress.getTask(taskTitle)
        self.uiHook.window2.subLabel.text = ''
        self.renderProgressMessage(task)
        self.uiHook.draw()

    def notifyTaskFinished(self, taskTitle):
        task = task_progress.getTask(taskTitle)
        self.uiHook.window2.subLabel.text = 'Finished %s' % (task.desc)
        self.renderProgressBar()
        self.uiHook.draw()

    def notifyTaskProgress(self, taskTitle, complete):
        # updating the progress does a bunch math and function call work
        # so don't do it more frequently than once per second
        thisSecond = int(time.time())
        if self.lastProgressUpdate == thisSecond:
            return
        self.lastProgressUpdate = thisSecond
        task = task_progress.getTask(taskTitle)
        self.renderProgressMessage(task)
        self.renderProgressBar()
        self.uiHook.draw()

    def renderProgressMessage(self, task):
        if task.title == 'install':
            return
        if task.desc:
            labelText = task.desc
        else:
            labelText = task.title

        if task.estimatedTotal != None:
            # user interface doesn't benefit from the granularity of floats,
            # so cast to ints.
            amountDone = int(task.estimatedTotal - task.amountRemaining)
            estimatedTotal = int(task.estimatedTotal)
            labelText += ' ( %s / %s )' % (amountDone, estimatedTotal)
        self.uiHook.window2.label.text = labelText

        detail = task.lastMessage
        if detail:
            self.uiHook.window2.subLabel.text = detail

    def renderProgressBar(self):
        try:
            masterTask = task_progress.getTask('install')
        except KeyError:
            pass
        else:
            pctComplete = 100.0 - masterTask.percentRemaining()
            self.uiHook.window2.progress.progress = pctComplete


class UserInterface(object):
    '''Root class for generic user interface

       - sets up exception handler
       - initializes the user interface screen

     '''
    def __init__(self):
        self.screen = Screen()
        import exception
        sys.excepthook = lambda except_type, value, tb: \
                         exception.handleException(self,
                            except_type, value, tb)


    def exceptionDialog(self, details):
        dialog = Dialog(self.screen,
            "An exceptional circumstance has occurred\n\n%s" % details,
            20, 58, center=True)
        dialog.loop()

        self.screen.restore_screen()

class Scui(UserInterface):
    def __init__(self, script):
        UserInterface.__init__(self)

        y, x = self.screen.stdscr.getmaxyx()

        topWinHeight = y // 2
        bottomWinHeight = (y // 2) + (y % 2)

        self.bg_window = Window(self.screen,
                                height=y,
                                width=x,
                                box=True,
                                color_id=3)
        self.window1 = TopWindow(self.screen,
                                 height=topWinHeight,
                                 width=x)
        self.window2 = BottomWindow(self.screen,
                                    height=bottomWinHeight,
                                    width=x,
                                    offset=(topWinHeight, 0))

        self.draw(refresh=True)

        # an alertHandler will allow us to display UI_ALERTs
        alertHandler = AlertHandler(self)
        log.addHandler(alertHandler)
        self.collectedWarnings = []
        self.hadWarnings = False

        if script != None:
            self._execute()

    def draw(self, refresh=False):
        for win in [self.bg_window, self.window1, self.window2]:
            win.draw(refresh=refresh)
        curses.doupdate()

    def wipeClean(self):
        self.bg_window.draw(clear=True, refresh=True)
        curses.doupdate()
        curses.setsyx(25, 0)

    def _execute(self):
        scriptDict = userchoices.getRootScriptLocation()

        if not scriptDict:
            msg = 'Script location has not been set.'
            longMsg = 'An install script is required. Check your ks option.'
            log.error(msg)
            raise HandledError(msg, longMsg)

        script = scriptDict['rootScriptLocation']

        installCompleted = False

        stdoutReporter = ProgressReporter(self)

        try:
            if not checkNICsDetected():
                raise HandledError(NO_NIC_MSG)

            self.preparser = ScriptedInstallPreparser(script)

            (result, errors, warnings) = self.preparser.parseAndValidate()
            if warnings:
                log.warn("\n".join(warnings))
                self.displayWarningWindow(WARNING_TEXT, warnings)
                self.hadWarnings = True

            if errors:
                errorText = "\n".join(errors)
                log.error(errorText)
                userchoices.setReboot(False)
                raise HandledError(ERROR_TEXT, errorText)

            # Bring up the network so VUM can communicate with this host
            warnings = self.tryNetworkConnect()

            if warnings:
                log.warn("\n".join(warnings))
                prologue = ('The following warnings were encountered while'
                            ' preparing the system\n\n')
                self.displayWarningWindow(prologue, warnings)
                self.hadWarnings = True

            if userchoices.getDebug():
                log.info(userchoices.dumpToString())

            # Run the prechecks, unless this is a VUM-initiated upgrade, in
            # which case, they've already been run.
            if not userchoices.getVumEnvironment():
                task_progress.taskStarted(upgrade_precheck.TASKNAME, 1,
                                          taskDesc=upgrade_precheck.TASKDESC)
                warningMsg = None
                if userchoices.getUpgrade():
                    # UpgradeAction will only run non customziation checks
                    errorMsg, warningMsg = upgrade_precheck.upgradeAction()

                    if errorMsg and not userchoices.getIgnorePrereqErrors():
                        raise HandledError(ERROR_TEXT, errorMsg)
                elif userchoices.getInstall():
                    errorMsg, warningMsg = upgrade_precheck.installAction()
                    if errorMsg and not userchoices.getIgnorePrereqErrors():
                        raise HandledError(ERROR_TEXT, errorMsg)

                task_progress.taskFinished(upgrade_precheck.TASKNAME)

                if warningMsg:
                    self.collectedWarnings += [warningMsg]

                if (self.collectedWarnings
                    and not userchoices.getIgnorePrereqWarnings()):
                    prologue = ('The following warnings were encountered while'
                                ' inspecting the system\n\n')
                    self.displayWarningWindow(prologue, self.collectedWarnings)
                    self.hadWarnings = True
                    self.collectedWarnings = []

            if not userchoices.getDryrun():
                applychoices.doit()
            installCompleted = True

        except HandledError as e:
            self.displayHandledError(e)
        except IOError as e:
            self.displayHandledError(HandledError("cannot open file", str(e)))

        if self.collectedWarnings and not userchoices.getIgnorePrereqWarnings():
            self.displayWarningWindow('Warning(s):\n\n', self.collectedWarnings)
            self.hadWarnings = True

        if not installCompleted:
            log.error("installation aborted")
            dialog = Dialog(self.screen, INCOMPLETE_TEXT,
                            5, 58, center=True)
            dialog.loop()
        else:
            completionMsgBodyList = completion_msg.getCompletionDialog()
            completionMsg = ''
            for message in completionMsgBodyList[:-1]:
                completionMsg += message + '\n\n'
            completionMsg += completionMsgBodyList[-1]

            if userchoices.getDryrun():
                msg = ('Finished.\n'
                       '(In dry run mode. No errors were encountered, but\n'
                       ' installation will not proceed.)')
                height = 7
            else:
                msg = completionMsg
                height = 18

            if self.hadWarnings:
                msg += '\n\nThere were warnings. See log files.'
                height += 2

            dialog = Dialog(self.screen, msg, height, 61, center=True)
            if userchoices.getReboot():
                dialog.loop(timeout=WARNING_TIMEOUT)
            else:
                dialog.loop()

        try:
            process_end.reboot()
        except HandledError as e:
            self.displayHandledError(e)

        self.destroy()

    def destroy(self):
        # Don't leave ugly discoloured curses barf if we need to end process.
        self.wipeClean()
        self.screen.restore_screen()

    def displayWarningWindow(self, prologue, warnings):
        warningText = "\n".join(warnings)
        dialog = Dialog(self.screen, prologue + warningText,
                        20, 58, center=True)
        dialog.loop(timeout=WARNING_TIMEOUT)
        self.draw(refresh=True)

    def displayHandledError(self, e):
        log.info(userchoices.dumpToString())
        log.error(str(e)) # ensure errors get logged
        dialog = Dialog(self.screen, str(e), 22, 58, center=True)
        dialog.loop()
        self.draw(refresh=True)

    def tryNetworkConnect(self):
        from weasel.networking import connect, connected, \
                                      ConnectException, WrappedVmkctlException
        warnings = []
        if not connected():
            try:
                connect()
            except (ConnectException, WrappedVmkctlException) as ex:
                msg = 'Could not bring up network (%s)' % str(ex)
                log.exception(msg)
                warnings.append(msg)
        return warnings

