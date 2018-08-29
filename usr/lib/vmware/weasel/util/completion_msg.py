# pylint: disable-msg=C0103

"""
This file is used to create the completion message dialog
"""

from weasel.consts import PRODUCT_SHORT_STRING
from weasel import userchoices

def getCompletionDialog():
    '''
    This function create the message to be presented at
    the end of installation or upgrade.
    Things to convey:
    1 The installation/upgrade was successful
    2 License status
    3 How to administer the product
    4 Remove the disc before rebooting
    5 Reboot the system to use the product
    '''

    introMessage = ("This system has been upgraded to %s successfully."
                    % (PRODUCT_SHORT_STRING))

    # Check if it was an upgrade to provide the 'introMessage'
    if userchoices.getInstall():
        introMessage = PRODUCT_SHORT_STRING +\
            ' has been installed successfully.'

    # License message when no serial number/license has been provided
    licenseMessage = ('%s will operate in evaluation mode for 60 days.'
                      '\nTo use %s after the evaluation period, you must '
                      'register for a VMware product license.' %
                      (PRODUCT_SHORT_STRING, PRODUCT_SHORT_STRING))

    # If the serial number has been provided, we inform that the licnese
    # will be checked at next boot
    if userchoices.getSerialNumber():
        licenseMessage = ('The provided license has been applied and '
                          'will be'
                          '\nvalidated at reboot.')

    usageMessage = ('To administer your server, navigate to the server\'s'
                    '\nhostname or IP address from your web browser or use the'
                    '\nDirect Control User Interface.')

    removeDiscMessage = 'Remove the installation media before rebooting.'

    rebootMessage = ('Reboot the server to start using %s.'
                     % PRODUCT_SHORT_STRING)

    completeMessageBody = [introMessage,
                           licenseMessage,
                           usageMessage,
                           removeDiscMessage,
                           rebootMessage]

    return completeMessageBody

def getCompletionHeader():
    '''
    This function returns the header to be written after completion of
    installation or upgrade.
    '''
    actionString = "Installation"
    if userchoices.getUpgrade():
        actionString = userchoices.getActionString()
        if not actionString:
            actionString = "Upgrade"

    completionHeader = '%s Complete' % actionString
    return completionHeader
