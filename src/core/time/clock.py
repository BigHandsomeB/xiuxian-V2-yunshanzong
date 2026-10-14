"""@module core/time/clock
@purpose Injectable wall-clock interface; system access lives only here.
@depends Python standard library
@usedBy application/memory, tests/core/test_settlement
@see ./INDEX.md
"""
from time import time_ns
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return time_ns() // 1_000_000
