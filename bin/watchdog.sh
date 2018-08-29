#!/bin/sh
#
# Watchdog script that manages VMware services.
# Launches the specified process, and respawns it after it exits;
# Gives up after recording the specified number of 'quick failures'
# in succession or after recording a specified total number of
# failures (over any length of time).
#
# This script supports Linux and VMkernel platforms and
# should be tested on both.
UPTIME_LIMIT_SECS=14400    #4 Hours

# Handler used to cleanly exit the watchdog
cleanup () {
   log daemon.info "[$$] Signal received: exiting the watchdog"
   if [ $START = 1 ] ; then
       rm -rf ${PIDFILE}
   fi
   exit 0
}

rebootVM () {
   log daemon.info "Reboot signal received: sending reboot"
   # If the system has been up for a day, allow reboot to occur.  This is to
   # prevent a reboot loop.  Following this though, manual intervention is
   # required.
   UPTIME_SECONDS=$(cat /proc/uptime | cut -d' ' -f1 | cut -d'.' -f1)
   if [ $UPTIME_SECONDS -gt $UPTIME_LIMIT_SECS ] ; then
      log daemon.err "Rebooting system due to repeated $CMD service restart"\
                     "failure."
      /sbin/shutdown -r +5
   else
      log daemon.err "$CMD service restart has failed repeatedly.  Unable to"\
                     "recover from service failures, please contact VMware"\
                     "support for further assistance."
   fi
}

# Trap all trappable signals (this excludes 9 17 19 23) and clean up.
trap cleanup 1 2 3 6 7 8 10 13 14 15 16 24 25 26 27 30 31

# Unset LC_ALL and LANG env variables so we avoid mapping useless files like
# /usr/lib/locale/locale-archive into memory. A daemon can force this script to
# keep these variables in the env by setting WATCHDOG_KEEP_LOCALE.
if [ -z "$WATCHDOG_KEEP_LOCALE" ]; then
    unset LC_ALL
    unset LANG
fi

usage () {
    echo "Usage: $0 [-n] -a|-s|-k|-r <tag> [(options)] <command>"
    echo "   Start the watchdog: $0 -s <tag> [-u <min_uptime>]"\
         "[-q <max_quick_failures>] [-a ] [-t <max_total_failures>]"\
         "[-i <respawn_delay>] <command>"
    echo "   Start the watchdog in background: $0 -d -s <tag>"\
         "[-u <min_uptime>] [-q <max_quick_failures>] [-a ]"\
         "[-t <max_total_failures>] [-i <respawn_delay>] <command>"
    echo "   Kill a running watchdog: $0 -k <tag>"
    echo "   Query whether a watchdog is running: $0 -r <tag>"
    echo "   Suppress logging: -n"
    echo "   Immortal mode: -i <respawn_delay>"
    echo "   In immortal mode instead of exiting after"\
         "max_quick_failures watchdog sleeps for respawn_delay seconds"\
         "and retries."
    echo "   Reboot system when quick failures exceed max quick failures: -a"
    exit 1
}

