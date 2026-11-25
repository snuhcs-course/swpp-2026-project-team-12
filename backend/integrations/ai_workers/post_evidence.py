"""Read ranked family post sources together for the Post QA evidence pass."""

import re

from django.utils import timezone
from graphiti_core.search.search_utils import fulltext_query, rrf

from apps.posts.models import Post
from integrations.ai.prompts import EPISODE_BUDGET, SUPPLEMENTAL_EPISODE_LIMIT

from .graphiti_client import family_group
from .searching_graphiti import SEARCH_CONFIG
from .temporal_search import date_preference, time_rank


POST_SOURCE_QUERY = """
UNWIND $queries AS candidate
CALL (candidate) {
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.name STARTS WITH 'post_' AND e.content_embedding IS NOT NULL
      AND ($exclude_post IS NULL OR e.name <> $exclude_post)
      AND size(e.content_embedding) = size(candidate.vector)
      AND (candidate.cutoff IS NULL OR e.valid_at <= candidate.cutoff)
    WITH e, vector.similarity.cosine(e.content_embedding, candidate.vector) AS score
    WHERE score >= $min_score
    ORDER BY score DESC, e.uuid LIMIT $limit
    RETURN collect(e.uuid) AS semantic
}
CALL (candidate) {
    WITH candidate WHERE candidate.lexical <> ''
    CALL db.index.fulltext.queryNodes('episode_content', candidate.lexical) YIELD node AS e, score
    WHERE e.group_id = $group_id AND e.name STARTS WITH 'post_'
      AND ($exclude_post IS NULL OR e.name <> $exclude_post)
      AND (candidate.cutoff IS NULL OR e.valid_at <= candidate.cutoff)
    WITH e, score ORDER BY score DESC, e.uuid LIMIT $limit
    RETURN collect(e.uuid) AS lexical
}
WITH collect({index: candidate.index, semantic: semantic, lexical: lexical}) AS rankings
CALL (rankings) {
    UNWIND rankings AS ranking
    UNWIND ranking.semantic + ranking.lexical AS id
    WITH DISTINCT id
    MATCH (e:Episodic {group_id: $group_id, uuid: id})
    RETURN collect({id: e.uuid, name: e.name, text: e.content, recorded_at: e.valid_at}) AS sources
}
RETURN rankings, sources
"""


async def attach_post_fields(family_id, sources):
    """Read the actual author, caption and description for the selected graph records."""
    names = {source["name"] for source in sources if re.fullmatch(r"post_[0-9]{1,19}", source["name"])}
    if not names:
        return sources
    ids = {int(name[5:]) for name in names if int(name[5:]) <= 2**63 - 1}
    records = Post.objects.filter(room_id=family_id, pk__in=ids).values_list(
        "pk", "author__display_name", "caption", "description",
    )
    posts = {f"post_{pk}": (author, caption, description) async for pk, author, caption, description in records}
    for source in sources:
        name = source["name"]
        if name not in names:
            continue
        if name in posts:
            author, caption, description = posts[name]
        else:
            # Older graph records may no longer have a corresponding SQLite row.
            header, marker, description = source["text"].partition("\n상세 설명: ")
            author = header.removeprefix("작성자: ") if marker and header.startswith("작성자: ") else None
            caption = None
            if not marker:
                description = source["text"]
        source["post_fields"] = {"게시글 작성자": author, "게시글 원문": caption, "게시글 설명": description}
    return sources


async def prefetch_post_episodes(graphiti, family_id, queries, *, question=None, exclude_post=None):
    group_id = family_group(family_id)
    reference_time = timezone.now()
    vectors = await graphiti.embedder.create_batch([query.replace('\n', ' ') for query in queries])
    question_preference = date_preference(question, reference_time)
    preferences = [question_preference or date_preference(query, reference_time) for query in queries]
    scans = [{
        'index': index,
        'vector': vector,
        'lexical': fulltext_query(query, [group_id], graphiti.driver),
        'cutoff': preference.cutoff if preference else None,
    } for index, (query, vector, preference) in enumerate(zip(queries, vectors, preferences, strict=True))]
    rows, _, _ = await graphiti.driver.execute_query(
        POST_SOURCE_QUERY, group_id=group_id, queries=scans, exclude_post=exclude_post, routing_='r',
        min_score=SEARCH_CONFIG.episode_config.sim_min_score, limit=SEARCH_CONFIG.limit,
    )
    row, = rows
    sources = {source['id']: source for source in row['sources']}
    ranked_ids = []
    for ranking in sorted(row['rankings'], key=lambda item: item['index']):
        semantic = ranking['semantic']
        ids, scores = rrf([ranking['lexical'], semantic, semantic])
        ranked = sorted(zip(ids, scores, strict=True), key=lambda item: time_rank(
            item[1] * 2 / 3, sources[item[0]]['recorded_at'].to_native(), reference_time, preferences[ranking['index']],
        ), reverse=True)
        ranked_ids.append([key for key, _ in ranked])

    # Give each query a chance to contribute current and historical evidence.
    selected = {}
    budget = EPISODE_BUDGET + SUPPLEMENTAL_EPISODE_LIMIT
    for rank in range(max(map(len, ranked_ids), default=0)):
        for ids in ranked_ids:
            if rank < len(ids):
                key = ids[rank]
                if key not in selected:
                    source = sources[key]
                    selected[key] = {**source, 'recorded_at': source['recorded_at'].isoformat()}
                if len(selected) == budget:
                    return await attach_post_fields(family_id, list(selected.values()))
    return await attach_post_fields(family_id, list(selected.values()))
