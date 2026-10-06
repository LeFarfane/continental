"""La lista de espera en el menú: una tarjeta por proveedor (ticket 11).

Cuatro niveles, los del repo. **Ninguna prueba toca Postgres, la red ni duerme.**

1. **Lo puro**: el llenado de la barra y sus frases, la acción nueva de las
   transiciones y el agrupar por proveedor (`lista_de_espera.py`).
2. **Lo guardado**: el doble de elegir proveedor de la espera y su sentencia SQL,
   leída como texto.
3. **La ruta de punta a punta**: `GET /api/lista-de-espera` y
   `POST /api/renglon/{id}/proveedor-de-la-espera`, con las rutas de siempre para
   mandar y sacar.
4. **La estática del JavaScript**: pinta lo que dice el servidor y no suma, no
   compara montos ni agrupa.

Lo que se cuida sobre todo, y cada nivel lo repite: **un renglón sin precio dice
«sin precio» y no `$0.00`**; **el precio es el de hoy y no el de cuando se mandó
a espera**; **la barra no promete más de lo que se sabe**; y **un pedido enviado
no ofrece «Sacar de la espera»** hacia él.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental import almacenamiento as modulo_almacenamiento
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    CANCELADO,
    CERRADO,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_POSPUESTO,
    AlmacenamientoDelPedido,
    PedidoGuardado,
    PedidoSugeridoGuardado,
    PrecioDeProveedor,
    RenglonGuardado,
    Ventana,
)
from continental.dobles import AlmacenamientoFalso
from continental.lista_de_espera import (
    FRASE_PRECIO_SIN_LEER,
    FRASE_SIN_PRECIO,
    MOTIVO_CERRADA_SIN_REPARTIR,
    MOTIVO_LISTA_CERRADA,
    MOTIVO_PROVEEDOR_DESCONOCIDO,
    MOTIVO_SIN_LISTA,
    MOTIVO_SIN_REPARTIR,
    MOTIVO_SIN_VENTAS,
    frase_del_estado_del_pedido,
    la_lista_de_espera,
    lista_que_no_hay,
    motivo_para_no_sacar,
)
from continental.minimos import (
    PROVEEDORES_CONOCIDOS,
    MinimoDelProveedor,
    SumaDelPedido,
    avisar_el_minimo,
    llenado_de_la_barra,
)
from continental.precios import LecturaDePrecio
from continental.sugerido import Renglon
from continental.transiciones import (
    ELEGIR_PROVEEDOR_DE_LA_ESPERA,
    motivo_para_no_editar,
)

D = Decimal
RUTA = "/api/pedido-sugerido"
ESPERA = "/api/lista-de-espera"
NEGOCIO = "farmacia_01"
CORREO = "encargada@farmacia.mx"
OTRO = "luis@farmacia.mx"
HOY = dt.date(2024, 3, 5)
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


# ==========================================================================
# 1. LO PURO
# ==========================================================================


# --- el llenado de la barra


@pytest.mark.parametrize(
    ("comparado", "monto", "esperado"),
    [
        ("0", "2000", 0),
        ("1000", "2000", 50),
        ("1999.99", "2000", 99),  # hacia abajo: 100 diría «ya llegó» y no llega
        ("2000", "2000", 100),
        ("5000", "2000", 100),  # con tope: no es un 250
        ("1", "3", 33),
        ("-5", "2000", 0),
    ],
)
def test_el_llenado_es_entero_hacia_abajo_y_con_tope(comparado, monto, esperado):
    assert llenado_de_la_barra(D(comparado), D(monto)) == esperado


def _minimo(monto: str, con_iva: bool = False) -> MinimoDelProveedor:
    return MinimoDelProveedor("nadro", D(monto), con_iva, CORREO, ARMADO)


def _suma(sin_iva: str | None, con_iva: str | None = None, *, parcial: str = "0",
          parcial_con_iva: str = "0", renglones: int = 2, sin_precio: int = 0,
          sin_tasa: int = 0) -> SumaDelPedido:
    return SumaDelPedido(
        renglones=renglones,
        sin_precio=sin_precio,
        sin_iva=None if sin_iva is None else D(sin_iva),
        parcial_sin_iva=D(sin_iva if sin_iva is not None else parcial),
        con_iva=None if con_iva is None else D(con_iva),
        parcial_con_iva=D(con_iva if con_iva is not None else parcial_con_iva),
        sin_tasa=sin_tasa,
    )


def test_el_aviso_trae_el_llenado_calculado_en_la_base_del_minimo():
    # $1,900 sin IVA son $2,060 con IVA: contra un mínimo de $2,000 CON IVA ya llega
    # (100); contra el mismo mínimo SIN IVA le faltan $100 (95). Si la barra
    # comparara en la base equivocada, diría 95 en el primer caso.
    con = avisar_el_minimo("nadro", _minimo("2000", True), _suma("1900.00", "2060.00"))
    sin = avisar_el_minimo("nadro", _minimo("2000", False), _suma("1900.00", "2060.00"))

    assert (con.estado, con.progreso) == ("llega", 100)
    assert (sin.estado, sin.progreso) == ("no_llega", 95)
    assert sin.como_json()["progreso"] == 95


def test_un_total_que_casi_llega_no_pinta_la_barra_llena():
    aviso = avisar_el_minimo("nadro", _minimo("2000"), _suma("1999.99"))

    assert aviso.estado == "no_llega" and aviso.progreso == 99


def test_con_un_piso_la_barra_no_promete_mas_de_lo_que_se_sabe():
    # Falta un precio: el total no se sabe. Lo que sí se sabe es un piso, y la
    # barra es el piso.
    aviso = avisar_el_minimo(
        "nadro", _minimo("2000"), _suma(None, parcial="500.00", sin_precio=1)
    )

    assert aviso.estado == "no_se_sabe" and aviso.progreso == 25


def test_si_el_piso_ya_alcanza_la_barra_va_llena():
    aviso = avisar_el_minimo(
        "nadro", _minimo("2000"), _suma(None, parcial="2500.00", sin_precio=1)
    )

    assert aviso.estado == "llega" and aviso.progreso == 100


def test_un_pedido_sin_renglones_tiene_la_barra_vacia():
    aviso = avisar_el_minimo("nadro", _minimo("2000"), _suma("0", renglones=0))

    assert aviso.estado == "no_se_sabe" and aviso.progreso == 0


def test_sin_barra_que_pintar_el_progreso_es_none_y_no_cero():
    """Sin mínimo capturado, sin mínimo, o sin poder leer: no hay barra, que no es
    una barra vacía (un cero diría «no ha avanzado» de lo que no se mide)."""
    capturado = avisar_el_minimo("nadro", None, _suma("1900.00"))
    cero = avisar_el_minimo("nadro", _minimo("0"), _suma("1900.00"))
    sin_suma = avisar_el_minimo("nadro", _minimo("2000"), None)

    assert (capturado.estado, capturado.progreso) == ("sin_capturar", None)
    assert capturado.frase == "sin mínimo capturado"
    assert (cero.estado, cero.progreso) == ("sin_minimo", None)
    assert cero.frase == "no tiene mínimo"
    assert sin_suma.progreso is None


# --- la acción nueva de las transiciones


def _renglon(
    renglon_id: int,
    estado: str = RENGLON_ABIERTO,
    pedido_id: int | None = None,
    proveedor_de_la_espera: str | None = None,
    cantidad: int = 3,
    capturado: bool = False,
) -> RenglonGuardado:
    pospuesto = estado == RENGLON_POSPUESTO
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=renglon_id,
            clave=f"75010000{renglon_id:05d}",
            descripcion=f"PRODUCTO {renglon_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        pedido_id=pedido_id,
        pedido_sugerido_id=1,
        pospuesto_por=CORREO if pospuesto else None,
        pospuesto_en=ARMADO if pospuesto else None,
        proveedor_de_la_espera=proveedor_de_la_espera,
        espera_desde=HOY if pospuesto else None,
        listas_en_espera=1 if pospuesto else None,
        capturado_por=CORREO if capturado else None,
        capturado_en=ARMADO if capturado else None,
    )


def _pedido(pedido_id: int, proveedor: str, estado: str = BORRADOR) -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=pedido_id,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor=proveedor,
        proveedor_id=None,
        estado_declarado=estado,
        armado_en=ARMADO,
        enviado_por=CORREO if estado != BORRADOR else None,
        enviado_en=ARMADO if estado != BORRADOR else None,
        cancelado_por=CORREO if estado == CANCELADO else None,
        cancelado_en=ARMADO if estado == CANCELADO else None,
    )


def _lista(renglones, estado: str = "abierto") -> PedidoSugeridoGuardado:
    return PedidoSugeridoGuardado(
        pedido_sugerido_id=1,
        negocio=NEGOCIO,
        fecha_del_pedido=HOY,
        estado=estado,
        ventana=Ventana(HOY, HOY),
        armado_en=ARMADO,
        cerrado_en=ARMADO if estado == CERRADO else None,
        renglones=tuple(renglones),
    )


def _precio(renglon_id: int, proveedor: str, precio: str | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor=proveedor,
        consultado_en=ARMADO,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else D(precio),
        motivo=None if precio is not None else "sin_resultados",
    )


def test_elegir_proveedor_de_la_espera_exige_pospuesto_y_sin_proveedor():
    lista = _lista([])

    sin_proveedor = _renglon(1, RENGLON_POSPUESTO)
    assert motivo_para_no_editar(sin_proveedor, lista, ELEGIR_PROVEEDOR_DE_LA_ESPERA) is None

    con_proveedor = _renglon(1, RENGLON_POSPUESTO, proveedor_de_la_espera="levic")
    assert "ya tiene proveedor" in motivo_para_no_editar(
        con_proveedor, lista, ELEGIR_PROVEEDOR_DE_LA_ESPERA
    )

    abierto = _renglon(1, RENGLON_ABIERTO)
    assert "no está en espera" in motivo_para_no_editar(
        abierto, lista, ELEGIR_PROVEEDOR_DE_LA_ESPERA
    )


def test_elegir_proveedor_de_la_espera_exige_la_lista_abierta():
    motivo = motivo_para_no_editar(
        _renglon(1, RENGLON_POSPUESTO), _lista([], CERRADO), ELEGIR_PROVEEDOR_DE_LA_ESPERA
    )

    assert "la lista ya no está abierta" in motivo


# --- agrupar por proveedor


def _armada(estado_de_la_lista: str = "abierto", estado_del_pedido: str = BORRADOR):
    """NADRO con dos renglones en su pedido y uno en espera; LEVIC solo con uno en
    espera y su pedido; VICMA y QuePharma sin pedido; y uno en espera sin proveedor."""
    renglones = [
        _renglon(1, pedido_id=10),
        _renglon(2, pedido_id=10),
        _renglon(3, RENGLON_POSPUESTO, proveedor_de_la_espera="nadro"),
        _renglon(4, RENGLON_POSPUESTO, proveedor_de_la_espera="levic"),
        _renglon(5, RENGLON_POSPUESTO),
    ]
    pedidos = [_pedido(10, "nadro", estado_del_pedido), _pedido(11, "levic")]
    precios = {
        1: [_precio(1, "nadro", "10.50")],
        2: [_precio(2, "nadro", None)],
        3: [_precio(3, "nadro", "20.00"), _precio(3, "levic", "18.00")],
        4: [_precio(4, "levic", "7.25")],
        5: [_precio(5, "nadro", "30.00")],
    }
    return _lista(renglones, estado_de_la_lista), pedidos, precios


def test_las_tarjetas_son_los_cuatro_proveedores_en_el_orden_de_siempre():
    lista, pedidos, precios = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, precios, None)

    assert [t["proveedor"] for t in cuerpo["proveedores"]] == list(PROVEEDORES_CONOCIDOS)
    assert [t["nombre"] for t in cuerpo["proveedores"]] == [
        "NADRO", "LEVIC", "VICMA", "QuePharma",
    ]


def test_cada_renglon_va_en_la_tarjeta_de_su_proveedor_y_en_su_bloque():
    lista, pedidos, precios = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, precios, None)
    nadro, levic, vicma, quepharma = cuerpo["proveedores"]

    assert [r["renglon_id"] for r in nadro["hoy"]] == [1, 2]
    assert [r["renglon_id"] for r in nadro["en_espera"]] == [3]
    assert [r["renglon_id"] for r in levic["hoy"]] == []
    assert [r["renglon_id"] for r in levic["en_espera"]] == [4]
    assert vicma["hoy"] == vicma["en_espera"] == quepharma["hoy"] == []
    assert [r["renglon_id"] for r in cuerpo["sin_proveedor"]] == [5]


def test_el_precio_es_el_de_ese_proveedor_y_sin_precio_no_es_un_cero():
    lista, pedidos, precios = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, precios, None)
    nadro = cuerpo["proveedores"][0]
    hoy = {r["renglon_id"]: r for r in nadro["hoy"]}

    assert (hoy[1]["precio"], hoy[1]["frase_del_precio"]) == ("10.50", "$10.50")
    # Sin precio: nunca $0.00 ni una cadena vacía.
    assert (hoy[2]["precio"], hoy[2]["frase_del_precio"]) == (None, FRASE_SIN_PRECIO)
    # Lo que espera de NADRO se ve con el precio de NADRO, no con el de LEVIC.
    assert nadro["en_espera"][0]["frase_del_precio"] == "$20.00"


def test_un_renglon_al_que_nadie_le_consulto_ese_proveedor_dice_sin_precio():
    lista, pedidos, _ = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, {}, None)

    assert {r["frase_del_precio"] for t in cuerpo["proveedores"] for r in t["hoy"]} == {
        FRASE_SIN_PRECIO
    }


def test_si_los_precios_no_se_pudieron_leer_se_dice_y_no_se_pinta_como_sin_precio():
    lista, pedidos, _ = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, None, None)
    nadro = cuerpo["proveedores"][0]

    assert nadro["hoy"][0]["frase_del_precio"] == FRASE_PRECIO_SIN_LEER
    assert nadro["total"] is None
    assert nadro["frase_del_total"].startswith("total sin saber")


def test_el_total_es_el_del_servidor_y_solo_cuenta_el_pedido_de_hoy():
    lista, pedidos, precios = _armada()

    cuerpo = la_lista_de_espera(lista, pedidos, precios, None)
    nadro, levic, vicma, _ = cuerpo["proveedores"]

    # Un renglón de NADRO no tiene precio: no hay total y se dice cuánto falta,
    # jamás la suma de lo demás. Lo que espera no cuenta.
    assert nadro["total"]["hay"] is False
    assert nadro["frase_del_total"] == "$31.50 + 1 sin precio"
    assert levic["frase_del_total"] == "sin renglones"
    assert vicma["frase_del_total"] == "sin pedido hoy"
    assert vicma["total"] is None and vicma["pedido_id"] is None


def test_la_cabecera_trae_el_aviso_del_minimo_con_su_llenado():
    lista, pedidos, precios = _armada()
    aviso = avisar_el_minimo("nadro", _minimo("63"), _suma("31.50", renglones=1)).como_json()

    cuerpo = la_lista_de_espera(lista, pedidos, precios, {10: aviso})

    assert cuerpo["proveedores"][0]["minimo"]["progreso"] == 50
    assert cuerpo["proveedores"][1]["minimo"] is None, "sin aviso calculado, ni barra ni frase"


def test_mandar_a_espera_se_ofrece_en_un_borrador_de_una_lista_abierta():
    lista, pedidos, precios = _armada()

    hoy = la_lista_de_espera(lista, pedidos, precios, None)["proveedores"][0]["hoy"]

    assert all(r["accion"] == "mandar" and r["se_puede"] for r in hoy)
    assert hoy[0]["etiqueta"] == "Mandar a espera"


def test_un_renglon_tachado_no_se_manda_y_dice_por_que():
    lista, pedidos, precios = _armada()
    renglones = list(lista.renglones)
    renglones[0] = _renglon(1, pedido_id=10, capturado=True)
    lista = _lista(renglones)

    hoy = la_lista_de_espera(lista, pedidos, precios, None)["proveedores"][0]["hoy"]

    assert hoy[0]["se_puede"] is False and "tachado" in hoy[0]["motivo_para_no"]
    assert hoy[1]["se_puede"] is True


def test_sacar_de_la_espera_se_ofrece_hacia_un_pedido_en_borrador():
    lista, pedidos, precios = _armada()

    espera = la_lista_de_espera(lista, pedidos, precios, None)["proveedores"][0]["en_espera"]

    assert espera[0]["accion"] == "sacar" and espera[0]["etiqueta"] == "Sacar de la espera"
    assert espera[0]["se_puede"] is True and espera[0]["motivo_para_no"] is None


def test_un_pedido_enviado_no_ofrece_sacar_de_la_espera_hacia_el_ni_mandar_a_el():
    lista, pedidos, precios = _armada(estado_del_pedido=ENVIADO)

    nadro = la_lista_de_espera(lista, pedidos, precios, None)["proveedores"][0]

    assert nadro["frase_del_pedido"] == "Enviado"
    assert nadro["en_espera"][0]["se_puede"] is False
    assert "ya no está en borrador" in nadro["en_espera"][0]["motivo_para_no"]
    assert all(not r["se_puede"] for r in nadro["hoy"])
    assert "ya no está en borrador" in nadro["hoy"][0]["motivo_para_no"]


def test_sin_pedido_de_hoy_lo_que_espera_no_ofrece_sacarse():
    lista, pedidos, precios = _armada()
    sin_levic = [p for p in pedidos if p.proveedor != "levic"]

    levic = la_lista_de_espera(lista, sin_levic, precios, None)["proveedores"][1]

    assert levic["en_espera"][0]["se_puede"] is False
    assert "hoy no hay pedido de LEVIC" in levic["en_espera"][0]["motivo_para_no"]


def test_el_motivo_de_no_sacar_nombra_al_proveedor():
    lista, pedidos, _ = _armada(estado_del_pedido=CANCELADO)
    renglon = _renglon(3, RENGLON_POSPUESTO, proveedor_de_la_espera="nadro")

    motivo = motivo_para_no_sacar(renglon, lista, pedidos[0], "nadro")

    assert "pedido de NADRO" in motivo


def test_con_la_lista_cerrada_se_ve_todo_y_ningun_boton_se_ofrece():
    lista, pedidos, precios = _armada(estado_de_la_lista=CERRADO)

    cuerpo = la_lista_de_espera(lista, pedidos, precios, None)
    renglones = [
        r
        for t in cuerpo["proveedores"]
        for r in t["hoy"] + t["en_espera"]
    ] + cuerpo["sin_proveedor"]

    assert cuerpo["solo_lectura"] is True
    assert cuerpo["motivo_solo_lectura"] == MOTIVO_LISTA_CERRADA
    assert cuerpo["globo"] == 0, "con la lista cerrada la espera ya es de la siguiente"
    assert len(renglones) == 5, "se ve todo"
    assert all(r["se_puede"] is False for r in renglones)
    assert all("lista ya no está abierta" in r["motivo_para_no"] for r in renglones)


def test_antes_de_repartir_no_hay_tarjetas_y_se_ofrece_ir_a_repartir():
    lista = _lista([_renglon(1), _renglon(2, RENGLON_POSPUESTO)])

    cuerpo = la_lista_de_espera(lista, [], {}, None)

    assert cuerpo["repartida"] is False
    assert cuerpo["motivo"] == MOTIVO_SIN_REPARTIR
    assert cuerpo["ir_a_repartir"] is True
    assert cuerpo["proveedores"] == [] and cuerpo["sin_proveedor"] == []


def test_una_lista_cerrada_sin_repartir_no_ofrece_repartir():
    cuerpo = la_lista_de_espera(_lista([_renglon(1)], CERRADO), [], {}, None)

    assert cuerpo["motivo"] == MOTIVO_CERRADA_SIN_REPARTIR
    assert cuerpo["ir_a_repartir"] is False


def test_el_globo_cuenta_lo_pospuesto_de_la_lista_abierta():
    lista, pedidos, precios = _armada()

    assert la_lista_de_espera(lista, pedidos, precios, None)["globo"] == 3


def test_sin_proveedor_ofrece_los_cuatro_con_su_precio_de_hoy():
    lista, pedidos, precios = _armada()

    [sin] = la_lista_de_espera(lista, pedidos, precios, None)["sin_proveedor"]

    assert sin["accion"] == "elegir" and sin["se_puede"] is True
    assert [o["proveedor"] for o in sin["opciones"]] == list(PROVEEDORES_CONOCIDOS)
    por_proveedor = {o["proveedor"]: o["frase_del_precio"] for o in sin["opciones"]}
    assert por_proveedor == {
        "nadro": "$30.00", "levic": FRASE_SIN_PRECIO,
        "vicma": FRASE_SIN_PRECIO, "quepharma": FRASE_SIN_PRECIO,
    }


def test_un_proveedor_de_espera_que_no_se_conoce_no_se_cae_de_la_pantalla():
    lista = _lista([_renglon(1, RENGLON_POSPUESTO, proveedor_de_la_espera="otro")])

    [sin] = la_lista_de_espera(lista, [_pedido(10, "nadro")], {}, None)["sin_proveedor"]

    assert sin["se_puede"] is False and sin["motivo_para_no"] == MOTIVO_PROVEEDOR_DESCONOCIDO


def test_el_pedido_vacio_sigue_en_su_tarjeta_y_lo_descartado_no_cuenta():
    # Un descartado dentro del pedido no se cuenta ni se muestra.
    from dataclasses import replace

    descartado = replace(
        _renglon(1, pedido_id=10),
        estado="descartado",
        descartado_por=CORREO,
        descartado_en=ARMADO,
    )
    lista = _lista([descartado])

    nadro = la_lista_de_espera(lista, [_pedido(10, "nadro")], {}, None)["proveedores"][0]

    assert nadro["hoy"] == [] and nadro["pedido_id"] == 10


def test_el_estado_del_pedido_se_dice_con_palabras():
    assert frase_del_estado_del_pedido(None) == "Sin pedido hoy"
    assert frase_del_estado_del_pedido(_pedido(1, "nadro")) == "En borrador"
    assert frase_del_estado_del_pedido(_pedido(1, "nadro", ENVIADO)) == "Enviado"


def test_una_lista_que_no_hay_trae_su_motivo_y_ninguna_tarjeta():
    cuerpo = lista_que_no_hay(MOTIVO_SIN_LISTA)

    assert cuerpo["ok"] is True and cuerpo["hay_lista"] is False
    assert cuerpo["motivo"] == MOTIVO_SIN_LISTA and cuerpo["globo"] == 0
    assert cuerpo["proveedores"] == []


# ==========================================================================
# 2. LO GUARDADO — el doble y la sentencia
# ==========================================================================


def _renglon_del_catalogo(producto_id: int, cantidad: int = 5) -> Renglon:
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


def _con_uno_en_espera(almacenamiento, proveedor_de_la_espera=None, estado_de_la_lista=None):
    lista = almacenamiento.insertar_la_lista(
        NEGOCIO, HOY, Ventana(HOY, HOY), [_renglon_del_catalogo(1), _renglon_del_catalogo(2)]
    )
    [uno, otro] = [r.renglon_id for r in lista.renglones]
    almacenamiento.posponer(NEGOCIO, uno, CORREO)
    if proveedor_de_la_espera:
        almacenamiento._renglon_por_id(uno)[0]["proveedor_de_la_espera"] = proveedor_de_la_espera
    if estado_de_la_lista:
        almacenamiento._por_id(lista.pedido_sugerido_id)["estado"] = estado_de_la_lista
    return uno, otro


def test_el_doble_sigue_cumpliendo_la_interfaz():
    assert isinstance(AlmacenamientoFalso(), AlmacenamientoDelPedido)
    assert hasattr(AlmacenamientoDelPedido, "elegir_proveedor_de_la_espera")


def test_el_doble_guarda_la_espera_y_la_eleccion_firmada_y_el_renglon_sigue_en_espera():
    almacenamiento = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(almacenamiento)

    lista = almacenamiento.elegir_proveedor_de_la_espera(NEGOCIO, uno, "levic", OTRO)

    r = next(r for r in lista.renglones if r.renglon_id == uno)
    assert r.estado == RENGLON_POSPUESTO, "sigue en espera"
    assert r.proveedor_de_la_espera == "levic"
    # La firma es la de la elección de siempre: quién y cuándo.
    assert (r.proveedor_elegido, r.elegido_por) == ("levic", OTRO)
    assert r.elegido_en is not None
    # Y quien lo mandó a espera sigue siendo quien lo mandó.
    assert r.pospuesto_por == CORREO
    assert r.pedido_id is None


def test_el_doble_no_toca_lo_que_ya_tiene_proveedor():
    almacenamiento = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(almacenamiento, proveedor_de_la_espera="nadro")

    assert almacenamiento.elegir_proveedor_de_la_espera(NEGOCIO, uno, "levic", OTRO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, uno).proveedor_de_la_espera == "nadro"
    assert almacenamiento.leer_renglon(NEGOCIO, uno).proveedor_elegido is None


def test_el_doble_solo_elige_a_un_renglon_en_espera():
    almacenamiento = AlmacenamientoFalso()
    _, abierto = _con_uno_en_espera(almacenamiento)

    assert almacenamiento.elegir_proveedor_de_la_espera(NEGOCIO, abierto, "levic", OTRO) is None
    assert almacenamiento.leer_renglon(NEGOCIO, abierto).proveedor_elegido is None


def test_el_doble_exige_la_lista_abierta_y_el_negocio():
    cerrada = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(cerrada, estado_de_la_lista=CERRADO)
    assert cerrada.elegir_proveedor_de_la_espera(NEGOCIO, uno, "levic", OTRO) is None

    abierta = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(abierta)
    assert abierta.elegir_proveedor_de_la_espera("otro_negocio", uno, "levic", OTRO) is None
    assert abierta.elegir_proveedor_de_la_espera(NEGOCIO, 9999, "levic", OTRO) is None


def test_el_doble_se_niega_como_la_tabla_a_una_firma_vacia():
    almacenamiento = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(almacenamiento)

    with pytest.raises(ValueError):
        almacenamiento.elegir_proveedor_de_la_espera(NEGOCIO, uno, "levic", "")
    assert almacenamiento.leer_renglon(NEGOCIO, uno).proveedor_de_la_espera is None


def test_el_doble_falla_como_la_base_cuando_se_le_pide():
    almacenamiento = AlmacenamientoFalso()
    uno, _ = _con_uno_en_espera(almacenamiento)
    almacenamiento.falla = RuntimeError("caída")

    with pytest.raises(RuntimeError):
        almacenamiento.elegir_proveedor_de_la_espera(NEGOCIO, uno, "levic", OTRO)


def _sql(nombre: str) -> str:
    return " ".join(str(getattr(modulo_almacenamiento, nombre)).split())


def test_la_sentencia_pone_la_espera_y_la_eleccion_juntas_en_un_solo_update():
    sql = _sql("_ELEGIR_PROVEEDOR_DE_LA_ESPERA")

    assert sql.startswith("update pedidos.renglon as r set proveedor_de_la_espera = :proveedor,")
    assert "proveedor_elegido = :proveedor" in sql
    assert "elegido_por = :quien" in sql
    # La hora la pone la base, no Python.
    assert "elegido_en = now()" in sql and ":elegido_en" not in sql
    assert "returning r.renglon_id, r.pedido_sugerido_id" in sql


def test_las_tres_condiciones_viven_en_el_where_y_no_en_un_if():
    sql = _sql("_ELEGIR_PROVEEDOR_DE_LA_ESPERA")
    donde = sql.split(" where ", 1)[1]

    assert "r.negocio = :negocio" in donde
    assert "r.renglon_id = :renglon_id" in donde
    assert "r.estado = 'pospuesto'" in donde
    assert "r.proveedor_de_la_espera is null" in donde
    assert "p.estado = 'abierto'" in donde
    # El renglón sigue en espera: la sentencia no toca su estado ni su pedido.
    cambios = sql.split(" set ", 1)[1].split(" from ", 1)[0]
    assert "estado" not in cambios.replace("proveedor_elegido", "").replace(
        "proveedor_de_la_espera", ""
    )
    assert "pedido_id" not in cambios


def test_no_hay_migracion_nueva_para_esto():
    """Las columnas son las de la 0020 y la firma es la de la elección: no hace
    falta una 0022."""
    from pathlib import Path

    carpeta = Path(__file__).resolve().parent.parent / "sql" / "migraciones"
    assert sorted(p.name[:4] for p in carpeta.glob("*.sql"))[-1] == "0021"


# ==========================================================================
# 3. LA RUTA, de punta a punta
# ==========================================================================


def _venta(n: int) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=HOY, producto_id=n, cantidad=3, importe=30.0, costo=18.0, utilidad=12.0
    )


def _producto(n: int) -> Producto:
    return Producto(
        producto_id=n,
        clave=f"750100000{n:04d}",
        descripcion=f"PRODUCTO {n}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=0.0,
        esta_activo=True,
        es_granel=False,
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


def _firma(correo: str = CORREO) -> dict:
    return {"Cf-Access-Authenticated-User-Email": correo}


def _abrir(cliente, almacen, productos: int = 4) -> dict:
    almacen.catalogo_en_memoria = [_producto(n) for n in range(1, productos + 1)]
    almacen.ventas_en_memoria = [_venta(n) for n in range(1, productos + 1)]
    return cliente.get(RUTA).json()


def _preciar(almacenamiento, lista: dict, producto: int, proveedor: str, precio: str) -> int:
    renglon = next(r for r in lista["renglones"] if r["producto_id"] == producto)
    almacenamiento.guardar_precios(
        NEGOCIO, renglon["renglon_id"], [_lectura(proveedor, precio)]
    )
    return renglon["renglon_id"]


def _repartida(cliente, almacen, almacenamiento) -> dict[str, int]:
    """Cuatro productos: 1 y 2 con precio de NADRO, 3 de LEVIC, 4 sin precio
    de nadie (se queda sin proveedor). Devuelve `{producto: renglon_id}`."""
    lista = _abrir(cliente, almacen)
    ids = {
        1: _preciar(almacenamiento, lista, 1, "nadro", "10.50"),
        2: _preciar(almacenamiento, lista, 2, "nadro", "20.00"),
        3: _preciar(almacenamiento, lista, 3, "levic", "7.25"),
        4: next(r["renglon_id"] for r in lista["renglones"] if r["producto_id"] == 4),
    }
    lista = cliente.get(RUTA).json()
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir")
    assert partida.status_code == 200, partida.text
    return ids


def _la_espera(cliente) -> dict:
    respuesta = cliente.get(ESPERA)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _tarjeta(cuerpo: dict, proveedor: str) -> dict:
    return next(t for t in cuerpo["proveedores"] if t["proveedor"] == proveedor)


def _ids(renglones: list[dict]) -> list[int]:
    return [r["renglon_id"] for r in renglones]


def _mandar(cliente, renglon_id: int, correo: str = CORREO):
    return cliente.post(f"/api/renglon/{renglon_id}/posponer", headers=_firma(correo))


def _sacar(cliente, renglon_id: int):
    return cliente.post(f"/api/renglon/{renglon_id}/devolver-pospuesto", headers=_firma())


def _elegir(cliente, renglon_id: int, proveedor: str, correo: str = OTRO):
    return cliente.post(
        f"/api/renglon/{renglon_id}/proveedor-de-la-espera",
        json={"proveedor": proveedor},
        headers=_firma(correo),
    )


# --- GET /api/lista-de-espera


def test_sin_una_sola_venta_no_hay_lista_y_se_dice_sin_escribir_nada(cliente, almacenamiento):
    cuerpo = _la_espera(cliente)

    assert cuerpo["ok"] is True and cuerpo["hay_lista"] is False
    assert cuerpo["motivo"] == MOTIVO_SIN_VENTAS
    assert almacenamiento.listas == []


def test_la_lista_que_nadie_ha_abierto_no_se_abre_desde_aqui(cliente, almacen, almacenamiento):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(1)]

    cuerpo = _la_espera(cliente)

    assert cuerpo["hay_lista"] is False and cuerpo["motivo"] == MOTIVO_SIN_LISTA
    assert almacenamiento.listas == [], "leer no abre el día"


def test_antes_de_repartir_dice_que_primero_hay_que_repartir_con_su_boton(
    cliente, almacen, almacenamiento
):
    _abrir(cliente, almacen)

    cuerpo = _la_espera(cliente)

    assert cuerpo["repartida"] is False and cuerpo["motivo"] == MOTIVO_SIN_REPARTIR
    assert cuerpo["ir_a_repartir"] is True and cuerpo["proveedores"] == []


def test_repartida_trae_una_tarjeta_por_proveedor_con_su_pedido_y_su_precio_de_hoy(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)

    cuerpo = _la_espera(cliente)
    nadro, levic, vicma, quepharma = cuerpo["proveedores"]

    assert [t["nombre"] for t in cuerpo["proveedores"]] == [
        "NADRO", "LEVIC", "VICMA", "QuePharma",
    ]
    assert set(_ids(nadro["hoy"])) == {ids[1], ids[2]}
    assert _ids(levic["hoy"]) == [ids[3]]
    assert {r["frase_del_precio"] for r in nadro["hoy"]} == {"$10.50", "$20.00"}
    assert levic["hoy"][0]["frase_del_precio"] == "$7.25"
    assert nadro["frase_del_pedido"] == "En borrador"
    assert nadro["pedido_id"] is not None
    assert vicma["pedido_id"] is None and vicma["frase_del_pedido"] == "Sin pedido hoy"
    assert quepharma["hoy"] == []
    assert cuerpo["sin_proveedor"] == []


def test_el_total_es_el_mismo_que_usa_la_captura_para_enviar(cliente, almacen, almacenamiento):
    _repartida(cliente, almacen, almacenamiento)
    pedidos = cliente.get(RUTA).json()["pedidos"]
    nadro_captura = next(p for p in pedidos if p["proveedor"] == "nadro")

    nadro = _tarjeta(_la_espera(cliente), "nadro")

    assert nadro["total"] == nadro_captura["total"]
    assert nadro["frase_del_total"] == nadro_captura["total"]["dinero"]


def test_sin_minimo_capturado_no_hay_barra_y_dice_su_frase(cliente, almacen, almacenamiento):
    _repartida(cliente, almacen, almacenamiento)

    minimo = _tarjeta(_la_espera(cliente), "nadro")["minimo"]

    assert minimo["estado"] == "sin_capturar" and minimo["frase"] == "sin mínimo capturado"
    assert minimo["progreso"] is None


def test_con_minimo_cero_dice_que_no_tiene_y_tampoco_hay_barra(cliente, almacen, almacenamiento):
    _repartida(cliente, almacen, almacenamiento)
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", D("0"), False, CORREO)

    minimo = _tarjeta(_la_espera(cliente), "nadro")["minimo"]

    assert minimo["estado"] == "sin_minimo" and minimo["frase"] == "no tiene mínimo"
    assert minimo["progreso"] is None


def test_la_barra_se_llena_hacia_el_minimo_en_su_base_y_baja_al_mandar_a_espera(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)
    nadro = _tarjeta(_la_espera(cliente), "nadro")
    por_renglon = {r["renglon_id"]: D(r["precio"]) * r["piezas"] for r in nadro["hoy"]}
    total = sum(por_renglon.values())
    # Un mínimo del doble del total, sin IVA: la barra va a la mitad.
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", total * 2, False, CORREO)

    antes = _tarjeta(_la_espera(cliente), "nadro")["minimo"]
    assert antes["estado"] == "no_llega" and antes["progreso"] == 50
    assert antes["comparado"] == f"${total:,.2f}"

    # Mandar a espera el renglón más caro baja el total, y la barra con él.
    assert _mandar(cliente, ids[2]).status_code == 200
    despues = _tarjeta(_la_espera(cliente), "nadro")["minimo"]
    quedan = por_renglon[ids[1]]
    assert despues["progreso"] == int(quedan * 100 // (total * 2))
    assert despues["progreso"] < antes["progreso"]


def test_con_el_minimo_cumplido_la_barra_va_llena_y_dice_que_llega(
    cliente, almacen, almacenamiento
):
    _repartida(cliente, almacen, almacenamiento)
    almacenamiento.guardar_el_minimo(NEGOCIO, "levic", D("1"), False, CORREO)

    minimo = _tarjeta(_la_espera(cliente), "levic")["minimo"]

    assert minimo["estado"] == "llega" and minimo["progreso"] == 100


def test_un_minimo_con_iva_se_compara_en_su_base_y_no_con_el_total_sin_iva(
    cliente, almacen, almacenamiento
):
    """Cuatro productos con tasa conocida: el IVA se lleva renglón por renglón."""
    _repartida(cliente, almacen, almacenamiento)
    almacen.tasas_en_memoria = {n: D("0.16") for n in (1, 2, 3, 4)}
    nadro = _tarjeta(_la_espera(cliente), "nadro")
    total = sum(D(r["precio"]) * r["piezas"] for r in nadro["hoy"])
    con_iva = sum((D(r["precio"]) * r["piezas"] * D("1.16")).quantize(D("0.01"))
                  for r in nadro["hoy"])
    # Un mínimo CON IVA que el total sin IVA no alcanza, pero con IVA sí.
    minimo = (total + con_iva) / 2
    almacenamiento.guardar_el_minimo(NEGOCIO, "nadro", minimo.quantize(D("0.01")), True, CORREO)

    aviso = _tarjeta(_la_espera(cliente), "nadro")["minimo"]

    assert aviso["base"] == "con IVA"
    assert aviso["estado"] == "llega" and aviso["progreso"] == 100


def test_el_minimo_que_no_se_pudo_leer_no_se_pinta_como_sin_capturar(
    cliente, almacen, almacenamiento, monkeypatch
):
    _repartida(cliente, almacen, almacenamiento)

    def sin_leer(negocio):
        raise RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    monkeypatch.setattr(almacenamiento, "minimos_de_los_proveedores", sin_leer)
    respuesta = cliente.get(ESPERA)

    assert "SECRETO" not in respuesta.text
    minimo = _tarjeta(respuesta.json(), "nadro")["minimo"]
    assert minimo["estado"] == "sin_leer" and minimo["progreso"] is None


def test_los_precios_que_no_se_pudieron_leer_se_dicen_y_no_son_sin_precio(
    cliente, almacen, almacenamiento, monkeypatch
):
    _repartida(cliente, almacen, almacenamiento)

    def sin_leer(negocio, lista_id):
        raise RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    monkeypatch.setattr(almacenamiento, "precios_de_la_lista", sin_leer)
    respuesta = cliente.get(ESPERA)

    assert "SECRETO" not in respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    nadro = _tarjeta(cuerpo, "nadro")
    assert {r["frase_del_precio"] for r in nadro["hoy"]} == {FRASE_PRECIO_SIN_LEER}
    assert nadro["total"] is None


def test_mandar_a_espera_con_la_ruta_de_siempre_cambia_el_renglon_de_bloque(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)

    assert _mandar(cliente, ids[1]).status_code == 200
    nadro = _tarjeta(_la_espera(cliente), "nadro")

    assert _ids(nadro["hoy"]) == [ids[2]]
    assert _ids(nadro["en_espera"]) == [ids[1]]
    assert nadro["frase_del_total"] == "$60.00", "el total de hoy ya no cuenta lo que espera"


def test_lo_que_espera_se_ve_con_el_precio_de_hoy_y_no_con_el_de_cuando_se_mando(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)
    _mandar(cliente, ids[1])
    assert _tarjeta(_la_espera(cliente), "nadro")["en_espera"][0]["frase_del_precio"] == "$10.50"

    # Después de mandarlo, NADRO contesta otro precio: el último consultado.
    almacenamiento.guardar_precios(NEGOCIO, ids[1], [_lectura("nadro", "12.00")])

    espera = _tarjeta(_la_espera(cliente), "nadro")["en_espera"]
    assert espera[0]["frase_del_precio"] == "$12.00"


def test_sacar_de_la_espera_con_la_ruta_de_siempre_regresa_al_pedido(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)
    _mandar(cliente, ids[1])

    respuesta = _sacar(cliente, ids[1])
    assert respuesta.status_code == 200
    assert respuesta.json()["frase_de_sacar_de_la_espera"].startswith("Volvió al pedido de NADRO")

    nadro = _tarjeta(_la_espera(cliente), "nadro")
    assert set(_ids(nadro["hoy"])) == {ids[1], ids[2]} and nadro["en_espera"] == []


def test_un_pedido_enviado_no_ofrece_sacar_de_la_espera_hacia_el(cliente, almacen, almacenamiento):
    ids = _repartida(cliente, almacen, almacenamiento)
    _mandar(cliente, ids[1])
    pedido_id = _tarjeta(_la_espera(cliente), "nadro")["pedido_id"]
    enviado = cliente.post(f"/api/pedido/{pedido_id}/enviar", headers=_firma())
    assert enviado.status_code == 200, enviado.text

    nadro = _tarjeta(_la_espera(cliente), "nadro")

    assert nadro["frase_del_pedido"] == "Enviado"
    assert nadro["en_espera"][0]["se_puede"] is False
    assert "ya no está en borrador" in nadro["en_espera"][0]["motivo_para_no"]
    # Y lo que ya se envió tampoco se manda a espera desde aquí.
    assert all(r["se_puede"] is False for r in nadro["hoy"])


def test_un_renglon_tachado_viaja_con_su_boton_apagado(cliente, almacen, almacenamiento):
    ids = _repartida(cliente, almacen, almacenamiento)
    tachado = cliente.post(
        f"/api/renglon/{ids[1]}/capturado", json={"capturado": True}, headers=_firma()
    )
    assert tachado.status_code == 200

    hoy = {r["renglon_id"]: r for r in _tarjeta(_la_espera(cliente), "nadro")["hoy"]}

    assert hoy[ids[1]]["se_puede"] is False and "tachado" in hoy[ids[1]]["motivo_para_no"]
    assert hoy[ids[2]]["se_puede"] is True


def test_con_la_lista_cerrada_se_ve_todo_y_no_se_ofrece_ninguna_accion(
    cliente, almacen, almacenamiento
):
    ids = _repartida(cliente, almacen, almacenamiento)
    _mandar(cliente, ids[1])
    almacenamiento._por_id(almacenamiento.leer(NEGOCIO, HOY).pedido_sugerido_id)["estado"] = CERRADO

    cuerpo = _la_espera(cliente)

    assert cuerpo["solo_lectura"] is True and cuerpo["globo"] == 0
    nadro = _tarjeta(cuerpo, "nadro")
    assert _ids(nadro["hoy"]) == [ids[2]] and _ids(nadro["en_espera"]) == [ids[1]]
    assert not any(r["se_puede"] for r in nadro["hoy"] + nadro["en_espera"])


def test_el_globo_cuenta_lo_que_espera_y_viene_del_servidor(cliente, almacen, almacenamiento):
    ids = _repartida(cliente, almacen, almacenamiento)
    assert _la_espera(cliente)["globo"] == 0

    _mandar(cliente, ids[1])
    _mandar(cliente, ids[3])

    assert _la_espera(cliente)["globo"] == 2
    # La lista del día dice lo mismo, para el globo que está al abrir la página.
    assert cliente.get(RUTA).json()["pospuestos"] == 2


def test_el_almacen_caido_es_un_hueco_con_que_hacer_y_el_error_no_viaja(
    cliente, almacen
):
    almacen.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = cliente.get(ESPERA)

    assert "SECRETO" not in respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False and cuerpo["que_hacer"]
    assert "RuntimeError" in cuerpo["detalle"]


def test_el_almacenamiento_caido_es_un_hueco_con_que_hacer_y_no_una_lista_vacia(
    cliente, almacen, almacenamiento
):
    _abrir(cliente, almacen)
    almacenamiento.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = cliente.get(ESPERA)

    assert "SECRETO" not in respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False and cuerpo["que_hacer"] and "proveedores" not in cuerpo


# --- la tarjeta «Sin proveedor» y POST /api/renglon/{id}/proveedor-de-la-espera


def _con_uno_sin_proveedor(cliente, almacen, almacenamiento) -> dict[int, int]:
    ids = _repartida(cliente, almacen, almacenamiento)
    # El producto 4 nadie lo cotizó: se queda sin repartir, y al mandarlo a espera
    # nadie sabe a quién se le iba a pedir.
    assert _mandar(cliente, ids[4]).status_code == 200
    return ids


def test_lo_que_espera_sin_proveedor_va_en_la_quinta_tarjeta_con_el_selector(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    cuerpo = _la_espera(cliente)

    [sin] = cuerpo["sin_proveedor"]
    assert sin["renglon_id"] == ids[4] and sin["accion"] == "elegir" and sin["se_puede"] is True
    assert [o["nombre"] for o in sin["opciones"]] == ["NADRO", "LEVIC", "VICMA", "QuePharma"]
    assert all(t["en_espera"] == [] for t in cuerpo["proveedores"])
    assert cuerpo["globo"] == 1


def test_elegir_guarda_la_espera_firmada_y_mueve_el_renglon_a_la_tarjeta_de_ese_proveedor(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    respuesta = _elegir(cliente, ids[4], "levic")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["ok"] is True
    guardado = almacenamiento.leer_renglon(NEGOCIO, ids[4])
    assert guardado.estado == RENGLON_POSPUESTO, "sigue en espera"
    assert guardado.proveedor_de_la_espera == "levic"
    assert (guardado.proveedor_elegido, guardado.elegido_por) == ("levic", OTRO)

    cuerpo = _la_espera(cliente)
    assert cuerpo["sin_proveedor"] == []
    assert _ids(_tarjeta(cuerpo, "levic")["en_espera"]) == [ids[4]]
    assert cuerpo["globo"] == 1


def test_el_selector_se_puede_elegir_a_alguien_que_no_dio_precio(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    assert _elegir(cliente, ids[4], "quepharma").status_code == 200

    quepharma = _tarjeta(_la_espera(cliente), "quepharma")
    assert quepharma["en_espera"][0]["frase_del_precio"] == FRASE_SIN_PRECIO


def test_despues_de_elegir_sacar_de_la_espera_vuelve_al_pedido_de_ese_proveedor(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)
    _elegir(cliente, ids[4], "levic")

    assert _sacar(cliente, ids[4]).status_code == 200

    levic = _tarjeta(_la_espera(cliente), "levic")
    assert set(_ids(levic["hoy"])) == {ids[3], ids[4]} and levic["en_espera"] == []


def test_elegir_a_alguien_sin_pedido_de_hoy_deja_el_renglon_esperando_sin_boton_de_sacar(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)
    _elegir(cliente, ids[4], "vicma")

    vicma = _tarjeta(_la_espera(cliente), "vicma")

    assert vicma["en_espera"][0]["se_puede"] is False
    assert "hoy no hay pedido de VICMA" in vicma["en_espera"][0]["motivo_para_no"]


def test_la_respuesta_de_elegir_trae_los_pedidos_recalculados(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    cuerpo = _elegir(cliente, ids[4], "levic").json()

    assert cuerpo["renglon"]["renglon_id"] == ids[4]
    assert {p["proveedor"] for p in cuerpo["pedidos"]} == {"nadro", "levic"}


def test_elegir_un_proveedor_que_no_se_consulta_es_422_y_no_toca_nada(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    respuesta = _elegir(cliente, ids[4], "farmacias_del_ahorro")

    assert respuesta.status_code == 422 and respuesta.json()["ok"] is False
    assert "NADRO, LEVIC, VICMA, QuePharma" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, ids[4]).proveedor_de_la_espera is None


def test_elegir_a_un_renglon_que_no_espera_es_409_con_el_motivo_real(
    cliente, almacen, almacenamiento
):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    respuesta = _elegir(cliente, ids[1], "levic")

    assert respuesta.status_code == 409 and respuesta.json()["ok"] is False
    assert "no está en espera" in respuesta.json()["detalle"]
    assert almacenamiento.leer_renglon(NEGOCIO, ids[1]).proveedor_elegido is None


def test_elegir_otra_vez_es_409_y_no_pisa_la_primera_eleccion(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)
    assert _elegir(cliente, ids[4], "levic", OTRO).status_code == 200

    segunda = _elegir(cliente, ids[4], "vicma", CORREO)

    assert segunda.status_code == 409
    assert "ya tiene proveedor" in segunda.json()["detalle"]
    guardado = almacenamiento.leer_renglon(NEGOCIO, ids[4])
    assert (guardado.proveedor_de_la_espera, guardado.elegido_por) == ("levic", OTRO)


def test_elegir_con_la_lista_cerrada_es_409_con_su_motivo(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)
    almacenamiento._por_id(almacenamiento.leer(NEGOCIO, HOY).pedido_sugerido_id)["estado"] = CERRADO

    respuesta = _elegir(cliente, ids[4], "levic")

    assert respuesta.status_code == 409
    assert "la lista ya no está abierta" in respuesta.json()["detalle"]


def test_elegir_sin_encabezado_de_access_firma_sin_identificar(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)

    respuesta = cliente.post(
        f"/api/renglon/{ids[4]}/proveedor-de-la-espera", json={"proveedor": "levic"}
    )

    assert respuesta.status_code == 200
    assert almacenamiento.leer_renglon(NEGOCIO, ids[4]).elegido_por == "sin-identificar"


def test_el_error_de_la_base_al_elegir_no_viaja_al_navegador(cliente, almacen, almacenamiento):
    ids = _con_uno_sin_proveedor(cliente, almacen, almacenamiento)
    almacenamiento.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = _elegir(cliente, ids[4], "levic")

    assert "SECRETO" not in respuesta.text
    assert respuesta.json()["ok"] is False and respuesta.json()["que_hacer"]


# ==========================================================================
# 4. LA ESTÁTICA DEL JAVASCRIPT
# ==========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_la_entrada_va_debajo_de_la_lista_del_dia_con_su_globo_y_su_panel_escondido():
    pantalla = pantalla_completa()
    script = _script()

    assert pantalla.index('id="pestana-pedido"') < pantalla.index('id="pestana-espera"')
    assert pantalla.index('id="pestana-espera"') < pantalla.index('id="pestana-camino"')
    assert 'id="cuenta-espera"' in pantalla
    [panel] = re.findall(r'<section id="panel-espera"[^>]*>', pantalla)
    assert " hidden" in panel
    pestanas = script.split("const PESTANAS = [", 1)[1].split("]", 1)[0]
    assert pestanas.index("'pedido'") < pestanas.index("'espera'") < pestanas.index("'camino'")
    # Se lee cada vez que se abre.
    assert "if (elegida === 'espera') cargarListaDeEspera();" in cuerpo_de_funcion(
        script, "const mostrarPestana"
    )


def test_el_globo_se_pinta_con_el_numero_del_servidor_al_cargar_la_lista_del_dia():
    script = _script()
    globo = cuerpo_de_funcion(script, "const pintarCuentaDeLaEspera")
    repintar = cuerpo_de_funcion(script, "const repintar = () => {")

    assert "pintarCuenta('espera', estado === 'abierto' ? pospuestos : 0, 'gris')" in globo
    assert "pintarCuentaDeLaEspera(datos.pospuestos, datos.estado);" in repintar
    # Y al abrir la pantalla, con el globo que dice su propia respuesta.
    assert "pintarCuenta('espera', datos.globo, 'gris');" in cuerpo_de_funcion(
        script, "async function cargarListaDeEspera"
    )


def test_la_pantalla_lee_y_mueve_por_las_rutas_que_ya_existen_y_la_nueva():
    script = _script()
    leer = cuerpo_de_funcion(script, "async function cargarListaDeEspera")
    mover = cuerpo_de_funcion(script, "async function moverDesdeLaEspera")
    boton = cuerpo_de_funcion(script, "const botonDeUnRenglonDeEspera")
    selector = cuerpo_de_funcion(script, "const selectorDeProveedorDeLaEspera")

    assert "fetch('/api/lista-de-espera')" in leer
    assert "fetch('/api/renglon/' + renglonId + ruta, peticion)" in mover
    assert "{ mandar: '/posponer', sacar: '/devolver-pospuesto' }" in boton
    assert "'/proveedor-de-la-espera', { proveedor: o.proveedor }" in selector
    # Al volver, la pantalla vuelve a decir lo que hay, salga como salga.
    assert "await cargarListaDeEspera();" in mover
    assert "notaDeFalla('espera-accion', respuesta);" in mover
    assert "'al_guardar'" in mover
    # Lo que se movió deja vieja a la lista del día que está en la pantalla.
    assert "LISTA_DEL_DIA_VIEJA = true;" in mover


def test_el_boton_apagado_sigue_siendo_boton_con_el_motivo_del_servidor():
    script = _script()
    boton = cuerpo_de_funcion(script, "const botonDeUnRenglonDeEspera")
    apagar = cuerpo_de_funcion(script, "const apagarBoton")

    assert "if (!r.se_puede) apagarBoton(boton, r.motivo_para_no);" in boton
    assert "boton.title = motivo || '';" in apagar
    assert "aria-disabled" in apagar


def test_el_javascript_pinta_el_precio_y_el_total_que_dice_el_servidor_y_no_hace_cuentas():
    script = _script()
    espera = script.split("// ------------------------------------------------------- Lista de espera", 1)[1]
    espera = espera.split("// ---------------------------------------------------------------- Sesiones", 1)[0]

    assert "r.frase_del_precio" in espera and "t.frase_del_total" in espera
    assert "t.minimo.frase" in espera
    # Sin precio se ve con su palabra; nunca se escribe un cero.
    assert "r.precio === null ? ' nose' : ''" in espera
    assert "$0.00" not in espera and "'sin precio'" not in espera
    # Nada de aritmética ni de comparar dinero en el navegador.
    for prohibido in ("parseFloat", "Number(", "toFixed", ".reduce(", "parseInt", "Math."):
        assert prohibido not in espera, prohibido


def test_la_barra_se_dibuja_con_el_llenado_del_servidor_y_sin_minimo_no_se_pinta():
    cabeza = cuerpo_de_funcion(_script(), "const cabezaDeLaTarjeta")

    assert "if (t.minimo.progreso !== null) {" in cabeza
    assert "relleno.style.width = t.minimo.progreso + '%';" in cabeza
    assert "t.minimo.estado === 'llega' ? ' completa' : ''" in cabeza
    assert "aria-valuenow" in cabeza and "role', 'progressbar'" in cabeza
    # La frase del mínimo se pinta aunque no haya barra: es lo que dice «sin mínimo capturado».
    assert cabeza.index("t.minimo.frase") > cabeza.index("if (t.minimo.progreso !== null) {")
    # El estado de la barra no se decide aquí comparando montos: viene en `estado`.
    assert "t.minimo.comparado" not in cabeza and "t.minimo.falta" not in cabeza


def test_la_cabecera_dice_solo_el_total_y_la_barra():
    cabeza = cuerpo_de_funcion(_script(), "const cabezaDeLaTarjeta")

    assert "total.textContent = t.frase_del_total;" in cabeza
    assert "total.className = 'espera-total' + (t.total && t.total.hay ? '' : ' nose');" in cabeza
    # Ni renglones ni piezas ni parcial en la cabecera.
    assert "t.total.parcial" not in cabeza and "t.total.renglones" not in cabeza


def test_la_tarjeta_tiene_los_dos_bloques_y_la_quinta_es_sin_proveedor():
    script = _script()
    tarjeta = cuerpo_de_funcion(script, "const tarjetaDeEspera")
    sin = cuerpo_de_funcion(script, "const tarjetaSinProveedor")
    pintar = cuerpo_de_funcion(script, "const pintarLaListaDeEspera")

    assert "bloqueDeEspera('Pedido de hoy', t.hoy" in tarjeta
    assert "bloqueDeEspera('En espera', t.en_espera" in tarjeta
    assert "'Sin proveedor'" in sin
    assert "datos.proveedores.forEach((t) => tarjetas.append(tarjetaDeEspera(t)));" in pintar
    assert "if (datos.sin_proveedor.length) tarjetas.append(tarjetaSinProveedor(datos.sin_proveedor));" in pintar
    # El navegador no agrupa: pinta lo que llega, en el orden que llega.
    assert ".filter(" not in tarjeta and ".filter(" not in pintar


def test_el_selector_de_proveedor_es_un_boton_por_cada_opcion_del_servidor():
    selector = cuerpo_de_funcion(_script(), "const selectorDeProveedorDeLaEspera")

    assert "r.opciones.forEach((o) => {" in selector
    assert "o.nombre + ' · ' + o.frase_del_precio" in selector
    assert "if (!r.se_puede) apagarBoton(boton, r.motivo_para_no);" in selector


def test_antes_de_repartir_dice_el_motivo_del_servidor_y_ofrece_ir_a_repartir():
    pintar = cuerpo_de_funcion(_script(), "const pintarLaListaDeEspera")

    assert "if (!datos.repartida) {" in pintar
    assert "frase.textContent = datos.motivo;" in pintar
    assert "if (datos.ir_a_repartir) {" in pintar
    assert "botonDeAccion('Ir a repartir'" in pintar
    assert "IR_A_PASO('repartir');" in pintar
    # Lo de repartir termina antes de pintar tarjetas.
    assert pintar.index("return;") < pintar.index("datos.proveedores.forEach")


def test_con_la_lista_cerrada_se_dice_por_que_y_las_tarjetas_se_pintan_igual():
    pintar = cuerpo_de_funcion(_script(), "const pintarLaListaDeEspera")

    assert "if (datos.solo_lectura) {" in pintar
    assert "cerrada.textContent = datos.motivo_solo_lectura;" in pintar
    assert pintar.index("datos.solo_lectura") < pintar.index("datos.proveedores.forEach")


def test_si_la_lectura_falla_no_se_borra_lo_que_estaba_y_se_dice():
    leer = cuerpo_de_funcion(_script(), "async function cargarListaDeEspera")

    assert "if (!datos.ok) {" in leer
    assert "notaDeFalla('espera-falla', datos);" in leer
    assert leer.index("return;") < leer.index("pintarLaListaDeEspera(datos);")


def test_la_lista_del_dia_se_vuelve_a_leer_al_volver_si_la_espera_movio_algo():
    mostrar = cuerpo_de_funcion(_script(), "const mostrarPestana")

    assert "if (elegida === 'pedido' && LISTA_DEL_DIA_VIEJA) {" in mostrar
    assert "cargarPedido(FECHA_ACTUAL && FECHA_ACTUAL !== FECHA_DE_HOY ? FECHA_ACTUAL : undefined);" in mostrar


def test_el_javascript_no_firma_nada_por_su_cuenta():
    espera = _script().split(
        "// ------------------------------------------------------- Lista de espera", 1
    )[1].split("// ---------------------------------------------------------------- Sesiones", 1)[0]

    for campo in ("elegido_por", "pospuesto_por", "fijado_por"):
        assert campo not in espera, campo


def test_la_hoja_tiene_la_barra_y_los_colores_en_los_dos_temas():
    css = pantalla_completa()

    for regla in (".espera-tarjeta", ".barra-minimo", ".barra-minimo.completa span",
                  ".espera-minimo.avisa", ".espera-renglones .accion.apagado"):
        assert regla in css, regla
    # Los colores son variables del tema (claro y oscuro), no valores escritos aquí.
    bloque = css.split("/* ------------------------------------------------------- Lista de espera", 1)[1]
    bloque = bloque.split("</style>", 1)[0]
    assert "#" not in re.sub(r"/\*.*?\*/", "", bloque, flags=re.S), "colores fijos en la lista de espera"
