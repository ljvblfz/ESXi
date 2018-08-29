#!/bin/ash
#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Shutdown script to extract and save the random seed

dd if=/dev/urandom of=/etc/random-seed count=1 2>/dev/null
