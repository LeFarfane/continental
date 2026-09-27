"""El cierre automático de listas anteriores, y `cerrado_por` (2026-09-27).

Decisión del dueño: "al crearse la lista de hoy, se cierra sola la de ayer.
Automático, sin intervención." Sustituye a `vencer_las_de_dias_anteriores` en
el flujo de abrir el día (`web/app.py::pedido_sugerido` y
`lote.py::correr_el_lote`), que hasta ahora dejaba `vencida` —sin mover el
corte, sin poder reabrirse nunca (ADR 0016)— cualquier lista abierta de un día
anterior.

Este archivo prueba la pieza nueva de datos y almacenamiento:

- `pedidos.pedido_sugerido.cerrado_por` (migración 0013): quién cerró la
  lista la última vez, con los mismos dos CHECK que ya tiene `reabierto_por`
  desde el ADR 0016 (ninguno exige el par simétrico, porque una fila cerrada
  antes de esta migración se queda en `NULL` para siempre y eso es válido).
- `almacenamiento.cerrar_las_de_dias_anteriores`: la función que reemplaza a
  `vencer_las_de_dias_anteriores` en el flujo de abrir el día.

Los escenarios de punta a punta —qué pasa con la ventana, con lo cancelado,
con lo recibido parcial— viven donde ya vivían: `test_acumulacion.py`,
`test_cancelar.py`, `test_parcial.py`, `test_transito.py` y `test_cierre.py`
se actualizaron el mismo día para reflejar el cambio. Aquí se prueba la pieza
en sí, aislada.

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from continental.almacenamiento import (
    ABIERTO,
    CERRADO,
    SISTEMA,
    VENCIDO,
    Ventana,
    revisar_la_lista,
)
from continental.cierre import lo_que_se_perderia
from continental.dobles import AlmacenamientoFalso
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0013-cerrado_por-la-firma-del-cierre.sql"

NEGOCIO = "farmacia_01"
LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
DUENO = "dueno@farmacia.mx"


def _renglon(producto_id: int, cantidad: int = 3) -> Renglon:
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


def _lista(almacenamiento, fecha: dt.date, negocio: str = NEGOCIO, producto_id: int = 1):
    return almacenamiento.insertar_la_lista(
        negocio, fecha, Ventana(fecha, fecha), [_renglon(producto_id)]
    )


# ==========================================================================
# `almacenamiento.cerrar_las_de_dias_anteriores`
# ==========================================================================


def test_cierra_todas_las_abiertas_de_dias_anteriores_de_una_vez(almacenamiento):
    """No solo "la de ayer": todas las que sigan abiertas de días anteriores.

    Si por lo que sea quedaron dos o tres sin cerrar, se cierran todas con la
    misma firma y la misma hora, igual que ya hacía `vencer_las_de_dias_anteriores`."""
    _lista(almacenamiento, LUNES)
    _lista(almacenamiento, MARTES)

    cerradas = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MIERCOLES, SISTEMA)

    assert {c.fecha_del_pedido for c in cerradas} == {LUNES, MARTES}
    for cerrada in cerradas:
        assert cerrada.estado == CERRADO
        assert cerrada.cerrado_por == SISTEMA
        assert cerrada.cerrado_en is not None
    assert almacenamiento.leer(NEGOCIO, LUNES).estado == CERRADO
    assert almacenamiento.leer(NEGOCIO, MARTES).estado == CERRADO


def test_no_toca_la_del_dia_que_se_esta_abriendo_ni_las_ya_cerradas(almacenamiento):
    """El `WHERE` es `estado = 'abierto' AND fecha_del_pedido < :fecha`: ni
    igual ni posterior, y no vuelve a tocar lo que ya estaba cerrado."""
    _lista(almacenamiento, LUNES)
    almacenamiento.cerrar(NEGOCIO, almacenamiento.leer(NEGOCIO, LUNES).pedido_sugerido_id, DUENO)
    _lista(almacenamiento, MARTES)

    cerradas = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MARTES, SISTEMA)

    assert cerradas == (), "No había nada abierto antes de martes: no debía cerrar nada."
    assert almacenamiento.leer(NEGOCIO, LUNES).cerrado_por == DUENO, (
        "Se le pisó la firma a una lista que ya estaba cerrada por una persona."
    )
    assert almacenamiento.leer(NEGOCIO, MARTES).estado == ABIERTO


def test_no_toca_los_renglones_solo_la_lista(almacenamiento):
    """Cerrar no descarta ni cambia ningún renglón: lo que seguía `abierto`
    sigue `abierto`, nada más deja de proponerse."""
    _lista(almacenamiento, LUNES)

    [cerrada] = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MARTES, SISTEMA)

    assert [r.estado for r in cerrada.renglones] == ["abierto"]


def test_devuelve_las_listas_con_sus_renglones_para_loguear_lo_que_se_pierde(
    almacenamiento,
):
    """El cierre automático no puede mostrar un diálogo de confirmación —no
    hay nadie ahí para leerlo—, pero tampoco puede ser silencioso (regla 4 de
    `CLAUDE.md`): devuelve la lista ENTERA, con renglones, para que quien
    llame pueda loguear `cierre.lo_que_se_perderia` antes de seguir.

    Con piezas que faltaron de un pedido anterior (ADR 0015): eso es
    justamente lo que `se_perderia` mide -no las ventas ordinarias de la
    propia ventana, que un renglón sin pedir cualquier día es la decisión de
    todos los días (ADR 0016)-.
    """
    renglon_con_faltantes = Renglon(
        producto_id=1, clave="7501000000001", descripcion="PRODUCTO 1",
        piezas_vendidas=3.0, cantidad_propuesta=7, esta_en_el_catalogo=True,
        existencia=0.0, dias_de_cobertura=None, clasificacion="medicamento",
        piezas_que_faltaron=4,
    )
    almacenamiento.insertar_la_lista(
        NEGOCIO, LUNES, Ventana(LUNES, LUNES), [renglon_con_faltantes]
    )

    [cerrada] = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MARTES, SISTEMA)

    perdidas = lo_que_se_perderia(cerrada)
    assert len(perdidas) == 1
    assert perdidas[0].propuesto.producto_id == 1
    assert perdidas[0].propuesto.piezas_que_faltaron == 4


def test_una_lista_recien_cerrada_sola_nace_sin_reapertura_previa(almacenamiento):
    _lista(almacenamiento, LUNES)

    [cerrada] = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MARTES, SISTEMA)

    assert cerrada.reabierto_por is None and cerrada.reabierto_en is None


def test_reabrir_limpia_la_firma_del_cierre(almacenamiento):
    """`cerrado_por` se limpia al reabrir, igual que `cerrado_en`: "quién
    cerró" deja de describir algo en cuanto la lista vuelve a `abierto`."""
    _lista(almacenamiento, LUNES)
    [cerrada] = almacenamiento.cerrar_las_de_dias_anteriores(NEGOCIO, MARTES, SISTEMA)
    assert cerrada.cerrado_por == SISTEMA

    reabierta = almacenamiento.reabrir(NEGOCIO, cerrada.pedido_sugerido_id, DUENO, MARTES)

    assert reabierta is not None
    assert reabierta.cerrado_por is None
    assert reabierta.cerrado_en is None
    assert reabierta.reabierto_por == DUENO


