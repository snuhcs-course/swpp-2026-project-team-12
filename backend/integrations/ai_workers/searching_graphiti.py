"""One retrieval path for both a single question and parallel questions."""

import asyncio

from .graphiti_client import family_group


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
        tasks = [group.create_task(graphiti.search(
            query=query, group_ids=[group_id], num_results=5,
        )) for query in queries]
    edges_by_query = [[edge for edge in task.result() if edge.group_id == group_id] for task in tasks]
    source_ids_by_query = [list(dict.fromkeys(
        source for edge in edges for source in edge.episodes
    ))[:12] for edges in edges_by_query]
    source_ids = list(dict.fromkeys(source for ids in source_ids_by_query for source in ids))
    sources = {}
    if source_ids:
        records, _, _ = await graphiti.driver.execute_query(
            "MATCH (e:Episodic {group_id: $group_id}) WHERE e.uuid IN $ids "
            "RETURN e.uuid AS id, e.name AS name, e.content AS text, toString(e.valid_at) AS recorded_at",
            group_id=group_id, ids=source_ids, routing_="r",
        )
        sources = {record["id"]: dict(record) for record in records}
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
        } for edge in edges],
    } for query, edges, ids in zip(queries, edges_by_query, source_ids_by_query)]
