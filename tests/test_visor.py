"""El botón de abrir sesión tiene que decir A DÓNDE ASOMARSE, y abrir una sola.

**Nació de una falla real del 2026-09-21 al 22.** El dueño le dio a «Abrir
sesión», no vio nada, y volvió a darle ocho veces en once segundos. El botón
funcionó las nueve: los dos journals lo prueban —`continental-web` registra el
primer clic a las 19:30:26 y los ocho siguientes contestando *"ya había una
ventana esperando"*—. Lo que faltaba no era la ventana: era la dirección para
verla. El texto de la ruta mandaba a *"la máquina donde corre Doyle"*, escrito
el 2026-09-19 cuando Doyle corría en la torre, y para el 21 Doyle ya vivía en
atlas, que no tiene monitor.

En medio, a las 19:39:50, hay un `404` del visor: entró a la raíz de noVNC, que
sirve un listado de archivos sin `index.html`, y no había forma de saber que de
esa lista hay que darle clic a `vnc.html`.

La segunda mitad de este archivo cubre una falla que todavía **no** ha pasado y
que no queremos medir: el visor muestra la pantalla entera de atlas, Doyle no
serializa nada, y con dos portales abiertos a la vez la contraseña de uno puede
acabar tecleada en el otro. Eso no se deshace con un clic: se deshace cambiando
la contraseña. Por eso Continental bloquea la segunda (ADR 0018).
"""

import pytest

from continental import config


# =========================================================================
# A DÓNDE ASOMARSE
# =========================================================================


def test_la_respuesta_trae_la_direccion_del_visor(cliente):
    """Sin esto la ventana se abre donde nadie la ve, que es lo que pasó."""
    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is True
    assert respuesta["visor"], "sin la dirección, el botón vuelve a no decir nada"
    assert respuesta["visor"].endswith("/vnc.html"), (
        "la raíz de noVNC sirve un listado de archivos: la dirección tiene que "
        "llevar a la ventana, no a un índice que nadie sabe leer"
    )


def test_el_texto_ya_no_manda_a_la_maquina_donde_corre_doyle(cliente):
    """Esa frase era verdad hasta el 2026-09-21 y después mandaba a un
    servidor sin monitor. Es la frase exacta que costó la tarde."""
    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert "máquina donde corre Doyle" not in respuesta["siguiente"]
    assert "VISOR" in respuesta["siguiente"]


def test_sin_la_llave_en_el_yaml_el_boton_lo_dice_en_vez_de_callarse(
    cliente, monkeypatch, tmp_path
):
    """Regla 4. Mandar a la persona a buscar la ventana por su cuenta es la
    misma falla silenciosa con otro disfraz."""
    yml = tmp_path / "continental.yml"
    yml.write_text("modulos: {}\npedido: {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG", yml)
    config.cargar.cache_clear()
    try:
        respuesta = cliente.post("/api/sesion/nadro/abrir").json()

        assert respuesta["ok"] is True, "la ventana SÍ se abrió: eso no se niega"
        assert respuesta["visor"] is None
        assert "visor_de_doyle" in respuesta["siguiente"]
    finally:
        config.cargar.cache_clear()


def test_la_direccion_del_visor_es_configuracion_y_no_esta_en_el_codigo():
    """El día que cambie el hostname, cambia en el YAML y en ningún otro lado.

    Es la misma regla que `a_quien_avisar`, y por la misma razón: un hostname
    escrito en Python se encuentra cuando ya falló.
    """
    yml = (config.RAIZ / "config" / "continental.yml").read_text(encoding="utf-8")
    app = (
        config.RAIZ / "src" / "continental" / "web" / "app.py"
    ).read_text(encoding="utf-8")

    assert "visor_de_doyle:" in yml
    assert "doyle.farfanlab.uk" not in app, (
        "el hostname del visor no se escribe en el código"
    )


# =========================================================================
# UNA VENTANA A LA VEZ (ADR 0018)
# =========================================================================


def _esperando(doyle, proveedor: str, nombre: str) -> None:
    """Deja a ese proveedor con su ventana abierta esperando, como el Doyle
    real: `abrir` puebla el diccionario del que `listar` saca `abriendo`."""
    doyle.sesiones_en_memoria.append({"proveedor": proveedor, "nombre": nombre})
    doyle.abrir_sesion(proveedor)


def test_con_otra_ventana_esperando_no_se_abre_la_segunda(cliente, doyle):
    """La falla que este bloqueo evita entrega una credencial real a un
    tercero, y no se deshace: se cambia la contraseña."""
    _esperando(doyle, "levic", "LEVIC")

    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is False
    assert "LEVIC" in respuesta["detalle"]
    assert doyle.sesiones_abriendose == ["levic"], (
        "no basta con avisar: la segunda ventana no se abre"
    )


def test_el_bloqueo_dice_que_hacer_y_no_solo_que_no(cliente, doyle):
    """Regla 4: un "no" sin salida deja a la persona igual de atorada."""
    _esperando(doyle, "levic", "LEVIC")

    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert "Ya entré" in respuesta["que_hacer"]
    assert "LEVIC" in respuesta["que_hacer"]


def test_el_mismo_proveedor_sigue_pasando(cliente, doyle):
    """El bloqueo es contra OTRO portal. Volver a darle al mismo es el caso
    ya cubierto de "ya había una ventana esperando", y no se rompe."""
    _esperando(doyle, "levic", "LEVIC")

    respuesta = cliente.post("/api/sesion/levic/abrir").json()

    assert respuesta["ok"] is True
    assert respuesta["ya_abierta"] is True


def test_confirmada_la_primera_se_abre_la_siguiente(cliente, doyle):
    """El bloqueo es una fila, no una puerta cerrada: al terminar con una,
    la siguiente abre. Sin esto, abrir los cuatro portales sería imposible."""
    _esperando(doyle, "levic", "LEVIC")
    cliente.post("/api/sesion/levic/confirmar")

    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is True
    assert "nadro" in doyle.sesiones_abriendose


def test_doyle_apagado_no_se_disfraza_de_bloqueo(cliente, doyle):
    """Si no se puede preguntar quién está abriendo, el motivo que se dice es
    el de Doyle caído y no un "termina con el otro" inventado."""
    doyle.falla = RuntimeError("connection refused a 127.0.0.1:8383")

    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is False
    assert "RuntimeError" in respuesta["detalle"]
    assert "termina" not in respuesta["detalle"].lower()


# =========================================================================
# LA PANTALLA
# =========================================================================


@pytest.mark.parametrize(
    "fragmento",
    [
        "window.open",          # el popup
        "notaConEnlace",        # y el enlace de respaldo, siempre
        "respuesta.visor",      # la dirección viene del servidor
    ],
)
def test_la_pantalla_abre_el_visor_y_deja_el_enlace(fragmento):
    """Popup MÁS enlace. El popup es la ruta buena; un bloqueador de ventanas
    lo puede impedir sin avisar, y entonces la pantalla volvería a no decir a
    dónde ir, que es exactamente la falla de la que nace este archivo."""
    js = (
        config.RAIZ / "src" / "continental" / "web" / "static" / "continental.js"
    ).read_text(encoding="utf-8")

    assert fragmento in js


def test_la_pantalla_ya_no_manda_a_la_maquina_donde_doyle_corre():
    """La misma frase caduca, en el otro lado."""
    js = (
        config.RAIZ / "src" / "continental" / "web" / "static" / "continental.js"
    ).read_text(encoding="utf-8")

    assert "máquina donde Doyle corre" not in js
