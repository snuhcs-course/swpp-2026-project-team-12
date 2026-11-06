import unittest,json
from datetime import datetime
from collections import Counter
from run import ROOT,LEGACY,CASES,read,recall,verify_inputs
class ContractTests(unittest.TestCase):
 def test_panel_distribution(self):
  self.assertEqual(Counter(c['category'] for c in CASES),{'single_fact':8,'update_correction':8,'entity_disambiguation':6,'multi_record':4,'unanswerable':4})
  self.assertEqual(len({c['id'] for c in CASES}),30)
 def test_nested_time_safe_sources(self):
  previous={}
  for size in [100,200,300]:
   posts={p['post_key']:p for p in read(LEGACY/f'datasets/history_{size}/memory_posts.json')}
   self.assertEqual(len(posts),size)
   for k,p in previous.items():self.assertEqual(posts[k],p)
   for c in CASES:
    for s in c['evidence_sets']:
     self.assertTrue(all(k in posts for k in s))
    self.assertTrue(all(datetime.fromisoformat(p['created_at'])<datetime.fromisoformat(c['asked_at']) for p in posts.values()))
   previous=posts
 def test_alternative_sets_not_union_denominator(self):
  c={'evidence_sets':[['A','B'],['C']]}
  self.assertEqual(recall(c,['A']),.5)
  self.assertEqual(recall(c,['C']),1)
  self.assertEqual(recall(c,[]),0)
  self.assertIsNone(recall({'evidence_sets':[]},[]))
 def test_no_post_or_viewer_runtime_dependency(self):
  for c in CASES:
   self.assertNotIn('current_post_key',c);self.assertNotIn('viewer_key',c)
   self.assertNotIn('사진 속',c['question']);self.assertNotIn('아빠',c['question'])
 def test_sources_and_app_unchanged(self):verify_inputs()
if __name__=='__main__':unittest.main()
