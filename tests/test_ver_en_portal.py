"""«Ver en el portal» y «Ya vi» (ADR 0026): las rutas, las frases y el borde HTTP.

Ninguna prueba abre un navegador, le habla a Doyle ni toca Postgres: Doyle es
`DoyleFalso` (o un `httpx.MockTransport` para el borde) y el almacenamiento es
el doble en memoria. Mirar no guarda nada, y por eso varias pruebas afirman que
no quedó ninguna fila ni se tocó la sesión.
"""

from __future__ import annotations

import json

import httpx
import pytest

from continental import config
from continental.doyle import (
    TOPE_DE_VER_EN_PORTAL_SEG,
    DoylePorHttp,
    ProveedorDesconocido,
    VisorOcupado,
    VistaAbierta,
    VistaDesconocida,
)
from continental.vista_del_portal import SIN_VISOR, frase_de_cerrar, frase_de_ver

from test_precio import CLAVE, _poblar, _primer_renglon

LOS_CUATRO = ("levic", "nadro", "quepharma", "vicma")


def _ver(cliente, proveedor: str, renglon_id: int | None):
    cuerpo = {} if renglon_id is None else {"renglon_id": renglon_id}
    return cliente.post(f"/api/proveedor/{proveedor}/ver", json=cuerpo)


@pytest.fixture
def renglon(cliente, almacen):
    _poblar(almacen)
    return _primer_renglon(cliente)


# =========================================================================
# LA RUTA DE VER
# =========================================================================


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_ver_le_pide_a_doyle_el_ean_del_renglon_en_ese_proveedor(
    cliente, doyle, renglon, proveedor
):
    respuesta = _ver(cliente, proveedor, renglon["renglon_id"]).json()

    assert respuesta["ok"] is True
    assert doyle.vistas_pedidas == [(proveedor, CLAVE)]
    assert doyle.vistas_abiertas == {proveedor: CLAVE}


def test_la_respuesta_trae_el_visor_y_la_frase_hecha(cliente, renglon):
    respuesta = _ver(cliente, "nadro", renglon["renglon_id"]).json()

    assert respuesta["visor"] == config.cargar().visor_de_doyle
    assert "NADRO" in respuesta["mensaje"]
    assert CLAVE in respuesta["mensaje"]
    assert "«Ya vi»" in respuesta["mensaje"]


def test_el_ean_sale_del_renglon_y_no_de_lo_que_mande_el_navegador(
    cliente, doyle, renglon
):
    """Un cuerpo con un `termino` ajeno se ignora: lo único que cuenta es el
    renglón. Buscar en un portal con la cuenta del dueño lo que cualquiera
    escriba sería abrirle esa cuenta a quien alcance el puerto."""
    cliente.post(
        "/api/proveedor/nadro/ver",
        json={"renglon_id": renglon["renglon_id"], "termino": "otra-cosa", "ean": "1"},
    )

    assert doyle.vistas_pedidas == [("nadro", CLAVE)]


def test_una_tarjeta_sin_dato_tambien_se_puede_ver(cliente, doyle, renglon):
    """El renglón no tiene ningún precio consultado: es justo donde sirve."""
    assert not renglon.get("precios")

    assert _ver(cliente, "vicma", renglon["renglon_id"]).json()["ok"] is True


def test_ya_abierta_se_dice_sin_error(cliente, doyle, renglon):
    _ver(cliente, "nadro", renglon["renglon_id"])
    respuesta = _ver(cliente, "nadro", renglon["renglon_id"]).json()

    assert respuesta["ok"] is True
    assert respuesta["ya_abierta"] is True
    assert "misma vista" in respuesta["mensaje"]
    assert len(doyle.vistas_abiertas) == 1


def test_parece_login_lo_dice_la_frase(cliente, doyle, renglon):
    doyle.vistas_que_parecen_login.append("levic")

    respuesta = _ver(cliente, "levic", renglon["renglon_id"]).json()

    assert respuesta["ok"] is True
    assert respuesta["parece_login"] is True
    assert "parece caída" in respuesta["mensaje"]
    assert "se ve el login" in respuesta["mensaje"]


def test_sin_visor_configurado_la_frase_lo_dice(cliente, renglon, monkeypatch):
    ajustes = config.cargar()
    monkeypatch.setattr(
        "continental.web.app.cargar",
        lambda: type(ajustes)(**{**ajustes.__dict__, "visor_de_doyle": None}),
    )

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"]).json()

    assert respuesta["ok"] is True
    assert respuesta["visor"] is None
    assert SIN_VISOR in respuesta["mensaje"]


