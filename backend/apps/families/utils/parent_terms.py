"""Resolve a question's initial parent title relative to the signed-in viewer."""

import re

from .relationships import find_relationship


PARENT_TITLES = {
    "아빠": "아버지", "아버지": "아버지", "부친": "아버지",
    "엄마": "어머니", "어머니": "어머니", "모친": "어머니",
}
PARENT_MENTION = re.compile(
    r"(?<!\w)(?P<title>" + "|".join(PARENT_TITLES)
    + r")(?:한테서|에게서|한테|에게|께서|께|가|는|를|의|도|랑|와|과)?(?!\w)"
)


def question_parent_terms(viewer, room, question):
    """Use the family tree when the question clearly refers to one parent of the viewer."""
    from .tree import tree_data

    mentions = list(PARENT_MENTION.finditer(question))
    if len(mentions) != 1:
        return {}
    mention, = mentions
    if question[:mention.start()].strip() not in {"", "우리", "저희", "내", "제"}:
        return {}

    relation = PARENT_TITLES[mention["title"]]
    tree = tree_data(room)
    viewer_id = next((p["id"] for p in tree["people"] if p["user_id"] == viewer.pk), None)
    parent_ids = {link["parent_id"] for link in tree["parents"] if link["child_id"] == viewer_id}
    parents = [p for p in tree["people"] if p["id"] in parent_ids
               and find_relationship(tree, viewer_id, p["id"]) == relation]
    if len(parents) != 1 or not parents[0]["name"].strip():
        return {}
    name = parents[0]["name"].strip()
    return {title: name for title, role in PARENT_TITLES.items() if role == relation}


def include_parent_name(query, parent_terms, *, single_query):
    """Supply the known name to retrieval when the model's query omits it."""
    if not parent_terms:
        return query
    name = next(iter(parent_terms.values()))
    mentions = list(PARENT_MENTION.finditer(query))
    relevant = any(match["title"] in parent_terms for match in mentions)
    if name not in query and (relevant or (single_query and not mentions)) and len(name) + 1 + len(query) <= 1000:
        return f"{name} {query}"
    return query
