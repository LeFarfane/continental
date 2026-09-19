"""Lo que del ticket 07 se puede comprobar **sin Postgres**.

Ninguna prueba de este repo toca una base, y ésta tampoco: lee los tres `.sql`
de `sql/` como texto y afirma sobre ellos. No es un sustituto de
`sql/verificar_rol.sql` —que es el que pregunta a la base de verdad y da el
veredicto sobre el rol—, es la mitad que sí cabe en el suite: las decisiones
que viven **en el archivo** y que se rompen al editarlo.

Por qué vale la pena, y no es celo:

- Los `.sql` no los importa nadie. Un `double precision` que se cuele en la
  tabla del pedido no rompe ninguna prueba, no rompe el arranque, y se
  descubre meses después cuando un total no cuadra contra la factura por
  centavos que nadie puede explicar.
- Las cinco tablas de `marts` están escritas en **tres lugares**: las consultas
  de `almacen.py`, los `GRANT` de `crear_rol.sql` y la lista esperada de
  `verificar_rol.sql`. Que los tres digan lo mismo es exactamente el tipo de
  cosa que se desincroniza en silencio, y la falla que produce —"permission
  denied for table ..." en atlas, a las 8 de la mañana— es cara de diagnosticar
  desde lejos.
- El acento de `'en tránsito'` sobrevive a git, a un editor y a un `psql`
  distraído, o no sobrevive. Aquí se revisa el archivo; la comprobación 15 de
  `verificar_rol.sql` revisa lo que de verdad quedó guardado.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from continental.almacenamiento import ESTADOS_DE_LA_LISTA, ESTADOS_DEL_RENGLON
from continental.clasificacion import ABARROTE, MEDICAMENTO, SIN_CLASIFICAR

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"

CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"

#: Las tres del glosario de `CONTEXT.md`, en su orden, más las dos que no están
#: ahí: el precio congelado de un renglón en un proveedor (ticket 12) y la
#: corrida del lote nocturno (ticket 19, ADR 0007).
#:
#: Que las dos últimas no estén en el glosario no es un descuido. "Precio de
#: proveedor" no es un concepto que el negocio nombre —el dueño dice "el precio
#: de NADRO"—, es el grano con el que ese precio se puede guardar sin inventar
#: treinta y seis columnas; y "corrida del lote" es cómo le fue a un proceso
#: nuestro una noche, que tampoco es vocabulario de farmacia. El glosario manda
#: sobre el nombre de lo que el negocio nombra.
TABLAS = (
    "pedidos.pedido_sugerido",
    "pedidos.pedido",
    "pedidos.renglon",
    "pedidos.precio_de_proveedor",
    "pedidos.corrida_del_lote",
)

#: Lo único que Continental lee del almacén. Cinco y ninguna más: `fct_merma`,
#: `fct_caducidad` y `fct_precio_competencia` también viven en `marts` y no se
#: leen aquí.
MARTS_QUE_SE_LEEN = {
    "marts.dim_fecha",
    "marts.dim_producto",
    "marts.dim_proveedor",
    "marts.fct_compras",
    "marts.fct_ventas",
}

#: Tipos que jamás deben aparecer en estas tablas. Los dos primeros porque el
#: dinero en coma flotante deja de cuadrar por centavos que nadie puede
#: explicar (la lección que farmacia-data pagó al dejar que una librería
#: dedujera los tipos). `money` porque depende de `lc_monetary` del servidor:
#: el mismo valor se lee distinto según cómo arrancara el contenedor.
TIPOS_PROHIBIDOS = ("double precision", "real", "float", "money")


def _texto(ruta: Path) -> str:
    """El archivo como texto, exigiendo UTF-8.

    En binario y decodificando a mano a propósito: si alguien lo guarda en
    latin1, el acento de `'en tránsito'` se rompe y esta prueba se pone roja
    aquí, que es barato. La alternativa es descubrirlo en atlas, con el CHECK
    ya creado con el acento deformado y un `UPDATE` que rebota sin explicar por
    qué.
    """
    return ruta.read_bytes().decode("utf-8")


def _cuerpo_de_tabla(sql: str, tabla: str) -> str:
    """El `CREATE TABLE` de esa tabla, desde el paréntesis hasta su cierre."""
    inicio = sql.index(f"CREATE TABLE IF NOT EXISTS {tabla} (")
    fin = sql.index("\n);", inicio)
    return sql[inicio:fin]


# ------------------------------------------------------- las tres tablas


def test_los_tres_archivos_existen_y_son_utf8():
    """El primer cinturón: que estén, y que se puedan leer como UTF-8.

    Si esto falla, todo lo demás falla con un error que no explica nada.
    """
    for ruta in (CREAR_TABLAS, CREAR_ROL, VERIFICAR_ROL):
        assert ruta.exists(), f"Falta {ruta.relative_to(RAIZ).as_posix()}."
        _texto(ruta)


def test_estan_las_cinco_tablas_y_ninguna_mas():
    """Las cinco y ninguna más: las tres del glosario, el precio y la corrida.

    Una sexta que aparezca sin pasar por aquí es una decisión de esquema que
    nadie razonó: el DDL se corre a mano una vez, así que agregar una tabla es
    un acto deliberado y debe verse como tal. La cuarta entró con el ticket 12
    y **la quinta con el 19** (`pedidos.corrida_del_lote`, ADR 0007), y las dos
    llegaron acompañadas de su migración, de su GRANT y de comprobaciones
    nuevas en el verificador — que es el precio completo de una tabla aquí.
    """
    declaradas = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\S+)", _texto(CREAR_TABLAS)))
    assert declaradas == set(TABLAS)


@pytest.mark.parametrize("tabla", TABLAS)
def test_toda_tabla_dice_a_que_negocio_pertenece(tabla: str):
    """Regla 7 de CLAUDE.md, y sin `DEFAULT`.

    Un default dejaría escribir una fila sin decir de qué negocio es, que es
    justo lo contrario de lo que la regla pide. Hoy siempre vale `farmacia_01`
    y aun así se escribe cada vez.
    """
    cuerpo = _cuerpo_de_tabla(_texto(CREAR_TABLAS), tabla)
    columna = re.search(r"^\s*negocio\s+(.+)$", cuerpo, re.MULTILINE)

    assert columna, f"{tabla} no tiene columna `negocio` (regla 7 de CLAUDE.md)."
    assert "NOT NULL" in columna.group(1), f"{tabla}.negocio admite nulos."
    assert "DEFAULT" not in columna.group(1), (
        f"{tabla}.negocio tiene DEFAULT: eso deja escribir una fila sin decir "
        "de qué negocio es."
    )


@pytest.mark.parametrize("tipo", TIPOS_PROHIBIDOS)
def test_el_dinero_no_es_coma_flotante(tipo: str):
    """Ni el dinero ni nada más en estas tablas.

    `piezas_vendidas` tampoco: viene de `fct_ventas.cantidad`, que no siempre
    es entera (5 artículos con `granel = 1`, medido sobre el respaldo del
    2026-07-27), y en coma flotante `1.1 + 2.2 + 0.7` da `4.000000000000001`
    —que redondeado hacia arriba propone 5 piezas de algo de lo que salieron 4.
    """
    sql = _texto(CREAR_TABLAS)
    # Solo los cuerpos de las tablas: los comentarios de la cabecera nombran
    # `double precision` justamente para explicar por qué no se usa.
    cuerpos = "\n".join(_cuerpo_de_tabla(sql, t) for t in TABLAS)

    assert not re.search(rf"\b{tipo}\b", cuerpos), (
        f"Alguna columna de las tablas del pedido quedó como `{tipo}`. El "
        "dinero es `numeric` explícito, siempre."
    )


def test_el_total_del_pedido_es_decimal_explicito():
    """Hoy nadie escribe precios todavía, pero la columna ya tiene su tipo.

    Es el punto del ticket: el lugar donde va a vivir el dinero se decide
    ahora, no el día que haya precios y alguien tenga prisa.
    """
    cuerpo = _cuerpo_de_tabla(_texto(CREAR_TABLAS), "pedidos.pedido")
    assert re.search(r"^\s*total_sin_iva\s+numeric\(12,2\)", cuerpo, re.MULTILINE), (
        "`pedidos.pedido.total_sin_iva` dejó de ser `numeric(12,2)`."
    )


def test_uno_por_dia_y_negocio_lo_impide_la_base():
    """La restricción, no la intención.

    Un `SELECT` y si-no-existe-`INSERT` en Python tiene una carrera entre los
    dos pasos: dos pestañas abiertas a la misma hora bastan para duplicar la
    lista del día sin un solo error. Que lo rechace la base.
    """
    cuerpo = _cuerpo_de_tabla(_texto(CREAR_TABLAS), "pedidos.pedido_sugerido")
    assert "UNIQUE (negocio, fecha_del_pedido)" in cuerpo, (
        "Se perdió la restricción que garantiza un pedido sugerido por día y "
        "negocio. Sin ella, 'uno por día' vuelve a ser una intención del "
        "código."
    )


# --------------------------------------------- el vocabulario del glosario


def _valores_del_check(tabla: str, restriccion: str) -> list[str]:
    """Los literales de un `CHECK (columna IN ('a', 'b', ...))`."""
    cuerpo = _cuerpo_de_tabla(_texto(CREAR_TABLAS), tabla)
    bloque = cuerpo[cuerpo.index(f"CONSTRAINT {restriccion}") :]
    return re.findall(r"'([^']+)'", bloque[: bloque.index("),")])


def test_los_estados_del_pedido_sugerido_son_los_del_glosario():
    """`abierto` → `cerrado` → `vencido`, y ningún sinónimo.

    Un "finalizado" que se cuele parte la lista en dos vocabularios y las
    consultas empiezan a mentir por omisión.
    """
    assert _valores_del_check("pedidos.pedido_sugerido", "ck_pedido_sugerido_estado") == [
        "abierto",
        "cerrado",
        "vencido",
    ]


def test_los_estados_del_renglon_son_los_del_glosario_con_su_acento():
    """Los cinco de `CONTEXT.md`, y **`en tránsito` lleva acento**.

    El glosario manda sobre el nombre de cualquier cosa. Guardar `en_transito`
    sería un segundo nombre para lo mismo, que es justo lo que el repo
    prohíbe; y guardarlo sin acento por accidente —un archivo en latin1, un
    editor servicial— es peor, porque el código sí lo escribe con acento y el
    CHECK lo rechazaría sin decir por qué.
    """
    assert _valores_del_check("pedidos.renglon", "ck_renglon_estado") == [
        "abierto",
        "en tránsito",
        "recibido",
        "recibido parcial",
        "descartado",
    ]


def test_la_clasificacion_guardada_es_la_que_calcula_el_codigo():
    """El CHECK y `clasificacion.py` no pueden divergir.

    Se importan las constantes de verdad en vez de repetir los textos: si
    alguien renombra `SIN_CLASIFICAR`, esta prueba se pone roja en lugar de
    dejar que el renglón rebote contra el CHECK en producción.
    """
    assert set(_valores_del_check("pedidos.renglon", "ck_renglon_clasificacion")) == {
        MEDICAMENTO,
        ABARROTE,
        SIN_CLASIFICAR,
    }


def test_los_estados_que_escribe_el_codigo_son_los_que_el_ddl_acepta():
    """Las constantes de `almacenamiento.py` contra los CHECK, en los dos sentidos.

    Es el mismo hueco que `test_lo_que_lee_almacen_py_esta_otorgado` cierra del
    lado de los permisos: dos archivos que dicen lo mismo y que nadie obliga a
    decirlo igual. Si el código escribiera un estado que el CHECK no conoce, el
    `UPDATE` rebotaría en atlas con una violación de restricción que no explica
    nada; si el CHECK aceptara uno que el código nunca escribe, sería
    vocabulario muerto invitando a que alguien lo use.

    Se comparan como **tuplas** y no como conjuntos: el orden de los estados es
    el del glosario —`abierto` → `cerrado` → `vencido`— y ese orden es la
    máquina de estados escrita.
    """
    assert (
        tuple(_valores_del_check("pedidos.pedido_sugerido", "ck_pedido_sugerido_estado"))
        == ESTADOS_DE_LA_LISTA
    )
    assert (
        tuple(_valores_del_check("pedidos.renglon", "ck_renglon_estado"))
        == ESTADOS_DEL_RENGLON
    )


# ------------------------------------------------------- el rol y sus GRANT


def test_el_rol_solo_lee_de_marts_lo_que_el_codigo_lee():
    """Los `GRANT SELECT ON marts.*` son exactamente las cinco.

    Ni una menos —el código truena con "permission denied"— ni una más: que
    `fct_merma` o `fct_precio_competencia` se colaran sería dejar de estar
    acotado, que es el único motivo por el que este rol existe en vez de
    reusar `farmacia`.
    """
    otorgadas = set(re.findall(r"GRANT SELECT ON (marts\.\w+)", _texto(CREAR_ROL)))
    assert otorgadas == MARTS_QUE_SE_LEEN


def test_lo_que_lee_almacen_py_esta_otorgado():
    """Las consultas y los permisos no pueden desincronizarse.

    Es el hueco que Marlowe descubrió dos veces, las dos en producción y las
    dos igual: se agrega una lectura, nadie toca el rol, y la pantalla se cae
    con "permission denied for table ...". Aquí se cae la prueba.

    `dim_proveedor` es la excepción al revés y por eso no se exige al derecho:
    está otorgada porque el ticket 07 la pide —la pantalla tiene que decir
    "NADRO" y no "proveedor 3"—, y todavía no hay consulta que la use.
    """
    almacen = (RAIZ / "src" / "continental" / "almacen.py").read_text(encoding="utf-8")
    leidas = set(re.findall(r"\bmarts\.\w+", almacen))

    faltantes = leidas - MARTS_QUE_SE_LEEN
    assert not faltantes, (
        f"almacen.py lee {sorted(faltantes)} y sql/crear_rol.sql no lo otorga. "
        "En atlas eso es un 'permission denied for table' a las 8 de la mañana."
    )


def test_el_rol_no_puede_crear_tablas_ni_borrar_filas():
    """Lo que `crear_rol.sql` **no** otorga, comprobado sobre el archivo.

    - `CREATE`: el DDL se corre a mano con credenciales de dueño y vive en
      `crear_tablas.sql`. Un rol que puede crear tablas puede darle la vuelta a
      todo lo demás.
    - `DELETE` y `TRUNCATE`: Continental nunca borra una fila. Descartar un
      renglón, cerrar una lista o cancelar un pedido son cambios de estado.
      Un permiso que el código nunca ejercita es superficie de ataque gratuita
      —la misma lección que llevó a omitir `UPDATE` en el rol de Marlowe—.

    Solo se miran las líneas `GRANT`: los comentarios del archivo nombran las
    tres palabras justamente para explicar por qué no se otorgan, y un `REVOKE
    CREATE` defensivo también las nombra.
    """
    concedidos = [
        linea
        for linea in _texto(CREAR_ROL).splitlines()
        if linea.strip().startswith("GRANT")
    ]

    for prohibido in ("CREATE", "DELETE", "TRUNCATE", "ALL"):
        colados = [l for l in concedidos if re.search(rf"\b{prohibido}\b", l)]
        assert not colados, (
            f"sql/crear_rol.sql otorga `{prohibido}`: {colados}. Si de verdad "
            "hace falta, agrégalo con la razón escrita y actualiza esta prueba "
            "—no al revés."
        )


def test_el_verificador_espera_las_mismas_cinco_tablas():
    """`crear_rol.sql` otorga y `verificar_rol.sql` comprueba: que digan lo mismo.

    La comprobación 7 del verificador compara la lista de tablas de `marts` que
    el rol puede leer contra una lista literal. Si esa lista y los `GRANT` se
    separan, el verificador da luz verde sobre un rol que quedó mal —que es la
    peor de las fallas posibles en un archivo cuyo único trabajo es decir la
    verdad.
    """
    esperadas = ", ".join(sorted(t.removeprefix("marts.") for t in MARTS_QUE_SE_LEEN))
    assert f"'{esperadas}'" in _texto(VERIFICAR_ROL), (
        "La lista esperada de la comprobación 7 de sql/verificar_rol.sql no "
        f"coincide con los GRANT. Debería decir: {esperadas}"
    )
