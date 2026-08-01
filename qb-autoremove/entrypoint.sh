#!/bin/sh
set -eu

case "${QB_AUTOREMOVE_ENABLED:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    echo "qb-mdcng-autoremove enabled: watching qB category '${QB_CATEGORY:-dbonline}'"
    exec python -u /app/autoremove.py
    ;;
  *)
    echo "qb-mdcng-autoremove disabled. Set QB_AUTOREMOVE_ENABLED=true and recreate the container to enable it."
    exec tail -f /dev/null
    ;;
esac
