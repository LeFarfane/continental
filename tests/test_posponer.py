"""Pasar un renglón al día siguiente (ADR 0025).

**Lo que arregla.** Con un tope de dinero en el pedido del día, la encargada
solo tenía dos salidas y las dos mentían: descartar ("no se pide") o dejarlo
abierto (la lista se cierra sola y se da por atendido, ADR 0020). Desde aquí un
renglón se puede **pasar al día siguiente**, uno por uno, y sus piezas se suman
en la siguiente lista que se arme.

**Las ocho decisiones del ADR 0025, fijadas aquí:**

1. Es un estado nuevo, `pospuesto`, firmado (quién y cuándo) y contado aparte
   de los descartados.
2. Solo desde una lista que se puede editar y solo un renglón `abierto`.
3. Se deshace mientras la lista siga abierta, de un clic.
4. Lo que pasa son **piezas** (`cantidad_a_pedir`), se suman a lo vendido y se
   guardan aparte (`piezas_pospuestas`); el producto entra aunque no se haya
   vendido.
5. "El día siguiente" es la siguiente lista que se arme, y pasa **una vez**; si
   el renglón ya traía piezas pospuestas o que faltaron, no se cuentan doble.
6. Lo que viene en camino le gana.
7. Un pospuesto no es "algo que se perdería" al cerrar.
8. No cuenta en el total ni en el reparto de hoy.

Los tres seams del repo: lo puro, lo que se guarda (el doble, los CHECK en
Python, el SQL como texto) y lo que se ve (las rutas de punta a punta, varios
días). **Ninguna prueba toca Postgres, la red ni duerme, y ningún dato es
real.**
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from continental import almacenamiento as modulo_almacenamiento
from continental import cierre
from continental.almacen import DiaCalendario, LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import (
    ESTADOS_DEL_RENGLON,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_POSPUESTO,
    AlmacenamientoDelPedido,
    PedidoSugeridoGuardado,
    RenglonGuardado,
    Ventana,
    columnas_del_renglon,
    revisar_el_renglon,
)
from continental.conciliacion import conciliar
from continental.dobles import AlmacenamientoFalso
from continental.sugerido import Renglon, armar_la_lista, calcular_pedido_sugerido
from continental.transiciones import motivo_para_no_editar
from continental.transito import (
    MemoriaDeLoPedido,
    frase_de_lo_que_paso_del_dia_anterior,
    frase_de_los_pospuestos,
    frase_del_renglon_pospuesto,
    memoria_de_lo_pedido,
    titulo_de_los_pospuestos,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
MIGRACION = SQL / "migraciones" / "0019-el-renglon-pospuesto.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
CORREO = "encargada@farmacia.mx"
CENTRO = dt.timezone(dt.timedelta(hours=-6))

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)
SABADO = dt.date(2026, 9, 19)


def _local(fecha: dt.date, hora: int = 10) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, 0, tzinfo=CENTRO)


def _renglon(
    producto_id: int,
    cantidad: int = 5,
    *,
    vendidas: float | None = None,
    piezas_que_faltaron: int = 0,
    piezas_pospuestas: int = 0,
) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        piezas_vendidas=float(cantidad if vendidas is None else vendidas),
        cantidad_propuesta=cantidad,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
        piezas_que_faltaron=piezas_que_faltaron,
        piezas_pospuestas=piezas_pospuestas,
    )


def _guardado(
    renglon_id: int,
    producto_id: int,
    estado: str = RENGLON_ABIERTO,
    *,
    cantidad: int = 5,
    cantidad_final: int | None = None,
    piezas_que_faltaron: int = 0,
    piezas_pospuestas: int = 0,
    pospuesto_por: str | None = None,
    pospuesto_en: dt.datetime | None = None,
) -> RenglonGuardado:
    pospuesto = estado == RENGLON_POSPUESTO
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=_renglon(
            producto_id,
            cantidad,
            piezas_que_faltaron=piezas_que_faltaron,
            piezas_pospuestas=piezas_pospuestas,
        ),
        cantidad_final=cantidad_final,
        ajustada_por=CORREO if cantidad_final is not None else None,
        ajustada_en=_local(MARTES) if cantidad_final is not None else None,
        pospuesto_por=pospuesto_por or (CORREO if pospuesto else None),
        pospuesto_en=pospuesto_en or (_local(MARTES) if pospuesto else None),
    )


def _lista_guardada(
    *renglones: RenglonGuardado, estado: str = "abierto", hasta: dt.date = MARTES
) -> PedidoSugeridoGuardado:
    return PedidoSugeridoGuardado(
        pedido_sugerido_id=4,
        negocio=NEGOCIO,
        fecha_del_pedido=hasta,
        estado=estado,
        ventana=Ventana(desde=hasta, hasta=hasta),
        armado_en=_local(hasta, 8),
        cerrado_en=_local(hasta, 23) if estado == "cerrado" else None,
        renglones=renglones,
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


def _producto(producto_id: int, existencia: float = 0.0) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


def _lista_en_el_doble(almacenamiento, fecha: dt.date, cantidades: dict[int, int]):
    return almacenamiento.insertar_la_lista(
        NEGOCIO,
        fecha,
        Ventana(fecha, fecha),
        [_renglon(p, c) for p, c in cantidades.items()],
    )


# ==========================================================================
# LO PURO — el estado, la regla y las frases
# ==========================================================================


def test_el_septimo_estado_es_pospuesto_y_va_al_final():
    """`pospuesto` no es un sinónimo de `descartado`: dice lo contrario."""
    assert RENGLON_POSPUESTO == "pospuesto"
    assert ESTADOS_DEL_RENGLON[-1] == RENGLON_POSPUESTO
    assert len(ESTADOS_DEL_RENGLON) == 7
    assert RENGLON_POSPUESTO != RENGLON_DESCARTADO


def test_un_renglon_pospuesto_lo_sabe_y_no_es_un_descartado():
    r = _guardado(1, 1, RENGLON_POSPUESTO)
    assert r.esta_pospuesto is True
    assert r.esta_descartado is False
    assert r.se_puede_repartir is False
    assert _guardado(2, 2).esta_pospuesto is False


def test_lo_que_pasa_es_la_cantidad_ajustada_si_la_hay():
    """`cantidad_a_pedir`: la corrección de la persona gana a la propuesta."""
    assert _guardado(1, 1, RENGLON_POSPUESTO, cantidad=5).cantidad_a_pedir == 5
    assert _guardado(1, 1, RENGLON_POSPUESTO, cantidad=5, cantidad_final=8).cantidad_a_pedir == 8


def test_la_lista_cuenta_los_pospuestos_aparte_de_los_descartados():
    lista = _lista_guardada(
        _guardado(1, 1),
        _guardado(2, 2, RENGLON_POSPUESTO),
        _guardado(3, 3, RENGLON_POSPUESTO),
        _guardado(4, 4, RENGLON_DESCARTADO),
    )
    assert lista.pospuestos == 2
    assert lista.descartados == 1


def test_un_pospuesto_sale_de_la_lista_de_trabajo_y_del_reparto():
    """El ADR dice que no cuenta en el total ni en el reparto de hoy."""
    lista = _lista_guardada(_guardado(1, 1), _guardado(2, 2, RENGLON_POSPUESTO))
    assert [r.renglon_id for r in lista.de_trabajo] == [1]
    assert [r.renglon_id for r in lista.por_repartir] == [1]


def test_un_pospuesto_ya_se_atendio_y_no_deja_la_lista_con_trabajo_sin_atender():
    lista = _lista_guardada(_guardado(1, 1, RENGLON_POSPUESTO))
    assert lista.tiene_renglones_sin_atender is False


# ----------------------------------------------------------- las transiciones


def test_solo_un_renglon_abierto_de_una_lista_abierta_se_pospone():
    assert motivo_para_no_editar(_guardado(1, 1), _lista_guardada(), "posponer") is None


@pytest.mark.parametrize(
    ("estado", "pista"),
    [
        (RENGLON_EN_TRANSITO, "ya se le pidió a un proveedor"),
        ("recibido", "ya llegó"),
        ("cancelado", "se dejó de esperar"),
        (RENGLON_DESCARTADO, "primero hay que devolverlo"),
        (RENGLON_POSPUESTO, "ya pasa al día siguiente"),
    ],
)
def test_lo_que_ya_no_esta_abierto_no_se_pospone_y_dice_por_que(estado, pista):
    motivo = motivo_para_no_editar(_guardado(1, 1, estado), _lista_guardada(), "posponer")
    assert motivo is not None
    assert pista in motivo


@pytest.mark.parametrize("estado_de_lista", ["cerrado", "vencido"])
def test_con_la_lista_cerrada_ni_se_pospone_ni_se_devuelve(estado_de_lista):
    """Las dos direcciones o ninguna: deshacer también es modificar."""
    lista = _lista_guardada(estado=estado_de_lista)
    assert "lista ya no está abierta" in motivo_para_no_editar(
        _guardado(1, 1), lista, "posponer"
    )
    assert "lista ya no está abierta" in motivo_para_no_editar(
        _guardado(1, 1, RENGLON_POSPUESTO), lista, "devolver_pospuesto"
    )


def test_devolver_pospuesto_exige_lo_contrario_el_renglon_pospuesto():
    for estado in (RENGLON_ABIERTO, RENGLON_DESCARTADO, RENGLON_EN_TRANSITO):
        motivo = motivo_para_no_editar(
            _guardado(1, 1, estado), _lista_guardada(), "devolver_pospuesto"
        )
        assert motivo is not None and "no pasa al día siguiente" in motivo
    assert (
        motivo_para_no_editar(
            _guardado(1, 1, RENGLON_POSPUESTO), _lista_guardada(), "devolver_pospuesto"
        )
        is None
    )


def test_un_pospuesto_no_se_descarta_ni_se_ajusta_sin_devolverlo():
    for accion in ("descartar", "ajustar_la_cantidad", "elegir_proveedor"):
        motivo = motivo_para_no_editar(
            _guardado(1, 1, RENGLON_POSPUESTO), _lista_guardada(), accion
        )
        assert motivo is not None and "primero hay que devolverlo" in motivo


# ------------------------------------------------------------- las frases


def test_la_frase_del_renglon_de_manana_dice_la_aritmetica_entera():
    frase = frase_de_lo_que_paso_del_dia_anterior(pospuestas=3, vendidas=2, propuesta=5)
    assert frase == (
        "Trae piezas que pasaron del día anterior: se vendieron 2 y pasaron 3 "
        "piezas, se piden 5."
    )


def test_la_frase_dice_que_no_se_vendio_nada_en_vez_de_dejar_un_cero_sin_explicar():
    frase = frase_de_lo_que_paso_del_dia_anterior(pospuestas=3, vendidas=0, propuesta=3)
    assert "no se vendió nada" in frase
    assert "pasaron 3 piezas" in frase


def test_la_frase_concuerda_con_una_sola_pieza_y_con_granel():
    assert "pasó 1 pieza" in frase_de_lo_que_paso_del_dia_anterior(1, 2, 3)
    assert "se vendieron 2.5 y" in frase_de_lo_que_paso_del_dia_anterior(3, 2.5, 6)


def test_sin_piezas_pospuestas_no_hay_frase():
    assert frase_de_lo_que_paso_del_dia_anterior(0, 4, 4) is None


def test_la_frase_del_pospuesto_dice_cuantas_piezas_quien_y_cuando():
    r = _guardado(1, 1, RENGLON_POSPUESTO, cantidad=5, cantidad_final=8)
    frase = frase_del_renglon_pospuesto(r)
    assert "8 piezas" in frase
    assert CORREO in frase
    assert "siguiente lista" in frase
    assert "a las 10:00" in frase


def test_la_frase_del_pospuesto_concuerda_en_singular_y_calla_si_no_lo_esta():
    assert "(1 pieza)" in frase_del_renglon_pospuesto(
        _guardado(1, 1, RENGLON_POSPUESTO, cantidad=1)
    )
    assert frase_del_renglon_pospuesto(_guardado(1, 1)) is None


def test_el_titulo_y_la_frase_de_los_pospuestos_concuerdan_y_dicen_que_no_cuentan():
    assert titulo_de_los_pospuestos(0) is None
    assert frase_de_los_pospuestos(0) is None
    assert titulo_de_los_pospuestos(1) == "1 renglón pasa al día siguiente"
    assert titulo_de_los_pospuestos(3) == "3 renglones pasan al día siguiente"
    assert "no cuenta en el total de hoy" in frase_de_los_pospuestos(1)
    assert "no cuentan en el total de hoy" in frase_de_los_pospuestos(3)
    assert "siguiente lista" in frase_de_los_pospuestos(3)


# ==========================================================================
# LA SIGUIENTE LISTA — piezas, no ventas
# ==========================================================================


def test_las_piezas_pospuestas_se_suman_a_lo_vendido_y_se_dicen_aparte():
    """"Se vendieron 2 y pasaron 3, se piden 5": verificable de un vistazo."""
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MIERCOLES, 1, 2)], catalogo=[_producto(1)], pospuestos={1: 3}
    )
    [renglon] = lista.renglones
    assert renglon.piezas_vendidas == 2
    assert renglon.piezas_pospuestas == 3
    assert renglon.cantidad_propuesta == 5
    assert renglon.piezas_que_faltaron == 0


def test_lo_pospuesto_entra_aunque_no_se_haya_vuelto_a_vender():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MIERCOLES, 2, 1)],
        catalogo=[_producto(1), _producto(2)],
        pospuestos={1: 3},
    )
    por_producto = {r.producto_id: r for r in lista.renglones}
    assert por_producto[1].cantidad_propuesta == 3
    assert por_producto[1].piezas_vendidas == 0
    assert por_producto[1].piezas_pospuestas == 3
    assert por_producto[2].piezas_pospuestas == 0


def test_sin_una_sola_venta_no_hay_lista_y_lo_pospuesto_espera():
    """Igual que `faltaron`: un domingo no hay lista, y lo pospuesto no se
    pierde porque la memoria lo sigue trayendo hasta la primera con ventas."""
    lista = calcular_pedido_sugerido(ventas=[], catalogo=[_producto(1)], pospuestos={1: 3})
    assert lista.renglones == ()


def test_las_piezas_pospuestas_en_cero_o_negativas_se_ignoran():
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MIERCOLES, 1, 2)], catalogo=[_producto(1)], pospuestos={1: 0, 2: -4}
    )
    [renglon] = lista.renglones
    assert renglon.piezas_pospuestas == 0
    assert renglon.cantidad_propuesta == 2


def test_la_memoria_toma_la_cantidad_a_pedir_del_pospuesto_de_la_lista_anterior():
    memoria = memoria_de_lo_pedido(
        [],
        pospuestos=[
            _guardado(1, 1, RENGLON_POSPUESTO, cantidad=5),
            _guardado(2, 2, RENGLON_POSPUESTO, cantidad=5, cantidad_final=8),
        ],
    )
    assert memoria.pospuestos == {1: 5, 2: 8}


def test_la_memoria_ignora_lo_que_no_esta_pospuesto():
    """Como con lo ya pedido: un `abierto` o un `descartado` que alguien pasara
    por error no entra."""
    memoria = memoria_de_lo_pedido(
        [], pospuestos=[_guardado(1, 1), _guardado(2, 2, RENGLON_DESCARTADO)]
    )
    assert memoria.pospuestos == {}


def test_la_memoria_vacia_no_trae_nada_pospuesto():
    assert MemoriaDeLoPedido().pospuestos == {}
    assert memoria_de_lo_pedido([]).pospuestos == {}


def test_un_pospuesto_que_ya_traia_piezas_las_pasa_enteras_sin_contarlas_doble():
    """El renglón de ayer ya sumaba 4 que faltaron: su `cantidad_a_pedir` (10)
    es lo que pasa, y no 10 + 4."""
    ayer = _guardado(
        1, 1, RENGLON_POSPUESTO, cantidad=10, piezas_que_faltaron=4
    )
    memoria = memoria_de_lo_pedido([], pospuestos=[ayer])
    lista = calcular_pedido_sugerido(
        ventas=[_venta(MIERCOLES, 1, 2)],
        catalogo=[_producto(1)],
        faltaron=memoria.faltaron,
        pospuestos=memoria.pospuestos,
    )
    [renglon] = lista.renglones
    assert renglon.cantidad_propuesta == 12
    assert renglon.piezas_pospuestas == 10
    assert renglon.piezas_que_faltaron == 0


def test_si_se_vuelve_a_pasar_lleva_lo_de_ayer_sumado():
    """Pasa una vez; para pasar otra el renglón de mañana se pospone otra vez y
    la lista siguiente lo toma de ÉL, ya con las piezas de ayer dentro."""
    hoy = calcular_pedido_sugerido(
        ventas=[_venta(MIERCOLES, 1, 2)], catalogo=[_producto(1)], pospuestos={1: 3}
    ).renglones[0]
    assert hoy.cantidad_propuesta == 5

    como_guardado = RenglonGuardado(
        renglon_id=9,
        estado=RENGLON_POSPUESTO,
        propuesto=hoy,
        pospuesto_por=CORREO,
        pospuesto_en=_local(MIERCOLES),
    )
    memoria = memoria_de_lo_pedido([], pospuestos=[como_guardado])
    otra = calcular_pedido_sugerido(
        ventas=[_venta(JUEVES, 1, 1)], catalogo=[_producto(1)], pospuestos=memoria.pospuestos
    ).renglones[0]
    assert otra.piezas_pospuestas == 5
    assert otra.cantidad_propuesta == 6


def test_lo_que_viene_en_camino_le_gana_a_lo_pospuesto():
    from continental.almacenamiento import LoYaPedido

    en_camino = LoYaPedido(
        renglon=_guardado(7, 1, RENGLON_EN_TRANSITO),
        pedido_sugerido_id=2,
        fecha_del_pedido=LUNES,
        ventas_hasta=LUNES,
        proveedor="nadro",
        enviado_por=CORREO,
        enviado_en=_local(LUNES),
    )
    memoria = memoria_de_lo_pedido(
        [en_camino], pospuestos=[_guardado(1, 1, RENGLON_POSPUESTO, cantidad=5)]
    )
    assert memoria.esta_en_camino(1)
    assert memoria.pospuestos == {}


def test_un_pospuesto_manda_sobre_lo_que_faltaba_del_mismo_producto():
    """Su `cantidad_a_pedir` ya incluía esas piezas: sumarlas otra vez sería
    pedirlas dos veces. Se queda lo pospuesto y se suelta lo viejo."""
    from continental.almacenamiento import LoYaPedido

    parcial = LoYaPedido(
        renglon=RenglonGuardado(
            renglon_id=7,
            estado="recibido parcial",
            propuesto=_renglon(1, 10),
            recibido_por=CORREO,
            recibido_en=_local(LUNES),
            piezas_recibidas=6.0,
        ),
        pedido_sugerido_id=2,
        fecha_del_pedido=LUNES,
        ventas_hasta=LUNES,
        proveedor="nadro",
        enviado_por=CORREO,
        enviado_en=_local(LUNES),
    )
    solo_el_parcial = memoria_de_lo_pedido([parcial])
    assert solo_el_parcial.faltaron == {1: 4}

    con_pospuesto = memoria_de_lo_pedido(
        [parcial], pospuestos=[_guardado(1, 1, RENGLON_POSPUESTO, cantidad=10)]
    )
    assert con_pospuesto.pospuestos == {1: 10}
    assert con_pospuesto.faltaron == {}
    assert 1 not in con_pospuesto.desde


def test_armar_la_lista_trae_lo_pospuesto_con_lo_vendido(almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(MIERCOLES, 1, 2)]
    memoria = memoria_de_lo_pedido(
        [], pospuestos=[_guardado(1, 1, RENGLON_POSPUESTO, cantidad=3)]
    )

    lista = armar_la_lista(almacen, Ventana(MIERCOLES, MIERCOLES), memoria)

    [renglon] = lista.renglones
    assert renglon.piezas_vendidas == 2
    assert renglon.piezas_pospuestas == 3
    assert renglon.cantidad_propuesta == 5


# ==========================================================================
# LO QUE SE GUARDA — el doble, los CHECK en Python y el SQL como texto
# ==========================================================================


def test_el_doble_sigue_cumpliendo_la_interfaz():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)
    for metodo in ("posponer", "devolver_pospuesto", "lo_pospuesto"):
        assert hasattr(AlmacenamientoDelPedido, metodo), metodo


def test_posponer_deja_el_renglon_pospuesto_y_firmado(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id

    guardada = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    r = guardada.renglones[0]
    assert r.estado == RENGLON_POSPUESTO
    assert r.pospuesto_por == CORREO
    assert r.pospuesto_en is not None and r.pospuesto_en.tzinfo is not None
    assert guardada.pospuestos == 1


def test_posponer_no_toca_las_cantidades(almacenamiento):
    """Lo que pasa es lo que `cantidad_a_pedir` valga después, no una copia."""
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id
    almacenamiento.ajustar_la_cantidad(NEGOCIO, renglon_id, 8, CORREO)

    r = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO).renglones[0]

    assert r.propuesto.cantidad_propuesta == 5
    assert r.cantidad_final == 8
    assert r.cantidad_a_pedir == 8


def test_posponer_dos_veces_no_mueve_la_firma(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id
    primera = almacenamiento.posponer(NEGOCIO, renglon_id, CORREO).renglones[0]

    assert almacenamiento.posponer(NEGOCIO, renglon_id, "otra@farmacia.mx") is None

    r = almacenamiento.leer(NEGOCIO, MARTES).renglones[0]
    assert r.pospuesto_por == CORREO
    assert r.pospuesto_en == primera.pospuesto_en


@pytest.mark.parametrize("estado", ["en tránsito", "descartado"])
def test_lo_que_no_esta_abierto_no_se_pospone(almacenamiento, estado):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id
    if estado == "descartado":
        almacenamiento.descartar(NEGOCIO, renglon_id, CORREO)
    else:
        almacenamiento.poner_estado_del_renglon(renglon_id, estado)

    assert almacenamiento.posponer(NEGOCIO, renglon_id, CORREO) is None
    assert almacenamiento.leer(NEGOCIO, MARTES).renglones[0].estado == estado


def test_con_la_lista_cerrada_no_se_pospone_ni_se_devuelve(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5, 2: 3})
    primero, segundo = (r.renglon_id for r in lista.renglones)
    almacenamiento.posponer(NEGOCIO, primero, CORREO)
    almacenamiento.cerrar(NEGOCIO, lista.pedido_sugerido_id, CORREO)

    assert almacenamiento.posponer(NEGOCIO, segundo, CORREO) is None
    assert almacenamiento.devolver_pospuesto(NEGOCIO, primero) is None
    quedo = almacenamiento.leer(NEGOCIO, MARTES)
    assert {r.renglon_id: r.estado for r in quedo.renglones} == {
        primero: RENGLON_POSPUESTO,
        segundo: RENGLON_ABIERTO,
    }


def test_un_renglon_de_otro_negocio_no_se_pospone(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id

    assert almacenamiento.posponer("otro_negocio", renglon_id, CORREO) is None
    assert almacenamiento.devolver_pospuesto("otro_negocio", renglon_id) is None
    assert almacenamiento.posponer(NEGOCIO, 99999, CORREO) is None


def test_devolver_un_pospuesto_lo_deja_abierto_y_sin_firma(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    renglon_id = lista.renglones[0].renglon_id
    almacenamiento.posponer(NEGOCIO, renglon_id, CORREO)

    guardada = almacenamiento.devolver_pospuesto(NEGOCIO, renglon_id)

    r = guardada.renglones[0]
    assert r.estado == RENGLON_ABIERTO
    assert r.pospuesto_por is None and r.pospuesto_en is None
    assert guardada.pospuestos == 0


def test_devolver_lo_que_no_esta_pospuesto_no_hace_nada(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5})
    assert almacenamiento.devolver_pospuesto(NEGOCIO, lista.renglones[0].renglon_id) is None


def test_lo_pospuesto_es_solo_lo_de_la_lista_inmediatamente_anterior(almacenamiento):
    """Pasa UNA vez: lo de hace dos listas, si nadie lo volvió a pasar, corre la
    regla del ADR 0020 y no vuelve."""
    vieja = _lista_en_el_doble(almacenamiento, LUNES, {1: 5})
    almacenamiento.posponer(NEGOCIO, vieja.renglones[0].renglon_id, CORREO)
    intermedia = _lista_en_el_doble(almacenamiento, MARTES, {2: 3})
    almacenamiento.posponer(NEGOCIO, intermedia.renglones[0].renglon_id, CORREO)

    de_ayer = almacenamiento.lo_pospuesto(NEGOCIO, MIERCOLES)

    assert [r.propuesto.producto_id for r in de_ayer] == [2]
    assert [r.propuesto.producto_id for r in almacenamiento.lo_pospuesto(NEGOCIO, MARTES)] == [1]


def test_lo_pospuesto_solo_trae_pospuestos_y_de_este_negocio(almacenamiento):
    lista = _lista_en_el_doble(almacenamiento, MARTES, {1: 5, 2: 3, 3: 2})
    uno, dos, _tres = (r.renglon_id for r in lista.renglones)
    almacenamiento.posponer(NEGOCIO, uno, CORREO)
    almacenamiento.descartar(NEGOCIO, dos, CORREO)

    assert [r.propuesto.producto_id for r in almacenamiento.lo_pospuesto(NEGOCIO, MIERCOLES)] == [1]
    assert almacenamiento.lo_pospuesto("otro_negocio", MIERCOLES) == ()
    # Y de la lista que se arma, hacia atrás: nunca la misma ni una posterior.
    assert almacenamiento.lo_pospuesto(NEGOCIO, MARTES) == ()


def test_lo_pospuesto_sin_listas_anteriores_es_nada(almacenamiento):
    assert almacenamiento.lo_pospuesto(NEGOCIO, MARTES) == ()


def test_la_lista_nueva_guarda_las_piezas_pospuestas_aparte(almacenamiento):
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO,
        MIERCOLES,
        Ventana(MIERCOLES, MIERCOLES),
        [_renglon(1, 5, vendidas=2, piezas_pospuestas=3)],
    )
    r = almacenamiento.leer(NEGOCIO, MIERCOLES).renglones[0]
    assert r.propuesto.piezas_pospuestas == 3
    assert r.propuesto.cantidad_propuesta == 5
    assert lista.renglones[0].propuesto.piezas_pospuestas == 3


# ------------------------------------------- que el doble no sea permisivo


def _columnas(**cambios) -> dict:
    columnas = columnas_del_renglon(_renglon(1, 5), NEGOCIO, 1)
    columnas.update(cambios)
    return columnas


def test_un_renglon_nace_sin_firma_de_pospuesto_ni_piezas():
    columnas = columnas_del_renglon(_renglon(1, 5), NEGOCIO, 1)
    assert columnas["pospuesto_por"] is None
    assert columnas["pospuesto_en"] is None
    assert columnas["piezas_pospuestas"] == 0
    revisar_el_renglon(columnas)


def test_el_doble_rechaza_un_pospuesto_sin_firma():
    with pytest.raises(ValueError, match="ck_renglon_pospuesto"):
        revisar_el_renglon(_columnas(estado=RENGLON_POSPUESTO))
    with pytest.raises(ValueError, match="ck_renglon_pospuesto"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_POSPUESTO, pospuesto_por=CORREO, pospuesto_en=None)
        )


def test_el_doble_rechaza_la_firma_de_pospuesto_en_un_renglon_abierto():
    with pytest.raises(ValueError, match="ck_renglon_pospuesto"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_ABIERTO, pospuesto_por=CORREO, pospuesto_en=_local(MARTES))
        )


def test_el_doble_acepta_un_pospuesto_firmado_y_rechaza_la_firma_vacia():
    revisar_el_renglon(
        _columnas(estado=RENGLON_POSPUESTO, pospuesto_por=CORREO, pospuesto_en=_local(MARTES))
    )
    with pytest.raises(ValueError, match="pospuesto_por"):
        revisar_el_renglon(
            _columnas(estado=RENGLON_POSPUESTO, pospuesto_por="", pospuesto_en=_local(MARTES))
        )


@pytest.mark.parametrize("piezas", [-1, 6])
def test_las_piezas_pospuestas_caben_en_la_propuesta_y_no_son_negativas(piezas):
    with pytest.raises(ValueError, match="ck_renglon_piezas_pospuestas"):
        revisar_el_renglon(_columnas(piezas_pospuestas=piezas))
    revisar_el_renglon(_columnas(piezas_pospuestas=5))


# ------------------------------------------------------- el SQL como texto


def _sentencia(nombre: str) -> str:
    return getattr(modulo_almacenamiento, nombre).text


def test_posponer_es_un_update_con_las_dos_condiciones_en_el_where():
    """Revisado como texto, porque desde la torre no hay Postgres que lo corra.

    `abierto` el renglón y `abierta` su lista, las mismas dos que `_DESCARTAR`:
    comprobarlas en Python y actualizar después tiene una carrera en medio.
    """
    sentencia = _sentencia("_POSPONER").lower()
    assert sentencia.lstrip().startswith("update")
    assert "set estado = 'pospuesto'" in sentencia
    assert "r.estado = 'abierto'" in sentencia
    assert "p.estado = 'abierto'" in sentencia
    assert "pospuesto_por = :quien" in sentencia
    # La hora la pone el servidor que guarda la fila, como en el descarte.
    assert "pospuesto_en = now()" in sentencia
    assert "cantidad_final" not in sentencia and "cantidad_propuesta" not in sentencia


def test_devolver_un_pospuesto_limpia_las_dos_columnas_y_exige_la_lista_abierta():
    sentencia = _sentencia("_DEVOLVER_DE_POSPUESTO").lower()
    assert sentencia.lstrip().startswith("update")
    assert "r.estado = 'pospuesto'" in sentencia
    assert "p.estado = 'abierto'" in sentencia
    assert "pospuesto_por = null" in sentencia
    assert "pospuesto_en = null" in sentencia


def test_lo_pospuesto_se_lee_de_la_lista_inmediatamente_anterior_y_sin_reloj():
    sentencia = _sentencia("_LO_POSPUESTO").lower()
    assert sentencia.lstrip().startswith("select")
    assert "r.estado = 'pospuesto'" in sentencia
    assert "max(s2.fecha_del_pedido)" in sentencia
    assert "s2.fecha_del_pedido < :antes_de" in sentencia
    for reloj in ("now()", "current_date", "current_timestamp"):
        assert reloj not in sentencia


def test_las_lecturas_y_el_insert_nombran_las_columnas_nuevas():
    for nombre in ("_LEER_RENGLONES", "_LEER_RENGLON_POR_ID"):
        sentencia = _sentencia(nombre)
        for columna in ("pospuesto_por", "pospuesto_en", "piezas_pospuestas"):
            assert columna in sentencia, (nombre, columna)
    assert "piezas_pospuestas" in _sentencia("_INSERTAR_RENGLONES")


def test_el_ddl_trae_las_columnas_el_estado_y_los_check():
    sql = CREAR_TABLAS.read_bytes().decode("utf-8")
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.renglon (")
    cuerpo = sql[inicio : sql.index("\n);", inicio)]

    assert re.search(r"^\s*pospuesto_por\s+text,", cuerpo, re.MULTILINE)
    assert re.search(r"^\s*pospuesto_en\s+timestamptz,", cuerpo, re.MULTILINE)
    assert re.search(
        r"^\s*piezas_pospuestas\s+integer NOT NULL DEFAULT 0,", cuerpo, re.MULTILINE
    )
    assert "'pospuesto'" in cuerpo
    assert "CONSTRAINT ck_renglon_pospuesto\n" in cuerpo
    assert "pospuesto_por IS NOT NULL AND pospuesto_en IS NOT NULL" in cuerpo
    assert "CONSTRAINT ck_renglon_piezas_pospuestas" in cuerpo


def test_hay_una_migracion_para_la_base_que_ya_tiene_la_tabla():
    assert MIGRACION.exists()
    texto = MIGRACION.read_bytes().decode("utf-8")
    assert b"\r" not in MIGRACION.read_bytes(), "los .sql de atlas van con LF"
    sentencias = "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("--")
    )

    assert "ALTER TABLE pedidos.renglon" in sentencias
    assert "CREATE TABLE" not in sentencias
    for columna in ("pospuesto_por", "pospuesto_en", "piezas_pospuestas"):
        assert f"ADD COLUMN IF NOT EXISTS {columna}" in sentencias, columna
    # `ADD CONSTRAINT` no tiene IF NOT EXISTS: la idempotencia es quitarlo antes.
    for restriccion in (
        "ck_renglon_estado",
        "ck_renglon_pospuesto_por",
        "ck_renglon_pospuesto",
        "ck_renglon_piezas_pospuestas",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {restriccion};" in sentencias, restriccion
        assert f"ADD CONSTRAINT {restriccion}\n" in sentencias, restriccion
    assert "'pospuesto'" in sentencias
    # Con el acento dentro del CHECK, y la guardia de quién la corre.
    assert "'en tránsito'" in sentencias
    assert "current_user = 'continental'" in sentencias
    for prohibida in ("DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN"):
        assert prohibida not in sentencias.upper()


def test_la_forma_de_la_base_exige_las_columnas_y_las_atribuye_a_la_0019():
    """`forma.py` lee las columnas esperadas de `crear_tablas.sql` y la
    migración de cada una de las que hay: ADR 0017."""
    from continental import forma

    esperadas = forma.columnas_de_crear_tablas(CREAR_TABLAS.read_bytes().decode("utf-8"))
    for columna in ("pospuesto_por", "pospuesto_en", "piezas_pospuestas"):
        assert columna in esperadas["renglon"], columna

    migraciones = {
        archivo.name: archivo.read_bytes().decode("utf-8")
        for archivo in (SQL / "migraciones").glob("*.sql")
    }
    de_que = forma.migracion_de_cada_columna(migraciones)
    for columna in ("pospuesto_por", "pospuesto_en", "piezas_pospuestas"):
        assert de_que[("renglon", columna)] == "0019-el-renglon-pospuesto.sql", columna


# ==========================================================================
# EL CIERRE Y LA CONCILIACIÓN
# ==========================================================================


def test_un_pospuesto_no_es_algo_que_se_perderia_al_cerrar():
    """Ya tiene adónde ir: la siguiente lista lo trae. Aunque traiga piezas de
    otro pedido, señalarlo mandaría a "arreglar" lo que alguien decidió."""
    ventana = Ventana(MARTES, MARTES)
    r = _guardado(1, 1, RENGLON_POSPUESTO, cantidad=10, piezas_que_faltaron=4)
    assert cierre.se_perderia(r, ventana) is False

    lista = _lista_guardada(r, _guardado(2, 2))
    assert cierre.lo_que_se_perderia(lista) == ()


def test_un_abierto_con_lo_mismo_si_se_perderia_y_el_pospuesto_no_lo_acompana():
    """El contraste: lo mismo, sin pasarlo a mañana, sí se señala."""
    ventana = Ventana(MARTES, MARTES)
    assert cierre.se_perderia(_guardado(1, 1, cantidad=10, piezas_que_faltaron=4), ventana)
    assert not cierre.se_perderia(
        _guardado(1, 1, RENGLON_POSPUESTO, cantidad=10, piezas_que_faltaron=4), ventana
    )


def test_cerrar_con_pospuestos_lo_dice_y_no_los_cuenta_como_sin_pedir():
    lista = _lista_guardada(
        _guardado(1, 1),
        _guardado(2, 2, RENGLON_POSPUESTO),
        _guardado(3, 3, RENGLON_POSPUESTO),
    )
    resumen = cierre.al_cerrar(lista)

    assert resumen["sin_pedir"] == 1
    assert resumen["se_perderian"] == []
    assert resumen["boton"] == "Cerrar la lista"
    assert "2 renglones pasan al día siguiente" in resumen["frase"]
    assert "la siguiente lista los trae" in resumen["frase"]


def test_cerrar_con_un_solo_pospuesto_concuerda_y_con_todo_atendido_lo_dice():
    lista = _lista_guardada(_guardado(1, 1, RENGLON_POSPUESTO))
    resumen = cierre.al_cerrar(lista)

    assert resumen["sin_pedir"] == 0
    assert resumen["frase"].startswith(
        "Todo lo de esta lista ya se pidió, se descartó o pasa al día siguiente."
    )
    assert "1 renglón pasa al día siguiente y la siguiente lista lo trae" in resumen["frase"]


def test_sin_pospuestos_la_frase_de_cerrar_no_cambia():
    resumen = cierre.al_cerrar(_lista_guardada(_guardado(1, 1, RENGLON_DESCARTADO)))
    assert resumen["frase"].startswith("Todo lo de esta lista ya se pidió o se descartó.")
    assert "día siguiente" not in resumen["frase"]


NADRO = 1
PUENTE = {"nadro": NADRO}
CALENDARIO = {
    d: DiaCalendario(fecha=d, es_cerrado=False, es_festivo_oficial=False, nombre_evento=None)
    for d in (LUNES, MARTES, MIERCOLES, JUEVES, VIERNES, SABADO)
}


def _conciliar(renglones, compras, dia=MARTES):
    return conciliar(
        dia,
        renglones,
        compras,
        puente=PUENTE,
        tolerancia_dias_habiles=3,
        calendario=CALENDARIO,
        ancla=VIERNES,
    )


def _compra(compra_id: int, producto_id: int, fecha: dt.date) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=compra_id,
        producto_id=producto_id,
        proveedor_id=NADRO,
        fecha=fecha,
        cantidad=5.0,
        precio_unitario_pagado=100.0,
        importe_pagado=500.0,
        folio=f"F{compra_id}",
    )


def test_un_pospuesto_sin_compra_no_es_sin_comprar():
    """No se iba a comprar HOY: nadie falló en pedirlo."""
    resultado = _conciliar(
        [_guardado(1, 100, RENGLON_POSPUESTO), _guardado(2, 200)], []
    )
    assert [s.renglon.propuesto.producto_id for s in resultado.sin_comprar] == [200]
    assert resultado.coincidencias == ()


def test_un_pospuesto_no_es_coincidencia_de_hoy_aunque_se_haya_comprado():
    """Si de todos modos se compró, es una compra suelta: no cumple una
    propuesta de hoy y no se marca como descartado, que no lo está."""
    resultado = _conciliar(
        [_guardado(1, 100, RENGLON_POSPUESTO)], [_compra(9001, 100, MARTES)]
    )
    assert resultado.coincidencias == ()
    assert resultado.sin_comprar == ()
    [suelta] = resultado.compradas_sin_proponer
    assert suelta.compra.compra_id == 9001
    assert suelta.fue_descartado is False


def test_un_descartado_comprado_sigue_marcandose_como_descartado():
    """Lo que ya existía no cambió: el pospuesto no se confunde con él."""
    descartado = RenglonGuardado(
        renglon_id=1,
        estado=RENGLON_DESCARTADO,
        propuesto=_renglon(100),
        descartado_por=CORREO,
        descartado_en=_local(MARTES),
    )
    resultado = _conciliar([descartado], [_compra(9001, 100, MARTES)])
    assert resultado.compradas_sin_proponer[0].fue_descartado is True


# ==========================================================================
# LAS RUTAS — de punta a punta, y varios días
# ==========================================================================

HOY = dt.date(2024, 3, 5)
MANANA = dt.date(2024, 3, 6)
PASADO = dt.date(2024, 3, 7)


def _poblar(almacen) -> None:
    almacen.catalogo_en_memoria = [_producto(1), _producto(2, existencia=90)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3), _venta(HOY, 2, 1)]


def _posponer(cliente, renglon_id: int, correo: str | None = CORREO):
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(f"/api/renglon/{renglon_id}/posponer", headers=cabeceras)


def _devolver(cliente, renglon_id: int):
    return cliente.post(f"/api/renglon/{renglon_id}/devolver-pospuesto")


def _renglon_de(lista: dict, producto_id: int) -> dict:
    return next(r for r in lista["renglones"] if r["producto_id"] == producto_id)


def test_un_clic_pasa_el_renglon_al_dia_siguiente(cliente, almacen, almacenamiento):
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = _renglon_de(lista, 1)["renglon_id"]
    assert _renglon_de(lista, 1)["se_puede_posponer"] is True

    respuesta = _posponer(cliente, renglon_id)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["renglon"]["estado"] == RENGLON_POSPUESTO
    assert cuerpo["renglon"]["esta_pospuesto"] is True
    assert cuerpo["renglon"]["pospuesto_por"] == CORREO
    assert dt.datetime.fromisoformat(cuerpo["renglon"]["pospuesto_en"]).tzinfo is not None
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    assert next(r for r in guardado.renglones if r.renglon_id == renglon_id).esta_pospuesto


def test_la_respuesta_trae_los_conteos_y_las_frases_hechas_en_python(cliente, almacen):
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    assert lista["pospuestos"] == 0
    assert lista["frase_de_los_pospuestos"] is None
    assert lista["titulo_de_los_pospuestos"] is None

    cuerpo = _posponer(cliente, _renglon_de(lista, 1)["renglon_id"]).json()

    assert cuerpo["pospuestos"] == 1
    assert cuerpo["descartados"] == 0
    assert cuerpo["de_trabajo"] == 1
    assert cuerpo["titulo_de_los_pospuestos"] == "1 renglón pasa al día siguiente"
    assert "no cuenta en el total de hoy" in cuerpo["frase_de_los_pospuestos"]
    assert "Pasa al día siguiente (3 piezas)" in cuerpo["renglon"]["frase_de_lo_pospuesto"]
    assert CORREO in cuerpo["renglon"]["frase_de_lo_pospuesto"]


def test_el_pospuesto_sale_del_total_y_del_reparto_pero_sigue_en_la_respuesta(
    cliente, almacen
):
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    assert lista["de_trabajo"] == 2
    _posponer(cliente, _renglon_de(lista, 1)["renglon_id"])

    despues = cliente.get(RUTA).json()

    assert despues["de_trabajo"] == 1
    assert despues["pospuestos"] == 1
    assert len(despues["renglones"]) == 2, "pasar al día siguiente no borra nada"
    # El total y el reparto: solo el renglón que sigue abierto cuenta.
    assert despues["conteo_de_precios"]["renglones"] == 1
    lineas = [
        l
        for pedido in despues["particion"]["pedidos"]
        for l in pedido["lineas"]
    ] + list(despues["particion"].get("sin_proveedor", []))
    assert all(l.get("renglon_id") != _renglon_de(despues, 1)["renglon_id"] for l in lineas)


def test_sin_encabezado_la_firma_es_sin_identificar_pero_se_guarda(cliente, almacen):
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]

    cuerpo = _posponer(cliente, renglon_id, correo=None).json()

    assert cuerpo["renglon"]["pospuesto_por"] == "sin-identificar"


def test_la_firma_va_tambien_a_la_bitacora(cliente, almacen, caplog):
    import logging

    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]

    with caplog.at_level(logging.INFO, logger="continental"):
        _posponer(cliente, renglon_id)

    assert CORREO in caplog.text
    assert "pasar el renglón al día siguiente" in caplog.text


def test_devolver_lo_pospuesto_vuelve_a_abierto_y_a_la_lista_de_trabajo(
    cliente, almacen, almacenamiento
):
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]
    _posponer(cliente, renglon_id)
    assert _renglon_de(cliente.get(RUTA).json(), 1)["se_puede_devolver_pospuesto"] is True

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["renglon"]["estado"] == RENGLON_ABIERTO
    assert cuerpo["renglon"]["pospuesto_por"] is None
    assert cuerpo["renglon"]["pospuesto_en"] is None
    assert cuerpo["pospuestos"] == 0
    assert cuerpo["de_trabajo"] == 2
    assert cuerpo["frase_de_los_pospuestos"] is None


def test_posponer_dos_veces_contesta_409_y_no_mueve_la_firma(cliente, almacen):
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]
    primera = _posponer(cliente, renglon_id).json()["renglon"]["pospuesto_en"]

    segunda = _posponer(cliente, renglon_id, "otra@farmacia.mx")

    assert segunda.status_code == 409
    assert segunda.json()["ok"] is False
    assert "ya pasa al día siguiente" in segunda.json()["detalle"]
    assert _renglon_de(cliente.get(RUTA).json(), 1)["pospuesto_en"] == primera


def test_devolver_lo_que_no_esta_pospuesto_contesta_409(cliente, almacen):
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]

    respuesta = _devolver(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert "no pasa al día siguiente" in respuesta.json()["detalle"]


def test_posponer_lo_que_no_existe_contesta_409(cliente, almacen):
    _poblar(almacen)
    assert _posponer(cliente, 99999).status_code == 409


def test_un_renglon_en_transito_no_se_pospone_y_la_bandera_ya_lo_decia(
    cliente, almacen, almacenamiento
):
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]
    almacenamiento.poner_estado_del_renglon(renglon_id, "en tránsito")

    renglon = _renglon_de(cliente.get(RUTA).json(), 1)
    assert renglon["se_puede_posponer"] is False

    respuesta = _posponer(cliente, renglon_id)
    assert respuesta.status_code == 409
    assert "ya se le pidió a un proveedor" in respuesta.json()["detalle"]


def test_con_la_lista_cerrada_la_bandera_se_apaga_y_el_409_dice_por_que(cliente, almacen):
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = _renglon_de(lista, 1)["renglon_id"]
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    renglon = _renglon_de(cliente.get(RUTA).json(), 1)
    assert renglon["se_puede_posponer"] is False

    respuesta = _posponer(cliente, renglon_id)
    assert respuesta.status_code == 409
    assert "lista ya no está abierta" in respuesta.json()["detalle"]


def test_con_la_lista_cerrada_tampoco_se_devuelve_un_pospuesto(cliente, almacen):
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    renglon_id = _renglon_de(lista, 1)["renglon_id"]
    _posponer(cliente, renglon_id)
    cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/cerrar")

    renglon = _renglon_de(cliente.get(RUTA).json(), 1)
    assert renglon["se_puede_devolver_pospuesto"] is False

    respuesta = _devolver(cliente, renglon_id)
    assert respuesta.status_code == 409
    assert "lista ya no está abierta" in respuesta.json()["detalle"]


def test_el_almacenamiento_caido_es_un_hueco_con_el_tipo_y_nunca_con_el_texto(
    cliente, almacen, almacenamiento
):
    """Reglas 4 y 5: el texto de SQLAlchemy lleva la cadena de conexión."""
    _poblar(almacen)
    renglon_id = _renglon_de(cliente.get(RUTA).json(), 1)["renglon_id"]
    almacenamiento.falla = RuntimeError(
        "connection to postgresql://continental:SECRETO@atlas:5432/farmacia failed"
    )

    for cuerpo in (_posponer(cliente, renglon_id).json(), _devolver(cliente, renglon_id).json()):
        assert cuerpo["ok"] is False
        assert "RuntimeError" in cuerpo["detalle"]
        assert "SECRETO" not in str(cuerpo)
        assert cuerpo.get("que_hacer")


def test_cerrar_la_lista_no_senala_un_pospuesto_como_perdida(cliente, almacen):
    """El ADR 0025, punto 7, de punta a punta: la confirmación de cierre."""
    _poblar(almacen)
    lista = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_de(lista, 1)["renglon_id"])

    resumen = cliente.get(f"{RUTA}/{lista['pedido_sugerido_id']}/al-cerrar").json()

    assert resumen["se_perderian"] == []
    assert resumen["sin_pedir"] == 1
    assert "pasa al día siguiente" in resumen["frase"]


# ------------------------------------------ el día siguiente, de verdad


def test_la_siguiente_lista_trae_las_piezas_pospuestas_sumadas_a_lo_vendido(
    cliente, almacen, almacenamiento
):
    """El ADR entero en un escenario: ayer 3 piezas, hoy se vendieron 2, se
    piden 5, y el renglón dice de dónde sale cada número."""
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_de(ayer, 1)["renglon_id"])

    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 2))
    hoy = cliente.get(RUTA).json()

    renglon = _renglon_de(hoy, 1)
    assert renglon["estado"] == RENGLON_ABIERTO
    assert renglon["piezas_vendidas"] == 2
    assert renglon["piezas_pospuestas"] == 3
    assert renglon["cantidad_propuesta"] == 5
    assert renglon["cantidad_a_pedir"] == 5
    assert renglon["frase_de_lo_que_paso_del_dia_anterior"] == (
        "Trae piezas que pasaron del día anterior: se vendieron 2 y pasaron 3 "
        "piezas, se piden 5."
    )
    # Lo que ayer NO se pasó no trae nada del día anterior.
    assert "frase_de_lo_que_paso_del_dia_anterior" in renglon
    # Y la lista de ayer, ya cerrada sola, conserva su pospuesto intacto.
    guardada = almacenamiento.leer(NEGOCIO, HOY)
    assert guardada.estado == "cerrado"
    assert next(r for r in guardada.renglones if r.propuesto.producto_id == 1).esta_pospuesto


def test_lo_pospuesto_entra_a_la_lista_siguiente_aunque_no_se_haya_vuelto_a_vender(
    cliente, almacen
):
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_de(ayer, 1)["renglon_id"])

    # Mañana solo se vendió el otro producto.
    almacen.ventas_en_memoria.append(_venta(MANANA, 2, 1))
    hoy = cliente.get(RUTA).json()

    renglon = _renglon_de(hoy, 1)
    assert renglon["piezas_vendidas"] == 0
    assert renglon["piezas_pospuestas"] == 3
    assert renglon["cantidad_propuesta"] == 3
    assert "no se vendió nada" in renglon["frase_de_lo_que_paso_del_dia_anterior"]
    # El otro, que no se pasó, es una lista normal.
    otro = _renglon_de(hoy, 2)
    assert otro["piezas_pospuestas"] == 0
    assert otro["frase_de_lo_que_paso_del_dia_anterior"] is None


def test_un_descartado_no_pasa_al_dia_siguiente_aunque_se_vuelva_a_vender(
    cliente, almacen
):
    """El contraste que justifica el estado nuevo: descartar no arrastra nada."""
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    cliente.post(f"/api/renglon/{_renglon_de(ayer, 1)['renglon_id']}/descartar")

    almacen.ventas_en_memoria.append(_venta(MANANA, 2, 1))
    hoy = cliente.get(RUTA).json()

    assert [r["producto_id"] for r in hoy["renglones"]] == [2]


def test_lo_pospuesto_pasa_una_sola_vez(cliente, almacen):
    """Si mañana tampoco se pide ni se vuelve a pasar, la lista de pasado
    mañana ya no lo trae: corre la regla del ADR 0020."""
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_de(ayer, 1)["renglon_id"])
    almacen.ventas_en_memoria.append(_venta(MANANA, 2, 1))
    cliente.get(RUTA)

    almacen.ventas_en_memoria.append(_venta(PASADO, 2, 1))
    pasado = cliente.get(RUTA).json()

    assert [r["producto_id"] for r in pasado["renglones"]] == [2]


def test_si_se_vuelve_a_pasar_la_siguiente_lista_lleva_lo_de_ayer_sumado(cliente, almacen):
    _poblar(almacen)
    primera = cliente.get(RUTA).json()
    _posponer(cliente, _renglon_de(primera, 1)["renglon_id"])
    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 2))
    segunda = cliente.get(RUTA).json()
    assert _renglon_de(segunda, 1)["cantidad_a_pedir"] == 5
    _posponer(cliente, _renglon_de(segunda, 1)["renglon_id"])

    almacen.ventas_en_memoria.append(_venta(PASADO, 1, 1))
    tercera = cliente.get(RUTA).json()

    renglon = _renglon_de(tercera, 1)
    assert renglon["piezas_pospuestas"] == 5
    assert renglon["piezas_vendidas"] == 1
    assert renglon["cantidad_propuesta"] == 6


def test_la_cantidad_ajustada_es_la_que_pasa(cliente, almacen):
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    renglon_id = _renglon_de(ayer, 1)["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/cantidad", json={"cantidad": 7})
    _posponer(cliente, renglon_id)

    almacen.ventas_en_memoria.append(_venta(MANANA, 1, 1))
    hoy = cliente.get(RUTA).json()

    assert _renglon_de(hoy, 1)["piezas_pospuestas"] == 7


def test_lo_devuelto_antes_de_cerrar_no_pasa_a_manana(cliente, almacen):
    _poblar(almacen)
    ayer = cliente.get(RUTA).json()
    renglon_id = _renglon_de(ayer, 1)["renglon_id"]
    _posponer(cliente, renglon_id)
    _devolver(cliente, renglon_id)

    almacen.ventas_en_memoria.append(_venta(MANANA, 2, 1))
    hoy = cliente.get(RUTA).json()

    assert [r["producto_id"] for r in hoy["renglones"]] == [2]


# ==========================================================================
# LA PANTALLA — estáticas del JavaScript y del HTML
# ==========================================================================


def _script() -> str:
    from conftest import pantalla_completa

    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str) -> str:
    from conftest import cuerpo_de_funcion

    return cuerpo_de_funcion(_script(), "const " + nombre + " =")


def test_cada_fila_trae_su_flecha_con_el_nombre_del_producto_y_apagada_con_la_bandera():
    cuerpo = _funcion("renglon")
    assert "acciones.posponer" in cuerpo
    assert "'Pasar al día siguiente ' + r.descripcion" in cuerpo
    assert "posponer.disabled = !r.se_puede_posponer" in cuerpo
    # Junto a la cruz, y con el mismo estilo de botón.
    assert "celdaAcciones.append(posponer, quitar)" in cuerpo
    assert "confirm(" not in cuerpo


def test_el_detalle_ofrece_pasar_al_dia_siguiente_solo_si_se_puede():
    cuerpo = _funcion("pintarDetalle")
    assert "r.se_puede_posponer && acciones.posponer" in cuerpo
    assert "'Pasar al día siguiente ' + r.descripcion" in cuerpo


def test_la_pantalla_no_pide_confirmacion_para_pasar_al_dia_siguiente():
    pantalla = _script()
    assert "'/posponer'" in pantalla
    assert "'/devolver-pospuesto'" in pantalla
    assert "confirm(" not in pantalla


def test_el_reparto_de_la_pantalla_saca_a_los_pospuestos_de_la_lista_de_trabajo():
    pantalla = _script()
    assert "const POSPUESTO = 'pospuesto';" in pantalla
    assert re.search(
        r"r\.estado !== DESCARTADO && r\.estado !== POSPUESTO", pantalla
    ), "los pospuestos siguen en la lista de trabajo: contarían en el total de hoy"
    assert "pintarPospuestos(" in pantalla


def test_el_bloque_de_pospuestos_tiene_su_html_su_boton_de_devolver_y_se_esconde_con_el_dia():
    from conftest import pantalla_completa

    html = pantalla_completa()
    assert 'id="pospuestos"' in html
    assert 'id="pospuestos-resumen"' in html
    assert 'id="pospuestos-lista"' in html

    cuerpo = _funcion("renglonPospuesto")
    assert "se_puede_devolver_pospuesto" in cuerpo
    assert "'Devolver ' + r.descripcion + ' a la lista'" in cuerpo
    # Las frases las compone Python: el JavaScript solo las pinta.
    assert "r.frase_de_lo_pospuesto" in cuerpo

    cuerpo = _funcion("pintarPospuestos")
    assert "titulo" in cuerpo and "caja.hidden = !cuantos" in cuerpo
    # Y el bloque se apaga al cambiar de día, junto a los demás.
    assert "'pospuestos'" in _funcion("ocultarLoDeOtroDia")


def test_el_detalle_del_renglon_de_manana_pinta_la_frase_de_python():
    cuerpo = _funcion("marcasDe")
    assert "r.frase_de_lo_que_paso_del_dia_anterior" in cuerpo


def test_la_respuesta_de_mover_un_renglon_actualiza_los_pospuestos_desde_el_servidor():
    pantalla = _script()
    assert "datos.pospuestos = respuesta.pospuestos" in pantalla
    assert "datos.titulo_de_los_pospuestos = respuesta.titulo_de_los_pospuestos" in pantalla


def test_el_css_nuevo_usa_solo_variables_de_root():
    """Colores solo vía variables: ni un `#` ni un `rgb(` en lo que se agregó."""
    from conftest import pantalla_completa

    css = pantalla_completa()
    reglas = [
        linea
        for linea in css.splitlines()
        if linea.startswith((".quitar.posponer", ".descartados.pospuestos"))
    ]
    assert reglas, "no se encontró el CSS del botón de pasar al día siguiente"
    for linea in reglas:
        assert "#" not in linea.split("/*")[0], linea
        assert "rgb(" not in linea and "hsl(" not in linea, linea
        assert "var(--" in linea, linea
