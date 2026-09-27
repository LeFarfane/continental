"""No hay lista los domingos ni los días festivos (decisión del dueño, 2026-09-27).

Existe porque la trampa es real y está medida en el ticket: `es_cerrado` de
`marts.dim_fecha` **solo marca domingos** — el 16 de septiembre de 2026
(Independencia) tuvo cero ventas y `es_cerrado = f`, porque el festivo se ve
en `es_festivo_oficial`, no ahí. En la práctica esto casi nunca se dispara por
el camino ordinario: la farmacia no ha vendido nada en domingo en 33 meses, y
un festivo cerrado se ve exactamente igual (cero ventas, así que
`ultima_fecha_con_ventas()` nunca aterriza ahí). Lo que estas pruebas cubren es
el caso anómalo — una venta con fecha de domingo o de festivo— para que, si
alguna vez pasa, ninguna lista quede fechada ahí.

**Nunca se deduce "cerrado" de "sin ventas".** `DiaCalendario.es_dia_sin_lista`
solo mira las dos banderas del calendario (`es_cerrado`, `es_festivo_oficial`);
lo tercero -datos que todavía no llegan- no vive aquí y no se confunde con
esto en ningún punto del código (ver `fallas.estado_de_las_ventas`, que sí
distingue esa tercera posibilidad para la casilla de frescura).

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt

from continental.almacen import DiaCalendario, LineaDeVenta, Producto
from continental.dobles import AlmacenamientoFalso, AlmacenFalso, DoyleFalso
from continental.lote import SIN_LISTA, correr_el_lote

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"

#: 2026-09-20 es domingo de verdad (comprobado contra el calendario).
UN_DOMINGO = dt.date(2026, 9, 20)
#: 2026-09-16 es un miércoles: entre semana, y por eso es el caso que
#: `es_cerrado` no puede ver por sí solo.
INDEPENDENCIA = dt.date(2026, 9, 16)


def _venta(fecha: dt.date, producto_id: int = 1, cantidad: float = 1) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha, producto_id=producto_id, cantidad=cantidad,
        importe=cantidad * 10.0, costo=cantidad * 6.0, utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int = 1) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=10.0,
        esta_activo=True,
        es_granel=False,
    )


# ============================================================ la ruta


def test_un_domingo_con_una_venta_anomala_no_arma_lista(cliente, almacen):
    """El caso defensivo: `ultima_fecha_con_ventas()` aterriza en domingo.

    En 33 meses no ha pasado -CLAUDE.md- pero si algún día una venta se
    captura con esa fecha (una devolución tardía, un error de captura), la
    lista no se arma con esa fecha: `AlmacenFalso.dia()` marca domingo por
    `weekday()`, igual que `dim_fecha.es_cerrado` en producción.
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(UN_DOMINGO)]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] is None
    assert cuerpo["dia_sin_lista"]["fecha"] == UN_DOMINGO.isoformat()
    assert cuerpo["dia_sin_lista"]["es_cerrado"] is True
    assert cuerpo["dia_sin_lista"]["es_festivo_oficial"] is False


def test_un_festivo_entre_semana_tampoco_arma_lista_aunque_es_cerrado_no_lo_vea(
    cliente, almacen
):
    """La trampa exacta del ticket: festivo entre semana, `es_cerrado` en falso.

    Independencia es un miércoles en 2026: `weekday() != 6`, así que si el
    código solo mirara `es_cerrado` -como hace `fallas.estado_de_las_ventas`
    hoy, con su propio `_DOMINGO`- esto pasaría de largo. `almacen.dia` trae
    la segunda bandera aparte, y por eso sí lo detiene.
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(INDEPENDENCIA)]
    almacen.dias_en_memoria[INDEPENDENCIA] = DiaCalendario(
        fecha=INDEPENDENCIA,
        es_cerrado=False,
        es_festivo_oficial=True,
        nombre_evento="Independencia",
    )

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] is None
    assert cuerpo["dia_sin_lista"]["es_cerrado"] is False
    assert cuerpo["dia_sin_lista"]["es_festivo_oficial"] is True
    assert cuerpo["dia_sin_lista"]["nombre_evento"] == "Independencia"


def test_un_dia_ordinario_arma_lista_igual_que_siempre(cliente, almacen):
    """El caso de todos los días: ni domingo ni festivo, se arma como siempre.

    Sin esto, una prueba que solo mide "no arma en domingo" no distingue un
    guardia correcto de uno que nunca deja armar nada.
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 21))]  # lunes

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] is not None
    assert "dia_sin_lista" not in cuerpo


def test_si_el_calendario_no_se_pudo_leer_la_lista_se_arma_igual(cliente, almacen):
    """Fallar abierto: sin poder saber si es festivo, se arma la lista igual.

    Bloquear el pedido del día entero porque una lectura lateral (¿es
    festivo?) se cayó sería peor que el problema que el guardia intenta
    prevenir -sería la falla silenciosa que la regla 4 de `CLAUDE.md`
    prohíbe, solo que en la dirección contraria-. El motivo queda en la
    bitácora del servidor, nunca en la respuesta (regla 5).
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 21))]

    original = almacen.dia

    def falla(fecha):
        raise RuntimeError("el almacén no contestó")

    almacen.dia = falla  # type: ignore[method-assign]
    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] is not None, (
        "Un guardia que no se pudo evaluar tumbó la lista del día."
    )


def test_las_fechas_comerciales_no_cuentan_como_dia_sin_lista(cliente, almacen):
    """San Valentín, Día de las Madres: la farmacia abre, solo vende distinto.

    `es_dia_sin_lista` mira `es_cerrado` y `es_festivo_oficial`, nunca
    `es_fecha_comercial` — confundir las dos apagaría el pedido de días que en
    realidad son de los que más venden.
    """
    fecha = dt.date(2026, 5, 11)  # lunes cercano al Día de las Madres
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(fecha)]
    almacen.dias_en_memoria[fecha] = DiaCalendario(
        fecha=fecha, es_cerrado=False, es_festivo_oficial=False, nombre_evento=None
    )

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] is not None


# ============================================================ el lote


def test_el_lote_no_arma_lista_en_domingo_ni_festivo():
    """El mismo guardia, del lado del lote nocturno (ticket 18).

    `SIN_LISTA` es el final que ya existía para "no hubo ventas": se reusa
    aquí porque desde el punto de vista del lote es exactamente lo mismo — no
    se armó lista esta corrida, y no es un error.
    """
    almacen = AlmacenFalso()
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(INDEPENDENCIA)]
    almacen.dias_en_memoria[INDEPENDENCIA] = DiaCalendario(
        fecha=INDEPENDENCIA,
        es_cerrado=False,
        es_festivo_oficial=True,
        nombre_evento="Independencia",
    )
    almacenamiento = AlmacenamientoFalso()

    resumen = correr_el_lote(
        almacen=almacen,
        almacenamiento=almacenamiento,
        doyle=DoyleFalso(),
        negocio=NEGOCIO,
        tope_seg=3600.0,
        tope_por_consulta_seg=120.0,
        cada_seg=1.0,
        dormir=lambda _s: None,
        ahora=lambda: 0.0,
    )

    assert resumen.final == SIN_LISTA
    assert "Independencia" in resumen.detalle
    assert almacenamiento.listas == []
