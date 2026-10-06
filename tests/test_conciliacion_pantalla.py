"""La pantalla de la conciliación diaria (ADR 0021, 2026-09-27).

`tests/test_conciliacion.py` y `tests/test_conciliacion_guardado.py` ya
prueban las dos capas de abajo: la función pura `conciliacion.conciliar()` y
el guardado `AlmacenamientoDelPedido.confirmar_la_conciliacion`. Este archivo
prueba lo único que faltaba para que una persona pudiera llegar hasta ahí
desde el navegador — lo construido en esta sesión:

1. Las funciones puras nuevas de `conciliacion.py` que arman el JSON y las
   frases de la pantalla (`conciliacion_como_json`, `frase_de_la_diferencia`,
   `frase_del_bloque`, `frase_del_lote_confirmado`, `conciliacion_con_hueco`)
   — sin Postgres, sin red, sin `TestClient`.
2. Las dos rutas HTTP, de punta a punta contra los dobles:
   `GET /api/pedido-sugerido/{id}/conciliacion` (solo lee) y
   `POST .../conciliacion/confirmar` (el único clic que escribe, en lote).

Lo que este archivo NO vuelve a probar: los tres motivos de "no comprado", el
caso ambiguo, el descartado-y-comprado-de-todos-modos y la ventana de
tolerancia — eso ya está cubierto, exhaustivo, en `test_conciliacion.py`. Aquí
solo se prueba que la ruta los deja pasar hasta el JSON sin perder la
distinción, no que la distinción misma sea correcta.

Ningún dato es real: proveedores, productos y compras son inventados. Ninguna
prueba toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import PrecioDeProveedor
from continental.conciliacion import (
    MOTIVO_DATOS_NO_HAN_LLEGADO,
    MOTIVO_NUNCA_EN_COMPRAS,
    Coincidencia,
    Conciliacion,
    SinComprar,
    comparar_precio_pagado,
    conciliacion_como_json,
    conciliacion_con_hueco,
    frase_de_la_diferencia,
    frase_del_bloque,
    frase_del_lote_confirmado,
)
from continental.sugerido import Renglon

NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}

#: Los `pro_id` de SICAR del YAML versionado (ADR 0008) — no son datos de
#: nadie, son la configuración de esta instalación real.
NADRO = 1
LEVIC = 10
SIN_PUENTE = 77

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
JUEVES = dt.date(2026, 9, 17)

RUTA = "/api/pedido-sugerido"


# ============================================================== lo puro


def _renglon_propuesto(producto_id: int, cantidad: int = 5) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        piezas_vendidas=float(cantidad),
        cantidad_propuesta=cantidad,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
    )


def _lectura(proveedor: str, precio: float | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=proveedor,
        consultado_en=dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.UTC),
        precio=None if precio is None else Decimal(str(precio)),
        existencia=Decimal("10"),
    )


class TestFraseDeLaDiferencia:
    def test_el_ejemplo_del_adr_0021_dinero_real(self):
        """"pagó $126.25 a NADRO cuando teníamos LEVIC a $122.50 — $3.75 por
        pieza": la frase por la que existe el proyecto entero."""
        lecturas = [_lectura("nadro", 126.25), _lectura("levic", 122.50)]
        cmp = comparar_precio_pagado(126.25, "nadro", lecturas)

        frase = frase_de_la_diferencia(cmp, "PRODUCTO 1")

        assert frase == (
            "PRODUCTO 1: se pagó $126.25 a NADRO cuando LEVIC lo tenía a "
            "$122.50 — $3.75 más por pieza."
        )

    def test_sin_hallazgo_solo_dice_lo_que_se_pago(self):
        lecturas = [_lectura("nadro", 126.25), _lectura("levic", 122.50)]
        cmp = comparar_precio_pagado(122.50, "levic", lecturas)

        frase = frase_de_la_diferencia(cmp, "PRODUCTO 1")

        assert frase == "PRODUCTO 1: se pagó $122.50 a LEVIC."
        assert "más por pieza" not in frase

    def test_sin_lecturas_tampoco_afirma_un_hallazgo(self):
        cmp = comparar_precio_pagado(126.25, "nadro", [])

        frase = frase_de_la_diferencia(cmp, "PRODUCTO 1")

        assert frase == "PRODUCTO 1: se pagó $126.25 a NADRO."

    def test_proveedor_pagado_sin_clave_de_doyle(self):
        cmp = comparar_precio_pagado(126.25, None, [])

        frase = frase_de_la_diferencia(cmp, "PRODUCTO 1")

        assert "un proveedor sin clave de Doyle" in frase


