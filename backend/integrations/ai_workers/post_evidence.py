"""Read ranked family post sources together for the Post QA evidence pass."""

from django.utils import timezone
from graphiti_core.search.search_utils import fulltext_query, rrf

from integrations.ai.prompts import EPISODE_BUDGET, SUPPLEMENTAL_EPISODE_LIMIT

from .graphiti_client import family_group
from .searching_graphiti import SEARCH_CONFIG
from .temporal_search import date_window, time_rank


POST_SOURCE_QUERY = """
UNWIND $queries AS candidate
CALL (candidate) {
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.name STARTS WITH 'post_' AND e.content_embedding IS NOT NULL
      AND size(e.content_embedding) = size(candidate.vector)
      AND (candidate.start IS NULL OR (e.valid_at >= candidate.start AND e.valid_at < candidate.end))
    WITH e, vector.similarity.cosine(e.content_embedding, candidate.vector) AS score
    WHERE score >= $min_score
    ORDER BY score DESC, e.uuid LIMIT $limit
    RETURN collect(e.uuid) AS semantic
}
CALL (candidate) {
    WITH candidate WHERE candidate.lexical <> ''
    CALL db.index.fulltext.queryNodes('episode_content', candidate.lexical) YIELD node AS e, score
    WHERE e.group_id = $group_id AND e.name STARTS WITH 'post_'
      AND (candidate.start IS NULL OR (e.valid_at >= candidate.start AND e.valid_at < candidate.end))
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


async def prefetch_post_episodes(graphiti, family_id, queries):
    group_id = family_group(family_id)
    reference_time = timezone.now()
    vectors = await graphiti.embedder.create_batch([query.replace('\n', ' ') for query in queries])
    windows = [date_window(query, reference_time) for query in queries]
    scans = [{
        'index': index,
        'vector': vector,
        'lexical': fulltext_query(query, [group_id], graphiti.driver),
        'start': window[0] if window else None,
        'end': window[1] if window else None,
    } for index, (query, vector, window) in enumerate(zip(queries, vectors, windows, strict=True))]
    rows, _, _ = await graphiti.driver.execute_query(
        POST_SOURCE_QUERY, group_id=group_id, queries=scans, routing_='r',
        min_score=SEARCH_CONFIG.episode_config.sim_min_score, limit=SEARCH_CONFIG.limit,
    )
    row, = rows
    sources = {source['id']: source for source in row['sources']}
    ranked_ids = []
    for ranking in sorted(row['rankings'], key=lambda item: item['index']):
        semantic = ranking['semantic']
        ids, scores = rrf([ranking['lexical'], semantic, semantic])
        window = windows[ranking['index']]
        ranked = sorted(zip(ids, scores, strict=True), key=lambda item: time_rank(
            item[1] * 2 / 3, sources[item[0]]['recorded_at'].to_native(), reference_time, window,
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
                    return list(selected.values())
    return list(selected.values())
