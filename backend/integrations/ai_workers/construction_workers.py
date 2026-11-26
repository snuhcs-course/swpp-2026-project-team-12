"""One background construction worker per family, independent of search."""

import asyncio
import logging
import os
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections

from apps.families.models import FamilyRoom
from apps.posts.models import Post

from integrations.utils.family_graph import sync_family
from apps.telemetry.jobs import enqueue, processing
from integrations.telemetry import stage, runtime


class WorkerAlreadyRunning(RuntimeError):
    pass


def run_worker(family_id, once, stdout, stderr, *, stop_event=None):
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
            raise WorkerAlreadyRunning("이 가족의 저장 worker가 이미 실행 중이에요.") from error
        # The OS releases this local family lock even after a process crash.
        if stop_event is None:
            construct(family_id, once, stdout, stderr)
        else:
            construct(family_id, once, stdout, stderr, stop_event=stop_event)


def construct(family_id, once, stdout, stderr, *, stop_event=None):
    from integrations.ai.feed_description import describe_post

    from .construction_graphiti import add_memory, episode_names
    from .graphiti_client import close_graphiti, initialize_graphiti

    with asyncio.Runner() as runner:
        graphiti = runner.run(initialize_graphiti())
        try:
            runner.run(graphiti.build_indices_and_constraints())
            while stop_event is None or not stop_event.is_set():
                if stop_event is not None:
                    # Background threads don't get Django's request connection cleanup.
                    close_old_connections()
                runtime("construction", last_poll=time.time())
                try:
                    sync_family(graphiti, family_id, runner)
                    names = runner.run(episode_names(graphiti, family_id))
                except FamilyRoom.DoesNotExist:
                    return
                except Exception as error:
                    if once:
                        raise RuntimeError("가족 기록 동기화에 실패했어요.") from error
                    logging.getLogger(__name__).exception("Family graph sync or episode embedding failed")
                    stderr.write("가족 기록 동기화 실패. 5초 후 다시 시도해요.")
                    pause(stop_event)
                    continue
                completed = {
                    int(name[5:]) for name in names
                    if name.startswith("post_") and name[5:].isdigit()
                }
                posts = Post.objects.filter(room_id=family_id, kind="news").exclude(pk__in=completed)
                for post in posts.select_related("author").order_by("created_at", "pk")[:100]:
                    if stop_event is not None and stop_event.is_set():
                        return
                    try:
                        with processing(enqueue("construction", f"post:{post.pk}", post.created_at)):
                            if not post.description:
                                with stage("description_generation"):
                                    post.description = runner.run(describe_post(post))
                                    post.save(update_fields=["description"])
                            with stage("graphiti_save"):
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
                pause(stop_event)
        except KeyboardInterrupt:
            stdout.write("가족 기록 저장 worker를 종료합니다.")
        finally:
            runner.run(close_graphiti(graphiti))


def pause(stop_event):
    if stop_event is None:
        time.sleep(5)
    else:
        stop_event.wait(5)
