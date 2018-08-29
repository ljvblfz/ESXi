"""Implements a token bucket to be used for rate limiting"""
# Based on lib/vsan/tracing/token_bucket.c

from datetime import datetime, timedelta
import time
import logging
import sys
import threading


class TokenBucket(object):
   def __init__(self, tokenPeriod, tokensPerPeriod, maxTokens):
      self.tokenPeriod = tokenPeriod # Should be of type timedelta
      self.tokensPerPeriod = tokensPerPeriod
      self.maxTokens = maxTokens

      # Start off as if we had one period worth of "charge up" time.
      self.numTokens = tokensPerPeriod
      self.nextPeriodTimestamp = datetime.now() + tokenPeriod

   def useTokens(self, numTokensToUse, allowNegative):
      now = datetime.now()
      while now > self.nextPeriodTimestamp:
         self.numTokens += self.tokensPerPeriod
         self.nextPeriodTimestamp += self.tokenPeriod

      # Never accumulate more than the allowed max tokens.
      self.numTokens = min(self.numTokens, self.maxTokens)

      if allowNegative or self.numTokens >= numTokensToUse:
         self.numTokens -= numTokensToUse
         return True;

      return False;

   def timeToGetTokens(self, numTokens):

      # Process any elapsed periods so that now is less than nextPeriodTimestamp
      now = datetime.now()
      while now > self.nextPeriodTimestamp:
         self.numTokens += self.tokensPerPeriod
         self.nextPeriodTimestamp += self.tokenPeriod

      # Time for the token counter to reach the desired value.
      if numTokens <= self.numTokens:
         return timedelta(seconds=0)

      # Delta t = Delta x * dt / dx
      waitSinceLastPeriodStart = (numTokens - self.numTokens) * self.tokenPeriod / self.tokensPerPeriod
      elapsedSincePeriodStart = self.tokenPeriod - (self.nextPeriodTimestamp - now)
      assert(waitSinceLastPeriodStart > elapsedSincePeriodStart)

      return waitSinceLastPeriodStart - elapsedSincePeriodStart


# ---- Unit test code ----- #
# Starts a thread that uses 10 tokens every 5 seconds as a snapshot
# (allowNegative = TRUE) and one token as an update on every second
# in between.  Usage:
#  0  1  2  3  4  5  6  7  8  9 10
# 10  1  1  1  1 10  1  1  1  1 10
#
# With the token rate at 10 per 7 seconds, we should see a snapshot
# every 7 seconds.  With a token rate of 12 every 10 seconds, we should
# see every snapshot and two of the 4 updates.

def loop5(test):
   tokensBefore = test.tb.numTokens
   if test.i % 5 == 0:
      tokensAsked = 10
      isSnap = True
   else:
      tokensAsked = 1
      isSnap = False

   if tokensBefore < 0:
      couldUse = False
   else:
      couldUse = test.tb.useTokens(tokensAsked, isSnap)

   print("Had {} tokens, asked for {} tokens, could use={}".format(tokensBefore, tokensAsked, couldUse))

   if couldUse or not isSnap:
      # Dont' skip snaps if they aren't allowed.
      test.i += 1

   if not couldUse and isSnap:
      sleepTime = test.tb.timeToGetTokens(0)
      print("Sleeping {} seconds for tokens".format(sleepTime))

      t = threading.Timer(sleepTime.total_seconds(), loop5, [ test ])
   else:
      t = threading.Timer(1, loop5, [ test ])
   t.start()

   if test.i == 20:
      print( "Setting token rate to 12")

      test.tb = TokenBucket(timedelta(seconds=5), 12, 50)

   if test.i == 40:
      sys.exit()

class TokenBucketTest(object):
   def __init__(self):
      pass

   def start(self):
      self.i = 0

      # make 5 a time value, start with zero tokens.
      self.tb = TokenBucket(timedelta(seconds=7), 10, 50)
      self.tb.useTokens(10, False)

      t = threading.Timer(1, loop5, [ self ])
      t.start()

# test = TokenBucketTest()
# test.start()

