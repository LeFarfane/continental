"""`transiciones.py`: el motivo real de cada transición, probado rama por
rama (propuesta 1 de la revisión de arquitectura, 2026-09-21; paso 2,
2026-09-22).

Puro y sin almacenamiento: cada prueba arma un `RenglonGuardado`, un
`PedidoGuardado` o un `PedidoSugeridoGuardado` a mano y pregunta el motivo. La
garantía —el `WHERE` de cada sentencia de `almacenamiento.py`— la cubren
`test_parcial.py`, `test_guardado.py`, `test_descarte.py`, `test_ajuste.py`,
`test_captura.py` (elegir proveedor), `test_envio.py` y `test_cancelar.py`;
esto solo cubre que la copia legible diga lo mismo que esas sentencias, rama
por rama. Las pruebas de `motivo_para_no_cancelar`, `motivo_para_no_enviar` y
`motivo_para_no_reabrir` —movidas aquí el 2026-09-22— se quedaron en los
archivos donde ya vivían (`test_cancelar.py`, `test_envio.py`,
`test_cierre.py`) y solo cambiaron de dónde importan la función: no se
perdió ninguna, y duplicarlas aquí no habría probado nada nuevo.
`motivo_para_no_editar` es enteramente nueva y sus pruebas están abajo.
"""

from __future__ import annotations

import datetime as dt

from continental.almacenamiento import (
    ABIERTO,
    BORRADOR,
    CANCELADO,
    CERRADO,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_CANCELADO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    VENCIDO,
    PedidoGuardado,
    PedidoSugeridoGuardado,
    Renglon,
    RenglonGuardado,
    Ventana,
)
from continental.transiciones import (
    ACCIONES_DE_EDICION,
    ACCIONES_QUE_EXIGEN_RENGLON_ABIERTO,
    DEVOLVER_A_ABIERTO,
    motivo_para_no_corregir,
    motivo_para_no_editar,
    motivo_para_no_recibir_a_mano,
)

NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
CENTRO = dt.timezone(dt.timedelta(hours=-6))
LUNES = dt.date(2026, 9, 14)
JUEVES = dt.date(2026, 9, 17)


def _local(fecha: dt.date, hora: int = 10) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, tzinfo=CENTRO)


def _renglon(estado: str, *, piezas_recibidas: float | None = None) -> RenglonGuardado:
    recibido = estado in (RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL)
    cancelado = estado == RENGLON_CANCELADO
    return RenglonGuardado(
        renglon_id=1,
        estado=estado,
        propuesto=Renglon(
            producto_id=1,
            clave="7501000000001",
            descripcion="PRODUCTO 1",
            piezas_vendidas=6.0,
            cantidad_propuesta=10,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        pedido_id=7,
        pedido_sugerido_id=1,
        recibido_por=CORREO if recibido else None,
        recibido_en=_local(JUEVES) if recibido else None,
        piezas_recibidas=piezas_recibidas,
        cancelado_por=CORREO if cancelado else None,
        cancelado_en=_local(JUEVES) if cancelado else None,
    )


def _pedido(estado: str = ENVIADO) -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=7,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor="nadro",
        proveedor_id=1,
        estado_declarado=estado,
        armado_en=_local(LUNES),
        enviado_por=CORREO if estado != BORRADOR else None,
        enviado_en=_local(LUNES, 11) if estado != BORRADOR else None,
        cancelado_por=CORREO if estado == CANCELADO else None,
        cancelado_en=_local(JUEVES) if estado == CANCELADO else None,
    )


# ==========================================================================
# motivo_para_no_corregir
# ==========================================================================


def test_no_recibido_no_se_corrige():
    for estado in (RENGLON_ABIERTO, RENGLON_DESCARTADO, RENGLON_EN_TRANSITO, RENGLON_CANCELADO):
        motivo = motivo_para_no_corregir(_renglon(estado), _pedido(), atendido_despues=False)
        assert motivo is not None
        assert "recibido" in motivo


def test_sin_pedido_no_se_afirma_que_se_pueda():
    """`pedido=None` bloquea igual, sea porque no hay pedido o porque quien
    llama no lo leyó: las dos son "no se puede afirmar que siga enviado"."""
    motivo = motivo_para_no_corregir(
        _renglon(RENGLON_RECIBIDO, piezas_recibidas=10), None, atendido_despues=False
    )
    assert motivo is not None
    assert "enviado" in motivo


def test_pedido_no_enviado_no_se_corrige():
    motivo = motivo_para_no_corregir(
        _renglon(RENGLON_RECIBIDO, piezas_recibidas=10),
        _pedido(BORRADOR),
        atendido_despues=False,
    )
    assert motivo is not None
    assert "enviado" in motivo


