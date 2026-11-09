import ast
import copy
import json
import random
import unittest
from unittest.mock import patch
from pathlib import Path
import budget_lab as lab
from replay_answers import build_request


def memory(i, kind='fact', source=None, fact=None):
    sid=source or 's'+str(i)
    mid=sid if kind=='episode' else 'f'+str(i)
    return {'id':mid,'fact':fact or f'fact {i}','valid_at':None,'invalid_at':None,
            'source_episode_ids':[sid], 'sources':[{'id':sid,'name':'post_'+str(i),
            'text':fact or f'fact {i}','recorded_at':'2026-10-15T00:00:00+09:00'}]}


def fixture():
    old=[memory(i,source='old',fact=f'과거 화분 관련 사실 {i}') for i in range(5)]
    new=memory(6,'episode',source='new',fact='방울토마토 화분을 창가 안쪽으로 옮겼어요.')
    c={'id':'synthetic-tomato','question':'방울토마토 화분은 지금 어디에 있나요?',
       'question_at':'2026-10-17T12:00:00+09:00',
       'input_text':json.dumps({'질문':'방울토마토 화분은 지금 어디에 있나요?',
                                '현재시각':'2026-10-17T12:00:00+09:00'},ensure_ascii=False),
       'results':[{'query':'방울토마토 화분 위치 변경','memories':old+[new]}],
       'source_labels':{'old':['OLD'],'new':['CURRENT']},
       'gold':{'required_memories':['CURRENT'],'must_filter':['OLD']}}
    c['final_request']={'instructions':'TEST ONLY: frozen answer instructions','tool_choice':'none','tools':[],
        'input':[{'role':'user','content':[{'type':'input_text','text':c['input_text']}]},
                 {'type':'function_call','name':'search_family_memory','arguments':json.dumps({'query':c['results'][0]['query']}),'call_id':'call1'},
                 {'type':'function_call_output','call_id':'call1','output':'{}'}]}
    return {'schema_version':1,'synthetic':True,'cases':[c]}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.net=patch('socket.socket.connect',side_effect=AssertionError('Network forbidden in offline tests'))
        self.net.start();self.addCleanup(self.net.stop)

    def test_baseline_matches_app_randomized(self):
        tree=ast.parse((lab.ROOT/'frozen/app_post_flow.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='select_budget')
        fn.args.defaults=[ast.Constant(5)]
        module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
        ns={};exec(compile(module,'frozen select_budget','exec'),ns)
        rng=random.Random(72)
        for _ in range(150):
            results=[{'query':str(q),'memories':[memory(rng.randrange(12)) for _ in range(rng.randrange(12))]}
                     for q in range(rng.randrange(1,6))]
            for limit in [1,3,5,9]:
                expected={m['id'] for r in ns['select_budget'](results,limit) for m in r['memories']}
                self.assertEqual(expected,{m['id'] for m in lab.baseline(results,limit)})

    def test_episode_survives_interleave(self):
        c=fixture()['cases'][0]
        self.assertNotIn('new',[m['id'] for m in lab.baseline(c['results'])])
        self.assertIn('new',[m['id'] for m in lab.interleave(c['results'])])

    def test_different_facts_same_source_not_destroyed(self):
        items=[memory(1,source='same',fact='A'),memory(2,source='same',fact='B')]
        self.assertEqual(len(lab.interleave([{'memories':items}],5)),2)

    def test_exact_duplicates_removed(self):
        items=[memory(1,source='same',fact='A'),memory(2,source='same',fact='A')]
        self.assertEqual(len(lab.interleave([{'memories':items}],5)),1)

    def test_no_source_and_empty_results(self):
        m=memory(1);m['sources']=[]
        self.assertEqual(lab.interleave([{'memories':[m]}]),[m])
        self.assertEqual(lab.interleave([]),[])

    def test_no_mutation(self):
        c=fixture()['cases'][0];before=copy.deepcopy(c)
        lab.baseline(c['results']);lab.interleave(c['results']);lab.rank_request(c)
        self.assertEqual(c,before)

    def test_zero_limit(self):
        for fn in [lab.baseline,lab.interleave]:
            with self.assertRaises(ValueError):fn([],0)

    def test_gold_not_in_reranker_or_key(self):
        c=fixture()['cases'][0];key=lab.rank_key(c,{})
        c['gold']={'required_memories':['SECRET_GOLD']};c['source_labels']={'new':['SECRET_GOLD']}
        self.assertNotIn('SECRET_GOLD',json.dumps(lab.rank_request(c)))
        self.assertEqual(key,lab.rank_key(c,{}))

    def test_cache_sensitive_to_inputs_and_settings(self):
        c=fixture()['cases'][0];key=lab.rank_key(c,{})
        self.assertNotEqual(key,lab.rank_key(c,{'model':'changed'}))
        c['question']='다른 질문';self.assertNotEqual(key,lab.rank_key(c,{}))

    def test_unknown_duplicate_missing_ids_rejected(self):
        pool=[memory(1),memory(2)]
        for order in [['f1'],['f1','f1'],['f1','fake']]:
            with self.assertRaises(ValueError):lab.validate_ranking(order,pool)

    def test_no_silent_reranker_fallback(self):
        result=lab.compare(fixture(),{},lab.read(lab.ROOT/'config.json'))
        self.assertEqual(result['rows'][2]['status'],'missing_rank_cache')

    def test_future_sources_rejected(self):
        b=fixture();b['cases'][0]['results'][0]['memories'][0]['sources'][0]['recorded_at']='2027-01-01T00:00:00+09:00'
        with self.assertRaises(ValueError):lab.validate_bundle(b)

    def test_conflicting_ids_rejected(self):
        b=fixture();m=copy.deepcopy(b['cases'][0]['results'][0]['memories'][0]);m['fact']='different'
        b['cases'][0]['results'][0]['memories'].append(m)
        with self.assertRaises(ValueError):lab.validate_bundle(b)

    def test_api_gate_before_sdk_import(self):
        with patch.dict('sys.modules',{'openai':None}):
            with self.assertRaisesRegex(RuntimeError,'Paid calls disabled'):lab.paid_client(False)

    def test_replay_keeps_original_input_and_changes_only_tools(self):
        c=fixture()['cases'][0];before=copy.deepcopy(c['final_request'])
        r=build_request(c,lab.interleave(c['results']),{})
        self.assertEqual(r['input'][:2],before['input'][:2])
        self.assertEqual(c['final_request'],before)
        self.assertIn('창가 안쪽',r['input'][2]['output'])

    def test_capture_required_and_call_id_checked(self):
        c=fixture()['cases'][0];del c['final_request']
        with self.assertRaises(ValueError):build_request(c,[],{})
        c=fixture()['cases'][0];c['final_request']['input'][2]['call_id']='bad'
        with self.assertRaises(ValueError):build_request(c,[],{})

    def test_summary_does_not_invent_accuracy(self):
        from summarize import summarize
        result=summarize(lab.compare(fixture(),{},lab.read(lab.ROOT/'config.json')))
        self.assertIsNone(result['modes']['baseline']['correct_rate_among_graded'])
        self.assertEqual(result['modes']['baseline']['answer_attempts'],0)

    def test_duplicate_cases_rejected(self):
        b=fixture();b['cases'].append(copy.deepcopy(b['cases'][0]))
        with self.assertRaises(ValueError):lab.validate_bundle(b)

    def test_capture_hook_restores_app_and_does_not_change_result(self):
        import asyncio, tempfile, types
        from capture_hook import capture_case
        class FakeClient:
            def __init__(self,*args,**kwargs):
                async def create(**request):return 'same response'
                self.responses=types.SimpleNamespace(create=create)
        select=lambda results: 'same selection'
        module=types.ModuleType('integrations.ai.post_flow')
        module.select_budget=select;module.AsyncOpenAI=FakeClient
        ai=types.ModuleType('integrations.ai');ai.post_flow=module
        parent=types.ModuleType('integrations');parent.ai=ai
        with tempfile.TemporaryDirectory(dir=lab.ROOT/'outputs') as folder:
            with patch.dict('sys.modules',{'integrations':parent,'integrations.ai':ai,'integrations.ai.post_flow':module}):
                with capture_case('case',folder):
                    self.assertEqual(module.select_budget([]),'same selection')
                    response=asyncio.run(module.AsyncOpenAI().responses.create(tool_choice='none',input=[],instructions='frozen'))
                    self.assertEqual(response,'same response')
                self.assertIs(module.select_budget,select)
                self.assertIs(module.AsyncOpenAI,FakeClient)
                captured=lab.read(next(Path(folder).glob('*.json')))
                self.assertEqual(captured['final_request']['instructions'],'frozen')

    def test_importer_uses_captured_timestamp_and_post_mapping(self):
        from import_team_bundle import convert
        c=fixture()['cases'][0]
        c['results'][0]['memories']=[memory(6,'episode',source='new',fact='new location')]
        raw={c['results'][0]['query']:c['results'][0]['memories']}
        case={'id':c['id'],'feed_key':'probe','question':c['question'],'required_memories':['CURRENT']}
        report={'cases':[{'case':case,'output':{'queries':[c['results'][0]['query']]}}]}
        result=convert(report,raw,{'events':[{'feed_key':'update','establishes':['CURRENT']}]},
                       {'post_ids':{'update':6}},None,{c['id']:c['final_request']})
        self.assertEqual(result['cases'][0]['source_labels']['new'],['CURRENT'])
        self.assertEqual(result['cases'][0]['question_at'],c['question_at'])


if __name__=='__main__':unittest.main()
