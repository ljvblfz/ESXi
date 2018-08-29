#!/bin/sh
/bin/rm -rf /tmp/$$
/bin/mkdir -p /tmp/$$
/bin/esxhpcli gd -o /tmp/$$/gd_results.bin
/bin/esxhpcli ep -c /tmp/$$/gd_results.bin -o /tmp/$$/profile.bin
if [ $# -gt 0 ]; then
   # If there are params then loop through them and print out each host profile
   while [ $# -gt 0 ]; do
      /bin/esxhpedit dp -r -p $1 /tmp/$$/profile.bin
      shift
   done
else
   # If there are no params then print out all storage host profiles
   /bin/esxhpedit dp -r -p storage.psa_psaProfile_PluggableStorageArchitectureProfile /tmp/$$/profile.bin
   /bin/esxhpedit dp -r -p storage.nmp_nmpProfile_NativeMultiPathingProfile /tmp/$$/profile.bin
   /bin/esxhpedit dp -r -p storage.vvol_vvolProfile_VirtualVolumesProfile /tmp/$$/profile.bin
fi
/bin/rm -rf /tmp/$$
