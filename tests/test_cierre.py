"""Cerrar avisa lo que se pierde, y reabrir deshace el cierre (ADR 0016).

**Lo que arregla.** La revisión de código de los tickets 24 y 27 encontró que
cerrar una lista con un renglón `abierto` o `descartado` que traía **lo que
faltó de un parcial** o **lo vendido mientras un pedido viajaba** lo da por
atendido para siempre: `_LO_YA_PEDIDO` ve una lista posterior cerrada con el
producto y no lo vuelve a traer. Es la segunda y última oportunidad de esas
piezas, y se iba sin que nada lo dijera.

**Las dos decisiones del dueño, fijadas aquí:**

1. **Una confirmación antes de cerrar**, que enseña qué se da por atendido sin
   haberse pedido —con sus piezas— y, si no hay nada de eso, lo normal: cuántos
   renglones quedan sin pedir. El cálculo y las frases son de Python
   (`continental.cierre`); la pantalla solo los pinta en un `<dialog>`. Avisa,
   no prohíbe.
2. **Reabrir deshace el cierre solo mientras ninguna lista se haya armado
   después**: es la única condición en que nadie usó el corte que el cierre
   escribió. La regla vive en el `WHERE` (`_NINGUNA_LISTA_DESPUES`), no en un
   `if`: dos pestañas, o una pestaña y el lote.

Los tres seams del repo: lo puro, lo que se guarda (el doble, los CHECK en
Python, el SQL como texto, la migración) y lo que se ve (las rutas de punta a
punta con varios días escritos con sus números, y la pantalla). **Ninguna prueba
toca Postgres ni duerme, y ningún dato es real.**
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental import cierre
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    ABIERTO,
    CERRADO,
    RENGLON_CANCELADO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    VENCIDO,
    AlmacenamientoDelPedido,
    PedidoSugeridoGuardado,
    RenglonGuardado,
    Ventana,
    revisar_la_lista,
)
from continental.dobles import AlmacenamientoFalso
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0012-reabrir-la-lista-cerrada.sql"
CONTEXTO = RAIZ / "CONTEXT.md"

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


def _local(fecha: dt.date, hora: int = 10, minuto: int = 0) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=CENTRO)


# ==========================================================================
# LO PURO — qué se perdería al cerrar, y cómo se dice
# ==========================================================================


def _renglon(
    renglon_id: int,
    estado: str = ABIERTO,
    *,
    cantidad: int = 5,
    cantidad_final: int | None = None,
    piezas_que_faltaron: int = 0,
    ventas_desde: dt.date | None = None,
    pedido_id: int | None = None,
    descripcion: str | None = None,
) -> RenglonGuardado:
    descartado = estado == RENGLON_DESCARTADO
    recibido = estado in (RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL)
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=renglon_id,
            clave=f"750100000{renglon_id:04d}",
            descripcion=descripcion or f"PRODUCTO {renglon_id}",
            piezas_vendidas=float(cantidad - piezas_que_faltaron),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
            ventas_desde=ventas_desde,
            piezas_que_faltaron=piezas_que_faltaron,
        ),
        descartado_por=CORREO if descartado else None,
        descartado_en=_local(JUEVES, 9) if descartado else None,
        cantidad_final=cantidad_final,
        ajustada_por=CORREO if cantidad_final is not None else None,
        ajustada_en=_local(JUEVES, 9) if cantidad_final is not None else None,
        pedido_id=pedido_id,
        recibido_por=CORREO if recibido else None,
        recibido_en=_local(JUEVES, 11) if recibido else None,
        piezas_recibidas=float(cantidad) if recibido else None,
    )


def _lista(
    *renglones: RenglonGuardado,
    estado: str = ABIERTO,
    desde: dt.date = JUEVES,
    hasta: dt.date = JUEVES,
    reabierto_por: str | None = None,
    reabierto_en: dt.datetime | None = None,
) -> PedidoSugeridoGuardado:
    return PedidoSugeridoGuardado(
        pedido_sugerido_id=4,
        negocio=NEGOCIO,
        fecha_del_pedido=hasta,
        estado=estado,
        ventana=Ventana(desde=desde, hasta=hasta),
        armado_en=_local(hasta, 22),
        cerrado_en=_local(hasta, 23) if estado == CERRADO else None,
        renglones=renglones,
        reabierto_por=reabierto_por,
        reabierto_en=reabierto_en,
    )


def test_lo_que_faltaron_de_un_parcial_se_perderia_si_sigue_abierto():
    lista = _lista(_renglon(1, piezas_que_faltaron=4, cantidad=10), _renglon(2))

    assert [r.renglon_id for r in cierre.lo_que_se_perderia(lista)] == [1]


def test_lo_vendido_mientras_venia_se_perderia_si_sigue_abierto():
    """`ventas_desde` anterior a la ventana: son ventas de otros días, que solo
    esta lista trae (ADR 0012)."""
    lista = _lista(_renglon(1, ventas_desde=MARTES), _renglon(2))

    assert [r.renglon_id for r in cierre.lo_que_se_perderia(lista)] == [1]


def test_lo_descartado_tambien_se_perderia():
    """Descartado es "una persona decidió no pedirlo", y puede ser a
    propósito. Se enseña igual: cerrar es lo que lo vuelve definitivo."""
    lista = _lista(_renglon(1, RENGLON_DESCARTADO, piezas_que_faltaron=2))

    assert [r.renglon_id for r in cierre.lo_que_se_perderia(lista)] == [1]


@pytest.mark.parametrize(
    "estado", [RENGLON_EN_TRANSITO, RENGLON_RECIBIDO, RENGLON_CANCELADO]
)
def test_lo_que_ya_se_pidio_no_se_pierde(estado):
    """Lo que se envió está pedido; lo cancelado vuelve por su cuenta (ADR
    0013). Ninguno se da por atendido sin haberse pedido."""
    renglon = _renglon(1, estado, piezas_que_faltaron=4, cantidad=10, pedido_id=7)
    if estado == RENGLON_CANCELADO:
        renglon = RenglonGuardado(
            **{**_campos(renglon), "cancelado_por": CORREO, "cancelado_en": _local(JUEVES)}
        )

    assert cierre.lo_que_se_perderia(_lista(renglon)) == ()


def _campos(renglon: RenglonGuardado) -> dict:
    return {nombre: getattr(renglon, nombre) for nombre in RenglonGuardado.__slots__}


def test_una_ventana_propia_que_empieza_despues_no_trae_nada_de_otro_dia():
    """"Solo cuenta desde el viernes": lo anterior ya venía en un pedido. Ahí
    no hay nada retenido que perder."""
    lista = _lista(_renglon(1, ventas_desde=VIERNES), desde=JUEVES, hasta=SABADO)

    assert cierre.lo_que_se_perderia(lista) == ()


def test_un_renglon_de_la_ventana_normal_no_es_una_perdida_especial():
    """Lo de la propia ventana sin pedir es la decisión de siempre: se cuenta,
    no se lista."""
    lista = _lista(_renglon(1), _renglon(2))

    assert cierre.lo_que_se_perderia(lista) == ()
    assert cierre.al_cerrar(lista)["sin_pedir"] == 2


def test_la_frase_de_lo_que_se_perderia_dice_piezas_y_por_que():
    renglon = _renglon(
        1, cantidad=10, piezas_que_faltaron=4, ventas_desde=MARTES,
        descripcion="PARACETAMOL 500 MG",
    )
    frase = cierre.frase_de_lo_que_se_perderia(renglon, Ventana(JUEVES, JUEVES))

    assert frase.startswith("PARACETAMOL 500 MG: 10 piezas sin pedir.")
    assert "4 piezas que faltaron en un pedido anterior" in frase
    assert "lo vendido desde el martes 15 de septiembre" in frase
    assert "ninguna lista vuelve a traer" in frase


def test_la_frase_usa_la_cantidad_corregida_y_el_singular():
    renglon = _renglon(1, cantidad=5, cantidad_final=1, piezas_que_faltaron=1)
    frase = cierre.frase_de_lo_que_se_perderia(renglon, Ventana(JUEVES, JUEVES))

    assert ": 1 pieza sin pedir." in frase
    assert "1 pieza que faltó en un pedido anterior" in frase


def test_la_frase_de_un_descartado_lo_dice():
    renglon = _renglon(1, RENGLON_DESCARTADO, cantidad=3, ventas_desde=MARTES)
    frase = cierre.frase_de_lo_que_se_perderia(renglon, Ventana(JUEVES, JUEVES))

    assert "descartado (eran 3 piezas)" in frase
    assert "faltaron" not in frase


def test_al_cerrar_con_algo_que_se_perderia():
    """**El ejemplo del reporte**, con su texto entero."""
    lista = _lista(
        _renglon(1, cantidad=10, piezas_que_faltaron=4, ventas_desde=MARTES,
                 descripcion="PARACETAMOL 500 MG"),
        _renglon(2, descripcion="IBUPROFENO 400 MG"),
        _renglon(3, RENGLON_DESCARTADO),
        _renglon(4, RENGLON_EN_TRANSITO, pedido_id=7),
    )
    resumen = cierre.al_cerrar(lista)

    assert resumen["ok"] is True
    assert resumen["se_puede_cerrar"] is True
    assert resumen["sin_pedir"] == 2
    assert resumen["titulo"] == "¿Cerrar la lista?"
    assert resumen["frase"] == (
        "Quedan 2 renglones sin pedir: al cerrarla se dan por atendidos y la "
        "siguiente lista no los vuelve a proponer. La siguiente arranca con las "
        "ventas del viernes 18 de septiembre. No se borra nada."
    )
    assert resumen["aviso"] == (
        "1 renglón trae algo de un pedido anterior que se perdería al cerrar:"
    )
    [perdida] = resumen["se_perderian"]
    assert perdida["renglon_id"] == 1
    assert perdida["piezas"] == 10
    assert perdida["piezas_que_faltaron"] == 4
    assert perdida["ventas_desde"] == MARTES.isoformat()
    assert perdida["frase"] == (
        "PARACETAMOL 500 MG: 10 piezas sin pedir. Trae 4 piezas que faltaron en "
        "un pedido anterior y lo vendido desde el martes 15 de septiembre "
        "mientras venía en camino: si se cierra así, ninguna lista vuelve a "
        "traerlas."
    )
    assert "pídelo antes de cerrar" in resumen["que_hacer_con_lo_que_se_perderia"]
    assert resumen["boton"] == "Cerrar de todos modos"
    assert resumen["volver"] == "Volver a la lista"
    assert "reabrir" in resumen["deshacer"]
    assert "lista siguiente" in resumen["deshacer"]


def test_al_cerrar_sin_nada_que_se_pierda_dice_lo_normal():
    resumen = cierre.al_cerrar(_lista(_renglon(1)))

    assert resumen["se_perderian"] == []
    assert resumen["aviso"] is None
    assert resumen["que_hacer_con_lo_que_se_perderia"] is None
    assert resumen["frase"].startswith("Queda 1 renglón sin pedir: al cerrarla se da")
    assert resumen["boton"] == "Cerrar la lista"


def test_al_cerrar_con_todo_atendido_lo_dice():
    lista = _lista(_renglon(1, RENGLON_EN_TRANSITO, pedido_id=7), _renglon(2, RENGLON_DESCARTADO))
    resumen = cierre.al_cerrar(lista)

    assert resumen["sin_pedir"] == 0
    assert resumen["frase"].startswith("Todo lo de esta lista ya se pidió o se descartó.")


def test_al_cerrar_una_lista_vacia_no_dice_que_quedo_algo():
    assert cierre.al_cerrar(_lista())["frase"].startswith("Todo lo de esta lista")


def test_al_cerrar_cuenta_lo_que_esta_en_un_borrador_sin_enviar():
    """Un renglón `abierto` con pedido es de un **borrador**: enviar lo pondría
    en tránsito y cancelar en cancelado. Cerrar con borradores sin enviar es
    un olvido frecuente y se dice aparte."""
    lista = _lista(_renglon(1, pedido_id=7), _renglon(2, pedido_id=7), _renglon(3))
    resumen = cierre.al_cerrar(lista)

    assert resumen["en_borrador"] == 2
    assert "2 de ellos están en un pedido en borrador" in resumen["frase"]


def test_al_cerrar_varios_que_se_perderian_en_plural():
    lista = _lista(_renglon(1, piezas_que_faltaron=2), _renglon(2, ventas_desde=LUNES))

    assert cierre.al_cerrar(lista)["aviso"].startswith("2 renglones traen algo")


def test_al_cerrar_una_lista_que_ya_no_esta_abierta_no_ofrece_cerrar():
    """Otra pestaña la cerró, o se venció. El resumen lo dice y no trae botón."""
    resumen = cierre.al_cerrar(_lista(_renglon(1), estado=CERRADO))

    assert resumen["se_puede_cerrar"] is False
    assert resumen["boton"] is None
    assert "ya no está abierta" in resumen["frase"]


# ------------------------------------------------------------ la reapertura


def test_la_reapertura_de_una_cerrada_que_se_puede_trae_su_boton():
    reapertura = cierre.reapertura(_lista(estado=CERRADO), se_puede=True)

    assert reapertura["se_puede"] is True
    assert reapertura["boton"] == "Reabrir la lista"
    assert "hasta que se arme la lista siguiente" in reapertura["frase"]
    assert "no deshace" in reapertura["frase"]


def test_la_reapertura_que_ya_no_se_puede_no_trae_boton_y_dice_por_que():
    reapertura = cierre.reapertura(_lista(estado=CERRADO), se_puede=False)

    assert reapertura["se_puede"] is False
    assert reapertura["boton"] is None
    assert "ya se armó la lista siguiente" in reapertura["frase"]


def test_la_reapertura_vieja_dice_hace_mas_de_un_dia_y_no_una_siguiente_inventada():
    """Enmienda 2026-09-21 al ADR 0016: sin `ancla` no hay cómo distinguir el
    motivo y se cae en el texto de siempre; con `ancla`, si la lista es de
    hace más de un día esa es la razón, y no una lista siguiente que puede no
    existir."""
    lista = _lista(estado=CERRADO, desde=MARTES, hasta=MARTES)

    reapertura = cierre.reapertura(lista, se_puede=False, ancla=JUEVES)

    assert reapertura["se_puede"] is False
    assert reapertura["boton"] is None
    assert "hace más de un día" in reapertura["frase"]
    assert "lista siguiente" not in reapertura["frase"]


def test_la_reapertura_de_ayer_no_cae_en_hace_mas_de_un_dia():
    """El borde: `ancla - 1` sigue siendo reabrible por fecha, así que si de
    todos modos no se puede, la razón sigue siendo la de siempre."""
    lista = _lista(estado=CERRADO, desde=MIERCOLES, hasta=MIERCOLES)

    reapertura = cierre.reapertura(lista, se_puede=False, ancla=JUEVES)

    assert "ya se armó la lista siguiente" in reapertura["frase"]


@pytest.mark.parametrize("estado", [ABIERTO, VENCIDO])
def test_solo_una_cerrada_tiene_reapertura(estado):
    assert cierre.reapertura(_lista(estado=estado), se_puede=True) is None


def test_si_no_se_pudo_saber_no_hay_boton_y_se_dice_que_hacer():
    falla = {"detalle": "no se pudo saber (RuntimeError)", "que_hacer": "Vuelve a cargar."}
    reapertura = cierre.reapertura(_lista(estado=CERRADO), se_puede=None, falla=falla)

    assert reapertura["se_puede"] is False
    assert reapertura["boton"] is None
    assert reapertura["detalle"] == falla["detalle"]
    assert reapertura["que_hacer"] == "Vuelve a cargar."


def test_la_firma_de_la_reapertura_va_en_la_hora_de_la_farmacia():
    """Guardada en UTC, dicha en la hora del centro: 00:05 UTC del viernes es
    el jueves a las 18:05 en el mostrador."""
    instante = dt.datetime(2026, 9, 18, 0, 5, tzinfo=dt.UTC)

    assert cierre.frase_de_la_reapertura(DUENO, instante) == (
        f"Se reabrió el jueves 17 de septiembre a las 18:05; lo firmó {DUENO}."
    )
    assert cierre.frase_de_la_reapertura(None, None) is None


@pytest.mark.parametrize(
    "estado,pista",
    [
        (ABIERTO, "ya está abierta"),
        (VENCIDO, "vencida no se reabre"),
        (CERRADO, "ya se armó la lista siguiente"),
    ],
)
def test_el_motivo_para_no_reabrir_depende_de_como_quedo(estado, pista):
    """`ancla=JUEVES` con una lista del jueves: dentro de la ventana de un
    día, así que el `CERRADO` de aquí solo puede deberse a la siguiente."""
    assert pista in cierre.motivo_para_no_reabrir(_lista(estado=estado), JUEVES)


def test_el_motivo_sin_lista_dice_que_no_existe():
    assert "No hay una lista" in cierre.motivo_para_no_reabrir(None, JUEVES)


def test_el_motivo_para_no_reabrir_dice_hace_mas_de_un_dia_cuando_la_lista_es_vieja():
    """Enmienda 2026-09-21 al ADR 0016: el caso nuevo, distinto de "ya se
    armó la lista siguiente"."""
    vieja = _lista(estado=CERRADO, desde=LUNES, hasta=LUNES)

    motivo = cierre.motivo_para_no_reabrir(vieja, JUEVES)

    assert "hace más de un día" in motivo
    assert "lunes 14 de septiembre" in motivo
    assert "lista siguiente" not in motivo
    assert "Vuelve a cargar la página" in motivo


