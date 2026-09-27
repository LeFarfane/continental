"""La bitácora navegable: los vecinos de una lista y `GET .../dia/{fecha}` (2026-09-27).

El dueño decidió que las listas pasadas no desaparecen —se pueden revisar con
facilidad—, y que la pantalla nueva (otro agente, sobre lo que este ticket
deja) va a necesitar dos cosas para pintar las flechas de "día anterior" y
"día siguiente": **saber si existen** y **poder leerlas sin escribir nada**.

Este archivo prueba las dos piezas de datos y API que lo hacen posible:

- `almacenamiento.vecinos` y el campo `"vecinos"` que ya trae toda respuesta
  con una lista (`Vecinos` en `almacenamiento.py` explica por qué viajan con
  la lista y no por un endpoint de navegación aparte).
- `GET /api/pedido-sugerido/dia/{fecha}`, que **solo lee**: a diferencia de
  `GET /api/pedido-sugerido` (que abre el día si hace falta), esta ruta nunca
  arma ni escribe nada, y por eso puede pedir cualquier fecha pasada sin
  romper la ventana de reposición (que siempre ancla `hasta` en `max(fecha)`).

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt

from continental.almacen import DiaCalendario, LineaDeVenta, Producto
from continental.almacenamiento import CERRADO

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)


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


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def _dia(cliente, fecha: dt.date):
    return cliente.get(f"{RUTA}/dia/{fecha.isoformat()}")


# ============================================================ los vecinos


def test_la_lista_de_hoy_no_tiene_siguiente_pero_si_anterior(cliente, almacen):
    """`siguiente` es `None` para hoy por definición: no existe un día posterior
    a `max(fecha)`. `anterior` sí aparece en cuanto hay una lista de antes."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    lunes = _abrir(cliente)
    assert lunes["vecinos"] == {"anterior": None, "siguiente": None}

    almacen.ventas_en_memoria.append(_venta(MARTES))
    martes = _abrir(cliente)

    assert martes["vecinos"] == {"anterior": LUNES.isoformat(), "siguiente": None}


def test_un_vecino_vencido_sigue_contando_como_dia_con_lista(
    cliente, almacen, almacenamiento
):
    """Nada desaparece (decisión 2 del ticket): un vecino no se filtra por estado.

    Se fuerza `vencido` directo en el almacenamiento -la ruta ya no lo
    produce sola desde el cierre automático- para comprobar que `vecinos` no
    tiene un `WHERE estado = ...` escondido que se le haya colado.
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    _abrir(cliente)
    almacenamiento.vencer_las_de_dias_anteriores(NEGOCIO, MARTES)

    almacen.ventas_en_memoria.append(_venta(MARTES))
    martes = _abrir(cliente)

    assert martes["vecinos"]["anterior"] == LUNES.isoformat()


# ================================================= GET .../dia/{fecha}


def test_pide_un_dia_pasado_y_no_escribe_nada(cliente, almacen, almacenamiento):
    """Solo lee: pedir la lista de ayer por su fecha no crea ni modifica nada."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    lunes = _abrir(cliente)

    antes = len(almacenamiento.listas)
    respuesta = _dia(cliente, LUNES)
    despues = len(almacenamiento.listas)

    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] == lunes["pedido_sugerido_id"]
    assert cuerpo["estado"] == lunes["estado"]
    assert despues == antes, "Leer por fecha armó o escribió algo."


def test_la_lista_de_un_dia_cerrado_dice_quien_la_cerro(cliente, almacen):
    """`cerrado_por` y su frase viajan igual por esta ruta que por la de hoy."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    lunes = _abrir(cliente)
    cliente.post(
        f"{RUTA}/{lunes['pedido_sugerido_id']}/cerrar",
        headers={"Cf-Access-Authenticated-User-Email": "encargado@farmacia.mx"},
    )

    cuerpo = _dia(cliente, LUNES).json()

    assert cuerpo["estado"] == CERRADO
    assert cuerpo["cerrado_por"] == "encargado@farmacia.mx"
    assert "encargado@farmacia.mx" in cuerpo["frase_del_cierre"]


def test_una_lista_auto_cerrada_dice_que_se_cerro_sola(cliente, almacen):
    """`SISTEMA` se dice distinto de un correo: "se cerró sola", no "la cerró sistema"."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    _abrir(cliente)

    almacen.ventas_en_memoria.append(_venta(MARTES))
    _abrir(cliente)  # cierra sola la de lunes

    cuerpo = _dia(cliente, LUNES).json()

    assert cuerpo["estado"] == CERRADO
    assert cuerpo["cerrado_por"] == "sistema"
    assert "Se cerró sola" in cuerpo["frase_del_cierre"]


def test_una_fecha_sin_lista_y_sin_motivo_de_calendario_da_404(cliente, almacen):
    """Ni domingo ni festivo, y no hay lista: 404, sin fingir saber por qué.

    Puede ser una fecha futura, de antes de que Continental existiera, o un
    hueco real -- la ruta no distingue esos tres casos, y decir que sí sería
    inventar una explicación que los datos no dan (regla 4 de `CLAUDE.md`).
    """
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    _abrir(cliente)

    respuesta = _dia(cliente, dt.date(2099, 1, 1))

    assert respuesta.status_code == 404
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert "vecinos" in cuerpo


