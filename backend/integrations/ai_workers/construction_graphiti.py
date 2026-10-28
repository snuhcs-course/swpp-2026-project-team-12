"""Construct graph episodes from family records."""

from django.utils import timezone
from graphiti_core.nodes import EpisodeType

from .episode_embeddings import embed_episodes
from .graphiti_client import family_group


async def episode_names(graphiti, family_id):
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $group_id}) "
        "RETURN e.uuid AS uuid, e.name AS name, "
        "CASE WHEN e.name STARTS WITH 'post_' AND e.content_embedding IS NULL "
        "THEN e.content END AS content",
        group_id=family_group(family_id), routing_="r",
    )
    # Repair older episodes and interrupted embedding writes without extracting facts again.
    pending = [record for record in records if record["content"] and record["content"].strip()]
    for start in range(0, len(pending), 100):
        await embed_episodes(graphiti, family_group(family_id), pending[start:start + 100])
    return {record["name"] for record in records}


async def add_memory(graphiti, family_id, text, source_name, reference_time=None):
    result = await graphiti.add_episode(
        name=source_name,
        episode_body=text,
        source=EpisodeType.text,
        source_description=f"토닥 기록: {source_name}",
        reference_time=reference_time or timezone.now(),
        group_id=family_group(family_id),
    )
    await embed_episodes(graphiti, family_group(family_id), [
        {"uuid": result.episode.uuid, "content": text},
    ])
    return result.episode.uuid
