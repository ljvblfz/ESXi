#!/bin/sh

# kill the watchdog first, so as to not set it off.  Unlikely, but
# there may be old watchdog pid files

for f in /var/run/vmware/vmsyslogd-watchdog-*.pid
do
    kill -INT $(cat $f)
done

kill -INT $(cat /var/run/vmware/vmsyslogd.pid)
