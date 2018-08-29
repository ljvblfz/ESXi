#!/bin/sh ++min=0,group=host/vim/vimuser/terminal/shell

ESXShell_MAGIC_FILE="/var/run/vmware/show-esx-shell-login"

# clear the screen, so that the banner/welcome show up
# at the top.
clear

. /etc/banner

if [ -f "$ESXShell_MAGIC_FILE" ]; then
    # the shell is enabled
    logger -t ESXShell "ESXi Shell available"

    # ignore SIGHUP from now on ... if shell is switched off while at
    # the login prompt, the init script will notice that getty/login
    # process is running and kill that.  Note that if we're already
    # logged in, we don't do anything, but it will be noticed when the
    # user logs out and we start all over again.
    trap "" SIGHUP
    getty 38400 tty1
else
    # the shell is disabled, display a blank screen
    logger -t ESXShell "ESXi Shell unavailable"

    # if we receive SIGHUP in this mode, that means the shell status
    # has been changed, so we exit and start again.
    trap "exit 0" SIGHUP
    stty -echo
    while [ 1 ]
    do
      read ignored
    done
fi

# clear the screen so as not to leave anything interesting if
# somebody looks at the console
clear

