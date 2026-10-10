"""La lista de espera en el menú: una tarjeta por proveedor (ticket 11).

Todo lo que la pantalla pinta sale de aquí, hecho: qué renglones van arriba (el
pedido de hoy) y cuáles abajo (lo que espera), con el precio de hoy de **ese**
proveedor; qué botón se ofrece y por qué está apagado; el total y la barra hacia
el mínimo. El JavaScript pinta lo que llega y no suma, no compara ni conjuga
(regla de `CLAUDE.md`: la regla que decide algo no vive en el único archivo que
ninguna prueba de Python mira).

Funciones puras: no abren una base, no llaman a Doyle, no miran el reloj. Quien
llama (`web/app.py`) lee la lista, sus pedidos, los precios congelados y los
avisos del mínimo, y los pasa.

## Lo que decide el dueño (2026-10-06) y dónde se ve

1. **Una entrada del menú**, no una sección de la captura.
2. **El precio es el de hoy**: el último consultado de ese proveedor
   (`particion.la_linea_del_renglon`), no el que tenía al mandarse a espera. Sin
   precio dice «sin precio», jamás `$0.00`.
3. **La cabecera dice el total y la barra**; sin mínimo capturado, sin barra y la
   frase de `minimos.py`.
4. **Solo funciona después de repartir.** Antes dice que primero hay que repartir,
   con un botón a Repartir (`ir_a_repartir`). No se inventa un segundo reparto.
5. **Lo que esperó sin proveedor** va en una quinta tarjeta, con el selector de
   siempre (los cuatro proveedores, cada uno con su precio de hoy).
6. **No cambia el modelo de la espera**: lo que espera entra solo a la lista
   siguiente. Esta pantalla enseña la lista de hoy.

## Por qué un solo endpoint de lectura y no la lista del día

La lista del día (`/api/pedido-sugerido`) puede **escribir** (abre el día), carga
catálogo y ventas, y trae el detalle de cada renglón. Esta pantalla necesita
otra cosa —renglones agrupados por proveedor, con un precio que depende del
proveedor— y la agrupación es una regla; escrita en el navegador sería una regla
sin pruebas. Alternativa descartada: pintarla con la respuesta de la lista del
día y agrupar en el JavaScript.

## Por qué el globo del menú viene de la lista del día y no de aquí

El número del menú tiene que estar al abrir la página, antes de que nadie entre
a esta pantalla, y la lista del día ya se carga entonces y ya trae `pospuestos`
contado por el servidor. Pedir este endpoint al cargar solo para un número sería
una segunda lectura de lo mismo. Cuando se abre esta pantalla, el globo se
repinta con el `globo` de aquí.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from continental.almacenamiento import (
    ABIERTO,
    BORRADOR,
    CANCELADO,
    ENVIADO,
    PEDIDO_RECIBIDO,
    PEDIDO_RECIBIDO_PARCIAL,
    PedidoGuardado,
    PedidoSugeridoGuardado,
    PrecioDeProveedor,
    RenglonGuardado,
)
from continental.minimos import PROVEEDORES_CONOCIDOS
from continental.particion import (
    el_total_del_pedido,
    en_pesos,
    la_linea_del_renglon,
    total_como_json,
)
from continental.precios import nombre_del_proveedor
from continental.recepcion import PedidoALaVista
from continental.transiciones import (
    ELEGIR_PROVEEDOR_DE_LA_ESPERA,
    motivo_para_no_editar,
    motivo_para_no_mandar_el_pedido_a_espera,
)

# ---------------------------------------------------------------- las frases

FRASE_SIN_PRECIO = "sin precio"
FRASE_PRECIO_SIN_LEER = "precio sin leer"

#: Antes de repartir (decisión 4).
MOTIVO_SIN_REPARTIR = (
    "Primero hay que repartir la lista del día: la lista de espera se arma "
    "sobre los pedidos de cada proveedor."
)
MOTIVO_CERRADA_SIN_REPARTIR = (
    "La lista de hoy se cerró sin repartirse: no hay pedidos de hoy que ver aquí."
)
MOTIVO_SIN_LISTA = "La lista del día todavía no se abre. Ábrela desde «Lista del día»."
MOTIVO_SIN_VENTAS = "Todavía no hay ventas en el almacén, así que no hay lista del día."

#: Con la lista cerrada, la pantalla se ve entera y sin botones.
MOTIVO_LISTA_CERRADA = (
    "La lista ya está cerrada: aquí solo se ve. Lo que espera entra a la lista siguiente."
)

#: Un proveedor de la espera que Continental no conoce no se puede cambiar desde aquí.
MOTIVO_PROVEEDOR_DESCONOCIDO = (
    "viene de un proveedor que Continental no conoce: no se le elige otro desde aquí."
)

#: Las frases de los cinco estados que la pantalla enseña (ADR 0015). Tres se
#: declaran y dos se calculan de los renglones; la tarjeta dice los cinco.
_ESTADOS_DEL_PEDIDO = {
    BORRADOR: "En borrador",
    ENVIADO: "Enviado",
    CANCELADO: "Cancelado",
    PEDIDO_RECIBIDO: "Recibido",
    PEDIDO_RECIBIDO_PARCIAL: "Recibido parcial",
}


def el_estado_a_la_vista(
    pedido: PedidoGuardado | None, renglones_de_la_lista: Sequence[RenglonGuardado]
) -> str | None:
    """El estado que la tarjeta ENSEÑA, o `None` sin pedido. **Pura.**

    Sale de `recepcion.PedidoALaVista`, no de `estado_declarado`: un pedido
    enviado cuyos renglones ya llegaron se ve «Recibido». Lo que se DECIDE
    (si se puede mandar o sacar de la espera) sigue leyendo lo declarado.
    """
    if pedido is None:
        return None
    return PedidoALaVista.de(pedido, renglones_de_la_lista).estado


def frase_del_estado_del_pedido(
    pedido: PedidoGuardado | None, renglones_de_la_lista: Sequence[RenglonGuardado]
) -> str:
    """Cómo se llama el pedido de hoy de un proveedor, o que no hay. **Pura.**

    Enseña, no decide: usa el estado a la vista (`el_estado_a_la_vista`).
    """
    estado = el_estado_a_la_vista(pedido, renglones_de_la_lista)
    if estado is None:
        return "Sin pedido hoy"
    return _ESTADOS_DEL_PEDIDO.get(estado, estado)


def motivo_para_no_sacar(
    renglon: RenglonGuardado,
    lista: PedidoSugeridoGuardado,
    pedido: PedidoGuardado | None,
    proveedor: str,
) -> str | None:
    """Por qué «Sacar de la espera» va apagado, o `None` si se ofrece.

    Lo del renglón y la lista lo dice `transiciones.motivo_para_no_editar`, la
    misma función que contesta el 409. Lo del pedido es del ticket 04: la ruta
    de siempre **sí** deja sacar de la espera a un renglón cuyo pedido ya no es
    un borrador, pero lo deja sin repartir, y esta pantalla no ofrece eso:
    solo vuelve a un pedido que se puede seguir armando.
    """
    motivo = motivo_para_no_editar(renglon, lista, "devolver_pospuesto")
    if motivo is not None:
        return motivo
    nombre = nombre_del_proveedor(proveedor)
    if pedido is None:
        return (
            f"hoy no hay pedido de {nombre}: lo que espera entra a la lista "
            "siguiente."
        )
    if not pedido.es_borrador:
        return (
            f"el pedido de {nombre} de hoy ya no está en borrador (se envió o "
            "se canceló): lo que espera entra a la lista siguiente."
        )
    return None


def motivo_para_no_mandar(
    renglon: RenglonGuardado,
    lista: PedidoSugeridoGuardado,
    pedido: PedidoGuardado,
) -> str | None:
    """Por qué «Mandar a espera» va apagado, o `None` si se ofrece.

    El pedido (borrador, y su lista abierta) lo dice la misma función que el
    botón del pedido entero; el renglón (abierto, no tachado) y la lista, la que
    contesta el 409 del clic suelto.
    """
    motivo = motivo_para_no_mandar_el_pedido_a_espera(pedido.estado_declarado, lista.estado)
    if motivo is not None:
        return motivo
    return motivo_para_no_editar(renglon, lista, "posponer")


# ---------------------------------------------------------------- los renglones


def _precio(
    renglon: RenglonGuardado,
    proveedor: str,
    precios: Mapping[int, Sequence[PrecioDeProveedor]] | None,
) -> dict:
    """El precio de hoy de ese proveedor, dicho: cadena y frase, jamás un cero.

    `precios is None` es que no se pudieron leer: se dice, y no se pinta como
    «sin precio» (que afirmaría que nadie lo consultó).
    """
    if precios is None:
        return {"precio": None, "frase_del_precio": FRASE_PRECIO_SIN_LEER}
    linea = la_linea_del_renglon(renglon, proveedor, precios.get(renglon.renglon_id, ()))
    if linea.precio is None:
        return {"precio": None, "frase_del_precio": FRASE_SIN_PRECIO}
    return {"precio": str(linea.precio), "frase_del_precio": en_pesos(linea.precio)}


def _lo_comun(renglon: RenglonGuardado) -> dict:
    return {
        "renglon_id": renglon.renglon_id,
        "descripcion": renglon.propuesto.descripcion,
        "clave": renglon.propuesto.clave,
        "piezas": renglon.cantidad_a_pedir,
        "esta_capturado": renglon.esta_capturado,
    }


def _renglon_de_hoy(renglon, lista, pedido, proveedor, precios) -> dict:
    motivo = motivo_para_no_mandar(renglon, lista, pedido)
    return {
        **_lo_comun(renglon),
        **_precio(renglon, proveedor, precios),
        "accion": "mandar",
        "etiqueta": "Mandar a espera",
        "se_puede": motivo is None,
        "motivo_para_no": motivo,
    }


def _renglon_en_espera(renglon, lista, pedido, proveedor, precios) -> dict:
    motivo = motivo_para_no_sacar(renglon, lista, pedido, proveedor)
    return {
        **_lo_comun(renglon),
        **_precio(renglon, proveedor, precios),
        "accion": "sacar",
        "etiqueta": "Sacar de la espera",
        "se_puede": motivo is None,
        "motivo_para_no": motivo,
        "listas_en_espera": renglon.listas_en_espera,
    }


def _renglon_sin_proveedor(renglon, lista, precios) -> dict:
    """Uno que espera sin saber a quién se le iba a pedir: ofrece los cuatro.

    Cada opción trae el precio de hoy de ese proveedor, para elegir mirándolo.
    Un renglón cuyo proveedor de espera no es ninguno de los que Continental
    conoce no ofrece elegir —no hay a quién cambiárselo desde aquí— y lo dice.
    """
    if renglon.proveedor_de_la_espera is not None:
        motivo = MOTIVO_PROVEEDOR_DESCONOCIDO
    else:
        motivo = motivo_para_no_editar(renglon, lista, ELEGIR_PROVEEDOR_DE_LA_ESPERA)
    return {
        **_lo_comun(renglon),
        "accion": "elegir",
        "etiqueta": "Elegir proveedor",
        "se_puede": motivo is None,
        "motivo_para_no": motivo,
        "opciones": [
            {
                "proveedor": p,
                "nombre": nombre_del_proveedor(p),
                **_precio(renglon, p, precios),
            }
            for p in PROVEEDORES_CONOCIDOS
        ],
    }


# ------------------------------------------------------------- las tarjetas


def _frase_del_total(pedido, total, precios) -> str:
    if pedido is None:
        return "sin pedido hoy"
    if precios is None or total is None:
        return "total sin saber: no se pudieron leer los precios"
    return total.dinero if total.hay else total.frase


def _el_minimo(pedido: PedidoGuardado | None, avisos: Mapping[int, dict] | None) -> dict | None:
    """El aviso del mínimo de ese pedido, tal como lo armó `minimos.avisar_el_minimo`
    (con su `progreso`, el llenado de la barra).

    `None` cuando no hay pedido (la tarjeta lo dice) o cuando el aviso no se
    calculó: la pantalla no pinta barra ni frase, que no es lo mismo que «sin
    mínimo capturado».
    """
    if pedido is None or not avisos:
        return None
    return avisos.get(pedido.pedido_id)


def _tarjeta(
    proveedor: str,
    lista: PedidoSugeridoGuardado,
    pedido: PedidoGuardado | None,
    precios,
    avisos,
) -> dict:
    hoy = []
    if pedido is not None:
        hoy = [
            _renglon_de_hoy(r, lista, pedido, proveedor, precios)
            for r in lista.renglones
            if r.pedido_id == pedido.pedido_id
            and not (r.esta_descartado or r.esta_pospuesto)
        ]
    en_espera = [
        _renglon_en_espera(r, lista, pedido, proveedor, precios)
        for r in lista.renglones
        if r.esta_pospuesto and r.proveedor_de_la_espera == proveedor
    ]
    total = (
        None
        if pedido is None or precios is None
        else el_total_del_pedido(pedido, lista.renglones, precios)
    )
    return {
        "proveedor": proveedor,
        "nombre": nombre_del_proveedor(proveedor),
        "pedido_id": None if pedido is None else pedido.pedido_id,
        # Lo declarado (decide) y lo que se enseña (calculado, ADR 0015), por
        # separado, como `app.py`: `estado` y `estado_a_la_vista`.
        "estado_del_pedido": None if pedido is None else pedido.estado_declarado,
        "estado_a_la_vista": el_estado_a_la_vista(pedido, lista.renglones),
        "frase_del_pedido": frase_del_estado_del_pedido(pedido, lista.renglones),
        "total": None if total is None else total_como_json(total),
        "frase_del_total": _frase_del_total(pedido, total, precios),
        "minimo": _el_minimo(pedido, avisos),
        "hoy": hoy,
        "en_espera": en_espera,
    }


def la_lista_de_espera(
    lista: PedidoSugeridoGuardado,
    pedidos: Sequence[PedidoGuardado],
    precios: Mapping[int, Sequence[PrecioDeProveedor]] | None,
    avisos: Mapping[int, dict] | None,
) -> dict:
    """La pantalla entera, hecha. **Pura.**

    `precios` es lo congelado de la lista (`None` si no se pudo leer) y `avisos`
    `{pedido_id: aviso del mínimo}` (`None` si no se calcularon). Una lista que
    todavía no se reparte no trae tarjetas: trae el motivo y `ir_a_repartir`.
    """
    abierta = lista.estado == ABIERTO
    cuerpo = {
        "ok": True,
        "hay_lista": True,
        "pedido_sugerido_id": lista.pedido_sugerido_id,
        "fecha_del_pedido": lista.fecha_del_pedido.isoformat(),
        "estado": lista.estado,
        # El globo del menú: lo que espera de la lista ABIERTA.
        "globo": lista.pospuestos if abierta else 0,
        "en_espera_total": lista.pospuestos,
        "solo_lectura": not abierta,
        "motivo_solo_lectura": None if abierta else MOTIVO_LISTA_CERRADA,
        "repartida": bool(pedidos),
        "motivo": None,
        "ir_a_repartir": False,
        "proveedores": [],
        "sin_proveedor": [],
    }
    if not pedidos:
        cuerpo["motivo"] = MOTIVO_SIN_REPARTIR if abierta else MOTIVO_CERRADA_SIN_REPARTIR
        cuerpo["ir_a_repartir"] = abierta
        return cuerpo

    por_proveedor = {p.proveedor: p for p in pedidos}
    cuerpo["proveedores"] = [
        _tarjeta(p, lista, por_proveedor.get(p), precios, avisos)
        for p in PROVEEDORES_CONOCIDOS
    ]
    # Nada se cae de la pantalla (regla 4): lo que espera sin proveedor, o con
    # uno que Continental no conoce, va en la quinta tarjeta.
    cuerpo["sin_proveedor"] = [
        _renglon_sin_proveedor(r, lista, precios)
        for r in lista.renglones
        if r.esta_pospuesto and r.proveedor_de_la_espera not in PROVEEDORES_CONOCIDOS
    ]
    return cuerpo


def lista_que_no_hay(motivo: str) -> dict:
    """Cuando no hay lista que enseñar: ni error ni tarjetas, y se dice por qué."""
    return {
        "ok": True,
        "hay_lista": False,
        "globo": 0,
        "en_espera_total": 0,
        "solo_lectura": False,
        "motivo_solo_lectura": None,
        "repartida": False,
        "motivo": motivo,
        "ir_a_repartir": False,
        "proveedores": [],
        "sin_proveedor": [],
    }
