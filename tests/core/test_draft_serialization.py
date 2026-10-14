"""Owned copy-on-write branches and canonical caches retain the JSON contract."""
import json,math,unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import StateEnvelope,freeze_json,thaw_json
from src.core.state.draft import batch_scope,DraftObject
from src.core.state.serialization import canonical_json,snapshot
from src.core.validation import ValidationError
from src.core.save.codec import encode_state
from src.core.time.model import state_fingerprint

class DraftTests(unittest.TestCase):
 def test_branches_nested_updates_iteration_and_exception_preserve_old_snapshot(self):
  original=freeze_json({'rows':{'one':{'n':1}},'log':[{'n':2}]})
  with batch_scope():
   branch=thaw_json(original)
   for row in branch['rows'].values():row['n']=3
   branch['log'][0]['n']=4
   new=freeze_json(branch)
   branch['rows']['one']['n']=5
   self.assertEqual(new['rows']['one']['n'],3);self.assertEqual(new['log'][0]['n'],4)
   retry=thaw_json(new);retry['rows']['one']['n']=6
   try:raise RuntimeError('discard candidate')
   except RuntimeError:pass
   self.assertEqual(new['rows']['one']['n'],3)
  self.assertEqual(thaw_json(original),{'rows':{'one':{'n':1}},'log':[{'n':2}]})
  self.assertNotIsInstance(freeze_json(new),DraftObject)
 def test_draft_strict_validation_and_scope_unwinds_on_error(self):
  with self.assertRaises(ValidationError):
   with batch_scope():freeze_json({'bad':float('nan')})
  self.assertNotIsInstance(freeze_json({'n':1}),DraftObject)
 def test_canonical_bytes_match_json_and_snapshot_digest_used_for_persistence(self):
  values=[None,True,False,1,-5,0.0,-0.0,1.25,1e100,'凝气丹\n"\\',[{'z':3,'a':[False,None,'🙂']}],{'s':'é','n':1.2}]
  for value in values:self.assertEqual(canonical_json(value),json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False))
  s=StateEnvelope.create(content_version='test',domains={'inventory':{'n':1}},last_settled_at_ms=1000)
  with patch('src.core.state.serialization.hashlib.sha256',wraps=__import__('hashlib').sha256) as digest:
   body,h=snapshot(s);self.assertEqual(state_fingerprint(s),h);self.assertEqual(digest.call_count,1);row=encode_state(s);self.assertEqual(row[6:8],(body,h));self.assertEqual(digest.call_count,2)  # Additional, separate wall-claim checksum.
  changed=replace(s,revision=1)
  self.assertNotEqual(snapshot(changed)[1],h)
  self.assertEqual(changed.domains._json_cache,s.domains._json_cache)
 def test_mutable_external_sources_never_reuse_cached_fragments(self):
  p={'one':{'n':1}};f=freeze_json(p);first=canonical_json(f);p['one']['n']=2
  self.assertEqual(canonical_json(f),first);self.assertNotEqual(canonical_json(p),first)
