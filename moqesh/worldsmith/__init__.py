"""Worldsmith: agente IA que CONSTRUYE y evoluciona el contenido inerte del World
y el pack de cebo, con una red de seguridad de inertness que nunca se salta.

Distinto de `moqesh/agent/` (el sensor remoto que reporta hits). Aquí el agente
PRODUCE ficheros estáticos; Moqesh los sirve como bytes y nunca los ejecuta.
"""

from .validate import (
    MAX_BINARY_BYTES,
    MAX_TEXT_BYTES,
    InertnessError,
    validate_file,
    validate_manifest,
    validate_tree,
)

__all__ = [
    "InertnessError",
    "MAX_BINARY_BYTES",
    "MAX_TEXT_BYTES",
    "validate_file",
    "validate_manifest",
    "validate_tree",
]
