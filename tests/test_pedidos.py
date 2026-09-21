"""Elegir proveedor y partir el sugerido en pedidos, de la tabla a la pantalla.

Lo puro —a quién se le pide, en cuántos pedidos se parte, cuánto suma cada
uno— vive en `tests/test_particion.py` y se prueba sin levantar nada. Aquí
están las otras tres mitades del ticket 20:

1. **Lo que se guarda**, contra el doble del almacenamiento, que se niega a lo
   mismo que la tabla porque llama a los mismos validadores.
2. **Lo que se ve**, contra la aplicación con sus cuatro bordes sustituidos.
3. **Lo que dicen los `.sql`**, leídos como texto — desde la torre no hay
   Postgres alcanzable, así que lo que cabe en el suite es revisar el archivo.

## Las cuatro cosas que este archivo vigila

1. **Partir dos veces no duplica nada.** La garantía es de la base
   (`ux_pedido_proveedor`), no de un `if`, y por eso se comprueba escribiendo
   dos veces y contando filas.
2. **Un renglón pertenece a un solo pedido**, incluso después de cambiar una
   elección y volver a partir: se mueve, no se agrega.
3. **El total es `NULL` en cuanto falta un precio**, jamás la suma de lo demás
   y jamás un cero.
4. **A QuePharma se le puede pedir aunque SICAR no lo conozca.** Es el caso que
   prueba que el puente puede faltar, y no un caso raro: no tiene fila en
   `marts.dim_proveedor` y nunca la ha tenido.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental import verificar as v
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import BORRADOR, ESTADOS_DEL_PEDIDO, Ventana
from continental.particion import PedidoPorArmar
from continental.precios import LecturaDePrecio, SESION_CADUCADA
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0005-elegir-proveedor-y-partir.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
# La pantalla entera —HTML, CSS y JavaScript— sale de `conftest.pantalla_completa`
# desde el ticket 28, que la separó en tres archivos: leer solo `index.html`
# dejaría las guardias de "esto NO está" revisando un texto sin el JavaScript.

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"


# ------------------------------------------------------------- utilidades


def _texto(ruta: Path) -> str:
    """El archivo como texto, exigiendo UTF-8. Igual que en `test_sql_del_pedido`."""
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    """El `.sql` **sin sus comentarios**, que es lo único que Postgres ejecuta.

    Los archivos de `sql/` de este repo son más prosa que sentencias: explican
    qué se descartó y por qué. Eso significa que casi cualquier cadena que uno
    quiera buscar está escrita *también* en un comentario —la migración 0005
    explica con todas sus letras el `UNIQUE (pedido_sugerido_id, proveedor_id)`
    que viene a quitar—, y una prueba que no los descarte afirmaría sobre la
    prosa en vez de sobre el DDL.

    Es la misma función que `verificar._sin_comentarios` hace del lado del
    código, y por la misma razón: un GRANT nombrado en un comentario no es un
    permiso.
    """
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=0.0,
        esta_activo=True,
        es_granel=False,
    )


def _poblar(almacen, cuantos: int = 2) -> None:
    almacen.catalogo_en_memoria = [
        _producto(n, f"750100000{n:04d}") for n in range(1, cuantos + 1)
    ]
    almacen.ventas_en_memoria = [_venta(HOY, n, 3) for n in range(1, cuantos + 1)]


def _lectura(
    proveedor: str, precio: str | None = None, existencia: str | None = None,
    motivo: str | None = None,
) -> LecturaDePrecio:
    """Lo que `guardar_precios` recibe: una lectura por proveedor."""
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="" if existencia is None else existencia,
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _elegir(cliente, renglon_id: int, proveedor: str, correo: str | None = CORREO):
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(
        f"/api/renglon/{renglon_id}/proveedor",
        json={"proveedor": proveedor},
        headers=cabeceras,
    )


def _renglon_guardado(almacenamiento, renglon_id: int):
    for lista in almacenamiento.listas:
        guardada = almacenamiento.leer(lista["negocio"], lista["fecha_del_pedido"])
        for renglon in guardada.renglones:
            if renglon.renglon_id == renglon_id:
                return renglon
    raise AssertionError(f"No hay ningún renglón {renglon_id} guardado.")


def _lista_con_precios(cliente, almacen, almacenamiento, precios_por_renglon):
    """Arma la lista del día y le congela los precios que se le pasen.

    `precios_por_renglon` va por POSICIÓN del renglón, no por id: los ids los
    entrega la secuencia y una prueba no debería depender de cuáles tocaron.
    """
    lista = cliente.get(RUTA).json()
    for i, lecturas in enumerate(precios_por_renglon):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], lecturas
        )
    return cliente.get(RUTA).json()


# ==========================================================================
# Casilla 1 — se elige proveedor por renglón, y la persona decide
# ==========================================================================


def test_el_mas_barato_con_existencia_viene_sugerido_por_omision(
    cliente, almacen, almacenamiento
):
    """Sin que nadie toque nada, cada renglón ya dice a quién se le pediría.

    Y lo dice **como sugerencia**, no como elección: `es_decision` es falso.
    Ésa es la mitad del ticket que se puede hacer mal sin que se vea — una
    sugerencia presentada como decisión hace imposible saber si alguien miró el
    renglón.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [[_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]],
    )

    eleccion = lista["renglones"][0]["eleccion"]
    assert eleccion["proveedor"] == "levic"
    assert eleccion["nombre"] == "LEVIC"
    assert eleccion["es_sugerencia"] is True
    assert eleccion["es_decision"] is False
    assert eleccion["certeza"] == "el más barato con existencia"


