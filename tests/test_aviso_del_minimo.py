"""El aviso del mínimo del proveedor en la captura (ticket 09 de lista-de-espera).

Los niveles, como en `test_total_del_pedido.py` y `test_minimos.py`; ninguno toca
Postgres ni la red:

1. **Lo puro**: la suma del pedido en las dos bases de IVA y la decisión
   `llega` / `no_llega` / `sin_capturar` / `sin_minimo` / `no_se_sabe`.
2. **La ruta de punta a punta**: el campo `minimo` de cada pedido, también en
   las respuestas que recalculan pedidos, y los fallos de lectura.
3. **El texto del JavaScript**: pinta la frase del servidor y no compara.

Lo que se cuida sobre todo: **la comparación es en la base del mínimo**. Un
mínimo «con IVA» se compara contra el total llevado a con-IVA renglón por
renglón con la tasa de cada producto, nunca contra el total sin IVA ni contra
total × 1.16 (lo exento no lleva IVA).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    PedidoGuardado,
    PrecioDeProveedor,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    RenglonGuardado,
)
from continental.dobles import AlmacenFalso, AlmacenamientoFalso
from continental.minimos import (
    LLEGA,
    NO_LLEGA,
    NO_SE_SABE,
    SIN_CAPTURAR,
    SIN_LEER,
    SIN_MINIMO,
    MinimoDelProveedor,
    SumaDelPedido,
    aviso_de_que_no_se_pudo_leer,
    avisar_el_minimo,
)
from continental.particion import la_suma_del_pedido
from continental.precios import LecturaDePrecio, SESION_CADUCADA
from continental.sugerido import Renglon

D = Decimal
RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


# ------------------------------------------------------------- utilidades


def _renglon(renglon_id: int, cantidad: int = 1, estado: str = RENGLON_ABIERTO) -> RenglonGuardado:
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
        pedido_id=7,
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
        total_sin_iva=None,
    )


def _precio(renglon_id: int, precio: str | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor="nadro",
        consultado_en=ARMADO,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else D(precio),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


def _minimo(monto: str, con_iva: bool) -> MinimoDelProveedor:
    return MinimoDelProveedor("nadro", D(monto), con_iva, CORREO, ARMADO)


def _suma(renglones, precios, tasas) -> SumaDelPedido:
    return la_suma_del_pedido(_pedido(), renglones, precios, tasas)


def _dos_renglones():
    """$1,000 de un producto con IVA 16% y $900 de uno exento: $1,900 sin IVA y
    $2,060 con IVA (1,160 + 900), que NO es 1,900 x 1.16 = 2,204."""
    return (
        [_renglon(1), _renglon(2)],
        {1: [_precio(1, "1000.00")], 2: [_precio(2, "900.00")]},
        {1: D("0.16"), 2: D("0")},
    )


# ==========================================================================
# 1. LO PURO
# ==========================================================================


def test_la_suma_lleva_a_con_iva_renglon_por_renglon_con_su_tasa():
    suma = _suma(*_dos_renglones())
    assert suma.sin_iva == D("1900.00")
    assert suma.con_iva == D("2060.00")
    assert suma.con_iva != (suma.sin_iva * D("1.16")).quantize(D("0.01"))


def test_el_ieps_se_suma_con_el_iva_en_la_tasa_del_producto():
    # 0.24 = IVA 16% + IEPS 8%, como la deja dim_producto.tasa_impuestos.
    suma = _suma([_renglon(1)], {1: [_precio(1, "100.00")]}, {1: D("0.24")})
    assert suma.con_iva == D("124.00")


def test_los_centavos_se_redondean_por_renglon():
    # 33.33 x 1.16 = 38.6628 -> 38.66 por renglón; tres renglones suman 115.98
    # (redondear al final daría 115.99).
    suma = _suma(
        [_renglon(1), _renglon(2), _renglon(3)],
        {n: [_precio(n, "33.33")] for n in (1, 2, 3)},
        {n: D("0.16") for n in (1, 2, 3)},
    )
    assert suma.con_iva == D("115.98")


def test_descartados_no_suman_en_ninguna_base():
    suma = _suma(
        [_renglon(1), _renglon(2, estado=RENGLON_DESCARTADO)],
        {1: [_precio(1, "10.00")], 2: [_precio(2, "500.00")]},
        {1: D("0.16"), 2: D("0.16")},
    )
    assert suma.sin_iva == D("10.00")
    assert suma.con_iva == D("11.60")


def test_un_producto_sin_tasa_no_se_supone_exento():
    renglones, precios, _ = _dos_renglones()
    suma = _suma(renglones, precios, {1: D("0.16")})  # falta la del 2
    assert suma.sin_iva == D("1900.00")
    assert suma.con_iva is None
    assert suma.sin_tasa == 1
    assert suma.parcial_con_iva == D("1160.00")


def test_si_las_tasas_no_se_pudieron_leer_se_dice():
    renglones, precios, _ = _dos_renglones()
    suma = _suma(renglones, precios, None)
    assert suma.con_iva is None
    assert suma.tasas_sin_leer is True
    assert suma.sin_iva == D("1900.00")  # sin IVA no necesita tasas


def test_un_renglon_sin_precio_deja_el_total_en_none_en_las_dos_bases():
    suma = _suma(
        [_renglon(1), _renglon(2)],
        {1: [_precio(1, "100.00")], 2: [_precio(2, None)]},
        {1: D("0.16"), 2: D("0.16")},
    )
    assert suma.sin_iva is None
    assert suma.con_iva is None
    assert suma.sin_precio == 1
    assert suma.parcial_sin_iva == D("100.00")
    assert suma.parcial_con_iva == D("116.00")


def test_con_un_minimo_sin_iva_se_compara_contra_el_total_sin_iva():
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), _suma(*_dos_renglones()))
    assert aviso.estado == NO_LLEGA
    assert aviso.falta == "100.00"
    assert aviso.base == "sin IVA"
    assert aviso.frase == "faltan $100.00 para el mínimo de NADRO ($2,000.00 sin IVA)"
    assert aviso.se_avisa is True


def test_con_un_minimo_con_iva_se_compara_en_con_iva_y_llega():
    # Contra el total sin IVA ($1,900) habría avisado un faltante que no existe.
    aviso = avisar_el_minimo("nadro", _minimo("2000", True), _suma(*_dos_renglones()))
    assert aviso.estado == LLEGA
    assert aviso.base == "con IVA"
    assert aviso.comparado == "$2,060.00"
    assert aviso.frase == "llega al mínimo de NADRO ($2,000.00 con IVA)"
    assert aviso.se_avisa is False


def test_con_un_minimo_con_iva_lo_que_falta_se_dice_en_con_iva():
    aviso = avisar_el_minimo("nadro", _minimo("2300", True), _suma(*_dos_renglones()))
    assert aviso.estado == NO_LLEGA
    assert aviso.falta == "240.00"
    assert aviso.frase == "faltan $240.00 para el mínimo de NADRO ($2,300.00 con IVA)"


def test_justo_en_el_minimo_llega():
    aviso = avisar_el_minimo("nadro", _minimo("1900.00", False), _suma(*_dos_renglones()))
    assert aviso.estado == LLEGA


def test_sin_fila_es_sin_minimo_capturado_y_no_avisa():
    aviso = avisar_el_minimo("nadro", None, _suma(*_dos_renglones()))
    assert aviso.estado == SIN_CAPTURAR
    assert aviso.frase == "sin mínimo capturado"
    assert aviso.se_avisa is False
    assert aviso.falta is None


def test_sin_fila_tampoco_depende_de_que_haya_suma():
    assert avisar_el_minimo("nadro", None, None).estado == SIN_CAPTURAR


def test_cero_es_no_tiene_minimo_y_siempre_llega():
    aviso = avisar_el_minimo("nadro", _minimo("0", False), _suma(*_dos_renglones()))
    assert aviso.estado == SIN_MINIMO
    assert aviso.frase == "no tiene mínimo"
    assert aviso.se_avisa is False
    # Aun con precios sin leer: no hay mínimo que alcanzar.
    assert avisar_el_minimo("nadro", _minimo("0", True), None).estado == SIN_MINIMO


def test_con_renglones_sin_precio_y_lo_que_hay_ya_alcanza_llega():
    suma = _suma(
        [_renglon(1), _renglon(2)],
        {1: [_precio(1, "2500.00")], 2: [_precio(2, None)]},
        {1: D("0"), 2: D("0")},
    )
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), suma)
    assert aviso.estado == LLEGA
    assert "aunque faltan datos" in aviso.frase


def test_con_renglones_sin_precio_no_se_da_por_buena_una_suma_incompleta():
    suma = _suma(
        [_renglon(1), _renglon(2), _renglon(3)],
        {1: [_precio(1, "1200.00")], 2: [_precio(2, None)], 3: [_precio(3, None)]},
        {n: D("0") for n in (1, 2, 3)},
    )
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), suma)
    assert aviso.estado == NO_SE_SABE
    assert aviso.falta is None
    assert aviso.frase == (
        "no se sabe si llega al mínimo de NADRO ($2,000.00 sin IVA): "
        "van $1,200.00 sin IVA y 2 renglones sin precio"
    )
    assert aviso.se_avisa is True


def test_un_solo_renglon_sin_precio_va_en_singular():
    suma = _suma(
        [_renglon(1), _renglon(2)],
        {1: [_precio(1, "10.00")], 2: [_precio(2, None)]},
        {1: D("0"), 2: D("0")},
    )
    assert "1 renglón sin precio" in avisar_el_minimo("nadro", _minimo("2000", False), suma).frase


def test_si_falta_una_tasa_con_un_minimo_con_iva_no_se_sabe_y_lo_dice():
    renglones, precios, _ = _dos_renglones()
    suma = _suma(renglones, precios, {1: D("0.16")})
    aviso = avisar_el_minimo("nadro", _minimo("5000", True), suma)
    assert aviso.estado == NO_SE_SABE
    assert "falta el IVA de 1 producto" in aviso.frase


def test_si_falta_una_tasa_pero_el_minimo_es_sin_iva_no_estorba():
    renglones, precios, _ = _dos_renglones()
    suma = _suma(renglones, precios, None)
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), suma)
    assert aviso.estado == NO_LLEGA  # se compara en sin IVA, que no necesita tasas


def test_si_las_tasas_no_se_pudieron_leer_con_un_minimo_con_iva_se_dice():
    renglones, precios, _ = _dos_renglones()
    aviso = avisar_el_minimo("nadro", _minimo("5000", True), _suma(renglones, precios, None))
    assert aviso.estado == NO_SE_SABE
    assert "no se pudo leer el IVA de los productos" in aviso.frase


def test_sin_precios_leidos_no_se_sabe():
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), None)
    assert aviso.estado == NO_SE_SABE
    assert "no se pudieron leer los precios" in aviso.frase


def test_un_pedido_sin_renglones_no_llega_ni_deja_de_llegar():
    aviso = avisar_el_minimo("nadro", _minimo("2000", False), _suma([], {}, {}))
    assert aviso.estado == NO_SE_SABE
    assert aviso.frase.startswith("sin renglones")


def test_si_no_se_pudo_leer_el_minimo_no_es_sin_capturar():
    aviso = aviso_de_que_no_se_pudo_leer("nadro")
    assert aviso.estado == SIN_LEER
    assert aviso.estado != SIN_CAPTURAR
    assert aviso.frase == "no se pudo leer el mínimo"
    assert aviso.se_avisa is True


def test_el_json_trae_cadenas_y_estado():
    j = avisar_el_minimo("nadro", _minimo("2300", True), _suma(*_dos_renglones())).como_json()
    assert j["estado"] == "no_llega"
    assert j["falta"] == "240.00" and isinstance(j["falta"], str)
    assert j["minimo"] == "$2,300.00 con IVA"
    assert j["se_avisa"] is True


# ==========================================================================
# 2. LA RUTA DE PUNTA A PUNTA
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
        LineaDeVenta(fecha=HOY, producto_id=n, cantidad=3, importe=30.0, costo=18.0, utilidad=12.0)
        for n in range(1, cuantos + 1)
    ]


def _lectura(precio: str | None) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor="nadro",
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else D(precio),
        existencia_como_llego="40",
        existencia=D("40"),
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


def _fijar(almacenamiento, monto, con_iva):
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D(monto), con_iva, CORREO)


def test_cada_pedido_trae_su_aviso_con_la_frase_del_servidor(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "100", False)
    # 3 piezas de cada uno: 30.00 + 61.50 = 91.50 sin IVA
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.50"])
    minimo = partida["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_llega"
    assert minimo["falta"] == "8.50"
    assert minimo["frase"] == "faltan $8.50 para el mínimo de NADRO ($100.00 sin IVA)"
    assert minimo["se_avisa"] is True


def test_sin_fila_el_pedido_dice_sin_minimo_capturado(cliente, almacen, almacenamiento):
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    minimo = partida["pedidos"][0]["minimo"]
    assert minimo["estado"] == "sin_capturar"
    assert minimo["frase"] == "sin mínimo capturado"
    assert minimo["se_avisa"] is False


def test_cero_dice_no_tiene_minimo(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "0", False)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    assert partida["pedidos"][0]["minimo"]["estado"] == "sin_minimo"


def test_con_un_minimo_con_iva_se_usa_la_tasa_de_cada_producto(cliente, almacen, almacenamiento):
    # Producto 1 con IVA 16%: 3 x 10.00 = 30.00 -> 34.80. Producto 2 exento:
    # 3 x 20.00 = 60.00. Con IVA: 94.80 (con total x 1.16 sería 104.40).
    almacen.tasas_en_memoria = {1: D("0.16"), 2: D("0")}
    _fijar(almacenamiento, "100", True)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    minimo = partida["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_llega"
    assert minimo["comparado"] == "$94.80"
    assert minimo["falta"] == "5.20"
    assert minimo["base"] == "con IVA"


def test_un_minimo_con_iva_que_llega_en_con_iva_no_avisa(cliente, almacen, almacenamiento):
    almacen.tasas_en_memoria = {1: D("0.16"), 2: D("0")}
    _fijar(almacenamiento, "94.80", True)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    assert partida["pedidos"][0]["minimo"]["estado"] == "llega"


def test_si_no_se_pueden_leer_las_tasas_con_un_minimo_con_iva_no_se_sabe(
    cliente, almacen, almacenamiento
):
    class _SinTasas(AlmacenFalso):
        def tasas_de_impuestos(self, productos):
            raise RuntimeError("tasas caídas con contraseña=secreta")

    _fijar(almacenamiento, "50", True)
    # Se parte con el almacén bueno y se relee con el que no lee tasas.
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    assert partida["pedidos"][0]["minimo"]["estado"] == "no_se_sabe"  # no hay tasa cargada

    from continental.web.app import app
    from continental.web.dependencias import obtener_almacen

    roto = _SinTasas()
    roto.catalogo_en_memoria = almacen.catalogo_en_memoria
    roto.ventas_en_memoria = almacen.ventas_en_memoria
    app.dependency_overrides[obtener_almacen] = lambda: roto
    lista = cliente.get(RUTA).json()
    minimo = lista["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_se_sabe"
    assert "no se pudo leer el IVA de los productos" in minimo["frase"]
    assert "secreta" not in str(lista)  # el error no viaja al navegador


def test_los_precios_sin_leer_de_un_renglon_se_dicen_en_el_aviso(
    cliente, almacen, almacenamiento
):
    _fijar(almacenamiento, "1000", False)
    _poblar(almacen, 2)
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_precios(NEGOCIO, lista["renglones"][0]["renglon_id"], [_lectura("10.00")])
    sin_precio = lista["renglones"][1]["renglon_id"]
    almacenamiento.guardar_precios(NEGOCIO, sin_precio, [_lectura(None)])
    lista = cliente.get(RUTA).json()
    assert cliente.post(
        f"/api/renglon/{sin_precio}/proveedor", json={"proveedor": "nadro"}, headers=_firma()
    ).status_code == 200
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    minimo = partida["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_se_sabe"
    assert "1 renglón sin precio" in minimo["frase"]


def test_descartar_recalcula_el_aviso_sin_recargar(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "70", False)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    pedido = partida["pedidos"][0]
    assert pedido["minimo"]["estado"] == "llega"  # 90.00
    renglon = pedido["captura"]["lineas"][0]["renglon_id"]  # el de 10.00

    respuesta = cliente.post(f"/api/renglon/{renglon}/descartar", headers=_firma())
    assert respuesta.status_code == 200, respuesta.text
    minimo = respuesta.json()["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_llega"  # 60.00
    assert minimo["falta"] == "10.00"

    devuelta = cliente.post(f"/api/renglon/{renglon}/devolver", headers=_firma())
    assert devuelta.json()["pedidos"][0]["minimo"]["estado"] == "llega"


def test_mandar_el_pedido_entero_a_espera_recalcula_el_aviso(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "50", False)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00", "20.00"])
    pedido = partida["pedidos"][0]
    respuesta = cliente.post(f"/api/pedido/{pedido['pedido_id']}/posponer", headers=_firma())
    assert respuesta.status_code == 200, respuesta.text
    minimo = respuesta.json()["pedidos"][0]["minimo"]
    assert minimo["estado"] == "no_se_sabe"  # se quedó sin renglones
    assert minimo["frase"].startswith("sin renglones")


def test_tachar_trae_el_aviso(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "100", False)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    renglon = partida["pedidos"][0]["captura"]["lineas"][0]["renglon_id"]
    respuesta = cliente.post(
        f"/api/renglon/{renglon}/capturado", json={"capturado": True}, headers=_firma()
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["pedidos"][0]["minimo"]["estado"] == "no_llega"


def test_el_aviso_no_bloquea_enviar(cliente, almacen, almacenamiento):
    _fijar(almacenamiento, "100000", False)
    partida = _partida(cliente, almacen, almacenamiento, ["10.00"])
    pedido = partida["pedidos"][0]
    assert pedido["minimo"]["estado"] == "no_llega"
    assert pedido["se_puede_enviar"] is True
    enviado = cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=_firma())
    assert enviado.status_code == 200, enviado.text


class _MinimosCaidos(AlmacenamientoFalso):
    caidos = False

    def minimos_de_los_proveedores(self, negocio):
        if self.caidos:
            raise RuntimeError("postgresql://usuario:contraseña@host/db")
        return super().minimos_de_los_proveedores(negocio)


def test_si_la_lectura_de_los_minimos_falla_se_dice_y_no_es_sin_capturar(cliente, almacen):
    from continental.web.app import app
    from continental.web.dependencias import obtener_almacenamiento

    roto = _MinimosCaidos()
    app.dependency_overrides[obtener_almacenamiento] = lambda: roto
    partida = _partida(cliente, almacen, roto, ["10.00"])
    assert partida["pedidos"][0]["minimo"]["estado"] == "sin_capturar"  # leía bien

    roto.caidos = True
    lista = cliente.get(RUTA).json()
    minimo = lista["pedidos"][0]["minimo"]
    assert minimo["estado"] == "sin_leer"
    assert minimo["frase"] == "no se pudo leer el mínimo"
    assert minimo["se_avisa"] is True
    assert "contraseña" not in str(lista)


def test_una_sola_lectura_de_minimos_por_respuesta(cliente, almacen, almacenamiento):
    llamadas = []
    original = almacenamiento.minimos_de_los_proveedores

    def contada(negocio):
        llamadas.append(negocio)
        return original(negocio)

    almacenamiento.minimos_de_los_proveedores = contada
    _poblar(almacen, 2)
    cliente.get(RUTA)
    lista = cliente.get(RUTA).json()
    for i in range(2):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], [_lectura("10.00")]
        )
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")
    llamadas.clear()
    cliente.get(RUTA)
    assert len(llamadas) == 1


def test_la_novena_lectura_es_un_select_acotado_sobre_dim_producto():
    from continental.almacen import _TASAS_DE_IMPUESTOS

    sql = str(_TASAS_DE_IMPUESTOS).lower()
    assert sql.lstrip().startswith("select")
    assert "marts.dim_producto" in sql
    assert "any(:productos)" in sql
    assert "tasa_impuestos is not null" in sql  # sin dato no es cero
    for escritura in ("insert", "update", "delete"):
        assert escritura not in sql


def test_el_doble_solo_devuelve_las_tasas_que_se_le_cargaron(almacen):
    almacen.tasas_en_memoria = {1: D("0.16")}
    assert almacen.tasas_de_impuestos({1, 2}) == {1: D("0.16")}


# ==========================================================================
# 3. EL TEXTO DEL JAVASCRIPT
# ==========================================================================


def test_el_pie_pinta_la_frase_del_servidor_y_no_compara_montos():
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarPasoCaptura")
    assert "guardado.minimo.frase" in cuerpo
    assert "guardado.minimo.estado" in cuerpo
    assert "g.minimo.frase" in cuerpo
    # Ningún monto se convierte ni se compara en el navegador.
    for cuenta in ("parseFloat", "Number(", "toFixed(", "reduce(", ".falta", ".comparado", "monto"):
        assert cuenta not in cuerpo, f"La captura calcula el mínimo en el navegador: {cuenta!r}"


def test_el_aviso_tiene_mandar_a_espera_solo_cuando_no_llega():
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarPasoCaptura")
    assert "guardado.minimo.estado === 'no_llega'" in cuerpo
    assert "botonDeEspera()" in cuerpo


def test_enviar_no_mira_el_minimo():
    cuerpo = cuerpo_de_funcion(pantalla_completa(), "const pintarPasoCaptura")
    inicio = cuerpo.index("const boton = botonDeAccion(\n      'Ya está en el portal")
    fin = cuerpo.index("fila.append(boton);", inicio)
    assert "minimo" not in cuerpo[inicio:fin]
