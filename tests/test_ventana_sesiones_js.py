"""La ventana flotante de las sesiones al abrir, el lado de la pantalla
(ADR 0024, decisiones 1 y 2; ticket 05 de `.scratch/sesiones-al-abrir`).

Este repo no ejecuta JavaScript en las pruebas (ver el docstring de
`test_pasada_visual.py`), así que todo esto se fija con pruebas estáticas
sobre el texto de la pantalla, igual que `test_conciliacion_js.py`: que el
`<dialog>` exista, que la ventana y la pestaña pinten con la MISMA función,
que exista el contador de una hora y lo reinicien los clics y las teclas, y
que Esc y «Continuar» la cierren.

Ninguna prueba toca Postgres ni la red.
"""

from __future__ import annotations

import re

from conftest import cuerpo_de_funcion, pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str) -> str:
    return cuerpo_de_funcion(_script(), nombre)


def _html() -> str:
    pantalla = pantalla_completa()
    return pantalla[: pantalla.index("<script>")]


def _dialogo() -> str:
    html = _html()
    inicio = html.index('<dialog id="ventana-sesiones"')
    return html[inicio : html.index("</dialog>", inicio)]


# ------------------------------------------------------------ el <dialog>


def test_la_ventana_es_un_dialog_estatico_con_titulo_y_continuar():
    dialogo = _dialogo()

    # Se anuncia como diálogo y con nombre: <dialog> modal ya lo es, y
    # `aria-labelledby` apunta a un título que existe.
    assert 'aria-labelledby="ventana-sesiones-titulo"' in dialogo
    assert 'id="ventana-sesiones-titulo"' in dialogo
    # Los textos fijos van en el HTML y no en el JavaScript.
    assert "Continuar" in dialogo
    assert 'id="ventana-sesiones-continuar"' in dialogo


def test_la_ventana_tiene_su_lugar_para_las_tarjetas_y_sus_notas():
    dialogo = _dialogo()

    for id_ in ("ventana-sesiones-tarjetas", "ventana-sesiones-accion", "ventana-sesiones-falla"):
        assert f'id="{id_}"' in dialogo, id_
    # Las notas nacen escondidas, como las de la pestaña.
    assert re.search(r'id="ventana-sesiones-falla"[^>]*hidden', dialogo)


def test_el_foco_entra_en_la_ventana_por_un_boton_inocuo():
    """`showModal()` enfoca el primer control o el que diga `autofocus`; el
    primer control de la ventana sería un «Probar» o un «Abrir sesión»."""
    assert re.search(r'<button[^>]*id="ventana-sesiones-continuar"[^>]*autofocus', _dialogo())


# ------------------------------------------ una sola función pinta las tarjetas


def test_la_pestana_y_la_ventana_pintan_con_la_misma_funcion():
    cuerpo = _funcion("const cargarSesiones")
    script = _script()

    # Los dos sitios están en una sola lista, y cada uno pasa por la misma
    # función de pintar.
    assert "'sesiones-tarjetas'" in script and "'ventana-sesiones-tarjetas'" in script
    assert "pintarSesiones(" in cuerpo
    # Y nadie más arma tarjetas: la única llamada a `tarjetaDeSesion` está
    # dentro de la función compartida.
    assert len(re.findall(r"tarjetaDeSesion\b", script)) == 2  # declaración y uso
    assert "tarjetaDeSesion" in _funcion("const pintarSesiones")


def test_la_funcion_compartida_recibe_donde_pintar_y_a_quien_avisar():
    cuerpo = _funcion("const pintarSesiones")

    assert "const pintarSesiones = (sitio, datos, alTerminar)" in _script()
    assert "sitio.caja" in cuerpo and "sitio.falla" in cuerpo
    # El aviso de que un paso terminó es el que se recibió, no uno fijo.
    tarjeta = _funcion("const tarjetaDeSesion")
    assert "sitio.accion" in tarjeta
    assert "alTerminar" in tarjeta
    assert "cargarSesiones" not in tarjeta


def test_los_pasos_de_una_tarjeta_escriben_en_la_nota_de_su_sitio():
    """La ventana no puede escribir en la nota de la pestaña, que está
    escondida detrás de ella."""
    tarjeta = _funcion("const tarjetaDeSesion")

    for paso in ("abrirSesion", "confirmarSesion", "cancelarSesion"):
        assert f"{paso}(s, b, sitio.accion, alTerminar)" in tarjeta


def test_si_doyle_no_responde_se_pinta_el_hueco_con_su_motivo():
    cuerpo = _funcion("const pintarSesiones")

    assert "notaDeFalla(sitio.falla, datos)" in cuerpo
    # Sin tarjetas vacías: el contenedor se vacía y no se pinta nada.
    assert "sitio.caja.replaceChildren()" in cuerpo


