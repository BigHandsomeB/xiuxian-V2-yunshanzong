"""@module Asset Manager HTTP adapter; @purpose Authenticated developer-only Flask UI.
@depends Flask, Catalog; @usedBy local CLI/browser; @see asset-pipeline.md
"""
import hmac, json, secrets
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, request, session, jsonify, render_template, send_file
from .catalog import Catalog, PROJECT
from .model import AssetError, require, REVIEW, INTERIOR_REVIEW, templates


def create_app(root, access_token, allowed_hosts=None, *, merge_runtime=False):
    require(isinstance(access_token, str) and len(access_token) >= 24, "Configure a private access token of at least 24 characters")
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    app.config.update(MAX_CONTENT_LENGTH=13 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", TRUSTED_HOSTS=allowed_hosts or ["127.0.0.1", "localhost", "[::1]"])
    catalog = Catalog(root, merge_runtime=merge_runtime)
    app.extensions["asset_catalog"] = catalog

    @app.before_request
    def access():
        from werkzeug.wsgi import get_host
        get_host(request.environ, trusted_hosts=app.config["TRUSTED_HOSTS"])
        if request.endpoint in ("static", "login"):
            if request.method != "GET":
                origin = request.headers.get("Origin")
                if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                    return jsonify(error="Cross-origin login rejected"), 403
            return None
        bearer = request.headers.get("Authorization", "")
        api_token = bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], access_token)
        if not api_token and not session.get("authenticated"):
            if request.path.startswith("/api/") or request.path.startswith("/file/"):
                return jsonify(error="Authentication required"), 401
            return render_template("login.html"), 401
        if request.method != "GET":
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                return jsonify(error="Cross-origin write rejected"), 403
            if not api_token and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.get("csrf", "unavailable")):
                return jsonify(error="CSRF token required"), 403

    @app.after_request
    def security(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(AssetError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    def malformed(error):
        return jsonify(error="Missing or invalid request fields"), 400

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("token", ""), access_token):
                return render_template("login.html", error="访问口令不正确"), 401
            session.clear(); session.update(authenticated=True, csrf=secrets.token_hex(24))
            from flask import redirect
            return redirect(request.script_root + "/")
        return render_template("login.html")

    @app.post("/api/logout")
    def logout():
        session.clear(); return jsonify(ok=True)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def state():
        catalog.templates=templates(json.loads(catalog.template_file.read_text()))
        assets=catalog.search(include_deprecated=True)
        asset_lookup={a["asset_id"]:a for a in assets}
        compact=request.args.get('compact')=='1'
        from .views import asset_detail, asset_summary, source_summary, prompt_summary
        assets=[asset_summary(a) if compact else asset_detail(catalog,a) for a in assets]
        from .sheets import canonical_spec
        sources=catalog.list('source')
        if compact:
            sources=[source_summary(s) for s in sources]
        else:
            for source in sources:
                if source.get('frozen_spec'):source['import_spec']=canonical_spec(source['frozen_spec'])
        return jsonify(collections=catalog.list("collection"), templates=list(catalog.templates.values()), assets=assets, sets=[catalog.completeness(s["set_id"],group=s,assets=asset_lookup) for s in catalog.list("set")], sources=sources, prompts=[prompt_summary(p) if compact else p for p in catalog.list("prompt")], compact=compact, manifest=(dict(assets={key:None for key in json.loads(catalog.path("manifest.json").read_text())["assets"]}) if compact else json.loads(catalog.path("manifest.json").read_text())), review_checks=REVIEW, interior_checks=INTERIOR_REVIEW, csrf=session.get("csrf"))

    @app.get('/api/asset-detail')
    def asset_detail_view():
        from .views import asset_detail
        a=catalog.get('asset',request.args['asset_id'])
        prompts=[p for p in catalog.list('prompt') if p.get('asset_id')==a['asset_id'] or a.get('set_id') and p.get('set_id')==a['set_id']]
        return jsonify(asset=asset_detail(catalog,a),prompts=prompts)

    @app.get('/api/source-detail')
    def source_detail_view():
        from .sheets import canonical_spec
        source=catalog.get('source',request.args['source_id'])
        if source.get('frozen_spec'):source['import_spec']=canonical_spec(source['frozen_spec'])
        return jsonify(source=source,prompt=catalog.get('prompt',source['prompt_id']) if source.get('prompt_id') else None)

    @app.get('/api/prompt-detail')
    def prompt_detail_view():
        return jsonify(catalog.get('prompt',request.args['prompt_id']))

    @app.get("/api/storage")
    def storage_usage():
        from .storage import usage
        return jsonify(usage(catalog.root))

    @app.get("/api/search")
    def search():
        fields = {key: request.args[key] for key in ["collection_id", "category", "template_id", "set_id", "art_status", "version", "tag", "runtime_ready"] if key in request.args}
        assets=catalog.search(request.args.get("q", ""),include_deprecated=request.args.get("include_deprecated")=="true", **fields)
        if request.args.get('compact')=='1':
            from .views import asset_summary
            assets=[asset_summary(a) for a in assets]
        return jsonify(assets=assets)

    @app.post('/api/collections')
    def create_collection():
        from .collections import create
        return jsonify(create(catalog,**request.get_json()))

    @app.post('/api/collection-rename')
    def rename_collection():
        from .collections import rename
        return jsonify(rename(catalog,**request.get_json()))

    @app.post('/api/collection-assign')
    def assign_collection():
        from .collections import assign
        return jsonify(assign(catalog,**request.get_json()))

    @app.post('/api/collection-remove')
    def remove_collection():
        from .collections import remove_empty
        return jsonify(remove_empty(catalog,**request.get_json()))

    @app.post("/api/assets")
    def asset():
        return jsonify(catalog.create_asset(**request.get_json()))

    @app.post("/api/sets")
    def group():
        return jsonify(catalog.create_set(**request.get_json()))

    @app.post("/api/create-preview")
    def creation_preview():
        return jsonify(catalog.creation_preview(**request.get_json()))

    @app.post("/api/create-named")
    def create_named():
        return jsonify(catalog.create_named(**request.get_json()))

    @app.post("/api/append-set-asset")
    def append_set_asset():
        return jsonify(catalog.append_set_asset(**request.get_json()))

    @app.post("/api/edit-static-set")
    def edit_static_set():
        return jsonify(catalog.edit_static_set(**request.get_json()))

    @app.post("/api/import-sheet")
    @app.post("/api/import-static-set")
    def import_static_set():
        return jsonify(assets=catalog.import_static_set(**request.get_json()))

    @app.post("/api/rename")
    def rename():
        return jsonify(catalog.rename(**request.get_json()))

    @app.post("/api/spec")
    def specification():
        return jsonify(catalog.specification(**request.get_json()))

    @app.post("/api/source-spec")
    def bind_source_spec():
        return jsonify(catalog.bind_source_spec(**request.get_json()))

    @app.post("/api/prompts")
    def prompt():
        return jsonify(catalog.prompt(**request.get_json()))

    @app.post("/api/source")
    def source():
        file = request.files.get("file")
        require(file is not None, "Choose an image")
        value=catalog.upload(file.filename, file.read(), request.form["template_id"], request.form.get("set_id") or None, request.form.get("prompt_id") or None, spec_options=json.loads(request.form.get("spec_options") or "{}"))
        from .sheets import canonical_spec
        if value.get('frozen_spec'):value['import_spec']=canonical_spec(value['frozen_spec'])
        return jsonify(value)

    @app.post("/api/quick-preview")
    def quick_preview():
        from .workflow import prepare
        return jsonify(prepare(catalog,**request.get_json()))

    @app.post("/api/quick-confirm")
    def quick_confirm():
        from .workflow import confirm
        data=request.get_json()
        require("actor" not in data,"Approval actor is assigned by the authenticated adapter")
        return jsonify(confirm(catalog,**data,actor="authenticated_operator"))

    @app.post("/api/auto-locate")
    def auto_locate():
        return jsonify(catalog.auto_locate(**request.get_json()))

    @app.post("/api/plan")
    def plan():
        data = request.get_json()
        if data.pop("master", False):
            return jsonify(catalog.master_plan(data["source_id"], data.get("rect")))
        return jsonify(catalog.plan(**data))

    @app.post("/api/import")
    def import_asset():
        return jsonify(catalog.import_version(**request.get_json()))

    @app.post("/api/replace-frame")
    def replace_frame():
        return jsonify(catalog.replace_frame(**request.get_json()))

    @app.post("/api/review")
    def review():
        return jsonify(catalog.review(**request.get_json()))

    @app.post("/api/lifecycle-preview")
    def lifecycle_preview():
        return jsonify(catalog.lifecycle_prepare(**request.get_json()))

    @app.post("/api/lifecycle-confirm")
    def lifecycle_confirm():
        data=request.get_json();require(isinstance(data,dict) and "actor" not in data,"Approval actor is server-owned")
        return jsonify(catalog.lifecycle_apply(**data,actor="authenticated_operator"))

    @app.post("/api/deprecate")
    def deprecate_asset():
        return jsonify(catalog.deprecate_asset(**request.get_json()))

    @app.post("/api/select")
    def select():
        return jsonify(catalog.select(**request.get_json()))

    @app.post("/api/build")
    def build():
        return jsonify(catalog.build(**request.get_json()))

    @app.post("/api/publish")
    def publish():
        return jsonify(catalog.publish())

    @app.post("/api/delete-source")
    def delete_source():
        catalog.delete_source(**request.get_json()); return jsonify(ok=True)

    @app.post("/api/delete-build")
    def delete_build():
        catalog.delete_build(**request.get_json()); return jsonify(ok=True)

    @app.get("/api/registry")
    def registry():
        return jsonify(catalog.export_registry())

    @app.get("/file/<kind>/<key>/<int:version>/<int:frame>")
    def image(kind, key, version, frame):
        require(kind in ("source", "component", "runtime", "preview", "preview-runtime"), "Unknown file role")
        if kind == "source":
            record = catalog.get("source", key)
            path = catalog.path(record["file"])
        elif kind in ("preview","preview-runtime"):
            record=catalog.get("preview",key)
            require(record.get("lifecycle_status")!="retired","此预览已退出使用；原图已删除，历史记录仍保留。")
            require(0 <= version < len(record["items"]),"Unknown preview item")
            files=record["items"][version]["preview_files"]
            require(0 <= frame < len(files),"Unknown preview frame")
            file=files[frame] if kind=="preview" else files[frame].get("runtime_preview")
            require(file is not None,"No Runtime preview available")
            path=catalog.path(file["file"])
        else:
            asset = catalog.get("asset", key)
            value = catalog.version(asset, version)
            files = value["files"] if kind == "component" else (value["runtime"] or {}).get("files", [])
            require(0 <= frame < len(files), "Unknown frame")
            path = catalog.path(files[frame]["file"])
        require(path.is_file(), "Image missing from storage")
        return send_file(path, conditional=False)
    return app
