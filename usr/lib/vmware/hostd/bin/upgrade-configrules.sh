#!/bin/sh

syslog() {
   echo "$@"
   logger -p daemon.info -t "hostd-upgrade-configrules" "$@"
}

CONFIGRULES=/etc/vmware/configrules
DEFAULTCONFIGRULES=/etc/vmware/defaultconfigrules

DEFAULT_VERSION=$(grep -o "CONFIGRULES_VERSION .*" "$DEFAULTCONFIGRULES")
CURRENT_VERSION=$(grep -o "CONFIGRULES_VERSION .*" "$CONFIGRULES")
if [ "$DEFAULT_VERSION" != "$CURRENT_VERSION" ]; then
   if cp "$DEFAULTCONFIGRULES" "$CONFIGRULES"; then
      chmod 01644 "$CONFIGRULES"
      syslog "Upgraded $CONFIGRULES from previous version. Local edits were overwritten."
   else
      syslog "Failed to upgrade $CONFIGRULES from previous version!"
   fi
fi
