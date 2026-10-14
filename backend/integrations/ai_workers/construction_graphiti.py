"""Construct graph episodes from family records."""

from django.utils import timezone
from graphiti_core.nodes import EpisodeType

from .graphiti_client import family_group


async def episode_names(graphiti, family_id):
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $group_id}) RETURN e.name AS name",
        group_id=family_group(family_id), routing_="r",
    )
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
    return result.episode.uuid
