#!/bin/sh

# Gather backtrace info if hostd is running
HOSTD_TAG=hostd
HOSTD_PID="$(pidof -s $HOSTD_TAG)"

if [ -n "${HOSTD_PID}" ]; then
   vmkbacktrace -s ${HOSTD_PID}
fi
