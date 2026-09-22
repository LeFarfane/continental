"""Tránsito atrasado y cancelar un pedido: la válvula de escape (ticket 25, ADR 0013).

**Lo que arregla.** Desde el ticket 24 un renglón `en tránsito` no se vuelve a
proponer. Si nunca llega —el pedido nunca se capturó, o el proveedor no lo
surtió— se queda fuera de la lista **para siempre**, y eso es mercancía que va
a faltar sin que nadie lo note. Este ticket abre dos salidas, las dos firmadas:

- **Cancelar un pedido** que nunca se capturó en el portal. El pedido pasa a
  `cancelado` y sus renglones en tránsito también.
- **Devolver a la lista un renglón atrasado**, uno por uno, sin cancelar el
  pedido entero. Solo se puede con lo que lleva **más de N días** en camino, y
  N vive en `config/continental.yml`.

**Las tres tensiones que el ticket traía, y cómo quedaron** (el ADR 0013 las
razona enteras):

1. *El ADR 0009 dijo que no hay "desenviar".* Y sigue sin haberlo: cancelar no
   devuelve el pedido a `borrador`, no lo deja editar y no se deshace. Es un
   tercer estado, terminal, y el ADR 0009 dice en qué punto lo enmienda el 0013.
2. *"Vencido" ya era un estado de la lista.* Lo del renglón se llama
   **atrasado**, y no es un estado: es una señal que se calcula cada vez.
3. *Lo que el renglón repuso tiene que volver.* El renglón `cancelado` no
   vuelve a `abierto` en su lista vieja —que puede estar cerrada, y el glosario
   dice que solo una lista `abierta` se modifica—: **lo que vuelve es el
   producto, a la siguiente lista**, contado desde el principio de lo que ese
   renglón cubría. Con la misma memoria del ticket 24, así que ni se pierde ni
   se propone dos veces. Los escenarios de varios días están abajo, de punta a
   punta.

Los tres seams del repo, en este orden: lo puro (`transito.py`), lo que se
guarda (el doble y el SQL como texto) y lo que se ve (las rutas, el lote y la
pantalla). Ninguna prueba de este archivo toca Postgres, la red, ni duerme.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    CANCELADO,
    ENVIADO,
    ESTADOS_DEL_PEDIDO,
    ESTADOS_DEL_RENGLON,
    ESTADOS_QUE_CIERRAN_EL_TRANSITO,
    LoYaPedido,
    PedidoGuardado,
    RENGLON_CANCELADO,
    RENGLON_EN_TRANSITO,
    RenglonGuardado,
    Ventana,
    dias_en_transito_para_atrasado_configurados,
    revisar_el_pedido,
    revisar_el_renglon,
)
from continental.dobles import AlmacenamientoFalso
from continental.particion import (
    frase_del_envio,
    frase_sin_nada_por_repartir,
)
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon
from continental.transiciones import motivo_para_no_cancelar, motivo_para_no_enviar
from continental.transito import (
    ADVERTENCIA_AL_DEVOLVER,
    ZONA_DE_LA_FARMACIA,
    dias_en_transito,
    en_camino_como_json,
    enviado_antes_de,
    esta_atrasado,
    frase_de_lo_que_vuelve,
    frase_de_los_atrasados,
    frase_de_los_que_vuelven,
    frase_del_atraso,
    frase_del_pedido_cancelado,
    frase_del_renglon_cancelado,
    frase_del_umbral,
    frase_para_cancelar,
    memoria_de_lo_pedido,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0009-cancelar-y-devolver-lo-atrasado.sql"
CONFIG = RAIZ / "config" / "continental.yml"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
# La pantalla entera —HTML, CSS y JavaScript— sale de `conftest.pantalla_completa`
# desde el ticket 28, que la separó en tres archivos: leer solo `index.html`
# dejaría las guardias de "esto NO está" revisando un texto sin el JavaScript.
GLOSARIO = RAIZ / "CONTEXT.md"
ADR = RAIZ / "docs" / "decisiones" / (
    "0013-cancelar-suelta-el-transito-y-lo-que-vuelve-es-el-producto.md"
)
ADR_0009 = RAIZ / "docs" / "decisiones" / (
    "0009-enviar-es-la-firma-de-que-ya-se-capturo-en-el-portal.md"
)

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
DUENO = "dueno@farmacia.mx"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}

# Dos semanas reales de calendario, de lunes 14 a jueves 24 de septiembre.
LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)
MARTES_22 = dt.date(2026, 9, 22)
MIERCOLES_23 = dt.date(2026, 9, 23)
JUEVES_24 = dt.date(2026, 9, 24)

#: La hora del centro de México, a mano, para construir instantes de prueba.
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


def _producto(producto_id: int) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=2.0,
        esta_activo=True,
        es_granel=False,
    )


def _renglon(producto_id: int, ventas_desde: dt.date | None = None) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        piezas_vendidas=3.0,
        cantidad_propuesta=3,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
        ventas_desde=ventas_desde,
    )


def _ya(
    producto_id: int,
    ventas_hasta: dt.date,
    estado: str = RENGLON_EN_TRANSITO,
    desde_la_lista: dt.date | None = None,
    ventas_desde: dt.date | None = None,
    estado_del_pedido: str | None = ENVIADO,
    cancelado_por: str | None = None,
    cancelado_en: dt.datetime | None = None,
    enviado_en: dt.datetime | None = None,
) -> LoYaPedido:
    """Un `LoYaPedido` armado a mano. `desde_la_lista` es el principio de la
    ventana de su lista; por omisión, la lista es de un solo día."""
    if estado == RENGLON_CANCELADO and cancelado_por is None:
        cancelado_por = DUENO
        cancelado_en = dt.datetime(2026, 9, 16, 10, 30, tzinfo=CENTRO)
    return LoYaPedido(
        renglon=RenglonGuardado(
            renglon_id=producto_id * 10,
            estado=estado,
            propuesto=_renglon(producto_id, ventas_desde),
            pedido_id=7,
            cancelado_por=cancelado_por,
            cancelado_en=cancelado_en,
        ),
        pedido_sugerido_id=1,
        fecha_del_pedido=ventas_hasta,
        ventas_hasta=ventas_hasta,
        proveedor="nadro",
        enviado_por=CORREO,
        enviado_en=enviado_en or dt.datetime(2026, 9, 14, 10, 0, tzinfo=CENTRO),
        ventas_desde_la_lista=desde_la_lista or ventas_hasta,
        estado_del_pedido=estado_del_pedido,
    )


def _pedido(estado: str = ENVIADO, **extra) -> PedidoGuardado:
    firma_de_envio = (
        {"enviado_por": CORREO, "enviado_en": dt.datetime(2026, 9, 14, 16, 0, tzinfo=dt.UTC)}
        if estado in (ENVIADO, CANCELADO)
        else {}
    )
    firma_de_cancelacion = (
        {"cancelado_por": DUENO, "cancelado_en": dt.datetime(2026, 9, 15, 16, 0, tzinfo=dt.UTC)}
        if estado == CANCELADO
        else {}
    )
    return PedidoGuardado(
        pedido_id=7,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor="nadro",
        proveedor_id=1,
        estado=estado,
        armado_en=dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.UTC),
        total_sin_iva=Decimal("37.50"),
        **{**firma_de_envio, **firma_de_cancelacion, **extra},
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


def _local(fecha: dt.date, hora: int = 10, minuto: int = 0) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=CENTRO)


# ==========================================================================
# LO PURO — cuántos días lleva, desde cuándo es atrasado, y cómo se dice
# ==========================================================================


def test_los_dias_en_transito_son_de_calendario_en_la_farmacia():
    """Un envío del lunes a las 20:30 son las 02:30 del martes en UTC.

    Contado en UTC saldría un día menos, y el renglón se señalaría un día
    tarde. Es la misma trampa del ticket 24, con otro número.
    """
    enviado = dt.datetime(2026, 9, 15, 2, 30, tzinfo=dt.UTC)  # lunes 20:30 local

    assert dias_en_transito(enviado, _local(MIERCOLES, 8)) == 2
    assert dias_en_transito(enviado, _local(LUNES, 23)) == 0


def test_los_dias_en_transito_sin_hora_de_envio_no_se_inventan():
    assert dias_en_transito(None, _local(MIERCOLES)) is None


def test_un_reloj_un_poco_adelantado_no_da_dias_negativos():
    assert dias_en_transito(_local(MARTES, 10, 1), _local(MARTES, 10, 0)) == 0


@pytest.mark.parametrize(
    "dias, atrasado", [(None, False), (0, False), (6, False), (7, False), (8, True), (30, True)]
)
def test_atrasado_es_MAS_de_n_dias_y_no_n(dias, atrasado):
    """El ticket dice "más de N días": con N = 7, el séptimo todavía no."""
    assert esta_atrasado(dias, 7) is atrasado


def test_el_limite_del_envio_es_la_medianoche_de_la_farmacia():
    """Lo que el `WHERE` compara: un instante, calculado en la hora de la farmacia."""
    limite = enviado_antes_de(_local(MARTES_22, 9), 7)

    assert limite == dt.datetime(2026, 9, 15, 0, 0, tzinfo=ZONA_DE_LA_FARMACIA)
    assert limite.astimezone(dt.UTC) == dt.datetime(2026, 9, 15, 6, 0, tzinfo=dt.UTC)


def test_el_limite_y_los_dias_dicen_exactamente_lo_mismo():
    """**La pantalla y el `WHERE` no pueden separarse.** La señal se calcula
    con `dias_en_transito` y el `UPDATE` con `enviado_antes_de`: si difirieran
    en un solo instante, la pantalla ofrecería devolver lo que la base niega, o
    al revés. Se recorren doce días de hora en hora, con tres umbrales."""
    ahora = _local(MARTES_22, 9, 17)
    for umbral in (1, 3, 7):
        limite = enviado_antes_de(ahora, umbral)
        for horas in range(0, 12 * 24):
            enviado = ahora - dt.timedelta(hours=horas, minutes=13)
            assert (enviado < limite) is esta_atrasado(
                dias_en_transito(enviado, ahora), umbral
            ), (umbral, enviado)


def test_la_frase_del_atraso_dice_los_dias_y_el_umbral():
    frase = frase_del_atraso(9, 7)

    assert "9 días" in frase
    assert "más de 7 días." in frase
    assert "devolver a la lista" in frase


def test_sin_atraso_no_hay_frase():
    assert frase_del_atraso(7, 7) is None
    assert frase_del_atraso(None, 7) is None
    assert frase_del_atraso(9, None) is None


def test_la_frase_del_atraso_en_singular():
    assert "más de 1 día." in frase_del_atraso(2, 1)


def test_la_frase_del_umbral_lo_dice_con_su_numero():
    assert "más de 7 días" in frase_del_umbral(7)
    assert "más de 1 día " in frase_del_umbral(1)


def test_la_frase_de_los_atrasados_cuenta_y_calla_con_cero():
    assert frase_de_los_atrasados(0, 7) is None
    assert frase_de_los_atrasados(1, 7).startswith("1 renglón lleva más de 7 días")
    assert frase_de_los_atrasados(3, 7).startswith("3 renglones llevan más de 7 días")


def test_la_advertencia_al_devolver_dice_lo_que_cuesta_equivocarse():
    """Devolver lo que sí llegó es pedirlo dos veces. Desde el ticket 26 lo que
    llega con compra en SICAR se puede recibir —y mientras tenga propuesta no
    se ofrece devolverlo—, pero no todo deja compra: la advertencia lo dice, y
    dice que el portal no se toca."""
    assert "llegó" in ADVERTENCIA_AL_DEVOLVER
    assert "dos veces" in ADVERTENCIA_AL_DEVOLVER
    assert "portal" in ADVERTENCIA_AL_DEVOLVER


# ---------------------------------------------------- la memoria (24 + 25)


def test_un_cancelado_vuelve_desde_el_principio_de_lo_que_cubria():
    """**La tensión 3, en una función.** Al recibirse, lo retenido vuelve desde
    el día siguiente al ancla (ADR 0012). Al cancelarse vuelve TAMBIÉN lo que
    el renglón cubría, porque nunca se pidió: desde el principio de su lista."""
    memoria = memoria_de_lo_pedido(
        [_ya(1, MARTES, RENGLON_CANCELADO, desde_la_lista=LUNES)]
    )
    ventana = Ventana(JUEVES, JUEVES)
    ventas = [
        _venta(LUNES, 1, 3),
        _venta(MARTES, 1, 2),
        _venta(MIERCOLES, 1, 1),
        _venta(JUEVES, 1, 1),
    ]

    assert sum(v.cantidad for v in memoria.recortar(ventas, ventana)) == 7
    assert memoria.desde_de_la_lectura(ventana) == LUNES
    assert memoria.ventas_desde(1, ventana) == LUNES
    assert not memoria.esta_en_camino(1)


def test_un_cancelado_con_ventana_propia_vuelve_desde_la_suya():
    """Si el renglón cancelado ya traía lo de un pedido anterior (su
    `ventas_desde`), eso también vuelve: tampoco se pidió nunca."""
    memoria = memoria_de_lo_pedido(
        [_ya(1, MIERCOLES, RENGLON_CANCELADO, desde_la_lista=MIERCOLES, ventas_desde=LUNES)]
    )

    assert memoria.ventas_desde(1, Ventana(JUEVES, JUEVES)) == LUNES


def test_un_cancelado_que_empieza_en_la_ventana_no_la_anota():
    memoria = memoria_de_lo_pedido(
        [_ya(1, LUNES, RENGLON_CANCELADO, desde_la_lista=LUNES)]
    )

    assert memoria.ventas_desde(1, Ventana(LUNES, MIERCOLES)) is None


def test_lo_que_viene_en_camino_le_gana_a_un_cancelado_del_mismo_producto():
    """Se canceló y se volvió a pedir: el pedido nuevo manda."""
    memoria = memoria_de_lo_pedido(
        [
            _ya(1, LUNES, RENGLON_CANCELADO),
            _ya(1, MIERCOLES),
        ]
    )

    assert memoria.esta_en_camino(1)


def test_un_cancelado_sin_el_principio_de_su_lista_truena():
    """Sin ese día no se sabe desde cuándo vuelve, y adivinarlo sería perder
    ventas o proponerlas dos veces, en silencio."""
    with pytest.raises(ValueError, match="principio"):
        LoYaPedido(
            renglon=RenglonGuardado(
                renglon_id=1,
                estado=RENGLON_CANCELADO,
                propuesto=_renglon(1),
                pedido_id=7,
                cancelado_por=DUENO,
                cancelado_en=_local(MARTES),
            ),
            pedido_sugerido_id=1,
            fecha_del_pedido=LUNES,
            ventas_hasta=LUNES,
            proveedor="nadro",
            enviado_por=CORREO,
            enviado_en=_local(LUNES),
        )


def test_los_estados_que_cierran_el_transito_siguen_siendo_los_de_la_recepcion():
    """Cancelar NO entra al enganche de los tickets 26 y 27: ese dice "vuelve
    desde el día siguiente al ancla", y lo cancelado vuelve desde antes."""
    assert RENGLON_CANCELADO not in ESTADOS_QUE_CIERRAN_EL_TRANSITO