def test_el_motivo_para_no_reabrir_de_ayer_no_dice_hace_mas_de_un_dia():
    """El borde: `ancla - 1` día sigue en la ventana por fecha, así que si
    aun así no se pudo, la razón fue que ya se armó la siguiente."""
    ayer = _lista(estado=CERRADO, desde=MIERCOLES, hasta=MIERCOLES)

    motivo = cierre.motivo_para_no_reabrir(ayer, JUEVES)

    assert "ya se armó la lista siguiente" in motivo


# ==========================================================================
# LO QUE SE GUARDA — el doble, los CHECK, el SQL y la migración
# ==========================================================================


def _producto_renglon(producto_id: int, cantidad: int = 3) -> Renglon:
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


def _lista_guardada(almacenamiento, fecha: dt.date, negocio: str = NEGOCIO):
    return almacenamiento.insertar_la_lista(
        negocio, fecha, Ventana(fecha, fecha), [_producto_renglon(1)]
    )


def test_el_doble_sigue_cumpliendo_la_interfaz():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)


def test_reabrir_la_ultima_cerrada_la_deja_abierta_y_firmada(almacenamiento):
    lista = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id)

    assert almacenamiento.se_puede_reabrir(NEGOCIO, lista.pedido_sugerido_id, JUEVES) is True
    reabierta = almacenamiento.reabrir(NEGOCIO, lista.pedido_sugerido_id, DUENO, JUEVES)

    assert reabierta.estado == ABIERTO
    assert reabierta.cerrado_en is None, "ck_pedido_sugerido_cierre lo exige"
    assert reabierta.reabierto_por == DUENO
    assert reabierta.reabierto_en is not None
    assert reabierta.ventana == lista.ventana, "la ventana no se toca"


