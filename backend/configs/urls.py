from django.http import JsonResponse
from django.urls import path

from apps.accounts import views as accounts

def test_reply(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("api/test_reply/", test_reply, name="test_reply"),
    path("api/accounts/register/", accounts.register, name="account-register"),
    path("api/accounts/login/", accounts.login, name="account-login"),
    path("api/accounts/logout/", accounts.logout, name="account-logout"),
    path("api/accounts/me/", accounts.me, name="account-me"),
]
