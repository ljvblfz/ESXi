from collections import defaultdict

#
# Commonly used Button Footer definitions
#
STANDARD_BUTTON_FOOTER='(Esc) Cancel     (Enter) Continue'
CONFIRM_BUTTON_FOOTER='(Esc) Cancel     (F11) Continue'
CONTINUE_BUTTON_FOOTER='(Enter) Continue'
REBOOT_BUTTON_FOOTER='(Enter) Reboot'
CONFIRM_BACK_BUTTON_FOOTER='(Esc) Cancel      (F9) Back      (F11) %s'
OTHER_BUTTON_FOOTER='(Esc) Cancel    (F9) Back    (Enter) Continue'
DEVICE_BUTTON_FOOTER='(Esc) Cancel    (Enter) Continue    (F1) Details'

#
# RebootDialog
#
REBOOT_HEADER = 'Rebooting Server'
REBOOT_BODY = ['The server will shut down and reboot.', \
               'The process will take a short time to complete.',]

#
# Progress bar constants
#
PROGRESS_MAX_VALUE = 100
PROGRESS_MIN_VALUE = 0

# Definitions for install/upgrade/both, used to determine which steps are used
# for what.

class StepType:
    upgrade = defaultdict(bool, upgrade=True)
    install = defaultdict(bool, install=True)
    info = defaultdict(bool, upgrade=True,
                             install=True,
                             info=True)
    usersel = defaultdict(bool, upgrade=True,
                                install=True)
