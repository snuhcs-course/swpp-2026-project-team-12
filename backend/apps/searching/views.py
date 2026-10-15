from apps.api import APIError, api, body, required
from apps.posts.services import current_room

from . import services


@api("POST")
def history(request):
    room = current_room(request)
    question = required(body(request), "question", 1000)
    try:
        return services.search_history(room.pk, question)
    except services.SearchUnavailable as error:
        raise APIError("가족 기록을 검색하지 못했어요. 잠시 후 다시 시도해 주세요.", 503) from error


@api("POST")
def memories(request):
    room = current_room(request)
    queries = body(request).get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise APIError("검색 질문을 1~3개 입력해 주세요.")
    queries = [required({"query": query}, "query", 1000) for query in queries]
    try:
        return services.search_queries(room.pk, queries)
    except services.SearchUnavailable as error:
        raise APIError("가족 기록을 검색하지 못했어요. 잠시 후 다시 시도해 주세요.", 503) from error
