"""Read-only narrative package validation; never opens a player save."""
from src.data.story.definitions import load_catalog
from src.data.content_loader import load_current
from src.data.registry import DefinitionKey
from src.core.validation import ValidationError


def check():
    data=load_catalog();registry=load_current()
    for node in data['nodes']:
        c=node['condition']
        if 'dungeon_id' in c:
            dungeon=registry.lookup(DefinitionKey('dungeons',c['dungeon_id']))
            if c.get('minimum',1)>len(dungeon.encounters):raise ValidationError('story floor exceeds dungeon')
        if 'building_kind' in c:registry.lookup(DefinitionKey('buildings',c['building_kind']))
        if c.get('kind')=='event' and c['event_id'] not in {'wood_harvest'}:
            raise ValidationError('story event has no production observer')
    print(f"Story catalog OK: {len(data['chapters'])} groups, {len(data['nodes'])} nodes; current content references valid")


if __name__=='__main__':check()
