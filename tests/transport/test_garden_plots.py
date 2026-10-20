"""Authenticated plot commands use the existing transport/receipt protocol."""
import unittest
from tests.transport import test_ecology as fixtures


class GardenHTTPTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EcologyHTTPTests.setUpClass.__func__)
    for name in ('setUp', 'read', 'bid', 'request', 'execute', 'command', 'assign', 'settle', 'fixture', 'body', 'post'):
        locals()[name] = getattr(fixtures.EcologyHTTPTests, name)

    def test_reclaim_plant_replay_and_stale_revision(self):
        bid = self.bid('garden'); self.assign('garden')
        payload = {'building_id': bid, 'plot_index': 0}
        q = self.body('garden_reclaim', payload)
        self.assertEqual(200, self.post(q).status_code)
        before = self.read(); self.assertEqual(200, self.post(q).status_code); self.assertEqual(before, self.read())
        plant = self.body('garden_plant', {**payload, 'recipe_id': 'herb'})
        self.assertEqual(200, self.post(plant).status_code)
        planted = self.read(); self.assertEqual(200, self.post(plant).status_code); self.assertEqual(planted, self.read())
        stale = self.body('garden_reclaim', {'building_id': bid, 'plot_index': 1})
        stale['expected_revision'] -= 1
        self.assertEqual(409, self.post(stale).status_code); self.assertEqual(planted, self.read())
        view = self.client.get('/api/view').json['view']
        self.assertEqual('GROWING', view['ecology']['gardens'][0]['plots'][0]['state'])
        self.assertEqual(planted, self.read())

    def test_csrf_locked_slot_and_world_pause_do_not_change_save(self):
        q = self.body('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': 999})
        before = self.read(); self.assertEqual(422, self.post(q).status_code); self.assertEqual(before, self.read())
        q = self.body('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': 0})
        self.assertEqual(403, self.client.post('/api/command', json=q).status_code); self.assertEqual(before, self.read())
        self.command('world_pause', {}); before = self.read()
        q = self.body('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': 0})
        self.assertEqual(422, self.post(q).status_code); self.assertEqual(before, self.read())
