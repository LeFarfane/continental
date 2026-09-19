"""El pedido sugerido deja de recalcularse: se guarda, se relee y se cierra.

**Ninguna prueba toca Postgres**, igual que el resto del suite. El
almacenamiento entra por la misma costura que el almacén —un `Protocol`, una
implementación real y un doble en memoria, entregados por `Depends`—, así que
sustituirlo cabe en un renglón de `conftest.py`.

Eso deja un hueco honesto y hay que decirlo: **el SQL real no se puede
ejecutar desde la torre** (no hay Postgres alcanzable: Docker Desktop apagado y
nada en el 5432, verificado el 2026-09-19). Lo que este archivo sí puede hacer,
y hace, son dos cosas:

1. **Que el doble no mienta.** Un doble que acepta lo que Postgres rechazaría
   deja pruebas en verde que en atlas truenan. Aquí el doble rechaza lo mismo
   que los CHECK y los UNIQUE del DDL —un estado inventado, una clave vacía,
   un cerrado sin hora, dos listas del mismo día— y esas negativas se prueban
   una por una.
2. **Que el SQL real esté escrito con cuidado**, revisándolo como texto: que
   "nunca se duplica" se apoye en `ux_pedido_sugerido_dia` y no en un `SELECT`
   previo —entre el `SELECT` y el `INSERT` hay una carrera—, que no haya un
   `DELETE` (el rol no lo tiene), y que ninguna fecha salga del reloj.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pytest
import sqlalchemy

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    ABIERTO,
    CERRADO,
    ESTADOS_DE_LA_LISTA,
    RENGLON_ABIERTO,
    VENCIDO,
    AlmacenamientoDelPedido,
    AlmacenamientoPostgres,
    PedidoSugeridoDuplicado,
    Ventana,
    dias_primera_vez_configurados,
)
from continental.dobles import AlmacenamientoFalso
from continental.sugerido import Renglon

RUTA = "/api/pedido-sugerido"
FUENTE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "continental"
    / "almacenamiento.py"
)

NEGOCIO = "farmacia_01"


# ------------------------------- se crea si no existe, se lee si existe


def test_al_abrir_el_dia_se_crea_el_pedido_sugerido_si_no_existe(
    cliente, almacen, almacenamiento
):
    """La primera carga arma la lista **y la guarda**, con su ventana y su hora.

    Antes de este ticket la lista vivía solo en la respuesta HTTP y moría con
    ella. Ahora la respuesta trae el `pedido_sugerido_id` de una fila que
    existe, y eso es lo que permite que mañana alguien la cierre.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", existencia=4)]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["estado"] == ABIERTO
    assert cuerpo["pedido_sugerido_id"] is not None

    guardado = almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 5))
    assert guardado is not None
    assert guardado.estado == ABIERTO
    # Sin un cierre anterior, la ventana es la de la primera vez: los días que
    # diga `pedido.dias_primera_vez` en el YAML, contando los dos extremos. El
    # extremo derecho es el último día con datos. Ver `test_acumulacion.py`.
    assert guardado.ventana == Ventana(
        dt.date(2024, 3, 5) - dt.timedelta(days=dias_primera_vez_configurados() - 1),
        dt.date(2024, 3, 5),
    )
    assert [r.propuesto.clave for r in guardado.renglones] == ["7501000000001"]
    assert [r.estado for r in guardado.renglones] == [RENGLON_ABIERTO]


