#!/bin/bash
set -e
Xvfb :99 -screen 0 1280x800x24 &
exec "$@"
