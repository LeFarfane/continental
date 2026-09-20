"""Pruebas del esqueleto. No tocan la red ni la base.

Usan `cliente_de_sesion` —el `TestClient` compartido de `conftest.py`— y no uno
propio: aquí no hacen falta los dobles, y un cliente propio sin `with` es un
bucle de eventos por petición, que es justo lo que el 2026-09-20 se juntó en
uno solo.
"""


def test_salud_responde_con_el_negocio(cliente_de_sesion):
    respuesta = cliente_de_sesion.get("/api/salud")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["negocio"]          # nunca vacío: un negocio sin código no empareja nada


def test_sin_encabezado_de_access_nadie_queda_identificado(cliente_de_sesion):
    # Importa que diga "sin-identificar" y no invente un usuario: la firma de
    # un pedido tiene que poder distinguir "lo hizo Eddie" de "no se sabe".
    assert cliente_de_sesion.get("/api/salud").json()["quien"] == "sin-identificar"


def test_el_correo_de_access_se_usa_como_firma(cliente_de_sesion):
    respuesta = cliente_de_sesion.get(
        "/api/salud",
        headers={"Cf-Access-Authenticated-User-Email": "alguien@ejemplo.com"},
    )
    assert respuesta.json()["quien"] == "alguien@ejemplo.com"


def test_la_portada_carga(cliente_de_sesion):
    respuesta = cliente_de_sesion.get("/")
    assert respuesta.status_code == 200
    assert "Continental" in respuesta.text
