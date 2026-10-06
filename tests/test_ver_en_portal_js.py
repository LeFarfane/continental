"""«Ver en el portal» y «Ya vi», el lado de la pantalla (ADR 0026).

Este repo no ejecuta JavaScript en las pruebas (ver `test_pasada_visual.py`),
así que esto se fija con pruebas estáticas sobre el texto de la pantalla, igual
que `test_ventana_sesiones_js.py`: que CADA tarjeta lleve el botón, que no
dispare el radio, que «Ya vi» solo salga con la vista abierta, que se use el
mismo `window.open` de «Abrir sesión» y que las frases no se escriban aquí.
"""

from __future__ import annotations

import re

from conftest import cuerpo_de_funcion, pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str) -> str:
    return cuerpo_de_funcion(_script(), nombre)


def _css() -> str:
    pantalla = pantalla_completa()
    return pantalla[: pantalla.index("<script>")]


def test_cada_tarjeta_lleva_su_fila_del_portal_siempre():
    """No condicionada a que falte la cantidad ni a que haya precio: el usuario
    decidió los cuatro siempre, y un botón que aparece y desaparece confunde."""
    cuerpo = _funcion("const preciosDelDetalle =")

    assert "filaDelPortal(" in cuerpo
    # Una sola condición alrededor: que la pantalla traiga la acción (la lista
    # de detalle de otros sitios puede no traerla). Nada de `c.estado` ni `c.precio`.
    llamada = cuerpo[cuerpo.index("if (acciones.verEnElPortal)") :]
    llamada = llamada[: llamada.index("filaDelPortal(")]
    assert "estado" not in llamada and "precio" not in llamada and "existencia" not in llamada


def test_el_boton_va_fuera_de_la_linea_del_radio():
    """La línea es un `<button>` con la lista abierta: dentro de ella, el botón
    sería un botón anidado y su clic elegiría al proveedor."""
    cuerpo = _funcion("const preciosDelDetalle =")

    assert "tarjeta.append(linea)" in cuerpo
    # La fila se agrega a la tarjeta, jamás a la línea.
    assert "linea.append(filaDelPortal" not in cuerpo
    assert "tarjeta.append(filaDelPortal" in cuerpo
    assert "tarjeta-proveedor" in cuerpo


def test_el_boton_es_accesible_y_nombra_al_proveedor():
    cuerpo = _funcion("const filaDelPortal =")

    assert "botonDeAccion('Ver en el portal'" in cuerpo  # `type="button"` viene de ahí
    assert "setAttribute('aria-label', 'Ver ' + r.descripcion + ' en el portal de ' + nombre)" in cuerpo
    assert "setAttribute('aria-label', 'Ya vi el portal de ' + nombre" in cuerpo


def test_ya_vi_solo_sale_con_la_vista_de_ese_proveedor_abierta():
    cuerpo = _funcion("const filaDelPortal =")

    assert "if (VISTA_EN_PORTAL === proveedor)" in cuerpo
    assert "botonDeAccion('Ya vi'" in cuerpo
    assert re.search(r"let VISTA_EN_PORTAL = null;", _script())


def test_ver_abre_el_visor_con_el_mismo_window_open_y_el_mismo_respaldo():
    cuerpo = _funcion("async function verEnElPortal")

    assert "window.open(respuesta.visor, 'visor-doyle')" in cuerpo
    assert "notaConEnlace(" in cuerpo
    assert "El navegador bloqueó la ventana del visor." in cuerpo
    # Sin visor configurado se dice con la frase del servidor y no se abre nada.
    assert "if (!respuesta.visor)" in cuerpo


def test_ver_no_manda_el_ean_solo_el_renglon():
    cuerpo = _funcion("async function verEnElPortal")

    assert "renglon_id: r.renglon_id" in cuerpo
    assert "clave" not in cuerpo.lower().replace("claves", "")
    assert "/api/proveedor/' + proveedor + '/ver'" in cuerpo


def test_ver_recuerda_la_vista_solo_si_el_servidor_dijo_ok():
    cuerpo = _funcion("async function verEnElPortal")

    falla = cuerpo.index("if (!respuesta.ok)")
    agrega = cuerpo.index("VISTA_EN_PORTAL = proveedor")
    assert falla < agrega
    assert "notaDeFalla('pedido-accion', respuesta)" in cuerpo[falla:agrega]


def test_ya_vi_olvida_la_vista_y_trata_el_cerrada_sola_como_exito():
    cuerpo = _funcion("async function cerrarVista")

    assert "/ver/cerrar'" in cuerpo
    assert "VISTA_EN_PORTAL = null" in cuerpo
    # El 404 de Doyle lo absorbe el servidor (`ok: true`): aquí no hay rama
    # de error especial para «ya estaba cerrada».
    assert "404" not in cuerpo
    # Si falla de verdad, la vista NO se olvida: puede seguir abierta.
    assert cuerpo.index("if (!respuesta.ok)") < cuerpo.index("VISTA_EN_PORTAL = null")


def test_las_acciones_llegan_a_las_dos_construcciones_del_detalle():
    """`repintar` y `elegirRenglon` arman cada una su objeto `acciones`: si una
    se queda sin el botón, desaparece al tocar otro renglón."""
    script = _script()

    assert len(re.findall(r"verEnElPortal: verEnElPortal", script)) == 2
    assert len(re.findall(r"cerrarVista: cerrarVista", script)) == 2


def test_las_frases_no_se_escriben_en_el_javascript():
    """Las frases de Python mandan: aquí solo se pinta `respuesta.mensaje`."""
    funcion = _funcion("async function verEnElPortal") + _funcion("async function cerrarVista")

    assert "respuesta.mensaje" in funcion
    assert "parece caída" not in funcion
    assert "ya estaba cerrada" not in funcion


def test_el_css_de_la_fila_usa_solo_variables():
    css = _css()
    inicio = css.index(".tarjeta-proveedor")
    bloque = css[inicio : css.index("button.precio-detalle", inicio)]

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", bloque)
