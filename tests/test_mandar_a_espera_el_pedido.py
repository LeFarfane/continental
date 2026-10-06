"""Mandar a espera el pedido entero (lista de espera, ticket 06).

**Lo que arregla.** Para bajar un pedido que se pasa del tope del dueño, o que
no llega al mínimo del proveedor, la encargada tenía que mandar a espera sus
renglones uno por uno. Ahora el pedido lleva un botón que manda **todo lo
abierto y no tachado** de una vez, en una sola operación del servidor. Lo
tachado ya está en el carrito del portal y **se queda**. Ver la enmienda del
2026-10-05 al ADR 0025 (punto 6).

Los cuatro niveles del repo. **Ninguna prueba toca Postgres, la red ni duerme.**

1. Lo puro: las frases y el motivo.
2. Lo guardado: el doble, y el SQL como texto (una sentencia, respeta lo
   tachado).
3. La ruta, de punta a punta.
4. Lo estático del JavaScript: el botón y el pedido vacío.
"""

from __future__ import annotations

import datetime as dt
import inspect
import re
from decimal import Decimal

from conftest import cuerpo_de_funcion, pantalla_completa
from continental import almacenamiento as modulo_almacenamiento
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_POSPUESTO,
    AlmacenamientoDelPedido,
    Ventana,
    columnas_del_pedido,
)
from continental.dobles import AlmacenamientoFalso
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon
from continental.transiciones import (
    frase_de_mandar_el_pedido_a_espera,
    frase_del_pedido_vacio,
    motivo_para_no_mandar_el_pedido_a_espera,
)

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargada@farmacia.mx"
HOY = dt.date(2024, 3, 5)
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


def _sentencia(nombre: str) -> str:
    return getattr(modulo_almacenamiento, nombre).text


# ==========================================================================
# 1. LO PURO
# ==========================================================================


def test_la_frase_del_ticket_dice_las_dos_cifras_y_que_hacer_con_lo_tachado():
    assert frase_de_mandar_el_pedido_a_espera(6, 3) == (
        "Se mandaron 6 a espera; 3 ya tachados se quedan: bórralos del carrito "
        "del portal o destáchalos primero."
    )


def test_la_frase_concuerda_en_singular():
    assert frase_de_mandar_el_pedido_a_espera(1, 1) == (
        "Se mandó 1 a espera; 1 ya tachado se queda: bórralo del carrito del "
        "portal o destáchalo primero."
    )


def test_sin_tachados_la_frase_no_inventa_una_segunda_cifra():
    assert frase_de_mandar_el_pedido_a_espera(6, 0) == "Se mandaron 6 a espera."
    assert frase_de_mandar_el_pedido_a_espera(1, 0) == "Se mandó 1 a espera."


def test_con_todo_tachado_la_frase_dice_que_no_se_mando_ninguno():
    frase = frase_de_mandar_el_pedido_a_espera(0, 3)
    assert frase.startswith("No se mandó ninguno a espera; 3 ya tachados se quedan")
    assert "destáchalos primero" in frase


def test_un_pedido_sin_nada_que_mandar_lo_dice():
    assert "no tiene renglones" in frase_de_mandar_el_pedido_a_espera(0, 0)


def test_solo_un_borrador_de_una_lista_abierta_se_manda():
    assert motivo_para_no_mandar_el_pedido_a_espera(BORRADOR, "abierto") is None


def test_un_pedido_enviado_o_una_lista_cerrada_dicen_su_motivo():
    enviado = motivo_para_no_mandar_el_pedido_a_espera(ENVIADO, "abierto")
    cerrada = motivo_para_no_mandar_el_pedido_a_espera(BORRADOR, "cerrado")
    assert "ya no está en borrador" in enviado
    assert "la lista ya no está abierta" in cerrada


def test_el_pedido_vacio_dice_todo_en_espera_solo_si_algo_espera():
    assert frase_del_pedido_vacio(4) == "sin renglones · todo en espera"
    assert frase_del_pedido_vacio(0) == "sin renglones"


