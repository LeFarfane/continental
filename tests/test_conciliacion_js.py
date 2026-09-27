"""La pantalla de la conciliación diaria, el lado del JavaScript (ADR 0021,
2026-09-27).

`tests/test_conciliacion_pantalla.py` ya prueba el JSON y las rutas HTTP.
Este archivo prueba lo que se construyó ENCIMA de eso, en `continental.js`:
el contenedor dentro de la vista del día (ADR 0020), que las frases lleguen
hechas de Python y el JavaScript solo las pinte, que el botón de lote nunca
pueda arrastrar lo descartado ni lo ambiguo, y que confirmar recargue la
pantalla igual que las demás acciones de recepción.

Este repo no ejecuta JavaScript en las pruebas (ver el docstring de
`test_pasada_visual.py`), así que todo esto se fija con pruebas estáticas
sobre el texto del archivo, exactamente como ya hace `test_navegacion_pantalla.py`
y `test_cierre.py`.

Ninguna prueba toca Postgres ni la red.
"""

from __future__ import annotations

import re

from conftest import pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str, *, hasta: int = 2200) -> str:
    """El cuerpo de una función con nombre, para acotar dónde se busca."""
    script = _script()
    inicio = script.index(nombre)
    return script[inicio : inicio + hasta]


# ------------------------------------------------- el HTML del contenedor


def test_el_contenedor_nace_escondido_dentro_de_la_vista_del_dia():
    pantalla = pantalla_completa()

    assert re.search(r'<div class="en-camino conciliacion" id="conciliacion" hidden></div>', pantalla)
    # Vive DESPUÉS de "descartados", dentro de la misma <section> que el resto
    # del pedido del día (ADR 0020): la conciliación es de un día concreto.
    inicio_seccion = pantalla.index('<h2>Pedido sugerido</h2>')
    fin_seccion = pantalla.index("</section>", inicio_seccion)
    seccion = pantalla[inicio_seccion:fin_seccion]
    assert 'id="conciliacion"' in seccion
    assert seccion.index('id="descartados"') < seccion.index('id="conciliacion"')


def test_el_contenedor_se_esconde_al_navegar_a_otro_dia():
    """Sin esto, navegar a un domingo o a un 404 de la bitácora dejaría la
    conciliación de un día pegada a la pantalla de otro (ADR 0020)."""
    cuerpo = _funcion("const ocultarLoDeOtroDia", hasta=400)

    assert "'conciliacion'" in cuerpo


# ----------------------------------------- se pide aparte, y con el id de la lista


def test_cargar_pedido_pide_la_conciliacion_con_el_id_de_la_lista():
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=9000)

    assert "cargarConciliacion(datos.pedido_sugerido_id);" in cuerpo


def test_cargar_conciliacion_pide_su_propia_ruta_y_se_esconde_sin_id():
    cuerpo = _funcion("const cargarConciliacion", hasta=500)

    assert (
        "fetch('/api/pedido-sugerido/' + pedidoSugeridoId + '/conciliacion')"
        in cuerpo
    )
    # Regla 4: sin id no hay nada que pedir, y esconderse no es lo mismo que
    # pedir con un id vacío -que 404earía o mentiría-.
    assert "if (!pedidoSugeridoId) { caja.hidden = true;" in cuerpo


