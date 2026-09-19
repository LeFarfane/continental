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

**Con el ticket 04 dentro el suite no subió: bajó.** Medido el 2026-09-19, en
tres corridas seguidas, 52 recolectadas —50 pasan, 2 saltadas— en
**0.39-0.49 s**, con la recolección en 0.04-0.05 s. Las 9 pruebas nuevas no
aparecen entre las ocho más lentas. La diferencia contra los 0.95-1.37 s de
arriba no está en ellas: la prueba más lenta sigue siendo la primera que sirve
un archivo estático, y aquí costó 0.17 s contra los 0.37-0.49 s del día
anterior. Ese `mimetypes.init()` leyendo el registro de Windows cuesta distinto
según lo que el sistema tenga en caché, y es justo por eso que aquí se anotan
rangos de varias corridas y no un número solo.

**Con el ticket 05 dentro sigue igual.** Medido el 2026-09-19, en tres
corridas seguidas, 66 recolectadas —64 pasan, 2 saltadas— en **0.44-0.52 s**.
Las 14 pruebas nuevas de `test_clasificacion.py` casi no cuestan: la mitad
llama a una función pura sin almacén ni archivo, y las que leen
`config/continental.yml` lo hacen sobre un `cargar()` cacheado.

**Con el ticket 06 dentro sigue igual.** Medido el 2026-09-19, en tres corridas
seguidas, 79 recolectadas —77 pasan, 2 saltadas— en **0.50-0.70 s**, con la
recolección en 0.05 s. Las 12 pruebas nuevas de `test_vistas.py` cuestan poco y
solo una aparece entre las ocho más lentas, con 0.01 s: la mitad mira `VISTAS`,
que es un dato sin archivo ni almacén, y el resto pasa por `TestClient` como
las de sus vecinas. La más lenta del suite sigue siendo la primera que sirve un
archivo estático (0.16 s), y sigue siendo `mimetypes.init()` leyendo el
registro de Windows, no una prueba.

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
