"""El mínimo del proveedor y la pestaña Ajustes (ticket 08 de lista-de-espera).

Cuatro niveles, los del repo, y ninguno toca Postgres ni la red:

1. **Lo puro**: leer un monto, las frases, la forma del JSON.
2. **Lo guardado**: el doble, los CHECK en Python y el SQL como texto.
3. **La ruta de punta a punta**: guardar, sobreescribir, rechazar.
4. **La estática del JavaScript** de la pestaña.

Lo que se cuida sobre todo: **sin fila es «sin mínimo capturado» y cero es «no
tiene mínimo»**, y no se confunden ni en la tabla, ni en la respuesta, ni en
pantalla.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental import config
from continental.almacenamiento import (
    _GUARDAR_MINIMO,
    _LEER_MINIMOS,
    AlmacenamientoDelPedido,
)
from continental.dobles import AlmacenamientoFalso
from continental.fallas import AL_GUARDAR, AL_LEER, que_hacer
from continental.minimos import (
    CON_MINIMO,
    FRASE_SIN_CAPTURAR,
    FRASE_SIN_MINIMO,
    PROVEEDORES_CONOCIDOS,
    SIN_CAPTURAR,
    SIN_MINIMO,
    MinimoDelProveedor,
    estado_del_minimo,
    frase_de_quien_y_cuando,
    frase_del_minimo,
    leer_el_monto,
    minimos_como_json,
    revisar_el_minimo,
    revisar_lo_que_llega,
)
from continental.precios import NOMBRES_DE_PROVEEDOR

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
MIGRACION = SQL / "migraciones" / "0021-el-minimo-del-proveedor.sql"
NEGOCIO = "farmacia_01"
ANA = "ana@farmacia.example"
LUIS = "luis@farmacia.example"
D = Decimal


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"--[^\n]*", "", texto)


# =========================================================================
# 1. LO PURO
# =========================================================================


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        (2000, D("2000.00")),
        ("2000", D("2000.00")),
        ("1,500.50", D("1500.50")),
        ("$ 1,500.50", D("1500.50")),
        (1500.5, D("1500.50")),
        ("0", D("0.00")),
        (0, D("0.00")),
        ("  350  ", D("350.00")),
        ("10.005", D("10.01")),  # a centavos, hacia arriba: así se lee un precio
    ],
)
def test_un_monto_valido_se_lee_a_centavos(crudo, esperado):
    assert leer_el_monto(crudo) == (esperado, None)


@pytest.mark.parametrize(
    "crudo",
    [None, "", "   ", "dos mil", "12abc", "-1", -5, "-0.01", True, False, [], {}, "NaN", "Infinity",
     float("nan"), float("inf"), "99999999999.00"],
)
def test_un_monto_invalido_se_rechaza_con_su_motivo(crudo):
    monto, motivo = leer_el_monto(crudo)

    assert monto is None
    assert motivo and motivo.endswith(".")


def test_el_motivo_del_negativo_dice_que_cero_es_no_tener_minimo():
    assert "escribe 0" in leer_el_monto("-3")[1]


def test_un_proveedor_desconocido_se_rechaza_nombrando_los_que_si_conoce():
    monto, iva, motivo = revisar_lo_que_llega("farmasana", 100, True)

    assert (monto, iva) == (None, None)
    for nombre in NOMBRES_DE_PROVEEDOR.values():
        assert nombre in motivo


def test_la_casilla_de_iva_tiene_que_ser_si_o_no_y_no_se_toma_por_no():
    for crudo in (None, "true", 1, "no"):
        assert revisar_lo_que_llega("nadro", 100, crudo)[2] == "Falta decir si el mínimo incluye IVA o no."
    assert revisar_lo_que_llega("nadro", 100, False) == (D("100.00"), False, None)


def test_los_proveedores_conocidos_son_los_cuatro_de_doyle_y_en_su_orden():
    assert PROVEEDORES_CONOCIDOS == tuple(NOMBRES_DE_PROVEEDOR) == ("nadro", "levic", "vicma", "quepharma")


def _minimo(monto: str, iva: bool = False, cuando: dt.datetime | None = None) -> MinimoDelProveedor:
    return MinimoDelProveedor(
        "nadro", D(monto), iva, ANA, cuando or dt.datetime(2026, 10, 6, 20, 5, tzinfo=dt.UTC)
    )


def test_los_tres_estados_y_sus_frases():
    assert estado_del_minimo(None) == SIN_CAPTURAR
    assert estado_del_minimo(_minimo("0")) == SIN_MINIMO
    assert estado_del_minimo(_minimo("2000")) == CON_MINIMO

    assert frase_del_minimo(None) == "sin mínimo capturado" == FRASE_SIN_CAPTURAR
    assert frase_del_minimo(_minimo("0")) == "no tiene mínimo" == FRASE_SIN_MINIMO
    assert frase_del_minimo(_minimo("2000")) == "$2,000.00 sin IVA"
    assert frase_del_minimo(_minimo("1500.5", iva=True)) == "$1,500.50 con IVA"


def test_sin_capturar_y_cero_no_se_dicen_igual():
    assert frase_del_minimo(None) != frase_del_minimo(_minimo("0"))
    assert estado_del_minimo(None) != estado_del_minimo(_minimo("0"))


def test_quien_y_cuando_va_en_la_hora_de_la_farmacia_y_sin_fila_no_hay_frase():
    # 20:05 UTC es 14:05 en UTC-6.
    frase = frase_de_quien_y_cuando(_minimo("2000"))

    assert ANA in frase and "14:05" in frase
    assert frase_de_quien_y_cuando(None) is None


def test_el_json_trae_a_todos_los_conocidos_con_o_sin_fila():
    lista = minimos_como_json({"levic": MinimoDelProveedor("levic", D("0.00"), False, LUIS, dt.datetime(2026, 10, 6, tzinfo=dt.UTC))})

    assert [m["proveedor"] for m in lista] == list(PROVEEDORES_CONOCIDOS)
    por = {m["proveedor"]: m for m in lista}
    assert por["nadro"]["estado"] == SIN_CAPTURAR
    assert (por["nadro"]["monto"], por["nadro"]["incluye_iva"], por["nadro"]["fijado_por"]) == (None, None, None)
    # El cero está CAPTURADO: monto "0.00", no None.
    assert por["levic"]["estado"] == SIN_MINIMO and por["levic"]["monto"] == "0.00"
    assert por["levic"]["fijado_por"] == LUIS
    # El dinero viaja como cadena, no como número de coma flotante.
    assert all(isinstance(m["monto"], (str, type(None))) for m in lista)


# =========================================================================
# 2. LO GUARDADO — el doble, los CHECK en Python y el SQL como texto
# =========================================================================


def test_el_doble_sigue_cumpliendo_la_interfaz():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)
    for metodo in ("minimos_de_los_proveedores", "guardar_el_minimo"):
        assert hasattr(AlmacenamientoDelPedido, metodo), metodo


def test_sin_fila_el_proveedor_no_aparece_en_la_lectura(almacenamiento):
    assert almacenamiento.minimos_de_los_proveedores(NEGOCIO) == {}


def test_guardar_deja_la_fila_firmada_y_con_hora(almacenamiento):
    guardado = almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("2000.00"), False, ANA)

    assert (guardado.proveedor, guardado.monto, guardado.incluye_iva, guardado.fijado_por) == (
        "nadro", D("2000.00"), False, ANA)
    assert guardado.fijado_en is not None and guardado.fijado_en.tzinfo is not None
    assert almacenamiento.minimos_de_los_proveedores(NEGOCIO) == {"nadro": guardado}


def test_guardar_otra_vez_sobreescribe_y_no_deja_historial(almacenamiento):
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("2000"), False, ANA)
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("1500"), True, LUIS)

    leido = almacenamiento.minimos_de_los_proveedores(NEGOCIO)
    assert len(almacenamiento.minimos) == 1
    assert (leido["nadro"].monto, leido["nadro"].incluye_iva, leido["nadro"].fijado_por) == (D("1500"), True, LUIS)


def test_un_cero_guardado_es_una_fila_y_no_es_lo_mismo_que_no_tenerla(almacenamiento):
    almacenamiento.guardar_el_minimo(NEGOCIO, "levic", D("0"), False, ANA)

    leido = almacenamiento.minimos_de_los_proveedores(NEGOCIO)

    assert "levic" in leido and leido["levic"].monto == 0
    assert "nadro" not in leido


def test_los_minimos_son_de_un_negocio(almacenamiento):
    almacenamiento.guardar_el_minimo("otro_negocio", "nadro", D("500"), False, ANA)

    assert almacenamiento.minimos_de_los_proveedores(NEGOCIO) == {}


@pytest.mark.parametrize(
    "columnas",
    [
        {"negocio": "", "proveedor": "nadro", "monto": D("1"), "incluye_iva": False, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "", "monto": D("1"), "incluye_iva": False, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": D("-1"), "incluye_iva": False, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": D("NaN"), "incluye_iva": False, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": 5, "incluye_iva": False, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": D("1"), "incluye_iva": None, "fijado_por": ANA},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": D("1"), "incluye_iva": False, "fijado_por": "  "},
        {"negocio": NEGOCIO, "proveedor": "nadro", "monto": D("1"), "incluye_iva": False, "fijado_por": ""},
    ],
)
def test_los_check_en_python_rechazan_lo_que_la_tabla_rechazaria(columnas):
    with pytest.raises(ValueError):
        revisar_el_minimo(columnas)


def test_el_doble_rechaza_lo_mismo_y_no_escribe(almacenamiento):
    with pytest.raises(ValueError):
        almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("-1"), False, ANA)
    with pytest.raises(ValueError):
        almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("1"), False, "")

    assert almacenamiento.minimos == {}


def test_el_doble_falla_como_la_base_cuando_se_le_pide(almacenamiento):
    almacenamiento.falla = RuntimeError("base caída")

    with pytest.raises(RuntimeError):
        almacenamiento.minimos_de_los_proveedores(NEGOCIO)
    with pytest.raises(RuntimeError):
        almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("1"), False, ANA)


# --- el SQL como texto


def _sentencia(texto) -> str:
    return " ".join(str(texto).split())


def test_guardar_es_un_solo_upsert_que_pone_la_hora_la_base_y_devuelve_lo_que_quedo():
    sql = _sentencia(_GUARDAR_MINIMO)

    assert "insert into pedidos.minimo_del_proveedor (negocio, proveedor, monto, incluye_iva, fijado_por)" in sql
    assert "on conflict (negocio, proveedor) do update" in sql
    assert "fijado_en = now()" in sql
    assert "returning proveedor, monto, incluye_iva, fijado_por, fijado_en" in sql
    # La hora no viaja desde Python: `fijado_en` no está entre los valores.
    assert ":fijado_en" not in sql


def test_leer_filtra_por_negocio():
    sql = _sentencia(_LEER_MINIMOS)

    assert "from pedidos.minimo_del_proveedor where negocio = :negocio" in sql


def _cuerpo_de_la_tabla(texto: str) -> str:
    inicio = texto.index("CREATE TABLE IF NOT EXISTS pedidos.minimo_del_proveedor (")
    return texto[inicio : texto.index("\n);", inicio)]


def test_la_tabla_dice_lo_mismo_en_el_ddl_y_en_la_migracion():
    ddl = _cuerpo_de_la_tabla(_texto(SQL / "crear_tablas.sql"))
    migracion = _cuerpo_de_la_tabla(_texto(MIGRACION))

    assert ddl == migracion
    for pedazo in (
        "negocio      text          NOT NULL,",
        "monto        numeric(12,2) NOT NULL,",
        "incluye_iva  boolean       NOT NULL,",
        "fijado_por   text          NOT NULL,",
        "fijado_en    timestamptz   NOT NULL DEFAULT now(),",
        "PRIMARY KEY (negocio, proveedor)",
        "CHECK (monto >= 0)",
        "CHECK (btrim(fijado_por) <> '')",
    ):
        assert pedazo in migracion, pedazo
    # El dinero no es coma flotante, y no hay historial: ni identidad ni versión.
    assert not re.search(r"double precision|\bfloat|\breal\b|IDENTITY|serial", _sin_comentarios(migracion), re.I)


def test_la_migracion_trae_su_guardia_su_transaccion_su_comment_y_su_grant():
    texto = _texto(MIGRACION)
    sentencias = _sin_comentarios(texto)

    assert "current_user = 'continental'" in sentencias  # el rol no corre DDL (ADR 0003)
    assert re.search(r"^BEGIN;", sentencias, re.M) and re.search(r"^COMMIT;", sentencias, re.M)
    assert "CREATE TABLE IF NOT EXISTS" in sentencias  # idempotente
    assert "COMMENT ON TABLE pedidos.minimo_del_proveedor" in sentencias
    assert "COMMENT ON COLUMN pedidos.minimo_del_proveedor.fijado_por" in sentencias
    assert "GRANT SELECT, INSERT, UPDATE ON pedidos.minimo_del_proveedor TO continental;" in sentencias
    assert not re.search(r"\bDELETE\b|\bDROP\b|\bTRUNCATE\b", sentencias)


def test_crear_rol_da_el_mismo_permiso_que_la_migracion():
    concedidos = [
        " ".join(l.split())
        for l in _sin_comentarios(_texto(SQL / "crear_rol.sql")).splitlines()
        if "pedidos.minimo_del_proveedor" in l
    ]

    assert concedidos == ["GRANT SELECT, INSERT, UPDATE ON pedidos.minimo_del_proveedor TO continental;"]


def test_el_verificador_exceptua_a_la_tabla_de_la_llave_de_identidad():
    verificador = _texto(SQL / "verificar_rol.sql")

    assert verificador.count("c.relname <> 'minimo_del_proveedor'") == 2


# =========================================================================
# 3. LA RUTA DE PUNTA A PUNTA
# =========================================================================


def _poner(cliente, proveedor, cuerpo, correo=ANA):
    return cliente.put(
        f"/api/minimos/{proveedor}", json=cuerpo, headers={"Cf-Access-Authenticated-User-Email": correo}
    )


def test_al_inicio_los_cuatro_estan_sin_capturar_y_ninguno_es_un_cero(cliente):
    datos = cliente.get("/api/minimos").json()

    assert datos["ok"] is True
    assert [m["proveedor"] for m in datos["minimos"]] == list(PROVEEDORES_CONOCIDOS)
    for m in datos["minimos"]:
        assert m["estado"] == SIN_CAPTURAR and m["monto"] is None
        assert m["frase"] == "sin mínimo capturado"


def test_guardar_firma_con_el_correo_de_access_y_la_lista_lo_muestra(cliente, almacenamiento):
    respuesta = _poner(cliente, "nadro", {"monto": "2,000", "incluye_iva": False})

    assert respuesta.status_code == 200
    minimo = respuesta.json()["minimo"]
    assert respuesta.json()["ok"] is True
    assert (minimo["monto"], minimo["incluye_iva"], minimo["fijado_por"]) == ("2000.00", False, ANA)
    assert minimo["frase"] == "$2,000.00 sin IVA"
    assert ANA in minimo["frase_de_quien"]
    # Y quedó en el almacenamiento, con el negocio de la configuración.
    assert almacenamiento.minimos[(config.cargar().negocio, "nadro")].fijado_por == ANA

    lista = {m["proveedor"]: m for m in cliente.get("/api/minimos").json()["minimos"]}
    assert lista["nadro"]["estado"] == CON_MINIMO
    assert lista["levic"]["estado"] == SIN_CAPTURAR  # los demás, intactos


def test_sin_encabezado_de_access_la_firma_es_sin_identificar(cliente, almacenamiento):
    cliente.put("/api/minimos/vicma", json={"monto": 100, "incluye_iva": True})

    assert almacenamiento.minimos[(config.cargar().negocio, "vicma")].fijado_por == "sin-identificar"


def test_sobreescribir_deja_el_valor_nuevo_con_la_firma_nueva(cliente, almacenamiento):
    _poner(cliente, "nadro", {"monto": 2000, "incluye_iva": False}, ANA)
    respuesta = _poner(cliente, "nadro", {"monto": 1500.5, "incluye_iva": True}, LUIS)

    minimo = respuesta.json()["minimo"]
    assert (minimo["monto"], minimo["incluye_iva"], minimo["fijado_por"]) == ("1500.50", True, LUIS)
    assert minimo["frase"] == "$1,500.50 con IVA"
    assert len(almacenamiento.minimos) == 1


def test_cero_es_valido_y_dice_no_tiene_minimo_distinto_de_sin_capturar(cliente):
    respuesta = _poner(cliente, "levic", {"monto": "0", "incluye_iva": False})

    minimo = respuesta.json()["minimo"]
    assert respuesta.status_code == 200
    assert minimo["estado"] == SIN_MINIMO and minimo["frase"] == "no tiene mínimo"
    assert minimo["monto"] == "0.00"  # capturado: no es None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"monto": "-1", "incluye_iva": False},
        {"monto": -50, "incluye_iva": False},
        {"monto": "dos mil", "incluye_iva": False},
        {"monto": "", "incluye_iva": False},
        {"monto": None, "incluye_iva": False},
        {"monto": True, "incluye_iva": False},
        {"incluye_iva": False},
        {"monto": 100},
        {"monto": 100, "incluye_iva": "sí"},
        {},
    ],
)
def test_un_cuerpo_invalido_se_rechaza_con_frase_y_no_toca_nada(cliente, almacenamiento, cuerpo):
    respuesta = _poner(cliente, "nadro", cuerpo)

    assert respuesta.status_code == 400
    datos = respuesta.json()
    assert datos["ok"] is False and datos["detalle"].endswith(".") and datos["que_hacer"]
    assert almacenamiento.minimos == {}


def test_un_rechazo_no_pisa_lo_que_ya_estaba(cliente, almacenamiento):
    _poner(cliente, "nadro", {"monto": 2000, "incluye_iva": False})
    _poner(cliente, "nadro", {"monto": -1, "incluye_iva": False})

    assert almacenamiento.minimos[(config.cargar().negocio, "nadro")].monto == D("2000.00")


def test_un_proveedor_que_continental_no_conoce_se_rechaza_y_dice_cuales_si(cliente, almacenamiento):
    respuesta = _poner(cliente, "farmasana", {"monto": 100, "incluye_iva": False})

    assert respuesta.status_code == 400
    assert "NADRO" in respuesta.json()["detalle"] and "QuePharma" in respuesta.json()["detalle"]
    assert almacenamiento.minimos == {}


def test_si_la_base_no_contesta_al_leer_no_se_manda_ninguna_lista_y_el_error_no_viaja(cliente, almacenamiento):
    almacenamiento.falla = RuntimeError("SECRETO postgresql://continental:clave@host/db")

    respuesta = cliente.get("/api/minimos")

    datos = respuesta.json()
    assert datos["ok"] is False and "minimos" not in datos
    assert datos["que_hacer"] == que_hacer(AL_LEER, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text and "clave" not in respuesta.text


def test_si_la_base_no_contesta_al_guardar_el_error_no_viaja(cliente, almacenamiento):
    almacenamiento.falla = RuntimeError("SECRETO postgresql://continental:clave@host/db")

    respuesta = _poner(cliente, "nadro", {"monto": 100, "incluye_iva": False})

    datos = respuesta.json()
    assert datos["ok"] is False
    assert datos["que_hacer"] == que_hacer(AL_GUARDAR, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text and "clave" not in respuesta.text


# =========================================================================
# 4. LA ESTÁTICA DEL JAVASCRIPT
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_la_pestana_ajustes_existe_y_las_flechas_la_alcanzan():
    pantalla = pantalla_completa()
    script = _script()

    assert 'id="pestana-ajustes"' in pantalla and 'id="panel-ajustes"' in pantalla
    [panel] = re.findall(r'<section id="panel-ajustes"[^>]*>', pantalla)
    assert " hidden" in panel  # nace escondida, como las demás
    assert "'ajustes'" in script.split("const PESTANAS = [", 1)[1].split("]", 1)[0]
    # Se lee al abrir la pestaña, no al cargar la página.
    assert "if (elegida === 'ajustes') cargarAjustes();" in cuerpo_de_funcion(script, "const mostrarPestana")


def test_el_javascript_lee_y_guarda_por_las_dos_rutas_y_firma_nada_por_su_cuenta():
    script = _script()
    leer = cuerpo_de_funcion(script, "const cargarAjustes")
    fila = cuerpo_de_funcion(script, "const filaDeMinimo")

    assert "fetch('/api/minimos')" in leer
    assert "fetch('/api/minimos/' + m.proveedor" in fila and "method: 'PUT'" in fila
    assert "JSON.stringify({ monto: monto.value, incluye_iva: casilla.checked })" in fila
    # El navegador no manda quién es: la firma es el encabezado de Access, en el servidor.
    assert "fijado_por" not in fila.replace("m.fijado_por", "")


def test_la_fila_pinta_las_frases_que_dice_el_servidor_y_no_las_compone():
    fila = cuerpo_de_funcion(_script(), "const filaDeMinimo")

    assert "m.frase" in fila and "m.frase_de_quien" in fila
    # Nada del JavaScript escribe «no tiene mínimo» ni «sin mínimo capturado»: son de minimos.py.
    assert "no tiene mínimo'" not in fila.replace("0 = no tiene mínimo", "")
    assert "sin mínimo capturado" not in fila


def test_sin_fila_el_campo_nace_vacio_y_no_en_cero():
    """Un cero guardado sin querer diría «no tiene mínimo» de un proveedor que sí tiene."""
    fila = cuerpo_de_funcion(_script(), "const filaDeMinimo")

    assert "monto.value = m.monto === null ? '' : m.monto;" in fila
    assert "casilla.checked = m.incluye_iva === true;" in fila


def test_sin_capturar_va_en_gris_con_su_palabra_y_se_repinta_con_lo_guardado():
    fila = cuerpo_de_funcion(_script(), "const filaDeMinimo")
    css = pantalla_completa()

    assert "m.estado === 'sin_capturar' ? ' sin-capturar' : ''" in fila
    assert ".ajustes .vale-hoy.sin-capturar" in css
    # Tras guardar, la fila se pinta con la respuesta del servidor, no con lo tecleado.
    assert "filaDeMinimo(respuesta.minimo)" in fila and "li.replaceWith(nueva)" in fila


def test_si_la_lectura_falla_no_se_pinta_ninguna_fila():
    leer = cuerpo_de_funcion(_script(), "const cargarAjustes")

    assert "if (!datos.ok) {" in leer
    # El `return` de la falla va antes de pintar la lista.
    assert leer.index("return;") < leer.index("replaceChildren")


def test_el_boton_se_apaga_mientras_guarda_y_la_falla_se_dice_en_la_fila():
    fila = cuerpo_de_funcion(_script(), "const filaDeMinimo")

    assert "boton.disabled = true;" in fila and "boton.disabled = false;" in fila
    assert "notaDeFalla(aviso, respuesta);" in fila
