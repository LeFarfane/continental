"""El EAN que copia y abre el portal (lista de espera, ticket 10).

Cuatro niveles, ninguno toca Postgres ni la red:

1. Lo puro: `armar_el_enlace` en sus dos modos, con sustitución múltiple,
   URL-encode, sin dirección, sin EAN y con una dirección que no es http(s).
2. El borde: `DoylePorHttp.portales` contra un `httpx.MockTransport`.
3. La ruta de punta a punta con `DoyleFalso`, con y sin respuesta de Doyle.
4. Lo estático del JavaScript, que aquí no se ejecuta: copia y abre, ventana
   nombrada por proveedor, enlace de respaldo, y no arma ninguna URL.
"""

from __future__ import annotations

import httpx
import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental.doyle import DoylePorHttp, PortalDeBusqueda
from continental.enlace_del_portal import (
    DOYLE_NO_RESPONDIO,
    PARA_PEGAR,
    SIN_CLAVE,
    YA_BUSCADO,
    armar_el_enlace,
)
from continental.particion import Captura, Linea, captura_como_json

from test_captura import _pedido_con

EAN = "7501000000001"
NADRO = PortalDeBusqueda("https://i22.nadro.mx/{termino}?_q={termino}&map=ft", True)
LEVIC = PortalDeBusqueda("https://www.levicventas.mx/frm_Catalogo_Levic.aspx", False)
QUEPHARMA = PortalDeBusqueda(None, False)
PORTALES = {"nadro": NADRO, "levic": LEVIC, "quepharma": QUEPHARMA}


# =========================================================================
# 1. LO PURO
# =========================================================================


def test_ya_buscado_sustituye_la_marca_en_todas_sus_apariciones():
    enlace = armar_el_enlace("nadro", EAN, PORTALES)

    assert enlace.modo == YA_BUSCADO
    assert enlace.url == f"https://i22.nadro.mx/{EAN}?_q={EAN}&map=ft"
    assert "{" not in enlace.url
    assert enlace.titulo == "Copiar y abrir la búsqueda en NADRO"


def test_el_ean_va_url_encoded_y_no_puede_cambiar_la_ruta():
    enlace = armar_el_enlace("nadro", "75 01/..?x=1&y#z", PORTALES)

    assert enlace.url == (
        "https://i22.nadro.mx/75%2001%2F..%3Fx%3D1%26y%23z"
        "?_q=75%2001%2F..%3Fx%3D1%26y%23z&map=ft"
    )


def test_para_pegar_abre_la_pagina_sola_sin_ningun_termino():
    enlace = armar_el_enlace("levic", EAN, PORTALES)

    assert enlace.modo == PARA_PEGAR
    assert enlace.url == "https://www.levicventas.mx/frm_Catalogo_Levic.aspx"
    assert EAN not in enlace.url
    assert enlace.titulo == "Copiar y abrir LEVIC para pegar"


def test_una_direccion_con_busqueda_por_url_y_sin_marca_se_abre_para_pegar():
    """Doyle dice que busca por dirección pero no trae dónde poner el término:
    decir «ya buscado» sería mentir sobre lo que la pestaña va a mostrar."""
    portal = PortalDeBusqueda("https://portal.example/buscar", True)

    enlace = armar_el_enlace("vicma", EAN, {"vicma": portal})

    assert enlace.modo == PARA_PEGAR
    assert enlace.url == "https://portal.example/buscar"


def test_sin_direccion_no_hay_enlace_y_el_titulo_dice_por_que():
    enlace = armar_el_enlace("quepharma", EAN, PORTALES)

    assert enlace.url is None and enlace.modo is None
    assert enlace.titulo == (
        "Doyle no tiene la dirección de búsqueda de QuePharma: solo se copia el código."
    )


def test_un_proveedor_que_doyle_no_lista_tampoco_tiene_enlace():
    enlace = armar_el_enlace("vicma", EAN, PORTALES)

    assert enlace.url is None
    assert "VICMA" in enlace.titulo


