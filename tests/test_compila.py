"""Que todo compile y que lo que corre en atlas no lleve basura de Windows.

La prueba más barata del suite, y nació en Marlowe de un fallo real del
2026-09-08: al agregar un endpoint se coló un salto de línea **real** dentro de
una cadena. `marlowe/web/app.py` dejó de compilar, `marlowe-web.service` entró
en bucle de reinicio, y el dueño estuvo un rato intentando corregir un enlace
contra un servidor que no existía. **Las 148 pruebas de Marlowe pasaban**, y no
por casualidad: ninguna importaba `marlowe.web.app`, así que el suite en verde
no decía nada sobre si el servidor arrancaba.

Continental hereda la lección antes que el fallo. Aquí hay dos huecos que
ninguna prueba de comportamiento ve:

1. **Un archivo que no compila.** `tests/test_bordes.py` importa todo el
   paquete, sí, pero `iniciar.py` —el archivo que el servicio ejecuta— no lo
   importa nadie.
2. **Un final de línea de Windows en algo que corre en Linux.** Se edita en la
   torre (`core.autocrlf=true`) y corre en atlas. Un `.sh` con CRLF muere en
   bash con `$'\r': command not found`, una unidad de systemd con CRLF no
   carga, y un `.sql` con CRLF se lleva el retorno de carro **dentro de las
   cadenas** —el CHECK de `pedidos.renglon.estado` guardaría `'en tránsito\r'`
   y el primer `UPDATE` de Continental rebotaría—. `.gitattributes` ya fija
   `eol=lf` para `.sh`, `.service`, `.timer` y `.sql`; esto es el cinturón que
   comprueba la copia que de verdad está en disco, que es la que se va a
   ejecutar.

**Hoy Continental no tiene ni un `.sh` ni una unidad de systemd**: medido el
2026-09-19, `scripts/desplegar.sh` y `continental-web.service` siguen en la
lista de "lo que todavía no existe" de `HANDOVER.md`. Por eso el caso del
shebang se anuncia como **saltado con su motivo** en vez de pasar callado: un
cero que nadie ve es indistinguible de una prueba que no revisa nada. Y para
que el detector no llegue sin estrenar el día que los archivos aparezcan,
`test_los_detectores_cazan_lo_que_deben` lo ejercita hoy contra bytes
inventados.

Esto no reemplaza probar el comportamiento; solo cierra el hueco entre "las
pruebas pasan" y "el proceso al menos levanta".

**Que siga siendo barata no es gratis.** Casi todo lo que hace este archivo
ocurre en la recolección de pytest, no dentro de una prueba, y ahí
`--durations` no mira: una búsqueda mal podada puede costar segundos sin que
ninguna prueba aparezca como lenta. El número medido y la trampa concreta
están junto a `CARPETAS_QUE_NO_SE_MIRAN`, y
`test_la_poda_ocurre_al_caminar_y_no_al_final` es lo que impide que se rompa
en silencio.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Carpetas por las que no se camina: no son código de este repo.
#
# **La poda tiene que ocurrir al entrar, no al filtrar el resultado**, y la
# diferencia está medida en la torre el 2026-09-18: recorrer el repo entero y
# descartar después cuesta **1.64 s** para encontrar cero archivos —4,250
# rutas, 3,960 de ellas dentro de `.venv`—, y el costo no es el recorrido
# (0.35 s) sino un `stat` de Windows por cada ruta para saber si es archivo.
# Podando al caminar baja a milisegundos.
#
# El precio se paga entero en **recolección**, que es donde `--durations` no
# mira: con el filtro tardío, `pytest --collect-only` pasaba de 0.15 s a
# 1.79 s y el suite completo de 0.79 s a 2.53 s, rompiendo el criterio del
# ticket 01 —menos de un segundo— sin que ninguna prueba apareciera como lenta.
# Si alguien "simplifica" esto de vuelta a `RAIZ.rglob("*")`, vuelve a costar
# 1.6 s y `test_la_poda_ocurre_al_caminar_y_no_al_final` se pone roja.
CARPETAS_QUE_NO_SE_MIRAN = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}

# Lo que se despliega en atlas y tiene que ir con LF. Es la misma lista de
# `.gitattributes`, a propósito: si una cambia sin la otra, el repo dice una
# cosa y el disco otra.
#
# `.sql` entró el 2026-09-19 con `sql/crear_tablas.sql` (ticket 07). El daño de
# un CRLF ahí es distinto al de un `.sh` y por eso vale la pena nombrarlo:
# psql tolera el retorno de carro entre sentencias, pero **no lo quita de
# dentro de una cadena**. El CHECK de `pedidos.renglon.estado` guardaría
# `'en tránsito\r'`, y el primer `UPDATE ... SET estado = 'en tránsito'` de
# Continental rebotaría con una violación de restricción que nadie sabría
# explicar mirando el código.
EXTENSIONES_PARA_ATLAS = (".sh", ".service", ".timer", ".sql")

MOTIVO_SIN_ARCHIVOS = (
    "Todavía no existe ningún archivo de esta clase en el repo. Los .sql sí "
    "existen desde el 2026-09-19 (sql/crear_tablas.sql y compañía, ticket "
    "07); los que siguen pendientes son scripts/desplegar.sh y "
    "continental-web.service, que HANDOVER.md tiene en su lista. El día que "
    "se agreguen, estos casos dejan de saltarse solos y empiezan a "
    "revisarlos."
)


def _es_visible(ruta: Path) -> bool:
    """Falso si la ruta pasa por alguna carpeta que no se mira."""
    return not (CARPETAS_QUE_NO_SE_MIRAN & set(ruta.relative_to(RAIZ).parts))


def _nombre(ruta: Path) -> str:
    """La ruta como se escribe en un mensaje de fallo: relativa a la raíz y con
    barras normales, para que se lea igual en la torre y en atlas."""
    return ruta.relative_to(RAIZ).as_posix()


def _modulos_de_python() -> list[Path]:
    """Todo `src/**/*.py` —lo que pide el ticket— más `iniciar.py`.

    `iniciar.py` no está en `src/` y aun así es el archivo que el servicio
    ejecuta: dejarlo fuera sería repetir el hueco exacto que esta prueba existe
    para cerrar.
    """
    modulos = [r for r in (RAIZ / "src").rglob("*.py") if _es_visible(r)]
    arranque = RAIZ / "iniciar.py"
    if arranque.exists():
        modulos.append(arranque)
    return sorted(modulos)


def _caminar_el_repo() -> Iterator[tuple[Path, list[str]]]:
    """Recorre el repo podando **al entrar**, y entrega cada carpeta con los
    nombres de sus archivos.

    `os.walk` permite recortar `subcarpetas` en el sitio y así no descender
    nunca en lo podado — por eso esto no es un `rglob` con un `if` al final
    (ver la nota de costo en `CARPETAS_QUE_NO_SE_MIRAN`). De paso, `os.walk`
    ya separa archivos de carpetas, así que tampoco hace falta un `is_file()`
    por ruta, que era el grueso del gasto.
    """
    for carpeta, subcarpetas, archivos in os.walk(RAIZ):
        subcarpetas[:] = [d for d in subcarpetas if d not in CARPETAS_QUE_NO_SE_MIRAN]
        yield Path(carpeta), archivos


def _archivos_para_atlas() -> list[Path]:
    """Los `.sh`, `.service`, `.timer` y `.sql` de todo el repo, vengan de donde
    vengan.

    Se busca en el repo entero y no solo en `scripts/` o en `sql/` porque la
    primera carpeta todavía no existe y nadie ha decidido dónde va a vivir cada
    unidad de systemd. Marlowe las tiene en `scripts/systemd/`; si aquí alguien
    las pone en otro lado, la prueba las encuentra igual.
    """
    return sorted(
        carpeta / nombre
        for carpeta, archivos in _caminar_el_repo()
        for nombre in archivos
        if nombre.endswith(EXTENSIONES_PARA_ATLAS)
    )


def _casos(archivos: list[Path]) -> list:
    """Un caso por archivo; si hoy no hay ninguno, un único caso saltado.

    Parametrizar sobre una lista vacía deja la prueba en un `pass` que no
    revisó nada y que en la salida de pytest no se distingue de una que sí.
    Un caso saltado con su motivo sí se ve —`pytest -rs` lo imprime entero— y
    cuenta aparte del resto en la línea del resumen.
    """
    if archivos:
        return [pytest.param(a, id=_nombre(a)) for a in archivos]
    return [
        pytest.param(
            None,
            id="todavia-no-hay-ninguno",
            marks=pytest.mark.skip(reason=MOTIVO_SIN_ARCHIVOS),
        )
    ]


MODULOS_DE_PYTHON = _modulos_de_python()
ARCHIVOS_PARA_ATLAS = _archivos_para_atlas()
SCRIPTS_DE_SHELL = [r for r in ARCHIVOS_PARA_ATLAS if r.suffix == ".sh"]


# ------------------------------------------------ los detectores, por separado
#
# Son funciones sobre `bytes` y no sobre rutas a propósito: así se pueden
# ejercitar hoy, sin un solo `.sh` en el repo, contra contenido inventado.


def _lineas_con_retorno_de_carro(datos: bytes) -> list[int]:
    """En qué líneas (1 en adelante) hay un `\\r`.

    Se trabaja sobre `bytes` **a propósito**: leer en modo texto deja que
    Python traduzca los finales de línea y un archivo lleno de CRLF llegaría
    aquí limpio, con la prueba en verde y el script muerto en atlas.
    """
    return [n for n, linea in enumerate(datos.split(b"\n"), start=1) if b"\r" in linea]


def _le_falta_shebang(datos: bytes) -> bool:
    """Verdadero si el archivo no empieza con `#!`."""
    return not datos.startswith(b"#!")


def test_los_detectores_cazan_lo_que_deben():
    """Que el cinturón no llegue sin estrenar el día que haya scripts.

    Mientras no exista ni un `.sh`, las dos pruebas de abajo se saltan y estos
    detectores no correrían nunca. Esta es la que los mantiene honestos: un
    `_lineas_con_retorno_de_carro` que devolviera siempre `[]` —por un modo
    texto que se coló, por ejemplo— se pondría rojo aquí.
    """
    assert _lineas_con_retorno_de_carro(b"#!/usr/bin/env bash\nset -euo pipefail\n") == []
    assert _lineas_con_retorno_de_carro(b"#!/usr/bin/env bash\r\nset -e\r\n") == [1, 2]
    assert _lineas_con_retorno_de_carro(b"ok\nmalo\r\nok\n") == [2]

    assert _le_falta_shebang(b"set -euo pipefail\n") is True
    assert _le_falta_shebang(b"# comentario primero\n#!/bin/bash\n") is True
    assert _le_falta_shebang(b"#!/usr/bin/env bash\n") is False


def test_la_poda_ocurre_al_caminar_y_no_al_final():
    """Que la búsqueda no entre en `.venv`, y que aun así sí entre en el repo.

    Una poda que se rompe no rompe ningún resultado: la lista de archivos sale
    igual y nadie se entera, solo que la recolección del suite vuelve a costar
    1.6 s (medido el 2026-09-18; el detalle está en
    `CARPETAS_QUE_NO_SE_MIRAN`). Esta prueba mira el recorrido y no su
    resultado, que es el único lugar donde ese defecto se ve.
    """
    carpetas = [c for c, _ in _caminar_el_repo()]

    coladas = [_nombre(c) for c in carpetas if not _es_visible(c)]
    assert not coladas, (
        f"El recorrido entró en {len(coladas)} carpeta(s) que debía podar, "
        f"la primera es {coladas[0]}. La poda de _caminar_el_repo() dejó de "
        "funcionar: el suite sigue en verde pero su recolección vuelve a "
        "costar ~1.6 s en la torre."
    )

    # Y el otro lado del cinturón: podar de más sería una prueba que no mira
    # nada. Estas tres carpetas tienen que estar siempre en el recorrido.
    for esperada in (RAIZ, RAIZ / "src", RAIZ / "src" / "continental"):
        assert esperada in carpetas, (
            f"{_nombre(esperada)} no se recorrió. La poda se pasó de lista y "
            "la búsqueda de .sh/.service/.timer dejó de mirar donde debe."
        )


# ------------------------------------------------------ que el Python compile


def test_hay_modulos_de_python_que_revisar():
    """Si el recorrido dejara de encontrar archivos, la prueba de abajo pasaría
    vacía y no protegería nada.

    El piso son 8: los módulos que había el 2026-09-18. No sube solo para no
    obligar a editar la prueba cada vez que nace un archivo.
    """
    assert len(MODULOS_DE_PYTHON) >= 8, (
        f"Solo se encontraron {len(MODULOS_DE_PYTHON)} archivos .py bajo "
        f"{_nombre(RAIZ / 'src')}. O el código se mudó de carpeta, o el "
        "recorrido de esta prueba dejó de funcionar y no está revisando nada."
    )
    assert RAIZ / "iniciar.py" in MODULOS_DE_PYTHON, (
        "iniciar.py no entró en la lista: es el archivo que ejecuta el "
        "servicio y es justo el que ninguna otra prueba importa."
    )


@pytest.mark.parametrize("ruta", MODULOS_DE_PYTHON, ids=_nombre)
def test_el_modulo_de_python_compila(ruta: Path):
    """`ast.parse` sobre cada archivo, uno por caso para que el rojo diga cuál.

    Se lee en binario y se deja que `ast` resuelva la codificación: así una
    declaración de `coding:` rota también se ve aquí y no en atlas.
    """
    try:
        ast.parse(ruta.read_bytes(), filename=str(ruta))
    except SyntaxError as exc:
        pytest.fail(
            f"{_nombre(ruta)} no compila: línea {exc.lineno}, {exc.msg}. "
            "Un archivo así desplegado deja el servicio en bucle de reinicio "
            "(le pasó a Marlowe el 2026-09-08).",
            pytrace=False,
        )


# ------------------------------------- que lo de atlas no lleve basura de Windows


@pytest.mark.parametrize("ruta", _casos(ARCHIVOS_PARA_ATLAS), ids=lambda p: p)
def test_el_archivo_de_atlas_no_trae_retorno_de_carro(ruta: Path):
    """Se edita en la torre y corre en atlas: el CRLF no se ve y mata igual.

    `.gitattributes` ya fija `eol=lf` para estas tres extensiones. Esto
    comprueba que de verdad ocurrió en disco, que es la copia que bash y
    systemd van a leer.
    """
    lineas = _lineas_con_retorno_de_carro(ruta.read_bytes())
    assert not lineas, (
        f"{_nombre(ruta)} trae retorno de carro (CRLF) en {len(lineas)} "
        f"línea(s), la primera es la {lineas[0]}. En atlas un .sh así muere "
        "con \"$'\\r': command not found\" y una unidad de systemd no carga. "
        "Arréglalo con: git add --renormalize <archivo> (el eol=lf ya está en "
        ".gitattributes)."
    )


@pytest.mark.parametrize("ruta", _casos(SCRIPTS_DE_SHELL), ids=lambda p: p)
def test_el_script_de_shell_empieza_con_shebang(ruta: Path):
    """Sin `#!` el intérprete lo pone quien lo invoque, y eso cambia de máquina
    a máquina. Un `desplegar.sh` que corre bajo `sh` en vez de `bash` pierde
    `set -o pipefail` y se traga el error de la compilación que venía a evitar.
    """
    assert not _le_falta_shebang(ruta.read_bytes()), (
        f"{_nombre(ruta)} no empieza con '#!'. Agrégale como primera línea "
        "'#!/usr/bin/env bash' (antes de cualquier comentario), o systemd y "
        "cron lo ejecutarán con el intérprete que les toque."
    )
