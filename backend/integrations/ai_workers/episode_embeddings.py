"""Persist and search post descriptions using the shared Graphiti embedder."""

from graphiti_core.driver.record_parsers import episodic_node_from_record
from graphiti_core.models.nodes.node_db_queries import EPISODIC_NODE_RETURN


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


async def search_episodes(graphiti, group_id, query_vector, *, limit, min_score):
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $group_id}) "
        "WHERE e.name STARTS WITH 'post_' AND e.content_embedding IS NOT NULL "
        "AND size(e.content_embedding) = size($query_vector) "
        "WITH e, vector.similarity.cosine(e.content_embedding, $query_vector) AS score "
        "WHERE score >= $min_score "
        "RETURN " + EPISODIC_NODE_RETURN + " ORDER BY score DESC LIMIT $limit",
        group_id=group_id, query_vector=query_vector, min_score=min_score, limit=limit,
        routing_="r",
    )
    return [episodic_node_from_record(record) for record in records]
