"""La reposición deja de ser un día: acumula desde el corte del último cerrado.

Este archivo es el ticket 09 entero, y lo que cuida es una sola cosa: **que no
se caiga una venta al piso**. Hasta el ticket 08 la ventana era *el último día
con datos*, y con el hueco de fin de semana eso tiraba el sábado en silencio —el
respaldo de SICAR sube hacia las 18:51 de lunes a viernes, la cadena corre a las
20:30, y lo del sábado y el viernes por la tarde llega junto hasta el lunes en la
noche: peor caso medido, 2.5 días (ADR 0002, `CLAUDE.md`)—.

La prueba que más vale de aquí es
`test_el_sugerido_del_lunes_trae_el_viernes_completo_y_el_sabado_completo`: es
el escenario con el que el ADR 0002 justifica la decisión entera, escrito con
fechas reales de calendario —viernes 11, sábado 12, domingo 13 y lunes 14 de
septiembre de 2026— y no con un caso abstracto.

La segunda que más vale es `test_el_dia_del_corte_no_se_propone_dos_veces`:
distingue las dos opciones que este ticket tenía enfrente —que el día del corte
entre o no entre en la ventana nueva— y falla con la contraria. El porqué de la
elegida está en el docstring de `almacenamiento.ventana_de_reposicion`.

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt

import pytest

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    VENCIDO,
    Ventana,
    dias_primera_vez_configurados,
    ventana_de_reposicion,
)
from continental.config import CONFIG
from continental.sugerido import DIAS_DE_RITMO

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"


# --------------------------------- la ventana, como función pura y sin reloj


def test_sin_cierre_anterior_la_ventana_es_la_de_la_primera_vez():
    """Sin corte no hay de dónde acumular: se toman los días que diga el YAML.

    Siete días **contando los dos extremos**, que es como `Ventana` y
    `almacen.ventas` cuentan un rango en todo el módulo.
    """
    ventana = ventana_de_reposicion(
        corte=None, hasta=dt.date(2026, 9, 16), dias_primera_vez=7
    )

    assert ventana == Ventana(dt.date(2026, 9, 10), dt.date(2026, 9, 16))
    assert (ventana.hasta - ventana.desde).days + 1 == 7


def test_el_numero_de_la_primera_vez_es_un_argumento_y_no_una_constante():
    """Si estuviera escrito en el código, el YAML y el módulo divergirían.

    `config/continental.yml` ya trae `pedido.dias_primera_vez` con su
    comentario; esta función lo recibe y no lo sabe. La capa que lee el archivo
    es `dias_primera_vez_configurados`, igual que `reglas_configuradas` para los
    anaqueles.
    """
    ventana = ventana_de_reposicion(
        corte=None, hasta=dt.date(2026, 9, 16), dias_primera_vez=3
    )

    assert ventana == Ventana(dt.date(2026, 9, 14), dt.date(2026, 9, 16))


def test_la_primera_vez_es_un_solo_dia_habil_y_sale_del_yaml_versionado():
    """El número vive en el archivo que se despliega, no en un literal del código.

    **Era 7 y bajó a 1 el 2026-09-20**, por decisión del dueño. Siete días era
    razonable mientras no hubiera historia de cierres, y es una mala primera
    impresión: la primerísima lista propondría una semana entera de ventas de
    golpe sobre un anaquel que ya se repuso solo durante esa semana.

    **Uno aquí ya es "un día hábil"** y no hace falta que nadie sepa de
    calendarios: la ventana termina en `max(fecha)` de las ventas, así que su
    último día siempre tiene ventas y ni un domingo ni un feriado pueden caer
    ahí. Medido el 2026-09-20 contra el almacén con el 16 de septiembre
    —Independencia—, que se ve idéntico a un domingo: cero filas.
    """
    assert "dias_primera_vez" in CONFIG.read_text(encoding="utf-8")
    assert dias_primera_vez_configurados() == 1


def test_sin_el_numero_en_el_yaml_la_ventana_es_de_un_dia_y_no_uno_inventado(
    monkeypatch, caplog
):
    """Un YAML a medias no puede dejar a la farmacia sin pedido del día.

    Tampoco puede inventarle un 7 por su cuenta: ese número es una decisión del
    negocio y vive en el archivo. El único valor que no inventa nada es **un
    día** —el último con datos, que es lo que el módulo hacía antes de este
    ticket—, y va con su aviso en la bitácora: pedir de menos en silencio es
    justo lo que la regla 4 prohíbe.
    """
    import logging

    import continental.config as config

    monkeypatch.setattr(
        config,
        "cargar",
        lambda: config.Ajustes(
            negocio=NEGOCIO, warehouse_url=None, modulos={}, pedido={}
        ),
    )

    with caplog.at_level(logging.WARNING, logger="continental"):
        assert dias_primera_vez_configurados() == 1

    assert "dias_primera_vez" in caplog.text


def test_la_ventana_arranca_el_dia_siguiente_al_corte():
    """La decisión del ticket: el día del corte **no** vuelve a entrar.

    `Ventana` incluye los dos extremos, así que la lista cerrada ya propuso lo
    de su `ventas_consideradas_hasta`. Empezar ahí otra vez sería proponer por
    segunda vez lo que ya se pidió.
    """
    ventana = ventana_de_reposicion(
        corte=dt.date(2026, 9, 10), hasta=dt.date(2026, 9, 14), dias_primera_vez=7
    )

    assert ventana == Ventana(dt.date(2026, 9, 11), dt.date(2026, 9, 14))


def test_las_ventanas_embaldosan_el_calendario_sin_huecos_ni_traslapes():
    """La propiedad que hace correcta a la regla, dicha de una vez.

    Cada día de ventas cae en **exactamente una** ventana: la de arriba termina
    donde la siguiente empieza, sin un día en medio que nadie mire y sin uno
    que dos listas repongan. Es lo que distingue "acumular desde el corte" de
    "mirar el último día".
    """
    primera = ventana_de_reposicion(
        corte=None, hasta=dt.date(2026, 9, 10), dias_primera_vez=7
    )
    segunda = ventana_de_reposicion(
        corte=primera.hasta, hasta=dt.date(2026, 9, 14), dias_primera_vez=7
    )
    tercera = ventana_de_reposicion(
        corte=segunda.hasta, hasta=dt.date(2026, 9, 18), dias_primera_vez=7
    )

    assert segunda.desde == primera.hasta + dt.timedelta(days=1)
    assert tercera.desde == segunda.hasta + dt.timedelta(days=1)


def test_un_corte_que_no_deja_dias_nuevos_no_arma_una_ventana_al_reves(caplog):
    """El cinturón contra un estado imposible, que la base rechazaría.

    `ck_pedido_sugerido_ventana` prohíbe una ventana al revés, y aquí saldría
    una si un cerrado tuviera un corte igual o posterior al último dato —solo
    puede pasar si alguien le borró filas al almacén—. En vez de tronar en el
    `INSERT`, se acota al propio día y se avisa: el pedido del día se hace y el
    motivo queda escrito.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="continental"):
        ventana = ventana_de_reposicion(
            corte=dt.date(2026, 9, 20), hasta=dt.date(2026, 9, 14), dias_primera_vez=7
        )

    assert ventana == Ventana(dt.date(2026, 9, 14), dt.date(2026, 9, 14))
    assert "corte" in caplog.text


