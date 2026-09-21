"""Recepción sugerida: "probablemente recibido", con su evidencia (ticket 26, ADR 0014).

**Lo que arregla.** Hasta el ticket 25 nada pasaba a `recibido`: todo lo que
llegaba seguía `en tránsito`, a los N días se veía atrasado igual que lo que no
llegó, y devolverlo a la lista era pedirlo dos veces. Lo retenido del ticket 24
—lo que se vendió mientras venía— tampoco volvía nunca, porque su enganche
(`ESTADOS_QUE_CIERRAN_EL_TRANSITO`) esperaba un estado que nadie escribía.

**Lo que NO hace, y es la regla del ADR 0002.** La recepción se sugiere, no se
afirma. SICAR no tiene pedidos: una compra se captura ya recibida, sin estado
parcial, y `folio` tiene semántica no verificada. Así que:

- una función pura cruza lo que viene en camino con las compras posteriores
  **por proveedor, producto y fecha** —nunca por folio— y devuelve propuestas
  con su evidencia;
- la propuesta **se calcula cada vez y no se guarda**: el renglón sigue
  `en tránsito` hasta que una persona la confirma (pasa a `recibido`, firmado,
  con las compras que lo sostienen) o la rechaza (sigue en tránsito, y esa
  compra ya no se le vuelve a proponer).

Los tres seams del repo, en este orden: lo puro (`recepcion.py`), lo que se
guarda (el doble, los CHECK en Python y el SQL como texto) y lo que se ve (las
rutas de punta a punta, de varios días, y la pantalla). Ninguna prueba de este
archivo toca Postgres, la red, ni duerme. **Ningún dato es real**: proveedores,
productos y compras son inventados.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from pathlib import Path

import pytest

from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import (
    ENVIADO,
    ESTADOS_QUE_CIERRAN_EL_TRANSITO,
    LoYaPedido,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RenglonGuardado,
)
from continental.recepcion import (
    AVISO_DEL_RETRASO,
    ADVERTENCIA_AL_CONFIRMAR,
    MOTIVO_NUNCA_EN_COMPRAS,
    MOTIVO_RECHAZADA,
    MOTIVO_SIN_HORA,
    MOTIVO_SIN_PUENTE,
    MOTIVO_TODAVIA_NO,
    MOTIVO_YA_USADA,
    desde_cuando_leer_compras,
    dia_del_envio,
    frase_de_la_cantidad,
    frase_del_bloque,
    frase_del_motivo,
    proponer,
    recepcion_como_json,
    recepcion_con_hueco,
)
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent

NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
DUENO = "dueno@farmacia.mx"

#: La hora del centro de México, a mano, para construir instantes de prueba.
CENTRO = dt.timezone(dt.timedelta(hours=-6))

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)
DOMINGO_ANTES = dt.date(2026, 9, 13)

#: Los `pro_id` de SICAR que usa el YAML versionado (ADR 0008). No son datos
#: de nadie: son la configuración de esta instalación.
NADRO = 1
LEVIC = 10


def _local(fecha: dt.date, hora: int = 10, minuto: int = 0) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=CENTRO)


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


def _ya(
    producto_id: int,
    *,
    renglon_id: int | None = None,
    cantidad: int = 5,
    proveedor: str = "nadro",
    proveedor_id: int | None = NADRO,
    enviado_en: dt.datetime | None = None,
    compras_rechazadas: tuple[int, ...] | None = None,
    fecha_del_pedido: dt.date = LUNES,
) -> LoYaPedido:
    """Un renglón en tránsito armado a mano, con el `pro_id` de su pedido."""
    return LoYaPedido(
        renglon=RenglonGuardado(
            renglon_id=renglon_id or producto_id * 10,
            estado=RENGLON_EN_TRANSITO,
            propuesto=_renglon(producto_id, cantidad),
            pedido_id=7,
            compras_rechazadas=compras_rechazadas,
            recepcion_rechazada_por=CORREO if compras_rechazadas else None,
            recepcion_rechazada_en=_local(MARTES) if compras_rechazadas else None,
        ),
        pedido_sugerido_id=1,
        fecha_del_pedido=fecha_del_pedido,
        ventas_hasta=fecha_del_pedido,
        proveedor=proveedor,
        enviado_por=CORREO,
        enviado_en=enviado_en or _local(LUNES, 11),
        ventas_desde_la_lista=fecha_del_pedido,
        estado_del_pedido=ENVIADO,
        proveedor_id=proveedor_id,
    )


def _compra(
    compra_id: int,
    producto_id: int,
    fecha: dt.date,
    cantidad: float = 5,
    proveedor_id: int = NADRO,
    folio: str = "F-0001",
) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=compra_id,
        producto_id=producto_id,
        proveedor_id=proveedor_id,
        fecha=fecha,
        cantidad=cantidad,
        precio_unitario_pagado=12.5,
        importe_pagado=12.5 * cantidad,
        folio=folio,
    )


# ==========================================================================
# LO PURO — qué compra encaja con qué renglón, y cómo se dice
# ==========================================================================


def test_casilla_1_la_propuesta_trae_su_evidencia():
    """La primera casilla, literal: *devuelve propuestas con su evidencia:
    proveedor, producto, cantidad y fecha de la compra*."""
    [propuesta] = proponer([_ya(1)], [_compra(501, 1, MIERCOLES, 5)]).propuestas

    assert propuesta.renglon_id == 10
    [compra] = propuesta.compras
    assert compra.compra_id == 501
    assert compra.proveedor_id == NADRO
    assert compra.producto_id == 1
    assert compra.cantidad == 5
    assert compra.fecha == MIERCOLES


def test_casilla_2_empareja_por_proveedor_producto_y_fecha_y_nunca_por_folio():
    """**El folio no entra al emparejamiento**, ni para sumar ni para quitar.

    Tres compras con el MISMO folio que el que alguien podría esperar: una de
    otro proveedor, una de otro producto y una anterior al envío. Ninguna
    encaja. Y una con un folio cualquiera que sí coincide en lo demás, sí.
    """
    compras = [
        _compra(601, 1, MIERCOLES, proveedor_id=LEVIC, folio="MISMO"),
        _compra(602, 2, MIERCOLES, folio="MISMO"),
        _compra(603, 1, DOMINGO_ANTES, folio="MISMO"),
        _compra(604, 1, MIERCOLES, folio="OTRO-CUALQUIERA"),
    ]

    [propuesta] = proponer([_ya(1)], compras).propuestas

    assert [c.compra_id for c in propuesta.compras] == [604]


def test_casilla_2_el_codigo_no_nombra_el_folio_para_decidir():
    """El cinturón sobre el código: `folio` solo aparece para ENSEÑARLO."""
    fuente = (RAIZ / "src" / "continental" / "recepcion.py").read_text(encoding="utf-8")
    usos = [linea for linea in fuente.splitlines() if ".folio" in linea]
    assert usos, "La evidencia tiene que enseñar el folio a la persona."
    for linea in usos:
        assert "==" not in linea and " in " not in linea, (
            f"El folio se usa para decidir: {linea.strip()!r}. Su semántica no "
            "está verificada (ADR 0002): se enseña, nunca se empareja."
        )


def test_una_compra_anterior_al_envio_no_encaja():
    assert proponer([_ya(1)], [_compra(501, 1, DOMINGO_ANTES)]).propuestas == ()


def test_una_compra_del_mismo_dia_del_envio_si_encaja():
    """SICAR guarda el DÍA de la compra, no la hora. "Posterior al envío" se
    mide en días de la farmacia, y el mismo día cuenta: un pedido capturado a
    las 9 y surtido a las 15 es el caso de todos los días. Lo que pueda tener de
    más —una compra de esa mañana que era de otro pedido— lo juzga la persona:
    por eso se sugiere y no se afirma."""
    [propuesta] = proponer([_ya(1, enviado_en=_local(LUNES, 9))], [_compra(501, 1, LUNES)]).propuestas
    assert propuesta.compras[0].compra_id == 501


def test_el_dia_del_envio_es_el_de_la_farmacia_y_no_el_de_utc():
    """Un envío del lunes a las 20:30 son las 02:30 del martes en UTC.

    Contado en UTC, la compra del lunes —el mismo día, en la farmacia— quedaría
    fuera. Es la trampa del contenedor otra vez, y por eso el día se calcula en
    Python y no con `at time zone '-06'` en Postgres, que es la convención
    POSIX y se lee UTC+6 (lo midió el ticket 25).
    """
    enviado = dt.datetime(2026, 9, 15, 2, 30, tzinfo=dt.UTC)  # lunes 20:30 local

    assert dia_del_envio(enviado) == LUNES
    [propuesta] = proponer([_ya(1, enviado_en=enviado)], [_compra(501, 1, LUNES)]).propuestas
    assert propuesta.renglon_id == 10


def test_un_instante_sin_zona_se_toma_como_utc():
    assert dia_del_envio(dt.datetime(2026, 9, 15, 2, 30)) == LUNES
    assert dia_del_envio(None) is None


def test_desde_cuando_leer_compras_es_el_envio_mas_viejo():
    """La lectura del almacén es una, desde el envío más viejo que puede
    tener propuesta. Los que no tienen puente o no tienen hora no cuentan:
    ninguna compra les va a servir."""
    en_camino = [
        _ya(1, enviado_en=_local(MIERCOLES)),
        _ya(2, enviado_en=_local(MARTES)),
        _ya(3, enviado_en=_local(DOMINGO_ANTES), proveedor="quepharma", proveedor_id=None),
    ]
    assert desde_cuando_leer_compras(en_camino) == MARTES
    assert desde_cuando_leer_compras([]) is None
    assert desde_cuando_leer_compras([_ya(3, proveedor_id=None)]) is None


def test_solo_lo_que_esta_en_transito_entra():
    """Un renglón que ya se recibió no vuelve a tener propuesta."""
    recibido = dataclasses.replace(
        _ya(1),
        renglon=RenglonGuardado(
            renglon_id=10,
            estado=RENGLON_RECIBIDO,
            propuesto=_renglon(1),
            pedido_id=7,
            recibido_por=CORREO,
            recibido_en=_local(MARTES),
            recibido_con_compras=(501,),
        ),
    )
    recepcion = proponer([recibido], [_compra(502, 1, MIERCOLES)])
    assert recepcion.propuestas == () and recepcion.sin_propuesta == ()


# ------------------------------------------------ sin propuesta, y por qué


def test_casilla_7_sin_puente_nunca_hay_propuesta_y_se_dice():
    """QuePharma no está en `dim_proveedor` (ADR 0008): ninguna compra de SICAR
    se le puede cruzar, ni siquiera una suya capturada con otro nombre."""
    ya = _ya(1, proveedor="quepharma", proveedor_id=None)

    recepcion = proponer([ya], [_compra(501, 1, MIERCOLES)])

    assert recepcion.propuestas == ()
    [sin] = recepcion.sin_propuesta
    assert sin.motivo == MOTIVO_SIN_PUENTE
    frase = frase_del_motivo(MOTIVO_SIN_PUENTE, ["QuePharma"])
    assert "QuePharma" in frase
    assert "nunca" in frase.lower()
    assert "a mano" in frase


def test_sin_hora_de_envio_no_se_inventa_que_compra_es_posterior():
    ya = dataclasses.replace(_ya(1), enviado_en=None)

    [sin] = proponer([ya], [_compra(501, 1, MIERCOLES)]).sin_propuesta
    assert sin.motivo == MOTIVO_SIN_HORA


def test_casilla_7_un_producto_que_nunca_aparece_en_compras_lo_dice():
    """606 de 3,429 artículos (17.7%) nunca aparecen en compras: para ésos
    nunca va a haber propuesta, y la pantalla no puede dejarlos esperando sin
    decirlo. Su salida es el marcado manual (ticket 27), que todavía no existe:
    la frase dice eso, sin prometer un botón que no hay."""
    [sin] = proponer([_ya(1)], [], productos_con_compras=frozenset({2, 3})).sin_propuesta

    assert sin.motivo == MOTIVO_NUNCA_EN_COMPRAS
    frase = frase_del_motivo(MOTIVO_NUNCA_EN_COMPRAS)
    assert "nunca ha aparecido en una compra" in frase or "nunca han aparecido en una compra" in frase
    assert "a mano" in frase
    assert "todavía no" in frase


def test_sin_saber_si_se_compro_alguna_vez_no_se_afirma_que_nunca():
    """`None` es "no se pudo leer", que no es "nunca" (regla 4): se dice lo
    que sí se sabe —todavía no aparece— y nada más."""
    [sin] = proponer([_ya(1)], [], productos_con_compras=None).sin_propuesta
    assert sin.motivo == MOTIVO_TODAVIA_NO


def test_casilla_6_todavia_no_aparece_es_normal_y_no_un_error():
    """Una noche de retraso es lo ordinario: la compra que se captura hoy en
    SICAR llega al almacén con la cadena de la noche. Se dice así."""
    [sin] = proponer([_ya(1)], [], productos_con_compras=frozenset({1})).sin_propuesta
    assert sin.motivo == MOTIVO_TODAVIA_NO

    frase = frase_del_motivo(MOTIVO_TODAVIA_NO)
    assert "normal" in frase
    assert "no un error" in frase or "no es un error" in frase
    assert "20:30" in AVISO_DEL_RETRASO
    assert "normal" in AVISO_DEL_RETRASO
    assert "sábado" in AVISO_DEL_RETRASO and "lunes" in AVISO_DEL_RETRASO


def test_casilla_5_lo_rechazado_no_se_vuelve_a_proponer_pero_otra_compra_si():
    """**Por qué el rechazo se guarda aunque la propuesta no.** Si solo se
    recalculara, la misma compra rechazada volvería mañana. Se guarda QUÉ
    compra se rechazó —no una fecha tope— porque una compra con la misma fecha
    puede llegar al almacén una noche después (capturada a las 19:30 del
    viernes, llega el lunes) y no hay por qué esconderla."""
    ya = _ya(1, compras_rechazadas=(501,))

    solo_la_rechazada = proponer([ya], [_compra(501, 1, MIERCOLES)])
    assert solo_la_rechazada.propuestas == ()
    assert solo_la_rechazada.sin_propuesta[0].motivo == MOTIVO_RECHAZADA

    con_otra = proponer([ya], [_compra(501, 1, MIERCOLES), _compra(502, 1, MIERCOLES)])
    [propuesta] = con_otra.propuestas
    assert [c.compra_id for c in propuesta.compras] == [502]


def test_una_compra_que_ya_confirmo_otro_renglon_no_se_propone_otra_vez():
    [sin] = proponer(
        [_ya(1)], [_compra(501, 1, MIERCOLES)], ya_usadas=frozenset({501})
    ).sin_propuesta
    assert sin.motivo == MOTIVO_YA_USADA
    assert "un solo renglón" in frase_del_motivo(MOTIVO_YA_USADA)


# ------------------------------------------------------------ las cantidades


def test_dos_compras_del_mismo_producto_se_suman_en_una_propuesta():
    """Un pedido puede llegar en dos facturas. La evidencia es la suma, y cada
    compra se enseña por separado con su fecha."""
    [propuesta] = proponer(
        [_ya(1, cantidad=5)],
        [_compra(502, 1, JUEVES, 2), _compra(501, 1, MIERCOLES, 3)],
    ).propuestas

    assert [c.compra_id for c in propuesta.compras] == [501, 502]
    assert propuesta.piezas == 5
    assert propuesta.compras_ids == (501, 502)
    assert propuesta.se_puede_confirmar is True


def test_si_la_compra_trae_menos_no_se_confirma_como_completo_y_lo_dice():
    """**La puerta del ticket 27 se queda abierta, no se cierra.** `recibido`
    quiere decir "llegó completo" (CONTEXT.md); confirmar 3 de 5 así sería un
    renglón cerrado en falso, mercancía que no se vuelve a pedir (ADR 0002). Lo
    honesto es enseñar la cantidad y no ofrecer el clic que miente."""
    [propuesta] = proponer([_ya(1, cantidad=5)], [_compra(501, 1, MIERCOLES, 3)]).propuestas

    assert propuesta.piezas == 3
    assert propuesta.piezas_pedidas == 5
    assert propuesta.se_puede_confirmar is False
    assert "3 de las 5" in propuesta.motivo_para_no_confirmar
    frase = frase_de_la_cantidad(propuesta)
    assert "3 de las 5" in frase
    assert "parcial" in frase


def test_si_la_compra_trae_mas_se_puede_confirmar_y_se_dice():
    [propuesta] = proponer([_ya(1, cantidad=5)], [_compra(501, 1, MIERCOLES, 8)]).propuestas

    assert propuesta.se_puede_confirmar is True
    assert propuesta.motivo_para_no_confirmar is None
    frase = frase_de_la_cantidad(propuesta)
    assert "8 piezas" in frase and "5" in frase
    assert "más" in frase


def test_si_trae_lo_mismo_se_dice_sin_rodeos():
    [propuesta] = proponer([_ya(1, cantidad=5)], [_compra(501, 1, MIERCOLES, 5)]).propuestas
    assert frase_de_la_cantidad(propuesta) == "Trae las 5 piezas que se pidieron."


def test_con_una_sola_pieza_la_frase_no_se_tropieza():
    """Lo cazó el recorrido del navegador: decía "Trae las 1 pieza que se
    pidieron"."""
    [propuesta] = proponer([_ya(1, cantidad=1)], [_compra(501, 1, MIERCOLES, 1)]).propuestas
    assert frase_de_la_cantidad(propuesta) == "Trae la pieza que se pidió."


