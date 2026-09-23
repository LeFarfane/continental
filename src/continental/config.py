"""Lee la configuración: `config/continental.yml` más lo que venga de `.env`.

No toca la base ni la red. Lo que lleva contraseña vive solo en el entorno y
nunca en el YAML, que sí se versiona.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "continental.yml"


@dataclass(frozen=True)
class Modulo:
    """A dónde le pregunta Continental por un dato que no es suyo."""

    nombre: str
    url: str
    timeout_seg: float


@dataclass(frozen=True)
class Ajustes:
    negocio: str
    warehouse_url: str | None
    modulos: dict[str, Modulo]
    pedido: dict
    #: A quién le dice la pantalla que avise cuando algo falla y desde el
    #: navegador no hay nada más que hacer (ticket 29). Es una frase y no un
    #: nombre: "a quien administra atlas". Con valor por omisión para que un
    #: YAML sin la llave no deje ninguna falla sin su "a quién avisarle".
    a_quien_avisar: str = "a quien administra atlas"
    #: A dónde mandar el NAVEGADOR de la persona para que vea la ventana que
    #: Doyle abrió en su pantalla Xvfb. No es un módulo —Continental no le
    #: pregunta nada— y por eso no vive en `modulos`. `None` cuando el YAML no
    #: la trae, y entonces el botón de abrir sesión lo dice en vez de mandar a
    #: nadie a una ventana que no puede ver.
    visor_de_doyle: str | None = None


@lru_cache(maxsize=1)
def cargar() -> Ajustes:
    """Lee el YAML y el entorno. Se cachea: el archivo no cambia en caliente."""
    load_dotenv(RAIZ / ".env")

    if not CONFIG.exists():
        raise SystemExit(
            f"Falta {CONFIG}. Sin configuración no se arranca: adivinar a qué "
            f"puerto vive cada módulo sería justo el tipo de falla silenciosa "
            f"que este repo prohíbe."
        )

    crudo = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}

    modulos = {
        nombre: Modulo(
            nombre=nombre,
            url=str(datos["url"]).rstrip("/"),
            timeout_seg=float(datos.get("timeout_seg", 10)),
        )
        for nombre, datos in (crudo.get("modulos") or {}).items()
    }

    # EXACTAMENTE el mismo código que farmacia-data/config/farmacia.yml, clave
    # `codigo`. Marlowe perdió una tarde el 2026-09-05 por usar "farmacia" a
    # secas: el join salió vacío, sin error, y parecía una corrida exitosa.
    negocio = os.environ.get("CODIGO_NEGOCIO", "farmacia_01")

    return Ajustes(
        negocio=negocio,
        warehouse_url=os.environ.get("WAREHOUSE_URL"),
        modulos=modulos,
        pedido=crudo.get("pedido") or {},
        # Vacío o ausente es la frase por omisión, no una cadena vacía: una
        # falla que termina en "avísale ." no dice a quién.
        a_quien_avisar=str(crudo.get("a_quien_avisar") or "").strip()
        or "a quien administra atlas",
        # Vacía o ausente es `None` y no una cadena vacía: la pantalla
        # distingue "no hay visor configurado" de una dirección rota, y son
        # dos arreglos distintos.
        visor_de_doyle=str(crudo.get("visor_de_doyle") or "").strip() or None,
    )