# ----------------------------------------- acumular de verdad, por la ruta


def test_un_pedido_nuevo_incluye_todo_lo_vendido_desde_el_corte_del_ultimo_cerrado(
    cliente, almacen
):
    """La casilla principal del ticket, de punta a punta.

    Se cierra la lista del martes; el miércoles nadie abre la página; el jueves
    el sugerido trae **el miércoles y el jueves**, no solo el jueves.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
        _producto(3, "7501000000003", "CLORFENAMINA"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 8), 1, 2)]  # martes
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria += [
        _venta(dt.date(2026, 9, 9), 2, 5),  # miércoles: nadie abrió la lista
        _venta(dt.date(2026, 9, 10), 3, 1),  # jueves
    ]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ventas_consideradas_desde"] == "2026-09-09"
    assert cuerpo["ventas_consideradas_hasta"] == "2026-09-10"
    assert sorted(r["producto_id"] for r in cuerpo["renglones"]) == [2, 3]


def test_el_dia_del_corte_no_se_propone_dos_veces(cliente, almacen):
    """La prueba que distingue las dos opciones del ticket.

    El martes se vendieron 4 piezas de AMOXICILINA y esa lista **se cerró**: ya
    se pidió lo que se iba a pedir. Si la ventana del miércoles arrancara en el
    día del corte en vez de en el siguiente, esas 4 piezas volverían a
    proponerse y se pedirían dos veces — y en el renglón no se vería, porque se
    sumarían a las de los otros días.

    Con la regla elegida, el miércoles solo trae lo del miércoles.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 8), 1, 4)]
    cerrada = cliente.get(RUTA).json()
    cliente.post(f"{RUTA}/{cerrada['pedido_sugerido_id']}/cerrar")

    # Lo del martes ya se propuso y se pidió: está en la lista cerrada.
    assert [r["producto_id"] for r in cerrada["renglones"]] == [1]

    almacen.ventas_en_memoria.append(_venta(dt.date(2026, 9, 9), 2, 1))
    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ventas_consideradas_desde"] == "2026-09-09"
    assert [r["producto_id"] for r in cuerpo["renglones"]] == [2], (
        "El día del corte volvió a entrar en la ventana: la AMOXICILINA que ya "
        "se pidió el martes se está proponiendo otra vez."
    )