def test_la_persona_elige_y_queda_firmado(cliente, almacen, almacenamiento):
    """*Hay razones que el sistema no ve*: mínimo de pedido, entrega, crédito.

    Se guarda **a quién** y **quién lo decidió**, porque la pregunta que esto
    tiene que poder contestar es "¿por qué le compraste a NADRO habiendo LEVIC
    más barato?" y esa pregunta necesita a alguien a quien hacérsela. Es una
    firma y no un permiso (regla 3 de `CLAUDE.md`).
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [[_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]],
    )
    renglon_id = lista["renglones"][0]["renglon_id"]

    respuesta = _elegir(cliente, renglon_id, "nadro")

    assert respuesta.status_code == 200
    eleccion = respuesta.json()["renglon"]["eleccion"]
    assert eleccion["proveedor"] == "nadro"
    assert eleccion["es_decision"] is True
    assert eleccion["elegido_por"] == CORREO
    # Y la sugerencia sigue a la vista al lado: es lo que vuelve auditable la
    # elección, igual que "el sistema propuso 3" junto a un 10.
    assert eleccion["sugerido"] == "levic"
    assert eleccion["difiere_de_la_sugerencia"] is True

    guardado = _renglon_guardado(almacenamiento, renglon_id)
    assert guardado.proveedor_elegido == "nadro"
    assert guardado.elegido_por == CORREO
    assert guardado.elegido_en is not None
    assert guardado.fue_elegido is True


def test_confirmar_la_sugerencia_tambien_se_guarda_como_decision(
    cliente, almacen, almacenamiento
):
    """Quien confirma decide. Es la misma regla que `fue_ajustada` del ticket 11.

    Si esto no se guardara —"eligió lo mismo, no hace falta"— se perdería la
    única evidencia de que alguien revisó el renglón, y un renglón revisado y
    uno que nadie miró se verían idénticos.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "86.05", "40")]]
    )
    renglon_id = lista["renglones"][0]["renglon_id"]

    _elegir(cliente, renglon_id, "nadro")

    guardado = _renglon_guardado(almacenamiento, renglon_id)
    assert guardado.proveedor_elegido == "nadro"
    assert guardado.fue_elegido is True


def test_la_sugerencia_no_se_guarda_en_ninguna_columna(
    cliente, almacen, almacenamiento
):
    """**La decisión consciente del ticket**, y la que se aparta del 11.

    `cantidad_propuesta` se guarda porque no se puede recalcular; el proveedor
    sugerido sí se recalcula, de una función pura sobre una tabla de precios
    que solo crece. Guardarlo sería una segunda copia del mismo hecho, y una
    que envejece sin avisar en cuanto llega un precio más barato.

    Esta prueba lo demuestra por el lado que duele: la sugerencia **cambia** al
    llegar un precio nuevo, y la columna sigue vacía porque nadie ha decidido.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "146.38", "40")]]
    )
    renglon_id = lista["renglones"][0]["renglon_id"]
    assert lista["renglones"][0]["eleccion"]["proveedor"] == "nadro"
    assert _renglon_guardado(almacenamiento, renglon_id).proveedor_elegido is None

    almacenamiento.guardar_precios(
        NEGOCIO, renglon_id, [_lectura("levic", "86.05", "40")]
    )
    despues = cliente.get(RUTA).json()

    assert despues["renglones"][0]["eleccion"]["proveedor"] == "levic"
    assert _renglon_guardado(almacenamiento, renglon_id).proveedor_elegido is None


def test_una_decision_no_la_pisa_un_precio_mas_barato_que_llegue_despues(
    cliente, almacen, almacenamiento
):
    """La otra mitad: lo decidido **manda**, aunque el cálculo diga otra cosa.

    Y el sistema sigue diciendo lo que habría sugerido, para que la diferencia
    se pueda mirar y preguntar.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "146.38", "40")]]
    )
    renglon_id = lista["renglones"][0]["renglon_id"]
    _elegir(cliente, renglon_id, "nadro")

    almacenamiento.guardar_precios(
        NEGOCIO, renglon_id, [_lectura("levic", "1.00", "40")]
    )
    eleccion = cliente.get(RUTA).json()["renglones"][0]["eleccion"]

    assert eleccion["proveedor"] == "nadro"
    assert eleccion["es_decision"] is True
    assert eleccion["sugerido"] == "levic"
    assert eleccion["difiere_de_la_sugerencia"] is True


