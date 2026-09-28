"""Cada consulta a los portales, guardada entera (2026-09-28).

El dueño pidió tomar cada consulta como una oportunidad: todo lo que contesta
cada portal —no solo el precio que empareja— va a `pedidos.lectura_de_portal`,
con la fecha y con quién NO tenía el producto, para preguntarle después a
Metabase cómo se mueven los precios de compra.

Ninguna prueba toca Postgres, ni Doyle, ni la red, ni duerme.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from pathlib import Path

import pytest

from continental.lecturas_de_portal import (
    BUSCAR,
    CON_RESULTADOS,
    CONSULTAR,
    NO_LO_TIENE,
    NO_SE_SABE_LEER,
    NO_TERMINO,
    ORIGENES,
    RESULTADOS,
    SIN_DATO,
    lecturas_de_portal,
)
from continental.consultas import RegistroDeConsultas, consultar_y_congelar
from continental.dobles import (
    AlmacenamientoFalso,
    DoyleFalso,
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_en_reconocimiento,
    respuesta_lista,
    respuesta_pendiente,
)
from continental.doyle import EstadoDeBusqueda
from continental.precios import SESION_CADUCADA, SIN_RESULTADOS

RAIZ = Path(__file__).resolve().parents[1]
EAN = "7501000000001"
NEGOCIO = "farmacia_01"
NO_ENCONTRO = "No se encontraron artículos. Si este error continúa, notifíquelo al administrador."


def _estado(**por_proveedor) -> EstadoDeBusqueda:
    return EstadoDeBusqueda(termino=EAN, proveedores=dict(por_proveedor))


def _lecturas(estado, **extra):
    return lecturas_de_portal(estado, origen=CONSULTAR, termino=EAN, trabajo="t-1", **extra)


# =========================================================================
# LO PURO
# =========================================================================


def test_cada_resultado_de_cada_portal_es_una_fila_con_su_posicion():
    """Todas las filas, no solo la que empareja: la de 20 unidades, la de 10."""
    [primera, segunda] = _lecturas(_estado(
        nadro=respuesta_lista("nadro", [(EAN, "86.05", "40"), ("7501000000002", "46.10", "0")]),
    ))

    assert (primera.posicion, primera.resultado, primera.precio) == (1, CON_RESULTADOS, Decimal("86.05"))
    assert (segunda.posicion, segunda.existencia) == (2, Decimal("0"))


def test_el_precio_se_guarda_como_llego_y_como_numero_nunca_en_cero():
    [fila] = _lecturas(_estado(nadro=respuesta_lista("nadro", [(EAN, "0.00", "DISPONIBLE")])))

    assert fila.precio is None and fila.precio_como_llego == "0.00"
    assert fila.existencia is None and fila.existencia_como_llego == "DISPONIBLE"


@pytest.mark.parametrize(
    ("respuesta", "resultado", "motivo"),
    [
        (respuesta_lista("vicma", []), NO_LO_TIENE, SIN_RESULTADOS),
        (respuesta_con_error("vicma", NO_ENCONTRO), NO_LO_TIENE, SIN_RESULTADOS),
        (respuesta_con_sesion_caducada("vicma"), SIN_DATO, SESION_CADUCADA),
        (respuesta_en_reconocimiento("vicma"), NO_SE_SABE_LEER, "no se sabe leer la página"),
    ],
    ids=["vacio", "no-encontro", "sesion", "reconocimiento"],
)
def test_quien_no_trajo_nada_deja_su_fila_cero_con_por_que(respuesta, resultado, motivo):
    """"Quién no tenía el producto" es `sin resultados`; lo demás es `sin
    dato`: no se sabe si lo tiene."""
    [fila] = _lecturas(_estado(vicma=respuesta))

    assert (fila.posicion, fila.resultado, fila.motivo) == (0, resultado, motivo)


def test_lo_que_sigue_buscando_no_se_guarda_salvo_que_se_acabe_el_tiempo():
    estado = _estado(nadro=respuesta_lista("nadro", [(EAN, "86.05", "40")]),
                     levic=respuesta_pendiente("levic"))

    assert [f.proveedor for f in _lecturas(estado)] == ["nadro"]
    al_tope = _lecturas(estado, incluir_pendientes=True)
    assert [(f.proveedor, f.resultado) for f in al_tope] == [("levic", NO_TERMINO), ("nadro", CON_RESULTADOS)]


def test_un_origen_desconocido_truena():
    with pytest.raises(ValueError):
        lecturas_de_portal(_estado(), origen="otro", termino=EAN, trabajo="t-1")


# =========================================================================
# DÓNDE SE GUARDA
# =========================================================================


def _registro():
    return RegistroDeConsultas(lanzar=lambda tarea: tarea())


def test_consultar_un_precio_guarda_todo_lo_que_contesto_cada_portal():
    doyle = DoyleFalso(resultados_por_termino={EAN: {
        "nadro": respuesta_lista("nadro", [(EAN, "86.05", "40"), ("X", "1.00", "1")]),
        "vicma": respuesta_con_error("vicma", NO_ENCONTRO),
    }})
    almacenamiento = AlmacenamientoFalso()
    registro = _registro()
    consulta, _ = registro.apartar(7, EAN)

    consultar_y_congelar(consulta, doyle=doyle, almacenamiento=almacenamiento,
                         registro=registro, negocio=NEGOCIO, dormir=lambda s: None)

    filas = almacenamiento.lecturas_de_portal
    assert [(f["proveedor"], f["posicion"]) for f in filas] == [("nadro", 1), ("nadro", 2), ("vicma", 0)]
    assert {(f["origen"], f["renglon_id"], f["negocio"]) for f in filas} == {(CONSULTAR, 7, NEGOCIO)}


def test_si_guardar_falla_el_precio_se_congela_igual(caplog):
    """Guardar de más es una oportunidad; perderla no puede costar el precio."""
    doyle = DoyleFalso(resultados_por_termino={EAN: {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")])}})
    almacenamiento = AlmacenamientoFalso()
    congelados = []

    def truena(*a, **k):
        raise RuntimeError("SECRETO")

    almacenamiento.guardar_lecturas_de_portal = truena
    almacenamiento.guardar_precios = lambda negocio, renglon_id, lecturas: congelados.append(lecturas) or 1
    registro = _registro()
    consulta, _ = registro.apartar(7, EAN)

    with caplog.at_level(logging.ERROR, logger="continental"):
        consultar_y_congelar(consulta, doyle=doyle, almacenamiento=almacenamiento,
                             registro=registro, negocio=NEGOCIO, dormir=lambda s: None)

    assert len(congelados) == 1
    assert any(r.exc_info for r in caplog.records)


def test_buscar_guarda_cada_proveedor_una_sola_vez_aunque_se_sondee_varias(cliente, doyle, almacenamiento):
    doyle.vueltas_por_termino = {EAN: [
        {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")]), "levic": respuesta_pendiente("levic")},
        {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")]), "levic": respuesta_lista("levic", [])},
    ]}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]

    cliente.get(f"/api/buscar/{job_id}")
    tras_la_primera = [(f["proveedor"], f["posicion"]) for f in almacenamiento.lecturas_de_portal]
    cliente.get(f"/api/buscar/{job_id}")
    cliente.get(f"/api/buscar/{job_id}")

    assert tras_la_primera == [("nadro", 1)]
    filas = almacenamiento.lecturas_de_portal
    assert [(f["proveedor"], f["posicion"], f["resultado"]) for f in filas] == [
        ("nadro", 1, CON_RESULTADOS), ("levic", 0, NO_LO_TIENE)]
    assert {f["origen"] for f in filas} == {BUSCAR}


def test_si_guardar_falla_la_busqueda_se_ve_igual(cliente, doyle, almacenamiento):
    doyle.resultados_por_termino = {EAN: {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")])}}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]

    def truena(*a, **k):
        raise RuntimeError("SECRETO")

    almacenamiento.guardar_lecturas_de_portal = truena
    respuesta = cliente.get(f"/api/buscar/{job_id}")

    assert respuesta.json()["ok"] is True
    assert "SECRETO" not in respuesta.text


@pytest.mark.parametrize("donde", ["origen=LOTE", "origen=SONDA_DEL_LOTE"])
def test_el_lote_y_su_sonda_tambien_guardan(donde):
    assert donde in (RAIZ / "src" / "continental" / "lote.py").read_text(encoding="utf-8")


# =========================================================================
# EL SQL DICE LO MISMO QUE EL CÓDIGO
# =========================================================================


def _texto(ruta: str) -> str:
    return (RAIZ / ruta).read_bytes().decode("utf-8")


def _en_el_check(sql: str, nombre: str) -> set[str]:
    cuerpo = re.search(nombre + r"\s+CHECK \((.*?)\)\)", sql, re.S).group(1)
    return set(re.findall(r"'([^']+)'", cuerpo))


@pytest.mark.parametrize("ruta", ["sql/crear_tablas.sql", "sql/migraciones/0016-la-consulta-al-abrir-sesion.sql"])
def test_los_origenes_del_check_son_los_del_codigo(ruta):
    """La 0015 los estrenó y la 0016 agregó 'al abrir sesión': la base desde
    cero y la migrada tienen que aceptar los mismos, con su acento."""
    assert _en_el_check(_texto(ruta), "ck_lectura_origen") == set(ORIGENES)


@pytest.mark.parametrize("ruta", ["sql/crear_tablas.sql", "sql/migraciones/0015-lo-que-contesto-cada-portal.sql"])
def test_los_resultados_del_check_son_los_del_codigo(ruta):
    """Con el acento de "no terminó": un CHECK sin él rebotaría el primer
    INSERT de un portal que tardó de más."""
    assert _en_el_check(_texto(ruta), "ck_lectura_resultado") == set(RESULTADOS)


def test_la_fecha_es_el_dia_de_la_farmacia_sin_la_trampa_posix():
    """`AT TIME ZONE '-06'` se lee como UTC+6 (ticket 25)."""
    sql = _texto("sql/crear_tablas.sql")

    assert "((now() AT TIME ZONE 'UTC') - interval '6 hours')::date" in sql
    assert "'-06'" not in sql.split("pedidos.lectura_de_portal", 1)[1]


def test_la_migracion_trae_su_propio_grant():
    assert "GRANT SELECT, INSERT, UPDATE ON pedidos.lectura_de_portal TO continental;" in _texto(
        "sql/migraciones/0015-lo-que-contesto-cada-portal.sql")


def test_metabase_solo_puede_leer_esta_tabla():
    """La puerta que pidió el dueño, angosta: SELECT sobre una tabla, nada más."""
    grants = [l for l in _texto("sql/crear_rol_metabase.sql").splitlines() if l.startswith("GRANT")]

    assert grants == [
        "GRANT CONNECT ON DATABASE farmacia TO metabase_continental;",
        "GRANT USAGE ON SCHEMA pedidos TO metabase_continental;",
        "GRANT SELECT ON pedidos.lectura_de_portal TO metabase_continental;",
    ]


# =========================================================================
# «YA ENTRÉ» EN LEVIC DISPARA LA LISTA, SOLO EN LEVIC (plan B, 2026-09-28)
# =========================================================================

import datetime as dt  # noqa: E402

import httpx  # noqa: E402

from continental.almacen import LineaDeVenta, Producto  # noqa: E402
from continental.consultas import proveedores_que_consultan_al_abrir  # noqa: E402
from continental.doyle import DoylePorHttp  # noqa: E402
from continental.lecturas_de_portal import AL_ABRIR_SESION  # noqa: E402

VIERNES = dt.date(2026, 9, 25)


def _lista_con_un_renglon(cliente, almacen, doyle):
    almacen.catalogo_en_memoria = [Producto(
        producto_id=1, clave=EAN, descripcion="PARACETAMOL", categoria="GRUP4",
        departamento="MEDICAMENTO", anaquel="GENERICO 1", precio_lista_sin_iva=20.0,
        costo=8.0, existencia=3, esta_activo=True, es_granel=False,
    )]
    almacen.ventas_en_memoria = [LineaDeVenta(fecha=VIERNES, producto_id=1, cantidad=2,
                                              importe=40, costo=16, utilidad=24)]
    assert cliente.get("/api/pedido-sugerido").json()["ok"] is True
    doyle.resultados_por_termino = {EAN: {
        p: respuesta_lista(p, [(EAN, "20.00", "5")]) for p in ("nadro", "levic", "vicma", "quepharma")
    }}


def test_ya_entre_en_levic_consulta_la_lista_solo_en_levic(cliente, almacen, almacenamiento, doyle):
    _lista_con_un_renglon(cliente, almacen, doyle)
    doyle.sesiones_abriendose = ["levic"]

    datos = cliente.post("/api/sesion/levic/confirmar").json()

    assert datos["ok"] is True and "solo en LEVIC" in datos["consulta_disparada"]
    assert doyle.filtros == [("levic",)]
    assert {f["proveedor"] for f in almacenamiento.precios} == {"levic"}
    assert {(f["proveedor"], f["origen"]) for f in almacenamiento.lecturas_de_portal} == {
        ("levic", AL_ABRIR_SESION)}


def test_ya_entre_en_un_portal_que_no_esta_en_el_yaml_no_dispara_nada(cliente, almacen, doyle):
    _lista_con_un_renglon(cliente, almacen, doyle)
    doyle.sesiones_abriendose = ["nadro"]

    datos = cliente.post("/api/sesion/nadro/confirmar").json()

    assert datos["consulta_disparada"] is None and doyle.pedidos == []


def test_si_la_pagina_seguia_en_el_login_no_se_gasta_la_consulta(cliente, almacen, doyle):
    _lista_con_un_renglon(cliente, almacen, doyle)
    doyle.sesiones_abriendose = ["levic"]
    doyle.sesiones_que_siguen_en_login = ["levic"]

    assert cliente.post("/api/sesion/levic/confirmar").json()["consulta_disparada"] is None
    assert doyle.pedidos == []


def test_sin_lista_abierta_confirmar_funciona_igual(cliente, doyle):
    doyle.sesiones_abriendose = ["levic"]

    datos = cliente.post("/api/sesion/levic/confirmar").json()

    assert datos["ok"] is True and datos["consulta_disparada"] is None


def test_el_filtro_viaja_a_doyle_solo_cuando_hay_filtro():
    enviados = []

    def contestar(peticion):
        enviados.append(json.loads(peticion.content))
        return httpx.Response(200, json={"job_id": "x", "proveedores": ["levic"]})

    doyle = DoylePorHttp(url="http://127.0.0.1:8383", transporte=httpx.MockTransport(contestar))
    doyle.pedir_busqueda(EAN)
    doyle.pedir_busqueda(EAN, ("levic",))

    assert enviados == [{"termino": EAN}, {"termino": EAN, "proveedores": ["levic"]}]


def test_levic_es_el_que_se_consulta_al_abrir():
    assert proveedores_que_consultan_al_abrir() == ("levic",)
