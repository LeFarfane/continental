"""La pantalla de la bitácora navegable (ADR 0020, 2026-09-27).

`tests/test_navegacion.py` ya prueba los datos y la API —`almacenamiento.
vecinos` y `GET /api/pedido-sugerido/dia/{fecha}`— que dejó lista otra sesión
(commit `c013df8`). Este archivo prueba lo que se construyó ENCIMA de eso: el
contenedor de navegación con la fecha al centro y una flecha a cada lado, y
cómo `continental.js` usa las tres formas de respuesta que esa ruta puede
traer —la lista completa, "domingo o festivo" y el 404 que no sabe por qué—
para que la persona nunca vea una lista vacía sin saber por qué está vacía
(regla 4 de `CLAUDE.md`, la que más importa en este ticket).

Este repo no ejecuta JavaScript en las pruebas (ver el docstring de
`test_pasada_visual.py`), así que lo del JavaScript se fija con pruebas
estáticas sobre el texto del archivo, exactamente como ya hace el resto del
suite (`test_cierre.py`, sección "la pantalla"). Son cuatro grupos:

1. **El HTML del contenedor**: nace escondido, con sus tres piezas.
2. **Qué URL pide cada carga**: "hoy" sin fecha —la única con permiso de
   armar el día—, un día de la bitácora con `GET .../dia/{fecha}`, que solo
   lee.
3. **Las tres respuestas de un día**, y que ninguna las confunde: el
   JavaScript no compone la frase de "domingo, la farmacia no abre" ni la de
   "no se sabe por qué" —las dos llegan hechas de Python—, por la misma
   lección de los tickets 15 y 21 que ya sigue el resto de esta pantalla.
4. **Lo pasado es de solo lectura, pero se puede reabrir**: no hay botón
   nuevo de "editar lo pasado" —la garantía sigue siendo el `estado` de la
   lista, que ya gobierna toda la pantalla desde el ADR 0016— y el botón de
   reabrir es el mismo de siempre.

Ninguna prueba toca Postgres ni la red.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import pantalla_completa


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def _funcion(nombre: str, *, hasta: int = 2200) -> str:
    """El cuerpo de una función con nombre, para acotar dónde se busca."""
    script = _script()
    inicio = script.index(nombre)
    return script[inicio : inicio + hasta]


# ------------------------------------------------- el HTML del contenedor


def test_el_contenedor_nace_escondido_con_sus_tres_piezas():
    pantalla = pantalla_completa()

    assert re.search(
        r'<div class="navegacion" id="pedido-navegacion" hidden>', pantalla
    )
    assert 'id="pedido-navegacion-anterior"' in pantalla
    assert 'id="pedido-navegacion-fecha"' in pantalla
    assert 'id="pedido-navegacion-siguiente"' in pantalla


def test_las_flechas_reusan_el_boton_que_ya_hay_y_no_estrenan_estilo():
    """`.accion` ya existe (el botón de completar, el de devolver…): las
    flechas lo reusan en vez de traer un color o una forma nuevos."""
    pantalla = pantalla_completa()
    inicio = pantalla.index('id="pedido-navegacion"')
    contenedor = pantalla[inicio : pantalla.index("</div>", inicio)]

    assert contenedor.count('class="accion"') == 2


def test_las_flechas_tienen_rotulo_para_quien_no_ve_la_flecha():
    pantalla = pantalla_completa()

    assert 'aria-label="Día anterior"' in pantalla
    assert 'aria-label="Día siguiente"' in pantalla


def test_el_contenedor_solo_acomoda_y_no_trae_color_a_mano():
    """La regla del ticket 28: los colores viven en `:root`. `.navegacion`
    puede acomodar los tres en línea, pero no puede pintar nada."""
    css = (
        Path(__file__).resolve().parents[1]
        / "src" / "continental" / "web" / "static" / "continental.css"
    ).read_text(encoding="utf-8")
    inicio = css.index(".navegacion {")
    bloque = css[inicio : inicio + 300]

    assert "#" not in bloque
    assert "rgb" not in bloque


# ---------------------------------------------- qué URL pide cada carga


def test_hoy_se_pide_sin_fecha_y_un_dia_de_la_bitacora_por_su_fecha():
    script = _script()

    assert "async function cargarPedido(fecha)" in script
    assert (
        "const url = fecha ? '/api/pedido-sugerido/dia/' + fecha : "
        "'/api/pedido-sugerido';"
    ) in script
    assert "fetch(url)" in script


def test_al_abrir_la_pantalla_se_pide_hoy_sin_fecha():
    """Decisión 1 del dueño: al abrir, siempre cae en el día de hoy. No hay
    `localStorage` ni nada que recuerde dónde se quedó la persona."""
    script = _script()

    assert re.search(r"\r?\ncargarPedido\(\);\r?\n", script)
    assert "localStorage" not in _funcion("cargarPedido(fecha)", hasta=6000)


def test_las_flechas_navegan_con_la_fecha_del_vecino():
    script = _script()

    assert "cargarPedido(vecinos.anterior)" in script
    assert "cargarPedido(vecinos.siguiente)" in script


def test_las_flechas_se_esconden_sin_vecino_y_no_solo_se_deshabilitan():
    """Regla 4: sin dato no hay botón que 404earía o mentiría sobre qué hay
    al lado. `vecinos` en `null` (o ausente) esconde las dos."""
    cuerpo = _funcion("const pintarNavegacion", hasta=900)

    assert "anterior.hidden = !(vecinos && vecinos.anterior)" in cuerpo
    assert "siguiente.hidden = !(vecinos && vecinos.siguiente)" in cuerpo
    assert "if (!fecha) { caja.hidden = true; return; }" in cuerpo


def test_la_etiqueta_del_centro_dice_hoy_cuando_es_hoy():
    cuerpo = _funcion("const pintarNavegacion", hasta=900)

    assert "FECHA_DE_HOY" in cuerpo
    assert "' (hoy)'" in cuerpo


# ------------------------------- las tres respuestas de un día, sin confundirlas


def test_una_falla_de_verdad_se_distingue_del_404_que_no_sabe_por_que():
    """`que_hacer` es la marca de una falla de lectura (`fallas.que_hacer`,
    ticket 29); el 404 de la bitácora no la trae y por eso no cae en esa
    rama —si cayera, se leería "no se pudo armar" sobre un día que solo no
    tiene lista, que es un motivo distinto."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=3200)

    assert (
        "if (datos.ok === false && (datos.que_hacer || datos.sin_respuesta)) {"
        in cuerpo
    )


