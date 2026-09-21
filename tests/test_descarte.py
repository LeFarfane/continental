"""Descartar un renglón: un clic, reversible, contado y firmado (ticket 10).

**Ninguna prueba toca Postgres**, igual que el resto del suite: el doble en
memoria es lo que se ejercita, y no puede ser más permisivo que la tabla. La
regla que dejó el ticket 08 se respeta aquí: las validaciones viven una sola
vez en `almacenamiento.py` —`revisar_el_renglon`, `columnas_del_renglon`— y las
llaman las dos implementaciones. Por eso el `CHECK` nuevo de este ticket
(`ck_renglon_descarte`: descartado si y solo si hay firma Y hora) se prueba
contra el doble, y `test_sql_del_pedido.py` más lo de aquí abajo comprueban que
el DDL diga lo mismo.

Lo que este archivo **no** puede hacer es ejecutar el SQL: desde la torre no
hay Postgres alcanzable (Docker Desktop apagado, nada en el 5432, verificado
el 2026-09-19). Lo que sí hace, como en `test_guardado.py`, es revisar las
sentencias como texto: que descartar sea un `UPDATE` con la transición en el
`WHERE` y nunca un `DELETE` —el rol no lo tiene—, y que la hora salga de
`now()` del servidor.

**La casilla de "quién descartó" no es un adorno.** Es la evidencia con la que
se evalúa la condición de revisión del ADR 0002: "si después de un mes de uso
los renglones descartados superan a los pedidos, la reposición 1 a 1 no es la
regla correcta". Sin `descartado_en` esa condición no se puede acotar a un mes
aunque se cumpla, y sin limpiar la firma al devolver a `abierto` el mismo
conteo sumaría renglones que ya nadie descartó.
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
    ESTADOS_DEL_RENGLON,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    Ventana,
)
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
MIGRACION = SQL / "migraciones" / "0001-renglon-quien-descarto-y-cuando.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

CORREO = "encargado@farmacia.mx"


def _descartar(cliente, renglon_id: int, correo: str | None = CORREO):
    """El clic. Sin cuerpo: descartar no lleva parámetros, solo la firma."""
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(f"/api/renglon/{renglon_id}/descartar", headers=cabeceras)


def _devolver(cliente, renglon_id: int):
    return cliente.post(f"/api/renglon/{renglon_id}/devolver")


# ------------------------------- un clic lo descarta y sale de la lista


def test_un_clic_pone_el_renglon_en_descartado(cliente, almacen, almacenamiento):
    """La casilla 1, en su forma más directa: una petición, un estado nuevo.

    Sin cuerpo y sin confirmación: el ticket dice "un clic", y lo que hace
    segura la operación no es un diálogo sino poder deshacerla.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]

    respuesta = _descartar(cliente, renglon_id)

    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True
    assert respuesta.json()["renglon"]["estado"] == RENGLON_DESCARTADO

    guardada = almacenamiento.leer(NEGOCIO, HOY)
    descartado = next(r for r in guardada.renglones if r.renglon_id == renglon_id)
    assert descartado.estado == RENGLON_DESCARTADO


def test_el_renglon_descartado_sale_de_la_lista_de_trabajo(cliente, almacen):
    """"Sale de la lista de trabajo" no es "desaparece".

    El renglón sigue en la respuesta, con su estado, porque el punto siguiente
    del ticket pide poder verlo aparte y devolverlo. Lo que baja es el conteo
    de lo que queda por atender.
    """
    _poblar(almacen)
    antes = cliente.get(RUTA).json()
    assert antes["de_trabajo"] == 2

    _descartar(cliente, antes["renglones"][0]["renglon_id"])
    despues = cliente.get(RUTA).json()

    assert despues["de_trabajo"] == 1
    assert len(despues["renglones"]) == 2, (
        "El renglón descartado desapareció de la respuesta. Descartar no borra: "
        "el rol no tiene DELETE y el punto siguiente del ticket pide verlo "
        "aparte y poder devolverlo."
    )


