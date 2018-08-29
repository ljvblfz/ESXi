#!/bin/sh

#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Upgrade rhttpproxy/endpoints.conf file.
#

FILE_PATH="/etc/vmware/rhttpproxy/endpoints.conf"

LOG_TAG="upgrade-endpoints.conf.sh"

logger -t $LOG_TAG "Upgrade check for file $FILE_PATH"

# Update the port number for server namespace /cgi-bin to 8303.
#
# The /cgi-bin port number is hard-coded in the read-only config file
# /etc/vmware/hostd/cgi-config.xml.
#
# In older releases /cgi-bin was handled by hostd on port 8309.
# Now /cgi-bin is handled by a standalone CGI service on port 8303.
CGI_PORT=8303
CGI_LINE="/cgi-bin                 local            $CGI_PORT                             redirect       allow"

# Check if the port number for /cgi-bin is not 8303 and needs updating.
grep "/cgi-bin" $FILE_PATH | grep -q -v -E "/cgi-bin[ \t]+local[ \t]+$CGI_PORT[ \t]+.*"
if [ $? != 0 ]
then
   logger -t $LOG_TAG "Upgrade not needed"
   exit 0
fi

# Need to update - just replace the line with the new one.
logger -t $LOG_TAG "Fixing port number for /cgi-bin to $CGI_PORT"

# Work on a temporary file.
cp $FILE_PATH ${FILE_PATH}.tmp
sed -e "/^\/cgi-bin/c\\$CGI_LINE" -i ${FILE_PATH}.tmp
mv ${FILE_PATH}.tmp $FILE_PATH

# Signal rhttpproxy (if found) to reload its config.
kill -sighup `pidof rhttpproxy` 2>/dev/null