def test_al_volver_a_abrir_el_dia_se_lee_lo_guardado_y_no_se_recalcula(
    cliente, almacen
):
    """El criterio que cambia la pantalla: **lo que se muestra es lo guardado**.

    Se comprueba de la forma más dura que hay: después de la primera carga, el
    catálogo del almacén se vuelve una lectura que truena. Si la segunda carga
    recalculara, la ruta devolvería un hueco con su motivo (`ok: false`); como
    lee lo guardado, ni lo toca.

    Y de paso lo que el ticket 04 dejó dicho: los números viajan congelados.
    Que llegue mercancía no puede cambiar un renglón ya propuesto.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", existencia=4)]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 2)]

    primera = cliente.get(RUTA).json()

    def no_se_vuelve_a_leer():
        raise AssertionError(
            "la segunda carga volvió a leer el catálogo: está recalculando la "
            "lista en vez de leer la guardada."
        )

    almacen.catalogo = no_se_vuelve_a_leer
    almacen.ventas = lambda desde, hasta: no_se_vuelve_a_leer()

    segunda = cliente.get(RUTA).json()

    assert segunda["ok"] is True
    assert segunda["pedido_sugerido_id"] == primera["pedido_sugerido_id"]
    assert segunda["renglones"] == primera["renglones"]
    assert segunda["renglones"][0]["existencia"] == 4


def test_nunca_se_duplica_para_el_mismo_dia_y_negocio(cliente, almacen, almacenamiento):
    """Tres cargas de la página, una sola lista."""
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]

    ids = {cliente.get(RUTA).json()["pedido_sugerido_id"] for _ in range(3)}

    assert len(ids) == 1
    assert len(almacenamiento.listas) == 1


def test_dos_pestanas_a_la_vez_no_duplican_la_lista(almacenamiento):
    """La carrera de verdad: entre mirar si existe e insertarla, otro la insertó.

    El gancho `antes_de_insertar` mete esa segunda pestaña justo en el hueco.
    Quien pierde la carrera **no puede** crear una segunda lista del día: tiene
    que quedarse con la del que ganó, porque es la que el encargado va a
    trabajar. Sin la restricción de la base, aquí habría dos listas y nadie se
    enteraría —no hay error que ver—.
    """
    ventana = Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5))
    otra_pestana = lambda: almacenamiento.abrir_el_dia(  # noqa: E731
        NEGOCIO, dt.date(2024, 3, 5), ventana, lambda: (_renglon(2, "NAPROXENO"),)
    )

    almacenamiento.antes_de_insertar = otra_pestana
    perdedora = almacenamiento.abrir_el_dia(
        NEGOCIO, dt.date(2024, 3, 5), ventana, lambda: (_renglon(1, "PARACETAMOL"),)
    )

    assert len(almacenamiento.listas) == 1
    assert [r.propuesto.descripcion for r in perdedora.renglones] == ["NAPROXENO"]


def test_el_doble_rechaza_el_duplicado_igual_que_el_unique_de_postgres(almacenamiento):
    """El doble no puede aceptar lo que la base rechaza.

    `ux_pedido_sugerido_dia` es `UNIQUE (negocio, fecha_del_pedido)`. Un doble
    que dejara pasar el segundo `INSERT` pondría en verde una prueba que en
    atlas truena con una violación de restricción.
    """
    ventana = Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5))
    almacenamiento.insertar_la_lista(NEGOCIO, dt.date(2024, 3, 5), ventana, ())

    with pytest.raises(PedidoSugeridoDuplicado):
        almacenamiento.insertar_la_lista(NEGOCIO, dt.date(2024, 3, 5), ventana, ())


def test_el_sql_real_se_apoya_en_la_restriccion_y_no_en_un_select_previo():
    """Revisado como texto, porque desde la torre no hay Postgres que lo corra.

    Un `SELECT` y si-no-existe-`INSERT` tiene una carrera entre los dos pasos:
    dos pestañas abiertas a la misma hora bastan para duplicar la lista del día
    sin un solo error. El `ON CONFLICT` nombrando la restricción es lo que hace
    que la base sea quien lo impide.
    """
    inserciones = [
        s for n, s in _sentencias().items() if s.lower().lstrip().startswith("insert")
    ]
    de_la_lista = [s for s in inserciones if "into pedidos.pedido_sugerido" in s.lower()]

    assert de_la_lista, "No hay INSERT sobre pedidos.pedido_sugerido que revisar."
    for sentencia in de_la_lista:
        assert "on conflict on constraint ux_pedido_sugerido_dia" in sentencia.lower(), (
            "El INSERT del pedido sugerido dejó de apoyarse en la restricción "
            "UNIQUE. Sin ella, 'uno por día' vuelve a ser una intención del "
            "código con una carrera en medio."
        )


def test_dos_negocios_tienen_su_propia_lista_el_mismo_dia(almacenamiento):
    """Regla 7 de CLAUDE.md: el día es el mismo, la lista no.

    Hoy solo hay una farmacia y por eso esto no se puede ver en la pantalla.
    Se prueba igual: es lo único que se paga hoy para no reescribir el módulo
    el día que haya dos.
    """
    ventana = Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5))
    for negocio in ("farmacia_01", "farmacia_02"):
        almacenamiento.abrir_el_dia(
            negocio, dt.date(2024, 3, 5), ventana, lambda: (_renglon(1, "X"),)
        )

    assert len(almacenamiento.listas) == 2
    assert almacenamiento.leer("farmacia_02", dt.date(2024, 3, 5)) is not None


# --------------------------------------------- los estados de la lista


def test_los_estados_de_la_lista_son_los_del_glosario():
    """`abierto` → `cerrado` → `vencido`, y ningún sinónimo.

    Las constantes del código y el CHECK del DDL no pueden divergir: el que
    revisa que digan lo mismo es `test_sql_del_pedido.py`. Aquí se fija el
    vocabulario del lado de Python.
    """
    assert ESTADOS_DE_LA_LISTA == ("abierto", "cerrado", "vencido")


def test_una_lista_nace_abierta_y_sin_hora_de_cierre(almacenamiento):
    """El CHECK del DDL: cerrado si y solo si hay hora de cierre."""
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        dt.date(2024, 3, 5),
        Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5)),
        lambda: (_renglon(1, "PARACETAMOL"),),
    )

    assert lista.estado == ABIERTO
    assert lista.cerrado_en is None


def test_el_doble_rechaza_un_estado_que_el_ddl_no_conoce(almacenamiento):
    """Un "finalizado" que se cuele parte la lista en dos vocabularios."""
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        dt.date(2024, 3, 5),
        Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5)),
        lambda: (),
    )

    with pytest.raises(ValueError):
        almacenamiento.poner_estado(lista.pedido_sugerido_id, "finalizado")


def test_el_doble_rechaza_un_cerrado_sin_hora_y_un_abierto_con_ella(almacenamiento):
    """`CHECK ((estado = 'cerrado') = (cerrado_en IS NOT NULL))`, tal cual.

    Un `cerrado` sin hora no se puede auditar, y una hora de cierre en una
    lista abierta es una mentira a la espera de que alguien la lea.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        dt.date(2024, 3, 5),
        Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5)),
        lambda: (),
    )

    with pytest.raises(ValueError):
        almacenamiento.poner_estado(lista.pedido_sugerido_id, CERRADO, cerrado_en=None)
    with pytest.raises(ValueError):
        almacenamiento.poner_estado(
            lista.pedido_sugerido_id, ABIERTO, cerrado_en=dt.datetime.now(dt.UTC)
        )


