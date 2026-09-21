"""Recibido parcial y marcado a mano (ticket 27, ADR 0015).

**Lo que arregla.** Hasta el ticket 26 un renglón en tránsito solo salía de ahí
con una compra de SICAR que trajera **al menos** lo pedido. El caso de todos los
días —el proveedor manda la mitad— no tenía salida: la propuesta decía "es un
parcial, todavía no se puede marcar aquí", y lo que nunca deja compra en SICAR
(QuePharma, 17.7% del catálogo) no tenía ninguna.

**Las cinco decisiones del ADR 0015, fijadas aquí:**

1. **Lo que faltó vuelve como piezas, no como ventas.** Pedí 10, llegaron 6: las
   4 que faltan se suman a la siguiente lista **aparte** de lo vendido mientras
   venía (que vuelve por el ancla del ticket 24). Así ninguna venta se propone
   dos veces y ninguna se pierde. Los escenarios de varios días, con sus
   números, están abajo.
2. **El estado del pedido se CALCULA de sus renglones**: `recibido` si todos
   llegaron completos, `recibido parcial` si alguno llegó corto o se dejó de
   esperar. En la tabla sigue `enviado`, que es lo que una persona declaró.
3. **Dos facturas**: lo que se escribe es **cuántas llegaron en total**. Un
   parcial al que le llega el resto se corrige a 10 y queda `recibido`; una
   cifra mal capturada se corrige igual. Solo mientras lo que faltó no se haya
   atendido en una lista posterior.
4. **Cancelar después de recibir parcial sigue prohibido**: si algo llegó, se
   capturó.
5. **Un renglón con propuesta que trae de menos** ya tiene salida: "recibir
   parcial" con esa evidencia.

Los tres seams del repo: lo puro, lo que se guarda (el doble, los CHECK en
Python, el SQL como texto) y lo que se ve (las rutas de punta a punta, varios
días, y la pantalla). **Ninguna prueba toca Postgres ni duerme, y ningún dato es
real.**
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import (
    CANCELADO,
    ENVIADO,
    PEDIDO_RECIBIDO,
    PEDIDO_RECIBIDO_PARCIAL,
    RENGLON_CANCELADO,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    LoYaPedido,
    PedidoGuardado,
    RenglonGuardado,
    Ventana,
    columnas_del_renglon,
    revisar_el_renglon,
)
from continental.recepcion import (
    PIEZAS_RECIBIDAS_MAXIMAS,
    estado_del_pedido,
    estado_por_las_piezas,
    frase_de_la_cantidad,
    frase_de_la_recepcion_del_pedido,
    frase_de_lo_recibido,
    frase_de_lo_recibido_a_mano,
    frase_del_motivo,
    MOTIVO_NUNCA_EN_COMPRAS,
    MOTIVO_SIN_PUENTE,
    piezas_escritas,
    proponer,
    recepcion_como_json,
)
from continental.sugerido import Renglon, armar_la_lista, calcular_pedido_sugerido
from continental.transito import (
    MemoriaDeLoPedido,
    en_camino_como_json,
    frase_de_lo_que_falto,
    memoria_de_lo_pedido,
)

RAIZ = Path(__file__).resolve().parent.parent

NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
DUENO = "dueno@farmacia.mx"
CENTRO = dt.timezone(dt.timedelta(hours=-6))

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)
SABADO = dt.date(2026, 9, 19)

NADRO = 1


def _local(fecha: dt.date, hora: int = 10, minuto: int = 0) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=CENTRO)


def _renglon(producto_id: int, cantidad: int = 10, piezas_que_faltaron: int = 0) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        piezas_vendidas=float(cantidad - piezas_que_faltaron),
        cantidad_propuesta=cantidad,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
        piezas_que_faltaron=piezas_que_faltaron,
    )


def _guardado(
    renglon_id: int,
    producto_id: int,
    estado: str,
    *,
    cantidad: int = 10,
    cantidad_final: int | None = None,
    piezas_recibidas: float | None = None,
    piezas_que_faltaron: int = 0,
    compras: tuple[int, ...] | None = None,
    pedido_id: int = 7,
) -> RenglonGuardado:
    recibido = estado in (RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL)
    cancelado = estado == RENGLON_CANCELADO
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=_renglon(producto_id, cantidad, piezas_que_faltaron),
        cantidad_final=cantidad_final,
        ajustada_por=CORREO if cantidad_final is not None else None,
        ajustada_en=_local(LUNES, 9) if cantidad_final is not None else None,
        pedido_id=pedido_id,
        recibido_por=CORREO if recibido else None,
        recibido_en=_local(JUEVES, 11) if recibido else None,
        recibido_con_compras=compras,
        piezas_recibidas=piezas_recibidas,
        cancelado_por=CORREO if cancelado else None,
        cancelado_en=_local(JUEVES, 11) if cancelado else None,
    )


def _ya(
    producto_id: int,
    estado: str,
    *,
    renglon_id: int | None = None,
    ventas_hasta: dt.date = LUNES,
    **kwargs,
) -> LoYaPedido:
    return LoYaPedido(
        renglon=_guardado(renglon_id or producto_id * 10, producto_id, estado, **kwargs),
        pedido_sugerido_id=1,
        fecha_del_pedido=ventas_hasta,
        ventas_hasta=ventas_hasta,
        proveedor="nadro",
        enviado_por=CORREO,
        enviado_en=_local(ventas_hasta, 11),
        ventas_desde_la_lista=ventas_hasta,
        estado_del_pedido=ENVIADO,
        proveedor_id=NADRO,
    )


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


def _compra(compra_id: int, producto_id: int, fecha: dt.date, cantidad: float) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=compra_id,
        producto_id=producto_id,
        proveedor_id=NADRO,
        fecha=fecha,
        cantidad=cantidad,
        precio_unitario_pagado=12.5,
        importe_pagado=12.5 * cantidad,
        folio="F-1",
    )


# ==========================================================================
# LO PURO — cuánto faltó, cómo vuelve, y cómo se dice
# ==========================================================================


def test_lo_que_falto_es_lo_pedido_menos_lo_que_llego():
    """Pedí 10, llegaron 6: faltaron 4. "Lo pedido" es `cantidad_a_pedir`: la
    corrección de la persona si la hubo, porque es lo que se le pidió al
    proveedor."""
    assert _guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6).lo_que_falto == 4
    corregido = _guardado(
        1, 1, RENGLON_RECIBIDO_PARCIAL, cantidad_final=8, piezas_recibidas=6
    )
    assert corregido.lo_que_falto == 2


def test_lo_que_falto_se_redondea_hacia_arriba_como_lo_vendido():
    """La evidencia de SICAR puede traer granel (2.5). A un proveedor no se le
    piden 2.5, y hacia arriba por la misma razón que `_piezas_a_pedir`:
    redondear a la baja repondría de menos, en silencio."""
    assert (
        _guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, cantidad=5, piezas_recibidas=2.5).lo_que_falto
        == 3
    )


@pytest.mark.parametrize(
    "estado,piezas",
    [(RENGLON_RECIBIDO, 10), (RENGLON_RECIBIDO, 12), (RENGLON_EN_TRANSITO, None)],
)
def test_solo_un_parcial_tiene_algo_que_falto(estado, piezas):
    assert _guardado(1, 1, estado, piezas_recibidas=piezas).lo_que_falto == 0


def test_un_parcial_sin_piezas_no_sabe_que_falto_y_truena():
    """Regla 4: adivinar cuántas faltaron —cero, o todas— sería perder piezas
    o pedirlas dos veces, en silencio."""
    with pytest.raises(ValueError, match="cuántas piezas llegaron"):
        _ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=None)


def test_lo_que_vuelve_de_cada_estado():
    """El parcial devuelve lo que faltó. El cancelado devuelve **todo lo que
    cubría**, y eso incluye lo que faltó de antes y él traía (ADR 0013). El
    recibido completo no devuelve piezas: las que traía, llegaron."""
    assert _ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6).piezas_que_vuelven == 4
    assert _ya(1, RENGLON_CANCELADO, piezas_que_faltaron=4).piezas_que_vuelven == 4
    assert (
        _ya(1, RENGLON_RECIBIDO, piezas_recibidas=10, piezas_que_faltaron=4).piezas_que_vuelven
        == 0
    )
    assert _ya(1, RENGLON_EN_TRANSITO).piezas_que_vuelven == 0


def test_la_memoria_recuerda_lo_que_falto_aparte_de_lo_vendido():
    """**La decisión 1.** Lo vendido mientras venía vuelve **por fecha** (el ancla
    del 24: desde el martes); lo que faltó vuelve **por piezas**. Son dos cosas
    distintas y se guardan en dos mapas."""
    memoria = memoria_de_lo_pedido([_ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6)])

    assert memoria.desde == {1: MARTES}
    assert memoria.faltaron == {1: 4}
    assert memoria.piezas_que_faltaron(1) == 4
    assert memoria.piezas_que_faltaron(2) == 0


def test_lo_que_viene_en_camino_le_gana_a_lo_que_falto():
    """Si lo que faltó ya se volvió a pedir, viene en camino: no se propone."""
    memoria = memoria_de_lo_pedido(
        [
            _ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6, renglon_id=10),
            _ya(1, RENGLON_EN_TRANSITO, renglon_id=11, ventas_hasta=MIERCOLES),
        ]
    )
    assert memoria.esta_en_camino(1)
    assert memoria.faltaron == {}


def test_un_recibido_completo_no_deja_nada_que_falte():
    memoria = memoria_de_lo_pedido([_ya(1, RENGLON_RECIBIDO, piezas_recibidas=10)])
    assert memoria.faltaron == {}
    assert memoria.desde == {1: MARTES}


def test_la_memoria_vacia_no_trae_nada_que_falte():
    assert MemoriaDeLoPedido().faltaron == {}


def test_lo_que_falto_se_suma_a_lo_vendido_y_se_dice_aparte():
    """"Se vendieron 2 y faltaron 4, se piden 6": sigue siendo aritmética que el
    encargado verifica de un vistazo, porque el renglón guarda las dos cifras."""
    lista = calcular_pedido_sugerido(
        ventas=[_venta(JUEVES, 1, 2)], catalogo=[_producto(1)], faltaron={1: 4}
    )
    [renglon] = lista.renglones
    assert renglon.piezas_vendidas == 2
    assert renglon.piezas_que_faltaron == 4
    assert renglon.cantidad_propuesta == 6


def test_lo_que_falto_entra_aunque_no_se_haya_vuelto_a_vender():
    """Un producto que faltó y no se vendió en la ventana **aparece igual**: son
    piezas que se vendieron antes, que se pidieron y no llegaron."""
    lista = calcular_pedido_sugerido(
        ventas=[_venta(JUEVES, 2, 1)], catalogo=[_producto(1), _producto(2)], faltaron={1: 4}
    )
    por_producto = {r.producto_id: r for r in lista.renglones}
    assert por_producto[1].cantidad_propuesta == 4
    assert por_producto[1].piezas_vendidas == 0
    assert por_producto[1].piezas_que_faltaron == 4
    assert por_producto[2].piezas_que_faltaron == 0


def test_sin_una_sola_venta_no_hay_lista_y_lo_que_falto_espera():
    """El domingo no hay lista. Lo que faltó no se pierde: nadie lo atendió, así
    que la memoria lo sigue trayendo hasta la primera lista con ventas."""
    lista = calcular_pedido_sugerido(ventas=[], catalogo=[_producto(1)], faltaron={1: 4})
    assert lista.renglones == ()


def test_armar_la_lista_trae_lo_que_falto_y_lo_retenido(almacen):
    """Las dos memorias juntas, sin sumar un día dos veces: lo del lunes ya se
    pidió (y 6 llegaron, 4 faltaron), lo del martes al jueves se vendió
    mientras venía."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [
        _venta(LUNES, 1, 10),
        _venta(MARTES, 1, 3),
        _venta(MIERCOLES, 1, 2),
        _venta(JUEVES, 1, 1),
    ]
    memoria = memoria_de_lo_pedido([_ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6)])

    lista = armar_la_lista(almacen, Ventana(JUEVES, JUEVES), memoria)

    [renglon] = lista.renglones
    assert renglon.piezas_vendidas == 3 + 2 + 1
    assert renglon.piezas_que_faltaron == 4
    assert renglon.cantidad_propuesta == 10
    assert renglon.ventas_desde == MARTES


