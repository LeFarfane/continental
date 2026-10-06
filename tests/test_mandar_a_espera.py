"""Mandar a espera un renglón desde Captura, con su proveedor (lista de espera, ticket 04).

**Lo que arregla.** «Pasar al día siguiente» existía solo en Revisar, renglón por
renglón, y al día siguiente se volvía a repartir: se perdía a quién se le iba a
pedir. Desde aquí el renglón en espera **recuerda a su proveedor**, **sale de su
pedido** —de la captura, del «0 de 9» y del total— y se puede regresar a ese
pedido con un clic. Ver la enmienda del 2026-10-05 al ADR 0025 (puntos 2 y 6).

Los cuatro niveles del repo, sin abrir uno nuevo. **Ninguna prueba toca Postgres,
la red ni duerme, y ningún dato es real.**

1. Lo puro: de qué proveedor hereda la espera, el motivo del tachado, la frase
   de sacar de la espera y los CHECK escritos en Python.
2. Lo guardado: el doble, y el SQL como texto (la migración 0020, el DDL, las
   dos sentencias).
3. Las rutas, de punta a punta.
4. Lo estático del JavaScript: el botón de la captura.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental import almacenamiento as modulo_almacenamiento
from continental import forma
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    RENGLON_ABIERTO,
    RENGLON_POSPUESTO,
    RenglonGuardado,
    Ventana,
    columnas_del_pedido,
    columnas_del_renglon,
    revisar_el_renglon,
)
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon
from continental.transiciones import (
    MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA,
    frase_de_sacar_de_la_espera,
    motivo_para_no_editar,
    proveedor_de_la_espera,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
MIGRACION = SQL / "migraciones" / "0020-la-espera-con-proveedor-y-edad.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargada@farmacia.mx"
HOY = dt.date(2024, 3, 5)
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


# ---------------------------------------------------------------- utilidades


def _renglon(producto_id: int = 1, cantidad: int = 5) -> Renglon:
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


def _guardado(
    estado: str = RENGLON_ABIERTO,
    *,
    pedido_id: int | None = 7,
    capturado_por: str | None = None,
    proveedor_de_la_espera: str | None = None,
) -> RenglonGuardado:
    pospuesto = estado == RENGLON_POSPUESTO
    return RenglonGuardado(
        renglon_id=1,
        estado=estado,
        propuesto=_renglon(),
        pedido_id=pedido_id,
        capturado_por=capturado_por,
        capturado_en=ARMADO if capturado_por else None,
        pospuesto_por=CORREO if pospuesto else None,
        pospuesto_en=ARMADO if pospuesto else None,
        proveedor_de_la_espera=proveedor_de_la_espera,
        espera_desde=HOY if pospuesto else None,
        listas_en_espera=1 if pospuesto else None,
    )


def _lista(*renglones: RenglonGuardado, estado: str = "abierto"):
    from continental.almacenamiento import PedidoSugeridoGuardado

    return PedidoSugeridoGuardado(
        pedido_sugerido_id=4,
        negocio=NEGOCIO,
        fecha_del_pedido=HOY,
        estado=estado,
        ventana=Ventana(desde=HOY, hasta=HOY),
        armado_en=ARMADO,
        cerrado_en=None,
        renglones=renglones,
    )


def _columnas(**cambios) -> dict:
    columnas = columnas_del_renglon(_renglon(), NEGOCIO, 1)
    columnas.update(cambios)
    return columnas


def _sentencia(nombre: str) -> str:
    return getattr(modulo_almacenamiento, nombre).text


# ==========================================================================
# 1. LO PURO
# ==========================================================================


def test_la_espera_hereda_el_proveedor_del_pedido_donde_estaba():
    assert proveedor_de_la_espera("nadro", None) == "nadro"


def test_el_pedido_manda_sobre_la_eleccion_porque_es_donde_iba_a_salir():
    assert proveedor_de_la_espera("nadro", "levic") == "nadro"


def test_sin_pedido_hereda_el_proveedor_elegido_a_mano():
    assert proveedor_de_la_espera(None, "levic") == "levic"


def test_sin_pedido_ni_eleccion_no_hereda_nada():
    assert proveedor_de_la_espera(None, None) is None


def test_si_no_hay_pedido_ni_eleccion_conserva_el_que_ya_traia_de_una_espera_anterior():
    assert proveedor_de_la_espera(None, None, "levic") == "levic"
    assert proveedor_de_la_espera("nadro", None, "levic") == "nadro"


def test_una_cadena_vacia_cuenta_como_ninguno():
    assert proveedor_de_la_espera("", "") is None
    assert proveedor_de_la_espera("", "levic") == "levic"


def test_un_renglon_tachado_no_se_manda_a_espera_y_dice_por_que():
    renglon = _guardado(capturado_por=CORREO)

    motivo = motivo_para_no_editar(renglon, _lista(renglon), "posponer")

    assert motivo == MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA
    assert "tachado" in motivo and "carrito" in motivo


def test_destachado_si_se_manda_a_espera():
    renglon = _guardado(capturado_por=None)
    assert motivo_para_no_editar(renglon, _lista(renglon), "posponer") is None


def test_lo_tachado_solo_frena_mandar_a_espera_y_no_las_otras_acciones():
    """Descartar y ajustar la cantidad se quedan como estaban."""
    renglon = _guardado(capturado_por=CORREO)
    lista = _lista(renglon)
    for accion in ("descartar", "ajustar_la_cantidad", "elegir_proveedor"):
        assert motivo_para_no_editar(renglon, lista, accion) is None, accion


def test_lo_que_ya_esta_en_transito_dice_su_motivo_y_no_el_del_tachado():
    renglon = RenglonGuardado(
        renglon_id=1,
        estado="en tránsito",
        propuesto=_renglon(),
        capturado_por=CORREO,
        capturado_en=ARMADO,
    )
    motivo = motivo_para_no_editar(renglon, _lista(renglon), "posponer")
    assert motivo != MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA
    assert "ya se le pidió" in motivo


def test_la_frase_de_sacar_de_la_espera_dice_que_volvio_a_su_pedido():
    antes = _guardado(RENGLON_POSPUESTO, pedido_id=None, proveedor_de_la_espera="nadro")
    despues = _guardado(pedido_id=7)

    assert frase_de_sacar_de_la_espera(antes, despues, "NADRO") == (
        "Volvió al pedido de NADRO."
    )


def test_la_frase_dice_por_que_volvio_sin_repartir_si_su_pedido_ya_no_es_borrador():
    antes = _guardado(RENGLON_POSPUESTO, pedido_id=None, proveedor_de_la_espera="nadro")
    despues = _guardado(pedido_id=None)

    frase = frase_de_sacar_de_la_espera(antes, despues, "NADRO")

    assert "sin repartir" in frase
    assert "pedido de NADRO" in frase and "ya no está en borrador" in frase


def test_la_frase_dice_que_no_tenia_proveedor_cuando_no_lo_tenia():
    antes = _guardado(RENGLON_POSPUESTO, pedido_id=None, proveedor_de_la_espera=None)
    despues = _guardado(pedido_id=None)

    frase = frase_de_sacar_de_la_espera(antes, despues)

    assert "sin repartir" in frase and "no tenía proveedor" in frase


def test_la_frase_calla_si_no_sabe_de_donde_venia():
    despues = _guardado(pedido_id=7)
    assert frase_de_sacar_de_la_espera(None, despues) is None
    assert frase_de_sacar_de_la_espera(_guardado(), despues) is None


def test_un_renglon_nace_sin_espera_y_pasa_los_check():
    columnas = columnas_del_renglon(_renglon(), NEGOCIO, 1)
    for columna in ("proveedor_de_la_espera", "espera_desde", "listas_en_espera"):
        assert columnas.get(columna) is None, columna
    revisar_el_renglon(columnas)


def test_los_check_de_la_espera_en_python():
    firmado = dict(
        estado=RENGLON_POSPUESTO, pospuesto_por=CORREO, pospuesto_en=ARMADO
    )
    # Un pospuesto con su espera, con o sin proveedor, pasa.
    revisar_el_renglon(
        _columnas(**firmado, espera_desde=HOY, listas_en_espera=1, proveedor_de_la_espera="nadro")
    )
    revisar_el_renglon(_columnas(**firmado, espera_desde=HOY, listas_en_espera=3))
    # Un abierto que viene de una espera anterior también los puede traer.
    revisar_el_renglon(
        _columnas(espera_desde=HOY, listas_en_espera=2, proveedor_de_la_espera="levic")
    )

    with pytest.raises(ValueError, match="ck_renglon_espera_proveedor"):
        revisar_el_renglon(_columnas(proveedor_de_la_espera=""))
    with pytest.raises(ValueError, match="ck_renglon_espera_listas"):
        revisar_el_renglon(_columnas(espera_desde=HOY, listas_en_espera=0))
    with pytest.raises(ValueError, match="ck_renglon_espera\\b"):
        revisar_el_renglon(_columnas(espera_desde=HOY))
    with pytest.raises(ValueError, match="ck_renglon_espera\\b"):
        revisar_el_renglon(_columnas(listas_en_espera=1))
    with pytest.raises(ValueError, match="ck_renglon_espera_pospuesto"):
        revisar_el_renglon(_columnas(**firmado))


def test_la_linea_de_captura_dice_si_se_puede_mandar_a_espera():
    from continental.particion import Captura, Linea, captura_como_json

    suelta = Linea(renglon_id=1, descripcion="A", cantidad=1, clave="1")
    tachada = Linea(
        renglon_id=2, descripcion="B", cantidad=1, clave="2",
        capturado_por=CORREO, capturado_en=ARMADO,
    )

    lineas = captura_como_json(
        Captura(proveedor="nadro", lineas=(suelta, tachada)), True
    )["lineas"]

    assert lineas[0]["se_puede_mandar_a_espera"] is True
    assert lineas[0]["motivo_para_no_mandar_a_espera"] is None
    assert lineas[1]["se_puede_mandar_a_espera"] is False
    assert lineas[1]["motivo_para_no_mandar_a_espera"] == MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA


# ==========================================================================
# 2. LO GUARDADO — el doble
# ==========================================================================


def _pedido_en_el_doble(almacenamiento, lista, proveedor="nadro", estado=BORRADOR):
    fila = {
        **columnas_del_pedido(
            NEGOCIO, lista.pedido_sugerido_id, proveedor, None, Decimal("10.00")
        ),
        "pedido_id": len(almacenamiento.pedidos) + 1,
        "armado_en": ARMADO,
    }
    fila["estado"] = estado
    almacenamiento.pedidos.append(fila)
    return fila


def _lista_con_un_renglon(almacenamiento):
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO, HOY, Ventana(HOY, HOY), [_renglon(1, 5), _renglon(2, 4)]
    )
    return lista, lista.renglones[0].renglon_id


def _fila(almacenamiento, renglon_id) -> dict:
    return almacenamiento._renglon_por_id(renglon_id)[0]


def test_mandar_a_espera_guarda_el_proveedor_del_pedido_y_saca_el_renglon_de_el(
    almacenamiento,
):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    pedido = _pedido_en_el_doble(almacenamiento, lista, "nadro")
    _fila(almacenamiento, renglon_id)["pedido_id"] = pedido["pedido_id"]

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.estado == RENGLON_POSPUESTO
    assert r.proveedor_de_la_espera == "nadro"
    assert r.pedido_id is None, "sale de su pedido en la misma operación"
    assert r.espera_desde == HOY, "la fecha de la lista"
    assert r.listas_en_espera == 1


def test_sin_pedido_guarda_el_proveedor_elegido_a_mano(almacenamiento):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    almacenamiento.elegir_proveedor(NEGOCIO, renglon_id, "levic", CORREO)

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.proveedor_de_la_espera == "levic"


def test_sin_pedido_ni_eleccion_el_proveedor_queda_vacio(almacenamiento):
    """Mandar a espera desde Revisar, antes de repartir: como hoy."""
    _, renglon_id = _lista_con_un_renglon(almacenamiento)

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.proveedor_de_la_espera is None
    assert r.estado == RENGLON_POSPUESTO and r.listas_en_espera == 1


def test_el_pedido_gana_a_la_eleccion_al_mandar_a_espera(almacenamiento):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    almacenamiento.elegir_proveedor(NEGOCIO, renglon_id, "levic", CORREO)
    pedido = _pedido_en_el_doble(almacenamiento, lista, "nadro")
    _fila(almacenamiento, renglon_id)["pedido_id"] = pedido["pedido_id"]

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.proveedor_de_la_espera == "nadro"


def test_lo_que_el_renglon_ya_traia_de_una_espera_anterior_se_conserva(almacenamiento):
    """El diseño que deja listo el ticket 05: no se pisa la primera vez."""
    _, renglon_id = _lista_con_un_renglon(almacenamiento)
    fila = _fila(almacenamiento, renglon_id)
    fila.update(espera_desde=dt.date(2024, 3, 1), listas_en_espera=2)

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.espera_desde == dt.date(2024, 3, 1)
    assert r.listas_en_espera == 2


def test_un_renglon_tachado_no_se_manda_a_espera_y_no_se_mueve(almacenamiento):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    pedido = _pedido_en_el_doble(almacenamiento, lista, "nadro")
    fila = _fila(almacenamiento, renglon_id)
    fila["pedido_id"] = pedido["pedido_id"]
    almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO)

    assert almacenamiento.posponer(NEGOCIO, renglon_id, CORREO) is None

    assert fila["estado"] == RENGLON_ABIERTO
    assert fila["pedido_id"] == pedido["pedido_id"]
    assert fila.get("proveedor_de_la_espera") is None


def test_sacar_de_la_espera_regresa_al_pedido_de_su_proveedor_si_sigue_en_borrador(
    almacenamiento,
):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    pedido = _pedido_en_el_doble(almacenamiento, lista, "nadro")
    _fila(almacenamiento, renglon_id)["pedido_id"] = pedido["pedido_id"]
    almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    guardada = almacenamiento.devolver_pospuesto(NEGOCIO, renglon_id)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.estado == RENGLON_ABIERTO
    assert r.pedido_id == pedido["pedido_id"]
    assert r.pospuesto_por is None and r.pospuesto_en is None
    # Lo de la espera se borra: este renglón no venía de una espera anterior.
    assert (r.proveedor_de_la_espera, r.espera_desde, r.listas_en_espera) == (None, None, None)


def test_sacar_de_la_espera_con_el_pedido_ya_enviado_lo_deja_sin_repartir(almacenamiento):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    pedido = _pedido_en_el_doble(almacenamiento, lista, "nadro")
    _fila(almacenamiento, renglon_id)["pedido_id"] = pedido["pedido_id"]
    almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)
    pedido["estado"] = "enviado"

    guardada = almacenamiento.devolver_pospuesto(NEGOCIO, renglon_id)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.estado == RENGLON_ABIERTO
    assert r.pedido_id is None


def test_sacar_de_la_espera_sin_proveedor_lo_deja_sin_repartir(almacenamiento):
    lista, renglon_id = _lista_con_un_renglon(almacenamiento)
    _pedido_en_el_doble(almacenamiento, lista, "nadro")
    almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    guardada = almacenamiento.devolver_pospuesto(NEGOCIO, renglon_id)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert r.pedido_id is None


def test_sacar_de_la_espera_no_borra_la_espera_de_un_renglon_que_venia_de_antes(
    almacenamiento,
):
    _, renglon_id = _lista_con_un_renglon(almacenamiento)
    fila = _fila(almacenamiento, renglon_id)
    fila.update(
        espera_desde=dt.date(2024, 3, 1),
        listas_en_espera=2,
        proveedor_de_la_espera="levic",
        piezas_pospuestas=3,
    )
    almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    guardada = almacenamiento.devolver_pospuesto(NEGOCIO, renglon_id)

    r = next(x for x in guardada.renglones if x.renglon_id == renglon_id)
    assert (r.proveedor_de_la_espera, r.espera_desde, r.listas_en_espera) == (
        "levic", dt.date(2024, 3, 1), 2
    )


def test_el_doble_rechaza_un_pospuesto_sin_espera_igual_que_la_base(almacenamiento):
    _, renglon_id = _lista_con_un_renglon(almacenamiento)
    with pytest.raises(ValueError, match="ck_renglon_espera_pospuesto"):
        almacenamiento.poner_estado_del_renglon(
            renglon_id, RENGLON_POSPUESTO, pospuesto_por=CORREO, pospuesto_en=ARMADO
        )


# ---------------------------------------------------- el SQL como texto


def test_posponer_guarda_el_proveedor_y_saca_el_renglon_en_la_misma_sentencia():
    sentencia = _sentencia("_POSPONER").lower()

    assert sentencia.lstrip().startswith("update")
    assert "pedido_id = null" in sentencia
    assert "proveedor_de_la_espera = coalesce(" in sentencia
    # El del pedido primero, el elegido a mano después.
    assert (
        sentencia.index("pe.proveedor")
        < sentencia.index("r.proveedor_elegido")
        < sentencia.index("r.proveedor_de_la_espera)")
    )
    assert "coalesce(r.espera_desde, p.fecha_del_pedido)" in sentencia
    assert "coalesce(r.listas_en_espera, 1)" in sentencia
    # Y las dos de siempre: el renglón abierto, la lista abierta.
    assert "r.estado = 'abierto'" in sentencia
    assert "p.estado = 'abierto'" in sentencia


def test_posponer_respeta_lo_tachado_en_el_where():
    sentencia = _sentencia("_POSPONER").lower()
    donde = sentencia[sentencia.index("where"):]
    assert "r.capturado_por is null" in donde


def test_devolver_regresa_al_pedido_de_su_proveedor_solo_si_es_borrador():
    sentencia = _sentencia("_DEVOLVER_DE_POSPUESTO").lower()

    assert "pedido_id = (select pe.pedido_id" in sentencia
    assert "pe.proveedor = r.proveedor_de_la_espera" in sentencia
    assert "pe.estado = 'borrador'" in sentencia
    assert "pe.pedido_sugerido_id = r.pedido_sugerido_id" in sentencia
    # Lo de la espera solo se borra si el renglón no venía de una espera anterior.
    assert "when r.piezas_pospuestas > 0" in sentencia
    assert "pospuesto_por = null" in sentencia and "pospuesto_en = null" in sentencia


def test_las_lecturas_nombran_las_tres_columnas_de_la_espera():
    for nombre in ("_LEER_RENGLONES", "_LEER_RENGLON_POR_ID", "_LO_POSPUESTO"):
        sentencia = _sentencia(nombre)
        for columna in ("proveedor_de_la_espera", "espera_desde", "listas_en_espera"):
            assert columna in sentencia, (nombre, columna)


def test_el_ddl_trae_las_columnas_y_los_check_de_la_espera():
    sql = CREAR_TABLAS.read_bytes().decode("utf-8")
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.renglon (")
    cuerpo = sql[inicio : sql.index("\n);", inicio)]

    assert re.search(r"^\s*proveedor_de_la_espera\s+text,", cuerpo, re.MULTILINE)
    assert re.search(r"^\s*espera_desde\s+date,", cuerpo, re.MULTILINE)
    assert re.search(r"^\s*listas_en_espera\s+integer,", cuerpo, re.MULTILINE)
    for restriccion in (
        "ck_renglon_espera_proveedor",
        "ck_renglon_espera_listas",
        "ck_renglon_espera\n",
        "ck_renglon_espera_pospuesto",
    ):
        assert f"CONSTRAINT {restriccion}" in cuerpo, restriccion
    assert "CHECK (proveedor_de_la_espera <> '')" in cuerpo
    assert "CHECK (listas_en_espera >= 1)" in cuerpo
    assert "CHECK ((espera_desde IS NULL) = (listas_en_espera IS NULL))" in cuerpo
    assert "CHECK (estado <> 'pospuesto' OR espera_desde IS NOT NULL)" in cuerpo


def test_hay_una_migracion_0020_idempotente_y_sin_tablas_nuevas():
    assert MIGRACION.exists()
    crudo = MIGRACION.read_bytes()
    assert b"\r" not in crudo, "los .sql de atlas van con LF"
    texto = crudo.decode("utf-8")
    sentencias = "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("--")
    )

    assert "CREATE TABLE" not in sentencias
    for columna in ("proveedor_de_la_espera", "espera_desde", "listas_en_espera"):
        assert f"ADD COLUMN IF NOT EXISTS {columna}" in sentencias, columna
    for restriccion in (
        "ck_renglon_espera_proveedor",
        "ck_renglon_espera_listas",
        "ck_renglon_espera",
        "ck_renglon_espera_pospuesto",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {restriccion};" in sentencias, restriccion
        assert f"ADD CONSTRAINT {restriccion}\n" in sentencias, restriccion
    assert "current_user = 'continental'" in sentencias
    for prohibida in ("DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN"):
        assert prohibida not in sentencias.upper()


def test_la_migracion_rellena_lo_que_ya_estaba_pospuesto_antes_de_los_check():
    """Si no, `ck_renglon_espera_pospuesto` rechazaría los de la 0019."""
    texto = MIGRACION.read_bytes().decode("utf-8")
    sentencias = "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("--")
    )
    relleno = sentencias.index("UPDATE pedidos.renglon")
    assert relleno < sentencias.index("ADD CONSTRAINT ck_renglon_espera_pospuesto")
    assert "WHERE r.estado = 'pospuesto'" in sentencias
    assert "r.espera_desde IS NULL" in sentencias, "idempotente: solo lo que no tiene fecha"


def test_la_forma_de_la_base_atribuye_las_tres_columnas_a_la_0020():
    esperadas = forma.columnas_de_crear_tablas(CREAR_TABLAS.read_bytes().decode("utf-8"))
    migraciones = {
        archivo.name: archivo.read_bytes().decode("utf-8")
        for archivo in (SQL / "migraciones").glob("*.sql")
    }
    de_que = forma.migracion_de_cada_columna(migraciones)
    for columna in ("proveedor_de_la_espera", "espera_desde", "listas_en_espera"):
        assert columna in esperadas["renglon"], columna
        assert de_que[("renglon", columna)] == MIGRACION.name, columna


# ==========================================================================
# 3. LAS RUTAS, de punta a punta
# ==========================================================================


def _venta(n: int) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=HOY, producto_id=n, cantidad=3, importe=30.0, costo=18.0, utilidad=12.0
    )


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


def _lectura(precio: str) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor="nadro",
        precio_como_llego=precio,
        precio=Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def _firma(correo: str = CORREO) -> dict:
    return {"Cf-Access-Authenticated-User-Email": correo}


def _partida(cliente, almacen, almacenamiento, cuantos: int = 3):
    """Una lista de `cuantos` renglones a NADRO, partida en un solo pedido."""
    almacen.catalogo_en_memoria = [_producto(n) for n in range(1, cuantos + 1)]
    almacen.ventas_en_memoria = [_venta(n) for n in range(1, cuantos + 1)]
    lista = cliente.get(RUTA).json()
    for i in range(cuantos):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], [_lectura(f"1{i}.50")]
        )
    lista = cliente.get(RUTA).json()
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    return partida, partida["pedidos"][0]


def _posponer(cliente, renglon_id: int, correo: str = CORREO):
    return cliente.post(f"/api/renglon/{renglon_id}/posponer", headers=_firma(correo))


def _devolver(cliente, renglon_id: int):
    return cliente.post(f"/api/renglon/{renglon_id}/devolver-pospuesto")


def _tachar(cliente, renglon_id: int, capturado: bool = True):
    return cliente.post(
        f"/api/renglon/{renglon_id}/capturado",
        json={"capturado": capturado},
        headers=_firma(),
    )


def test_mandar_a_espera_desde_la_captura_guarda_proveedor_y_saca_el_renglon_del_pedido(
    cliente, almacen, almacenamiento
):
    _, pedido = _partida(cliente, almacen, almacenamiento)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]

    respuesta = _posponer(cliente, renglon_id)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    r = cuerpo["renglon"]
    assert r["estado"] == RENGLON_POSPUESTO
    assert r["proveedor_de_la_espera"] == "nadro"
    assert r["espera_desde"] == HOY.isoformat()
    assert r["listas_en_espera"] == 1
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    guardado_r = next(x for x in guardado.renglones if x.renglon_id == renglon_id)
    assert guardado_r.pedido_id is None, "ya no pertenece al pedido"
    assert guardado_r.proveedor_de_la_espera == "nadro"


def test_la_captura_y_el_cero_de_nueve_dejan_de_contar_al_renglon_en_espera(
    cliente, almacen, almacenamiento
):
    """El pendiente del ticket 03: `lo_que_hay_que_capturar` ya no lo cuenta."""
    _, pedido = _partida(cliente, almacen, almacenamiento, cuantos=3)
    assert pedido["captura"]["cuantos"] == 3
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]

    cuerpo = _posponer(cliente, renglon_id).json()

    # La respuesta trae los pedidos ya recalculados, para que la pantalla no
    # recargue: sin el renglón dentro, en la captura, en el avance y en el total.
    nuevo = next(p for p in cuerpo["pedidos"] if p["pedido_id"] == pedido["pedido_id"])
    assert nuevo["captura"]["cuantos"] == 2
    assert renglon_id not in [l["renglon_id"] for l in nuevo["captura"]["lineas"]]
    assert nuevo["captura"]["faltan"] == 2
    assert nuevo["total"]["cifra"] == str(
        Decimal(pedido["total"]["cifra"]) - Decimal("10.50") * 3
    )
    # Y la carga siguiente dice lo mismo.
    de_nuevo = cliente.get(RUTA).json()
    recargado = next(p for p in de_nuevo["pedidos"] if p["pedido_id"] == pedido["pedido_id"])
    assert recargado["captura"]["cuantos"] == 2


def test_el_total_del_pedido_baja_al_mandar_a_espera(cliente, almacen, almacenamiento):
    _, pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]  # el de 10.50
    antes = Decimal(pedido["total"]["cifra"])

    cuerpo = _posponer(cliente, renglon_id).json()

    despues = Decimal(cuerpo["totales_de_los_pedidos"][str(pedido["pedido_id"])]["cifra"])
    assert despues == antes - Decimal("10.50") * 3


def test_un_renglon_tachado_se_rechaza_con_su_motivo_y_el_boton_ya_lo_decia(
    cliente, almacen, almacenamiento
):
    partida, pedido = _partida(cliente, almacen, almacenamiento)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]
    assert _tachar(cliente, renglon_id).status_code == 200

    lista = cliente.get(RUTA).json()
    r = next(x for x in lista["renglones"] if x["renglon_id"] == renglon_id)
    assert r["se_puede_posponer"] is False
    assert r["motivo_para_no_posponer"] == MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA
    linea = next(
        l
        for p in lista["pedidos"]
        for l in p["captura"]["lineas"]
        if l["renglon_id"] == renglon_id
    )
    assert linea["se_puede_mandar_a_espera"] is False
    assert linea["motivo_para_no_mandar_a_espera"] == MOTIVO_TACHADO_NO_SE_MANDA_A_ESPERA

    respuesta = _posponer(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False
    assert "tachado" in respuesta.json()["detalle"]
    # Nada se movió: sigue abierto, tachado y dentro de su pedido.
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    r = next(x for x in guardado.renglones if x.renglon_id == renglon_id)
    assert r.estado == RENGLON_ABIERTO and r.pedido_id == pedido["pedido_id"]


def test_destachado_se_puede_mandar_a_espera(cliente, almacen, almacenamiento):
    _, pedido = _partida(cliente, almacen, almacenamiento)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]
    _tachar(cliente, renglon_id)
    _tachar(cliente, renglon_id, capturado=False)

    assert _posponer(cliente, renglon_id).status_code == 200


def test_sacar_de_la_espera_regresa_al_pedido_y_lo_dice(cliente, almacen, almacenamiento):
    _, pedido = _partida(cliente, almacen, almacenamiento, cuantos=3)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]
    _posponer(cliente, renglon_id)

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["renglon"]["estado"] == RENGLON_ABIERTO
    assert cuerpo["frase_de_sacar_de_la_espera"] == "Volvió al pedido de NADRO."
    nuevo = next(p for p in cuerpo["pedidos"] if p["pedido_id"] == pedido["pedido_id"])
    assert nuevo["captura"]["cuantos"] == 3
    assert nuevo["total"]["cifra"] == pedido["total"]["cifra"]
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    r = next(x for x in guardado.renglones if x.renglon_id == renglon_id)
    assert r.pedido_id == pedido["pedido_id"]


def test_sacar_de_la_espera_con_el_pedido_enviado_vuelve_sin_repartir_y_dice_por_que(
    cliente, almacen, almacenamiento
):
    _, pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    uno, otro = (l["renglon_id"] for l in pedido["captura"]["lineas"])
    _posponer(cliente, uno)
    enviado = cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=_firma())
    assert enviado.status_code == 200, enviado.text

    respuesta = _devolver(cliente, uno)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["renglon"]["estado"] == RENGLON_ABIERTO
    assert "sin repartir" in cuerpo["frase_de_sacar_de_la_espera"]
    assert "ya no está en borrador" in cuerpo["frase_de_sacar_de_la_espera"]
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    r = next(x for x in guardado.renglones if x.renglon_id == uno)
    assert r.pedido_id is None


def test_mandar_a_espera_desde_revisar_antes_de_repartir_funciona_como_hoy(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(1)]
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]

    cuerpo = _posponer(cliente, renglon_id).json()

    assert cuerpo["ok"] is True
    assert cuerpo["renglon"]["estado"] == RENGLON_POSPUESTO
    assert cuerpo["renglon"]["proveedor_de_la_espera"] is None
    assert cuerpo["renglon"]["listas_en_espera"] == 1
    assert cuerpo["pedidos"] is None, "sin pedidos no hay nada que sustituir"
    assert cuerpo["frase_de_sacar_de_la_espera"] is None


def test_la_frase_de_sacar_de_la_espera_solo_viaja_en_esa_ruta(
    cliente, almacen, almacenamiento
):
    _, pedido = _partida(cliente, almacen, almacenamiento)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]

    cuerpo = _posponer(cliente, renglon_id).json()
    assert cuerpo["frase_de_sacar_de_la_espera"] is None
    descartado = cliente.post(f"/api/renglon/{pedido['captura']['lineas'][1]['renglon_id']}/descartar")
    assert descartado.json()["frase_de_sacar_de_la_espera"] is None


def test_el_error_de_la_base_no_viaja_al_navegador(cliente, almacen, almacenamiento):
    _, pedido = _partida(cliente, almacen, almacenamiento)
    renglon_id = pedido["captura"]["lineas"][0]["renglon_id"]
    almacenamiento.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = _posponer(cliente, renglon_id)

    assert "SECRETO" not in respuesta.text
    assert respuesta.json()["ok"] is False


# ==========================================================================
# 4. LO ESTÁTICO DEL JAVASCRIPT
# ==========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_cada_renglon_de_la_captura_trae_su_boton_de_mandar_a_espera():
    cuerpo = cuerpo_de_funcion(_script(), "const pintarCaptura")

    assert "botonDeAccion('Mandar a espera'" in cuerpo
    assert "alPosponer(" in cuerpo
    # El botón se apaga con el motivo del servidor, no con uno escrito aquí.
    assert "linea.se_puede_mandar_a_espera" in cuerpo
    assert "linea.motivo_para_no_mandar_a_espera" in cuerpo
    assert "Mandar a espera ' + linea.descripcion" in cuerpo


def test_la_captura_recibe_posponer_desde_el_repintado_y_lo_pasa_hacia_abajo():
    script = _script()
    assert "pintarPasoCaptura(datos.pedidos, tacharRenglon, enviarPedido, posponer)" in script
    paso = cuerpo_de_funcion(script, "const pintarPasoCaptura")
    assert "pintarCaptura(guardado, alTachar, alPosponer)" in paso


def test_mandar_a_espera_usa_la_ruta_que_ya_existe_y_no_agrega_un_fetch():
    script = _script()
    assert "'/posponer'" in cuerpo_de_funcion(script, "function posponer")
    assert "fetch(" not in cuerpo_de_funcion(script, "const pintarCaptura")


def test_la_respuesta_sustituye_los_pedidos_y_la_frase_de_sacar_de_la_espera_se_dice():
    script = _script()
    aplicar = cuerpo_de_funcion(script, "const aplicar = (respuesta)")
    assert "if (respuesta.pedidos) datos.pedidos = respuesta.pedidos;" in aplicar

    devolver = cuerpo_de_funcion(script, "function devolverPospuesto")
    assert "respuesta.frase_de_sacar_de_la_espera" in devolver
    assert "'/devolver-pospuesto'" in devolver


def test_el_boton_de_revisar_dice_el_motivo_del_servidor_cuando_esta_apagado():
    script = _script()
    assert "r.motivo_para_no_posponer" in script
