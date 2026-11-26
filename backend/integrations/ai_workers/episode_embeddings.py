"""Persist and search post descriptions using the shared Graphiti embedder."""

import re

from graphiti_core.driver.record_parsers import episodic_node_from_record
from graphiti_core.models.nodes.node_db_queries import EPISODIC_NODE_RETURN
from graphiti_core.search.search_utils import fulltext_query


KOREAN_WORD = re.compile(r"[가-힣]+")
ACTION_ENDING = re.compile(r"([가-힣]{2,}?)(?:했는지|했나요|했던|했다는|했다고|하는지|하는|한다는|한다고|할지|한)")
NOUN_PARTICLE = re.compile(r"([가-힣]{2,}?)(?:께서|이가|에게|에서|으로|이랑|하고|처럼|까지|부터|은|는|이|가|을|를|와|과|에|의|로|도)")


def action_keywords(query):
    """Allow an inflected Korean action to match the same stem in a record."""
    words = KOREAN_WORD.findall(query)
    clauses = {}
    for index, word in enumerate(words):
        action = ACTION_ENDING.fullmatch(word)
        if action is None:
            continue
        stem = action[1]
        clauses[f"{stem}*"] = None
        if index and (argument := NOUN_PARTICLE.fullmatch(words[index - 1])):
            # A subject or object next to the action narrows the prefix match.
            clauses[f"({argument[1]}* AND {stem}*)^2"] = None
        if len(clauses) >= 8:
            break
    return " ".join(clauses)


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


async def search_episodes(graphiti, group_id, query_vector, *, limit, min_score, cutoff=None, exclude_post=None):
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $group_id}) "
        "WHERE e.name STARTS WITH 'post_' AND e.content_embedding IS NOT NULL "
        "AND ($exclude_post IS NULL OR e.name <> $exclude_post) "
        "AND ($cutoff IS NULL OR e.valid_at <= $cutoff) "
        "AND size(e.content_embedding) = size($query_vector) "
        "WITH e, vector.similarity.cosine(e.content_embedding, $query_vector) AS score "
        "WHERE score >= $min_score "
        "RETURN " + EPISODIC_NODE_RETURN + " ORDER BY score DESC LIMIT $limit",
        group_id=group_id, query_vector=query_vector, min_score=min_score, limit=limit,
        routing_="r", exclude_post=exclude_post, cutoff=cutoff,
    )
    return [episodic_node_from_record(record) for record in records]


async def search_lexical_episodes(graphiti, group_id, query, *, limit, cutoff, exclude_post, keywords=""):
    # Graphiti's Neo4j episode BM25 search does not apply episode exclusions or cutoffs.
    fuzzy_query = fulltext_query(query, [group_id], graphiti.driver)
    if keywords:
        # fulltext_query sanitizes user syntax. Only the server's Hangul prefix
        # clauses are added within the existing family-scoped disjunction.
        fuzzy_query = f"{fuzzy_query[:-1]} {keywords})" if fuzzy_query else keywords
    if not fuzzy_query:
        return []
    records, _, _ = await graphiti.driver.execute_query(
        "CALL db.index.fulltext.queryNodes('episode_content', $query) YIELD node AS e, score "
        "WHERE e.group_id = $group_id AND ($exclude_post IS NULL OR e.name <> $exclude_post) "
        "AND ($cutoff IS NULL OR e.valid_at <= $cutoff) "
        "RETURN " + EPISODIC_NODE_RETURN + " ORDER BY score DESC LIMIT $limit",
        query=fuzzy_query, group_id=group_id, exclude_post=exclude_post, cutoff=cutoff, limit=limit, routing_="r",
    )
    return [episodic_node_from_record(record) for record in records]