def test_el_404_de_la_bitacora_no_inventa_una_causa():
    """Regla 4: "puede ser futura, de antes de Continental, o un hueco" es
    justo lo que el servidor ya dijo que no distingue (`app.
    pedido_sugerido_de_un_dia`). El JavaScript no compone esa frase: solo
    pinta `datos.detalle`, tal cual llega."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=4000)

    assert "nota('pedido-nota', datos.detalle || '', 'aviso');" in cuerpo
    # Ninguna de las tres explicaciones del 404 se ESCRIBE como texto que
    # afirma algo: solo pueden aparecer dentro de un comentario que describe
    # lo que el SERVIDOR ya dijo, nunca en una cadena que la pantalla pinte.
    codigo = re.sub(r"//[^\r\n]*", "", cuerpo)
    for prohibido in ("fecha futura", "antes de que Continental existiera", "un hueco"):
        assert prohibido not in codigo


def test_domingo_o_festivo_no_compone_la_frase_la_pinta():
    """La frase ("Domingo: la farmacia no abre…" / "Independencia: día
    festivo…") la redacta `fallas.frase_del_dia_sin_lista` en Python —lección
    de los tickets 15 y 21—. El JavaScript solo la muestra."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=4000)

    assert "if (datos.dia_sin_lista) {" in cuerpo
    assert "nota('pedido-nota', datos.dia_sin_lista.frase, 'aviso');" in cuerpo
    # Si el JavaScript compusiera la frase como texto que afirma algo, alguna
    # de estas palabras aparecería fuera de un comentario: la frase de
    # verdad vive en `fallas.py`, no aquí.
    codigo = re.sub(r"//[^\r\n]*", "", cuerpo)
    for prohibido in ("la farmacia no abre", "día festivo", "Domingo:"):
        assert prohibido not in codigo


def test_ningun_dia_sin_lista_pierde_las_flechas_de_navegacion():
    """Las tres formas de respuesta traen `vecinos` (ver `_dia_sin_lista` y el
    404 en `app.py`): domingo, festivo y el 404 ambiguo siguen ofreciendo
    llegar al día de al lado, no solo la lista completa."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=4000)

    assert cuerpo.count("pintarNavegacion(") >= 3


def test_lo_que_pinto_un_dia_anterior_se_apaga_antes_de_los_tres_casos_sin_lista():
    """Sin esto, navegar de un día con renglones a un domingo dejaría la
    tabla, el cierre o el recuadro de completar pegados de otro día."""
    cuerpo = _funcion("async function cargarPedido(fecha)", hasta=4000)

    assert cuerpo.count("ocultarLoDeOtroDia();") == 3


def test_ocultar_lo_de_otro_dia_apaga_la_tabla_y_los_bloques_de_una_lista():
    cuerpo = _funcion("const ocultarLoDeOtroDia", hasta=600)

    for id_ in (
        "pedido-tabla", "armado", "cierre", "pedido-avisos", "vistas",
        "completar", "particion", "descartados", "pedido-corrida",
        "pedido-sin-clasificar", "recepcion", "en-camino",
    ):
        assert f"'{id_}'" in cuerpo, id_


# --------------------------------------- lo pasado es de solo lectura, pero se reabre


def test_no_hay_un_segundo_candado_para_lo_pasado_el_estado_sigue_siendo_el_unico():
    """Decisión 2 del dueño: normal cerrado, no se descarta, no se ajusta, no
    se pide. La garantía sigue siendo `datos.estado === 'abierto'`, la misma
    desde el ADR 0016 —esta pantalla no inventa una segunda regla que
    dependa de si la lista es de hoy o de la bitácora."""
    script = _script()

    assert "editable: datos.estado === 'abierto'" in script
    # Ninguna condición nueva mira la fecha para decidir qué se puede tocar:
    # si apareciera `fecha ===` o `=== FECHA_DE_HOY` cerca de `editable`, la
    # pantalla estaría decidiendo la edición dos veces, con dos reglas que
    # podrían no coincidir.
    cuerpo = _funcion("const repintar = () => {", hasta=700)
    assert "FECHA_DE_HOY" not in cuerpo
    assert "FECHA_ACTUAL" not in cuerpo


def test_el_boton_de_reabrir_sigue_siendo_el_mismo_para_cualquier_dia():
    """Nace escondido y solo `reapertura.se_puede` lo enseña (ADR 0016): la
    bitácora navegable no necesita un botón de reabrir aparte porque
    `_respuesta_de_la_lista` ya calcula `reapertura` para cualquier día,
    hoy o pasado (`tests/test_navegacion.py`)."""
    pantalla = pantalla_completa()

    assert re.search(r'<button type="button" id="reabrir" hidden>', pantalla)
    assert pantalla.count('id="reabrir"') == 1


# ----------------------------- recargar no pierde el lugar donde se estaba


def test_recibir_o_cancelar_recargan_el_dia_que_se_esta_viendo_no_siempre_hoy():
    """Confirmar una recepción, recibir a mano, cancelar un pedido o devolver
    un atrasado cambian lo que viene en camino y se recargan enteros —ese
    bloque solo lo trae la carga—. Antes de la bitácora navegable "recargar"
    siempre quería decir "hoy" porque no había otro día que ver; con
    navegación, recargar tiene que quedarse en el día que la persona estaba
    viendo, no mandarla de vuelta a hoy sin que lo pidiera."""
    script = _script()

    assert "const recargarLoQueSeVe = () =>" in script
    assert (
        "cargarPedido(FECHA_ACTUAL === FECHA_DE_HOY ? undefined : FECHA_ACTUAL);"
        in script
    )
    # Las cuatro acciones usan la misma función: ninguna volvió a escribir
    # `await cargarPedido()` a secas, que habría sido el error de raíz.
    assert script.count("await recargarLoQueSeVe();") == 4
    assert "await cargarPedido();" not in script