# ------------------------------------------------------------- las frases


def test_la_frase_para_cancelar_dice_que_el_portal_no_se_toca():
    frase = frase_para_cancelar("NADRO", 3)

    assert "portal de NADRO" in frase
    assert "nunca se capturó" in frase
    assert "no cancela nada" in frase
    assert "3 renglones" in frase
    assert "siguiente lista" in frase


def test_la_frase_para_cancelar_en_singular():
    frase = frase_para_cancelar("LEVIC", 1)

    assert "Su renglón deja de estar en camino y vuelve" in frase


def test_sin_nada_en_camino_las_frases_no_dicen_cero_renglones():
    """Si todo se devolvió uno por uno, cancelar solo deja dicho que no está en
    el portal. "Sus 0 renglones dejan de estar en camino" no dice nada."""
    assert "0 renglones" not in frase_para_cancelar("NADRO", 0)
    assert "nada en camino" in frase_para_cancelar("NADRO", 0)
    assert "0 renglones" not in frase_del_pedido_cancelado("NADRO", 0)
    assert "nada en camino" in frase_del_pedido_cancelado("NADRO", 0)


def test_solo_un_pedido_enviado_se_puede_cancelar():
    assert motivo_para_no_cancelar(_pedido(ENVIADO)) is None
    assert "borrador" in motivo_para_no_cancelar(_pedido(BORRADOR))
    assert "ya está cancelado" in motivo_para_no_cancelar(_pedido(CANCELADO))


