#!/bin/sh

MINIO_URL="http://minio:${MINIO_PORT}"

# Функция для проверки, доступен ли MinIO
check_minio_ready() {
  mc alias set local "${MINIO_URL}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"
  curl -s "${MINIO_URL}/minio/health/cluster"

  return $?
}

# Ожидаем, пока MinIO станет доступен
until check_minio_ready; do
  echo "Waiting for MinIO to be available..."
  sleep 2
done


echo "Creating user"
# Создание пользователя
mc admin user add local "${MINIO_USER}" "${MINIO_PASSWORD}"

echo "Attaching policy"
# Настройка прав пользователя (в данном случае мы назначаем права полного доступа на созданный bucket)
mc admin policy attach local readwrite --user "${MINIO_USER}"

echo "Minio initialized"

exit 0