def test_la_primera_vez_sin_ningun_cierre_la_ventana_es_de_siete_dias(
    cliente, almacen
):
    """La otra casilla: cuando no hay de dónde acumular, siete días del YAML.

    Seis días antes del último dato entra; siete días antes ya no. El número no
    está escrito aquí: se lee del mismo archivo que el módulo.
    """
    dias = dias_primera_vez_configurados()
    ultima = dt.date(2026, 9, 16)
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
        _producto(3, "7501000000003", "CLORFENAMINA"),
    ]
    almacen.ventas_en_memoria = [
        _venta(ultima - dt.timedelta(days=dias), 3, 1),  # justo afuera
        _venta(ultima - dt.timedelta(days=dias - 1), 2, 1),  # el primero adentro
        _venta(ultima, 1, 1),
    ]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ventas_consideradas_desde"] == (
        ultima - dt.timedelta(days=dias - 1)
    ).isoformat()
    assert cuerpo["ventas_consideradas_hasta"] == ultima.isoformat()
    assert sorted(r["producto_id"] for r in cuerpo["renglones"]) == [1, 2]


def test_una_lista_abierta_o_vencida_no_es_un_corte(cliente, almacen, almacenamiento):
    """"No hay cierre anterior" no es "no hay listas anteriores".

    Una lista `abierta` o `vencida` no ordenó nada —`vencida` es literalmente
    "pasó su día y quedaron renglones sin atender"—, así que tomar su
    `ventas_consideradas_hasta` como corte dejaría fuera días que nadie repuso.
    Solo una lista **cerrada** mueve el corte; mientras no la haya, cada lista
    nueva es una primera vez.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 15), 1, 3)]
    cliente.get(RUTA)  # se arma y nadie la cierra

    almacen.ventas_en_memoria.append(_venta(dt.date(2026, 9, 16), 2, 1))
    cuerpo = cliente.get(RUTA).json()

    assert almacenamiento.leer(NEGOCIO, dt.date(2026, 9, 15)).estado == VENCIDO
    # El principio de la lista que nadie cerró, que es `piso_sin_pedir`. Aquí
    # decía `2026-09-10` —siete días— y eso era la ventana ancha de la primera
    # vez recogiéndolo **por accidente**. Desde que la ventana es de un día
    # hábil (2026-09-20) lo recoge a propósito, y esta prueba pasó de
    # comprobar una casualidad a comprobar la garantía.
    assert cuerpo["ventas_consideradas_desde"] == "2026-09-15"
    assert sorted(r["producto_id"] for r in cuerpo["renglones"]) == [1, 2], (
        "Lo del día que nadie cerró desapareció de la lista siguiente."
    )


def test_si_un_dia_nadie_abrio_la_lista_lo_de_ese_dia_aparece_en_la_siguiente(
    cliente, almacen, almacenamiento
):
    """La casilla del ticket, con el caso que la motiva: un día sin nadie.

    El jueves se cerró la lista. El viernes el encargado no entró y **no hay
    fila** de ese día. El lunes las ventas del viernes tienen que estar ahí: si
    la ventana mirara el último día, se habrían caído al piso sin un solo error
    que ver.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 10), 1, 1)]  # jueves
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria.append(_venta(dt.date(2026, 9, 11), 2, 6))  # viernes
    almacen.ventas_en_memoria.append(_venta(dt.date(2026, 9, 14), 2, 1))  # lunes

    cuerpo = cliente.get(RUTA).json()

    assert almacenamiento.leer(NEGOCIO, dt.date(2026, 9, 11)) is None
    assert cuerpo["ventas_consideradas_desde"] == "2026-09-11"
    assert [r["cantidad_propuesta"] for r in cuerpo["renglones"]] == [7]


