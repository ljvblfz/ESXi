#!/usr/bin/env python
#
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# Collect and format VMFS latency stats
#

__author__ = "VMware, Inc."

import os
import io
import datetime
import sys
import subprocess
import gzip
import time
import logging
from optparse import OptionParser
import pdb
import csv
import traceback

dataFileVersion = "1.0"


class vsiFailure(Exception):
   pass


def DumpLatencyStats(datastore=None):
   basename = "/tmp/vsi_traverse"
   suffix = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
   tmpFile = "_".join([basename, suffix])
   cmd = 'vsi_traverse -o %s -p /vmkModules/vmfs3/latencyStats' % (tmpFile)
   if datastore:
      cmd += ('/%s' % (datastore))
   status, output = subprocess.getstatusoutput(cmd)
   if status != 0:
      logging.error("Failed to get stats datastore: %s; error: %s" %
                    (datastore, output))
      os.remove(tmpFile)
      raise vsiFailure()
   return tmpFile


def GetDatastoreList(vsiStatsFile=None):
   if vsiStatsFile:
      cmd = 'vsish -c %s -e ls /vmkModules/vmfs3/latencyStats' % \
            (vsiStatsFile)
   else:
      cmd = 'vsish -e ls /vmkModules/vmfs3/latencyStats'

   status, output = subprocess.getstatusoutput(cmd)
   if status != 0:
      logging.error("Failed to get stats datastore list; error: %s" % (output))
      return None
   return output.replace('/', '').split()


def GetOpsList(vsiStatsFile, datastore):
   cmd = 'vsish -c %s -e ls /vmkModules/vmfs3/latencyStats/%s/ops' % \
         (vsiStatsFile, datastore)
   status, output = subprocess.getstatusoutput(cmd)
   if status != 0:
      logging.error("Failed to get stats ops for datastore: %s; error: %s" %
                    (datastore, output))
      return None
   return output.replace('/', '').split()


def GetStatsList(vsiStatsFile, datastore, op):
   cmd = 'vsish -c %s -e ls /vmkModules/vmfs3/latencyStats/%s/ops/%s/stats' % \
         (vsiStatsFile, datastore, op)
   status, output = subprocess.getstatusoutput(cmd)
   if status != 0:
      logging.error("Failed to get stats list for datastore: %s; error: %s" %
                    (datastore, output))
      return None
   return output.replace('/', '').split()


def GetStatsHisto(vsiStatsFile, datastore, op, stat):
   cmd = 'vsish -c %s -p -e get ' % (vsiStatsFile) + \
         '/vmkModules/vmfs3/latencyStats/%s/ops/%s/stats/%s/histo' % \
         (datastore, op, stat)
   status, output = subprocess.getstatusoutput(cmd)
   if status != 0:
      logging.error("Failed to get stats histo for datastore: %s; error: %s" %
                    (datastore, output))
      return None
   output = eval(output.replace('main():Python mode is deprecated and will be removed in future releases. You can use pyvsilib instead.\n',''))
   output['buckets'] = [(i['limit'], i['count'])
                        for i in output['buckets'] if i['count'] != 0]
   return {'datastore': datastore, 'op': op, 'stat': stat, 'histo': output}


def ClearStats(dsList):
   if len(dsList):
      datastores = dsList
   else:
      datastores = GetDatastoreList()

   if len(datastores) == 0:
      return False

   for d in datastores:
      cmd = 'vsish -e ls /vmkModules/vmfs3/latencyStats/%s' % (d)
      status, output = subprocess.getstatusoutput(cmd)
      if status:
         logging.error('Could not fond datastore %s to dump stats' % (d))
         raise vsiFailure
      vsiFile = None
      try:
         vsiFile = DumpLatencyStats(d)
      except vsiFailure:
         logging.error("Failed to clear stats histo for datastore: %s" % (d))
         return False
      finally:
         if vsiFile:
            os.remove(vsiFile)

   return True


def DumpStats(g, dsList):
   dt = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
   vsiFile = None
   try:
      vsiFile = DumpLatencyStats()

      if len(dsList):
         datastores = dsList
      else:
         datastores = GetDatastoreList(vsiFile)

      if datastores is None:
         raise vsiFailure()

      for d in datastores:
         ops = GetOpsList(vsiFile, d)
         if ops is None:
            raise vsiFailure()
         for o in ops:
            stats = GetStatsList(vsiFile, d, o)
            if stats is None:
               raise vsiFailure()
            for s in stats:
               histo = GetStatsHisto(vsiFile, d, o, s)
               if histo is None:
                  raise vsiFailure()
               if len(histo['histo']['buckets']) > 0:
                  g.writerow({'time': dt, 'datastore': d,
                              'op': o, 'stat': s,
                              'count': histo['histo']['count'],
                              'max': histo['histo']['max'],
                              'min': histo['histo']['min'],
                              'mean': histo['histo']['mean'],
                              'buckets': histo['histo']['buckets']})
   except vsiFailure:
      return False
   finally:
      if vsiFile:
         os.remove(vsiFile)

   return True


