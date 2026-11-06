"""Read-only audit of the supplied evaluation snapshot; no DB restore or API calls."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
from budget_lab import ROOT, read, write


def audit(root):
    base=root/'testbed_output/family-week-100-five-members'
    report=read(base/'feature_eval/post_qa.json')
    queries=read(base/'feature_eval/queries.json')['post_qa']
    manifest=read(base/'manifest.json');state=read(base/'database_state.json')
    graph=json.loads(gzip.decompress((root/'neo4j/graph_family_5971.json.gz').read_bytes()))
    nodes={n['p']['uuid']:n['p'] for n in graph['nodes']}
    episodes={n['p']['name']:n['p'] for n in graph['nodes'] if 'Episodic' in n['labels']}
    edges=[e['p'] for e in graph['edges'] if e['kind']=='RELATES_TO']
    graph_ids=set(nodes)|{e['uuid'] for e in edges}
    cases=report['cases'];grouped=collections.defaultdict(list)
    for row in cases:grouped[row['case']['feed_key']].append(row)
    per_probe={}
    for probe,rows in grouped.items():
        per_probe[probe]={
            'question':rows[0]['case']['question'],
            'correct':sum(r['judge']['verdicts']['correct']['pass'] for r in rows),
            'total':len(rows),
            'required_recall_full':sum(r['checks']['required_recall']==1 for r in rows),
            'required_memories':rows[0]['case']['required_memories'],
            'optional_memories':rows[0]['case']['optional_memories']}
    update_audit=[]
    for event in manifest['events']:
        if event['kind']!='update':continue
        ep=episodes.get('post_'+str(state['post_ids'][event['feed_key']]))
        update_audit.append({'feed_key':event['feed_key'],'episode_present':bool(ep),
                             'embedding_dimensions':len(ep.get('content_embedding',[])) if ep else None,
                             'fact_count':sum(ep['uuid'] in e.get('episodes',[]) for e in edges) if ep else 0})
    cross=collections.Counter((r['checks']['required_recall']==1,r['judge']['verdicts']['correct']['pass']) for r in cases)
    result={'evaluated_at':report['evaluated_at'],'metrics':report['metrics'],
            'retrieval_metrics':queries['metrics'],'per_probe':per_probe,
            'coverage_correct_cross_tab':[
                {'label_recall_full':key[0],'judge_correct':key[1],'cases':value} for key,value in sorted(cross.items())],
            'lost_to_budget_cases':sum(c['lost_to_budget'] for c in queries['cases']),
            'selected_memory_ids_missing_from_graph':sorted({m['id'] for r in cases for m in r['output']['memories'] if m['id'] not in graph_ids}),
            'selected_source_text_mismatches':sorted({s['id'] for r in cases for m in r['output']['memories'] for s in m['sources'] if s['id'] not in nodes or nodes[s['id']].get('content')!=s['text']}),
            'graph':{'nodes':len(graph['nodes']),'edges':len(graph['edges']),
                     'episodes':len(episodes),'facts':len(edges),'group_id':graph['group_id']},
            'updates':update_audit,
            'photos':{'count':len(list((base/'images').glob('*'))),
                      'unique_sha256':len({hashlib.sha256(p.read_bytes()).hexdigest() for p in (base/'images').glob('*') if p.is_file()})},
            'missing_for_exact_replay':['raw candidate memory arrays per query before select_budget','captured final Responses request','exact runtime commit and non-secret effective model settings'],
            'warning':'All pass/fail figures preserve the supplied judge decisions. These are not manually corrected accuracy scores.'}
    return result


if __name__=='__main__':
    result=audit(ROOT/'inputs/team_export')
    write(ROOT/'outputs/team_export_audit.json',result)
    print(json.dumps({'cases':result['metrics']['case_count'],'correct':result['metrics']['judge_correct_pass_rate'],
                      'lost_to_budget_cases':result['lost_to_budget_cases'],'graph':result['graph']},ensure_ascii=False))
