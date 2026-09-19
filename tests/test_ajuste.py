"""Ajustar la cantidad de un renglón: lo que propuso el sistema y lo que se pide.

El ticket 11 tiene una sola idea de fondo y conviene decirla antes de leer
nada: **las dos cantidades se guardan por separado y la propuesta jamás se
sobreescribe.** El encargado sabe cosas que el sistema no —que mañana es
puente, que un cliente viene por una caja entera— y corrige; la diferencia
entre lo que se propuso y lo que se pidió es lo único que después va a decir si
la reposición 1 a 1 está bien calibrada. Si al corregir se pisara
`cantidad_propuesta`, esa diferencia sería cero siempre y el dato se perdería
sin que nadie lo notara, que es exactamente la falla silenciosa que la regla 4
de `CLAUDE.md` prohíbe.

**Ninguna prueba toca Postgres**, igual que el resto del suite: lo que se
ejercita es el doble en memoria, y el doble no puede ser más permisivo que la
tabla. Por eso las reglas nuevas —la cantidad final de al menos uno, la firma
pareada con la cantidad— viven en `revisar_el_renglon`, que llaman las dos
implementaciones, y aquí se comprueba que el DDL diga lo mismo.

Lo que este archivo **no** puede hacer es ejecutar el SQL: desde la torre no
hay Postgres alcanzable (verificado el 2026-09-19). Lo que sí hace es revisar
las sentencias como texto —que la lista abierta esté en el `WHERE` y no en un
`if`, y que el `UPDATE` no nombre `cantidad_propuesta`— y leer los dos archivos
de SQL, el de la base desde cero y el de la que ya existe.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

import pytest
import sqlalchemy

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    Ventana,
)
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
MIGRACION = SQL / "migraciones" / "0002-renglon-cantidad-final-y-quien-la-ajusto.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

CORREO = "encargado@farmacia.mx"


def _ajustar(cliente, renglon_id: int, cantidad, correo: str | None = CORREO):
    """El cambio de cantidad. Lleva cuerpo: es el único dato que el ticket recibe."""
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(
        f"/api/renglon/{renglon_id}/cantidad",
        json={"cantidad": cantidad},
        headers=cabeceras,
    )


# ------------------------ casilla 1: se cambia con la lista abierta


def test_se_puede_cambiar_la_cantidad_con_la_lista_abierta(
    cliente, almacen, almacenamiento
):
    """La casilla 1 en su forma más directa: una petición, otra cantidad a pedir.

    Es la razón de ser del ticket: el sistema propone 3 porque se vendieron 3, y
    el encargado sabe que mañana es puente y pide 10.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]

    respuesta = _ajustar(cliente, renglon_id, 10)

    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True
    assert respuesta.json()["renglon"]["cantidad_a_pedir"] == 10

    guardado = _renglon_guardado(almacenamiento, renglon_id)
    assert guardado.cantidad_final == 10
    assert guardado.cantidad_a_pedir == 10


def test_con_la_lista_cerrada_la_cantidad_ya_no_se_cambia(
    cliente, almacen, almacenamiento
):
    """"Mientras la lista esté `abierta`" es literal, y es lo que el ticket pide.

    Una lista cerrada quiere decir "ya se pidió lo que se iba a pedir"
    (`CONTEXT.md`): cambiar ahí una cantidad la separaría de lo que de verdad se
    le pidió al proveedor, y el renglón dejaría de servir para recibir la
    mercancía contra él (ticket 26).

    La condición vive en el `WHERE` del `UPDATE`, con la lista adentro, y no en
    un `if` de Python: comprobar el estado y actualizar después tiene una
    carrera en medio —dos pestañas, una cierra y la otra corrige—.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    respuesta = _ajustar(cliente, renglon_id, 10)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False
    assert _renglon_guardado(almacenamiento, renglon_id).cantidad_final is None


def test_con_la_lista_vencida_la_cantidad_tampoco_se_cambia(
    cliente, almacen, almacenamiento
):
    """`vencido` es el otro estado que no es `abierto`, y cuenta igual.

    Una lista vencida pasó su día y nadie la cerró: lo que quede ahí ya no se va
    a pedir con esas cantidades. El `WHERE` dice `estado = 'abierto'`, así que
    los dos casos caen solos y no hay una lista de estados prohibidos que se
    quede vieja el día que aparezca un cuarto.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 4), 1, 2)]
    ayer = cliente.get(RUTA).json()
    renglon_id = ayer["renglones"][0]["renglon_id"]

    # Cargar el día siguiente es lo que vence la lista de ayer.
    almacen.ventas_en_memoria.append(_venta(HOY, 1, 3))
    cliente.get(RUTA)
    assert almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 4)).estado == "vencido"

    assert _ajustar(cliente, renglon_id, 9).status_code == 409
    assert _renglon_guardado(almacenamiento, renglon_id).cantidad_final is None


