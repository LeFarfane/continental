"""Enviar un pedido: `borrador` -> `enviado`, de la tabla a la pantalla (21).

**La palabra "enviar" miente y por eso este archivo empieza por ahí.**
Continental no le manda nada a ningún proveedor y no va a hacerlo (regla 1 de
`CLAUDE.md`, y el ADR 0002 lo dejó fuera de alcance con su razón). Lo que se
guarda es la declaración de una persona —*yo ya lo capturé en el portal*—,
firmada con el correo que verificó Access. El ADR 0009 tiene el porqué entero.

Los tres seams del repo, en este orden:

1. **Lo puro** —`particion.frase_del_envio` y `particion.motivo_para_no_enviar`:
   qué se le dice al encargado y cuándo se le niega el botón. Sin base, sin red
   y sin reloj.
2. **Lo que se guarda** —`almacenamiento.enviar_el_pedido` contra el doble, que
   se niega a lo mismo que la tabla porque llama a los mismos validadores.
3. **Lo que se ve** —la aplicación con sus cuatro bordes sustituidos, y los
   `.sql` leídos como texto: desde la torre no hay Postgres alcanzable.

## Las cinco cosas que este archivo vigila

1. **El total en pesos se ve ANTES de enviar**, y cuando no se puede saber lo
   dice con palabras en vez de escribir un `$0.00`.
2. **`borrador` -> `enviado` va firmado**: quién y cuándo, pareados por
   `ck_pedido_envio`. Una firma sin estado o un estado sin firma se rechazan.
3. **Un pedido `enviado` ya no se edita**, y eso lo sostiene el `WHERE` de cada
   sentencia y no un `if` de la pantalla.
4. **Al enviar, sus renglones pasan a `en tránsito`** — el estado que el
   glosario define como "ya se le pidió a un proveedor", y el que impide que el
   sugerido de mañana vuelva a proponerlos.
5. **La pantalla dice qué significa "enviado"**, con la frase hecha desde
   Python. Es la lección del ticket 15: una afirmación compuesta en el único
   archivo que ninguna prueba mira es una afirmación sin pruebas.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from continental import verificar as v
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    ENVIADO,
    ESTADOS_DEL_PEDIDO,
    PedidoGuardado,
    RENGLON_ABIERTO,
    RENGLON_EN_TRANSITO,
)
from continental.particion import (
    CONTINENTAL_NO_PIDE_EN_PORTALES,
    ENVIAR_ES_UNA_DECLARACION,
    TOTAL_ENVEJECIDO,
    frase_del_envio,
    motivo_para_no_enviar,
)
from continental.precios import LecturaDePrecio, SESION_CADUCADA

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0006-enviar-el-pedido.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
PANTALLA = RAIZ / "src" / "continental" / "web" / "static" / "index.html"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"


# ------------------------------------------------------------- utilidades


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    """El `.sql` **sin sus comentarios**, que es lo único que Postgres ejecuta.

    La misma función que `test_pedidos.py`, y por la misma razón: los archivos
    de `sql/` de este repo son más prosa que sentencias, así que casi cualquier
    cadena que uno busque está escrita *también* en un comentario.
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


def _poblar(almacen, cuantos: int = 1) -> None:
    almacen.catalogo_en_memoria = [
        _producto(n, f"750100000{n:04d}") for n in range(1, cuantos + 1)
    ]
    almacen.ventas_en_memoria = [_venta(HOY, n, 3) for n in range(1, cuantos + 1)]


def _lectura(
    proveedor: str,
    precio: str | None = None,
    existencia: str | None = None,
    motivo: str | None = None,
) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="" if existencia is None else existencia,
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _pedido(
    estado: str = BORRADOR,
    total: str | None = "1234.50",
    proveedor: str = "nadro",
    enviado_por: str | None = None,
) -> PedidoGuardado:
    """Un `PedidoGuardado` a mano, para las pruebas de lo puro."""
    return PedidoGuardado(
        pedido_id=7,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor=proveedor,
        proveedor_id=1,
        estado=estado,
        armado_en=dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC),
        total_sin_iva=None if total is None else Decimal(total),
        enviado_por=enviado_por,
        enviado_en=(
            None
            if enviado_por is None
            else dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.UTC)
        ),
    )


def _lista_con_precios(cliente, almacenamiento, precios_por_renglon):
    """Arma la lista del día y le congela los precios que se le pasen."""
    lista = cliente.get(RUTA).json()
    for i, lecturas in enumerate(precios_por_renglon):
        almacenamiento.guardar_precios(
            NEGOCIO, lista["renglones"][i]["renglon_id"], lecturas
        )
    return cliente.get(RUTA).json()


def _partir(cliente, lista) -> dict:
    return cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()


def _enviar(cliente, pedido_id: int, correo: str | None = CORREO):
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(f"/api/pedido/{pedido_id}/enviar", headers=cabeceras)


def _renglones_guardados(almacenamiento, pedido_sugerido_id: int):
    lista = almacenamiento._por_id(pedido_sugerido_id)
    return lista["renglones"]


