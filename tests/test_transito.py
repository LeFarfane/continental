"""En tránsito: la memoria de lo ya pedido (ticket 24, ADR 0012).

**El problema que arregla existe hoy.** Si el lunes se piden 3 piezas y llegan
el jueves, mientras tanto el producto sigue vendido y con existencia baja, y la
lista lo vuelve a proponer. El caso más directo ni siquiera necesita una venta
nueva: una lista que se envió y **no se cerró** deja el corte donde estaba, así
que la del día siguiente vuelve a recoger sus mismos días (ticket 09) — y lo
que ya se le pidió a NADRO se propone otra vez, sumado en el mismo número.

**La casilla cara es la tercera**, y la decisión está en el ADR 0012: lo que se
vende mientras un renglón está en tránsito **se queda en `marts.fct_ventas`**,
que es donde ya estaba, y lo que se guarda es **el ancla** —hasta qué día de
ventas repuso ese renglón, que es la `ventas_consideradas_hasta` de su lista y
ya existía—. Cuando el renglón se cierra (`recibido` o `recibido parcial`, los
estados de los tickets 26 y 27), la siguiente lista lee ese producto **desde el
día siguiente al ancla**, aunque el corte de la lista haya avanzado encima.
Ninguna tabla nueva, ninguna copia de una venta, y nada que envejezca cuando
las ventas llegan tarde.

Los tres seams del repo, en este orden:

1. **Lo puro** —`transito.py`—: qué producto se queda fuera, desde qué día
   vuelve, cuánto se ha vendido desde que se pidió y las frases que lo dicen.
   Sin base, sin red y sin reloj: el `ahora` entra por argumento.
2. **Lo que se guarda** —`lo_ya_pedido` contra el doble, y el SQL leído como
   texto—, más la columna `ventas_desde` del renglón que vuelve.
3. **Lo que se ve** —la ruta con sus bordes sustituidos, el lote, y la pantalla
   leída como texto—.

## Las cinco casillas, y dónde se vigila cada una

1. **Un renglón en tránsito no vuelve a proponerse** —
   `test_casilla_1_*`, por la ruta y por el lote.
2. **Se ven en algún lado, con su proveedor y la fecha de envío** —
   `test_casilla_2_*`.
3. **La venta durante el tránsito no se pierde** — `test_casilla_3_*`: de punta
   a punta, con la lista de en medio **cerrada** (que es cuando se perdería).
4. **Atenuados y con "pedido el martes, sin recibir"** — `test_casilla_4_*` y
   las de `cuando_se_envio`.
5. **Solo protege lo que pasó por Continental** — `test_casilla_5_*`.

Ninguna prueba de este archivo toca Postgres, la red, ni duerme.
"""

from __future__ import annotations

import ast
import datetime as dt
import logging
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    AlmacenamientoDelPedido,
    ESTADOS_DEL_RENGLON,
    ESTADOS_QUE_CIERRAN_EL_TRANSITO,
    LoYaPedido,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RenglonGuardado,
    Ventana,
    columnas_del_renglon,
    renglon_desde_columnas,
)
from continental.dobles import AlmacenFalso, AlmacenamientoFalso
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon, armar_la_lista
from continental.transito import (
    ADVERTENCIA_DE_LO_QUE_PROTEGE,
    ZONA_DE_LA_FARMACIA,
    MemoriaDeLoPedido,
    cuando_se_envio,
    en_camino,
    fecha_en_palabras,
    frase_de_la_ventana_propia,
    frase_de_la_firma,
    frase_de_lo_vendido,
    frase_de_ya_en_camino,
    frase_del_bloque,
    frase_del_transito,
    memoria_de_lo_pedido,
    vendido_desde_que_se_pidio,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0008-el-renglon-que-vuelve-dice-desde-cuando.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
TRANSITO = RAIZ / "src" / "continental" / "transito.py"
# La pantalla entera —HTML, CSS y JavaScript— sale de `conftest.pantalla_completa`
# desde el ticket 28, que la separó en tres archivos: leer solo `index.html`
# dejaría las guardias de "esto NO está" revisando un texto sin el JavaScript.
ADR = RAIZ / "docs" / "decisiones" / (
    "0012-lo-vendido-en-transito-se-queda-en-el-almacen-y-vuelve-al-recibirse.md"
)

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"

# Una semana real de calendario: lunes 14 a viernes 18 de septiembre de 2026.
LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)

#: La hora del centro de México, a mano, para construir instantes de prueba que
#: se lean igual que los lee la farmacia.
CENTRO = dt.timezone(dt.timedelta(hours=-6))


# ------------------------------------------------------------- utilidades


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    """El `.sql` sin sus comentarios: lo único que Postgres ejecuta."""
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def _sentencia_python(nombre: str) -> str:
    """El texto de una sentencia `text(...)` de `almacenamiento.py`."""
    fuente = _texto(ALMACENAMIENTO)
    inicio = fuente.index('"""', fuente.index(f"{nombre} = text(")) + 3
    fin = fuente.index('"""', inicio)
    return re.sub(r"--[^\n]*", "", fuente[inicio:fin])


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, descripcion: str | None = None) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=descripcion or f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=2.0,
        esta_activo=True,
        es_granel=False,
    )


def _renglon_guardado(
    renglon_id: int,
    producto_id: int,
    estado: str = RENGLON_EN_TRANSITO,
    cantidad: int = 3,
    piezas_recibidas: float | None = None,
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=producto_id,
            clave=f"750100000{producto_id:04d}",
            descripcion=f"PRODUCTO {producto_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        pedido_id=7,
        piezas_recibidas=piezas_recibidas,
    )


def _ya_pedido(
    producto_id: int,
    ventas_hasta: dt.date,
    estado: str = RENGLON_EN_TRANSITO,
    renglon_id: int | None = None,
    proveedor: str | None = "nadro",
    enviado_en: dt.datetime | None = None,
    cantidad: int = 3,
    piezas_recibidas: float | None = None,
) -> LoYaPedido:
    return LoYaPedido(
        renglon=_renglon_guardado(
            renglon_id if renglon_id is not None else producto_id * 10,
            producto_id,
            estado,
            cantidad,
            piezas_recibidas,
        ),
        pedido_sugerido_id=1,
        fecha_del_pedido=ventas_hasta,
        ventas_hasta=ventas_hasta,
        proveedor=proveedor,
        enviado_por=CORREO,
        enviado_en=enviado_en or dt.datetime(2026, 9, 15, 10, 0, tzinfo=CENTRO),
    )