def test_un_renglon_descartado_no_cambia_de_cantidad(cliente, almacen, almacenamiento):
    """Descartado es "no se pide": ponerle cantidad sería decir dos cosas a la vez.

    Para volver a pedirlo está `/devolver`, que lo regresa a `abierto`. La
    transición vive en el `WHERE ... AND estado = 'abierto'` del renglón, la
    misma que usa el descarte.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/descartar")

    assert _ajustar(cliente, renglon_id, 10).status_code == 409
    assert _renglon_guardado(almacenamiento, renglon_id).cantidad_final is None


@pytest.mark.parametrize("estado", ["en tránsito", "recibido", "recibido parcial"])
def test_un_renglon_que_no_esta_abierto_no_cambia_de_cantidad(almacenamiento, estado):
    """Esos estados los escriben los tickets 24 y 26; la transición vale desde hoy.

    `en tránsito` ya se le pidió a un proveedor: cambiarle la cantidad aquí haría
    que el renglón dijera una cifra y el proveedor tuviera otra, y el ticket 26
    recibiría mercancía contra un número que nadie pidió. `recibido` y `recibido
    parcial` son hechos consumados.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id
    almacenamiento.poner_estado_del_renglon(renglon_id, estado)

    assert almacenamiento.ajustar_la_cantidad(NEGOCIO, renglon_id, 9, CORREO) is None
    assert almacenamiento.leer(NEGOCIO, HOY).renglones[0].cantidad_final is None


