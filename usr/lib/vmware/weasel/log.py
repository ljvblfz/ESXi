import os
import re
import shutil
import logging
import sys

LOGLEVEL_HUMAN = 25
LOGLEVEL_UI_ALERT = 35 # A level that indicates the UI should show an alert
LOG_PATH = "/var/log/weasel.log"
ESX_LOG_PATH = "/var/log/esxi_install.log"

logging.addLevelName(LOGLEVEL_HUMAN, "HUMAN")
logging.addLevelName(LOGLEVEL_UI_ALERT, "UI_ALERT")

log = logging.getLogger()
formatterForLog = logging.Formatter('%(asctime)s.%(msecs)03dZ %(levelname)-8s %(message)s',
                                    datefmt='%Y-%m-%dT%H:%M:%S')
formatterForHuman = logging.Formatter('%(message)s')
stdoutHandler = None
fileHandler = None

class URLPasswordFilter(logging.Filter):
    '''Filter used to censor passwords in URLs.'''
    def filter(self, record):
        record.msg = re.sub(r'(://.*?:).*?@', r'\1XXXXXX@', str(record.msg))
        return True

def addStdoutHandler():
    global stdoutHandler

    stdoutHandler = logging.StreamHandler(sys.stdout)
    stdoutHandler.setFormatter(formatterForHuman)
    stdoutHandler.setLevel(logging.CRITICAL)
    log.addHandler(stdoutHandler)

def addLogFileHandler():
    global fileHandler

    try:
        fileHandler = logging.FileHandler(LOG_PATH)
        fileHandler.setFormatter(formatterForLog)
        log.addHandler(fileHandler)

        #users like "esx_install.log" over "weasel.log"
        if not os.path.exists(ESX_LOG_PATH):
            os.symlink(LOG_PATH, ESX_LOG_PATH)
    except IOError:
        #Could not open for writing.  Probably not the root user
        pass

log.addFilter(URLPasswordFilter())
addStdoutHandler()
addLogFileHandler()

installHandler = None
upgradeHandler = None

try:
    # dump messages to /dev/klog (aka serial port).
    handler3 = logging.StreamHandler(open('/dev/klog', "w"))
    handler3.setFormatter(formatterForLog)
    log.addHandler(handler3)
except IOError:
    #Could not open for writing.  Probably not the root user
    pass

log.setLevel(logging.DEBUG)

