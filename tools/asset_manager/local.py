"""Local manager connected through the existing Manifest/Runtime contract."""
import hashlib,json,os,secrets
from flask import jsonify,render_template,request,send_file
from .catalog import PROJECT
from .web import create_app
from .model import require


def linked_app(token,root=None):
    root=root or PROJECT/'assets'
    app=create_app(root,token,merge_runtime=True)
    catalog=app.extensions['asset_catalog']
    @app.context_processor
    def context():return {'game_linked':True}
    def published():
        doc=json.loads(catalog.path('manifest.json').read_text(encoding='utf-8'))
        require(doc.get('schema_version')==1 and type(doc.get('assets')) is dict,'Invalid game manifest')
        return doc['assets']
    def names():
        try:
            data=json.loads(catalog.path('registry/published-catalog.json').read_text(encoding='utf-8'))
            return {r['asset_id']:r.get('name',r['asset_id']) for g in data['groups'] for r in g['items']}
        except (OSError,ValueError,KeyError,TypeError):return {}
    @app.get('/game-runtime')
    def game_runtime():return render_template('game-runtime.html')
    @app.get('/api/game-runtime')
    def game_runtime_list():
        titles=names();managed={r['asset_id'] for r in catalog.list('asset')};rows=[]
        for identity,row in published().items():
            template=(row.get('export_origin') or {}).get('template_id')
            rows.append({'asset_id':identity,'name':titles.get(identity,identity),'version':row.get('version'),
                         'template_id':template,'can_register':template in catalog.templates,
                         'managed':identity in managed,'frames':len(row.get('files',[])),
                         'preview':'/game-runtime/image/'+identity})
        return jsonify(count=len(rows),managed_count=len(managed),assets=rows)
    @app.get('/game-runtime/image/<identity>')
    def game_runtime_image(identity):
        row=published().get(identity);require(row is not None,'Unknown published asset')
        files=row.get('files',[]);require(bool(files),'No published frame')
        frame=files[0];relative=frame['file'];require(relative.startswith('runtime/'),'Runtime only')
        path=catalog.path(relative)
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256'],'Published file checksum mismatch')
        return send_file(path,conditional=True)
    @app.post('/api/game-runtime/register')
    def game_runtime_register():
        body=request.get_json();require(type(body) is dict and set(body)=={'asset_id'},'Select one published asset')
        identity=body['asset_id'];require(type(identity) is str,'Invalid asset identity')
        rows=published();require(identity in rows,'Unknown published asset')
        asset=catalog.get('asset',identity,missing=True)
        if asset is None:
            template=(rows[identity].get('export_origin') or {}).get('template_id')
            require(template in catalog.templates,'No current template; create a new asset explicitly')
            asset=catalog.create_asset(identity,names().get(identity,identity),template)
        return jsonify(asset_id=asset['asset_id'],url='/#asset/'+asset['asset_id'])
    return app


def main():
    token=os.environ.get('ASSET_MANAGER_TOKEN') or secrets.token_urlsafe(32)
    app=linked_app(token)
    print('素材管理器已连接本地游戏：assets/manifest.json + assets/runtime/',flush=True)
    print('打开 http://127.0.0.1:8765/ ，登录口令：'+token,flush=True)
    print('停止时按 Ctrl+C；游戏本身仍使用无端口桌面模式。',flush=True)
    app.run(host='127.0.0.1',port=8765,debug=False,use_reloader=False,threaded=False)

if __name__=='__main__':main()