def test_un_renglon_de_otro_negocio_no_cambia_de_cantidad(almacenamiento):
    """Regla 7 de `CLAUDE.md`: el `negocio` va en el `WHERE`, no solo en la fila.

    Hoy hay una farmacia y esto no se puede ver en la pantalla. Se prueba igual:
    es lo único que se paga hoy para no reescribir el módulo el día que haya dos.
    """
    lista = almacenamiento.abrir_el_dia(
        "farmacia_02", HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id

    assert almacenamiento.ajustar_la_cantidad(NEGOCIO, renglon_id, 9, CORREO) is None
    assert almacenamiento.leer("farmacia_02", HOY).renglones[0].cantidad_final is None


def test_ajustar_un_renglon_que_no_existe_contesta_409(cliente, almacen):
    """Mismo 409 que el descarte, y a propósito: desde fuera no se distingue "no
    existe" de "no estaba abierto", y decirlo sería contar qué ids hay en la
    tabla."""
    _poblar(almacen)

    assert _ajustar(cliente, 99999, 5).status_code == 409


# ------------------- casilla 2: propuesta y final, por separado


def test_la_cantidad_propuesta_no_se_sobreescribe_nunca(
    cliente, almacen, almacenamiento
):
    """La mitad del valor del ticket, y la que es fácil de perder.

    Si ajustar pisara `cantidad_propuesta`, la pantalla se vería idéntica y la
    diferencia entre lo que el sistema propuso y lo que se pidió valdría cero
    para siempre — sin un solo error que ver. Esa diferencia es lo que después
    dice si la reposición 1 a 1 está bien calibrada.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    antes = lista["renglones"][0]
    assert antes["cantidad_propuesta"] == 3

    despues = _ajustar(cliente, antes["renglon_id"], 10).json()["renglon"]

    assert despues["cantidad_propuesta"] == 3, (
        "Ajustar pisó la cantidad propuesta por el sistema. La diferencia entre "
        "las dos es lo único que calibra la reposición 1 a 1."
    )
    assert despues["cantidad_final"] == 10
    guardado = _renglon_guardado(almacenamiento, antes["renglon_id"])
    assert guardado.propuesto.cantidad_propuesta == 3
    assert guardado.cantidad_final == 10


def test_sin_ajuste_la_cantidad_final_es_nula_y_se_pide_la_propuesta(
    cliente, almacen, almacenamiento
):
    """`NULL` es "nadie la tocó", y por eso no se copia la propuesta al nacer.

    Nacer con `cantidad_final = cantidad_propuesta` habría hecho indistinguibles
    dos hechos distintos: un renglón que nadie miró y uno que alguien revisó y
    dejó igual. El segundo es evidencia de que la propuesta era correcta; el
    primero no dice nada. Lo que se pide sale de `cantidad_a_pedir`, que es la
    regla escrita una sola vez en Python y no repetida en el JavaScript.
    """
    _poblar(almacen)
    renglon = cliente.get(RUTA).json()["renglones"][0]

    assert renglon["cantidad_final"] is None
    assert renglon["cantidad_a_pedir"] == renglon["cantidad_propuesta"]
    assert renglon["fue_ajustada"] is False

    guardado = _renglon_guardado(almacenamiento, renglon["renglon_id"])
    assert guardado.cantidad_final is None
    assert guardado.cantidad_a_pedir == 3
    assert almacenamiento.listas[0]["renglones"][0]["cantidad_final"] is None


def test_confirmar_la_misma_cantidad_queda_registrado(cliente, almacen, almacenamiento):
    """Y no se confunde con "nadie la tocó": eso es lo que `NULL` compra.

    Alguien que mira la propuesta y decide que está bien está diciendo algo
    sobre la reposición 1 a 1 — que acertó—. Ese renglón se distingue del que
    nadie revisó, aunque las dos cantidades valgan lo mismo.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    respuesta = _ajustar(cliente, renglon_id, 3).json()["renglon"]

    assert respuesta["cantidad_final"] == 3
    assert respuesta["fue_ajustada"] is True
    assert respuesta["difiere_de_la_propuesta"] is False
    assert _renglon_guardado(almacenamiento, renglon_id).ajustada_por == CORREO


def test_la_pantalla_recibe_las_dos_cantidades_cuando_difieren(cliente, almacen):
    """Lo que el ticket pide que se vea: la propuesta **y** la final.

    Las dos viajan siempre; quién decide si se muestran las dos es
    `difiere_de_la_propuesta`, calculado en Python —donde hay pruebas— y no en
    el JavaScript.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    _ajustar(cliente, renglon_id, 10)

    renglon = next(
        r for r in cliente.get(RUTA).json()["renglones"] if r["renglon_id"] == renglon_id
    )

    assert renglon["cantidad_propuesta"] == 3
    assert renglon["cantidad_final"] == 10
    assert renglon["cantidad_a_pedir"] == 10
    assert renglon["difiere_de_la_propuesta"] is True


def test_ajustar_dos_veces_deja_la_ultima_y_la_propuesta_intacta(
    cliente, almacen, almacenamiento
):
    """Corregir una corrección es corriente: el encargado se equivoca al teclear.

    No se guarda el historial de cada cambio —sería otra tabla y otro ticket—:
    se guarda la última, que es la que se va a pedir, junto con quién la dejó
    así. La propuesta del sistema sigue sin moverse en las dos.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    _ajustar(cliente, renglon_id, 10)
    _ajustar(cliente, renglon_id, 4, correo="otro@farmacia.mx")

    guardado = _renglon_guardado(almacenamiento, renglon_id)
    assert guardado.cantidad_final == 4
    assert guardado.ajustada_por == "otro@farmacia.mx"
    assert guardado.propuesto.cantidad_propuesta == 3


def test_descartar_un_renglon_ajustado_no_borra_su_cantidad(
    cliente, almacen, almacenamiento
):
    """Son dos hechos distintos y se guardan aparte.

    Alguien corrigió la cantidad y después decidió no pedirlo: las dos cosas
    pasaron, y la corrección sigue siendo evidencia de que la propuesta no era
    la buena. Devolverlo a `abierto` lo deja con la cantidad que tenía.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    _ajustar(cliente, renglon_id, 10)

    cliente.post(f"/api/renglon/{renglon_id}/descartar")
    descartado = _renglon_guardado(almacenamiento, renglon_id)
    cliente.post(f"/api/renglon/{renglon_id}/devolver")
    vuelto = _renglon_guardado(almacenamiento, renglon_id)

    assert descartado.estado == RENGLON_DESCARTADO
    assert descartado.cantidad_final == 10
    assert vuelto.estado == RENGLON_ABIERTO
    assert vuelto.cantidad_final == 10


# ------------------- casilla 3: un cero no es una forma de descartar


def test_una_cantidad_de_cero_se_rechaza_y_el_renglon_no_se_descarta(
    cliente, almacen, almacenamiento
):
    """La casilla 3. Y el mensaje dice cuál es el camino, porque existe.

    Un cero guardado sería un renglón que dice "pídeme cero piezas": ni pedido
    ni descartado, invisible para el conteo del ADR 0002 y sin nadie detrás.
    `descartado` es el estado del glosario para "una persona decidió no
    pedirlo", con su firma y su hora.
    """
    _poblar(almacen)
    renglon = cliente.get(RUTA).json()["renglones"][0]

    respuesta = _ajustar(cliente, renglon["renglon_id"], 0)

    assert respuesta.status_code == 422
    assert respuesta.json()["ok"] is False
    assert "descarta" in respuesta.json()["detalle"].lower(), (
        "El rechazo no dice cuál es la manera correcta de no pedir un renglón."
    )
    guardado = _renglon_guardado(almacenamiento, renglon["renglon_id"])
    assert guardado.estado == RENGLON_ABIERTO
    assert guardado.cantidad_final is None


def test_una_cantidad_negativa_se_rechaza_igual(cliente, almacen):
    """Por debajo de cero no es una cantidad de nada: mismo camino, mismo 422."""
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    assert _ajustar(cliente, renglon_id, -3).status_code == 422


def test_despues_del_cero_descartar_sigue_siendo_el_camino(cliente, almacen):
    """El rechazo no deja al encargado sin salida: le dice la que sí es.

    Es la prueba de que las dos mitades de la casilla 3 encajan — el cero no
    descarta, **y** descartar está ahí para eso—.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    _ajustar(cliente, renglon_id, 0)

    respuesta = cliente.post(f"/api/renglon/{renglon_id}/descartar")

    assert respuesta.status_code == 200
    assert respuesta.json()["renglon"]["estado"] == RENGLON_DESCARTADO


def test_el_doble_rechaza_una_cantidad_final_de_cero(almacenamiento):
    """`ck_renglon_cantidad_final`, escrito en Python.

    El cinturón de en medio: aunque alguien llame al almacenamiento sin pasar
    por la ruta, el doble se niega igual que la tabla. Un doble que aceptara el
    cero dejaría el suite en verde y el `UPDATE` rebotaría en atlas con una
    violación de restricción.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )

    with pytest.raises(ValueError):
        almacenamiento.ajustar_la_cantidad(
            NEGOCIO, lista.renglones[0].renglon_id, 0, CORREO
        )


def test_el_ddl_exige_que_la_cantidad_final_sea_al_menos_una_pieza():
    """Y el CHECK es la garantía de verdad: no depende de qué código escriba.

    Las otras dos comprobaciones —la ruta y el validador compartido— son las que
    explican; ésta es la que **impide**. El día que alguien escriba en la tabla
    desde un `psql` o desde un script nuevo, es la única que sigue puesta.
    """
    cuerpo = _cuerpo_del_renglon()
    assert "CONSTRAINT ck_renglon_cantidad_final" in cuerpo
    assert "cantidad_final >= 1" in cuerpo, (
        "El CHECK de la cantidad final no exige al menos una pieza: un cero "
        "sería un descarte encubierto, sin firma y sin estado."
    )


# ----------------------------- casilla 4: quién la cambió, y cuándo


def test_queda_guardado_quien_cambio_la_cantidad(cliente, almacen, almacenamiento):
    """La casilla 4. Una FIRMA, no un permiso (regla 3 de `CLAUDE.md`).

    El correo llega en `Cf-Access-Authenticated-User-Email`, ya validado por
    Cloudflare Access. Nada de este código lo trata como prueba de
    autorización: sirve para saber a quién preguntarle por qué se pidieron diez
    de algo de lo que se vendieron tres.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    _ajustar(cliente, renglon_id, 10)

    assert _renglon_guardado(almacenamiento, renglon_id).ajustada_por == CORREO


def test_sin_encabezado_la_firma_del_ajuste_es_sin_identificar(
    cliente, almacen, almacenamiento
):
    """Hoy en la torre, sin el túnel delante, vale `sin-identificar`.

    Y está bien: dice que no se supo, que es un dato honesto. Lo que no puede
    pasar es que no se guarde nada — un `NULL` ahí dejaría una cantidad
    corregida sin nadie detrás, y `ck_renglon_ajuste` lo rechaza.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    _ajustar(cliente, renglon_id, 10, correo=None)

    assert _renglon_guardado(almacenamiento, renglon_id).ajustada_por == "sin-identificar"


def test_queda_guardado_cuando_se_cambio_como_instante_con_zona(cliente, almacen):
    """El cuándo va con el quién, igual que en el descarte.

    Sin él, "quién la cambió" no se puede ordenar en el tiempo: con dos
    correcciones seguidas no habría forma de saber cuál quedó, y la comparación
    entre lo propuesto y lo pedido no se podría acotar a un periodo.

    Con zona porque el contenedor corre en UTC: un instante sin zona es un reloj
    de pared que alguien en México lee seis horas en el futuro.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    cuando = _ajustar(cliente, renglon_id, 10).json()["renglon"]["ajustada_en"]

    assert dt.datetime.fromisoformat(cuando).tzinfo is not None


def test_la_firma_y_la_cantidad_van_tambien_a_la_bitacora(cliente, almacen, caplog):
    """La columna es para consultar; la bitácora es para reconstruir el día.

    La cantidad va en la línea a propósito: la columna guarda la última, y la
    bitácora es lo único que deja ver que alguien puso 100 y lo corrigió a 10.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    with caplog.at_level(logging.INFO, logger="continental"):
        _ajustar(cliente, renglon_id, 10)

    assert CORREO in caplog.text
    assert "10" in caplog.text


def test_el_doble_rechaza_una_cantidad_sin_firma_y_una_firma_sin_cantidad(
    almacenamiento,
):
    """`ck_renglon_ajuste`, tal cual, escrito en Python: las dos mitades.

    Sin la de ida, una cantidad corregida podría quedar sin decir quién ni
    cuándo. Sin la de vuelta, una firma podría quedar colgada en un renglón que
    nadie tocó y diría que alguien corrigió lo que no.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id

    with pytest.raises(ValueError):
        almacenamiento.poner_la_cantidad(renglon_id, 10)
    with pytest.raises(ValueError):
        almacenamiento.poner_la_cantidad(
            renglon_id, None, ajustada_por=CORREO, ajustada_en=dt.datetime.now(dt.UTC)
        )


def test_el_doble_rechaza_una_firma_de_ajuste_vacia(almacenamiento):
    """`ck_renglon_ajustada_por`: o hay firma o es `NULL`, igual que la clave.

    Una cadena vacía se compara igual que un dato y empareja con cualquier otra
    vacía. `quien()` nunca devuelve `''` —sin encabezado devuelve
    `sin-identificar`— así que esto es el cinturón.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )

    with pytest.raises(ValueError):
        almacenamiento.ajustar_la_cantidad(NEGOCIO, lista.renglones[0].renglon_id, 5, "")


def test_el_almacenamiento_caido_al_ajustar_es_un_hueco_con_motivo(
    cliente, almacen, almacenamiento
):
    """Regla 4 y regla 5, las dos a la vez.

    El motivo es el **tipo** de la falla y nunca su texto: un `str(exc)` de
    SQLAlchemy lleva la cadena de conexión con contraseña y esto corre detrás de
    un túnel.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    almacenamiento.falla = RuntimeError(
        "connection to postgresql://continental:SECRETO@atlas:5432/farmacia failed"
    )

    cuerpo = _ajustar(cliente, renglon_id, 10).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "SECRETO" not in str(cuerpo)


# ------------------------------------------- el SQL, revisado como texto


def test_el_ajuste_es_un_update_y_la_lista_abierta_esta_en_el_where():
    """Las dos transiciones en el `WHERE`: el renglón abierto y **su lista**.

    Es lo que distingue a este ticket del 10. Descartar mira solo el renglón;
    aquí el ticket pide explícitamente que la lista esté `abierta`, y esa
    condición tiene que viajar en la misma sentencia: leer el estado de la lista
    en Python y actualizar después tiene una carrera en medio —una pestaña
    cierra mientras otra corrige— y dejaría una cantidad nueva en una lista que
    ya se pidió.
    """
    ajuste = _sentencia_del_ajuste()

    assert ajuste.lower().lstrip().startswith("update")
    assert "estado = 'abierto'" in ajuste.lower()
    assert "pedido_sugerido" in ajuste.lower(), (
        "El UPDATE del ajuste no nombra la tabla de la lista: la condición de "
        "que esté abierta no puede estar en el WHERE."
    )
    assert ajuste.lower().count("estado = 'abierto'") == 2, (
        "Falta una de las dos condiciones: el renglón abierto y su lista abierta."
    )


def test_el_sql_del_ajuste_no_toca_la_cantidad_propuesta():
    """La inmutabilidad, comprobada sobre lo que se va a ejecutar.

    `cantidad_propuesta` se escribe una vez, en el `INSERT` que arma la lista, y
    ninguna otra sentencia la nombra en un `SET`. Es la mitad del valor del
    ticket y la más fácil de romper sin que se vea.
    """
    ajuste = _sentencia_del_ajuste()
    asignaciones = ajuste.lower().split("where")[0]

    assert "cantidad_propuesta" not in asignaciones, (
        "El UPDATE del ajuste escribe `cantidad_propuesta`. Esa columna es "
        "inmutable: la diferencia contra la final es lo que calibra la "
        "reposición 1 a 1."
    )
    assert "cantidad_final" in asignaciones


def test_la_hora_del_ajuste_la_pone_el_servidor_que_guarda_la_fila():
    """`now()` y no una hora calculada en Python.

    Dos procesos con relojes distintos escribirían ajustes incomparables, y no
    habría forma de saber cuál corrección quedó al final.
    """
    assert "now()" in _sentencia_del_ajuste().lower()


def test_ninguna_sentencia_del_modulo_borra_filas():
    """El rol no tiene `DELETE`, y este ticket no es la excepción.

    Corregir una cantidad es un `UPDATE`; poner cero y borrar el renglón habría
    sido la otra manera de leer el ticket, y es la que el ADR 0003 prohíbe.
    """
    for nombre, sentencia in _sentencias().items():
        assert "delete" not in sentencia.lower(), f"{nombre} borra filas."


# ------------------------------------------------------------ el DDL nuevo


def _cuerpo_del_renglon() -> str:
    sql = CREAR_TABLAS.read_bytes().decode("utf-8")
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.renglon (")
    return sql[inicio : sql.index("\n);", inicio)]


def test_la_tabla_guarda_las_dos_cantidades_por_separado():
    """La casilla 2 del lado del esquema: dos columnas, no una.

    `cantidad_propuesta` es `NOT NULL` —toda lista propone algo— y
    `cantidad_final` admite nulos, que es como se dice "nadie la tocó". Guardar
    una sola columna habría sido la decisión cómoda y la que borra el dato.
    """
    cuerpo = _cuerpo_del_renglon()
    propuesta = re.search(r"^\s*cantidad_propuesta\s+(\w+)(.*)$", cuerpo, re.MULTILINE)
    final = re.search(r"^\s*cantidad_final\s+(\w+)(.*)$", cuerpo, re.MULTILINE)

    assert propuesta and propuesta.group(1) == "integer"
    assert "NOT NULL" in propuesta.group(2)
    assert final, "`pedidos.renglon` no tiene columna `cantidad_final`."
    assert final.group(1) == "integer"
    assert "NOT NULL" not in final.group(2), (
        "cantidad_final es NOT NULL: entonces no hay forma de distinguir un "
        "renglón que nadie revisó de uno que alguien confirmó igual."
    )
    assert "DEFAULT" not in final.group(2), (
        "cantidad_final tiene DEFAULT: copiar la propuesta al nacer borra "
        "justamente la diferencia que el ticket existe para guardar."
    )


@pytest.mark.parametrize(
    ("columna", "tipo"), [("ajustada_por", "text"), ("ajustada_en", "timestamptz")]
)
def test_la_tabla_guarda_quien_cambio_la_cantidad_y_cuando(columna: str, tipo: str):
    """La casilla 4 del lado del esquema, con el mismo criterio del descarte.

    `timestamptz` y no `date`: es un INSTANTE que ocurrió aquí, igual que
    `armado_en`, `cerrado_en` y `descartado_en`, y eso no contradice anclarse en
    `max(fecha)` —esa regla es sobre fechas de venta—.
    """
    columnas = re.search(
        rf"^\s*{columna}\s+(\w+)(.*)$", _cuerpo_del_renglon(), re.MULTILINE
    )
    assert columnas, f"`pedidos.renglon` no tiene columna `{columna}`."
    assert columnas.group(1) == tipo
    assert "NOT NULL" not in columnas.group(2), (
        f"{columna} es NOT NULL: la mayoría de los renglones no se corrigen y "
        "no tienen qué poner ahí."
    )


def test_el_ddl_exige_cantidad_final_si_y_solo_si_hay_firma_y_hora():
    """`ck_renglon_ajuste`, el par que hace honesta a la columna.

    Es el mismo patrón de `ck_renglon_descarte` y de `ck_pedido_sugerido_cierre`:
    el dato y su firma se escriben juntos o no se escriben.
    """
    cuerpo = _cuerpo_del_renglon()
    assert "CONSTRAINT ck_renglon_ajuste" in cuerpo
    assert "ajustada_por IS NOT NULL AND ajustada_en IS NOT NULL" in cuerpo


def test_la_firma_del_ajuste_no_puede_ser_una_cadena_vacia():
    """`ck_renglon_ajustada_por`, igual que `ck_renglon_descartado_por`."""
    assert "CONSTRAINT ck_renglon_ajustada_por" in _cuerpo_del_renglon()


# -------------------------------------------------------- la migración 0002


def _sentencias_de_la_migracion() -> str:
    """Las sentencias y no el archivo entero.

    Por la misma razón que en `test_descarte.py`: la cabecera nombra `CREATE
    TABLE IF NOT EXISTS` justamente para explicar por qué no alcanza, y buscar
    la palabra en la prosa castigaría la explicación en vez del defecto.
    """
    texto = MIGRACION.read_bytes().decode("utf-8")
    return "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("--")
    )


def test_hay_una_migracion_para_la_base_que_ya_tiene_la_tabla():
    """La convención del repo: una columna nueva se escribe en DOS archivos.

    `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS`, que **calla si la tabla
    ya existe con otra forma**: sobre la base de atlas volver a correrlo no
    agrega nada y no avisa, y el primer `UPDATE ... SET cantidad_final = ...`
    rebotaría con "column does not exist" después de que aquí todo se viera
    verde. Y al revés, dejar la columna solo en la migración haría que una base
    desde cero naciera sin ella. La regla vive en las Consecuencias del ADR
    0003.
    """
    assert MIGRACION.exists(), (
        "Falta sql/migraciones/0002-*. Ver las Consecuencias del ADR 0003."
    )
    sentencias = _sentencias_de_la_migracion()

    assert "ALTER TABLE pedidos.renglon" in sentencias
    assert "CREATE TABLE" not in sentencias, (
        "La migración crea tablas: eso es trabajo de sql/crear_tablas.sql."
    )
    for columna in ("cantidad_final", "ajustada_por", "ajustada_en"):
        assert f"ADD COLUMN IF NOT EXISTS {columna}" in sentencias, (
            f"La migración no agrega `{columna}`, o no es idempotente."
        )
    # `ADD CONSTRAINT` no tiene IF NOT EXISTS en Postgres: la idempotencia se
    # consigue quitándolo primero.
    for restriccion in (
        "ck_renglon_cantidad_final",
        "ck_renglon_ajustada_por",
        "ck_renglon_ajuste",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {restriccion}" in sentencias
        assert f"ADD CONSTRAINT {restriccion}" in sentencias
    for prohibida in ("DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN"):
        assert prohibida not in sentencias.upper(), (
            f"La migración contiene {prohibida}: agregar una columna no borra nada."
        )


def test_la_migracion_se_corre_a_mano_desde_la_ruta_de_atlas():
    """La cabecera tiene que decir cómo correrla, y desde dónde.

    `~/proyectos/Continental`, **plano**: en atlas los repos son hermanos, al
    revés que en la torre. Una cabecera con la ruta de la torre manda a alguien
    a un directorio que allá no existe, con credenciales de dueño en la mano.

    Y la guardia contra el rol acotado: con `continental` esto fallaría por
    permisos, pero el mensaje de Postgres no diría cuál es la manera correcta.
    """
    texto = MIGRACION.read_bytes().decode("utf-8")

    assert "~/proyectos/Continental" in texto
    assert "docker exec -i farmacia_warehouse psql" in texto
    assert "ON_ERROR_STOP=1" in texto
    assert "current_user = 'continental'" in texto, (
        "La migración no se niega a correr con el rol acotado."
    )


def test_la_migracion_no_la_corre_el_codigo_de_arranque():
    """ADR 0003: el DDL se corre a mano, con credenciales de dueño.

    Si el arranque aplicara migraciones, el rol `continental` necesitaría
    `ALTER` sobre sus tablas — y con `ALTER` puede quitar un CHECK, que es la
    mitad de las garantías de este esquema. Se repite del ticket 10 a propósito:
    es la clase de regla que se rompe agregando la segunda migración.
    """
    fuentes = [RAIZ / "iniciar.py"] + sorted((RAIZ / "src").rglob("*.py"))
    for ruta in fuentes:
        assert "migraciones" not in ruta.read_text(encoding="utf-8"), (
            f"{ruta.name} nombra `migraciones`: el DDL no lo corre el código."
        )


# ------------------------------------------------------------ la pantalla


def test_la_pantalla_deja_cambiar_la_cantidad_con_la_lista_abierta(cliente):
    """Lo que el ticket pide, revisado sobre el HTML que se sirve.

    Ninguna prueba de Python ejecuta este JavaScript; lo que sí se puede
    afirmar es que los pedazos están: el campo de número con su mínimo de una
    pieza y la ruta a la que escribe.
    """
    pagina = cliente.get("/").text

    assert "/cantidad" in pagina
    assert "type = 'number'" in pagina or "type=\"number\"" in pagina
    assert "min = '1'" in pagina or 'min="1"' in pagina, (
        "El campo no tiene mínimo de una pieza: el cero llegaría al servidor en "
        "el camino más común, que es teclear."
    )


def test_la_pantalla_no_deja_cambiar_la_cantidad_si_la_lista_no_esta_abierta(cliente):
    """Con la lista cerrada o vencida el número se ve y no se edita.

    El servidor lo vuelve a comprobar en el `WHERE` de su `UPDATE`: esconder el
    campo es comodidad, no la garantía. Pero una pantalla que deja teclear algo
    que el servidor va a rechazar enseña a ignorar los avisos.
    """
    pagina = cliente.get("/").text

    assert "editable" in pagina
    assert "estado === 'abierto'" in pagina


def test_la_pantalla_dice_que_el_cero_no_descarta(cliente):
    """El camino correcto se dice donde se comete el error, no solo en el 422."""
    pagina = cliente.get("/").text

    assert "Descartar" in pagina
    assert re.search(r"cero.{0,120}[Dd]escarta", pagina, re.S), (
        "La pantalla no explica que para no pedir un renglón está Descartar."
    )


def test_la_pantalla_muestra_la_propuesta_cuando_la_cantidad_se_cambio(cliente):
    """"La pantalla muestra propuesta y final cuando difieren", del ticket.

    La decisión de si difieren viene del servidor (`difiere_de_la_propuesta`);
    aquí solo se comprueba que el HTML la use y tenga dónde pintarla.
    """
    pagina = cliente.get("/").text

    assert "difiere_de_la_propuesta" in pagina
    assert "propuso" in pagina
    assert "ajustada_por" in pagina


# ------------------------------------------------------------------ ayudas


def _sentencias() -> dict[str, str]:
    """Las sentencias SQL del módulo, por su nombre, como texto.

    Se leen del módulo ya importado y no del archivo: así lo que se revisa es
    **lo que se va a ejecutar**, sin que la prosa que explica por qué algo no se
    usa cuente como si se usara.
    """
    import continental.almacenamiento as modulo

    return {
        nombre: valor.text
        for nombre, valor in vars(modulo).items()
        if isinstance(valor, sqlalchemy.sql.elements.TextClause)
    }


def _sentencia_del_ajuste() -> str:
    return next(s for n, s in _sentencias().items() if "AJUSTAR" in n)


def _renglon_guardado(almacenamiento, renglon_id: int):
    """El renglón tal como quedó en la tabla, buscado por su id."""
    for lista in almacenamiento.listas:
        guardada = almacenamiento.leer(lista["negocio"], lista["fecha_del_pedido"])
        for renglon in guardada.renglones:
            if renglon.renglon_id == renglon_id:
                return renglon
    raise AssertionError(f"No hay ningún renglón {renglon_id} guardado.")


def _poblar(almacen) -> None:
    """Dos productos vendidos el mismo día: uno agotado y uno con anaquel lleno.

    El primero propone 3 piezas, que es el número que estas pruebas corrigen.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", existencia=0),
        _producto(2, "7501000000002", existencia=90),
    ]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3), _venta(HOY, 2, 1)]


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


def _renglon(producto_id: int, descripcion: str) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave="7501000000001",
        descripcion=descripcion,
        piezas_vendidas=3.0,
        cantidad_propuesta=3,
        esta_en_el_catalogo=True,
        existencia=7.0,
        dias_de_cobertura=2.3,
        clasificacion="medicamento",
    )
