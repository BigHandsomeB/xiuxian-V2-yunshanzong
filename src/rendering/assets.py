"""@module rendering/assets
@purpose Read approved Runtime Manifest only; no Catalog, Source or manager service.
@depends pathlib/json/hashlib/urllib; @usedBy playable composition and tests
@see ./INDEX.md
"""
import hashlib, json, re
from pathlib import Path
from urllib.parse import quote


class RuntimeAssets:
    def __init__(self,root):self.root=Path(root).resolve()

    def snapshot(self):
        path=self.root/'manifest.json'
        try:
            if path.is_symlink() or path.stat().st_size>2*1024*1024:return {}
            doc=json.loads(path.read_text())
            if doc.get('schema_version')!=1 or type(doc.get('assets')) is not dict:return {}
            return doc['assets']
        except (OSError,ValueError,AttributeError):return {}

    def resolve(self,asset_id,manifest=None):
        if not isinstance(asset_id,str) or re.fullmatch(r'[a-z][a-z0-9_.]*',asset_id) is None:return None
        manifest=self.snapshot() if manifest is None else manifest
        try:
            row=manifest[asset_id];files=row['files']
            # Only a single-frame still image is used in this slice; no guessed sprite frame.
            if len(files)!=1:return None
            frame=files[0];path=self.root/frame['file'];resolved=path.resolve()
            runtime=(self.root/'runtime').resolve()
            if (not runtime.is_relative_to(self.root) or path.is_symlink() or
                any(p.is_symlink() for p in path.parents if p.is_relative_to(self.root)) or
                not resolved.is_relative_to(runtime) or not resolved.is_file() or resolved.suffix.lower() not in ('.png','.webp','.jpg','.jpeg') or
                resolved.stat().st_size>13*1024*1024):return None
            width,height=frame['width'],frame['height'];digest=frame['sha256']
            if (type(width) is not int or type(height) is not int or min(width,height)<1 or
                not isinstance(digest,str) or re.fullmatch('[a-f0-9]{64}',digest) is None):return None
            return {'asset_id':asset_id,'width':width,'height':height,'version':row['version'],
                    'url':'/play/runtime/'+quote(asset_id,safe='')+'/'+digest,'digest':digest,'path':resolved}
        except (KeyError,TypeError,ValueError,OSError):return None

    def file(self,asset_id,digest):
        row=self.resolve(asset_id)
        if row is None or row['digest']!=digest:return None
        try:
            if hashlib.sha256(row['path'].read_bytes()).hexdigest()!=digest:return None
            return row['path']
        except OSError:return None