# ------------------------------------------------ lo que una persona escribe


@pytest.mark.parametrize("valor,esperado", [(6, 6), (6.0, 6), (1, 1)])
def test_las_piezas_escritas_son_enteras(valor, esperado):
    assert piezas_escritas(valor) == (esperado, None)


@pytest.mark.parametrize(
    "valor,pista",
    [
        (0, "sigue en camino"),
        (-3, "sigue en camino"),
        (2.5, "enteras"),
        ("6", "número"),
        (True, "número"),
        (None, "número"),
        (PIEZAS_RECIBIDAS_MAXIMAS + 1, "no parece"),
    ],
)
def test_las_piezas_escritas_se_validan_en_el_servidor(valor, pista):
    """Entero y mayor que cero. **Cero no es recibir**: si no llegó nada, el
    renglón sigue en camino, y si no va a llegar se devuelve a la lista. Y un
    número absurdo no se guarda: es un dedo en el teclado."""
    piezas, motivo = piezas_escritas(valor)
    assert piezas is None
    assert pista in motivo


def test_mas_de_lo_pedido_se_acepta():
    """**Decidido:** más de lo pedido es `recibido`. Puede ser una bonificación o
    otro pedido del mismo producto; lo que sobra **no se descuenta** de ninguna
    lista (ADR 0012, opción 5: proponer y restar mezcla un hecho con una
    promesa)."""
    assert piezas_escritas(12) == (12, None)
    assert estado_por_las_piezas(10, 12) == RENGLON_RECIBIDO


def test_el_estado_sale_de_las_piezas():
    assert estado_por_las_piezas(10, 10) == RENGLON_RECIBIDO
    assert estado_por_las_piezas(10, 6) == RENGLON_RECIBIDO_PARCIAL
    assert estado_por_las_piezas(5, 4.999) == RENGLON_RECIBIDO_PARCIAL


# ---------------------------------------------------- el estado del pedido


def _pedido(estado: str = ENVIADO, pedido_id: int = 7) -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=pedido_id,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor="nadro",
        proveedor_id=NADRO,
        estado=estado,
        armado_en=_local(LUNES, 9),
        enviado_por=CORREO if estado != "borrador" else None,
        enviado_en=_local(LUNES, 11) if estado != "borrador" else None,
        cancelado_por=CORREO if estado == CANCELADO else None,
        cancelado_en=_local(MARTES) if estado == CANCELADO else None,
    )


def test_el_pedido_queda_recibido_si_todos_llegaron_completos():
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, RENGLON_RECIBIDO, piezas_recibidas=12),
    ]
    assert estado_del_pedido(_pedido(), renglones) == PEDIDO_RECIBIDO


def test_el_pedido_queda_recibido_parcial_si_alguno_quedo_corto():
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
    ]
    assert estado_del_pedido(_pedido(), renglones) == PEDIDO_RECIBIDO_PARCIAL


def test_un_renglon_que_se_dejo_de_esperar_tambien_deja_el_pedido_parcial():
    """Llegó uno y el otro se devolvió por atrasado: "llegaron todos" es falso."""
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, RENGLON_CANCELADO),
    ]
    assert estado_del_pedido(_pedido(), renglones) == PEDIDO_RECIBIDO_PARCIAL


def test_mientras_algo_venga_en_camino_el_pedido_sigue_enviado():
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, RENGLON_EN_TRANSITO),
    ]
    assert estado_del_pedido(_pedido(), renglones) == ENVIADO


