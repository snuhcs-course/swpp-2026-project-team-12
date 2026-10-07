import json
from functools import wraps

from django.http import JsonResponse

from apps.accounts.models import AccessToken


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


def api(*methods, anonymous=False):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                response = JsonResponse({"error": "지원하지 않는 요청이에요."}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            try:
                if not anonymous:
                    header = request.headers.get("Authorization", "")
                    if not header.startswith("Bearer "):
                        raise APIError("다시 로그인해 주세요.", 401)
                    token = AccessToken.from_raw(header[7:])
                    if token is None:
                        raise APIError("다시 로그인해 주세요.", 401)
                    request.user = token.user
                    request.access_token = token
                result = view(request, *args, **kwargs)
                response = result if hasattr(result, "status_code") else JsonResponse(result)
            except APIError as error:
                response = JsonResponse({"error": error.message}, status=error.status)
            if "Cache-Control" not in response:
                response["Cache-Control"] = "no-store"
            return response

        return wrapped

    return decorate


def body(request):
    if request.content_type != "application/json":
        raise APIError("JSON 요청을 보내 주세요.", 415)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeError) as error:
        raise APIError("입력한 내용을 다시 확인해 주세요.") from error
    if not isinstance(data, dict):
        raise APIError("입력한 내용을 다시 확인해 주세요.")
    return data
