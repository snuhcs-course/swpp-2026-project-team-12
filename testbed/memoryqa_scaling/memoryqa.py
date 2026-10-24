"""Portable MemoryQA family-memory scaling experiment commands."""
import argparse
import json
import sys
from pathlib import Path

from lib.common import ROOT, read, save, sha


def check_bundle():
    lock=read(ROOT/"bundle_manifest.json")
    for name,expected in lock["files"].items():
        from lib.common import relative_path
        path=relative_path(name)
        if not path.is_file() or sha(path)!=expected:raise ValueError("Packaged input changed: "+name)
    return {"checksummed_files":len(lock["files"])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    c=sub.add_parser("check",help="Offline inputs, hashes and recorded metrics; no database or API")
    c.add_argument("--images",action="store_true")
    c.add_argument("--directory",help="Optional flat image cache directory")
    sub.add_parser("prepare-app",help="Extract the pinned backend from local Git history")
    sub.add_parser("verify-results",help="Recompute the six result cells without network or API")
    sub.add_parser("check-graphs",help="Read-only comparison of restored graphs to snapshots")
    r=sub.add_parser("restore-graphs",help="Restore all three snapshots into EMPTY isolated Neo4j")
    r.add_argument("--allow-db-write",action="store_true")
    for name in ("restore-sql","check-sql","run"):
        s=sub.add_parser(name)
        s.add_argument("--size",type=int,choices=(100,200,300),required=True)
        s.add_argument("--output",type=Path,required=True)
        if name=="run":s.add_argument("--allow-paid",action="store_true")
    args=parser.parse_args()
    check_bundle()
    if args.command=="check":
        from lib.app import verify_environment
        from lib.validate import check_inputs,verify_results
        result={"bundle":check_bundle(),"environment":verify_environment(),"inputs":check_inputs(images=args.images,directory=args.directory),
                "recorded_results":verify_results(),"paid_calls":0}
        save(ROOT/"output/offline_check.json",result)
        print(json.dumps({"bundle":result["bundle"],"environment":result["environment"],"inputs":result["inputs"],
              "recorded_tasks":result["recorded_results"]["tasks"],"all_six_cells_recomputed":True,"paid_calls":0},ensure_ascii=False,indent=2))
        return
    if args.command=="prepare-app":
        from lib.app import prepare_app
        result=prepare_app()
    elif args.command=="verify-results":
        from lib.validate import verify_results
        result=verify_results()
        save(ROOT/"output/recomputed_results.json",result)
    elif args.command in ("restore-graphs","check-graphs"):
        from lib.graphs import restore_graphs,check_graphs
        result=restore_graphs(allow_write=args.allow_db_write) if args.command=="restore-graphs" else check_graphs()
    elif args.command in ("restore-sql","check-sql"):
        from lib.sql import restore_sql,check_sql
        result=(restore_sql if args.command=="restore-sql" else check_sql)(args.size,args.output)
    elif args.command=="run":
        from lib.run import run
        result=run(args.size,args.output,allow_paid=args.allow_paid)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    try:
        main()
    except (ValueError,RuntimeError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