def test_con_una_lista_despues_ya_no_se_reabre(almacenamiento):
    jueves = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, jueves.pedido_sugerido_id)
    _lista_guardada(almacenamiento, VIERNES)

    assert (
        almacenamiento.se_puede_reabrir(NEGOCIO, jueves.pedido_sugerido_id, VIERNES)
        is False
    )
    assert almacenamiento.reabrir(NEGOCIO, jueves.pedido_sugerido_id, DUENO, VIERNES) is None
    assert almacenamiento.leer(NEGOCIO, JUEVES).estado == CERRADO


def test_una_lista_despues_de_otro_negocio_no_cuenta(almacenamiento):
    """Regla 7: el negocio va en la subconsulta también."""
    jueves = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, jueves.pedido_sugerido_id)
    _lista_guardada(almacenamiento, VIERNES, negocio="farmacia_02")

    assert (
        almacenamiento.reabrir(NEGOCIO, jueves.pedido_sugerido_id, DUENO, JUEVES)
        is not None
    )


@pytest.mark.parametrize("como_queda", ["abierta", "vencida"])
def test_solo_se_reabre_lo_cerrado(almacenamiento, como_queda):
    lista = _lista_guardada(almacenamiento, JUEVES)
    if como_queda == "vencida":
        almacenamiento.vencer_las_de_dias_anteriores(NEGOCIO, VIERNES)

    assert almacenamiento.se_puede_reabrir(NEGOCIO, lista.pedido_sugerido_id, JUEVES) is False
    assert almacenamiento.reabrir(NEGOCIO, lista.pedido_sugerido_id, DUENO, JUEVES) is None


