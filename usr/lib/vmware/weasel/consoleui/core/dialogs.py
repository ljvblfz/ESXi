import urwid
import sys

from weasel.consts import PRODUCT_STRING, PRODUCT_TITLE
from weasel.consoleui.core.display import launchDialog

from weasel.log import log

def colorizeTokenize(text):
    '''
    >>> from pprint import pprint
    >>> pprint(colorizeTokenize('asdf qwer'))
    [('normal text', 'asdf'), ('normal text', ' '), ('normal text', 'qwer')]

    >>> pprint(colorizeTokenize('@SSS@ boring #EEE#'))
    [('standout text', 'SSS'),
     ('normal text', ' '),
     ('normal text', 'boring'),
     ('normal text', ' '),
     ('error text', 'EEE')]
    '''
    textListofTuples = []

    assert text.count('@') % 2 == 0
    assert text.count('#') % 2 == 0

    standoutToken = False
    errorToken = False

    for token in text.split(' '):
        color = 'normal text'

        punct = None
        if token and token[-1] in ['.', '!', '?', ',']:
            punct = token[-1]
            token = token[0:-1]

        if token.startswith('@') and token.endswith('@'):
            color = 'standout text'
        elif token.startswith('#') and token.endswith('#'):
            color = 'error text'
        elif token.startswith('@'):
            standoutToken = True
        elif token.endswith('@'):
            color = 'standout text'
            standoutToken = False
        elif token.startswith('#'):
            errorToken = True
        elif token.endswith('#'):
            color = 'error text'
            errorToken = False

        token = token.strip('@#')

        if standoutToken:
            color = 'standout text'
        if errorToken:
            color = 'error text'

        # insert a space, unless this is the very first token
        if textListofTuples:
            textListofTuples.append(('normal text', ' '))
        textListofTuples.append((color, token))
        if punct:
            textListofTuples.append(('normal text', punct))
    return textListofTuples

