"""Recreate the isolated SQL fixture from portable posts and frozen descriptions."""
from pathlib import Path

from .app import bootstrap
from .common import ROOT, dataset, read, relative_path, save


def restore_sql(size, output):
    output = Path(output).resolve()
    bootstrap(size, output)
    from django.conf import settings
    from django.core.management import call_command
    from django.db import transaction
    from apps.accounts.models import User
    from apps.families.models import FamilyRoom, Membership
    from apps.posts.models import Post

    data = dataset(size)
    posts = data["memory"] | data["probes"]
    marker = output / "sql_fixture.json"
    if marker.exists():
        return check_sql(size, output)
    db_path = output / "test.sqlite3"
    if db_path.exists() and db_path.stat().st_size:
        raise ValueError("Existing unmarked SQLite database will not be changed; use a new output directory")
    for spec in posts.values():
        if spec.get("image_path") and not relative_path(spec["image_path"]).is_file():
            raise ValueError("Download and verify all images before SQL restoration")
    call_command("migrate", interactive=False, verbosity=0)
    with transaction.atomic():
        users = {}
        for member in data["family"]["members"]:
            user = User(username="memoryqa_" + member["key"], display_name=member["name"], gender=member["gender"])
            user.set_unusable_password()
            user.save()
            users[member["key"]] = user
        room = FamilyRoom.objects.create(pk=data["db"]["family_id"], name="MemoryQA reproduction",
            owner=users[data["family"]["owner_key"]], invite_code="MQ" + str(size), password_hash="disabled-synthetic-fixture")
        for member in data["family"]["members"]:
            Membership.objects.create(room=room, user=users[member["key"]], slot=member["slot"])
        for key, spec in posts.items():
            post = Post.objects.create(pk=data["db"]["post_ids"][key], room=room,
                author=users[spec["author_key"]], caption=spec["caption"], image=spec.get("image_path") or "",
                description=data["descriptions"].get(key, {}).get("description", ""))
            Post.objects.filter(pk=post.pk).update(created_at=spec["created_at"])
    save(marker, {"history_size": size, "family_id": room.pk, "posts": size + 20,
        "paid_calls": 0, "graph_writes": 0, "images_copied": 0})
    return check_sql(size, output)


def check_sql(size, output):
    bootstrap(size, output)
    from datetime import datetime, timezone
    from apps.accounts.models import User
    from apps.families.models import FamilyRoom, Membership
    from apps.families.services import relationship
    from apps.posts.models import Post
    data = dataset(size)
    room = FamilyRoom.objects.get(pk=data["db"]["family_id"])
    members = data["family"]["members"]
    users = {m["key"]: User.objects.get(username="memoryqa_" + m["key"]) for m in members}
    if User.objects.count() != 4 or FamilyRoom.objects.count() != 1 or Membership.objects.count() != 4 or Post.objects.count() != size + 20:
        raise ValueError("SQL fixture counts differ")
    for member in members:
        user = users[member["key"]]
        if user.display_name != member["name"] or user.gender != member["gender"] or Membership.objects.get(room=room,user=user).slot != member["slot"]:
            raise ValueError("Family membership differs")
    for key,spec in (data["memory"] | data["probes"]).items():
        post=Post.objects.get(pk=data["db"]["post_ids"][key],room=room)
        expected_description=data["descriptions"].get(key,{}).get("description","")
        if (post.caption != spec["caption"] or post.author_id != users[spec["author_key"]].pk
                or post.created_at != datetime.fromisoformat(spec["created_at"])
                or post.description != expected_description or post.image.name != (spec.get("image_path") or "")):
            raise ValueError(f"SQL fixture changed: {key}")
    # Compare the actual app's relationship/provider payload against all 30 selected cases.
    import json
    from unittest.mock import patch
    from integrations.ai import provider
    tasks=read(ROOT/f"panel/history_{size}/tasks.json")
    seen=set()
    for task in tasks:
        if task["case_id"] in seen:continue
        seen.add(task["case_id"])
        post=Post.objects.get(pk=data["db"]["post_ids"][task["current_post_key"]])
        viewer=users[task["viewer_key"]]
        rel=relationship(viewer,post.author,room)
        with patch.object(provider,"answer_with_memory",return_value="offline" ) as adapter, \
             patch.object(provider.timezone,"now",return_value=datetime.fromisoformat(task["as_of"]).astimezone(timezone.utc)):
            provider.ask(post,rel,task["payload"]["질문"],[],viewer.display_name)
        if json.loads(adapter.call_args.args[2]) != task["payload"]:
            raise ValueError(f"Actual app payload differs: {task['case_id']}")
    return {"history_size":size,"posts":size+20,"history_descriptions":size,"question_payloads_verified":len(seen),
            "paid_calls":0,"graph_calls":0}