def _lectura(proveedor: str, precio: str) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego=precio,
        precio=Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def _enviar_a_nadro(cliente, almacenamiento, lista: dict, productos: set[int]) -> dict:
    """Pone precio de NADRO a los renglones de `productos`, parte y envía.

    Los demás renglones se descartan antes de partir, para que el pedido de
    NADRO lleve solo lo que la prueba quiere en tránsito. Devuelve la lista tal
    como la deja el envío.
    """
    for r in lista["renglones"]:
        if r["producto_id"] in productos:
            almacenamiento.guardar_precios(
                NEGOCIO, r["renglon_id"], [_lectura("nadro", "12.50")]
            )
        else:
            cliente.post(
                f"/api/renglon/{r['renglon_id']}/descartar",
                headers={"Cf-Access-Authenticated-User-Email": CORREO},
            )
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    assert partida["ok"] is True, partida
    [pedido] = [p for p in partida["pedidos"] if p["proveedor"] == "nadro"]
    enviada = cliente.post(
        f"/api/pedido/{pedido['pedido_id']}/enviar",
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    ).json()
    assert enviada["ok"] is True, enviada
    return enviada


def _cerrar(cliente, lista: dict) -> None:
    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")
    assert respuesta.status_code == 200, respuesta.json()


def _recibir(almacenamiento, producto_id: int) -> None:
    """Pone en `recibido` el renglón en tránsito de ese producto.

    Es lo que el ticket 26 hace con un clic (`confirmar_la_recepcion`). Aquí
    va por `poner_estado_del_renglon` para probar el enganche sin compras de
    por medio; desde el 26 lleva firma, porque `ck_renglon_recepcion` la exige,
    y desde el 27 dice cuántas llegaron —todas las pedidas—, porque
    `ck_renglon_completo_o_parcial` también.
    """
    for lista in almacenamiento.listas:
        for fila in lista["renglones"]:
            if fila["producto_id"] == producto_id and fila["estado"] == RENGLON_EN_TRANSITO:
                pedidas = (
                    fila["cantidad_propuesta"]
                    if fila["cantidad_final"] is None
                    else fila["cantidad_final"]
                )
                almacenamiento.poner_estado_del_renglon(
                    fila["renglon_id"],
                    "recibido",
                    recibido_por="encargado@farmacia.mx",
                    recibido_en=dt.datetime(2026, 9, 16, 16, 0, tzinfo=dt.UTC),
                    piezas_recibidas=pedidas,
                )
                return
    raise AssertionError(f"No había renglón en tránsito del producto {producto_id}.")


def _productos(lista: dict) -> list[int]:
    return sorted(r["producto_id"] for r in lista["renglones"])


# ==========================================================================
# LO PURO — qué se queda fuera, desde cuándo vuelve, y cómo se dice
# ==========================================================================


def test_un_producto_en_transito_se_queda_fuera_de_la_lista():
    memoria = memoria_de_lo_pedido([_ya_pedido(1, LUNES)])
    ventana = Ventana(MARTES, MARTES)

    recortadas = memoria.recortar(
        [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)], ventana
    )

    assert [v.producto_id for v in recortadas] == [2]
    assert memoria.esta_en_camino(1)
    assert not memoria.esta_en_camino(2)


def test_sin_nada_pedido_la_memoria_recorta_exactamente_la_ventana():
    """La memoria vacía no cambia nada: es la lista del ticket 09, idéntica."""
    memoria = MemoriaDeLoPedido()
    ventana = Ventana(MARTES, MIERCOLES)
    ventas = [_venta(LUNES, 1, 5), _venta(MARTES, 1, 2), _venta(MIERCOLES, 2, 1)]

    assert memoria.recortar(ventas, ventana) == ventas[1:]
    assert memoria.desde_de_la_lectura(ventana) == MARTES


def test_en_transito_se_queda_fuera_aunque_la_ventana_vuelva_a_sus_dias():
    """El doble pedido que existe HOY, sin ninguna venta nueva.

    El lunes se envió a NADRO y la lista del lunes nadie la cerró: el corte no
    se movió y la ventana del martes arranca en el lunes (ticket 09, piso). Las
    3 piezas del lunes ya están pedidas; sin la memoria se proponen otra vez,
    sumadas con las del martes en un solo número que no deja ver el doble.
    """
    memoria = memoria_de_lo_pedido([_ya_pedido(1, LUNES)])
    ventana = Ventana(LUNES, MARTES)

    recortadas = memoria.recortar(
        [_venta(LUNES, 1, 3), _venta(MARTES, 1, 2), _venta(LUNES, 2, 1)], ventana
    )

    assert [v.producto_id for v in recortadas] == [2]


def test_al_recibirse_vuelve_desde_el_dia_siguiente_al_ancla_aunque_el_corte_avanzo():
    """**La casilla 3, en una función.** Lo retenido vuelve aunque la ventana ya no llegue.

    Pedido el lunes (ancla = lunes). El martes y el miércoles se vendió y la
    lista de esos días —sin el producto, que estaba en camino— se cerró: el
    corte está en el miércoles. El jueves llegó. La ventana del jueves es solo
    el jueves, y aun así el producto se lee desde el MARTES.
    """
    memoria = memoria_de_lo_pedido([_ya_pedido(1, LUNES, estado="recibido")])
    ventana = Ventana(JUEVES, JUEVES)
    ventas = [
        _venta(LUNES, 1, 3),  # lo que ya se pidió: no vuelve
        _venta(MARTES, 1, 2),
        _venta(MIERCOLES, 1, 1),
        _venta(JUEVES, 1, 1),
        _venta(MIERCOLES, 2, 9),  # de otro producto, fuera de la ventana: no entra
        _venta(JUEVES, 2, 1),
    ]

    recortadas = memoria.recortar(ventas, ventana)

    assert sum(v.cantidad for v in recortadas if v.producto_id == 1) == 4
    assert sum(v.cantidad for v in recortadas if v.producto_id == 2) == 1
    assert memoria.desde_de_la_lectura(ventana) == MARTES
    assert memoria.ventas_desde(1, ventana) == MARTES
    assert memoria.ventas_desde(2, ventana) is None


