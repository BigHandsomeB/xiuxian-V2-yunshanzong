"""Playable composition root. Private routing identity is not a second gameplay save."""
from contextlib import contextmanager
from pathlib import Path
from src.application.danding import DandingApplication, initial_slice
from src.core.save.sqlite import SQLiteSave
from src.core.time.clock import SystemClock
from src.core.time.config import SETTLEMENT_BUDGET_MS, SETTLEMENT_MAX_EVENTS
from src.core.validation import integer
from src.core.validation import uuid4_id
from src.data.recipes.alchemy import load_alchemy
from src.data.cultivation.definitions import load_cultivation
from src.application.world import WorldApplication
from src.application.dungeons import DungeonApplication
from src.data.dungeons.definitions import load_dungeons

PROJECT=Path(__file__).resolve().parents[2]


def backup_application(factory, save_id, root):
    from src.application.save_backup import SaveBackup
    from src.core.save.backup import BackupStore
    return SaveBackup(factory, BackupStore(root/'backups.sqlite3', root), save_id)


def game_factory(path,root,clock=None,*,registry=None,application_class=None,settlement_budget_ms=SETTLEMENT_BUDGET_MS):
    integer(settlement_budget_ms,'settlement budget milliseconds',1)
    if settlement_budget_ms>5000:raise ValueError('settlement budget must not exceed 5000 milliseconds')
    if registry is None:
        from src.data.content_loader import load_current
        registry=load_current()
    clock=clock or SystemClock()
    if application_class is None:
        from src.data.economy.sect_rules import settings
        from src.application.sect_management import ManagementApplication
        from src.application.ecology import EcologyApplication
        application_class=EcologyApplication if (settings(registry) or {}).get('ecology') else ManagementApplication if (settings(registry) or {}).get('management') else DungeonApplication
    @contextmanager
    def application():
        with SQLiteSave(path,allowed_root=root) as store:
            game=application_class(store,registry,clock)
            if hasattr(game.engine,'budget_ms'):
                game.engine.budget_ms=settlement_budget_ms;game.settlement_max_events=SETTLEMENT_MAX_EVENTS
            yield game
    return application


def setup():
    """Explicit CLI-only creation; never run in GET or implicitly replace a save."""
    root=PROJECT/'.game'
    if root.is_symlink():raise RuntimeError('private scenario directory cannot be a symlink')
    root.mkdir(mode=0o700,exist_ok=True)
    path=root/'danding.sqlite3';pointer=root/'save-id'
    if path.exists() or pointer.exists():raise RuntimeError('scenario already exists; no reset or overwrite')
    registry=load_alchemy();clock=SystemClock()
    state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
    with SQLiteSave.initialize(path,allowed_root=root) as store:
        game=DandingApplication(store,registry,clock);game.create(state);game.checkpoint(state.save_id)
    # Routing only; all Gameplay facts/receipts remain in the Foundation SQLite.
    with pointer.open('x') as output:output.write(state.save_id+'\n')
    pointer.chmod(0o600)
    return state.save_id


def configured_game():
    root=PROJECT/'.game';pointer=root/'save-id'
    if root.is_symlink() or pointer.is_symlink():raise RuntimeError('scenario routing symlink rejected')
    save_id=pointer.read_text().strip();uuid4_id(save_id,'scenario save_id')
    import os
    from src.data.content_compatibility import profile
    # Pure content selection preserves old saves until an explicit operator upgrade.
    with SQLiteSave(root/'danding.sqlite3',allowed_root=root) as store:
        current=store.inspect(save_id,include_recovery=False).current
        if current is None:raise RuntimeError('valid current scenario required')
        selected=profile(current.content_version)
        if selected.loader=='current':
            from src.data.content_loader import load_current
            registry=load_current()
        else:
            registry=load_dungeons(**dict(selected.flags))
    factory=game_factory(root/'danding.sqlite3',root,registry=registry,settlement_budget_ms=int(os.environ.get('GAME_SETTLE_BUDGET_MS',SETTLEMENT_BUDGET_MS)))
    with factory() as app:app.view(save_id)  # Fail closed; no auto repair/reset/reward.
    return factory,save_id


if __name__=='__main__':print('Private scenario created:',setup())
