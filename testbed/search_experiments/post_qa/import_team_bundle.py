"""Convert teammate reports + raw query results into a frozen offline bundle."""
import argparse
import json
from budget_lab import read, write, validate_bundle


def convert(report, raw, manifest, database_state, question_at, captures):
    events={e['feed_key']:e for e in manifest['events']}
    names={f'post_{pid}':key for key,pid in database_state['post_ids'].items()}
    cases=[]
    for row in report['cases']:
        if 'error' in row:continue
        c=row['case']; queries=row['output'].get('queries',[])
        if not queries:raise ValueError('This experiment requires searched cases; record no-search cases separately')
        results=[{'query':q,'memories':raw[q]} for q in queries]
        source_labels={}
        for r in results:
            for m in r['memories']:
                for s in m.get('sources',[]):
                    key=names.get(s.get('name'))
                    # Registry/non-post sources contribute no post labels. Unknown post IDs are errors.
                    if key is None and s.get('name','').startswith('post_'):
                        raise ValueError('source post ID missing from database_state')
                    source_labels[s['id']]=events[key].get('establishes',[]) if key else []
        if c['id'] not in captures:raise ValueError(f"Missing final request capture for {c['id']}")
        capture=captures[c['id']]
        input_texts=[i['text'] for x in capture['input'] if x.get('role')=='user'
                     for i in x.get('content',[]) if isinstance(i,dict) and i.get('type')=='input_text']
        if len(input_texts)!=1:raise ValueError('expected one exact app input_text')
        text=input_texts[0]
        timestamp=json.loads(text).get('현재시각')
        if not timestamp:raise ValueError('captured question time missing')
        if question_at and timestamp!=question_at:raise ValueError('question timestamp differs from declared frozen cutoff')
        cases.append({'id':c['id'],'probe_id':c['feed_key'],'question':c['question'],
                      'question_at':timestamp,'input_text':text,'results':results,'source_labels':source_labels,
                      'gold':{k:c.get(k,[]) for k in ['required_memories','optional_memories','must_filter','reference','stale_reference']},
                      'final_request':capture})
    bundle={'schema_version':1,'synthetic':False,'cases':cases}
    validate_bundle(bundle)
    return bundle


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['report','raw-queries','manifest','database-state','captures','output']:
        p.add_argument('--'+name,required=True)
    p.add_argument('--question-at',help='Optional common cutoff; otherwise retain each captured original timestamp')
    a=p.parse_args()
    write(a.output,convert(read(a.report),read(a.raw_queries),read(a.manifest),read(a.database_state),a.question_at,read(a.captures)))
