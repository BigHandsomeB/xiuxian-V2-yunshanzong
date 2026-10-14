"""New recruit fees, atomic replay and already-funded legacy orders."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.systems.sect import management
from tests.systems import test_sect_management as fixtures

class GateRecruitmentTests(unittest.TestCase):
    setUp=fixtures.ManagementTests.setUp
    app=fixtures.ManagementTests.app
    read=fixtures.ManagementTests.read
    view=fixtures.ManagementTests.view
    fixture=fixtures.ManagementTests.fixture
    q=fixtures.ManagementTests.q
    execute=fixtures.ManagementTests.execute
    cmd=fixtures.ManagementTests.cmd
    settle=fixtures.ManagementTests.settle
    drain=fixtures.ManagementTests.drain

    def test_exact_stone_fee_no_grain_and_replay(self):
        before=self.read();q=self.q('sect_recruit',{'count':2});receipt=self.execute(q);started=self.read()
        a=before.domains['inventory']['holdings'];b=started.domains['inventory']['holdings']
        self.assertEqual(b['coins'],a['coins']-240);self.assertEqual(b['spirit_stone_low'],a['spirit_stone_low']-12);self.assertEqual(b['grain'],a['grain'])
        self.assertEqual(dict(self.view()['sect_services']['housing']['recruit_cost']),{'coins':120,'spirit_stone_low':6})
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),started)
        order=started.domains['sect_management']['recruit'];self.clock.advance(order['due_ms']-order['started_ms']);self.drain()
        self.assertEqual(sum(g['count'] for g in self.read().domains['disciples']['groups'].values()),sum(g['count'] for g in before.domains['disciples']['groups'].values())+2)
        self.assertIsNone(self.read().domains['sect_management']['recruit'])

    def test_grain_cannot_substitute_for_missing_stones(self):
        def scarce(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings']['spirit_stone_low']=5
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(scarce);before=self.read()
        with self.assertRaises(ValidationError):self.cmd('sect_recruit',{'count':1})
        self.assertEqual(self.read(),before)

    def test_old_grain_funded_order_finishes_without_new_charge(self):
        # Build one historical order with its original fees, then load new rules.
        original=thaw_json(management.config(self.r));legacy={**original,'recruit_cost':{'coins':120,'grain':6}}
        before=self.read()
        with patch.object(management,'config',return_value=legacy):
            q=self.q('sect_recruit',{'count':1});receipt=self.execute(q)
        started=self.read();self.assertEqual(started.domains['inventory']['holdings']['grain'],before.domains['inventory']['holdings']['grain']-6)
        self.assertEqual(started.domains['inventory']['holdings']['spirit_stone_low'],before.domains['inventory']['holdings']['spirit_stone_low'])
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),started)
        order=started.domains['sect_management']['recruit'];self.clock.advance(order['due_ms']-order['started_ms']);self.drain()
        self.assertEqual(self.read().domains['inventory']['holdings']['spirit_stone_low'],started.domains['inventory']['holdings']['spirit_stone_low'])
        self.assertEqual(sum(g['count'] for g in self.read().domains['disciples']['groups'].values()),sum(g['count'] for g in before.domains['disciples']['groups'].values())+1)