def test_si_nada_llego_el_pedido_sigue_enviado():
    """Todo devuelto uno por uno: no se recibió nada, y decir "recibido
    parcial" afirmaría una mercancía que no llegó."""
    assert estado_del_pedido(_pedido(), [_guardado(1, 1, RENGLON_CANCELADO)]) == ENVIADO


def test_los_estados_guardados_se_respetan_y_los_ajenos_no_cuentan():
    """Borrador y cancelado son lo que una persona declaró; se dicen tal cual.
    Los renglones de otro pedido, o descartados dentro de éste, no cuentan."""
    assert estado_del_pedido(_pedido("borrador"), []) == "borrador"
    assert estado_del_pedido(_pedido(CANCELADO), []) == CANCELADO
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, "descartado"),
        _guardado(3, 3, RENGLON_EN_TRANSITO, pedido_id=99),
    ]
    assert estado_del_pedido(_pedido(), renglones) == PEDIDO_RECIBIDO


def test_la_frase_del_pedido_dice_que_llego_y_que_falto():
    renglones = [
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        _guardado(2, 2, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
        _guardado(3, 3, RENGLON_CANCELADO),
    ]
    frase = frase_de_la_recepcion_del_pedido(_pedido(), renglones)
    assert frase.startswith("Recibido parcial")
    assert "1 llegó completo" in frase
    assert "1 llegó de menos" in frase
    assert "1 se dejó de esperar" in frase
    assert "siguiente lista" in frase

    completo = frase_de_la_recepcion_del_pedido(
        _pedido(), [_guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10)]
    )
    assert completo.startswith("Recibido")
    assert "completo" in completo
    assert frase_de_la_recepcion_del_pedido(_pedido(), [_guardado(1, 1, RENGLON_EN_TRANSITO)]) is None


# ------------------------------------------------------------- las frases


def test_la_firma_de_lo_recibido_a_mano_lo_dice():
    """Firmado con quién y cuándo (casilla 5), y **sin compra que lo sostenga**:
    es la palabra de una persona."""
    frase = frase_de_lo_recibido(_guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10))
    assert frase.startswith("Recibido completo")
    assert "llegaron 10 de 10" in frase
    assert f"lo dijo {CORREO} el jueves 17 de septiembre a las 11:00" in frase
    assert "a mano" in frase


def test_la_firma_de_un_parcial_dice_cuantas_faltaron_y_adonde_van():
    frase = frase_de_lo_recibido(_guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6))
    assert frase.startswith("Recibido parcial: llegaron 6 de 10")
    assert "las 4 que faltaron vuelven a proponerse en la siguiente lista" in frase


def test_la_firma_con_compras_sigue_diciendo_que_lo_confirmo():
    frase = frase_de_lo_recibido(
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10, compras=(501,))
    )
    assert f"lo confirmó {CORREO}" in frase
    assert "1 compra de SICAR" in frase


def test_con_una_pieza_la_firma_no_se_tropieza():
    frase = frase_de_lo_recibido(
        _guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, cantidad=2, piezas_recibidas=1)
    )
    assert "llegó 1 de 2" in frase
    assert "la 1 que faltó vuelve" in frase


def test_lo_recibido_a_mano_se_contesta_con_lo_que_pasa_despues():
    parcial = frase_de_lo_recibido_a_mano(
        _guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6), antes=None
    )
    assert "quedó recibido parcial" in parcial
    assert "4 que faltaron vuelven a proponerse" in parcial

    completo = frase_de_lo_recibido_a_mano(
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10), antes=None
    )
    assert "quedó recibido" in completo and "parcial" not in completo

    de_mas = frase_de_lo_recibido_a_mano(
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=12), antes=None
    )
    assert "más de las 10" in de_mas
    assert "no se descuenta" in de_mas


def test_corregir_dice_de_cuanto_a_cuanto_y_avisa_de_lo_ya_armado():
    """Dos facturas: el jueves llegó el resto. Lo que ya está armado no se
    recalcula (ADR 0012), así que se dice dónde corregir."""
    frase = frase_de_lo_recibido_a_mano(
        _guardado(1, 1, RENGLON_RECIBIDO, piezas_recibidas=10),
        antes=_guardado(1, 1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
    )
    assert "de 6 a 10" in frase
    assert "lista que ya esté armada" in frase


def test_lo_que_falto_se_dice_en_el_renglon_que_lo_trae():
    assert frase_de_lo_que_falto(0) is None
    assert frase_de_lo_que_falto(4) == (
        "Trae también 4 piezas que faltaron en un pedido anterior: se pidieron, "
        "llegaron de menos y no se perdieron."
    )
    assert "1 pieza que faltó" in frase_de_lo_que_falto(1)


def test_la_salida_a_mano_ya_existe_y_se_dice():
    """El 26 decía "todavía no se puede desde esta pantalla". Ya se puede."""
    for motivo in (MOTIVO_SIN_PUENTE, MOTIVO_NUNCA_EN_COMPRAS):
        frase = frase_del_motivo(motivo, ("QuePharma",))
        assert "todavía no" not in frase
        assert "a mano" in frase
    fuente = (RAIZ / "src" / "continental" / "recepcion.py").read_text(encoding="utf-8")
    assert "FALTA_EL_MARCADO_MANUAL" not in fuente


def test_una_propuesta_que_trae_de_menos_ofrece_recibirla_parcial():
    """**La decisión 5.** Hasta el 26 no tenía salida: ni confirmar (sería
    "llegó completo") ni nada más."""
    ya = _ya(1, RENGLON_EN_TRANSITO, cantidad=5)
    [menos] = proponer([ya], [_compra(501, 1, MARTES, 3)]).propuestas
    assert menos.se_puede_confirmar is False
    assert menos.se_puede_recibir_parcial is True
    assert menos.etiqueta_del_parcial == "Llegaron solo 3 de 5: recibir parcial"
    frase = frase_de_la_cantidad(menos)
    assert "todavía no" not in frase
    assert "recíbelo parcial" in frase
    assert "otra factura" in frase

    [completa] = proponer([ya], [_compra(501, 1, MARTES, 5)]).propuestas
    assert completa.se_puede_recibir_parcial is False
    assert completa.etiqueta_del_parcial is None


def test_el_json_de_la_recepcion_trae_la_salida_a_mano_en_cada_renglon():
    """Cada renglón en camino —con propuesta o sin ella— se puede recibir a mano,
    y la etiqueta llega hecha de Python."""
    recepcion = proponer(
        [_ya(1, RENGLON_EN_TRANSITO, cantidad=5), _ya(2, RENGLON_EN_TRANSITO)],
        [_compra(501, 1, MARTES, 3)],
    )
    como_json = recepcion_como_json(recepcion, _local(JUEVES))
    [propuesta] = como_json["propuestas"]
    assert propuesta["se_puede_recibir_lo_que_trae"] is True
    assert propuesta["etiqueta_de_lo_que_trae"] == "Llegaron solo 3 de 5: recibir parcial"
    assert propuesta["etiqueta_a_mano"] == "Recibir a mano"
    [grupo] = como_json["esperan"]
    [renglon] = grupo["renglones"]
    assert renglon["etiqueta_a_mano"] == "Recibir a mano"
    assert "cuántas llegaron" in como_json["como_se_recibe_a_mano"]


def test_el_bloque_de_lo_que_viene_ensena_lo_que_falto_y_deja_corregirlo():
    faltaron = [_ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6)]
    bloque = en_camino_como_json((), {}, _local(JUEVES), faltaron=faltaron)
    [uno] = bloque["faltaron"]
    assert uno["renglon_id"] == 10
    assert uno["piezas_recibidas"] == 6
    assert uno["cantidad"] == 10
    assert "llegaron 6 de 10" in uno["frase"]
    assert uno["etiqueta_a_mano"] == "Corregir cuántas llegaron"
    assert "1 renglón llegó de menos" in bloque["frase_de_los_que_faltaron"]
    assert en_camino_como_json((), {}, _local(JUEVES))["faltaron"] == []


