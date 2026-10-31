// Prefer the server's room-scoped feed records. Older servers expose only
// episode provenance; resolve exact post names through the authenticated API.
export async function memoryEvidence(result, fetchPost) {
  const unique = posts => [...new Map(posts.filter(post => post && Number.isSafeInteger(post.id) && post.id > 0)
    .map(post => [post.id, post])).values()];
  if (Object.hasOwn(result, 'evidence_posts')) {
    return { posts: unique(Array.isArray(result.evidence_posts) ? result.evidence_posts : []), unavailable: false };
  }
  const sources = (Array.isArray(result.memories) ? result.memories : [])
    .flatMap(memory => Array.isArray(memory?.sources) ? memory.sources : []).filter(Boolean);
  const selected = Array.isArray(result.source_episode_ids)
    ? result.source_episode_ids.flatMap(id => sources.filter(source => source.id === id)) : sources;
  const ids = [...new Set(selected.flatMap(source => {
    const match = /^post_([1-9][0-9]*)$/.exec(source.name);
    const id = match ? Number(match[1]) : NaN;
    return Number.isSafeInteger(id) ? [id] : [];
  }))];
  let unavailable = false;
  const posts = await Promise.all(ids.map(async id => {
    try {
      const post = await fetchPost(id);
      return post?.id === id ? post : null;
    } catch (error) {
      if (error.status === 401) throw error;
      if (![403, 404].includes(error.status)) unavailable = true;
      return null;
    }
  }));
  return { posts: unique(posts), unavailable };
}