def test_al_recibirse_con_la_lista_sin_cerrar_no_vuelve_a_proponer_lo_ya_pedido():
    """El otro lado del ancla: a veces recorta HACIA ADELANTE.

    Pedido el lunes desde una lista que nadie cerró; llega el miércoles. La
    ventana del miércoles arranca en el lunes (el piso), pero lo del lunes ya
    se pidió y ya llegó: se propone desde el martes.
    """
    # Desde el 27 un parcial dice cuántas llegaron (2 de 3): sin eso no se sabe
    # cuánto faltó, y `LoYaPedido` truena en vez de adivinar.
    memoria = memoria_de_lo_pedido(
        [_ya_pedido(1, LUNES, estado="recibido parcial", piezas_recibidas=2)]
    )
    ventana = Ventana(LUNES, MIERCOLES)

    recortadas = memoria.recortar(
        [_venta(LUNES, 1, 3), _venta(MARTES, 1, 2), _venta(MIERCOLES, 1, 1)], ventana
    )

    assert sum(v.cantidad for v in recortadas) == 3
    assert memoria.ventas_desde(1, ventana) == MARTES


def test_el_ancla_que_coincide_con_la_ventana_no_se_anota():
    """`ventas_desde` es `None` cuando no dice nada que la lista no diga ya."""
    memoria = memoria_de_lo_pedido([_ya_pedido(1, LUNES, estado="recibido")])

    assert memoria.ventas_desde(1, Ventana(MARTES, JUEVES)) is None


def test_en_transito_le_gana_a_un_recibido_del_mismo_producto():
    """Se pidió, llegó, se volvió a pedir: el último manda y está en camino."""
    memoria = memoria_de_lo_pedido(
        [
            _ya_pedido(1, LUNES, estado="recibido", renglon_id=10),
            _ya_pedido(1, MIERCOLES, renglon_id=11),
        ]
    )

    assert memoria.esta_en_camino(1)
    assert memoria.recortar([_venta(JUEVES, 1, 5)], Ventana(JUEVES, JUEVES)) == []


def test_de_dos_recibidos_manda_el_ancla_mas_reciente():
    memoria = memoria_de_lo_pedido(
        [
            _ya_pedido(1, LUNES, estado="recibido", renglon_id=10),
            _ya_pedido(1, MIERCOLES, estado="recibido", renglon_id=11),
        ]
    )

    assert memoria.ventas_desde(1, Ventana(VIERNES, VIERNES)) == JUEVES


def test_los_estados_que_cierran_el_transito_son_los_del_glosario():
    """El enganche de los tickets 26 y 27, con nombre.

    `recibido` y `recibido parcial` ya están en el glosario y en el CHECK. `en
    tránsito` NO está aquí: es lo que se cierra, no lo que cierra.
    """
    assert set(ESTADOS_QUE_CIERRAN_EL_TRANSITO) == {"recibido", "recibido parcial"}
    assert set(ESTADOS_QUE_CIERRAN_EL_TRANSITO) <= set(ESTADOS_DEL_RENGLON)
    assert RENGLON_EN_TRANSITO not in ESTADOS_QUE_CIERRAN_EL_TRANSITO


def test_un_estado_que_no_es_ya_pedido_no_entra_a_la_memoria():
    """Un abierto o un descartado que se cuele no puede sacar nada de la lista."""
    memoria = memoria_de_lo_pedido(
        [_ya_pedido(1, LUNES, estado=RENGLON_ABIERTO), _ya_pedido(2, LUNES, estado=RENGLON_DESCARTADO)]
    )

    assert not memoria.esta_en_camino(1)
    assert memoria.ventas_desde(1, Ventana(MARTES, MARTES)) is None
    assert memoria.ventas_desde(2, Ventana(MARTES, MARTES)) is None


def test_en_camino_son_solo_los_que_siguen_en_transito_en_su_orden():
    lo_pedido = [
        _ya_pedido(1, LUNES, renglon_id=10),
        _ya_pedido(2, LUNES, estado="recibido", renglon_id=11),
        _ya_pedido(3, MARTES, renglon_id=12),
    ]

    assert [p.renglon.renglon_id for p in en_camino(lo_pedido)] == [10, 12]


def test_lo_vendido_desde_que_se_pidio_cuenta_desde_el_dia_siguiente_al_ancla():
    lo_pedido = [_ya_pedido(1, LUNES, renglon_id=10), _ya_pedido(2, MARTES, renglon_id=20)]
    ventas = [
        _venta(LUNES, 1, 3),  # el día que se pidió: ya estaba en el pedido
        _venta(MARTES, 1, 2),
        _venta(MIERCOLES, 1, 0.5),
        _venta(MARTES, 2, 4),  # ancla del 2: no cuenta
        _venta(MIERCOLES, 3, 9),  # de nadie en camino
    ]

    vendido = vendido_desde_que_se_pidio(ventas, lo_pedido, hasta=MIERCOLES)

    assert vendido == {10: 2.5, 20: 0.0}


def test_la_zona_de_la_farmacia_es_la_del_centro_sin_horario_de_verano():
    """UTC-6 fijo. México quitó el horario de verano el 30 de octubre de 2022.

    Fija y no `ZoneInfo`: la torre no tiene `tzdata` (lo midió el ticket 23) y
    un `ZoneInfo('America/Mexico_City')` truena ahí.
    """
    assert ZONA_DE_LA_FARMACIA.utcoffset(None) == dt.timedelta(hours=-6)


def test_cuando_se_envio_hoy_y_ayer():
    ahora = dt.datetime(2026, 9, 15, 12, 0, tzinfo=CENTRO)  # martes

    assert cuando_se_envio(dt.datetime(2026, 9, 15, 8, 0, tzinfo=CENTRO), ahora) == "hoy"
    assert cuando_se_envio(dt.datetime(2026, 9, 14, 19, 0, tzinfo=CENTRO), ahora) == "ayer"


@pytest.mark.parametrize(
    ("dia", "palabra"),
    [
        (dt.date(2026, 9, 16), "el miércoles"),
        (dt.date(2026, 9, 17), "el jueves"),
        (dt.date(2026, 9, 18), "el viernes"),
        (dt.date(2026, 9, 19), "el sábado"),
        (dt.date(2026, 9, 20), "el domingo"),
    ],
)
def test_dentro_de_la_semana_es_el_dia_de_la_semana_en_palabras(dia, palabra):
    """"Pedido el martes": el día de la semana, que en seis días no se repite."""
    enviado = dt.datetime(dia.year, dia.month, dia.day, 10, 0, tzinfo=CENTRO)
    ahora = dt.datetime(2026, 9, 22, 10, 0, tzinfo=CENTRO)  # martes 22

    assert cuando_se_envio(enviado, ahora) == palabra


