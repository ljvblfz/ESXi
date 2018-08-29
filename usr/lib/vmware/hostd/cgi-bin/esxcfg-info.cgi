#!/usr/bin/python

# Copyright 2010-2017 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# CGI script that invokes esxcfg-info.
#
# Example usage:
#    http://host/cgi-bin/esxcfg-info.cgi
#    http://host/cgi-bin/esxcfg-info.cgi?xml
#    http://host/cgi-bin/esxcfg-info.cgi?format=xml&subree=all&filter=F1%0aF2
# is equivalent to invoking
#    esxcfg-info -a
#    esxcfg-info -a -F xml
#    esxcfg-info --all -F xml --filter F1 --filter F2
#

import os
import sys
import cgi
import subprocess

HELP_PAGE = """
<html>
<head><title>Invalid Arguments</title></head>
<body>

<pre>
Invalid arguments!

Usage:
   http://host/cgi-bin/esxcfg-info.cgi
   http://host/cgi-bin/esxcfg-info.cgi?xml

The output can be filtered with the following parameters:

   http://host/cgi-bin/esxcfg-info.cgi?format=FORMAT&subree=SUBTREE&filter=F1&filter=F2%0aF3%0aF4

where:
   FORMAT = xml|txt|perl
   SUBTREE = all|hardware|resource|storage|network|system|advopt|devicetree
   F1, F2, F3, F4 are xpath-like filters
   %0a is the new-line character separating multiple filters


Use HTTP POST request if a large number of filters need to be specified.


Example filters for format=xml:

  /host/hardware-info@*
  //cpuimpl@name
  //cpuimpl@cpu-speed
  //cpuimpl@bus-speed

  //system-info@system-uuid

  /host/system-info/loaded-modules/module@name
  /host/system-info/loaded-modules/module@version

  /host/storage-info/vmfs-filesystems/vm-filesystem@volume-uuid
  /host/storage-info/vmfs-filesystems/vm-filesystem@volume-name
  /host/storage-info/vmfs-filesystems/vm-filesystem@size
  /host/storage-info/vmfs-filesystems/vm-filesystem@usage

  /host/storage-info/all-luns/disk-lun/lun@name

  //resource-group/virtual-machines/resource-leaf

</pre>
<br/>
<br/>
Testing form:<br/><br/>

<form action="esxcfg-info.cgi" method=\"post\">

Format:
<select name="format">
   <option value="xml">xml</option>
   <option value="txt">txt</option>
   <option value="perl">perl</option>
</select>
<br/>

Subtree:
<select name="subtree">
   <option value="all">all</option>
   <option value="hardware">hardware</option>
   <option value="resource">resource</option>
   <option value="storage">storage</option>
   <option value="network">network</option>
   <option value="system">system</option>
   <option value="advopt">advopt</option>
   <option value="devicetree">devicetree</option>
</select>
<br/>
<br/>

Filters:<br/>
<textarea name="filter" rows="10" cols="60">
//hardware-info@*
//system-info/loaded-modules/module@name
//system-info/loaded-modules/module@version
</textarea>
<br>
<input type="submit" value="Submit"></input>
</form>

</body>
</html>
"""


#
# Send help HTML page.
#

def SendHelpPage():
   print("Content-type: text/html")
   print()
   print(HELP_PAGE)


#
# Send default data.
#

def SendDefault():
   print("Content-type: text/plain")
   print()
   # We need to flush or the output of the subprocess will be printed first.
   sys.stdout.flush()

   os.execve("/bin/esxcfg-info", ["/bin/esxcfg-info", "-a"], os.environ)
   #subprocess.call(["esxcfg-info", "-a"])


#
# Send default XML data.
#

def SendDefaultXml():
   print("Content-type: text/xml")
   print()
   sys.stdout.flush()

   os.execve("/bin/esxcfg-info", ["/bin/esxcfg-info", "-a", "-F", "xml"], os.environ)
   #subprocess.call(["esxcfg-info", "-a", "-F", "xml"])

#
# Send filtered data.
#

def SendFilteredData(keyFormat, keySubtree, filters):
   if (keyFormat == "xml"):
      print("Content-type: text/xml")
   else:
      print("Content-type: text/plain")
   print()
   sys.stdout.flush()

   subtreeArg = "--" + keySubtree
   cmdArgs = ["esxcfg-info", subtreeArg, "--filter", "-"]
   if keyFormat != "txt":
      cmdArgs += ["-F", keyFormat]

   # XXX: We can use os.execve instead of subprocess.Popen, but we need write
   # the filters to a temporary file first and pipe it with /bin/cat or make
   # /bin/esxcfg-info read filters from file.
   #
   #tmpName = "/tmp/.esxcfg-info.cgi.%d" % os.getpid()
   #tmpFile = open(tmpName, "w")
   #for val in filters:
   #   tmpFile.write(val + "\n")
   #tmpFile.close()
   #
   #shellCmd = "cat " + tmpName + " | " + " ".join(cmdArgs) + " ; rm " + tmpName
   #argv = ["/bin/sh", "-c", shellCmd]
   #os.execve("/bin/sh", argv, os.environ)

   # TODO: Do we need to log all the filters for auditing purposes?

   p = subprocess.Popen(args=cmdArgs, stdin=subprocess.PIPE)

   for val in filters:
      p.stdin.write((val + "\n").encode('ascii'))
   p.stdin.close()
   p.wait()


#
# Main entry point.
#

def main():
   # CGI parameters.
   form = cgi.FieldStorage()
   queryString = os.getenv("QUERY_STRING", "")

   if not queryString and len(form.keys()) == 0:
      # No arguments.
      SendDefault()
      return

   if queryString == "xml":
      SendDefaultXml()
      return

   keyFormat = form.getfirst("format", "")
   keySubtree = form.getfirst("subtree", "all")
   filters = form.getlist("filter")
   # Keep those in sync with the HELP_PAGE.
   validFormats = ["xml", "txt", "perl"]
   validSubtrees = ["all", "hardware", "resource", "storage", "network",
                    "system", "advopt", "devicetree"]

   if not keyFormat in validFormats or not keySubtree in validSubtrees:
      SendHelpPage()
      return

   SendFilteredData(keyFormat, keySubtree, filters)


if __name__ == '__main__':
   main()
