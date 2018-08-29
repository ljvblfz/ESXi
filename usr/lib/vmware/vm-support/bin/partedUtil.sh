#!/bin/sh

SCSIDEVS="/bin/esxcfg-scsidevs"

echo -e "Partition table and usable sector information for disks\n"

DEVS=`$SCSIDEVS -c | grep "Direct-Access" | awk '{print $3}'`
for dev in $DEVS
do
   echo "Device:  $dev"

   # show partition table information
   echo "Partition table:"
   echo -e "$(partedUtil getptbl $dev)\n"

   # show usable sectors information
   echo "Usable sectors:"
   echo -e "$(partedUtil getUsableSectors $dev)\n\n"
done