def test_a_siete_dias_o_mas_el_dia_de_la_semana_ya_no_alcanza():
    """"El martes" hace ocho días se lee como el martes de hoy: va la fecha.

    Y va con cuántos días lleva, que es lo que el ticket 25 va a comparar
    contra su N para señalarlo como vencido.
    """
    enviado = dt.datetime(2026, 9, 8, 10, 0, tzinfo=CENTRO)  # martes 8
    ahora = dt.datetime(2026, 9, 21, 10, 0, tzinfo=CENTRO)  # lunes 21

    assert cuando_se_envio(enviado, ahora) == "el martes 8 de septiembre (hace 13 días)"


def test_exactamente_siete_dias_tambien_lleva_la_fecha():
    enviado = dt.datetime(2026, 9, 15, 10, 0, tzinfo=CENTRO)
    ahora = dt.datetime(2026, 9, 22, 10, 0, tzinfo=CENTRO)

    assert cuando_se_envio(enviado, ahora) == "el martes 15 de septiembre (hace 7 días)"


def test_de_otro_anio_lleva_el_anio():
    enviado = dt.datetime(2025, 12, 30, 10, 0, tzinfo=CENTRO)
    ahora = dt.datetime(2026, 1, 12, 10, 0, tzinfo=CENTRO)

    assert cuando_se_envio(enviado, ahora) == (
        "el martes 30 de diciembre de 2025 (hace 13 días)"
    )


def test_el_dia_de_la_semana_es_el_de_la_farmacia_y_no_el_de_utc():
    """**La trampa de siempre, del lado del instante.**

    `enviado_en` es `timestamptz` y el contenedor corre en UTC. Un envío del
    martes a las 20:00 en el mostrador son las 02:00 del MIÉRCOLES en UTC: sin
    convertir, la pantalla diría "pedido el miércoles" sobre algo que se pidió
    el martes.
    """
    enviado_utc = dt.datetime(2026, 9, 16, 2, 0, tzinfo=dt.UTC)  # martes 20:00 local
    ahora_utc = dt.datetime(2026, 9, 18, 16, 0, tzinfo=dt.UTC)  # viernes 10:00 local

    assert cuando_se_envio(enviado_utc, ahora_utc) == "el martes"


def test_un_envio_con_el_reloj_un_poco_adelante_es_hoy_y_no_un_futuro():
    ahora = dt.datetime(2026, 9, 15, 12, 0, tzinfo=CENTRO)
    enviado = ahora + dt.timedelta(seconds=3)

    assert cuando_se_envio(enviado, ahora) == "hoy"


def test_sin_hora_de_envio_se_dice_y_no_se_inventa():
    """Un tránsito sin `enviado_en` no sale de la pantalla: lo pondría alguien a mano."""
    ahora = dt.datetime(2026, 9, 15, 12, 0, tzinfo=CENTRO)

    assert cuando_se_envio(None, ahora) == "sin fecha de envío escrita"


def test_la_frase_de_la_casilla_4():
    ahora = dt.datetime(2026, 9, 18, 10, 0, tzinfo=CENTRO)  # viernes
    enviado = dt.datetime(2026, 9, 15, 10, 0, tzinfo=CENTRO)  # martes

    assert frase_del_transito("NADRO", enviado, ahora) == (
        "Pedido el martes a NADRO, sin recibir."
    )
    assert frase_del_transito("LEVIC", ahora, ahora) == "Pedido hoy a LEVIC, sin recibir."


def test_la_firma_del_envio_dice_quien_cuando_y_de_que_lista():
    """La casilla 2 entera: quién lo marcó, a qué hora de la farmacia, y de dónde salió.

    Salió del recorrido del navegador: el JavaScript la armaba pegando un punto
    a `instanteEnPalabras`, que ya termina en "a.m.", y escribía "a.m..". Es el
    mismo tropiezo del ticket 21. Ahora es de Python y tiene prueba.
    """
    ya = _ya_pedido(
        1, LUNES, enviado_en=dt.datetime(2026, 9, 15, 2, 30, tzinfo=dt.UTC)
    )

    assert frase_de_la_firma(ya) == (
        "Lo marcó como enviado encargado@farmacia.mx el lunes 14 de septiembre "
        "a las 20:30. Salió de la lista del lunes 14 de septiembre."
    )
    assert ".." not in frase_de_la_firma(ya)


def test_la_firma_sin_hora_ni_correo_lo_dice():
    ya = LoYaPedido(
        renglon=_renglon_guardado(10, 1),
        pedido_sugerido_id=1,
        fecha_del_pedido=LUNES,
        ventas_hasta=LUNES,
        proveedor=None,
        enviado_por=None,
        enviado_en=None,
    )

    assert frase_de_la_firma(ya) == (
        "Nadie quedó escrito como quien lo marcó enviado, y no quedó la hora. "
        "Salió de la lista del lunes 14 de septiembre."
    )


def test_sin_proveedor_se_dice_y_no_se_inventa():
    ahora = dt.datetime(2026, 9, 18, 10, 0, tzinfo=CENTRO)

    assert frase_del_transito(None, ahora, ahora) == (
        "Pedido hoy a un proveedor que no quedó escrito, sin recibir."
    )


@pytest.mark.parametrize(
    ("piezas", "frase"),
    [
        (0.0, "No se ha vendido desde que se pidió."),
        (1.0, "Desde que se pidió se vendió 1 pieza más: no se pierde, se propone al recibirlo."),
        (4.0, "Desde que se pidió se vendieron 4 piezas más: no se pierden, se proponen al recibirlo."),
        (2.5, "Desde que se pidió se vendieron 2.5 piezas más: no se pierden, se proponen al recibirlo."),
        (None, "No se pudo leer cuánto se ha vendido desde que se pidió."),
    ],
)
def test_la_frase_de_lo_vendido_mientras_viene_en_camino(piezas, frase):
    assert frase_de_lo_vendido(piezas) == frase


def test_la_frase_del_bloque_cuenta_y_nunca_calla():
    assert frase_del_bloque(0) == "Nada de listas anteriores viene en camino."
    assert frase_del_bloque(1) == (
        "1 renglón de listas anteriores viene en camino: no se vuelve a proponer "
        "hasta que se reciba."
    )
    assert frase_del_bloque(3) == (
        "3 renglones de listas anteriores vienen en camino: no se vuelven a "
        "proponer hasta que se reciban."
    )