class Dialog(urwid.WidgetWrap):
    """Dialog
    Base Class for NonModalDialogs. Any dialog deriving from this base class
    can choose to either be a full screen window or standard dialog by
    specifying a wrapMagic function in the constructor that will continue
    the wrapping practice. All NonModalDialogs should pass wrapMagic to
    encapsulate their dialog definition into the Dialog Window."""

    #TODO: There is probably a better way to get around this wrap magic stuff
    #      by creating some additonal widgets to encapsulate a Frame.
    #      Unfortunalty I don't have the time to make this as elegant
    #      as it should be for the initial release
    def __init__(self, bodyItems, headerText, footer,
                 backgroundAttr='frame box', wrapMagic=None, isBodyText=True):

        # Signal to Screen to terminate processing of input for this dialog
        self.terminate = False

        self.body = self._buildDialogBody(bodyItems, isBodyText)
        tokenTuples = colorizeTokenize(headerText)
        self.header = urwid.Text(tokenTuples, align='center')
        self.footer = self._buildDialogFooter(footer)
        frame = urwid.Frame(self.body, header=self.header, footer=self.footer)

        border = urwid.LineBox(frame)
        wrap = urwid.AttrWrap(border, backgroundAttr)

        # May or may not exist... used to circumvent Urwid component wrapping
        # craziness
        if wrapMagic:
            wrap = wrapMagic(wrap)

        urwid.WidgetWrap.__init__(self, wrap)

    @staticmethod
    def _isString(obj):
        """Check whether obj is a string (python 2 and 3 compliant).
        """
        if sys.version_info[0] >= 3:
            return isinstance(obj, str)
        else:
            return isinstance(obj, basestring)

    def _buildDialogFooter(self, footer):
        """buildDialogFooter
        Creates a urwid.Text object if footer is a string, else returns footer if
        it is a recognized type (urwid.Text or urwid.ProgressBar)"""
        if footer is None:
            return None

        if isinstance(footer, (urwid.Text, urwid.ProgressBar)):
            return footer
        elif self._isString(footer):
            return urwid.Text(('frame box', footer), align="center")
        return None


    def _buildDialogBody(self, bodyItems, isBodyText=True):
        """buildDialogBody
        Creates a ListBox urwid widget that contains a non selectable list of
        urwid text items suitable for embedding within an urwid Frame. Text is
        parsed for metacharacters that describe the color of a particular text
        token. Urwid Dividers are placed before each line element to give
        paragraph-like line breaks. The size of the resulting ListBox is padded
        to 50% the width and height of the display screen. It is possible that
        text could be left unrendered if the size of the ListBox exceeds the
        size of the Dialog."""

        componentList = []

        if bodyItems is not None:
            if isBodyText:
                for paragraph in bodyItems:
                    componentList.append(urwid.Divider())
                    parse = True
                    if type(paragraph) is tuple:
                        paragraph, parse = paragraph

                    # if just one urwid.Text widget is used, then we can't
                    # scroll line by line, so break every line into its
                    # own urwid.Text widget
                    for line in paragraph.splitlines():
                        log.debug('adding l %s' % line)
                        if line.strip() == '':
                            # all whitespace, so use a divider for better
                            # scrollability
                            item = urwid.Divider()
                        else:
                            if parse:
                                item = urwid.Text(colorizeTokenize(line))
                            else:
                                item = urwid.Text(('normal text', line))
                        componentList.append(item)

            # If we didn't just get a list of strings, then we assume we have
            # urwid objects passed to us.
            else:
                componentList = bodyItems

        componentList.append(urwid.Divider())
        self._listBox = urwid.ListBox(componentList)

        return urwid.Padding(self._listBox, align='center',
                             width=('relative', 100))

    def keypress(self, size, key):
        """keypress
        All Dialogs by default will terminate on the keypress 'enter' and reboot
        on the keypress 'esc'. If you want different input functionality
        override this method"""
        if key == 'enter':
            self.terminate = True
        elif key == 'esc':
            # imported at this level to avoid circular import of ModalDialog
            from Core.TUI.ConfirmRebootDialog import ConfirmRebootDialog
            launchDialog(ConfirmRebootDialog(self))

        return key

class NonModalDialog(Dialog):
    """NonModalDialog
    A simple class to encapsulate several urwid components into a Dialog looking
    object"""
    def __init__(self, body, header, footer,  height=15, width=50,
                 dialogBackgroundAttr='frame box', frameBackgroundAttr='bg',
                 frameHeaderAttr='banner', isBodyText=True):
        self.headerAttr = frameHeaderAttr
        self.backgroundAttr = frameBackgroundAttr
        self.width = width
        self.height = height

        Dialog.__init__(self, body, header, footer,
                        backgroundAttr=dialogBackgroundAttr,
                        wrapMagic=self.frameWrap,
                        isBodyText=isBodyText)

    def frameWrap(self, wrap):
        """frameWrap
        Gentlemen, I introduce WrapMagic! A way to work around the shortcummings
        of urwid component wrapping by delaying the initialization of the outer
        frame until the Base Dialog is created. *sigh*"""
        constrain_horizontal = urwid.Padding(wrap, 'center', self.width)
        constrain_vertical = urwid.Filler(constrain_horizontal, \
                                          height=self.height)

        textAttr = (self.headerAttr, PRODUCT_STRING + ' ' + PRODUCT_TITLE)
        heading = urwid.Text(textAttr, align="center")

        frame = urwid.Frame(constrain_vertical, header=heading, footer=None)
        return urwid.AttrWrap(frame, self.backgroundAttr)

