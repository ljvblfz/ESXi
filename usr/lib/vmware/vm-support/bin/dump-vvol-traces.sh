#!/bin/sh

# Its not an error if vvoltraced is not on the system
[[ -f /etc/init.d/vvoltraced ]] || exit 0

# Flush and dump vvol traces
/etc/init.d/vvoltraced flush >/dev/null 2>&1
if [ -d /var/log ]; then
   cd /var/log
   tracefiles="$(ls -tr vvoltraces/vvol-trace.bin*.gz 2>/dev/null)"
   if [ -n "$tracefiles" ]; then
      tar -c $tracefiles 2>/dev/null
   fi
fi
