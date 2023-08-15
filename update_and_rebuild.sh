#!/bin/bash

# Pull the latest image based on the IMAGE_TAG environment variable
docker pull artfaal/wisdomwave:${IMAGE_TAG:-other-latest}

# Use docker-compose to update your running containers
docker-compose down
docker-compose up -d
