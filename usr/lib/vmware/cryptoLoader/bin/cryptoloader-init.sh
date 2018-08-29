#!/bin/sh

# This script runs the cryptoLoader program that loads the crypto module.

modParam=""
cryptoLoaderArgs=""
# Get the cryptoFIPS140/cryptoUseASM options value thru localcli.
# The value is present in the 4th column (Runtime value column).
cryptoFIPS140=$(/bin/localcli system settings kernel list \
                | /bin/awk '$1 == "cryptoFIPS140" {print $4}')
cryptoUseASM=$(/bin/localcli system settings kernel list \
                | /bin/awk '$1 == "cryptoUseASM" {print $4}')

# Check if the boot arg is set for assembler support
if [ "$cryptoUseASM" == "FALSE" ]; then
   cryptoLoaderArgs=$cryptoLoaderArgs" -a"
   modParam="cryptoUseASM=0"
else
   modParam="cryptoUseASM=1"
fi

# Check if the boot arg is set for FIPS-140.
if [ "$cryptoFIPS140" == "TRUE" ]; then
   # -m <path to crypto module>
   # -M <crypto module hmac>
   # -h <path to cryptoloader hmac file>
   cryptoModulePath="/usr/lib/vmware/vmkmod/crypto_fips"

   cryptoLoaderArgs=$cryptoLoaderArgs" -m "$cryptoModulePath
   cryptoLoaderArgs=$cryptoLoaderArgs" -M "$(cat /usr/lib/vmware/cryptoLoader/crypto.hmac)
   cryptoLoaderArgs=$cryptoLoaderArgs" -h /usr/lib/vmware/cryptoLoader/cryptoLoader.hmac"

   # Run cryptoLoader to load crypto module.
   exec /usr/lib/vmware/cryptoLoader/bin/cryptoLoader $cryptoLoaderArgs > /var/log/cryptoloader.log 2>&1
else
   exec /bin/vmkload_mod -m crypto /usr/lib/vmware/vmkmod/crypto $modParam
fi
