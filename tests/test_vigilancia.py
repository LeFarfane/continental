"""La pestaña de Vigilancia (2026-09-28): la de Doyle, dibujada aquí.

Doyle la tenía en su web (su ADR 0007): productos que faltan, revisados solo a
las 9:30 y 19:30, con un aviso cuando alguno aparece. Se quedó sin pantalla el
2026-09-21 igual que Buscar. La lista, el reloj y las búsquedas siguen siendo
de Doyle; Continental la dibuja y hace «Revisar ahora» en un hilo, porque en
Doyle esa petición bloquea minutos enteros.

Ninguna prueba toca Doyle, ni la red, ni arranca un hilo, ni duerme.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re

import httpx
import pytest

from conftest import pantalla_completa
from continental import config
from continental.doyle import (
    TOPE_DE_LA_REVISION_SEG,
    ArticuloVigilado,
    DoylePorHttp,
    VigiladoDesconocido,
)
from continental.fallas import DOYLE, que_hacer
from continental.vigilancia import (
    FRASE_SIN_ARTICULOS,
    RegistroDeRevision,
    articulo_como_json,
    frase_de_los_avisos,
    frase_del_articulo,
    frase_del_error,
    motivo_de_proveedores_desconocidos,
    revision_como_json,
)
from continental.web.app import YA_NO_SE_VIGILA

RUTA = "/api/vigilancia"
FIRMA = {"Cf-Access-Authenticated-User-Email": "encargado@farmacia.mx"}


def _articulo(**campos) -> ArticuloVigilado:
    return ArticuloVigilado(**{"articulo_id": 1, "termino": "PARACETAMOL", **campos})


def _en_memoria(**campos) -> dict:
    return {"articulo_id": 1, "termino": "PARACETAMOL", **campos}


# =========================================================================
# EL CONTRATO CON DOYLE
# =========================================================================


def _doyle(contestar) -> DoylePorHttp:
    return DoylePorHttp(url="http://127.0.0.1:8383", transporte=httpx.MockTransport(contestar))


def test_la_fila_de_doyle_se_lee_con_la_forma_que_su_tabla_tiene_hoy():
    """La forma, copiada de `Doyle/src/doyle/web/db.py` (tabla `vigilancia`) y
    de su `GET /api/vigilancia` el 2026-09-28: `proveedores` como texto con
    comas (vacío = los cuatro) y `avisado` como 0/1 de SQLite."""
    fila = {
        "id": 7, "termino": "SIGDAN", "proveedores": "nadro,levic", "estado": "disponible",
        "disponible_desde": "2026-09-28T09:31:02.114", "avisado": 0,
        "ultima_revision": "2026-09-28T09:31:02.114", "ultimo_error": None,
        "creado_en": "2026-09-27 18:00:00",
    }
    doyle = _doyle(lambda r: httpx.Response(200, json={"items": [fila]}))

    [articulo] = doyle.vigilados()

    assert articulo == ArticuloVigilado(
        articulo_id=7, termino="SIGDAN", proveedores=("nadro", "levic"), estado="disponible",
        avisado=False, disponible_desde="2026-09-28T09:31:02.114",
        ultima_revision="2026-09-28T09:31:02.114", ultimo_error=None,
    )


def test_agregar_manda_los_proveedores_como_lista_como_los_pide_doyle():
    pedidas = []

    def contestar(peticion):
        pedidas.append(json.loads(peticion.content))
        return httpx.Response(200, json={"id": 1, "termino": "SIGDAN", "proveedores": "", "avisado": 0})

    _doyle(contestar).vigilar("SIGDAN", ())

    assert pedidas == [{"termino": "SIGDAN", "proveedores": []}]


@pytest.mark.parametrize("verbo", ["dejar_de_vigilar", "marcar_visto"])
def test_un_articulo_que_doyle_ya_no_tiene_no_es_un_doyle_caido(verbo):
    doyle = _doyle(lambda r: httpx.Response(404, json={"detail": "no está"}))

    with pytest.raises(VigiladoDesconocido):
        getattr(doyle, verbo)(3)


def test_revisar_ahora_espera_con_el_tope_largo_y_no_con_el_del_yaml():
    """Doyle bloquea esa petición mientras visita cada portal: con los 10 s
    del YAML se cortaría siempre."""
    esperas = []

    def contestar(peticion):
        esperas.append(peticion.extensions["timeout"]["read"])
        return httpx.Response(200, json={"ok": True})

    DoylePorHttp(url="http://127.0.0.1:8383", timeout_seg=10,
                 transporte=httpx.MockTransport(contestar)).revisar_la_vigilancia()

    assert esperas == [TOPE_DE_LA_REVISION_SEG]


# =========================================================================
# LAS FRASES
# =========================================================================


def test_lo_nunca_revisado_dice_cuando_lo_va_a_revisar_doyle():
    frase = frase_del_articulo(_articulo())

    assert "9:30" in frase and "19:30" in frase and "Revisar ahora" in frase


def test_lo_que_ya_hay_dice_desde_cuando_y_manda_a_buscar_donde():
    """Doyle guarda SI ya hay, no EN CUÁL ni a cómo."""
    frase = frase_del_articulo(_articulo(
        estado="disponible",
        disponible_desde="2026-09-28T09:31:02",
        ultima_revision="2026-09-28T19:30:40",
    ))

    assert "desde el lunes 28 de septiembre a las 09:31" in frase
    assert "búscalo" in frase
    assert "19:30" in frase


def test_un_instante_con_zona_se_dice_en_la_hora_de_la_farmacia():
    frase = frase_del_articulo(_articulo(estado="agotado", ultima_revision="2026-09-28T15:30:00+00:00"))

    assert "a las 09:30" in frase


def test_un_instante_que_no_se_puede_leer_se_ensena_tal_cual():
    assert "ayer temprano" in frase_del_articulo(_articulo(estado="agotado", ultima_revision="ayer temprano"))


@pytest.mark.parametrize(
    ("proveedores", "dice"),
    [((), "en los cuatro proveedores"), (("vicma",), "solo en VICMA"),
     (("nadro", "levic", "quepharma"), "en NADRO, LEVIC y QuePharma")],
)
def test_en_que_proveedores_se_vigila_se_dice_con_los_nombres_del_glosario(proveedores, dice):
    assert dice in frase_del_articulo(_articulo(proveedores=proveedores))


def test_un_estado_que_doyle_estrene_se_ensena_y_no_se_esconde():
    assert "«revisando»" in frase_del_articulo(_articulo(estado="revisando", ultima_revision="2026-09-28T09:30:00"))


def test_una_revision_con_errores_avisa_que_el_estado_puede_ser_de_antes():
    """Si ningún proveedor contestó, Doyle no toca el estado (su ADR 0007):
    "no hay" podría ser de una revisión anterior."""
    assert frase_del_error(_articulo()) is None
    error = frase_del_error(_articulo(ultimo_error="levic: la sesión caducó\ndetalle largo"))

    assert "revisión anterior" in error
    assert error.endswith("levic: la sesión caducó")


def test_el_aviso_es_solo_de_lo_que_ya_hay_y_nadie_ha_visto():
    articulos = [
        _articulo(articulo_id=1, termino="UNO", estado="disponible"),
        _articulo(articulo_id=2, termino="DOS", estado="disponible", avisado=True),
        _articulo(articulo_id=3, termino="TRES", estado="agotado"),
    ]

    assert [articulo_como_json(a)["aviso_pendiente"] for a in articulos] == [True, False, False]
    assert frase_de_los_avisos(articulos) == "Ya hay de lo que se vigilaba: UNO. Míralo en Vigilancia."
    assert frase_de_los_avisos(articulos[1:]) is None


def test_un_proveedor_que_no_existe_no_se_filtra_en_silencio():
    """Doyle lo tiraría sin decir nada, y el artículo quedaría vigilado en los
    cuatro creyendo que era en uno."""
    assert motivo_de_proveedores_desconocidos(["nadro", "qpharma"]) is not None
    assert motivo_de_proveedores_desconocidos(["nadro", "quepharma"]) is None


# =========================================================================
# «REVISAR AHORA», EN UN HILO
# =========================================================================


class _Reloj:
    def __init__(self):
        self.instante = dt.datetime(2026, 9, 28, 16, 14, tzinfo=dt.UTC)

    def __call__(self):
        return self.instante


def test_mientras_una_revision_sigue_no_se_lanza_otra():
    """Dos clics serían dos pasadas por los portales del dueño."""
    pendientes = []
    registro = RegistroDeRevision(lanzar=pendientes.append)

    primera, nueva = registro.pedir("a@farmacia.mx", lambda: None)
    segunda, otra_nueva = registro.pedir("b@farmacia.mx", lambda: None)

    assert nueva and not otra_nueva
    assert segunda is primera and len(pendientes) == 1
    pendientes[0]()
    assert registro.ultima().ok is True
    assert registro.pedir("b@farmacia.mx", lambda: None)[1] is True


def test_una_revision_que_falla_guarda_el_tipo_y_no_el_texto(caplog):
    reloj = _Reloj()
    registro = RegistroDeRevision(lanzar=lambda tarea: tarea(), ahora=reloj)

    def truena():
        raise httpx.ReadTimeout("postgresql://usuario:SECRETO@host")

    with caplog.at_level(logging.ERROR, logger="continental"):
        registro.pedir("a@farmacia.mx", truena)

    ultima = registro.ultima()
    assert (ultima.ok, ultima.detalle) == (False, "Doyle no terminó la revisión (ReadTimeout)")
    assert any(r.exc_info for r in caplog.records)


def test_como_va_la_revision_se_dice_en_la_hora_de_la_farmacia():
    reloj = _Reloj()
    pendientes = []
    registro = RegistroDeRevision(lanzar=pendientes.append, ahora=reloj)
    registro.pedir("a@farmacia.mx", lambda: None)

    en_curso = revision_como_json(registro.ultima(), "qué hacer")
    reloj.instante += dt.timedelta(minutes=6)
    pendientes[0]()
    terminada = revision_como_json(registro.ultima(), "qué hacer")

    assert en_curso["en_curso"] is True and "10:14" in en_curso["frase"]
    assert en_curso["sondeo_ms"] > 0
    assert terminada["ok"] is True and "10:20" in terminada["frase"]
    assert revision_como_json(None, "qué hacer") is None


# =========================================================================
# LAS RUTAS
# =========================================================================


def test_la_lista_trae_sus_frases_el_aviso_y_los_cuatro_proveedores(cliente, doyle):
    doyle.vigilados_en_memoria = [
        _en_memoria(articulo_id=1, termino="UNO", estado="disponible",
                    ultima_revision="2026-09-28T09:30:10", disponible_desde="2026-09-28T09:30:10"),
        _en_memoria(articulo_id=2, termino="DOS"),
    ]

    datos = cliente.get(RUTA).json()

    assert datos["ok"] is True
    assert [a["termino"] for a in datos["articulos"]] == ["DOS", "UNO"]  # lo más nuevo primero
    assert datos["avisos"] == "Ya hay de lo que se vigilaba: UNO. Míralo en Vigilancia."
    assert [p["nombre"] for p in datos["proveedores"]] == ["NADRO", "LEVIC", "VICMA", "QuePharma"]
    assert datos["frase"] is None and datos["revision"] is None


def test_una_lista_vacia_lo_dice_el_servidor(cliente):
    assert cliente.get(RUTA).json()["frase"] == FRASE_SIN_ARTICULOS


def test_doyle_caido_es_un_hueco_con_que_hacer_y_la_revision_se_sigue_diciendo(
    cliente, doyle, revision
):
    pendientes = []
    revision.lanzar = pendientes.append
    cliente.post(f"{RUTA}/revisar", headers=FIRMA)
    doyle.falla = RuntimeError("SECRETO")

    respuesta = cliente.get(RUTA)

    datos = respuesta.json()
    assert datos["ok"] is False
    assert datos["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert datos["revision"]["en_curso"] is True
    assert "SECRETO" not in respuesta.text


def test_agregar_le_pasa_a_doyle_el_termino_limpio_y_los_proveedores(cliente, doyle):
    datos = cliente.post(RUTA, json={"termino": "  sigdan  20mg ", "proveedores": ["nadro", "nadro"]},
                         headers=FIRMA).json()

    assert datos["ok"] is True
    assert doyle.vigilados_en_memoria[0]["termino"] == "sigdan 20mg"
    assert doyle.vigilados_en_memoria[0]["proveedores"] == ("nadro",)


@pytest.mark.parametrize("cuerpo", [
    {"termino": "   "},
    {"termino": "x" * 101},
    {"termino": "SIGDAN", "proveedores": ["qpharma"]},
])
def test_lo_que_no_se_puede_vigilar_no_llega_a_doyle(cliente, doyle, cuerpo):
    respuesta = cliente.post(RUTA, json=cuerpo)

    assert respuesta.status_code == 400
    assert respuesta.json()["que_hacer"]
    assert doyle.vigilados_en_memoria == []


def test_quitar_lo_quita_y_quitar_lo_que_ya_no_esta_lo_dice(cliente, doyle):
    doyle.vigilados_en_memoria = [_en_memoria()]

    assert cliente.delete(f"{RUTA}/1").json()["ok"] is True
    otra_vez = cliente.delete(f"{RUTA}/1")

    assert doyle.vigilados_en_memoria == []
    assert otra_vez.status_code == 404
    assert otra_vez.json()["detalle"] == YA_NO_SE_VIGILA and otra_vez.json()["que_hacer"]


def test_ya_lo_vi_apaga_el_aviso_sin_tocar_el_estado(cliente, doyle):
    doyle.vigilados_en_memoria = [_en_memoria(estado="disponible")]

    assert cliente.post(f"{RUTA}/1/visto").json()["ok"] is True
    datos = cliente.get(RUTA).json()

    assert datos["avisos"] is None
    assert datos["articulos"][0]["estado"] == "disponible"


def test_revisar_ahora_se_lo_pide_a_doyle_y_vuelve_con_como_termino(cliente, doyle):
    datos = cliente.post(f"{RUTA}/revisar", headers=FIRMA).json()

    assert datos["ok"] is True and datos["nueva"] is True
    assert doyle.revisiones == 1
    assert datos["revision"]["ok"] is True


def test_revisar_dos_veces_mientras_sigue_no_manda_dos_pasadas(cliente, doyle, revision):
    pendientes = []
    revision.lanzar = pendientes.append

    cliente.post(f"{RUTA}/revisar", headers=FIRMA)
    segunda = cliente.post(f"{RUTA}/revisar", headers=FIRMA).json()

    assert segunda["nueva"] is False and segunda["revision"]["en_curso"] is True
    assert len(pendientes) == 1


def test_una_revision_que_doyle_no_termino_dice_que_hacer(cliente, doyle):
    doyle.falla = RuntimeError("SECRETO")

    respuesta = cliente.post(f"{RUTA}/revisar", headers=FIRMA)

    como_va = respuesta.json()["revision"]
    assert como_va["ok"] is False and como_va["que_hacer"]
    assert "SECRETO" not in respuesta.text


# =========================================================================
# LA PANTALLA
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_el_aviso_vive_fuera_de_las_pestanas():
    """Tiene que verse aunque nadie abra la pestaña de Vigilancia."""
    pantalla = pantalla_completa()
    aviso = pantalla.index('id="avisos-vigilancia"')

    assert pantalla.index("</nav>") < aviso < pantalla.index('id="panel-pedido"')


def test_la_vigilancia_se_carga_al_abrir_la_pagina():
    """Sin esto, el aviso de "ya hay" solo saldría a quien abriera la pestaña."""
    script = _script()
    iniciar = script[script.index("const iniciarVigilancia"):]

    assert re.search(r"\niniciarVigilancia\(\);", script)
    assert "cargarVigilancia();\n};" in iniciar.replace("\r\n", "\n")


def test_la_pantalla_pregunta_como_va_la_revision_con_el_numero_del_servidor():
    script = _script()

    assert "datos.revision.sondeo_ms" in script
    assert "clearTimeout(SONDEO_DE_LA_VIGILANCIA)" in script


def test_lo_que_ya_hay_se_busca_con_la_pestana_de_buscar():
    """Doyle guarda SI ya hay, no EN CUÁL: eso lo contesta una búsqueda."""
    script = _script()

    assert "buscarDesdeOtraPestana(a.termino)" in script
    assert "mostrarPestana('buscar')" in script


def test_la_pantalla_pinta_las_frases_de_la_vigilancia_del_servidor():
    script = _script()

    for llave in ("a.frase", "a.etiqueta", "a.error", "datos.avisos", "datos.frase", "a.aviso_pendiente"):
        assert llave in script, llave
