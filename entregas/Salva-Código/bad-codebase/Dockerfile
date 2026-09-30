FROM php:8.4-cli-alpine
RUN apk add --no-cache git unzip libzip-dev $PHPIZE_DEPS && docker-php-ext-install pdo_mysql zip && apk del $PHPIZE_DEPS
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
WORKDIR /var/www/html
COPY . .
RUN composer install --no-interaction --prefer-dist && chmod -R 777 storage bootstrap/cache
EXPOSE 8000
CMD ["sh", "-c", "php artisan migrate --force && php artisan serve --host=0.0.0.0 --port=8000"]