def test_las_frases_de_los_grupos_concuerdan_en_numero():
    """Lo cazó el recorrido: "siguen en camino" debajo de un solo renglón."""
    assert "sigue en camino" in frase_del_motivo(MOTIVO_RECHAZADA, cuantos=1)
    assert "siguen en camino" in frase_del_motivo(MOTIVO_RECHAZADA, cuantos=2)
    assert "este pedido" in frase_del_motivo(MOTIVO_SIN_PUENTE, ["QuePharma"], 1)
    assert "estos pedidos" in frase_del_motivo(MOTIVO_SIN_PUENTE, ["QuePharma"], 3)
    assert "este producto nunca ha" in frase_del_motivo(MOTIVO_NUNCA_EN_COMPRAS, cuantos=1)
    assert "estos productos nunca han" in frase_del_motivo(MOTIVO_NUNCA_EN_COMPRAS, cuantos=2)


def test_la_pantalla_no_cuenta_lo_recibido_como_por_atender():
    """Lo cazó el recorrido: un renglón recibido seguía en "por atender"."""
    pantalla = _texto(RAIZ / "src" / "continental" / "web" / "static" / "index.html")
    assert "visibles.length - enTransito - cancelados - recibidos" in pantalla
    assert "marcado como recibido" in pantalla


