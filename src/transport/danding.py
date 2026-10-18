"""@module transport/danding
@purpose Private single-save HTTP adapter, explicit writes only through Application.
@depends Flask, injected Application/presentation/runtime-file interfaces, standard library
@usedBy tools/playable/server; tests/transport/test_danding; @see ./INDEX.md
"""
import hashlib, hmac, secrets
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from time import monotonic
from io import BytesIO
from flask import Flask, jsonify, request, session, g, render_template, redirect, url_for, send_file
from werkzeug.wsgi import get_host
from src.application.danding import SliceRequestError
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError, NotFoundError
from src.core.save.codec import CorruptSaveError, PersistenceError
from src.core.save.backup import MAX_SAVE_BYTES
from src.application.history import compact_view,compact_report
import gzip

UI_ROOT=Path(__file__).resolve().parents[1]/'ui/pages/danding'


def create_app(application,save_id,render_view,runtime_file,access_token,*,allowed_hosts=None,secure=True,
               ui_root=None,cookie_path='/play/',asset_view=None,catalog_notes=None):
    """application is a context-manager factory; route never opens SQL or mutates State."""
    if not isinstance(access_token,str) or len(access_token)<24:raise ValueError('private access token required')
    root=Path(ui_root) if ui_root is not None else UI_ROOT
    app=Flask(__name__,template_folder=str(root),static_folder=str(root/'static'))
    scope=b'xianxia-v2-private-play-session-v1' if cookie_path=='/play/' else b'xianxia-v2-private-game-session-v1'
    app.secret_key=hmac.new(access_token.encode(),scope,hashlib.sha256).digest()
    app.config.update(MAX_CONTENT_LENGTH=4096,SESSION_COOKIE_NAME='xianxia_play' if cookie_path=='/play/' else 'xianxia_game',SESSION_COOKIE_PATH=cookie_path,
                      SESSION_COOKIE_SECURE=secure,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',
                      PERMANENT_SESSION_LIFETIME=timedelta(days=7),TRUSTED_HOSTS=allowed_hosts or ['localhost','127.0.0.1'])
    failures={}

    @app.before_request
    def protect():
        get_host(request.environ,trusted_hosts=app.config['TRUSTED_HOSTS'])
        save_put=request.method=='PUT' and request.path=='/api/save' and app.config.get('GAME_SAVE_BACKUP_ENABLED',False)
        # Per-request limit also bounds streamed/chunked bodies; no global POST relaxation.
        request.max_content_length=MAX_SAVE_BYTES if save_put else 4096
        if request.content_length is not None and request.content_length>request.max_content_length:
            return error_body('请求格式或大小不正确','FORMAT','VALIDATION'),413
        if request.method not in ('GET','HEAD','POST') and not save_put:return error_body('此入口不支持该操作','METHOD','VALIDATION'),405
        if request.method=='POST' or save_put:
            origin=request.headers.get('Origin')
            if (origin and origin.rstrip('/')!=request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site')=='cross-site':
                return error_body('请从当前游戏页面操作','ORIGIN','AUTH'),403
        if request.endpoint in ('login','static'):return None
        if not session.get('authenticated'):
            if request.path.startswith(('/api/','/runtime/')):return error_body('请重新登录','LOGIN','AUTH',True),401
            return redirect(url_for('login'))
        if (request.method=='POST' or save_put) and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf','missing')):
            return error_body('页面登录已过期，请重新登录','CSRF','AUTH',True),403
        if (request.method=='POST' or save_put) and request.content_length is None and request.environ.get('wsgi.input_terminated'):
            # Read one extra byte: LimitedStream can otherwise truncate a chunked JSON prefix.
            chunks=[];remaining=request.max_content_length+1
            while remaining:
                part=request.input_stream.read(min(65536,remaining))
                if not part:break
                chunks.append(part);remaining-=len(part)
            if not remaining:return error_body('请求格式或大小不正确','FORMAT','VALIDATION'),413
            request._cached_data=b''.join(chunks)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['Cache-Control']='private, max-age=31536000, immutable' if request.endpoint=='runtime' and response.status_code in (200,304) else 'no-store'
        if response.status_code==200 and response.mimetype=='application/json':
            response.vary.add('Accept-Encoding')
            if request.accept_encodings['gzip']>0 and not response.headers.get('Content-Encoding') and len(response.get_data())>=512:
                response.set_data(gzip.compress(response.get_data(),compresslevel=6,mtime=0));response.headers['Content-Encoding']='gzip'
        return response

    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None
        if request.method=='POST':
            # Monotonic here throttles access attempts only; it never affects Simulation.
            address=request.remote_addr or 'local';now=monotonic();n,until=failures.get(address,(0,0))
            if now<until:return render_template('login.html',error='尝试过于频繁，请稍后重试'),429
            token=request.form.get('token','')
            if hmac.compare_digest(token.encode(),access_token.encode()):
                failures.pop(address,None);session.clear();session['authenticated']=True
                session['csrf']=secrets.token_hex(24);session.permanent=True
                return redirect(url_for('index'))
            if len(failures)>=512:failures.clear()
            failures[address]=(n+1,now+(60 if n>=4 else 1))
            error='口令不正确'
        return render_template('login.html',error=error),401 if error else 200

    @app.get('/')
    def index():return render_template('index.html')

    @app.get('/api/view')
    def view():
        with application() as game:snapshot=compact_view(game.view(save_id))
        return jsonify(protocol_version=1,save_schema_version=snapshot['save_schema_version'],
                       data_schema_version=snapshot['data_schema_version'],content_version=snapshot['content_version'],
                       save_id=snapshot['save_id'],generation=snapshot['generation'],revision=snapshot['revision'],
                       time=snapshot['time'],view=snapshot,presentation=render_view(snapshot),csrf=session['csrf'])

    if catalog_notes is not None:
        @app.post('/api/catalog-notes')
        def edit_catalog_notes():
            from src.application.catalog_notes import NotesConflict
            try:entry=catalog_notes.write(request.get_json(silent=True))
            except NotesConflict as e:return error_body('此素材说明已被更新，请重新加载后再编辑','STALE','CONFLICT',True,current_revision=e.revision),409
            return jsonify(protocol_version=1,entry=entry)

    if asset_view is not None:
        @app.get('/api/assets')
        def asset_manifest():
            # Only injected public Runtime metadata; never Catalog or Source paths.
            return jsonify(protocol_version=1,presentation=asset_view())

    def input_body():
        body=request.get_json()
        candidate=body.get('request_id') if isinstance(body,dict) else None
        g.request_id=candidate if isinstance(candidate,str) and len(candidate)<=64 else None
        return body

    @app.post('/api/command')
    def command():
        with application() as game:
            receipt=game.act(save_id,input_body());current=compact_view(game.view(save_id))
        return jsonify(protocol_version=1,receipt={'request_id':receipt.request_id,'status':'completed',
                       'committed_revision':receipt.committed_revision,'result':thaw_json(receipt.result)},
                       save_id=save_id,generation=current['generation'],revision=current['revision'],
                       time=current['time'],view=current,presentation=render_view(current),csrf=session['csrf'])

    @app.post('/api/settle')
    def settle():
        with application() as game:
            body=input_body();receipt=game.advance(save_id,body)
            current=compact_view(game.view(save_id)) if receipt.result.status=='COMPLETE' else None
        wire=asdict(receipt);wire['result']['processed_count']=len(receipt.result.processed_events);wire['result']['processed_events']=[]
        if wire['result'].get('offline_report') is not None:wire['result']['offline_report']=compact_report(wire['result']['offline_report'])
        response=dict(protocol_version=1,processed_count=len(receipt.result.processed_events),complete=receipt.result.status=='COMPLETE',receipt={**wire,'status':receipt.result.status.lower()},
                       save_id=save_id,generation=body['generation'],revision=receipt.committed_revision,
                       time={'simulation_time_ms':receipt.result.to_sim_ms,'pending':receipt.result.status=='PENDING',
                             'target_sim_ms':receipt.result.target_sim_ms,'remaining_ms':receipt.result.target_sim_ms-receipt.result.to_sim_ms,
                             'processed_sim_ms':receipt.result.to_sim_ms-receipt.result.from_sim_ms,
                             'offline_duration_ms':receipt.result.accepted_ms+receipt.result.discarded_ms,
                             'settlement_duration_ms':receipt.result.accepted_ms,
                             'from_sim_ms':receipt.result.target_sim_ms-receipt.result.accepted_ms,
                             'continuation':asdict(receipt.result.continuation) if receipt.result.continuation else None})
        if current is not None:response.update(view=current,presentation=render_view(current),csrf=session['csrf'])
        return jsonify(response)

    @app.get('/api/history')
    def history():
        try:offset=int(request.args.get('offset',0));limit=int(request.args.get('limit',50))
        except ValueError:raise ValidationError('invalid history page')
        with application() as game:return jsonify(game.history(save_id,request.args.get('kind','equipment'),offset=offset,limit=limit))

    @app.get('/api/offline-report/<report_id>')
    def offline_report_detail(report_id):
        with application() as game:return jsonify(game.history(save_id,'report',report_id=report_id))

    @app.get('/api/settlement/<request_id>')
    def settlement_detail(request_id):
        with application() as game:return jsonify(game.history(save_id,'settlement',request_id=request_id))

    @app.get('/runtime/<asset_id>/<digest>')
    def runtime(asset_id,digest):
        path=runtime_file(asset_id,digest)
        if path is None:return error_body('素材暂不可用','MISSING_ASSET','NOT_FOUND',True),404
        return send_file(path,conditional=True,**({'mimetype':'image/png','etag':digest} if isinstance(path,BytesIO) else {}))

    def error_body(message,code,category,retryable=False,**details):
        request_id=getattr(g,'request_id',None)
        return jsonify(protocol_version=1,error=message,message=message,code=code,category=category,request_id=request_id,retryable=retryable,**details)

    @app.errorhandler(SliceRequestError)
    def invalid_envelope(error):return error_body('请求版本或格式不正确，请刷新页面后重试','FORMAT','VALIDATION'),400

    @app.errorhandler(ConflictError)
    def conflict(error):
        with application() as game:current=game.query(save_id)
        return error_body('状态已更新或存档已恢复换代，请刷新后重试','STALE','CONFLICT',True,
                          current_revision=current.revision,current_generation=current.generation),409

    @app.errorhandler(ValidationError)
    @app.errorhandler(NotFoundError)
    def invalid(error):
        from src.application.world import WorldPaused
        if isinstance(error,WorldPaused):return error_body(str(error),'WORLD_PAUSED','DOMAIN'),422
        from src.application.cultivation import CultivationBlocked
        if isinstance(error,CultivationBlocked):return error_body(str(error),'INVALID','DOMAIN'),422
        if str(error) in ('此装备及配方已移除','此装备已移除','此装备配方已移除'):
            return error_body(str(error),'CONTENT_RETIRED','DOMAIN'),422
        if request.path.endswith('/api/catalog-notes'):return error_body(str(error),'INVALID','VALIDATION'),422
        message='当前条件不满足，请查看材料、岗位和仓容后重试'
        if cookie_path=='/game/' and request.is_json and 'cultivation_' in str(request.get_json(silent=True)):
            message='修炼请求无效，请更新状态后重试。'
        if cookie_path=='/game/' and (request.path=='/api/combat' or (request.is_json and 'combat_' in str(request.get_json(silent=True)))):
            message='战斗状态或目标已改变；请更新状态。领取奖励前须获胜，仓库须有空位。'
        return error_body(message,'INVALID','DOMAIN'),422

    @app.errorhandler(CorruptSaveError)
    @app.errorhandler(PersistenceError)
    def unavailable(error):
        app.logger.error('Game save unavailable: %s',type(error).__name__)
        return error_body('存档暂不可用，请联系维护者；没有自动重置存档','SAVE_UNAVAILABLE','PERSISTENCE',True),503

    @app.errorhandler(400)
    @app.errorhandler(413)
    def malformed(error):return error_body('请求格式或大小不正确，请刷新页面后重试','FORMAT','VALIDATION'),error.code

    @app.errorhandler(500)
    def failed(error):return error_body('服务暂不可用，原请求会保留以便重试','SERVER','INTERNAL',True),500
    return app