def test_la_frase_del_pedido_cancelado():
    frase = frase_del_pedido_cancelado("NADRO", 2)

    assert frase.startswith("Pedido a NADRO cancelado.")
    assert "2 renglones" in frase
    assert "siguiente lista" in frase
    assert "no canceló nada en el portal de NADRO" in frase


def test_lo_que_vuelve_de_un_pedido_cancelado_lo_dice_con_su_firma_y_su_fecha():
    ya = _ya(1, MARTES, RENGLON_CANCELADO, desde_la_lista=LUNES, estado_del_pedido=CANCELADO)

    frase = frase_de_lo_que_vuelve(ya)

    assert "Su pedido a NADRO se canceló" in frase
    assert DUENO in frase
    assert "10:30" in frase
    assert "siguiente lista" in frase
    assert "desde el lunes 14 de septiembre" in frase


def test_lo_que_vuelve_devuelto_uno_por_uno_lo_dice_distinto():
    ya = _ya(1, MARTES, RENGLON_CANCELADO, desde_la_lista=LUNES, estado_del_pedido=ENVIADO)

    frase = frase_de_lo_que_vuelve(ya)

    assert frase.startswith(f"Lo devolvió a la lista {DUENO}")
    assert "no llegó" in frase


def test_el_renglon_cancelado_de_hoy_dice_que_vuelve_en_la_siguiente_y_no_en_esta():
    renglon = RenglonGuardado(
        renglon_id=1,
        estado=RENGLON_CANCELADO,
        propuesto=_renglon(1),
        pedido_id=7,
        cancelado_por=DUENO,
        cancelado_en=_local(LUNES),
    )

    por_pedido = frase_del_renglon_cancelado(renglon, pedido_cancelado=True, nombre="NADRO")
    uno_por_uno = frase_del_renglon_cancelado(renglon, pedido_cancelado=False, nombre="NADRO")

    assert "Su pedido a NADRO se canceló" in por_pedido
    assert "siguiente lista, no en ésta" in por_pedido
    assert "no llegó" in uno_por_uno
    assert "siguiente lista, no en ésta" in uno_por_uno


def test_un_pedido_cancelado_no_dice_que_se_puede_enviar():
    """`fue_enviado` se separó de `not es_borrador` en el ticket 21 esperando
    justo esto: un tercer estado donde "no es borrador" no quiere decir "se
    capturó"."""
    cancelado = _pedido(CANCELADO)

    assert not cancelado.fue_enviado
    assert not cancelado.es_borrador
    assert cancelado.fue_cancelado
    assert motivo_para_no_enviar(cancelado, renglones_dentro=3) is not None
    frase = frase_del_envio(cancelado)
    assert DUENO in frase and "canceló" in frase
    assert "no canceló nada" in frase


# ------------------------------------------------------------- el bloque


def test_el_bloque_dice_cuanto_lleva_cada_uno_y_cual_esta_atrasado():
    ahora = _local(MARTES_22, 9)
    viejo = _ya(1, LUNES, enviado_en=_local(LUNES, 10))
    reciente = _ya(2, VIERNES, enviado_en=_local(VIERNES, 10))

    bloque = en_camino_como_json([viejo, reciente], {}, ahora, umbral=7)
    por_producto = {r["producto_id"]: r for r in bloque["renglones"]}

    assert por_producto[1]["dias_en_transito"] == 8
    assert por_producto[1]["atrasado"] is True
    assert por_producto[1]["se_puede_devolver"] is True
    assert "8 días" in por_producto[1]["frase_del_atraso"]
    assert por_producto[2]["dias_en_transito"] == 4
    assert por_producto[2]["atrasado"] is False
    assert por_producto[2]["se_puede_devolver"] is False
    assert por_producto[2]["frase_del_atraso"] is None
    assert bloque["umbral_del_atraso"] == 7
    assert bloque["frase_de_los_atrasados"].startswith("1 renglón")
    assert bloque["advertencia_al_devolver"] == ADVERTENCIA_AL_DEVOLVER


def test_sin_umbral_el_bloque_lo_dice_y_no_esconde_nada():
    """Regla 4: la configuración rota es un hueco con su motivo. Los renglones
    se siguen enseñando; lo que no se puede es decir cuál está atrasado."""
    bloque = en_camino_como_json(
        [_ya(1, LUNES)], {}, _local(MARTES_22), detalle_del_umbral="config rota (ValueError)"
    )
    [fila] = bloque["renglones"]

    assert fila["atrasado"] is None
    assert fila["se_puede_devolver"] is False
    assert fila["dias_en_transito"] == 8
    assert bloque["umbral_del_atraso"] is None
    assert "config rota (ValueError)" in bloque["frase_del_umbral"]


def test_el_bloque_agrupa_los_pedidos_que_se_pueden_cancelar():
    uno = _ya(1, LUNES)
    dos = _ya(2, LUNES)

    bloque = en_camino_como_json([uno, dos], {}, _local(MARTES), umbral=7)
    [pedido] = bloque["pedidos"]

    assert pedido["pedido_id"] == 7
    assert pedido["nombre"] == "NADRO"
    assert pedido["renglones_en_camino"] == 2
    assert "2 renglones" in pedido["frase_para_cancelar"]


def test_lo_que_vuelve_lleva_su_encabezado_y_con_cero_calla():
    """Lo cazó el recorrido del navegador: sin encabezado, la línea de lo que
    vuelve se leía como parte del pedido de arriba."""
    assert frase_de_los_que_vuelven(0) is None
    assert frase_de_los_que_vuelven(1).startswith("1 renglón se dejó de esperar")
    assert "siguiente lista" in frase_de_los_que_vuelven(2)
    bloque = en_camino_como_json([], {}, _local(MARTES), umbral=7, vuelven=[_ya(3, LUNES, RENGLON_CANCELADO)])
    assert bloque["frase_de_los_que_vuelven"] == frase_de_los_que_vuelven(1)


