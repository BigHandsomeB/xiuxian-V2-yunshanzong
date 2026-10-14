"""Daily offers exercise real saved time, transactional inventory and replay."""
import unittest
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from collections import Counter
from tests.systems import test_sect_management as fixtures
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from src.core.validation import ValidationError
from src.data.economy.market import settings
from src.systems.sect import market
from src.core.state.envelope import thaw_json

class DailyMarketTests(unittest.TestCase):
    setUp=fixtures.ManagementTests.setUp
    app=fixtures.ManagementTests.app
    read=fixtures.ManagementTests.read
    view=fixtures.ManagementTests.view
    fixture=fixtures.ManagementTests.fixture
    execute=fixtures.ManagementTests.execute
    settle=fixtures.ManagementTests.settle
    drain=fixtures.ManagementTests.drain

    def intent(self,row,quantity=1,name='market_buy',**changes):
        state=self.read();payload={'resource_id':row['resource_id'],'quantity':quantity,'market_day':row['market_day'],'price_milli':row['price_milli'],**changes}
        return Command(self.sid,state.generation,state.revision,str(uuid4()),name,payload)

    def test_twenty_unique_offers_stable_across_reads_and_restart(self):
        before=self.read();a=self.view()['sect_services']['market'];b=self.view()['sect_services']['market']
        self.assertEqual(a,b);self.assertEqual(before,self.read());self.assertEqual(len(a['offers']),20);self.assertEqual(len({r['resource_id'] for r in a['offers']}),20)
        self.assertNotIn('coins',{r['resource_id'] for r in a['offers']});self.assertTrue(all('pill' not in r['resource_id'] for r in a['offers']))

    def test_day_changes_only_at_120_seconds_of_saved_time(self):
        a=self.view()['sect_services']['market'];self.clock.advance(119999);self.drain();b=self.view()['sect_services']['market']
        self.assertEqual(a['day'],b['day']);self.assertEqual([(r['resource_id'],r['price_milli'],r['remaining_stock']) for r in a['offers']],[(r['resource_id'],r['price_milli'],r['remaining_stock']) for r in b['offers']])
        self.clock.advance(1);self.drain();c=self.view()['sect_services']['market'];self.assertEqual(c['day'],a['day']+1);self.assertNotEqual(a['offers'],c['offers'])

    def test_pause_and_resume_do_not_advance_shop(self):
        state=self.read();self.execute(Command(self.sid,state.generation,state.revision,str(uuid4()),'world_pause',{}));before=self.view()['sect_services']['market'];self.clock.advance(3600000)
        with self.assertRaises(ValidationError):self.drain()
        self.assertEqual(self.view()['sect_services']['market'],before)
        state=self.read();self.execute(Command(self.sid,state.generation,state.revision,str(uuid4()),'world_resume',{}));after=self.view()['sect_services']['market']
        self.assertEqual(after['day'],before['day']);self.assertEqual([(r['resource_id'],r['price_milli']) for r in after['offers']],[(r['resource_id'],r['price_milli']) for r in before['offers']])

    def test_price_range_tenths_and_higher_levels_less_likely(self):
        cfg=settings(self.r);counts=Counter();variations=set()
        for day in range(1000):
            for rid in market.offers(self.r,'fixed-market-statistical-seed',day):counts[cfg['items'][rid]['level']]+=1
            variations.add(market.price(self.r,'fixed-market-statistical-seed',day,'stone')['variation_permille'])
        size=Counter(row['level'] for row in cfg['items'].values());averages=[counts[level]/size[level] for level in range(1,7)]
        self.assertTrue(all(a>b for a,b in zip(averages,averages[1:])),averages)
        self.assertTrue(all(-200<=n<=200 for n in variations));self.assertTrue(any(n%10 for n in variations));self.assertGreater(len(variations),350)

    def test_buy_atomic_exact_price_and_idempotent_after_day_change(self):
        row=self.view()['sect_services']['market']['offers'][0];q=self.intent(row,3);before=self.read();receipt=self.execute(q);after=self.read()
        self.assertEqual(after.domains['inventory']['holdings'].get(row['resource_id'],0),before.domains['inventory']['holdings'].get(row['resource_id'],0)+3)
        self.assertEqual(before.domains['inventory']['holdings']['coins']-after.domains['inventory']['holdings']['coins'],(row['price_milli']*3+999)//1000)
        self.clock.advance(120000);self.drain();saved=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),saved)

    def test_nonoffer_forged_price_bad_quantity_and_old_endpoint_rejected(self):
        row=self.view()['sect_services']['market']['offers'][0];selected=market.offers(self.r,self.sid,market.day(self.read()));absent=next(rid for rid in settings(self.r)['items'] if rid not in selected)
        for changes in [{'resource_id':absent},{'price_milli':row['price_milli']-1},{'quantity':101},{'quantity':True},{'market_day':-1}]:
            before=self.read()
            with self.assertRaises(ValidationError):self.execute(self.intent(row,**changes))
            self.assertEqual(before,self.read())
        state=self.read();q=Command(self.sid,state.generation,state.revision,str(uuid4()),'sect_stone_buy',{'resource_id':'spirit_stone_immortal','quantity':1})
        with self.assertRaises(ValidationError):self.execute(q)
        self.assertEqual(state,self.read())

    def test_yesterday_quote_rejected_without_charge(self):
        row=self.view()['sect_services']['market']['offers'][0];self.clock.advance(120000);self.drain();before=self.read()
        with self.assertRaisesRegex(ValidationError,'新的一天'):self.execute(self.intent(row))
        self.assertEqual(before,self.read())

    def test_buy_write_failure_rolls_back_fee_and_materials(self):
        row=self.view()['sect_services']['market']['offers'][0];before=self.read()
        with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture write failure')):
            with self.assertRaises(RuntimeError):self.execute(self.intent(row))
        self.assertEqual(before,self.read())

    def test_sell_cannot_profit_from_buy_across_any_price_bounds(self):
        for row in settings(self.r)['items'].values():self.assertGreater(row['buy_coins']*800,row['sell_coins']*1200)

    def test_basic_material_sale_obeys_retention_and_batch_rounding(self):
        state=self.read();self.execute(Command(self.sid,state.generation,state.revision,str(uuid4()),'material_reserve',{'resource_id':'grain','quantity':995}))
        row=next(r for r in self.view()['sect_services']['materials'] if r['resource_id']=='grain');before=self.read()
        with self.assertRaises(ValidationError):self.execute(self.intent(row,6,'material_sell'))
        self.assertEqual(before,self.read());receipt=self.execute(self.intent(row,5,'material_sell'));after=self.read()
        self.assertEqual(after.domains['inventory']['holdings']['grain'],995)
        self.assertEqual(after.domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],5*row['price_milli']//1000)
        self.assertEqual(receipt.result['quantity'],5)

    def test_gameplay_pause_allows_market_purchase_once(self):
        row=self.view()['sect_services']['market']['offers'][0];state=self.read();self.execute(Command(self.sid,state.generation,state.revision,str(uuid4()),'world_pause',{}));before=self.read()
        q=self.intent(row);receipt=self.execute(q);after=self.read()
        self.assertEqual(after.domains['inventory']['holdings'][row['resource_id']],before.domains['inventory']['holdings'].get(row['resource_id'],0)+1)
        self.assertEqual(before.domains['inventory']['holdings']['coins']-after.domains['inventory']['holdings']['coins'],(row['price_milli']+999)//1000)
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after);self.assertEqual(after.time,before.time)

    def test_full_warehouse_and_insufficient_coins_reject_entire_buy(self):
        from src.application.sect import capacity_source
        from src.systems.inventory import holdings
        def fill(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings']['stone']+=capacity_source(s,self.r)['effective']-holdings.stock_size(stock,self.r)
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(fill);row=self.view()['sect_services']['market']['offers'][0];self.assertEqual(row['max_quantity'],0);before=self.read()
        with self.assertRaisesRegex(ValidationError,'仓库'):self.execute(self.intent(row))
        self.assertEqual(before,self.read())
        self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{k:v for k,v in s.domains['inventory']['holdings'].items() if k!='coins'}}}));before=self.read()
        with self.assertRaises(ValidationError):self.execute(self.intent(row))
        self.assertEqual(before,self.read())
