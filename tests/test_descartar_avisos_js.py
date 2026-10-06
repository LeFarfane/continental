"""Descartar un aviso de la franja, uno por uno (pedido del dueño, 2026-10-05).

Cada fila de la franja de avisos lleva una cruz que la quita. Lo descartado se
recuerda por el TEXTO de la nota, no solo por cuál nota es: si la situación
cambia —otra corrida del lote, otra sesión caducada—, la frase cambia y el
aviso vuelve solo. Descartar es "ya vi esto", no "no me avises más" (regla 4
de `CLAUDE.md`: lo que falla no se calla para siempre por un clic de ayer).

Pruebas estáticas sobre el texto de la pantalla, igual que
`test_ventana_sesiones_js.py`. Ninguna toca Postgres ni la red.
"""

from __future__ import annotations

import re

from conftest import cuerpo_de_funcion, pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str) -> str:
    return cuerpo_de_funcion(_script(), "const " + nombre + " =")


def test_cada_fila_recibe_su_cruz_con_nombre_para_el_lector_de_pantalla():
    cuerpo = _funcion("ponerCrucesALosAvisos")
    assert ".aviso-fila" in cuerpo
    assert "aviso-cerrar" in cuerpo
    assert "aria-label" in cuerpo


def test_lo_descartado_se_recuerda_por_el_texto_de_la_nota():
    cuerpo = _funcion("pintarResumenDeAvisos")
    assert re.search(r"DESCARTADOS\[nota\.id\]\s*===\s*texto", cuerpo)


def test_lo_descartado_no_cuenta_en_el_resumen():
    cuerpo = _funcion("pintarResumenDeAvisos")
    # La fila descartada se esconde y sale antes de sumar a visibles.
    descartada = cuerpo.index("DESCARTADOS[nota.id]")
    assert descartada < cuerpo.index("visibles += 1")


def test_leer_y_guardar_lo_descartado_va_con_su_try():
    for nombre in ("descartadosRecordados", "recordarDescartados"):
        cuerpo = _funcion(nombre)
        assert "localStorage" in cuerpo
        assert "try" in cuerpo and "catch" in cuerpo


def test_se_puede_volver_a_mostrar_lo_descartado():
    pantalla = pantalla_completa()
    assert 'id="avisos-descartados"' in pantalla
    cuerpo = _funcion("iniciarLaVistaDelDia")
    assert "avisos-descartados" in cuerpo


def test_la_cruz_tiene_su_lugar_en_la_rejilla_y_su_color_de_la_paleta():
    pantalla = pantalla_completa()
    regla = re.search(r"\.aviso-cerrar\s*\{([^}]*)\}", pantalla).group(1)
    assert "grid-column" in regla
    assert "#" not in regla  # los colores viven en :root