def test_una_lista_sin_nada_por_repartir_porque_se_cancelo_no_manda_a_elegir_proveedor():
    """**Lo cazó el recorrido del navegador**, la sexta vez (14, 15, 21, 22, 24,
    25): con todo cancelado, la pantalla decía *"Todavía no hay en qué partir
    esta lista · Elige a quién se le pide cada renglón"* sobre renglones que ya
    no se pueden repartir. Es el mismo tropiezo del 21 con otro estado."""
    assert frase_sin_nada_por_repartir(en_transito=0, cancelados=0) is None
    solo_cancelados = frase_sin_nada_por_repartir(en_transito=0, cancelados=3)
    assert solo_cancelados.startswith("No queda nada por repartir")
    assert "3 renglones se dejaron de esperar" in solo_cancelados
    assert "siguiente lista" in solo_cancelados
    mezcla = frase_sin_nada_por_repartir(en_transito=1, cancelados=1)
    assert "1 renglón ya se pidió" in mezcla and "1 renglón se dejó de esperar" in mezcla


def test_el_bloque_enseña_lo_que_vuelve_en_la_siguiente_lista():
    vuelve = _ya(3, LUNES, RENGLON_CANCELADO)

    bloque = en_camino_como_json([], {}, _local(MARTES), umbral=7, vuelven=[vuelve])
    [fila] = bloque["vuelven"]

    assert fila["producto_id"] == 3
    assert "siguiente lista" in fila["frase"]


# ==========================================================================
# LO QUE SE GUARDA — el doble, los CHECK en Python y el SQL como texto
# ==========================================================================


def _lista_con(almacenamiento, fecha: dt.date, productos, negocio: str = NEGOCIO):
    return almacenamiento.insertar_la_lista(
        negocio, fecha, Ventana(fecha, fecha), [_renglon(p) for p in productos]
    )


def _enviar_en_el_doble(almacenamiento, lista, productos, proveedor="nadro"):
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
    [pedido] = [p for p in pedidos if p.proveedor == proveedor]
    return almacenamiento.enviar_el_pedido(lista.negocio, pedido.pedido_id, CORREO)


def _estados(almacenamiento) -> dict[int, str]:
    return {
        fila["producto_id"]: fila["estado"]
        for lista in almacenamiento.listas
        for fila in lista["renglones"]
    }


def test_cancelar_pasa_el_pedido_y_sus_renglones_en_transito_a_cancelado(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2, 3])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1, 2})

    cancelado = almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    assert cancelado.pedido.estado == CANCELADO
    assert cancelado.pedido.cancelado_por == DUENO
    assert cancelado.pedido.cancelado_en is not None
    # La firma del envío se queda: alguien SÍ dijo haberlo capturado, y eso
    # también es parte de la historia de este pedido.
    assert cancelado.pedido.enviado_por == CORREO
    assert sorted(cancelado.renglones) == sorted(
        r.renglon_id for r in lunes.renglones if r.propuesto.producto_id in {1, 2}
    )
    assert _estados(almacenamiento) == {1: RENGLON_CANCELADO, 2: RENGLON_CANCELADO, 3: "abierto"}
    for fila in almacenamiento.listas[0]["renglones"][:2]:
        assert fila["cancelado_por"] == DUENO
        assert fila["cancelado_en"] == cancelado.pedido.cancelado_en
        # El renglón sigue colgando de su pedido: es la historia de qué se
        # pidió y qué se canceló, no un renglón suelto.
        assert fila["pedido_id"] == enviado.pedido.pedido_id


def test_cancelar_no_exige_la_lista_abierta(almacenamiento):
    """Igual que enviar (ADR 0009): cancelar no modifica lo que se iba a pedir,
    dice que no se pidió. Exigir la lista abierta dejaría atrapado para siempre
    lo que se envió desde una lista que ya se cerró."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cerrar(NEGOCIO, lunes.pedido_sugerido_id)

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)


def test_cancelar_dos_veces_no_mueve_la_firma(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    primero = almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, CORREO) is None
    assert almacenamiento.pedidos[0]["cancelado_por"] == DUENO
    assert almacenamiento.pedidos[0]["cancelado_en"] == primero.pedido.cancelado_en


def test_un_borrador_no_se_cancela(almacenamiento):
    """Un borrador no se le ha pedido a nadie: no hay tránsito que soltar. Se
    vuelve a partir, que es lo que ya existe."""
    from continental.particion import Linea, PedidoPorArmar

    lunes = _lista_con(almacenamiento, LUNES, [1])
    [pedido] = almacenamiento.guardar_la_particion(
        NEGOCIO,
        lunes.pedido_sugerido_id,
        [PedidoPorArmar("nadro", 1, (Linea(lunes.renglones[0].renglon_id, "X", 3),))],
    )

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, pedido.pedido_id, DUENO) is None
    assert almacenamiento.pedidos[0]["estado"] == BORRADOR


def test_un_pedido_de_otro_negocio_no_se_cancela(almacenamiento):
    ajena = _lista_con(almacenamiento, LUNES, [1], negocio="farmacia_02")
    enviado = _enviar_en_el_doble(almacenamiento, ajena, {1})

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO) is None


def test_un_pedido_con_algo_recibido_no_se_cancela(almacenamiento):
    """Si algo llegó, el pedido SÍ se capturó: "nunca se capturó" es falso."""
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1, 2})
    # Desde el 27, lo recibido dice cuántas llegaron: las que se pidieron.
    almacenamiento.poner_estado_del_renglon(
        lunes.renglones[0].renglon_id,
        "recibido",
        recibido_por=CORREO,
        recibido_en=_local(MARTES),
        piezas_recibidas=lunes.renglones[0].cantidad_a_pedir,
    )

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO) is None
    assert _estados(almacenamiento)[2] == RENGLON_EN_TRANSITO


def test_un_pedido_cancelado_no_se_vuelve_a_enviar_ni_a_partir(almacenamiento):
    """No hay "desenviar" (ADR 0009): cancelar es un final, no una vuelta atrás."""
    from continental.particion import Linea, PedidoPorArmar

    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    assert almacenamiento.enviar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, CORREO) is None
    almacenamiento.guardar_la_particion(
        NEGOCIO,
        lunes.pedido_sugerido_id,
        [PedidoPorArmar("nadro", 1, (Linea(lunes.renglones[1].renglon_id, "X", 3),))],
    )
    assert almacenamiento.pedidos[0]["estado"] == CANCELADO
    assert _estados(almacenamiento)[2] == "abierto"
    assert almacenamiento.listas[0]["renglones"][1].get("pedido_id") is None


def test_devolver_un_atrasado_lo_cancela_a_el_solo(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1, 2})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES)
    limite = enviado_antes_de(_local(MARTES_22), 7)

    renglon = almacenamiento.devolver_el_atrasado(
        NEGOCIO, lunes.renglones[0].renglon_id, DUENO, limite
    )

    assert renglon.estado == RENGLON_CANCELADO
    assert renglon.cancelado_por == DUENO
    assert renglon.cancelado_en is not None
    assert _estados(almacenamiento) == {1: RENGLON_CANCELADO, 2: RENGLON_EN_TRANSITO}
    assert almacenamiento.pedidos[0]["estado"] == ENVIADO
    assert enviado.pedido.pedido_id == renglon.pedido_id


def test_lo_que_no_esta_atrasado_no_se_devuelve(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.pedidos[0]["enviado_en"] = _local(MARTES)
    limite = enviado_antes_de(_local(MARTES_22), 7)  # medianoche del 15

    assert almacenamiento.devolver_el_atrasado(
        NEGOCIO, lunes.renglones[0].renglon_id, DUENO, limite
    ) is None
    assert _estados(almacenamiento)[1] == RENGLON_EN_TRANSITO


def test_solo_se_devuelve_lo_que_esta_en_transito(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES)
    limite = enviado_antes_de(_local(MARTES_22), 7)
    [uno, dos] = lunes.renglones

    assert almacenamiento.devolver_el_atrasado(NEGOCIO, dos.renglon_id, DUENO, limite) is None
    assert almacenamiento.devolver_el_atrasado(NEGOCIO, uno.renglon_id, DUENO, limite)
    assert almacenamiento.devolver_el_atrasado(NEGOCIO, uno.renglon_id, CORREO, limite) is None
    assert almacenamiento.listas[0]["renglones"][0]["cancelado_por"] == DUENO


def test_un_atrasado_de_otro_negocio_no_se_devuelve(almacenamiento):
    ajena = _lista_con(almacenamiento, LUNES, [1], negocio="farmacia_02")
    _enviar_en_el_doble(almacenamiento, ajena, {1})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES)
    limite = enviado_antes_de(_local(MARTES_22), 7)

    assert almacenamiento.devolver_el_atrasado(
        NEGOCIO, ajena.renglones[0].renglon_id, DUENO, limite
    ) is None


def test_lo_ya_pedido_trae_lo_cancelado_con_el_principio_de_su_lista(almacenamiento):
    lunes = almacenamiento.insertar_la_lista(
        NEGOCIO, MARTES, Ventana(LUNES, MARTES), [_renglon(1)]
    )
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)

    assert ya.fue_cancelado
    assert ya.estado_del_pedido == CANCELADO
    assert ya.ventas_desde_la_lista == LUNES
    assert ya.retiene_desde == LUNES
    assert ya.renglon.cancelado_por == DUENO


def test_lo_cancelado_se_olvida_cuando_una_lista_cerrada_lo_trae(almacenamiento):
    """Igual que un recibido: en cuanto una lista posterior CERRADA lo trae, sus
    ventas ya se propusieron, y recordarlo más las propondría dos veces."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    martes = _lista_con(almacenamiento, MARTES, [1])
    assert len(almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)) == 1, (
        "Una lista posterior ABIERTA todavía no pidió nada: sigue recordándose."
    )

    almacenamiento.cerrar(NEGOCIO, martes.pedido_sugerido_id)
    assert almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES) == ()


