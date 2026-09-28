"""Cada consulta a los portales, guardada entera (2026-09-28).

Hasta aquí se guardaba **un** precio por proveedor y renglón —el que empareja
por EAN (`pedidos.precio_de_proveedor`, ADR 0004)— y se tiraba todo lo demás:
las otras filas que contestó cada portal, todo lo que trajo Buscar, y quién no
tenía el producto. El dueño pidió tomar cada consulta como una oportunidad:
**guardarlo todo, crudo, para después preguntarle en Metabase cómo se mueven
los precios de compra de cada proveedor**. Es el mismo criterio de "capturar
primero" de la enmienda del ADR 0001 y del snapshot diario de farmacia-data.

Una fila de `pedidos.lectura_de_portal` por **cada resultado** que devolvió un
portal (`posicion` 1..n), y **una fila por el proveedor que no trajo ninguno**
(`posicion` 0), con su resultado y su motivo: ése es "quién no tenía el
producto". No se empareja nada al guardar —eso lo hace quien consulte—, y el
precio se guarda dos veces: como llegó y como número cuando se puede leer, con
las mismas reglas de `precios.precio_a_numero` (nunca un cero).

Funciones puras: lo que contestó Doyle → filas. No tocan la red ni la base.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from continental.busqueda import motivo_del_proveedor
from continental.doyle import ESTADOS_PENDIENTES, EstadoDeBusqueda, RespuestaDeProveedor
from continental.precios import (
    SIN_RESULTADOS,
    existencia_a_numero,
    precio_a_numero,
    recortar_el_mensaje,
)

# ------------------------------------------------------------ de dónde vino

#: El lote de la noche, renglón por renglón.
LOTE = "lote"
#: La búsqueda con que el lote prueba las sesiones antes de empezar (ADR 0019).
SONDA_DEL_LOTE = "sonda del lote"
#: El botón «Consultar precio» de un renglón.
CONSULTAR = "consultar"
#: El botón «Completar lo que falta».
COMPLETAR = "completar"
#: La pestaña de Buscar.
BUSCAR = "buscar"
#: La consulta de la lista que dispara «Ya entré» en un portal (LEVIC).
AL_ABRIR_SESION = "al abrir sesión"

ORIGENES: tuple[str, ...] = (LOTE, SONDA_DEL_LOTE, CONSULTAR, COMPLETAR, BUSCAR, AL_ABRIR_SESION)

# ------------------------------------------------------ qué le pasó a cada uno

CON_RESULTADOS = "con resultados"
#: El portal buscó y no lo tiene: la respuesta a "quién no tenía el producto".
NO_LO_TIENE = "sin resultados"
#: El portal no contestó, la sesión caducó, una ventana abierta: no se sabe si
#: lo tiene. El motivo va al lado.
SIN_DATO = "sin dato"
#: Doyle todavía no sabe leer esa página (`modo: reconocimiento`).
NO_SE_SABE_LEER = "no se sabe leer"
#: Se acabó el tiempo con ese proveedor todavía buscando.
NO_TERMINO = "no terminó"

RESULTADOS: tuple[str, ...] = (CON_RESULTADOS, NO_LO_TIENE, SIN_DATO, NO_SE_SABE_LEER, NO_TERMINO)


@dataclass(frozen=True, slots=True)
class LecturaDePortal:
    """Una fila de `pedidos.lectura_de_portal`. `consultado_en` y `fecha` los
    pone la base al insertar: los dos del mismo reloj, en la misma sentencia."""

    origen: str
    termino: str
    trabajo: str
    proveedor: str
    resultado: str
    posicion: int
    renglon_id: int | None = None
    motivo: str | None = None
    detalle: str = ""
    total_en_el_portal: int = 0
    clave: str | None = None
    descripcion: str | None = None
    precio_como_llego: str | None = None
    precio: Decimal | None = None
    precio_publico_como_llego: str | None = None
    precio_publico: Decimal | None = None
    existencia_como_llego: str | None = None
    existencia: Decimal | None = None
    advertencia: str | None = None


def _resultado_sin_filas(respuesta: RespuestaDeProveedor, motivo: str | None) -> str:
    if respuesta.estado in ESTADOS_PENDIENTES:
        return NO_TERMINO
    if respuesta.estado == "reconocimiento":
        return NO_SE_SABE_LEER
    if motivo == SIN_RESULTADOS:
        return NO_LO_TIENE
    return SIN_DATO


def _texto(valor: str) -> str | None:
    """El texto tal como llegó, o `None` si llegó vacío: un `''` guardado se
    compara igual que un dato."""
    return valor.strip() or None


def lecturas_de_portal(
    estado: EstadoDeBusqueda,
    *,
    origen: str,
    termino: str,
    trabajo: str,
    renglon_id: int | None = None,
    incluir_pendientes: bool = False,
) -> list[LecturaDePortal]:
    """Lo que contestó cada proveedor, como filas.

    Solo los proveedores que **terminaron**: uno que sigue buscando no dijo
    nada todavía. Con `incluir_pendientes` —cuando la espera se cortó por el
    tope— los que no terminaron también dejan su fila, `no terminó`: que un
    portal tarde de más también es algo que se quiere medir.
    """
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido {origen!r}: son {ORIGENES}")

    filas: list[LecturaDePortal] = []
    for proveedor in sorted(estado.proveedores):
        respuesta = estado.proveedores[proveedor]
        pendiente = respuesta.estado in ESTADOS_PENDIENTES
        if pendiente and not incluir_pendientes:
            continue
        comun = dict(
            origen=origen,
            termino=termino,
            trabajo=trabajo,
            proveedor=proveedor,
            renglon_id=renglon_id,
            total_en_el_portal=respuesta.total,
        )
        if respuesta.estado == "listo" and respuesta.filas:
            for posicion, fila in enumerate(respuesta.filas, start=1):
                filas.append(LecturaDePortal(
                    **comun,
                    resultado=CON_RESULTADOS,
                    posicion=posicion,
                    clave=_texto(fila.clave),
                    descripcion=_texto(fila.descripcion),
                    precio_como_llego=_texto(fila.precio),
                    precio=precio_a_numero(fila.precio),
                    precio_publico_como_llego=_texto(fila.precio_publico),
                    precio_publico=precio_a_numero(fila.precio_publico),
                    existencia_como_llego=_texto(fila.existencia),
                    existencia=existencia_a_numero(fila.existencia),
                    advertencia=_texto(recortar_el_mensaje(fila.advertencia)),
                ))
            continue
        motivo = None if pendiente else motivo_del_proveedor(respuesta)
        filas.append(LecturaDePortal(
            **comun,
            resultado=_resultado_sin_filas(respuesta, motivo),
            posicion=0,
            motivo=motivo,
            detalle=recortar_el_mensaje(respuesta.mensaje),
        ))
    return filas
