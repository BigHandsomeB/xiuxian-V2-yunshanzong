"""Stable enclosure/pool placement over the existing authoritative livestock."""
from src.core.validation import ValidationError
from src.data.economy.ecology import lookup

COMMANDS = ('habitat_stock', 'habitat_repeat')


def layout(part, registry, bid, capacity):
    cells = [None] * capacity
    rows = [(key, row) for key, row in part['batches'].items() if row['building_id'] == bid]
    # Explicitly placed individuals retain their cells; legacy groups fill free space.
    rows.sort(key=lambda item: ('slot_index' not in item[1], item[0]))
    for batch_id, row in rows:
        slots = lookup(registry, 'species', row['species_id'])['slots']
        for individual in range(row['count']):
            if 'slot_index' in row:
                start = row['slot_index']
                if row['count'] != 1 or start + slots > capacity or any(cells[start:start+slots]):
                    raise ValidationError('兽栏或灵池位置重叠或越界')
            else:
                start = next((i for i in range(capacity-slots+1) if not any(cells[i:i+slots])), None)
                if start is None:
                    # Legacy cohorts may use fragmented remaining capacity.
                    free = [i for i, cell in enumerate(cells) if cell is None][:slots]
                    if len(free) != slots: raise ValidationError('养殖存栏超过格子容量')
                    for offset, index in enumerate(free):
                        cells[index] = {'batch_id':batch_id, 'primary':offset == 0, 'individual':individual}
                    continue
            for offset in range(slots):
                cells[start+offset] = {'batch_id':batch_id, 'primary':offset == 0, 'individual':individual}
    return cells