def test_descartar_no_borra_la_fila_ni_toca_los_numeros_congelados(
    cliente, almacen, almacenamiento
):
    """Cambia el estado y nada más.

    Los números viajan congelados desde el ticket 04: descartar no es una
    ocasión para recalcular nada.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    antes = lista["renglones"][0]

    _descartar(cliente, antes["renglon_id"])
    despues = next(
        r
        for r in cliente.get(RUTA).json()["renglones"]
        if r["renglon_id"] == antes["renglon_id"]
    )

    assert len(almacenamiento.listas[0]["renglones"]) == 2
    for campo in ("producto_id", "clave", "cantidad_propuesta", "piezas_vendidas",
                  "existencia", "dias_de_cobertura", "clasificacion"):
        assert despues[campo] == antes[campo], f"Descartar movió {campo}."


def test_la_lista_sigue_teniendo_renglones_sin_atender_solo_si_queda_alguno_abierto(
    cliente, almacen
):
    """Un renglón descartado **ya se atendió**: alguien decidió no pedirlo.

    Es lo que distingue una lista que venció con trabajo pendiente de una donde
    se miró todo. Si `descartado` siguiera contando como "sin atender", vencer
    diría que quedó algo por ver cuando no.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    assert lista["tiene_renglones_sin_atender"] is True

    for renglon in lista["renglones"]:
        _descartar(cliente, renglon["renglon_id"])

    assert cliente.get(RUTA).json()["tiene_renglones_sin_atender"] is False


# --------------------------- se ven aparte y se devuelven a abierto


def test_un_renglon_descartado_vuelve_a_abierto(cliente, almacen, almacenamiento):
    """La otra dirección, que es lo que hace segura la operación de un clic."""
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    _descartar(cliente, renglon_id)

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 200
    assert respuesta.json()["renglon"]["estado"] == RENGLON_ABIERTO

    vuelto = next(
        r for r in almacenamiento.leer(NEGOCIO, HOY).renglones if r.renglon_id == renglon_id
    )
    assert vuelto.estado == RENGLON_ABIERTO


def test_al_devolver_a_abierto_se_borra_la_firma_del_descarte(
    cliente, almacen, almacenamiento
):
    """Y esa es una decisión, no un descuido.

    Un renglón devuelto a `abierto` **no está descartado**: dejarle la firma y
    la hora haría que el conteo mensual del ADR 0002 —"los renglones
    descartados de un mes"— sumara renglones que hoy alguien está trabajando, y
    la condición de revisión se dispararía con evidencia falsa. Lo mismo exige
    `ck_renglon_descarte` en la base.

    Lo que se pierde y se dice: **no queda rastro del descarte deshecho**. Un
    historial de cada clic sería otra tabla, y el dato que el ADR necesita es
    cuántos renglones quedaron descartados, no cuántas veces alguien dudó.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    _descartar(cliente, renglon_id)
    _devolver(cliente, renglon_id)

    vuelto = next(
        r for r in almacenamiento.leer(NEGOCIO, HOY).renglones if r.renglon_id == renglon_id
    )
    assert vuelto.descartado_por is None
    assert vuelto.descartado_en is None


def test_devolver_un_renglon_que_no_esta_descartado_no_hace_nada(cliente, almacen):
    """Un 409 y no un 500: no había nada que devolver.

    La transición vive en el `WHERE` del `UPDATE`, así que el segundo clic no
    reescribe nada y la ruta lo dice en vez de fingir que movió algo.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False


def test_descartar_dos_veces_no_mueve_la_firma(cliente, almacen, almacenamiento):
    """El segundo clic no reescribe la historia, igual que cerrar la lista."""
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    primera = _descartar(cliente, renglon_id).json()["renglon"]["descartado_en"]
    segunda = _descartar(cliente, renglon_id, correo="otro@farmacia.mx")

    assert segunda.status_code == 409
    vuelto = next(
        r for r in almacenamiento.leer(NEGOCIO, HOY).renglones if r.renglon_id == renglon_id
    )
    assert vuelto.descartado_en.isoformat() == primera
    assert vuelto.descartado_por == CORREO


