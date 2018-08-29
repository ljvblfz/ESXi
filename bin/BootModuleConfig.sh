#!/bin/sh
# Copyright 2008 VMware Inc.

TRUE=0
FALSE=1

cmd=
mod=
file=
verbose=${FALSE}
bank=/bootbank
lock_dir="/tmp"
lock=

. /etc/vmware/BootbankFunctions.sh

Usage()
{
   echo "Error: $@"
   cat <<EOF
   Usage: $0 [--add=<file>] [--remove=<module>] [--bank=<path>] [--verbose]
      --add=<file>	Adds file <file> to boot bank and boot.cfg
      --remove=<module>	Removes module <module> from boot bank and boot.cfg
      --bank=<path>	Sets path to boot bank (default=/bootbank)
      --verbose		Enable verbose output
EOF
  exit 0
}

vecho()
{
   [ ${verbose} -eq ${TRUE} ] && echo $*
}

warn()
{
   echo $* 1>&2
}

GetBackupLock()
{
   local lock_name=$(basename "${bank}")
   lock="${lock_dir}/${lock_name}.lck"

   vecho "Acquiring lock ${lock}"

   for  i in 0 1 2 4 8 16 32 64 ; do
      sleep ${i}
      # clean stale lock
      if [ -f "${lock}" ]; then
         lockpid=$(cat "${lock}")
         if [ -n "${lockpid}" ]; then
            kill -0 "${lockpid}" > /dev/null 2>&1 || rm -f "${lock}"
         else
            rm -f "${lock}"
         fi
      fi

      lockfile -r 1 "${lock}" && {
         return ${TRUE}
      }
   done

   warn "Failed to acquire backup lock"
   return ${FALSE}
}

ReleaseBackupLock()
{
   rm -f "${lock}"
}

DoAdd()
{
   vecho "Copying ${file} to ${bank}/${mod}"

   cp -f "${file}" "${bank}/${mod}" || {
      warn "Copying ${file} to ${bank}/${mod} failed: $?"
      return ${FALSE}
   }

   VerifyCopiedArchive "${bank}/${mod}"
   res=$?
   if [ "$res" != "0" ] ; then
      warn "Copied archive ${bank}/${mod} is corrupt, deleting: $res"
      esxcfg-init --alert "Copied archive ${bank}/${mod} is corrupt, deleting: $res"
      rm -f "${bank}/${mod}"
      return ${FALSE}
   fi

   vecho "Editing ${bank}/boot.cfg to add module ${mod}"

   # Add module to modules list (but only if it is not already present)
   sed -e "/^modules=/{ / --- ${mod}/!s/$/ --- ${mod}/ }" \
      "${bank}/boot.cfg" > "${bank}/boot-new.cfg" || {
      warn "Editing ${bank}/boot.cfg failed: $?"
      return ${FALSE}
   }

   mv -f "${bank}/boot-new.cfg" "${bank}/boot.cfg" || {
      warn "Failed to rename ${bank}/boot-new.cfg to ${bank}/boot.cfg: $?"
      return ${FALSE}
   }

   return ${TRUE}
}

DoRemove()
{
   [ -n "${mod}" -a -f "${bank}/${mod}" ] || return ${FALSE}

   vecho "Editing ${bank}/boot.cfg to remove module ${mod}"

   sed -e "/^modules=/{ / --- ${mod}/s/ --- ${mod}// }" \
      "${bank}/boot.cfg" > "${bank}/boot-new.cfg" || {
      warn "Editing ${bank}/boot.cfg failed: $?"
      return ${FALSE}
   }

   mv -f "${bank}/boot-new.cfg" "${bank}/boot.cfg" || {
      warn "Failed to rename ${bank}/boot-new.cfg to ${bank}/boot.cfg: $?"
      return ${FALSE}
   }

   vecho "Removing ${bank}/${mod}"

   rm -f "${bank}/${mod}"
   return ${TRUE}
}

for optarg in "$@"; do
   case $optarg in
      --add=*)
         file=$(echo "$optarg" | cut -d"=" -f2-)
         [ -f "$file" ] || {
            warn "File $file does not exist"
            exit 1
         }
         mod=$(basename "$file")
         cmd="add"
         ;;
      --remove=*)
         mod=$(echo "$optarg" | cut -d"=" -f2-)
         cmd="del"
         ;;
      --bank=*)
         bank=$(echo "$optarg" | cut -d"=" -f2-)
         [ -f "$bank/boot.cfg" ] || {
            warn "Cannot find $bank/boot.cfg"
            exit 1
         }
         ;;
      --verbose)
         verbose=${TRUE}
         ;;
      *)
         Usage "Unknown argument $optarg"
         ;;
   esac
done

[ -n $cmd ] || {
   Usage "Must specify one of --add or --remove"
}

res=${FALSE}

case $cmd in
   add)
      GetBackupLock && DoAdd && {
         res=${TRUE}
      }
      ReleaseBackupLock
      ;;
   del)
      GetBackupLock && DoRemove && {
         res=${TRUE}
      }
      ReleaseBackupLock
      ;;
   *)
      Usage "Invalid command $cmd"
      ;;
esac
exit ${res}