def test_el_sugerido_del_lunes_trae_el_viernes_completo_y_el_sabado_completo(
    cliente, almacen
):
    """El escenario con el que el ADR 0002 justifica la decisión entera.

    Fechas reales: **jueves 10, viernes 11, sábado 12, domingo 13 y lunes 14 de
    septiembre de 2026**. Lo que pasa de verdad:

    - Jueves 20:30 corre la cadena con el respaldo de las 18:51. El encargado
      arma la lista del jueves y la cierra: corte = jueves 10.
    - Viernes 20:30 corre la cadena. Trae el viernes hasta las 18:51 — **lo de
      la tarde todavía no existe en el almacén**. Nadie abre la página.
    - Sábado y domingo no corre la cadena: el respaldo sube de lunes a viernes.
      La farmacia abre el sábado y cierra el domingo (ni una venta en domingo en
      33 meses).
    - Lunes 20:30 corre la cadena y llega **todo junto**: el viernes completo
      —incluida la tarde—, el sábado entero y el lunes hasta las 18:51. Peor
      caso medido: 2.5 días de retraso.

    El sugerido del lunes tiene que traer las tres cosas. Con la ventana de "el
    último día con datos" traería solo el lunes y el sábado se caería al piso.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
        _producto(3, "7501000000003", "CLORFENAMINA"),
        _producto(4, "7501000000004", "DICLOFENACO"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 10), 1, 3)]  # jueves
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria += [
        _venta(dt.date(2026, 9, 11), 2, 2),  # viernes, antes de las 18:51
        _venta(dt.date(2026, 9, 11), 2, 3),  # viernes por la tarde: llega el lunes
        _venta(dt.date(2026, 9, 12), 3, 4),  # sábado completo: llega el lunes
        _venta(dt.date(2026, 9, 14), 4, 1),  # lunes, hasta las 18:51
    ]

    cuerpo = cliente.get(RUTA).json()
    por_producto = {r["producto_id"]: r for r in cuerpo["renglones"]}

    assert cuerpo["ventas_consideradas_desde"] == "2026-09-11"
    assert cuerpo["ventas_consideradas_hasta"] == "2026-09-14"
    assert por_producto[2]["cantidad_propuesta"] == 5, (
        "El viernes por la tarde no entró: llega al almacén junto con el "
        "sábado, hasta el lunes en la noche."
    )
    assert por_producto[3]["cantidad_propuesta"] == 4  # el sábado completo
    assert por_producto[4]["cantidad_propuesta"] == 1  # el lunes
    assert 1 not in por_producto  # el jueves ya se pidió


def test_un_producto_vendido_en_varios_dias_acumula_en_un_solo_renglon(
    cliente, almacen
):
    """La casilla del ticket, ahora que la ventana son varios días.

    `calcular_pedido_sugerido` ya sumaba los tickets de un mismo día —el grano
    de `fct_ventas` es ticket × artículo—; esto comprueba que lo siga haciendo
    cuando la ventana cruza días. Dos renglones del mismo producto en una lista
    serían pedirlo dos veces, y `ux_renglon_producto` los rechaza.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "AMOXICILINA")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 8), 1, 1)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria += [
        _venta(dt.date(2026, 9, 9), 1, 2),
        _venta(dt.date(2026, 9, 9), 1, 3),  # otro ticket del mismo día
        _venta(dt.date(2026, 9, 10), 1, 4),
    ]

    renglones = cliente.get(RUTA).json()["renglones"]

    assert len(renglones) == 1
    assert renglones[0]["piezas_vendidas"] == 9
    assert renglones[0]["cantidad_propuesta"] == 9


