#!/bin/sh

SFCBD_CFG=/etc/sfcb/sfcb.cfg
DISABLED=$(egrep -i "^\s*enabled\s*:\s*false\s*$" ${SFCBD_CFG})
       if [ "${DISABLED}" != "" ]; then
   echo "INFO: sfcbd is administratively disabled"
   exit 0
fi

INTEROP_CLASSES="CIM_Namespace \
CIM_RegisteredProfile \
CIM_IndicationFilter \
CIM_ListenerDestination \
CIM_IndicationSubscription "

IMPL_CLASSES="CIM_Sensor \
OMC_RawIpmiSensor \
OMC_RawIpmiEntity \
CIM_ComputerSystem \
CIM_Chassis \
CIM_SoftwareIdentity \
CIM_Memory \
CIM_PhysicalMemory \
CIM_Processor \
CIM_LogRecord \
CIM_RecordLog \
CIM_EthernetPort \
CIM_PowerSupply \
CIM_PCIDevice \
CIM_StorageExtent \
CIM_Controller \
CIM_StorageVolume \
CIM_Battery \
CIM_SASSATAPort "

echo "[`date`] CIM Diagnostic dump for root/interop"
for CLASS in $INTEROP_CLASSES
do
   echo "[`date`] Dumping instances of $CLASS"
   enum_instances $CLASS root/interop
done

echo "[`date`] CIM Diagnostic dump for root/cimv2"
for CLASS in $IMPL_CLASSES
do
   echo "[`date`] Dumping instances of $CLASS"
   enum_instances $CLASS
done

echo "[`date`] CIM Provider Diagnostic dump"
enum_instances sfcb_providerdiagnostics root/interop

echo "[`date`] CIM Diagnostic dump completed"
