#!/bin/sh
set -eu

python manage.py wait_for_services --timeout 90
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 60