def test_un_renglon_de_otro_negocio_no_se_descarta(almacenamiento):
    """Regla 7 de CLAUDE.md: el `negocio` va en el `WHERE`, no solo en la fila.

    Hoy hay una farmacia y esto no se puede ver en la pantalla. Se prueba
    igual: es lo único que se paga hoy para no reescribir el módulo el día que
    haya dos.
    """
    lista = almacenamiento.abrir_el_dia(
        "farmacia_02", HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id

    assert almacenamiento.descartar("farmacia_01", renglon_id, CORREO) is None
    assert almacenamiento.leer("farmacia_02", HOY).renglones[0].estado == RENGLON_ABIERTO


# ------------------------------- cuántos se descartaron en el día


def test_la_respuesta_dice_cuantos_renglones_se_descartaron_en_el_dia(cliente, almacen):
    """La casilla 3. El número sale del servidor, no de una cuenta del navegador.

    Dos pestañas abiertas en el mostrador bastan para que un contador que el
    JavaScript lleva a mano se separe de la verdad, y ese número es justo el
    que el ADR 0002 va a mirar después de un mes.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    assert lista["descartados"] == 0

    respuesta = _descartar(cliente, lista["renglones"][0]["renglon_id"]).json()

    assert respuesta["descartados"] == 1
    assert cliente.get(RUTA).json()["descartados"] == 1


def test_el_conteo_del_dia_es_el_de_la_lista_del_dia_y_no_sale_del_reloj(
    cliente, almacen, almacenamiento
):
    """"En el día" se ancla en la lista, que se ancla en `max(fecha)` del almacén.

    Contarlo con `descartado_en::date` sería preguntarle la fecha al reloj: el
    Postgres del contenedor corre en UTC y su idea de "hoy" puede ir dos días
    adelante del último dato —a farmacia-data le costó 11.7 puntos de
    crecimiento inventados—. Aquí el último dato es de 2024 y el reloj de la
    máquina no: si el conteo saliera del reloj, el descarte de esta lista no
    contaría para "hoy" ni una sola vez.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 4), 1, 2)]
    ayer = cliente.get(RUTA).json()
    _descartar(cliente, ayer["renglones"][0]["renglon_id"])

    almacen.ventas_en_memoria.append(_venta(HOY, 1, 3))
    hoy = cliente.get(RUTA).json()

    assert HOY < dt.date.today()
    assert hoy["descartados"] == 0, (
        "La lista de hoy está contando los descartes de la lista de ayer."
    )
    assert almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 4)).descartados == 1


# ------------------------------------- queda registrado quién, y cuándo


def test_queda_guardado_quien_descarto_el_renglon(cliente, almacen, almacenamiento):
    """La casilla 4. Una FIRMA, no un permiso (regla 3 de CLAUDE.md).

    El correo llega en `Cf-Access-Authenticated-User-Email`, ya validado por
    Cloudflare Access. Nada de este código lo trata como prueba de
    autorización: sirve para saber quién decidió no pedir un producto.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    _descartar(cliente, renglon_id)

    guardado = next(
        r for r in almacenamiento.leer(NEGOCIO, HOY).renglones if r.renglon_id == renglon_id
    )
    assert guardado.descartado_por == CORREO


def test_sin_encabezado_la_firma_es_sin_identificar_pero_se_guarda(
    cliente, almacen, almacenamiento
):
    """Hoy en la torre, sin el túnel delante, vale `sin-identificar`.

    Y está bien: dice que no se supo, que es un dato honesto. Lo que no puede
    pasar es que no se guarde nada — un `NULL` ahí dejaría un renglón
    descartado sin nadie detrás, y `ck_renglon_descarte` lo rechaza.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    _descartar(cliente, renglon_id, correo=None)

    guardado = next(
        r for r in almacenamiento.leer(NEGOCIO, HOY).renglones if r.renglon_id == renglon_id
    )
    assert guardado.descartado_por == "sin-identificar"


