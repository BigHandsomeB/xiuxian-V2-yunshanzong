"""New grid commands through authenticated HTTP, not a mocked command list."""
import unittest
from tests.transport import test_ecology as fixtures


class HabitatHTTPTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.EcologyHTTPTests.setUpClass.__func__)
    for name in ('setUp','read','bid','request','execute','command','assign','settle','fixture','body','post'):
        locals()[name]=getattr(fixtures.EcologyHTTPTests,name)

    def test_stock_repeat_switch_and_replay(self):
        self.assign('pasture');bid=self.bid('pasture')
        q=self.body('habitat_stock',{'building_id':bid,'slot_index':2,'species_id':'pasture_species_02'})
        self.assertEqual(200,self.post(q).status_code);before=self.read()
        self.assertEqual(200,self.post(q).status_code);self.assertEqual(before,self.read())
        batch=next(iter(before.domains['ecology']['batches']))
        q=self.body('habitat_repeat',{'batch_id':batch,'enabled':False})
        self.assertEqual(200,self.post(q).status_code)
        self.assertFalse(self.read().domains['ecology']['batches'][batch]['repeat'])
        before=self.read();view=self.client.get('/api/view').json['view']
        field=next(r for r in view['ecology']['habitats'] if r['building_id']==bid)
        self.assertEqual(field['cells'][2]['batch_id'],batch);self.assertEqual(before,self.read())

    def test_garden_repeat_and_invalid_payload_are_atomic(self):
        self.assign('garden');bid=self.bid('garden')
        self.assertEqual(200,self.post(self.body('garden_reclaim',{'building_id':bid,'plot_index':0})).status_code)
        self.assertEqual(200,self.post(self.body('garden_plant',{'building_id':bid,'plot_index':0,'recipe_id':'herb','repeat':True})).status_code)
        self.assertEqual(200,self.post(self.body('garden_repeat',{'building_id':bid,'plot_index':0,'enabled':False})).status_code)
        before=self.read();q=self.body('garden_repeat',{'building_id':bid,'plot_index':0,'enabled':'false'})
        self.assertEqual(422,self.post(q).status_code);self.assertEqual(before,self.read())