def test_casilla_5_la_advertencia_dice_lo_que_NO_protege():
    """Solo protege lo que se envió desde aquí. Lo de fuera se propone otra vez."""
    assert "Continental" in ADVERTENCIA_DE_LO_QUE_PROTEGE
    assert "por fuera" in ADVERTENCIA_DE_LO_QUE_PROTEGE
    assert "otra vez" in ADVERTENCIA_DE_LO_QUE_PROTEGE


def test_la_fecha_en_palabras_no_depende_del_locale():
    assert fecha_en_palabras(dt.date(2026, 9, 15)) == "el martes 15 de septiembre"
    assert fecha_en_palabras(dt.date(2026, 3, 1)) == "el domingo 1 de marzo"


def test_el_renglon_que_vuelve_dice_desde_cuando():
    ventana = Ventana(JUEVES, JUEVES)

    assert frase_de_la_ventana_propia(MARTES, ventana) == (
        "Trae también lo vendido desde el martes 15 de septiembre, mientras "
        "venía en camino: esas ventas no se perdieron."
    )
    assert frase_de_la_ventana_propia(MIERCOLES, Ventana(LUNES, MIERCOLES)) == (
        "Solo cuenta lo vendido desde el miércoles 16 de septiembre: lo anterior "
        "ya venía en un pedido."
    )
    assert frase_de_la_ventana_propia(None, ventana) is None
    assert frase_de_la_ventana_propia(JUEVES, ventana) is None


def test_un_renglon_de_hoy_cuyo_producto_ya_viene_en_camino_se_avisa():
    """El caso que la memoria no alcanza: la lista ya estaba armada.

    Se envía un pedido desde una lista vencida DESPUÉS de que la de hoy se
    armó con ese mismo producto dentro. La lista de hoy ya no se recalcula
    (lo que se muestra es lo guardado), así que lo único honesto es decirlo.
    """
    ahora = dt.datetime(2026, 9, 17, 10, 0, tzinfo=CENTRO)
    ya = _ya_pedido(1, LUNES, enviado_en=dt.datetime(2026, 9, 15, 10, 0, tzinfo=CENTRO))

    assert frase_de_ya_en_camino(ya, ahora) == (
        "Ya viene en camino: se le pidió el martes a NADRO y no ha llegado. "
        "Pedirlo aquí también sería pedirlo dos veces."
    )


def test_transito_es_puro_sin_reloj_sin_base_y_sin_red():
    """El `ahora` entra por argumento: aquí no se mira el reloj ni se abre nada."""
    fuente = _texto(TRANSITO)
    arbol = ast.parse(fuente)
    importados = {
        (n.module or "") for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)
    } | {a.name for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names}

    assert not any(m.startswith(("sqlalchemy", "httpx", "fastapi")) for m in importados)
    assert ".now(" not in fuente
    assert "date.today(" not in fuente


# ==========================================================================
# armar_la_lista — la memoria entra por argumento y es obligatoria
# ==========================================================================


def test_armar_la_lista_exige_la_memoria():
    """Olvidarla sería armar sin protección y en silencio: que truene."""
    with pytest.raises(TypeError):
        armar_la_lista(AlmacenFalso(), Ventana(MARTES, MARTES))  # type: ignore[call-arg]


def test_armar_la_lista_deja_fuera_lo_que_viene_en_camino():
    almacen = AlmacenFalso(
        catalogo_en_memoria=[_producto(1), _producto(2)],
        ventas_en_memoria=[_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)],
    )

    lista = armar_la_lista(
        almacen, Ventana(MARTES, MARTES), memoria_de_lo_pedido([_ya_pedido(1, LUNES)])
    )

    assert [r.producto_id for r in lista.renglones] == [2]


def test_armar_la_lista_trae_lo_retenido_con_su_fecha_y_en_una_sola_lectura():
    llamadas: list[tuple[dt.date, dt.date]] = []
    almacen = AlmacenFalso(
        catalogo_en_memoria=[_producto(1), _producto(2)],
        ventas_en_memoria=[
            _venta(dt.date(2026, 7, 1), 1, 7),  # muy atrás: antes del ancla
            _venta(dt.date(2026, 7, 2), 1, 2),  # retenida (fuera del ritmo)
            _venta(JUEVES, 1, 1),
            _venta(JUEVES, 2, 1),
        ],
    )
    original = almacen.ventas
    almacen.ventas = lambda desde, hasta: llamadas.append((desde, hasta)) or original(desde, hasta)

    lista = armar_la_lista(
        almacen,
        Ventana(JUEVES, JUEVES),
        memoria_de_lo_pedido([_ya_pedido(1, dt.date(2026, 7, 1), estado="recibido")]),
    )
    por_producto = {r.producto_id: r for r in lista.renglones}

    assert llamadas == [(dt.date(2026, 7, 2), JUEVES)], (
        "La lectura tiene que cubrir lo retenido, y ser una sola."
    )
    assert por_producto[1].piezas_vendidas == 3
    assert por_producto[1].ventas_desde == dt.date(2026, 7, 2)
    assert por_producto[2].ventas_desde is None


# ==========================================================================
# LO QUE SE GUARDA — lo ya pedido, contra el doble y como SQL
# ==========================================================================


def _lista_con(almacenamiento, fecha: dt.date, productos, negocio: str = NEGOCIO):
    renglones = [
        Renglon(
            producto_id=p,
            clave=f"750100000{p:04d}",
            descripcion=f"PRODUCTO {p}",
            piezas_vendidas=3.0,
            cantidad_propuesta=3,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        )
        for p in productos
    ]
    return almacenamiento.insertar_la_lista(negocio, fecha, Ventana(fecha, fecha), renglones)


def _enviar_en_el_doble(almacenamiento, lista, productos, proveedor="nadro"):
    """Parte a mano y envía, en el doble, los renglones de esos productos."""
    from continental.particion import Linea, PedidoPorArmar

    renglones = [r for r in lista.renglones if r.propuesto.producto_id in productos]
    pedidos = almacenamiento.guardar_la_particion(
        lista.negocio,
        lista.pedido_sugerido_id,
        [
            PedidoPorArmar(
                proveedor=proveedor,
                proveedor_id=1,
                lineas=tuple(
                    Linea(
                        renglon_id=r.renglon_id,
                        descripcion=r.propuesto.descripcion,
                        cantidad=r.cantidad_a_pedir,
                    )
                    for r in renglones
                ),
            )
        ],
    )
    return almacenamiento.enviar_el_pedido(lista.negocio, pedidos[0].pedido_id, CORREO)


