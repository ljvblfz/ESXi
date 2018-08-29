#!/usr/bin/env python

########################################################################
# Copyright 2016 VMware, Inc.  All rights reserved.
# -- VMware Confidential
########################################################################

import os
from vmware.esximage import HostImage
from vmware.esximage.Database import TarDatabase
from vmware.esximage.Vib import ArFileVib

DBPATH = '/bootbank/imgdb.tgz'

def main():
    himg = HostImage.HostImage()
    level = himg.GetHostAcceptance()

    # set acceptance level only when it is not properly set
    if not level in ArFileVib.ACCEPTANCE_LEVELS and os.path.exists(DBPATH):
       db = TarDatabase(dbpath=DBPATH)
       db.Load()
       himg.SetHostAcceptance(db.profile.acceptancelevel)

if __name__ == '__main__':
    main()