def test_el_409_de_doyle_llega_con_su_frase(cliente, doyle, renglon):
    doyle.proveedores_consultando.append("nadro")

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"])

    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert "está consultando ahora" in cuerpo["detalle"]
    assert cuerpo["que_hacer"]


def test_ver_otro_proveedor_reemplaza_la_vista_abierta(cliente, doyle, renglon):
    """Como el Doyle real: la vista nueva cierra la vieja, sin 409."""
    _ver(cliente, "nadro", renglon["renglon_id"])

    respuesta = _ver(cliente, "levic", renglon["renglon_id"])

    assert respuesta.status_code == 200
    assert respuesta.json()["ya_abierta"] is False
    assert doyle.vistas_abiertas == {"levic": CLAVE}


def test_con_una_sesion_esperando_el_visor_esta_ocupado(cliente, doyle, renglon):
    doyle.abrir_sesion("levic")

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"])

    assert respuesta.status_code == 409
    assert "sesión" in respuesta.json()["detalle"]


def test_si_doyle_tarda_mas_del_tope_la_frase_dice_que_pudo_abrirse(cliente, doyle, renglon):
    doyle.falla = httpx.ReadTimeout("secreto interno")

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"]).json()

    assert respuesta["ok"] is False
    assert "tardó demasiado" in respuesta["detalle"]
    assert "sí se haya abierto" in respuesta["detalle"]
    assert "secreto" not in str(respuesta)


def test_ver_espera_a_doyle_un_tope_propio_y_cerrar_el_corto():
    esperas = {}

    def contestar(peticion):
        esperas[peticion.url.path] = peticion.extensions["timeout"]["read"]
        return httpx.Response(200, json={"ok": True})

    doyle = DoylePorHttp(url="http://127.0.0.1:8383", timeout_seg=10,
                         transporte=httpx.MockTransport(contestar))
    doyle.ver_en_portal("nadro", CLAVE)
    doyle.cerrar_vista("nadro")

    assert esperas["/api/ver/nadro"] == TOPE_DE_VER_EN_PORTAL_SEG == 60.0
    assert esperas["/api/ver/nadro/cerrar"] == 10


def test_doyle_caido_es_doyle_no_responde_sin_el_texto_de_la_excepcion(
    cliente, doyle, renglon
):
    doyle.falla = RuntimeError("postgresql://continental:SECRETO@atlas/farmacia")

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"]).json()

    assert respuesta["ok"] is False
    assert "Doyle no responde" in respuesta["detalle"]
    assert "RuntimeError" in respuesta["detalle"]
    assert "SECRETO" not in str(respuesta)
    assert "postgresql" not in str(respuesta)
    assert respuesta["que_hacer"]


def test_un_proveedor_inventado_es_400_y_no_llega_a_doyle(cliente, doyle, renglon):
    respuesta = _ver(cliente, "farmacias-x", renglon["renglon_id"])

    assert respuesta.status_code == 400
    assert doyle.vistas_pedidas == []


def test_sin_renglon_es_422_y_no_llega_a_doyle(cliente, doyle):
    respuesta = _ver(cliente, "nadro", None)

    assert respuesta.status_code == 422
    assert doyle.vistas_pedidas == []


def test_un_renglon_que_no_existe_es_404(cliente, doyle, renglon):
    respuesta = _ver(cliente, "nadro", renglon["renglon_id"] + 999)

    assert respuesta.status_code == 404
    assert doyle.vistas_pedidas == []


def test_un_renglon_sin_clave_no_se_busca_por_nombre(cliente, doyle, almacen):
    _poblar(almacen, clave="")
    renglon = _primer_renglon(cliente)

    respuesta = _ver(cliente, "nadro", renglon["renglon_id"])

    assert respuesta.status_code == 422
    assert "código de barras" in respuesta.json()["detalle"]
    assert doyle.vistas_pedidas == []


def test_ver_firma_en_la_bitacora_quien_lo_pidio(cliente, renglon, caplog):
    caplog.set_level("INFO")

    cliente.post(
        "/api/proveedor/nadro/ver",
        json={"renglon_id": renglon["renglon_id"]},
        headers={"Cf-Access-Authenticated-User-Email": "encargada@ejemplo.mx"},
    )

    assert any("encargada@ejemplo.mx" in m and "nadro" in m for m in caplog.messages)


def test_mirar_no_toca_la_sesion_ni_el_pedido(cliente, doyle, almacenamiento, renglon):
    _ver(cliente, "nadro", renglon["renglon_id"])

    assert doyle.sesiones_confirmadas == []
    assert doyle.sesiones_abriendose == []
    assert almacenamiento.pruebas_de_sesion == []