def test_lo_cancelado_se_olvida_si_se_volvio_a_pedir(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)
    martes = _lista_con(almacenamiento, MARTES, [1])
    _enviar_en_el_doble(almacenamiento, martes, {1}, proveedor="levic")

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)

    assert ya.esta_en_transito
    assert ya.fecha_del_pedido == MARTES


def test_un_recibido_se_olvida_si_una_lista_posterior_lo_cancelo(almacenamiento):
    """El cancelado de después ya trae lo del recibido de antes (se armó con la
    memoria): recordar los dos serían dos intervalos del mismo producto."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.poner_estado_del_renglon(
        lunes.renglones[0].renglon_id,
        "recibido",
        recibido_por=CORREO,
        recibido_en=_local(MARTES),
        piezas_recibidas=lunes.renglones[0].cantidad_a_pedir,
    )
    martes = almacenamiento.insertar_la_lista(
        NEGOCIO, MARTES, Ventana(MARTES, MARTES), [_renglon(1, ventas_desde=MARTES)]
    )
    enviado = _enviar_en_el_doble(almacenamiento, martes, {1})
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)

    [ya] = almacenamiento.lo_ya_pedido(NEGOCIO, antes_de=MIERCOLES)

    assert ya.fue_cancelado
    assert ya.fecha_del_pedido == MARTES


def test_los_check_del_pedido_cancelado_en_python():
    base = {
        "negocio": NEGOCIO,
        "proveedor": "nadro",
        "proveedor_id": 1,
        "total_sin_iva": None,
        "enviado_por": CORREO,
        "enviado_en": _local(LUNES),
    }
    revisar_el_pedido(
        {**base, "estado": CANCELADO, "cancelado_por": DUENO, "cancelado_en": _local(MARTES)}
    )
    with pytest.raises(ValueError, match="ck_pedido_cancelacion"):
        revisar_el_pedido({**base, "estado": CANCELADO, "cancelado_por": None, "cancelado_en": None})
    with pytest.raises(ValueError, match="ck_pedido_cancelacion"):
        revisar_el_pedido(
            {**base, "estado": ENVIADO, "cancelado_por": DUENO, "cancelado_en": _local(MARTES)}
        )
    with pytest.raises(ValueError, match="ck_pedido_cancelado_por"):
        revisar_el_pedido(
            {**base, "estado": CANCELADO, "cancelado_por": "", "cancelado_en": _local(MARTES)}
        )
    with pytest.raises(ValueError, match="ck_pedido_envio"):
        revisar_el_pedido(
            {
                **base,
                "estado": CANCELADO,
                "enviado_por": None,
                "enviado_en": None,
                "cancelado_por": DUENO,
                "cancelado_en": _local(MARTES),
            }
        )


def test_los_check_del_renglon_cancelado_en_python(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    fila = dict(almacenamiento.listas[0]["renglones"][0])

    revisar_el_renglon(
        {**fila, "estado": RENGLON_CANCELADO, "cancelado_por": DUENO, "cancelado_en": _local(MARTES)}
    )
    with pytest.raises(ValueError, match="ck_renglon_cancelacion"):
        revisar_el_renglon({**fila, "estado": RENGLON_CANCELADO})
    with pytest.raises(ValueError, match="ck_renglon_cancelacion"):
        revisar_el_renglon({**fila, "cancelado_por": DUENO, "cancelado_en": _local(MARTES)})
    with pytest.raises(ValueError, match="ck_renglon_cancelado_por"):
        revisar_el_renglon(
            {**fila, "estado": RENGLON_CANCELADO, "cancelado_por": "", "cancelado_en": _local(MARTES)}
        )
    assert lunes.renglones[0].cancelado_por is None


def test_la_interfaz_trae_las_dos_escrituras():
    from continental.almacenamiento import AlmacenamientoDelPedido

    assert hasattr(AlmacenamientoDelPedido, "cancelar_el_pedido")
    assert hasattr(AlmacenamientoDelPedido, "devolver_el_atrasado")
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)


# ------------------------------------------------------ los estados y el glosario


def test_cancelado_es_el_tercer_estado_del_pedido_y_el_sexto_del_renglon():
    assert ESTADOS_DEL_PEDIDO == (BORRADOR, ENVIADO, CANCELADO)
    assert ESTADOS_DEL_RENGLON[-1] == RENGLON_CANCELADO == "cancelado"


def test_el_glosario_nombra_cancelado_y_atrasado_sin_confundirlo_con_vencido():
    glosario = _texto(GLOSARIO)

    assert "`cancelado`" in glosario
    assert "**Atrasado**" in glosario
    # Atrasado NO es un estado: no puede estar en ninguna de las dos tuplas.
    assert "atrasado" not in ESTADOS_DEL_RENGLON
    assert "vencido" not in ESTADOS_DEL_RENGLON


# ------------------------------------------------------- el SQL, como texto


def test_cancelar_tiene_la_transicion_en_el_where():
    sentencia = _sentencia_python("_CANCELAR_EL_PEDIDO")

    assert "set estado = 'cancelado'" in sentencia
    assert "p.negocio = :negocio" in sentencia
    assert "p.estado = 'enviado'" in sentencia
    assert "not exists" in sentencia
    assert "'recibido', 'recibido parcial'" in sentencia
    assert "cancelado_en = now()" in sentencia
    # Cancelar NO exige la lista abierta, igual que enviar (ADR 0009): la
    # lista ni siquiera aparece en la sentencia.
    assert "pedidos.pedido_sugerido" not in sentencia
    assert "s.estado" not in sentencia


def test_los_renglones_cancelados_son_solo_los_en_transito_de_ese_pedido():
    sentencia = _sentencia_python("_RENGLONES_CANCELADOS")

    assert "r.negocio = :negocio" in sentencia
    assert "r.pedido_id = :pedido_id" in sentencia
    assert "r.estado = 'en tránsito'" in sentencia
    assert "set estado = 'cancelado'" in sentencia


def test_devolver_el_atrasado_tiene_la_transicion_y_el_limite_en_el_where():
    sentencia = _sentencia_python("_DEVOLVER_EL_ATRASADO")

    assert "r.estado = 'en tránsito'" in sentencia
    assert "p.estado = 'enviado'" in sentencia
    assert "p.enviado_en < :enviado_antes_de" in sentencia
    assert "p.negocio = r.negocio" in sentencia
    assert "r.negocio = :negocio" in sentencia
    for prohibida in ("current_date", "localtimestamp", "interval"):
        assert prohibida not in sentencia.lower()


def test_lo_ya_pedido_trae_lo_cancelado_y_el_principio_de_la_lista():
    sentencia = _sentencia_python("_LO_YA_PEDIDO")

    assert "r.estado = 'cancelado'" in sentencia
    assert "r2.estado = 'cancelado'" in sentencia
    assert "s.ventas_consideradas_desde" in sentencia
    assert "p.estado as estado_del_pedido" in sentencia
    assert "r.cancelado_por" in sentencia


@pytest.mark.parametrize("nombre", ["_LEER_RENGLONES", "_LEER_RENGLON_POR_ID"])
def test_las_lecturas_del_renglon_traen_la_firma_de_la_cancelacion(nombre):
    assert "cancelado_por, cancelado_en" in _sentencia_python(nombre)


def test_la_lectura_de_los_pedidos_trae_la_firma_de_la_cancelacion():
    assert "cancelado_por, cancelado_en" in _sentencia_python("_LEER_PEDIDOS")


def test_crear_tablas_tiene_los_tres_estados_y_las_dos_firmas():
    sentencias = _sentencias(CREAR_TABLAS)

    assert "CHECK (estado IN ('borrador', 'enviado', 'cancelado'))" in sentencias
    assert "ck_pedido_cancelacion" in sentencias
    assert "ck_renglon_cancelacion" in sentencias
    assert "(estado IN ('enviado', 'cancelado'))" in sentencias
    assert "'recibido parcial', 'descartado', 'cancelado'" in sentencias
    assert re.search(r"cancelado_en\s+timestamptz", sentencias)


def test_la_migracion_0009_es_idempotente_no_crea_tabla_y_va_con_lf():
    texto = _texto(MIGRACION)
    sentencias = _sentencias(MIGRACION)

    assert "CREATE TABLE" not in sentencias.upper()
    assert "ADD COLUMN IF NOT EXISTS cancelado_por text" in sentencias
    assert "DROP CONSTRAINT IF EXISTS ck_pedido_estado" in sentencias
    assert "CHECK (estado IN ('borrador', 'enviado', 'cancelado'))" in sentencias
    assert "DROP CONSTRAINT IF EXISTS ck_renglon_estado" in sentencias
    assert "current_user = 'continental'" in sentencias
    assert "crear_rol.sql" in texto
    assert "BEGIN;" in sentencias and "COMMIT;" in sentencias
    assert "\r" not in texto


def test_verificar_rol_mira_los_estados_y_las_firmas_nuevas():
    texto = _sentencias(VERIFICAR_ROL)

    for n in (31, 32, 33):
        assert f"({n}," in texto
    assert "'ck_pedido_cancelacion'" in texto
    assert "'ck_renglon_cancelacion'" in texto


def test_el_adr_existe_y_enmienda_al_0009_por_escrito():
    """Tensión 1: el código no puede contradecir un ADR sin que el ADR lo diga."""
    texto = _texto(ADR)

    assert texto.startswith("# 0013")
    assert "0009" in texto
    assert "desenviar" in texto
    assert "0013" in _texto(ADR_0009)


# ------------------------------------------------------------- el YAML


def test_el_umbral_sale_del_yaml_con_su_comentario():
    texto = _texto(CONFIG)

    assert "dias_en_transito_para_atrasado: 7" in texto
    assert dias_en_transito_para_atrasado_configurados() == 7


def _yaml_con(monkeypatch, pedido: dict) -> None:
    import continental.config as config

    monkeypatch.setattr(
        config,
        "cargar",
        lambda: config.Ajustes(negocio=NEGOCIO, warehouse_url=None, modulos={}, pedido=pedido),
    )


def test_el_umbral_es_el_que_diga_el_yaml_y_no_uno_escrito_en_el_codigo(monkeypatch):
    _yaml_con(monkeypatch, {"dias_en_transito_para_atrasado": 11})

    assert dias_en_transito_para_atrasado_configurados() == 11


@pytest.mark.parametrize("valor", [None, "siete", 0, -3, 7.5, True, "7"])
def test_un_umbral_que_falta_o_esta_mal_escrito_truena(monkeypatch, valor):
    """Regla 4. Al revés que `dias_primera_vez`, aquí tronar no deja a nadie sin
    pedido: lo único que se pierde es la señal, y la pantalla lo dice con su
    hueco. Un número de omisión elegido en silencio sería una válvula que se
    abre en un día que nadie escogió."""
    _yaml_con(monkeypatch, {} if valor is None else {"dias_en_transito_para_atrasado": valor})

    with pytest.raises(ValueError, match="dias_en_transito_para_atrasado"):
        dias_en_transito_para_atrasado_configurados()


# ==========================================================================
# LO QUE SE VE — las rutas, de punta a punta y de varios días
# ==========================================================================


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def _enviar_a_nadro(cliente, almacenamiento, lista: dict, productos: set[int]) -> dict:
    """Pone precio de NADRO a esos productos, descarta el resto, parte y envía."""
    for r in lista["renglones"]:
        if r["producto_id"] in productos:
            almacenamiento.guardar_precios(NEGOCIO, r["renglon_id"], [_lectura("nadro", "12.50")])
        else:
            cliente.post(f"/api/renglon/{r['renglon_id']}/descartar", headers=FIRMA)
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    assert partida["ok"] is True, partida
    [pedido] = [p for p in partida["pedidos"] if p["proveedor"] == "nadro"]
    enviada = cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=FIRMA).json()
    assert enviada["ok"] is True, enviada
    return pedido


def _cerrar(cliente, lista: dict) -> None:
    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")
    assert respuesta.status_code == 200, respuesta.json()


def _cancelar(cliente, pedido_id: int, quien: str = DUENO):
    return cliente.post(
        f"/api/pedido/{pedido_id}/cancelar",
        headers={"Cf-Access-Authenticated-User-Email": quien},
    )


def _devolver(cliente, renglon_id: int, quien: str = DUENO):
    return cliente.post(
        f"/api/renglon/{renglon_id}/devolver-atrasado",
        headers={"Cf-Access-Authenticated-User-Email": quien},
    )


def _por_producto(lista: dict) -> dict[int, dict]:
    return {r["producto_id"]: r for r in lista["renglones"]}


def _fijar_la_hora(monkeypatch, instante: dt.datetime) -> None:
    from continental.web import app as modulo

    monkeypatch.setattr(modulo, "_ahora", lambda: instante)


def test_casilla_2_cancelar_con_las_listas_cerradas_trae_todo_una_sola_vez(
    cliente, almacen, almacenamiento
):
    """**La tensión 3, de punta a punta, con las listas de en medio CERRADAS.**

    - Lunes: se venden 3 del producto 1, se envían a NADRO, se cierra.
    - Martes: se venden 2 más; el 1 no se propone (viene en camino). Se cierra:
      el corte avanza al martes.
    - Se descubre que el pedido del lunes nunca se capturó, y se cancela.
    - Miércoles: se vende 1 más. La lista propone **6**: las 3 que el renglón
      cubría —nunca se pidieron—, las 2 del martes y la del miércoles.
    - Jueves: con el miércoles cerrado, **1** y nada más. Nada dos veces.
    """
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    pedido = _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert sorted(_por_producto(martes)) == [2]
    _cerrar(cliente, martes)

    respuesta = _cancelar(cliente, pedido["pedido_id"])
    assert respuesta.status_code == 200, respuesta.json()
    assert respuesta.json()["renglones_cancelados"] == 1

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1), _venta(MIERCOLES, 2, 1)]
    miercoles = _abrir(cliente)
    uno = _por_producto(miercoles)[1]
    assert uno["cantidad_propuesta"] == 6, "Lo que el renglón cancelado cubría se perdió."
    assert uno["ventas_desde"] == LUNES.isoformat()
    assert "lunes 14 de septiembre" in uno["frase_de_la_ventana"]
    assert _por_producto(miercoles)[2]["cantidad_propuesta"] == 1
    _cerrar(cliente, miercoles)

    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    jueves = _abrir(cliente)
    assert _por_producto(jueves)[1]["cantidad_propuesta"] == 1, "Se propuso dos veces."
    assert _por_producto(jueves)[1]["ventas_desde"] is None


def test_casilla_2_cancelar_con_las_listas_sin_cerrar_tampoco_duplica(
    cliente, almacen, almacenamiento
):
    """Las listas de en medio sin cerrar: la ventana ya vuelve a sus días por
    el piso del ticket 09, y la memoria no puede sumarlos otra vez."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    pedido = _enviar_a_nadro(cliente, almacenamiento, lunes, {1})

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert sorted(_por_producto(martes)) == [2]

    assert _cancelar(cliente, pedido["pedido_id"]).status_code == 200

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1)]
    miercoles = _abrir(cliente)
    assert miercoles["ventas_consideradas_desde"] == LUNES.isoformat()
    assert _por_producto(miercoles)[1]["cantidad_propuesta"] == 6
    assert _por_producto(miercoles)[1]["ventas_desde"] is None
    _cerrar(cliente, miercoles)

    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    assert _por_producto(_abrir(cliente))[1]["cantidad_propuesta"] == 1


