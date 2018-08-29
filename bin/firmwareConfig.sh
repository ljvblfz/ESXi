#!/bin/sh

. /etc/vmware/BootbankFunctions.sh

Usage()
{
   echo "Usage: $0 <cmd> [--force] [configurationBundleFile|configurationBundleDirectory]"
   echo "Commands:"
   echo " --reset       Reset the firmware configuration to factory defaults and reboot"
   echo " --reset-only  Reset the firmware configuration to factory defaults"
   echo " --remove-third-party    Remove custom ESXi extensions"
   echo " --restore     Restore firmware configuration to that specified in the bundle file"
   echo " --backup      Backup firmware configuration to the file specified"
   echo "Options:"
   echo " --force   Force restore even if the bundle is mismatched"

   exit 1
}


#
# Match expressions of the following form: key=value
# Usage: GetValue(<config file>, <option>)
#
GetValue()
{
   sed -n -e "/${2}=/s/${2}=//p" "${1}"
}


#
# Reset firmware configuration to factory defaults
#
ResetToFactoryDefaults()
{
   # remove state
   sed -e '/^modules=/{ s,--- state.tgz,, }' /bootbank/boot.cfg > "/bootbank/boot.cfg.$$"
   mv -f "/bootbank/boot.cfg.$$" /bootbank/boot.cfg
   rm -f '/bootbank/state.tgz'


   # restore kernel options
   # The boot option installerDiskDumpSlotSize is considered to be a factory
   # default setting, so we have to preserve the value of that boot option
   # across a factory default reset.
   local installerDiskDumpSlotSize=`grep "installerDiskDumpSlotSize=" /bootbank/boot.cfg`
   if [ ! -z "${installerDiskDumpSlotSize}" ]; then
      local slotSize=`echo "${installerDiskDumpSlotSize}" | awk -F "installerDiskDumpSlotSize=" {'print $2'} | awk {'print $1'}`
      local option="installerDiskDumpSlotSize="${slotSize}""
      sed -e "/^kernelopt=/ckernelopt= "${option}"" /bootbank/boot.cfg > "/bootbank/boot.cfg.$$"
   else
      sed -e '/^kernelopt=/ckernelopt=' /bootbank/boot.cfg > "/bootbank/boot.cfg.$$"
   fi
   mv -f "/bootbank/boot.cfg.$$" /bootbank/boot.cfg
   touch "/tmp/useropts.$$"
   gzip "/tmp/useropts.$$"
   mv -f "/tmp/useropts.$$.gz" /bootbank/useropts.gz

   # restore runonce plugins
   touch "/tmp/jumpstrt.$$"
   gzip "/tmp/jumpstrt.$$"
   mv -f "/tmp/jumpstrt.$$.gz" /bootbank/jumpstrt.gz
}


#
# Backup firmware configuration to a file called configBundle.tgz under
# the specified directory
#
# Usage: BackupConfiguration(<bundleDir>)
#
BackupConfiguration()
{
   mkdir -p "${1}/firmware-backup.$$"

   # create the state.tgz backup
   /sbin/backup.sh 0 "${1}/firmware-backup.$$" || exit $?

   # create the supporting manifest file
   cat > "${1}/firmware-backup.$$/Manifest.txt" <<-EOF
RELEASELEVEL=$(vmware -l)
UUID=$(esxcfg-info -u)
KERNELOPTS=$(GetValue "/bootbank/boot.cfg" kernelopt)
USEROPTS=$(esxcfg-info -c)
EOF

   # create the bundle
   (
      cd "${1}/firmware-backup.$$"
      tar czf "${1}/configBundle-$(hostname).tgz" *
   )

   # cleanup staging area
   rm -rf "${1}/firmware-backup.$$"

   echo "ConfigBundle: ${1}/configBundle-$(hostname).tgz"
}


#
# Restore configuration from the specified configuration bundle.
#
# Usage: RestoreConfiguration(<bundleFile>, <force>)
#
RestoreConfiguration()
{
   local bundle=${1} force=${2}
   local tmpdir="/tmp/firmware-restore.$$"
   local host_uuid=$(esxcfg-info -u) bundle_uuid=
   local host_release=$(vmware -l) bundle_release=
   local manifest_file="${tmpdir}/Manifest.txt"

   mkdir -p "${tmpdir}"

   tar xzf "${bundle}" -C "${tmpdir}"
   if [ ! -e "${manifest_file}" ] ; then
      echo "Invalid Bundle: Missing Manifest File"
      rm -rf "${tmpdir}"
      exit 1
   fi

   bundle_uuid=$(GetValue "${manifest_file}" UUID)
   bundle_release=$(GetValue "${manifest_file}" RELEASELEVEL)

   # validate version and UUID
   if [ "${bundle_release}" != "${host_release}" ] ; then
      echo "Mismatched Bundle: Host release level: ${host_release} Bundle release level: ${bundle_release}"
      rm -rf "${tmpdir}"
      exit 1
   fi

   if [ "${host_uuid}" != "${bundle_uuid}" ] && [ ${force} -ne 1 ] ; then
      echo "Mismatched Bundle: Host UUID: ${host_uuid} Bundle UUID: ${bundle_uuid}"
      rm -rf "${tmpdir}"
      exit 1
   fi

   # restore state
   CopyAndVerify "${tmpdir}/state.tgz" "/bootbank/state.tgz.$$"
   mv -f "/bootbank/state.tgz.$$" "/bootbank/state.tgz"

   # restore kernel options
   sed -e "/kernelopt=/ckernelopt=$(GetValue "${manifest_file}" KERNELOPTS)" /bootbank/boot.cfg > "/bootbank/boot.cfg.$$"
   mv -f "/bootbank/boot.cfg.$$" /bootbank/boot.cfg

   echo "$(GetValue ${manifest_file} USEROPTS)" | gzip -c > "/tmp/useropts.$$.gz"
   mv -f "/tmp/useropts.$$.gz" /bootbank/useropts.gz

   # append state.tgz to the modules list
   if ! grep -q state.tgz /bootbank/boot.cfg ; then
      sed -e '/^modules=/{ s,$, --- state.tgz, }' /bootbank/boot.cfg > "/bootbank/boot.cfg.$$"
      mv -f "/bootbank/boot.cfg.$$" /bootbank/boot.cfg
   fi

   sync

   # forcefully reboot to ensure that backup.sh is not called
   # /tmp is in visorfs, so it will be cleaned out by virtue of the RAM FS being
   # non-persistent
   reboot -f
}


# main()
case "${1}" in
   "--reset" )
      ResetToFactoryDefaults
      reboot -f
   ;;
   "--reset-only" )
      ResetToFactoryDefaults
   ;;
   "--remove-third-party" )
      # 3rd party extensions were stored in mod.tgz in the 3.5 release, and was
      # renamed to m.z in 4.0.  As of 5.0, m.z is no longer present.
      echo "--remove-third-party is deprecated and should not be used." >&2
      echo "Third party extensions no longer exist as of ESXi 5.0." >&2
      exit 0
   ;;
   "--backup" ) 
      [ $# -lt 2 ] && Usage
      BackupConfiguration "${2}"
   ;;
   "--restore" )
      [ $# -lt 2 ] && Usage

      if [ X"${2}" = X"--force" ]; then
         [ $# -lt 3 ] && Usage
         RestoreConfiguration "${3}" 1
      else
         RestoreConfiguration "${2}" 0
      fi
   ;;
   *)
      Usage
   ;;
esac

