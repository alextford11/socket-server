#!/usr/bin/env bash
set -e
eval `cat ./env.sh`
COMMIT=`git rev-parse HEAD`
RELEASE_DATE=`date`
the_command="docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build $@"
echo "Running '${the_command}'..."
eval ${the_command}