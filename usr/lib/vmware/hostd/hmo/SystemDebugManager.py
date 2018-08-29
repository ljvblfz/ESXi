#!/usr/bin/env python

"""
Copyright 2008-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
This module is an implementation for managed object vim.host.SystemDebugManager
"""
__author__ = "VMware, Inc"

from pyVmomi import vim
from vmware import vsi

import common
import subprocess
import logging

## The vim.host.SystemDebugManager implementation class
#
class SystemDebugManager(vim.host.SystemDebugManager):
   """
   vim.host.SystemDebugManager implementation
   """
   # Process name, vmodl process key
   _processNameList = {"hostd" : "hostd"}
   _hostdName = 'hostd'

   def __init__(self, moId):
      """
      vim.host.SystemDebugManager constructor
      """
      vim.host.SystemDebugManager.__init__(self, moId)


   class ProcessInfoHelper:
      """
      Helper class to keep track of process resource consumption.
      """

      def __init__(self, processKey):
         self._processKey = processKey
         self._uptime = 0
         self._cpuTime = 0
         self._totalTime = 0
         self._vSize = 0
         self._pid = []


      def AddProcessValues(self, pid, uptime, cpuTime, vSize):
         """
         Add information related to a process to a process group.
         """
         if (self._uptime < uptime) :
            self._uptime = uptime
         self._cpuTime += cpuTime
         self._totalTime += uptime
         self._vSize += vSize
         self._pid.append(pid)


      def GetProcessInfo(self):
         """
         Return the corresponding processInfo object.
         """
         if (len(self._pid) == 0) :
            return None

         cpuPercent = 0
         if (self._totalTime) :
            cpuPercent = float(self._cpuTime) * 100  * 100 / float(self._totalTime)

         processInfo = vim.host.SystemDebugManager.ProcessInfo(
            processKey = self._processKey,
            uptime = int(self._uptime),
            virtualMemSize = int(self._vSize),
            pid = self._pid,
            cpuPercentage = int(cpuPercent),
            cpuTime = int(self._cpuTime))

         return processInfo


   def QueryProcessInfo(self):
      """
      Query the process information for a processgroup
      """
      processInfos = []
      for processName, key in self._processNameList.items():
         processInfos.append(self._ExtractProcessInfoUW(processName, key))
      return processInfos


   def _GetHostdProcessId(self):
      """
      Return the hostd process id from PID file as a workaround for cases
      where process name got changed by foundry module. (PR456427)
      """
      pid = None

      try:
         with open('/var/run/vmware/vmware-hostd.PID', 'r') as fd:
            pid = fd.read().strip()
         logging.info('retrieved hostd pid as: %s' % pid)
      except Exception as e:
         logging.warning(str(e))

      return pid


   def _ExtractProcessInfoUW(self, processName, processKey):
      """
      Return the process info of a particular userworld process.
      """
      processInfoHelper = self.ProcessInfoHelper(processKey)

      pids = []
      processes = subprocess.Popen(["ps", "-Cu"],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
      for line in processes.stdout.readlines():
         line = line.decode('utf-8')
         cartels = line.split()

         if len(cartels) > 2 and cartels[1].isdigit() \
                             and processName in cartels[2]:
            pids.append(cartels[1].strip())

      #add pid in PID file in not included yet.
      if processName == self._hostdName:
         hostdPid = self._GetHostdProcessId()
         if hostdPid is not None and hostdPid not in pids:
            pids.append(hostdPid)

      for pid in pids:
         try:
            totalCommonFile = "/sched/memClients/%s/memStats/totalCommon" % pid
            totalCommonOutput = vsi.get(totalCommonFile)
            vsize = int(totalCommonOutput['memSize'])

            stateTimesFile = "/sched/Vcpus/%s/stats/stateTimes" % pid
            stateTimesOutput = vsi.get(stateTimesFile)
            cartelUpTime = int(stateTimesOutput['upTime'])
            cartelUsedTime = int(stateTimesOutput['usedTime'])
         except:
            # The process probably went away.
            logging.warning('no sched node found for pid %s' % pid)

         processInfoHelper.AddProcessValues(int(pid),
                                            cartelUpTime // 1000,
                                            cartelUsedTime // 1000,
                                            vsize)
      return processInfoHelper.GetProcessInfo()


# Create and register managed objects
def RegisterManagedObjects(vorb):
   vorb.RegisterObject(SystemDebugManager("ha-system-debug-manager"))


if __name__ == '__main__':
   vorb=common.InitVorb()
   RegisterManagedObjects(vorb)
   vorb.RunServer()