# ==========================================================================
# LO PURO — qué se le dice al encargado, y cuándo se le niega el botón
# ==========================================================================


def test_la_frase_de_un_borrador_dice_que_continental_no_manda_nada():
    """**La quinta casilla, y la más fácil de dejar a medias.**

    La palabra "enviar" tiene un significado obvio que aquí es falso. Si la
    pantalla no lo desmiente en el mismo sitio donde está el botón, el encargado
    va a suponer —razonablemente— que apretarlo le manda el pedido a NADRO.
    """
    frase = frase_del_envio(_pedido())

    assert ENVIAR_ES_UNA_DECLARACION in frase
    assert CONTINENTAL_NO_PIDE_EN_PORTALES in frase
    assert "NADRO" in frase


def test_la_frase_de_un_pedido_enviado_dice_quien_lo_capturo():
    """Y no "se envió" en voz pasiva: el hecho ocurrió en otra pantalla.

    Lo único verdadero que Continental puede decir es quién lo declara. Es una
    firma y no un permiso (regla 3 de `CLAUDE.md`).
    """
    frase = frase_del_envio(_pedido(estado=ENVIADO, enviado_por=CORREO))

    assert CORREO in frase
    assert "capturó" in frase
    assert "NADRO" in frase
    # Y se vuelve a desmentir: el pedido enviado es justo donde alguien podría
    # leer "enviado" y entender que Continental se lo mandó al proveedor.
    assert "no se lo mandó a nadie" in frase


def test_un_borrador_con_renglones_se_puede_enviar():
    assert motivo_para_no_enviar(_pedido(), renglones_dentro=3) is None


def test_un_pedido_ya_enviado_no_se_vuelve_a_enviar():
    """No es un error del encargado: es el segundo clic de un botón que viajó.

    Se dice con palabras en vez de rebotar con un 409 mudo.
    """
    motivo = motivo_para_no_enviar(
        _pedido(estado=ENVIADO, enviado_por=CORREO), renglones_dentro=3
    )
    assert motivo is not None
    assert "ya" in motivo


def test_un_pedido_sin_renglones_no_se_puede_enviar():
    """El pedido que se vació al volver a partir (ticket 20) sigue existiendo.

    El rol no tiene `DELETE`, así que ahí se queda con total `NULL`. Marcarlo
    `enviado` diría "capturé esto en el portal" sobre nada — y sus renglones ya
    se fueron a otro pedido, así que ni siquiera hay qué pasar a `en tránsito`.
    """
    motivo = motivo_para_no_enviar(_pedido(total=None), renglones_dentro=0)
    assert motivo is not None
    assert "renglones" in motivo


def test_un_pedido_con_el_total_viejo_no_se_envia():
    """El hilo abierto 13 de `HANDOVER.md`, que le dejó este caso a este ticket.

    `pedido.total_sin_iva` solo se reescribe al partir, así que corregir la
    cantidad de un renglón que ya está dentro lo deja enseñando lo que costaba
    hace un rato. Esa cifra es la que alguien va a comparar contra la factura
    del proveedor: si no cuadra, nadie sabe si falta mercancía o si el número
    estaba rancio.

    **Se niega en vez de recalcular**, y las dos se consideraron: recalcular
    cambiaría el número después de que el encargado leyó el del botón, o sea
    enviaría un total que nadie vio.
    """
    motivo = motivo_para_no_enviar(_pedido(), renglones_dentro=2, total_envejecido=True)
    assert motivo == TOTAL_ENVEJECIDO
    assert "vuelve a partir" in motivo


def test_un_pedido_sin_total_SI_se_puede_enviar():
    """**La esquina que se hace mal sola**, y es lo contrario del caso anterior.

    Un pedido con una línea sin precio tiene `total_sin_iva = NULL`. La quinta
    casilla del ticket 20 dice que *un renglón sin precio de ese proveedor se
    puede pedir igual*: el encargado ve el precio de verdad en el portal
    mientras lo captura. Negar el envío volvería el precio de Doyle un requisito
    para operar la farmacia.
    """
    assert motivo_para_no_enviar(_pedido(total=None), renglones_dentro=2) is None


# ==========================================================================
# Casilla 1 — el total en pesos se ve ANTES de enviar
# ==========================================================================