class SelectionDialog(NonModalDialog):
    """SelectionDialog
    A class that encapsulates a selectable Urwid ListBox"""
    def __init__(self, urwidTextList, headerText, footer, additionalFooterWidget=None, \
            height=15, width=30, backgroundAttr='frame box',
            additionalHeaderWidget=None):

        self.extraFooterWidget = additionalFooterWidget
        self.extraHeaderWidget = additionalHeaderWidget
        NonModalDialog.__init__(self, urwidTextList, headerText, footer,
                                dialogBackgroundAttr=backgroundAttr,
                                height=height, width=width+4)

    def _buildDialogBody(self, bodyItems, isBodyText=True):
        """
        Method is overridden since a SelectionDialog is nothing more than a
        Dialog with a ListBox body
        """
        self.listbox = urwid.ListBox(bodyItems)
        padd = urwid.Padding(self.listbox, 'center', self.width, 50)
        fill = urwid.Filler(padd, 'middle', self.height - 8, 10)
        border = urwid.AttrWrap(urwid.LineBox(fill), 'inside frame box')

        frameFooter = None
        frameHeader = None

        if self.extraFooterWidget:
            if isinstance(self.extraFooterWidget, urwid.CheckBox):
                frameFooter = self.extraFooterWidget
            else:
                frameFooter = urwid.Text(('normal text',
                                          str(self.extraFooterWidget)),
                                         align='center')

        if self.extraHeaderWidget:
            if self._isString(self.extraHeaderWidget):
                frameHeader = urwid.Text(('normal text',
                                          self.extraHeaderWidget),
                                         align='center')
            else:
                frameHeader = self.extraHeaderWidget

        return urwid.Frame(border, header=frameHeader, footer=frameFooter)

    def keypress(self, size, key):
        """keypress
        All keystrokes are passed directly to the listbox so that it can handle
        events like 'page up/down'"""
        return self.listbox.keypress(size, key)

class ModalDialog(urwid.WidgetWrap):
    """ModalDialog
    A simple class that manages a child Dialog and its respective parent.
    Urwid Overlay is utilized to layer the two windows"""
    def __init__(self, parent, bodyItems, headerText, footer, \
                 height=('relative', 70), width=('relative', 45), \
                 backgroundAttr='modal box background', isBodyText=True):

        self.terminate = False

        self.parent = parent
        self.child = Dialog(bodyItems, headerText, footer, backgroundAttr, isBodyText=isBodyText)
        overlay = urwid.Overlay(self.child, self.parent, 'center', width, \
                                'middle', height)

        urwid.WidgetWrap.__init__(self, overlay)


    def keypress(self, size, key):
        """keypress
        Pass all keystrokes to the Modal Dialogs body attribute by default"""
        return self.child.body.keypress(size, key)

class RadioModalDialog(ModalDialog):
    """
    A modal dialog that has support for radio buttons.
    """
    optionsFooter = "Use the arrow keys and spacebar to select an option."
    options = None

    def __init__(self, parent, body, header, footer, height=('relative', 70),
                 width=('relative', 45), isBodyText=False):
        self.bodyList = urwid.SimpleListWalker([])

        self.bodyList.append(urwid.Divider())
        for line in body:
            self.bodyList.append(urwid.Text(('normal text', line)))
        self.bodyList.append(urwid.Divider())

        self.radioGroup = []

        for item in self.options:
            w = urwid.RadioButton(self.radioGroup, item[0])
            w = urwid.AttrWrap(w, 'normal text', 'selected text')
            self.bodyList.append(w)

        self.bodyList.append(urwid.Divider())
        self.bodyList.append(urwid.Text(('normal text', self.optionsFooter), align='center'))

        ModalDialog.__init__(self, parent, self.bodyList, header, footer,
                             height=height, width=width, isBodyText=isBodyText)

    def keypress(self, size, key):
        """
        Set the correct userchoice settings after they've selected an option.
        """
        setChoices = []
        optionsDict = dict(self.options)

        if key == 'enter':
            for radio in self.radioGroup:
                if radio.get_state():
                    setChoices = optionsDict[radio.label]
                    break

            # radio *should* be defined by this point, if not .. then we have larger issues.
            log.debug("User selected to \"%s\"." % radio.label)
            for choice in setChoices:
                func, arg = choice
                func(arg)

            self.terminate = True
        elif key == 'esc':
            self.terminate = True
            launchDialog(self.parent)
        else:
            return self.child.body.keypress(size, key)
