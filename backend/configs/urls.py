from django.http import JsonResponse
from django.urls import path

from apps.accounts import views as accounts
from apps.families import views as families
from apps.posts import views as posts
from apps.replies import views as replies
from integrations.speech import views as speech

def test_reply(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("api/test_reply/", test_reply, name="test_reply"),
    path("api/accounts/register/", accounts.register, name="account-register"),
    path("api/accounts/login/", accounts.login, name="account-login"),
    path("api/accounts/logout/", accounts.logout, name="account-logout"),
    path("api/accounts/me/", accounts.me, name="account-me"),
    path("api/families/create/", families.create, name="family-create"),
    path("api/families/lookup/", families.lookup, name="family-lookup"),
    path("api/families/join/", families.join, name="family-join"),
    path("api/families/current/", families.current, name="family-current"),
    path("api/posts/", posts.feed, name="post-feed"),
    path("api/posts/<int:pk>/", posts.detail, name="post-detail"),
    path("api/posts/<int:pk>/image/", posts.photo, name="post-image"),
    path("api/posts/<int:pk>/message/", posts.message, name="post-message"),
    path("api/posts/<int:pk>/comments/", replies.text_comment, name="post-comment"),
    path("api/speech/", speech.speak, name="speech"),
]
