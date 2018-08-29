#!/bin/sh

. /etc/vmware/BootbankFunctions.sh

TRUE=0
FALSE=1

EXIT_SUCCESS=0
EXIT_FAILURE=1

LIVEINST_MARKER=/var/run/update_altbootbank

sysalert()
{
   esxcfg-init --alert "${*}"
   echo "${*}" >&2
}

mark_is_shutdown()
{
   case "${1}" in
      "0")
         eval "is_shutdown() { return 1 ; }"
      ;;
      "1")
         eval "is_shutdown() { return 0 ; }"
      ;;
      *)
         echo "Invalid parameter for is_shutdown: ${1}" >&2
         return 1
      ;;
   esac

   return 0
}

verify_ssl_certificates()
{
   [ -s "/etc/vmware/ssl/rui.key" ] && [ -s "/etc/vmware/ssl/rui.crt" ]
}

update_bootcfg()
{
   local bootbank=${1}

   if [ -s "${bootbank}/state.tgz" ] ; then
      if ! grep -q -e '--- state.tgz' "${bootbank}/boot.cfg" ; then
         sed -e '/^modules=/{ s/$/ --- state.tgz/ }' "${bootbank}/boot.cfg" > "${bootbank}/boot.cfg.$$"
         [ -s "${bootbank}/boot.cfg.$$" ] && mv -f "${bootbank}/boot.cfg.$$" "${bootbank}/boot.cfg"
         rm -f "${bootbank}/boot.cfg.$$"
         sync
      fi
   fi
}

update_bootbank_file()
{
   local bootbank="$1"
   local new="$2"
   local name="$3"

   local cur="${bootbank}/${name}.gz"
   local old="/tmp/${name}.old.$$"
   local comp="${new}.gz"

   gunzip -c "${cur}" > "${old}"

   diff -q "${new}" "${old}" >/dev/null 2>&1 || {
      # save kernel options
      if gzip "${new}" ; then
         # move from /tmp to ${bootbank} without overwriting ${name}.gz so that an
         # interrupted copy doesn't corrupt ${name}.gz  If the move succeeds, we
         # will rename the temporary file to boot.cfg (this assumes that rename
         # is effectively atomic).
         if mv -f "${comp}" "${bootbank}/${name}.$$.gz" ; then
            mv -f "${bootbank}/${name}.$$.gz" "${bootbank}/${name}.gz"
         else
            sysalert "Failed to move ${name}.gz from /tmp to ${bootbank}.  Updated kernel options may be lost"
         fi
      else
         sysalert "Failed to create ${name}.gz in /tmp. Updated kernel options may be lost."
      fi
   }

   rm -f "${old}" "${comp}"
}

