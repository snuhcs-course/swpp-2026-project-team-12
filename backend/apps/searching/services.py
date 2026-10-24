"""Thin application wrappers around the AI workers."""

from integrations.ai_workers import searching_workers
from integrations.ai_workers.searching_workers import SearchUnavailable


def search_history(family_id, question):
    return searching_workers.search_history(family_id, question)


def search_queries(family_id, queries):
    return searching_workers.search_queries(family_id, queries)
