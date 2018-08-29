#!/bin/python
#
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# HostProfile docs (hostprofile.xml and answerfile.xml) may contain password
# type value within it. Vm-support bundle should not capture them.
# This script gunzip the hostprofile docs, censores all PasswordFields' value,
# then prity print the xml data.
# This script is Maintained by HostProfile team.

import os
import sys
import gzip
from lxml import etree


CENSORED_PASSWORD = "********"
VALUE_TAG = "{urn:vim25}value"
TYPE_ATTRIB = '{http://www.w3.org/2001/XMLSchema-instance}type'

def censorXml(root):
    for value in root.iter(VALUE_TAG):
        vimType = value.attrib.get(TYPE_ATTRIB)
        if vimType != "PasswordField":
            continue
        passwd = value.find(VALUE_TAG)
        passwd.text = CENSORED_PASSWORD

def main():
    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        exit(1)
    xmlTree = etree.parse(gzip.open(filepath))
    censorXml(xmlTree.getroot())
    print(etree.tostring(xmlTree, pretty_print=True).decode('utf-8'))


if __name__ == "__main__":
    main()