create_state_tgz()
{
   local lock="$1"
   local bootbank="$2"
   local files_to_skip="$3"
   local delay="$4"

   cd /

   # Save all modified files in /etc.
   # Omit files a) where the .# file exists but the original one doesn't.
   #            b) specified to be skipped.
   local files_to_save=$(find etc -follow -type f -name '.#*' 2> /dev/null | \
                         sed -e 's,.#\(.*\),\1,g' |                          \
                         while read name ; do  \
                            if [ -f "${name}" ]; then echo ${files_to_skip} | \
                            grep -q ${name} || echo "${name}"; fi; \
                         done)

   # If running for vm-support, just print the file list.
   if [ -n "$VMSUPPORT_MODE" ] && [ -n "${files_to_save}" ]; then
      echo $files_to_save >&1
   fi

   # Otherwise, create state.tgz.
   if [ -z "$VMSUPPORT_MODE" ] && [ -n "${files_to_save}" ]; then
      # cleanup possible file leakage
      rm -rf "${bootbank}"/local.tgz.*
      rm -rf "${bootbank}"/state.tgz.*

      # Write to a temp file on same filesystem and then rename the file so
      # that we don't get a corrupted local.tgz if we are killed while
      # running tar.  Try twice at shutdown.
      # Also try twice if tar command failed.
      #
      # Verify the files between operations as power failures and flash media
      # caching are known to make state saving an unreliable process if done
      # naively.  See Bug #332281 and Bug #363887 for more information.
      for try in 0 1 ; do
         local res=0

         # Get the esx.conf lock to be sure we get a consistent view
         # of the configuration.
         logger -t "backup.sh.$$" "Locking esx.conf"
         esxcfg-init -L $$ || is_shutdown || {
               rm -f "${lock}"
               return ${EXIT_FAILURE}
         }

         logger -t "backup.sh.$$" "Creating archive"
         cmd="tar czf ${bootbank}/local.tgz.$$ -C / ${files_to_save}"
         msg=$(${cmd} 2>&1)
         res=$?

         # Release esx.conf lock
         logger -t "backup.sh.$$" "Unlocking esx.conf"
         esxcfg-init -U $$

         if [ ${res} -eq 0 -a -s "${bootbank}/local.tgz.$$" ] ; then
            mkdir -p "${bootbank}/state.$$"

            mv "${bootbank}/local.tgz.$$" "${bootbank}/state.$$/local.tgz"

            if tar czf "${bootbank}/state.tgz.$$" -C "${bootbank}/state.$$" local.tgz ; then
               if [ -s "${bootbank}/state.tgz.$$" ] ; then
                  mv -f "${bootbank}/state.tgz.$$" "${bootbank}/state.tgz"
               fi
            else
               sysalert "failed to create state.tgz"
            fi

            sync

            rm -rf "${bootbank}/state.$$"
            break
         else
            logger "Failed command: ${cmd}"
            logger "Error: ${msg}"
            if [ ${try} -eq 1 ] ; then
               sysalert "Error (${res}) saving state to ${bootbank}"
               res=1
               break
            fi
         fi

         if [ ! -z "${delay}" ] ; then
            # Sleep delay seconds before trying again
            sleep ${delay}
         fi
      done
   fi
}

update_useroptsgz()
{
   local bootbank=${1}
   local new="/tmp/useropts.new.$$"

   esxcfg-info -c > "${new}"

   update_bootbank_file "${bootbank}" "${new}" useropts

   rm -f "${new}"
   sync
}

update_jumpstrtgz()
{
   local bootbank=${1}
   local cur="/bootbank/jumpstrt.gz"
   local new="/tmp/jumpstrt.new.$$"

   if [ "${bootbank}" == "/bootbank" ]; then
      return
   fi

   # create the file if it does not exist so that
   # update_bootbank_file can do the right thing
   if [ ! -e "${bootbank}/jumpstrt.gz" ]; then
      touch "${bootbank}/jumpstrt"
      gzip "${bootbank}/jumpstrt"
   fi

   gunzip -c "${cur}" > "${new}"

   update_bootbank_file "${bootbank}" "${new}" jumpstrt

   rm -f "${new}"
   sync
}

update_featuresgz()
{
   local featcfg="/etc/vmware/vsphereFeatures/vsphereFeatures.cfg"

   if [ ! -f "${featcfg}" ]; then
      return
   fi

   local bootbank=${1}
   local new="/tmp/features.new.$$"

   sed -e 's/\(.*\) = \(.*\)/FeatureState.\1=\2/' < "${featcfg}" > "${new}"

   update_bootbank_file "${bootbank}" "${new}" features

   rm -f "${new}"
   sync
}

FileSystemCheckRequired()
{
   local fsCheck=$(vsish -e get /vmkModules/vfat/fsInfo | awk -F: '/fsCheck/ {print $2}')

   if [ $(bootOption -rf) -eq 0 -a "$fsCheck" = "0" ] ; then
      return ${FALSE}
   else
      return ${TRUE}
   fi
}

GetPrimaryBootVolume()
{
   local BootUUID=$(esxcfg-info -b 2> /dev/null)
   local BootVolume=

   if [ -n "${BootUUID}" ] ; then
      BootVolume="/vmfs/volumes/${BootUUID}"
   fi

   echo ${BootVolume}
}

GetHBAFromVolume()
{
   echo $(vmkfstools -P "$1" 2> /dev/null | awk '/^Partitions/ { getline; print gensub(/.*[\t ]([^ ]+):[0-9]+.*/, "\\1", "", $0); }')
}

GetBootHBA()
{
   local BootVolume=$(GetPrimaryBootVolume)
   local BootHBA=

   if [ -n "${BootVolume}" ] ; then
      BootHBA=$(GetHBAFromVolume "${BootVolume}")
   fi

   echo ${BootHBA}
}

