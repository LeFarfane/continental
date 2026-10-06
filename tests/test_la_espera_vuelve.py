"""Lo que espera entra solo al pedido de su proveedor (lista de espera, ticket 05).

**Lo que arregla.** Hasta el ticket 04 la espera guardaba a quién se le iba a
pedir, pero la lista siguiente lo repartía de cero: sumaba las piezas y olvidaba
al proveedor. Desde aquí el renglón que vuelve **nace elegido** a ese
proveedor, con la firma y la hora de quien lo mandó a espera, trae desde cuándo
espera y cuántas listas lleva, y la partición lo respeta como respeta cualquier
decisión de una persona.

**Dónde nace repartido, y por qué ahí.** Los pedidos en `borrador` nacen al
*partir* la lista (`guardar_la_particion`), no al armarla: al armar todavía no
hay precios, ni total, ni puente hacia SICAR. Un renglón nace con
`proveedor_elegido` y su firma (la forma que ya entiende `particion.elegir`), y
el pedido de ese proveedor se crea o se reutiliza —`ux_pedido_proveedor`— en
cuanto alguien parte la lista. Inventar el pedido al armar duplicaría esa
lógica con un total que no se puede calcular todavía.

Los tres seams del repo: lo puro, lo que se guarda (el doble, los CHECK en
Python, el SQL como texto) y lo que se ve (una ruta de varios días, de punta a
punta). **Ninguna prueba toca Postgres ni la red, y ningún dato es real.**
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from continental import almacenamiento as modulo_almacenamiento
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    RENGLON_ABIERTO,
    RENGLON_POSPUESTO,
    PrecioDeProveedor,
    RenglonGuardado,
    Ventana,
    columnas_del_renglon,
    eleccion_de_la_espera,
    revisar_el_renglon,
)
from continental.particion import elegir, partir
from continental.precios import LecturaDePrecio
from continental.sugerido import LaEspera, Renglon, calcular_pedido_sugerido
from continental.transito import (
    frase_de_la_espera,
    memoria_de_lo_pedido,
)

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargada@farmacia.mx"
OTRO = "dueno@farmacia.mx"
HOY = dt.date(2024, 3, 5)  # martes
MANANA = dt.date(2024, 3, 6)  # miércoles
PASADO = dt.date(2024, 3, 7)  # jueves
MANDADO_EN = dt.datetime(2024, 3, 5, 15, 30, tzinfo=dt.UTC)


def _espera(**cambios) -> LaEspera:
    base = dict(
        desde=HOY,
        listas=2,
        proveedor="nadro",
        mandada_por=CORREO,
        mandada_en=MANDADO_EN,
    )
    base.update(cambios)
    return LaEspera(**base)


def _producto(n: int) -> Producto:
    return Producto(
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


def _venta(fecha: dt.date, n: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=n,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _renglon_de_la_espera(**cambios) -> Renglon:
    """Un renglón propuesto que viene de una espera de 3 piezas, con 2 vendidas."""
    base = dict(
        producto_id=1,
        clave="7501000000001",
        descripcion="PRODUCTO 1",
        piezas_vendidas=2.0,
        cantidad_propuesta=5,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
        piezas_pospuestas=3,
        proveedor_de_la_espera="nadro",
        espera_desde=HOY,
        listas_en_espera=2,
        espera_mandada_por=CORREO,
        espera_mandada_en=MANDADO_EN,
    )
    base.update(cambios)
    return Renglon(**base)


def _pospuesto(
    producto_id: int = 1,
    *,
    cantidad: int = 3,
    proveedor: str | None = "nadro",
    desde: dt.date | None = HOY,
    listas: int | None = 1,
    por: str | None = CORREO,
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=producto_id,
        estado=RENGLON_POSPUESTO,
        propuesto=Renglon(
            producto_id=producto_id,
            clave="",
            descripcion=f"PRODUCTO {producto_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        pospuesto_por=por,
        pospuesto_en=MANDADO_EN if por else None,
        proveedor_de_la_espera=proveedor,
        espera_desde=desde,
        listas_en_espera=listas,
    )


# ==========================================================================
# 1. LO PURO
# ==========================================================================


def test_la_memoria_arrastra_el_proveedor_la_fecha_y_la_firma_y_suma_una_lista():
    memoria = memoria_de_lo_pedido([], [_pospuesto(listas=1)])

    assert memoria.pospuestos == {1: 3}
    assert memoria.esperas == {
        1: LaEspera(
            desde=HOY,
            listas=2,
            proveedor="nadro",
            mandada_por=CORREO,
            mandada_en=MANDADO_EN,
        )
    }


def test_si_alguien_eligio_el_proveedor_a_mano_la_firma_es_la_suya():
    """La tarjeta «Sin proveedor» (ticket 11) o una elección en Revisar: quien
    decidió a quién pedírselo firma la elección de mañana, no quien lo mandó a
    espera."""
    import dataclasses

    eligio_en = MANDADO_EN + dt.timedelta(hours=1)
    pospuesto = dataclasses.replace(
        _pospuesto(listas=1),
        proveedor_elegido="nadro", elegido_por="otra@farmacia.mx", elegido_en=eligio_en,
    )
    espera = memoria_de_lo_pedido([], [pospuesto]).esperas[1]
    assert (espera.mandada_por, espera.mandada_en) == ("otra@farmacia.mx", eligio_en)


def test_una_eleccion_de_otro_proveedor_no_firma_la_espera():
    import dataclasses

    pospuesto = dataclasses.replace(
        _pospuesto(listas=1),
        proveedor_elegido="levic", elegido_por="otra@farmacia.mx",
        elegido_en=MANDADO_EN,
    )
    espera = memoria_de_lo_pedido([], [pospuesto]).esperas[1]
    assert espera.mandada_por == CORREO


def test_el_contador_de_una_espera_larga_sigue_sumando():
    memoria = memoria_de_lo_pedido([], [_pospuesto(listas=4)])
    assert memoria.esperas[1].listas == 5


def test_sin_proveedor_de_la_espera_la_memoria_igual_trae_la_edad():
    memoria = memoria_de_lo_pedido([], [_pospuesto(proveedor=None)])
    assert memoria.esperas[1].proveedor is None
    assert memoria.esperas[1].desde == HOY


def test_un_pospuesto_viejo_sin_fecha_no_inventa_una_edad():
    memoria = memoria_de_lo_pedido([], [_pospuesto(desde=None, listas=None)])
    assert memoria.pospuestos == {1: 3}
    assert memoria.esperas == {}


def test_lo_que_viene_en_camino_le_gana_y_no_trae_espera():
    class _EnCamino:
        producto_id = 1
        ventas_hasta = HOY
        esta_en_transito = True
        vuelve_a_proponerse = False

    memoria = memoria_de_lo_pedido([_EnCamino()], [_pospuesto()])

    assert memoria.en_camino and 1 in memoria.en_camino
    assert memoria.pospuestos == {}
    assert memoria.esperas == {}


def test_un_renglon_que_no_esta_pospuesto_no_trae_espera():
    abierto = _pospuesto()
    abierto = RenglonGuardado(
        renglon_id=1,
        estado=RENGLON_ABIERTO,
        propuesto=abierto.propuesto,
        proveedor_de_la_espera="nadro",
        espera_desde=HOY,
        listas_en_espera=1,
    )
    assert memoria_de_lo_pedido([], [abierto]).esperas == {}


def test_el_renglon_nuevo_lleva_la_espera_junto_a_la_aritmetica():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MANANA, 1, 2)],
        catalogo=[_producto(1)],
        pospuestos={1: 3},
        esperas={1: _espera()},
    )

    r = lista.renglones[0]
    assert (r.piezas_vendidas, r.piezas_pospuestas, r.cantidad_propuesta) == (2, 3, 5)
    assert r.proveedor_de_la_espera == "nadro"
    assert r.espera_desde == HOY
    assert r.listas_en_espera == 2
    assert r.espera_mandada_por == CORREO
    assert r.espera_mandada_en == MANDADO_EN


def test_un_solo_renglon_aunque_el_producto_tambien_se_vendio():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MANANA, 1, 2), _venta(MANANA, 1, 1)],
        catalogo=[_producto(1)],
        pospuestos={1: 3},
        esperas={1: _espera()},
    )
    assert [r.producto_id for r in lista.renglones] == [1]
    assert lista.renglones[0].cantidad_propuesta == 6


def test_sin_piezas_pospuestas_una_espera_huerfana_no_pinta_edad():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MANANA, 1, 2)],
        catalogo=[_producto(1)],
        esperas={1: _espera()},
    )
    r = lista.renglones[0]
    assert r.espera_desde is None and r.listas_en_espera is None
    assert r.proveedor_de_la_espera is None


def test_lo_que_no_esperaba_nace_sin_espera():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MANANA, 1, 2), _venta(MANANA, 2, 1)],
        catalogo=[_producto(1), _producto(2)],
        pospuestos={1: 3},
        esperas={1: _espera()},
    )
    otro = next(r for r in lista.renglones if r.producto_id == 2)
    assert otro.proveedor_de_la_espera is None
    assert otro.listas_en_espera is None


def test_la_frase_dice_desde_cuando_y_cuantas_listas():
    assert frase_de_la_espera(dt.date(2026, 10, 5), 3, 3) == (
        "en espera desde el lunes 5 · 3 listas"
    )


def test_la_frase_concuerda_con_una_sola_lista():
    assert frase_de_la_espera(HOY, 1, 3) == "en espera desde el martes 5 · 1 lista"


@pytest.mark.parametrize(
    "desde, listas, piezas",
    [(None, 2, 3), (HOY, None, 3), (HOY, 2, 0)],
)
def test_la_frase_calla_si_no_hay_edad_que_decir_o_no_trae_piezas(desde, listas, piezas):
    assert frase_de_la_espera(desde, listas, piezas) is None


# ==========================================================================
# 2. LO QUE SE GUARDA: columnas, CHECK, el doble y el SQL como texto
# ==========================================================================


def test_con_proveedor_y_firma_el_renglon_nace_elegido_con_la_firma_de_quien_lo_mando():
    columnas = columnas_del_renglon(_renglon_de_la_espera(), NEGOCIO, 1)

    assert columnas["proveedor_elegido"] == "nadro"
    assert columnas["elegido_por"] == CORREO, "la firma de la espera, no la de hoy"
    assert columnas["elegido_en"] == MANDADO_EN
    assert columnas["proveedor_de_la_espera"] == "nadro"
    assert columnas["espera_desde"] == HOY
    assert columnas["listas_en_espera"] == 2
    assert columnas["pedido_id"] is None, "los pedidos nacen al partir"
    revisar_el_renglon(columnas)


def test_sin_proveedor_de_la_espera_nace_sin_elegir_como_hoy():
    columnas = columnas_del_renglon(
        _renglon_de_la_espera(proveedor_de_la_espera=None), NEGOCIO, 1
    )
    assert (columnas["proveedor_elegido"], columnas["elegido_por"]) == (None, None)
    assert columnas["elegido_en"] is None
    assert columnas["listas_en_espera"] == 2, "la edad se conserva"
    revisar_el_renglon(columnas)


def test_sin_firma_no_se_inventa_una_persona_pero_el_proveedor_queda_guardado():
    renglon = _renglon_de_la_espera(espera_mandada_por=None, espera_mandada_en=None)
    assert eleccion_de_la_espera(renglon) == (None, None, None)

    columnas = columnas_del_renglon(renglon, NEGOCIO, 1)
    assert columnas["proveedor_elegido"] is None
    assert columnas["proveedor_de_la_espera"] == "nadro"
    revisar_el_renglon(columnas)


def test_un_renglon_normal_nace_sin_espera_ni_eleccion():
    normal = Renglon(
        producto_id=9,
        clave="7501000000009",
        descripcion="PRODUCTO 9",
        piezas_vendidas=1.0,
        cantidad_propuesta=1,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
    )
    columnas = columnas_del_renglon(normal, NEGOCIO, 1)
    for nombre in (
        "proveedor_elegido",
        "elegido_por",
        "elegido_en",
        "proveedor_de_la_espera",
        "espera_desde",
        "listas_en_espera",
    ):
        assert columnas[nombre] is None, nombre


def test_el_insert_escribe_las_seis_columnas_nuevas():
    sql = modulo_almacenamiento._INSERTAR_RENGLONES.text
    for nombre in (
        "proveedor_elegido",
        "elegido_por",
        "elegido_en",
        "proveedor_de_la_espera",
        "espera_desde",
        "listas_en_espera",
    ):
        assert f":{nombre}" in sql, nombre
    # Cada columna del `insert` tiene su marcador en `values`.
    columnas, valores = sql.split("values")
    assert columnas.count(",") + 1 == valores.count(":")


def test_el_doble_guarda_lo_que_nacio_con_la_espera(almacenamiento):
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO, MANANA, Ventana(MANANA, MANANA), [_renglon_de_la_espera()]
    )

    r = lista.renglones[0]
    assert r.estado == RENGLON_ABIERTO
    assert (r.proveedor_elegido, r.elegido_por, r.elegido_en) == (
        "nadro",
        CORREO,
        MANDADO_EN,
    )
    assert (r.proveedor_de_la_espera, r.espera_desde, r.listas_en_espera) == (
        "nadro",
        HOY,
        2,
    )
    assert r.pedido_id is None


def test_el_doble_rechaza_una_eleccion_sin_firma_igual_que_la_base():
    columnas = columnas_del_renglon(_renglon_de_la_espera(), NEGOCIO, 1)
    columnas["elegido_por"] = None
    with pytest.raises(ValueError, match="ck_renglon_eleccion"):
        revisar_el_renglon(columnas)


# ==========================================================================
# 3. LA PARTICIÓN RESPETA LA ELECCIÓN DE LA ESPERA
# ==========================================================================


def _guardado_desde_espera(almacenamiento, **cambios) -> RenglonGuardado:
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO,
        MANANA,
        Ventana(MANANA, MANANA),
        [_renglon_de_la_espera(**cambios)],
    )
    return lista.renglones[0]


def _lectura(proveedor: str, precio: str) -> LecturaDePrecio:
    """Lo que Doyle contesta (se guarda con `guardar_precios`)."""
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego=precio,
        precio=Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def test_la_eleccion_de_la_espera_es_una_decision_con_su_firma(almacenamiento):
    renglon = _guardado_desde_espera(almacenamiento)

    eleccion = elegir(renglon, _comparacion_vacia())

    assert eleccion.proveedor == "nadro"
    assert eleccion.es_decision is True
    assert eleccion.elegido_por == CORREO


def test_otro_proveedor_mas_barato_se_dice_pero_no_cambia_la_eleccion(almacenamiento):
    from continental.comparacion import comparar

    renglon = _guardado_desde_espera(almacenamiento)
    lecturas = [
        _guardada(renglon.renglon_id, "nadro", "20.00"),
        _guardada(renglon.renglon_id, "levic", "10.00"),
    ]

    eleccion = elegir(renglon, comparar(lecturas, renglon.cantidad_a_pedir))

    assert eleccion.proveedor == "nadro", "no se cambia solo"
    assert eleccion.sugerido == "levic"
    assert eleccion.difiere_de_la_sugerencia is True


def test_partir_arma_el_pedido_de_su_proveedor_con_la_cantidad_sumada(almacenamiento):
    from continental.comparacion import comparar

    renglon = _guardado_desde_espera(almacenamiento)
    lecturas = [
        _guardada(renglon.renglon_id, "nadro", "20.00"),
        _guardada(renglon.renglon_id, "levic", "10.00"),
    ]
    comparaciones = {renglon.renglon_id: comparar(lecturas, 5)}

    particion = partir(
        [renglon], comparaciones, {renglon.renglon_id: lecturas}, {}
    )

    assert [p.proveedor for p in particion.pedidos] == ["nadro"]
    linea = particion.pedidos[0].lineas[0]
    assert linea.cantidad == 5
    assert particion.pedidos[0].total_sin_iva == Decimal("100.00")


def _guardada(renglon_id: int, proveedor: str, precio: str) -> PrecioDeProveedor:
    """La misma lectura, ya guardada: es lo que `comparar` recibe."""
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor=proveedor,
        consultado_en=MANDADO_EN,
        precio_como_llego=precio,
        precio=Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def _comparacion_vacia():
    from continental.particion import SIN_COMPARACION

    return SIN_COMPARACION


# ==========================================================================
# 4. EL SQL COMO TEXTO: lo que sigue valiendo
# ==========================================================================


def test_lo_pospuesto_sigue_leyendose_de_la_lista_inmediatamente_anterior():
    sql = modulo_almacenamiento._LO_POSPUESTO.text
    assert "max(s2.fecha_del_pedido)" in sql
    assert "s2.fecha_del_pedido < :antes_de" in sql
    for columna in ("proveedor_de_la_espera", "espera_desde", "listas_en_espera"):
        assert columna in sql


def test_la_firma_de_la_espera_la_trae_la_misma_lectura():
    sql = modulo_almacenamiento._LO_POSPUESTO.text
    assert "r.pospuesto_por" in sql and "r.pospuesto_en" in sql


# ==========================================================================
# 5. DE PUNTA A PUNTA, VARIOS DÍAS
# ==========================================================================


def _firma(correo: str = CORREO) -> dict:
    return {"Cf-Access-Authenticated-User-Email": correo}


def _renglon_json(lista: dict, producto_id: int) -> dict:
    return next(r for r in lista["renglones"] if r["producto_id"] == producto_id)


def _posponer(cliente, renglon_id: int, correo: str = CORREO):
    return cliente.post(f"/api/renglon/{renglon_id}/posponer", headers=_firma(correo))


def _lunes(cliente, almacen, almacenamiento):
    """El primer día: dos renglones a NADRO, partidos en un pedido."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3), _venta(HOY, 2, 1)]
    lista = cliente.get(RUTA).json()
    for r in lista["renglones"]:
        almacenamiento.guardar_precios(
            NEGOCIO, r["renglon_id"], [_lectura("nadro", "10.00")]
        )
    lista = cliente.get(RUTA).json()
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")
    return cliente.get(RUTA).json()