# ------------------------------------------------------- cerrar la lista


def test_cerrar_la_lista_guarda_hasta_que_momento_de_ventas_considero(
    cliente, almacen, almacenamiento
):
    """La casilla del ticket, y lo que el ticket 09 va a leer mañana.

    El corte no se inventa al cerrar: es el que la lista trae desde que se
    armó, anclado en `max(fecha)` del almacén. Cerrar lo vuelve definitivo —y
    la respuesta lo dice, porque es el dato con el que el encargado sabe desde
    dónde va a acumular la siguiente.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]

    cuerpo = cliente.post(f"{RUTA}/{identificador}/cerrar").json()

    assert cuerpo["ok"] is True
    assert cuerpo["estado"] == CERRADO
    assert cuerpo["ventas_consideradas_hasta"] == "2024-03-05"
    assert cuerpo["cerrado_en"] is not None

    guardada = almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 5))
    assert guardada.estado == CERRADO
    assert guardada.cerrado_en is not None
    assert guardada.ventana.hasta == dt.date(2024, 3, 5)


def test_una_lista_cerrada_se_relee_cerrada_y_no_vuelve_a_armarse(cliente, almacen):
    """Cerrar no borra nada: la lista sigue ahí, con su estado y sus renglones."""
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["estado"] == CERRADO
    assert cuerpo["pedido_sugerido_id"] == identificador
    assert len(cuerpo["renglones"]) == 1


def test_cerrar_dos_veces_no_mueve_la_hora_del_cierre(cliente, almacen, almacenamiento):
    """El segundo clic no reescribe la historia.

    La transición vive en el `WHERE ... AND estado = 'abierto'` del `UPDATE`:
    la segunda vez no hay fila que tocar y la ruta lo dice en vez de fingir que
    cerró algo.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]

    primera = cliente.post(f"{RUTA}/{identificador}/cerrar").json()
    segunda = cliente.post(f"{RUTA}/{identificador}/cerrar")

    assert segunda.status_code == 409
    assert segunda.json()["ok"] is False
    assert (
        almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 5)).cerrado_en.isoformat()
        == primera["cerrado_en"]
    )


