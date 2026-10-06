"""Qué dice el detalle de un producto sobre su clase ABC-XYZ.

Las frases se componen aquí, con pruebas, y el JavaScript solo las pinta (el
criterio de todo el repo: una regla que vive en la pantalla no se puede probar).

El significado de cada letra no se inventa: sale del ADR 0018 de farmacia-data
y del comentario de `dbt/models/marts/dim_producto.sql`, que es donde dbt la
calcula:

- **ABC**, por participación acumulada en la utilidad de 12 meses, de mayor a
  menor: A hasta el 80%, B hasta el 95%, C el resto.
- **XYZ**, por el coeficiente de variación de las piezas mensuales: X menor a
  0.5, Y menor a 1.0, Z el resto. Y un producto que vendió en un solo mes es Z
  a la fuerza: no hay desviación que medir.

Un producto **sin clase** no es un producto "C": dbt lo deja en NULL a
propósito cuando no vendió nada en 365 días (el ADR 0018 descartó mandarlo a C
porque afirmaría algo que nadie midió). Aquí se dice así, con su motivo, y
nunca como un hueco: regla 4 de `CLAUDE.md`.

Puro: no lee la base ni la red.
"""

from __future__ import annotations

from continental.almacen import CLASES_ABC, CLASES_XYZ

#: Qué quiere decir cada letra ABC, tal cual lo define dbt.
SIGNIFICADO_ABC = {
    "A": "es de los que juntos dan el 80% de la utilidad de los últimos 12 meses",
    "B": "es de los que juntos dan el siguiente 15% de la utilidad (del 80% al 95%)",
    "C": "es de los que juntos dan el último 5% de la utilidad",
}

#: Qué quiere decir cada letra XYZ, tal cual lo define dbt.
SIGNIFICADO_XYZ = {
    "X": "venta estable (de un mes a otro casi no cambia)",
    "Y": "venta variable (cambia bastante de un mes a otro)",
    "Z": "venta errática (impredecible, o vendió en un solo mes)",
}

SIN_CLASE_POR_NO_VENDER = (
    "Sin clase: no vendió en los últimos 12 meses, así que no hay con qué "
    "medir su utilidad ni su estabilidad."
)
SIN_CLASE_POR_NO_ESTAR_EN_EL_CATALOGO = (
    "Sin clase: el producto no está en el catálogo del almacén."
)
SIN_CLASE_POR_NO_PODER_LEER = (
    "Sin clase: no se pudo leer el catálogo del almacén. Eso no quiere decir "
    "que no la tenga."
)


def frase_de_la_clase(
    abc: str, xyz: str, *, en_el_catalogo: bool = True
) -> str:
    """La frase del detalle: «Clase AX: A = … · X = …», o «Sin clase: …».

    `abc` y `xyz` vienen ya normalizadas (`almacen.clase_abc_normalizada`):
    vacío es "no se sabe". `en_el_catalogo=False` distingue al producto que ni
    siquiera existe en `dim_producto` del que existe y no vendió.

    Si llega solo una de las dos letras —dbt las escribe juntas, así que no
    debería pasar— se dice cuál falta, en vez de callarla.
    """
    if not en_el_catalogo:
        return SIN_CLASE_POR_NO_ESTAR_EN_EL_CATALOGO
    tiene_abc = abc in CLASES_ABC
    tiene_xyz = xyz in CLASES_XYZ
    if not tiene_abc and not tiene_xyz:
        return SIN_CLASE_POR_NO_VENDER
    partes = [
        f"{abc} = {SIGNIFICADO_ABC[abc]}"
        if tiene_abc
        else "ABC = sin dato (el almacén no trajo la letra)",
        f"{xyz} = {SIGNIFICADO_XYZ[xyz]}"
        if tiene_xyz
        else "XYZ = sin dato (el almacén no trajo la letra)",
    ]
    return f"Clase {abc}{xyz}: " + " · ".join(partes)


def clase_del_renglon(producto, *, se_pudo_leer: bool = True) -> dict:
    """Lo que viaja al JSON por renglón: las dos letras y su frase.

    `producto` es el `almacen.Producto` del renglón, o `None` si no está en el
    catálogo. `se_pudo_leer=False` es el almacén caído: la frase lo dice.
    """
    if not se_pudo_leer:
        return {"abc": "", "xyz": "", "frase": SIN_CLASE_POR_NO_PODER_LEER}
    if producto is None:
        return {
            "abc": "",
            "xyz": "",
            "frase": frase_de_la_clase("", "", en_el_catalogo=False),
        }
    return {
        "abc": producto.clase_abc,
        "xyz": producto.clase_xyz,
        "frase": frase_de_la_clase(producto.clase_abc, producto.clase_xyz),
    }