def test_con_la_lista_cerrada_ya_no_se_elige_proveedor(
    cliente, almacen, almacenamiento
):
    """Una lista `cerrada` quiere decir "ya se pidió lo que se iba a pedir".

    La condición vive en el `WHERE` del `UPDATE` —con la lista dentro—, igual
    que en el ajuste del ticket 11: comprobarla en Python y escribir después
    tiene una carrera en medio.
    """
    _poblar(almacen, 1)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    assert _elegir(cliente, renglon_id, "nadro").status_code == 409
    assert _renglon_guardado(almacenamiento, renglon_id).proveedor_elegido is None


def test_un_renglon_descartado_no_cambia_de_proveedor(
    cliente, almacen, almacenamiento
):
    """Descartado es "no se pide": elegirle proveedor diría dos cosas a la vez."""
    _poblar(almacen, 1)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/descartar")

    assert _elegir(cliente, renglon_id, "nadro").status_code == 409
    assert _renglon_guardado(almacenamiento, renglon_id).proveedor_elegido is None


def test_un_proveedor_que_doyle_no_conoce_se_rechaza_con_su_texto(
    cliente, almacen, almacenamiento
):
    """422 con los cuatro nombres, y no un 500 con una violación de restricción.

    El `CHECK` de la tabla no puede decirle al encargado cuáles son; este `if`
    sí. Es el mismo reparto de papeles que el cero de la cantidad en el 11.
    """
    _poblar(almacen, 1)
    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]

    respuesta = _elegir(cliente, renglon_id, "farmasana")

    assert respuesta.status_code == 422
    assert "QuePharma" in respuesta.json()["detalle"]
    assert _renglon_guardado(almacenamiento, renglon_id).proveedor_elegido is None


def test_el_doble_se_niega_a_una_eleccion_sin_firma(almacenamiento):
    """El doble rechaza lo mismo que `ck_renglon_eleccion`.

    Un doble más permisivo que la tabla deja el suite en verde y rompe en
    atlas. Por eso el rechazo vive en `revisar_el_renglon`, que llaman las dos
    implementaciones, y por eso hay un camino (`poner_el_proveedor`) donde se
    puede ver negarse.
    """
    lista = almacenamiento.abrir_el_dia(
        NEGOCIO,
        HOY,
        Ventana(desde=HOY, hasta=HOY),
        lambda: [
            Renglon(
                producto_id=1,
                clave="7501000000001",
                descripcion="PRODUCTO 1",
                piezas_vendidas=3.0,
                cantidad_propuesta=3,
                esta_en_el_catalogo=True,
                existencia=0.0,
                dias_de_cobertura=None,
                clasificacion="medicamento",
            )
        ],
    )
    renglon_id = lista.renglones[0].renglon_id

    with pytest.raises(ValueError, match="ck_renglon_eleccion"):
        almacenamiento.poner_el_proveedor(renglon_id, "nadro")

    with pytest.raises(ValueError, match="ck_renglon_eleccion"):
        almacenamiento.poner_el_proveedor(
            renglon_id, None, elegido_por="a@b", elegido_en=dt.datetime.now(dt.UTC)
        )


# ==========================================================================
# Casilla 2 — se parte en varios pedidos, uno por proveedor
# ==========================================================================


def test_la_lista_se_parte_en_un_pedido_por_proveedor(
    cliente, almacen, almacenamiento
):
    """Dos renglones, dos ganadores distintos, dos pedidos con sus totales."""
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [
            [_lectura("nadro", "10.00", "40")],
            [_lectura("levic", "5.00", "40")],
        ],
    )

    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")

    assert respuesta.status_code == 200
    pedidos = respuesta.json()["pedidos"]
    assert [p["proveedor"] for p in pedidos] == ["levic", "nadro"]
    assert {p["total_sin_iva"] for p in pedidos} == {"30.00", "15.00"}
    # Y cada renglón quedó dentro de UNO.
    ids = [r["pedido_id"] for r in respuesta.json()["renglones"]]
    assert len(set(ids)) == 2 and None not in ids