def test_no_espera_a_la_conciliacion_para_pintar_el_resto_de_la_lista():
    """Una compra de hace tres días no tiene por qué retrasar pintar la lista
    de hoy: `cargarConciliacion` no lleva `await` en `cargarPedido`."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=9000)

    assert "await cargarConciliacion" not in cuerpo


# -------------------------------------------- las frases llegan hechas de Python


def test_pintar_conciliacion_usa_create_element_y_no_innerhtml():
    cuerpo = _funcion("const pintarConciliacion", hasta=5200)

    assert "innerHTML" not in cuerpo
    assert "createElement" in cuerpo


def test_las_frases_se_pintan_tal_cual_nunca_se_componen():
    """La lección de los tickets 15, 21, 24, 25 y 26, repetida aquí: ninguna
    palabra de negocio se escribe en el JavaScript. `datos.frase`,
    `c.frase`, `c.frase_del_pago`, `r.frase` — todo llega hecho."""
    cuerpo = _funcion("const pintarConciliacion", hasta=5200)

    assert "resumen.textContent = datos.frase" in cuerpo
    assert "que.textContent = c.frase;" in cuerpo
    assert "pago.textContent = c.frase_del_pago;" in cuerpo
    assert "fila.textContent = r.frase;" in cuerpo
    assert "li.textContent = c.frase;" in cuerpo
    # Ninguna de las palabras de las frases de Python (`conciliacion.py`)
    # aparece escrita como texto en el JavaScript: si apareciera fuera de un
    # comentario, la pantalla estaría componiendo lo que Python ya compone.
    codigo = re.sub(r"//[^\r\n]*", "", cuerpo)
    for prohibido in ("se pagó $", "nunca ha aparecido", "no se compró"):
        assert prohibido not in codigo


# --------------------------------------- lo que NUNCA se auto-confirma (ADR 0021)


def test_solo_lo_accionable_ofrece_el_checkbox_del_lote():
    cuerpo = _funcion("const pintarConciliacion", hasta=5200)

    assert "if (c.accionable) {" in cuerpo
    idx_if = cuerpo.index("if (c.accionable) {")
    idx_checkbox = cuerpo.index("marca.type = 'checkbox';")
    assert idx_if < idx_checkbox


def test_lo_sin_comprar_y_lo_comprado_sin_proponer_nunca_llevan_checkbox():
    """El bloque 2 (`sin_comprar`) y el bloque 3 (`compradas_sin_proponer`)
    no tienen ningún `<input type="checkbox">`: la garantía de que lo
    descartado y lo ambiguo no se auto-confirman está en la FORMA del dato
    que llega del servidor —sin `renglon_id` de coincidencia—, no en un
    `if` de este archivo que alguien podría olvidar (ver
    `test_conciliacion_pantalla.py`)."""
    script = _script()
    inicio = script.index("const pintarConciliacion")
    fin_coincidencias = script.index("(datos.sin_comprar || []).forEach", inicio)
    fin_bloque = script.index("const confirmarLoteDeConciliacion", inicio)
    bloques_2_y_3 = script[fin_coincidencias:fin_bloque]
    # Sin los comentarios: el docstring de este bloque EXPLICA por qué no
    # hay checkbox aquí, y esa explicación nombra la palabra a propósito.
    codigo = re.sub(r"//[^\r\n]*", "", bloques_2_y_3)

    assert "checkbox" not in codigo
    assert "accionable" not in codigo


def test_el_boton_de_lote_solo_manda_lo_que_sigue_marcado():
    cuerpo = _funcion("const confirmarLoteDeConciliacion", hasta=1200)

    assert "[...marcadas.entries()]" in cuerpo
    assert "fetch('/api/pedido-sugerido/' + pedidoSugeridoId" in cuerpo
    assert "+ '/conciliacion/confirmar'" in cuerpo
    assert "method: 'POST'" in cuerpo


def test_confirmar_el_lote_recarga_la_pantalla_entera():
    """La misma regla que confirmar una recepción, cancelar un pedido o
    recibir a mano: cambia el estado de los renglones y no se deduce a
    mano, se recarga (ADR 0020: se queda en el día que se estaba viendo)."""
    cuerpo = _funcion("const confirmarLoteDeConciliacion", hasta=1200)

    assert "await recargarLoQueSeVe();" in cuerpo


def test_una_falla_al_confirmar_no_esconde_el_detalle_al_navegador_regla_5():
    cuerpo = _funcion("const confirmarLoteDeConciliacion", hasta=1200)

    assert "notaDeFalla('pedido-accion', respuesta);" in cuerpo


# ------------------------------------------------------------------- el CSS


def test_el_css_reusa_las_variables_de_siempre_y_no_estrena_color():
    css = pantalla_completa().split("<style>", 1)[1].split("</style>", 1)[0]
    inicio = css.index(".conciliacion")
    bloque = css[inicio : css.index("\n\n", inicio) if "\n\n" in css[inicio:] else inicio + 900]

    assert "#" not in bloque
    assert "rgb" not in bloque
    for variable in ("--tenue", "--aviso", "--mal"):
        assert variable in bloque
