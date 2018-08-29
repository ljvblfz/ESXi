
class RegexLocator:
    bootloader = '((mbr)|(none)|(partition))'

    anywords = r'(\w+)'

    #
    # A valid md5 checksum starts with $1$, is up to 34 characters long, and
    # contains alpha-numeric characters plus some symbols.
    #
    md5 = r'(\$1\$[a-zA-Z0-9\.\$/]{22,31})'

    # A valid sha512 checksum starts with $6$
    # (http://www.kernel.org/doc/man-pages/online/pages/man3/crypt.3.html).
    # The salt can be up to 16 characters, but the output must be 86 characters.
    sha512 = r'(\$6\$[a-zA-Z0-9\./]{,16}\$[a-zA-Z0-9\./]{86})'
    #
    # Root directory OR a repeating sequence of '/' followed by characters,
    # with an optional '/' at the end of the sequence.
    #
    directory = r'(/|(/[^/]+)+/?)'

    networkproto = '((static)|(dhcp))'

    serialnum = r'(\w{5}-\w{5}-\w{5}-\w{5}-\w{5})'

    preInterpreter = '((python)|(busybox))'

    postInterpreter = '((python)|(busybox))'

    firstBootInterpreter = '((python)|(busybox))'

    firewallproto = '((tcp)|(udp))'

    portdir = '((in)|(out))'

    # take first 128 characters
    portname = r'(\w\w{,127})'

    # we should limit this range
    port = r'(\d+)'

    # Combination of mount-point/vmfs-volume for the partition command.  Can be
    # 'None' for mountpoint if the partition is not to be mounted or 'swap'
    # if it is the swap partition.
    mountpoint = r'(([^/]+|(/|(/[^/]+)+/?)))'

    # vmfs volume labels
    vmfsvolume = r'([^/]+)'

    vmdkname = r'([^/]+)'

    vmdkpath = r'((?:[^/]+/)+)([^/]+\.vmdk)'