def test_cerrar_por_una_persona_tambien_guarda_la_firma(almacenamiento):
    """`cerrar()` (el botón manual) también llena `cerrado_por` desde este
    ticket -- antes no guardaba quién cerró (ADR 0016 lo decía explícito:
    "nadie lo consulta"). Ahora sí hay quien lo consulta: distinguir un cierre
    automático de uno manual."""
    _lista(almacenamiento, LUNES)
    lista_id = almacenamiento.leer(NEGOCIO, LUNES).pedido_sugerido_id

    cerrada = almacenamiento.cerrar(NEGOCIO, lista_id, DUENO)

    assert cerrada.cerrado_por == DUENO


def test_cerrar_sin_decir_quien_sigue_funcionando_como_antes(almacenamiento):
    """`quien` es opcional y `None` por omisión: el código -y las pruebas- que
    llamaban `cerrar(negocio, id)` con dos argumentos, de antes de esta
    migración, no se rompen."""
    _lista(almacenamiento, LUNES)
    lista_id = almacenamiento.leer(NEGOCIO, LUNES).pedido_sugerido_id

    cerrada = almacenamiento.cerrar(NEGOCIO, lista_id)

    assert cerrada.estado == CERRADO
    assert cerrada.cerrado_por is None


# ==========================================================================
# LOS CHECK — `cerrado_por` no miente lo que Postgres rechazaría
# ==========================================================================


def _columnas(**cambios) -> dict:
    return {
        "negocio": NEGOCIO,
        "fecha_del_pedido": LUNES,
        "estado": ABIERTO,
        "ventas_consideradas_desde": LUNES,
        "ventas_consideradas_hasta": LUNES,
        "cerrado_en": None,
        "reabierto_por": None,
        "reabierto_en": None,
        "cerrado_por": None,
        **cambios,
    }


def test_una_lista_abierta_puede_no_tener_cerrado_por():
    revisar_la_lista(_columnas())


def test_cerrado_por_no_va_vacio():
    with pytest.raises(ValueError, match="ck_pedido_sugerido_cerrado_por"):
        revisar_la_lista(
            _columnas(estado=CERRADO, cerrado_en=dt.datetime(2026, 9, 14, tzinfo=dt.UTC),
                      cerrado_por="")
        )