def test_las_frases_de_los_grupos_no_suponen_singular_ni_plural():
    """Lo cazó el recorrido: "recibirlo a mano" debajo de "estos productos"."""
    for motivo in (MOTIVO_SIN_PUENTE, MOTIVO_NUNCA_EN_COMPRAS, MOTIVO_SIN_HORA):
        assert "recibirlo" not in frase_del_motivo(motivo)
        assert "el recibido a mano" in frase_del_motivo(motivo)


# ------------------------------------ una compra que encaja con dos renglones


def test_una_compra_que_encaja_con_dos_renglones_se_dice_en_los_dos():
    """Dos pedidos distintos del mismo producto al mismo proveedor, los dos en
    camino, y una compra que encaja con los dos. No se asigna a ninguno en
    silencio: se propone en los dos, **cada uno dice que la comparte**, y el
    `WHERE` de confirmar impide que la misma compra confirme dos renglones."""
    lunes = _ya(1, renglon_id=10, enviado_en=_local(LUNES))
    martes = _ya(1, renglon_id=11, enviado_en=_local(MARTES), fecha_del_pedido=MARTES)

    recepcion = proponer([lunes, martes], [_compra(501, 1, MIERCOLES, 5)])

    uno, dos = recepcion.propuestas
    assert uno.tambien_encaja_con == (11,)
    assert dos.tambien_encaja_con == (10,)
    como_json = recepcion_como_json(recepcion, _local(JUEVES))
    for propuesta in como_json["propuestas"]:
        assert propuesta["compartida"] is not None
        assert "un solo renglón" in propuesta["compartida"]


def test_una_compra_de_antes_del_segundo_envio_solo_encaja_con_el_primero():
    lunes = _ya(1, renglon_id=10, enviado_en=_local(LUNES))
    jueves = _ya(1, renglon_id=11, enviado_en=_local(JUEVES), fecha_del_pedido=JUEVES)

    recepcion = proponer([lunes, jueves], [_compra(501, 1, MARTES, 5)])

    [propuesta] = recepcion.propuestas
    assert propuesta.renglon_id == 10
    assert propuesta.tambien_encaja_con == ()
    assert [s.renglon_id for s in recepcion.sin_propuesta] == [11]


# ------------------------------------------------------------- el JSON y las frases


def test_el_json_trae_la_evidencia_hecha_frase_y_los_datos():
    [propuesta] = recepcion_como_json(
        proponer([_ya(1)], [_compra(501, 1, MIERCOLES, 5, folio="A-77")]),
        _local(JUEVES),
    )["propuestas"]

    assert propuesta["renglon_id"] == 10
    assert propuesta["compras"] == [501]
    assert propuesta["se_puede_confirmar"] is True
    assert propuesta["piezas"] == 5
    assert propuesta["piezas_pedidas"] == 5
    [evidencia] = propuesta["evidencia"]
    assert evidencia["fecha"] == MIERCOLES.isoformat()
    assert evidencia["cantidad"] == 5
    assert evidencia["folio"] == "A-77"
    # La frase dice proveedor, fecha, piezas y cuántos días después del envío,
    # y enseña el folio diciendo que NO se usó para emparejar.
    assert "NADRO" in evidencia["frase"]
    assert "miércoles 16 de septiembre" in evidencia["frase"]
    assert "5 piezas" in evidencia["frase"]
    assert "2 días después de enviarlo" in evidencia["frase"]
    assert "A-77" in evidencia["frase"]
    assert "no se usó para emparejar" in evidencia["frase"]
    assert "Probablemente" in propuesta["frase"]


def test_la_evidencia_del_mismo_dia_lo_dice_con_palabras():
    [propuesta] = recepcion_como_json(
        proponer([_ya(1, enviado_en=_local(MIERCOLES, 9))], [_compra(501, 1, MIERCOLES)]),
        _local(JUEVES),
    )["propuestas"]
    assert "el mismo día en que se envió" in propuesta["evidencia"][0]["frase"]


def test_el_json_agrupa_lo_que_no_tiene_propuesta_por_motivo():
    recepcion = proponer(
        [
            _ya(1),
            _ya(2),
            _ya(3, proveedor="quepharma", proveedor_id=None),
            _ya(4),
        ],
        [],
        productos_con_compras=frozenset({1, 2, 3}),
    )
    grupos = recepcion_como_json(recepcion, _local(JUEVES))["esperan"]

    por_motivo = {g["motivo"]: g for g in grupos}
    assert sorted(r["renglon_id"] for r in por_motivo[MOTIVO_TODAVIA_NO]["renglones"]) == [10, 20]
    assert [r["renglon_id"] for r in por_motivo[MOTIVO_SIN_PUENTE]["renglones"]] == [30]
    assert "QuePharma" in por_motivo[MOTIVO_SIN_PUENTE]["frase"]
    assert [r["renglon_id"] for r in por_motivo[MOTIVO_NUNCA_EN_COMPRAS]["renglones"]] == [40]
    # El orden es el de los motivos, fijo: lo que nunca va a tener propuesta
    # va primero, porque es lo que alguien tiene que resolver a mano.
    assert [g["motivo"] for g in grupos] == [
        MOTIVO_SIN_PUENTE,
        MOTIVO_NUNCA_EN_COMPRAS,
        MOTIVO_TODAVIA_NO,
    ]


