"""Frozen pre-optimization scheduler methods for result-equivalence gates only."""
from contextlib import contextmanager, ExitStack
from unittest.mock import patch
from src.application.economy_settlement import EconomySettlement
from src.application.dungeon_settlement import DungeonSettlement
from src.application.sect_management_settlement import ManagementSettlement

from pathlib import Path
ROOT=Path(__file__).parent

@contextmanager
def original_work():
    with ExitStack() as stack:
        for cls,source,names in [(EconomySettlement,'settlement_work_original.py',('advance','deliver','dispatch','wake')),(DungeonSettlement,'dungeon_work_original.py',('dispatch','wake')),(ManagementSettlement,'management_work_original.py',('dispatch','wake','meals'))]:
            # Rebind zero-argument super to the live class hierarchy; arithmetic,
            # boundaries and all method bodies remain those of the frozen baseline.
            namespace={'__name__':'settlement_reference','_base':cls}
            exec((ROOT/source).read_text().replace('super()','super(_base,self)'),namespace)
            old=namespace[cls.__name__]
            for name in names:stack.enter_context(patch.object(cls,name,getattr(old,name)))
        yield
