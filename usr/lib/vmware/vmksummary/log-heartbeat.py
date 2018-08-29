#!/sbin/python  ++group=host/vim/vmvisor/logging

import vmware.vsi as vsi
import esxclipy
import syslog

def main():

    clipy = esxclipy.EsxcliPy()
    def clifetch(*cmd):
        status, output = clipy.Execute(cmd)
        if status != 0:
            raise RuntimeError(output)
        return eval(output)

    def counted(num, thing):
        if num == 1:
            return "%d %s" % (num, thing)
        else:
            return "%d %ss" % (num, thing)

    # Uptime
    uptime = clifetch('system', 'stats', 'uptime', 'get')
    uptimeS = int(uptime) / 1000000
    uptimeM, uptimeS = divmod(uptimeS, 60)
    uptimeH, uptimeM = divmod(uptimeM, 60)
    uptimeD, uptimeH = divmod(uptimeH, 24)
    uptime = "%dd%dh%dm%ds" % (uptimeD, uptimeH, uptimeM, uptimeS)

    # VMs
    numVMs = len(clifetch('vm', 'process', 'list'))

    # Memory usage leaderboard
    rsses = []
    maxes = []
    for cartel in map(int, vsi.list('/userworld/cartel')):
        # A cartel may exit between when we get the list and when we query
        # its attributes; ignore it if this happens.
        try:
            leader = vsi.get('/userworld/cartel/%d/leader' % cartel)
            name = vsi.get('/world/%d/name' % leader)[:16] # trim for size
            gid = vsi.get('/sched/memClients/%d/SchedGroupID' % cartel)
            rss = vsi.get('/sched/groups/%d/stats/memoryStats' % gid)['consumed']
            rmx = vsi.get('/sched/groups/%d/memAllocationInKB' % gid)['max']
            assert(rmx > 0)
            pct = (100 * rss) / rmx
            rsses.append((rss, '[%d %s %dkB]' % (cartel, name, rss)))
            maxes.append((pct, '[%d %s %d%%max]' % (cartel, name, pct)))
        except Exception:
            continue
    rsses.sort()
    maxes.sort()
        
    message = 'up %s, %s; [%s] [%s]' % \
        (uptime, counted(numVMs, "VM"), \
             ' '.join([pair[1] for pair in rsses[-3:]]), \
             ' '.join([pair[1] for pair in maxes[-3:]]))

    syslog.openlog("heartbeat")
    syslog.syslog(message)
    syslog.closelog()


if __name__ == '__main__':
    main()
