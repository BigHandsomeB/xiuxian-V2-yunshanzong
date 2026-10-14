"""Atomic nonstacking Equipment/evaluation/trade invariants, isolated fixtures only."""
from unittest.mock import patch
from dataclasses import replace
from src.core.save.sqlite import SQLiteSave
from src.core.save.codec import PersistenceError,StoredReceipt
from src.core.validation import ValidationError,NotFoundError
from src.core.state.envelope import thaw_json
from src.systems.equipment import items
from src.application import equipment as equip
from src.data.registry import DefinitionKey
from src.data.economy.definitions import EquipmentDefinition
from tests.systems.test_economy import EconomyFixture
import unittest

class EquipmentFixture(EconomyFixture):
 def supplies(self):self.command('inventory_grant',{'amounts':{'coins':200,'ore':90,'wood':10}})
 def forge(self):
  self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000);self.finish_pending();return next(iter(self.state().domains['equipment']['instances']))
 def policy(self,mode='SELL',upgrade=True):return self.command('automation_equipment',{'policy':{'mode':mode,'min_quality':'rare','keep_stat':'attack_milli','min_stat':100000,'keep_upgrades':upgrade}})

class EquipmentTests(EquipmentFixture,unittest.TestCase):
 def test_definition_validation(self):
  d=items.definition(self.registry,'basic_left');self.assertEqual(dict(d.stats),{'attack_milli':4000})
  with self.assertRaises(ValidationError):replace(d,stats=(('attack_milli',-1),))
  with self.assertRaises(ValidationError):replace(d,sell_coins=0)
 def test_forge_cost_time_unique_output(self):
  i=self.forge();s=self.state();self.assertEqual(s.domains['inventory']['holdings']['coins'],180);self.assertEqual(s.domains['inventory']['holdings']['ore'],81);self.assertEqual(s.domains['inventory']['holdings']['wood'],9);self.assertEqual(s.domains['equipment']['instances'][i]['definition_id'],'basic_left');self.assertNotIn('basic_left',s.domains['inventory']['holdings']);self.assertEqual(s.domains['production']['jobs'][self.building('forge')]['status'],'COMPLETE')
 def test_repeated_completion_no_extra_instance(self):
  i=self.forge();before=self.state().domains['equipment'];self.settle();self.assertEqual(self.state().domains['equipment'],before)
 def test_two_instances_not_stacked(self):
  i=self.forge();self.start('forge_sword','forge');self.clock.advance(120000);self.finish_pending();rows=self.state().domains['equipment']['instances'];self.assertEqual(len(rows),2);self.assertEqual(len(set(rows)),2)
 def test_equip_and_unequip_projection(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});self.assertEqual(self.view()['cultivation']['combat_projection']['attack'],14);self.command('equipment_unequip',{'instance_id':i});self.assertEqual(self.view()['cultivation']['combat_projection']['attack'],10)
 def test_new_combat_equipment_projection_damage(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id'];self.assertEqual(self.view()['combat']['player']['attack'],14);self.command('combat_attack',{'battle_id':bid});self.assertEqual(self.view()['combat']['enemy']['hp'],21)
 def test_active_battle_prevents_hot_swap(self):
  i=self.forge();bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id'];before=self.state()
  with self.assertRaises(ValidationError):self.command('equipment_equip',{'instance_id':i})
  self.assertEqual(self.state(),before);self.assertEqual(self.view()['combat']['player']['attack'],10)
 def test_snapshot_survives_unequip_after_abandon(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id'];self.command('combat_abandon',{'battle_id':bid});self.command('equipment_unequip',{'instance_id':i});self.assertEqual(self.view()['combat']['player']['attack'],14);self.assertEqual(self.view()['cultivation']['combat_projection']['attack'],10)
 def test_equip_lock_favorite_protection(self):
  for key in ('equipment_equip','equipment_lock','equipment_favorite'):
   i=self.forge() if key=='equipment_equip' else next(iter(self.state().domains['equipment']['instances']))
   if key!='equipment_equip':self.command('equipment_unequip',{'instance_id':i}) if self.state().domains['equipment']['instances'][i]['equipped'] else None
   self.command(key,{'instance_id':i} if key=='equipment_equip' else {'instance_id':i,'value':True})
   for action in ('equipment_sell','equipment_salvage'):
    with self.assertRaises(ValidationError):self.command(action,{'instance_id':i})
   self.assertIn(i,self.state().domains['equipment']['instances'])
 def test_sell_real_coins_once(self):
  i=self.forge();q=self.q('equipment_sell',{'instance_id':i});r=self.execute(q);before=self.state();self.assertEqual(self.execute(q),r);self.assertEqual(self.state(),before);self.assertNotIn(i,before.domains['equipment']['instances']);self.assertEqual(before.domains['inventory']['holdings']['coins'],205)
 def test_sell_then_salvage_cannot_double_consume(self):
  i=self.forge();self.command('equipment_sell',{'instance_id':i});before=self.state()
  with self.assertRaises(NotFoundError):self.command('equipment_salvage',{'instance_id':i})
  self.assertEqual(self.state(),before)
 def test_salvage_real_v1_materials_once(self):
  i=self.forge();q=self.q('equipment_salvage',{'instance_id':i});r=self.execute(q);self.assertEqual(self.execute(q),r);stock=self.state().domains['inventory']['holdings'];self.assertEqual((stock['coins'],stock['ingot']),(187,1))
 def test_sell_failure_rolls_back_item_coins_receipt(self):
  i=self.forge();q=self.q('equipment_sell',{'instance_id':i});before=self.state();original=SQLiteSave.commit
  def fail(store,*args):original(store,*args);raise PersistenceError('isolated failure')
  with patch.object(SQLiteSave,'commit',fail):
   with self.assertRaises(PersistenceError):self.execute(q)
  self.assertEqual(self.state(),before)
  with self.application() as a:self.assertIsNone(a.store.receipt(self.save,before.generation,q.request_id))
  self.execute(q);self.assertEqual(self.state().domains['inventory']['holdings']['coins'],205)
 def test_salvage_inventory_failure_keeps_equipment(self):
  i=self.forge();before=self.state()
  with patch('src.application.equipment.operations.grant',side_effect=ValidationError('isolated inventory failure')):
   with self.assertRaises(ValidationError):self.command('equipment_salvage',{'instance_id':i})
  self.assertEqual(self.state(),before)
 def test_forge_completion_failure_keeps_job_and_materials_snapshot(self):
  self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000);before=self.state()
  with patch('src.application.equipment.items.add',side_effect=ValidationError('isolated output failure')):
   with self.assertRaises(ValidationError):self.settle()
  self.assertEqual(self.state(),before);self.finish_pending();self.assertEqual(len(self.state().domains['equipment']['instances']),1)
 def test_policy_edit_not_retroactive(self):
  i=self.forge();self.policy(upgrade=False);self.settle();self.assertIn(i,self.state().domains['equipment']['instances']);self.assertEqual(self.state().domains['equipment']['instances'][i]['evaluation'],'NONE')
 def test_auto_sell_only_new_and_keeps_upgrades(self):
  self.policy();i=self.forge();self.assertIn(i,self.state().domains['equipment']['instances']);self.assertEqual(self.state().domains['equipment']['instances'][i]['evaluation'],'KEEP');self.command('equipment_equip',{'instance_id':i});self.start('forge_sword','forge');self.clock.advance(120000);self.finish_pending();state=self.state();job=state.domains['production']['jobs'][self.building('forge')];d=items.definition(self.registry,state.domains['equipment']['instances'][i]['definition_id']);candidate={'stats':dict(d.stats),'affixes':items.rolled_affixes(d,job['job_id'])};current=items.effective_stats(state.domains['equipment']['instances'][i]);upgrade=any(n>current.get(k,0) for k,n in items.effective_stats(candidate).items());self.assertEqual(len(state.domains['equipment']['instances']),2 if upgrade else 1);self.assertEqual(state.domains['inventory']['holdings']['coins'],160 if upgrade else 185)
 def test_auto_sell_failure_retains_review(self):
  self.policy(upgrade=False);self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000)
  with patch('src.application.equipment.process',side_effect=ValidationError('isolated sale unavailable')):self.finish_pending()
  row=next(iter(self.state().domains['equipment']['instances'].values()));self.assertEqual(row['evaluation'],'REVIEW');self.assertEqual(self.state().domains['inventory']['holdings']['coins'],180)
 def test_unknown_affixes_and_attributes_review(self):
  i=self.forge();p=thaw_json(self.state().domains['equipment']);p['instances'][i]['affixes']=[{'kind':'unknown_rare','value':99}];rules={**self.state().domains['automation']['equipment'],'mode':'SELL','keep_upgrades':False};self.assertEqual(items.evaluate(p,self.registry,i,rules),'REVIEW')
  with self.assertRaises(ValidationError):items.remove(p,self.registry,i)
 def test_default_off_and_preview_pure(self):
  i=self.forge();before=self.state();self.assertEqual(self.view()['equipment']['policy']['mode'],'OFF');self.assertEqual(self.view()['equipment']['instances'][0]['evaluation'],'KEEP');self.assertEqual(self.state(),before)
 def test_pause_blocks_all_equipment_mutations(self):
  i=self.forge();self.command('world_pause');before=self.state()
  for name,payload in [('equipment_sell',{'instance_id':i}),('equipment_salvage',{'instance_id':i}),('equipment_equip',{'instance_id':i}),('equipment_lock',{'instance_id':i,'value':True})]:
   with self.assertRaises(ValidationError):self.command(name,payload)
  self.assertEqual(self.state(),before)
 def test_personal_equipment_does_not_count_warehouse_capacity(self):
  i=self.forge();self.assertEqual(self.view()['capacity']['used'],sum(n for k,n in self.state().domains['inventory']['holdings'].items() if self.registry.lookup(DefinitionKey('resources',k)).warehouse_counted))

 def test_auto_salvage_real_recipe(self):
  self.policy('SALVAGE',upgrade=False);self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000);self.finish_pending();self.assertFalse(self.state().domains['equipment']['instances']);self.assertEqual(self.state().domains['inventory']['holdings']['coins'],187);self.assertEqual(self.state().domains['inventory']['holdings']['ingot'],1)
 def test_epoch_edit_turns_pending_old_disposal_to_review(self):
  self.policy(upgrade=False);self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000)
  with patch('src.application.economy_settlement.equip.automate',side_effect=lambda s,r:s):self.finish_pending()
  i=next(iter(self.state().domains['equipment']['instances']));self.policy('SELL',upgrade=False);self.settle();self.assertIn(i,self.state().domains['equipment']['instances']);self.assertEqual(self.state().domains['equipment']['instances'][i]['evaluation'],'REVIEW')
 def test_salvage_full_bag_safely_keeps_item(self):
  from src.systems.inventory import holdings
  i=self.forge();capacity=self.view()['capacity']['effective'];used=holdings.stock_size(self.state().domains['inventory'],self.registry);self.command('inventory_grant',{'amounts':{'herb':capacity-used}});before=self.state()
  with self.assertRaises(ValidationError):self.command('equipment_salvage',{'instance_id':i})
  self.assertEqual(self.state(),before)
 def test_quality_and_real_stat_retention(self):
  i=self.forge();p=self.state().domains['equipment'];rules={**self.state().domains['automation']['equipment'],'mode':'SELL','keep_upgrades':False,'min_quality':'white'};self.assertEqual(items.evaluate(p,self.registry,i,rules),'KEEP');rules={**rules,'min_quality':'rare','min_stat':4000};self.assertEqual(items.evaluate(p,self.registry,i,rules),'KEEP')

 def test_automatic_disposition_durable_audit(self):
  self.policy('SELL',upgrade=False);self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000);self.finish_pending();audit=self.state().domains['equipment']['audit'];self.assertEqual(len(audit),1);self.assertEqual(audit[0]['amounts'],{'coins':25});self.assertEqual(audit[0]['action'],'SELL');self.assertTrue(audit[0]['instance_id']);self.settle();self.assertEqual(self.state().domains['equipment']['audit'],audit)
 def test_disposition_audit_budget_protects_item(self):
  self.policy('SELL',upgrade=False);self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');self.clock.advance(120000)
  with patch('src.application.equipment.items.AUDIT_LIMIT',0):self.finish_pending()
  row=next(iter(self.state().domains['equipment']['instances'].values()));self.assertEqual(row['evaluation'],'REVIEW');self.assertEqual(self.state().domains['inventory']['holdings']['coins'],180)

 def test_breakthrough_preview_includes_same_equipment_projection(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});v=self.view()['cultivation'];self.assertEqual(v['combat_projection']['attack'],14);self.assertEqual(v['next_realm_preview'],{'max_hp':210,'attack':30,'armor':1});self.command('equipment_unequip',{'instance_id':i});self.assertEqual(self.view()['cultivation']['next_realm_preview']['attack'],26)
