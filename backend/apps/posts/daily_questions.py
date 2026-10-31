"""Daily conversation prompts are posts for discussion, but never feed letters."""
import json
from datetime import date
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.api import APIError, api, body
from apps.families.models import FamilyRoom
from apps.families.services import room_for
from apps.families.utils import relationship

from .models import DailyQuestion, Post, QuestionAnswer, QuestionTemplate


ROTATION_PATH = Path(__file__).resolve().parent / "data" / "daily_questions.json"
GRADES = {"S", "A", "B", "C"}


def validate_definition(title, kind, options):
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 2000:
        raise APIError("질문은 1~2,000자로 적어 주세요.")
    if not isinstance(kind, str) or kind not in {"choice", "text", "weather", "tier"}:
        raise APIError("질문 형식을 확인해 주세요.")
    if not isinstance(options, list) or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in options):
        raise APIError("선택지는 100자 이내로 적어 주세요.")
    options = [x.strip() for x in options]
    if len(set(options)) != len(options) or (kind == "text" and options) or (kind != "text" and not 2 <= len(options) <= 6):
        raise APIError("서로 다른 선택지를 2~6개 등록해 주세요. 한 줄 답변에는 선택지를 넣지 않아요.")
    return title.strip(), kind, options


def load_rotation():
    try:
        entries = json.loads(ROTATION_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Cannot read daily question rotation: {ROTATION_PATH}: {error}") from error
    if not isinstance(entries, list) or not entries:
        raise ImproperlyConfigured(f"{ROTATION_PATH}: expected a non-empty question array")
    rotation = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or not {"title", "kind", "options"} <= entry.keys():
            raise ImproperlyConfigured(f"{ROTATION_PATH}: question {index} requires title, kind and options")
        try:
            title, kind, options = validate_definition(entry["title"], entry["kind"], entry["options"])
        except APIError as error:
            raise ImproperlyConfigured(f"{ROTATION_PATH}: question {index}: {error}") from error
        rotation.append((kind, title, options))
    return rotation


# Load and validate once per server process, rather than reading the file per request.
ROTATION = load_rotation()


def definition(day):
    scheduled = QuestionTemplate.objects.filter(date=day).first()
    if scheduled:
        return scheduled.title, scheduled.kind, scheduled.options
    kind, title, options = ROTATION[(day - date(2026, 10, 31)).days % len(ROTATION)]
    return title, kind, options


def ensure_today(room):
    day = timezone.localdate()
    existing = DailyQuestion.objects.select_related("post", "room").filter(room=room, date=day).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            # Serialize publication per room on databases with row locks. The unique
            # constraint is the final arbiter, and rolls back the losing post too.
            FamilyRoom.objects.select_for_update().get(pk=room.pk)
            existing = DailyQuestion.objects.select_related("post", "room").filter(room=room, date=day).first()
            if existing:
                return existing
            title, kind, options = definition(day)
            post = Post.objects.create(room=room, author=None, kind="question", caption=title)
            return DailyQuestion.objects.create(post=post, room=room, date=day, kind=kind, options=options)
    except IntegrityError:
        return DailyQuestion.objects.select_related("post", "room").get(room=room, date=day)


def question_for(request, pk):
    question = DailyQuestion.objects.select_related("post", "room").filter(
        pk=pk, room__members__user=request.user,
    ).first()
    if question is None:
        raise APIError("질문을 찾을 수 없어요.", 404)
    return question


def status(question, user):
    # Own writes do not create a new unread dot. IDs and timestamps are opaque
    # change tokens, never counters that pressure non-participants to answer.
    answer = question.answers.exclude(author=user).aggregate(value=Max("updated_at"))["value"]
    comment = question.post.comments.exclude(author=user).aggregate(value=Max("created_at"))["value"]
    return {"id": question.pk, "date": question.date.isoformat(), "title": question.post.caption,
            "version": f"{question.pk}:{answer.isoformat() if answer else ''}:{comment.isoformat() if comment else ''}"}


def answer_options(question):
    options = list(question.options)
    if question.kind in {"choice", "weather"} and "기타" not in options:
        options.append("기타")
    return options


def serialize_question(question, request):
    return {
        **status(question, request.user), "post_id": question.post_id,
        "title": question.post.caption, "kind": question.kind, "options": answer_options(question),
        "answers": [{
            "id": answer.pk, "author_id": answer.author_id,
            "author_name": answer.author.display_name,
            "relationship": relationship(request.user, answer.author, question.room),
            "choice": answer.choice, "other_text": answer.other_text, "text": answer.text, "tiers": answer.tiers, "source": answer.source,
            "updated_at": timezone.localtime(answer.updated_at).isoformat(),
        } for answer in question.answers.select_related("author")],
        "comments": [{
            "id": comment.pk, "author_id": comment.author_id, "author_name": comment.author.display_name,
            "text": comment.text, "source": comment.source,
            "created_at": timezone.localtime(comment.created_at).isoformat(),
        } for comment in question.post.comments.select_related("author")],
    }


@api("GET")
def today(request):
    return serialize_question(ensure_today(room_for(request)), request)


@api("GET")
def detail(request, pk):
    return serialize_question(question_for(request, pk), request)


@api("GET")
def history(request):
    room = room_for(request)
    ensure_today(room)
    try:
        before = request.GET.get("before")
        chosen = date.fromisoformat(before) if before else None
        if before and chosen.isoformat() != before:
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise APIError("날짜를 다시 확인해 주세요.") from error
    query = room.daily_questions.select_related("post")
    if chosen:
        query = query.filter(date__lt=chosen)
    rows = list(query[:31])
    return {"questions": [{"id": item.pk, "date": item.date.isoformat(), "kind": item.kind,
                           "title": item.post.caption} for item in rows[:30]],
            "next_before": rows[29].date.isoformat() if len(rows) > 30 else None}


@api("PUT")
def answer(request, pk):
    question = question_for(request, pk)
    data = body(request)
    choice, text, tiers = data.get("choice", ""), data.get("text", ""), data.get("tiers", {})
    source = data.get("source", "text")
    other_text = data.get("other_text", "")
    if not isinstance(other_text, str) or len(other_text.strip()) > 100:
        raise APIError("기타 내용은 100자 이내로 적어 주세요.")
    other_text = other_text.strip()
    if (choice == "기타" and not other_text) or (choice != "기타" and other_text):
        raise APIError("기타를 선택하면 내용을 적어 주세요.")
    if not isinstance(choice, str) or not isinstance(text, str) or len(text.strip()) > 1000 or not isinstance(source, str) or source not in {"text", "voice"}:
        raise APIError("답변은 1,000자 이내로 적어 주세요.")
    text = text.strip()
    if question.kind in {"choice", "weather"}:
        if choice not in answer_options(question) or tiers != {}:
            raise APIError("선택지 중 하나를 골라 주세요.")
    elif question.kind == "text":
        if not text or choice or tiers != {}:
            raise APIError("가족에게 들려줄 답변을 적어 주세요.")
    else:
        if choice or not isinstance(tiers, dict) or set(tiers) != set(question.options) or any(
            not isinstance(grade, str) or grade not in GRADES for grade in tiers.values()
        ):
            raise APIError("모든 항목의 등급을 골라 주세요.")
    QuestionAnswer.objects.update_or_create(question=question, author=request.user, defaults={
        "choice": choice, "other_text": other_text, "text": text, "tiers": tiers, "source": source,
    })
    return serialize_question(question, request)
