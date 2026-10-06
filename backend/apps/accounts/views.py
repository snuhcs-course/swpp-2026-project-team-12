from django.http import JsonResponse

from apps.api import api, body

from .services import account_data, login_account, register_account


@api("POST", anonymous=True)
def register(request):
    return JsonResponse(register_account(body(request)), status=201)


@api("POST", anonymous=True)
def login(request):
    return login_account(request, body(request))


@api("POST")
def logout(request):
    request.access_token.delete()
    return {"ok": True}


@api("GET")
def me(request):
    return account_data(request.user)