def test_el_total_del_pedido_viaja_con_el_pedido_antes_de_enviarlo(
    cliente, almacen, almacenamiento
):
    """Para saber cuánto se va a comprometer. Como **cadena**, nunca un double."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.10", "40")]])
    partida = _partir(cliente, lista)

    pedido = partida["pedidos"][0]
    assert pedido["total_sin_iva"] == "30.30"
    assert isinstance(pedido["total_sin_iva"], str)
    assert pedido["hay_total"] is True
    assert pedido["se_puede_enviar"] is True
    assert pedido["motivo_para_no_enviar"] is None


def test_sin_total_el_pedido_lo_dice_y_se_puede_enviar_igual(
    cliente, almacen, almacenamiento
):
    """`null` y nunca `$0.00`: un cero se leería "este pedido no cuesta nada"."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(
        cliente, almacenamiento, [[_lectura("nadro", motivo=SESION_CADUCADA)]]
    )
    # Se le elige NADRO aunque no haya dado precio: se pide igual (ticket 20).
    cliente.post(
        f"/api/renglon/{lista['renglones'][0]['renglon_id']}/proveedor",
        json={"proveedor": "nadro"},
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    partida = _partir(cliente, cliente.get(RUTA).json())

    pedido = partida["pedidos"][0]
    assert pedido["total_sin_iva"] is None
    assert pedido["hay_total"] is False
    assert pedido["se_puede_enviar"] is True


# ==========================================================================
# Casilla 2 — borrador -> enviado, firmado con el correo de Access
# ==========================================================================


def test_enviar_cambia_el_estado_y_lo_firma(cliente, almacen, almacenamiento):
    """Quién y cuándo, pareados. Es la respuesta a "¿qué capturaste exactamente?"."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    respuesta = _enviar(cliente, pedido_id)

    assert respuesta.status_code == 200
    pedido = respuesta.json()["pedidos"][0]
    assert pedido["estado"] == ENVIADO
    assert pedido["fue_enviado"] is True
    assert pedido["es_borrador"] is False
    assert pedido["enviado_por"] == CORREO
    assert pedido["enviado_en"] is not None

    fila = almacenamiento.pedidos[0]
    assert fila["estado"] == ENVIADO
    assert fila["enviado_por"] == CORREO
    assert fila["enviado_en"] is not None


def test_el_enviado_en_viaja_con_zona(cliente, almacen, almacenamiento):
    """Sin la zona el navegador lo lee como hora local y el contenedor va en UTC.

    Seis horas de diferencia, que es la misma trampa que ya costó 11.7 puntos
    de crecimiento inventados, solo que del lado del cliente.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    enviado_en = _enviar(cliente, pedido_id).json()["pedidos"][0]["enviado_en"]

    assert dt.datetime.fromisoformat(enviado_en).tzinfo is not None


def test_sin_encabezado_de_access_la_firma_es_sin_identificar(
    cliente, almacen, almacenamiento
):
    """Que sí es un dato, y no una cadena vacía.

    La cadena vacía la rechaza `ck_pedido_enviado_por`: se compara igual que un
    dato y empareja con cualquier otra vacía. "sin-identificar" dice la verdad
    —alguien alcanzó el puerto sin pasar por el túnel— y se puede buscar.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    _enviar(cliente, pedido_id, correo=None)

    assert almacenamiento.pedidos[0]["enviado_por"] == "sin-identificar"


def test_la_firma_y_el_estado_van_pareados_en_el_doble(almacenamiento):
    """`ck_pedido_envio` escrito en Python, comprobado por donde se niega.

    Sin la mitad de ida, un pedido enviado no diría quién; sin la de vuelta,
    una firma colgada de un borrador diría que alguien envió lo que nadie envió.
    """
    from continental.almacenamiento import columnas_del_pedido, revisar_el_pedido

    columnas = columnas_del_pedido(NEGOCIO, 1, "nadro", 1, Decimal("10.00"))

    # Enviado sin firma.
    with pytest.raises(ValueError, match="ck_pedido_envio"):
        revisar_el_pedido({**columnas, "estado": ENVIADO})

    # Firma sin estado.
    with pytest.raises(ValueError, match="ck_pedido_envio"):
        revisar_el_pedido(
            {
                **columnas,
                "enviado_por": CORREO,
                "enviado_en": dt.datetime.now(dt.UTC),
            }
        )

    # Firma vacía.
    with pytest.raises(ValueError, match="ck_pedido_enviado_por"):
        revisar_el_pedido(
            {
                **columnas,
                "estado": ENVIADO,
                "enviado_por": "",
                "enviado_en": dt.datetime.now(dt.UTC),
            }
        )


def test_enviado_esta_en_el_glosario_y_en_la_tupla_del_codigo():
    """`CONTEXT.md` manda sobre el nombre de cualquier cosa (`CLAUDE.md`).

    El ticket 20 se negó a adelantar este nombre —el glosario no lo tenía— y
    dejó anotado el precio: una migración para ampliar `ck_pedido_estado`. Ésta
    es la mitad del pago que se ve en el glosario.
    """
    glosario = (RAIZ / "CONTEXT.md").read_bytes().decode("utf-8")
    assert f"`{ENVIADO}`" in glosario
    # El ticket 25 agregó `cancelado` DESPUÉS (ADR 0013); los dos de este
    # ticket siguen siendo los dos primeros y en este orden.
    assert ESTADOS_DEL_PEDIDO[:2] == (BORRADOR, ENVIADO)


# ==========================================================================
# Casilla 3 — un pedido enviado ya no se edita
# ==========================================================================


def test_un_pedido_enviado_no_se_vuelve_a_enviar(cliente, almacen, almacenamiento):
    """El segundo clic contesta 409 y no mueve la firma ni la hora.

    Igual que cerrar una lista ya cerrada: la condición vive en el `WHERE`, así
    que dos pestañas no se pisan.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]
    _enviar(cliente, pedido_id)
    cuando = almacenamiento.pedidos[0]["enviado_en"]

    segundo = _enviar(cliente, pedido_id, correo="otro@farmacia.mx")

    assert segundo.status_code == 409
    assert almacenamiento.pedidos[0]["enviado_por"] == CORREO
    assert almacenamiento.pedidos[0]["enviado_en"] == cuando