def test_el_cierre_firma_en_la_bitacora_quien_lo_hizo(cliente, almacen, caplog):
    """Una firma, no un permiso (regla 3 de CLAUDE.md).

    El ticket 08 no pide una columna con quién cerró —el 10 la va a pedir para
    quién descartó— así que hoy la firma va a la bitácora, que es donde ya vive
    todo lo que se quiere poder auditar sin inventar esquema.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]

    with caplog.at_level(logging.INFO, logger="continental"):
        cliente.post(
            f"{RUTA}/{identificador}/cerrar",
            headers={"Cf-Access-Authenticated-User-Email": "encargado@farmacia.mx"},
        )

    assert "encargado@farmacia.mx" in caplog.text


# ------------------------------------------------- vencer, anclado en el dato


def test_una_lista_de_un_dia_anterior_con_renglones_sin_atender_queda_vencida(
    cliente, almacen, almacenamiento
):
    """No `abierta` para siempre: el día pasó y nadie la cerró.

    El vencimiento ocurre **al abrir el día**, que es el único momento en que
    alguien mira. No hay lote ni reloj de pared que lo dispare: el disparador
    es que el almacén ya tiene datos de un día posterior.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 4), 1, 3)]
    ayer = cliente.get(RUTA).json()["pedido_sugerido_id"]

    almacen.ventas_en_memoria.append(_venta(dt.date(2024, 3, 5), 1, 2))
    hoy = cliente.get(RUTA).json()

    vieja = almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 4))
    assert vieja.pedido_sugerido_id == ayer
    assert vieja.estado == VENCIDO
    assert vieja.cerrado_en is None
    assert [r.estado for r in vieja.renglones] == [RENGLON_ABIERTO]
    assert hoy["estado"] == ABIERTO


