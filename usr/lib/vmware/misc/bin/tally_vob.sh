#!/bin/sh
#
# Copyright 2014 VMware, Inc.  All rights reserved.
#
# This script raises a VOB for the user acount named $PAM_USER.
# The environment variable PAM_USER is supplied by the PAM module pam_exec,
# from the PAM configuration file /etc/pam.d/system-auth-tally.
#
# For more information see the manual page for pam_exec.
#

PAM_TALLY2_CMD=/bin/pam_tally2
ADD_VOB_CMD=/usr/lib/vmware/vob/bin/addvob

# get pam_tally2 config line
CONFIG=`grep pam_tally2.so /etc/pam.d/system-auth-tally | grep unlock_time=`

# Extract the value for option "unlock_time="
TIMEOUT=${CONFIG#*unlock_time=}
TIMEOUT=${TIMEOUT%% *}

# Extract the current number of failures for user $PAM_USER
FAILURES=`$PAM_TALLY2_CMD -u "$PAM_USER" | (read; read x y z; echo $y)`


# User 'vpxuser' is special, so reset the tally counter to prevent DoS.
# A separate VOB is raised in this case.
if [ $PAM_USER = 'vpxuser' ]
then
   # Raise a VOB.
   $ADD_VOB_CMD vob.user.account.loginfailures $PAM_USER
   # Reset tally counter for the user.
   $PAM_TALLY2_CMD -u $PAM_USER -r
else
   # Raise a VOB.
   $ADD_VOB_CMD vob.user.account.locked $PAM_USER $TIMEOUT $FAILURES
fi