# ==========================================================================
# 2. LO GUARDADO — el doble
# ==========================================================================


def _renglon(producto_id: int, cantidad: int = 5) -> Renglon:
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


def _pedido_con(almacenamiento, cuantos=4, estado=BORRADOR, lista_estado=None):
    """Una lista de `cuantos` renglones, todos en un pedido de NADRO."""
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO, HOY, Ventana(HOY, HOY), [_renglon(n) for n in range(1, cuantos + 1)]
    )
    pedido = {
        **columnas_del_pedido(
            NEGOCIO, lista.pedido_sugerido_id, "nadro", None, Decimal("10.00")
        ),
        "pedido_id": 1,
        "armado_en": ARMADO,
        "estado": estado,
    }
    almacenamiento.pedidos.append(pedido)
    for r in lista.renglones:
        almacenamiento._renglon_por_id(r.renglon_id)[0]["pedido_id"] = 1
    if lista_estado:
        almacenamiento._por_id(lista.pedido_sugerido_id)["estado"] = lista_estado
    return lista


def _tachar(almacenamiento, renglon_id):
    almacenamiento.poner_la_captura(renglon_id, CORREO, ARMADO)


def test_el_doble_manda_todo_lo_abierto_y_dice_cuantos():
    almacenamiento = AlmacenamientoFalso()
    _pedido_con(almacenamiento, cuantos=4)

    resultado = almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 1, CORREO)

    assert resultado.se_mando is True
    assert (resultado.mandados, resultado.tachados) == (4, 0)
    for r in resultado.lista.renglones:
        assert r.estado == RENGLON_POSPUESTO
        assert r.pedido_id is None, "sale del pedido, como al mandarlo solo"
        assert r.proveedor_de_la_espera == "nadro"
        assert (r.espera_desde, r.listas_en_espera) == (HOY, 1)
        assert r.pospuesto_por == CORREO


def test_el_doble_deja_lo_tachado_donde_estaba_y_lo_cuenta():
    almacenamiento = AlmacenamientoFalso()
    lista = _pedido_con(almacenamiento, cuantos=4)
    tachados = [r.renglon_id for r in lista.renglones[:3]]
    for renglon_id in tachados:
        _tachar(almacenamiento, renglon_id)

    resultado = almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 1, CORREO)

    assert (resultado.mandados, resultado.tachados) == (1, 3)
    por_id = {r.renglon_id: r for r in resultado.lista.renglones}
    for renglon_id in tachados:
        assert por_id[renglon_id].estado == RENGLON_ABIERTO
        assert por_id[renglon_id].pedido_id == 1
        assert por_id[renglon_id].capturado_por == CORREO


def test_el_doble_con_todo_tachado_manda_cero():
    almacenamiento = AlmacenamientoFalso()
    lista = _pedido_con(almacenamiento, cuantos=2)
    for r in lista.renglones:
        _tachar(almacenamiento, r.renglon_id)

    resultado = almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 1, CORREO)

    assert (resultado.mandados, resultado.tachados) == (0, 2)


def test_el_doble_no_mueve_nada_si_el_pedido_ya_se_envio():
    almacenamiento = AlmacenamientoFalso()
    _pedido_con(almacenamiento, cuantos=2, estado=ENVIADO)

    resultado = almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 1, CORREO)

    assert resultado.se_mando is False
    assert resultado.estado_del_pedido == ENVIADO
    assert resultado.mandados == 0 and resultado.lista is None
    assert all(
        f["estado"] == RENGLON_ABIERTO
        for f in almacenamiento._por_id(1)["renglones"]
    )


def test_el_doble_no_mueve_nada_si_la_lista_ya_no_esta_abierta():
    almacenamiento = AlmacenamientoFalso()
    _pedido_con(almacenamiento, cuantos=2, lista_estado="cerrado")

    resultado = almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 1, CORREO)

    assert resultado.se_mando is False and resultado.estado_de_la_lista == "cerrado"
    assert resultado.mandados == 0