def test_se_reabre_lo_del_dia_del_ancla(almacenamiento):
    """Enmienda 2026-09-21 al ADR 0016: el día del ancla siempre está dentro
    de la ventana de "hasta un día atrás"."""
    hoy = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, hoy.pedido_sugerido_id)

    assert almacenamiento.se_puede_reabrir(NEGOCIO, hoy.pedido_sugerido_id, JUEVES) is True


def test_se_reabre_lo_de_un_dia_antes_del_ancla():
    """El otro borde de "hasta un día atrás": una lista sin ninguna después
    —así que nadie armó la de hoy— sigue siendo de ayer contra el ancla, y se
    reabre igual. Un doble aparte: si compartiera la fixture con una lista de
    `JUEVES`, esa sería la "lista después" que la primera condición ya
    prohíbe, y no probaría el borde del día."""
    almacenamiento = AlmacenamientoFalso()
    ayer = _lista_guardada(almacenamiento, MIERCOLES)
    almacenamiento.cerrar(NEGOCIO, ayer.pedido_sugerido_id)

    assert almacenamiento.se_puede_reabrir(NEGOCIO, ayer.pedido_sugerido_id, JUEVES) is True
    assert almacenamiento.reabrir(NEGOCIO, ayer.pedido_sugerido_id, DUENO, JUEVES) is not None


def test_no_se_reabre_lo_de_hace_mas_de_un_dia(almacenamiento):
    """El hueco que encontró la revisión del dueño: sin una lista siguiente
    armada, una lista de hace varios días se quedaba reabrible para
    siempre. Desde la enmienda, ya no."""
    lista = _lista_guardada(almacenamiento, MARTES)
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id)

    assert almacenamiento.se_puede_reabrir(NEGOCIO, lista.pedido_sugerido_id, JUEVES) is False
    assert almacenamiento.reabrir(NEGOCIO, lista.pedido_sugerido_id, DUENO, JUEVES) is None
    assert almacenamiento.leer(NEGOCIO, MARTES).estado == CERRADO


def test_reabrir_mira_el_negocio_de_la_lista(almacenamiento):
    lista = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id)

    assert (
        almacenamiento.reabrir("farmacia_02", lista.pedido_sugerido_id, DUENO, JUEVES)
        is None
    )
    assert (
        almacenamiento.se_puede_reabrir("farmacia_02", lista.pedido_sugerido_id, JUEVES)
        is False
    )


def test_una_lista_que_no_existe_no_se_reabre(almacenamiento):
    assert almacenamiento.reabrir(NEGOCIO, 99, DUENO, JUEVES) is None
    assert almacenamiento.se_puede_reabrir(NEGOCIO, 99, JUEVES) is False


def test_reabrir_dos_veces_la_segunda_no_hace_nada(almacenamiento):
    """Dos pestañas: la segunda encuentra la lista abierta y el `WHERE` no la
    toca — la firma sigue siendo la de la primera."""
    lista = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id)
    almacenamiento.reabrir(NEGOCIO, lista.pedido_sugerido_id, DUENO, JUEVES)

    assert almacenamiento.reabrir(NEGOCIO, lista.pedido_sugerido_id, CORREO, JUEVES) is None
    assert almacenamiento.leer(NEGOCIO, JUEVES).reabierto_por == DUENO


def test_reabrir_hace_retroceder_el_corte_y_cerrar_lo_devuelve(almacenamiento):
    """Cerrar movió el corte; reabrir lo devuelve a la cerrada anterior, y
    volver a cerrar lo pone donde estaba. Nadie lo leyó en medio: no hay
    lista después."""
    miercoles = _lista_guardada(almacenamiento, MIERCOLES)
    almacenamiento.cerrar(NEGOCIO, miercoles.pedido_sugerido_id)
    jueves = _lista_guardada(almacenamiento, JUEVES)
    almacenamiento.cerrar(NEGOCIO, jueves.pedido_sugerido_id)
    assert almacenamiento.corte_del_ultimo_cerrado(NEGOCIO, VIERNES) == JUEVES

    almacenamiento.reabrir(NEGOCIO, jueves.pedido_sugerido_id, DUENO, JUEVES)
    assert almacenamiento.corte_del_ultimo_cerrado(NEGOCIO, VIERNES) == MIERCOLES

    cerrada = almacenamiento.cerrar(NEGOCIO, jueves.pedido_sugerido_id)
    assert almacenamiento.corte_del_ultimo_cerrado(NEGOCIO, VIERNES) == JUEVES
    assert cerrada.reabierto_por == DUENO, "la firma dice que hubo una reapertura"


def test_una_lista_recien_armada_nace_sin_reapertura(almacenamiento):
    lista = _lista_guardada(almacenamiento, JUEVES)

    assert lista.reabierto_por is None and lista.reabierto_en is None


# ------------------------------------------------------------ los CHECK


def _columnas(**cambios) -> dict:
    return {
        "negocio": NEGOCIO,
        "fecha_del_pedido": JUEVES,
        "estado": ABIERTO,
        "ventas_consideradas_desde": JUEVES,
        "ventas_consideradas_hasta": JUEVES,
        "cerrado_en": None,
        "reabierto_por": None,
        "reabierto_en": None,
        **cambios,
    }


