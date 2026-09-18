"""Pruebas del esqueleto. No tocan la red ni la base."""

from fastapi.testclient import TestClient

from continental.web.app import app

cliente = TestClient(app)


def test_salud_responde_con_el_negocio():
    respuesta = cliente.get("/api/salud")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["negocio"]          # nunca vacío: un negocio sin código no empareja nada


def test_sin_encabezado_de_access_nadie_queda_identificado():
    # Importa que diga "sin-identificar" y no invente un usuario: la firma de
    # un pedido tiene que poder distinguir "lo hizo Eddie" de "no se sabe".
    assert cliente.get("/api/salud").json()["quien"] == "sin-identificar"


def test_el_correo_de_access_se_usa_como_firma():
    respuesta = cliente.get(
        "/api/salud",
        headers={"Cf-Access-Authenticated-User-Email": "alguien@ejemplo.com"},
    )
    assert respuesta.json()["quien"] == "alguien@ejemplo.com"


def test_la_portada_carga():
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert "Continental" in respuesta.text