def test_el_doble_contesta_none_para_un_pedido_de_otro_negocio_o_inexistente():
    almacenamiento = AlmacenamientoFalso()
    _pedido_con(almacenamiento)

    assert almacenamiento.mandar_el_pedido_a_espera("otra_farmacia", 1, CORREO) is None
    assert almacenamiento.mandar_el_pedido_a_espera(NEGOCIO, 99, CORREO) is None


def test_el_doble_cumple_la_interfaz_de_la_operacion_nueva():
    firma_real = inspect.signature(AlmacenamientoDelPedido.mandar_el_pedido_a_espera)
    firma_doble = inspect.signature(AlmacenamientoFalso.mandar_el_pedido_a_espera)
    assert list(firma_real.parameters) == list(firma_doble.parameters)


# ---------------------------------------------------- el SQL como texto


def test_el_pedido_entero_es_una_sola_sentencia_con_un_solo_update():
    sentencia = _sentencia("_POSPONER_EL_PEDIDO").lower()

    assert sentencia.count("update pedidos.renglon") == 1
    assert ";" not in sentencia, "una sentencia, no dos"
    assert sentencia.lstrip().startswith("with base as")


def test_el_pedido_entero_respeta_lo_tachado_y_lo_cuenta_aparte():
    sentencia = _sentencia("_POSPONER_EL_PEDIDO").lower()
    update = sentencia[
        sentencia.index("update pedidos.renglon") : sentencia.index("returning")
    ]

    assert "r.capturado_por is null" in update, "lo tachado no se mueve"
    assert "r.estado = 'abierto'" in update
    assert "p.estado_del_pedido = 'borrador'" in update
    assert "p.estado_de_la_lista = 'abierto'" in update
    cuenta = sentencia[sentencia.index("as tachados") - 400 : sentencia.index("as tachados")]
    assert "t.capturado_por is not null" in cuenta


def test_el_pedido_entero_usa_el_mismo_set_que_mandar_un_renglon():
    """Una sola regla: el `SET` es el mismo texto en las dos sentencias."""
    fragmento = modulo_almacenamiento._PONER_EN_ESPERA
    assert fragmento in _sentencia("_POSPONER")
    assert fragmento in _sentencia("_POSPONER_EL_PEDIDO")
    assert "pedido_id = null" in fragmento
    assert "proveedor_de_la_espera = coalesce(" in fragmento


def test_la_implementacion_real_lo_hace_en_una_transaccion():
    fuente = inspect.getsource(
        modulo_almacenamiento.AlmacenamientoPostgres.mandar_el_pedido_a_espera
    )
    assert fuente.count(".begin()") == 1
    assert fuente.count("_POSPONER_EL_PEDIDO,") == 1, "una sola ejecución"


# ==========================================================================
# 3. LA RUTA, de punta a punta
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


def _partida(cliente, almacen, almacenamiento, cuantos: int = 4):
    almacen.catalogo_en_memoria = [_producto(n) for n in range(1, cuantos + 1)]
    almacen.ventas_en_memoria = [_venta(n) for n in range(1, cuantos + 1)]
    lista = cliente.get(RUTA).json()
    for i in range(cuantos):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], [_lectura(f"1{i}.50")]
        )
    lista = cliente.get(RUTA).json()
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    return partida["pedidos"][0]


def _a_espera(cliente, pedido_id: int):
    return cliente.post(f"/api/pedido/{pedido_id}/posponer", headers=_firma())


def _tachar_por_ruta(cliente, renglon_id: int):
    return cliente.post(
        f"/api/renglon/{renglon_id}/capturado",
        json={"capturado": True},
        headers=_firma(),
    )


def _del_pedido(cuerpo: dict, pedido_id: int) -> dict:
    return next(p for p in cuerpo["pedidos"] if p["pedido_id"] == pedido_id)


