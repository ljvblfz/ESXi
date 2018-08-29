#!/bin/sh

###################################################
#
# Esxupdate Installation Helper Script
#
#
# Copyright 2007 VMware, Inc.  All rights reserved.
# -- VMware Confidential
#
###################################################


print_stdout() { echo "$@"; }
print_stderr() { echo "$@" 1>&2; }


#
# Check command args
#
if [ $# -ne 2 ]; then
    print_stderr "Please specify a type and filename"
    print_stderr "Usage: InstallHelper.sh <type> <file>"
    exit 1
fi


#
# Get args
#
pkgtype=$1
pkgpath=$2
pkgdir=$(dirname $pkgpath)
pkgbase=$(basename $pkgpath)


#
# Move to directory where package exists
#
if [ -d "$pkgdir" ]; then
    cd $pkgdir
else
    print_stderr "Directory $srcdir does not exist"
    exit 1
fi


#
# Check for basename of file in current directory
#
if [ ! -f "./$pkgbase" ]; then
    print_stderr "Cannot find $pkgbase in $PWD"
    exit 1
fi


#
# Determine type of install file and run
#
result=0
if [ "$pkgtype" == "tar-gz-install" ]; then
    tar -xzf ./$pkgbase
    result=$?
    if [ $result -ne 0 ]; then
        print_stderr "Failed to untar package. Tar utility returned with status $result"
        exit 1
    fi

    if [ ! -x "./install.sh" ]; then
	print_stderr "Package has no install script"
	exit 1
    fi

    ./install.sh
    result=$?
    if [ $result -ne 0 ]; then
        print_stderr "Install script returned with status $result"
    fi

elif [ "$pkgtype" == "install-script" ]; then
    # Make sure install script is executable
    chmod +x ./$pkgbase
    ./$pkgbase
    result=$?
    if [ $result -ne 0 ]; then
        print_stderr "Install script returned with status $result"
    fi

else
    print_stderr "Unknown type $pkgtype"
    result=1
fi


#
# Cleanup and exit
#
exit $result