RunFileSystemCheck()
{
   local BootDevice=$(GetBootHBA)

   for partition in 5 6 8 ; do
      disk="/dev/disks/${BootDevice}:${partition}"

      if [ -f "${disk}" ] ; then
         dosfsck -a -v "${disk}" || sysalert "Possible corruption on ${disk}"
      fi
   done
}


#
# Remove a stale lock
RemoveStaleLock()
{
   local lock="${1}"
   local pid="${2}"
   logger -t "backup.sh.$$" "Found stale lock ${lock} with PID ${pid}"

   # Protect removal of stale locks by locking esx.conf.
   esxcfg-init -L $$ || {
      logger -t "backup.sh.$$" "Skip stale lock removal: esx.conf lock failed"
      return
   }

   # Now when we've locked esx.conf, check that the PID is the same
   # to avoid a race.

   local pid2=$(cat "${lock}")
   if [ "${pid2}" == "${pid}" ]
   then
      rm -f "${lock}"
      esxcfg-init -U $$
      logger -t "backup.sh.$$" "Stale lock removed"
   else
      esxcfg-init -U $$
      logger -t "backup.sh.$$" "Skip stale lock removal: new PID = ${pid2}"
   fi
}


#
# Try to clean up a stale lock.
#

TryCleanupStaleLock()
{
   local lock="$1"
   if [ -f "${lock}" ] ; then
      local pid=$(cat "${lock}")

      if [ -n "${pid}" ] ; then
         kill -0 "${pid}" >/dev/null 2>&1 || RemoveStaleLock "${lock}" "${pid}"
      else
         RemoveStaleLock "${lock}"
      fi
   fi
}


#
# if grep -q '^bootstate=1' /altbootbank/boot.cfg ; then
#   if [ -f /var/run/update_altbootbank ] ; then
#      ### write config to /altbootbank/state.tgz
#   else
#      ### write config to /bootbank/state.tgz
#      ### cp /bootbank/state.tgz /altbootbank/state.tgz
#   fi
# else
#    ### write config to /bootbank/state.tgz
# fi
#