def test_la_ruta_manda_el_pedido_entero_y_lo_deja_vacio_sin_desaparecer(
    cliente, almacen, almacenamiento
):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=4)

    respuesta = _a_espera(cliente, pedido["pedido_id"])

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert (cuerpo["mandados"], cuerpo["tachados"]) == (4, 0)
    assert cuerpo["frase_de_mandar_a_espera"] == "Se mandaron 4 a espera."
    nuevo = _del_pedido(cuerpo, pedido["pedido_id"])
    # Vacío, no enviado y no desaparecido: sigue en la lista de pedidos.
    assert nuevo["es_borrador"] is True and nuevo["fue_enviado"] is False
    assert nuevo["captura"]["cuantos"] == 0
    assert nuevo["frase_del_pedido_vacio"] == "sin renglones · todo en espera"
    assert nuevo["se_puede_enviar"] is False
    # Y lo guardado dice lo mismo: todos en espera con su proveedor.
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    assert {r.estado for r in guardado.renglones} == {RENGLON_POSPUESTO}
    assert {r.proveedor_de_la_espera for r in guardado.renglones} == {"nadro"}
    assert all(r.pedido_id is None for r in guardado.renglones)


def test_la_ruta_deja_lo_tachado_y_la_frase_lo_dice(cliente, almacen, almacenamiento):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=4)
    for linea in pedido["captura"]["lineas"][:3]:
        assert _tachar_por_ruta(cliente, linea["renglon_id"]).status_code == 200

    cuerpo = _a_espera(cliente, pedido["pedido_id"]).json()

    assert (cuerpo["mandados"], cuerpo["tachados"]) == (1, 3)
    assert cuerpo["frase_de_mandar_a_espera"] == (
        "Se mandó 1 a espera; 3 ya tachados se quedan: bórralos del carrito "
        "del portal o destáchalos primero."
    )
    nuevo = _del_pedido(cuerpo, pedido["pedido_id"])
    assert nuevo["captura"]["cuantos"] == 3, "los tachados siguen en su pedido"
    assert nuevo["frase_del_pedido_vacio"] is None, "no está vacío"
    assert nuevo["total"]["cifra"] != pedido["total"]["cifra"], "el total bajó"


def test_la_ruta_con_todo_tachado_no_manda_nada_pero_contesta_200(
    cliente, almacen, almacenamiento
):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    for linea in pedido["captura"]["lineas"]:
        _tachar_por_ruta(cliente, linea["renglon_id"])

    cuerpo = _a_espera(cliente, pedido["pedido_id"]).json()

    assert (cuerpo["mandados"], cuerpo["tachados"]) == (0, 2)
    assert cuerpo["frase_de_mandar_a_espera"].startswith("No se mandó ninguno")


def test_cada_renglon_queda_igual_que_si_se_hubiera_mandado_solo(
    cliente, almacen, almacenamiento
):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    solo, junto = (l["renglon_id"] for l in pedido["captura"]["lineas"])
    cliente.post(f"/api/renglon/{solo}/posponer", headers=_firma())

    _a_espera(cliente, pedido["pedido_id"])

    guardado = almacenamiento.leer(NEGOCIO, HOY)
    a = next(r for r in guardado.renglones if r.renglon_id == solo)
    b = next(r for r in guardado.renglones if r.renglon_id == junto)
    assert (a.proveedor_de_la_espera, a.espera_desde, a.listas_en_espera, a.pedido_id) == (
        b.proveedor_de_la_espera,
        b.espera_desde,
        b.listas_en_espera,
        b.pedido_id,
    )
    assert b.pospuesto_por == CORREO


def test_un_pedido_enviado_contesta_409_con_su_motivo_y_no_mueve_nada(
    cliente, almacen, almacenamiento
):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    enviado = cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=_firma())
    assert enviado.status_code == 200, enviado.text

    respuesta = _a_espera(cliente, pedido["pedido_id"])

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False
    assert "ya no está en borrador" in respuesta.json()["detalle"]
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    assert all(r.estado != RENGLON_POSPUESTO for r in guardado.renglones)