def test_el_dia_siguiente_el_renglon_aparece_elegido_y_partido_en_el_pedido_de_su_proveedor(
    cliente, almacen, almacenamiento
):
    primera = _lunes(cliente, almacen, almacenamiento)
    _posponer(cliente, _renglon_json(primera, 1)["renglon_id"])

    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 2))
    segunda = cliente.get(RUTA).json()

    r = _renglon_json(segunda, 1)
    # La aritmética, en un solo renglón: se vendieron 2 y esperaban 3, se piden 5.
    assert (r["piezas_vendidas"], r["piezas_pospuestas"], r["cantidad_a_pedir"]) == (
        2,
        3,
        5,
    )
    assert "se vendieron 2 y esperaban 3 piezas, se piden 5" in (
        r["frase_de_lo_que_paso_del_dia_anterior"]
    )
    assert len([x for x in segunda["renglones"] if x["producto_id"] == 1]) == 1
    # Nace elegido a su proveedor, con la firma de quien lo mandó a espera.
    assert r["eleccion"]["proveedor"] == "nadro"
    assert r["eleccion"]["es_decision"] is True
    assert r["eleccion"]["elegido_por"] == CORREO
    assert r["proveedor_de_la_espera"] == "nadro"
    # Desde cuándo y cuántas listas, dicho en Python.
    assert r["espera_desde"] == HOY.isoformat()
    assert r["listas_en_espera"] == 2
    assert r["frase_de_la_espera"] == "en espera desde el martes 5 · 2 listas"

    # Al partir, su pedido en borrador es el de NADRO, con las 5 piezas.
    partida = cliente.post(f"{RUTA}/{segunda['pedido_sugerido_id']}/partir").json()
    assert [p["proveedor"] for p in partida["pedidos"]] == ["nadro"]
    renglon = _renglon_json(partida, 1)
    assert renglon["pedido_id"] == partida["pedidos"][0]["pedido_id"]
    linea = next(
        l
        for l in partida["particion"]["pedidos"][0]["lineas"]
        if l["renglon_id"] == renglon["renglon_id"]
    )
    assert linea["cantidad"] == 5


