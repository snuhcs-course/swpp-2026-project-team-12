"""One background construction worker per family, independent of search."""

import asyncio
import logging
import os
import time
from pathlib import Path

from django.conf import settings

from apps.posts.models import Post

from integrations.utils.family_graph import sync_family


def run_worker(family_id, once, stdout, stderr):
    lock_dir = Path(settings.MEDIA_ROOT) / ".graphiti-workers"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / f"family_{family_id}.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("이 가족의 저장 worker가 이미 실행 중이에요.") from error
        # The OS releases this local family lock even after a process crash.
        construct(family_id, once, stdout, stderr)


def construct(family_id, once, stdout, stderr):
    from integrations.ai.feed_description import describe_post

    from .construction_graphiti import add_memory, episode_names
    from .graphiti_client import close_graphiti, initialize_graphiti

    with asyncio.Runner() as runner:
        graphiti = runner.run(initialize_graphiti())
        try:
            runner.run(graphiti.build_indices_and_constraints())
            while True:
                try:
                    sync_family(graphiti, family_id, runner)
                    names = runner.run(episode_names(graphiti, family_id))
                except Exception as error:
                    if once:
                        raise RuntimeError("가족 기록 동기화에 실패했어요.") from error
                    logging.getLogger(__name__).exception("Family graph sync or episode embedding failed")
                    stderr.write("가족 기록 동기화 실패. 5초 후 다시 시도해요.")
                    time.sleep(5)
                    continue
                completed = {
                    int(name[5:]) for name in names
                    if name.startswith("post_") and name[5:].isdigit()
                }
                posts = Post.objects.filter(room_id=family_id).exclude(pk__in=completed)
                for post in posts.select_related("author").order_by("created_at", "pk")[:100]:
                    try:
                        if not post.description:
                            post.description = runner.run(describe_post(post))
                            post.save(update_fields=["description"])
                        runner.run(add_memory(
                            graphiti, family_id,
                            f"작성자: {post.author.display_name}\n상세 설명: {post.description}",
                            f"post_{post.pk}", post.created_at,
                        ))
                    except Exception as error:
                        if once:
                            raise RuntimeError(f"게시물 {post.pk} 저장에 실패했어요.") from error
                        logging.getLogger(__name__).exception("Graph construction failed")
                        stderr.write(f"게시물 {post.pk} 저장 실패. 5초 후 다시 시도해요.")
                        break
                    stdout.write(f"게시물 {post.pk} 저장 완료")
                    stdout.flush()
                if once:
                    return
                time.sleep(5)
        except KeyboardInterrupt:
            stdout.write("가족 기록 저장 worker를 종료합니다.")
        finally:
            runner.run(close_graphiti(graphiti))
