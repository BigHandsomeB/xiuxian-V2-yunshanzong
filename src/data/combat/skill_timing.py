"""Versioned active-skill policy derived from the preserved v1 effect package."""
from copy import deepcopy

VERSION = 'timed-skills-v1'
CONTENT_VERSION = 'sect-skills-v2-6.3.0-r1'
COOLDOWNS_MS = {'movement': 10000, 'defense': 12000, 'special': 8000, 'ultimate': 24000}
CATEGORIES = {'special': 1, 'ultimate': 2, 'movement': 3, 'defense': 4}
ACTIVE_WINDOW_TURNS = 6


def compile_settings(legacy):
    """Keep legacy/inner-manual definitions intact; gate reactive active followups."""
    data = deepcopy(legacy)
    data['version'] = VERSION
    for category, name, modifiers in (
        ('movement', '身法运转', {'speed_bps': 1200, 'evasion_bps': 800}),
        ('defense', '防御运转', {'damage_reduction_bps': 1200}),
    ):
        data['statuses']['active_' + category] = {
            'name': name, 'max_stacks': 1, 'duration': ACTIVE_WINDOW_TURNS,
            'modifiers': modifiers, 'negative': False,
        }
    for row in data['techniques'].values():
        category = row['category']
        if category == 'passive':
            continue
        if category in ('special', 'ultimate'):
            for rule in row['rules']:
                if rule.get('category'):
                    rule.pop('cooldown', None)
                    rule['cooldown_ms'] = COOLDOWNS_MS[category]
            continue
        window = 'active_' + category
        for rule in row['rules']:
            rule['requires_active'] = window
            if rule['trigger'] == 'battle_start':
                rule['trigger'] = 'skill_cast'
                rule['condition'] = ['and', ['eq', 'event.category', CATEGORIES[category]],
                                     rule.get('condition', True)]
        row['rules'].insert(0, {
            'id': 'active_cast', 'trigger': 'turn_start', 'category': category,
            'cooldown_ms': COOLDOWNS_MS[category],
            'effects': [{'op': 'status', 'status': window, 'duration': ACTIVE_WINDOW_TURNS}],
        })
        row['description'] = ('自动施放后获得'+str(ACTIVE_WINDOW_TURNS)+'回合' + ('速度+12%、闪避+8%' if category == 'movement' else '减伤+12%')
                              + '，运转期间按条件触发原有特色；' + row['description'])
    return data