# ------------------------------------------------------------- abrir y cerrar


def test_la_ventana_se_abre_con_showmodal_y_guarda_donde_estaba_el_foco():
    cuerpo = _funcion("const abrirLaVentanaDeSesiones")

    assert ".showModal()" in cuerpo
    assert "document.activeElement" in cuerpo
    # Pide las sesiones: abre igual si Doyle no contesta (se pinta el hueco).
    assert "cargarSesiones()" in cuerpo


def test_la_ventana_no_se_abre_encima_de_otra_ventana_ni_dos_veces():
    cuerpo = _funcion("const abrirLaVentanaDeSesiones")

    assert ".open" in cuerpo
    assert "'confirmar-cierre'" in cuerpo


def test_continuar_cierra_la_ventana():
    script = _script()

    assert re.search(r"getElementById\('ventana-sesiones-continuar'\)\.onclick\s*=", script)
    assert ".close()" in _funcion("const cerrarLaVentanaDeSesiones")


def test_esc_cierra_la_ventana_y_no_se_va_al_detalle_del_renglon():
    cuerpo = _funcion("const iniciarLaVentanaDeSesiones")
    assert "'Escape'" in cuerpo
    assert "cerrarLaVentanaDeSesiones" in cuerpo

    # El Esc del detalle del renglón se calla mientras la ventana está abierta.
    script = _script()
    inicio = script.index("if (evento.key === 'Escape' && DETALLE_ABIERTO")
    assert "ventana-sesiones" in script[inicio : inicio + 250]


def test_al_cerrar_el_foco_vuelve_a_donde_estaba():
    cuerpo = _funcion("const iniciarLaVentanaDeSesiones")

    # Se cierre como se cierre, por el evento `close` y no por un botón.
    assert "addEventListener('close'" in cuerpo
    assert "FOCO_ANTES_DE_LA_VENTANA" in cuerpo and ".focus()" in cuerpo


def test_la_ventana_sale_despues_de_la_primera_carga():
    script = _script()
    arranque = script[script.rindex("iniciarApariencia();"):]

    assert "iniciarLaVentanaDeSesiones();" in arranque


# --------------------------------------------------- la hora sin clics ni teclas


def test_existe_el_contador_de_una_hora_y_es_una_hora():
    script = _script()

    assert "const UNA_HORA_SIN_USO_MS = 60 * 60 * 1000;" in script
    assert "setTimeout(" in _funcion("const reiniciarElReposo")


def test_los_clics_y_las_teclas_reinician_el_contador():
    cuerpo = _funcion("const iniciarLaVentanaDeSesiones")

    for evento in ("'click'", "'keydown'"):
        assert evento in cuerpo, evento
    # Capturando, para que un `stopPropagation` de la pantalla no lo esconda.
    assert "addEventListener(evento, reiniciarElReposo, true)" in cuerpo


def test_el_contador_vive_en_memoria_y_no_en_el_navegador():
    """Cada computadora y cada pestaña cuentan por separado (ADR 0024)."""
    # La Apariencia sí usa `localStorage`, a propósito; lo que se mira es
    # el código de la ventana y del contador.
    codigo = "".join(
        re.sub(r"//[^\n]*", "", _funcion(f"const {nombre}"))
        for nombre in ("reiniciarElReposo", "alVencerElReposo", "abrirLaVentanaDeSesiones",
                       "iniciarLaVentanaDeSesiones")
    )

    for prohibido in ("localStorage", "sessionStorage", "BroadcastChannel", "indexedDB"):
        assert prohibido not in codigo, prohibido


def test_cuando_vence_la_hora_vuelve_a_contar_si_no_pudo_abrirse():
    cuerpo = _funcion("const alVencerElReposo")

    assert "abrirLaVentanaDeSesiones()" in cuerpo
    # Mientras alguien usa la pantalla no sale: el contador vuelve a empezar.
    assert "reiniciarElReposo()" in cuerpo


# ----------------------------------------------------------------- el CSS


def test_la_ventana_cabe_en_un_telefono_y_se_desplaza_por_dentro():
    css = pantalla_completa()
    inicio = css.rindex(".ventana-sesiones {")
    regla = css[inicio : css.index("}", inicio)]

    assert "calc(100vw - 2rem)" in regla
    assert "overflow-y: auto" in regla
    assert "max-height" in regla


def test_la_ventana_comparte_el_vidrio_del_otro_dialogo():
    """Sin colores a mano: lo vigila `test_pasada_visual.py` para todo el CSS."""
    css = pantalla_completa()

    assert re.search(r"\.ventana-sesiones[^{]*\{[^}]*var\(--material-grueso\)", css) or (
        ".confirmar-cierre, .ventana-sesiones" in css
    )
