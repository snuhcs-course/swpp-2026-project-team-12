from django.http import JsonResponse
from django.urls import path

def test_reply(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("api/test_reply/", test_reply, name="test_reply"),
]