def test_queda_guardado_cuando_se_descarto_como_instante_con_zona(cliente, almacen):
    """Sin el cuándo, la condición de revisión del ADR 0002 no se puede medir.

    "Si después de un mes de uso los renglones descartados superan a los
    pedidos" es una consulta con un rango de fechas: sin `descartado_en` no hay
    con qué acotar el mes, y la condición se cumpliría sin que nadie pudiera
    demostrarlo.

    Con zona porque el contenedor corre en UTC: un instante sin zona es un
    reloj de pared que alguien en México lee seis horas en el futuro.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    cuando = _descartar(cliente, renglon_id).json()["renglon"]["descartado_en"]

    assert dt.datetime.fromisoformat(cuando).tzinfo is not None


def test_la_firma_del_descarte_tambien_va_a_la_bitacora(cliente, almacen, caplog):
    """La columna es para consultar; la bitácora es para reconstruir el día."""
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    with caplog.at_level(logging.INFO, logger="continental"):
        _descartar(cliente, renglon_id)

    assert CORREO in caplog.text


# ---------------------------------- la transición: solo se descarta lo abierto


@pytest.mark.parametrize("estado", ["en tránsito", "recibido", "recibido parcial"])
def test_un_renglon_que_no_esta_abierto_no_se_descarta(almacenamiento, estado):
    """Esos estados los pone otro ticket; la transición vale desde hoy.

    Un renglón `en tránsito` ya se le pidió a un proveedor: descartarlo diría
    que nadie lo va a pedir cuando la mercancía viene en camino, y el ticket 26
    la recibiría contra un renglón que dice que no se pidió. `recibido` y
    `recibido parcial` son hechos consumados y descartarlos sería reescribirlos.

    La transición vive en el `WHERE ... AND estado = 'abierto'` del `UPDATE`,
    así que cero filas es "no había nada que descartar" y quien llama lo dice.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id
    almacenamiento.poner_estado_del_renglon(renglon_id, estado)

    assert almacenamiento.descartar(NEGOCIO, renglon_id, CORREO) is None
    assert almacenamiento.leer(NEGOCIO, HOY).renglones[0].estado == estado


def test_la_ruta_contesta_409_al_descartar_algo_que_no_esta_abierto(
    cliente, almacen, almacenamiento
):
    """Y no un 500: el renglón existe, es su estado el que no deja."""
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    almacenamiento.poner_estado_del_renglon(renglon_id, "en tránsito")

    respuesta = _descartar(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False


def test_descartar_un_renglon_que_no_existe_contesta_409(cliente, almacen):
    """Mismo 409, y a propósito: desde fuera no se distingue "no existe" de
    "no estaba abierto", y decirlo sería contar qué ids hay en la tabla."""
    _poblar(almacen)

    assert _descartar(cliente, 99999).status_code == 409


# --------------------------------- descartar NO es una lista negra (ticket 09)


def test_un_producto_descartado_vuelve_a_proponerse_si_se_vuelve_a_vender(
    cliente, almacen, almacenamiento
):
    """La interacción con el ticket 09, comprobada y no supuesta.

    El descarte es **de un renglón**, no del producto: la ventana de reposición
    acumula por FECHAS DE VENTA desde el corte del último cerrado, y nada en
    `calcular_pedido_sugerido` mira el estado de renglones anteriores. Así que
    un producto que alguien decidió no pedir ayer vuelve a la lista mañana si
    se vuelve a vender — que es lo correcto: "hoy no hace falta" no es "nunca
    hace falta", y lo contrario sería mercancía que deja de proponerse para
    siempre por un clic.

    Lo único que sí saca un producto de la lista siguiente es `en tránsito`
    (glosario de `CONTEXT.md`), y eso es el ticket 24.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001")]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 4), 1, 2)]

    ayer = cliente.get(RUTA).json()
    _descartar(cliente, ayer["renglones"][0]["renglon_id"])
    # Se cierra para que la ventana de mañana arranque al día siguiente: así el
    # renglón de mañana no puede venir de la venta de ayer.
    cliente.post(f"{RUTA}/{ayer['pedido_sugerido_id']}/cerrar")

    almacen.ventas_en_memoria.append(_venta(HOY, 1, 3))
    hoy = cliente.get(RUTA).json()

    assert [r["producto_id"] for r in hoy["renglones"]] == [1]
    assert hoy["renglones"][0]["estado"] == RENGLON_ABIERTO
    assert hoy["renglones"][0]["cantidad_propuesta"] == 3
    assert (
        almacenamiento.leer(NEGOCIO, dt.date(2024, 3, 4)).renglones[0].estado
        == RENGLON_DESCARTADO
    ), "El descarte de ayer se perdió al armar la lista de hoy."


# ------------------------------------------- que el doble no sea permisivo


def test_el_doble_rechaza_un_descartado_sin_firma_y_un_abierto_con_ella(almacenamiento):
    """`ck_renglon_descarte`, tal cual, escrito en Python.

    Las dos mitades del `si y solo si`. Un doble que aceptara cualquiera de las
    dos dejaría el suite en verde y el `UPDATE` rebotaría en atlas con una
    violación de restricción que nadie sabría explicar.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )
    renglon_id = lista.renglones[0].renglon_id

    with pytest.raises(ValueError):
        almacenamiento.poner_estado_del_renglon(renglon_id, RENGLON_DESCARTADO)
    with pytest.raises(ValueError):
        almacenamiento.poner_estado_del_renglon(
            renglon_id,
            RENGLON_ABIERTO,
            descartado_por=CORREO,
            descartado_en=dt.datetime.now(dt.UTC),
        )