def test_la_ventana_se_ancla_en_el_corte_y_en_el_dato_y_nunca_en_el_reloj(
    cliente, almacen
):
    """La trampa heredada otra vez, ahora sobre la ventana acumulada.

    El último dato de este almacén es de 2024. Contra `date.today()` —o contra
    el `current_date` del Postgres del contenedor, que corre en UTC y puede ir
    dos días adelante— la ventana caería fuera de los datos y la lista saldría
    vacía: la misma falla silenciosa que a farmacia-data le costó 11.7 puntos de
    crecimiento inventados.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA"),
        _producto(2, "7501000000002", "BENZAL"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2024, 3, 4), 1, 1)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria.append(_venta(dt.date(2024, 3, 5), 2, 1))
    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ventas_consideradas_desde"] == "2024-03-05"
    assert cuerpo["ventas_consideradas_hasta"] == "2024-03-05"
    assert dt.date(2024, 3, 5) < dt.date.today()


# ------------------------------------- la otra ventana: la del ritmo, 28 días


def test_el_ritmo_sigue_midiendose_sobre_28_dias_aunque_la_reposicion_sea_mas_larga(
    cliente, almacen
):
    """Son **dos** ventanas distintas y este ticket alarga solo una.

    La de reposición puede abarcar meses —una lista cerrada hace dos y nadie
    volvió a entrar—; la del ritmo son 28 días fijos, cuatro semanas exactas,
    porque mide "a este ritmo, ¿cuánto dura lo que queda?" (ver `DIAS_DE_RITMO`).
    Antes del ticket 09 la de reposición era un subconjunto de la del ritmo y
    bastaba recortarla; ahora puede ser la más larga de las dos, y si el ritmo
    se midiera sobre toda la lectura el divisor se estiraría, el ritmo bajaría y
    la cobertura saldría inflada: lo urgente se hundiría al fondo de la lista.

    Aquí: 1 pieza el 11 de julio (fuera de los 28 días) y 1 el 16 de septiembre
    (dentro). Se reponen las 2; el ritmo sale de la última sola —1 pieza al
    día—, así que 28 piezas de existencia son 28 días de cobertura. Si el ritmo
    se midiera sobre la lectura entera darían 952.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA", existencia=28),
        _producto(9, "7501000000009", "IBUPROFENO"),
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 7, 10), 9, 1)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria += [
        _venta(dt.date(2026, 7, 11), 1, 1),  # dentro de la reposición, fuera del ritmo
        _venta(dt.date(2026, 9, 16), 1, 1),  # dentro de las dos
    ]

    cuerpo = cliente.get(RUTA).json()
    renglon = next(r for r in cuerpo["renglones"] if r["producto_id"] == 1)

    assert cuerpo["ventas_consideradas_desde"] == "2026-07-11"
    assert renglon["cantidad_propuesta"] == 2
    assert renglon["dias_de_cobertura"] == 28.0


