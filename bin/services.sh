#!/bin/sh

export PATH=/sbin:/bin
INIT_RP="host/vim/vmvisor/init"

log() {
   echo "$*"
   logger init "$*"
}

statusChange() {
   log $*
   esxcfg-init --set-boot-status-text "$*"
   esxcfg-init --set-boot-progress step
}

# Since hostd is not yet started by jumpstart,
# simply use localcli to update the firewall.
update_ruleset_status() {
   /sbin/localcli network firewall ruleset set -r $1 -e $2
}

update_firewall() {
   if [ $1 = "ntpd" ]; then
      update_ruleset_status "ntpClient" $2
   elif [ $1 = "SSH" ]; then
      update_ruleset_status "sshServer" $2
   elif [ $1 = "vpxa" ]; then
      update_ruleset_status "vpxHeartbeats" $2
   elif [ $1 = "sfcbd-watchdog" ]; then
      update_ruleset_status "CIMHttpServer" $2
      update_ruleset_status "CIMHttpsServer" $2
   fi
}

modify_firewall_ruleset() {
   svclsts=`/sbin/chkconfig -iom`

   IFS=$'\n'
   for svclst in $svclsts; do
      IFS=$'\t'
      for service in $svclst; do
         if [ -x "$service" ]; then
            svc=`basename $service`
            update_firewall $svc $1
         fi
      done
   done
}

cmdline=$(/bin/bootOption -roC)
get_mode() {
   local runmode=parallel
   if echo $cmdline | grep -q -e '\<services.sequential\>' ; then
      runmode=sequential
   fi
   echo "$runmode"
}

jumpstart_start() {
   ulimit -s 512
   modify_firewall_ruleset true
   if [ $(get_mode) == "sequential" ]; then
      daemonmode=wait
   else
      daemonmode=nowait
   fi
   /bin/jumpstart ++group=$INIT_RP --daemon=$daemonmode --method=start 2>&1 >> /var/log/jumpstart-stdout.log
}

jumpstart_stop() {
   ulimit -s 512
   /bin/jumpstart ++group=$INIT_RP --daemon --method=stop 2>&1 >> /var/log/jumpstart-stdout.log
   modify_firewall_ruleset false
}

action=$1

case "$1" in
   start)
      jumpstart_start
      ;;
   stop)
      jumpstart_stop
      ;;
   restart)
      jumpstart_stop
      jumpstart_start
      ;;
   *)
      echo "Usage: `basename "$0"` {start|stop|restart}"
      exit 1
esac