if [ $# -lt 2 ]
then
    usage
fi

log () {
    if [ "${QUIET}" -ne 0 ]
    then
        return
    fi

    if [ $# -lt 2 ]
    then
        logger -p daemon.err -t $LABEL "Bad log usage."
    else
        _loglevel=$1
        _logmsg=$2
        shift; shift;
        _logoptarg=$@
        logger -p $_loglevel -t $LABEL "$_logmsg" $_logoptarg
    fi
}

start () {
    MSG="[$$] Begin '$CMD', min-uptime = $MIN_UPTIME, max-quick-failures ="
    MSG="$MSG $MAX_QUICK_FAILURES, max-total-failures = $MAX_TOTAL_FAILURES,"
    MSG="$MSG bg_pid_file = '$BG_PID_FILE', reboot-flag = '$REBOOT_FLAG'"
    echo $MSG
    log daemon.info "$MSG"
    echo $$ > ${PIDFILE}

    while [ ! $QUICK_FAILURES -gt $MAX_QUICK_FAILURES -a ! $TOTAL_FAILURES -gt $MAX_TOTAL_FAILURES ]
      do
      # Erase the last BG_PID_FILE if it exists
      if [ "$BG_PROC" -eq 1 ] ; then
         rm -f "$BG_PID_FILE" > /dev/null 2>&1
      fi

      log daemon.info "Executing '$CMD'"
      if [ "$EXTRA_ENV" != "" ]; then
         log daemon.info "Additional environment '$EXTRA_ENV'"
      fi
      LAST=$(date +%s)
      # Lauches the command in a different process group.  Helps with signal handling.
      eval "setsid env $EXTRA_ENV $CMD &"

      # Wait for process to stop
      if [ "$BG_PROC" -eq 1 ] ; then
         local WAIT_TIME=0
         while [ ! -e "$BG_PID_FILE" -o $WAIT_TIME -gt $MAX_BG_PID_FILE_WAIT ]; do
            $SHORT_SLEEP
            WAIT_TIME=$(($WAIT_TIME + 1))
         done

         while kill -0 $(head -n1 "$BG_PID_FILE") 2>/dev/null ; do sleep 1; done
      else
         pid=$!
         wait $pid
         rc=$?
      fi

      if [ ! -f "$RESTART_FILE" -a ! -f "$ALWAYS_RESTART_FILE" ] ; then
          TOTAL_FAILURES=$(expr $TOTAL_FAILURES + 1)
          NOW=$(date +%s)
          UPTIME=$(expr $NOW - $LAST)
          if [ $UPTIME -lt $MIN_UPTIME ] ; then
              QUICK_FAILURES=$(expr $QUICK_FAILURES + 1)
              LOG_MESSAGE="'$CMD' exited after $UPTIME seconds (quick failure $QUICK_FAILURES) $rc"
              log daemon.err "$LOG_MESSAGE"
              if [ $QUICK_FAILURES -gt $MAX_QUICK_FAILURES ] ; then
                 # Only come here if the reboot turned on
                 if [ $REBOOT_FLAG -eq 1 ] ; then
                    rebootVM
                 elif [ $IMMORTAL -ne 0 ] ; then
                    log daemon.err "'$CMD' respawning too fast, sleeping"\
                                   "for $IMMORTAL seconds"
                    sleep ${IMMORTAL}
                    QUICK_FAILURES=0
                 fi
              fi
          else
              QUICK_FAILURES=0
              log daemon.err "'$CMD' exited after $UPTIME seconds $rc"
          fi
          if [ "$CLEANUP_CMD" != "" ] ; then
              log daemon.info "Executing cleanup command '$CLEANUP_CMD'"
              setsid $CLEANUP_CMD > /dev/null 2>&1
          fi
      else
          log daemon.info "Restart file detected, removing it."
          rm -rf "$RESTART_FILE" > /dev/null 2>&1
          if [ $? != 0 ] ; then
               log daemon.warning "unable to delete file $RESTART_FILE"
          fi
      fi
    done

    log daemon.err "End '$CMD', failure limit reached"
    rm -rf "${PIDFILE}"

    if [ "$EXIT_CLEANUP_CMD" != "" ] ; then
       log daemon.info "Executing cleanup command '$EXIT_CLEANUP_CMD' before exiting."
       $EXIT_CLEANUP_CMD > /dev/null 2>&1
    fi
    exit 0
}


daemonize () {
   # start the watchdog in background
   rm -rf ${PIDFILE}
   # This files redirection is fix for PR#756931
   # Use eval to preserve quoted string parameters in ORIG_OPTIONS
   eval "setsid $VMK_PARAMS $0 ${ORIG_OPTIONS} $CMD </dev/null >/dev/null 2>&1 &"
   local TIMEOUT=${MAX_DAEMONIZE_TIMEOUT}

   while [ ! -e ${PIDFILE} -a ${TIMEOUT} -gt 0 ] ; do
      $SHORT_SLEEP
      TIMEOUT=$(expr ${TIMEOUT} - 1)
   done

   if [ ! -e ${PIDFILE} ] ; then
      local MSG="Unable to verify ${TAG} started after ${MAX_DAEMONIZE_TIMEOUT} seconds"
      log daemon.err "${MSG}"
      echo "${MSG}"
   fi
}


# The awk selects the lines which lists watchdog being run with the
# specified TAG and is not the process itself and then extracts the
# PID.
LookupWatchdogPID () {
   local ps_args=""

   if [ "$(uname)" = "VMkernel" ] ; then
      ps_args="-cu";
   else
      # ww for wide output
      ps_args="axww";
   fi
   # Ignore the PID of this instance and the awk process should filter itself by *not* maching its parameters.
   # The regex expects a space before "-s", but there is a "+" there in the awk parameter that is outputed by ps.
   # Be very careful when modifying this line not to make a regex that matches itself!
   ps $ps_args 2> /dev/null | awk "!/^ *$$ / && /\/$(basename $0)\>.* +-s $TAG\>/ { print \$1 }"
}

VerifyWatchdogPID () {
  [ "${1}" = "$(LookupWatchdogPID)" ]
}

GetPid () {
    if [ ! -f ${PIDFILE} ]; then
        log daemon.info "PID file $PIDFILE does not exist" -s
        echo 0
        return
    fi
    PID=$(cat ${PIDFILE} 2> /dev/null)
    if [ -z "${PID}" ] ; then
        # This is a measure of last resort in case the pid file has been deleted somehow
        # Not foolproof but should work most of the time
        PID=$(LookupWatchdogPID)
        if [ -n "${PID}" ] ; then
            log daemon.info "Found running watchdog with pid $PID" -s
        else
           log daemon.info "Neither $PIDFILE nor running watchdog found" -s
        fi
    else
        # PR 253106
        if VerifyWatchdogPID ${PID}  ; then
            PID=$(LookupWatchdogPID)
            log daemon.info "Watchdog for $TAG is now $PID"
        fi
    fi
    # We are sure that the PID is not us
    if [ -n "${PID}" ] ; then
        echo $PID
    else
        echo 0
    fi
}

stop () {
    PID=$(GetPid)
    if [ "${PID}" -eq 0 ]; then
        MSG="Unable to terminate watchdog: No running watchdog process for $TAG"
        log daemon.info "$MSG" -s
        exit 1
    else
       local TIMEOUT=${MAX_SHUTDOWN_TIMEOUT}
       MSG="Terminating watchdog process with PID $PID"
       log daemon.info "$MSG" -s
       kill -HUP $PID 2> /dev/null
       while [ $((TIMEOUT--)) -gt 0 ] && kill -0 $PID 2>/dev/null ; do
           $SHORT_SLEEP
       done
       return $((TIMEOUT == 0))
    fi
}

query () {
    PID=$(LookupWatchdogPID)
    echo "${PID}"
    if [ "${PID}" = "" ]; then
       return 1
    else
       return 0
    fi
}

# Give these variables default values.
# These can be overridden with command line arguments.
# 1,000,000 here is basically meant to be infinity.
MAX_QUICK_FAILURES=5
IMMORTAL=0
MAX_TOTAL_FAILURES=1000000
MIN_UPTIME=60
MAX_BG_PID_FILE_WAIT=10       # Wait 10 seconds for BG PID FILE to show up
MAX_DAEMONIZE_TIMEOUT=10
MAX_SHUTDOWN_TIMEOUT=5
REBOOT_FLAG=0

# These variables tell us which action we will be performing.
START=0
STOP=0
QUERY=0

# Whether the process we're going to start backgrounds itself
BG_PROC=0
BG_PID_FILE=""

# Whether the execution should be quiet.
QUIET=0

# Environment variables to prepend to the executed command.
# Most useful for LD_PRELOAD, so that it doesn't affect the watchdog itself.
EXTRA_ENV=""

# Original options
ORIG_OPTIONS=""

VMK_PARAMS=""
case "$1" in
  ++*)
    VMK_PARAMS="$1"
    shift
    ;;
esac

# Read the command line arguments and set variables accordingly.
# Does no error checking on the inputs.
while getopts "dnab:s:k:r:u:q:t:i:c:f:e:" option
do
    case "$option" in
        d ) DAEMONIZE=1;;
        n ) QUIET=1; ORIG_OPTIONS=${ORIG_OPTIONS}" -n";;
        b ) BG_PROC=1; BG_PID_FILE=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -b $OPTARG";;
        s ) START=1; TAG=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -s $OPTARG";;
        k ) STOP=1; TAG=$OPTARG;;
        r ) QUERY=1; TAG=$OPTARG;;
        a ) REBOOT_FLAG=1;;
        u ) MIN_UPTIME=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -u $OPTARG";;
        q ) MAX_QUICK_FAILURES=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -q $OPTARG";;
        t ) MAX_TOTAL_FAILURES=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -t $OPTARG";;
        i ) IMMORTAL=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -i $OPTARG";;
        c ) CLEANUP_CMD=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -c \"$OPTARG\"";;
        f ) EXIT_CLEANUP_CMD=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -f \"$OPTARG\"";;
        e ) EXTRA_ENV=$OPTARG; ORIG_OPTIONS=${ORIG_OPTIONS}" -e \"$OPTARG\"";;
        * ) usage;;
    esac
