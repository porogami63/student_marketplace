#!/bin/bash
set -o errexit

pip install -r requirements.txt

echo "Running copy_logos..."
python manage.py copy_logos

echo "Running collectstatic..."
python manage.py collectstatic --no-input

echo "Running migrations..."
python manage.py migrate

echo "Running setup_ubelt..."
python manage.py setup_ubelt

echo "Running create_superuser..."
python manage.py create_superuser

echo "Running setup_site..."
python manage.py setup_site

echo "Build completed successfully!"
