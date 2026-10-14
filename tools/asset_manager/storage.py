"""Read-only asset workspace usage; no file content, link following or cleanup."""
import os, shutil, stat
from datetime import datetime, timezone
from pathlib import Path
from .model import require

LABELS = {"source":"原图", "master":"视觉基准", "components":"切块与预览", "runtime":"Runtime（含旧构建）", "metadata":"元数据与模板", "other":"其他文件"}

def usage(root, max_entries=100000):
    root=Path(root);require(not root.is_symlink() and root.is_dir(),"Unsafe asset workspace")
    require(type(max_entries) is int and 0<max_entries<=100000,"Invalid scan limit")
    groups={k:dict(category=k,name_zh=v,file_count=0,size_bytes=0,allocated_bytes=0) for k,v in LABELS.items()}
    root_stat=root.stat();groups["other"]["allocated_bytes"]=root_stat.st_blocks*512 if hasattr(root_stat,"st_blocks") else root_stat.st_size
    seen=set();pending=[(root,"other")];visited=skipped=duplicates=errors=0;partial=False;allocated_supported=True
    while pending and not partial:
        folder,category=pending.pop()
        if folder.is_symlink():skipped+=1;continue
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if visited>=max_entries:partial=True;break
                    visited+=1
                    try:
                        value=entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(value.st_mode):skipped+=1;continue
                        if not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):skipped+=1;continue
                        kind=category
                        if folder==root:
                            kind=entry.name if entry.name in ("source","master","components","runtime") else "metadata" if entry.name in ("registry","templates","manifest.json") else "other"
                        inode=(value.st_dev,value.st_ino)
                        if inode in seen:duplicates+=1;continue
                        seen.add(inode);group=groups[kind]
                        if hasattr(value,"st_blocks"):group["allocated_bytes"]+=value.st_blocks*512
                        else:group["allocated_bytes"]+=value.st_size;allocated_supported=False
                        if stat.S_ISDIR(value.st_mode):pending.append((Path(entry.path),kind))
                        else:group["file_count"]+=1;group["size_bytes"]+=value.st_size
                    except OSError:errors+=1
        except OSError:errors+=1
    volume=shutil.disk_usage(root)
    return dict(scanned_at=datetime.now(timezone.utc).isoformat(),file_count=sum(g["file_count"] for g in groups.values()),
                size_bytes=sum(g["size_bytes"] for g in groups.values()),allocated_bytes=sum(g["allocated_bytes"] for g in groups.values()),
                allocated_supported=allocated_supported,categories=list(groups.values()),volume=dict(total_bytes=volume.total,free_bytes=volume.free),
                skipped_links_or_special=skipped,duplicate_links=duplicates,scan_errors=errors,partial=partial or errors>0)