def test_las_dos_ventanas_salen_de_una_sola_lectura_del_almacen(cliente, almacen):
    """Una consulta y no dos, con el rango **unión** de las dos ventanas.

    Leer dos veces le costaría a Postgres dos recorridos de `fct_ventas` por
    carga, y algo peor: dos lecturas caen en momentos distintos, así que la
    reposición y el ritmo podrían salir de fotos que no coinciden. Se lee el
    rango que cubre a las dos y se recorta en memoria — del orden de 600 filas
    por cada 28 días (21,035 líneas en 33 meses, medido sobre el respaldo del
    2026-07-27).
    """
    llamadas: list[tuple[dt.date, dt.date]] = []
    original = almacen.ventas

    def espiar(desde: dt.date, hasta: dt.date):
        llamadas.append((desde, hasta))
        return original(desde, hasta)

    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "AMOXICILINA")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 7, 10), 1, 1)]
    identificador = cliente.get(RUTA).json()["pedido_sugerido_id"]
    cliente.post(f"{RUTA}/{identificador}/cerrar")

    almacen.ventas_en_memoria.append(_venta(dt.date(2026, 9, 16), 1, 1))
    almacen.ventas = espiar
    cliente.get(RUTA)

    assert len(llamadas) == 1, "La ruta está leyendo las ventas más de una vez."
    assert llamadas[0] == (dt.date(2026, 7, 11), dt.date(2026, 9, 16))


def test_cuando_la_reposicion_es_corta_se_siguen_leyendo_los_28_dias_del_ritmo(
    cliente, almacen
):
    """El caso de todos los días: la ventana de reposición cabe en la del ritmo.

    El rango leído lo manda entonces el ritmo, que necesita más historia — si
    se leyera solo la reposición, un producto que vendió una pieza ayer y una
    al mes saldría con el mismo ritmo.
    """
    llamadas: list[tuple[dt.date, dt.date]] = []
    original = almacen.ventas

    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "AMOXICILINA")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 1)]
    almacen.ventas = lambda desde, hasta: (
        llamadas.append((desde, hasta)) or original(desde, hasta)
    )

    cliente.get(RUTA)

    ultima = dt.date(2026, 9, 16)
    assert llamadas == [(ultima - dt.timedelta(days=DIAS_DE_RITMO - 1), ultima)]


# ------------------------------------------------------------- la pantalla


def test_la_pantalla_dice_el_rango_de_ventas_y_no_solo_la_fecha_final(cliente):
    """Con una ventana de varios días, decir solo el último es engañoso.

    "Ventas del lunes 14" con una ventana que arranca el viernes 11 hace creer
    que lo del fin de semana no está, y el encargado no tiene cómo saber que sí.
    La pantalla es HTML+JS a mano y ninguna prueba de Python la ejecuta, así que
    lo que se comprueba barato es que el extremo izquierdo de la ventana llegue
    al navegador y se pinte con su conector.
    """
    portada = cliente.get("/").text

    assert "ventas_consideradas_desde" in portada
    assert "' al '" in portada


# ------------------------------------------------------------------ ayudas


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 50.0,
        costo=cantidad * 30.0,
        utilidad=cantidad * 20.0,
    )


def _producto(
    producto_id: int, clave: str, descripcion: str, existencia: float = 4
) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=descripcion,
        categoria="GRUP4",
        departamento="MEDICAMENTO",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


