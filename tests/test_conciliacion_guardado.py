"""La conciliación diaria (2026-09-27): lo que se guarda al confirmar el lote.

**El seam de "lo que se guarda"**, la segunda mitad de la costura de siempre
(`test_conciliacion.py` es la pura). Aquí se comprueba lo que
`almacenamiento.AlmacenamientoDelPedido.confirmar_la_conciliacion` deja en el
doble en memoria, con las MISMAS condiciones que su SQL real:

- **El pedido retroactivo se crea aunque la lista ya esté cerrada.** Es el
  caso normal: la conciliación corre después de la cadena nocturna, sobre una
  lista que casi siempre ya se cerró sola (ADR 0020) — al revés que partir un
  pedido a mano, que sí exige la lista abierta.
- **Se reutilizan `enviar_el_pedido`, `confirmar_la_recepcion` y
  `recibir_parcial_con_compras` sin tocar.** Lo que prueba este archivo no es
  esa lógica otra vez —ya tiene sus pruebas en `test_envio.py`, `test_parcial.py`
  y `test_recepcion.py`—, es que la conciliación **encadena** las piezas bien:
  crea el pedido, mete el renglón, lo envía, y confirma con la evidencia
  correcta.
- **La firma dice que se dedujo**, no que alguien lo capturó en el portal ni
  que alguien juzgó una evidencia en la pantalla de recepción normal.
- **No es todo o nada**: una decisión que ya no calificó no tira las demás.
"""

from __future__ import annotations

import datetime as dt

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    CERRADO,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    RenglonPorConciliar,
)

NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
RUTA = "/api/pedido-sugerido"


def _producto(producto_id: int, clave: str, existencia: float = 0.0) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="",
        departamento="",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=100.0,
        costo=80.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha, producto_id=producto_id, cantidad=cantidad, importe=0.0, costo=0.0, utilidad=0.0
    )


def _armar_una_lista(cliente, almacen, *, dia: dt.date, producto_id: int = 1, cantidad: int = 5):
    """Una lista de un solo renglón, a través de la ruta real (como en
    `test_guardado.py`): es la manera de que el doble quede en el mismo
    estado que dejaría la app de verdad, sin repetir a mano la forma de sus
    filas."""
    almacen.catalogo_en_memoria = [_producto(producto_id, f"750100000{producto_id:04d}")]
    almacen.ventas_en_memoria = [_venta(dia, producto_id, cantidad)]
    almacen.dias_en_memoria = {}
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True
    renglon_id = cuerpo["renglones"][0]["renglon_id"]
    return cuerpo["pedido_sugerido_id"], renglon_id