def test_cerrado_por_exige_tener_hora_de_cierre():
    """Firmar un cierre que no pasó no tiene sentido: si hay `cerrado_por`,
    tiene que haber `cerrado_en`."""
    with pytest.raises(ValueError, match="ck_pedido_sugerido_cerrado_en_firmado"):
        revisar_la_lista(_columnas(cerrado_por=SISTEMA))


def test_una_fila_cerrada_antes_de_la_migracion_se_queda_en_null_para_siempre():
    """El caso que la 0013 tiene que dejar pasar: una lista cerrada por el
    código viejo de atlas, sin `cerrado_por` porque esa columna no existía.
    NO es un dato que falte -es la verdad de esa fila-, así que el CHECK no
    lo rechaza."""
    revisar_la_lista(
        _columnas(estado=CERRADO, cerrado_en=dt.datetime(2026, 9, 14, tzinfo=dt.UTC))
    )


def test_una_lista_cerrada_por_sistema_pasa_los_check():
    revisar_la_lista(
        _columnas(
            estado=CERRADO,
            cerrado_en=dt.datetime(2026, 9, 14, tzinfo=dt.UTC),
            cerrado_por=SISTEMA,
        )
    )


# ==========================================================================
# EL SQL COMO TEXTO — la migración 0013 y los archivos que la acompañan
# ==========================================================================


def _texto(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def _sentencias_sql(ruta: Path) -> str:
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def test_la_migracion_0013_agrega_una_columna_y_no_crea_tabla():
    sentencias = _sentencias_sql(MIGRACION)

    assert "CREATE TABLE" not in sentencias
    assert "GRANT" not in sentencias
    assert "ADD COLUMN IF NOT EXISTS cerrado_por text;" in sentencias
    assert "current_user = 'continental'" in sentencias
    assert "SET client_encoding TO 'UTF8'" in sentencias
    assert "BEGIN;" in sentencias and "COMMIT;" in sentencias


def test_la_0013_no_rompe_el_codigo_viejo_de_atlas():
    sentencias = _sentencias_sql(MIGRACION)

    assert "NOT NULL" not in sentencias.replace("IS NOT NULL", "")
    assert "DEFAULT" not in sentencias
    assert "ck_pedido_sugerido_estado" not in sentencias
    assert "ck_pedido_sugerido_cierre" not in sentencias
    assert "pedidos.renglon" not in sentencias
    assert "pedidos.pedido " not in sentencias and "pedidos.pedido\n" not in sentencias


def test_los_check_nuevos_estan_en_los_dos_archivos():
    for ruta in (CREAR_TABLAS, MIGRACION):
        sentencias = _sentencias_sql(ruta)
        assert "CONSTRAINT ck_pedido_sugerido_cerrado_por" in sentencias, ruta.name
        assert "CHECK (cerrado_por <> '')" in sentencias, ruta.name
        assert "CONSTRAINT ck_pedido_sugerido_cerrado_en_firmado" in sentencias, ruta.name
        assert (
            "CHECK (cerrado_por IS NULL OR cerrado_en IS NOT NULL)" in sentencias
        ), ruta.name


def test_crear_tablas_trae_la_columna_y_nombra_la_0013():
    sentencias = _sentencias_sql(CREAR_TABLAS)
    assert re.search(r"\n\s+cerrado_por\s+text,", sentencias)
    assert "0013-cerrado_por-la-firma-del-cierre.sql" in _texto(CREAR_TABLAS)


def test_verificar_rol_mira_la_firma_del_cierre():
    texto = _texto(VERIFICAR_ROL)
    assert "(39," in texto
    assert "ck_pedido_sugerido_cerrado_por" in texto
    assert "ck_pedido_sugerido_cerrado_en_firmado" in texto


@pytest.mark.parametrize(
    "nombre",
    ["_LEER_LISTA", "_LEER_LISTA_POR_ID", "_INSERTAR_LISTA", "_CERRAR",
     "_REABRIR", "_CERRAR_LAS_DE_DIAS_ANTERIORES"],
)
def test_las_lecturas_y_escrituras_de_la_lista_traen_cerrado_por(nombre):
    """Sin esto, con el código nuevo y la base sin la migración 0013, la
    lista del día no se puede leer ni armar: "column cerrado_por does not
    exist" (el mismo riesgo que ya medía `test_las_lecturas_de_la_lista_traen_la_firma_de_la_reapertura`
    en `test_cierre.py` para la 0012)."""
    import continental.almacenamiento as almacenamiento_modulo

    sql = str(getattr(almacenamiento_modulo, nombre))
    assert "cerrado_por" in sql, nombre
