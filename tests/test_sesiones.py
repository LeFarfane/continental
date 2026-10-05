"""La pestaña de Sesiones (2026-09-28): el «Inicio» de Doyle, sin creerle a `guardada`.

El `guardada` de Doyle es un marcador en disco que sobrevive a que el portal
caduque la sesión: el 2026-09-19 los cuatro decían `guardada` con las cuatro
caducadas. Así que la tarjeta cruza lo que dice Doyle con lo que vieron las
consultas guardadas: la última vez que el portal dio precio y la última vez
que mandó al login.

Ninguna prueba toca Doyle, ni Postgres, ni la red, ni duerme.
"""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import pantalla_completa
from continental import config
from continental.almacenamiento import EvidenciaDeLaSesion
from continental.almacenamiento import _EVIDENCIA_DE_LAS_SESIONES
from continental.doyle import SesionDeProveedor
from continental.fallas import AL_LEER, DOYLE, que_hacer
from continental.precios import SESION_CADUCADA
from continental.sesiones import (
    CADUCADA,
    ESPERANDO,
    SIN_EVIDENCIA,
    SIN_PROBAR,
    SIN_SESION,
    SIRVIO,
    estado_de_la_sesion,
    sesiones_como_json,
)

UTC = dt.UTC
NEGOCIO = "farmacia_01"


def _sesion(proveedor="levic", estado="guardada", guardada_en="2026-09-28T10:00:00"):
    return SesionDeProveedor(proveedor=proveedor, nombre=proveedor.upper(), estado=estado,
                             guardada_en=guardada_en)


def _utc(hora: int, minuto: int = 0) -> dt.datetime:
    """El 2026-09-28 a esa hora UTC. La farmacia va seis horas atrás."""
    return dt.datetime(2026, 9, 28, hora, minuto, tzinfo=UTC)


# =========================================================================
# LAS TARJETAS
# =========================================================================


def test_una_ventana_esperando_dice_que_hacer_y_ofrece_ya_entre_y_cancelar():
    [tarjeta] = sesiones_como_json([_sesion(estado="abriendo")], {})

    assert tarjeta["etiqueta"] == ESPERANDO
    assert tarjeta["se_puede_confirmar"] is True and tarjeta["se_puede_abrir"] is False
    assert "Cancelar" in tarjeta["frase"]


def test_sin_sesion_hay_que_abrirla():
    [tarjeta] = sesiones_como_json([_sesion(estado="sin_sesion", guardada_en=None)], {})

    assert (tarjeta["etiqueta"], tarjeta["hay_que_abrirla"]) == (SIN_SESION, True)
    assert tarjeta["rotulo_de_abrir"] == "Abrir sesión"


def test_guardada_pero_el_portal_mando_al_login_despues_es_caducada():
    """Lo que pasó el 2026-09-19: Doyle decía `guardada` y el portal ya no la
    aceptaba. Guardada a las 10:00 de la farmacia (16:00 UTC), el login a las
    10:30 de la farmacia."""
    evidencia = EvidenciaDeLaSesion("levic", dio_precio_en=_utc(16, 10), caduco_en=_utc(16, 30))

    etiqueta, frase = estado_de_la_sesion(_sesion(), evidencia)

    assert etiqueta == CADUCADA
    assert "a las 10:30" in frase and "login" in frase and "«guardada»" in frase


def test_volver_a_guardarla_despues_del_login_no_la_deja_caducada():
    """Se abrió otra vez a las 10:00 después de que caducara a las 09:30 de la
    farmacia (15:30 UTC): no se sabe todavía si sirve. Compara el instante sin
    zona de Doyle contra uno con zona de la base: las seis horas importan."""
    evidencia = EvidenciaDeLaSesion("levic", dio_precio_en=None, caduco_en=_utc(15, 30))

    assert estado_de_la_sesion(_sesion(), evidencia)[0] == SIN_PROBAR


def test_un_precio_despues_de_guardarla_dice_que_sirvio_sin_afirmar_que_sigue():
    evidencia = EvidenciaDeLaSesion("nadro", dio_precio_en=_utc(16, 45), caduco_en=_utc(15, 0))

    etiqueta, frase = estado_de_la_sesion(_sesion("nadro"), evidencia)

    assert etiqueta == SIRVIO
    assert "a las 10:45" in frase and "Pudo caducar" in frase


def test_guardada_sin_ninguna_consulta_despues_es_sin_probar():
    assert estado_de_la_sesion(_sesion(), None)[0] == SIN_PROBAR
    assert estado_de_la_sesion(_sesion(), EvidenciaDeLaSesion("levic", dio_precio_en=_utc(12)))[0] == SIN_PROBAR


def test_sin_poder_leer_la_evidencia_se_dice_y_no_se_afirma_nada():
    [tarjeta] = sesiones_como_json([_sesion()], None)

    assert tarjeta["etiqueta"] == "guardada"
    assert SIN_EVIDENCIA in tarjeta["frase"]
    assert tarjeta["hay_que_abrirla"] is False


def test_mientras_un_portal_espera_los_otros_dicen_por_que_no_se_abren():
    """ADR 0018: un portal a la vez. El botón no se pinta para rebotar."""
    tarjetas = sesiones_como_json(
        [_sesion("nadro", "abriendo"), _sesion("levic", "sin_sesion", None)], {}
    )
    nadro, levic = tarjetas

    assert nadro["se_puede_confirmar"] is True
    assert levic["se_puede_abrir"] is False
    assert "NADRO" in levic["por_que_no_se_abre"]