class TestFraseDelBloque:
    def test_sin_nada_que_conciliar(self):
        resultado = Conciliacion(dia=LUNES, limite=JUEVES)

        assert frase_del_bloque(resultado) == (
            "Sin nada que conciliar todavía en la ventana de este día."
        )

    def test_cuenta_los_tres_bloques_y_los_accionables(self):
        renglon = Renglon(
            producto_id=1, clave="7501000000001", descripcion="PRODUCTO 1",
            piezas_vendidas=5.0, cantidad_propuesta=5, esta_en_el_catalogo=True,
            existencia=0.0, dias_de_cobertura=None, clasificacion="medicamento",
        )
        from continental.almacenamiento import RENGLON_ABIERTO, RenglonGuardado

        guardado = RenglonGuardado(renglon_id=1, estado=RENGLON_ABIERTO, propuesto=renglon)
        compra = LineaDeCompra(
            compra_id=1, producto_id=1, proveedor_id=NADRO, fecha=MARTES,
            cantidad=5.0, precio_unitario_pagado=10.0, importe_pagado=50.0, folio="F1",
        )
        coincidencia = Coincidencia(
            renglon=guardado, compras=(compra,), proveedor="nadro", proveedor_id=NADRO,
        )
        sin_comprar = SinComprar(renglon=guardado, motivo=MOTIVO_NUNCA_EN_COMPRAS)
        resultado = Conciliacion(
            dia=LUNES, limite=JUEVES,
            coincidencias=(coincidencia,), sin_comprar=(sin_comprar,),
        )

        frase = frase_del_bloque(resultado)

        assert "1 coincidencia (1 para confirmar en lote)" in frase
        assert "1 sin comprar todavía" in frase


class TestFraseDelLoteConfirmado:
    def test_nada_que_confirmar(self):
        assert frase_del_lote_confirmado(0, 0) == "No había nada que confirmar."

    def test_todo_se_confirmo(self):
        assert frase_del_lote_confirmado(3, 3) == "Se confirmaron 3 renglones."
        assert frase_del_lote_confirmado(1, 1) == "Se confirmaron 1 renglón."

    def test_nada_se_confirmo_de_lo_pedido(self):
        frase = frase_del_lote_confirmado(0, 2)
        assert "No se confirmó ninguno de 2 renglones" in frase
        assert "cambiaron antes del clic" in frase

    def test_una_parte_se_confirmo(self):
        frase = frase_del_lote_confirmado(1, 3)
        assert frase.startswith("Se confirmaron 1 de 3 renglones")
        assert "los demás cambiaron antes del clic" in frase