def test_los_pedidos_nacen_en_borrador(cliente, almacen, almacenamiento):
    """La tercera casilla, en su forma más directa.

    `borrador` es vocabulario nuevo: `CONTEXT.md` no tenía estados para el
    pedido, así que entró al glosario con este ticket. **Nacer en borrador
    siguió siendo cierto después del ticket 21**, que le agregó `enviado` como
    segundo estado: lo que cambió es a dónde se puede ir desde aquí, no dónde se
    empieza. Por eso la afirmación es sobre el primer valor de la tupla y no
    sobre su longitud — una prueba que se pusiera roja cada vez que el glosario
    crece obliga a tocarla sin haber aprendido nada.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.00", "40")]]
    )

    pedidos = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()

    assert pedidos["pedidos"][0]["estado"] == BORRADOR
    assert pedidos["pedidos"][0]["es_borrador"] is True
    assert ESTADOS_DEL_PEDIDO[0] == BORRADOR


def test_partir_dos_veces_no_duplica_nada(cliente, almacen, almacenamiento):
    """La pregunta del ticket: *¿qué pasa si se parte dos veces?*

    **No se duplica**, y la garantía es de la base y no de un `if`:
    `ux_pedido_proveedor` es "uno por proveedor dentro de la misma lista" y
    `_ABRIR_EL_PEDIDO` la nombra en su `ON CONFLICT ON CONSTRAINT`, así que la
    segunda partición reencuentra el pedido que ya estaba. Se comprueba
    contando filas escritas, no mirando la respuesta.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("nadro", "5.00", "40")]],
    )

    primera = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    segunda = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()

    assert len(almacenamiento.pedidos) == 1
    assert [p["pedido_id"] for p in primera["pedidos"]] == [
        p["pedido_id"] for p in segunda["pedidos"]
    ]
    assert segunda["pedidos"][0]["total_sin_iva"] == "45.00"


def test_cambiar_una_eleccion_y_volver_a_partir_mueve_el_renglon(
    cliente, almacen, almacenamiento
):
    """*¿Y si se parte, se cambia una elección, y se vuelve a partir?*

    El renglón **se mueve**, no se agrega: `pedido_id` es una columna, así que
    un renglón no puede quedar en dos pedidos. Y el pedido que se quedó sin
    renglones **sigue ahí** —el rol no tiene `DELETE`— con su total en `NULL`:
    un pedido vacío no cuesta `0.00`, cuesta "no se sabe".
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40"), _lectura("levic", "12.00", "40")]],
    )
    renglon_id = lista["renglones"][0]["renglon_id"]
    primera = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    de_nadro = primera["pedidos"][0]["pedido_id"]
    assert primera["pedidos"][0]["proveedor"] == "nadro"

    _elegir(cliente, renglon_id, "levic")
    segunda = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()

    por_clave = {p["proveedor"]: p for p in segunda["pedidos"]}
    assert set(por_clave) == {"nadro", "levic"}
    assert por_clave["nadro"]["pedido_id"] == de_nadro
    # El que se quedó vacío: sin total, y NO en cero.
    assert por_clave["nadro"]["total_sin_iva"] is None
    assert por_clave["nadro"]["hay_total"] is False
    assert por_clave["levic"]["total_sin_iva"] == "36.00"
    # Y el renglón está en UNO solo, el nuevo.
    assert _renglon_guardado(almacenamiento, renglon_id).pedido_id == (
        por_clave["levic"]["pedido_id"]
    )


def test_con_la_lista_cerrada_no_se_parte(cliente, almacen, almacenamiento):
    """Armar pedidos dentro de una lista ya pedida es lo que `cerrado` prohíbe.

    La condición vive en el `INSERT ... SELECT` contra `pedido_sugerido`, no en
    un `if`: cero filas es "no se escribió", igual que en el precio congelado.

    **Esto se aparta del descarte a propósito y conviene decirlo**: descartar
    hoy funciona aunque la lista esté cerrada, porque el ticket 10 solo le puso
    el estado del RENGLÓN a su `WHERE`. Aquí se sigue al ajuste —la opción
    estricta—, que es lo que el glosario sostiene.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.00", "40")]]
    )
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")

    assert respuesta.status_code == 409
    assert almacenamiento.pedidos == []