# ==========================================================================
# LO QUE SE GUARDA — el doble, los CHECK en Python y el SQL como texto
# ==========================================================================

from continental.almacenamiento import AlmacenamientoDelPedido  # noqa: E402
from continental.dobles import AlmacenamientoFalso  # noqa: E402

SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0011-recibido-parcial-y-a-mano.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def _sentencia_python(nombre: str) -> str:
    fuente = _texto(ALMACENAMIENTO)
    inicio = fuente.index('"""', fuente.index(f"{nombre} = text(")) + 3
    fin = fuente.index('"""', inicio)
    return re.sub(r"--[^\n]*", "", fuente[inicio:fin])


def _lista_con(almacenamiento, fecha: dt.date, cantidades: dict[int, int]):
    return almacenamiento.insertar_la_lista(
        NEGOCIO,
        fecha,
        Ventana(fecha, fecha),
        [_renglon(p, c) for p, c in cantidades.items()],
    )


def _enviar_en_el_doble(almacenamiento, lista, productos, proveedor_id=NADRO):
    from continental.particion import Linea, PedidoPorArmar

    renglones = [r for r in lista.renglones if r.propuesto.producto_id in productos]
    pedidos = almacenamiento.guardar_la_particion(
        lista.negocio,
        lista.pedido_sugerido_id,
        [
            PedidoPorArmar(
                proveedor="nadro",
                proveedor_id=proveedor_id,
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
    [pedido] = pedidos
    return almacenamiento.enviar_el_pedido(lista.negocio, pedido.pedido_id, CORREO)


def _en_transito(almacenamiento, fecha=LUNES, cantidades=None):
    cantidades = cantidades or {1: 10}
    lista = _lista_con(almacenamiento, fecha, cantidades)
    enviado = _enviar_en_el_doble(almacenamiento, lista, set(cantidades))
    return lista, enviado


def test_el_doble_sigue_cumpliendo_la_interfaz():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)


def test_recibir_a_mano_menos_de_lo_pedido_queda_parcial_y_firmado(almacenamiento):
    """Casillas 1, 2 y 5: cuántas llegaron, `recibido parcial`, quién y cuándo.
    **Sin compras**: a mano no hay evidencia de SICAR, y eso se guarda así."""
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones

    recibido = almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, DUENO)

    assert recibido.estado == RENGLON_RECIBIDO_PARCIAL
    assert recibido.piezas_recibidas == 6
    assert recibido.lo_que_falto == 4
    assert recibido.recibido_por == DUENO
    assert recibido.recibido_en is not None
    assert recibido.recibido_con_compras is None


def test_recibir_a_mano_lo_pedido_o_mas_queda_recibido(almacenamiento):
    _, enviado = _en_transito(almacenamiento, cantidades={1: 10, 2: 5})
    uno, dos = enviado.renglones

    assert almacenamiento.recibir_a_mano(NEGOCIO, uno, 10, DUENO).estado == RENGLON_RECIBIDO
    de_mas = almacenamiento.recibir_a_mano(NEGOCIO, dos, 7, DUENO)
    assert de_mas.estado == RENGLON_RECIBIDO
    assert de_mas.piezas_recibidas == 7


def test_lo_recibido_a_mano_cierra_el_transito_y_lo_que_falto_vuelve(almacenamiento):
    """El enganche del 24 sin tocarlo, y la memoria nueva encima."""
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, DUENO)

    memoria = memoria_de_lo_pedido(almacenamiento.lo_ya_pedido(NEGOCIO, JUEVES))
    assert not memoria.esta_en_camino(1)
    assert memoria.desde[1] == MARTES
    assert memoria.faltaron[1] == 4


@pytest.mark.parametrize("estado", ["abierto", "descartado"])
def test_recibir_a_mano_exige_que_este_en_transito(almacenamiento, estado):
    lista = _lista_con(almacenamiento, LUNES, {1: 10})
    renglon_id = lista.renglones[0].renglon_id
    if estado == "descartado":
        almacenamiento.descartar(NEGOCIO, renglon_id, CORREO)

    assert almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, DUENO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == estado


def test_lo_cancelado_no_se_recibe_a_mano(almacenamiento):
    """Cancelado es un final (ADR 0013): lo que vuelve es su producto."""
    _, enviado = _en_transito(almacenamiento)
    almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, CORREO)
    [renglon_id] = enviado.renglones

    assert almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, DUENO) is None


def test_recibir_a_mano_mira_el_negocio(almacenamiento):
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    assert almacenamiento.recibir_a_mano("farmacia_02", renglon_id, 6, DUENO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO


def test_dos_facturas_el_resto_completa_el_parcial(almacenamiento):
    """**La decisión 3.** Lo que se escribe es cuántas llegaron EN TOTAL: 6 el
    lunes, y el jueves el resto → 10. Queda `recibido`, y lo que faltó ya no
    vuelve. La firma es la de quien dijo la cifra que está guardada."""
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, CORREO)

    completo = almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 10, DUENO)

    assert completo.estado == RENGLON_RECIBIDO
    assert completo.piezas_recibidas == 10
    assert completo.recibido_por == DUENO
    memoria = memoria_de_lo_pedido(almacenamiento.lo_ya_pedido(NEGOCIO, JUEVES))
    assert memoria.faltaron == {}
    assert memoria.desde[1] == MARTES


def test_una_cifra_mal_capturada_se_corrige_hacia_abajo(almacenamiento):
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 10, CORREO)

    corregido = almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 7, DUENO)

    assert corregido.estado == RENGLON_RECIBIDO_PARCIAL
    assert corregido.lo_que_falto == 3


def test_corregir_a_la_misma_cifra_no_mueve_la_firma(almacenamiento):
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    primero = almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, CORREO)

    assert almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, DUENO) is None
    releido = almacenamiento.leer_renglon(NEGOCIO, renglon_id)
    assert releido.recibido_por == CORREO
    assert releido.recibido_en == primero.recibido_en


def test_ya_no_se_corrige_cuando_una_lista_cerrada_trajo_lo_que_falto(almacenamiento):
    """Si una lista posterior **cerrada** ya propuso las 4 —y quizá se pidieron—,
    cambiar la cifra ya no cambia nada que se vaya a pedir, y diría lo
    contrario. Es el mismo "atendido" que `_LO_YA_PEDIDO`."""
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, CORREO)
    jueves = _lista_con(almacenamiento, JUEVES, {1: 4})
    almacenamiento.cerrar(NEGOCIO, jueves.pedido_sugerido_id)

    assert almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 10, DUENO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).piezas_recibidas == 6


def test_una_lista_posterior_abierta_no_impide_corregir(almacenamiento):
    """Abierta, nadie ha pedido nada: se corrige, y la ruta avisa que esa lista
    ya armada trae lo que faltó."""
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 6, CORREO)
    _lista_con(almacenamiento, JUEVES, {1: 4})

    assert almacenamiento.recibir_a_mano(NEGOCIO, renglon_id, 10, DUENO).estado == RENGLON_RECIBIDO


def test_recibir_parcial_con_la_evidencia(almacenamiento):
    """**La decisión 5**, en la tabla: la compra de 3 contra un pedido de 5."""
    _, enviado = _en_transito(almacenamiento, cantidades={1: 5})
    [renglon_id] = enviado.renglones

    parcial = almacenamiento.recibir_parcial_con_compras(NEGOCIO, renglon_id, (501,), 3, DUENO)

    assert parcial.estado == RENGLON_RECIBIDO_PARCIAL
    assert parcial.piezas_recibidas == 3
    assert parcial.recibido_con_compras == (501,)
    assert parcial.lo_que_falto == 2


