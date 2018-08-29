#!/usr/bin/env python

# Copyright 2016 VMware, Inc.
# All rights reserved. -- VMware Confidential

# Replacement for the generate-certificates script on the host.  This one will
# check to see if the cert in the image has the correct host name and request
# a new one if it not.

import os
import sys
import time
import random
import shutil
import socket
import tarfile
import syslog
import json

# __ssl_hack__
import ssl
if sys.version_info >= (2,7,9):
   if hasattr(ssl, '_create_unverified_context') and\
      hasattr(ssl, '_create_default_https_context'):
      ssl._create_default_https_context = ssl._create_unverified_context

try:
   from urllib2 import urlopen
except ImportError:
   # __python3_hack__
   from urllib.request import urlopen

LOCAL_FQDNS = ( 'localhost',
               'localhost6',
               'localhost.localdomain',
               'localhost6.localdomain6' )

def main(rekeyUrl, expectedHostname, rekeyToken):
   HOSTNAME = socket.gethostname()
   EXPECTED_HOSTNAME = expectedHostname
   TOKEN = rekeyToken

   if HOSTNAME in LOCAL_FQDNS:
      syslog.syslog("default hostname set, embedded cert should work.")
      sys.exit()

   FQDN = None
   try:
      FQDN = socket.getfqdn()
   except Exception as e:
      syslog.syslog("Unable to obtain FQDN of the host: %s" % str(e))
      FQDN = None

   # introduce a random delay to prevent flooding the server with these
   # requests in case of a boot storm.
   sleepTime = None
   try:
      random.seed()
      sleepTime = random.randint(1,10)
   except:
      syslog.syslog("Failed to generate a random sleep time")

   if sleepTime:
      time.sleep(sleepTime)

   RESOLVED_FQDN = None
   for attempt in range(0,5):
      try:
         RESOLVED_FQDN = set([ x[3] for x in
                             socket.getaddrinfo(HOSTNAME, 0, 0, 0, 0,
                                              socket.AI_CANONNAME) if x[3] and
                                              x[3] not in LOCAL_FQDNS])
         break
      except socket.gaierror as e:
         syslog.syslog("DNS resolution failure for HOSTNAME(%s): %s" % (
                       HOSTNAME, str(e)))
         if e.errno == socket.EAI_NONAME or attempt >= 4:
            syslog.syslog("Continuing with the default certificates, "
                          "since the HOSTNAME(%s) has no DNS bindings or "
                          "the DNS server is not responding." % HOSTNAME)
            sys.exit()

         # Let's be nice to the DNS server as well and not flood it.
         sleepTime = 3

         try:
            sleepTime = random.randint(1, 5)
         except:
            pass

         time.sleep(sleepTime)
      except Exception as e:
         syslog.syslog("Unable to resolve hostname: %s" % str(e))


   syslog.syslog("hostname check -- expected: %s; actual: HOSTNAME(%s), "
                 "FQDN(%s), RESOLVED(%s)" %
                 (EXPECTED_HOSTNAME, HOSTNAME, FQDN, RESOLVED_FQDN))
   FQDNS = [HOSTNAME, FQDN]
   if RESOLVED_FQDN:
        FQDNS.extend(RESOLVED_FQDN)
   if EXPECTED_HOSTNAME in FQDNS:
      syslog.syslog("hostname check passed, embedded cert should work.")
      sys.exit()
   else:
      syslog.syslog("attempting to regenerate cert")
      if RESOLVED_FQDN:
         HOSTNAME = RESOLVED_FQDN.pop()
      elif FQDN:
         HOSTNAME = FQDN

      syslog.syslog("Rekeying certificate for hostname=" + HOSTNAME)

      url = rekeyUrl + "?hostname=" + HOSTNAME + "&token=" + TOKEN

      sleepTime = 0
      while sleepTime <= 120:
         try:
            src = urlopen(url, timeout=20)
            dst = open("/tmp/rekey.tgz", "wb")
            shutil.copyfileobj(src, dst)
            src.close()
            dst.close()
            break
         except Exception as e:
            syslog.syslog("rekey attempt failed -- %s" % e)
            sTime = 20
            try:
               sTime = random.randint(1,30)
            except:
               syslog.syslog("Failed to generate a random sleep-time")
               pass
            sleepTime += sTime
            if sleepTime >= 120:
               syslog.syslog("Continuing with the default certificates.")
               sys.exit()
            time.sleep(sTime)

      if not os.path.exists("/tmp/rekey.tgz"):
         syslog.syslog("unable to download new key")
         sys.exit()

      tar = tarfile.open("/tmp/rekey.tgz", mode="r:gz")
      for ti in tar.getmembers():
         if ti.name not in ("etc/vmware/ssl/rui.crt",
                            "etc/vmware/ssl/rui.key"):
            continue
         syslog.syslog("injecting new key/cert file -- %s" % ti.name)
         tar.extract(ti, "/")
      os.remove("/tmp/rekey.tgz")

if __name__ == "__main__":

   configFilePath = "/etc/vmware/autodeploy/generateCertificates.json"

   # Open and parse JSON config file
   try:
      with open(configFilePath, "r") as cfg:
         config = json.load(cfg)
   except Exception as e: # FileNotFoundError, json.JSONDecoderError
      syslog.syslog(syslog.LOG_ALERT,
                    "Unexpected error while decoding JSON file {}"\
                    .format(configFilePath))
      syslog.syslog(syslog.LOG_ALERT, e)
      sys.exit(1)

   # Check if all necessary options are defined
   for option in ["rekeyUrl", "expectedHostname", "rekeyToken"]:
      if not option in config:
         syslog.syslog(syslog.LOG_ALERT,
                       "Failed to find {} in {}."\
                       .format(option, configFilePath))
         sys.exit(1)

   main(config["rekeyUrl"],
        config["expectedHostname"],
        config["rekeyToken"])