def test_un_pedido_que_ya_no_es_borrador_no_lo_toca_volver_a_partir(
    cliente, almacen, almacenamiento
):
    """La otra mitad de "se pueden modificar **mientras estén así**".

    El estado se pone a mano porque hoy **ningún código escribe otro**: el de
    "enviado" lo estrena el ticket 21. Es el mismo recurso con el que
    `poner_estado_del_renglon` deja probar `en tránsito` y `recibido` desde el
    ticket 10, y existe justo para esto — la garantía se escribe hoy y se puede
    comprobar hoy, en vez de descubrir dentro de un ticket que volver a partir
    vaciaba un pedido que ya estaba en el portal del proveedor.

    Lo protegen dos cosas, las dos en el `WHERE`: el `where pedido.estado =
    'borrador'` del `DO UPDATE` —el pedido no se reescribe— y el `EXISTS` de
    `_SOLTAR_RENGLONES` —sus renglones no se sueltan—.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.00", "40")]]
    )
    renglon_id = lista["renglones"][0]["renglon_id"]
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")
    pedido = almacenamiento.pedidos[0]
    pedido["estado"] = "enviado"
    pedido["total_sin_iva"] = Decimal("30.00")

    # Se cambia la elección y se vuelve a partir: el pedido enviado NO se toca.
    _elegir(cliente, renglon_id, "levic")
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")

    assert pedido["estado"] == "enviado"
    assert pedido["total_sin_iva"] == Decimal("30.00")
    assert _renglon_guardado(almacenamiento, renglon_id).pedido_id == pedido["pedido_id"]


def test_un_renglon_descartado_no_entra_en_ningun_pedido(
    cliente, almacen, almacenamiento
):
    """Ya se atendió: alguien lo miró y decidió no pedirlo.

    Se cuenta sobre `de_trabajo`, el mismo corte que el conteo de huecos del
    ticket 15 y por la misma razón.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("nadro", "5.00", "40")]],
    )
    cliente.post(f"/api/renglon/{lista['renglones'][1]['renglon_id']}/descartar")

    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()

    assert partida["pedidos"][0]["total_sin_iva"] == "30.00"
    descartado = _renglon_guardado(
        almacenamiento, lista["renglones"][1]["renglon_id"]
    )
    assert descartado.pedido_id is None


# ==========================================================================
# Casilla 5 — sin precio de ese proveedor se pide igual
# ==========================================================================


def test_un_renglon_sin_precio_de_ese_proveedor_se_pide_igual(
    cliente, almacen, almacenamiento
):
    """Y el total del pedido se vuelve `NULL`, **nunca la suma de los demás**.

    Un total parcial escrito en `pedido.total_sin_iva` se compara contra la
    factura del proveedor, no cuadra, y nadie sabe si falta mercancía o falta
    un precio. El parcial sí se enseña, aparte y con el conteo al lado: lo que
    se sabe no se esconde (regla 4 de `CLAUDE.md`).
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacen,
        almacenamiento,
        [
            [_lectura("nadro", "10.00", "40")],
            [_lectura("nadro", motivo=SESION_CADUCADA)],
        ],
    )
    # El segundo renglón no tiene precio de NADRO; se le elige a NADRO igual.
    _elegir(cliente, lista["renglones"][1]["renglon_id"], "nadro")

    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    pedido = partida["pedidos"][0]

    assert pedido["proveedor"] == "nadro"
    assert pedido["total_sin_iva"] is None
    assert pedido["hay_total"] is False
    # Los dos renglones están dentro: el sin precio TAMBIÉN se pide.
    assert {r["pedido_id"] for r in partida["renglones"]} == {pedido["pedido_id"]}

    previa = next(
        p for p in partida["particion"]["pedidos"] if p["proveedor"] == "nadro"
    )
    assert previa["renglones"] == 2
    assert previa["sin_precio"] == 1
    assert previa["parcial_sin_iva"] == "30.00"
    assert previa["total_sin_iva"] is None


def test_la_linea_sin_precio_va_marcada_y_nunca_en_cero(
    cliente, almacen, almacenamiento
):
    """"Precio desconocido" es una marca con su motivo, no un hueco mudo."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", motivo=SESION_CADUCADA)]]
    )
    _elegir(cliente, lista["renglones"][0]["renglon_id"], "nadro")

    previa = cliente.get(RUTA).json()["particion"]["pedidos"][0]
    linea = previa["lineas"][0]

    assert linea["precio"] is None
    assert linea["importe"] is None
    assert linea["tiene_precio"] is False
    assert linea["motivo"] == "precio desconocido"
    assert linea["cantidad"] == 3


# ==========================================================================
# El puente con SICAR
# ==========================================================================


def test_el_pedido_lleva_el_proveedor_id_de_sicar_cuando_lo_hay(
    cliente, almacen, almacenamiento
):
    """`nadro` -> 1, leído de `config/continental.yml`.

    El cruce lo estrena este ticket: hasta aquí la comparación hablaba en
    claves de Doyle y `pedidos.pedido` en `pro_id` de SICAR, y nada las
    cruzaba.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.00", "40")]]
    )

    pedido = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()[
        "pedidos"
    ][0]

    assert pedido["proveedor"] == "nadro"
    assert pedido["proveedor_id"] == 1
    assert pedido["tiene_puente"] is True


def test_a_quepharma_se_le_puede_pedir_aunque_sicar_no_lo_conozca(
    cliente, almacen, almacenamiento
):
    """**La pregunta del ticket**: ¿se puede pedir si el puente no existe? Sí.

    QuePharma no tiene fila en `marts.dim_proveedor` (22 filas, medido en atlas
    el 2026-09-19) porque la farmacia nunca le ha comprado. Con
    `proveedor_id NOT NULL` habría que inventarle un id o no poder pedirle: las
    dos cosas son peores que un `NULL` que dice la verdad (regla 4).
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.00", "40")]]
    )
    _elegir(cliente, lista["renglones"][0]["renglon_id"], "quepharma")

    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    pedido = partida["pedidos"][0]

    assert pedido["proveedor"] == "quepharma"
    assert pedido["proveedor_id"] is None
    assert pedido["tiene_puente"] is False
    assert almacenamiento.pedidos[0]["proveedor_id"] is None
    # Y se dice arriba, una vez, en vez de repetirlo en cada renglón.
    assert partida["particion"]["sin_puente"] == ["quepharma"]


