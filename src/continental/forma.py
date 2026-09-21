"""¿Este código puede correr contra esta base? **La forma, no los datos.**

    python -m continental.verificar --forma

Compara las columnas que **de verdad** tiene cada tabla de `pedidos` —leídas
como el rol, con `select * from pedidos.<tabla> limit 0`— contra las que
declara `sql/crear_tablas.sql`, y traduce cada columna que falta a **la
migración exacta** que la agrega, con el comando listo para copiar. Es la
alternativa C de `docs/propuestas/verificar-la-forma-de-la-base.md`, y el
porqué está en el ADR 0017.

## Por qué hace falta, si ya está `verificar`

Porque las migraciones 0006 a 0012 **agregan columnas que el código nombra**, y
nada miraba si se corrieron: `pytest` corre sin Postgres, `/api/salud` no toca
la base, y los invariantes de `verificar` corrían **después** del reinicio. Con
la base sin migrar, la lista del día rebotaba con `column ... does not exist` y
el lote de las 22:00 se cortaba igual.

## Por qué la columna basta como testigo

Cada migración corre en **una sola transacción** y agrega al menos una columna
o crea una tabla. Si la columna está, el resto de su migración —sus CHECK
ampliados, sus rellenos— también entró. Así que no hace falta una tabla de
migraciones ni una etiqueta: la forma de la tabla **es** la marca, y las doce
migraciones que ya existen no hay que rellenarlas.

## Qué NO ve

- **Tipos, nulabilidad ni CHECK.** Eso sigue siendo de `sql/verificar_rol.sql`,
  a mano y con credenciales de dueño. Lo que traen las migraciones viaja con su
  columna en la misma transacción.
- **Una columna que el código nombra y el DDL no declara.** Eso es un error de
  los archivos y se ve en el suite (`tests/test_forma.py`, la prueba G).
- **Nada fuera de `pedidos`.** Si `dbt` renombra una columna de `marts`, esto
  no lo ve (alternativa F de la propuesta, para después).

## Qué hace con lo que encuentra

- Una columna **de menos**: `FALLA`, con la migración que la trae. El
  despliegue se detiene **antes** del reinicio (paso 4 de `desplegar.sh`) y el
  lote de la noche no corre (`antes_del_lote`).
- Una columna **de más**: `PENDIENTE`, sin fallar. La base va adelante del
  código —se migró y todavía no se despliega, que es el orden correcto—, y el
  código de hoy no la nombra, así que no le estorba.

## Las dos mitades, como en `verificar`

- **Puras** (`sin_comentarios`, `columnas_de_crear_tablas`,
  `migracion_de_cada_columna`, `revisar_forma`, `mensaje_para_el_latido`):
  reciben texto y diccionarios, devuelven un `Informe`. Ésas se prueban.
- **Recolección** (`leer_la_forma`, `revisar_con`, `correr`): leen de Postgres
  y de disco. **No se prueban**; importar este módulo no abre nada.

**No escribe nada, ni una fila ni una columna** (ADR 0003): el rol no hace DDL,
y el día que alguien convierta "no cuadra" en "aplica lo que falta" habrá
reinventado el `preparar()` que ese ADR prohíbe. Aquí se señala y se dice el
comando; las migraciones las corre una persona con credenciales de dueño.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from continental.verificar import (
    _PSQL,
    FALLA,
    Informe,
    _falla,
    _ok,
    _pendiente,
    _plural,
)

log = logging.getLogger("continental")

RAIZ = Path(__file__).resolve().parents[2]
CREAR_TABLAS = RAIZ / "sql" / "crear_tablas.sql"
MIGRACIONES = RAIZ / "sql" / "migraciones"

ESQUEMA = "pedidos"

TITULO = "Continental · la forma de la base, leída como el rol"

#: SQLSTATE de Postgres que la recolección distingue. Cualquier otro es "no se
#: pudo leer", dicho con su tipo y sin inventarle causa.
NO_EXISTE = "42P01"  # undefined_table
SIN_PERMISO = "42501"  # insufficient_privilege

NOMBRE = "la base tiene las columnas que el código nombra"
NOMBRE_DE_MAS = "columnas de la base que el código no conoce"

_NO_SON_COLUMNAS = frozenset(
    {"constraint", "primary", "unique", "check", "foreign", "exclude", "like"}
)


# ==========================================================================
# MITAD PURA — texto y diccionarios adentro, un informe afuera
# ==========================================================================


def sin_comentarios(sql: str) -> str:
    """El SQL sin sus comentarios `--`, **respetando las cadenas**.

    `crear_tablas.sql` tiene un `COMMENT` cuyo texto lleva ` -- `: una
    expresión regular ingenua cortaría esa cadena, dejaría una comilla abierta
    y lo que siga se leería al revés. Esto camina el texto y sólo trata como
    comentario lo que está fuera de comillas simples. Un apóstrofo DENTRO de un
    comentario no abre nada, porque el comentario se salta entero antes.
    """
    salida: list[str] = []
    i, n = 0, len(sql)
    en_cadena = False
    while i < n:
        c = sql[i]
        if en_cadena:
            salida.append(c)
            if c == "'":
                en_cadena = False
            i += 1
        elif c == "'":
            en_cadena = True
            salida.append(c)
            i += 1
        elif sql.startswith("--", i):
            fin = sql.find("\n", i)
            i = n if fin == -1 else fin
        else:
            salida.append(c)
            i += 1
    return "".join(salida)


def _cuerpo_entre_parentesis(texto: str, abre: int) -> str:
    """Lo que hay entre el `(` de la posición `abre` y su `)` pareja."""
    nivel = 0
    en_cadena = False
    for i in range(abre, len(texto)):
        c = texto[i]
        if c == "'":
            en_cadena = not en_cadena
        if en_cadena:
            continue
        if c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
            if nivel == 0:
                return texto[abre + 1 : i]
    raise ValueError("Un CREATE TABLE sin su paréntesis de cierre.")


def _partir_arriba(cuerpo: str) -> list[str]:
    """Parte por las comas de primer nivel: las de un `numeric(12,2)` o un
    `CHECK (a, b)` no separan columnas."""
    partes: list[str] = []
    nivel = 0
    en_cadena = False
    actual: list[str] = []
    for c in cuerpo:
        if c == "'":
            en_cadena = not en_cadena
        elif not en_cadena and c == "(":
            nivel += 1
        elif not en_cadena and c == ")":
            nivel -= 1
        if c == "," and nivel == 0 and not en_cadena:
            partes.append("".join(actual))
            actual = []
        else:
            actual.append(c)
    partes.append("".join(actual))
    return partes


_CREATE_TABLE = re.compile(
    rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{ESQUEMA}\.(\w+)\s*\(",
    re.IGNORECASE,
)


def _tablas_creadas(sql: str) -> dict[str, frozenset[str]]:
    limpio = sin_comentarios(sql)
    tablas: dict[str, frozenset[str]] = {}
    for m in _CREATE_TABLE.finditer(limpio):
        cuerpo = _cuerpo_entre_parentesis(limpio, m.end() - 1)
        columnas = set()
        for definicion in _partir_arriba(cuerpo):
            palabras = definicion.split()
            if palabras and palabras[0].lower() not in _NO_SON_COLUMNAS:
                columnas.add(palabras[0].strip('"').lower())
        tablas[m.group(1).lower()] = frozenset(columnas)
    return tablas


def columnas_de_crear_tablas(sql: str) -> dict[str, frozenset[str]]:
    """`{'renglon': {...}, 'pedido': {...}, ...}` de `sql/crear_tablas.sql`.

    La lista esperada **no se escribe a mano**: el ADR 0003 define
    `crear_tablas.sql` como "la forma a la que se quiere llegar", y toda
    columna nueva ya tiene que ir ahí. Una segunda copia sería una lista que se
    queda vieja y da luz verde sobre una base a la que le falta algo.
    """
    tablas = _tablas_creadas(sql)
    if not tablas:
        raise ValueError(
            f"No se encontró ni un CREATE TABLE de `{ESQUEMA}` en "
            f"sql/crear_tablas.sql. Cero tablas no es 'todo en orden': es que "
            f"el archivo cambió de forma y el chequeo compararía contra nada."
        )
    return tablas


_ALTER_TABLE = re.compile(
    rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{ESQUEMA}\.(\w+)\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)
_ADD = re.compile(
    r"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)",
    re.IGNORECASE,
)


def migracion_de_cada_columna(
    migraciones: Mapping[str, str],
) -> dict[tuple[str, str], str]:
    """`{('renglon', 'piezas_que_faltaron'): '0011-recibido-parcial-y-a-mano.sql', ...}`

    De los `ADD COLUMN` de cada `ALTER TABLE pedidos.<t>`, y de las columnas de
    los `CREATE TABLE` que hacen la 0003 y la 0004. Si dos migraciones nombran
    la misma columna, se queda la **primera** por nombre de archivo: es la que
    la trajo, y las demás son idempotentes sobre ella.
    """
    de_que: dict[tuple[str, str], str] = {}
    for archivo in sorted(migraciones):
        sql = migraciones[archivo]
        for tabla, columnas in _tablas_creadas(sql).items():
            for columna in columnas:
                de_que.setdefault((tabla, columna), archivo)
        for m in _ALTER_TABLE.finditer(sin_comentarios(sql)):
            tabla = m.group(1).lower()
            for columna in _ADD.findall(m.group(2)):
                if columna.lower() not in _NO_SON_COLUMNAS:
                    de_que.setdefault((tabla, columna.lower()), archivo)
    return de_que


@dataclass(frozen=True, slots=True)
class LecturaDeForma:
    """Lo que devolvió `select * from pedidos.<tabla> limit 0`.

    `columnas` es `None` si la lectura no se pudo hacer; entonces `tipo` es el
    nombre de la excepción y `sqlstate` el código de Postgres, si lo hubo.
    **Nunca el texto de la excepción** (regla 5): lleva la cadena de conexión.
    """

    tabla: str
    columnas: frozenset[str] | None
    tipo: str = ""
    sqlstate: str = ""


def _comando_de(archivo: str) -> str:
    return f"{_PSQL} -v ON_ERROR_STOP=1 < {archivo}"


def revisar_forma(
    esperadas: Mapping[str, frozenset[str]],
    lecturas: Sequence[LecturaDeForma],
    de_que_migracion: Mapping[tuple[str, str], str],
) -> Informe:
    """El veredicto. **Función pura.**

    - Todo lo esperado está: `ok`.
    - Falta algo: **una** `FALLA` que lo junta todo —tabla por tabla, con qué
      migración trae cada cosa— y cuya reparación es el comando de **cada**
      migración que falta, en orden y sin repetir (la 0009 toca dos tablas y
      se corre una vez). Si alguna crea una tabla, después va `crear_rol.sql`:
      una tabla nueva nace sin GRANT.
    - Sobra algo: un `PENDIENTE` aparte, que no tumba nada.

    Una columna que **ninguna** migración agrega —de la primera versión del
    DDL— no se atribuye a una migración inventada: se dice, y la reparación es
    mirar la tabla (`\\d`) contra `crear_tablas.sql`. Un permiso negado tampoco
    es una migración: es `crear_rol.sql`.
    """
    por_tabla = {l.tabla: l for l in lecturas}
    renglones: list[str] = []
    a_correr: set[str] = set()
    crean_tabla = False
    falta_el_ddl = False
    sin_permiso: list[str] = []
    a_mirar: list[str] = []
    de_mas: list[str] = []
    cuantas_de_mas = 0
    total = 0

    for tabla in sorted(esperadas):
        esperadas_aqui = esperadas[tabla]
        total += len(esperadas_aqui)
        lectura = por_tabla.get(tabla)

        if lectura is None or lectura.columnas is None:
            tipo = lectura.tipo if lectura else "no se leyó"
            sqlstate = lectura.sqlstate if lectura else ""
            if sqlstate == NO_EXISTE:
                archivos = sorted(
                    {de_que_migracion[(tabla, c)] for c in esperadas_aqui
                     if (tabla, c) in de_que_migracion}
                )
                if archivos:
                    a_correr.update(archivos)
                    crean_tabla = True
                    renglones.append(
                        f"{ESQUEMA}.{tabla}: la tabla NO EXISTE. La crea "
                        f"sql/migraciones/{archivos[0]}."
                    )
                else:
                    falta_el_ddl = crean_tabla = True
                    renglones.append(
                        f"{ESQUEMA}.{tabla}: la tabla NO EXISTE y ninguna "
                        f"migración la crea: sale de sql/crear_tablas.sql."
                    )
            elif sqlstate == SIN_PERMISO:
                sin_permiso.append(tabla)
                renglones.append(
                    f"{ESQUEMA}.{tabla}: permiso negado al leerla ({tipo}). No es "
                    f"una migración: es un GRANT que falta."
                )
            else:
                a_mirar.append(tabla)
                renglones.append(
                    f"{ESQUEMA}.{tabla}: no se pudo leer su forma ({tipo}"
                    f"{', SQLSTATE ' + sqlstate if sqlstate else ''})."
                )
            continue

        faltan = sorted(esperadas_aqui - lectura.columnas)
        sobran = sorted(lectura.columnas - esperadas_aqui)
        if sobran:
            de_mas.append(f"{ESQUEMA}.{tabla}: {', '.join(sobran)}")
            cuantas_de_mas += len(sobran)
        if not faltan:
            continue

        agrupadas: dict[str, list[str]] = {}
        huerfanas: list[str] = []
        for columna in faltan:
            archivo = de_que_migracion.get((tabla, columna))
            if archivo is None:
                huerfanas.append(columna)
            else:
                agrupadas.setdefault(archivo, []).append(columna)
        for archivo in sorted(agrupadas):
            a_correr.add(archivo)
            renglones.append(
                f"{ESQUEMA}.{tabla}: falta {', '.join(agrupadas[archivo])} "
                f"-> la trae sql/migraciones/{archivo}"
            )
        if huerfanas:
            a_mirar.append(tabla)
            renglones.append(
                f"{ESQUEMA}.{tabla}: falta {', '.join(huerfanas)} y ninguna "
                f"migración la agrega: viene de la primera versión de "
                f"sql/crear_tablas.sql, o alguien la quitó a mano."
            )

    informe = Informe()

    if not renglones:
        informe += _ok(
            NOMBRE,
            f"{_plural(len(esperadas), 'tabla', 'tablas')}, "
            f"{total} columnas, ninguna falta",
        )
    else:
        migraciones = sorted(a_correr)
        detalle = renglones + [
            "",
            "El código que se está desplegando nombra esas columnas en sus",
            "sentencias: con la base así, la lista del día rebota con",
            "'column ... does not exist' y el lote de la noche se corta.",
            "Las migraciones sólo agregan: el código anterior sigue funcionando",
            "con la base migrada, así que el orden es migrar y después desplegar.",
            "El rol continental no puede correrlas (ADR 0003): va con el dueño.",
        ]
        reparacion = ["# desde ~/proyectos/Continental, con credenciales de dueño, en este orden:"]
        if falta_el_ddl:
            reparacion.append(_comando_de("sql/crear_tablas.sql"))
        reparacion += [_comando_de(f"sql/migraciones/{m}") for m in migraciones]
        if crean_tabla or sin_permiso:
            reparacion.append(
                "# una tabla nueva nace sin GRANT: otórgalo DESPUÉS de crearla"
                if crean_tabla
                else "# el rol no alcanza su propia tabla: vuelve a otorgar"
            )
            reparacion.append(_comando_de("sql/crear_rol.sql"))
        for tabla in a_mirar:
            reparacion.append(
                f"# mira la tabla real y compárala con sql/crear_tablas.sql:"
            )
            reparacion.append(f'{_PSQL} -c "\\d {ESQUEMA}.{tabla}"')
        reparacion.append("# y vuelve a desplegar: ~/proyectos/Continental/scripts/desplegar.sh")

        if migraciones:
            resumen = (
                f"falta{'n' if len(migraciones) > 1 else ''} "
                f"{_plural(len(migraciones), 'migración', 'migraciones')}: "
                + ", ".join(m[:4] for m in migraciones)
            )
        elif sin_permiso:
            resumen = f"permiso negado en {', '.join(sin_permiso)}"
        else:
            resumen = "la base no tiene la forma que el código espera"
        informe += _falla(NOMBRE, resumen, "\n".join(detalle), "\n".join(reparacion))

    if de_mas:
        informe += _pendiente(
            NOMBRE_DE_MAS,
            "la base trae "
            + _plural(cuantas_de_mas, "columna", "columnas")
            + " de más",
            "\n".join(
                de_mas
                + [
                    "",
                    "La base va ADELANTE del código: se corrió una migración que",
                    "este código todavía no conoce. Es el orden correcto —migrar,",
                    "luego desplegar— y el código de hoy no las nombra, así que no",
                    "le estorban. Si nadie corrió una migración así, alguien las",
                    "agregó a mano, y eso sí hay que preguntarlo.",
                ]
            ),
        )

    return informe


def mensaje_para_el_latido(informe: Informe) -> str:
    """Una línea para Kuma. **Función pura.** Sin comandos y sin excepciones:
    el comando largo vive en el journal, y una línea de Kuma se lee de reojo."""
    fallas = informe.fallas
    if not fallas:
        return "el lote no corrió: la revisión de la forma no dijo nada"
    return "el lote no corrió, la base no cuadra: " + "; ".join(
        r.resumen for r in fallas
    )


# ==========================================================================
# RECOLECCIÓN — lee de Postgres y de disco. Esto NO se prueba.
# ==========================================================================


def leer_la_forma(motor, tablas: Sequence[str]) -> list[LecturaDeForma]:
    """`select * from pedidos.<t> limit 0` por tabla. **LEE de Postgres.**

    Como el rol, y no preguntándole al catálogo: es lo que el rol puede hacer
    sin permisos nuevos, y contesta lo que este rol ve **ahora** (casilla 5 del
    ticket 17). `limit 0` trae las claves del resultado sin traer una fila.

    Cada tabla en su transacción (`rollback` tras el fallo), por lo mismo que
    `verificar._intentar_leer`: sin eso, la primera tabla que falta abortaría
    la transacción y las demás contestarían otra cosa.
    """
    from sqlalchemy import text

    lecturas: list[LecturaDeForma] = []
    with motor.connect() as conexion:
        for tabla in tablas:
            try:
                resultado = conexion.execute(
                    text(f"select * from pedidos.{tabla} limit 0")
                )
                lecturas.append(
                    LecturaDeForma(tabla, frozenset(k.lower() for k in resultado.keys()))
                )
            except Exception as exc:  # noqa: BLE001
                conexion.rollback()
                origen = getattr(exc, "orig", None)
                lecturas.append(
                    LecturaDeForma(
                        tabla,
                        None,
                        type(exc).__name__,
                        str(getattr(origen, "pgcode", "") or ""),
                    )
                )
    return lecturas


def _leer_los_archivos() -> tuple[dict[str, frozenset[str]], dict[tuple[str, str], str]]:
    esperadas = columnas_de_crear_tablas(CREAR_TABLAS.read_bytes().decode("utf-8"))
    migraciones = {
        m.name: m.read_bytes().decode("utf-8")
        for m in sorted(MIGRACIONES.glob("*.sql"))
    }
    return esperadas, migracion_de_cada_columna(migraciones)


def revisar_con(motor) -> Informe:
    """La revisión entera con un motor ya construido. **LEE de Postgres.**

    La usa `verificar.correr`, que ya tiene su motor, para que la corrida
    completa diga también la forma.
    """
    try:
        esperadas, de_que = _leer_los_archivos()
    except (OSError, ValueError) as exc:
        return _falla(
            NOMBRE,
            "no se pudieron leer sql/crear_tablas.sql o sql/migraciones/",
            f"{type(exc).__name__}. Sin la forma esperada no hay contra qué comparar.",
            "git -C ~/proyectos/Continental status -- sql/",
        )
    try:
        lecturas = leer_la_forma(motor, sorted(esperadas))
    except Exception as exc:  # noqa: BLE001
        return _falla(
            NOMBRE,
            "no se pudo preguntar a la base",
            "\n".join(
                [
                    f"no se pudo abrir la conexión ({type(exc).__name__}).",
                    "Esto no dice que la forma esté mal: dice que no se pudo",
                    "averiguar, y sin averiguarlo no se reinicia nada.",
                ]
            ),
            "# ¿está arriba el contenedor del almacén?\n"
            "docker ps --filter name=farmacia_warehouse\n"
            "# ¿trae el .env su WAREHOUSE_URL?\n"
            "grep -c WAREHOUSE_URL ~/proyectos/Continental/.env",
        )
    return revisar_forma(esperadas, lecturas, de_que)


def correr() -> Informe:
    """Construye el motor y revisa. **LEE de Postgres**; no se prueba."""
    try:
        from continental.almacen import motor

        el_motor = motor()
    except Exception as exc:  # noqa: BLE001
        return _falla(
            NOMBRE,
            "no se pudo construir el motor",
            f"{type(exc).__name__}. Sin WAREHOUSE_URL no hay base a la que "
            f"preguntarle su forma (ver .env.example).",
            "grep -c WAREHOUSE_URL ~/proyectos/Continental/.env",
        )
    return revisar_con(el_motor)


# ==========================================================================
# E — el lote no corre sobre una base que no cuadra
# ==========================================================================


def antes_del_lote(
    *,
    revisar: Callable[[], Informe] | None = None,
    latir: Callable[..., object] | None = None,
) -> int:
    """Lo primero que hace `python -m continental.lote`. 0 = puede correr.

    Tapa la trampa de la alternativa D: el `git pull` del despliegue ya dejó
    el código nuevo en disco aunque el despliegue se haya detenido en el paso
    de la forma, y el timer de las 22:00 lo usaría contra la base vieja.

    Si la forma no cuadra —o no se pudo averiguar—: el informe entero va al
    journal con el comando que lo arregla, el latido va `down` con la
    migración que falta, y se devuelve 1 para que systemd marque la unidad.
    **No escribe la fila de `corrida_del_lote`**: el lote no corrió, y con la
    base así esa tabla puede ser justo la que falta.

    Si cuadra, no late: el latido de una noche buena lo manda la corrida al
    final. Latir `up` aquí diría "todo bien" antes de saberlo.

    Las columnas de más no detienen nada, igual que en el despliegue.

    Solo **lee**. El servicio web NO se niega a arrancar por esto (ADR 0017).
    """
    if revisar is None:
        revisar = correr
    if latir is None:
        from continental.latido import mandar_el_latido

        latir = mandar_el_latido

    try:
        informe = revisar()
    except Exception as exc:  # noqa: BLE001
        # El TIPO y nunca el texto (regla 5).
        informe = _falla(
            NOMBRE,
            f"la revisión de la forma se cayó ({type(exc).__name__})",
            f"la revisión levantó {type(exc).__name__} antes de dar un veredicto.",
            "cd ~/proyectos/Continental && .venv/bin/python -m continental.verificar --forma",
        )

    if informe.codigo_de_salida == 0:
        if informe.pendientes:
            log.info("%s", informe.como_texto(TITULO))
        return 0

    log.error(
        "%s\n\n==> el lote NO corrió: la base no tiene la forma que este código "
        "espera.\n    Corre arriba lo que se nombra y vuelve a lanzarlo:\n"
        "    sudo systemctl start continental-lote.service",
        informe.como_texto(TITULO),
    )
    from continental.latido import ABAJO

    try:
        latir(estado=ABAJO, mensaje=mensaje_para_el_latido(informe), segundos=0.0)
    except Exception as exc:  # noqa: BLE001 — un latido perdido no cambia el veredicto
        log.warning("El latido a Uptime Kuma levantó (%s).", type(exc).__name__)
    return 1


__all__ = [
    "FALLA",
    "LecturaDeForma",
    "NO_EXISTE",
    "SIN_PERMISO",
    "TITULO",
    "antes_del_lote",
    "columnas_de_crear_tablas",
    "correr",
    "leer_la_forma",
    "mensaje_para_el_latido",
    "migracion_de_cada_columna",
    "revisar_con",
    "revisar_forma",
    "sin_comentarios",
]