def test_recibir_parcial_con_compras_exige_que_traiga_de_menos(almacenamiento):
    """Con lo pedido completo es `confirmar`: la misma cifra, dos veces, en el
    `WHERE` de cada una."""
    _, enviado = _en_transito(almacenamiento, cantidades={1: 5})
    [renglon_id] = enviado.renglones

    assert almacenamiento.recibir_parcial_con_compras(NEGOCIO, renglon_id, (501,), 5, DUENO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO


def test_una_compra_no_sostiene_dos_recepciones_tampoco_parciales(almacenamiento):
    _, enviado = _en_transito(almacenamiento, cantidades={1: 5, 2: 5})
    uno, dos = enviado.renglones
    almacenamiento.confirmar_la_recepcion(NEGOCIO, uno, (501,), 5, DUENO)

    assert almacenamiento.recibir_parcial_con_compras(NEGOCIO, dos, (501,), 3, DUENO) is None


def test_confirmar_guarda_cuantas_trajo_la_evidencia(almacenamiento):
    """Desde el 27 todo lo recibido dice cuántas piezas: con eso se corrige
    igual lo confirmado con compras que lo recibido a mano."""
    _, enviado = _en_transito(almacenamiento, cantidades={1: 5})
    [renglon_id] = enviado.renglones

    recibido = almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 8, DUENO)

    assert recibido.piezas_recibidas == 8


def test_un_pedido_con_algo_recibido_parcial_sigue_sin_cancelarse(almacenamiento):
    """**La decisión 4.** El 25 prohibió cancelar un pedido con algo recibido, y
    `recibido parcial` ya estaba en ese `NOT EXISTS`: si llegó algo, se
    capturó. Lo que sigue en camino de ese pedido se recibe a mano o se
    devuelve cuando se atrase."""
    _, enviado = _en_transito(almacenamiento, cantidades={1: 10, 2: 5})
    uno, dos = enviado.renglones
    almacenamiento.recibir_a_mano(NEGOCIO, uno, 6, DUENO)

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, CORREO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, dos).estado == RENGLON_EN_TRANSITO


# ------------------------------------------------------------ los CHECK


def _columnas(**cambios) -> dict:
    columnas = columnas_del_renglon(_renglon(1, 10), NEGOCIO, 1)
    columnas.update(cambios)
    return columnas


_FIRMA = {"recibido_por": CORREO, "recibido_en": _local(JUEVES)}


def test_lo_recibido_sin_piezas_rebota():
    for estado in (RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL):
        with pytest.raises(ValueError, match="ck_renglon_piezas_recibidas"):
            revisar_el_renglon(_columnas(estado=estado, **_FIRMA))


def test_piezas_recibidas_en_lo_que_no_llego_rebotan():
    with pytest.raises(ValueError, match="ck_renglon_piezas_recibidas"):
        revisar_el_renglon(_columnas(piezas_recibidas=6))


def test_piezas_recibidas_en_cero_rebotan():
    with pytest.raises(ValueError, match="ck_renglon_piezas_recibidas"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=0, **_FIRMA)
        )


def test_un_parcial_con_lo_pedido_completo_rebota():
    with pytest.raises(ValueError, match="ck_renglon_completo_o_parcial"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=10, **_FIRMA)
        )


def test_un_recibido_con_piezas_de_menos_rebota():
    """`recibido` es "llegó completo": con 6 de 10, las 4 que faltan no
    volverían nunca. La tabla lo impide aunque el código se equivoque."""
    with pytest.raises(ValueError, match="ck_renglon_completo_o_parcial"):
        revisar_el_renglon(_columnas(estado=RENGLON_RECIBIDO, piezas_recibidas=6, **_FIRMA))


def test_lo_pedido_es_la_cantidad_corregida_si_la_hubo():
    revisar_el_renglon(
        _columnas(
            estado=RENGLON_RECIBIDO,
            piezas_recibidas=8,
            cantidad_final=8,
            ajustada_por=CORREO,
            ajustada_en=_local(LUNES),
            **_FIRMA,
        )
    )


@pytest.mark.parametrize("piezas", [-1, 11])
def test_lo_que_falto_que_trae_un_renglon_cabe_en_su_propuesta(piezas):
    with pytest.raises(ValueError, match="ck_renglon_piezas_que_faltaron"):
        revisar_el_renglon(_columnas(piezas_que_faltaron=piezas))


def test_el_renglon_nace_sin_nada_recibido_y_con_lo_que_falto_que_trae():
    columnas = columnas_del_renglon(_renglon(1, 6, piezas_que_faltaron=4), NEGOCIO)
    assert columnas["piezas_recibidas"] is None
    assert columnas["piezas_que_faltaron"] == 4
    revisar_el_renglon(columnas)


def test_el_doble_rechaza_un_parcial_sin_piezas_igual_que_postgres(almacenamiento):
    _, enviado = _en_transito(almacenamiento)
    [renglon_id] = enviado.renglones
    with pytest.raises(ValueError, match="ck_renglon_piezas_recibidas"):
        almacenamiento.poner_estado_del_renglon(renglon_id, RENGLON_RECIBIDO_PARCIAL, **_FIRMA)


# --------------------------------------------------------- el SQL como texto


def test_recibir_a_mano_lleva_la_transicion_en_el_where():
    sentencia = _sentencia_python("_RECIBIR_A_MANO")
    assert "r.estado = 'en tránsito'" in sentencia
    assert "p.estado = 'enviado'" in sentencia
    assert "p.negocio = r.negocio" in sentencia
    assert "r.negocio = :negocio" in sentencia
    assert "piezas_recibidas = :piezas" in sentencia
    assert "recibido_por = :quien" in sentencia and "recibido_en = now()" in sentencia
    # El estado sale de las piezas, igual que el CHECK: no puede separarse.
    assert "coalesce(r.cantidad_final, r.cantidad_propuesta) <= :piezas" in sentencia
    assert "'recibido parcial'" in sentencia
    assert "recibido_con_compras" not in sentencia


def test_corregir_exige_que_lo_que_falto_no_se_haya_atendido():
    sentencia = _sentencia_python("_CORREGIR_LO_RECIBIDO")
    assert "r.estado in ('recibido', 'recibido parcial')" in sentencia
    assert "r.piezas_recibidas <> :piezas" in sentencia
    assert "not exists" in sentencia
    assert "s2.estado = 'cerrado'" in sentencia
    assert "s2.fecha_del_pedido > s.fecha_del_pedido" in sentencia
    assert "s.negocio = r.negocio" in sentencia and "s2.negocio = r2.negocio" in sentencia
    # Lo que se corrige es la cifra, no la evidencia: las compras se quedan.
    assert "recibido_con_compras" not in sentencia


def test_recibir_parcial_con_compras_lleva_sus_garantias_en_el_where():
    sentencia = _sentencia_python("_RECIBIR_PARCIAL_CON_COMPRAS")
    assert "set estado = 'recibido parcial'" in sentencia
    assert "coalesce(r.cantidad_final, r.cantidad_propuesta) > :piezas" in sentencia
    assert "r.estado = 'en tránsito'" in sentencia
    assert "p.proveedor_id is not null" in sentencia
    assert "r2.recibido_con_compras &&" in sentencia
    assert "folio" not in sentencia


def test_confirmar_guarda_las_piezas():
    assert "piezas_recibidas = :piezas" in _sentencia_python("_CONFIRMAR_LA_RECEPCION")


def test_las_lecturas_traen_las_dos_columnas_nuevas():
    for nombre in ("_LEER_RENGLONES", "_LEER_RENGLON_POR_ID", "_LO_YA_PEDIDO", "_EN_TRANSITO"):
        sentencia = _sentencia_python(nombre)
        assert "piezas_recibidas" in sentencia, nombre
        assert "piezas_que_faltaron" in sentencia, nombre
    assert ":piezas_que_faltaron" in _sentencia_python("_INSERTAR_RENGLONES")