def test_las_tarjetas_van_en_el_orden_del_glosario():
    sesiones = [_sesion(p, "sin_sesion", None) for p in ("vicma", "quepharma", "levic", "nadro")]

    assert [t["nombre"] for t in sesiones_como_json(sesiones, {})] == ["NADRO", "LEVIC", "VICMA", "QuePharma"]


# =========================================================================
# LA EVIDENCIA
# =========================================================================


def test_la_evidencia_sale_de_precios_leidos_y_del_motivo_como_parametro():
    """Un precio solo llega con la sesión viva; el motivo con su acento vive
    en `precios.py`, no copiado en el SQL."""
    sql = str(_EVIDENCIA_DE_LAS_SESIONES)

    assert "filter (where precio is not null)" in sql
    assert "motivo = :caducada" in sql
    assert "sesi" not in sql.lower().replace("sesiones", "")


def test_el_doble_calcula_la_evidencia_igual_que_el_sql(almacenamiento):
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(15), "precio": 10, "motivo": None},
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(17), "precio": None,
         "motivo": SESION_CADUCADA},
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(18), "precio": None,
         "motivo": "no empareja"},
        {"negocio": "otra", "proveedor": "nadro", "consultado_en": _utc(18), "precio": 5, "motivo": None},
    ]

    evidencia = almacenamiento.evidencia_de_las_sesiones(NEGOCIO)

    assert evidencia == {"levic": EvidenciaDeLaSesion("levic", dio_precio_en=_utc(15), caduco_en=_utc(17))}


# =========================================================================
# LAS RUTAS
# =========================================================================


def test_las_sesiones_cruzan_lo_de_doyle_con_las_consultas_guardadas(cliente, doyle, almacenamiento):
    doyle.sesiones_en_memoria = [
        {"proveedor": "levic", "estado": "guardada", "guardada_en": "2026-09-28T10:00:00"},
        {"proveedor": "nadro", "estado": "sin_sesion"},
    ]
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(16, 30), "precio": None,
         "motivo": SESION_CADUCADA},
    ]

    datos = cliente.get("/api/sesiones").json()

    assert datos["ok"] is True and datos["evidencia_sin_leer"] is None
    nadro, levic = datos["sesiones"]
    assert (nadro["etiqueta"], levic["etiqueta"]) == (SIN_SESION, CADUCADA)


def test_sin_la_tabla_de_precios_las_tarjetas_se_ven_y_avisan(cliente, doyle, almacenamiento):
    doyle.sesiones_en_memoria = [{"proveedor": "levic", "estado": "guardada", "guardada_en": "2026-09-28T10:00:00"}]
    almacenamiento.falla = RuntimeError("SECRETO")

    respuesta = cliente.get("/api/sesiones")

    datos = respuesta.json()
    assert datos["ok"] is True
    assert datos["evidencia_sin_leer"]["que_hacer"] == que_hacer(AL_LEER, config.cargar().a_quien_avisar)
    assert SIN_EVIDENCIA in datos["sesiones"][0]["frase"]
    assert "SECRETO" not in respuesta.text


def test_doyle_caido_es_un_hueco_con_que_hacer(cliente, doyle):
    doyle.falla = RuntimeError("SECRETO")

    respuesta = cliente.get("/api/sesiones")

    assert respuesta.json()["ok"] is False
    assert respuesta.json()["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text


def test_cancelar_cierra_la_ventana_y_suelta_el_candado(cliente, doyle):
    """La salida que el ADR 0018 dejó prevista: una ventana abandonada ya no
    bloquea a los otros tres portales."""
    doyle.sesiones_en_memoria = [{"proveedor": p} for p in ("nadro", "levic")]
    assert cliente.post("/api/sesion/nadro/abrir").json()["ok"] is True
    assert cliente.post("/api/sesion/levic/abrir").json()["ok"] is False  # el candado

    cancelada = cliente.post("/api/sesion/nadro/cancelar").json()

    assert cancelada["ok"] is True and doyle.sesiones_canceladas == ["nadro"]
    assert cliente.post("/api/sesion/levic/abrir").json()["ok"] is True


def test_cancelar_sin_ventana_dice_que_hacer(cliente, doyle):
    datos = cliente.post("/api/sesion/nadro/cancelar").json()

    assert datos["ok"] is False and datos["que_hacer"]


# =========================================================================
# LA PANTALLA
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_las_sesiones_se_leen_al_abrir_su_pestana():
    """Una pregunta a Doyle que solo hace falta cuando alguien las va a mirar."""
    assert "if (elegida === 'sesiones') cargarSesiones();" in _script()


def test_las_tarjetas_pintan_lo_que_decide_el_servidor():
    script = _script()

    for llave in ("s.etiqueta", "s.frase", "s.se_puede_abrir", "s.por_que_no_se_abre",
                  "s.se_puede_confirmar", "s.rotulo_de_abrir"):
        assert llave in script, llave


@pytest.mark.parametrize("paso", ["abrirSesion", "confirmarSesion", "cancelarSesion"])
def test_cada_paso_vuelve_a_pintar_las_tarjetas(paso):
    # Desde el ticket 05 la tarjeta es de la función compartida: escribe en la
    # nota de su sitio y avisa a quien se le pasó (la pestaña y la ventana).
    assert f"{paso}(s, b, sitio.accion, alTerminar)" in _script()


def test_la_pantalla_dice_donde_se_teclea_la_contrasena():
    """Nunca en Continental: en el portal, dentro del visor (ADR 0001 de Doyle)."""
    assert "nunca en esta página" in pantalla_completa()