def test_el_puente_viaja_a_la_pantalla_con_los_cuatro(cliente, almacen):
    """Los cuatro siempre, con su id o con su hueco.

    Si solo salieran los emparejados, un proveedor sin puente se vería como un
    proveedor que no existe — y de ahí sale el desplegable de cada renglón.
    """
    _poblar(almacen, 1)
    puente = cliente.get(RUTA).json()["puente"]

    assert [p["proveedor"] for p in puente] == ["nadro", "levic", "vicma", "quepharma"]
    assert {p["proveedor"]: p["proveedor_id"] for p in puente} == {
        "nadro": 1,
        "levic": 10,
        "vicma": 8,
        "quepharma": None,
    }


def test_el_puente_no_costo_una_tabla(cliente):
    """El esquema `pedidos` sigue teniendo CINCO tablas.

    Era una de las opciones —una tabla propia para el cruce— y se descartó: una
    tabla aquí cuesta `crear_tablas.sql`, una migración, **volver a correr
    `crear_rol.sql`**, `verificar_rol.sql` y `verificar.py` (ADR 0007), y el
    mapa son cuatro parejas que no cambian nunca.

    Se comprueba por donde de verdad se sabría: la lista de tablas que
    `verificar.py` saca **parseando `crear_rol.sql`**, que es el archivo que
    otorga los permisos de verdad.
    """
    assert v.tablas_de_pedidos_en(_texto(CREAR_ROL)) == (
        "pedido_sugerido",
        "renglon",
        "pedido",
        "precio_de_proveedor",
        "corrida_del_lote",
    )


# ==========================================================================
# Lo que dicen los .sql — sin Postgres, leídos como texto
# ==========================================================================


def test_el_ddl_y_la_migracion_existen_y_son_utf8():
    for ruta in (CREAR_TABLAS, MIGRACION):
        assert ruta.exists(), f"Falta {ruta.relative_to(RAIZ).as_posix()}."
        _texto(ruta)


def test_la_migracion_va_con_lf_y_no_con_crlf():
    """Un CRLF dentro de un CHECK guardaría `'borrador\\r'` y el primer INSERT
    rebotaría con una violación de restricción que nadie sabría explicar. Es lo
    que `.gitattributes` fija para `*.sql`, comprobado aquí sobre el archivo."""
    assert b"\r\n" not in MIGRACION.read_bytes()


def test_el_proveedor_id_de_sicar_admite_nulos_en_los_dos_archivos():
    """Con `NOT NULL`, a QuePharma no se le puede pedir. Los dos archivos igual.

    `crear_tablas.sql` es la base desde cero y la migración es la que ya
    existe: si solo uno lo dijera, atlas y la torre tendrían tablas distintas
    — y el que se descubre tarde es siempre el de atlas.
    """
    ddl = _sentencias(CREAR_TABLAS)
    cuerpo = ddl[ddl.index("CREATE TABLE IF NOT EXISTS pedidos.pedido (") :]
    cuerpo = cuerpo[: cuerpo.index("\n);")]
    assert re.search(r"proveedor_id\s+bigint\s*,", cuerpo), (
        "`pedidos.pedido.proveedor_id` tiene que admitir nulos: es el estado de "
        "QuePharma, que no tiene fila en marts.dim_proveedor."
    )
    assert "ALTER COLUMN proveedor_id DROP NOT NULL" in _sentencias(MIGRACION)


def test_uno_por_proveedor_esta_sobre_la_clave_de_doyle_en_los_dos_archivos():
    """La trampa que hunde este ticket si se hace mal.

    Con `proveedor_id` admitiendo nulos, un `UNIQUE` sobre él **deja de impedir
    lo que existe para impedir**: en Postgres dos nulos no se consideran
    iguales, así que dos pedidos a QuePharma entrarían los dos, sin un solo
    error que ver.
    """
    for ruta in (CREAR_TABLAS, MIGRACION):
        texto = _sentencias(ruta)
        assert "UNIQUE (pedido_sugerido_id, proveedor)" in texto, ruta.name
        assert "UNIQUE (pedido_sugerido_id, proveedor_id)" not in texto, ruta.name