def test_la_firma_de_la_reapertura_va_pareada():
    revisar_la_lista(_columnas(reabierto_por=DUENO, reabierto_en=_local(JUEVES)))
    with pytest.raises(ValueError, match="ck_pedido_sugerido_reapertura"):
        revisar_la_lista(_columnas(reabierto_por=DUENO))
    with pytest.raises(ValueError, match="ck_pedido_sugerido_reapertura"):
        revisar_la_lista(_columnas(reabierto_en=_local(JUEVES)))


def test_la_firma_de_la_reapertura_no_va_vacia():
    with pytest.raises(ValueError, match="ck_pedido_sugerido_reabierto_por"):
        revisar_la_lista(_columnas(reabierto_por="", reabierto_en=_local(JUEVES)))


def test_una_cerrada_puede_llevar_la_firma_de_una_reapertura_anterior():
    """El CHECK pareado no mira el estado: una lista reabierta y vuelta a
    cerrar la conserva, y el `_CERRAR` viejo de atlas no tiene que saber de
    ella."""
    revisar_la_lista(
        _columnas(
            estado=CERRADO, cerrado_en=_local(JUEVES, 19),
            reabierto_por=DUENO, reabierto_en=_local(JUEVES, 18),
        )
    )


# --------------------------------------------------------- el SQL como texto


def _sql(nombre: str) -> str:
    import continental.almacenamiento as modulo

    return re.sub(r"\s+", " ", getattr(modulo, nombre).text)


def test_la_regla_esta_escrita_una_sola_vez_y_la_usan_las_dos_sentencias():
    from continental.almacenamiento import _NINGUNA_LISTA_DESPUES

    regla = re.sub(r"\s+", " ", _NINGUNA_LISTA_DESPUES).strip()
    assert "not exists" in regla
    assert "despues.negocio = s.negocio" in regla, "regla 7: el negocio en la unión"
    assert "despues.fecha_del_pedido > s.fecha_del_pedido" in regla
    for nombre in ("_REABRIR", "_SE_PUEDE_REABRIR"):
        assert regla in _sql(nombre), nombre


def test_la_regla_del_dia_tambien_esta_escrita_una_sola_vez():
    """Enmienda 2026-09-21 al ADR 0016: `_HASTA_UN_DIA_ATRAS`, el mismo texto
    en las dos sentencias que ya comparten `_NINGUNA_LISTA_DESPUES`."""
    from continental.almacenamiento import _HASTA_UN_DIA_ATRAS

    regla = re.sub(r"\s+", " ", _HASTA_UN_DIA_ATRAS).strip()
    assert "s.fecha_del_pedido >= :ultimo_dia_con_ventas - 1" in regla
    for nombre in ("_REABRIR", "_SE_PUEDE_REABRIR"):
        assert regla in _sql(nombre), nombre


def test_reabrir_lleva_la_transicion_en_el_where():
    sentencia = _sql("_REABRIR")

    assert sentencia.lstrip().startswith("update pedidos.pedido_sugerido as s")
    assert "s.estado = 'cerrado'" in sentencia
    assert "s.negocio = :negocio" in sentencia
    assert "s.pedido_sugerido_id = :pedido_sugerido_id" in sentencia
    assert "estado = 'abierto'" in sentencia
    assert "cerrado_en = null" in sentencia
    assert "reabierto_por = :quien" in sentencia
    assert "reabierto_en = now()" in sentencia
    assert "returning" in sentencia and "reabierto_por, s.reabierto_en" in sentencia


def test_se_puede_reabrir_mira_lo_mismo_que_el_where():
    sentencia = _sql("_SE_PUEDE_REABRIR")

    assert sentencia.lstrip().startswith("select exists")
    assert "s.estado = 'cerrado'" in sentencia
    assert "s.negocio = :negocio" in sentencia


@pytest.mark.parametrize(
    "nombre", ["_LEER_LISTA", "_LEER_LISTA_POR_ID", "_INSERTAR_LISTA", "_CERRAR"]
)
def test_las_lecturas_de_la_lista_traen_la_firma_de_la_reapertura(nombre):
    assert "reabierto_por, reabierto_en" in _sql(nombre).replace("s.", "")


# ---------------------------------------------------------- la migración 0012


def _texto(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def _sentencias_sql(ruta: Path) -> str:
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def test_la_migracion_0012_agrega_dos_columnas_y_no_crea_tabla():
    sentencias = _sentencias_sql(MIGRACION)

    assert "CREATE TABLE" not in sentencias
    assert "GRANT" not in sentencias
    assert "ADD COLUMN IF NOT EXISTS reabierto_por text;" in sentencias
    assert "ADD COLUMN IF NOT EXISTS reabierto_en timestamptz;" in sentencias
    assert "current_user = 'continental'" in sentencias
    assert "SET client_encoding TO 'UTF8'" in sentencias
    assert "BEGIN;" in sentencias and "COMMIT;" in sentencias


def test_la_0012_no_rompe_el_codigo_viejo_de_atlas():
    """El código que hoy corre en atlas no nombra estas columnas: si fueran
    `NOT NULL` sin `DEFAULT`, su `INSERT` de la lista rebotaría. Y la 0012 no
    toca `ck_pedido_sugerido_estado` ni `ck_pedido_sugerido_cierre`, que el
    `_CERRAR` y el `_VENCER` viejos necesitan como están."""
    sentencias = _sentencias_sql(MIGRACION)

    assert "NOT NULL" not in sentencias.replace("IS NOT NULL", "")
    assert "DEFAULT" not in sentencias
    assert "ck_pedido_sugerido_estado" not in sentencias
    assert "ck_pedido_sugerido_cierre" not in sentencias
    assert "pedidos.renglon" not in sentencias


def test_los_check_nuevos_estan_en_los_dos_archivos():
    for ruta in (CREAR_TABLAS, MIGRACION):
        sentencias = _sentencias_sql(ruta)
        assert "CONSTRAINT ck_pedido_sugerido_reabierto_por" in sentencias, ruta.name
        assert "CHECK (reabierto_por <> '')" in sentencias, ruta.name
        assert "CONSTRAINT ck_pedido_sugerido_reapertura" in sentencias, ruta.name
        assert "CHECK ((reabierto_por IS NULL) = (reabierto_en IS NULL))" in sentencias, ruta.name


def test_crear_tablas_trae_las_dos_columnas_y_nombra_la_0012():
    sentencias = _sentencias_sql(CREAR_TABLAS)
    assert re.search(r"\n\s+reabierto_por\s+text,", sentencias)
    assert re.search(r"\n\s+reabierto_en\s+timestamptz,", sentencias)
    assert "0012-reabrir-la-lista-cerrada.sql" in _texto(CREAR_TABLAS)


def test_verificar_rol_mira_la_reapertura():
    texto = _texto(VERIFICAR_ROL)
    assert "(38," in texto
    assert "ck_pedido_sugerido_reapertura" in texto


def test_el_glosario_tiene_la_transicion_de_cerrado_a_abierto():
    texto = _texto(CONTEXTO)
    assert "`cerrado` → `abierto`" in texto
    assert "reabr" in texto


# ==========================================================================
# LO QUE SE VE — las rutas de punta a punta, varios días, y la pantalla
# ==========================================================================

RUTA = "/api/pedido-sugerido"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha, producto_id=producto_id, cantidad=cantidad,
        importe=cantidad * 10.0, costo=cantidad * 6.0, utilidad=cantidad * 4.0,
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


def _lectura() -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor="nadro", precio_como_llego="12.50", precio=Decimal("12.50"),
        existencia_como_llego="40", existencia=Decimal("40"), motivo=None,
    )


