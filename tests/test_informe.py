"""`continental.informe`: el vocabulario que `forma.py` y `verificar.py`
comparten sin importarse el uno al otro (enmienda del 2026-09-21 al ADR 0017).

Antes de este módulo, `forma.py` tomaba `Informe`, `Resultado`,
`OK`/`FALLA`/`PENDIENTE` y sus tres constructores de
`from continental.verificar import ...` —un préstamo de lo **privado** de un
módulo hacia otro—, y `verificar.py` sólo podía usar `forma.py` importándolo
adentro de sus funciones, para no cerrar el círculo. Las funciones puras y los
constructores del informe ya se prueban de sobra, indirectamente, en
`tests/test_forma.py` y `tests/test_verificar.py` —los dos importan este
módulo a través de `f.` y `v.`, y ejercitan `Informe`, `Resultado`, `OK`,
`FALLA`, `PENDIENTE` con esos alias—, así que este archivo no repite esa
cobertura. Lo que sí es nuevo, y lo único que le falta a la garantía, son dos
cosas:

- que `informe.py` **no vuelva a importar** ni a `verificar` ni a `forma`,
  que es la comprobación de que el círculo no se puede volver a cerrar; y
- que `COMANDO_FORMA` —la cadena que antes estaba escrita dos veces, a mano,
  en `forma.py` y en `verificar.py`— sea de verdad **el mismo texto** en los
  dos lugares donde el informe la usa, y no dos copias que un día se separan.
"""

from __future__ import annotations

import ast
from pathlib import Path

from continental import forma as f
from continental import informe as inf
from continental import verificar as v
from continental.latido import ABAJO, ResultadoDelLatido

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "src" / "continental" / "informe.py"


# ==========================================================================
# El círculo no se puede volver a cerrar
# ==========================================================================


def test_informe_no_importa_ni_a_verificar_ni_a_forma():
    """La garantía completa de la enmienda: sobre el árbol, no de palabra.

    `forma.py` y `verificar.py` comparten este vocabulario precisamente para
    dejar de importarse el uno al otro en privado. Si algún día `informe.py`
    importara cualquiera de los dos —o al paquete `continental` entero, que
    los trae consigo—, el ciclo estaría de vuelta, sólo que un archivo más
    lejos y más difícil de notar.
    """
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    nombrados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombrados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombrados.add(nodo.module)

    prohibidos = {"continental", "continental.forma", "continental.verificar"}
    coladas = nombrados & prohibidos
    assert not coladas, (
        f"informe.py importa {sorted(coladas)}. Eso reabre el círculo que "
        f"este archivo existe para cerrar."
    )


def test_informe_no_nombra_un_motor_ni_el_reloj():
    """Nada aquí lee de Postgres ni mira el reloj: son constantes y texto.

    Es la misma comprobación que `tests/test_verificar.py` y
    `tests/test_forma.py` les hacen a sus propias funciones puras, aplicada
    al módulo entero: todo lo que hay aquí es la mitad pura.
    """
    arbol = ast.parse(FUENTE.read_bytes(), filename=str(FUENTE))
    nombrado = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)
    }
    prohibido = {"motor", "connect", "execute", "text", "create_engine", "now", "today", "open"}
    assert not nombrado & prohibido


# ==========================================================================
# `COMANDO_FORMA`: un solo texto, citado en los dos lugares de siempre
# ==========================================================================


def test_comando_forma_es_el_texto_que_ya_conocian_las_dos_pruebas():
    """El valor no cambió con la mudanza: sigue siendo exactamente el comando
    que `desplegar.sh` y las dos suites ya citaban de memoria."""
    assert inf.COMANDO_FORMA == (
        "cd ~/proyectos/Continental && .venv/bin/python -m continental.verificar --forma"
    )
    # Los dos módulos importan la MISMA constante, no una copia: si un día se
    # editara sólo en un lado dejarían de ser el mismo objeto.
    assert f.COMANDO_FORMA is inf.COMANDO_FORMA
    assert v.COMANDO_FORMA is inf.COMANDO_FORMA


def test_forma_cita_comando_forma_cuando_la_revision_misma_revienta(caplog):
    """El primero de los dos lugares: `forma.antes_del_lote`, si `revisar()`
    levanta antes de dar un veredicto. Ya lo cubre
    `tests/test_forma.py::test_si_la_revision_misma_revienta_el_lote_tampoco_corre_y_no_filtra_el_texto`
    para la falla en general; aquí se repite nada más para dejar en un mismo
    lugar la prueba de que las dos citas usan la constante compartida."""
    latidos: list[dict] = []

    def revisar():
        raise RuntimeError("como sea")

    def latir(**kw):
        latidos.append(kw)
        return ResultadoDelLatido(se_mando=True, estado=ABAJO)

    with caplog.at_level("INFO", logger="continental"):
        codigo = f.antes_del_lote(revisar=revisar, latir=latir)

    assert codigo != 0
    assert inf.COMANDO_FORMA in caplog.text


def test_verificar_cita_comando_forma_cuando_faltan_las_columnas_del_envio():
    """El segundo lugar: `verificar.revisar_pedidos_enviados`, si a
    `pedidos.pedido` le faltan `estado` o `enviado_por`. Antes de la mudanza
    esto era una cadena escrita a mano, igual que la de arriba; ahora las dos
    citan `informe.COMANDO_FORMA`."""
    informe = v.revisar_pedidos_enviados([], frozenset({"pedido_id", "negocio"}))

    (falla,) = informe.fallas
    assert inf.COMANDO_FORMA in falla.reparacion
