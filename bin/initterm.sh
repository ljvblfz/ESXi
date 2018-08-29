#!/bin/sh

GetBootOption()
{
   local key="$(echo "${1}" | sed -e 's:\([\^\$\.\*\/]\):\\\1:g')"
   /sbin/bootOption -roC | sed -ne 's:.*\b'"${key}"'\b\s*=\s*\(\([^ \\]\|\\.\)\+\).*:\1:Ip' 2>/dev/null
}


# Check ESX boot options to see if terminal is to be redirected over serial 
# connection
serialPortBootOpt="$(GetBootOption ${1}Port)"

# ESX boot options are case-insensitive; convert to lower case
serialPort=`echo $serialPortBootOpt | awk '{print tolower($0)}'`

# Set terminal type depending on whether tty is redirected over serial connection
case $serialPort in
   com1|com2|firewire) export TERM=vt102;;
   *) export TERM=linux;;
esac

shift
exec "$@"