def test_si_doyle_no_respondio_se_dice_y_solo_se_copia():
    enlace = armar_el_enlace("nadro", EAN, None)

    assert enlace.url is None
    assert enlace.titulo == DOYLE_NO_RESPONDIO == "Doyle no respondió: solo se copia el código."


def test_sin_ean_no_hay_enlace_aunque_Doyle_haya_respondido():
    enlace = armar_el_enlace("nadro", "", PORTALES)

    assert enlace.url is None
    assert enlace.titulo == SIN_CLAVE


@pytest.mark.parametrize(
    "direccion",
    [
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        "ftp://portal.example/{termino}",
        "//portal.example/{termino}",
        "/relativa/{termino}",
        "https://",
        "portal.example/{termino}",
        "https://{termino}.example/x",  # el término no puede ser el anfitrión
        "https://portal.example@{termino}/x",
    ],
)
def test_una_direccion_que_no_es_http_https_con_anfitrion_no_se_usa(direccion):
    enlace = armar_el_enlace("nadro", EAN, {"nadro": PortalDeBusqueda(direccion, True)})

    assert enlace.url is None and enlace.modo is None
    assert "solo se copia el código" in enlace.titulo
    assert "javascript" not in enlace.titulo


def test_una_marca_sin_busqueda_por_url_no_manda_las_llaves_al_portal():
    enlace = armar_el_enlace(
        "levic", EAN, {"levic": PortalDeBusqueda("https://levic.example/{termino}", False)}
    )

    assert enlace.url is None


def test_el_json_de_la_linea_tiene_los_tres_campos():
    assert armar_el_enlace("levic", EAN, PORTALES).como_json() == {
        "enlace_del_portal": "https://www.levicventas.mx/frm_Catalogo_Levic.aspx",
        "modo_del_enlace": "para_pegar",
        "titulo_del_clic": "Copiar y abrir LEVIC para pegar",
    }
    assert armar_el_enlace("levic", EAN, None).como_json()["enlace_del_portal"] is None


def test_la_captura_arma_el_enlace_de_cada_linea_con_su_propio_ean():
    captura = Captura(
        proveedor="nadro",
        lineas=(
            Linea(renglon_id=1, descripcion="A", cantidad=1, clave="111"),
            Linea(renglon_id=2, descripcion="B", cantidad=1, clave="222"),
            Linea(renglon_id=3, descripcion="C", cantidad=1, clave=""),
        ),
    )

    lineas = captura_como_json(captura, False, PORTALES)["lineas"]

    assert lineas[0]["enlace_del_portal"] == "https://i22.nadro.mx/111?_q=111&map=ft"
    assert lineas[1]["enlace_del_portal"] == "https://i22.nadro.mx/222?_q=222&map=ft"
    assert lineas[2]["enlace_del_portal"] is None
    assert lineas[2]["titulo_del_clic"] == SIN_CLAVE
    # Sin leer Doyle (`None`): todas dicen por qué no se abre nada.
    sin_doyle = captura_como_json(captura, False)["lineas"]
    assert sin_doyle[0]["titulo_del_clic"] == DOYLE_NO_RESPONDIO


# =========================================================================
# 2. EL BORDE HTTP
# =========================================================================

LO_QUE_DOYLE_CONTESTA = {
    "nadro": {"url_busqueda": NADRO.url_busqueda, "busqueda_por_url": True},
    "levic": {"url_busqueda": LEVIC.url_busqueda, "busqueda_por_url": False},
    "quepharma": {"url_busqueda": None, "busqueda_por_url": False},
}


def _doyle(contestar) -> DoylePorHttp:
    return DoylePorHttp(url="http://127.0.0.1:8383", transporte=httpx.MockTransport(contestar))


def test_el_borde_lee_portales_de_get_api_portales():
    pedidas = []

    def contestar(peticion: httpx.Request) -> httpx.Response:
        pedidas.append((peticion.method, peticion.url.path))
        return httpx.Response(200, json=LO_QUE_DOYLE_CONTESTA)

    assert _doyle(contestar).portales() == PORTALES
    assert pedidas == [("GET", "/api/portales")]