def test_volver_a_mandarlo_conserva_la_edad_y_no_cuenta_las_piezas_dos_veces(
    cliente, almacen, almacenamiento
):
    primera = _lunes(cliente, almacen, almacenamiento)
    _posponer(cliente, _renglon_json(primera, 1)["renglon_id"])
    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 2))
    segunda = cliente.get(RUTA).json()
    cliente.post(f"{RUTA}/{segunda['pedido_sugerido_id']}/partir")
    reenviado = _posponer(
        cliente, _renglon_json(segunda, 1)["renglon_id"], correo=OTRO
    ).json()["renglon"]

    assert reenviado["estado"] == RENGLON_POSPUESTO
    assert reenviado["proveedor_de_la_espera"] == "nadro"
    assert reenviado["espera_desde"] == HOY.isoformat(), "la fecha de la primera vez"
    assert reenviado["listas_en_espera"] == 2

    almacen.ventas_en_memoria.append(_venta(PASADO, 1, 1))
    tercera = cliente.get(RUTA).json()

    r = _renglon_json(tercera, 1)
    # Las 5 de antes (3 que esperaban + 2 vendidas) pasan enteras y se suma 1:
    # no se cuentan dos veces las 3 de la espera.
    assert (r["piezas_pospuestas"], r["piezas_vendidas"], r["cantidad_a_pedir"]) == (
        5,
        1,
        6,
    )
    assert r["espera_desde"] == HOY.isoformat()
    assert r["listas_en_espera"] == 3
    assert r["frase_de_la_espera"] == "en espera desde el martes 5 · 3 listas"
    # La decisión conserva la firma de quien lo mandó la segunda vez.
    assert r["eleccion"]["proveedor"] == "nadro"
    assert r["eleccion"]["elegido_por"] == OTRO