done

# Everything after the options is the command we are running.
shift $(expr $OPTIND - 1)
CMD=$@

# The current number of failures.
QUICK_FAILURES=0
TOTAL_FAILURES=0

# Use this file to keep state across invocations of the script (i.e. allow
# us to query or kill a watchdog we start).
LABEL="watchdog-$TAG"
PIDDIR="/var/run/vmware"
PIDFILE="$PIDDIR/$LABEL.PID"
RESTART_FILE="/var/run/vmware/restart-$TAG"
ALWAYS_RESTART_FILE="/etc/vmware/always-restart-$TAG"

# Define short term sleep function used when waiting for a event to happen that
# is likely to appear very soon, e.g. start of a program or kill -9 to take
# effect
USLEEP=$(type usleep)
if [ $? -eq 0 ]; then
  MAX_DAEMONIZE_TIMEOUT=$(($MAX_DAEMONIZE_TIMEOUT * 100))
  MAX_SHUTDOWN_TIMEOUT=$(($MAX_SHUTDOWN_TIMEOUT * 100))
  MAX_BG_PID_FILE_WAIT=$(($MAX_BG_PID_FILE_WAIT * 100))
  SHORT_SLEEP="usleep 10000"
else
  SHORT_SLEEP="sleep 1"
fi

# Make sure the pid directory exists
mkdir -p -m 755 "${PIDDIR}"

if [ "${DAEMONIZE}" = "1" -a $START = 1 ] ; then
    daemonize
elif [ $START = 1 ] ; then
    start
elif [ $STOP = 1 ] ; then
    stop
elif [ $QUERY = 1 ] ; then
    query
else
    usage
fi
