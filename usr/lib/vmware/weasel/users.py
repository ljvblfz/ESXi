#! /usr/bin/env python

from __future__ import print_function

import random
from . import script
import string
import crypt
from weasel import userchoices # always import via weasel.
from weasel.util import execCommand

TASKNAME = 'ROOTPASS'
TASKDESC = 'Setting the root password'

SALT_CHARS = string.ascii_letters + string.digits + './'
ALLOWED_CHARS = string.digits + string.ascii_letters + string.punctuation + " "
ALLOWED_USER_CHARS = string.digits + string.ascii_letters

_rootpass = None

SHADOW_FILE = '/etc/shadow'

useMD5 = userchoices.ROOTPASSWORD_TYPE_MD5
useSHA512 = userchoices.ROOTPASSWORD_TYPE_SHA512

def sanityCheckPassword(password, pwqcheck=False):
    '''password sanity check'''

    # run length tests natively for faster speed
    if len(password) < 7:
        raise ValueError("Password must be at least 7 characters long.")
    if len(password) > 40:
        raise ValueError("Password must be less than 41 characters long.")

    # non-ASCII is not allowed
    for letter in password:
        if letter not in ALLOWED_CHARS:
            raise ValueError("Password may only contain ASCII characters.")

    # use pwqcheck for weak password detection when wanted
    if pwqcheck:
        cmd = "/bin/pwqcheck -1 config=/etc/passwdqc.conf"
        retcode, stdout, stderr = execCommand(cmd, input=password)

        if stdout != "OK":
            # extract detailed reason
            reason =  stdout[stdout.find('(') + 1:stdout.find(')')]
            msg = None
            # change default pwqcheck messages to shorter forms
            if reason == "not enough different characters or classes for this" \
                         " length" or \
               reason == "not enough different characters or classes":
                msg = "Password does not have enough character types."
            if reason == "based on a dictionary word and not a passphrase":
                msg = "Password must not contain dictionary words."
            elif reason == "based on a common sequence of characters and not " \
                           "a passphrase":
                msg = "Password must not contain common sequences."
            # check failed probably mean something is wrong
            elif reason == "check failed":
                raise Exception("pwqcheck execution failed")

        # other reasons should not normally appear, ignore:
        # "is the same as the old one"
        # "is based on the old one"
        # "based on personal login information"

        if msg:
            raise ValueError(msg)

def sanityCheckUserAccount(account):
    if not account:
        raise ValueError("You need to specify a user name.")
    elif len(account) > 31:
        raise ValueError("User Names must be shorter than 32 characters.")

    if account in RESERVED_ACCOUNTS:
        raise ValueError("The account you specified is reserved by the system.")

    for letter in account:
        if letter not in ALLOWED_USER_CHARS:
            raise ValueError("Accounts may only contain ascii letters and "
                             "numbers.")


def cryptPassword(password, algo=useSHA512):
    '''
    crypt the password using either simple crypt or md5 algorithms.
    Since glibc2, crypt uses a special three character lead to
    generate a MD5 string followed by at most 8 characters.
    See man crypt(3) for more info.
    '''
    if algo == useMD5:
        salt = "$1$"
        saltLen = 8
    elif algo == useSHA512:
        salt = "$6$"
        saltLen = 8
    else:
        salt = ""
        saltLen = 2

    for i in range(saltLen):
        salt = salt + random.choice(SALT_CHARS)

    return crypt.crypt(password, salt)


class RootPassword(object):
    def __init__(self, password, isCrypted=False, algo=useSHA512):
        if isCrypted:
            self.password = password
        else:
            self.password = cryptPassword(password, algo)
        self.account = 'root'

def hostAction():
    applyUserchoices()

def installAction():
    applyUserchoices()


def applyUserchoices():
    '''prepare the root password'''
    global _rootpass
    rootPassword = userchoices.getRootPassword()
    # Only do this if there was a password set.
    if rootPassword:
        crypted = rootPassword['crypted']
        algo = rootPassword['passwordType']
        _rootpass = RootPassword(rootPassword['password'],
                                 isCrypted=crypted,
                                 algo=algo)

def getFirstBootVals():
   keyVals = {} 
   if _rootpass:
      keyVals["password"] = _rootpass.password
   return keyVals

if __name__ == "__main__":
    import doctest
    doctest.testmod()

    userchoices.setInstall(False)
    crypted = cryptPassword('asdfasdf')
    print('crypted was %s' % crypted)
    userchoices.setRootPassword(crypted, userchoices.ROOTPASSWORD_TYPE_CRYPT)
    hostAction()
    print('wrote to /etc/shadow')
    os.system('cat /etc/shadow')

    print('made firstboot script')
    print(_rootpass.script)