def test_sin_proveedor_de_la_espera_se_reparte_como_hoy(cliente, almacen):
    """Mandado a espera desde Revisar, antes de repartir: no hay a quién."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3), _venta(HOY, 2, 1)]
    primera = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_json(primera, 1)["renglon_id"])

    almacen.ventas_en_memoria.append(_venta(MANANA, 2, 1))
    segunda = cliente.get(RUTA).json()

    r = _renglon_json(segunda, 1)
    assert r["cantidad_a_pedir"] == 3
    assert r["eleccion"]["es_decision"] is False
    assert r["eleccion"]["elegido_por"] is None
    assert r["proveedor_de_la_espera"] is None
    # Pero la edad sí viaja: el renglón sigue diciendo desde cuándo espera.
    assert r["frase_de_la_espera"] == "en espera desde el martes 5 · 2 listas"


def test_un_renglon_que_no_vino_de_la_espera_no_dice_nada_de_espera(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3)]

    r = _renglon_json(cliente.get(RUTA).json(), 1)

    assert r["frase_de_la_espera"] is None
    assert r["eleccion"]["es_decision"] is False


# ==========================================================================
# 6. LO QUE SE VE: la estática del JavaScript
# ==========================================================================


def test_la_pantalla_pinta_la_edad_de_la_espera_sin_componerla():
    js = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "continental"
        / "web"
        / "static"
        / "continental.js"
    ).read_text(encoding="utf-8")
    assert "r.frase_de_la_espera" in js
    # La frase llega hecha: el JS no sabe de días de la semana ni de listas.
    assert "listas_en_espera" not in js.split("r.frase_de_la_espera")[0][-400:]


# ==========================================================================
# AL CERRAR (ticket 07): lo que volvió de la espera se avisa
# ==========================================================================


def _martes_con_lo_de_la_espera(cliente, almacen, almacenamiento) -> dict:
    """Lunes manda el producto 1 a espera; el día siguiente vuelve con 3 piezas."""
    primera = _lunes(cliente, almacen, almacenamiento)
    _posponer(cliente, _renglon_json(primera, 1)["renglon_id"])
    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 2))
    return cliente.get(RUTA).json()


def test_cerrar_con_un_renglon_que_volvio_de_la_espera_lo_avisa_de_punta_a_punta(
    cliente, almacen, almacenamiento
):
    segunda = _martes_con_lo_de_la_espera(cliente, almacen, almacenamiento)

    resumen = cliente.get(f"{RUTA}/{segunda['pedido_sugerido_id']}/al-cerrar").json()

    [perdida] = resumen["se_perderian"]
    assert perdida["renglon_id"] == _renglon_json(segunda, 1)["renglon_id"]
    assert perdida["piezas_de_la_espera"] == 3
    assert "3 piezas que volvieron de la espera (en espera desde el martes 5 · 2 listas)" in (
        perdida["frase"]
    )
    assert "reabrir deja de servir en cuanto se arma la lista siguiente" in perdida["frase"]
    assert resumen["boton"] == "Cerrar de todos modos"
    # Avisa, no prohíbe: cerrar sigue funcionando y da por atendido.
    cerrada = cliente.post(f"{RUTA}/{segunda['pedido_sugerido_id']}/cerrar")
    assert cerrada.status_code == 200


def test_cerrar_con_el_renglon_en_espera_no_lo_avisa_de_punta_a_punta(
    cliente, almacen, almacenamiento
):
    """Volvió, y la encargada lo mandó a esperar otra vez: ya tiene adónde ir."""
    segunda = _martes_con_lo_de_la_espera(cliente, almacen, almacenamiento)
    cliente.post(f"{RUTA}/{segunda['pedido_sugerido_id']}/partir")
    _posponer(cliente, _renglon_json(segunda, 1)["renglon_id"], correo=OTRO)

    resumen = cliente.get(f"{RUTA}/{segunda['pedido_sugerido_id']}/al-cerrar").json()

    assert resumen["se_perderian"] == []
    assert resumen["boton"] == "Cerrar la lista"
