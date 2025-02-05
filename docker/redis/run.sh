# Не нужно это писать - #!/bin/bash

ACL_FILE_PATH=/usr/local/etc/redis/aclfile.acl

# Генерируем файл ACL на основе шаблона
cat <<EOL > ${ACL_FILE_PATH}
user default off
user $REDIS_USER on >$REDIS_PASSWORD ~* &* +@all
EOL

# Запускаем Redis
redis-server \
      /usr/local/etc/redis/redis.conf \
      --port "${REDIS_PORT:-6379}" \
      --aclfile ${ACL_FILE_PATH}
