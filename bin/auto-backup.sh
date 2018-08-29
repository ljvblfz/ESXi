#!/bin/sh

export PATH=/bin:/sbin

main()
{
   local files_to_save=

   # PXE boots need not be backed-up
   if [ ! -d /bootbank ] ; then
       esxcfg-init --alert "Bootbank cannot be found at path '/bootbank'"
       exit 1
   fi

   if [ ! -f /bootbank/state.tgz ] ; then
      # always backup if we do not yet have a state.tgz
      /sbin/backup.sh 0 || logger "state.tgz not found, auto-backup failed"
      exit 0
   fi

   files_to_save=$(find /etc -follow -type f -name '.#*' 2>/dev/null |
                   sed -e 's,.#\(.*\),\1,g'                          |
                   while read name ; do [ -f "${name}" ] && echo "${name}" ; done)

   tmp_backup_dir="/tmp/auto-backup.$$"

   mkdir -p "${tmp_backup_dir}"

   tar xzf /bootbank/state.tgz -C "${tmp_backup_dir}" || {
      rm -rf "${tmp_backup_dir}"
      logger "Unable to extract system configuration.  Are you out of disk space?"
      exit 1
   }

   tar xzf "${tmp_backup_dir}/local.tgz" -C "${tmp_backup_dir}" || {
      rm -rf "${tmp_backup_dir}"
      logger "Unable to extract system state.  Are you out of disk space?"
      exit 1
   }

   for file in ${files_to_save} ; do
      diff -N "${file}" "${tmp_backup_dir}/${file}" || {
         /sbin/backup.sh 0 || logger "failed to regenerate system configuration"
         break
      }
   done

   # clean up
   rm -rf "${tmp_backup_dir}"
}

main "${@}"