# ------------------ el piso: dias propuestos que nadie pidio (2026-09-20)
#
# Llego con la ventana corta. Hasta ese dia `dias_primera_vez` valia 7 y esta
# red existia por accidente: una ventana de una semana volvia a recoger lo que
# nadie habia cerrado. Al bajarla a un dia habil -para que la lista sea corta y
# legible- la red desaparecia, y las ventas de un dia desatendido se caian al
# suelo sin un solo error que ver.


def test_sin_corte_la_ventana_retrocede_hasta_lo_que_nadie_pidio():
    """Un dia propuesto y no cerrado manda sobre la ventana de la primera vez."""
    ventana = ventana_de_reposicion(
        corte=None,
        hasta=dt.date(2026, 9, 18),
        dias_primera_vez=1,
        piso_sin_pedir=dt.date(2026, 9, 15),
    )

    assert ventana == Ventana(dt.date(2026, 9, 15), dt.date(2026, 9, 18))


def test_sin_nada_pendiente_la_ventana_es_la_corta():
    """El caso ordinario: el encargado cierra su lista y no arrastra nada."""
    ventana = ventana_de_reposicion(
        corte=None, hasta=dt.date(2026, 9, 18), dias_primera_vez=1, piso_sin_pedir=None
    )

    assert ventana == Ventana(dt.date(2026, 9, 18), dt.date(2026, 9, 18))


def test_el_piso_no_retrocede_por_encima_de_un_corte_porque_duplicaria():
    """**La restriccion que impide pedir el doble en silencio.**

    Si el lunes quedo `abierta` y el martes se `cerro`, retroceder hasta el
    lunes volveria a proponer TAMBIEN el martes, que ya se pidio. Las piezas de
    los dos dias se suman en un solo numero por renglon, asi que el pedido
    saldria del doble sin que se vea -- la falla que el ADR 0002 prohibe y que
    no se nota mirando la pantalla.

    `Ventana` es un intervalo y no un conjunto, asi que no puede saltarse el
    martes por dentro. Por eso el piso solo se aplica cuando NO hay corte.
    """
    ventana = ventana_de_reposicion(
        corte=dt.date(2026, 9, 16),
        hasta=dt.date(2026, 9, 18),
        dias_primera_vez=1,
        piso_sin_pedir=dt.date(2026, 9, 14),
    )

    assert ventana == Ventana(dt.date(2026, 9, 17), dt.date(2026, 9, 18)), (
        "La ventana retrocedio por debajo del corte: esos dias ya se pidieron."
    )


def test_la_pantalla_avisa_cuando_la_lista_trae_mas_de_un_dia(cliente):
    """Una lista de cinco dias y una de uno se ven IGUAL en los renglones.

    Las piezas se suman en un solo numero por renglon, asi que el arrastre es
    invisible mirando la tabla: el encargado veria "pedir 12" sin manera de
    saber que son tres dias y no el de ayer. Por eso el numero va arriba, junto
    a las fechas.

    La frase no nombra "el ultimo cierre", y eso es a proposito: desde que la
    ventana es de un dia habil, una lista larga puede venir de un dia que nadie
    cerro -- y ahi NO hay ningun cierre del cual acumular. La frase vieja
    nombraba algo que en ese caso no existe.
    """
    pagina = cliente.get("/").text

    assert "días de ventas en esta lista, no uno" in pagina
    # Sobre lo que se PINTA y no sobre el archivo entero: la frase vieja sigue
    # ahi, citada dentro del comentario que explica por que se fue.
    assert "textContent = dias + ' días acumulados" not in pagina, (
        "Volvio la frase que miente cuando no hubo ningun cierre."
    )
    assert "dias > 1" in pagina, (
        "El aviso dejo de estar condicionado: una lista de un dia no tiene nada "
        "que advertir, y un aviso permanente se deja de leer."
    )