def test_la_migracion_0011_agrega_dos_columnas_y_no_crea_tabla():
    """No crea tabla ni da permisos: `crear_rol.sql` NO se vuelve a correr."""
    sentencias = _sentencias(MIGRACION)
    assert "CREATE TABLE" not in sentencias
    assert "GRANT" not in sentencias
    assert "ADD COLUMN IF NOT EXISTS piezas_recibidas numeric(12,3)" in sentencias
    assert (
        "ADD COLUMN IF NOT EXISTS piezas_que_faltaron integer NOT NULL DEFAULT 0"
        in sentencias
    )
    assert "current_user = 'continental'" in sentencias
    assert "SET client_encoding TO 'UTF8'" in sentencias
    # Lo confirmado por el 26 antes de la columna dijo "llegó completo": se
    # llena con lo pedido ANTES de poner el CHECK, o el CHECK no entraría.
    relleno = sentencias.index("UPDATE pedidos.renglon")
    assert relleno < sentencias.index("ADD CONSTRAINT ck_renglon_piezas_recibidas")


def test_los_check_nuevos_estan_en_los_dos_archivos():
    for ruta in (CREAR_TABLAS, MIGRACION):
        sentencias = _sentencias(ruta)
        for restriccion in (
            "ck_renglon_piezas_recibidas",
            "ck_renglon_completo_o_parcial",
            "ck_renglon_piezas_que_faltaron",
        ):
            assert f"CONSTRAINT {restriccion}" in sentencias, (ruta.name, restriccion)


def test_crear_tablas_trae_las_dos_columnas_y_nombra_la_0011():
    sentencias = _sentencias(CREAR_TABLAS)
    assert re.search(r"\n\s+piezas_recibidas\s+numeric\(12,3\)", sentencias)
    assert re.search(r"\n\s+piezas_que_faltaron\s+integer NOT NULL DEFAULT 0", sentencias)
    assert "0011-recibido-parcial-y-a-mano.sql" in _texto(CREAR_TABLAS)


def test_el_estado_del_pedido_no_se_guarda():
    """**La decisión 2.** `recibido` y `recibido parcial` del pedido se calculan:
    `ck_pedido_estado` sigue con los tres que declara una persona."""
    from continental.almacenamiento import ESTADOS_DEL_PEDIDO

    assert ESTADOS_DEL_PEDIDO == ("borrador", "enviado", "cancelado")
    assert "ck_pedido_estado" not in _sentencias(MIGRACION)


def test_verificar_rol_mira_lo_recibido():
    texto = _texto(VERIFICAR_ROL)
    assert "(36," in texto and "(37," in texto
    assert "ck_renglon_completo_o_parcial" in texto
    assert "ck_renglon_piezas_que_faltaron" in texto


# ==========================================================================
# LO QUE SE VE — las rutas de punta a punta, varios días, y la pantalla
# ==========================================================================

from continental.precios import LecturaDePrecio  # noqa: E402

RUTA = "/api/pedido-sugerido"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}
PANTALLA = RAIZ / "src" / "continental" / "web" / "static" / "index.html"


def _lectura(proveedor: str = "nadro") -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego="12.50",
        precio=Decimal("12.50"),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def _enviar(cliente, almacenamiento, lista: dict, productos: set[int], enviado_en) -> dict:
    """Precio de NADRO a esos productos, descarta el resto, parte, envía, y fija
    la hora del envío (el doble firma con el reloj real)."""
    for r in lista["renglones"]:
        if r["producto_id"] in productos:
            almacenamiento.guardar_precios(NEGOCIO, r["renglon_id"], [_lectura()])
        elif r["estado"] == "abierto":
            cliente.post(f"/api/renglon/{r['renglon_id']}/descartar", headers=FIRMA)
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    assert partida["ok"] is True, partida
    [pedido] = [p for p in partida["pedidos"] if p["proveedor"] == "nadro"]
    enviada = cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=FIRMA).json()
    assert enviada["ok"] is True, enviada
    for fila in almacenamiento.pedidos:
        if fila["pedido_id"] == pedido["pedido_id"]:
            fila["enviado_en"] = enviado_en
    return pedido


def _cerrar(cliente, lista: dict) -> None:
    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")
    assert respuesta.status_code == 200, respuesta.json()


def _fijar_la_hora(monkeypatch, instante: dt.datetime) -> None:
    from continental.web import app as modulo

    monkeypatch.setattr(modulo, "_ahora", lambda: instante)


def _a_mano(cliente, renglon_id: int, piezas, quien: str | None = DUENO):
    cabeceras = {} if quien is None else {"Cf-Access-Authenticated-User-Email": quien}
    return cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/a-mano",
        json={"piezas": piezas},
        headers=cabeceras,
    )


def _por_producto(lista: dict) -> dict[int, dict]:
    return {r["producto_id"]: r for r in lista["renglones"]}


def _renglon_de(lista: dict, producto_id: int) -> int:
    return _por_producto(lista)[producto_id]["renglon_id"]


def test_escenario_pedi_10_llegaron_6_y_lo_que_falto_vuelve_una_sola_vez(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**La decisión 1, con los números escritos.** Las listas de en medio se
    cierran: es el caso en que el corte avanza encima y algo se podría perder.

    - Lunes: se venden **10** del producto 1; se piden 10 a NADRO.
    - Martes: se venden **3** (no se proponen: viene en camino). Se cierra.
    - Miércoles: se venden **2**. Se cierra.
    - Jueves: llegan **6**. Se recibe a mano: `recibido parcial`, faltan **4**.
      Se vende **1**. La lista del jueves trae 3 + 2 + 1 = **6** vendidas
      mientras venía (el ancla del 24) **más las 4 que faltaron** = **10**.
    - Viernes: se vende **1**. La lista trae **1**: ni las 4 ni lo del martes
      vuelven otra vez, porque la del jueves se cerró.

    Cuenta de comprobación: vendidas 10 + 3 + 2 + 1 + 1 = 17; propuestas 10
    (lunes) + 10 (jueves) + 1 (viernes) = 21; llegaron 6 de las primeras 10,
    así que lo repuesto de verdad es 6 + 10 + 1 = 17. Ninguna venta dos veces
    y ninguna perdida.
    """
    _fijar_la_hora(monkeypatch, _local(JUEVES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    assert _por_producto(lunes)[1]["cantidad_propuesta"] == 10
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 3), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert sorted(_por_producto(martes)) == [2]
    _cerrar(cliente, martes)

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 2), _venta(MIERCOLES, 2, 1)]
    miercoles = _abrir(cliente)
    assert sorted(_por_producto(miercoles)) == [2]
    _cerrar(cliente, miercoles)

    respuesta = _a_mano(cliente, renglon_id, 6)
    assert respuesta.status_code == 200, respuesta.json()
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["estado"] == RENGLON_RECIBIDO_PARCIAL
    assert "4 que faltaron vuelven a proponerse" in cuerpo["frase"]

    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    jueves = _abrir(cliente)
    uno = _por_producto(jueves)[1]
    assert uno["piezas_vendidas"] == 3 + 2 + 1
    assert uno["piezas_que_faltaron"] == 4
    assert uno["cantidad_propuesta"] == 10, "Lo que faltó o lo vendido se perdió."
    assert uno["ventas_desde"] == MARTES.isoformat()
    assert "4 piezas que faltaron" in uno["frase_de_lo_que_falto"]
    # El bloque de lo que viene lo enseña, con su firma y para corregirlo.
    [falto] = jueves["en_camino"]["faltaron"]
    assert falto["renglon_id"] == renglon_id
    assert "llegaron 6 de 10" in falto["frase"]
    _cerrar(cliente, jueves)

    almacen.ventas_en_memoria += [_venta(VIERNES, 1, 1)]
    viernes = _abrir(cliente)
    uno = _por_producto(viernes)[1]
    assert uno["cantidad_propuesta"] == 1, "Lo que faltó se propuso dos veces."
    assert uno["piezas_que_faltaron"] == 0
    assert viernes["en_camino"]["faltaron"] == []


def test_escenario_dos_facturas_el_resto_llega_y_no_se_pide_de_mas(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**La decisión 3.** Lunes se piden 10. Llegan 6 (primera factura) y se
    reciben a mano. La lista del martes —que NADIE cierra— ya trae 3 vendidas
    + 4 que faltaron = 7. El miércoles llega el resto (segunda factura): se
    corrige a 10. La respuesta avisa que la lista ya armada trae las 4.

    La del miércoles trae 3 (martes) + 2 (miércoles) = **5**, y **ninguna**
    de las 4: llegaron.
    """
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)

    assert _a_mano(cliente, renglon_id, 6).json()["estado"] == RENGLON_RECIBIDO_PARCIAL

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 3), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert _por_producto(martes)[1]["cantidad_propuesta"] == 3 + 4

    respuesta = _a_mano(cliente, renglon_id, 10)
    assert respuesta.status_code == 200, respuesta.json()
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == RENGLON_RECIBIDO
    assert "de 6 a 10" in cuerpo["frase"]
    assert "lista que ya esté armada" in cuerpo["frase"]

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 2)]
    miercoles = _abrir(cliente)
    uno = _por_producto(miercoles)[1]
    assert uno["cantidad_propuesta"] == 3 + 2
    assert uno["piezas_que_faltaron"] == 0


