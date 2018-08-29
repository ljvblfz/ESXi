#!/bin/sh

#
# Copyright 2017 VMware, Inc. All rights reserved.
#
# Upgrade /etc/ntp.conf config file.
#

# The file to upgrade.
FILE="/etc/ntp.conf"

# The default contents of the file in the current version of ESXi.
# We rely on the fact that vmkernel creates a ".#" version of the file
# whenever a sticky file is modifed.
DEFAULT_FILE="/etc/.#ntp.conf"

LOG_TAG="ntp.conf"

logger -t $LOG_TAG "Upgrade check for file $FILE"

# If $DEFAULT_FILE does not exist, then no upgrade is needed since the file
# has never been changed, hence no backup and restore have taken place.

if [ ! -f $DEFAULT_FILE ]
then
   logger -t $LOG_TAG "File has not been changed"
   exit 0
fi

# Don't upgrade if the files are the same.

if diff $FILE $DEFAULT_FILE > /dev/null
then
   logger -t $LOG_TAG "File is the same as the default"
   exit 0
fi

# Search in files for restrict key word and list of options
restrictSearch="^restrict\([[:space:]]\+[[:lower:]]\+\)\+"
restrictFile=$(grep $restrictSearch $FILE)
restrictDefault=$(grep $restrictSearch $DEFAULT_FILE)

# Don't upgrade if the restrict options in both files are the same
if [ "$restrictFile" == "$restrictDefault" ]
then
   logger -t $LOG_TAG "Restrict options has not been changed"
   exit 0
fi

pid=$$

# Upgrade the file by changing only the restrict options
sed "s/$restrictSearch/$restrictDefault/" $FILE > $FILE.tmp.$pid

# -rw-r--r-T
chmod 1644 $FILE.tmp.$pid

mv -f $FILE.tmp.$pid $FILE

logger -t $LOG_TAG "File has been upgraded"
