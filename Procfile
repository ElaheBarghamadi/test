web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn exam_system.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
