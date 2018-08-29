#!/bin/sh

# Gather information about Software from CIM Providers.

echo "Software and Firmware versioning info from CIM Providers."
echo 
export NS=`enum_instances CIM_Namespace root/interop | grep " Name = " | sed 's/[ ]*Name =//'`

for namespace in $NS
do
    echo "Namespace:  $namespace"
    enum_instances CIM_SoftwareIdentity $namespace | sed  -n '/\(NULL\)/ !p'
    echo
    echo
done