def test_el_bloque_nunca_calla():
    """Callar se leería "no hay nada que recibir", y quizá sí lo haya."""
    assert "Nada viene en camino" in frase_del_bloque(0, 0)
    assert "Ninguna compra" in frase_del_bloque(0, 3)
    assert frase_del_bloque(1, 0).startswith("1 renglón en camino probablemente ya llegó")
    assert frase_del_bloque(2, 1).startswith("2 renglones en camino probablemente ya llegaron")


def test_el_json_lleva_siempre_el_aviso_del_retraso_y_lo_que_significa_confirmar():
    vacio = recepcion_como_json(proponer([], []), _local(JUEVES))

    assert vacio["ok"] is True
    assert vacio["aviso_del_retraso"] == AVISO_DEL_RETRASO
    assert vacio["advertencia"] == ADVERTENCIA_AL_CONFIRMAR
    assert "completo" in ADVERTENCIA_AL_CONFIRMAR
    assert "Rechazar" in ADVERTENCIA_AL_CONFIRMAR
    assert "sigue en camino" in ADVERTENCIA_AL_CONFIRMAR


def test_la_recepcion_con_hueco_dice_por_que_y_no_enseña_un_cero():
    hueco = recepcion_con_hueco("no se pudieron leer las compras (OperationalError)")

    assert hueco["ok"] is False
    assert hueco["detalle"] == "no se pudieron leer las compras (OperationalError)"
    assert hueco["propuestas"] == [] and hueco["esperan"] == []
    assert "No se pudo" in hueco["frase"]
    # El aviso viaja igual: que no se haya podido leer no quita que el retraso
    # de una noche sea normal.
    assert hueco["aviso_del_retraso"] == AVISO_DEL_RETRASO


def test_ninguna_frase_de_recepcion_afirma_que_llego():
    """"Probablemente" y no "llegó": la palabra del glosario. Solo la firma de
    lo confirmado afirma, y esa es de una persona."""
    como_json = recepcion_como_json(
        proponer([_ya(1)], [_compra(501, 1, MIERCOLES)]), _local(JUEVES)
    )
    [propuesta] = como_json["propuestas"]
    assert propuesta["frase"].startswith("Probablemente ya llegó")
    assert "llegó completo" not in propuesta["frase"]


def test_el_enganche_del_24_sigue_siendo_recibido():
    """Confirmar escribe `recibido`, que es uno de los estados que cierran el
    tránsito: con eso lo retenido vuelve solo (ADR 0012)."""
    assert RENGLON_RECIBIDO in ESTADOS_QUE_CIERRAN_EL_TRANSITO


# ==========================================================================
# LO QUE SE GUARDA — el doble, los CHECK en Python y el SQL como texto
# ==========================================================================

from continental.almacen import AlmacenPostgres, LecturaDelAlmacen  # noqa: E402
from continental.almacenamiento import (  # noqa: E402
    AlmacenamientoDelPedido,
    RenglonRecibido,
    Ventana,
    revisar_el_renglon,
)
from continental.dobles import AlmacenFalso, AlmacenamientoFalso  # noqa: E402

SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
CREAR_ROL = SQL / "crear_rol.sql"
MIGRACION = SQL / "migraciones" / "0010-la-recepcion-sugerida.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
ALMACEN = RAIZ / "src" / "continental" / "almacen.py"


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    """El `.sql` sin sus comentarios: lo único que Postgres ejecuta."""
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def _sentencia_python(ruta: Path, nombre: str) -> str:
    """El texto de una sentencia `text(...)` de un módulo, sin comentarios."""
    fuente = _texto(ruta)
    inicio = fuente.index('"""', fuente.index(f"{nombre} = text(")) + 3
    fin = fuente.index('"""', inicio)
    return re.sub(r"--[^\n]*", "", fuente[inicio:fin])


def _lista_con(almacenamiento, fecha: dt.date, productos, negocio: str = NEGOCIO):
    return almacenamiento.insertar_la_lista(
        negocio, fecha, Ventana(fecha, fecha), [_renglon(p) for p in productos]
    )


def _enviar_en_el_doble(
    almacenamiento, lista, productos, proveedor="nadro", proveedor_id=NADRO
):
    from continental.particion import Linea, PedidoPorArmar

    renglones = [r for r in lista.renglones if r.propuesto.producto_id in productos]
    pedidos = almacenamiento.guardar_la_particion(
        lista.negocio,
        lista.pedido_sugerido_id,
        [
            PedidoPorArmar(
                proveedor=proveedor,
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
    [pedido] = [p for p in pedidos if p.proveedor == proveedor]
    return almacenamiento.enviar_el_pedido(lista.negocio, pedido.pedido_id, CORREO)


def _estado(almacenamiento, renglon_id: int, negocio: str = NEGOCIO) -> str:
    return almacenamiento.leer_renglon(negocio, renglon_id).estado


def test_el_doble_sigue_cumpliendo_las_dos_interfaces():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)
    assert isinstance(AlmacenFalso(), LecturaDelAlmacen)
    assert isinstance(AlmacenPostgres(fabrica_de_motor=None), LecturaDelAlmacen)


def test_lo_que_esta_en_transito_trae_todas_las_listas_con_su_pro_id(almacenamiento):
    """La lista de HOY también: lo enviado hoy puede llegar hoy mismo. Y cada
    renglón trae el `pro_id` que su pedido guardó al partirse (ADR 0008), que
    es con lo que se cruza `fct_compras`."""
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    _enviar_en_el_doble(almacenamiento, lunes, {1})
    martes = _lista_con(almacenamiento, MARTES, [3])
    _enviar_en_el_doble(almacenamiento, martes, {3}, proveedor="quepharma", proveedor_id=None)

    en_camino = almacenamiento.lo_que_esta_en_transito(NEGOCIO)

    assert [ya.producto_id for ya in en_camino] == [1, 3]
    assert [ya.proveedor_id for ya in en_camino] == [NADRO, None]
    assert all(ya.esta_en_transito for ya in en_camino)
    assert almacenamiento.lo_que_esta_en_transito("farmacia_02") == ()


def test_confirmar_pasa_a_recibido_firmado_y_con_sus_compras(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1})
    [renglon_id] = enviado.renglones

    recibido = almacenamiento.confirmar_la_recepcion(
        NEGOCIO, renglon_id, (501, 502), 5, DUENO
    )

    assert recibido.estado == RENGLON_RECIBIDO
    assert recibido.recibido_por == DUENO
    assert recibido.recibido_en is not None
    assert recibido.recibido_con_compras == (501, 502)
    assert recibido.esta_recibido is True


def test_confirmar_cierra_el_transito_y_lo_retenido_vuelve_solo(almacenamiento):
    """**El enganche del ticket 24, ejercitado por quien lo iba a usar.** En
    cuanto el renglón pasa a `recibido`, `lo_ya_pedido` lo trae como "ya
    llegó" y la memoria lo cuenta desde el día siguiente al ancla. Nadie tuvo
    que tocar `transito.py`."""
    from continental.transito import memoria_de_lo_pedido

    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    antes = memoria_de_lo_pedido(almacenamiento.lo_ya_pedido(NEGOCIO, MIERCOLES))
    assert antes.esta_en_camino(1)

    almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO)

    despues = memoria_de_lo_pedido(almacenamiento.lo_ya_pedido(NEGOCIO, MIERCOLES))
    assert not despues.esta_en_camino(1)
    assert despues.desde[1] == MARTES