def ShowStats(statsFile, showFilter, printBuckets):
   filters = {}
   showFilter = showFilter.strip(' ;')
   try:
      if len(showFilter) > 0:
         filters = dict([(g[0], g[1]) for g in [i.split('=')
                        for i in showFilter.split(';')]])
   except:
      logging.error('Invalid syntax for filter: "%s"' % (showFilter))
      raise

   if 'datastore' in filters:
      filters['datastore'] = filters['datastore'].split(',')
   else:
      filters.update({'datastore': None})

   if 'op' in filters:
      filters['op'] = filters['op'].split(',')
   else:
      filters.update({'op': None})

   if 'stat' in filters:
      filters['stat'] = filters['stat'].split(',')
   else:
      filters.update({'stat': None})

   try:
      csvfile = gzip.open(statsFile, 'rb')
   except:
      logging.error("Input file [%s] not found" % statsFile)
      sys.exit(1)

   verLine = csvfile.readline().decode()
   if verLine[0] != '#':
      logging.error('Invalid format for stats file')
      sys.exit(1)

   verInfo = dict([(g[0], g[1]) for g in [i.split('=')
                  for i in verLine.strip('# \n').split(',')]])

   if verInfo['App'] != 'VmfsLatencyStats':
      logging.error('Not a VmfsLatencyStats file')
      sys.exit(1)

   if verInfo['Version'] != dataFileVersion:
      logging.error('Not a supported VmfsLatencyStats version')
      sys.exit(1)

   fieldnames = ['time', 'datastore', 'op', 'stat', 'min', 'max',
                 'mean', 'count', 'buckets']
   g = csv.DictReader(io.TextIOWrapper(csvfile, newline=""),
                      fieldnames=fieldnames)

   # skip field header line
   next(g, None)

   prevTime = ""
   for row in g:
      if row['time'] != prevTime:
         print("Time: %s" % row['time'])
         print("%70s :   %-10s %-10s %-10s %-10s" %
               ("datstore_op_stat", "count", "min", "max", "mean"))
      if (filters['datastore'] is None or row['datastore'] in
          filters['datastore']) and \
         (filters['op'] is None or row['op'] in filters['op']) and \
         (filters['stat'] is None or row['stat'] in filters['stat']):
         s = "%s,%s,%s" % (row['datastore'], row['op'], row['stat'])
         print("%70s :   %-10u %-10u %-10u %-10u" % (s,
                                                     int(row['count']),
                                                     int(row['min']),
                                                     int(row['max']),
                                                     int(row['mean'])))
         if printBuckets:
            for b in eval(row['buckets']):
               if b[0] == 0x7fffffffffffffff:
                  print("%70s :   (%10u   > %10u)" % (s, b[1], 10000000))
               else:
                  print("%70s :   (%10u  <= %10u)" % (s, b[1], b[0]))
            print("")
      prevTime = row['time']
   csvfile.close()


def GetOptions():
    """
    Supports the command-line arguments listed below
    """

    parser = OptionParser()
    parser.add_option("-E", "--enable",
                      action="append", dest="enable", default=[],
                      help="Enable Stats")
    parser.add_option("-D", "--disable",
                      action="append", dest="disable", default=[],
                      help="Disable Stats")
    parser.add_option("-s", "--show-stats",
                      action="store", dest="statsFile", default=None,
                      help="stats file to display stats from.")
    parser.add_option("-b", "--print-buckets",
                      action="store_true", dest="printBuckets", default=False,
                      help="Print detailed stats buckets")
    parser.add_option("-f", "--show-filter",
                      action="store", dest="showFilter", default="",
                      help="Filter the stats during display")
    parser.add_option("-i", "--interval",
                      action="store", dest="interval", default="120",
                      help="Interval for statistics collection. Default=120sec")
    parser.add_option("-n", "--numIters",
                      action="store", dest="numIters", type=int, default=-1,
                      help="Number of iterations. Default=Infinite")
    parser.add_option("-d", "--datastore",
                      action="append", dest="datastores", default=[],
                      help="Datastore for which statistics to be collected.")
    parser.add_option("-o", "--outFile",
                      action="store", dest="outFile", default=None,
                      help="Name of the file to output the statistics.")

    (options, _) = parser.parse_args()

    return options, parser


def main(argv):
   options, parser = GetOptions()

   if options.statsFile:
      ShowStats(options.statsFile, options.showFilter, options.printBuckets)
      return

   status, vsphereVersion = subprocess.getstatusoutput('vmware -v')
   if status != 0:
      logging.error('Could not obtain vSphere version')
      return

   if options.outFile:
      dumpFile = options.outFile
   else:
      dumpFile = "_".join(['/var/run/log/vmfsLatencyData',
                           datetime.datetime.now().strftime("%y%m%d_%H%M%S")])

   dumpFile += '.csv.gz'

   csvfile = gzip.open(dumpFile, 'wb')

   versionInfo = "# App=VmfsLatencyStats,Version=%s,vSphere=%s\n" % \
                 (dataFileVersion, vsphereVersion)
   csvfile.write(versionInfo.encode())

   fieldnames = ['time', 'datastore', 'op', 'stat', 'min', 'max',
                 'mean', 'count', 'buckets']
   g = csv.DictWriter(io.TextIOWrapper(csvfile, newline="",
                                       write_through=True),
                      fieldnames=fieldnames)
   g.writeheader()

   res = ClearStats(options.datastores)
   if not res:
      return

   sleepInterval = int(options.interval)
   iter = 0
   while options.numIters == -1 or iter < options.numIters:
      time.sleep(sleepInterval)
      startSecs = int(datetime.datetime.now().strftime("%s"))
      res = DumpStats(g, options.datastores)
      if not res:
         break
      endSecs = int(datetime.datetime.now().strftime("%s"))
      sleepInterval = int(options.interval) - (endSecs - startSecs)
      if sleepInterval < 0:
         sleepInterval = 1
      iter += 1


# Start program
if __name__ == "__main__":
    try:
       main(sys.argv[1:])
    except:
       if os.getenv('PDB_ONERROR'):
          type, value, tb = sys.exc_info()
          traceback.print_exc()
          pdb.post_mortem(tb)
       else:
          raise
