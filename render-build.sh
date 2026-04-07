/#!/usr/bin/env bash
set -o errexit

python manage.py migrate
python manage.py sync_media_for_render
python manage.py collectstatic --noinput
python manage.py setup_socialapps
