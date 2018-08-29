#!/bin/sh

#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Upgrade /etc/pam.d/system-auth-tally PAM config file.
#

# The file to upgrade.
FILE="/etc/pam.d/system-auth-tally"

# The default contents of the file in the current version of ESXi.
# We rely on the fact that vmkernel creates a ".#" version of the file
# whenever a sticky file is modifed.
DEFAULT_FILE="/etc/pam.d/.#system-auth-tally"

LOG_TAG="upgrade-system-auth-tally.sh"

logger -t $LOG_TAG "Upgrade check for file $FILE"

# If $DEFAULT_FILE does not exist, then no upgrade is needed since the file
# has never been changed, hence no backup and restore have taken place.

if [ ! -f $DEFAULT_FILE ]
then
   logger -t $LOG_TAG "File has not been changed"
   exit 0
fi

# Don't upgrade if the files are the same.

if diff $FILE $DEFAULT_FILE >/dev/null
then
   logger -t $LOG_TAG "File is the same as the default"
   exit 0
fi


# Upgrade the file by preserving only some of the existing changes.
# Currently only pam_tally2.so options "deny" and "unlock_time" are carried
# over from the old config file to the new version.

lineToUpgrade=`grep -E "^auth[[:space:]]+.*[[:space:]]+.*pam_tally2.so[[:space:]]+" $FILE`

savedDeny=`echo $lineToUpgrade | grep -o -E "deny=[^[:space:]]+"`
savedUnlockTime=`echo $lineToUpgrade | grep -o -E "unlock_time=[^[:space:]]+"`

cp $DEFAULT_FILE ${FILE}.tmp
# -rw-r--r-T
chmod 1644 ${FILE}.tmp

sedRegexStart="s/(^auth[[:space:]]+sufficient[[:space:]]+.*pam_tally2.so[[:space:]]+.+)"

# Sed regular expressions for updating the options "deny" and "unlock_time".
sedRegexForDeny="${sedRegexStart}deny=[^[:space:]]+(.*)/\1${savedDeny}\2/"
sedRegexForUnlockTime="${sedRegexStart}unlock_time=[^[:space:]]+(.*)/\1${savedUnlockTime}\2/"

sed -i -E "${sedRegexForDeny}" ${FILE}.tmp
sed -i -E "${sedRegexForUnlockTime}" ${FILE}.tmp

mv ${FILE}.tmp ${FILE}

logger -t $LOG_TAG "File has been upgraded"

