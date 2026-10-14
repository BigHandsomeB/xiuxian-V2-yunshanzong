"""Isolated real-save HTTP checks for Phase13's icon-first read model."""
import copy
import json
import unittest
from unittest.mock import patch

from src.systems.inventory.holdings import definition
from src.core.state.envelope import thaw_json
from src.rendering.game import present, manifest, bindings
from src.transport.danding import create_app
from tests.transport import test_danding as fixtures


class GameShellTests(unittest.TestCase):
    # Reuse only isolated fixture/helpers, not the legacy suite's test methods.
    setUp = fixtures.DandingTests.setUp
    tearDown = fixtures.DandingTests.tearDown
    application = fixtures.DandingTests.application
    login = fixtures.DandingTests.login
    view = fixtures.DandingTests.view
    body = fixtures.DandingTests.body
    post = fixtures.DandingTests.post
    stock = fixtures.DandingTests.stock
    start = fixtures.DandingTests.start
    settle = fixtures.DandingTests.settle
    publish = fixtures.DandingTests.publish

    def make_web(self):
        # Default adapter works before optional ui_root/cookie_path integration.
        web = create_app(self.application, self.save, lambda v: present(v, self.assets),
                         self.assets.file, fixtures.TOKEN, secure=False)
        web.config['SESSION_COOKIE_PATH'] = '/'
        return web

    def test_all_real_holdings_with_metadata_and_legacy_zero_entries(self):
        self.stock({'wood': 17, 'coins': 23, 'ore': 2})
        response = self.view(); v = response['view']
        with self.application() as game:
            state = game.query(self.save)
            self.assertEqual({k: r['quantity'] for k, r in v['holdings'].items()},
                             thaw_json(state.domains['inventory']['holdings']))
            for key, row in v['holdings'].items():
                d = definition(self.registry, key)
                self.assertEqual(row, {'resource_id': key, 'name': d.display_name,
                    'quantity': state.domains['inventory']['holdings'][key], 'grade': d.grade, 'tier': d.tier,
                    'capacity_counted': d.capacity_counted, 'category': 'herb' if key == 'herb' else 'resource'})
        self.assertEqual(v['inventory_items'], list(v['holdings'].values()))
        self.assertTrue(all(row['quantity'] > 0 for row in v['inventory_items']))
        self.assertNotIn('pill', v['holdings'])
        self.assertEqual(v['inventory']['pill']['quantity'], 0)
        self.assertEqual(v['inventory']['wood']['quantity'], 17)
        self.assertFalse(v['holdings']['coins']['capacity_counted'])
        self.assertEqual(v['capacity']['used'], 49)
        self.assertEqual(response['revision'], v['revision'])

    def test_all_existing_buildings_and_groups_match_committed_state(self):
        v = self.view()['view']
        with self.application() as game:
            state = game.query(self.save)
            self.assertEqual(set(v['buildings']), set(state.domains['sect']['buildings']))
            self.assertEqual({g['instance_id'] for g in v['disciples']['groups']}, set(state.domains['disciples']['groups']))
            for identity, row in v['buildings'].items():
                for key, value in state.domains['sect']['buildings'][identity].items():
                    self.assertEqual(row[key], value)
                self.assertEqual(row['instance_id'], identity)
            for row in v['disciples']['groups']:
                identity = row['instance_id']
                source = state.domains['disciples']['groups'][identity]
                self.assertEqual(row['count'], source['count'])
                self.assertEqual(row['definition_id'], source['definition_id'])
                self.assertNotIn('stats', row)
                self.assertEqual(row['available_count'] + row['occupied_count'], row['count'])
        self.assertEqual(sum(g['assigned_count'] for g in v['disciples']['groups']), 1)
        self.assertEqual(v['disciples']['commitments'], {})
        assigned = next(g for g in v['disciples']['groups'] if g['assigned_count'])
        self.assertEqual(assigned['assignments'], [{'building_id': v['building']['instance_id'],
            'name': '丹鼎阁', 'count': 1}])

    def test_assignments_and_commitments_remain_distinct_until_settlement(self):
        self.assertEqual(self.start().status_code, 200)
        self.assertEqual(self.post('/api/command', self.body('unassign')).status_code, 200)
        v = self.view()['view']
        group = next(g for g in v['disciples']['groups'] if g['definition_id'] == 'ordinary_alchemy')
        self.assertEqual((group['assigned_count'], group['working_count'], group['occupied_count']), (0, 1, 1))
        self.assertEqual(group['assignments'], [])
        self.assertEqual(group['allocations'], {v['building']['instance_id']: 1})
        self.assertTrue(v['disciples']['commitments'])
        self.settle(30000)
        v = self.view()['view']
        self.assertEqual(v['disciples']['commitments'], {})
        self.assertEqual(v['holdings']['pill']['quantity'], 1)
        self.assertEqual(v['holdings']['pill']['category'], 'pill')

    def test_get_and_present_are_read_only_single_snapshot(self):
        self.start(); before = self.view()
        self.clock.advance(60000)
        with patch.object(self.clock, 'now_ms', side_effect=AssertionError('read must not settle')):
            self.assertEqual(self.view(), before)
            with self.application() as game, patch.object(game, 'query', wraps=game.query) as query:
                game.view(self.save)
                self.assertEqual(query.call_count, 1)
        original = copy.deepcopy(before['view'])
        for _ in range(3): present(before['view'], self.assets)
        self.assertEqual(before['view'], original)

    def test_refresh_recreation_preserves_full_model_and_job(self):
        self.stock({'wood': 7}); self.start(); self.settle(10000)
        before = self.view()['view']
        self.web = self.make_web(); self.client = self.web.test_client(); self.login()
        self.assertEqual(self.view()['view'], before)
        self.settle(20000)
        v = self.view()['view']
        self.assertEqual(v['holdings']['wood']['quantity'], 7)
        self.assertEqual(v['holdings']['pill']['quantity'], 1)

    def test_daily_icons_only_battle_is_unimplemented_scene(self):
        p = self.view()['presentation']
        self.assertEqual(p['mode'], 'icon'); self.assertNotIn('scene', p)
        for key, screen in p['screens'].items():
            self.assertEqual(screen['mode'], 'scene' if key == 'battle' else 'icon')
            if not screen['implemented']: self.assertTrue(screen['read_only'])
        self.assertFalse(p['battle']['implemented'])
        self.assertIsNone(p['battle']['assets']['background'])
        self.assertEqual(p['battle']['assets']['sprites'], {})
        before = self.view()['view']
        for command in ('battle_start', 'equipment_equip', 'cultivation_start'):
            self.assertEqual(self.post('/api/command', self.body(command)).status_code, 422)
        self.assertEqual(self.view()['view'], before)

    def test_icons_resolve_stable_ids_and_game_url_without_private_paths(self):
        asset_id = 'icon.pill.a05aa9179e82c'
        _, digest = self.publish(asset_id)
        with patch.object(self.assets, 'snapshot', wraps=self.assets.snapshot) as snapshot:
            p = present(self.view()['view'], self.assets)
            # self.view also invoked present once.
            self.assertEqual(snapshot.call_count, 2)
        icon = p['icons']['pill']
        self.assertEqual(icon['asset_id'], asset_id); self.assertFalse(icon['fallback'])
        self.assertEqual(icon['asset']['url'], '/game/runtime/' + asset_id + '/' + digest)
        self.assertEqual(set(icon['asset']), {'asset_id', 'url', 'width', 'height', 'version'})
        response = self.client.get('/runtime/' + asset_id + '/' + digest)
        self.assertEqual(response.status_code, 200); response.close()
        public = manifest(self.assets)
        self.assertTrue(public['manifest_available']); self.assertEqual(public['manifest_asset_count'], 1)
        self.assertEqual(public['icons']['pill'], icon)
        def check_private_keys(value):
            if isinstance(value,dict):
                self.assertNotIn('path',value)
                for child in value.values():check_private_keys(child)
            elif isinstance(value,list):
                for child in value:check_private_keys(child)
        check_private_keys(public)
        self.assertNotIn('/root/',json.dumps(public))

    def test_game_mount_and_manifest_optional_transport_integration(self):
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        from src.core.save.sqlite import V2_ROOT
        asset_id = 'icon.pill.a05aa9179e82c'
        self.publish(asset_id)
        web = create_app(self.application, self.save, lambda v: present(v, self.assets),
                         self.assets.file, fixtures.TOKEN, secure=False,
                         ui_root=V2_ROOT / 'src/ui/pages/game', cookie_path='/game/',
                         asset_view=lambda: manifest(self.assets))
        def absent(environ, start_response):
            start_response('404 Not Found', []); return [b'Not Found']
        client = Client(DispatcherMiddleware(absent, {'/game': web}), Response)
        self.assertEqual(client.get('/game/api/assets').status_code, 401)
        login = client.post('/game/login', data={'token': fixtures.TOKEN})
        self.assertEqual(login.status_code, 302)
        self.assertIn('Path=/game/', login.headers['Set-Cookie'])
        response = client.get('/game/api/view')
        self.assertEqual(response.status_code, 200)
        icon = response.json['presentation']['icons']['pill']
        runtime = client.get(icon['asset']['url'])
        self.assertEqual(runtime.status_code, 200); runtime.close()
        availability = client.get('/game/api/assets')
        self.assertEqual(availability.status_code, 200)
        self.assertEqual(availability.json['presentation']['icons']['pill'], icon)
        self.assertEqual(client.get('/game/').status_code, 200)

    def test_missing_unknown_and_invalid_runtime_are_honest_placeholders(self):
        self.stock({'wood': 1})
        p = self.view()['presentation']
        self.assertEqual(p['icons']['wood'], {'asset_id': bindings()['icons']['wood'], 'fallback': True, 'asset': None})
        self.assertTrue(p['icons']['herb']['fallback'])
        self.assertTrue(all(row['fallback'] for row in p['building_icons'].values()))
        self.assertFalse(manifest(self.assets)['manifest_available'])
        doc, _ = self.publish('icon.pill.a05aa9179e82c')
        doc['assets']['icon.pill.a05aa9179e82c']['files'][0]['file'] = '../source.png'
        (self.root / 'assets/manifest.json').write_text(json.dumps(doc))
        self.assertTrue(self.view()['presentation']['icons']['pill']['fallback'])
        (self.root / 'assets/manifest.json').write_text('broken')
        self.assertFalse(manifest(self.assets)['manifest_available'])
        self.assertEqual(self.client.get('/api/view').status_code, 200)


if __name__ == '__main__': unittest.main()
