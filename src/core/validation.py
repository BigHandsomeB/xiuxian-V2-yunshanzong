"""@module core/validation
@purpose Small Foundation errors and shared scalar validation.
@depends Python standard library
@usedBy data/registry, core/state/envelope, application/memory
@see ./INDEX.md
"""
import re
from uuid import UUID


class ValidationError(ValueError):
    """Malformed or unsupported Foundation input."""


class DuplicateError(ValidationError):
    """A definition identity was already registered."""


class ConflictError(Exception):
    """Request does not match the committed generation/revision/intent."""


class NotFoundError(LookupError):
    """An explicitly requested definition or command is unknown."""


def machine_id(value: str, field: str = 'machine_id') -> None:
    if not isinstance(value, str) or re.fullmatch(r'[a-z][a-z0-9_]*', value) is None:
        raise ValidationError(f'{field} must match [a-z][a-z0-9_]*')


def integer(value: int, field: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValidationError(f'{field} must be an integer >= {minimum}')


def schema_version(value: int, field: str) -> None:
    integer(value, field, 1)
    if value != 1:
        raise ValidationError(f'{field}: only schema version 1 is supported')


def text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValidationError(f'{field} must be a non-blank string without NUL')


def uuid4_id(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise ValidationError(f'{field} must be a canonical UUID4 string')
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValidationError(f'{field} must be a canonical UUID4 string') from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValidationError(f'{field} must be a canonical UUID4 string')
