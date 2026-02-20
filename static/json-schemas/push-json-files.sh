#!/bin/bash
#
if [ "$#" -ne 1 ]; then
    echo "You must provide exactly one argument: 'test', 'uat' or 'prod'."
    exit 1
elif [ "$1" != "test" ] && [ "$1" != "uat" ] && [ "$1" != "prod" ]; then
    echo "This script only accepts 'test', 'uat' or 'prod' as an argument."
    exit 1
fi

ENV="$1"

echo "Pushing JSON files to the ${ENV} servers"
echo "======================================"
scp common-schema-*.json vms-schema-*.json "${ENV}"-nomad01.geant.org:/tmp
ssh "${ENV}-nomad01.geant.org" "sudo /usr/local/bin/move-json-tformator.sh"