def test_volver_a_partir_no_toca_un_pedido_enviado(cliente, almacen, almacenamiento):
    """La garantía del ticket 20, ahora con un estado que el código sí escribe.

    Hasta hoy esto solo se podía probar poniendo el estado a mano. Es la
    diferencia entre una restricción escrita y una restricción ejercitada.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    renglon_id = lista["renglones"][0]["renglon_id"]
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]
    _enviar(cliente, pedido_id)

    # Se intenta cambiar la elección y volver a partir.
    cliente.post(
        f"/api/renglon/{renglon_id}/proveedor",
        json={"proveedor": "levic"},
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    _partir(cliente, lista)

    fila = almacenamiento.pedidos[0]
    assert fila["estado"] == ENVIADO
    assert fila["total_sin_iva"] == Decimal("30.00")
    # Y el renglón sigue dentro del pedido enviado: no se lo lleva otro.
    assert _renglones_guardados(almacenamiento, lista["pedido_sugerido_id"])[0][
        "pedido_id"
    ] == pedido_id


def test_un_renglon_enviado_ya_no_se_descarta_ni_se_ajusta(
    cliente, almacen, almacenamiento
):
    """La otra mitad de "ya no se edita", y viene gratis del estado del renglón.

    `en tránsito` no es `abierto`, así que las tres rutas que exigen un renglón
    abierto —descartar, corregir la cantidad, elegir proveedor— rebotan solas.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    renglon_id = lista["renglones"][0]["renglon_id"]
    _enviar(cliente, _partir(cliente, lista)["pedidos"][0]["pedido_id"])

    cabeceras = {"Cf-Access-Authenticated-User-Email": CORREO}
    assert cliente.post(
        f"/api/renglon/{renglon_id}/descartar", headers=cabeceras
    ).status_code == 409
    assert cliente.post(
        f"/api/renglon/{renglon_id}/cantidad", json={"cantidad": 9}, headers=cabeceras
    ).status_code == 409
    assert cliente.post(
        f"/api/renglon/{renglon_id}/proveedor",
        json={"proveedor": "levic"},
        headers=cabeceras,
    ).status_code == 409


def test_un_pedido_vacio_no_se_puede_enviar(cliente, almacen, almacenamiento):
    """El pedido que se quedó sin renglones al volver a partir.

    Sigue existiendo —el rol no tiene `DELETE`— con su total en `NULL`, y desde
    la pantalla se ve. Enviarlo diría "capturé esto en el portal" sobre nada.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    renglon_id = lista["renglones"][0]["renglon_id"]
    vacio = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    # Se cambia la elección y se vuelve a partir: el de NADRO se queda vacío.
    cliente.post(
        f"/api/renglon/{renglon_id}/proveedor",
        json={"proveedor": "levic"},
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    partida = _partir(cliente, lista)
    de_nadro = next(p for p in partida["pedidos"] if p["pedido_id"] == vacio)

    assert de_nadro["total_sin_iva"] is None
    assert de_nadro["se_puede_enviar"] is False
    assert _enviar(cliente, vacio).status_code == 409
    assert almacenamiento.pedidos[0]["estado"] == BORRADOR


def test_corregir_una_cantidad_despues_de_partir_bloquea_el_envio(
    cliente, almacen, almacenamiento
):
    """De punta a punta: el total viejo no llega al portal ni a la factura.

    El camino entero —partir, corregir la cantidad de un renglón que ya está
    dentro, intentar enviar— y las dos mitades de la respuesta: la pantalla lo
    dice antes (`se_puede_enviar` en falso con su motivo) y el `WHERE` lo impide
    después. Volver a partir lo desbloquea, que es el botón al que el motivo
    manda.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    renglon_id = lista["renglones"][0]["renglon_id"]
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    cliente.post(
        f"/api/renglon/{renglon_id}/cantidad",
        json={"cantidad": 9},
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    despues = cliente.get(RUTA).json()
    pedido = next(p for p in despues["pedidos"] if p["pedido_id"] == pedido_id)

    # El total guardado es el de antes —30.00, tres piezas— y la pantalla lo
    # dice en vez de enseñarlo como si fuera de ahora.
    assert pedido["total_sin_iva"] == "30.00"
    assert pedido["se_puede_enviar"] is False
    assert pedido["motivo_para_no_enviar"] == TOTAL_ENVEJECIDO
    assert _enviar(cliente, pedido_id).status_code == 409
    assert almacenamiento.pedidos[0]["estado"] == BORRADOR

    # Y volver a partir lo pone al día: 9 piezas a 10.00.
    _partir(cliente, lista)
    assert _enviar(cliente, pedido_id).status_code == 200
    assert almacenamiento.pedidos[0]["total_sin_iva"] == Decimal("90.00")


def test_un_pedido_de_otro_negocio_no_se_envia(cliente, almacen, almacenamiento):
    """El negocio va en el `WHERE` como en todas las demás (regla 7)."""
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]
    almacenamiento.pedidos[0]["negocio"] = "farmacia_99"

    assert _enviar(cliente, pedido_id).status_code == 409
    assert almacenamiento.pedidos[0]["estado"] == BORRADOR


