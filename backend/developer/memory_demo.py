"""Isolated, synthetic family history for the Android memory-evidence demo.

setup: start a dedicated Neo4j container, migrate a separate SQLite DB and seed.
ingest: run the real Graphiti construction worker for this synthetic family only.
serve: run the normal Django application on localhost:8001.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
STATE = ROOT / ".local" / "memory-demo"
ROOM_ID = 961031
USERNAME = "01000001031"
PASSWORD = "MemoryDemo1031!"  # Public credentials for synthetic, local-only data.
CONTAINER = "talkdock-memory-demo"
QUESTIONS = [
    "지난 가족 여행은 어디로 갔고 뭘 먹었어?",
    "부산 여행에서 지민이가 고른 기념품은 뭐야?",
    "보리 밥은 누가 몇 시에 줘?",
    "엄마 생일에 지민이가 준비한 건 뭐야?",
    "아빠가 요즘 읽는 책 제목이 뭐였지?",
]

# All people, events, dates and posts below are fictional.
POSTS = [
    ("sujin", "2026-09-20T09:00:00+09:00", "2026년 9월 19일 가족 여행으로 부산에 다녀왔어요. 해운대에서 산책하고 저녁에는 돼지국밥을 먹었어요.", "td_art_together.png"),
    ("doyun", "2026-09-21T18:00:00+09:00", "부산 가족 여행에서 지민이가 바다 그림 엽서를 기념품으로 골랐어요. 집에 와서 할머니 선희께 편지를 써서 드렸어요.", "td_art_grandchild.png"),
    ("jimin", "2026-10-03T20:00:00+09:00", "10월 3일은 엄마 수진의 생일이었어요. 제가 딸기 케이크를 준비했고, 아빠 도윤이 꽃다발을 드렸어요.", "td_art_together.png"),
    ("doyun", "2026-10-10T08:00:00+09:00", "우리 집 강아지 이름은 보리예요. 보리 밥은 지민이가 매일 아침 8시와 저녁 6시에 챙겨주기로 했어요.", None),
    ("sunhee", "2026-10-18T18:00:00+09:00", "오늘 아들 도윤과 손녀 지민이가 함께 관악산에 다녀왔대요. 정상에서 가족 사진도 찍었다고 해요.", "td_art_together.png"),
    ("doyun", "2026-10-25T19:00:00+09:00", "요즘 제가 읽는 책은 어린 왕자예요. 자기 전에 하루에 열 쪽씩 읽고 있어요. 다 읽으면 딸 지민이에게 빌려주려고 해요.", None),
]


def configure():
    STATE.mkdir(parents=True, exist_ok=True)
    config_path = STATE / "config.json"
    if not config_path.exists():
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump({"neo4j_password": secrets.token_urlsafe(24)}, file)
    config = json.loads(config_path.read_text())
    os.environ.update({
        "DJANGO_SETTINGS_MODULE": "configs.settings", "DJANGO_DEBUG": "1",
        "DJANGO_DB_PATH": str(STATE / "db.sqlite3"),
        "DJANGO_MEDIA_ROOT": str(STATE / "media"),
        "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost,10.0.2.2,testserver",
        "PUBLIC_ORIGIN": "", "NEO4J_URI": "bolt://127.0.0.1:7688",
        "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": config["neo4j_password"],
        "GRAPHITI_SEARCH_WORKERS": "1",
    })
    sys.path.insert(0, str(BACKEND))
    import django
    django.setup()
    return config


def setup_neo4j(config):
    existing = subprocess.run(["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER],
                              capture_output=True, text=True)
    if existing.returncode:
        env = STATE / "neo4j.env"
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write("NEO4J_AUTH=neo4j/" + config["neo4j_password"] + "\n")
            file.write("NEO4J_server_memory_heap_initial__size=256m\n")
            file.write("NEO4J_server_memory_heap_max__size=512m\n")
            file.write("NEO4J_server_memory_pagecache_size=256m\n")
        subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "--env-file", str(env),
                        "-p", "127.0.0.1:7688:7687", "-p", "127.0.0.1:7475:7474",
                        "-v", "talkdock-memory-demo-data:/data", "neo4j:5.26-community"], check=True,
                       stdout=subprocess.DEVNULL)
    elif existing.stdout.strip() != "true":
        subprocess.run(["docker", "start", CONTAINER], check=True, stdout=subprocess.DEVNULL)
    from neo4j import GraphDatabase
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=("neo4j", config["neo4j_password"])) as driver:
        for _ in range(60):
            try:
                driver.verify_connectivity()
                print("Isolated demo Neo4j is ready.", flush=True)
                return
            except Exception:
                time.sleep(1)
    raise RuntimeError("Demo Neo4j did not become ready; check docker logs talkdock-memory-demo.")


def seed():
    from datetime import datetime
    from django.contrib.auth.hashers import make_password
    from django.core.management import call_command
    from django.db import transaction
    from apps.accounts.models import User
    from apps.families.models import FamilyRoom, FamilyPerson, Membership, ParentChild, Partnership
    from apps.posts.models import Post
    from PIL import Image
    call_command("migrate", verbosity=0)
    with transaction.atomic():
        members = {}
        people = {}
        for index, (key, name, gender, generation) in enumerate([
            ("jimin", "지민", "female", 0), ("doyun", "도윤", "male", 1),
            ("sujin", "수진", "female", 1), ("sunhee", "선희", "female", 2),
        ]):
            user, created = User.objects.get_or_create(username=f"010000010{31 + index}",
                defaults={"display_name": name, "gender": gender})
            if created:
                user.set_password(PASSWORD); user.save(update_fields=["password"])
            members[key] = user
        room, _ = FamilyRoom.objects.get_or_create(pk=ROOM_ID, defaults={
            "name": "추억 찾기 체험 가족", "owner": members["sujin"], "invite_code": "DEMO1031",
            "password_hash": make_password("FamilyDemo1031!")})
        for key, generation in [("jimin", 0), ("doyun", 1), ("sujin", 1), ("sunhee", 2)]:
            person, _ = FamilyPerson.objects.get_or_create(room=room, name=members[key].display_name,
                defaults={"gender": members[key].gender, "generation": generation})
            Membership.objects.get_or_create(room=room, user=members[key], defaults={"person": person})
            people[key] = person
        for parent, child in [("sunhee", "doyun"), ("doyun", "jimin"), ("sujin", "jimin")]:
            ParentChild.objects.get_or_create(parent=people[parent], child=people[child])
        first, second = sorted([people["doyun"].pk, people["sujin"].pk])
        Partnership.objects.get_or_create(first_id=first, second_id=second)
        photos = STATE / "media" / "demo"
        photos.mkdir(parents=True, exist_ok=True)
        artwork = ROOT / "client/app/src/main/assets/todak"
        for index, (author, at, caption, image) in enumerate(POSTS):
            images = []
            names = [image] if image else []
            if index == 0:
                names.append("td_art_grandchild.png")
            for photo_index, name in enumerate(names):
                filename = f"post-{index}-{photo_index}.jpg"
                with Image.open(artwork / name) as asset:
                    background = Image.new("RGB", asset.size, (255, 252, 246))
                    if asset.mode == "RGBA": background.paste(asset, mask=asset.getchannel("A"))
                    else: background.paste(asset.convert("RGB"))
                    background.save(photos / filename, "JPEG", quality=90)
                images.append("demo/" + filename)
            post, created = Post.objects.get_or_create(pk=ROOM_ID * 100 + index + 1, defaults={
                "room": room, "author": members[author], "caption": caption, "images": images,
                "description": caption + "\n사진은 체험용 가족 일러스트이며 실제 인물이나 장소 사진이 아니다."})
            if created:
                Post.objects.filter(pk=post.pk).update(created_at=datetime.fromisoformat(at))
    print(f"Demo family ready: {room.posts.count()} fictional posts.", flush=True)
    print(f"Login: {USERNAME} / {PASSWORD}", flush=True)
    for question in QUESTIONS:
        print("Example: " + question, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "seed", "ingest", "serve"])
    args = parser.parse_args()
    config = configure()
    if args.action == "setup":
        setup_neo4j(config); seed()
    elif args.action == "seed":
        seed()
    elif args.action == "ingest":
        from django.conf import settings
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("Set OPENAI_API_KEY in the repository .env before real Graphiti ingestion.")
        from django.core.management import call_command
        call_command("run_construction_worker", family_id=ROOM_ID, once=True)
    else:
        from django.core.management import call_command
        call_command("runserver", "127.0.0.1:8001", use_reloader=False)


if __name__ == "__main__":
    main()