def _abrir(cliente) -> dict:
    cuerpo = cliente.get(RUTA).json()
    assert cuerpo["ok"] is True, cuerpo
    return cuerpo


def _por_producto(lista: dict) -> dict[int, dict]:
    return {r["producto_id"]: r for r in lista["renglones"]}


def _enviar(cliente, almacenamiento, lista: dict, productos: set[int]) -> None:
    """Precio de NADRO a esos productos, descarta el resto, parte y envía."""
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


def _cerrar(cliente, lista: dict) -> dict:
    respuesta = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")
    assert respuesta.status_code == 200, respuesta.json()
    return respuesta.json()


def _reabrir(cliente, lista: dict, quien: str | None = DUENO):
    cabeceras = {} if quien is None else {"Cf-Access-Authenticated-User-Email": quien}
    return cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/reabrir", headers=cabeceras)


def _al_cerrar(cliente, lista: dict):
    return cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/al-cerrar")


def _a_mano(cliente, renglon_id: int, piezas: int) -> None:
    respuesta = cliente.post(
        f"/api/renglon/{renglon_id}/recepcion/a-mano", json={"piezas": piezas}, headers=FIRMA
    )
    assert respuesta.status_code == 200, respuesta.json()


def _hasta_el_jueves_con_10_sin_pedir(cliente, almacen, almacenamiento) -> dict:
    """Lunes 10 pedidas; martes 3 y miércoles 2 (en camino, las listas se
    cierran); el jueves llegan 6 —faltan 4— y se vende 1. Devuelve la lista del
    jueves, que trae 3 + 2 + 1 + 4 = 10 del producto 1."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 10)]
    lunes = _abrir(cliente)
    renglon_del_lunes = _por_producto(lunes)[1]["renglon_id"]
    _enviar(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    for dia, cuantas in ((MARTES, 3), (MIERCOLES, 2)):
        almacen.ventas_en_memoria += [_venta(dia, 1, cuantas), _venta(dia, 2, 1)]
        lista = _abrir(cliente)
        assert sorted(_por_producto(lista)) == [2], "viene en camino: no se propone"
        _cerrar(cliente, lista)

    _a_mano(cliente, renglon_del_lunes, 6)
    almacen.ventas_en_memoria += [_venta(JUEVES, 1, 1)]
    jueves = _abrir(cliente)
    uno = _por_producto(jueves)[1]
    assert uno["cantidad_propuesta"] == 3 + 2 + 1 + 4
    assert uno["piezas_que_faltaron"] == 4
    assert uno["ventas_desde"] == MARTES.isoformat()
    return jueves


def test_escenario_se_cierra_por_error_se_reabre_a_tiempo_y_nada_se_pierde(
    cliente, almacen, almacenamiento
):
    """**Cerrar por error y reabrir a tiempo**, con los números escritos.

    - Lunes: se venden **10** del producto 1; se piden 10.
    - Martes **3**, miércoles **2**: viene en camino, no se propone; las dos
      listas se cierran.
    - Jueves: llegan **6** (faltan **4**) y se vende **1**. La lista del
      jueves trae 3 + 2 + 1 = 6 vendidas mientras venía + 4 = **10**.
    - La confirmación lo enseña: 10 piezas sin pedir, 4 que faltaron, lo
      vendido desde el martes. **Se cierra igual.**
    - Nadie ha armado nada después: **se reabre**, se piden las 10, se cierra.
    - Viernes: llegan las 10 y se vende **1**. La del viernes propone **1**.

    Vendidas 10 + 3 + 2 + 1 + 1 = **17**; repuesto 6 + 10 + 1 = **17**.
    """
    jueves = _hasta_el_jueves_con_10_sin_pedir(cliente, almacen, almacenamiento)

    resumen = _al_cerrar(cliente, jueves).json()
    assert resumen["ok"] is True, resumen
    [perdida] = resumen["se_perderian"]
    assert perdida["piezas"] == 10
    assert perdida["piezas_que_faltaron"] == 4
    assert "lo vendido desde el martes 15 de septiembre" in perdida["frase"]
    assert resumen["boton"] == "Cerrar de todos modos"

    cerrada = _cerrar(cliente, jueves)
    assert cerrada["reapertura"]["se_puede"] is True
    assert _abrir(cliente)["reapertura"]["se_puede"] is True, "recargar dice lo mismo"

    respuesta = _reabrir(cliente, jueves)
    assert respuesta.status_code == 200, respuesta.json()
    reabierta = respuesta.json()
    assert reabierta["estado"] == "abierto"
    assert reabierta["reabierto_por"] == DUENO
    assert DUENO in reabierta["frase_de_la_reapertura"]
    assert reabierta["reapertura"] is None, "abierta: se cierra, no se reabre"

    jueves = _abrir(cliente)
    assert jueves["estado"] == "abierto"
    _enviar(cliente, almacenamiento, jueves, {1})
    _cerrar(cliente, jueves)

    _a_mano(cliente, _por_producto(jueves)[1]["renglon_id"], 10)
    almacen.ventas_en_memoria += [_venta(VIERNES, 1, 1)]
    viernes = _abrir(cliente)
    uno = _por_producto(viernes)[1]
    assert uno["cantidad_propuesta"] == 1, "Lo del jueves se propuso dos veces."
    assert uno["piezas_que_faltaron"] == 0
    assert 6 + 10 + uno["cantidad_propuesta"] == 10 + 3 + 2 + 1 + 1


def test_escenario_ya_se_armo_la_siguiente_y_reabrir_contesta_409(
    cliente, almacen, almacenamiento
):
    """**Demasiado tarde.** Jueves cerrado con las 10 sin pedir; el viernes se
    vende 1 y se arma la lista del viernes, que empieza donde terminó la del
    jueves y trae **1**. Reabrir la del jueves contesta 409 y la deja cerrada:
    dos listas abiertas con ventanas que se tocan, y la vieja vencida al primer
    clic. Las 10 se perdieron, que es lo que la confirmación avisó."""
    jueves = _hasta_el_jueves_con_10_sin_pedir(cliente, almacen, almacenamiento)
    _cerrar(cliente, jueves)

    almacen.ventas_en_memoria += [_venta(VIERNES, 1, 1)]
    viernes = _abrir(cliente)
    assert _por_producto(viernes)[1]["cantidad_propuesta"] == 1

    respuesta = _reabrir(cliente, jueves)
    cuerpo = respuesta.json()
    assert respuesta.status_code == 409
    assert cuerpo["ok"] is False
    assert "ya se armó la lista siguiente" in cuerpo["detalle"]
    assert almacenamiento.leer(NEGOCIO, JUEVES).estado == CERRADO
    assert almacenamiento.leer(NEGOCIO, VIERNES).estado == ABIERTO


def test_escenario_la_cadena_trajo_ventas_y_nadie_abrio_el_dia(
    cliente, almacen, almacenamiento
):
    """**El borde**: jueves cerrado por error; a las 20:30 entra la venta del
    viernes (**1**) pero nadie abrió la pantalla ni corrió el lote. La del
    jueves sigue siendo la última lista: **se reabre** (una pestaña que se quedó
    abierta). La siguiente carga la vence —su día pasó— y arma la del viernes
    desde el corte del miércoles: el producto 1 vuelve con 3 + 2 + 1 + 1 = 7
    vendidas + 4 que faltaron = **11** = las 10 del jueves + 1 del viernes.
    Ninguna perdida y ninguna dos veces: es lo que pasa con cualquier lista que
    nadie cerró (ticket 09)."""
    jueves = _hasta_el_jueves_con_10_sin_pedir(cliente, almacen, almacenamiento)
    _cerrar(cliente, jueves)
    almacen.ventas_en_memoria += [_venta(VIERNES, 1, 1)]

    assert _reabrir(cliente, jueves).status_code == 200

    viernes = _abrir(cliente)
    assert almacenamiento.leer(NEGOCIO, JUEVES).estado == VENCIDO
    uno = _por_producto(viernes)[1]
    assert uno["piezas_vendidas"] == 3 + 2 + 1 + 1
    assert uno["piezas_que_faltaron"] == 4
    assert uno["cantidad_propuesta"] == 11
    _cerrar(cliente, viernes)

    almacen.ventas_en_memoria += [_venta(SABADO, 1, 1)]
    sabado = _abrir(cliente)
    assert _por_producto(sabado)[1]["cantidad_propuesta"] == 1, "Se propuso dos veces."


def test_escenario_lo_de_hace_mas_de_un_dia_ya_no_se_reabre(
    cliente, almacen, almacenamiento
):
    """**La enmienda 2026-09-21 al ADR 0016.** El hueco que encontró la
    revisión del dueño: desde una pestaña vieja se podía reabrir una lista de
    hace varios días con tal de que nadie hubiera armado otra encima —una
    farmacia floja de movimiento puede pasar así varios días—. Lunes se cierra
    y nadie vuelve a abrir la pantalla ni corre el lote martes, miércoles ni
    jueves: solo llegan ventas. Para el jueves, el lunes ya es "de hace más de
    un día" —y sigue siendo, también, la última lista: nadie armó ninguna
    después—. Reabrirlo contesta 409 con la razón nueva, no con "ya se armó la
    lista siguiente", que aquí sería mentira: no existe ninguna."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [
        _venta(MARTES, 1, 1), _venta(MIERCOLES, 1, 1), _venta(JUEVES, 1, 1)
    ]

    respuesta = _reabrir(cliente, lunes)
    cuerpo = respuesta.json()

    assert respuesta.status_code == 409
    assert cuerpo["ok"] is False
    assert "hace más de un día" in cuerpo["detalle"]
    assert "lista siguiente" not in cuerpo["detalle"]
    assert almacenamiento.leer(NEGOCIO, LUNES).estado == CERRADO