@pytest.mark.parametrize(
    "contestar",
    [
        lambda p: httpx.Response(500, json={"detail": "x"}),
        lambda p: httpx.Response(200, json=["no", "es", "un", "objeto"]),
        lambda p: httpx.Response(200, text="<html>login</html>"),
    ],
    ids=["5xx", "json_que_no_es_objeto", "no_es_json"],
)
def test_el_borde_levanta_si_doyle_contesta_mal(contestar):
    with pytest.raises(Exception):
        _doyle(contestar).portales()


def test_el_borde_solo_acepta_true_literal_en_busqueda_por_url():
    def contestar(peticion):
        return httpx.Response(
            200, json={"nadro": {"url_busqueda": "https://x.example/{termino}", "busqueda_por_url": "false"}}
        )

    assert _doyle(contestar).portales()["nadro"].busqueda_por_url is False


# =========================================================================
# 3. LA RUTA DE PUNTA A PUNTA
# =========================================================================


def _lineas(pedido: dict) -> list[dict]:
    return pedido["captura"]["lineas"]


def test_la_respuesta_de_partir_trae_el_enlace_de_cada_renglon(cliente, almacen, almacenamiento):
    _, pedido = _pedido_con(cliente, almacen, almacenamiento, cuantos=2)

    lineas = _lineas(pedido)

    assert len(lineas) == 2
    for linea in lineas:
        assert linea["enlace_del_portal"] == (
            f"https://i22.nadro.mx/{linea['clave']}?_q={linea['clave']}&map=ft"
        )
        assert linea["modo_del_enlace"] == YA_BUSCADO
        assert linea["titulo_del_clic"] == "Copiar y abrir la búsqueda en NADRO"


def test_una_sola_lectura_de_portales_por_respuesta_no_una_por_renglon(
    cliente, almacen, almacenamiento, doyle
):
    _pedido_con(cliente, almacen, almacenamiento, cuantos=4)
    antes = doyle.lecturas_de_portales

    cliente.get("/api/pedido-sugerido")

    assert doyle.lecturas_de_portales - antes == 1


def test_el_modo_para_pegar_sale_para_levic(cliente, almacen, almacenamiento, doyle):
    doyle.portales_en_memoria = {"nadro": LEVIC}  # la dirección de LEVIC bajo la clave de NADRO
    _, pedido = _pedido_con(cliente, almacen, almacenamiento, cuantos=1)

    [linea] = _lineas(pedido)

    assert linea["modo_del_enlace"] == PARA_PEGAR
    assert linea["enlace_del_portal"] == LEVIC.url_busqueda
    assert linea["titulo_del_clic"] == "Copiar y abrir NADRO para pegar"


def test_si_doyle_no_contesta_la_captura_sigue_y_la_frase_lo_dice(
    cliente, almacen, almacenamiento, doyle
):
    _pedido_con(cliente, almacen, almacenamiento, cuantos=2)
    doyle.falla = httpx.ConnectError("postgresql://usuario:SECRETO@host/db")

    respuesta = cliente.get("/api/pedido-sugerido")

    assert respuesta.status_code == 200
    [pedido] = respuesta.json()["pedidos"]
    assert len(_lineas(pedido)) == 2
    for linea in _lineas(pedido):
        assert linea["enlace_del_portal"] is None
        assert linea["modo_del_enlace"] is None
        assert linea["titulo_del_clic"] == DOYLE_NO_RESPONDIO
        assert linea["clave"]  # el EAN sigue ahí para copiarse
    # Regla 5: ni el texto de la excepción ni su tipo viajan al navegador.
    assert "SECRETO" not in respuesta.text and "ConnectError" not in respuesta.text


