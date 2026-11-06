"""One retrieval path for both a single question and parallel questions."""

import asyncio

from graphiti_core.search.search_config import (
    EdgeSearchConfig,
    EdgeSearchMethod,
    EpisodeSearchConfig,
    EpisodeSearchMethod,
    SearchConfig,
)
from graphiti_core.search.search_utils import rrf

from .episode_embeddings import search_episodes
from .graphiti_client import family_group


SEARCH_CONFIG = SearchConfig(
    edge_config=EdgeSearchConfig(
        search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
    ),
    episode_config=EpisodeSearchConfig(search_methods=[EpisodeSearchMethod.bm25]),
    limit=5,
)


async def _search(graphiti, group_id, query):
    # Share one query embedding between fact and episode retrieval.
    vector = await graphiti.embedder.create(input_data=[query.replace("\n", " ")])
    async with asyncio.TaskGroup() as group:
        graph = group.create_task(graphiti.search_(
            query=query, group_ids=[group_id], config=SEARCH_CONFIG, query_vector=vector,
        ))
        semantic = group.create_task(search_episodes(
            graphiti, group_id, vector, limit=2 * SEARCH_CONFIG.limit,
            min_score=SEARCH_CONFIG.episode_config.sim_min_score,
        ))
    result = graph.result()
    ranked_lists = [[episode for episode in episodes if episode.group_id == group_id]
                    for episodes in [result.episodes, semantic.result()]]
    episodes = {episode.uuid: episode for ranked in ranked_lists for episode in ranked}
    ids, _ = rrf([[episode.uuid for episode in ranked] for ranked in ranked_lists])
    result.episodes = [episodes[uuid] for uuid in ids[:SEARCH_CONFIG.limit]]
    return result


async def search_many(graphiti, family_id, queries, *, max_queries=3):
    # Server-owned limit; never accept a query limit chosen by the model.
    if type(max_queries) is not int or not 1 <= max_queries <= 5:
        raise ValueError("검색 질문 상한은 1~5 사이 정수여야 합니다.")
    if not isinstance(queries, (list, tuple)) or not 1 <= len(queries) <= max_queries or any(
        not isinstance(query, str) or not query.strip() or len(query) > 1000
        for query in queries
    ):
        raise ValueError(f"검색 질문은 1~{max_queries}개, 각 1,000자 이내로 입력하세요.")
    group_id = family_group(family_id)
    # Cancel sibling searches before their shared client is closed on failure.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(_search(graphiti, group_id, query)) for query in queries]
    edges_by_query = [[edge for edge in task.result().edges if edge.group_id == group_id] for task in tasks]
    episodes_by_query = [[episode for episode in task.result().episodes if episode.group_id == group_id]
                         for task in tasks]
    source_ids_by_query = [list(dict.fromkeys(
        source for edge in edges for source in edge.episodes
    ))[:12] for edges in edges_by_query]
    sources = {episode.uuid: {
        "id": episode.uuid, "name": episode.name, "text": episode.content,
        "recorded_at": episode.valid_at.isoformat(),
    } for episodes in episodes_by_query for episode in episodes}
    source_ids = list(dict.fromkeys(source for ids in source_ids_by_query for source in ids
                                    if source not in sources))
    if source_ids:
        records, _, _ = await graphiti.driver.execute_query(
            "MATCH (e:Episodic {group_id: $group_id}) WHERE e.uuid IN $ids "
            "RETURN e.uuid AS id, e.name AS name, e.content AS text, toString(e.valid_at) AS recorded_at",
            group_id=group_id, ids=source_ids, routing_="r",
        )
        sources.update({record["id"]: dict(record) for record in records})
    return [{
        "query": query,
        "memories": [{
            "id": edge.uuid,
            "fact": edge.fact,
            "valid_at": edge.valid_at.isoformat() if edge.valid_at else None,
            "invalid_at": edge.invalid_at.isoformat() if edge.invalid_at else None,
            "source_episode_ids": edge.episodes,
            "sources": [sources[source] for source in edge.episodes
                        if source in ids and source in sources],
        } for edge in edges] + [{
            "id": episode.uuid,
            "fact": episode.content,
            # Episode time is the source's recorded_at, not a fact validity interval.
            "valid_at": None,
            "invalid_at": None,
            "source_episode_ids": [episode.uuid],
            "sources": [sources[episode.uuid]],
        } for episode in episodes if episode.uuid not in ids],
    } for query, edges, episodes, ids in zip(queries, edges_by_query, episodes_by_query, source_ids_by_query)]
