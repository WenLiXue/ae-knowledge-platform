#!/bin/sh
set -eu

# Bind mounts retain the host's ownership. Repair only the application-owned
# directories before dropping privileges so fresh deployments and upgrades can
# always persist documents and logs.
mkdir -p /app/backend/storage /app/backend/exports /app/logs
chown -R app:app /app/backend/storage /app/backend/exports /app/logs

exec setpriv --reuid=app --regid=app --init-groups -- "$@"
