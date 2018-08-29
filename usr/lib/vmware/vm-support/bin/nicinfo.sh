#!/bin/sh

# Gather information about Network Interface Cards.
LOCALCLI="/sbin/localcli"
ETHTOOL="/sbin/ethtool"
VSISH="/bin/vsish"

echo "Network Interface Cards Information."
echo

NICS=`$LOCALCLI --format-param=show-header=false network nic list | cut -d ' ' -f 1`
# Show all NIC settings, same output as "esxcfg-nic -l"
$LOCALCLI network nic list
echo

for nic in $NICS
do
    echo "NIC:  $nic"
    echo
    # Show generic and driver information
    $LOCALCLI network nic get --nic-name=$nic

    # check if a nic is driven by legacy or native driver
    legacy=`$VSISH -e get /net/pNics/$nic/properties | \
            grep -E "^[[:blank:]]+Legacy" | cut -d ':' -f 2`
    if [ "$legacy" == "1" ]; then
       # Show RX/TX ring information
       $ETHTOOL --show-ring $nic
    fi
    # XXX: add RX/TX ring information for native driver once it's supported

    # show NIC statistics
    $LOCALCLI network nic stats get -n $nic

    # show private stats for both legacy and native driver
    echo "NIC Private statistics:"
    $LOCALCLI --plugin-dir /usr/lib/vmware/esxcli/int networkinternal \
              nic privstats get -n $nic
    echo
done