# ==========================================================================
# Casilla 4 — al enviar, sus renglones pasan a `en tránsito`
# ==========================================================================


def test_al_enviar_los_renglones_pasan_a_en_transito(cliente, almacen, almacenamiento):
    """El estado que impide pedir dos veces lo mismo (`CONTEXT.md`).

    Hasta el ticket 20 **ningún código lo escribía**: un renglón dentro de un
    pedido en borrador sigue `abierto`, porque un borrador no se le ha pedido a
    nadie. Esto es lo que lo mueve.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("nadro", "20.00", "40")]],
    )
    pedido_id = _partir(cliente, lista)["pedidos"][0]["pedido_id"]

    despues = _enviar(cliente, pedido_id).json()

    assert [r["estado"] for r in despues["renglones"]] == [
        RENGLON_EN_TRANSITO,
        RENGLON_EN_TRANSITO,
    ]
    assert despues["en_transito"] == 2
    # Y la lista deja de tener renglones sin atender: los dos ya se pidieron.
    assert despues["tiene_renglones_sin_atender"] is False


def test_solo_pasan_a_transito_los_renglones_de_ESE_pedido(
    cliente, almacen, almacenamiento
):
    """Dos proveedores, un envío. El otro pedido se queda como estaba.

    Es la condición `r.pedido_id = :pedido_id` del `UPDATE`, y sin ella enviar
    a NADRO marcaría como pedido lo que todavía está en el borrador de LEVIC.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("levic", "20.00", "40")]],
    )
    partida = _partir(cliente, lista)
    de_nadro = next(p for p in partida["pedidos"] if p["proveedor"] == "nadro")

    despues = _enviar(cliente, de_nadro["pedido_id"]).json()

    por_estado = {r["renglon_id"]: r["estado"] for r in despues["renglones"]}
    assert sorted(por_estado.values()) == [RENGLON_ABIERTO, RENGLON_EN_TRANSITO]
    assert despues["en_transito"] == 1
    assert despues["tiene_renglones_sin_atender"] is True


def test_un_renglon_en_transito_no_vuelve_a_repartirse(
    cliente, almacen, almacenamiento
):
    """*No se vuelve a proponer mientras esté así* (`CONTEXT.md`), y tampoco a repartir.

    La vista previa de la partición deja de contarlo: si siguiera ahí, el botón
    "Volver a partir" prometería mover un renglón que el `WHERE` no puede mover
    —`r.estado = 'abierto'`— y la pantalla enseñaría dos veces el mismo dinero.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("levic", "20.00", "40")]],
    )
    partida = _partir(cliente, lista)
    de_nadro = next(p for p in partida["pedidos"] if p["proveedor"] == "nadro")

    despues = _enviar(cliente, de_nadro["pedido_id"]).json()

    assert [p["proveedor"] for p in despues["particion"]["pedidos"]] == ["levic"]
    assert despues["particion"]["renglones_repartidos"] == 1


def test_lo_ya_pedido_no_entra_en_la_cola_del_boton_de_completar(
    cliente, almacen, almacenamiento
):
    """Cuatro visitas a portales ajenos por mercancía que ya se pidió, no.

    Es el mismo criterio con el que un descartado queda fuera (ticket 19): ~9 s
    por proveedor y las credenciales del dueño. Aquí además el precio ya no
    cambia nada — el pedido está capturado.
    """
    _poblar(almacen, 2)
    lista = cliente.get(RUTA).json()
    # Nadie tiene precio: los dos son faltantes.
    assert lista["faltantes"]["cuantos"] == 2

    cabeceras = {"Cf-Access-Authenticated-User-Email": CORREO}
    cliente.post(
        f"/api/renglon/{lista['renglones'][0]['renglon_id']}/proveedor",
        json={"proveedor": "nadro"},
        headers=cabeceras,
    )
    partida = _partir(cliente, lista)
    despues = _enviar(cliente, partida["pedidos"][0]["pedido_id"]).json()

    assert despues["faltantes"]["cuantos"] == 1
    assert despues["conteo_de_precios"]["renglones"] == 1


# ==========================================================================
# Casilla 5 — la pantalla dice qué significa "enviado"
# ==========================================================================


def test_la_frase_de_que_significa_enviar_viaja_hecha_desde_python(
    cliente, almacen, almacenamiento
):
    """La lección del ticket 15, aplicada al sitio donde más duele.

    Una frase compuesta en el JavaScript a partir de banderas es una afirmación
    que ninguna prueba mira — y ésta es la que impide que el encargado crea que
    Continental le mandó el pedido a NADRO.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    partida = _partir(cliente, lista)

    assert ENVIAR_ES_UNA_DECLARACION in partida["pedidos"][0]["frase_del_envio"]

    despues = _enviar(cliente, partida["pedidos"][0]["pedido_id"]).json()
    assert CORREO in despues["pedidos"][0]["frase_del_envio"]