@pytest.mark.parametrize("estado", ["abierto", "descartado"])
def test_confirmar_exige_que_este_en_transito(almacenamiento, estado):
    """La transición vive en el `WHERE`: solo lo `en tránsito` se recibe."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    renglon_id = lunes.renglones[0].renglon_id
    if estado == "descartado":
        almacenamiento.descartar(NEGOCIO, renglon_id, CORREO)

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO) is None
    assert _estado(almacenamiento, renglon_id) == estado


def test_confirmar_dos_veces_no_mueve_la_firma(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    primero = almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO)

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (502,), 5, CORREO) is None
    releido = almacenamiento.leer_renglon(NEGOCIO, renglon_id)
    assert releido.recibido_por == DUENO
    assert releido.recibido_en == primero.recibido_en
    assert releido.recibido_con_compras == (501,)


def test_confirmar_exige_que_la_evidencia_alcance_lo_pedido(almacenamiento):
    """El mismo límite que la pantalla, como parámetro del `WHERE`: la base no
    cierra como completo lo que trae menos, aunque alguien fabrique la
    petición (es el patrón del límite del atraso del ticket 25)."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 4.999, DUENO) is None
    assert _estado(almacenamiento, renglon_id) == RENGLON_EN_TRANSITO


def test_una_compra_no_confirma_dos_renglones(almacenamiento):
    """**La decisión de "una compra que encaja con dos renglones", en la tabla.**
    La pantalla la enseña en los dos; el primero que se confirma se la queda, y
    el segundo intento con la misma compra da cero filas."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [uno] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    martes = _lista_con(almacenamiento, MARTES, [1])
    [dos] = _enviar_en_el_doble(almacenamiento, martes, {1}).renglones

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, uno, (501,), 5, DUENO) is not None
    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, dos, (501, 502), 5, DUENO) is None
    assert _estado(almacenamiento, dos) == RENGLON_EN_TRANSITO


def test_no_se_confirma_con_una_compra_que_ese_renglon_rechazo(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (501,), CORREO)

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO) is None


def test_un_pedido_sin_puente_no_se_confirma_con_compras(almacenamiento):
    """Sin `pro_id` no hay compra de SICAR que pueda ser suya (ADR 0008)."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(
        almacenamiento, lunes, {1}, proveedor="quepharma", proveedor_id=None
    ).renglones

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO) is None


def test_confirmar_y_rechazar_miran_el_negocio(almacenamiento):
    """Regla 7: el negocio va en el `WHERE`, no solo en la fila."""
    lunes = _lista_con(almacenamiento, LUNES, [1], negocio="farmacia_02")
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones

    assert almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO) is None
    assert almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (501,), DUENO) is None
    assert _estado(almacenamiento, renglon_id, "farmacia_02") == RENGLON_EN_TRANSITO


def test_rechazar_deja_el_renglon_en_transito_y_acumula_lo_rechazado(almacenamiento):
    """"Rechazar lo devuelve a `en tránsito`": nunca dejó de estarlo, porque la
    propuesta no es un estado. Lo que se guarda es QUÉ compra no es suya."""
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones

    primero = almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (501,), CORREO)
    segundo = almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (502, 503), DUENO)

    assert primero.estado == RENGLON_EN_TRANSITO
    assert segundo.estado == RENGLON_EN_TRANSITO
    assert segundo.compras_rechazadas == (501, 502, 503)
    # La firma es la del último rechazo: lo dice el ADR 0014, con lo que cuesta.
    assert segundo.recepcion_rechazada_por == DUENO
    assert segundo.recepcion_rechazada_en is not None


def test_rechazar_dos_veces_la_misma_compra_no_escribe_nada(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (501,), CORREO)

    assert almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (501,), DUENO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).recepcion_rechazada_por == CORREO


def test_rechazar_exige_que_este_en_transito(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    [renglon_id] = _enviar_en_el_doble(almacenamiento, lunes, {1}).renglones
    almacenamiento.confirmar_la_recepcion(NEGOCIO, renglon_id, (501,), 5, DUENO)

    assert almacenamiento.rechazar_la_recepcion(NEGOCIO, renglon_id, (502,), CORREO) is None
    assert _estado(almacenamiento, renglon_id) == RENGLON_RECIBIDO


def test_lo_recibido_dice_que_compras_ya_se_usaron_y_de_que_pedido(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1, 2})
    uno, _dos = enviado.renglones
    almacenamiento.confirmar_la_recepcion(NEGOCIO, uno, (501, 502), 5, DUENO)

    recibidos = almacenamiento.lo_recibido(NEGOCIO, {1}, set())
    assert recibidos == (
        RenglonRecibido(
            renglon_id=uno,
            pedido_id=enviado.pedido.pedido_id,
            producto_id=1,
            compras=(501, 502),
        ),
    )
    # También por pedido: es lo que dice que ese pedido ya no se cancela.
    assert len(almacenamiento.lo_recibido(NEGOCIO, set(), {enviado.pedido.pedido_id})) == 1
    assert almacenamiento.lo_recibido(NEGOCIO, {2}, set()) == ()
    assert almacenamiento.lo_recibido("farmacia_02", {1}, set()) == ()


def test_un_pedido_con_algo_recibido_ya_no_se_cancela(almacenamiento):
    """El `NOT EXISTS` que el ticket 25 dejó puesto "para que el 26 no tenga
    que acordarse": ahora lo ejercita un recibido de verdad."""
    lunes = _lista_con(almacenamiento, LUNES, [1, 2])
    enviado = _enviar_en_el_doble(almacenamiento, lunes, {1, 2})
    almacenamiento.confirmar_la_recepcion(NEGOCIO, enviado.renglones[0], (501,), 5, DUENO)

    assert almacenamiento.cancelar_el_pedido(NEGOCIO, enviado.pedido.pedido_id, DUENO) is None


# --------------------------------------------------- los CHECK, en Python


def _columnas(**cambios) -> dict:
    from continental.almacenamiento import columnas_del_renglon

    return {**columnas_del_renglon(_renglon(1), NEGOCIO), **cambios}


def test_recibido_sin_firma_rebota():
    with pytest.raises(ValueError, match="ck_renglon_recepcion"):
        revisar_el_renglon(_columnas(estado=RENGLON_RECIBIDO))


def test_recibido_parcial_tambien_exige_firma():
    """El ticket 27 firma igual: todo marcado de recepción dice quién y cuándo."""
    with pytest.raises(ValueError, match="ck_renglon_recepcion"):
        revisar_el_renglon(_columnas(estado="recibido parcial"))


def test_una_firma_de_recepcion_en_un_renglon_que_no_llego_rebota():
    with pytest.raises(ValueError, match="ck_renglon_recepcion"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_EN_TRANSITO, recibido_por=DUENO, recibido_en=_local(MARTES))
        )


def test_compras_de_la_recepcion_en_un_renglon_que_no_llego_rebotan():
    with pytest.raises(ValueError, match="ck_renglon_compras_de_la_recepcion"):
        revisar_el_renglon(_columnas(estado=RENGLON_EN_TRANSITO, recibido_con_compras=[501]))


def test_la_lista_de_compras_de_la_recepcion_no_va_vacia():
    with pytest.raises(ValueError, match="ck_renglon_compras_de_la_recepcion"):
        revisar_el_renglon(
            _columnas(
                estado=RENGLON_RECIBIDO,
                recibido_por=DUENO,
                recibido_en=_local(MARTES),
                recibido_con_compras=[],
            )
        )


def test_recibido_sin_compras_es_valido_para_el_marcado_manual_del_27():
    """La puerta del 27, en el CHECK: recibido y firmado, sin compra de SICAR."""
    revisar_el_renglon(
        _columnas(estado=RENGLON_RECIBIDO, recibido_por=DUENO, recibido_en=_local(MARTES))
    )


def test_la_firma_de_recepcion_vacia_rebota():
    with pytest.raises(ValueError, match="ck_renglon_recibido_por"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_RECIBIDO, recibido_por="", recibido_en=_local(MARTES))
        )


