"""Persist and search post descriptions using the shared Graphiti embedder."""

from graphiti_core.driver.record_parsers import episodic_node_from_record
from graphiti_core.models.nodes.node_db_queries import EPISODIC_NODE_RETURN
from graphiti_core.search.search_utils import fulltext_query


async def embed_episodes(graphiti, group_id, episodes):
    if not episodes:
        return
    embeddings = await graphiti.embedder.create_batch([episode["content"] for episode in episodes])
    rows = [{"uuid": episode["uuid"], "content": episode["content"], "embedding": embedding}
            for episode, embedding in zip(episodes, embeddings, strict=True)]
    await graphiti.driver.execute_query(
        "UNWIND $episodes AS episode "
        "MATCH (e:Episodic {uuid: episode.uuid, group_id: $group_id}) "
        "WHERE e.content = episode.content "
        "SET e.content_embedding = episode.embedding",
        group_id=group_id, episodes=rows,
    )


async def search_episodes(graphiti, group_id, query_vector, *, limit, min_score, window=None, exclude_post=None):
    date_constraint = "AND e.valid_at >= $start AND e.valid_at < $end " if window else ""
    dates = {"start": window[0], "end": window[1]} if window else {}
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $group_id}) "
        "WHERE e.name STARTS WITH 'post_' AND e.content_embedding IS NOT NULL "
        "AND ($exclude_post IS NULL OR e.name <> $exclude_post) "
        "AND size(e.content_embedding) = size($query_vector) " + date_constraint
        + "WITH e, vector.similarity.cosine(e.content_embedding, $query_vector) AS score "
        "WHERE score >= $min_score "
        "RETURN " + EPISODIC_NODE_RETURN + " ORDER BY score DESC LIMIT $limit",
        group_id=group_id, query_vector=query_vector, min_score=min_score, limit=limit,
        routing_="r", exclude_post=exclude_post, **dates,
    )
    return [episodic_node_from_record(record) for record in records]


async def search_lexical_episodes(graphiti, group_id, query, *, limit, window, exclude_post):
    # Graphiti's Neo4j episode BM25 search does not apply SearchFilters.
    fuzzy_query = fulltext_query(query, [group_id], graphiti.driver)
    if not fuzzy_query:
        return []
    date_constraint = "AND e.name STARTS WITH 'post_' AND e.valid_at >= $start AND e.valid_at < $end " if window else ""
    dates = {"start": window[0], "end": window[1]} if window else {}
    records, _, _ = await graphiti.driver.execute_query(
        "CALL db.index.fulltext.queryNodes('episode_content', $query) YIELD node AS e, score "
        "WHERE e.group_id = $group_id AND ($exclude_post IS NULL OR e.name <> $exclude_post) "
        + date_constraint + "RETURN " + EPISODIC_NODE_RETURN + " ORDER BY score DESC LIMIT $limit",
        query=fuzzy_query, group_id=group_id, exclude_post=exclude_post, limit=limit, routing_="r", **dates,
    )
    return [episodic_node_from_record(record) for record in records]
