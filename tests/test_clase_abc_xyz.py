"""La clase ABC-XYZ en el detalle del renglón: frases, lectura y pantalla.

Las frases se componen en Python y el JavaScript solo las pinta. Lo que más
vale aquí es el caso sin clase: nunca un hueco ni un guion mudo (regla 4).
"""

from __future__ import annotations

import pytest

from conftest import cuerpo_de_funcion, pantalla_completa
from continental.almacen import (
    CLASES_XYZ,
    SIN_CLASE_XYZ,
    Producto,
    clase_xyz_normalizada,
    _sql_del_catalogo,
)
from continental.clase_abc_xyz import (
    SIGNIFICADO_ABC,
    SIGNIFICADO_XYZ,
    SIN_CLASE_POR_NO_ESTAR_EN_EL_CATALOGO,
    SIN_CLASE_POR_NO_PODER_LEER,
    SIN_CLASE_POR_NO_VENDER,
    clase_del_renglon,
    frase_de_la_clase,
)


def _producto(abc="", xyz="") -> Producto:
    return Producto(
        producto_id=7, clave="7501", descripcion="X", categoria="", departamento="",
        anaquel="", precio_lista_sin_iva=1.0, costo=1.0, existencia=1.0,
        esta_activo=True, es_granel=False, clase_abc=abc, clase_xyz=xyz,
    )


@pytest.mark.parametrize("crudo,esperado", [
    ("X", "X"), (" y ", "Y"), ("z", "Z"), (None, SIN_CLASE_XYZ), ("", SIN_CLASE_XYZ),
    ("W", SIN_CLASE_XYZ), ("XY", SIN_CLASE_XYZ),
])
def test_la_xyz_se_normaliza_estricta(crudo, esperado):
    assert clase_xyz_normalizada(crudo) == esperado


def test_la_consulta_del_catalogo_pide_las_dos_letras():
    assert "clase_abc, clase_xyz" in _sql_del_catalogo(True)
    assert "clase_xyz" not in _sql_del_catalogo(False)


def test_un_producto_sin_xyz_por_omision_vale_no_se_sabe():
    assert _producto().clase_xyz == SIN_CLASE_XYZ


def test_la_frase_con_clase_dice_las_dos_letras_y_su_significado():
    frase = frase_de_la_clase("A", "X")
    assert frase.startswith("Clase AX: ")
    assert "A = " in frase and "80%" in frase
    assert "X = venta estable" in frase


@pytest.mark.parametrize("abc", ["A", "B", "C"])
@pytest.mark.parametrize("xyz", list(CLASES_XYZ))
def test_las_nueve_clases_tienen_frase_con_su_significado(abc, xyz):
    frase = frase_de_la_clase(abc, xyz)
    assert f"Clase {abc}{xyz}:" in frase
    assert SIGNIFICADO_ABC[abc] in frase and SIGNIFICADO_XYZ[xyz] in frase


def test_sin_clase_lo_dice_con_su_motivo_y_no_queda_vacio():
    frase = frase_de_la_clase("", "")
    assert frase == SIN_CLASE_POR_NO_VENDER
    assert frase.startswith("Sin clase:") and "12 meses" in frase


def test_fuera_del_catalogo_es_otro_motivo_que_no_vender():
    frase = frase_de_la_clase("", "", en_el_catalogo=False)
    assert frase == SIN_CLASE_POR_NO_ESTAR_EN_EL_CATALOGO
    assert frase != SIN_CLASE_POR_NO_VENDER


def test_si_llega_una_sola_letra_se_dice_cual_falta():
    frase = frase_de_la_clase("A", "")
    assert frase.startswith("Clase A:") and "XYZ = sin dato" in frase


def test_el_almacen_caido_no_se_lee_como_sin_ventas():
    c = clase_del_renglon(None, se_pudo_leer=False)
    assert c["frase"] == SIN_CLASE_POR_NO_PODER_LEER
    assert "no se pudo leer" in c["frase"]


def test_clase_del_renglon_trae_letras_y_frase():
    c = clase_del_renglon(_producto("B", "Z"))
    assert (c["abc"], c["xyz"]) == ("B", "Z")
    assert c["frase"].startswith("Clase BZ:")
    assert clase_del_renglon(_producto())["frase"] == SIN_CLASE_POR_NO_VENDER
    assert clase_del_renglon(None)["frase"] == SIN_CLASE_POR_NO_ESTAR_EN_EL_CATALOGO


# ----------------------------------------------------------- la pantalla


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_el_detalle_pinta_la_frase_del_servidor_y_no_la_compone():
    cuerpo = cuerpo_de_funcion(_script(), "const pintarDetalle =")
    assert "parte('abcxyz')" in cuerpo
    assert "clase.frase" in cuerpo
    # Sin el mapa o sin el producto, lo dice: nunca un hueco.
    assert "no la trajo" in cuerpo
    # Las letras y sus significados no se escriben en el navegador.
    assert "80%" not in cuerpo and "estable" not in cuerpo


def test_el_html_tiene_donde_pintarla_y_las_dos_llamadas_pasan_el_mapa():
    pantalla = pantalla_completa()
    assert 'id="inspector-abcxyz"' in pantalla
    assert pantalla.count("clases: datos.clases") == 2