main()
{
   local bootbank=${2}
   local lock=
   local update_alt_bootbank=""
   # Testing option
   local delay=${3}

   # check parameters
   if [ ${#} -lt 1 ] ; then
      echo "Usage: ${0} IsShutdown [PATH_NAME]" >&2
      return ${EXIT_SUCCESS}
   fi

   if [ -z "${bootbank}" -a -f "${LIVEINST_MARKER}" -a -f /altbootbank/boot.cfg ] ; then
      update_alt_bootbank=$(awk -F= '/^bootstate=[0-9]/{ print $2 }' /altbootbank/boot.cfg)
   fi

   if [ -z "${bootbank}" ] ; then
      if  [ "${update_alt_bootbank}" = "0" ] ; then
         # When LiveVib is installed, altbootbank_bootstate is set to 0.
         bootbank='/altbootbank'
      else
         bootbank='/bootbank'
      fi
   fi

   lock="/tmp/$(basename "${bootbank}").lck"

   mark_is_shutdown "${1}" || return ${EXIT_FAILURE}

   # audit-mode check
   [ "$(bootOption -ri)" = "1" ] && return ${EXIT_SUCCESS}

   # XXX Sanity check for QA.  See Bug #184932 for more information.
   # Panic and halt shutdown if the SSL certificates are invalid
   if ! verify_ssl_certificates ; then
      sysalert "SSL certificates are invalid"
      is_shutdown || return ${EXIT_FAILURE}
      while true ; do : ; done
   fi

   if [ ! -d "${bootbank}" ] ; then
      sysalert "Bootbank cannot be found at path '${bootbank}'"
      return ${EXIT_FAILURE}
   fi

   # Obtain a backup lock to prevent simultaneous backups with the same target
   # from clobbering one another.
   #
   # When called from shutdown, we will break locks so that a dead lock holder
   # doesn't prevent us from completing.  Otherwise we will exit without doing
   # anything if we timeout on the locks.

   # Try to clean up a stale lock before trying to take it.
   TryCleanupStaleLock "${lock}"

   if is_shutdown ; then
      # timeout is 1 min
      lockfile -l 60 "${lock}"
   else
      lockfile -3 -r 20 "${lock}" || return ${EXIT_FAILURE}
   fi

   # backup counter with creation and modification time
   COUNTER_FILE="/etc/vmware/.backup.counter"

   if [ -f $COUNTER_FILE ]
   then
      COUNTER=$(cat $COUNTER_FILE | grep -v '#')
      STR_CREATED=$(cat $COUNTER_FILE | grep '# CREATED:')
   fi
   if [ -z "$COUNTER" ]
   then
      COUNTER=0
   fi
   if [ -z "$STR_CREATED" ]
   then
      STR_CREATED="# CREATED: $(date)"
   fi
   NEW_COUNTER=$(expr $COUNTER + 1)

   # update counter file
   echo "# This file is owned and updated by /sbin/backup.sh" >$COUNTER_FILE
   echo $STR_CREATED >>$COUNTER_FILE
   echo "# MODIFIED: $(date)" >>$COUNTER_FILE
   echo $NEW_COUNTER >>$COUNTER_FILE

   : "${files_to_skip:=}"
   [ -z "$VMSUPPORT_MODE" ] && echo "Saving current state in ${bootbank}"
   (
      create_state_tgz ${lock} ${bootbank} "${files_to_skip}" ${delay}
   )

   # sanity check altbootbank if we have just upgraded
   if is_shutdown && [ -f /altbootbank/boot.cfg ] ; then
      local bootbank_serial=$(awk -F= '/^updated/{ print $2 }' /bootbank/boot.cfg)
      local altbootbank_serial=$(awk -F= '/^updated/{ print $2 }' /altbootbank/boot.cfg)
      local altbootbank_state=$(awk -F= '/^bootstate/{ print $2 }' /altbootbank/boot.cfg)
      local failures=0

      if [ ${bootbank_serial} -lt ${altbootbank_serial} -a ${altbootbank_state} -lt 2 ] ; then
         # refresh state.tgz in altbootbank when the host is updated.
         # Normal vib update: altbootbank_state = 1
         # Live vib update: altbootbank_state = 0
         if [ -d /bootbank -a -d /altbootbank -a "${bootbank}" != '/altbootbank' ] ; then
            if [ -d /var/run/configblacklist ] ; then
               cd /var/run/configblacklist
               blacklist_files=$(find * -type f 2> /dev/null)
               files_to_skip="$files_to_skip $blacklist_files"
            fi
            create_state_tgz ${lock} /altbootbank "${files_to_skip}" ${delay}
         fi

         for file in /altbootbank/* ; do
            [ -f "${file}" ] || continue

            VerifyCopiedArchive "${file}" || {
               res=$?

               sysalert "New version of ${file} appears corrupt, upgrade may fail"
               failures=$(( ${failures} + 1 ))
            }
         done

         if [ ${failures} -gt 0 ] ; then
            sysalert "New upgrade image appears corrupted, upgrade may fail"
            sleep 10
         fi
      fi
   fi

   # Sync hardware clock
   hwclock $(date -u "+-t %H:%M:%S -d %m/%d/%Y") >&2

   # Save vmkernel options
   # Do this after unlocking esx.conf.LOCK.
   # Potentially we could have a mismatch between esx.conf and the saved
   # options. We will ignore the last minute change and address it in the next
   # backup cycle.
   if [ -e "${bootbank}/boot.cfg" ]; then
      update_bootcfg "${bootbank}" || {
         res=$?
         sysalert "Failed to update boot.cfg on ${bootbank}"
      }
   fi

   if [ -e "${bootbank}/useropts.gz" ]; then
      update_useroptsgz "${bootbank}"
   fi

   if [ -e "/bootbank/jumpstrt.gz" ]; then
      update_jumpstrtgz "${bootbank}"
   fi

   if [ -e "${bootbank}/features.gz" ]; then
      update_featuresgz "${bootbank}"
   fi


   # In the case of shutdown don't delete the lock.
   # lockfile is in ramdisk so shutdown should take care of deleting it.
   if ! is_shutdown ; then
      rm -f "${lock}"
   else
      # run file system check if necessary
      if FileSystemCheckRequired ; then
         echo "Starting filesystem check on VFAT partitions" >&2
         RunFileSystemCheck
      fi
   fi

   return ${res}
}

main "${@}"