def test_el_vencimiento_se_ancla_en_el_dato_y_nunca_en_el_reloj(
    cliente, almacen, almacenamiento
):
    """La trampa heredada, otra vez, y aquí muerde distinto.

    El último dato de este almacén es de 2024. Contra el reloj —o contra el
    `current_date` del Postgres del contenedor, que corre en UTC y puede ir dos
    días adelante— **toda** lista estaría vencida desde el primer segundo, y el
    encargado nunca podría trabajar una: se le vencería la del día mientras la
    tiene abierta.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]

    cliente.get(RUTA)
    cliente.get(RUTA)

    lista = almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 5))
    assert lista.estado == ABIERTO, (
        "La lista del último día con datos se venció sola: el vencimiento se "
        "está midiendo contra el reloj y no contra max(fecha) del almacén."
    )
    assert dt.date(2024, 3, 5) < dt.date.today()


def test_una_lista_cerrada_no_se_vence(almacenamiento):
    """Vencer es para lo que quedó abierto. Lo cerrado ya es un corte.

    Si una lista cerrada pasara a `vencida`, el ticket 09 perdería el corte
    desde el cual acumular y las ventas de ese día se contarían dos veces.
    """
    ventana = Ventana(dt.date(2024, 3, 4), dt.date(2024, 3, 4))
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, dt.date(2024, 3, 4), ventana, lambda: (_renglon(1, "PARACETAMOL"),)
    )
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id)

    assert almacenamiento.vencer_las_de_dias_anteriores(NEGOCIO, dt.date(2024, 3, 5)) == 0
    assert almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 4)).estado == CERRADO


def test_el_almacenamiento_no_saca_una_sola_fecha_del_reloj():
    """El cinturón sobre el código, no sobre el resultado.

    La prueba de comportamiento solo se pone roja si el reloj cambia el
    resultado; un `current_date` en una rama que hoy no se recorre pasaría en
    verde y mordería en atlas. `now()` sí aparece —`armado_en` y `cerrado_en`
    son instantes reales con zona, y eso no contradice anclarse en
    `max(fecha)`: esa regla es sobre fechas de venta—, pero una **fecha** no
    puede salir de ahí.

    Se miran **las sentencias**, no el archivo entero, y esa distinción es la
    que hace la prueba honesta: los comentarios nombran `current_date`
    justamente para explicar por qué no se usa, así que buscar la palabra en el
    texto castigaría la explicación en vez del defecto.
    """
    for nombre, sentencia in _sentencias().items():
        for prohibida in ("current_date", "now()::date", "localtimestamp", "today"):
            assert prohibida not in sentencia.lower(), (
                f"La sentencia {nombre} saca una fecha del reloj con "
                f"{prohibida!r}. El Postgres del contenedor corre en UTC y su "
                "current_date puede ir dos días adelante del último dato."
            )

    assert "date.today(" not in FUENTE.read_text(encoding="utf-8"), (
        "almacenamiento.py mira el reloj del proceso para sacar una fecha."
    )


# --------------------------------------------- cuándo se armó, y se ve


def test_la_lista_guarda_cuando_se_armo_y_la_respuesta_lo_dice(cliente, almacen):
    """`armado_en` es un instante real **con zona**, no una fecha.

    Distinto de `ventas_consideradas_hasta`, que dice de qué día son los datos.
    Con zona porque el contenedor corre en UTC: un `timestamp` pelón guardaría
    un reloj de pared que alguien en México lee seis horas en el futuro.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]

    cuerpo = cliente.get(RUTA).json()

    armado = dt.datetime.fromisoformat(cuerpo["armado_en"])
    assert armado.tzinfo is not None
    assert cuerpo["armado_en"] != cuerpo["ventas_consideradas_hasta"]


def test_la_pantalla_muestra_cuando_se_armo_y_deja_cerrar_la_lista(cliente):
    """Lo que el ticket pide que se vea, revisado sobre el HTML que se sirve.

    Es el mismo criterio del ticket 06: la pantalla es HTML+JS a mano y
    ninguna prueba de Python la ejecuta, así que lo que sí se puede afirmar es
    que los pedazos están —el instante del armado y el botón de cerrar— y que
    la fecha con hora **no** se arma con el constructor que ya costó una
    trampa de zona horaria del lado del cliente.
    """
    pagina = cliente.get("/").text

    assert "armado_en" in pagina
    assert "cerrar" in pagina
    assert "Cerrar la lista" in pagina
    assert "estado" in pagina


# --------------------------------------------- que el doble no mienta