def test_lo_ya_pedido_trae_el_transito_con_su_proveedor_y_su_envio(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    _enviar_en_el_doble(almacenamiento, lunes, {1})

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MARTES)

    assert ya.renglon.propuesto.producto_id == 1
    assert ya.esta_en_transito
    assert ya.proveedor == "nadro"
    assert ya.enviado_por == CORREO
    assert ya.enviado_en is not None
    assert ya.fecha_del_pedido == LUNES
    assert ya.ventas_hasta == LUNES
    assert ya.retiene_desde == MARTES


def test_lo_ya_pedido_no_mira_la_lista_del_dia_ni_otro_negocio(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    ajena = _lista_con(almacenamiento, LUNES, [2], negocio="farmacia_02")
    _enviar_en_el_doble(almacenamiento, ajena, {2})

    assert almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=LUNES) == ()
    assert [
        y.renglon.propuesto.producto_id
        for y in almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MARTES)
    ] == [1]


def test_lo_abierto_y_lo_descartado_no_son_lo_ya_pedido(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    almacenamiento.descartar(NEGOCIO, lunes.renglones[1].renglon_id, CORREO)

    assert almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MARTES) == ()


def test_un_recibido_se_recuerda_hasta_que_una_lista_cerrada_lo_atiende(almacenamiento):
    """El ancla dura exactamente lo que tiene que durar.

    Recibido y sin que ninguna lista posterior lo haya atendido: se recuerda,
    porque sus ventas retenidas todavía no se propusieron. En cuanto una lista
    posterior lo trae y se CIERRA, esas ventas ya se propusieron: recordarlo
    más las propondría dos veces.
    """
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    _recibir(almacenamiento, 1)

    assert len(almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)) == 1

    martes = _lista_con(almacenamiento, MARTES, [1])
    assert len(almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)) == 1, (
        "Una lista posterior ABIERTA todavía no atendió nada: el ancla sigue."
    )

    almacenamiento.cerrar(NEGOCIO, martes.pedido_sugerido_id)
    assert almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES) == ()


def test_un_recibido_se_olvida_si_el_producto_se_volvio_a_pedir(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    _recibir(almacenamiento, 1)
    martes = _lista_con(almacenamiento, MARTES, [1])
    _enviar_en_el_doble(almacenamiento, martes, {1})

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)

    assert ya.fecha_del_pedido == MARTES
    assert ya.esta_en_transito


def test_un_transito_nunca_se_olvida_aunque_una_lista_cerrada_traiga_el_producto(
    almacenamiento,
):
    """En tránsito se ve siempre: esconderlo es lo que la casilla 4 prohíbe."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    martes = _lista_con(almacenamiento, MARTES, [1])
    almacenamiento.cerrar(NEGOCIO, martes.pedido_sugerido_id)
    _enviar_en_el_doble(almacenamiento, lunes, {1})  # desde la lista vieja

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)

    assert ya.fecha_del_pedido == LUNES


def test_la_interfaz_trae_lo_ya_pedido():
    assert hasattr(AlmacenamientoDelPedido, "lo_ya_pedido")
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)


def test_un_renglon_nace_sin_ventana_propia():
    columnas = columnas_del_renglon(
        Renglon(
            producto_id=1,
            clave="7501000000001",
            descripcion="X",
            piezas_vendidas=1.0,
            cantidad_propuesta=1,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        NEGOCIO,
        1,
    )

    assert columnas["ventas_desde"] is None


def test_la_ventana_propia_se_guarda_y_se_relee(almacenamiento):
    renglon = Renglon(
        producto_id=1,
        clave="7501000000001",
        descripcion="X",
        piezas_vendidas=3.0,
        cantidad_propuesta=3,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
        ventas_desde=MARTES,
    )
    guardada = almacenamiento.insertar_la_lista(
        NEGOCIO, JUEVES, Ventana(JUEVES, JUEVES), [renglon]
    )

    assert guardada.renglones[0].propuesto.ventas_desde == MARTES
    assert almacenamiento.leer(NEGOCIO, JUEVES).renglones[0].propuesto.ventas_desde == MARTES


def test_una_fila_sin_la_migracion_0008_se_lee_sin_ventana_propia():
    fila = {
        "producto_id": 1,
        "clave": None,
        "descripcion": "X",
        "piezas_vendidas": 1,
        "cantidad_propuesta": 1,
        "esta_en_el_catalogo": False,
        "existencia": None,
        "dias_de_cobertura": None,
        "clasificacion": "sin clasificar",
    }

    assert renglon_desde_columnas(fila).ventas_desde is None


# ------------------------------------------------------ el SQL, como texto


def test_la_sentencia_de_lo_ya_pedido_filtra_por_negocio_en_cada_tabla():
    sentencia = _sentencia_python("_LO_YA_PEDIDO")

    assert "r.negocio = :negocio" in sentencia
    assert "s.negocio = r.negocio" in sentencia
    assert "p.negocio = r.negocio" in sentencia
    assert "s2.negocio = r2.negocio" in sentencia


def test_la_sentencia_de_lo_ya_pedido_mira_antes_del_dia_y_nunca_el_reloj():
    sentencia = _sentencia_python("_LO_YA_PEDIDO").lower()

    assert "s.fecha_del_pedido < :antes_de" in sentencia
    for prohibida in ("current_date", "now()", "localtimestamp"):
        assert prohibida not in sentencia


def test_la_sentencia_trae_el_transito_siempre_y_el_recibido_solo_sin_atender():
    sentencia = _sentencia_python("_LO_YA_PEDIDO")

    assert "r.estado = 'en tránsito'" in sentencia
    assert "r.estado in ('recibido', 'recibido parcial')" in sentencia
    assert "not exists" in sentencia
    assert "s2.estado = 'cerrado'" in sentencia
    assert "r2.estado in ('en tránsito', 'recibido', 'recibido parcial')" in sentencia


def test_los_estados_que_cierran_escritos_en_el_sql_son_los_de_python():
    """El enganche vive en dos sitios; si uno cambia sin el otro, rojo."""
    sentencia = _sentencia_python("_LO_YA_PEDIDO")
    en_python = ", ".join(f"'{e}'" for e in ESTADOS_QUE_CIERRAN_EL_TRANSITO)

    assert f"r.estado in ({en_python})" in sentencia


def test_la_sentencia_de_lo_ya_pedido_no_escribe():
    sentencia = _sentencia_python("_LO_YA_PEDIDO").lower()

    for verbo in ("insert ", "update ", "delete ", "truncate "):
        assert verbo not in sentencia


@pytest.mark.parametrize(
    "nombre", ["_LEER_RENGLONES", "_LEER_RENGLON_POR_ID", "_INSERTAR_RENGLONES", "_LO_YA_PEDIDO"]
)
def test_las_sentencias_del_renglon_llevan_la_ventana_propia(nombre):
    assert "ventas_desde" in _sentencia_python(nombre)


def test_crear_tablas_declara_la_ventana_propia():
    sentencias = _sentencias(CREAR_TABLAS)

    assert re.search(r"ventas_desde\s+date", sentencias)
    assert "COMMENT ON COLUMN pedidos.renglon.ventas_desde" in _texto(CREAR_TABLAS)


def test_la_migracion_0008_es_idempotente_y_no_crea_tabla():
    texto = _texto(MIGRACION)
    sentencias = _sentencias(MIGRACION)

    assert "ADD COLUMN IF NOT EXISTS ventas_desde date" in sentencias
    assert "CREATE TABLE" not in sentencias.upper()
    assert "current_user = 'continental'" in sentencias
    assert "crear_rol.sql" in texto
    assert "\r" not in texto


def test_verificar_rol_mira_la_ventana_propia():
    texto = _sentencias(VERIFICAR_ROL)

    assert "(30," in texto
    assert "'ventas_desde'" in texto


def test_el_adr_existe_y_nombra_lo_que_descarto():
    texto = _texto(ADR)

    assert texto.startswith("# 0012")
    for descartada in ("tabla", "corte", "restar"):
        assert descartada in texto.lower()
    assert "26" in texto and "27" in texto


# ==========================================================================
# LO QUE SE VE — la ruta, el lote y la pantalla
# ==========================================================================


def test_casilla_1_lo_enviado_no_se_propone_aunque_la_lista_no_se_cierre(
    cliente, almacen, almacenamiento
):
    """El doble pedido de hoy, de punta a punta.

    El lunes se envía el producto 1 a NADRO y **nadie cierra la lista**. El
    martes la ventana vuelve a recoger el lunes (el piso del ticket 09): sin la
    memoria, las 3 piezas del lunes se piden otra vez.
    """
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 1)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})

    almacen.ventas_en_memoria.append(_venta(MARTES, 2, 1))
    martes = _abrir(cliente)

    assert martes["ventas_consideradas_desde"] == LUNES.isoformat()
    assert 1 not in _productos(martes), (
        "Lo que ya se le pidió a NADRO el lunes se está proponiendo otra vez."
    )
    assert _productos(martes) == [2]


def test_casilla_1_con_la_lista_cerrada_la_venta_nueva_tampoco_se_propone(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)

    assert _productos(martes) == [2]


def test_casilla_1_el_lote_de_la_noche_tampoco_lo_propone(almacen, almacenamiento):
    from continental.lote import correr_el_lote
    from continental.dobles import DoyleFalso

    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacen.ventas_en_memoria = [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]

    correr_el_lote(
        almacen=almacen,
        almacenamiento=almacenamiento,
        doyle=DoyleFalso(),
        negocio=NEGOCIO,
        tope_seg=0.0,
        tope_por_consulta_seg=1.0,
        cada_seg=1.0,
        dormir=lambda segundos: None,
        ahora=lambda: 0.0,
    )

    martes = almacenamiento.leer(NEGOCIO, MARTES)
    assert [r.propuesto.producto_id for r in martes.renglones] == [2]


def test_sin_poder_leer_lo_ya_pedido_la_lista_NO_se_arma_sin_proteccion(
    cliente, almacen, almacenamiento, caplog
):
    """Armar sin memoria sería el doble pedido en silencio: mejor un hueco."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]

    def se_cae(negocio, antes_de):
        raise RuntimeError("postgresql://continental:secreta@atlas/farmacia")

    almacenamiento.lo_ya_pedido = se_cae

    with caplog.at_level(logging.ERROR, logger="continental"):
        cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "secreta" not in str(cuerpo)
    assert almacenamiento.listas == [], "Se guardó una lista armada sin memoria."