# =========================================================================
# YA VI
# =========================================================================


def test_ya_vi_le_pide_a_doyle_cerrar_la_vista(cliente, doyle, renglon):
    _ver(cliente, "nadro", renglon["renglon_id"])

    respuesta = cliente.post("/api/proveedor/nadro/ver/cerrar").json()

    assert respuesta["ok"] is True
    assert doyle.vistas_cerradas == ["nadro"]
    assert doyle.vistas_abiertas == {}
    assert respuesta["visor"] == config.cargar().visor_de_doyle
    assert "Se cerró la vista de NADRO" in respuesta["mensaje"]


def test_ya_vi_con_404_de_doyle_se_trata_como_ya_cerrada_sin_error(cliente, doyle):
    """Doyle la cierra sola por tope: el clic llega tarde y no es una falla."""
    respuesta = cliente.post("/api/proveedor/nadro/ver/cerrar")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert "ya estaba cerrada" in cuerpo["mensaje"]
    assert "que_hacer" not in cuerpo


def test_ya_vi_con_doyle_caido_dice_que_puede_seguir_abierta(cliente, doyle):
    doyle.falla = RuntimeError("detalle interno")

    cuerpo = cliente.post("/api/proveedor/nadro/ver/cerrar").json()

    assert cuerpo["ok"] is False
    assert "Doyle no responde" in cuerpo["detalle"]
    assert "siga abierta" in cuerpo["detalle"]
    assert "detalle interno" not in str(cuerpo)


def test_ya_vi_con_proveedor_inventado_es_400(cliente):
    assert cliente.post("/api/proveedor/xx/ver/cerrar").status_code == 400


# =========================================================================
# LAS FRASES
# =========================================================================


def test_frase_de_ver_sin_login_ni_repeticion():
    frase = frase_de_ver("nadro", CLAVE, ya_abierta=False, parece_login=False, hay_visor=True)

    assert frase.startswith("Doyle abrió NADRO en el visor")
    assert "parece" not in frase


def test_frase_de_cerrar_las_dos_formas():
    assert "Se cerró" in frase_de_cerrar("levic", ya_estaba_cerrada=False)
    assert "ya estaba cerrada" in frase_de_cerrar("levic", ya_estaba_cerrada=True)


# =========================================================================
# EL BORDE HTTP (contrato fijo con Doyle)
# =========================================================================


def _doyle(contestar) -> DoylePorHttp:
    return DoylePorHttp(url="http://127.0.0.1:8383", transporte=httpx.MockTransport(contestar))


def test_el_borde_manda_el_termino_y_lee_la_respuesta():
    vistas = []

    def contestar(peticion):
        vistas.append((peticion.method, peticion.url.path, json.loads(peticion.read())))
        return httpx.Response(200, json={"ok": True, "ya_abierta": True, "parece_login": True})

    resultado = _doyle(contestar).ver_en_portal("nadro", CLAVE)

    assert vistas == [("POST", "/api/ver/nadro", {"termino": CLAVE})]
    assert resultado == VistaAbierta("nadro", ya_abierta=True, parece_login=True)


def test_el_borde_traduce_409_404_y_5xx():
    ocupado = _doyle(lambda p: httpx.Response(409, json={"detail": "Visor ocupado por LEVIC."})
                     ).ver_en_portal("nadro", CLAVE)
    assert ocupado == VisorOcupado("Visor ocupado por LEVIC.")

    sin_frase = _doyle(lambda p: httpx.Response(409, text="<html>")).ver_en_portal("nadro", CLAVE)
    assert isinstance(sin_frase, VisorOcupado)
    assert "<html>" not in sin_frase.detalle

    with pytest.raises(ProveedorDesconocido):
        _doyle(lambda p: httpx.Response(404)).ver_en_portal("zz", CLAVE)

    with pytest.raises(httpx.HTTPStatusError):
        _doyle(lambda p: httpx.Response(500)).ver_en_portal("nadro", CLAVE)


def test_el_borde_cierra_y_traduce_el_404():
    rutas = []

    def contestar(peticion):
        rutas.append((peticion.method, peticion.url.path))
        return httpx.Response(200, json={"ok": True})

    _doyle(contestar).cerrar_vista("vicma")
    assert rutas == [("POST", "/api/ver/vicma/cerrar")]

    with pytest.raises(VistaDesconocida):
        _doyle(lambda p: httpx.Response(404)).cerrar_vista("vicma")
