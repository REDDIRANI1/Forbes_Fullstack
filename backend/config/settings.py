import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"Missing required environment variable {name}. Copy .env.example to .env and set it."
        )
    return value


SECRET_KEY = required_env("DJANGO_SECRET_KEY")
DEBUG = required_env("DJANGO_DEBUG").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in required_env("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]
DATABASE_URL = required_env("DATABASE_URL")
REDIS_URL = required_env("REDIS_URL")
INGEST_BEARER_TOKEN = required_env("INGEST_BEARER_TOKEN")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rates",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"

database_options = {part.split("=", 1)[0]: part.split("=", 1)[1] for part in DATABASE_URL.split("?", 1)[1].split("&")} if "?" in DATABASE_URL else {}
database_base_url = DATABASE_URL.split("?", 1)[0]
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": database_base_url.rsplit("/", 1)[1], "USER": database_base_url.split("//", 1)[1].split(":", 1)[0], "PASSWORD": database_base_url.split("//", 1)[1].split(":", 1)[1].split("@", 1)[0], "HOST": database_base_url.split("@", 1)[1].split(":", 1)[0], "PORT": database_base_url.rsplit(":", 1)[1].split("/", 1)[0], "OPTIONS": database_options}}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {"DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"] = "rest_framework.pagination.PageNumberPagination"
REST_FRAMEWORK["PAGE_SIZE"] = 50
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