class TestConciliacionComoJson:
    def _conciliacion_con_los_tres_bloques(self) -> Conciliacion:
        from continental.almacenamiento import RENGLON_ABIERTO, RenglonGuardado

        r1 = RenglonGuardado(
            renglon_id=1, estado=RENGLON_ABIERTO, propuesto=_renglon_propuesto(1)
        )
        r2 = RenglonGuardado(
            renglon_id=2, estado=RENGLON_ABIERTO, propuesto=_renglon_propuesto(2)
        )
        compra = LineaDeCompra(
            compra_id=9001, producto_id=1, proveedor_id=NADRO, fecha=MARTES,
            cantidad=5.0, precio_unitario_pagado=126.25, importe_pagado=631.25, folio="F1",
        )
        coincidencia = Coincidencia(
            renglon=r1, compras=(compra,), proveedor="nadro", proveedor_id=NADRO,
        )
        sin_comprar = SinComprar(renglon=r2, motivo=MOTIVO_NUNCA_EN_COMPRAS)
        suelta_compra = LineaDeCompra(
            compra_id=9002, producto_id=3, proveedor_id=NADRO, fecha=MARTES,
            cantidad=2.0, precio_unitario_pagado=8.0, importe_pagado=16.0, folio="F2",
        )
        from continental.conciliacion import CompraSuelta

        suelta = CompraSuelta(compra=suelta_compra, proveedor="nadro")
        return Conciliacion(
            dia=LUNES, limite=JUEVES,
            coincidencias=(coincidencia,), sin_comprar=(sin_comprar,),
            compradas_sin_proponer=(suelta,),
        )

    def test_agrupa_sin_comprar_por_motivo(self):
        resultado = self._conciliacion_con_los_tres_bloques()

        cuerpo = conciliacion_como_json(resultado)

        assert cuerpo["ok"] is True
        [grupo] = cuerpo["sin_comprar"]
        assert grupo["motivo"] == MOTIVO_NUNCA_EN_COMPRAS
        assert grupo["renglones"][0]["producto_id"] == 2

    def test_lo_que_todavia_es_pronto_no_se_lista_renglon_por_renglon(self):
        """Pedido del dueño, 2026-10-05: doce renglones con la misma frase de
        "el respaldo puede tardar 2.5 días" eran ruido que nadie lee. El
        resumen del bloque los sigue contando; la lista ya no los repite."""
        resultado = self._conciliacion_con_los_tres_bloques()
        [s] = resultado.sin_comprar
        resultado = replace(
            resultado, sin_comprar=(replace(s, motivo=MOTIVO_DATOS_NO_HAN_LLEGADO),)
        )

        cuerpo = conciliacion_como_json(resultado)

        assert cuerpo["sin_comprar"] == []
        assert "1 sin comprar todavía" in cuerpo["frase"]

    def test_la_coincidencia_trae_lo_que_paga_el_modulo(self):
        resultado = self._conciliacion_con_los_tres_bloques()
        lecturas = [_lectura("nadro", 126.25), _lectura("levic", 122.50)]
        cmp = comparar_precio_pagado(126.25, "nadro", lecturas)

        cuerpo = conciliacion_como_json(resultado, {1: cmp})

        [c] = cuerpo["coincidencias"]
        assert c["accionable"] is True
        assert c["hubo_mas_barato"] is True
        assert c["diferencia_por_pieza"] == "3.75"
        assert "LEVIC" in c["frase_del_pago"]

    def test_sin_comparacion_no_afirma_un_hallazgo(self):
        resultado = self._conciliacion_con_los_tres_bloques()

        cuerpo = conciliacion_como_json(resultado)

        [c] = cuerpo["coincidencias"]
        assert c["hubo_mas_barato"] is None
        assert c["frase_del_pago"] is None

    def test_la_compra_suelta_no_trae_renglon_id_ni_accionable(self):
        """Es la garantía estructural del ADR 0021: nada de este bloque se
        puede meter en un `RenglonPorConciliar` — no hay con qué."""
        resultado = self._conciliacion_con_los_tres_bloques()

        cuerpo = conciliacion_como_json(resultado)

        [suelta] = cuerpo["compradas_sin_proponer"]
        assert "renglon_id" not in suelta
        assert "accionable" not in suelta
        assert suelta["fue_descartado"] is False
        assert suelta["ambiguo"] is False


def test_conciliacion_con_hueco_no_afirma_que_no_hay_nada_que_conciliar():
    cuerpo = conciliacion_con_hueco("no se pudo leer el calendario (RuntimeError)")

    assert cuerpo["ok"] is False
    assert cuerpo["coincidencias"] == []
    assert "no se pudo" in cuerpo["frase"].lower() or "no se pudo conciliar" in cuerpo["frase"].lower()


# ============================================================ las rutas


def _producto(producto_id: int) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=2.0,
        esta_activo=True,
        es_granel=False,
    )


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha, producto_id=producto_id, cantidad=cantidad,
        importe=cantidad * 50, costo=cantidad * 30, utilidad=cantidad * 20,
    )


def _compra(
    compra_id: int, producto_id: int, proveedor_id: int, fecha: dt.date,
    cantidad: float = 5.0, precio: float = 12.5, folio: str = "F-0001",
) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=compra_id, producto_id=producto_id, proveedor_id=proveedor_id,
        fecha=fecha, cantidad=cantidad, precio_unitario_pagado=precio,
        importe_pagado=precio * cantidad, folio=folio,
    )


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def test_get_conciliacion_404_si_la_lista_no_existe(cliente):
    respuesta = cliente.get(f"{RUTA}/999999/conciliacion")

    assert respuesta.status_code == 404
    assert respuesta.json()["ok"] is False


