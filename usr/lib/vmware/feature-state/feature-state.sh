#!/bin/sh

# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential

# Feature state library for shell scripts. It calls into the python version of
# the library to get the feature state info and exits if the feature name is
# unknown or the value is other than 'enabled' or 'disabled'.

isFeatureEnabled ()
{
   local featureName=$1
   local filename="/usr/lib/vmware/feature-state/feature-state-wrapper.py"
   state=$(python ${filename} ${featureName} 2>&1)

   if [ "$state" == "enabled" ]; then
      return 0
   elif [ "$state" == "disabled" ]; then
      return 1
   else
      echo "$state"
      echo "Fatal error while getting feature state for '${featureName}'" 1>&2
      exit 71
   fi
}


isFeatureDisabled ()
{
   local featureName=$1
   local filename="/usr/lib/vmware/feature-state/feature-state-wrapper.py"
   state=$(python ${filename} ${featureName} 2>&1)

   if [ "$state" == "disabled" ]; then
      return 0
   elif [ "$state" == "enabled" ]; then
      return 1
   else
      echo "$state"
      echo "Fatal error while getting feature state for '${featureName}'" 1>&2
      exit 71
   fi
}
