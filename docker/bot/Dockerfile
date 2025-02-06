# Based on https://github.com/wemake-services/wemake-django-template/blob/master/%7B%7Bcookiecutter.project_name%7D%7D/docker/django/Dockerfile
# syntax = docker/dockerfile:1
# This Dockerfile uses multi-stage build to customize DEV and PROD images:
# https://docs.docker.com/develop/develop-images/multistage-build/

FROM jrottenberg/ffmpeg:6.1-nvidia2204 AS development_build

LABEL maintainer="Dmitry Sharonov"
LABEL name="antilector-telegram-bot"
LABEL version="0.1.0"

ARG RUST_VERSION=1.84.1
ARG PHANTOMJS_VERSION="phantomjs-2.1.1"

# Needed for fixing permissions of files created by Docker:
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
  # python:
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PYTHONDONTWRITEBYTECODE=1 \
  # tini:
  TINI_VERSION=v0.19.0 \
  # uv:
  UV_VERSION=0.5.29 \
  UV_CACHE_DIR='/root/.cache/uv' \
  UV_PROJECT_ENVIRONMENT='/venv' \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  # locale:
  LANG=ru_RU.UTF-8 \
  LANGUAGE=ru_RU:ru \
  LC_LANG=ru_RU.UTF-8 \
  LC_ALL=ru_RU.UTF-8

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# ca-certificates, bzip2, libfontconfig for PhantomJS
# git for DeepFilterNet
# graphviz for draw dialog diagrams
# locales for display for display russian month names in datetime
# PhantomJS for yt-dlp
# rust for compile DeepFilterNet
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
  # Fix fontconfig installation
  # https://stackoverflow.com/questions/53343241/dependency-problems-leaving-unconfigured
  # https://github.com/jrottenberg/ffmpeg/issues/316
  && (apt-get -y install --no-install-recommends fontconfig || true) \
  && dpkg --configure -a \
  && apt-get -y -f install --no-install-recommends \
  # Install required packages
  && apt-get -y install --no-install-recommends \
    bash \
    brotli \
    build-essential \
    curl \
    gettext \
    git \
    libpq-dev \
    wait-for-it \
    graphviz \
    locales \
    libcudnn8  \
    libcudnn9-cuda-12  \
    libcudnn8-dev \
  # Setup locale:
  && locale-gen ${LANG} && update-locale LANG=${LANG} \
  # Installing `tini` utility:
  # https://github.com/krallin/tini
  # Get architecture to download appropriate tini release:
  # See https://github.com/wemake-services/wemake-django-template/issues/1725
  && dpkgArch="$(dpkg --print-architecture | awk -F- '{ print $NF }')" \
  && curl -o /usr/local/bin/tini -sSLO "https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini-${dpkgArch}" \
  && chmod +x /usr/local/bin/tini && tini --version \
  # Install rust
  && curl --proto '=https' --tlsv1.2 -sSf "https://sh.rustup.rs" | sh -s -- --default-toolchain "$RUST_VERSION" -y \
  # Install PhantomJS
  # https://github.com/wernight/docker-phantomjs/blob/master/latest/Dockerfile
  && apt-get -y install --no-install-recommends ca-certificates bzip2 libfontconfig \
  && mkdir /tmp/phantomjs \
  && curl -L "https://bitbucket.org/ariya/phantomjs/downloads/${PHANTOMJS_VERSION}-linux-x86_64.tar.bz2" \
          | tar -xj --strip-components=1 -C /tmp/phantomjs \
  && mv /tmp/phantomjs/bin/phantomjs /usr/local/bin \
  # texlive-full for render latex
  # TODO: Можно уменьшить размер образа, если ставить пакеты texlive отдельно. См. apt search texlive
  #       этой команде будут установлены, как минимум, лишние пакеты с документацией
  && apt-get -y install --no-install-recommends texlive-full \
  # Installing `uv` package manager:
  # https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
  && curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh \
  && export PATH="/root/.local/bin/:$PATH" \
  && uv --version \
  # Cleaning cache:
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && apt-get clean -y && rm -rf /var/[log,tmp]/* /tmp/* /var/lib/apt/lists/*

# https://github.com/cross-rs/cross/issues/260#issuecomment-520193756
ENV CARGO_HOME=/root/.cargo/bin PATH=/root/.cargo/bin:$PATH

# Make uv avaliable
ENV PATH="/root/.local/bin/:$PATH"

# https://stackoverflow.com/questions/73004195/phantomjs-wont-install-autoconfiguration-error
# Можно еще закомметрировать строчку "providers = provider_sect" в /etc/ssl/openssl.cnf
# Так как переменная OPENSSL_CONF не опредлена, то установим её в надеже на отсутсвие сайдэффектов
ENV OPENSSL_CONF=/opt/openssl.cnf

WORKDIR /code

RUN groupadd -g "${GID}" -r web \
  && useradd -d '/code' -g web -l -r -u "${UID}" web \
  && chown web:web -R '/code'

# Install python
COPY --chown=web:web ./.python-version /code/
RUN uv python install

# Copy only requirements, to cache them in docker layer:

COPY --chown=web:web ./uv.lock ./pyproject.toml /code/
COPY --chown=web:web ./djgram/pyproject.toml /code/djgram/

# Project initialization:

# `BOT_ENV` arg is used to make prod / dev builds:
ARG BOT_ENV

# Install dependencies
# https://docs.astral.sh/uv/guides/integration/docker
# hadolint ignore=SC2046
RUN --mount=type=cache,target="$UV_CACHE_DIR" \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=djgram/pyproject.toml,target=djgram/pyproject.toml \
    echo "$BOT_ENV" \
    && uv --version \
    && uv sync --frozen --no-install-project --color never \
    $(if [ "$BOT_ENV" = 'production' ]; then echo '--no-dev'; fi)

# This is a special case. We need to run this script as an entry point:
COPY ./docker/bot/entrypoint.sh /docker-entrypoint.sh

# Setting up proper permissions:
RUN chmod +x '/docker-entrypoint.sh' \
  # Replacing line separator CRLF with LF for Windows users:
  && sed -i 's/\r$//g' '/docker-entrypoint.sh'

# Running as non-root user:
USER web

# Place executables in the environment at the front of the path
ENV PATH="$UV_PROJECT_ENVIRONMENT/bin:$PATH"

# We customize how our app is loaded with the custom entrypoint:
ENTRYPOINT ["tini", "--", "/docker-entrypoint.sh"]


# The following stage is only for production:
# https://wemake-django-template.readthedocs.io/en/latest/pages/template/production.html
FROM development_build AS production_build
COPY --chown=web:web . /code