def test_el_doble_rechaza_una_firma_vacia(almacenamiento):
    """`ck_renglon_descartado_por`: o hay firma o es NULL, igual que la clave.

    Una cadena vacía se compara igual que un dato y empareja con cualquier otra
    vacía. `quien()` nunca devuelve `''` —sin encabezado devuelve
    `sin-identificar`— así que esto es el cinturón.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )

    with pytest.raises(ValueError):
        almacenamiento.descartar(NEGOCIO, lista.renglones[0].renglon_id, "")


def test_el_doble_rechaza_un_estado_de_renglon_que_el_ddl_no_conoce(almacenamiento):
    """Los cinco del glosario y ninguno más."""
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )

    with pytest.raises(ValueError):
        almacenamiento.poner_estado_del_renglon(
            lista.renglones[0].renglon_id, "cancelado"
        )


def test_un_renglon_nace_abierto_y_sin_firma_de_descarte(almacenamiento):
    """El estado inicial que `columnas_del_renglon` arma para las dos
    implementaciones: sin firma y sin hora, que es lo que
    `ck_renglon_descarte` exige de todo lo que no está descartado."""
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO, HOY, Ventana(HOY, HOY), lambda: (_renglon(1, "PARACETAMOL"),)
    )

    assert lista.renglones[0].estado == RENGLON_ABIERTO
    assert lista.renglones[0].descartado_por is None
    assert lista.renglones[0].descartado_en is None
    assert almacenamiento.listas[0]["renglones"][0]["descartado_por"] is None


def test_el_almacenamiento_caido_al_descartar_es_un_hueco_con_motivo(
    cliente, almacen, almacenamiento
):
    """Regla 4 y regla 5, las dos a la vez.

    El motivo es el **tipo** de la falla y nunca su texto: un `str(exc)` de
    SQLAlchemy lleva la cadena de conexión con contraseña y esto corre detrás
    de un túnel.
    """
    _poblar(almacen)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    almacenamiento.falla = RuntimeError(
        "connection to postgresql://continental:SECRETO@atlas:5432/farmacia failed"
    )

    cuerpo = _descartar(cliente, renglon_id).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "SECRETO" not in str(cuerpo)


# ------------------------------------------------- el SQL, revisado como texto


def test_el_descarte_es_un_update_con_la_transicion_en_el_where():
    """Revisado como texto, porque desde la torre no hay Postgres que lo corra.

    Dos cosas en una: que sea un `UPDATE` —el rol no tiene `DELETE`, y
    descartar es un cambio de estado— y que la transición viva en el `WHERE`.
    Comprobar el estado en Python y después actualizar tiene una carrera en
    medio: dos pestañas pueden descartar y recibir el mismo renglón a la vez.
    """
    sentencias = {
        n: s for n, s in _sentencias().items() if "descartad" in s.lower()
    }
    assert sentencias, "No hay ninguna sentencia del descarte que revisar."

    descarte = next(s for n, s in sentencias.items() if "DESCARTAR" in n)
    assert descarte.lower().lstrip().startswith("update")
    assert "estado = 'abierto'" in descarte.lower()

    devolucion = next(s for n, s in sentencias.items() if "DEVOLVER" in n)
    assert devolucion.lower().lstrip().startswith("update")
    assert "estado = 'descartado'" in devolucion.lower()


def test_la_hora_del_descarte_la_pone_el_servidor_que_guarda_la_fila():
    """`now()` y no una hora calculada en Python.

    Dos procesos con relojes distintos escribirían descartes incomparables, y
    el conteo mensual del ADR 0002 se haría sobre instantes que no se pueden
    ordenar entre sí.
    """
    descarte = next(s for n, s in _sentencias().items() if "DESCARTAR" in n)
    assert "now()" in descarte.lower()


def test_al_devolver_a_abierto_el_sql_limpia_las_dos_columnas():
    """Las dos, no una: `ck_renglon_descarte` exige que vayan juntas."""
    devolucion = next(s for n, s in _sentencias().items() if "DEVOLVER" in n)
    assert "descartado_por = null" in devolucion.lower()
    assert "descartado_en = null" in devolucion.lower()


# --------------------------------------------------------- el DDL nuevo


def _cuerpo_del_renglon() -> str:
    sql = CREAR_TABLAS.read_bytes().decode("utf-8")
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.renglon (")
    return sql[inicio : sql.index("\n);", inicio)]


@pytest.mark.parametrize(
    ("columna", "tipo"),
    [("descartado_por", "text"), ("descartado_en", "timestamptz")],
)
def test_la_tabla_guarda_quien_descarto_y_cuando(columna: str, tipo: str):
    """La casilla 4 del lado del esquema.

    `timestamptz` y no `date`: es un INSTANTE que ocurrió aquí, igual que
    `armado_en` y `cerrado_en`, y eso no contradice anclarse en `max(fecha)`
    —esa regla es sobre fechas de venta—.
    """
    columnas = re.search(
        rf"^\s*{columna}\s+(\w+)(.*)$", _cuerpo_del_renglon(), re.MULTILINE
    )
    assert columnas, f"`pedidos.renglon` no tiene columna `{columna}`."
    assert columnas.group(1) == tipo
    assert "NOT NULL" not in columnas.group(2), (
        f"{columna} es NOT NULL: la mayoría de los renglones no están "
        "descartados y no tienen qué poner ahí."
    )


def test_el_ddl_exige_descartado_si_y_solo_si_hay_firma_y_hora():
    """`ck_renglon_descarte`, la restricción que hace medible al ADR 0002."""
    cuerpo = _cuerpo_del_renglon()
    assert "CONSTRAINT ck_renglon_descarte" in cuerpo
    assert "descartado_por IS NOT NULL AND descartado_en IS NOT NULL" in cuerpo


def test_hay_una_migracion_para_la_base_que_ya_tiene_la_tabla():
    """El archivo aparte, y por qué no basta con `crear_tablas.sql`.

    `CREATE TABLE IF NOT EXISTS` **calla si la tabla ya existe con otra
    forma**: sobre una base donde `pedidos.renglon` ya está creada, volver a
    correr el DDL no agrega la columna y no avisa de nada. El primer
    `UPDATE ... SET descartado_por = ...` rebotaría en atlas con "column does
    not exist", después de que aquí todo se viera verde.

    Y el archivo de migración tampoco basta solo: una base desde cero se crea
    con `crear_tablas.sql`, así que la columna tiene que estar en los dos.
    """
    assert MIGRACION.exists(), (
        "Falta el archivo de migración. Ver la cabecera de sql/crear_tablas.sql."
    )
    texto = MIGRACION.read_bytes().decode("utf-8")
    # Las SENTENCIAS y no el archivo entero, por la misma razón que
    # `test_guardado.py` mira las sentencias del módulo: la cabecera nombra
    # `CREATE TABLE IF NOT EXISTS` justamente para explicar por qué no alcanza,
    # y buscar la palabra en la prosa castigaría la explicación en vez del
    # defecto.
    sentencias = "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("--")
    )

    assert "ALTER TABLE pedidos.renglon" in sentencias
    assert "CREATE TABLE" not in sentencias, (
        "La migración crea tablas: eso es trabajo de sql/crear_tablas.sql."
    )
    for columna in ("descartado_por", "descartado_en"):
        assert f"ADD COLUMN IF NOT EXISTS {columna}" in sentencias, (
            f"La migración no agrega `{columna}`, o no es idempotente."
        )
    # `ADD CONSTRAINT` no tiene IF NOT EXISTS en Postgres: la idempotencia se
    # consigue quitándolo primero.
    for restriccion in ("ck_renglon_descartado_por", "ck_renglon_descarte"):
        assert f"DROP CONSTRAINT IF EXISTS {restriccion}" in sentencias
        assert f"ADD CONSTRAINT {restriccion}" in sentencias
    # Quitar un CHECK no borra una fila, pero un DELETE aquí sí sería otra cosa:
    # el rol no lo tiene y el dueño no debería necesitarlo para agregar columnas.
    for prohibida in ("DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN"):
        assert prohibida not in sentencias.upper(), (
            f"La migración contiene {prohibida}: agregar una columna no borra "
            "nada."
        )


def test_la_migracion_no_la_corre_el_codigo_de_arranque():
    """ADR 0003: el DDL se corre a mano, con credenciales de dueño.

    Si el arranque aplicara migraciones, el rol `continental` necesitaría
    `ALTER` sobre sus tablas — y con `ALTER` puede quitar un CHECK, que es la
    mitad de las garantías de este esquema.
    """
    fuentes = [RAIZ / "iniciar.py"] + sorted((RAIZ / "src").rglob("*.py"))
    for ruta in fuentes:
        texto = ruta.read_text(encoding="utf-8")
        assert "migraciones" not in texto, (
            f"{ruta.name} nombra `migraciones`: el DDL no lo corre el código."
        )


def test_el_descarte_no_es_uno_de_los_estados_nuevos():
    """El vocabulario no creció con este ticket: `descartado` ya estaba.

    Se comprueba porque la tentación al implementar un ticket de estado es
    inventarse un sinónimo —"quitado", "omitido"— y partir la lista en dos
    vocabularios.
    """
    assert RENGLON_DESCARTADO == "descartado"
    assert RENGLON_DESCARTADO in ESTADOS_DEL_RENGLON
    assert len(ESTADOS_DEL_RENGLON) == 5


# ------------------------------------------------------------ la pantalla


def test_la_pantalla_descarta_de_un_clic_y_sin_pedir_confirmacion(cliente):
    """Lo que el ticket pide, revisado sobre el HTML que se sirve.

    Ninguna prueba de Python ejecuta este JavaScript, así que lo que sí se
    puede afirmar es que los pedazos están y que **no hay un `confirm()`**: el
    ticket dice un clic, y lo que hace segura la operación es poder deshacerla,
    no un diálogo que se aprende a cerrar sin leer.
    """
    pagina = cliente.get("/").text

    assert "Descartar" in pagina
    assert "/descartar" in pagina
    assert "confirm(" not in pagina, (
        "La pantalla pide confirmación para descartar. El ticket dice UN CLIC: "
        "lo que hace segura la operación es que se puede devolver a abierto."
    )


def test_la_pantalla_muestra_los_descartados_aparte_y_deja_devolverlos(cliente):
    """Las dos direcciones, y el conteo del día."""
    pagina = cliente.get("/").text

    assert "descartados" in pagina
    assert "/devolver" in pagina
    assert "Devolver" in pagina


def test_la_pantalla_sigue_cabiendo_en_un_telefono(cliente):
    """375 px: la tabla se apila y el botón nuevo no puede romper eso.

    Se comprueba lo único que se puede comprobar sin navegador —que la regla
    de ancho sigue ahí y que el botón tiene su tamaño mínimo tocable—; el
    recorrido con el ojo a 375 px está en el reporte del ticket.
    """
    pagina = cliente.get("/").text

    assert "@media (max-width: 34rem)" in pagina
    assert "td.acciones" in pagina


# ------------------------------------------------------------------ ayudas


def _sentencias() -> dict[str, str]:
    """Las sentencias SQL del módulo, por su nombre, como texto.

    Se leen del módulo ya importado y no del archivo: así lo que se revisa es
    **lo que se va a ejecutar**, sin que la prosa que explica por qué algo no
    se usa cuente como si se usara.
    """
    import continental.almacenamiento as modulo

    return {
        nombre: valor.text
        for nombre, valor in vars(modulo).items()
        if isinstance(valor, sqlalchemy.sql.elements.TextClause)
    }


def _poblar(almacen) -> None:
    """Dos productos vendidos el mismo día: uno agotado y uno con anaquel lleno.

    Los dos entran a la lista —nada se filtra, ADR 0002— y por eso hay algo que
    descartar: el que tiene 90 piezas en el anaquel es justo el renglón que el
    encargado va a quitar de un clic.
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