def test_casilla_2_cancelar_el_mismo_dia_lo_trae_en_la_siguiente_y_no_en_esta(
    cliente, almacen, almacenamiento
):
    """Alguien apretó Enviar por error y se da cuenta en el acto. El renglón NO
    vuelve a `abierto` en esta lista —eso sería desenviar por la puerta de
    atrás, y el pedido de NADRO de esta lista ya existe—: se ve cancelado, y el
    producto vuelve en la siguiente con todo lo suyo."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    pedido = _enviar_a_nadro(cliente, almacenamiento, lunes, {1})

    cuerpo = _cancelar(cliente, pedido["pedido_id"]).json()
    assert cuerpo["ok"] is True
    assert cuerpo["pedido"]["estado"] == CANCELADO
    assert cuerpo["pedido"]["cancelado_por"] == DUENO
    assert "siguiente lista" in cuerpo["frase"]

    otra_vez = _abrir(cliente)
    [renglon] = otra_vez["renglones"]
    assert renglon["estado"] == RENGLON_CANCELADO
    assert renglon["esta_cancelado"] is True
    assert "siguiente lista, no en ésta" in renglon["frase_de_lo_cancelado"]
    [guardado] = otra_vez["pedidos"]
    assert guardado["fue_cancelado"] is True
    assert guardado["se_puede_enviar"] is False
    assert guardado["se_puede_cancelar"] is False
    assert otra_vez["particion"]["hay"] is False
    assert "se dejó de esperar" in otra_vez["particion"]["sin_nada_por_repartir"]
    _cerrar(cliente, otra_vez)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2)]
    martes = _abrir(cliente)
    assert _por_producto(martes)[1]["cantidad_propuesta"] == 5
    assert _por_producto(martes)[1]["ventas_desde"] == LUNES.isoformat()


def test_casilla_3_cancelar_queda_firmado_y_la_firma_no_es_permiso(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    pedido = _enviar_a_nadro(cliente, almacenamiento, _abrir(cliente), {1})

    sin_encabezado = cliente.post(f"/api/pedido/{pedido['pedido_id']}/cancelar")

    assert sin_encabezado.status_code == 200
    assert almacenamiento.pedidos[0]["cancelado_por"] == "sin-identificar"
    assert almacenamiento.pedidos[0]["cancelado_en"] is not None
    assert almacenamiento.listas[0]["renglones"][0]["cancelado_por"] == "sin-identificar"


def test_cancelar_lo_que_no_se_puede_es_un_409_con_palabras(cliente, almacen, almacenamiento):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    pedido = _enviar_a_nadro(cliente, almacenamiento, _abrir(cliente), {1})
    assert _cancelar(cliente, pedido["pedido_id"]).status_code == 200

    otra_vez = _cancelar(cliente, pedido["pedido_id"])

    assert otra_vez.status_code == 409
    assert "ya no se puede cancelar" in otra_vez.json()["detalle"]


def test_cancelar_con_el_almacenamiento_caido_no_suelta_la_cadena(
    cliente, almacenamiento, caplog
):
    almacenamiento.falla = RuntimeError("postgresql://continental:secreta@atlas/farmacia")

    with caplog.at_level(logging.ERROR, logger="continental"):
        cuerpo = _cancelar(cliente, 1).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "secreta" not in str(cuerpo)


def test_casilla_1_y_4_el_atrasado_se_senala_y_se_devuelve_uno_por_uno(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**De punta a punta, en dos semanas.**

    - Lunes 14: se venden 3 del 1 y 3 del 2, se envían los dos a NADRO, se
      cierra.
    - Martes 15 a viernes 18: cada día 1 del producto 1. Los dos se quedan
      fuera (vienen en camino) y cada lista se cierra.
    - Martes 22, a las 9 de la mañana: ocho días. El bloque dice que los dos
      están **atrasados**, con los días a la vista.
    - Se devuelve SOLO el 1. El 2 sigue en camino y el pedido sigue enviado.
    - Miércoles 23: el 1 vuelve con **todo**: las 3 que cubría, las 4 de esa
      semana, la del 22 y la del 23 = 9. El 2 no aparece.
    - Jueves 24, con el 23 cerrado: 1.
    """
    almacen.catalogo_en_memoria = [_producto(1), _producto(2), _producto(3)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1, 2})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES, 11)
    _cerrar(cliente, lunes)

    for dia in (MARTES, MIERCOLES, JUEVES, VIERNES):
        _fijar_la_hora(monkeypatch, _local(dia, 9))
        almacen.ventas_en_memoria += [_venta(dia, 1, 1), _venta(dia, 3, 1)]
        lista = _abrir(cliente)
        assert sorted(_por_producto(lista)) == [3]
        for fila in lista["en_camino"]["renglones"]:
            assert fila["atrasado"] is False
            assert fila["se_puede_devolver"] is False
        _cerrar(cliente, lista)

    _fijar_la_hora(monkeypatch, _local(MARTES_22, 9))
    almacen.ventas_en_memoria += [_venta(MARTES_22, 1, 1), _venta(MARTES_22, 3, 1)]
    martes_22 = _abrir(cliente)
    bloque = martes_22["en_camino"]
    filas = {f["producto_id"]: f for f in bloque["renglones"]}
    assert set(filas) == {1, 2}
    for fila in filas.values():
        assert fila["dias_en_transito"] == 8
        assert fila["atrasado"] is True
        assert fila["se_puede_devolver"] is True
        assert "8 días" in fila["frase_del_atraso"]
    assert bloque["umbral_del_atraso"] == 7
    assert bloque["frase_de_los_atrasados"].startswith("2 renglones")

    respuesta = _devolver(cliente, filas[1]["renglon_id"])
    assert respuesta.status_code == 200, respuesta.json()
    assert respuesta.json()["ok"] is True
    assert "siguiente lista" in respuesta.json()["frase"]

    recargada = _abrir(cliente)
    assert [f["producto_id"] for f in recargada["en_camino"]["renglones"]] == [2]
    [vuelve] = recargada["en_camino"]["vuelven"]
    assert vuelve["producto_id"] == 1
    assert DUENO in vuelve["frase"]
    assert almacenamiento.pedidos[0]["estado"] == ENVIADO
    _cerrar(cliente, recargada)

    _fijar_la_hora(monkeypatch, _local(MIERCOLES_23, 9))
    almacen.ventas_en_memoria += [_venta(MIERCOLES_23, 1, 1), _venta(MIERCOLES_23, 2, 5)]
    miercoles_23 = _abrir(cliente)
    assert _por_producto(miercoles_23)[1]["cantidad_propuesta"] == 9
    assert _por_producto(miercoles_23)[1]["ventas_desde"] == LUNES.isoformat()
    assert 2 not in _por_producto(miercoles_23), "Lo que sigue en camino se propuso."
    _cerrar(cliente, miercoles_23)

    _fijar_la_hora(monkeypatch, _local(JUEVES_24, 9))
    almacen.ventas_en_memoria += [_venta(JUEVES_24, 1, 1)]
    jueves_24 = _abrir(cliente)
    assert _por_producto(jueves_24)[1]["cantidad_propuesta"] == 1
    assert jueves_24["en_camino"]["vuelven"] == []


