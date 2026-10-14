"""Independent private playable WSGI service; no asset-manager runtime dependency."""
import os
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import make_server
from src.transport.danding import create_app
from src.transport.combat import register as register_combat
from src.transport.ui_review import create_review_app,load_bundle
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering.scenes.sect.danding import present
from src.rendering.game import present as present_game, manifest as game_manifest
from tools.playable.game import PROJECT, configured_game, backup_application
from src.transport.save import register as register_save
from src.application.catalog_notes import CatalogNotes


def application():
    factory,save_id=configured_game();assets=GameRuntimeAssets(PROJECT/'assets')
    app=create_app(factory,save_id,lambda view:present(view,assets),assets.file,os.environ['ASSET_MANAGER_TOKEN'],
                   allowed_hosts=os.environ.get('GAME_ALLOWED_HOSTS','localhost,127.0.0.1').split(','),secure=os.environ.get('GAME_LOCAL_HTTP') != '1')
    game=create_app(factory,save_id,lambda view:present_game(view,assets),assets.file,os.environ['ASSET_MANAGER_TOKEN'],
                    allowed_hosts=os.environ.get('GAME_ALLOWED_HOSTS','localhost,127.0.0.1').split(','),secure=os.environ.get('GAME_LOCAL_HTTP') != '1',
                    ui_root=PROJECT/'src/ui/pages/game',cookie_path='/game/',asset_view=lambda:game_manifest(assets),catalog_notes=CatalogNotes(PROJECT/'assets',lambda:set(assets.snapshot())))
    register_combat(game,factory,save_id)
    register_save(game,backup_application(factory,save_id,PROJECT/'.game'))
    review=create_review_app(load_bundle(PROJECT/'.ui-review.json'),assets.file,ui_root=PROJECT/'src/ui/pages/game',guide_root=PROJECT/'src/ui/pages/review',design_file=PROJECT/'docs/gameplay/current-game-overview.md',allowed_hosts=os.environ.get('GAME_ALLOWED_HOSTS','localhost,127.0.0.1').split(','))
    def absent(environ,start_response):
        start_response('404 Not Found',[('Content-Type','text/plain')]);return [b'Not Found']
    return ProxyFix(DispatcherMiddleware(absent,{'/play':app,'/game':game,'/game/review':review}),x_proto=1)


if __name__=='__main__':
    with make_server('127.0.0.1',8000,application(),threaded=True) as server:server.serve_forever()
