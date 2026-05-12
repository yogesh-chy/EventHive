#!/bin/bash

set -e

# Wait for redis
echo "Waiting for redis..."
until curl -s $REDIS_URL; do
  >&2 echo "Redis is unavailable - sleeping"
  sleep 1
done

echo "Redis is up - executing command"
exec "$@"
