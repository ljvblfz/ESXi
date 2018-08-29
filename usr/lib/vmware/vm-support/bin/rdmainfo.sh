#!/bin/sh

# Gather information for RDMA devices
LOCALCLI="/sbin/localcli"
ETHTOOL="/sbin/ethtool"
VSISH="/bin/vsish"

echo "RDMA Device Information."
echo

DEVICES=`$LOCALCLI --format-param=show-header=false rdma device list | awk '{print $1}'`

echo "Output of \"localcli rdma device list\":"
$LOCALCLI rdma device list
echo

echo "Output of \"localcli rdma device vmknic list\":"
$LOCALCLI rdma device vmknic list
echo

echo "Per-device output:"
for device in $DEVICES
do
    echo "DEVICE:  $device"

    echo "Statistics:"
    # show statistics
    $LOCALCLI rdma device stats get --device $device

    # show private stats
    echo "Private statistics:"
    $LOCALCLI --plugin-dir /usr/lib/vmware/esxcli/int rdmainternal \
              device privstats get --device $device
    echo
done

