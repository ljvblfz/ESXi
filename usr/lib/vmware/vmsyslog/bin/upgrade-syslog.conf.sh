#!/bin/sh

OLD_CONFIG=/etc/syslog.conf

if [ -f "$OLD_CONFIG" ]; then

   OLD_LOGHOST="$(awk -F '=' '/^loghost=/ { print $2 }' "${OLD_CONFIG}")"
   OLD_LOGDIR="$(awk -F '='  '/^logdir=/  { print $2 }' "${OLD_CONFIG}")"
   OLD_LOGFILE="$(awk -F '=' '/^logfile=/ { print $2 }' "${OLD_CONFIG}")"

   # logfile turned into logdir ages ago, but handle it anyway.  We
   # just use the dirname -- this is what the old syslog daemon was
   # doing.
   if [ -n "${OLD_LOGFILE}" ]; then
       OLD_LOGDIR="$(dirname "${OLD_LOGFILE}")/"
   fi

   if [ -d "${OLD_LOGDIR}" ]; then
       localcli system syslog config set --logdir="${OLD_LOGDIR}"
       logger $0 logdir updated: ${OLD_LOGDIR}
   fi

   if [ -n "${OLD_LOGHOST}" ]; then
       localcli system syslog config set --loghost="${OLD_LOGHOST}"
       logger $0 loghost updated: ${OLD_LOGHOST}
   fi

   echo "# this file has been migrated; see esxcli.system.syslog" > "${OLD_CONFIG}.old"
   cat "${OLD_CONFIG}" >> "${OLD_CONFIG}.old"
   rm "${OLD_CONFIG}"

fi
