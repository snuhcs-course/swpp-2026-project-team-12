"""Process-local DB write prevention for a retrieval-only experiment.

No app/package source is edited. Disable automatic index construction, reject
write Cypher and sessions/transactions, and set SQLite query_only on connection.
The search query implementation and all model prompts/settings are unchanged.
"""
from contextlib import contextmanager
import re

WRITE_WORDS=re.compile(r'\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|ALTER|GRANT|DENY|REVOKE|LOAD|FOREACH)\b',re.I)
PROCEDURES=re.compile(r'\bCALL\s+([a-zA-Z0-9_.]+)',re.I)
ALLOWED_PROCEDURES={'db.index.fulltext.queryNodes','db.index.fulltext.queryRelationships',
                    'db.index.vector.queryNodes','db.index.vector.queryRelationships'}


def assert_read_query(query):
    if WRITE_WORDS.search(query):raise RuntimeError('DB write query blocked by experiment guard')
    if not re.match(r'^\s*(MATCH|OPTIONAL\s+MATCH|WITH|RETURN|SHOW|CALL)\b',query,re.I):
        raise RuntimeError('Unknown query type blocked by experiment guard')
    if any(name not in ALLOWED_PROCEDURES for name in PROCEDURES.findall(query)):
        raise RuntimeError('Non-search procedure blocked by experiment guard')


@contextmanager
def read_only_database_scope():
    from django.db.backends.signals import connection_created
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    original_query=Neo4jDriver.execute_query
    originals={name:getattr(Neo4jDriver,name) for name in ('build_indices_and_constraints','execute_query','session','transaction')}
    async def no_schema_changes(self,*args,**kwargs):return None
    async def query(self,cypher_query_,**kwargs):
        assert_read_query(cypher_query_)
        kwargs['routing_']='r'
        return await original_query(self,cypher_query_,**kwargs)
    def deny_session(*args,**kwargs):raise RuntimeError('Raw DB session/transaction blocked by experiment guard')
    def sqlite_read_only(sender,connection,**kwargs):
        if connection.vendor!='sqlite':raise RuntimeError('Unexpected SQL engine')
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA query_only=ON')
            cursor.execute('PRAGMA query_only')
            assert cursor.fetchone()[0]==1
    try:
        Neo4jDriver.build_indices_and_constraints=no_schema_changes
        Neo4jDriver.execute_query=query
        Neo4jDriver.session=deny_session
        Neo4jDriver.transaction=deny_session
        connection_created.connect(sqlite_read_only,weak=False,dispatch_uid='familyqa30_readonly')
        yield
    finally:
        connection_created.disconnect(dispatch_uid='familyqa30_readonly')
        for name,method in originals.items():setattr(Neo4jDriver,name,method)
