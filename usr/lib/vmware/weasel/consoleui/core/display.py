import urwid
import urwid.util
import urwid.raw_display

# For module-internal use only
__display = None

class Screen:
    """Screen
    A simple class to abstract the functions of the urwid Screen implelentation"""
    #TODO: Its possible that enheriting urwid.raw_display may be benificial as I
    # would have more control over the underlying Screen effects this way. However
    # for the frist version this simple wrapper will do just fine
    def __init__(self, palette=None):
        """Screen -
           Simple class to manage urwid input/output."""
        self.palette = palette
        self.currentDialog = None

        self.ui = urwid.raw_display.Screen()

        self.ui.register_palette( self.palette )

        # Manage the urwid screen lock manually
        self.start()

    def start(self):
        """start
        Urwid rawdisplay manages Start and Stop via the run_wrapper method. This
        is not ideal since we want to use a single display and event loop for
        each Dialog rather than worrying about tracking multiple instances of
        the UI singleton. Use this method to Start the display Screen"""
        if not self.ui._started:
            self.ui.start(True)

    def stop(self):
        """stop
        Urwid rawdisplay manages Start and Stop via the run_wrapper method. This
        is not ideal since we want to use a single display and event loop for
        each Dialog rather than worrying about tracking multiple instances of
        the UI singleton. Use this method to Stop the display Screen"""
        # Manage the urwid screen lock manually
        if self.ui._started:
            self.ui.stop()

    def launchDialog(self, dialog):
        self.currentDialog = dialog

        if not hasattr(self.currentDialog, 'NoInput'):
            self.run()

        return self.currentDialog.data

    def draw(self):
        """draw
        Paints a dialog to the screen based on the gathered size of the
        terminal."""

        cols, rows = self.ui.get_cols_rows()

        # Fall back to 80x24 if the kernel does not know the terminal size
        if rows == 0:
            rows = 24
        if cols == 0:
            cols = 80

        # Hack around incomplete terminal emulation
        # Side effect: Artifacts may appear in the bottom two rows of the terminal.
        # See PR191483
        rows = rows - 2

        self.size = (cols, rows)

        canvas = self.currentDialog.render(self.size, focus=True)
        self.ui.clear()
        self.ui.draw_screen(self.size, canvas)

    def run(self):
        while not self.currentDialog.terminate:
            self.draw()
            keys = self.ui.get_input()
            for k in keys:
                # pass keystrokes to the current widget
                k = self.currentDialog.keypress(self.size, k)

    def flushInput(self):
        """flushInput
        Method consumes all queued input esentially flushing the input
        buffer."""
        keys = self.ui.get_input_nonblocking()


def initializeDisplay():
    """initializeDisplay
    Create the palette and Initialize the a Screen"""
    global __display

    palette = [
        ('banner', 'white', 'black', ('standout', 'underline')),
        ('bg', 'white', 'black'),
        ('frame bg', 'black', 'light gray'),
        ('frame box', 'white', 'light gray'),
        ('body', 'white', 'black', 'standout'),
        ('standout text', 'yellow', 'light gray'),
        ('error text', 'dark red', 'light gray'),
        ('normal text', 'black', 'light gray'),
        ('normal lun text', 'black', 'light gray'),
        ('selected text', 'yellow', 'light gray'),
        ('text header', 'white', 'light gray'),
        ('error selected text', 'yellow', 'light gray'),
        ('inside frame box', 'white', 'light gray'),
        ('pg normal', 'yellow', 'black', 'standout'),
        ('pg complete', 'yellow', 'light gray'),
        ('modal box background', 'white', 'light gray'),
    ]

    if not __display:
        __display = Screen(palette)

    __display.start()


def launchDialog(dialog):
    """launchDialog
    Wrapper to protect global Screen instance. The Screen is Initialized if not
    already. The Dialog is then launched via the Screen instance"""
    global __display

    initializeDisplay()

    flushInput()

    data = __display.launchDialog(dialog)

    redraw()

    return data

def releaseDisplay():
    """releaseDisplay
    Wrapper to protect global Screen instance. The Screen instance is Stopped
    if defined"""
    global __display

    if not __display:
        return

    __display.stop()

def currentDialog():
    """currentDialog
    Wrapper to protect global Screen instance. The Screen is Initialized if not
    already. The currently assigned Dialog instance is returned. """
    global __display

    initializeDisplay()

    return __display.currentDialog

def redraw():
    """redraw
    Wrapper to protect global Screen instance. The Screen is Initialized if not
    already. The Screen canvas is forced to reDraw."""
    global __display

    initializeDisplay()

    __display.draw()

def flushInput():
    """flushInput
    Wrapper to protect global Screen instance. The Screen is Initialized if not
    already. The queued input of the screen instance is flushed."""
    global __display

    initializeDisplay()

    __display.flushInput()