@pytest.mark.parametrize(
    "cambios",
    [
        {"compras_rechazadas": [501]},
        {"compras_rechazadas": [501], "recepcion_rechazada_por": CORREO},
        {
            "recepcion_rechazada_por": CORREO,
            "recepcion_rechazada_en": dt.datetime(2026, 9, 15, tzinfo=dt.UTC),
        },
        {
            "compras_rechazadas": [],
            "recepcion_rechazada_por": CORREO,
            "recepcion_rechazada_en": dt.datetime(2026, 9, 15, tzinfo=dt.UTC),
        },
    ],
)
def test_el_rechazo_va_pareado_con_su_firma(cambios):
    with pytest.raises(ValueError, match="ck_renglon_rechazo"):
        revisar_el_renglon(_columnas(estado=RENGLON_EN_TRANSITO, **cambios))


def test_la_firma_del_rechazo_vacia_rebota():
    with pytest.raises(ValueError, match="ck_renglon_rechazo_por"):
        revisar_el_renglon(
            _columnas(
                estado=RENGLON_EN_TRANSITO,
                compras_rechazadas=[501],
                recepcion_rechazada_por="",
                recepcion_rechazada_en=_local(MARTES),
            )
        )


def test_el_doble_rechaza_un_recibido_sin_firma_igual_que_postgres(almacenamiento):
    lunes = _lista_con(almacenamiento, LUNES, [1])
    with pytest.raises(ValueError, match="ck_renglon_recepcion"):
        almacenamiento.poner_estado_del_renglon(lunes.renglones[0].renglon_id, RENGLON_RECIBIDO)


# ------------------------------------------------------------- el almacén


def test_el_almacen_dice_que_productos_han_aparecido_alguna_vez_en_compras():
    """Para decir "nunca va a haber propuesta" hay que saber que el producto
    nunca se ha comprado. Es una lectura sobre `fct_compras`, que el rol ya
    lee: no hace falta un permiso nuevo."""
    almacen = AlmacenFalso(
        compras_en_memoria=[_compra(501, 1, dt.date(2024, 1, 5)), _compra(502, 3, MARTES)]
    )
    assert almacen.productos_con_compras({1, 2, 3}) == frozenset({1, 3})
    assert almacen.productos_con_compras(set()) == frozenset()


def test_la_consulta_de_productos_con_compras_solo_lee_fct_compras():
    sentencia = _sentencia_python(ALMACEN, "_PRODUCTOS_CON_COMPRAS")
    assert "from marts.fct_compras" in sentencia
    assert "producto_id = any(:productos)" in sentencia
    assert "folio" not in sentencia
    # Ninguna tabla nueva de `marts`: el GRANT que ya estaba alcanza.
    assert "GRANT SELECT ON marts.fct_compras TO continental;" in _texto(CREAR_ROL)


# --------------------------------------------------------- el SQL como texto


def test_confirmar_lleva_la_transicion_y_las_garantias_en_el_where():
    sentencia = _sentencia_python(ALMACENAMIENTO, "_CONFIRMAR_LA_RECEPCION")

    assert "set estado = 'recibido'" in sentencia
    assert "recibido_por = :quien" in sentencia
    assert "recibido_en = now()" in sentencia
    assert "r.estado = 'en tránsito'" in sentencia
    assert "p.estado = 'enviado'" in sentencia
    assert "p.proveedor_id is not null" in sentencia
    assert "p.negocio = r.negocio" in sentencia
    assert "coalesce(r.cantidad_final, r.cantidad_propuesta) <= :piezas" in sentencia
    # Ni una compra rechazada por él, ni una que ya confirmó otro renglón.
    assert "r.compras_rechazadas" in sentencia and "&&" in sentencia
    assert "r2.recibido_con_compras &&" in sentencia
    assert "folio" not in sentencia


def test_rechazar_no_cambia_el_estado_y_lo_exige():
    sentencia = _sentencia_python(ALMACENAMIENTO, "_RECHAZAR_LA_RECEPCION")

    assert "set estado" not in sentencia
    assert "r.estado = 'en tránsito'" in sentencia
    assert "recepcion_rechazada_por = :quien" in sentencia
    assert "||" in sentencia  # agrega, nunca pisa
    assert "p.estado = 'enviado'" in sentencia


def test_lo_que_esta_en_transito_no_mira_la_fecha_de_la_lista():
    sentencia = _sentencia_python(ALMACENAMIENTO, "_EN_TRANSITO")
    assert "r.estado = 'en tránsito'" in sentencia
    assert "p.proveedor_id" in sentencia
    assert "antes_de" not in sentencia
    assert "p.negocio = r.negocio" in sentencia and "s.negocio = r.negocio" in sentencia


def test_las_lecturas_de_renglones_traen_las_columnas_de_la_recepcion():
    for nombre in ("_LEER_RENGLONES", "_LEER_RENGLON_POR_ID", "_LO_YA_PEDIDO", "_EN_TRANSITO"):
        sentencia = _sentencia_python(ALMACENAMIENTO, nombre)
        for columna in (
            "recibido_por",
            "recibido_en",
            "recibido_con_compras",
            "compras_rechazadas",
            "recepcion_rechazada_por",
            "recepcion_rechazada_en",
        ):
            assert columna in sentencia, (nombre, columna)


def test_la_migracion_0010_agrega_columnas_y_no_crea_tabla():
    """No crea tabla: `crear_rol.sql` NO hace falta volver a correrlo."""
    sentencias = _sentencias(MIGRACION)

    assert "CREATE TABLE" not in sentencias
    assert "GRANT" not in sentencias
    for columna in (
        "recibido_por text",
        "recibido_en timestamptz",
        "recibido_con_compras bigint[]",
        "compras_rechazadas bigint[]",
        "recepcion_rechazada_por text",
        "recepcion_rechazada_en timestamptz",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {columna}" in sentencias, columna
    assert "current_user = 'continental'" in sentencias
    assert "SET client_encoding TO 'UTF8'" in sentencias


def test_los_check_de_la_recepcion_estan_en_los_dos_archivos():
    """`crear_tablas.sql` es la forma a la que se quiere llegar y la migración
    es cómo llega una base que ya existe (ADR 0003): las dos o ninguna."""
    for ruta in (CREAR_TABLAS, MIGRACION):
        sentencias = _sentencias(ruta)
        for restriccion in (
            "ck_renglon_recibido_por",
            "ck_renglon_recepcion",
            "ck_renglon_compras_de_la_recepcion",
            "ck_renglon_rechazo_por",
            "ck_renglon_rechazo",
        ):
            assert f"CONSTRAINT {restriccion}" in sentencias, (ruta.name, restriccion)
        assert "estado IN ('recibido', 'recibido parcial')" in sentencias
        assert "cardinality(recibido_con_compras) >= 1" in sentencias
        assert "cardinality(compras_rechazadas) >= 1" in sentencias


def test_crear_tablas_trae_las_seis_columnas():
    sentencias = _sentencias(CREAR_TABLAS)
    for columna in (
        "recibido_por",
        "recibido_en",
        "recibido_con_compras",
        "compras_rechazadas",
        "recepcion_rechazada_por",
        "recepcion_rechazada_en",
    ):
        assert re.search(rf"\n\s+{columna}\s+", sentencias), columna
    assert "0010-la-recepcion-sugerida.sql" in _texto(CREAR_TABLAS)


def test_verificar_rol_mira_la_recepcion():
    texto = _texto(VERIFICAR_ROL)
    assert "(34," in texto and "(35," in texto
    assert "ck_renglon_recepcion" in texto
    assert "ck_renglon_rechazo" in texto


# ==========================================================================
# LO QUE SE VE — las rutas de punta a punta, de varios días, y la pantalla
# ==========================================================================

from decimal import Decimal  # noqa: E402

from continental.precios import LecturaDePrecio  # noqa: E402

RUTA = "/api/pedido-sugerido"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}
PANTALLA = RAIZ / "src" / "continental" / "web" / "static" / "index.html"


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


def _lectura(proveedor: str, precio: str = "12.50") -> LecturaDePrecio:
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


