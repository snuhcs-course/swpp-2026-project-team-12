"""File-SQLite regression driver, invoked only by test_daily_questions."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "configs.settings")

import django
from django.conf import settings

settings.DATABASES["default"]["OPTIONS"] = {"timeout": 0.1}
django.setup()

from django.core.management import call_command
from django.db import connections
from django.test import Client

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom
from apps.posts.daily_questions import definition
from apps.posts.models import DailyQuestion, Post
from developer.test_codes.family_fixtures import add_member, auth_headers


def main():
    call_command("migrate", verbosity=0)
    owner = User.objects.create_user(username="concurrent-owner", display_name="가족")
    room = FamilyRoom.objects.create(owner=owner, name="동시 요청", invite_code="RACE01", password_hash="unused")
    add_member(room, owner)
    auth = auth_headers(AccessToken.issue(owner), room)
    barrier, worker = Barrier(2), local()

    def synchronized_definition(day):
        if not getattr(worker, "ready", False):
            worker.ready = True
            # Both transactions have read "no question" before trying to write.
            barrier.wait(timeout=10)
        return definition(day)

    def request(path):
        try:
            response = Client().get(path, **auth)
            assert response.status_code == 200, response.content
            data = response.json()
            return data["daily_question"]["id"] if path == "/api/posts/" else data["id"]
        finally:
            connections.close_all()

    with patch("apps.posts.daily_questions.definition", side_effect=synchronized_definition):
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(request, ["/api/posts/", "/api/daily-questions/today/"]))
    assert ids[0] == ids[1], ids
    assert DailyQuestion.objects.count() == 1
    assert Post.objects.filter(kind="question").count() == 1
    connections.close_all()


if __name__ == "__main__":
    main()