def test_doyle_sin_la_direccion_de_ese_proveedor_lo_dice_por_su_nombre(
    cliente, almacen, almacenamiento, doyle
):
    doyle.portales_en_memoria = {}
    _, pedido = _pedido_con(cliente, almacen, almacenamiento, cuantos=1)

    [linea] = _lineas(pedido)

    assert linea["enlace_del_portal"] is None
    assert "NADRO" in linea["titulo_del_clic"]


def test_mandar_a_espera_devuelve_los_pedidos_repintados_con_su_enlace(
    cliente, almacen, almacenamiento
):
    """La respuesta de mandar a espera repinta la captura entera: el enlace
    tiene que viajar también ahí y no solo en la carga."""
    _, pedido = _pedido_con(cliente, almacen, almacenamiento, cuantos=2)
    renglon = _lineas(pedido)[0]["renglon_id"]

    respuesta = cliente.post(
        f"/api/renglon/{renglon}/posponer",
        headers={"Cf-Access-Authenticated-User-Email": "e@f.mx"},
    )

    assert respuesta.status_code == 200, respuesta.text
    pedidos = respuesta.json()["pedidos"]
    assert pedidos, "la respuesta trae los pedidos repintados"
    for p in pedidos:
        for linea in _lineas(p):
            assert linea["enlace_del_portal"] == (
                f"https://i22.nadro.mx/{linea['clave']}?_q={linea['clave']}&map=ft"
            )


# =========================================================================
# 4. LO ESTÁTICO DEL JAVASCRIPT
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _copiar_y_abrir() -> str:
    return cuerpo_de_funcion(_script(), "const copiarYAbrir =")


def test_el_clic_en_el_ean_copia_y_abre_en_una_ventana_nombrada_por_proveedor():
    cuerpo = _copiar_y_abrir()

    assert "copiarClave(linea.clave, boton)" in cuerpo
    assert "window.open(linea.enlace_del_portal, 'portal-' + proveedor)" in cuerpo


def test_la_copia_se_lanza_antes_de_abrir_la_ventana():
    """Abrir primero le quita el foco a la página y el portapapeles rechaza la
    copia; esperar la copia antes de abrir hace que el navegador bloquee la
    ventana. El orden es copiar (sin esperar) -> abrir -> esperar."""
    cuerpo = _copiar_y_abrir()

    copia = cuerpo.index("copiarClave(")
    abre = cuerpo.index("window.open(")
    espera = cuerpo.index("await copia")
    assert copia < abre < espera
    assert "await copiarClave" not in cuerpo


def test_si_el_navegador_bloquea_la_ventana_se_pone_un_enlace_de_respaldo():
    cuerpo = _copiar_y_abrir()

    assert "if (!ventana)" in cuerpo
    assert "a.href = linea.enlace_del_portal" in cuerpo
    assert "a.target = 'portal-' + proveedor" in cuerpo
    assert "a.rel = 'noopener'" in cuerpo
    assert "createElement('a')" in cuerpo  # y no innerHTML


def test_el_navegador_no_arma_la_url_ni_manda_un_termino():
    cuerpo = _copiar_y_abrir()

    assert "fetch(" not in cuerpo
    assert "encodeURIComponent" not in cuerpo
    assert "https://" not in cuerpo and "http://" not in cuerpo
    assert "{termino}" not in cuerpo and ".replace(" not in cuerpo


def test_el_boton_del_ean_usa_el_titulo_del_servidor_y_copiar_y_abrir():
    cuerpo = cuerpo_de_funcion(_script(), "const pintarCaptura =")

    assert "clave.title = linea.titulo_del_clic" in cuerpo
    assert "copiarYAbrir(linea, captura.proveedor, captura.nombre, clave)" in cuerpo
    # La frase vieja, escrita en el navegador, ya no existe.
    assert "Copiar la clave para pegarla" not in cuerpo


def test_las_frases_de_por_que_no_se_abre_no_se_escriben_en_el_javascript():
    script = _script()

    assert "Doyle no respondió" not in script
    assert "solo se copia el código" not in script