def _enviar(
    cliente,
    almacenamiento,
    lista: dict,
    productos: set[int],
    enviado_en: dt.datetime,
    proveedor: str = "nadro",
) -> dict:
    """Pone precio de ese proveedor a esos productos, descarta el resto, parte,
    envía, y **fija la hora del envío**: el doble firma con el reloj real, y
    la recepción cuenta "posterior al envío" contra esa hora."""
    for r in lista["renglones"]:
        if r["producto_id"] in productos:
            almacenamiento.guardar_precios(NEGOCIO, r["renglon_id"], [_lectura(proveedor)])
        elif r["estado"] == "abierto":
            cliente.post(f"/api/renglon/{r['renglon_id']}/descartar", headers=FIRMA)
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    assert partida["ok"] is True, partida
    [pedido] = [p for p in partida["pedidos"] if p["proveedor"] == proveedor]
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


def _confirmar(cliente, renglon_id: int, compras, quien: str | None = DUENO):
    cabeceras = {} if quien is None else {"Cf-Access-Authenticated-User-Email": quien}
    return cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/confirmar",
        json={"compras": list(compras)},
        headers=cabeceras,
    )


def _rechazar(cliente, renglon_id: int, compras, quien: str = CORREO):
    return cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/rechazar",
        json={"compras": list(compras)},
        headers={"Cf-Access-Authenticated-User-Email": quien},
    )


def _por_producto(lista: dict) -> dict[int, dict]:
    return {r["producto_id"]: r for r in lista["renglones"]}


def _propuestas(lista: dict) -> dict[int, dict]:
    return {p["renglon_id"]: p for p in lista["recepcion"]["propuestas"]}


def _esperan(lista: dict) -> dict[str, list[int]]:
    return {
        g["motivo"]: [r["renglon_id"] for r in g["renglones"]]
        for g in lista["recepcion"]["esperan"]
    }


def test_de_punta_a_punta_esperar_proponer_confirmar_y_lo_retenido_vuelve(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**Las siete casillas en una semana**, con las listas de en medio cerradas.

    - Lunes: se venden 3 del producto 1, se envían a NADRO a las 11:00.
    - Martes: se venden 2 más; el 1 no se propone (viene en camino). SICAR
      todavía no tiene la compra: la recepción dice que **es normal**.
    - Miércoles: la cadena trae la compra del martes —una noche de retraso—.
      El renglón queda **probablemente recibido**, con su evidencia, y **sigue
      en tránsito**: nadie lo ha confirmado.
    - Se confirma: pasa a `recibido`, firmado, con la compra que lo sostiene.
    - Jueves: la lista trae las 2 del martes, la del miércoles y la del jueves,
      que se vendieron mientras venía (el enganche del ticket 24): **4**.
    """
    _fijar_la_hora(monkeypatch, _local(JUEVES, 9))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    # Una compra vieja del producto 1: sí aparece en compras alguna vez.
    almacen.compras_en_memoria = [_compra(400, 1, dt.date(2025, 3, 3), 10)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 2), _venta(MARTES, 2, 1)]
    martes = _abrir(cliente)
    assert sorted(_por_producto(martes)) == [2]
    assert martes["recepcion"]["propuestas"] == []
    [renglon_id] = _esperan(martes)[MOTIVO_TODAVIA_NO]
    assert "normal" in martes["recepcion"]["aviso_del_retraso"]
    _cerrar(cliente, martes)

    almacen.compras_en_memoria.append(_compra(501, 1, MARTES, 3, folio="B-12"))
    almacen.ventas_en_memoria += [_venta(MIERCOLES, 1, 1)]
    miercoles = _abrir(cliente)
    propuesta = _propuestas(miercoles)[renglon_id]
    assert propuesta["compras"] == [501]
    assert propuesta["se_puede_confirmar"] is True
    assert "martes 15 de septiembre" in propuesta["evidencia"][0]["frase"]
    # Casilla 3: probablemente, y todavía en camino. Nada pasó solo.
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO
    assert [r["renglon_id"] for r in miercoles["en_camino"]["renglones"]] == [renglon_id]
    _cerrar(cliente, miercoles)

    respuesta = _confirmar(cliente, renglon_id, [501])
    assert respuesta.status_code == 200, respuesta.json()
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert "quedó recibido" in cuerpo["frase"]
    recibido = almacenamiento.leer_renglon(NEGOCIO, renglon_id)
    assert recibido.estado == RENGLON_RECIBIDO
    assert recibido.recibido_por == DUENO
    assert recibido.recibido_con_compras == (501,)

    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    jueves = _abrir(cliente)
    uno = _por_producto(jueves)[1]
    assert uno["cantidad_propuesta"] == 4, "Lo vendido mientras venía se perdió."
    assert uno["ventas_desde"] == MARTES.isoformat()
    assert jueves["recepcion"]["propuestas"] == []
    assert jueves["en_camino"]["renglones"] == []


def test_casilla_5_rechazar_lo_deja_en_camino_y_no_vuelve_a_proponer_esa_compra(
    cliente, almacen, almacenamiento, monkeypatch
):
    """Rechazar no es un estado: el renglón sigue en tránsito. La compra
    rechazada no vuelve mañana; una compra distinta, sí."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    [renglon_id] = _propuestas(_abrir(cliente))

    respuesta = _rechazar(cliente, renglon_id, [501])
    assert respuesta.status_code == 200, respuesta.json()
    assert "sigue en camino" in respuesta.json()["frase"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO

    otra_vez = _abrir(cliente)
    assert otra_vez["recepcion"]["propuestas"] == []
    assert _esperan(otra_vez)[MOTIVO_RECHAZADA] == [renglon_id]

    almacen.compras_en_memoria.append(_compra(502, 1, MIERCOLES, 3))
    con_otra = _abrir(cliente)
    assert _propuestas(con_otra)[renglon_id]["compras"] == [502]


def test_confirmar_lo_que_ya_no_es_la_propuesta_contesta_409(
    cliente, almacen, almacenamiento, monkeypatch
):
    """Lo que se confirma es lo que la persona VIO: el servidor vuelve a
    calcular la propuesta y se niega si ya no es la misma (otra compra
    apareció, otra pestaña rechazó…). Nada cambia."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    [renglon_id] = _propuestas(_abrir(cliente))

    for compras in ([999], [501, 999], []):
        respuesta = _confirmar(cliente, renglon_id, compras)
        assert respuesta.status_code == 409, compras
        assert respuesta.json()["ok"] is False
        assert "Vuelve a cargar" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO
    assert _rechazar(cliente, renglon_id, [999]).status_code == 409


def test_lo_que_trae_menos_no_se_confirma_y_se_dice_por_que(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 2)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    lista = _abrir(cliente)
    [(renglon_id, propuesta)] = _propuestas(lista).items()
    assert propuesta["se_puede_confirmar"] is False
    assert "parcial" in propuesta["frase_de_la_cantidad"]

    respuesta = _confirmar(cliente, renglon_id, [501])
    assert respuesta.status_code == 409
    assert "2 de las 3" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).estado == RENGLON_EN_TRANSITO


def test_lo_enviado_hoy_tambien_puede_recibirse_hoy(
    cliente, almacen, almacenamiento, monkeypatch
):
    """La lista de HOY entra a la recepción: se pidió a las 9 y llegó a las 15.
    El renglón de la tabla dice que se recibió, con su firma, y deja de contar
    como algo en camino."""
    _fijar_la_hora(monkeypatch, _local(LUNES, 18))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 9))
    almacen.compras_en_memoria = [_compra(501, 1, LUNES, 3)]

    otra_vez = _abrir(cliente)
    [renglon_id] = _propuestas(otra_vez)
    assert "el mismo día en que se envió" in _propuestas(otra_vez)[renglon_id]["evidencia"][0]["frase"]
    assert _confirmar(cliente, renglon_id, [501]).status_code == 200

    despues = _abrir(cliente)
    [renglon] = despues["renglones"]
    assert renglon["estado"] == RENGLON_RECIBIDO
    assert renglon["esta_recibido"] is True
    assert renglon["esta_en_transito"] is False
    assert f"lo confirmó {DUENO}" in renglon["frase_de_lo_recibido"]
    assert "1 compra de SICAR" in renglon["frase_de_lo_recibido"]
    # Un pedido con algo recibido ya no ofrece cancelar: sí se capturó.
    [pedido] = despues["pedidos"]
    assert pedido["se_puede_cancelar"] is False
    assert "recibió" in pedido["motivo_para_no_cancelar"]
    assert "llegó" in despues["particion"]["sin_nada_por_repartir"]


def test_casilla_7_sin_puente_se_dice_que_nunca_habra_propuesta(
    cliente, almacen, almacenamiento, monkeypatch
):
    """QuePharma no está en `dim_proveedor` (ADR 0008): su pedido existe, se
    envía, y la recepción dice que nunca va a proponer nada para él."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11), proveedor="quepharma")

    lista = _abrir(cliente)
    assert lista["recepcion"]["propuestas"] == []
    [grupo] = lista["recepcion"]["esperan"]
    assert grupo["motivo"] == MOTIVO_SIN_PUENTE
    assert "QuePharma" in grupo["frase"]
    assert "Nunca" in grupo["frase"]


def test_casilla_7_lo_que_nunca_aparece_en_compras_se_dice(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))

    [grupo] = _abrir(cliente)["recepcion"]["esperan"]
    assert grupo["motivo"] == MOTIVO_NUNCA_EN_COMPRAS
    assert "todavía no se puede" in grupo["frase"]


def test_un_atrasado_con_propuesta_no_ofrece_devolverlo(
    cliente, almacen, almacenamiento, monkeypatch
):
    """**La advertencia del ticket 25, resuelta donde se puede.** Hasta hoy, lo
    que sí llegó también se veía atrasado, y devolverlo era pedirlo dos veces.
    Si hay una compra que encaja, lo probable es que llegó: el botón de
    devolver se apaga y se dice que primero se confirme o se rechace."""
    _fijar_la_hora(monkeypatch, _local(dt.date(2026, 9, 25), 9))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    almacen.ventas_en_memoria += [_venta(MARTES, 2, 1)]

    martes = _abrir(cliente)
    [fila] = martes["en_camino"]["renglones"]
    assert fila["atrasado"] is True
    assert fila["se_puede_devolver"] is False
    assert "Probablemente ya llegó" in fila["frase_de_la_recepcion"]

    # Y si se rechaza, el botón vuelve: ya no hay evidencia de que llegó.
    _rechazar(cliente, fila["renglon_id"], [501])
    [fila] = _abrir(cliente)["en_camino"]["renglones"]
    assert fila["se_puede_devolver"] is True
    assert fila["frase_de_la_recepcion"] is None


def test_el_bloque_de_lo_que_viene_no_ofrece_cancelar_un_pedido_con_algo_recibido(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2), _producto(3)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1, 2}, _local(LUNES, 11))
    uno = _por_producto(lunes)[1]["renglon_id"]
    assert _confirmar(cliente, uno, [501]).status_code == 200

    almacen.ventas_en_memoria += [_venta(MARTES, 3, 1)]
    [grupo] = _abrir(cliente)["en_camino"]["pedidos"]
    assert grupo["se_puede_cancelar"] is False
    assert "recibió" in grupo["motivo_para_no_cancelar"]