def test_escenario_ya_no_se_corrige_lo_que_una_lista_cerrada_ya_propuso(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 18))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)
    _a_mano(cliente, renglon_id, 6)
    almacen.ventas_en_memoria += [_venta(MARTES, 1, 3)]
    martes = _abrir(cliente)
    assert _por_producto(martes)[1]["cantidad_propuesta"] == 7
    _cerrar(cliente, martes)

    respuesta = _a_mano(cliente, renglon_id, 10)

    assert respuesta.status_code == 409
    assert "ya se volvió a proponer" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).piezas_recibidas == 6


def test_escenario_la_propuesta_que_trae_de_menos_se_recibe_parcial(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**La decisión 5.** Se piden 5; SICAR tiene una compra de 3. Hasta el 26
    ese renglón no tenía salida. Ahora: "llegaron solo 3 de 5". Faltan 2, y
    el jueves vuelven con lo vendido el miércoles (1) y el jueves (1): **4**."""
    _fijar_la_hora(monkeypatch, _local(JUEVES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1), _venta(MIERCOLES, 2, 1)]
    miercoles = _abrir(cliente)
    [propuesta] = miercoles["recepcion"]["propuestas"]
    assert propuesta["se_puede_confirmar"] is False
    assert propuesta["se_puede_recibir_lo_que_trae"] is True

    completo = cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/confirmar", json={"compras": [501]}, headers=FIRMA
    )
    assert completo.status_code == 409
    respuesta = cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/parcial", json={"compras": [501]}, headers=FIRMA
    )
    assert respuesta.status_code == 200, respuesta.json()
    assert respuesta.json()["estado"] == RENGLON_RECIBIDO_PARCIAL
    guardado = almacenamiento.leer_renglon(NEGOCIO, renglon_id)
    assert guardado.recibido_con_compras == (501,)
    assert guardado.piezas_recibidas == 3

    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    uno = _por_producto(_abrir(cliente))[1]
    assert uno["piezas_vendidas"] == 1 + 1
    assert uno["piezas_que_faltaron"] == 2
    assert uno["cantidad_propuesta"] == 4


def test_recibir_parcial_una_propuesta_completa_contesta_409(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 5)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 5)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))

    respuesta = cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/parcial", json={"compras": [501]}, headers=FIRMA
    )
    assert respuesta.status_code == 409
    assert "confírmala" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO


def test_escenario_lo_que_falto_vuelve_aunque_se_cancele_el_pedido_que_lo_traia(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**Cancelado vuelve con todo lo que cubría** (ADR 0013), y eso incluye lo
    que faltó que traía. Lunes 10, llegan 6: faltan 4. La lista del martes trae
    3 vendidas + 4 = 7, se envía… y el pedido se cancela: nunca se capturó.

    La del miércoles trae desde el martes: 3 + 2 = 5 vendidas, **más las 4**
    = **9**. Vendidas 10 + 3 + 2 = 15, llegaron 6: faltan 9. Cuadra.
    """
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)
    _a_mano(cliente, renglon_id, 6)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 3), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert _por_producto(martes)[1]["cantidad_propuesta"] == 7
    pedido = _enviar(cliente, almacenamiento, martes, {1}, _local(MARTES, 11))
    _cerrar(cliente, martes)
    cancelado = cliente.post(f"/api/pedido/{pedido['pedido_id']}/cancelar", headers=FIRMA)
    assert cancelado.status_code == 200, cancelado.json()

    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 2)]
    uno = _por_producto(_abrir(cliente))[1]
    assert uno["piezas_vendidas"] == 3 + 2
    assert uno["piezas_que_faltaron"] == 4
    assert uno["cantidad_propuesta"] == 9


def test_el_pedido_queda_recibido_o_recibido_parcial_segun_sus_renglones(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**Casilla 4**, en la pantalla de la lista de hoy: lo que se pidió a las 9
    llega a las 15, en dos renglones del mismo pedido."""
    _fijar_la_hora(monkeypatch, _local(LUNES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10), _venta(LUNES, 2, 5)]
    lunes = _abrir(cliente)
    uno, dos = _renglon_de(lunes, 1), _renglon_de(lunes, 2)
    _enviar(cliente, almacenamiento, lunes, {1, 2}, _local(LUNES, 9))

    def _el_pedido():
        [pedido] = _abrir(cliente)["pedidos"]
        return pedido

    _a_mano(cliente, uno, 10)
    assert _el_pedido()["estado_a_la_vista"] == ENVIADO
    assert _el_pedido()["frase_de_la_recepcion"] is None

    _a_mano(cliente, dos, 3)
    pedido = _el_pedido()
    assert pedido["estado"] == ENVIADO  # lo guardado no cambia
    assert pedido["estado_a_la_vista"] == PEDIDO_RECIBIDO_PARCIAL
    assert pedido["frase_de_la_recepcion"].startswith("Recibido parcial")
    assert pedido["se_puede_cancelar"] is False

    _a_mano(cliente, dos, 5)
    pedido = _el_pedido()
    assert pedido["estado_a_la_vista"] == PEDIDO_RECIBIDO
    assert pedido["frase_de_la_recepcion"].startswith("Recibido")
    assert pedido["fue_enviado"] is True  # la firma del envío sigue siendo cierta

    renglon = _por_producto(_abrir(cliente))[2]
    assert renglon["esta_recibido"] is True
    assert renglon["se_puede_corregir"] is True
    assert renglon["piezas_recibidas"] == 5
    assert renglon["etiqueta_a_mano"] == "Corregir cuántas llegaron"


def test_lo_que_nunca_tendra_propuesta_se_recibe_a_mano(
    cliente, almacen, almacenamiento, monkeypatch
):
    """Casilla 3: QuePharma no está en SICAR. Su única salida era "todavía no
    se puede"; ahora es recibirlo a mano, y el bloque ya no lo tiene esperando."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    for r in lunes["renglones"]:
        almacenamiento.guardar_precios(NEGOCIO, r["renglon_id"], [_lectura("quepharma")])
    cliente.post(f"/api/renglon/{renglon_id}/proveedor", json={"proveedor": "quepharma"}, headers=FIRMA)
    partida = cliente.post(f"{RUTA}/{lunes['pedido_sugerido_id']}/partir").json()
    [pedido] = partida["pedidos"]
    assert cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=FIRMA).json()["ok"]

    [grupo] = _abrir(cliente)["recepcion"]["esperan"]
    assert grupo["motivo"] == MOTIVO_SIN_PUENTE
    assert "a mano" in grupo["frase"]

    assert _a_mano(cliente, renglon_id, 3).status_code == 200
    assert _abrir(cliente)["recepcion"]["esperan"] == []


@pytest.mark.parametrize(
    "piezas,pista", [(0, "sigue en camino"), (2.5, "enteras"), ("6", "número"), (None, "número")]
)
def test_la_ruta_valida_las_piezas_en_el_servidor(
    cliente, almacen, almacenamiento, monkeypatch, piezas, pista
):
    _fijar_la_hora(monkeypatch, _local(LUNES, 18))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 9))

    respuesta = _a_mano(cliente, renglon_id, piezas)

    assert respuesta.status_code == 422
    assert pista in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO


