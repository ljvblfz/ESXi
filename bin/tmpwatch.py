#!/usr/bin/python
"""
Copyright 2011 - 2014 VMware, Inc.  All rights reserved.

This module removes stale temporary files
"""

import os, os.path, stat, time, syslog, re

def init_syslog():
   syslog.openlog("tmpwatch", 0, syslog.LOG_DAEMON)

# Return specialized `ls`-like output

def delta_t_ls(statbuf):
   return "ln=%d id=%d/%d sz=%d chg=%ds acc=%ds %s-%03o" % (
      statbuf.st_nlink,
      statbuf.st_uid,
      statbuf.st_gid,
      statbuf.st_size,
      script_cutoff - max(statbuf.st_ctime, statbuf.st_mtime),
      script_cutoff - statbuf.st_atime,
      'd' if stat.S_ISDIR(statbuf.st_mode) else 'f' if stat.S_ISREG(statbuf.st_mode) else '?',
      stat.S_IMODE(statbuf.st_mode))

# Remove a file or directory, logging details

def remove_and_log(path, statbuf):
   global frm, drm, erm
   try:
      if stat.S_ISREG(statbuf.st_mode):
         os.remove(path)
         frm += 1
      elif stat.S_ISDIR(statbuf.st_mode):
         # Blindly remove all dirs; only empty ones actually go away
         os.rmdir(path)
         drm += 1
      else:
         return
      syslog.syslog(syslog.LOG_INFO, "rm %s '%s'" % (delta_t_ls(statbuf), path.encode('string_escape')))
   except OSError as e:
      # Don't report rmdir errors, we're provoking them on purpose
      if stat.S_ISDIR(statbuf.st_mode):
         return
      syslog.syslog(syslog.LOG_WARNING, "rm %s %s" % (delta_t_ls(statbuf), e.encode('string_escape')))
      erm += 1

# A file or dir should be removed if it is stale & not on the exclusion list.
# We can't remove an empty directory unconditionally; it may have just been
# created by a currently running process that is about to create a file in it.
# Non-empty directories are protected since rmdir() will fail.

def should_remove(script_cutoff, days, exclusion_re, path, statbuf):
   if (re.match("(?s)(" + exclusion_re + ")$", path)) != None:
      return False
   if stat.S_ISREG(statbuf.st_mode):
      modify_cutoff = script_cutoff - (days * 86400)
      access_cutoff = script_cutoff - ( 1.5 * 86400)
      if statbuf.st_mtime > modify_cutoff:
         return False
      if statbuf.st_ctime > modify_cutoff:
         return False
      if statbuf.st_atime > access_cutoff:
         return False
   elif stat.S_ISDIR(statbuf.st_mode):
      dirmod_cutoff = script_cutoff - 3600
      if statbuf.st_mtime > dirmod_cutoff:
         return False
   else:
      return False
   return True

# Scan the specified directory looking for files unmodified for `days' and
# not accessed for at least one day; remove them unless on exclusion list.
# Directories will be removed if older than an hour, as of before we started
# removing their contents.

def tmpwatch(script_cutoff, days, rootdir, exclusion_re = ""):
   try:
      names = os.listdir(rootdir)
   except OSError:
      return
   for name in names:
      path = os.path.join(rootdir, name)
      try:
         statbuf = os.lstat(path)
      except OSError:
         continue
      stale = should_remove(script_cutoff, days, exclusion_re, path, statbuf)
      if stat.S_ISDIR(statbuf.st_mode):
         tmpwatch(script_cutoff, days, path, exclusion_re)
      if stale:
            remove_and_log(path, statbuf)

# Clean those directories which require cleaning under VMware ESXi.
# The 3- & 11-day times match the previous tmpwatch.sh implementation's
# `find -mtime +2 or +10`, in which +n means "more than".

def do_tmpwatch(script_cutoff):
    # Remove stale core files.
    tmpwatch(script_cutoff, 11, "/var/core")

    # Remove files from /var/tmp after 3 days.  Protect a few directories,
    # but not files in those directories.
    tmpwatch(script_cutoff,  3, "/var/tmp", "/var/tmp/uswap|/var/tmp/downloads|/var/tmp/cache.*")

    # Remove stale vm-support files.
    tmpwatch(script_cutoff,  3, "/usr/lib/vmware/hostd/docroot/downloads")

    # Remove files from /tmp after 11 days.  Protect a few directories,
    # including their contents.
    tmpwatch(script_cutoff, 11, "/tmp", "/tmp/scratch(|/.*)|" \
                                        "/tmp/stageliveimage(|/.*)|" \
                                        "/tmp/stagebootbank(|/.*)|" \
                                        "/tmp/vmware-root/hbr(|/.*)|" \
                                        "/tmp/nfsgssd_krb5cc(|/.*)")

# Main

script_cutoff = time.time()
init_syslog()

syslog.syslog(syslog.LOG_INFO, "scanning")

frm = drm = erm = 0
do_tmpwatch(script_cutoff)

syslog.syslog(syslog.LOG_INFO, "done: removed %s%s%s." % (
   ("%d %s and " % (drm, "directory" if drm == 1 else "directories")) if drm > 0 else "",
   "%d %s" % (frm, "file" if frm == 1 else "files"),
   (" with %d %s" % (erm, "error" if erm == 1 else "errors")) if erm > 0 else ""
))
