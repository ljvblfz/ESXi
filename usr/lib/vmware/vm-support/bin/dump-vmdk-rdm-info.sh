#!/bin/sh

# Dump raw disk mapping (rdm) information about every virtual disk
vmCfg="$1"
vmDir="$(dirname "$vmCfg")"

awk 'tolower($0) ~ /^[^#].*filename.*=.*vmdk/ { \
        val = substr($0, match($0, "= *") + RLENGTH); \
        sub("^\"", "", val); \
        sub("\" *$", "", val); \
        print val; }' "$vmCfg" |
while read VMDK; do
   ( cd "$vmDir";
   echo "# vmkfstools -q $VMDK";
   /sbin/vmkfstools -q "$VMDK"; )
done
