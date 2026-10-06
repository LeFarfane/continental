"""El total en dinero de cada pedido, en la columna izquierda de la captura.

Antes la cifra del botón «Enviar» era `pedido.total_sin_iva`, la columna que
`partir` escribe **una vez**: descartar, devolver o ajustar una cantidad después
la dejaba enseñando lo que costaba hace un rato. El ticket 03 de la lista de
espera pide el total en la columna de la izquierda, y pide que sea **la misma
cifra** que la del botón. Dos sumas acaban por no cuadrar, así que hay una sola
función —`particion.el_total_del_pedido`— y las dos pantallas pintan lo que ella
dice.

Los niveles, como en `test_captura.py`:

1. **Lo puro**: la función, con y sin precios faltantes, con descartados y en
   espera.
2. **La ruta de punta a punta**: el campo `total` de cada pedido y que cambia
   cuando cambia el pedido, sin que nadie recargue.
3. **El texto del JavaScript**: la columna y el botón pintan lo del servidor y no
   suman en el navegador.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from conftest import cuerpo_de_funcion, pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    PedidoGuardado,
    PrecioDeProveedor,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    RENGLON_POSPUESTO,
    RenglonGuardado,
)
from continental.particion import el_total_del_pedido
from continental.precios import LecturaDePrecio, SESION_CADUCADA
from continental.sugerido import Renglon

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


# ------------------------------------------------------------- utilidades


def _renglon(
    renglon_id: int,
    estado: str = RENGLON_ABIERTO,
    cantidad: int = 3,
    pedido_id: int = 7,
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=renglon_id,
            clave=f"75010000{renglon_id:05d}",
            descripcion=f"PRODUCTO {renglon_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        descartado_por=CORREO if estado == RENGLON_DESCARTADO else None,
        descartado_en=ARMADO if estado == RENGLON_DESCARTADO else None,
        pospuesto_por=CORREO if estado == RENGLON_POSPUESTO else None,
        pospuesto_en=ARMADO if estado == RENGLON_POSPUESTO else None,
        pedido_id=pedido_id,
    )


def _pedido() -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=7,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor="nadro",
        proveedor_id=1,
        estado_declarado=BORRADOR,
        armado_en=ARMADO,
        # Guardado desde antes: la función NO debe leerlo.
        total_sin_iva=Decimal("999.99"),
    )


def _precio(renglon_id: int, precio: str | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor="nadro",
        consultado_en=ARMADO,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


# ==========================================================================
# LO PURO
# ==========================================================================


def test_el_total_suma_cantidad_por_precio_de_ese_proveedor():
    total = el_total_del_pedido(
        _pedido(),
        [_renglon(1, cantidad=2), _renglon(2, cantidad=3)],
        {1: [_precio(1, "10.00")], 2: [_precio(2, "100.50")]},
    )
    assert total.total == Decimal("321.50")
    assert total.hay is True
    assert total.sin_precio == 0
    assert total.dinero == "$321.50"
    assert total.frase == "$321.50"


def test_el_total_no_lee_la_columna_guardada_que_envejece():
    """`pedido.total_sin_iva` solo se reescribe al partir; la suma se hace con
    lo que el pedido tiene dentro ahora."""
    total = el_total_del_pedido(_pedido(), [_renglon(1, cantidad=1)], {1: [_precio(1, "5.00")]})
    assert total.total == Decimal("5.00")


def test_con_miles_el_dinero_lleva_coma():
    total = el_total_del_pedido(
        _pedido(), [_renglon(1, cantidad=1)], {1: [_precio(1, "1661.94")]}
    )
    assert total.dinero == "$1,661.94"


def test_un_renglon_sin_precio_no_se_suma_como_cero_y_se_dice_aparte():
    total = el_total_del_pedido(
        _pedido(),
        [_renglon(1, cantidad=1), _renglon(2), _renglon(3)],
        {1: [_precio(1, "1200.00")], 2: [_precio(2, None)]},
    )
    assert total.total is None
    assert total.hay is False
    assert total.dinero is None
    assert total.parcial == Decimal("1200.00")
    assert total.sin_precio == 2
    assert total.frase == "$1,200.00 + 2 sin precio"


def test_un_solo_renglon_sin_precio_va_en_singular_y_sin_precio_alguno_no_dice_cero():
    uno = el_total_del_pedido(
        _pedido(), [_renglon(1, cantidad=1), _renglon(2)], {1: [_precio(1, "10.00")]}
    )
    todos = el_total_del_pedido(_pedido(), [_renglon(1), _renglon(2)], {})
    assert uno.frase == "$10.00 + 1 sin precio"
    assert todos.frase == "2 sin precio"
    assert "$0" not in todos.frase


def test_descartados_y_en_espera_no_cuentan_ni_como_sin_precio():
    total = el_total_del_pedido(
        _pedido(),
        [
            _renglon(1, cantidad=1),
            _renglon(2, estado=RENGLON_DESCARTADO),
            _renglon(3, estado=RENGLON_POSPUESTO),
        ],
        {1: [_precio(1, "10.00")]},
    )
    assert total.total == Decimal("10.00")
    assert total.sin_precio == 0
    assert total.renglones == 1


def test_un_pedido_sin_renglones_que_contar_no_cuesta_cero():
    total = el_total_del_pedido(_pedido(), [_renglon(1, estado=RENGLON_POSPUESTO)], {})
    assert total.total is None
    assert total.hay is False
    assert total.frase == "sin renglones"


def test_solo_cuentan_los_renglones_que_cuelgan_de_ese_pedido():
    ajeno = _renglon(2, pedido_id=8)
    total = el_total_del_pedido(
        _pedido(),
        [_renglon(1, cantidad=1), ajeno],
        {1: [_precio(1, "10.00")], 2: [_precio(2, "99.00")]},
    )
    assert total.total == Decimal("10.00")


# ==========================================================================
# LA RUTA DE PUNTA A PUNTA
# ==========================================================================


def _poblar(almacen, cuantos: int) -> None:
    almacen.catalogo_en_memoria = [
        Producto(
            producto_id=n,
            clave=f"750100000{n:04d}",
            descripcion=f"PRODUCTO {n}",
            categoria="MEDICAMENTO",
            departamento="FARMACIA",
            anaquel="PATENTE 1",
            precio_lista_sin_iva=50.0,
            costo=30.0,
            existencia=0.0,
            esta_activo=True,
            es_granel=False,
        )
        for n in range(1, cuantos + 1)
    ]
    almacen.ventas_en_memoria = [
        LineaDeVenta(
            fecha=HOY, producto_id=n, cantidad=3, importe=30.0, costo=18.0, utilidad=12.0
        )
        for n in range(1, cuantos + 1)
    ]


def _lectura(precio: str | None) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor="nadro",
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


def _partida(cliente, almacen, almacenamiento, precios: list[str | None]) -> dict:
    _poblar(almacen, len(precios))
    lista = cliente.get(RUTA).json()
    for i, precio in enumerate(precios):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], [_lectura(precio)]
        )
    lista = cliente.get(RUTA).json()
    return cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()


def _firma():
    return {"Cf-Access-Authenticated-User-Email": CORREO}


def test_cada_pedido_trae_su_total_ya_dicho(cliente, almacen, almacenamiento):
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.50"])
    total = partida["pedidos"][0]["total"]
    # 3 piezas de cada uno: 30.00 + 61.50
    assert total["cifra"] == "91.50"
    assert isinstance(total["cifra"], str)
    assert total["dinero"] == "$91.50"
    assert total["hay"] is True
    assert total["sin_precio"] == 0
    assert total["frase"] == "$91.50"


def test_la_cifra_del_boton_y_la_de_la_columna_son_el_mismo_campo(
    cliente, almacen, almacenamiento
):
    """No hay dos campos con dos sumas: el servidor manda uno y las dos lo pintan."""
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    pedido = partida["pedidos"][0]
    assert pedido["total"]["cifra"] == pedido["total_sin_iva"] == "30.00"


def test_un_renglon_sin_precio_se_dice_aparte_en_la_respuesta(
    cliente, almacen, almacenamiento
):
    # Un renglón sin precio de nadie no se reparte solo: alguien tiene que
    # elegir a NADRO para que entre al pedido «con la marca de precio
    # desconocido» (la quinta casilla del ticket 20).
    _poblar(almacen, 2)
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_precios(
        NEGOCIO, lista["renglones"][0]["renglon_id"], [_lectura("10.00")]
    )
    sin_precio = lista["renglones"][1]["renglon_id"]
    almacenamiento.guardar_precios(NEGOCIO, sin_precio, [_lectura(None)])
    lista = cliente.get(RUTA).json()
    elegido = cliente.post(
        f"/api/renglon/{sin_precio}/proveedor", json={"proveedor": "nadro"}, headers=_firma()
    )
    assert elegido.status_code == 200, elegido.text
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    total = partida["pedidos"][0]["total"]
    assert total["cifra"] is None
    assert total["hay"] is False
    assert total["sin_precio"] == 1
    assert total["frase"] == "$30.00 + 1 sin precio"


def test_descartar_baja_el_total_en_la_respuesta_sin_recargar(
    cliente, almacen, almacenamiento
):
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    pedido = partida["pedidos"][0]
    assert pedido["total"]["cifra"] == "90.00"
    renglon = pedido["captura"]["lineas"][0]["renglon_id"]  # el de 10.00

    clave = str(pedido["pedido_id"])

    # Estas respuestas no traen los pedidos enteros: traen el total de cada uno.
    respuesta = cliente.post(f"/api/renglon/{renglon}/descartar", headers=_firma())
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["totales_de_los_pedidos"][clave]["cifra"] == "60.00"

    devuelta = cliente.post(f"/api/renglon/{renglon}/devolver", headers=_firma())
    assert devuelta.status_code == 200, devuelta.text
    assert devuelta.json()["totales_de_los_pedidos"][clave]["cifra"] == "90.00"


def test_corregir_la_cantidad_mueve_el_total(cliente, almacen, almacenamiento):
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    pedido = partida["pedidos"][0]
    renglon = pedido["captura"]["lineas"][0]["renglon_id"]

    respuesta = cliente.post(
        f"/api/renglon/{renglon}/cantidad", json={"cantidad": 5}, headers=_firma()
    )
    assert respuesta.status_code == 200, respuesta.text
    total = respuesta.json()["totales_de_los_pedidos"][str(pedido["pedido_id"])]
    assert total["cifra"] == "50.00"


def test_mandar_a_espera_saca_el_renglon_del_total(cliente, almacen, almacenamiento):
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    pedido = partida["pedidos"][0]
    renglon = pedido["captura"]["lineas"][0]["renglon_id"]

    respuesta = cliente.post(f"/api/renglon/{renglon}/posponer", headers=_firma())
    assert respuesta.status_code == 200, respuesta.text
    total = respuesta.json()["totales_de_los_pedidos"][str(pedido["pedido_id"])]
    assert total["cifra"] == "60.00"


# ==========================================================================
# EL TEXTO DEL JAVASCRIPT
# ==========================================================================


def test_la_columna_pinta_el_total_del_servidor_y_no_lo_suma():
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarPasoCaptura")
    # Pinta lo que el servidor dijo...
    assert "g.total" in cuerpo
    assert ".frase" in cuerpo
    # ... y el navegador no hace aritmética de dinero.
    for suma in ("reduce(", "parseFloat", "Number(", "toFixed(", "precio *"):
        assert suma not in cuerpo, f"La captura suma en el navegador: {suma!r}"


def test_al_mover_un_renglon_la_pantalla_sustituye_el_total_del_servidor():
    """Sin recargar: `aplicar` copia lo que llega por pedido y no suma nada."""
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const aplicar = (respuesta)")
    assert "respuesta.totales_de_los_pedidos" in cuerpo
    assert "p.total = nuevo" in cuerpo
    for suma in ("reduce(", "parseFloat", "Number(", "toFixed("):
        assert suma not in cuerpo


def test_el_boton_enviar_pinta_la_misma_cifra_del_servidor():
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarPasoCaptura")
    assert "guardado.total.dinero" in cuerpo
    assert "guardado.total_sin_iva" not in cuerpo


def test_el_pedido_fuera_de_la_particion_pinta_el_total_del_servidor():
    """Un pedido que se vació mandándolo a espera ya no está en la partición y
    se pinta desde el guardado: su `total_sin_iva` se escribió al partir y
    quedaría viejo. Va el `total` del servidor, con la columna como respaldo."""
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarParticion =")
    fuera = cuerpo[cuerpo.index("fueraDeLaParticion.forEach"):]
    assert "g.total ? g.total.frase" in fuera
    assert "g.total ? g.total.hay : g.hay_total" in fuera