def test_escenario_lo_de_ayer_si_se_reabre_aunque_ya_no_sea_el_ancla(
    cliente, almacen, almacenamiento
):
    """El borde bueno: lunes cerrado, y para el martes —un solo día después,
    sin que nadie abriera la pantalla ni corriera el lote— sigue siendo "hasta
    un día atrás". Se reabre."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _cerrar(cliente, lunes)

    almacen.ventas_en_memoria += [_venta(MARTES, 1, 1)]

    assert _reabrir(cliente, lunes).status_code == 200
    assert almacenamiento.leer(NEGOCIO, LUNES).estado == ABIERTO


def test_reabrir_no_deshace_lo_que_se_envio(cliente, almacen, almacenamiento):
    """Se envía un pedido, se cierra, se reabre: el pedido sigue `enviado` y su
    renglón sigue `en tránsito`. Lo capturado en un portal no se descaptura."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 2)]
    lunes = _abrir(cliente)
    _enviar(cliente, almacenamiento, lunes, {1})
    _cerrar(cliente, lunes)

    reabierta = _reabrir(cliente, lunes).json()

    estados = {r["producto_id"]: r["estado"] for r in reabierta["renglones"]}
    assert estados == {1: RENGLON_EN_TRANSITO, 2: RENGLON_DESCARTADO}
    assert [p["estado"] for p in almacenamiento.pedidos] == ["enviado"]
    # Lo descartado se puede devolver a la lista: vuelve a estar abierta.
    renglon_2 = _por_producto(reabierta)[2]["renglon_id"]
    devuelto = cliente.post(f"/api/renglon/{renglon_2}/devolver", headers=FIRMA)
    assert devuelto.json()["ok"] is True


def test_la_firma_es_firma_y_no_permiso(cliente, almacen, almacenamiento):
    """Sin el encabezado de Access se reabre igual y se firma "sin-identificar":
    la seguridad es Access, no esto (regla 3)."""
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    _cerrar(cliente, lunes)

    cuerpo = _reabrir(cliente, lunes, quien=None).json()

    assert cuerpo["ok"] is True
    assert cuerpo["reabierto_por"] == "sin-identificar"


