"""Project-local file writes with traversal and final symlink protection."""
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def guard(target):
    target = Path(target)
    if not target.is_absolute():
        target = PROJECT / target
    resolved = target.resolve()
    if not resolved.is_relative_to(PROJECT):
        raise RuntimeError('Output outside project write boundary')
    if resolved.exists() and (not resolved.is_file() or resolved.stat().st_nlink != 1):
        raise RuntimeError('Target must be a single-link regular file')
    return resolved


def write(target, text):
    resolved = guard(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved = guard(target)
    fd = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(text)

