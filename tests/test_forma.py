"""La forma de la base: ¿este código puede correr contra esta base? (ADR 0017)

Es la alternativa C de `docs/propuestas/verificar-la-forma-de-la-base.md`, y
aquí se prueba **la mitad pura**, igual que `tests/test_verificar.py`:

- la lista de columnas **esperadas** sale de `sql/crear_tablas.sql`, no de una
  copia escrita a mano;
- la columna que falta se traduce a **la migración exacta** que la agrega,
  leyendo los `ADD COLUMN` y los `CREATE TABLE` de `sql/migraciones/`;
- `revisar_forma` recibe diccionarios y devuelve un `Informe`.

La recolección —`select * from pedidos.<tabla> limit 0`, como el rol— no se
prueba: exigiría un Postgres, y ninguna prueba de este repo toca uno.

Más abajo, dos refuerzos de la misma propuesta:

- **E, sólo el lote**: `python -m continental.lote` revisa la forma al arrancar
  y, si no cuadra, no corre, sale distinto de cero y late `down`.
- **G**: las columnas que **nombra el código** en las sentencias de
  `almacenamiento.py` están en `crear_tablas.sql`, y lo que agregan las
  migraciones también. Es lo que impide que C compare contra un DDL incompleto.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

from continental import forma as f
from continental import verificar as v
from continental.latido import ABAJO, ResultadoDelLatido

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "src" / "continental" / "forma.py"
CREAR_TABLAS = RAIZ / "sql" / "crear_tablas.sql"
MIGRACIONES = RAIZ / "sql" / "migraciones"

TABLAS = {
    "pedido_sugerido",
    "pedido",
    "renglon",
    "precio_de_proveedor",
    "corrida_del_lote",
}


def _ddl() -> str:
    return CREAR_TABLAS.read_bytes().decode("utf-8")


def _migraciones() -> dict[str, str]:
    return {
        m.name: m.read_bytes().decode("utf-8")
        for m in sorted(MIGRACIONES.glob("*.sql"))
    }


def _esperadas() -> dict[str, frozenset[str]]:
    return f.columnas_de_crear_tablas(_ddl())


def _de_que_migracion() -> dict[tuple[str, str], str]:
    return f.migracion_de_cada_columna(_migraciones())


def _todo_en_orden() -> list[f.LecturaDeForma]:
    return [f.LecturaDeForma(t, cols) for t, cols in _esperadas().items()]


def _sin(tabla: str, *columnas: str) -> list[f.LecturaDeForma]:
    """La forma completa, salvo esas columnas de esa tabla."""
    return [
        f.LecturaDeForma(t, cols - set(columnas) if t == tabla else cols)
        for t, cols in _esperadas().items()
    ]


def _revisar(lecturas) -> v.Informe:
    return f.revisar_forma(_esperadas(), lecturas, _de_que_migracion())


# ==========================================================================
# Lo que se espera sale de sql/crear_tablas.sql
# ==========================================================================


def test_las_esperadas_son_las_cinco_tablas_del_ddl():
    """Las mismas cinco que `test_estan_las_cinco_tablas_y_ninguna_mas`."""
    assert set(_esperadas()) == TABLAS


def test_las_esperadas_traen_columnas_de_cada_migracion_y_ninguna_restriccion():
    esperadas = _esperadas()

    assert {"renglon_id", "negocio", "piezas_que_faltaron", "capturado_por"} <= esperadas["renglon"]
    assert {"enviado_por", "cancelado_por", "proveedor"} <= esperadas["pedido"]
    assert {"reabierto_por", "reabierto_en"} <= esperadas["pedido_sugerido"]
    assert "precio_como_llego" in esperadas["precio_de_proveedor"]
    assert "termino_en" in esperadas["corrida_del_lote"]
    for tabla, columnas in esperadas.items():
        coladas = columnas & {"constraint", "primary", "unique", "check", "foreign"}
        assert not coladas, (
            f"{tabla}: se colaron {sorted(coladas)} como columnas. Una "
            f"restricción no es una columna, y la base nunca la tendría."
        )


def test_el_conteo_de_columnas_es_el_del_ddl():
    """Contadas a mano sobre `sql/crear_tablas.sql` el 2026-09-21. Si cambia el
    DDL, este número cambia con él — y alguien lo tiene que mirar."""
    esperadas = _esperadas()

    assert len(esperadas["renglon"]) == 35
    assert len(esperadas["pedido"]) == 12
    assert len(esperadas["pedido_sugerido"]) == 10
    assert len(esperadas["precio_de_proveedor"]) == 14
    assert len(esperadas["corrida_del_lote"]) == 16


def test_un_guion_doble_dentro_de_una_cadena_no_se_come_el_resto():
    """`crear_tablas.sql` tiene un `COMMENT` cuyo texto lleva ` -- `. Quitar
    comentarios con una expresión regular ingenua cortaría esa cadena, dejaría
    una comilla abierta, y lo que siga se leería al revés."""
    sql = (
        "COMMENT ON TABLE pedidos.x IS 'uno -- dos';\n"
        "CREATE TABLE IF NOT EXISTS pedidos.x (\n"
        "    a text,  -- comentario con 'comilla\n"
        "    b text NOT NULL DEFAULT 'y -- z',\n"
        "    CONSTRAINT ck_x CHECK (a <> '')\n"
        ");\n"
    )

    assert f.columnas_de_crear_tablas(sql) == {"x": frozenset({"a", "b"})}


def test_un_ddl_sin_tablas_no_pasa_de_largo():
    """Cero tablas no es "todo en orden": es que el archivo cambió de forma y
    el chequeo se quedaría comparando contra nada, en verde."""
    with pytest.raises(ValueError):
        f.columnas_de_crear_tablas("-- nada por aquí\nSELECT 1;\n")


# ==========================================================================
# Cada columna, con la migración que la trae
# ==========================================================================


def test_cada_columna_apunta_a_la_migracion_que_la_agrega():
    de_que = _de_que_migracion()

    assert de_que[("renglon", "piezas_que_faltaron")] == "0011-recibido-parcial-y-a-mano.sql"
    assert de_que[("pedido", "enviado_por")] == "0006-enviar-el-pedido.sql"
    assert de_que[("pedido", "cancelado_por")] == "0009-cancelar-y-devolver-lo-atrasado.sql"
    assert de_que[("renglon", "cancelado_por")] == "0009-cancelar-y-devolver-lo-atrasado.sql"
    assert de_que[("pedido_sugerido", "reabierto_por")] == "0012-reabrir-la-lista-cerrada.sql"
    assert de_que[("renglon", "descartado_por")] == "0001-renglon-quien-descarto-y-cuando.sql"


def test_las_tablas_que_crea_una_migracion_tambien_apuntan_a_ella():
    """La 0003 y la 0004 no agregan columnas: crean la tabla entera."""
    de_que = _de_que_migracion()

    assert de_que[("precio_de_proveedor", "precio_como_llego")].startswith("0003-")
    assert de_que[("corrida_del_lote", "termino_en")].startswith("0004-")


def test_la_columna_la_trae_la_primera_migracion_que_la_nombra():
    migraciones = {
        "0002-despues.sql": "ALTER TABLE pedidos.t ADD COLUMN IF NOT EXISTS c text;",
        "0001-antes.sql": "ALTER TABLE pedidos.t\n    ADD COLUMN IF NOT EXISTS c text;",
    }

    assert f.migracion_de_cada_columna(migraciones) == {("t", "c"): "0001-antes.sql"}


def test_add_constraint_no_es_una_columna():
    migraciones = {
        "0001-x.sql": (
            "ALTER TABLE pedidos.t DROP CONSTRAINT IF EXISTS ck_t;\n"
            "ALTER TABLE pedidos.t ADD CONSTRAINT ck_t CHECK (c <> '');\n"
            "-- ALTER TABLE pedidos.t ADD COLUMN comentada text;\n"
            "ALTER TABLE pedidos.t ADD COLUMN c text, ADD COLUMN d date;\n"
        )
    }

    assert f.migracion_de_cada_columna(migraciones) == {
        ("t", "c"): "0001-x.sql",
        ("t", "d"): "0001-x.sql",
    }


def test_toda_columna_que_agrega_una_migracion_esta_en_crear_tablas():
    """La regla de los "dos archivos" del ADR 0003, comprobada: una columna
    nueva va en su migración **y** en `crear_tablas.sql`. Si falta en el DDL,
    el chequeo de forma nunca la exigiría y una base sin migrar pasaría."""
    esperadas = _esperadas()
    faltan = sorted(
        f"{t}.{c} ({m})"
        for (t, c), m in _de_que_migracion().items()
        if c not in esperadas.get(t, frozenset())
    )

    assert not faltan, f"Migraciones con columnas que crear_tablas.sql no declara: {faltan}"


# ==========================================================================
# revisar_forma — el veredicto
# ==========================================================================


def test_la_forma_completa_esta_en_orden():
    informe = _revisar(_todo_en_orden())

    assert informe.fallas == ()
    assert informe.pendientes == ()
    assert informe.codigo_de_salida == 0


def test_sin_enviado_por_falla_y_nombra_la_0006_con_el_comando_listo():
    informe = _revisar(_sin("pedido", "enviado_por", "enviado_en"))

    (falla,) = informe.fallas
    assert informe.codigo_de_salida == 1
    assert "enviado_por" in falla.detalle
    assert "pedidos.pedido" in falla.detalle
    assert (
        "docker exec -i farmacia_warehouse psql -U farmacia -d farmacia "
        "-v ON_ERROR_STOP=1 < sql/migraciones/0006-enviar-el-pedido.sql"
    ) in falla.reparacion


def test_dos_migraciones_que_faltan_salen_las_dos_en_orden_y_sin_repetir():
    lecturas = [
        f.LecturaDeForma(
            t,
            cols
            - {"piezas_que_faltaron", "piezas_recibidas", "cancelado_por", "cancelado_en"},
        )
        for t, cols in _esperadas().items()
    ]
    (falla,) = _revisar(lecturas).fallas

    ordenes = [l for l in falla.reparacion.splitlines() if "sql/migraciones/" in l]
    assert [re.search(r"migraciones/(\d{4})", l).group(1) for l in ordenes] == [
        "0009",
        "0011",
    ], "Cada migración una vez —la 0009 toca pedido y renglón— y en su orden."


def test_una_tabla_que_no_existe_nombra_la_migracion_que_la_crea_y_crear_rol():
    """La 0003 y la 0004 crean tablas, y una tabla nueva nace sin GRANT."""
    lecturas = [
        l if l.tabla != "corrida_del_lote"
        else f.LecturaDeForma("corrida_del_lote", None, "ProgrammingError", f.NO_EXISTE)
        for l in _todo_en_orden()
    ]
    (falla,) = _revisar(lecturas).fallas

    assert "0004-la-corrida-del-lote-en-una-fila.sql" in falla.reparacion
    assert "sql/crear_rol.sql" in falla.reparacion
    assert falla.reparacion.index("0004-") < falla.reparacion.index("crear_rol.sql"), (
        "El GRANT va DESPUÉS de crear la tabla: no se otorga sobre lo que no existe."
    )


def test_un_permiso_negado_no_se_confunde_con_una_migracion_que_falta():
    lecturas = [
        l if l.tabla != "renglon"
        else f.LecturaDeForma("renglon", None, "ProgrammingError", f.SIN_PERMISO)
        for l in _todo_en_orden()
    ]
    (falla,) = _revisar(lecturas).fallas

    assert "permiso" in falla.detalle
    assert "sql/crear_rol.sql" in falla.reparacion
    assert "sql/migraciones/" not in falla.reparacion


def test_una_columna_que_ninguna_migracion_agrega_falla_sin_inventar_una():
    """`renglon.descripcion` viene de la primera versión del DDL: si falta, no
    hay migración que la traiga, y decir una sería mandar a correr algo que no
    la arregla."""
    (falla,) = _revisar(_sin("renglon", "descripcion")).fallas

    assert "descripcion" in falla.detalle
    assert "ninguna migración" in falla.detalle
    assert "sql/migraciones/" not in falla.reparacion
    assert "\\d pedidos.renglon" in falla.reparacion


def test_una_lectura_que_fallo_por_otra_cosa_se_dice_con_el_tipo_y_nada_mas():
    lecturas = [
        l if l.tabla != "pedido"
        else f.LecturaDeForma("pedido", None, "OperationalError", "08006")
        for l in _todo_en_orden()
    ]
    (falla,) = _revisar(lecturas).fallas

    assert "OperationalError" in falla.detalle


def test_columnas_de_mas_son_un_pendiente_que_no_tumba_nada():
    """La base va ADELANTE del código: se corrió la migración de mañana y se
    desplegó el código de hoy. Es el orden correcto —migrar, luego desplegar—
    y a media semana es lo normal. Se dice y no se detiene nada."""
    lecturas = [
        f.LecturaDeForma(l.tabla, l.columnas | {"columna_de_manana"})
        if l.tabla == "renglon"
        else l
        for l in _todo_en_orden()
    ]
    informe = _revisar(lecturas)

    assert informe.fallas == ()
    (pendiente,) = informe.pendientes
    assert "columna_de_manana" in pendiente.detalle
    assert informe.codigo_de_salida == 0


def test_faltar_y_sobrar_a_la_vez_se_dicen_las_dos():
    lecturas = [
        f.LecturaDeForma(l.tabla, (l.columnas - {"enviado_por"}) | {"otra"})
        if l.tabla == "pedido"
        else l
        for l in _todo_en_orden()
    ]
    informe = _revisar(lecturas)

    assert len(informe.fallas) == 1 and len(informe.pendientes) == 1


def test_el_informe_de_forma_se_imprime_con_su_propio_titulo():
    texto = _revisar(_sin("pedido", "enviado_por")).como_texto(f.TITULO)

    assert texto.startswith(f.TITULO)
    assert "0006-enviar-el-pedido.sql" in texto


# ==========================================================================
# La línea entre lo puro y lo que lee Postgres (la misma casilla 1 del 17)
# ==========================================================================


PURAS = (
    "sin_comentarios",
    "columnas_de_crear_tablas",
    "migracion_de_cada_columna",
    "revisar_forma",
    "mensaje_para_el_latido",
)

PROHIBIDO_EN_LAS_PURAS = {
    "motor", "connect", "execute", "text", "cargar", "create_engine",
    "now", "today", "open", "read_text",
}


@pytest.mark.parametrize("nombre", PURAS)
def test_la_funcion_pura_no_nombra_un_motor_ni_el_reloj(nombre):
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    (definicion,) = [
        n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name == nombre
    ]
    nombrado = {n.id for n in ast.walk(definicion) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(definicion) if isinstance(n, ast.Attribute)
    }

    assert not nombrado & PROHIBIDO_EN_LAS_PURAS


def test_importar_el_modulo_no_abre_nada(monkeypatch):
    from continental import almacen

    import continental

    monkeypatch.delenv("WAREHOUSE_URL", raising=False)
    almacen.motor.cache_clear()
    # `delitem`/`setattr` de monkeypatch y no un `pop`: el módulo se vuelve a
    # poner al terminar, para que las pruebas que siguen parcheen el mismo
    # objeto que `verificar.main` importa.
    monkeypatch.delitem(sys.modules, "continental.forma")
    monkeypatch.setattr(continental, "forma", f)

    importlib.import_module("continental.forma")

    assert almacen.motor.cache_info().currsize == 0


def test_la_recoleccion_lee_como_el_rol_y_no_escribe_nada():
    """ADR 0003: el rol no hace DDL, y esto no escribe ni una fila. Lee con
    `limit 0` —las claves del resultado sin traer filas— y no pregunta al
    catálogo, igual que la casilla 5 del ticket 17."""
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    sentencias = [
        ast.unparse(n.args[0]).strip("'\" f").lower()
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", None)) == "text"
    ]

    assert sentencias, "forma.py no ejecuta ninguna sentencia: ¿de dónde lee la forma?"
    for sentencia in sentencias:
        assert sentencia.startswith("select * from pedidos."), sentencia
        assert sentencia.endswith("limit 0"), sentencia


def test_un_error_de_la_recoleccion_nunca_se_imprime_con_su_texto():
    """Regla 5: `str(exc)` de SQLAlchemy lleva la cadena de conexión con la
    contraseña. En la recolección se guarda el TIPO y el SQLSTATE, nada más."""
    fuente = FUENTE.read_text(encoding="utf-8")

    assert "str(exc)" not in fuente
    assert "{exc}" not in fuente
    assert "type(exc).__name__" in fuente


# ==========================================================================
# verificar: `--forma`, y el invariante 3 ya no calla la columna que falta
# ==========================================================================


def test_verificar_acepta_forma_y_corre_solo_eso(monkeypatch, capsys):
    llamado = []
    monkeypatch.setattr(
        f, "correr", lambda: llamado.append(1) or _revisar(_sin("pedido", "enviado_por"))
    )
    monkeypatch.setattr(v, "correr", lambda: pytest.fail("corrió los invariantes"))

    codigo = v.main(["--forma"])

    assert llamado and codigo == 1
    assert "0006-enviar-el-pedido.sql" in capsys.readouterr().out


def test_verificar_sin_forma_no_cambia_de_contrato(monkeypatch, capsys):
    monkeypatch.setattr(v, "correr", lambda: v.revisar_sugeridos_abiertos([]))
    monkeypatch.setattr(f, "correr", lambda: pytest.fail("corrió sólo la forma"))

    assert v.main([]) == 0


# ==========================================================================
# E — el lote no corre sobre una base que no cuadra
# ==========================================================================


class _Latidos:
    def __init__(self, resultado=None, levanta=None):
        self.llamadas: list[dict] = []
        self._resultado = resultado or ResultadoDelLatido(se_mando=True, estado=ABAJO)
        self._levanta = levanta

    def __call__(self, **kw):
        self.llamadas.append(kw)
        if self._levanta:
            raise self._levanta
        return self._resultado


def test_con_la_forma_en_orden_el_lote_sigue_y_no_late():
    """El latido de una noche buena lo manda la corrida, al final. Si éste
    latiera `up` al arrancar, una corrida que muere después ya habría dicho
    "todo bien"."""
    latir = _Latidos()

    assert f.antes_del_lote(revisar=lambda: _revisar(_todo_en_orden()), latir=latir) == 0
    assert latir.llamadas == []


def test_con_columnas_de_mas_el_lote_corre_igual():
    lecturas = [
        f.LecturaDeForma(l.tabla, l.columnas | {"otra"}) for l in _todo_en_orden()
    ]
    latir = _Latidos()

    assert f.antes_del_lote(revisar=lambda: _revisar(lecturas), latir=latir) == 0
    assert latir.llamadas == []


def test_sin_la_migracion_el_lote_no_corre_late_down_y_lo_dice(caplog):
    latir = _Latidos()

    with caplog.at_level("INFO", logger="continental"):
        codigo = f.antes_del_lote(
            revisar=lambda: _revisar(_sin("renglon", "piezas_que_faltaron")),
            latir=latir,
        )

    assert codigo != 0
    (latido,) = latir.llamadas
    assert latido["estado"] == ABAJO
    assert "0011" in latido["mensaje"], "El monitor tiene que decir qué migración falta."
    journal = caplog.text
    assert "NO corrió" in journal
    assert "< sql/migraciones/0011-recibido-parcial-y-a-mano.sql" in journal


def test_si_la_revision_misma_revienta_el_lote_tampoco_corre_y_no_filtra_el_texto(caplog):
    latir = _Latidos()

    def revisar():
        raise RuntimeError("postgresql://continental:secreta@host/farmacia")

    with caplog.at_level("INFO", logger="continental"):
        codigo = f.antes_del_lote(revisar=revisar, latir=latir)

    assert codigo != 0
    assert latir.llamadas[0]["estado"] == ABAJO
    assert "secreta" not in caplog.text
    assert "secreta" not in latir.llamadas[0]["mensaje"]
    assert "RuntimeError" in caplog.text


def test_un_latido_que_levanta_no_cambia_el_veredicto(caplog):
    """El latido nunca levanta; y si un doble lo hace, el lote sigue sin correr."""
    latir = _Latidos(levanta=RuntimeError("x"))

    codigo = f.antes_del_lote(
        revisar=lambda: _revisar(_sin("pedido", "enviado_por")), latir=latir
    )

    assert codigo != 0


def test_el_mensaje_del_latido_nombra_las_migraciones_y_no_lleva_comandos():
    informe = _revisar(
        [
            f.LecturaDeForma(t, c - {"enviado_por", "piezas_que_faltaron"})
            for t, c in _esperadas().items()
        ]
    )
    mensaje = f.mensaje_para_el_latido(informe)

    assert "0006" in mensaje and "0011" in mensaje
    assert "docker" not in mensaje, "Una línea de Kuma no es sitio para un comando."


def test_el_main_del_lote_revisa_la_forma_antes_de_construir_nada():
    """`lote.main` no se prueba (construye bordes de verdad), así que el orden
    se comprueba sobre el texto: la revisión va antes de leer la
    configuración y antes de correr el lote."""
    fuente = (RAIZ / "src" / "continental" / "lote.py").read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("def main("):]

    assert "antes_del_lote(" in cuerpo
    assert cuerpo.index("antes_del_lote(") < cuerpo.index("cargar()")
    assert cuerpo.index("antes_del_lote(") < cuerpo.index("correr_el_lote(")


def test_el_servicio_web_no_se_niega_a_arrancar_por_la_forma():
    """La alternativa E aplicada al web se descartó (ADR 0017): convertiría la
    falla de una pantalla en la caída de la puerta entera, y llegaría después
    del reinicio."""
    for ruta in [RAIZ / "iniciar.py", *sorted((RAIZ / "src" / "continental" / "web").rglob("*.py"))]:
        texto = ruta.read_text(encoding="utf-8")
        assert "antes_del_lote" not in texto and "continental.forma" not in texto, ruta.name


# ==========================================================================
# G — las columnas que el código nombra están en el DDL
# ==========================================================================
#
# Deliberadamente tosco (la propuesta lo dice así): no es un parser de SQL.
# Lee las sentencias `text(...)` de `almacenamiento.py` ya armadas —incluidas
# las que se componen con f-strings— y saca, por tabla de `pedidos`:
#
#   - las columnas de `insert into pedidos.T (...)`;
#   - las de la izquierda de cada `set c = ...` de `update pedidos.T`;
#   - las calificadas `a.c`, cuando `a` es alias de una tabla de `pedidos`;
#   - en sentencias de UNA sola tabla y sin alias, todo identificador suelto
#     que no sea palabra reservada, función, parámetro ni alias de salida.


_RESERVADAS = frozenset(
    """
    select from where and or not in is null as order by desc asc limit insert
    into values update set returning on conflict constraint do nothing exists
    join left inner outer true false distinct group having case when then else
    end between any all with union count coalesce greatest least now interval
    date bigint integer int text numeric boolean array cardinality current_date
    nulls first last for skip locked lateral cross using like ilike cast
    excluded delete sum max min unnest filter over partition
    """.split()
)


def _sentencias_del_codigo() -> dict[str, str]:
    from sqlalchemy.sql.elements import TextClause

    from continental import almacenamiento

    return {
        nombre: valor.text
        for nombre, valor in vars(almacenamiento).items()
        if isinstance(valor, TextClause)
    }


def _partir_arriba(texto: str) -> list[str]:
    """Parte por comas de primer nivel (fuera de paréntesis)."""
    partes, nivel, actual = [], 0, []
    for c in texto:
        if c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
        if c == "," and nivel == 0:
            partes.append("".join(actual))
            actual = []
        else:
            actual.append(c)
    partes.append("".join(actual))
    return partes


def columnas_que_nombra(sql: str) -> set[tuple[str, str]]:
    """(tabla, columna) de las tablas de `pedidos` que una sentencia nombra."""
    s = re.sub(r"'[^']*'", "''", sql.lower())
    s = re.sub(r"::\s*\w+(\[\])?", "", s)
    s = re.sub(r":\w+", ":p", s)

    tablas = set(re.findall(r"pedidos\.(\w+)", s))
    alias: dict[str, str] = {}
    for tabla, nombre in re.findall(r"pedidos\.(\w+)(?:\s+as)?\s+(\w+)", s):
        if nombre not in _RESERVADAS:
            alias[nombre] = tabla

    nombradas: set[tuple[str, str]] = set()

    for tabla, lista in re.findall(r"insert\s+into\s+pedidos\.(\w+)\s*\(([^)]*)\)", s):
        nombradas |= {(tabla, c.strip()) for c in lista.split(",")}

    for tabla, cuerpo in re.findall(
        r"update\s+pedidos\.(\w+)(?:\s+as\s+\w+)?\s+set\s+(.*?)\s+(?:from|where|returning)\b",
        s,
        flags=re.S,
    ):
        for asignacion in _partir_arriba(cuerpo):
            izquierda = asignacion.split("=")[0].strip().split(".")[-1]
            nombradas.add((tabla, izquierda))

    for quien, columna in re.findall(r"\b(\w+)\.(\w+)\b", s):
        if quien in alias:
            nombradas.add((alias[quien], columna))

    otras_tablas = re.search(r"\b(?:marts|raw|public)\.\w+", s)
    if len(tablas) == 1 and not alias and not otras_tablas:
        (tabla,) = tablas
        limpio = re.sub(r"\bas\s+\w+", " ", s)
        limpio = re.sub(r"\bconstraint\s+\w+", " ", limpio)
        limpio = re.sub(r"pedidos\.\w+", " ", limpio)
        for token in re.findall(r"(?<![:.\w])([a-z_][a-z0-9_]*)\b(?!\s*\()", limpio):
            if token not in _RESERVADAS and token != "p":
                nombradas.add((tabla, token))

    return nombradas


def test_el_extractor_caza_una_columna_inventada():
    """El extractor es tosco a propósito; esto prueba que al menos ve lo que
    tiene que ver en cada una de sus cuatro formas."""
    assert ("renglon", "no_existe") in columnas_que_nombra(
        "select renglon_id, no_existe from pedidos.renglon where negocio = :negocio"
    )
    assert ("pedido", "inventada") in columnas_que_nombra(
        "update pedidos.pedido as p set inventada = :x where p.pedido_id = :id"
    )
    assert ("renglon", "otra") in columnas_que_nombra(
        "select r.otra from pedidos.renglon as r join pedidos.pedido as p on p.pedido_id = r.pedido_id"
    )
    assert ("corrida_del_lote", "rara") in columnas_que_nombra(
        "insert into pedidos.corrida_del_lote (negocio, rara) values (:negocio, :rara)"
    )


def test_el_extractor_encuentra_las_sentencias_y_sus_columnas():
    """Si el extractor dejara de ver, la prueba de abajo pasaría en verde sin
    revisar nada. Las columnas de las migraciones 0006, 0011 y 0012 tienen que
    salir, porque el código las nombra."""
    sentencias = _sentencias_del_codigo()
    nombradas = set().union(*(columnas_que_nombra(s) for s in sentencias.values()))

    assert len(sentencias) >= 40
    assert {
        ("pedido", "enviado_por"),
        ("renglon", "piezas_que_faltaron"),
        ("pedido_sugerido", "reabierto_por"),
        ("corrida_del_lote", "orden_cumplido"),
        ("precio_de_proveedor", "precio_como_llego"),
    } <= nombradas
    assert {t for t, _ in nombradas} == TABLAS


def test_toda_columna_que_nombra_el_codigo_esta_en_crear_tablas():
    """El error que dejaría a C comparando contra una forma incompleta: el
    código nombra una columna y `crear_tablas.sql` no la declara. En atlas sería
    un `column ... does not exist` que el chequeo de forma no vio venir; aquí
    es una prueba roja en la torre."""
    esperadas = _esperadas()
    fuera = sorted(
        f"{nombre}: pedidos.{t}.{c}"
        for nombre, sql in _sentencias_del_codigo().items()
        for t, c in columnas_que_nombra(sql)
        if c not in esperadas.get(t, frozenset())
    )

    assert not fuera, (
        "El código nombra columnas que sql/crear_tablas.sql no declara: "
        f"{fuera}. Agrégalas al DDL y a una migración nueva (ADR 0003)."
    )
