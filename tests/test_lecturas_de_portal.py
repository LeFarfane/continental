"""Cada consulta a los portales, guardada entera (2026-09-28).

El dueño pidió tomar cada consulta como una oportunidad: todo lo que contesta
cada portal —no solo el precio que empareja— va a `pedidos.lectura_de_portal`,
con la fecha y con quién NO tenía el producto, para preguntarle después a
Metabase cómo se mueven los precios de compra.

Ninguna prueba toca Postgres, ni Doyle, ni la red, ni duerme.
"""

from __future__ import annotations

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


@pytest.mark.parametrize("ruta", ["sql/crear_tablas.sql", "sql/migraciones/0015-lo-que-contesto-cada-portal.sql"])
def test_los_origenes_y_resultados_del_check_son_los_del_codigo(ruta):
    """Con el acento de "no terminó": un CHECK sin él rebotaría el primer
    INSERT de un portal que tardó de más."""
    sql = _texto(ruta)

    assert _en_el_check(sql, "ck_lectura_origen") == set(ORIGENES)
    assert _en_el_check(sql, "ck_lectura_resultado") == set(RESULTADOS)


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