def test_atendido_despues_no_se_corrige():
    """El motivo real que la ruta adivinaba antes del 2026-09-21."""
    motivo = motivo_para_no_corregir(
        _renglon(RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
        _pedido(),
        atendido_despues=True,
    )
    assert motivo is not None
    assert "lista posterior" in motivo


def test_con_piezas_none_solo_pregunta_si_se_podria_ofrecer_en_general():
    """Es la pregunta de la bandera de la pantalla: sin una cifra todavía, no
    se juzga "la cifra ya es ésa" ni "piezas <= 0", que necesitan una."""
    assert (
        motivo_para_no_corregir(
            _renglon(RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
            _pedido(),
            atendido_despues=False,
            piezas=None,
        )
        is None
    )


def test_piezas_cero_o_negativas_no_corrigen():
    for piezas in (0, -1):
        motivo = motivo_para_no_corregir(
            _renglon(RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
            _pedido(),
            atendido_despues=False,
            piezas=piezas,
        )
        assert motivo is not None
        assert "cero" in motivo


def test_la_misma_cifra_no_mueve_la_firma():
    motivo = motivo_para_no_corregir(
        _renglon(RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
        _pedido(),
        atendido_despues=False,
        piezas=6,
    )
    assert motivo is not None
    assert "ya es la que está guardada" in motivo


def test_se_puede_corregir_con_todo_en_regla():
    assert (
        motivo_para_no_corregir(
            _renglon(RENGLON_RECIBIDO_PARCIAL, piezas_recibidas=6),
            _pedido(),
            atendido_despues=False,
            piezas=10,
        )
        is None
    )
    # También lo completo, corrigiendo hacia otra cifra completa.
    assert (
        motivo_para_no_corregir(
            _renglon(RENGLON_RECIBIDO, piezas_recibidas=10),
            _pedido(),
            atendido_despues=False,
            piezas=12,
        )
        is None
    )


# ==========================================================================
# motivo_para_no_recibir_a_mano
# ==========================================================================


def test_sin_renglon_no_hay_que_recibir():
    motivo = motivo_para_no_recibir_a_mano(None, None)
    assert "no hay un renglón" in motivo


def test_ya_recibido_no_es_este_motivo():
    """Quien llama debería haber usado `motivo_para_no_corregir`; aun así no
    truena, dice algo razonable (regla 4)."""
    motivo = motivo_para_no_recibir_a_mano(
        _renglon(RENGLON_RECIBIDO, piezas_recibidas=10), _pedido()
    )
    assert "recibido" in motivo


def test_no_viene_en_camino_no_se_recibe_a_mano():
    for estado in (RENGLON_ABIERTO, RENGLON_DESCARTADO, RENGLON_CANCELADO):
        motivo = motivo_para_no_recibir_a_mano(_renglon(estado), _pedido())
        assert "no viene en camino" in motivo


def test_en_transito_sin_pedido_no_se_afirma_que_se_pueda():
    motivo = motivo_para_no_recibir_a_mano(_renglon(RENGLON_EN_TRANSITO), None)
    assert "enviado" in motivo


def test_en_transito_con_pedido_no_enviado_no_se_recibe():
    motivo = motivo_para_no_recibir_a_mano(_renglon(RENGLON_EN_TRANSITO), _pedido(CANCELADO))
    assert "enviado" in motivo


# ==========================================================================
# motivo_para_no_editar (nueva, 2026-09-22, paso 2)
# ==========================================================================


def _lista_guardada(
    estado: str = ABIERTO, *, renglones: tuple[RenglonGuardado, ...] = ()
) -> PedidoSugeridoGuardado:
    return PedidoSugeridoGuardado(
        pedido_sugerido_id=1,
        negocio=NEGOCIO,
        fecha_del_pedido=JUEVES,
        estado=estado,
        ventana=Ventana(desde=LUNES, hasta=JUEVES),
        armado_en=_local(JUEVES, 22),
        cerrado_en=_local(JUEVES, 23) if estado == CERRADO else None,
        renglones=renglones,
    )


def test_las_tres_acciones_de_edicion_exigen_el_renglon_abierto():
    """El mismo `WHERE`, letra por letra, en `_DESCARTAR`,
    `_AJUSTAR_LA_CANTIDAD` y `_ELEGIR_PROVEEDOR`."""
    assert ACCIONES_QUE_EXIGEN_RENGLON_ABIERTO == (
        "descartar",
        "ajustar_la_cantidad",
        "elegir_proveedor",
    )
    for accion in ACCIONES_QUE_EXIGEN_RENGLON_ABIERTO:
        for estado in (
            RENGLON_EN_TRANSITO,
            RENGLON_CANCELADO,
            RENGLON_RECIBIDO,
            RENGLON_RECIBIDO_PARCIAL,
            RENGLON_DESCARTADO,
        ):
            motivo = motivo_para_no_editar(_renglon(estado), _lista_guardada(), accion)
            assert motivo is not None, (accion, estado)
        # Abierto, con la lista abierta: sí se puede.
        assert (
            motivo_para_no_editar(_renglon(RENGLON_ABIERTO), _lista_guardada(), accion)
            is None
        )


def test_descartar_en_transito_dice_que_ya_se_le_pidio_a_un_proveedor():
    motivo = motivo_para_no_editar(
        _renglon(RENGLON_EN_TRANSITO), _lista_guardada(), "descartar"
    )
    assert "ya se le pidió a un proveedor" in motivo


def test_ajustar_cancelado_dice_que_se_dejo_de_esperar():
    motivo = motivo_para_no_editar(
        _renglon(RENGLON_CANCELADO), _lista_guardada(), "ajustar_la_cantidad"
    )
    assert "se dejó de esperar" in motivo


def test_elegir_proveedor_recibido_dice_que_ya_llego():
    for estado in (RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL):
        motivo = motivo_para_no_editar(
            _renglon(estado), _lista_guardada(), "elegir_proveedor"
        )
        assert "ya llegó" in motivo


def test_descartar_ya_descartado_manda_a_devolverlo_primero():
    motivo = motivo_para_no_editar(
        _renglon(RENGLON_DESCARTADO), _lista_guardada(), "descartar"
    )
    assert "primero hay que devolverlo" in motivo


def test_devolver_a_abierto_exige_lo_contrario_el_renglon_descartado():
    """`_DEVOLVER_A_ABIERTO` es la única de las cuatro que exige lo opuesto:
    el renglón `descartado`, no `abierto`."""
    assert DEVOLVER_A_ABIERTO == "devolver_a_abierto"
    for estado in (
        RENGLON_ABIERTO,
        RENGLON_EN_TRANSITO,
        RENGLON_CANCELADO,
        RENGLON_RECIBIDO,
        RENGLON_RECIBIDO_PARCIAL,
    ):
        motivo = motivo_para_no_editar(_renglon(estado), _lista_guardada(), DEVOLVER_A_ABIERTO)
        assert motivo is not None, estado
    assert (
        motivo_para_no_editar(
            _renglon(RENGLON_DESCARTADO), _lista_guardada(), DEVOLVER_A_ABIERTO
        )
        is None
    )


def test_las_cuatro_acciones_exigen_ademas_la_lista_abierta():
    """La condición unificada el 2026-09-20: sin ella, una lista cerrada
    seguiría dejándose modificar."""
    for accion in ACCIONES_DE_EDICION:
        estado_que_pasa = (
            RENGLON_DESCARTADO if accion == DEVOLVER_A_ABIERTO else RENGLON_ABIERTO
        )
        for estado_de_lista in (CERRADO, VENCIDO):
            motivo = motivo_para_no_editar(
                _renglon(estado_que_pasa), _lista_guardada(estado_de_lista), accion
            )
            assert motivo is not None, (accion, estado_de_lista)
            assert "lista ya no está abierta" in motivo


def test_sin_lista_no_se_afirma_que_se_pueda_editar():
    """`lista=None` bloquea igual que una lista que no está abierta: sin
    poder leerla, no se puede afirmar que sí lo esté — la misma convención
    que `motivo_para_no_corregir` usa con `pedido=None`."""
    for accion in ACCIONES_DE_EDICION:
        estado_que_pasa = (
            RENGLON_DESCARTADO if accion == DEVOLVER_A_ABIERTO else RENGLON_ABIERTO
        )
        motivo = motivo_para_no_editar(_renglon(estado_que_pasa), None, accion)
        assert motivo is not None


def test_una_accion_desconocida_truena_en_vez_de_decir_que_si():
    """Una cadena mal escrita no puede colar un `None` silencioso: revienta
    con un `ValueError` claro, no con un "sí se puede" por accidente."""
    try:
        motivo_para_no_editar(_renglon(RENGLON_ABIERTO), _lista_guardada(), "de_pantorrilla")
    except ValueError as exc:
        assert "de_pantorrilla" in str(exc)
    else:
        raise AssertionError("debió reventar con ValueError")
