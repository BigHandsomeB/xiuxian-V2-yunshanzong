"""Create one fresh current-content save explicitly; never overwrite an existing save."""
from tools.playable.game import PROJECT, game_factory
from src.application.danding import initial_slice
from src.core.save.sqlite import SQLiteSave
from src.core.time.clock import SystemClock
from src.data.dungeons.definitions import load_dungeons


def setup():
    root = PROJECT / '.game'
    if root.is_symlink():
        raise RuntimeError('Private save directory cannot be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    path, pointer = root / 'danding.sqlite3', root / 'save-id'
    if path.exists() or pointer.exists() or path.is_symlink() or pointer.is_symlink():
        raise RuntimeError('Save already exists; refusing to overwrite')
    registry = load_dungeons(management=True, cold_jade=True, ecology=True)
    clock = SystemClock()
    state = initial_slice(registry, last_settled_at_ms=clock.now_ms())
    with SQLiteSave.initialize(path, allowed_root=root):
        pass
    factory = game_factory(path, root, clock, registry=registry)
    with factory() as app:
        app.create(state)
        app.checkpoint(state.save_id)
    with pointer.open('x') as out:
        out.write(state.save_id + '\n')
    pointer.chmod(0o600)
    return 'Fresh current-content save created.'


if __name__ == '__main__':
    print(setup())
