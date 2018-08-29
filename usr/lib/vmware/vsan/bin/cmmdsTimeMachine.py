"""Track updates to CMMDS over time"""
import pyCMMDS
from datetime import datetime, timedelta
import time
import signal
import logging
from logging.handlers import SysLogHandler
from logging import Formatter
import argparse
import pyvsilib
from collections import deque
from tokenBucket import TokenBucket
import sys
from vmware import vsi

class CmmdsTimeMachineDaemon(object):
   # logger for standard log messages
   LOG_TAG = 'cmmdsTimeMachine: '
   log = logging.getLogger('cmmdsTimeMachine')
   logHandler = SysLogHandler('/dev/log')
   logHandler.setFormatter(Formatter(LOG_TAG +
         '%(asctime)s.%(msecs)d %(message)s', '%Y-%m-%d %H:%M:%S'))
   log.addHandler(logHandler)
   log.setLevel(logging.INFO)

   # logger for CMMDS update messages
   DUMP_TAG = 'cmmdsTimeMachineDump: '
   dump = logging.getLogger('cmmdsTimeMachineDump')
   dumpHandler = SysLogHandler('/dev/log')
   dumpHandler.setFormatter(Formatter(DUMP_TAG + '%(message)s'))
   dump.addHandler(dumpHandler)
   dump.setLevel(logging.INFO)

   def __init__(self,
         uuid,
         minBatchSizeB = 8*(2**10),
         overflowWaitSec = 30,
         updatesToSnapshot = 1000,
         writeTimeSec = 120,
         delaySec = 1,
         mbPerDay = None,
         verbosity = 1):

      if verbosity == 0:
         self.log.setLevel(logging.ERROR)
      elif verbosity == 1:
         self.log.setLevel(logging.INFO)
      else:
         self.log.setLevel(logging.DEBUG)

      self.localTypes = [13, 17, 20, 21, 23, 26]
      self.globalTypes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 16, 24,
            25, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
      self.snapshotOnlyTypes = [15, 27]
      self.subscriptions = [] # each entry is (subscription, [subscription query, active])

      self.entryFormat = '%s,%s,%s,%s,%s,%s,%s%s' # uuid,type,revision,owner,flags,data delim
      self.timeFormat = '%Y-%m-%dT%H:%M:%S.%f'
      self.deleteString = b'deleted'

      # DOM_OBJECT payloads are sometimes too big for a single syslog message,
      # so we need a custom entry delimiter
      self.delimiter = '\q'

      self.writeQueue = []
      self.minBatchSizeB = minBatchSizeB
      self.bytesReceived = 0
      self.writeTimeSec = writeTimeSec

      self.updatesToSnapshot = updatesToSnapshot
      self.uuid = uuid
      self.numUpdates = 0

      # entry:[snapshotType, (query.type, query.owner, query.wildcards), itersSinceOverflow]
      self.overflowQueue = deque()
      self.overflowWaitSec = overflowWaitSec

      # entry:[pyCMMDS.FindEntry, (query, pyCMMDS.FIND_FLAGS_NONE, True), itersSinceOverflow]
      self.delayQueue = deque()
      self.delaySec = delaySec

      # get mbPerDay value from adv config if not given
      if not mbPerDay:
         vsiPath = '/config/CMMDS/intOpts/ctmMbPerDay'
         mbPerDay = vsi.get(vsiPath)['cur']
      # If we want 100MB to cover 5 days assuming 4x compression, we have
      # 970 bytes per second.  Let's allow large bursts up to 30MB,
      bps = (mbPerDay * 4 * 1024 * 1024) // (24 * 60 * 60)
      rawFileSize = mbPerDay * 5 * 1024 * 1024

      self.log.info('Token bucket bps %d', bps)
      self.tb = TokenBucket(timedelta(seconds=5), bps * 5, rawFileSize * 100 // 30)

      self.stopped = False

   def getLogTimestamp(self):
      # timezones?
      return datetime.utcnow().isoformat() + 'Z'

   def getDumpTimestamp(self):
      return datetime.utcnow().timestamp()

   # syslog messages get automatically split at 880 characters
   # and are truncated at 8170 characters
   # return message length (without tag/timestamp)
   def writeEntry(self, message):
      messageSize = 800 # roughly account for tag/timestamp
      for i in range(0, len(message), messageSize):
         self.dump.info(message[i : i + messageSize])
      return len(message)

   def dumpWriteQueue(self):
      chars = 0
      for message in self.writeQueue:
         chars += self.writeEntry(message)
      self.log.info('dumped %d messages, %d characters',
            len(self.writeQueue), chars)
      self.writeQueue = []
      self.bytesReceived = 0

   def addEntryToQueue(self, entry, isSnapshot):
      timestamp = self.getDumpTimestamp()
      if entry.dataStr == b'':
         convertedData = ''
      elif entry.dataStr == self.deleteString:
         convertedData = bytes.decode(self.deleteString)
      else:
         convertedData = pyCMMDS.BinToText(entry.dataStr, True,
               pyCMMDS.CmmdsTypeToExprType(entry.type))
      message = (self.entryFormat %
                  (timestamp, entry.uuid, entry.type,
                  entry.revision, entry.owner, entry.flags,
                  convertedData, self.delimiter))
      # Returns true if there were enough tokens, or if allowNegative is true.
      if self.tb.useTokens(len(message), isSnapshot):
         self.writeQueue.append(message)
         self.bytesReceived += entry.realLength
         self.log.debug('update applied: [uuid:%s, type:%s, owner:%s]'
               + ' len %d, tokens %d, isSnap %r',
               entry.uuid, entry.type, entry.owner,
               len(message), self.tb.numTokens, isSnapshot)
         return True
      else:
         self.log.debug('update throttled: [uuid:%s, type:%s, owner:%s]'
               + ' len %d, tokens %d, isSnap %r',
               entry.uuid, entry.type, entry.owner,
               len(message), self.tb.numTokens, isSnapshot)

         # XXX Find a different way to use the delayQueue?
         # See commend in run loop.
         # self.delayQueue.append([self.findLatestEntry,
         #      (pyCMMDS.EntryToQuery(entry),), 0])
         return False

   def addSnapshotMarkerToQueue(self):
      message = 'SNAPSHOT:%s\q' % self.getDumpTimestamp()
      self.writeQueue.append(message)

   # args[0] is the query used to make the subscription
   # args[1] is True if the subscription is enabled; False otherwise
   def callback(self, args, entry, status):
      if status == pyCMMDS.VMK_IS_ENABLED:   # subscription enabled
         args[1] = True
         self.log.debug('subscripiton enabled: [uuid:%s, type:%s, owner:%s]',
               args[0].uuid, args[0].type, args[0].owner)
      if status == pyCMMDS.VMK_IS_DISABLED:   # subscription disabled
         args[1] = False
         self.log.debug('subscripiton disabled: [uuid:%s, type:%s, owner:%s]',
               args[0].uuid, args[0].type, args[0].owner)
      if status == pyCMMDS.VMK_EOVERFLOW:   # overflow in subscription callback queue
         self.log.debug('subscripiton overflow: [uuid:%s, type:%s, owner:%s]',
               args[0].uuid, args[0].type, args[0].owner)
         # XXX Is this queue needed?  We could add them to the delayQueue
         # self.overflowQueue.append([self.snapshotType,
         #      (args[0].type, args[0].owner, args[0].wildcards), 0])
      if status == pyCMMDS.VMK_OK:      # new or updated entry
         self.log.debug('entry updated: [uuid:%s, type:%s, owner:%s]',
               entry.uuid, entry.type, entry.owner)
         # query again to get the payload
         query = pyCMMDS.CMMDSQuery()
         query.uuid = entry.uuid
         query.type = entry.type
         query.owner = entry.owner
         query.revision = entry.revision
         data = pyCMMDS.FindEntry(query, pyCMMDS.CMMDS_FIND_FLAG_NONE, True)
         if data:
            self.addEntryToQueue(data, False)
            # Count the update even if it was throttled.
            # We base our desire to snapshot on cluster activity
            # so we can distinguish between a period of lots of activity
            # but no tokens from a period of very few actual updates.
            self.numUpdates += 1
      if status == pyCMMDS.VMK_NOT_FOUND:   # entry deleted
         self.log.debug('entry deleted: [uuid:%s, type:%s, owner:%s]',
               entry.uuid, entry.type, entry.owner)
         entry.data = bytearray(self.deleteString)
         self.addEntryToQueue(entry, False)
         # Count the update even if it was throttled.
         self.numUpdates += 1

   # If this is ever called as part of a snapshot, need to plumb that
   # info to addEntryToQueue.
   def findLatestEntry(self, query):
      query.wildcards['latestRevision'] = 1
      entry = pyCMMDS.FindEntry(query, pyCMMDS.CMMDS_FIND_FLAG_NONE, True)
      if entry:
         self.addEntryToQueue(entry, False)
         # Count the update even if it was throttled.
         self.numUpdates += 1

   def snapshotType(self, type, owner=None,
         wildcards={'anyUUID':1, 'anyRevision':1, 'anyOwner':1}):
      query = pyCMMDS.CMMDSQuery()
      query.wildcards = wildcards
      if owner:
         query.owner = owner
      query.type = type
      next = True
      while next:
         try:
            entry = pyCMMDS.FindEntry(query, pyCMMDS.CMMDS_FIND_FLAG_NEXT, True)
         except Exception as e:
            self.log.error('Query failed: %s', e)
         if entry:
            next = True
            self.addEntryToQueue(entry, True)
         else:
            next = False

   def fullSnapshot(self):
      # If we have a nonnegative number of tokens at the beginning, we allow
      # all the snapshot writes to be queued, possibly taking the number of
      # tokens negative. But in order to rate limit snapshots themselves, do
      # not start a new snapshot if we are still negative from the previous
      # snapshot.
      if self.tb.numTokens >= 0:
         tokensBefore = self.tb.numTokens

         self.addSnapshotMarkerToQueue()
         for type in self.localTypes:
            self.snapshotType(type, self.uuid,
                  {'anyUUID':1, 'anyRevision':1})
         for type in self.globalTypes:
            self.snapshotType(type)
         for type in self.snapshotOnlyTypes:
            self.snapshotType(type)
         self.dumpWriteQueue()

         self.log.debug('Snapshot taken, tokens before %d, tokens after %d'
               + ' numUpdates %d',
               tokensBefore, self.tb.numTokens, self.numUpdates)
         self.numUpdates = 0
      else:
         self.log.debug('Snapshot delayed, tokens %d numUpdates %d',
               self.tb.numTokens, self.numUpdates)

   def unsubscribe(self):
      for sub, data in self.subscriptions:
         sub.Unsubscribe()
         # data[1] is True if the subscription is still active
         while data[1]:
            time.sleep(0.1)
      self.subscriptions = []

   def close(self, signum, frame):
      self.log.info('Caught signal %d, closing', signum)
      self.stopped = True

   def run(self):
      self.log.info('Starting up')

      # Intercept SIGTERM signals from init.d script
      signal.signal(signal.SIGTERM, self.close)

      # initial snapshot
      self.fullSnapshot()

      try:
         # subscribe to all entries
         for i in self.localTypes:
            query = pyCMMDS.CMMDSQuery()
            query.type = i
            query.owner = self.uuid
            query.wildcards = {'anyUUID':1, 'anyRevision':1}
            opaqueData = [query, False]
            self.subscriptions.append(
                  (pyCMMDS.Subscribe(query, self.callback, opaqueData),
                     opaqueData))

         for i in self.globalTypes:
            query = pyCMMDS.CMMDSQuery()
            query.type = i
            query.wildcards = {'anyOwner':1, 'anyUUID':1, 'anyRevision':1}
            opaqueData = [query, False]
            self.subscriptions.append(
                  (pyCMMDS.Subscribe(query, self.callback, opaqueData),
                     opaqueData))

         count = 0
         while not self.stopped:
            # Attempt to snapshot every updatesToSnapshot updates we become
            # aware of, whether or not we throttled those updates.
            #
            # We want snapshots to get priority over the regular updates, but
            # even if we get tons of updates, we don't want to snapshot faster
            # than the bandwidth limit.  Further complicating things is the
            # fact that we don't know how large a snapshot will be before we
            # take it.
            #
            # The solution is to have snapshots use tokens from the
            # tokenBucket, but allow allow the value to go negative.  We still
            # will initiate a snapshot if the value is negative, but as soon
            # as it becomes positive, we will allow a snapshot to happen
            # and take the valaue negative again.  This means if the desired
            # snapshot bandwidth is higher than the allocated bandwidth,
            # we will dedicate all our resources to snapshots, which will
            # happen at a rate of snap size / allowed bandwidth.  If our
            # rate slows down and we are able to build up a positive number
            # of tokens, those will be used to service updates as much as
            # possible.  The overall bandwidth usage will not get ahead of
            # the token bucket fill rate by more than the size of a single
            # snapshot.
            if (self.numUpdates > 0
                  and self.numUpdates >= self.updatesToSnapshot):
               self.fullSnapshot()

            # dump the write queue approx every writeTimeSec seconds
            if count % self.writeTimeSec == 0:
               if self.bytesReceived > 0:
                  self.dumpWriteQueue()

            # XXX Replaced by tokenBucket. Is this still useful?
            # wait approx overflowWaitSec seconds for each overflowed subscription
            # self.iterateOverflowQueue(self.overflowQueue, self.overflowWaitSec)

            # XXX The following function just introduces extra delay in the run
            # lop based on the number of delayd subscriptions.  This is not needed
            # with the tokenBucket implementation.  We could still use this queue
            # to rerun subscriptions that did not get to run when we have tokens
            # instead of just waiting for the next callback or snapshot to update
            # the entry.
            # self.iterateOverflowQueue(self.delayQueue, self.delaySec)

            # batch writes so we can do large writes to the filesystem.
            if self.bytesReceived >= self.minBatchSizeB:
               self.dumpWriteQueue()

            count += 1
            # might want to make sleep time smaller if we aren't catching events fast enough
            time.sleep(1)
      finally:
         self.unsubscribe()

   def iterateOverflowQueue(self, queue, thresholdSec):
      # Items in the queue should be of the form
      # [updateFunction, params(tuple), numIterationsSinceOverflow]

      # We need a separate loop to remove items from the queue
      # since python doesn't allow for mutation of deques during iteration
      while len(queue) > 0 and queue[0][2] >= thresholdSec:
         updateFunc, params, _ = queue.popleft()
         updateFunc(*params)

      for item in queue:
         item[2] += 1

def validUUID(s):
   validChars = '0123456789abcdef'
   validPartLengths = [8, 4, 4, 4, 12]
   valid = True
   parts = s.split('-')

   if len(parts) != len(validPartLengths):
      valid = False

   if [len(part) for part in parts] != validPartLengths:
      valid = False

   for part in parts:
      for char in list(part):
         if char not in validChars:
            valid = False

   if not valid:
      msg = 'Invalid UUID: %s' % s
      raise argparse.ArgumentTypeError(msg)

   return s

if __name__ == '__main__':
   vsiPath = '/config/CMMDS/intOpts/cmmdsTimeMachineEnabled'
   parser = argparse.ArgumentParser()

   parser.add_argument(
      '-u',
      '--uuid',
      required = True,
      type = validUUID,
      help = 'UUID of this node')
   parser.add_argument(
      '-b',
      '--batchsize',
      required = False,
      type = int,
      default = 8*(2**10),
      help = 'Minimum size of a write batch in bytes (default: 8KB)')
   parser.add_argument(
      '-s',
      '--snapshots',
      required = False,
      type = int,
      default = 1000,
      help = ('Number of updates to receive before taking a snapshot '
              '(default: 1000)'))
   parser.add_argument(
      '-o',
      '--overflowSec',
      required = False,
      type = int,
      default = 30,
      help = ('Number of seconds to wait after receiving an overflow '
              'notification to take a snapshot (default: 30)'))
   parser.add_argument(
      '-w',
      '--writetimeSec',
      required = False,
      type = int,
      default = 120,
      help = ('Number of seconds to wait before writing a batch, '
              'regardless of the batch\'s size (default: 120)'))
   parser.add_argument(
      '-d',
      '--delaySec',
      required = False,
      type = int,
      default = 1,
      help = ('Number of seconds to wait after receiving an update '
              'to fetch the update contents (default: 1)'))
   parser.add_argument(
      '-m',
      '--mbPerDay',
      required = False,
      type = int,
      default = 20,
      # We want to cover 5 days with 100mb (gzipped)
      help = ('Megabytes per day of logging rate assuming 4x '
              'compression ratio. (default: 20)'))
   parser.add_argument(
      '-v',
      '--verbosity',
      required = False,
      type = int,
      default = 1,
      # We want to cover 5 days with 100mb (gzipped)
      help = ('Verbosity. 0 is ERROR (quiet), 1 => INFO, 2 => DEBUG '
              '(default: 1, INFO)'))

   args = parser.parse_args()
   if pyvsilib.get(vsiPath)['cur']:
      timeMachineDaemon = CmmdsTimeMachineDaemon(args.uuid,
            minBatchSizeB = args.batchsize,
            updatesToSnapshot = args.snapshots,
            overflowWaitSec = args.overflowSec,
            writeTimeSec = args.writetimeSec,
            delaySec = args.delaySec,
            mbPerDay = args.mbPerDay,
            verbosity = args.verbosity)
      timeMachineDaemon.run()