def test_get_conciliacion_de_punta_a_punta_el_ejemplo_del_adr_0021(
    cliente, almacen, almacenamiento
):
    """El caso completo: se propuso, SICAR ya tiene la compra a NADRO, y
    LEVIC daba mejor precio — el número por el que existe el proyecto."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)
    [renglon] = [r for r in lista["renglones"] if r["producto_id"] == 1]

    almacenamiento.guardar_precios(NEGOCIO, renglon["renglon_id"], [])
    almacen.compras_en_memoria = [_compra(9001, 1, NADRO, MARTES, cantidad=5.0, precio=126.25)]

    respuesta = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["pedido_sugerido_id"] == lista["pedido_sugerido_id"]
    [c] = cuerpo["coincidencias"]
    assert c["accionable"] is True
    assert c["proveedor"] == "nadro"
    assert c["proveedor_nombre"] == "NADRO"
    assert c["compras"] == [9001]
    assert c["pagado"] == "126.25"
    # Sin precios congelados de LEVIC en este renglón no hay con qué comparar
    # —`guardar_precios` se llamó con una lista vacía—, así que no se afirma
    # un hallazgo que no se pudo ver.
    assert c["hubo_mas_barato"] is False


def test_get_conciliacion_con_algo_mas_barato_dice_la_diferencia(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)
    [renglon] = [r for r in lista["renglones"] if r["producto_id"] == 1]

    from continental.precios import LecturaDePrecio

    almacenamiento.guardar_precios(
        NEGOCIO, renglon["renglon_id"],
        [
            LecturaDePrecio(
                proveedor="levic", precio_como_llego="122.50", precio=Decimal("122.50"),
                existencia_como_llego="10", existencia=Decimal("10"), motivo=None,
            ),
        ],
    )
    almacen.compras_en_memoria = [_compra(9001, 1, NADRO, MARTES, cantidad=5.0, precio=126.25)]

    cuerpo = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion").json()

    [c] = cuerpo["coincidencias"]
    assert c["hubo_mas_barato"] is True
    assert c["diferencia_por_pieza"] == "3.75"
    assert "LEVIC" in c["frase_del_pago"]
    assert "$3.75" in c["frase_del_pago"]


def test_get_conciliacion_proveedor_sin_puente_no_es_accionable(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)
    almacen.compras_en_memoria = [_compra(9001, 1, SIN_PUENTE, MARTES, cantidad=5.0)]

    cuerpo = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion").json()

    [c] = cuerpo["coincidencias"]
    assert c["accionable"] is False
    assert c["motivo_no_accionable"]
    assert c["proveedor_nombre"] is None


def test_get_conciliacion_nunca_en_compras_se_distingue(cliente, almacen):
    """Un producto que nunca ha aparecido en `fct_compras` (606 de 3,429 en
    la farmacia real) nunca va a disparar la conciliación, y se dice así."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)

    cuerpo = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion").json()

    [grupo] = cuerpo["sin_comprar"]
    assert grupo["motivo"] == MOTIVO_NUNCA_EN_COMPRAS
    assert grupo["renglones"][0]["producto_id"] == 1


def test_get_conciliacion_lo_ambiguo_y_lo_descartado_no_se_auto_confirman(
    cliente, almacen
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5), _venta(LUNES, 2, 3)]
    lista = _abrir(cliente)
    [r2] = [r for r in lista["renglones"] if r["producto_id"] == 2]
    descartado = cliente.post(f"/api/renglon/{r2['renglon_id']}/descartar", headers=FIRMA)
    assert descartado.json()["ok"] is True

    almacen.compras_en_memoria = [
        # El producto 1 se compró a dos proveedores dentro de la ventana: ambiguo.
        _compra(9001, 1, NADRO, MARTES, cantidad=5.0),
        _compra(9002, 1, LEVIC, MARTES, cantidad=5.0),
        # El producto 2 se descartó y se compró de todos modos.
        _compra(9003, 2, NADRO, MARTES, cantidad=3.0),
    ]

    cuerpo = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion").json()

    assert cuerpo["coincidencias"] == []
    sueltas = {s["compra_id"]: s for s in cuerpo["compradas_sin_proponer"]}
    assert sueltas[9001]["ambiguo"] is True
    assert sueltas[9002]["ambiguo"] is True
    assert sueltas[9003]["fue_descartado"] is True
    # Ninguna trae con qué armar un `RenglonPorConciliar` (ver el JSON puro).
    for suelta in sueltas.values():
        assert "renglon_id" not in suelta


def test_get_conciliacion_hueco_si_la_tolerancia_no_esta_configurada(
    cliente, almacen, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)

    from continental import config

    monkeypatch.setattr(
        config, "cargar",
        lambda: config.Ajustes(negocio=NEGOCIO, warehouse_url=None, modulos={}, pedido={}),
    )

    respuesta = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert cuerpo["que_hacer"]
    assert cuerpo["coincidencias"] == []


def test_get_conciliacion_hueco_si_el_almacen_no_contesta(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)

    almacen.falla = RuntimeError("se cayó la réplica")

    respuesta = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert "se cayó la réplica" not in cuerpo["detalle"]  # regla 5: nunca el texto
    assert cuerpo["que_hacer"]


