"""Recompute published metrics from saved answers and grades. Standard library only."""
import ast,lzma,hashlib,importlib.util,json,math,statistics,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parent

def read(p):return json.loads(p.read_text())
def archive(name):return json.loads(lzma.decompress((ROOT/name/'recorded.json.xz').read_bytes()))
def j(d,k):return json.loads(d[k])
def lines(d,k):return [json.loads(x) for x in d[k].splitlines()]
def mean(v):return statistics.mean(v)
def equal(x,y):
 if isinstance(x,float) or isinstance(y,float):assert math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-10),(x,y)
 else:assert x==y,(x,y)
def family():
 d=archive('family_history');cases=read(ROOT/'family_history/cases.json');byid={c['id']:c for c in cases}
 grades={r['id']:r for r in j(d,'full_grades.json')};result={}
 assert len(grades)==540 and len(byid)==30
 for n in [100,200,300]:
  rows=lines(d,f'history_{n}/full.jsonl');assert len(rows)==180 and len({r['id'] for r in rows})==180
  for m in ['full_history','graphiti']:
   rr=[r for r in rows if r['mode']==m];assert len(rr)==90
   assert Counter(r['case_id'] for r in rr)=={k:3 for k in byid}
   assert all(r['status']=='complete' and r['id'] in grades for r in rr)
   answerable=[r for r in rr if byid[r['case_id']]['answerability']=='answerable'];assert len(answerable)==78
   metrics={'tasks':90,'correct':sum(grades[r['id']]['correct'] for r in rr),'accuracy':mean(grades[r['id']]['correct'] for r in rr),
    'retrieval_evidence_recall':mean(r['retrieval_evidence_recall'] for r in answerable),
    'semantic_citation_sufficiency':mean(grades[r['id']]['citation_sufficient'] for r in answerable),
    'generation_tokens':mean(r['usage']['observed_generation_tokens'] for r in rr),'mean_seconds':mean(r['online_seconds'] for r in rr)}
   for k,v in metrics.items():equal(v,j(d,'full_metrics.json')[f'{n}_{m}'][k])
   result[f'{n}_{m}']=metrics
 return result

def post_qa():
 d=archive('post_qa');base='full300_once/';new='separate_budget_855cd61_100/'
 sys.path.insert(0,str(ROOT/'post_qa'));import budget_lab as lab
 bundle=j(d,'selection_inputs.json');lab.validate_bundle(bundle);cases={c['id']:c for c in bundle['cases']}
 assert len(cases)==100
 selections={(r['case_id'],r['mode']):r for r in j(d,base+'selection_comparison.json')['rows']}
 selections.update({(r['case_id'],r['mode']):r for r in j(d,new+'selection_comparison.json')['rows']})
 answers={(r['case_id'],r['mode']):r for r in lines(d,base+'answers.jsonl')};answers.update({(r['case_id'],r['mode']):r for r in lines(d,new+'answers.jsonl')})
 grades={(r['case_id'],r['mode']):r for r in lines(d,base+'grades.jsonl')};grades.update({(r['case_id'],r['mode']):r for r in lines(d,new+'grades.jsonl')})
 path=ROOT/'post_qa/candidate_selectors/post_flow_855cd61.py';tree=ast.parse(path.read_text())
 spec=importlib.util.spec_from_file_location('pinned_prompts',path.with_name('prompts_855cd61.py'));prompts=importlib.util.module_from_spec(spec);spec.loader.exec_module(prompts)
 ns={'prompts':prompts};exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='select_budget'],type_ignores=[]),str(path),'exec'),ns)
 result={};expected=read(ROOT/'post_qa/reports/separate_budget_855cd61_100/results.json')['summary']
 for mode in ['baseline','interleave','separate_5_5']:
  for cid,c in cases.items():
   selected=([m for r in ns['select_budget'](c['results']) for m in r['memories']] if mode=='separate_5_5' else getattr(lab,mode)(c['results'],5))
   assert selected==selections[cid,mode]['selected'],(cid,mode)
   assert lab.selection_metrics(c,selected)==selections[cid,mode]['metrics']
  aa=[answers[c,mode] for c in cases];gg=[grades[c,mode] for c in cases]
  metrics={'correct':sum(g['verdicts']['correct']['pass'] for g in gg),
    'required_recall_mean':mean(selections[c,mode]['metrics']['required_recall'] for c in cases),
    'total_tokens_mean':mean(a['usage']['total_tokens'] for a in aa),'answer_seconds_mean':mean(a['answer_seconds'] for a in aa)}
  for k,v in metrics.items():equal(v,expected[mode][k])
  result[mode]=metrics
 # Prompt-only comparison: 54 -> 54, paired 5 gains and 5 losses.
 candidate={r['case_id']:r for r in lines(d,'qa_interleave_v2_100/grades.jsonl')};assert len(candidate)==100
 expected_prompt=read(ROOT/'post_qa/reports/qa_interleave_v2_100/results.json')
 correct=sum(x['verdicts']['correct']['pass'] for x in candidate.values());equal(correct,expected_prompt['summary']['B']['correct'])
 result['prompt_candidate_correct']=correct
 return result

def verify_package():
 for name,h in read(ROOT/'package_manifest.json').items():
  p=ROOT/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==h,name
 return True
if __name__=='__main__':
 verify_package();result={'passed':True,'family_history':family(),'post_qa':post_qa(),'api_calls':0,'database_writes':0}
 (ROOT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2))