def test_el_almacenamiento_real_y_el_doble_cumplen_la_misma_interfaz():
    """Un doble que se desvía de la interfaz real prueba otra cosa."""
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)
    assert isinstance(
        AlmacenamientoPostgres(fabrica_de_motor=None), AlmacenamientoDelPedido
    )


def test_el_doble_rechaza_los_renglones_que_el_ddl_rechaza(almacenamiento):
    """Uno por CHECK, porque cada uno esconde una falla distinta.

    - **Clave vacía**: el EAN es lo único que empareja con el catálogo de un
      proveedor, y una cadena vacía se compara igual que un dato — empareja con
      cualquier otra vacía. O hay EAN o no se sabe (`NULL`).
    - **Clasificación desconocida**: el CHECK solo conoce las tres de
      `clasificacion.py`.
    - **Cantidad negativa**: no se pide "menos tres".
    - **Dos renglones del mismo producto**: sería pedirlo dos veces.
    """
    ventana = Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5))

    with pytest.raises(ValueError):
        almacenamiento.insertar_la_lista(
            NEGOCIO,
            dt.date(2024, 3, 5),
            ventana,
            (_renglon(1, "X", clasificacion="vitaminas"),),
        )
    with pytest.raises(ValueError):
        almacenamiento.insertar_la_lista(
            NEGOCIO, dt.date(2024, 3, 6), ventana, (_renglon(1, "X", cantidad=-1),)
        )
    with pytest.raises(ValueError):
        almacenamiento.insertar_la_lista(
            NEGOCIO,
            dt.date(2024, 3, 7),
            ventana,
            (_renglon(1, "X"), _renglon(1, "X otra vez")),
        )


def test_una_clave_vacia_se_guarda_como_no_se_sabe_y_vuelve_vacia(almacenamiento):
    """El puente entre el `""` del cálculo y el `NULL` de la columna.

    `sugerido.Renglon.clave` vale `""` cuando el producto no está en el
    catálogo, y la columna tiene `CHECK (clave <> '')`. La traducción ocurre en
    un solo lugar —el que usan el SQL real y el doble— y es de ida y vuelta:
    lo que entra vacío sale vacío, sin inventar un EAN por el camino.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        dt.date(2024, 3, 5),
        Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5)),
        lambda: (_renglon(1, "Producto 1 — no está en el catálogo", en_catalogo=False),),
    )

    assert almacenamiento.listas[0]["renglones"][0]["clave"] is None
    assert lista.renglones[0].propuesto.clave == ""
    assert lista.renglones[0].propuesto.existencia is None


def test_el_doble_guarda_con_la_misma_escala_que_la_columna(almacenamiento):
    """`numeric(12,3)` redondea; un doble que guarde el float entero miente.

    El caso es real: `1.1 + 2.2 + 0.7` da `4.000000000000001` en coma flotante.
    Postgres lo guarda como `4.000` y lo devuelve así; si el doble devolviera
    `4.000000000000001`, una prueba de igualdad pasaría aquí y fallaría allá.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        dt.date(2024, 3, 5),
        Ventana(dt.date(2024, 3, 5), dt.date(2024, 3, 5)),
        lambda: (_renglon(1, "GRANEL", piezas=1.1 + 2.2 + 0.7),),
    )

    assert lista.renglones[0].propuesto.piezas_vendidas == 4.0


