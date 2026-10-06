"""El botón de completar, el lado de la pantalla: seguir la fila en orden.

El 2026-10-05, con 36 renglones en la cola, el servidor los consultó todos
uno tras otro pero la etiqueta «consultando» se quedó en el primero: se lanzaba
un `sondear` por renglón, y ése se rinde al ver una consulta que no está en
curso — que al arrancar son todas menos la primera.

Este repo no ejecuta JavaScript en las pruebas (ver `test_pasada_visual.py`),
así que se fija con pruebas estáticas sobre el texto, igual que
`test_ver_en_portal_js.py`.
"""

from __future__ import annotations

from conftest import cuerpo_de_funcion, pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_completar_sigue_la_cola_del_servidor_y_no_un_sondeo_por_renglon():
    cuerpo = cuerpo_de_funcion(_script(), "async function completarLoQueFalta")

    assert "sondearCola(respuesta.cola" in cuerpo
    assert "respuesta.lanzada_en" in cuerpo
    assert "forEach(f => sondear(" not in cuerpo


def test_la_cola_espera_la_consulta_de_esta_vuelta_antes_de_pasar_al_siguiente():
    cuerpo = cuerpo_de_funcion(_script(), "function sondearCola")

    # Un renglón al que no le toca todavía trae, a lo sumo, una consulta vieja:
    # se distingue por la hora de arranque de la fila.
    assert ">= arranque" in cuerpo
    assert "posicion += 1" in cuerpo
    # Mientras está en curso se pinta, para que la etiqueta salte a ese renglón.
    assert "respuesta.consulta.en_curso" in cuerpo
    assert "aplicarPrecios(renglonId, respuesta)" in cuerpo
    # Y el navegador no pregunta para siempre.
    assert "hastaMs" in cuerpo
