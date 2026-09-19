"""El ticket 17, y aquí **solo se prueba una de sus dos mitades**.

`continental.verificar` está partido en dos a propósito y la línea es la
casilla 1 del ticket:

- **La mitad pura** recibe listas y diccionarios y devuelve un `Informe`. No
  conoce Postgres, no abre un socket y no mira el reloj. Es todo lo que este
  archivo prueba, y por eso el suite sigue corriendo **sin Postgres, sin red y
  sin `.env`**.
- **La mitad de recolección** (`correr`, `_intentar_leer`, `_filas_de`) es la
  que ejecuta SQL contra el almacén de producción. **No se prueba, y eso es
  correcto**: probarla exigiría un Postgres con datos rotos a propósito, que es
  justo lo que el verificador existe para encontrar en el mundo. Lo que sí se
  comprueba aquí es que esa mitad esté **aislada**: que importar el módulo no
  abra nada y que ninguna función pura nombre un motor.

La frase que define el ticket es "pytest dice que el código hace lo que dice;
esto dice que los datos de producción están sanos". Estas pruebas son la
primera mitad de esa frase aplicada al verificador mismo.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib
import sys
from pathlib import Path

import pytest

from continental import verificar as v

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "src" / "continental" / "verificar.py"
CREAR_ROL = RAIZ / "sql" / "crear_rol.sql"


# --------------------------------------------------------------------------
# Datos de juguete. Listas y dataclasses, nada más: ni un fixture de conexión.
# --------------------------------------------------------------------------


def _sugerido(id_, dia="2026-09-18", estado="abierto", negocio="farmacia_01"):
    return v.FilaSugerido(
        pedido_sugerido_id=id_,
        negocio=negocio,
        fecha_del_pedido=dt.date.fromisoformat(dia),
        estado=estado,
    )


def _renglon(id_, estado="abierto", pedido_id=None, negocio="farmacia_01"):
    return v.FilaRenglon(
        renglon_id=id_,
        negocio=negocio,
        pedido_sugerido_id=1,
        pedido_id=pedido_id,
        estado=estado,
        descripcion=f"PRODUCTO {id_}",
    )


def _pedido(id_, estado=None, enviado_por=None, negocio="farmacia_01"):
    return v.FilaPedido(
        pedido_id=id_, negocio=negocio, estado=estado, enviado_por=enviado_por
    )


#: Las columnas que `pedidos.pedido` tiene HOY, según `sql/crear_tablas.sql`.
#: Ni `estado` ni `enviado_por` están: llegan con los tickets 20 y 21.
COLUMNAS_DE_HOY = frozenset(
    {
        "pedido_id",
        "negocio",
        "pedido_sugerido_id",
        "proveedor_id",
        "armado_en",
        "total_sin_iva",
    }
)

COLUMNAS_CON_EL_ENVIO = COLUMNAS_DE_HOY | {"estado", "enviado_por", "enviado_en"}


# ==========================================================================
# Casilla 1 — la línea entre lo puro y lo que lee Postgres
# ==========================================================================


def test_importar_el_modulo_no_abre_nada(monkeypatch):
    """Importar el verificador no puede exigir `.env`, ni Postgres, ni red.

    `desplegar.sh` lo invoca con `python -m`, pero `tests/test_compila.py` lo
    compila y este archivo lo importa: si el módulo creara el motor al
    importarse, el suite entero dependería de que exista `WAREHOUSE_URL`. Es
    la misma razón por la que `almacen.motor` está detrás de un `lru_cache` y
    no en el cuerpo del módulo.
    """
    from continental import almacen

    monkeypatch.delenv("WAREHOUSE_URL", raising=False)
    almacen.motor.cache_clear()
    sys.modules.pop("continental.verificar", None)

    modulo = importlib.import_module("continental.verificar")

    assert modulo.Informe() is not None
    assert almacen.motor.cache_info().currsize == 0, (
        "Importar continental.verificar creó el motor de SQLAlchemy. La mitad "
        "pura tiene que poder importarse sin almacén."
    )


#: Las funciones de la mitad pura, por nombre. La lista es el contrato de la
#: casilla 1 y **se comprueba con el ast**, no de palabra: si alguna de éstas
#: empieza a llamar a `motor()`, `connect()` o `text()`, la prueba de abajo se
#: pone roja.
PURAS = (
    "redactar",
    "tablas_de_marts_en",
    "tablas_de_pedidos_en",
    "revisar_sugeridos_abiertos",
    "revisar_transito_con_pedido",
    "revisar_pedidos_enviados",
    "revisar_permisos",
)

#: Lo que una función pura no puede nombrar. `now` y `today` están porque un
#: informe que dependa del reloj deja de ser reproducible — y porque el
#: Postgres del contenedor corre en UTC y su `current_date` va adelante del
#: último dato (trampa heredada de `CLAUDE.md`).
PROHIBIDO_EN_LAS_PURAS = {
    "motor",
    "connect",
    "execute",
    "text",
    "cargar",
    "create_engine",
    "now",
    "today",
    "open",
    "read_text",
}


def _definiciones() -> dict[str, ast.FunctionDef]:
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    return {
        n.name: n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)
    }


def _solo_las_ordenes() -> str:
    """El módulo sin su prosa: sin docstrings y sin comentarios.

    Hace falta por la misma razón que `_sin_comentarios` en
    `tests/test_compila.py`: este módulo **explica** en qué se diferencia de
    `sql/verificar_rol.sql`, y esa explicación nombra `information_schema`.
    Buscar sobre el texto entero confundiría la explicación con la orden y
    pondría roja una prueba por decir exactamente lo correcto.

    `ast.unparse` tira los comentarios solo; los docstrings hay que quitarlos.
    """
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    for nodo in ast.walk(arbol):
        cuerpo = getattr(nodo, "body", None)
        if not isinstance(nodo, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            continue
        primero = cuerpo[0] if cuerpo else None
        if (
            isinstance(primero, ast.Expr)
            and isinstance(primero.value, ast.Constant)
            and isinstance(primero.value.value, str)
        ):
            cuerpo.pop(0)
    return ast.unparse(arbol)


@pytest.mark.parametrize("nombre", PURAS)
def test_la_funcion_pura_no_nombra_un_motor_ni_el_reloj(nombre):
    """La casilla 1, comprobada sobre el árbol y no sobre la buena intención.

    Una función "pura" que un día llama a `motor()` deja de poder probarse sin
    Postgres, y el suite se entera tarde y mal: no con esta prueba roja, sino
    con una prueba que empieza a tardar diez segundos o a fallar en la torre.
    """
    definicion = _definiciones()[nombre]
    nombrado = {
        n.id for n in ast.walk(definicion) if isinstance(n, ast.Name)
    } | {n.attr for n in ast.walk(definicion) if isinstance(n, ast.Attribute)}

    coladas = nombrado & PROHIBIDO_EN_LAS_PURAS
    assert not coladas, (
        f"La función pura {nombre} nombra {sorted(coladas)}. Si necesita leer "
        f"de algún lado, lo que hace falta es un parámetro más, no una "
        f"conexión adentro."
    )


def test_la_recoleccion_no_se_prueba_y_el_modulo_lo_dice():
    """Que la mitad no probada esté **declarada**, no simplemente ausente.

    Es la diferencia entre una decisión y un olvido, y la única forma de que
    quien llegue después no "arregle" la falta de cobertura montando un
    Postgres en el suite.
    """
    doc = v.__doc__ or ""
    assert "no se prueban" in doc or "no se prueba" in doc
    assert "recolección" in doc.lower()


# ==========================================================================
# Casilla 2 — ninguna falla sin su comando de reparación
# ==========================================================================


def test_una_falla_sin_comando_de_reparacion_no_se_puede_ni_construir():
    """La casilla 2, puesta donde no se puede cumplir a medias.

    Escribirla como convención ("acuérdate de poner el comando") es cómo la
    tercera comprobación que alguien agregue el año que viene sale sin él. Un
    `Resultado` en falla **exige** la reparación en el constructor: el olvido
    revienta en la corrida, no en la revisión de código.
    """
    with pytest.raises(ValueError) as fallo:
        v.Resultado(nombre="lo que sea", estado=v.FALLA, detalle="algo está mal")

    assert "reparación" in str(fallo.value)


def test_un_ok_y_un_pendiente_no_necesitan_comando():
    """El otro lado: exigirle un comando a lo que no está roto sería teatro."""
    assert v.Resultado(nombre="x", estado=v.OK).estado == v.OK
    assert v.Resultado(nombre="y", estado=v.PENDIENTE, detalle="falta").estado == v.PENDIENTE


def test_el_estado_tiene_que_ser_uno_de_los_tres():
    with pytest.raises(ValueError):
        v.Resultado(nombre="x", estado="casi")


# ==========================================================================
# Casilla 4, invariante 1 — un solo sugerido abierto por día y negocio
# ==========================================================================


def test_un_solo_sugerido_abierto_por_dia_esta_en_orden():
    informe = v.revisar_sugeridos_abiertos(
        [
            _sugerido(1, "2026-09-17", estado="cerrado"),
            _sugerido(2, "2026-09-18"),
            _sugerido(3, "2026-09-18", negocio="farmacia_02"),
        ]
    )

    assert informe.fallas == ()
    assert informe.codigo_de_salida == 0


def test_dos_sugeridos_abiertos_el_mismo_dia_y_negocio_fallan():
    """El invariante tal cual lo escribe el ticket.

    `ux_pedido_sugerido_dia` debería impedirlo desde la base, y por eso el
    mensaje manda a mirar la restricción: si esto falla en producción, lo roto
    no es una lista, es la tabla — `CREATE TABLE IF NOT EXISTS` calla si la
    tabla ya existía con otra forma.
    """
    informe = v.revisar_sugeridos_abiertos(
        [_sugerido(7, "2026-09-18"), _sugerido(9, "2026-09-18")]
    )

    (falla,) = informe.fallas
    assert "2026-09-18" in falla.detalle
    assert "7" in falla.detalle and "9" in falla.detalle
    assert "UPDATE pedidos.pedido_sugerido" in falla.reparacion
    assert "IN (7)" in falla.reparacion, (
        "El comando tiene que cerrar las viejas y dejar abierta la más "
        "reciente (id 9), no cerrarlas todas."
    )
    assert "cerrado_en" in falla.reparacion, (
        "Sin cerrado_en el UPDATE rebota contra ck_pedido_sugerido_cierre: el "
        "comando de reparación tiene que correr tal cual está escrito."
    )


def test_una_lista_cerrada_no_compite_con_una_abierta():
    """Dos listas del mismo día donde una ya se cerró es lo normal, no una
    falla: el invariante habla de listas **abiertas**."""
    informe = v.revisar_sugeridos_abiertos(
        [_sugerido(7, "2026-09-18", estado="cerrado"), _sugerido(9, "2026-09-18")]
    )

    assert informe.fallas == ()


# ==========================================================================
# Casilla 4, invariante 2 — ningún renglón en tránsito sin su pedido
# ==========================================================================


def test_los_renglones_en_transito_con_su_pedido_estan_en_orden():
    informe = v.revisar_transito_con_pedido(
        [
            _renglon(1, estado=v.EN_TRANSITO, pedido_id=5),
            _renglon(2, estado="abierto"),
            _renglon(3, estado="descartado"),
        ]
    )

    assert informe.fallas == ()


def test_un_renglon_en_transito_sin_pedido_falla_con_las_dos_salidas():
    """La reparación dice **dos** cosas porque el dato admite dos lecturas.

    Si el pedido no existe, el renglón no se le pidió a nadie y devolverlo a
    `abierto` es lo defendible. Si el pedido sí existe y lo que se perdió es el
    enlace, la corrección es la otra — y ésa la decide una persona mirando
    `pedidos.pedido`, que es por qué el comando trae también el `SELECT` con
    el que se mira.
    """
    informe = v.revisar_transito_con_pedido(
        [
            _renglon(41, estado=v.EN_TRANSITO),
            _renglon(77, estado=v.EN_TRANSITO),
            _renglon(8, estado=v.EN_TRANSITO, pedido_id=2),
        ]
    )

    (falla,) = informe.fallas
    assert "41" in falla.detalle and "77" in falla.detalle
    assert "UPDATE pedidos.renglon" in falla.reparacion
    assert "IN (41, 77)" in falla.reparacion
    assert "SELECT" in falla.reparacion, (
        "Falta el comando con el que se mira si el pedido existe antes de "
        "devolver el renglón a abierto."
    )


# ==========================================================================
# Casilla 4, invariante 3 — ningún pedido enviado sin quién lo envió
# ==========================================================================


def test_sin_las_columnas_del_envio_el_invariante_queda_declarado_y_no_truena():
    """**Hoy `pedidos.pedido` no tiene ni `estado` ni `enviado_por`.**

    Llegan con los tickets 20 (`borrador`) y 21 (`borrador` -> `enviado`, con
    quién y cuándo). Inventarlas aquí sería escribir un `SELECT` que rebota en
    atlas con "column does not exist" y dejar el despliegue rojo por una
    columna que nadie prometió. El invariante se declara **pendiente**, con su
    porqué, y se enciende solo el día que las columnas existan.
    """
    informe = v.revisar_pedidos_enviados([_pedido(1)], COLUMNAS_DE_HOY)

    (pendiente,) = informe.pendientes
    assert informe.fallas == ()
    assert informe.codigo_de_salida == 0, (
        "Un invariante que todavía no se puede revisar no puede tumbar un "
        "despliegue: lo que falta es una columna, no un dato roto."
    )
    assert "enviado_por" in pendiente.detalle
    assert "21" in pendiente.detalle, "No dice qué ticket trae las columnas."


def test_con_las_columnas_puestas_el_invariante_empieza_a_revisar():
    """El día que los tickets 20 y 21 creen las columnas, esto revisa solo."""
    informe = v.revisar_pedidos_enviados(
        [
            _pedido(1, estado="enviado", enviado_por="encargado@farmacia"),
            _pedido(2, estado="borrador"),
        ],
        COLUMNAS_CON_EL_ENVIO,
    )

    assert informe.fallas == ()
    assert informe.pendientes == ()


def test_un_pedido_enviado_sin_firma_falla():
    informe = v.revisar_pedidos_enviados(
        [
            _pedido(3, estado="enviado", enviado_por=None),
            _pedido(4, estado="enviado", enviado_por="   "),
            _pedido(5, estado="enviado", enviado_por="duenio@farmacia"),
        ],
        COLUMNAS_CON_EL_ENVIO,
    )

    (falla,) = informe.fallas
    assert "3" in falla.detalle and "4" in falla.detalle
    assert "UPDATE pedidos.pedido" in falla.reparacion
    assert "IN (3, 4)" in falla.reparacion
    assert "borrador" in falla.reparacion, (
        "La reparación tiene que devolver el pedido a borrador para que se "
        "vuelva a enviar firmado, no inventarle una firma."
    )


# ==========================================================================
# Casilla 5 — los permisos, con SELECT 1 y no con el catálogo
# ==========================================================================


def test_las_tablas_de_marts_salen_de_crear_rol_sql_y_son_las_cinco():
    """La lista **no se escribe de memoria**: se lee de `sql/crear_rol.sql`.

    Es el archivo que de verdad otorga los permisos. Mantener aquí una
    segunda copia sería mantener una lista que se queda vieja y que da luz
    verde sobre un rol al que le falta una tabla — exactamente el modo de
    fallar que el ticket 07 ya nombró.
    """
    tablas = v.tablas_de_marts_en(CREAR_ROL.read_text(encoding="utf-8"))

    assert tablas == (
        "fct_ventas",
        "dim_producto",
        "dim_fecha",
        "fct_compras",
        "dim_proveedor",
    )


def test_las_tablas_de_pedidos_salen_del_mismo_archivo():
    tablas = v.tablas_de_pedidos_en(CREAR_ROL.read_text(encoding="utf-8"))

    assert tablas == (
        "pedido_sugerido",
        "renglon",
        "pedido",
        "precio_de_proveedor",
    )


def test_el_parseo_ignora_los_comentarios():
    """`crear_rol.sql` es mitad prosa: un GRANT nombrado en un comentario no
    es un permiso otorgado."""
    sql = """
    -- GRANT SELECT ON marts.fct_merma TO continental;  <- lo que NO se otorga
    GRANT SELECT ON marts.fct_ventas TO continental;
    """

    assert v.tablas_de_marts_en(sql) == ("fct_ventas",)


def test_un_archivo_sin_grants_no_pasa_de_largo():
    """Cero tablas no es "todo en orden": es que el archivo cambió de forma y
    el verificador se quedaría revisando nada, en verde."""
    with pytest.raises(ValueError):
        v.tablas_de_marts_en("-- aquí no hay nada")


def test_los_permisos_en_orden_se_reportan_juntos():
    informe = v.revisar_permisos(
        "marts",
        [v.LecturaDeTabla("marts", t, True) for t in ("fct_ventas", "dim_fecha")],
    )

    assert informe.fallas == ()
    assert "fct_ventas" in informe.resultados[0].resumen


def test_un_permiso_negado_trae_el_grant_y_el_arreglo_que_dura():
    """Las dos mitades, y la segunda es la que importa.

    El `GRANT` a mano levanta el servicio ahora y **se borra a las 20:30**:
    cada `dbt build` recrea los modelos de `marts` y se lleva los permisos por
    delante. Marlowe lo midió el 2026-09-06. El arreglo que dura vive en el
    repo de farmacia-data, en el `grants` del modelo, y por eso el mensaje lo
    nombra con la ruta del archivo.
    """
    informe = v.revisar_permisos(
        "marts",
        [
            v.LecturaDeTabla("marts", "fct_ventas", False, "permission denied"),
            v.LecturaDeTabla("marts", "dim_fecha", True),
            v.LecturaDeTabla("marts", "dim_proveedor", False, "permission denied"),
        ],
    )

    (falla,) = informe.fallas
    assert "GRANT SELECT ON marts.fct_ventas, marts.dim_proveedor TO continental" in (
        falla.reparacion
    )
    assert "dbt" in falla.reparacion and "grants" in falla.reparacion
    assert "20:30" in falla.detalle
    assert "dim_fecha" not in falla.resumen, "Se está señalando una tabla que sí se lee."


def test_los_permisos_se_comprueban_leyendo_y_no_mirando_el_catalogo():
    """La casilla 5 al pie de la letra, comprobada sobre el código.

    `information_schema` y `has_table_privilege` contestan lo que el catálogo
    cree, y el catálogo puede tener razón mientras la lectura rebota — o al
    revés. Lo que el ticket pide es la pregunta que de verdad importa: ¿puede
    este rol, ahora, leer esta tabla?
    """
    ordenes = _solo_las_ordenes()

    assert "SELECT 1 FROM" in ordenes
    for atajo in ("information_schema", "pg_catalog", "has_table_privilege", "pg_class"):
        assert atajo not in ordenes, (
            f"El verificador consulta {atajo}. Los permisos se comprueban "
            f"HACIENDO la lectura (casilla 5 del ticket 17)."
        )


# ==========================================================================
# Regla 5 de CLAUDE.md, traducida a una terminal
# ==========================================================================


def test_la_cadena_de_conexion_con_contrasena_nunca_sale_impresa():
    """Aquí no hay navegador, pero sí hay un journal y una terminal compartida.

    Un `str(exc)` de SQLAlchemy lleva la URL del motor con la contraseña
    dentro, y la salida de `desplegar.sh` se lee por ssh y queda en el
    scrollback de quien despliega. La decisión es **detalle sí, credenciales
    no**: se redacta en el borde, una vez.
    """
    crudo = (
        "OperationalError: (psycopg2.OperationalError) connection to server at "
        'postgresql+psycopg2://continental:s3cr3t-de-verdad@172.19.0.1:5432/farmacia'
        " failed"
    )

    limpio = v.redactar(crudo)

    assert "s3cr3t-de-verdad" not in limpio
    assert "continental" in limpio, "Redactó de más: el usuario sirve para diagnosticar."
    assert "172.19.0.1:5432" in limpio
    assert "OperationalError" in limpio


def test_redactar_no_estropea_un_texto_sin_credenciales():
    assert v.redactar("permission denied for table fct_ventas") == (
        "permission denied for table fct_ventas"
    )


# ==========================================================================
# Casillas 1 y 3 — acumula todas las fallas, y el código de salida sirve
# ==========================================================================


def _informe_con_los_tres_invariantes_rotos() -> v.Informe:
    """Los tres invariantes rotos **a la vez**, más un permiso negado.

    Es el escenario que demuestra la casilla de acumular: un verificador que se
    detuviera en la primera falla obligaría a desplegar cuatro veces para
    enterarse de cuatro cosas.
    """
    return (
        v.revisar_sugeridos_abiertos(
            [_sugerido(7, "2026-09-18"), _sugerido(9, "2026-09-18")]
        )
        + v.revisar_transito_con_pedido(
            [_renglon(41, estado=v.EN_TRANSITO), _renglon(77, estado=v.EN_TRANSITO)]
        )
        + v.revisar_pedidos_enviados(
            [_pedido(3, estado="enviado"), _pedido(4, estado="enviado")],
            COLUMNAS_CON_EL_ENVIO,
        )
        + v.revisar_permisos(
            "marts",
            [
                v.LecturaDeTabla("marts", "fct_ventas", False, "permission denied"),
                v.LecturaDeTabla("marts", "dim_producto", True),
            ],
        )
    )


def test_acumula_las_cuatro_fallas_en_lugar_de_detenerse_en_la_primera():
    informe = _informe_con_los_tres_invariantes_rotos()

    assert len(informe.fallas) == 4, (
        "Se perdió alguna falla por el camino. La casilla del ticket es "
        "acumular TODAS y publicarlas juntas."
    )
    assert len(informe.resultados) == 4


def test_cada_falla_acumulada_trae_un_comando_que_se_puede_copiar():
    """La casilla 2 revisada **mensaje por mensaje**, que es donde se cumple a
    medias."""
    for falla in _informe_con_los_tres_invariantes_rotos().fallas:
        assert falla.reparacion.strip(), f"{falla.nombre} no trae comando."
        assert "docker exec" in falla.reparacion, (
            f"{falla.nombre}: el comando no es copiable en atlas tal cual."
        )
        assert ";" in falla.reparacion, f"{falla.nombre}: la sentencia no termina."
        assert "<" not in falla.reparacion.split("#")[0], (
            f"{falla.nombre}: el comando tiene un hueco por llenar a mano. Un "
            f"comando con `<algo>` adentro no se copia, se interpreta — y a "
            f"las ocho de la mañana se interpreta mal."
        )


def test_el_codigo_de_salida_es_uno_si_algo_falla():
    assert _informe_con_los_tres_invariantes_rotos().codigo_de_salida == 1


def test_el_codigo_de_salida_es_cero_si_todo_esta_en_orden():
    informe = v.revisar_sugeridos_abiertos([_sugerido(1)])

    assert informe.codigo_de_salida == 0


def test_un_pendiente_solo_no_tumba_el_despliegue_pero_se_ve():
    informe = v.revisar_pedidos_enviados([_pedido(1)], COLUMNAS_DE_HOY)

    assert informe.codigo_de_salida == 0
    assert "··" in informe.como_texto(), "Un pendiente invisible es un pendiente perdido."


def test_el_texto_publica_las_cuatro_fallas_con_sus_comandos():
    texto = _informe_con_los_tres_invariantes_rotos().como_texto()

    for esperado in (
        "un solo pedido sugerido abierto por día y negocio",
        "ningún renglón en tránsito sin su pedido",
        "ningún pedido enviado sin quién lo envió",
        "UPDATE pedidos.pedido_sugerido",
        "UPDATE pedidos.renglon",
        "UPDATE pedidos.pedido",
        "GRANT SELECT ON marts.fct_ventas",
    ):
        assert esperado in texto, f"La salida no publica {esperado!r}."

    assert texto.rstrip().endswith("eso lo decide una persona."), (
        "La última línea tiene que dejar claro que esto señala y no repara."
    )
    assert "4 de 4" in texto


def test_el_informe_vacio_lo_dice_en_vez_de_imprimir_una_nada_verde():
    """Cero comprobaciones es un verificador que no revisó nada, no un
    almacén sano. Confundirlos es cómo una corrida rota se lee como buena."""
    texto = v.Informe().como_texto()

    assert "ninguna comprobación" in texto


# ==========================================================================
# En qué se diferencia de `sql/verificar_rol.sql`
# ==========================================================================


def test_el_modulo_explica_por_que_existen_los_dos_verificadores():
    """Dos archivos que se llaman parecido y revisan cosas distintas es una
    trampa para quien llegue después: uno mira la **forma** de la base con
    credenciales de dueño y una sola vez; el otro mira los **datos** con el rol
    acotado y en cada despliegue. Si el código no lo dice, alguien va a borrar
    uno creyendo que sobra."""
    doc = v.__doc__ or ""

    assert "verificar_rol.sql" in doc
    assert "dueño" in doc
