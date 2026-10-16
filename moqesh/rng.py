"""RNG determinista por (seed, path) — primitivo anti-fingerprint.

Deriva una secuencia pseudoaleatoria de `SHA-256(seed + "\\0" + path)` y la
extiende re-hasheando el estado. Propiedad clave:

- **Estable**: el mismo (seed, path) produce SIEMPRE la misma salida -> un nodo
  del laberinto no delata aleatoriedad entre peticiones.
- **Único por deployment**: otro seed cambia por completo nombres, rutas,
  tokens y banners -> dos instalaciones no comparten firma estática.

No es un RNG de propósito criptográfico; es un generador determinista reproducible.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

_UINT_MAX = 0xFFFFFFFF
_HEX = "0123456789abcdef"
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


class SeededRandom:
    """Flujo determinista de bytes derivado de (seed, path)."""

    __slots__ = ("_state", "_pos")

    def __init__(self, seed: str, path: str) -> None:
        self._state = hashlib.sha256(f"{seed}\x00{path}".encode()).digest()
        self._pos = 0

    def _byte(self) -> int:
        if self._pos >= len(self._state):
            self._state = hashlib.sha256(self._state).digest()
            self._pos = 0
        b = self._state[self._pos]
        self._pos += 1
        return b

    def _u32(self) -> int:
        v = 0
        for _ in range(4):
            v = ((v << 8) | self._byte()) & _UINT_MAX
        return v

    def below(self, n: int) -> int:
        """Entero en [0, n)."""
        return 0 if n <= 1 else self._u32() % n

    def between(self, lo: int, hi: int) -> int:
        """Entero en [lo, hi)."""
        return lo + self.below(hi - lo)

    def real(self) -> float:
        """Flotante en [0, 1]."""
        return self._u32() / _UINT_MAX

    def chance(self, p: float) -> bool:
        return self.real() < p

    def pick(self, items: Sequence[T]) -> T:
        return items[self.below(len(items))]

    def hex(self, length: int) -> str:
        return "".join(_HEX[self.below(16)] for _ in range(length))

    def alnum(self, length: int) -> str:
        return "".join(_ALNUM[self.below(len(_ALNUM))] for _ in range(length))