@pytest.mark.parametrize("como_queda,pista", [("abierta", "ya está abierta"), ("vencida", "vencida")])
def test_reabrir_lo_que_no_esta_cerrado_contesta_409_con_su_motivo(
    cliente, almacen, almacenamiento, como_queda, pista
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    lunes = _abrir(cliente)
    if como_queda == "vencida":
        almacen.ventas_en_memoria += [_venta(MARTES, 1, 1)]
        _abrir(cliente)

    respuesta = _reabrir(cliente, lunes)

    assert respuesta.status_code == 409
    assert pista in respuesta.json()["detalle"]


def test_reabrir_una_lista_que_no_existe_contesta_409(cliente, almacen):
    """`ancla` se necesita para intentar `reabrir` aunque la lista no exista
    —el `WHERE` la compara con `fecha_del_pedido - 1` de todos modos—, así
    que el almacén necesita al menos una venta (regla del repo: nunca el
    reloj) para que la ruta llegue a preguntar por la lista."""
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 1)]

    respuesta = cliente.post(f"{RUTA}/99/reabrir", headers=FIRMA)

    assert respuesta.status_code == 409
    assert "No hay una lista" in respuesta.json()["detalle"]


def test_regla_5_reabrir_con_la_base_caida_no_lleva_el_error_al_navegador(
    cliente, almacen, almacenamiento
):
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 1)]
    almacenamiento.falla = RuntimeError("postgresql://usuario:secreto@atlas")
    cuerpo = cliente.post(f"{RUTA}/1/reabrir", headers=FIRMA).json()

    assert cuerpo["ok"] is False
    assert "secreto" not in str(cuerpo)
    assert cuerpo["detalle"] == "no se pudo reabrir la lista (RuntimeError)"
    assert cuerpo["que_hacer"]


def test_al_cerrar_de_una_lista_que_no_existe_contesta_404(cliente):
    respuesta = cliente.get(f"{RUTA}/99/al-cerrar")

    assert respuesta.status_code == 404
    assert respuesta.json()["ok"] is False


def test_al_cerrar_con_la_base_caida_dice_que_hacer_y_que_se_puede_cerrar_igual(
    cliente, almacenamiento
):
    almacenamiento.falla = RuntimeError("postgresql://usuario:secreto@atlas")
    cuerpo = cliente.get(f"{RUTA}/1/al-cerrar").json()

    assert cuerpo["ok"] is False
    assert "secreto" not in str(cuerpo)
    assert cuerpo["que_hacer"]
    assert "se puede cerrar igual" in cuerpo["frase"]


def test_al_cerrar_lee_la_lista_en_el_momento_del_clic(cliente, almacen):
    """Descartar sustituye un renglón en la pantalla sin reenviar la lista:
    el resumen se lee al apretar, no se arrastra desde la carga."""
    almacen.catalogo_en_memoria = [_producto(1), _producto(2)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3), _venta(LUNES, 2, 2)]
    lunes = _abrir(cliente)
    assert _al_cerrar(cliente, lunes).json()["sin_pedir"] == 2

    renglon = _por_producto(lunes)[2]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon}/descartar", headers=FIRMA)

    assert _al_cerrar(cliente, lunes).json()["sin_pedir"] == 1


def test_una_lista_abierta_no_trae_reapertura(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]

    assert _abrir(cliente)["reapertura"] is None


def test_si_no_se_puede_saber_si_se_reabre_no_hay_boton_y_la_lista_se_ve(
    cliente, almacen, almacenamiento, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES, 1, 3)]
    _cerrar(cliente, _abrir(cliente))

    def caida(*a, **k):
        raise RuntimeError("postgresql://usuario:secreto@atlas")

    monkeypatch.setattr(almacenamiento, "se_puede_reabrir", caida)
    cuerpo = _abrir(cliente)

    assert cuerpo["estado"] == "cerrado"
    assert cuerpo["reapertura"]["se_puede"] is False
    assert cuerpo["reapertura"]["que_hacer"]
    assert "secreto" not in str(cuerpo)


# ---------------------------------------------------------------- la pantalla


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_la_confirmacion_es_un_dialogo_propio_y_no_window_confirm():
    pantalla = pantalla_completa()

    assert '<dialog id="confirmar-cierre"' in pantalla
    assert "showModal()" in _script()
    assert not re.search(r"confirm\(", _script()), "nada de window.confirm()"


def test_el_dialogo_se_cierra_con_el_teclado_y_tiene_titulo():
    """`<dialog>` con `showModal` atrapa el foco y cierra con Esc solo; el
    título lo nombra para el lector de pantalla."""
    pantalla = pantalla_completa()
    dialogo = pantalla[pantalla.index('<dialog id="confirmar-cierre"'):]
    dialogo = dialogo[: dialogo.index("</dialog>")]

    assert 'aria-labelledby="confirmar-cierre-titulo"' in dialogo
    assert 'id="confirmar-cierre-titulo"' in dialogo
    assert 'method="dialog"' in dialogo, "Volver cierra el diálogo sin JavaScript"
    assert dialogo.count("<button") == 2


def test_la_pantalla_pide_el_resumen_y_pinta_lo_que_llega():
    script = _script()

    assert "fetch('/api/pedido-sugerido/' + id + '/al-cerrar')" in script
    for llave in ("se_perderian", "aviso", "que_hacer_con_lo_que_se_perderia",
                  "deshacer", "resumen.boton", "resumen.volver"):
        assert llave in script, llave


def test_la_pantalla_no_compone_las_frases_del_cierre():
    """Lección de los tickets 15 y 21: la frase que afirma algo sale de Python."""
    script = _script()

    for frase in ("Cerrar de todos modos", "que se perdería al cerrar", "piezas sin pedir",
                  "Reabrir la lista", "ya se armó la lista siguiente", "Se reabrió"):
        assert frase not in script, frase


def test_el_boton_de_reabrir_no_se_pinta_muerto():
    """Nace escondido en el HTML y solo se enseña con `se_puede`."""
    pantalla = pantalla_completa()

    assert re.search(r'<button type="button" id="reabrir" hidden>', pantalla)
    assert "reapertura.se_puede" in _script()
    assert "fetch('/api/pedido-sugerido/' + id + '/reabrir'" in _script()


def test_lo_que_se_perderia_no_se_distingue_solo_por_el_color():
    """Ticket 28: cada renglón que se perdería lleva un signo, y el aviso su
    rótulo escrito."""
    hoja = (RAIZ / "src" / "continental" / "web" / "static" / "continental.css").read_text(
        encoding="utf-8"
    )
    regla = re.search(r"\.se-perderia li::before\s*\{([^}]*)\}", hoja)
    assert regla and "content:" in regla.group(1)
    aviso = re.search(r"\.confirmar-cierre \.aviso\s*\{([^}]*)\}", hoja)
    assert aviso and "border-left" in aviso.group(1) and "var(--aviso)" in aviso.group(1)