def test_casilla_3_lo_vendido_en_transito_vuelve_al_recibirlo(
    cliente, almacen, almacenamiento
):
    """**La casilla difícil, de punta a punta, con la lista de en medio CERRADA.**

    - Lunes: se venden 3 del producto 1, se envían a NADRO, se cierra.
    - Martes: se venden 2 más. El producto 1 no se propone (está en camino). La
      lista del martes se CIERRA: el corte avanza al martes. Aquí es donde, sin
      el ancla, esas 2 piezas se perderían para siempre.
    - Miércoles: llega (ticket 26: `recibido`). Se vende 1 más.
    - La lista del miércoles propone **3**: las 2 del martes y la del miércoles.
    """
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert _productos(martes) == [2]
    _cerrar(cliente, martes)

    _recibir(almacenamiento, 1)
    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1), _venta(MIERCOLES, 2, 1)]
    miercoles = _abrir(cliente)
    por_producto = {r["producto_id"]: r for r in miercoles["renglones"]}

    assert miercoles["ventas_consideradas_desde"] == MIERCOLES.isoformat()
    assert por_producto[1]["cantidad_propuesta"] == 3, (
        "Las 2 piezas del martes, vendidas mientras venía en camino, se perdieron."
    )
    assert por_producto[1]["ventas_desde"] == MARTES.isoformat()
    assert "martes 15 de septiembre" in por_producto[1]["frase_de_la_ventana"]
    assert por_producto[2]["cantidad_propuesta"] == 1
    assert por_producto[2]["frase_de_la_ventana"] is None


