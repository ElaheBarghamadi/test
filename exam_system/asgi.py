"""
ASGI config for exam_system project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('EXAM_SYSTEM_SERVING', '1')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "exam_system.settings")

application = get_asgi_application()