def test_la_pantalla_sabe_pintar_el_envio():
    """HTML+JS plano: lo que cabe probar es que el archivo lo diga.

    Se busca lo que **no se puede deducir de otra cosa**: el botón, la ruta, la
    frase que viene hecha y el total dentro del botón.
    """
    pantalla = _texto(PANTALLA)
    for pedazo in (
        "'/enviar'",
        "enviarPedido",
        "frase_del_envio",
        "se_puede_enviar",
        "motivo_para_no_enviar",
        "fue_enviado",
        # La hora sí la pinta el navegador —`instanteEnPalabras`—, y eso no
        # choca con lo de arriba: formatear una fecha no es componer una
        # afirmación. QUIÉN lo capturó no aparece aquí a propósito: viaja
        # dentro de `frase_del_envio`, hecha desde Python.
        "enviado_en",
    ):
        assert pedazo in pantalla, f"La pantalla no sabe pintar {pedazo!r}."


def test_la_pantalla_no_compone_la_frase_del_envio_ella_sola():
    """Ni la arma ni la deduce: la escribe. Y el total lo pinta, no lo suma."""
    pantalla = PANTALLA.read_text(encoding="utf-8")
    bloque = pantalla[pantalla.index("const pintarParticion") :]
    bloque = bloque[: bloque.index("// Los descartados, aparte")]

    assert "frase_del_envio" in bloque
    assert "capturé" not in bloque, (
        "La frase que explica qué significa 'enviado' se está componiendo en el "
        "JavaScript. Tiene que venir hecha de `particion.frase_del_envio`."
    )
    assert "reduce(" not in bloque
    assert "parseFloat" not in bloque


# ==========================================================================
# Lo que el RECORRIDO DEL NAVEGADOR cazó y el suite no (2026-09-21)
# ==========================================================================
#
# Las tres salieron de abrir la pantalla y apretar el botón, no de escribir
# pruebas. Es la tercera vez que pasa en este repo —el ticket 14 y el 15
# dejaron la misma nota— y por eso quedan fijadas aquí abajo.


def test_el_pedido_enviado_NO_desaparece_de_la_pantalla(
    cliente, almacen, almacenamiento
):
    """**El peor de los tres, y el suite lo habría dejado pasar entero.**

    Al enviar, los renglones del pedido pasan a `en tránsito` y salen de
    `por_repartir`, así que el pedido **desaparece de `particion.pedidos`** —que
    es el cálculo de lo que queda por hacer, y ahí está bien que no esté—. Pero
    la pantalla recorría esa lista para pintar el bloque entero: el pedido
    recién enviado se borraba de la vista, con su firma y su total, justo el que
    el encargado acaba de crear.

    Mercancía pedida que desaparece de la pantalla sin que nadie se entere es
    exactamente lo que `CONTEXT.md` prohíbe para los productos sin anaquel.

    La respuesta sigue trayéndolo en `pedidos`, que son **las filas que
    existen**; lo que cambió es que la pantalla pinta la unión de las dos
    listas. Aquí se comprueban los dos lados: que el dato viaja, y que el
    archivo sabe pintar lo que no está en la partición.
    """
    _poblar(almacen, 2)
    lista = _lista_con_precios(
        cliente,
        almacenamiento,
        [[_lectura("nadro", "10.00", "40")], [_lectura("levic", "20.00", "40")]],
    )
    partida = _partir(cliente, lista)
    de_nadro = next(p for p in partida["pedidos"] if p["proveedor"] == "nadro")

    despues = _enviar(cliente, de_nadro["pedido_id"]).json()

    # Salió de la partición, que es el cálculo de lo que queda por repartir...
    assert [p["proveedor"] for p in despues["particion"]["pedidos"]] == ["levic"]
    # ...y SIGUE en `pedidos`, que son las filas que existen, con todo lo suyo.
    enviado = next(p for p in despues["pedidos"] if p["proveedor"] == "nadro")
    assert enviado["fue_enviado"] is True
    assert enviado["total_sin_iva"] == "30.00"
    assert enviado["renglones"] == 1
    assert CORREO in enviado["frase_del_envio"]

    pantalla = PANTALLA.read_text(encoding="utf-8")
    assert "fueraDeLaParticion" in pantalla, (
        "La pantalla solo recorre `particion.pedidos`: un pedido enviado se "
        "borraría de la vista en cuanto sus renglones salgan de la partición."
    )


