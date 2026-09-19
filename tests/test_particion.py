"""Elegir proveedor y partir el sugerido en pedidos (ticket 20), sin Postgres.

Las tres decisiones del ticket son **funciones puras** y por eso casi todo este
archivo no levanta la aplicación:

- `particion.sugerir` / `particion.elegir` — a quién se le pide un renglón, y
  si eso lo decidió una persona o lo propone el sistema.
- `particion.partir` — la lista de trabajo repartida en un pedido por
  proveedor, con sus líneas.
- `PedidoPorArmar.total_sin_iva` — lo que cuesta, o `None` cuando no se puede
  saber.
- `proveedores.leer_el_puente` / `id_en_sicar` — el cruce entre la clave de
  Doyle y el `proveedor_id` de SICAR.

## Las cuatro trampas que este archivo vigila

1. **La sugerencia no es la decisión.** Un renglón donde nadie eligió enseña a
   quién le compraría el sistema, y eso **no** se guarda ni se presenta como
   elegido. El ticket 11 resolvió la misma pregunta con dos columnas; aquí la
   respuesta es distinta a propósito y hay pruebas de las dos mitades.
2. **El empate no se desempata.** `elegir_ganador` devuelve una tupla porque un
   empate son dos opciones; convertirlo en una por orden alfabético sería una
   decisión que nadie tomó.
3. **Un renglón sin precio de ese proveedor se pide igual.** La línea entra,
   marcada, y el total del pedido se vuelve `None` — **nunca la suma de las
   demás, nunca un cero**.
4. **El puente puede faltar.** QuePharma no tiene fila en `marts.dim_proveedor`
   (medido el 2026-09-19), y aun así se le puede pedir: `proveedor_id` queda en
   `NULL` y la pantalla lo dice.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import pytest

from continental.almacenamiento import PrecioDeProveedor, RenglonGuardado
from continental.comparacion import (
    GANADOR_CON_EXISTENCIA,
    GANADOR_UNICO,
    NADIE_CONSULTO,
    NINGUNO_LO_TIENE,
    comparar,
)
from continental.particion import (
    HAY_EMPATE,
    NADIE_A_QUIEN_PEDIRLE,
    SIN_CONSULTARLE,
    SIN_PRECIO_DE_ESE_PROVEEDOR,
    Linea,
    PedidoPorArmar,
    elegir,
    eleccion_como_json,
    particion_como_json,
    partir,
    sugerir,
)
from continental.precios import SESION_CADUCADA
from continental.proveedores import (
    CLAVE_DEL_PUENTE,
    CON_PUENTE,
    SIN_PUENTE,
    estado_del_puente,
    id_en_sicar,
    leer_el_puente,
    los_que_no_estan_en_sicar,
    puente_como_json,
)
from continental.sugerido import Renglon

INSTANTE = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.timezone.utc)

#: El puente tal como quedó medido contra `marts.dim_proveedor` en atlas el
#: 2026-09-19: NADRO es el 1, VICMA el 8, LEVIC el 10 y **QuePharma no está**.
PUENTE = {"nadro": 1, "vicma": 8, "levic": 10}


# ------------------------------------------------------------- utilidades


def _lectura(
    proveedor: str,
    precio: str | None = None,
    existencia: str | None = None,
    motivo: str | None = None,
    renglon_id: int = 1,
) -> PrecioDeProveedor:
    """Una lectura congelada, igual que la de `test_comparacion`.

    Los números entran como **texto** y se convierten a `Decimal` aquí: un
    `float` en una prueba estrenaría en el suite justo el tipo que el DDL
    prohíbe.
    """
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor=proveedor,
        consultado_en=INSTANTE,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="" if existencia is None else existencia,
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _renglon(
    n: int = 1,
    cantidad: int = 3,
    *,
    proveedor_elegido: str | None = None,
    elegido_por: str | None = None,
    cantidad_final: int | None = None,
    estado: str = "abierto",
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=n,
        estado=estado,
        propuesto=Renglon(
            producto_id=n,
            clave=f"750100000{n:04d}",
            descripcion=f"PRODUCTO {n}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=True,
            existencia=1.0,
            dias_de_cobertura=1.0,
            clasificacion="medicamento",
        ),
        cantidad_final=cantidad_final,
        ajustada_por=None if cantidad_final is None else "quien@casa",
        ajustada_en=None if cantidad_final is None else INSTANTE,
        proveedor_elegido=proveedor_elegido,
        elegido_por=elegido_por,
        elegido_en=None if proveedor_elegido is None else INSTANTE,
    )


# ============================================================================
# El puente entre la clave de Doyle y el proveedor_id de SICAR
# ============================================================================


def test_el_puente_traduce_la_clave_de_doyle_al_proveedor_de_sicar():
    """Lo que el ticket no tenía: `nadro` -> 1.

    Hasta aquí la comparación hablaba en claves (`nadro`, `levic`, …) y
    `pedidos.pedido.proveedor_id` en `pro_id` de SICAR, y nada las cruzaba.
    """
    puente = leer_el_puente({"nadro": 1, "vicma": 8, "levic": 10})
    assert puente == PUENTE
    assert id_en_sicar("nadro", puente) == 1
    assert id_en_sicar("levic", puente) == 10


def test_un_proveedor_sin_puente_da_None_y_nunca_un_cero():
    """QuePharma no está en `dim_proveedor`, y eso es un dato, no un fallo.

    **Nunca un cero**, que es lo que haría un `.get(clave, 0)` distraído: un
    cero es un id que no existe y que aun así entra en una columna `bigint`, y
    a partir de ahí todo `join` contra `dim_proveedor` sale vacío sin error.
    """
    assert id_en_sicar("quepharma", PUENTE) is None
    assert los_que_no_estan_en_sicar(PUENTE) == ("quepharma",)


def test_el_estado_del_puente_viaja_como_frase_hecha():
    """La pantalla escribe, no deduce — igual que la certeza del ganador."""
    assert estado_del_puente("nadro", PUENTE) == CON_PUENTE
    assert estado_del_puente("quepharma", PUENTE) == SIN_PUENTE


def test_el_puente_json_trae_los_cuatro_aunque_falte_uno():
    """Los cuatro siempre, como la fila de la comparación.

    Si solo salieran los emparejados, un proveedor sin puente se vería como un
    proveedor que no existe, y son dos cosas distintas (regla 4).
    """
    filas = puente_como_json(PUENTE)
    assert [f["proveedor"] for f in filas] == ["nadro", "levic", "vicma", "quepharma"]
    sin = next(f for f in filas if f["proveedor"] == "quepharma")
    assert sin["proveedor_id"] is None
    assert sin["tiene_puente"] is False
    assert sin["estado"] == SIN_PUENTE


@pytest.mark.parametrize("valor", ["uno", 0, -3, 1.5, None, True])
def test_una_entrada_mal_escrita_se_descarta_con_aviso_y_no_tumba_nada(valor, caplog):
    """Un `nadro: "uno"` deja a NADRO sin puente; no deja a la farmacia sin lista.

    Abortar el arranque por una línea de configuración dejaría sin pedido del
    día; aceptarlo callado metería basura en una columna `bigint`. El estado
    "sin puente" ya se sabe decir y se ve en la pantalla.

    `True` está en la lista a propósito: `bool` es subclase de `int` en Python,
    así que un `nadro: true` del YAML llegaría como `1` — y "sí" no es un
    `proveedor_id`.
    """
    with caplog.at_level(logging.WARNING, logger="continental"):
        puente = leer_el_puente({"nadro": valor})
    assert puente == {}
    assert CLAVE_DEL_PUENTE in caplog.text


def test_una_clave_que_doyle_no_conoce_se_descarta_con_aviso(caplog):
    """Un puente hacia alguien a quien nadie le pregunta el precio no cruza nada."""
    with caplog.at_level(logging.WARNING, logger="continental"):
        puente = leer_el_puente({"farmasana": 7, "nadro": 1})
    assert puente == {"nadro": 1}
    assert "farmasana" in caplog.text


def test_sin_puente_configurado_no_truena_y_deja_a_todos_sin_id():
    """Una instalación que todavía no configuró el mapa puede pedir igual."""
    assert leer_el_puente(None) == {}
    assert leer_el_puente({}) == {}
    assert len(los_que_no_estan_en_sicar({})) == 4


# ============================================================================
# La sugerencia: el más barato con existencia, por omisión
# ============================================================================


def test_el_sistema_sugiere_al_mas_barato_con_existencia():
    """La primera casilla: *por omisión se sugiere el más barato con existencia*."""
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("levic", "86.05", "12"),
            _lectura("vicma", "60.00", "0"),
        ]
    )
    proveedor, certeza, empatados = sugerir(comparacion)
    assert proveedor == "levic"
    assert certeza == GANADOR_CON_EXISTENCIA
    assert empatados == ()


def test_con_empate_no_hay_sugerencia_y_los_empatados_se_ven():
    """El sistema **no desempata**, y esa es una decisión heredada del 14.

    `Ganador.proveedores` es una tupla porque un empate son dos opciones;
    elegir una por orden alfabético diría "éste es el más barato" sobre algo
    que el sistema no decidió.
    """
    comparacion = comparar(
        [_lectura("nadro", "86.05", "10"), _lectura("levic", "86.05", "10")]
    )
    proveedor, _certeza, empatados = sugerir(comparacion)
    assert proveedor is None
    assert empatados == ("levic", "nadro")

    eleccion = elegir(_renglon(), comparacion)
    assert eleccion.hay is False
    assert eleccion.motivo == HAY_EMPATE
    assert eleccion.empatados == ("levic", "nadro")


@pytest.mark.parametrize(
    "lecturas, motivo_del_ganador",
    [
        ([], NADIE_CONSULTO),
        ([_lectura("nadro", "86.05", "0")], NINGUNO_LO_TIENE),
    ],
)
def test_sin_ganador_no_hay_a_quien_pedirle_y_se_dice(lecturas, motivo_del_ganador):
    """Sin ganador, el renglón no se reparte a nadie **y se cuenta**.

    El motivo fino —nadie consultó, ninguno lo tiene— sigue viviendo en
    `Comparacion.ganador.motivo` y no se repite aquí: una regla escrita dos
    veces se cambia una sola.
    """
    comparacion = comparar(lecturas)
    assert comparacion.ganador.motivo == motivo_del_ganador
    eleccion = elegir(_renglon(), comparacion)
    assert eleccion.hay is False
    assert eleccion.motivo == NADIE_A_QUIEN_PEDIRLE


def test_la_certeza_del_ganador_viaja_con_la_sugerencia():
    """Un solo precio no es "el más barato": es *el único que contestó*.

    La frase la eligió el ticket 15 y aquí no se vuelve a elegir — viaja hecha
    para que la pantalla la escriba tal cual.
    """
    comparacion = comparar([_lectura("vicma", "86.05", "3")])
    eleccion = elegir(_renglon(), comparacion)
    assert eleccion.proveedor == "vicma"
    assert eleccion.certeza == GANADOR_UNICO
    assert eleccion.es_sugerencia is True


# ============================================================================
# La decisión: la persona manda
# ============================================================================


def test_la_decision_le_gana_a_la_sugerencia_y_las_dos_se_ven():
    """*La persona decide*: mínimo de pedido, días de entrega, crédito.

    Y el sistema sigue **diciendo** lo que habría sugerido: las dos viajan, que
    es lo que permite mirar una elección cara y preguntar por qué.
    """
    comparacion = comparar(
        [_lectura("nadro", "86.05", "40"), _lectura("levic", "146.38", "40")]
    )
    eleccion = elegir(
        _renglon(proveedor_elegido="levic", elegido_por="encargado@casa"), comparacion
    )
    assert eleccion.proveedor == "levic"
    assert eleccion.es_decision is True
    assert eleccion.es_sugerencia is False
    assert eleccion.sugerido == "nadro"
    assert eleccion.difiere_de_la_sugerencia is True
    assert eleccion.elegido_por == "encargado@casa"


def test_confirmar_la_sugerencia_es_una_decision_y_no_se_deduce_comparando():
    """Quien confirma decide, igual que en el ticket 11.

    Si `es_decision` se dedujera de que las dos cadenas difieren, confirmar la
    sugerencia borraría la decisión — que es justo la evidencia de que la
    sugerencia acertó.
    """
    comparacion = comparar([_lectura("nadro", "86.05", "40")])
    eleccion = elegir(
        _renglon(proveedor_elegido="nadro", elegido_por="encargado@casa"), comparacion
    )
    assert eleccion.es_decision is True
    assert eleccion.difiere_de_la_sugerencia is False


def test_se_puede_elegir_a_un_proveedor_que_no_dio_precio():
    """La quinta casilla empieza aquí: la elección no se revisa contra el precio.

    Hay razones que el sistema no ve. Que LEVIC no haya contestado hoy no es
    una razón para no pedirle.
    """
    comparacion = comparar(
        [_lectura("nadro", "86.05", "40"), _lectura("levic", motivo=SESION_CADUCADA)]
    )
    eleccion = elegir(
        _renglon(proveedor_elegido="levic", elegido_por="encargado@casa"), comparacion
    )
    assert eleccion.proveedor == "levic"
    assert eleccion.es_decision is True


def test_la_eleccion_json_lleva_los_dos_ejes_resueltos():
    """La pantalla pinta y no deduce: es decisión, y difiere de la sugerencia."""
    comparacion = comparar(
        [_lectura("nadro", "86.05", "40"), _lectura("vicma", "99.00", "40")]
    )
    json = eleccion_como_json(
        elegir(_renglon(proveedor_elegido="vicma", elegido_por="a@b"), comparacion)
    )
    assert json["nombre"] == "VICMA"
    assert json["nombre_sugerido"] == "NADRO"
    assert json["es_decision"] is True
    assert json["difiere_de_la_sugerencia"] is True


# ============================================================================
# Partir: uno por proveedor
# ============================================================================


def _partir(renglones, precios_por_renglon, puente=None):
    comparaciones = {
        r.renglon_id: comparar(
            precios_por_renglon.get(r.renglon_id, ()), r.cantidad_a_pedir
        )
        for r in renglones
    }
    return partir(
        renglones,
        comparaciones,
        precios_por_renglon,
        PUENTE if puente is None else puente,
    )


def test_la_lista_se_parte_en_un_pedido_por_proveedor():
    """La segunda casilla. Dos renglones, dos ganadores, dos pedidos."""
    renglones = [_renglon(1), _renglon(2)]
    precios = {
        1: (_lectura("nadro", "86.05", "40", renglon_id=1),),
        2: (_lectura("levic", "50.00", "40", renglon_id=2),),
    }
    particion = _partir(renglones, precios)
    assert particion.proveedores == ("nadro", "levic")
    assert [p.renglones for p in particion.pedidos] == [1, 1]


def test_dos_renglones_del_mismo_proveedor_van_en_un_solo_pedido():
    """"Uno por proveedor" es el grano: no un pedido por renglón."""
    renglones = [_renglon(1), _renglon(2)]
    precios = {
        1: (_lectura("nadro", "86.05", "40", renglon_id=1),),
        2: (_lectura("nadro", "12.00", "40", renglon_id=2),),
    }
    particion = _partir(renglones, precios)
    assert particion.proveedores == ("nadro",)
    assert particion.pedidos[0].renglones == 2
    assert particion.renglones_repartidos == 2


def test_el_orden_de_los_pedidos_es_fijo_y_no_depende_del_total():
    """La referencia primero, como en la fila de precios del ticket 14.

    Un orden por importe cambiaría de sitio los pedidos entre dos cargas de la
    misma pantalla.
    """
    renglones = [_renglon(1), _renglon(2), _renglon(3)]
    precios = {
        1: (_lectura("vicma", "1.00", "40", renglon_id=1),),
        2: (_lectura("nadro", "999.00", "40", renglon_id=2),),
        3: (_lectura("levic", "50.00", "40", renglon_id=3),),
    }
    assert _partir(renglones, precios).proveedores == ("nadro", "levic", "vicma")


def test_un_renglon_sin_a_quien_pedirle_no_se_reparte_pero_se_cuenta():
    """Nada desaparece en silencio: se queda fuera **y se dice**.

    Es la misma regla que `CONTEXT.md` fija para los productos sin anaquel: un
    renglón que se cae de la lista es mercancía que va a faltar sin que nadie
    se entere.
    """
    particion = _partir([_renglon(1), _renglon(2)], {1: (_lectura("nadro", "5", "9"),)})
    assert particion.proveedores == ("nadro",)
    assert [e.renglon_id for e in particion.sin_proveedor] == [2]
    assert particion.sin_proveedor[0].motivo == NADIE_A_QUIEN_PEDIRLE


def test_un_renglon_pertenece_a_un_solo_pedido():
    """La cuarta casilla, del lado del cálculo: su id sale una sola vez.

    En la tabla lo defiende `renglon.pedido_id` —una columna, no una tabla de
    cruce— con su llave foránea compuesta; aquí se comprueba que la partición
    no lo duplique antes de llegar ahí.
    """
    renglones = [_renglon(n) for n in (1, 2, 3)]
    precios = {
        1: (_lectura("nadro", "10", "5", renglon_id=1),),
        2: (_lectura("levic", "10", "5", renglon_id=2),),
        3: (_lectura("nadro", "10", "5", renglon_id=3),),
    }
    particion = _partir(renglones, precios)
    ids = [linea.renglon_id for p in particion.pedidos for linea in p.lineas]
    assert sorted(ids) == [1, 2, 3]
    assert len(ids) == len(set(ids))


def test_se_le_pide_la_cantidad_corregida_y_no_la_propuesta():
    """`cantidad_a_pedir` del ticket 11, sin reimplementarla aquí."""
    renglones = [_renglon(1, cantidad=3, cantidad_final=10)]
    particion = _partir(renglones, {1: (_lectura("nadro", "10.00", "40"),)})
    assert particion.pedidos[0].lineas[0].cantidad == 10
    assert particion.pedidos[0].total_sin_iva == Decimal("100.00")


# ============================================================================
# El puente al partir, y el pedido que se arma igual sin él
# ============================================================================


def test_un_pedido_a_quien_sicar_conoce_lleva_su_proveedor_id():
    particion = _partir([_renglon(1)], {1: (_lectura("levic", "10", "5"),)})
    assert particion.pedidos[0].proveedor_id == 10
    assert particion.pedidos[0].tiene_puente is True


def test_a_quepharma_se_le_puede_pedir_aunque_sicar_no_lo_conozca():
    """La pregunta del ticket: *¿se puede pedir igual?* Sí.

    Si la identidad del pedido fuera el `proveedor_id`, un proveedor sin fila en
    SICAR no se podría pedir — y ese es el estado de QuePharma hoy, medido
    contra `marts.dim_proveedor` el 2026-09-19. El pedido se arma con
    `proveedor_id` en `NULL` y la pantalla lo dice.
    """
    renglon = _renglon(1, proveedor_elegido="quepharma", elegido_por="a@b")
    particion = _partir([renglon], {1: (_lectura("nadro", "10", "5"),)})
    pedido = particion.pedidos[0]
    assert pedido.proveedor == "quepharma"
    assert pedido.proveedor_id is None
    assert pedido.tiene_puente is False
    assert particion.sin_puente == ("quepharma",)
    assert particion_como_json(particion)["pedidos"][0]["estado_del_puente"] == SIN_PUENTE


# ============================================================================
# El total: NULL nunca es 0
# ============================================================================


def test_el_total_es_la_suma_en_decimal_de_lo_que_se_va_a_pedir():
    renglones = [_renglon(1, cantidad=3), _renglon(2, cantidad=2)]
    precios = {
        1: (_lectura("nadro", "86.05", "40", renglon_id=1),),
        2: (_lectura("nadro", "10.10", "40", renglon_id=2),),
    }
    pedido = _partir(renglones, precios).pedidos[0]
    assert pedido.total_sin_iva == Decimal("278.35")
    assert isinstance(pedido.total_sin_iva, Decimal)


def test_una_linea_sin_precio_deja_el_total_en_None_y_el_parcial_a_la_vista():
    """La quinta casilla entera, y la trampa más cara del ticket.

    El renglón se pide igual —la línea existe, con su cantidad y su marca de
    precio desconocido— y el **total** se vuelve `None`. Jamás la suma de las
    demás: un total parcial escrito en `pedido.total_sin_iva` se compara contra
    la factura del proveedor, no cuadra, y nadie sabe si falta mercancía o falta
    un precio.

    Lo que sí se sabe no se esconde: el parcial viaja aparte con su conteo.
    """
    renglones = [_renglon(1, cantidad=3), _renglon(2, cantidad=1)]
    precios = {
        1: (_lectura("nadro", "86.05", "40", renglon_id=1),),
        2: (
            _lectura("nadro", motivo=SESION_CADUCADA, renglon_id=2),
            _lectura("levic", "5.00", "40", renglon_id=2),
        ),
    }
    # El renglón 2 lo gana LEVIC; hay que elegir NADRO a mano para que entre al
    # mismo pedido sin precio, que es exactamente el caso del ticket.
    renglones[1] = _renglon(2, cantidad=1, proveedor_elegido="nadro", elegido_por="a@b")

    pedido = _partir(renglones, precios).pedidos[0]
    assert pedido.renglones == 2
    assert pedido.sin_precio == 1
    assert pedido.total_sin_iva is None
    assert pedido.parcial_sin_iva == Decimal("258.15")

    sin = next(l for l in pedido.lineas if not l.tiene_precio)
    assert sin.precio is None
    assert sin.motivo == SIN_PRECIO_DE_ESE_PROVEEDOR
    assert sin.cantidad == 1
    assert sin.importe is None


def test_un_proveedor_al_que_nadie_le_pregunto_se_distingue_del_que_no_contesto():
    """Dos huecos que se arreglan distinto: uno con el botón, otro mirando el motivo."""
    renglon = _renglon(1, proveedor_elegido="quepharma", elegido_por="a@b")
    pedido = _partir([renglon], {1: (_lectura("nadro", "10", "5"),)}).pedidos[0]
    assert pedido.lineas[0].motivo == SIN_CONSULTARLE


def test_un_pedido_vacio_no_cuesta_cero():
    """Un pedido sin líneas da `None`, no `0.00`.

    Pasa cuando alguien parte, cambia todas las elecciones y vuelve a partir: el
    pedido de ayer se queda sin renglones. `0.00` en una lista de totales pasa
    desapercibido; `None` dice "no tiene nada".
    """
    assert PedidoPorArmar(proveedor="nadro").total_sin_iva is None
    assert PedidoPorArmar(proveedor="nadro").parcial_sin_iva == Decimal("0.00")


def test_el_total_viaja_al_navegador_como_cadena():
    """El JSON de JavaScript solo tiene `double`; mandarlo como número lo
    metería en coma flotante justo en el borde donde acababa de salir."""
    pedido = _partir([_renglon(1)], {1: (_lectura("nadro", "86.05", "40"),)}).pedidos[0]
    json = particion_como_json(
        _partir([_renglon(1)], {1: (_lectura("nadro", "86.05", "40"),)})
    )["pedidos"][0]
    assert pedido.total_sin_iva == Decimal("258.15")
    assert json["total_sin_iva"] == "258.15"
    assert isinstance(json["total_sin_iva"], str)
    assert json["lineas"][0]["importe"] == "258.15"


def test_el_importe_de_una_linea_no_pasa_por_coma_flotante():
    """`0.1 * 3` en `float` es `0.30000000000000004`. En `Decimal` no."""
    linea = Linea(renglon_id=1, descripcion="X", cantidad=3, precio=Decimal("0.10"))
    assert linea.importe == Decimal("0.30")
