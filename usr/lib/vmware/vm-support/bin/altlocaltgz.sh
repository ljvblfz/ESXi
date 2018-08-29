#!/bin/sh

# create a subdir (with unique name) in /tmp/ so that mkdir operation does not fail
# untar /altbootbank/state.tgz and save it in subdir
# untar $subdir/local.tgz to get etc folder
# find out the files to be skipped from config-system.mfx
# find out list of all the files path (relative to etc folder) in etc folder
# find out the files path which needs to be removed
# send the output to invoking program
# remove the directory that was created

random=`date -u | sed 's/ //g' | sed 's/\://g'`
subdir="/tmp/$random"
mkdir $subdir
tar -xzf /altbootbank/state.tgz -C $subdir 2>/dev/null
tar -xzf $subdir/local.tgz -C $subdir 2> /dev/null

files_to_skip=`awk '$1 == "prune" {print $3}' /etc/vmware/vm-support/config-system.mfx 2> /dev/null | cut -d'/' -f2-`
fileslist=`find $subdir/etc/ -type f 2> /dev/null`

if [ -n "$files_to_skip" ]; then
    echo "$files_to_skip" > $subdir/files_to_skip
    sed 's,.#\(.*\),\1,g' $subdir/files_to_skip > $subdir/filtered_files_to_skip
fi

if [ -n "$fileslist" ];then
    echo "$fileslist" > $subdir/fileslist
    sed -e "s/\/tmp\/$random\///" $subdir/fileslist  > $subdir/fileslist_relative_path
fi

if [ -f "$subdir/fileslist_relative_path" ]  && [ -f "$subdir/filtered_files_to_skip" ]; then
    files_to_save=`grep -v -f $subdir/filtered_files_to_skip $subdir/fileslist_relative_path 2> /dev/null`
    tar -C $subdir -zc $files_to_save 2> /dev/null
fi
rm -rf $subdir 2> /dev/null
