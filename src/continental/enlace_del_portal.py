"""El EAN que abre el portal (ticket 10 de la lista de espera).

Un clic en el EAN de la captura lo copia y además abre el portal de ese
proveedor en una pestaña nueva. **El servidor arma el enlace** y el navegador
solo lo abre: Continental no controla un navegador (regla 1 de `CLAUDE.md`), le
da una dirección a una persona. El navegador nunca arma la URL ni manda un
término (ADR 0026, punto 4): si lo hiciera, cualquier cosa escrita en la
pantalla podría terminar mandando a alguien a un sitio que Continental nunca
eligió.

Funciones puras: no tocan la red ni la base. La dirección viene de Doyle
(`GET /api/portales`), que es quien sabe cómo busca cada portal; aquí solo se
decide si se puede usar y qué se le dice a la persona.

Dos modos, y la diferencia importa para el título del botón:

- **`ya_buscado`**: el portal busca por dirección (NADRO, VICMA). La pestaña cae
  en el resultado del EAN y no hay que pegar nada.
- **`para_pegar`**: el portal busca por formulario (LEVIC). Se abre su página de
  búsqueda, el EAN ya va copiado, y se pega.

**Sin enlace no es un error** (reglas 4 y 5): el EAN se sigue copiando y el
título del botón dice por qué no se abre el portal. Nunca el texto de una
excepción.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from continental.doyle import PortalDeBusqueda
from continental.precios import nombre_del_proveedor

#: Donde la dirección de Doyle pone lo buscado. Puede aparecer más de una vez
#: (NADRO lo usa en la ruta y en `_q`).
MARCA_DEL_TERMINO = "{termino}"

YA_BUSCADO = "ya_buscado"
PARA_PEGAR = "para_pegar"

#: Por qué no hay enlace. Cada una es una frase para la persona, escrita aquí y
#: no en el JavaScript, y ninguna lleva texto de una excepción.
SIN_CLAVE = (
    "Este producto no tiene código de barras: no hay qué copiar ni qué buscar "
    "en el portal."
)
DOYLE_NO_RESPONDIO = "Doyle no respondió: solo se copia el código."


@dataclass(frozen=True, slots=True)
class EnlaceDelPortal:
    """Lo que el clic en el EAN de un renglón hace, ya decidido.

    `url` es `None` cuando no hay a dónde abrir, y entonces `modo` también lo
    es. `titulo` siempre dice qué va a pasar con el clic: lo que abre, o por qué
    solo se copia.
    """

    url: str | None
    modo: str | None
    titulo: str

    def como_json(self) -> dict:
        return {
            "enlace_del_portal": self.url,
            "modo_del_enlace": self.modo,
            "titulo_del_clic": self.titulo,
        }


def _sin_enlace(frase: str) -> EnlaceDelPortal:
    return EnlaceDelPortal(url=None, modo=None, titulo=frase)


def _se_puede_abrir(url: str, con_marca: bool) -> bool:
    """Si la dirección es `http(s)` con anfitrión y, cuando lleva la marca del
    término, ésta no cae en el anfitrión.

    Doyle es de confianza, pero esto es lo último que se mira antes de mandar a
    una persona a una dirección: un `javascript:` o un `data:` en esa
    configuración se abriría con los permisos de esta pantalla, y un término
    puesto en el anfitrión dejaría que el EAN cambiara a dónde se va.
    """
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return False
    return not (con_marca and MARCA_DEL_TERMINO in partes.netloc)


def armar_el_enlace(
    proveedor: str,
    clave: str,
    portales: Mapping[str, PortalDeBusqueda] | None,
) -> EnlaceDelPortal:
    """El enlace y el título del clic en el EAN de un renglón.

    `portales` es lo que Doyle contestó, o `None` si no contestó (que se dice
    distinto de «Doyle contestó y no tiene esa dirección»). `clave` es el EAN
    del renglón y va URL-encoded en cada aparición de `{termino}`.
    """
    nombre = nombre_del_proveedor(proveedor)
    if not clave:
        return _sin_enlace(SIN_CLAVE)
    if portales is None:
        return _sin_enlace(DOYLE_NO_RESPONDIO)

    portal = portales.get(proveedor)
    if portal is None or not portal.url_busqueda:
        return _sin_enlace(
            f"Doyle no tiene la dirección de búsqueda de {nombre}: solo se "
            "copia el código.",
        )

    url = portal.url_busqueda.strip()
    con_marca = MARCA_DEL_TERMINO in url
    # Una marca en una dirección que no busca por dirección es una
    # configuración incoherente: abrirla mandaría las llaves tal cual al portal.
    if (con_marca and not portal.busqueda_por_url) or not _se_puede_abrir(url, con_marca):
        return _sin_enlace(
            f"La dirección de {nombre} que dio Doyle no se puede abrir: solo "
            "se copia el código.",
        )

    if portal.busqueda_por_url and con_marca:
        return EnlaceDelPortal(
            url=url.replace(MARCA_DEL_TERMINO, quote(clave, safe="")),
            modo=YA_BUSCADO,
            titulo=f"Copiar y abrir la búsqueda en {nombre}",
        )
    return EnlaceDelPortal(
        url=url,
        modo=PARA_PEGAR,
        titulo=f"Copiar y abrir {nombre} para pegar",
    )
