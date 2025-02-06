#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

readonly cmd="$*"

# We need this line to make sure that this container is started
# after the one with postgres:
wait-for-it \
  --host="$POSTGRES_HOST" \
  --port="$POSTGRES_PORT" \
  --timeout=90 \
  --strict

# It is also possible to wait for other services as well: redis, elastic, mongo
echo "Postgres ${POSTGRES_HOST}:${POSTGRES_PORT} is up"

# And redis
wait-for-it \
  --host="$REDIS_HOST" \
  --port="$REDIS_PORT" \
  --timeout=90 \
  --strict

echo "Redis ${REDIS_HOST}:${REDIS_PORT} is up"

# And clickhouse
wait-for-it \
  --host="$CLICKHOUSE_HOST" \
  --port="$CLICKHOUSE_PORT" \
  --timeout=90 \
  --strict

echo "ClickHouse ${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT} is up"

# And RabbitMQ
wait-for-it \
  --host="$RABBITMQ_HOST" \
  --port="$RABBITMQ_PORT" \
  --timeout=90 \
  --strict

echo "RabbitMQ ${RABBITMQ_HOST}:${RABBITMQ_PORT} is up"

# And MinIO
wait-for-it \
  --host="$MINIO_HOST" \
  --port="$MINIO_PORT" \
  --timeout=90 \
  --strict

echo "MinIO ${MINIO_HOST}:${MINIO_PORT} is up"

# Evaluating passed command (do not touch):
# shellcheck disable=SC2086
exec $cmd
