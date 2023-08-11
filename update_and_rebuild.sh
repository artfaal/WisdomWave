#!/bin/bash

# Пуллим последние изменения из репозитория
git pull

# Пересобираем Docker образ
docker-compose build

# Перезапускаем контейнеры
docker-compose down
docker-compose up -d
