"""`transiciones.py`: el motivo real de corregir lo recibido y de recibir a
mano, probado en cada rama (propuesta 1 de la revisión de arquitectura,
2026-09-21).

Puro y sin almacenamiento: cada prueba arma un `RenglonGuardado` y un
`PedidoGuardado` a mano y pregunta el motivo. La garantía —el `WHERE` de
`_CORREGIR_LO_RECIBIDO` y `_RECIBIR_A_MANO`— la cubren `test_parcial.py` y
`test_guardado.py`; esto solo cubre que la copia legible diga lo mismo que
esas sentencias, rama por rama.
"""

from __future__ import annotations

import datetime as dt

from continental.almacenamiento import (
    BORRADOR,
    CANCELADO,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_CANCELADO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    PedidoGuardado,
    Renglon,
    RenglonGuardado,
)
from continental.transiciones import (
    motivo_para_no_corregir,
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
        estado=estado,
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
