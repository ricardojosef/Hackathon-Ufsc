# Ambiente de análise estática.
#
# Portado de `analyzer-env/Dockerfile` do repositório oficial da hackathon
# (soluevo/Hackathon-Ufsc @ 55609f6). Duas mudanças em relação ao original:
#   1. As deps Python vêm de requirements.txt (fonte única de versões).
#   2. pytest incluído — o original não tinha, e os testes do scoring model
#      são entrega obrigatória.
#
# Python 3.11 é intencional: semgrep/pylint nas versões pinadas não têm
# wheels para 3.14. Veja a seção "Ambiente" no README.
FROM python:3.11-slim

# --- ferramentas do sistema ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    php-cli \
    php-mbstring \
    php-xml \
    php-zip \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# --- composer (gerenciador de dependências PHP) ---
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# --- ferramentas PHP de análise estática (bônus) ---
RUN composer global require \
    phpstan/phpstan \
    phploc/phploc \
    phpmetrics/phpmetrics \
    && ln -s /root/.composer/vendor/bin/phpstan    /usr/local/bin/phpstan \
    && ln -s /root/.composer/vendor/bin/phploc     /usr/local/bin/phploc \
    && ln -s /root/.composer/vendor/bin/phpmetrics /usr/local/bin/phpmetrics

# --- ferramentas Python de análise estática + pipeline ---
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# O código do pipeline e os alvos de análise são montados via volume.
# Veja docker-compose.yml na raiz do repositório.
WORKDIR /workspace

CMD ["bash"]