def test_casilla_4_lo_que_no_esta_atrasado_no_se_devuelve(
    cliente, almacen, almacenamiento, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES, 11)
    _cerrar(cliente, lunes)
    _fijar_la_hora(monkeypatch, _local(MARTES_22 - dt.timedelta(days=1), 23, 59))

    respuesta = _devolver(cliente, lunes["renglones"][0]["renglon_id"])

    assert respuesta.status_code == 409
    assert "7 días" in respuesta.json()["detalle"]
    assert almacenamiento.listas[0]["renglones"][0]["estado"] == RENGLON_EN_TRANSITO


def test_devolver_con_el_umbral_roto_no_devuelve_nada_y_lo_dice(
    cliente, almacen, almacenamiento, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    almacenamiento.pedidos[0]["enviado_en"] = _local(LUNES, 11)
    _fijar_la_hora(monkeypatch, _local(MARTES_22, 9))
    _yaml_con(monkeypatch, {"dias_en_transito_para_atrasado": "siete"})

    cuerpo = _devolver(cliente, lunes["renglones"][0]["renglon_id"]).json()

    assert cuerpo["ok"] is False
    assert "dias_en_transito_para_atrasado" in cuerpo["detalle"]
    assert "ValueError" in cuerpo["detalle"]
    assert almacenamiento.listas[0]["renglones"][0]["estado"] == RENGLON_EN_TRANSITO


def test_con_el_umbral_roto_el_bloque_es_un_hueco_y_la_lista_sale_igual(
    cliente, almacen, almacenamiento, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar_a_nadro(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)
    _yaml_con(monkeypatch, {})

    almacen.ventas_en_memoria += [_venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    bloque = martes["en_camino"]

    assert [f["producto_id"] for f in bloque["renglones"]] == [1]
    assert bloque["renglones"][0]["atrasado"] is None
    assert bloque["umbral_del_atraso"] is None
    assert "ValueError" in bloque["frase_del_umbral"]


def test_devolver_con_el_almacenamiento_caido_no_suelta_la_cadena(
    cliente, almacenamiento, caplog
):
    almacenamiento.falla = RuntimeError("postgresql://continental:secreta@atlas/farmacia")

    with caplog.at_level(logging.ERROR, logger="continental"):
        cuerpo = _devolver(cliente, 1).json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "secreta" not in str(cuerpo)


def test_el_bloque_ofrece_cancelar_el_pedido_de_una_lista_anterior(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 1)]
    lunes = _abrir(cliente)
    pedido = _enviar_a_nadro(cliente, almacenamiento, lunes, {1, 2})
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 1)]
    [ofrecido] = _abrir(cliente)["en_camino"]["pedidos"]

    assert ofrecido["pedido_id"] == pedido["pedido_id"]
    assert ofrecido["renglones_en_camino"] == 2
    assert "portal de NADRO" in ofrecido["frase_para_cancelar"]