class TestConfirmarLaConciliacion:
    def test_crea_el_pedido_retroactivo_aunque_la_lista_ya_este_cerrada(
        self, cliente, almacen, almacenamiento
    ):
        dia = dt.date(2024, 3, 5)
        pedido_sugerido_id, renglon_id = _armar_una_lista(cliente, almacen, dia=dia, cantidad=5)

        # La lista ya se cerró -el caso normal: la conciliación corre días
        # después, y ADR 0020 la cierra sola al abrirse la siguiente-.
        almacenamiento.listas[0]["estado"] = CERRADO

        decision = RenglonPorConciliar(
            renglon_id=renglon_id,
            proveedor="nadro",
            proveedor_id=1,
            compras=(9001,),
            piezas=5.0,
            piezas_pedidas=5,
        )
        resultado = almacenamiento.confirmar_la_conciliacion(
            NEGOCIO, pedido_sugerido_id, [decision], CORREO
        )

        assert resultado.confirmados == 1
        assert resultado.fallidos == ()

        (pedido,) = almacenamiento.pedidos_de_la_lista(NEGOCIO, pedido_sugerido_id)
        assert pedido.proveedor == "nadro"
        assert pedido.estado_declarado == ENVIADO
        assert pedido.enviado_por == f"{CORREO} (conciliación: deducido de una compra)"

        lista = almacenamiento.leer_por_id(NEGOCIO, pedido_sugerido_id)
        (renglon,) = lista.renglones
        assert renglon.estado == RENGLON_RECIBIDO
        assert renglon.recibido_con_compras == (9001,)
        assert renglon.recibido_por == f"{CORREO} (conciliación: deducido de una compra)"
        assert renglon.piezas_recibidas == 5.0

    def test_menos_piezas_que_las_pedidas_confirma_parcial(
        self, cliente, almacen, almacenamiento
    ):
        dia = dt.date(2024, 3, 5)
        pedido_sugerido_id, renglon_id = _armar_una_lista(cliente, almacen, dia=dia, cantidad=10)
        almacenamiento.listas[0]["estado"] = CERRADO

        decision = RenglonPorConciliar(
            renglon_id=renglon_id,
            proveedor="nadro",
            proveedor_id=1,
            compras=(9001,),
            piezas=4.0,
            piezas_pedidas=10,
        )
        resultado = almacenamiento.confirmar_la_conciliacion(
            NEGOCIO, pedido_sugerido_id, [decision], CORREO
        )

        assert resultado.confirmados == 1
        lista = almacenamiento.leer_por_id(NEGOCIO, pedido_sugerido_id)
        (renglon,) = lista.renglones
        assert renglon.estado == RENGLON_RECIBIDO_PARCIAL
        assert renglon.piezas_recibidas == 4.0

    def test_dos_renglones_del_mismo_proveedor_comparten_un_solo_pedido(
        self, cliente, almacen, almacenamiento
    ):
        almacen.catalogo_en_memoria = [
            _producto(1, "7501000000001"),
            _producto(2, "7501000000002"),
        ]
        dia = dt.date(2024, 3, 5)
        almacen.ventas_en_memoria = [_venta(dia, 1, 3), _venta(dia, 2, 4)]
        cuerpo = cliente.get(RUTA).json()
        pedido_sugerido_id = cuerpo["pedido_sugerido_id"]
        renglon_1, renglon_2 = (r["renglon_id"] for r in cuerpo["renglones"])
        almacenamiento.listas[0]["estado"] = CERRADO

        decisiones = [
            RenglonPorConciliar(renglon_1, "nadro", 1, (9001,), 3.0, 3),
            RenglonPorConciliar(renglon_2, "nadro", 1, (9002,), 4.0, 4),
        ]
        resultado = almacenamiento.confirmar_la_conciliacion(
            NEGOCIO, pedido_sugerido_id, decisiones, CORREO
        )

        assert resultado.confirmados == 2
        pedidos = almacenamiento.pedidos_de_la_lista(NEGOCIO, pedido_sugerido_id)
        assert len(pedidos) == 1  # un solo pedido para los dos renglones

    def test_una_decision_que_ya_no_califica_no_tira_las_demas(
        self, cliente, almacen, almacenamiento
    ):
        almacen.catalogo_en_memoria = [
            _producto(1, "7501000000001"),
            _producto(2, "7501000000002"),
        ]
        dia = dt.date(2024, 3, 5)
        almacen.ventas_en_memoria = [_venta(dia, 1, 3), _venta(dia, 2, 4)]
        cuerpo = cliente.get(RUTA).json()
        pedido_sugerido_id = cuerpo["pedido_sugerido_id"]
        renglon_1, renglon_2 = (r["renglon_id"] for r in cuerpo["renglones"])
        almacenamiento.listas[0]["estado"] = CERRADO

        decisiones = [
            # Este renglón ya no existe: un id inventado.
            RenglonPorConciliar(999_999, "nadro", 1, (9001,), 3.0, 3),
            RenglonPorConciliar(renglon_2, "nadro", 1, (9002,), 4.0, 4),
        ]
        resultado = almacenamiento.confirmar_la_conciliacion(
            NEGOCIO, pedido_sugerido_id, decisiones, CORREO
        )

        assert resultado.confirmados == 1
        assert resultado.fallidos == (999_999,)
        lista = almacenamiento.leer_por_id(NEGOCIO, pedido_sugerido_id)
        estados = {r.renglon_id: r.estado for r in lista.renglones}
        assert estados[renglon_1] == RENGLON_ABIERTO  # sin tocar
        assert estados[renglon_2] == RENGLON_RECIBIDO

    def test_una_compra_ya_usada_en_otra_lista_no_se_vuelve_a_confirmar(
        self, cliente, almacen, almacenamiento
    ):
        # Primera lista, confirmada con la compra 9001.
        pedido_sugerido_1, renglon_1 = _armar_una_lista(
            cliente, almacen, dia=dt.date(2024, 3, 5), producto_id=1, cantidad=3
        )
        almacenamiento.listas[0]["estado"] = CERRADO
        almacenamiento.confirmar_la_conciliacion(
            NEGOCIO,
            pedido_sugerido_1,
            [RenglonPorConciliar(renglon_1, "nadro", 1, (9001,), 3.0, 3)],
            CORREO,
        )

        # Segunda lista, otro día, mismo producto: alguien (por error) también
        # la manda a conciliar con la MISMA compra.
        almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 6), 1, 2)]
        cuerpo = cliente.get(RUTA).json()
        pedido_sugerido_2 = cuerpo["pedido_sugerido_id"]
        renglon_2 = cuerpo["renglones"][0]["renglon_id"]
        almacenamiento.listas[1]["estado"] = CERRADO

        resultado = almacenamiento.confirmar_la_conciliacion(
            NEGOCIO,
            pedido_sugerido_2,
            [RenglonPorConciliar(renglon_2, "nadro", 1, (9001,), 2.0, 2)],
            CORREO,
        )

        assert resultado.confirmados == 0
        assert resultado.fallidos == (renglon_2,)
