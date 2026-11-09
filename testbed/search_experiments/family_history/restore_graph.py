"""Restore the frozen graphs to an EMPTY isolated Neo4j. Never builds new embeddings."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[2]/'testbed/memoryqa_scaling'))
from lib import graphs
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--allow-db-write',action='store_true');a=p.parse_args()
 graphs.ROOT=ROOT/'.inputs/restore'
 print(graphs.restore_graphs(allow_write=a.allow_db_write))