def test_sin_el_campo_tambien_se_dice_en_espanol(cliente, almacen, almacenamiento):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    renglon_id = _renglon_de(_abrir(cliente), 1)
    respuesta = cliente.post(f"/api/renglon/{renglon_id}/recepcion/a-mano", json={})
    assert respuesta.status_code == 422
    assert "número" in respuesta.json()["detalle"]


def test_lo_que_no_esta_en_camino_ni_recibido_contesta_409(cliente, almacen, almacenamiento):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    renglon_id = _renglon_de(_abrir(cliente), 1)

    respuesta = _a_mano(cliente, renglon_id, 6)

    assert respuesta.status_code == 409
    assert "Vuelve a cargar" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == "abierto"


def test_la_firma_es_firma_y_no_permiso(cliente, almacen, almacenamiento, monkeypatch):
    """Regla 3: sin encabezado se firma como `sin-identificar` y se guarda igual."""
    _fijar_la_hora(monkeypatch, _local(LUNES, 18))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 9))

    assert _a_mano(cliente, renglon_id, 6, quien=None).status_code == 200
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).recibido_por == "sin-identificar"


def test_regla_5_el_error_no_viaja_al_navegador(cliente, almacen, almacenamiento):
    almacenamiento.falla = RuntimeError("postgresql://continental:secreto@atlas/farmacia")

    respuesta = _a_mano(cliente, 1, 6)

    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert cuerpo["detalle"] == "no se pudo recibir a mano (RuntimeError)"
    assert "secreto" not in respuesta.text


# ---------------------------------------------------------------- la pantalla


def _pantalla() -> str:
    return _texto(PANTALLA)


def test_la_pantalla_recibe_a_mano_y_manda_solo_las_piezas():
    pantalla = _pantalla()
    assert "const recibirAMano" in pantalla
    assert "'/recepcion/a-mano'" in pantalla
    assert "JSON.stringify({ piezas })" in pantalla
    inicio = pantalla.index("const recibirAMano")
    assert "await cargarPedido()" in pantalla[inicio : inicio + 2000]


def test_la_pantalla_no_compone_las_frases_de_lo_recibido():
    """Etiquetas y frases llegan hechas de Python (la lección del 15)."""
    pantalla = _pantalla()
    inicio = pantalla.index("const controlAMano")
    fin = pantalla.index("const recibirAMano")
    cuerpo = pantalla[inicio:fin]
    for palabra in ("faltaron", "parcial", "llegaron", "Recibir"):
        assert palabra not in cuerpo, palabra
    assert "etiqueta" in cuerpo


def test_la_pantalla_pinta_lo_que_falto_y_el_estado_del_pedido():
    pantalla = _pantalla()
    assert "r.frase_de_lo_que_falto" in pantalla
    assert "frase_de_la_recepcion" in pantalla
    assert "en_camino.faltaron" in pantalla or "enCamino.faltaron" in pantalla
    assert "p.etiqueta_de_lo_que_trae" in pantalla
    assert "'parcial'" in pantalla  # la acción, junto a 'confirmar' y 'rechazar'



# ---------------------------------------- lo que cazó el recorrido del navegador


def test_lo_que_falto_y_ya_viene_en_la_lista_de_hoy_lo_dice():
    """**Lo cazó el recorrido del navegador.** El bloque de lo que llegó de
    menos decía "vuelven a proponerse en la siguiente lista" debajo de una lista
    de hoy que ya las traía. Si la lista de hoy ya las trae, se dice eso."""
    ya = _ya(1, RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6)
    hoy = en_camino_como_json((), {}, _local(JUEVES), faltaron=[ya], faltaron_en_esta_lista={1})
    [uno] = hoy["faltaron"]
    assert "ya vienen en esta lista" in uno["frase"]
    assert "siguiente lista" not in uno["frase"]
    [otro] = en_camino_como_json((), {}, _local(JUEVES), faltaron=[ya])["faltaron"]
    assert "siguiente lista" in otro["frase"]


def test_la_particion_no_dice_que_se_pidio_entera_si_queda_algo_sin_proveedor():
    """**El hilo abierto 18, disparado por este ticket.** Con un pedido enviado
    —y desde el 27, recibido— y otro renglón sin proveedor, la pantalla decía
    "Esta lista ya se pidió entera · sus renglones están en tránsito": dos
    mentiras. La frase sale de Python también en el caso mixto."""
    from continental.particion import frase_sin_nada_por_repartir

    mixta = frase_sin_nada_por_repartir(en_transito=0, cancelados=0, recibidos=1, sin_proveedor=2)
    assert "1 renglón ya se pidió y llegó" in mixta
    assert "2 renglones sin proveedor" in mixta
    assert "Ya se puede cerrar" not in mixta
    assert "No queda nada por repartir" not in mixta
    # Sin nada atendido, "elige a quién" lo dice la pantalla, como antes.
    assert frase_sin_nada_por_repartir(0, 0, 0, sin_proveedor=2) is None


def test_la_lista_mixta_recibe_su_frase_de_python(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(LUNES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10), _venta(LUNES, 2, 5)]
    lunes = _abrir(cliente)
    uno, dos = _renglon_de(lunes, 1), _renglon_de(lunes, 2)
    almacenamiento.guardar_precios(NEGOCIO, uno, [_lectura()])
    partida = cliente.post(f"{RUTA}/{lunes['pedido_sugerido_id']}/partir").json()
    [pedido] = partida["pedidos"]
    cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar", headers=FIRMA)
    _a_mano(cliente, uno, 10)

    particion = _abrir(cliente)["particion"]

    assert particion["hay"] is False
    assert particion["cuantos_sin_proveedor"] == 1
    assert "ya se pidió y llegó" in particion["sin_nada_por_repartir"]
    assert "1 renglón sin proveedor" in particion["sin_nada_por_repartir"]


def test_la_pantalla_no_titula_entera_una_lista_con_algo_sin_proveedor():
    pantalla = _pantalla()
    inicio = pantalla.index("const titular = document.createElement('b');")
    cuerpo = pantalla[inicio : pantalla.index("caja.append(titular);", inicio)]
    assert "cuantos_sin_proveedor" in cuerpo
    assert "Esta lista se pidió en parte" in cuerpo


def test_el_renglon_que_trae_lo_que_ya_llego_lo_avisa():
    """**Lo cazó el recorrido del navegador**, y es el caso de las dos facturas:
    la lista de hoy se armó con las 4 que faltaban; después llegó el resto y se
    corrigió a 10. Lo que se muestra es lo guardado y no se recalcula (ADR
    0012), así que el renglón lo dice en ámbar, igual que "ya viene en camino"
    del ticket 24."""
    from continental.transito import frase_de_lo_que_ya_no_falta

    assert "ya no faltan" in frase_de_lo_que_ya_no_falta(4)
    assert "corrige" in frase_de_lo_que_ya_no_falta(4)
    assert "ya no falta" in frase_de_lo_que_ya_no_falta(1)


def test_escenario_la_segunda_factura_despues_de_armar_la_lista_se_avisa_en_el_renglon(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MARTES, 18))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_id = _renglon_de(lunes, 1)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)
    _a_mano(cliente, renglon_id, 6)
    almacen.ventas_en_memoria += [_venta(MARTES, 1, 3), _venta(MARTES, 2, 1)]
    uno = _por_producto(_abrir(cliente))[1]
    assert uno["piezas_que_faltaron"] == 4
    assert uno["ya_no_falta"] is None

    assert _a_mano(cliente, renglon_id, 10).status_code == 200

    uno = _por_producto(_abrir(cliente))[1]
    assert uno["cantidad_propuesta"] == 7  # lo guardado no se recalcula
    assert "ya no faltan" in uno["ya_no_falta"]


def test_la_pantalla_pinta_el_aviso_de_lo_que_ya_no_falta():
    assert "r.ya_no_falta" in _pantalla()
