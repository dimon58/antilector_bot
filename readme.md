# Антилектор

Телеграм бот для помощи студентам в учёбе

### Возможности

- Улучшение звука и удаление шумов в лекциях
- Удаление участков с тишиной в лекциях (обычно 15-20%)
- Конспектирование лекций с помощью ИИ

## Зависимости

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [FFmpeg](https://ffmpeg.org/)
- [Rust](https://rustup.rs/)
- [TeX Live](https://tug.org/texlive/) или аналоги
- [PhantomJS](https://phantomjs.org/)

В случае использования gpu от Nvidia для обработки нужно установить [CUDA Toolkit 12](https://developer.nvidia.com/cuda-downloads) версии 12.4 или выше

## Запуск

Пока что предполагается, что бот запускается на одной машине, поэтому логи будут писаться в папку logs помимо stdout

1. Скачать общую библиотеку для тг ботов (возможно когда-нибудь загружу на pypi)

   ```shell
   git clone https://github.com/dimon58/djgram
   ```

2. Настроить переменное окружение

   ```shell
   cp example.env .env
   ```
   В файле `.env` нужно прописать все токены и настройки

### Для разработки

1. Устанавливаем хуки pre-commit
   ```shell
   pre-commit install
   ```
2. Устанавливаем зависимости python
   ```shell
   uv sync --frozen --dev
   ```
3. Активируем созданное переменное окружение
   Windows:
   ```shell
   .venv/Scripts/activate
   ```
   Linux:
   ```shell
   source .venv/bin/activate
   ```
4. Запускаем требуемые внешние сервисы
   ```shell
   docker compose up redis postgres clickhouse rabbitmq minio minio-init telegram-bot-api nginx
   ```
5. Применяем миграции и инициализируем базу данных
   ```shell
   alembic upgrade head
   python run_init.py
   ```
6. Запускаем бота
   ```shell
   python run_tg_bot.py
   ```
7. Запускаем воркеров для обработки видео
   ```shell
   celery -A run_celery worker -n "worker.video_download_queue" -Q video_download_queue --loglevel=INFO --pool=solo
   celery -A run_celery worker -n "worker.video_process_queue" -Q video_process_queue --loglevel=INFO --pool=solo
   celery -A run_celery worker -n "worker.video_upload_queue" -Q video_upload_queue --loglevel=INFO --pool=solo
   ```
   Если значения переменных окружения VIDEO_DOWNLOAD_QUEUE, VIDEO_PROCESS_QUEUE, VIDEO_UPLOAD_QUEUE отличаются,
   то нужно использовать соответствующие названия

### В продакшн

1. Собираем образ
   ```shell
   docker compose --profile production build
   ```
   Или
   ```shell
   docker build -f .\docker\bot\Dockerfile -t a1 --build-arg BOT_ENV=production --target production_build .
   ```
   Образ собирается около 30-40 минут и имеет размер ~28 Гб

2. Запускаем
   ```shell
   docker compose --profile production up -d
   ```