# --------------------------- pendiente 4: la lista cerrada cierra de verdad
#
# Decidido el 2026-09-20. Hasta ese dia convivian dos criterios sobre la misma
# lista: ajustar la cantidad (11) y elegir proveedor (20) exigian la lista
# `abierta`, y descartar (10) no. El ticket 10 nunca lo pidio, asi que no era un
# incumplimiento -- era una incoherencia, y `_ELEGIR_PROVEEDOR` la dejo anotada
# en su comentario pidiendo que el arreglo se hiciera "a proposito y no de
# paso". Esto es ese arreglo.
#
# De cara al encargado, una lista cerrada que todavia se deja modificar es una
# lista que no esta cerrada. `cerrado` significa "ya se pidio lo que se iba a
# pedir" (CONTEXT.md): descartar despues separa el renglon de lo que de verdad
# se le pidio al proveedor, y el ticket 26 recibiria mercancia contra un renglon
# que dice que nadie la pidio.


def test_con_la_lista_cerrada_ya_no_se_descarta(cliente, almacen, almacenamiento):
    """La mitad que faltaba para que los tres criterios digan lo mismo."""
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    respuesta = _descartar(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False


def test_con_la_lista_cerrada_tampoco_se_devuelve_a_abierto(
    cliente, almacen, almacenamiento
):
    """Las dos direcciones, porque deshacer tambien es modificar.

    Dejar solo una mitad seria peor que no haber tocado nada: un renglon podria
    salir de `descartado` dentro de una lista cerrada y no poder volver.
    """
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]
    _descartar(cliente, renglon_id)
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False