def test_una_lista_cerrada_contesta_409_con_su_motivo(cliente, almacen, almacenamiento):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    lista_id = almacenamiento.leer(NEGOCIO, HOY).pedido_sugerido_id
    almacenamiento._por_id(lista_id)["estado"] = "cerrado"

    respuesta = _a_espera(cliente, pedido["pedido_id"])

    assert respuesta.status_code == 409
    assert "la lista ya no está abierta" in respuesta.json()["detalle"]


def test_un_pedido_que_no_existe_contesta_409_generico(cliente, almacen, almacenamiento):
    _partida(cliente, almacen, almacenamiento, cuantos=2)

    respuesta = _a_espera(cliente, 9999)

    assert respuesta.status_code == 409 and respuesta.json()["ok"] is False


def test_el_boton_del_pedido_viaja_apagado_con_el_motivo_del_servidor(
    cliente, almacen, almacenamiento
):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    assert pedido["se_puede_mandar_a_espera"] is True
    assert pedido["motivo_para_no_mandar_a_espera"] is None
    cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=_firma())

    de_nuevo = _del_pedido(cliente.get(RUTA).json(), pedido["pedido_id"])

    assert de_nuevo["se_puede_mandar_a_espera"] is False
    assert "ya no está en borrador" in de_nuevo["motivo_para_no_mandar_a_espera"]


def test_el_error_de_la_base_no_viaja_al_navegador(cliente, almacen, almacenamiento):
    pedido = _partida(cliente, almacen, almacenamiento, cuantos=2)
    almacenamiento.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = _a_espera(cliente, pedido["pedido_id"])

    assert "SECRETO" not in respuesta.text
    assert respuesta.json()["ok"] is False and respuesta.json()["que_hacer"]


# ==========================================================================
# 4. LO ESTÁTICO DEL JAVASCRIPT
# ==========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_la_captura_trae_el_boton_de_mandar_el_pedido_a_espera():
    script = _script()
    paso = cuerpo_de_funcion(script, "const pintarPasoCaptura")

    assert "alMandarElPedido(guardado.pedido_id, guardado.nombre" in paso
    assert "botonDeAccion('Mandar a espera'" in paso
    # Se apaga con el motivo del servidor, no con uno escrito aquí.
    assert "guardado.se_puede_mandar_a_espera" in paso
    assert "guardado.motivo_para_no_mandar_a_espera" in paso
    assert (
        "pintarPasoCaptura(datos.pedidos, tacharRenglon, enviarPedido, posponer, "
        "mandarPedidoAEspera)"
    ) in script


def test_el_boton_llama_la_ruta_y_pinta_lo_que_devuelve_con_la_frase_del_servidor():
    funcion = cuerpo_de_funcion(_script(), "async function mandarPedidoAEspera")

    assert "'/api/pedido/' + pedidoId + '/posponer'" in funcion
    assert "method: 'POST'" in funcion
    assert "datos = conservarLoDeLaCarga(respuesta, datos);" in funcion
    assert "repintar();" in funcion
    # La frase llega hecha: aquí no se cuenta ni se conjuga.
    assert "respuesta.frase_de_mandar_a_espera" in funcion
    assert "notaDeFalla('pedido-accion', respuesta)" in funcion
    assert "boton.disabled = false;" in funcion


def test_un_pedido_vacio_sigue_en_la_columna_y_no_ofrece_enviar():
    paso = cuerpo_de_funcion(_script(), "const pintarPasoCaptura")

    # No se filtra: el borrador sin renglones se queda si trae su frase.
    assert "!!g.frase_del_pedido_vacio" in paso
    assert "g.frase_del_pedido_vacio" in paso.split("avance.textContent")[1]
    # Sin botón de enviar y sin la frase de qué significa enviar.
    assert re.search(
        r"if \(guardado\.es_borrador && guardado\.frase_del_pedido_vacio\) \{.*?"
        r"\} else if \(guardado\.es_borrador\) \{.*?botonDeAccion\(",
        paso,
        re.DOTALL,
    )
    assert "if (!sinRenglones) {" in paso