def test_el_pedido_enviado_de_hoy_se_ofrece_para_cancelar_con_su_frase(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    _enviar_a_nadro(cliente, almacenamiento, _abrir(cliente), {1})

    [pedido] = _abrir(cliente)["pedidos"]

    assert pedido["fue_enviado"] is True
    assert pedido["se_puede_cancelar"] is True
    assert pedido["motivo_para_no_cancelar"] is None
    assert "Su renglón deja de estar en camino" in pedido["frase_para_cancelar"]


def test_el_lote_de_la_noche_tambien_trae_lo_cancelado(almacen, almacenamiento):
    """La memoria es la misma en la pantalla y en el lote: el lote la lee con
    `lo_ya_pedido` y no tiene que saber que cancelar existe."""
    from continental.dobles import DoyleFalso
    from continental.lote import correr_el_lote

    almacen.catalogo_en_memoria = [_producto(1)]
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    almacenamiento.cerrar(NEGOCIO, lunes.pedido_sugerido_id)
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO)
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(MARTES, 1, 2)]

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

    [renglon] = almacenamiento.leer(NEGOCIO, MARTES).renglones
    assert renglon.propuesto.cantidad_propuesta == 5
    assert renglon.propuesto.ventas_desde == LUNES


# ------------------------------------------------------------- la pantalla


def test_la_pantalla_llama_a_las_dos_rutas():
    pantalla = pantalla_completa()

    assert "'/cancelar'" in pantalla
    assert "'/devolver-atrasado'" in pantalla


def test_la_pantalla_pinta_las_frases_que_llegan_hechas():
    """Lección del ticket 15: las frases que afirman algo son de Python."""
    pantalla = pantalla_completa()

    for llave in (
        "frase_del_atraso",
        "frase_de_los_atrasados",
        "advertencia_al_devolver",
        "frase_para_cancelar",
        "frase_de_lo_cancelado",
        "frase_del_umbral",
    ):
        assert llave in pantalla, llave
    # Y no las compone: ni los días ni el umbral se pegan a mano.
    assert "días en camino" not in pantalla
    assert "nunca se capturó" not in pantalla


def test_la_captura_solo_se_pinta_para_un_borrador():
    """Un cancelado no es enviado ni borrador: `!fue_enviado` le pintaría la
    lista de captura con sus casillas a un pedido que ya no existe."""
    pantalla = pantalla_completa()

    assert "!guardado.fue_enviado && guardado.captura" not in pantalla
    assert "!g.fue_enviado && g.captura" not in pantalla
