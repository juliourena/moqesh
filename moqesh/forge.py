"""Forja de binarios señuelo con credenciales embebidas.

Estrategia (elegida para evitar dependencia de .NET en runtime): se parte de una
**plantilla .NET DLL pre-forjada offline** (ver `tools/build_template_dll.md`) que
contiene literales-placeholder de ancho fijo; en runtime se **parchean los bytes**
(UTF-16LE del heap de strings) con los valores reales del deployment, sin recompilar.
El resultado es un DLL .NET válido y decompilable (dnSpy/ILSpy).

Si la plantilla no está presente (p.ej. entorno sin el artefacto), se degrada a un
binario señuelo con cabecera PE y las credenciales embebidas en claro: un agente que
lo descargue y haga `strings`/decompile igualmente encuentra el cebo. Nunca rompe.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("moqesh.forge")

# Plantilla por defecto (si existe). Generable offline con el build de .NET.
_DEFAULT_TEMPLATE = os.path.join(os.path.dirname(__file__), "assets", "portal_template.dll")

# Literales-placeholder de ancho fijo que debe contener la plantilla (ASCII).
# El parcheo respeta exactamente su longitud para no desplazar metadata del PE.
_PLACEHOLDERS = {
    "connection_string": "MQCONN__" + "0" * 120,  # 128 chars
    "internal_api_base": "MQAPI__" + "0" * 57,  # 64 chars
    "bearer_token": "MQBEARER__" + "0" * 118,  # 128 chars
}
_B62 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


@dataclass(frozen=True)
class ForgeInput:
    assembly_name: str
    namespace: str
    connection_string: str
    internal_api_base: str
    bearer_token: str


def _safe_name(s: str) -> str:
    cleaned = "".join(c for c in (s or "") if c.isalnum() or c == ".")
    return cleaned or "Portal"


def _pad(value: str, width: int, salt: bytes) -> str:
    """Ajusta `value` a `width` chars: trunca si sobra, o rellena con base62
    derivado del salt (parece un secreto más largo; el marcador real queda de prefijo)."""
    if len(value) >= width:
        return value[:width]
    need = width - len(value)
    fill = "".join(_B62[b % len(_B62)] for b in hashlib.sha256(salt).digest())
    while len(fill) < need:
        fill += "".join(_B62[b % len(_B62)] for b in hashlib.sha256(fill.encode()).digest())
    return value + fill[:need]


class AssemblyForge:
    """Forja DLLs señuelo parcheando una plantilla; cachea por clave."""

    def __init__(self, template_path: str | None = None) -> None:
        self._template_path = template_path or _DEFAULT_TEMPLATE
        self._cache: dict[str, bytes] = {}
        self._warned = False

    def forge(self, cache_key: str, inp: ForgeInput) -> tuple[bytes, str]:
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build(cache_key, inp)
        filename = _safe_name(inp.assembly_name)
        if not filename.lower().endswith(".dll"):
            filename += ".dll"
        return self._cache[cache_key], filename

    def _build(self, cache_key: str, inp: ForgeInput) -> bytes:
        template = self._load_template()
        if template is not None:
            return self._patch(template, cache_key, inp)
        if not self._warned:
            logger.warning(
                "Plantilla DLL ausente (%s): se sirve binario señuelo PE con credenciales "
                "embebidas. Genera la plantilla offline para un DLL .NET decompilable.",
                self._template_path,
            )
            self._warned = True
        return self._decoy_pe(cache_key, inp)

    def _load_template(self) -> bytes | None:
        try:
            with open(self._template_path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def _patch(self, template: bytes, cache_key: str, inp: ForgeInput) -> bytes:
        buf = bytearray(template)
        values = {
            "connection_string": inp.connection_string,
            "internal_api_base": inp.internal_api_base,
            "bearer_token": inp.bearer_token,
        }
        for field_name, placeholder in _PLACEHOLDERS.items():
            value = _pad(values[field_name], len(placeholder), f"{cache_key}:{field_name}".encode())
            needle = placeholder.encode("utf-16-le")
            repl = value.encode("utf-16-le")
            i = buf.find(needle)
            if i >= 0 and len(repl) == len(needle):
                buf[i : i + len(needle)] = repl
            else:
                logger.debug("Placeholder '%s' no encontrado en la plantilla; se omite.", field_name)
        return bytes(buf)

    @staticmethod
    def _decoy_pe(cache_key: str, inp: ForgeInput) -> bytes:
        h = hashlib.sha256(cache_key.encode()).digest()
        size = 8192 + h[0] * 32
        buf = bytearray(size)
        # Cabecera DOS/PE plausible (file(1) la reconoce como ejecutable PE, no ELF).
        buf[0:2] = b"MZ"
        buf[0x3C:0x40] = (0x80).to_bytes(4, "little")  # e_lfanew -> offset del PE
        buf[0x80:0x84] = b"PE\x00\x00"
        for i in range(0x84, size):
            buf[i] = h[i % len(h)]
        # Credenciales embebidas en claro (recuperables con `strings`/decompilación).
        blob = (
            "\x00AppConfig\x00ConnectionString\x00"
            + inp.connection_string
            + "\x00InternalApiBase\x00"
            + inp.internal_api_base
            + "\x00ServiceToken\x00"
            + inp.bearer_token
            + "\x00"
        ).encode("utf-8", "ignore")
        off = 0x200
        buf[off : off + len(blob)] = blob
        return bytes(buf)
