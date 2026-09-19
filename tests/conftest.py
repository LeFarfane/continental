"""La costura de pruebas de Continental, en un solo lugar y en pocas líneas.

Son tres fixtures porque los bordes son dos. Ese es el punto del prefactor: el
equivalente en Marlowe es un fixture de ~100 líneas que monta un `DISPLAY`
falso y una URL de Postgres muerta solo para que `import app` no truene, y
existe porque allá la conexión nace al importar el módulo. Aquí nace detrás de
un `Depends`, así que sustituirla cabe en cuatro renglones.

Ninguna prueba toca Postgres ni la red.

**El suite tarda ~1.0-1.3 s en la torre y el grueso no es una prueba.** Medido
el 2026-09-18, con el ticket 03 dentro: la primera prueba que sirve un archivo
estático paga 0.37-0.49 s de `mimetypes.init()` leyendo el registro de Windows.
En atlas (Linux) ese costo no existe, así que allá el mismo suite va por ~0.7 s.

El número subió con el ticket 03, y está medido, no adivinado: en corridas
seguidas, 30 pruebas en 0.73-0.95 s contra 43 en 0.95-1.37 s. Las 13 nuevas
cuestan ~0.2 s en total —~20 ms cada una de las que pasan por `TestClient`,
exactamente lo que ya costaba cada prueba de `test_bordes.py`— y ninguna
aparece entre las cinco más lentas. La recolección no se movió: 0.13-0.17 s, y
ahí es donde `--durations` no mira (ver la nota de `CARPETAS_QUE_NO_SE_MIRAN`
en `test_compila.py`).

**La medición en la torre tiene ruido de ±0.4 s**, así que una sola corrida no
dice nada: corre tres. Y si el número se sale de lo anterior, mide antes de
culpar a las pruebas nuevas: `pytest --durations=8` para el tiempo de las
pruebas y `pytest --collect-only` para el de la recolección, que son dos
problemas distintos.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from continental.dobles import AlmacenFalso, DoyleFalso
from continental.web.app import app
from continental.web.dependencias import obtener_almacen, obtener_doyle


@pytest.fixture
def almacen() -> AlmacenFalso:
    """El doble del almacén. Se le cargan filas y las devuelve tal cual."""
    return AlmacenFalso()


@pytest.fixture
def doyle() -> DoyleFalso:
    """El doble de Doyle. Guarda las búsquedas pedidas en memoria."""
    return DoyleFalso()


@pytest.fixture
def cliente(almacen: AlmacenFalso, doyle: DoyleFalso):
    """La aplicación real con los dos bordes sustituidos.

    Se limpia al terminar: `app` es un objeto de módulo y un override que
    sobrevive a su prueba contamina a las demás en un orden que depende de
    cómo pytest recolectó los archivos — el tipo de falla que se descubre un
    mes después y cuesta media tarde.
    """
    app.dependency_overrides[obtener_almacen] = lambda: almacen
    app.dependency_overrides[obtener_doyle] = lambda: doyle
    yield TestClient(app)
    app.dependency_overrides.clear()