def test_la_lista_abierta_viaja_en_el_where_del_descarte_y_de_la_devolucion():
    """La condicion va en la sentencia, no en un `if` de Python.

    Comprobar el estado de la lista y actualizar despues tiene una carrera en
    medio: una pestana cierra mientras otra descarta. Es la misma razon por la
    que la transicion del renglon ya viajaba ahi, y la misma forma que usan
    `_AJUSTAR_LA_CANTIDAD` y `_ELEGIR_PROVEEDOR`.
    """
    sentencias = _sentencias()
    descarte = next(s for n, s in sentencias.items() if "DESCARTAR" in n)
    devolucion = next(s for n, s in sentencias.items() if "DEVOLVER" in n)

    for nombre, sentencia in (("descarte", descarte), ("devolucion", devolucion)):
        bajo = sentencia.lower()
        assert "pedido_sugerido" in bajo, (
            f"El UPDATE del {nombre} no nombra la tabla de la lista, asi que la "
            "condicion de lista abierta no puede estar en su WHERE."
        )
        assert "p.estado = 'abierto'" in bajo, (
            f"El UPDATE del {nombre} no exige que la LISTA este abierta. Sin "
            "eso, una lista cerrada se sigue dejando modificar y deja de "
            "significar 'ya se pidio lo que se iba a pedir'."
        )