def test_un_renglon_solo_cuelga_de_un_pedido_de_su_propia_lista():
    """"Un renglón pertenece a un solo pedido", defendido en la TABLA.

    Es una columna con una llave foránea, no una tabla de cruce. Y desde este
    ticket la llave lleva `pedido_sugerido_id`: sin él, un renglón del martes
    podía colgar de un pedido del lunes y el total de ese pedido contaba
    mercancía de otro día, sin violar nada.
    """
    for ruta in (CREAR_TABLAS, MIGRACION):
        texto = _sentencias(ruta)
        assert "FOREIGN KEY (pedido_id, pedido_sugerido_id, negocio)" in texto, ruta.name
        assert "FOREIGN KEY (pedido_id, negocio)" not in texto, ruta.name


def test_el_estado_del_pedido_del_ddl_es_el_que_escribe_el_codigo():
    """El CHECK de `crear_tablas.sql` y `ESTADOS_DEL_PEDIDO` dicen lo mismo.

    **La migración de este ticket NO entra en la comparación, y eso no es un
    descuido: una migración es un hecho del pasado.** La 0005 dejó el CHECK en
    `('borrador')` porque ése era el vocabulario del 2026-09-19, y el ticket 21
    pagó la suya —la 0006— para ampliarlo. Reescribir la 0005 para que dijera lo
    de hoy haría que una base que ya la corrió y otra que la corra mañana
    quedaran distintas sin que nada avise, que es exactamente la falla que el
    ADR 0003 describe.

    Lo que sí se exige de la 0005 es que **siga diciendo lo que dijo**: abajo.
    Quien vigila que `crear_tablas.sql` y la última migración coincidan es
    `test_envio.test_el_check_del_estado_se_amplio_en_los_dos_archivos`.
    """
    esperado = "CHECK (estado IN (" + ", ".join(
        f"'{e}'" for e in ESTADOS_DEL_PEDIDO
    ) + "))"
    assert esperado in _sentencias(CREAR_TABLAS), (
        f"{CREAR_TABLAS.name} no dice {esperado}. `ck_pedido_estado` y "
        "`almacenamiento.ESTADOS_DEL_PEDIDO` tienen que decir lo mismo."
    )
    assert "CHECK (estado IN ('borrador'))" in _sentencias(MIGRACION), (
        "La migración 0005 dejó de decir lo que dijo el día que se corrió. Una "
        "migración es un hecho del pasado: lo que amplía el CHECK es la 0006."
    )


def test_borrador_esta_en_el_glosario():
    """`CONTEXT.md` manda sobre el nombre de cualquier cosa (CLAUDE.md).

    El glosario definía los estados del pedido sugerido y los del renglón, y no
    los del pedido — porque hasta el ticket 20 un pedido no tenía estado. Con
    `borrador` en el código y no en el glosario, uno de los dos estaría mal.
    """
    glosario = (RAIZ / "CONTEXT.md").read_bytes().decode("utf-8")
    assert f"`{BORRADOR}`" in glosario


def test_la_eleccion_va_firmada_en_los_dos_archivos():
    """El par firma-y-hora, el mismo de `ck_renglon_descarte` y de `_ajuste`."""
    for ruta in (CREAR_TABLAS, MIGRACION):
        texto = _sentencias(ruta)
        assert "ck_renglon_eleccion" in texto, ruta.name
        assert "proveedor_elegido IS NOT NULL" in texto, ruta.name
        assert "elegido_por IS NOT NULL AND elegido_en IS NOT NULL" in texto, ruta.name


def test_no_hay_columna_para_lo_que_el_sistema_sugiere():
    """La decisión del ticket, comprobada por su ausencia.

    Una columna `proveedor_sugerido` sería una segunda copia de un hecho que se
    recalcula, y una que envejece sin avisar. Si alguien la agrega, esta prueba
    se pone roja y tiene que venir con su razón escrita.
    """
    ddl = _sentencias(CREAR_TABLAS)
    assert "proveedor_sugerido" not in ddl
    assert "sugerido_por" not in ddl


def test_las_transiciones_van_en_el_where_y_no_en_un_if():
    """El patrón del repo: dos pestañas no se pisan porque el `WHERE` lo impide.

    Se lee la sentencia como texto —desde la torre no hay Postgres— y se exige
    lo mismo que el ticket 11 exigió del ajuste: el renglón abierto **y** la
    lista abierta.
    """
    # `read_text` y no `read_bytes().decode()`: los `.py` de este repo van con
    # CRLF en la copia de trabajo (`.gitattributes` solo fija LF para .sql, .sh
    # y las unidades de systemd), y `read_text` normaliza los saltos. Sin eso
    # el recorte buscaría un fin de sentencia que en disco lleva un retorno de carro delante.
    codigo = ALMACENAMIENTO.read_text(encoding="utf-8")

    def sentencia(nombre: str) -> str:
        """El cuerpo de un `text(...)` de `almacenamiento.py`, sin su cierre."""
        desde = codigo.index(nombre + " = text(")
        return codigo[desde : codigo.index("\n)\n", desde)]

    elegir = sentencia("_ELEGIR_PROVEEDOR")
    assert "r.estado = 'abierto'" in elegir
    assert "p.estado = 'abierto'" in elegir

    abrir = sentencia("_ABRIR_EL_PEDIDO")
    assert "s.estado = 'abierto'" in abrir
    assert "where pedido.estado = 'borrador'" in abrir
    assert "on conflict on constraint ux_pedido_proveedor" in abrir