def test_casilla_3_lo_que_volvio_no_vuelve_dos_veces(cliente, almacen, almacenamiento):
    """Después de la lista que lo trajo de vuelta, ya no se recuerda."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    _recibir(almacenamiento, 1)
    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2)]
    martes = _abrir(cliente)
    assert [r["cantidad_propuesta"] for r in martes["renglones"]] == [2]
    _cerrar(cliente, martes)

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1)]
    miercoles = _abrir(cliente)

    assert [r["cantidad_propuesta"] for r in miercoles["renglones"]] == [1]
    assert miercoles["renglones"][0]["ventas_desde"] is None


def test_casilla_2_y_4_lo_de_listas_anteriores_se_ve_con_proveedor_y_fecha(
    cliente, almacen, almacenamiento, monkeypatch
):
    from continental.web import app as modulo

    almacen.catalogo_en_memoria = [_producto(1, "AMOXICILINA"), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    enviado = dt.datetime(2026, 9, 15, 16, 30, tzinfo=dt.UTC)  # martes 10:30 local
    almacenamiento.pedidos[0]["enviado_en"] = enviado
    monkeypatch.setattr(
        modulo, "_ahora", lambda: dt.datetime(2026, 9, 17, 17, 0, tzinfo=dt.UTC)
    )

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MIERCOLES, 2, 1)]
    cuerpo = _abrir(cliente)
    bloque = cuerpo["en_camino"]
    [fila] = bloque["renglones"]

    assert bloque["ok"] is True
    assert fila["producto_id"] == 1
    assert fila["descripcion"] == "AMOXICILINA"
    assert fila["cantidad"] == 3
    assert fila["proveedor"] == "nadro"
    assert fila["nombre"] == "NADRO"
    assert fila["enviado_en"] == enviado.isoformat()
    assert fila["enviado_por"] == CORREO
    assert fila["fecha_del_pedido"] == LUNES.isoformat()
    assert fila["frase"] == "Pedido el martes a NADRO, sin recibir."
    assert fila["firma"].startswith("Lo marcó como enviado " + CORREO + " el martes")
    assert fila["vendido_desde_que_se_pidio"] == 2
    assert "2 piezas más" in fila["frase_de_lo_vendido"]
    assert bloque["frase"].startswith("1 renglón de listas anteriores")


def test_casilla_4_el_renglon_de_hoy_ya_enviado_trae_su_frase(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lista = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lista, {1})

    cuerpo = _abrir(cliente)
    [renglon] = cuerpo["renglones"]

    assert renglon["esta_en_transito"] is True
    assert renglon["frase_del_transito"] == "Pedido hoy a NADRO, sin recibir."


def test_casilla_5_la_advertencia_viaja_aunque_no_haya_nada_en_camino(
    cliente, almacen
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]

    bloque = _abrir(cliente)["en_camino"]

    assert bloque["renglones"] == []
    assert bloque["frase"] == "Nada de listas anteriores viene en camino."
    assert bloque["advertencia"] == ADVERTENCIA_DE_LO_QUE_PROTEGE


def test_un_renglon_abierto_de_hoy_que_ya_viene_en_camino_se_avisa(
    cliente, almacen, almacenamiento
):
    """El borde que la memoria no alcanza, dicho en el renglón.

    La lista del martes se arma con el producto 1 dentro (la del lunes nadie
    la cerró, y su pedido todavía no se enviaba). Después alguien envía el
    pedido del lunes — desde una lista vencida, que el ADR 0009 permite. La
    lista del martes ya está guardada y no se recalcula: se avisa.
    """
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    for r in lunes["renglones"]:
        almacenamiento.guardar_precios(NEGOCIO, r["renglon_id"], [_lectura("nadro", "12.50")])
    partida = cliente.post(f"{RUTA}/{lunes['pedido_sugerido_id']}/partir").json()

    almacen.ventas_en_memoria.append(_venta(MARTES, 1, 1))
    martes = _abrir(cliente)
    assert _productos(martes) == [1]

    pedido = partida["pedidos"][0]["pedido_id"]
    assert cliente.post(f"/api/pedido/{pedido}/enviar").json()["ok"] is True

    [renglon] = _abrir(cliente)["renglones"]

    assert renglon["ya_viene_en_camino"].startswith("Ya viene en camino")


def test_si_no_se_puede_leer_lo_que_viene_en_camino_la_lista_sale_igual(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    _abrir(cliente)  # la lista ya existe: armar no vuelve a llamar

    def se_cae(negocio, antes_de):
        raise RuntimeError("postgresql://continental:secreta@atlas/farmacia")

    almacenamiento.lo_ya_pedido = se_cae
    cuerpo = _abrir(cliente)

    assert cuerpo["renglones"], "Sin el bloque, la lista del día tiene que salir igual."
    assert cuerpo["en_camino"]["ok"] is False
    assert "RuntimeError" in cuerpo["en_camino"]["detalle"]
    assert "secreta" not in str(cuerpo)
    assert cuerpo["en_camino"]["advertencia"] == ADVERTENCIA_DE_LO_QUE_PROTEGE


def test_si_no_se_pueden_leer_las_ventas_lo_vendido_es_un_hueco_y_no_un_cero(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    almacen.ventas_en_memoria += [_venta(MARTES, 2, 1)]
    _abrir(cliente)  # la del martes queda armada

    original = almacen.ventas

    def se_cae(desde, hasta):
        raise RuntimeError("postgresql://continental:secreta@atlas/farmacia")

    almacen.ventas = se_cae
    try:
        bloque = _abrir(cliente)["en_camino"]
    finally:
        almacen.ventas = original

    [fila] = bloque["renglones"]
    assert fila["vendido_desde_que_se_pidio"] is None
    assert fila["frase_de_lo_vendido"].startswith("No se pudo leer")
    assert "secreta" not in str(bloque)


# ------------------------------------------------------------- la pantalla


def test_la_pantalla_tiene_el_bloque_de_lo_que_viene_en_camino():
    pagina = pantalla_completa()

    assert 'id="en-camino"' in pagina
    assert "pintarEnCamino" in pagina
    assert "en_camino.advertencia" in pagina


def test_la_pantalla_atenua_y_no_esconde():
    """Atenuados con una clase, y con opacidad: siguen leyéndose."""
    pagina = pantalla_completa()

    assert ".transito" in pagina
    assert re.search(r"\.transito[^{]*\{[^}]*opacity", pagina)
    assert "classList.add('transito')" in pagina


def test_la_pantalla_no_compone_las_frases_que_afirman():
    """"Pedido el martes, sin recibir" llega hecho de Python (lección del 15)."""
    pagina = pantalla_completa()
    codigo = re.sub(r"//[^\n]*", "", pagina)

    assert "sin recibir'" not in codigo
    assert "r.frase_del_transito" in pagina
    assert "v.firma" in pagina
    assert "'Lo marcó como enviado '" not in codigo
    assert "r.frase_de_la_ventana" in pagina
    assert "r.ya_viene_en_camino" in pagina


def test_el_bloque_se_pinta_tambien_el_dia_sin_renglones():
    """Una lista vacía no quiere decir que no venga nada en camino."""
    pagina = pantalla_completa()
    inicio = pagina.index("async function cargarPedido()")
    pintado = pagina.index("pintarEnCamino(", inicio)
    salida = pagina.index("if (!datos.renglones.length)", inicio)

    assert pintado < salida
