#! /usr/bin/env python
'''
debugging

This module is optionally imported in weasel.py.  It monkeypatches some stuff
and provides a hook for further monkeypatching
'''

from __future__ import print_function

from weasel.log import log

def init():
    pass


if __name__ == "__main__":
    print('this is the debugging module')