def test_el_orden_por_urgencia_se_guarda_y_se_relee_igual(cliente, almacen):
    """Lo que se guardó es lo que se ve, incluido el orden.

    El orden por urgencia se calcula **una vez**, al armar; los renglones se
    insertan en ese orden y se releen por `renglon_id`, que la secuencia
    entrega creciente. Volver a ordenar al leer sería recalcular por la puerta
    de atrás: un renglón que se llenó ayer subiría o bajaría solo.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", existencia=0),  # agotado: primero
        _producto(2, "7501000000002", existencia=90),  # de sobra: al final
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2024, 3, 5), 1, 3),
        _venta(dt.date(2024, 3, 5), 2, 1),
    ]

    primera = [r["producto_id"] for r in cliente.get(RUTA).json()["renglones"]]
    segunda = [r["producto_id"] for r in cliente.get(RUTA).json()["renglones"]]

    assert primera == [1, 2]
    assert segunda == primera


def test_el_sql_real_nunca_borra_una_fila():
    """El rol no tiene `DELETE` ni `TRUNCATE`: si el diseño los necesita, está mal.

    Cerrar una lista, vencerla y descartar un renglón son cambios de estado. Un
    `DELETE` aquí no fallaría en las pruebas —no hay base que lo rechace— y en
    atlas sería un "permission denied" a media operación.
    """
    for nombre, sentencia in _sentencias().items():
        for prohibida in ("delete", "truncate", "drop"):
            assert prohibida not in sentencia.lower(), (
                f"La sentencia {nombre} contiene {prohibida!r} y el rol "
                "`continental` no tiene ese permiso (ver sql/crear_rol.sql y "
                "el ADR 0003)."
            )


def test_el_almacenamiento_caido_es_un_hueco_con_motivo_y_sin_cadena_de_conexion(
    cliente, almacen, almacenamiento
):
    """Regla 4 y regla 5, las dos a la vez.

    Un almacenamiento caído no puede verse como "hoy no se vendió nada", y el
    motivo es el **tipo** de la falla y nunca su texto: un `str(exc)` de
    SQLAlchemy lleva la cadena de conexión con contraseña y esto corre detrás
    de un túnel.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 5), 1, 3)]
    almacenamiento.falla = RuntimeError(
        "connection to postgresql://continental:SECRETO@atlas:5432/farmacia failed"
    )

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "SECRETO" not in str(cuerpo)
    assert cuerpo["renglones"] == []


def test_el_almacenamiento_entra_por_depends_y_se_sustituye_en_pruebas(
    cliente, almacenamiento
):
    """La misma costura del ticket 01, sin `monkeypatch` y sin variables de entorno.

    Es lo que hace que este ticket se pueda construir entero sin un Postgres
    alcanzable: la implementación real existe, no se ejecuta aquí, y lo que las
    pruebas ejercitan es el doble que respeta sus mismas restricciones.
    """
    from continental.web.dependencias import obtener_almacenamiento
    from continental.web.app import app

    assert obtener_almacenamiento in app.dependency_overrides
    assert app.dependency_overrides[obtener_almacenamiento]() is almacenamiento


# ------------------------------------------------------------------ ayudas


def _sentencias() -> dict[str, str]:
    """Las sentencias SQL del módulo, por su nombre, como texto.

    Se leen del módulo ya importado y no del archivo: así lo que se revisa es
    **lo que se va a ejecutar**, sin que la prosa que explica por qué algo no
    se usa cuente como si se usara. Es lo más cerca que se puede llegar a
    correrlas sin un Postgres alcanzable.
    """
    import continental.almacenamiento as modulo

    return {
        nombre: valor.text
        for nombre, valor in vars(modulo).items()
        if isinstance(valor, sqlalchemy.sql.elements.TextClause)
    }


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(
    producto_id: int, clave: str, anaquel: str = "PATENTE 1", existencia: float = 10.0
) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel=anaquel,
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


def _renglon(
    producto_id: int,
    descripcion: str,
    clasificacion: str = "medicamento",
    cantidad: int = 3,
    piezas: float = 3.0,
    en_catalogo: bool = True,
) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave="7501000000001" if en_catalogo else "",
        descripcion=descripcion,
        piezas_vendidas=piezas,
        cantidad_propuesta=cantidad,
        esta_en_el_catalogo=en_catalogo,
        existencia=7.0 if en_catalogo else None,
        dias_de_cobertura=2.3 if en_catalogo else None,
        clasificacion=clasificacion,
    )