def test_la_firma_es_firma_y_no_permiso(cliente, almacen, almacenamiento, monkeypatch):
    """Regla 3: sin encabezado se firma `sin-identificar` y no se niega nada."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    [renglon_id] = _propuestas(_abrir(cliente))

    assert _confirmar(cliente, renglon_id, [501], quien=None).status_code == 200
    assert almacenamiento.leer_renglon(NEGOCIO, renglon_id).recibido_por == "sin-identificar"


def test_regla_5_el_error_no_viaja_al_navegador(
    cliente, almacen, almacenamiento, monkeypatch
):
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    almacen.compras_en_memoria = [_compra(501, 1, MARTES, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    [renglon_id] = _propuestas(_abrir(cliente))

    almacenamiento.falla = RuntimeError("postgresql://continental:secreto@atlas/farmacia")
    for respuesta in (_confirmar(cliente, renglon_id, [501]), _rechazar(cliente, renglon_id, [501])):
        cuerpo = respuesta.json()
        assert cuerpo["ok"] is False
        assert "(RuntimeError)" in cuerpo["detalle"]
        assert "secreto" not in respuesta.text


def test_regla_4_sin_compras_la_recepcion_es_un_hueco_y_la_lista_sigue(
    cliente, almacen, almacenamiento, monkeypatch
):
    """Si el almacén no deja leer compras —un `dbt build` se llevó el GRANT de
    `fct_compras`— la lista se enseña igual y la recepción dice por qué no."""
    _fijar_la_hora(monkeypatch, _local(MIERCOLES, 9))
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1}, _local(LUNES, 11))
    almacen.ventas_en_memoria += [_venta(MARTES, 2, 1)]
    _abrir(cliente)  # la lista del martes queda guardada

    def sin_permiso(fecha):
        raise PermissionError("permission denied for table fct_compras")

    monkeypatch.setattr(almacen, "compras_desde", sin_permiso)
    lista = _abrir(cliente)
    assert lista["recepcion"]["ok"] is False
    assert lista["recepcion"]["detalle"] == "no se pudieron leer las compras (PermissionError)"
    assert "fct_compras" not in str(lista["recepcion"])
    assert [r["producto_id"] for r in lista["renglones"]] == [2]


def test_sin_nada_en_camino_la_recepcion_lo_dice_y_no_lee_compras(
    cliente, almacen, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]

    def no_deberia(*_):
        raise AssertionError("Sin nada en camino no hay compras que leer.")

    monkeypatch.setattr(almacen, "compras_desde", no_deberia)
    lista = _abrir(cliente)
    assert lista["recepcion"]["ok"] is True
    assert "Nada viene en camino" in lista["recepcion"]["frase"]


# ------------------------------------------------------------ la pantalla


def _pantalla() -> str:
    return _texto(PANTALLA)


def test_la_pantalla_tiene_el_bloque_de_la_recepcion_y_sus_dos_botones():
    pantalla = _pantalla()
    assert 'id="recepcion"' in pantalla
    assert "const pintarRecepcion" in pantalla
    assert "pintarRecepcion(datos.recepcion)" in pantalla
    assert "'/recepcion/' + accion" in pantalla
    assert "Confirmar que llegó" in pantalla
    assert "Rechazar: no es este pedido" in pantalla


def test_la_pantalla_no_compone_las_frases_de_la_recepcion():
    """Las frases que afirman algo llegan hechas de Python (lección del 15)."""
    pantalla = _pantalla()
    inicio = pantalla.index("const pintarRecepcion")
    fin = pantalla.index("const recibirORechazar")
    cuerpo = pantalla[inicio:fin]
    # "piezas" no se revisa: `plural(p.cantidad, 'pieza', 'piezas')` es la
    # cifra pedida, que el bloque de lo en camino ya pinta igual desde el 24.
    for frase in ("Probablemente", "normal", "nunca", "parcial", "llegó completo"):
        assert frase not in cuerpo, frase
    for campo in ("p.frase", "e.frase", "p.frase_de_la_cantidad", "g.frase", "aviso_del_retraso"):
        assert campo in cuerpo, campo


def test_la_pantalla_manda_las_compras_que_vio():
    pantalla = _pantalla()
    inicio = pantalla.index("const recibirORechazar")
    cuerpo = pantalla[inicio : inicio + 2500]
    assert "JSON.stringify({ compras })" in cuerpo
    assert "await cargarPedido()" in cuerpo


def test_la_pantalla_conserva_la_recepcion_de_la_carga():
    """Partir, enviar y tachar devuelven la lista sin recepción: no se borra."""
    assert "if (!nuevo.recepcion) nuevo.recepcion = anterior.recepcion;" in _pantalla()


def test_lo_recibido_de_hoy_se_atenua_y_no_se_edita():
    pantalla = _pantalla()
    assert "r.esta_en_transito || r.esta_cancelado || r.esta_recibido" in pantalla
    assert "r.frase_de_lo_recibido" in pantalla
