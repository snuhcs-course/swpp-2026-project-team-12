"""Typed, checksummed Graphiti snapshots; no LLM calls or automatic graph rebuild."""
from __future__ import annotations

import gzip
import json
import os
import re

from .common import ROOT, SIZES, digest, read, save, sha


def encode(value):
    from neo4j.time import Date, DateTime, Duration, Time
    if isinstance(value, (Date, DateTime, Duration, Time)):
        return {"$neo4j": type(value).__name__, "value": value.iso_format()}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Unsupported graph property type: {type(value).__name__}")


def decode(value):
    if isinstance(value, dict) and set(value) == {"$neo4j", "value"}:
        from neo4j.time import Date, DateTime, Duration, Time
        cls = {"Date": Date, "DateTime": DateTime, "Duration": Duration, "Time": Time}[value["$neo4j"]]
        return cls.from_iso_format(value["value"])
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def connection():
    from neo4j import GraphDatabase
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        raise ValueError("Export NEO4J_PASSWORD; no .env is read automatically")
    return GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), password), connection_timeout=15)


def canonical(nodes, edges):
    return {"nodes": sorted(({"p": encode(n["p"]), "labels": sorted(n["labels"])} for n in nodes), key=lambda n:n["p"]["uuid"]),
            "edges": sorted(({"a": e["a"], "b": e["b"], "kind": e["kind"], "p": encode(e["p"])} for e in edges),
                key=lambda e:(e["a"], e["b"], e["kind"], e["p"].get("uuid", "")))}


def read_group(driver, group):
    with driver.session(default_access_mode="READ") as session:
        # A single read transaction gives a consistent snapshot of nodes and edges.
        def load(tx):
            nodes = tx.run("MATCH (n {group_id:$g}) RETURN properties(n) AS p,labels(n) AS labels ORDER BY n.uuid", g=group).data()
            edges = tx.run("MATCH (n {group_id:$g})-[r]->(m) RETURN n.uuid AS a,m.uuid AS b,type(r) AS kind,properties(r) AS p ORDER BY a,b,kind,r.uuid", g=group).data()
            return nodes, edges
        return session.execute_read(load)


def export_graphs():
    """Operator-only packaging step: read existing experiment groups without writes."""
    entries = {}
    with connection() as driver:
        for size in SIZES:
            seed = read(ROOT / f"snapshots/history_{size}/graph_seed.json")
            nodes, edges = read_group(driver, seed["group_id"])
            historical = digest(json.loads(json.dumps({"nodes": nodes, "edges": edges}, default=str)))
            if historical != seed["fingerprint"]:
                raise ValueError(f"Existing graph {size} differs from the recorded experiment; export stopped")
            ids = {n["p"]["uuid"] for n in nodes}
            if not nodes or len(ids) != len(nodes) or any(e["a"] not in ids or e["b"] not in ids for e in edges):
                raise ValueError("Incomplete group snapshot or cross-group edge")
            body = canonical(nodes, edges)
            document = {"schema_version": 1, "history_size": size, "group_id": seed["group_id"],
                "recorded_fingerprint": historical, "content_sha256": digest(body), **body}
            name = f"snapshots/history_{size}/graph.json.gz"
            raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            path = ROOT / name
            path.write_bytes(gzip.compress(raw, mtime=0))
            entries[str(size)] = {"path": name, "sha256": sha(path), "content_sha256": digest(body),
                "nodes": len(nodes), "edges": len(edges), "bytes": path.stat().st_size,
                "group_id": seed["group_id"], "recorded_fingerprint": historical}
            print(f"Exported {size}: {len(nodes)} nodes, {len(edges)} edges, {path.stat().st_size} bytes", flush=True)
    save(ROOT / "snapshots/graph_manifest.json", {"schema_version": 1, "groups": entries,
        "source_access": "Neo4j read transactions only; no schema/index or LLM call",
        "canonicalization": "Sort labels and UUIDs; retain property types, embeddings and all recorded facts."})
    return entries


def load_snapshot(size):
    entry = read(ROOT / "snapshots/graph_manifest.json")["groups"][str(size)]
    path = ROOT / entry["path"]
    if sha(path) != entry["sha256"]:
        raise ValueError("Graph archive checksum mismatch")
    doc = json.loads(gzip.decompress(path.read_bytes()))
    if digest({k:doc[k] for k in ("nodes", "edges")}) != entry["content_sha256"]:
        raise ValueError("Graph content checksum mismatch")
    if len(doc["nodes"]) != entry["nodes"] or len(doc["edges"]) != entry["edges"]:
        raise ValueError("Graph snapshot counts differ")
    return doc


def check_graphs():
    rows = {}
    with connection() as driver:
        with driver.session(default_access_mode="READ") as session:
            indexes = session.run("SHOW INDEXES YIELD name,state RETURN name,state").data()
        required = {"node_name_and_summary", "edge_name_and_fact", "episode_content", "community_name"}
        online = {r["name"] for r in indexes if r["state"] == "ONLINE"}
        if not required <= online:
            raise ValueError("Required search indexes are not ONLINE; finish index initialization first")
        for size in SIZES:
            doc = load_snapshot(size)
            nodes, edges = read_group(driver, doc["group_id"])
            if digest(canonical(nodes, edges)) != doc["content_sha256"]:
                raise ValueError(f"Restored graph differs from the snapshot: {size}")
            rows[str(size)] = {"nodes": len(nodes), "edges": len(edges), "exact_properties_verified": True,
                              "search_indexes_online": True}
    return rows


def restore_graphs(*, allow_write=False):
    if not allow_write:
        raise ValueError("Graph restoration requires --allow-db-write and an EMPTY isolated Neo4j database")
    docs = [load_snapshot(size) for size in SIZES]
    symbol = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    with connection() as driver:
        with driver.session() as session:
            if session.run("MATCH (n) RETURN count(n) AS count").single()["count"]:
                raise ValueError("Destination Neo4j is not empty; existing data will not be modified")
            for doc in docs:
                def restore(tx):
                    for node in doc["nodes"]:
                        if not node["labels"] or not all(symbol.fullmatch(n) for n in node["labels"]):
                            raise ValueError("Unexpected node label")
                        labels = ":".join(node["labels"])
                        tx.run(f"CREATE (n:{labels}) SET n=$p", p=decode(node["p"])).consume()
                    for edge in doc["edges"]:
                        if not symbol.fullmatch(edge["kind"]):
                            raise ValueError("Unexpected relationship type")
                        tx.run(f"MATCH (a {{uuid:$a}}),(b {{uuid:$b}}) CREATE (a)-[r:{edge['kind']}]->(b) SET r=$p",
                            a=edge["a"], b=edge["b"], p=decode(edge["p"])).consume()
                session.execute_write(restore)
    # Only creates Graphiti indexes in the explicitly authorized isolated database.
    import asyncio
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    # Construct outside a running loop, so Graphiti does not schedule a second,
    # concurrent index initialization task from its constructor.
    index_driver = Neo4jDriver(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
    async def indices():
        try:
            await index_driver.build_indices_and_constraints()
        finally:
            await index_driver.close()
    asyncio.run(indices())
    with connection() as driver:
        with driver.session() as session:
            session.run("CALL db.awaitIndexes(60)").consume()
    return check_graphs()