def test_la_pantalla_no_ofrece_descartar_si_la_lista_no_esta_abierta(cliente):
    """La mitad visible del pendiente 4, revisada sobre el HTML que se sirve.

    El servidor lo vuelve a comprobar en el `WHERE` de su `UPDATE`, asi que
    apagar el boton es comodidad y no la garantia. Pero descartar es **la
    accion que mas se toca de esta pantalla** -la lista trae tantos renglones
    como productos distintos se vendieron-, y un boton que se deja tocar para
    contestar 409 enseña a ignorar los avisos justo donde mas caro sale.

    Se apaga y no se esconde: la columna de acciones tiene ancho fijo y quitarlo
    movería todas las filas al cerrar la lista.

    Las dos direcciones, porque deshacer tambien es modificar. Dejar encendido
    el de devolver seria lo peor de los dos mundos: prometeria rescatar un
    renglon que alguien quito por error, y el servidor lo rechazaria.

    **Desde el ticket 21 lo que decide son DOS cosas y no una**, y por eso esto
    ya no busca `acciones.editable` pegado al boton: el estado de la LISTA
    —"mientras este abierta"— y el del RENGLON —uno `en transito` ya se le pidio
    a un proveedor—. Los dos entran en `editable`, que se calcula una vez por
    renglon y lo usan los tres controles: la cantidad, el proveedor y este.
    """
    pagina = cliente.get("/").text

    assert "const editable = acciones.editable && !r.esta_en_transito" in pagina, (
        "El renglon no mira las dos cosas: el estado de la lista y el suyo."
    )
    assert "quitar.disabled = !editable" in pagina, (
        "El boton de descartar no mira el estado de la lista."
    )
    assert "devolver.disabled = !editable" in pagina, (
        "El boton de devolver a la lista no mira el estado de la lista."
    )
    assert pagina.count("La lista ya se cerró: lo que se iba a pedir ya se pidió.") == 2, (
        "Los dos botones tienen que decir POR QUE estan apagados. Un boton gris "
        "sin explicacion se lee como que la pantalla se rompio."
    )
