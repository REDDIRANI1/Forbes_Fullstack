from rest_framework import authentication, exceptions

from django.conf import settings


class BearerUser:
    is_authenticated = True


class BearerTokenAuthentication(authentication.BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.INGEST_BEARER_TOKEN}"
        if header != expected:
            raise exceptions.AuthenticationFailed("A valid bearer token is required.")
        return (BearerUser(), None)
