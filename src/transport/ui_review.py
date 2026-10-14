"""Public, read-only UI review over injected synthetic exports; no game factory."""
import json,re
from pathlib import Path
from io import BytesIO
from flask import Flask,abort,jsonify,render_template,request,send_file

CASES=('normal','elite','boss','production')

def create_review_app(bundle,runtime_file,*,ui_root,guide_root,design_file,allowed_hosts=None):
    # Capture only URLs explicitly used by this export; never publish an arbitrary file route.
    assets=set()
    def collect(value):
        if isinstance(value,str) and re.fullmatch(r'/game/review/runtime/[a-z][a-z0-9_.]*/[a-f0-9]{64}',value):assets.add(value)
        elif isinstance(value,dict):
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(bundle)
    app=Flask(__name__,template_folder=str(guide_root),static_folder=str(Path(ui_root)/'static'))
    app.config.update(TRUSTED_HOSTS=allowed_hosts or ['localhost','127.0.0.1'],MAX_CONTENT_LENGTH=4096)
    @app.before_request
    def read_only():
        if request.method not in ('GET','HEAD'):abort(405)
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Robots-Tag']='noindex, nofollow'
        response.headers['Cache-Control']='public, max-age=31536000, immutable' if request.endpoint=='runtime' and response.status_code in (200,304) else 'no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'"
        return response
    @app.get('/')
    def guide():return render_template('guide.html',cases=CASES,available=bundle is not None)
    @app.get('/preview')
    def preview():
        if bundle is None:abort(503)
        # Use the exact production template and CSS, switching only its API client.
        from jinja2 import Environment,FileSystemLoader,select_autoescape
        env=Environment(loader=FileSystemLoader(str(ui_root)),autoescape=select_autoescape(['html']))
        from flask import url_for
        return env.get_template('index.html').render(url_for=url_for,review=True)
    @app.get('/api/view')
    def view():
        if bundle is None:abort(503)
        case=request.args.get('case','normal')
        if case not in CASES:abort(404)
        return jsonify(bundle['views'][case])
    @app.get('/api/assets')
    def asset_view():
        if bundle is None:abort(503)
        return jsonify(protocol_version=1,presentation=bundle['assets'])
    @app.get('/design.md')
    def design():return send_file(design_file,mimetype='text/plain; charset=utf-8',conditional=True)
    @app.get('/runtime/<asset_id>/<digest>')
    def runtime(asset_id,digest):
        if '/game/review/runtime/'+asset_id+'/'+digest not in assets:abort(404)
        path=runtime_file(asset_id,digest)
        if path is None:abort(404)
        return send_file(path,conditional=True,**({'mimetype':'image/png','etag':digest} if isinstance(path,BytesIO) else {}))
    return app

def load_bundle(path):
    # An unavailable review must not prevent the private game from starting.
    try:
        path=Path(path)
        if not path.is_file() or path.is_symlink() or path.stat().st_size>4*1024*1024:return None
        result=json.loads(path.read_text())
        if set(result)!={'schema_version','views','assets'} or result['schema_version']!=1 or set(result['views'])!=set(CASES):return None
        if not isinstance(result['assets'],dict) or not all(isinstance(v,dict) and v.get('review',{}).get('synthetic') is True and v.get('review',{}).get('read_only') is True for v in result['views'].values()):return None
        return result
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return None
