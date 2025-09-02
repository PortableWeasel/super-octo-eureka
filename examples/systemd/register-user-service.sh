#!/bin/sh
# Register a user-level git-mirror service and timer
# Replace /home/git/repositories/mirrors with your base directory
python -m git_mirror.cli register-service --base-dir /home/git/repositories/mirrors