def test_el_verificador_lee_de_vuelta_lo_que_esta_migracion_cambia():
    """Las tres cosas se pueden ver bien en el archivo y estar mal en la base.

    `sql/verificar_rol.sql` es quien pregunta a Postgres de verdad; aquí solo
    se comprueba que las comprobaciones existan.
    """
    texto = _texto(VERIFICAR_ROL)
    assert "ux_pedido_proveedor" in texto
    assert "fk_renglon_pedido" in texto
    assert "ck_renglon_eleccion" in texto
    assert "ck_pedido_estado" in texto


# ==========================================================================
# Lo que la pantalla sabe pintar
# ==========================================================================


def test_la_pantalla_pinta_la_eleccion_y_la_particion():
    """HTML+JS plano, sin framework: lo que cabe probar es que el archivo lo diga.

    Se busca lo que **no se puede deducir de otra cosa**: la columna del
    proveedor, el bloque de la partición, su botón y las dos frases que
    distinguen una sugerencia de una decisión.
    """
    pantalla = pantalla_completa()
    for pedazo in (
        'id="particion"',
        "celdaDeProveedor",
        "pintarParticion",
        "elegirProveedor",
        "'/proveedor'",
        "/partir",
        "Lo sugiere el sistema",
        "Lo eligió ",
        "total sin saber",
        "Se le pide a",
    ):
        assert pedazo in pantalla, f"La pantalla no sabe pintar {pedazo!r}."


def test_la_pantalla_no_calcula_ningun_total():
    """Toda la aritmética vive en Python, donde hay pruebas.

    Es la misma regla que el ticket 14 fijó para el ahorro y la diferencia por
    pieza: el JavaScript pinta y no calcula. Si alguien sumara aquí, el total
    de un pedido pasaría por la coma flotante de JavaScript justo después de
    salir de un `numeric(12,2)`.
    """
    pantalla = pantalla_completa()
    bloque = pantalla[pantalla.index("const pintarParticion") :]
    bloque = bloque[: bloque.index("// Los descartados, aparte")]
    assert "total_sin_iva" in bloque
    assert "reduce(" not in bloque
    assert "parseFloat" not in bloque
    assert "Number(" not in bloque


def test_el_total_viaja_como_cadena_y_nunca_como_numero_de_json(
    cliente, almacen, almacenamiento
):
    """El JSON de JavaScript solo tiene `double`."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacen, almacenamiento, [[_lectura("nadro", "10.10", "40")]]
    )
    pedido = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()[
        "pedidos"
    ][0]
    assert pedido["total_sin_iva"] == "30.30"
    assert isinstance(pedido["total_sin_iva"], str)


# ==========================================================================
# El invariante que esperaba este ticket
# ==========================================================================


def test_el_invariante_del_envio_sigue_pendiente_por_una_sola_columna():
    """El hilo abierto 4 de `HANDOVER.md`, a medio cerrar y dicho así.

    `estado` ya existe desde este ticket; `enviado_por` llega con el 21. La
    tupla `COLUMNAS_QUE_EXIGE_EL_ENVIO` **no cambió**, que es exactamente lo
    que se quería: el ticket 20 usó el nombre que ya estaba escrito y el
    pendiente pasó de nombrar dos columnas a nombrar una sin que nadie tocara
    `verificar.py`.
    """
    assert v.COLUMNAS_QUE_EXIGE_EL_ENVIO == ("estado", "enviado_por")

    informe = v.revisar_pedidos_enviados([], {"pedido_id", "negocio", "estado"})
    assert informe.resultados[0].estado == v.PENDIENTE
    assert "enviado_por" in informe.resultados[0].resumen
    assert "estado" not in informe.resultados[0].resumen.replace("pedidos.pedido", "")


def test_con_las_dos_columnas_el_invariante_se_enciende_solo():
    """Y el día que el ticket 21 escriba `enviado_por`, empieza a revisar."""
    informe = v.revisar_pedidos_enviados(
        [v.FilaPedido(pedido_id=1, negocio=NEGOCIO, estado=BORRADOR)],
        {"pedido_id", "negocio", "estado", "enviado_por"},
    )
    assert informe.resultados[0].estado == v.OK