def test_un_renglon_en_transito_sigue_en_la_tabla_pero_no_se_puede_tocar(
    cliente, almacen, almacenamiento
):
    """No desaparece —hay que poder mirar qué se pidió— y deja de editarse.

    Las tres rutas que lo tocan exigen `abierto` en su `WHERE`, así que dejar
    los controles encendidos sería ofrecer tres botones que contestan 409. Eso
    enseña a ignorar los avisos, que es lo mismo que el campo de la cantidad ya
    había decidido para la lista cerrada.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    _enviar(cliente, _partir(cliente, lista)["pedidos"][0]["pedido_id"])

    despues = cliente.get(RUTA).json()

    # Sigue en la lista que la pantalla pinta, con su bandera resuelta.
    assert len(despues["renglones"]) == 1
    assert despues["renglones"][0]["esta_en_transito"] is True

    pantalla = PANTALLA.read_text(encoding="utf-8")
    assert "const editable = acciones.editable && !r.esta_en_transito" in pantalla
    assert "Ya se pidió: en tránsito." in pantalla


def test_una_lista_ya_pedida_entera_no_dice_que_falta_elegir_proveedor():
    """El cuarto hallazgo del recorrido, y el que peor consejo daba.

    Con todos los pedidos enviados no queda nada que partir, y la pantalla
    escribía *"Todavía no hay en qué partir esta lista · Elige a quién se le
    pide cada renglón"* — sobre una lista que ya se pidió entera. "Nada que
    partir" son dos situaciones opuestas y decirlas con la misma frase manda a
    rehacer un trabajo que ya está hecho.
    """
    pantalla = PANTALLA.read_text(encoding="utf-8")
    assert "Esta lista ya se pidió entera" in pantalla
    assert "No queda nada por repartir" in pantalla


def test_lo_ya_pedido_no_cuenta_como_renglon_por_atender():
    """"3 renglones por atender" con dos ya pedidos diría que queda trabajo.

    Es el número que se lee de un vistazo, y el bloque de descartados ya había
    pagado por la misma lección: cuando el número baja, la razón tiene que estar
    donde se lee el número.
    """
    pantalla = PANTALLA.read_text(encoding="utf-8")
    assert "const enTransito = visibles.filter(r => r.esta_en_transito).length" in pantalla
    assert "ya se pidió y sigue aquí, marcado como en tránsito." in pantalla


def test_la_hora_no_se_escribe_con_dos_puntos_al_final():
    """`instanteEnPalabras` ya termina en "a.m.", así que el punto extra sobra.

    Salía "armado lunes 21 de septiembre, 02:07 a.m..", y lo cazó el recorrido
    del navegador. Es cosmético y aun así se fija: el repo ya aprendió que lo
    que no tiene prueba vuelve.
    """
    pantalla = PANTALLA.read_text(encoding="utf-8")
    assert "instanteEnPalabras(guardado.armado_en) + '.'" not in pantalla
    assert "instanteEnPalabras(guardado.enviado_en) + '.'" not in pantalla
    assert "instanteEnPalabras(g.enviado_en) + '.'" not in pantalla


# ==========================================================================
# Lo que dicen los .sql — sin Postgres, leídos como texto
# ==========================================================================


def test_la_migracion_existe_y_es_utf8_y_va_con_lf():
    """Un CRLF dentro de un CHECK guardaría `'enviado\\r'`, y el primer UPDATE
    rebotaría con una violación de restricción que nadie sabría explicar."""
    assert MIGRACION.exists(), f"Falta {MIGRACION.relative_to(RAIZ).as_posix()}."
    _texto(MIGRACION)
    assert b"\r\n" not in MIGRACION.read_bytes()


def test_el_check_del_estado_se_amplio_en_los_dos_archivos():
    """El precio que el ticket 20 dejó anotado, pagado en los dos lados.

    `CREATE TABLE IF NOT EXISTS` **calla si la tabla ya existe con otra forma**:
    sin la migración, atlas se quedaría con el CHECK viejo y el primer envío
    rebotaría; sin el DDL, una base desde cero nacería sin poder enviar.

    **Desde el ticket 25 la 0006 ya no es la última palabra**, y esta prueba lo
    dice igual que `test_pedidos` lo dijo de la 0005: una migración es un hecho
    del pasado. La 0006 tiene que seguir diciendo lo que dijo —borrador y
    enviado—; `crear_tablas.sql` y la migración que amplía el CHECK después
    (la 0009, que agrega `cancelado`) dicen lo de hoy.
    """
    esperado = "CHECK (estado IN (" + ", ".join(
        f"'{e}'" for e in ESTADOS_DEL_PEDIDO
    ) + "))"
    ultima = SQL / "migraciones" / "0009-cancelar-y-devolver-lo-atrasado.sql"
    for ruta in (CREAR_TABLAS, ultima):
        assert esperado in _sentencias(ruta), (
            f"{ruta.name} no dice {esperado}. `ck_pedido_estado` y "
            "`almacenamiento.ESTADOS_DEL_PEDIDO` tienen que decir lo mismo."
        )
    assert "CHECK (estado IN ('borrador', 'enviado'))" in _sentencias(MIGRACION), (
        "La migración 0006 dejó de decir lo que dijo el día que se corrió. Una "
        "migración es un hecho del pasado: lo que amplía el CHECK es la 0009."
    )


def test_la_firma_del_envio_va_pareada_en_los_dos_archivos():
    """El mismo par de `ck_renglon_descarte`, `_ajuste` y `_eleccion`."""
    for ruta in (CREAR_TABLAS, MIGRACION):
        texto = _sentencias(ruta)
        assert "ck_pedido_envio" in texto, ruta.name
        assert "ck_pedido_enviado_por" in texto, ruta.name
        assert "enviado_por IS NOT NULL AND enviado_en IS NOT NULL" in texto, ruta.name


def test_el_envio_no_costo_una_tabla():
    """El esquema `pedidos` sigue teniendo CINCO, así que `crear_rol.sql` no se
    vuelve a correr: el GRANT es sobre la tabla entera y no hay permisos por
    columna. Se comprueba por donde de verdad se sabría."""
    assert v.tablas_de_pedidos_en(_texto(CREAR_ROL)) == (
        "pedido_sugerido",
        "renglon",
        "pedido",
        "precio_de_proveedor",
        "corrida_del_lote",
    )


def test_la_transicion_del_envio_va_en_el_where_y_no_en_un_if():
    """Dos pestañas no se pisan porque el `WHERE` lo impide, no porque el
    botón se deshabilite."""
    codigo = ALMACENAMIENTO.read_text(encoding="utf-8")

    def sentencia(nombre: str) -> str:
        desde = codigo.index(nombre + " = text(")
        return codigo[desde : codigo.index("\n)\n", desde)]

    enviar = sentencia("_ENVIAR_EL_PEDIDO")
    assert "p.estado = 'borrador'" in enviar
    assert "exists" in enviar, (
        "Falta el EXISTS sobre los renglones: un pedido vacío no se envía."
    )
    # Y NO exige que la lista siga abierta (ADR 0009): si lo exigiera, cerrar la
    # lista antes de marcar el último pedido dejaría sus renglones `abierto`
    # para siempre, y la recepción del ticket 26 no podría cruzarlos.
    assert "s.estado = 'abierto'" not in enviar

    transito = sentencia("_RENGLONES_A_TRANSITO")
    assert "r.estado = 'abierto'" in transito
    assert "r.pedido_id = :pedido_id" in transito


def test_el_verificador_lee_de_vuelta_lo_que_esta_migracion_cambia():
    """Las dos cosas se pueden ver bien en el archivo y estar mal en la base."""
    texto = _texto(VERIFICAR_ROL)
    assert "ck_pedido_envio" in texto
    assert "enviado_por" in texto


# ==========================================================================
# El invariante que este ticket enciende
# ==========================================================================


def test_el_invariante_del_envio_deja_de_estar_pendiente():
    """El hilo abierto 4 de `HANDOVER.md`, cerrado.

    Estaba escrito desde el ticket 17 esperando estas dos columnas **con estos
    nombres**, y por eso `COLUMNAS_QUE_EXIGE_EL_ENVIO` no cambió ni en el 20 ni
    en el 21. Deja de imprimirse como PENDIENTE en cada despliegue y empieza a
    revisar de verdad.
    """
    assert v.COLUMNAS_QUE_EXIGE_EL_ENVIO == ("estado", "enviado_por")

    columnas = {"pedido_id", "negocio", "estado", "enviado_por"}
    bien = v.revisar_pedidos_enviados(
        [v.FilaPedido(pedido_id=1, negocio=NEGOCIO, estado=ENVIADO, enviado_por=CORREO)],
        columnas,
    )
    assert bien.resultados[0].estado == v.OK

    mal = v.revisar_pedidos_enviados(
        [v.FilaPedido(pedido_id=1, negocio=NEGOCIO, estado=ENVIADO)], columnas
    )
    assert mal.resultados[0].estado == v.FALLA


def test_lo_que_el_codigo_escribe_es_lo_que_el_invariante_espera(
    cliente, almacen, almacenamiento
):
    """La costura entre el ticket 21 y el 17, comprobada de verdad.

    No basta con que el invariante sepa revisar: lo que este ticket **escribe**
    tiene que ser lo que él **lee**. Se le pasa la fila tal como quedó guardada.
    """
    _poblar(almacen, 1)
    lista = _lista_con_precios(cliente, almacenamiento, [[_lectura("nadro", "10.00", "40")]])
    _enviar(cliente, _partir(cliente, lista)["pedidos"][0]["pedido_id"])
    fila = almacenamiento.pedidos[0]

    informe = v.revisar_pedidos_enviados(
        [
            v.FilaPedido(
                pedido_id=fila["pedido_id"],
                negocio=fila["negocio"],
                estado=fila["estado"],
                enviado_por=fila["enviado_por"],
            )
        ],
        set(fila) | {"enviado_por"},
    )
    assert informe.resultados[0].estado == v.OK
