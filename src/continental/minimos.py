"""El mínimo del proveedor: lo que cada proveedor pide para surtir (ticket 08).

Funciones puras y un dato. Nada de aquí abre una base ni lee configuración; la
tabla es `pedidos.minimo_del_proveedor` (migración 0021) y la lectura y la
escritura viven en el almacenamiento.

## Las tres cosas que un proveedor puede estar diciendo, y por qué son tres

| En la tabla | Qué quiere decir | Cómo se dice |
|---|---|---|
| no hay fila | nadie lo ha capturado | «sin mínimo capturado» (gris) |
| `monto = 0` | el proveedor **no tiene** mínimo | «no tiene mínimo» |
| `monto > 0` | pide al menos eso, con o sin IVA | «$2,000.00 sin IVA» |

El primero **no es un cero**: un proveedor sin capturar dicho como cero se
leería «no tiene mínimo», y el aviso de «no llega» que el ticket 09 pinta no
saldría nunca (regla 4 de `CLAUDE.md`: sin dato, jamás un cero). Por eso la
ausencia es la ausencia de la fila y no un valor centinela.

## El monto es tal como lo dice el proveedor

Con o sin IVA, según él: `incluye_iva` viaja con el monto y no se convierte al
guardar. Convertirlo obligaría a quien lo captura a hacer la cuenta, que es la
resta entre cifras con y sin IVA que ya volteó una flecha en Marlowe
(enmienda del 2026-10-05 al ADR 0025, punto 7). **La comparación contra el
total del pedido es del ticket 09** y se hace en la base que diga el mínimo.

## La firma

`fijado_por` es el correo de Access: una firma, no un permiso (regla 3). Se
sobreescribe sin historial: lo que importa es el valor de hoy y quién lo puso.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor
from continental.transito import ZONA_DE_LA_FARMACIA, fecha_en_palabras

#: Los proveedores que Continental conoce: los mismos cuatro de Doyle, y el
#: mismo diccionario del que el puente y la comparación sacan su lista. Una
#: clave que no esté aquí no se captura (historia 41).
PROVEEDORES_CONOCIDOS: tuple[str, ...] = tuple(NOMBRES_DE_PROVEEDOR)

#: Lo más que cabe en `numeric(12, 2)`. Un monto mayor lo rechazaría la base
#: con un error que nadie sabría leer; aquí se dice con palabras.
MONTO_MAXIMO = Decimal("9999999999.99")

#: Los tres estados que viajan en la respuesta y que la pantalla pinta distinto.
SIN_CAPTURAR = "sin_capturar"
SIN_MINIMO = "sin_minimo"
CON_MINIMO = "con_minimo"

#: Las frases, hechas aquí y no en el JavaScript.
FRASE_SIN_CAPTURAR = "sin mínimo capturado"
FRASE_SIN_MINIMO = "no tiene mínimo"

#: Qué hacer ante un rechazo de la validación.
QUE_HACER_CON_EL_MINIMO = (
    "Corrige el dato y vuelve a guardar. Si el proveedor no tiene mínimo, escribe 0."
)


@dataclass(frozen=True, slots=True)
class MinimoDelProveedor:
    """Una fila de `pedidos.minimo_del_proveedor`.

    `fijado_en` lo pone la base con `now()`: quien guarda no lo manda, y lo que
    se lee siempre lo trae. El negocio no viaja en el objeto: es un argumento de
    cada llamada, como en el resto del almacenamiento (regla 7).
    """

    proveedor: str
    monto: Decimal
    incluye_iva: bool
    fijado_por: str
    fijado_en: dt.datetime | None = None


def revisar_el_minimo(columnas: dict) -> None:
    """Los `CHECK` de `pedidos.minimo_del_proveedor`, escritos en Python.

    Los llaman las dos implementaciones antes de escribir, igual que
    `revisar_la_prueba`: un doble permisivo deja el suite en verde y rebota en
    atlas.
    """
    if not columnas["negocio"]:
        raise ValueError("ck_minimo_negocio: un mínimo tiene que decir de qué negocio es.")
    if not columnas["proveedor"]:
        raise ValueError("ck_minimo_proveedor: un mínimo tiene que decir de qué proveedor es.")
    monto = columnas["monto"]
    if not isinstance(monto, Decimal) or not monto.is_finite() or monto < 0:
        raise ValueError(f"{monto!r} no es un monto: ck_minimo_monto pide un número de 0 en adelante.")
    if not isinstance(columnas["incluye_iva"], bool):
        raise ValueError("incluye_iva es sí o no, no un valor intermedio.")
    if not (columnas["fijado_por"] or "").strip():
        raise ValueError("ck_minimo_fijado_por: un mínimo se guarda con la firma de quien lo puso.")


# ------------------------------------------------------------ la validación


def leer_el_monto(crudo: Any) -> tuple[Decimal | None, str | None]:
    """`(monto, None)` o `(None, por_qué_no)`. Puro.

    Acepta un número o un texto que sea un número (con o sin `$` y comas, como
    lo escribe quien captura). Un `bool` **no** es un número aquí: es subclase
    de `int` y un `true` del JSON llegaría como 1. Se redondea a centavos con
    ROUND_HALF_UP, que es como se lee un precio.
    """
    if crudo is None or (isinstance(crudo, str) and not crudo.strip()):
        return None, "Falta el monto. Si el proveedor no tiene mínimo, escribe 0."
    if isinstance(crudo, bool):
        return None, "El monto tiene que ser un número, no un sí o un no."
    if isinstance(crudo, float):
        if not math.isfinite(crudo):
            return None, "El monto tiene que ser un número."
        crudo = repr(crudo)
    elif isinstance(crudo, int):
        crudo = str(crudo)
    elif isinstance(crudo, str):
        crudo = crudo.strip().replace(",", "").replace("$", "").replace(" ", "")
    else:
        return None, "El monto tiene que ser un número."
    try:
        monto = Decimal(crudo)
    except InvalidOperation:
        return None, "El monto tiene que ser un número, por ejemplo 2000 o 1500.50."
    if not monto.is_finite():
        return None, "El monto tiene que ser un número."
    if monto < 0:
        return None, "El monto no puede ser negativo. Si no tiene mínimo, escribe 0."
    monto = monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if monto > MONTO_MAXIMO:
        return None, "Ese monto es demasiado grande para ser el mínimo de un proveedor."
    return monto, None


def motivo_de_un_proveedor_desconocido(proveedor: str) -> str | None:
    """Por qué ese proveedor no se puede capturar, o `None` si sí."""
    if proveedor in PROVEEDORES_CONOCIDOS:
        return None
    conocidos = ", ".join(nombre_del_proveedor(p) for p in PROVEEDORES_CONOCIDOS)
    return f"Continental no conoce a ese proveedor. Los que conoce son: {conocidos}."


def revisar_lo_que_llega(
    proveedor: str, monto_crudo: Any, incluye_iva_crudo: Any
) -> tuple[Decimal | None, bool | None, str | None]:
    """`(monto, incluye_iva, None)` si todo está bien; `(None, None, motivo)` si no.

    El primer motivo que encuentre: proveedor, luego monto, luego la casilla.
    Una casilla que no es sí ni no se rechaza y no se toma por «no»: «incluye
    IVA» mal leído como falso compararía el mínimo contra el total equivocado.
    """
    motivo = motivo_de_un_proveedor_desconocido(proveedor)
    if motivo is not None:
        return None, None, motivo
    monto, motivo = leer_el_monto(monto_crudo)
    if motivo is not None:
        return None, None, motivo
    if not isinstance(incluye_iva_crudo, bool):
        return None, None, "Falta decir si el mínimo incluye IVA o no."
    return monto, incluye_iva_crudo, None


# ------------------------------------------------------------- las frases


def _pesos(valor: Decimal) -> str:
    return f"${valor:,.2f}"


def estado_del_minimo(minimo: MinimoDelProveedor | None) -> str:
    """`SIN_CAPTURAR`, `SIN_MINIMO` o `CON_MINIMO`."""
    if minimo is None:
        return SIN_CAPTURAR
    return SIN_MINIMO if minimo.monto == 0 else CON_MINIMO


def frase_del_minimo(minimo: MinimoDelProveedor | None) -> str:
    """Lo que vale hoy el mínimo, dicho como lo dijo el proveedor."""
    estado = estado_del_minimo(minimo)
    if estado == SIN_CAPTURAR:
        return FRASE_SIN_CAPTURAR
    if estado == SIN_MINIMO:
        return FRASE_SIN_MINIMO
    assert minimo is not None
    return f"{_pesos(minimo.monto)} {'con IVA' if minimo.incluye_iva else 'sin IVA'}"


def frase_de_quien_y_cuando(minimo: MinimoDelProveedor | None) -> str | None:
    """Quién lo puso y cuándo, en la hora de la farmacia. `None` si no hay fila."""
    if minimo is None or minimo.fijado_en is None:
        return None
    cuando = minimo.fijado_en
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=dt.UTC)
    local = cuando.astimezone(ZONA_DE_LA_FARMACIA)
    return f"Lo puso {minimo.fijado_por} {fecha_en_palabras(local.date())} a las {local:%H:%M}."


def un_minimo_como_json(proveedor: str, minimo: MinimoDelProveedor | None) -> dict:
    """Un proveedor como la pantalla lo lee. El monto viaja como cadena: el
    dinero no pasa por coma flotante ni para pintarse."""
    return {
        "proveedor": proveedor,
        "nombre": nombre_del_proveedor(proveedor),
        "estado": estado_del_minimo(minimo),
        "monto": None if minimo is None else str(minimo.monto),
        "incluye_iva": None if minimo is None else minimo.incluye_iva,
        "fijado_por": None if minimo is None else minimo.fijado_por,
        "fijado_en": None
        if minimo is None or minimo.fijado_en is None
        else minimo.fijado_en.isoformat(),
        "frase": frase_del_minimo(minimo),
        "frase_de_quien": frase_de_quien_y_cuando(minimo),
    }


def minimos_como_json(minimos: Mapping[str, MinimoDelProveedor]) -> list[dict]:
    """**Todos los proveedores conocidos, siempre**, con o sin fila: si solo
    salieran los capturados, uno sin capturar se vería como un proveedor que no
    existe, y no se podría capturar."""
    return [un_minimo_como_json(p, minimos.get(p)) for p in PROVEEDORES_CONOCIDOS]
