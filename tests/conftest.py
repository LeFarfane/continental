"""La costura de pruebas de Continental, en un solo lugar y en pocas líneas.

Son tres fixtures porque los bordes son dos. Ese es el punto del prefactor: el
equivalente en Marlowe es un fixture de ~100 líneas que monta un `DISPLAY`
falso y una URL de Postgres muerta solo para que `import app` no truene, y
existe porque allá la conexión nace al importar el módulo. Aquí nace detrás de
un `Depends`, así que sustituirla cabe en cuatro renglones.

Ninguna prueba toca Postgres ni la red.

**El suite tarda ~0.95 s en la torre y el culpable no es una prueba.** Medido el
2026-09-18: `test_la_portada_carga` cuesta 0.57 s, de los cuales 0.46 s son
`mimetypes.init()` leyendo el registro de Windows la primera vez que alguien
sirve un archivo. En atlas (Linux) ese costo no existe. Si el numero se sale de
un segundo en la torre, mide antes de culpar a las pruebas nuevas:
`pytest --durations=6`.
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
