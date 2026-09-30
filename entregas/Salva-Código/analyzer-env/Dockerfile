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

# --- ferramentas PHP de análise estática ---
RUN composer global require \
    phpstan/phpstan \
    phploc/phploc \
    phpmetrics/phpmetrics \
    && ln -s /root/.composer/vendor/bin/phpstan    /usr/local/bin/phpstan \
    && ln -s /root/.composer/vendor/bin/phploc     /usr/local/bin/phploc \
    && ln -s /root/.composer/vendor/bin/phpmetrics /usr/local/bin/phpmetrics

# --- ferramentas Python de análise estática ---
# setuptools necessário para pkg_resources (dependência do semgrep)
RUN pip install --no-cache-dir \
    setuptools \
    bandit==1.7.9 \
    radon==6.0.1 \
    pylint==3.3.1 \
    semgrep==1.93.0 \
    pydantic==2.8.2 \
    google-generativeai==0.8.3

# --- diretório de trabalho dos alunos ---
WORKDIR /workspace

# O código dos repositórios será montado via volume.
# O aluno desenvolve o pipeline em /workspace/analyzer/.

CMD ["bash"]
