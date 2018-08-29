#!/bin/sh

# Flush and dump vmfs traces
/etc/init.d/vmfstraced flush >/dev/null 2>&1
if [ -d /var/log ]; then
   cd /var/log
   tracefiles="$(ls -tr vmfstraces/vmfsGlobalTrace*.gz 2>/dev/null)"
   if [ -n "$tracefiles" ]; then
      tar -c $tracefiles 2>/dev/null
   fi
fi
