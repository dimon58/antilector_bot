FROM jrottenberg/ffmpeg:7.1-nvidia2204 AS build-deps

ENV DEBIAN_FRONTEND=noninteractive

ARG PYTHON_VERSION=3.12
ARG RUST_VERSION=1.81.0
ARG PHANTOMJS_VERSION="phantomjs-2.1.1"

# ------------- Установка зависимостей для сборки ------------- #

# Install python and build-essential
# build-essential нужен для сборки deepfilternet и работы PhantomJS
# https://zomro.com/rus/blog/faq/475-how-to-install-python-312-on-ubuntu-2204
RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      wget build-essential python${PYTHON_VERSION}-full python${PYTHON_VERSION}-dev \
    && ln -sf python${PYTHON_VERSION} /usr/bin/python \
    && wget https://bootstrap.pypa.io/get-pip.py \
    && python${PYTHON_VERSION} get-pip.py --break-system-packages \
    && rm get-pip.py \
    && apt-get purge --auto-remove -y wget \
    && apt-get clean \
    && rm -rf /var/[log,tmp]/* /tmp/* /var/lib/apt/lists/*

# rust нужен для компиляции DeepFilterNet
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- --default-toolchain ${RUST_VERSION} -y \
    && apt-get purge --auto-remove -y curl \
    && apt-get clean \
    && rm -rf /var/[log,tmp]/* /tmp/* /var/lib/apt/lists/*

# https://github.com/cross-rs/cross/issues/260#issuecomment-520193756
ENV CARGO_HOME=/root/.cargo/bin PATH=/root/.cargo/bin:$PATH


# ------------- Установка зависимостей для запуска ------------- #

# Install PhantomJS
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        bzip2 \
        libfontconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && mkdir /tmp/phantomjs \
    && curl -L https://bitbucket.org/ariya/phantomjs/downloads/${PHANTOMJS_VERSION}-linux-x86_64.tar.bz2 \
            | tar -xj --strip-components=1 -C /tmp/phantomjs \
    && cd /tmp/phantomjs \
    && mv bin/phantomjs /usr/local/bin \
    && cd \
    && apt-get purge --auto-remove -y \
        curl \
    && apt-get clean \
    && rm -rf /tmp/* /var/lib/apt/lists/*

# https://stackoverflow.com/questions/73004195/phantomjs-wont-install-autoconfiguration-error
# Можно еще закомметрировать строчку "providers = provider_sect" в /etc/ssl/openssl.cnf
# Так как переменная OPENSSL_CONF не опредлена, то установим её в надеже на отсутсвие сайдэффектов
ENV OPENSSL_CONF=/dev/null


# ------------- Установка зависимостей для python ------------- #

FROM build-deps AS python-deps

# Устанавливаем самые тяжелые зависимости отдельно для удобства разработки
RUN pip install --break-system-packages --no-cache-dir \
    torch==2.4.1+cu124 torchaudio==2.4.1+cu124 --index-url https://download.pytorch.org/whl/cu124

# Python requirements
WORKDIR /app
RUN pip install --break-system-packages --no-cache-dir uv
COPY ./djgram/requirements.txt djgram/requirements.txt
COPY ./libs/nisqa/requirements.txt libs/nisqa/requirements.txt
COPY ./libs/unsilence/requirements.txt libs/unsilence/requirements.txt
COPY ./requirements.txt requirements.txt
RUN uv pip install --system --no-cache-dir -r requirements.txt


FROM python-deps AS service

WORKDIR /app
ADD . .