def test_un_domingo_sin_lista_dice_dia_sin_lista_y_no_404(cliente, almacen):
    """Domingo sin lista no es un hueco: es lo esperado, y se dice con su motivo."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    _abrir(cliente)

    domingo = dt.date(2026, 9, 13)  # el domingo antes del lunes de arriba
    cuerpo = _dia(cliente, domingo).json()

    assert cuerpo["ok"] is True
    assert cuerpo["dia_sin_lista"]["es_cerrado"] is True
    assert cuerpo["pedido_sugerido_id"] is None
    # La pantalla nueva (otro agente, sobre lo que este archivo deja) no
    # compone la frase: la pinta tal cual llega de
    # `fallas.frase_del_dia_sin_lista` (lección de los tickets 15 y 21).
    assert cuerpo["dia_sin_lista"]["frase"] == "Domingo: la farmacia no abre y no hay lista."


def test_un_festivo_entre_semana_sin_lista_tambien_dice_dia_sin_lista(
    cliente, almacen
):
    """La misma trampa de `test_dia_operable.py`, ahora del lado de la lectura."""
    miercoles_festivo = MIERCOLES
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    almacen.dias_en_memoria[miercoles_festivo] = DiaCalendario(
        fecha=miercoles_festivo,
        es_cerrado=False,
        es_festivo_oficial=True,
        nombre_evento="Independencia",
    )
    _abrir(cliente)

    cuerpo = _dia(cliente, miercoles_festivo).json()

    assert cuerpo["ok"] is True
    assert cuerpo["dia_sin_lista"]["nombre_evento"] == "Independencia"
    assert cuerpo["dia_sin_lista"]["frase"] == (
        "Independencia: día festivo. La farmacia no abre y no hay lista."
    )


def test_los_vecinos_de_un_dia_leido_por_fecha_se_calculan_igual(
    cliente, almacen
):
    """El día de en medio de tres ve al de antes y al de después, aunque no sea hoy."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    _abrir(cliente)
    almacen.ventas_en_memoria.append(_venta(MARTES))
    _abrir(cliente)
    almacen.ventas_en_memoria.append(_venta(MIERCOLES))
    _abrir(cliente)

    cuerpo = _dia(cliente, MARTES).json()

    assert cuerpo["vecinos"] == {
        "anterior": LUNES.isoformat(),
        "siguiente": MIERCOLES.isoformat(),
    }


# ============================================ lo pasado se navega, de solo
# ============================================ lectura, pero se puede reabrir
#
# Decisión 2 y 3 del dueño (2026-09-27, ADR 0020): un día pasado se ve por
# `GET .../dia/{fecha}` con su estado normal `cerrado` -no se descarta, no se
# ajusta cantidad, no se pide-, y la pantalla ofrece reabrirlo. Las dos cosas
# ya las calcula esta misma ruta -comparte `_respuesta_de_la_lista` con la de
# hoy-, y lo que prueban los dos casos de aquí es que le llegan igual de
# completas a la pantalla nueva por este camino como por el de siempre.


def test_un_dia_pasado_cerrado_no_se_deja_editar(cliente, almacen):
    """`se_puede_editar` en falso por renglón: la pantalla nueva no necesita
    adivinar el estado de la lista para saber que no hay nada que tocar."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    lunes = _abrir(cliente)
    cliente.post(f"{RUTA}/{lunes['pedido_sugerido_id']}/cerrar")

    cuerpo = _dia(cliente, LUNES).json()

    assert cuerpo["estado"] == CERRADO
    assert all(r["se_puede_editar"] is False for r in cuerpo["renglones"])

    # Y el servidor lo exige también, no solo lo declara: descartar un
    # renglón de esta lista pasada rebota con un 409, el mismo candado que
    # ya prueba `test_descarte.py` para una lista cerrada cualquiera.
    renglon_id = cuerpo["renglones"][0]["renglon_id"]
    rechazado = cliente.post(f"/api/renglon/{renglon_id}/descartar")
    assert rechazado.status_code == 409


def test_una_lista_cerrada_leida_por_fecha_ofrece_reabrir(cliente, almacen):
    """Solo lectura no quiere decir sin salida: el botón de reabrir viaja
    igual por esta ruta que por la de hoy (`cierre.reapertura`)."""
    almacen.catalogo_en_memoria = [_producto()]
    almacen.ventas_en_memoria = [_venta(LUNES)]
    lunes = _abrir(cliente)
    cliente.post(f"{RUTA}/{lunes['pedido_sugerido_id']}/cerrar")

    cuerpo = _dia(cliente, LUNES).json()

    assert cuerpo["reapertura"] is not None
    assert cuerpo["reapertura"]["se_puede"] is True
    assert cuerpo["reapertura"]["boton"]