def _renglon_id_del_producto(lista: dict, producto_id: int) -> int:
    [r] = [r for r in lista["renglones"] if r["producto_id"] == producto_id]
    return r["renglon_id"]


def test_post_confirmar_el_lote_escribe_recibido_y_cambia_el_estado(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)
    renglon_id = _renglon_id_del_producto(lista, 1)
    almacen.compras_en_memoria = [_compra(9001, 1, NADRO, MARTES, cantidad=5.0)]

    conciliada = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion").json()
    [c] = conciliada["coincidencias"]
    cuerpo = {"renglones": [{"renglon_id": c["renglon_id"], "compras": c["compras"]}]}

    respuesta = cliente.post(
        f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion/confirmar",
        json=cuerpo, headers=FIRMA,
    )

    assert respuesta.status_code == 200
    resultado = respuesta.json()
    assert resultado["ok"] is True
    assert resultado["confirmados"] == 1
    assert resultado["total"] == 1

    releida = cliente.get(RUTA).json()
    releido = _renglon_id_del_producto(releida, 1)
    [renglon] = [r for r in releida["renglones"] if r["renglon_id"] == releido]
    assert renglon["estado"] == "recibido"


def test_post_confirmar_el_lote_salta_lo_que_ya_no_es_la_misma_evidencia(
    cliente, almacen
):
    """La misma garantía que confirmar una recepción normal: el servidor
    vuelve a conciliar antes de escribir y no confirma una evidencia que la
    persona no vio."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)
    renglon_id = _renglon_id_del_producto(lista, 1)

    cuerpo = {"renglones": [{"renglon_id": renglon_id, "compras": [9999]}]}

    respuesta = cliente.post(
        f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion/confirmar",
        json=cuerpo, headers=FIRMA,
    )

    assert respuesta.status_code == 200
    resultado = respuesta.json()
    assert resultado["ok"] is True
    assert resultado["confirmados"] == 0
    [fila] = resultado["resultados"]
    assert fila["ok"] is False
    assert fila["motivo"]


def test_post_confirmar_el_lote_no_puede_arrastrar_lo_ambiguo_ni_lo_descartado(
    cliente, almacen
):
    """No por un `if` que alguien podría olvidar: `compradas_sin_proponer`
    nunca trae `renglon_id`, así que no hay con qué armar el cuerpo del
    lote — se prueba mandando el `renglon_id` de una compra suelta y
    comprobando que no confirma nada."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5), _venta(LUNES, 2, 3)]
    lista = _abrir(cliente)
    r2 = _renglon_id_del_producto(lista, 2)
    cliente.post(f"/api/renglon/{r2}/descartar", headers=FIRMA)
    almacen.compras_en_memoria = [_compra(9003, 2, NADRO, MARTES, cantidad=3.0)]

    # r2 está descartado: su producto se compró de todos modos, pero eso vive
    # en `compradas_sin_proponer`, nunca en `coincidencias`. Intentar
    # confirmarlo con el `renglon_id` del renglón descartado no encuentra
    # nada que confirmar porque nunca fue una coincidencia `accionable`.
    cuerpo = {"renglones": [{"renglon_id": r2, "compras": [9003]}]}

    respuesta = cliente.post(
        f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion/confirmar",
        json=cuerpo, headers=FIRMA,
    )

    resultado = respuesta.json()
    assert resultado["confirmados"] == 0
    releida = cliente.get(RUTA).json()
    [renglon] = [r for r in releida["renglones"] if r["renglon_id"] == r2]
    assert renglon["estado"] == "descartado"


def test_post_confirmar_lote_vacio_no_hace_nada(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    lista = _abrir(cliente)

    respuesta = cliente.post(
        f"{RUTA}/{lista['pedido_sugerido_id']}/conciliacion/confirmar",
        json={"renglones": []}, headers=FIRMA,
    )

    assert respuesta.status_code == 200
    resultado = respuesta.json()
    assert resultado["ok"] is True
    assert resultado["confirmados"] == 0
    assert resultado["total"] == 0
    assert resultado["frase"] == "No había nada que confirmar."


def test_post_confirmar_el_lote_404_si_la_lista_no_existe(cliente):
    respuesta = cliente.post(
        f"{RUTA}/999999/conciliacion/confirmar",
        json={"renglones": []}, headers=FIRMA,
    )

    assert respuesta.status_code == 404
