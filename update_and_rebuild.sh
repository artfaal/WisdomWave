#!/bin/bash

# Ensure that the IMAGE_TAG variable is set
if [[ -z "$IMAGE_TAG" ]]; then
    echo "ERROR: The IMAGE_TAG variable is not set."
    exit 1
fi

# Pull the latest image version
docker pull artfaal/wisdomwave:$IMAGE_TAG

export IMAGE_TAG
# Navigate to the directory containing docker-compose file
# Note: This assumes that the docker-compose file is in the same directory from which this script is run.
docker-compose down
docker-compose up -d
