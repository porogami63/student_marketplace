#!/bin/bash
set -o errexit

pip install -r requirements.txt

python manage.py copy_logos
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py setup_ubelt
python manage.py create_superuser
python manage.py setup_site
