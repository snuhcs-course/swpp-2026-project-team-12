"""Summarize selection and optional answer/review artifacts without API access."""
import argparse
import json
import statistics
from pathlib import Path
from budget_lab import read,write,MODES


def mean(xs):
    xs=[x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def summarize(comparison, answers=(), reviews=()):
    result={'synthetic':comparison['synthetic'],'modes':{},
            'limits':['Recall is label/source coverage, not semantic evidence sufficiency.',
                      'Replay excludes query planning, retrieval and graph construction.',
                      'Local selection duration is not user response latency.',
                      'Reranker call costs are separate; do not treat cached ranking as free production inference.']}
    for mode in MODES:
        selected=[r for r in comparison['rows'] if r['mode']==mode and r['status']=='selected']
        aa=[a for a in answers if a['mode']==mode]
        rr=[r for r in reviews if r['mode']==mode]
        for rows in [aa,rr]:
            ids=[(r['case_id'],r['repeat']) for r in rows]
            if len(ids)!=len(set(ids)):raise ValueError('duplicate case/repeat; use a separate output per run')
        usage=[a['usage'] for a in aa if a.get('usage')]
        ranks=[s['reranker_call'] for s in selected if s.get('reranker_call')]
        result['modes'][mode]={
            'selected_cases':len(selected),
            'required_recall':mean([s['metrics']['required_recall'] for s in selected]),
            'context_utf8_bytes_mean':mean([s['metrics']['context_utf8_bytes'] for s in selected]),
            'answer_attempts':len(aa),'completed_answers':sum(a['status']=='completed' for a in aa),
            'answer_seconds_mean':mean([a['answer_seconds'] for a in aa]),
            'answer_input_tokens_mean':mean([u['input_tokens'] for u in usage]),
            'answer_output_tokens_mean':mean([u['output_tokens'] for u in usage]),
            'answer_total_tokens_mean':mean([u['input_tokens']+u['output_tokens'] for u in usage]),
            'reranker_seconds_mean_per_case':mean([r['seconds'] for r in ranks]),
            'reranker_total_tokens_mean_per_case':mean([r['usage']['input_tokens']+r['usage']['output_tokens'] for r in ranks if r.get('usage')]),
            'graded_answers':sum(type(r.get('correct')) is bool for r in rr),
            'correct_rate_among_graded':mean([r['correct'] for r in rr if type(r.get('correct')) is bool]),
            'stale_or_invented_rate_among_graded':mean([not r['no_stale_or_invented'] for r in rr if type(r.get('no_stale_or_invented')) is bool]),
            'evidence_sufficient_rate_among_graded':mean([r['evidence_sufficient'] for r in rr if type(r.get('evidence_sufficient')) is bool])}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--comparison',required=True);p.add_argument('--answers');p.add_argument('--reviews');p.add_argument('--output',required=True)
    a=p.parse_args()
    answers=[json.loads(s) for s in Path(a.answers).read_text().splitlines()] if a.answers else []
    write(a.output,summarize(read(a.comparison),answers,read(a.reviews) if a.reviews else []))
