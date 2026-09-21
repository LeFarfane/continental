"""La pasada visual (ticket 28): lo que se puede afirmar de la pantalla sin abrirla.

Este repo no ejecuta JavaScript en las pruebas y no va a abrir un navegador para
probarse a sí mismo (regla 1 de `CLAUDE.md`). Así que aquí no se mide cómo se
VE nada —eso lo hizo el recorrido del ticket, con el `scrollWidth` medido en el
teléfono y las capturas en claro y oscuro—: se cuida que las decisiones que
hacen que se vea así no se deshagan sin que nada se ponga rojo.

Son seis familias, una por casilla del ticket que se puede comprobar con texto:

- **Tres archivos servidos tal cual**: HTML, CSS y JS, sin compilar y sin nada
  de fuera. Y servidos con `Cache-Control: no-cache`, para que el mostrador no
  se quede con el JavaScript de ayer.
- **Los colores en un solo lugar**: ningún color escrito a mano fuera de las dos
  listas de `:root`, y la oscura redefine todos los de la clara.
- **El fondo explícito** en `html` y en `body`.
- **Las cifras a la derecha**, con dígitos de ancho fijo.
- **La jerarquía sin depender solo del color**: cada cosa que se distingue por
  color se distingue además por una forma, un signo, un peso o una cursiva.
- **El teléfono**: la tabla se apila por debajo de 76rem y nada fija un ancho
  mínimo mayor que un teléfono.

Y una más, que cuida a las demás pruebas: que ninguna vuelva a leer
`index.html` a secas, porque desde que la pantalla son tres archivos una
guardia de "esto NO está" que lee solo el HTML pasa por vacío.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import ESTATICOS, pantalla_completa, pantalla_servida

RAIZ = Path(__file__).resolve().parents[1]
HTML = ESTATICOS / "index.html"
CSS = ESTATICOS / "continental.css"
JS = ESTATICOS / "continental.js"


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _css() -> str:
    """La hoja SIN comentarios: los comentarios nombran colores y reglas a
    propósito, y lo que importa es lo que el navegador aplica."""
    return re.sub(r"/\*.*?\*/", "", _texto(CSS), flags=re.S)


def _bloque(css: str, inicio: str) -> str:
    """El cuerpo de un bloque con llaves anidadas (`@media … { … }`)."""
    i = css.index(inicio)
    abre = css.index("{", i)
    nivel = 0
    for j in range(abre, len(css)):
        if css[j] == "{":
            nivel += 1
        elif css[j] == "}":
            nivel -= 1
            if nivel == 0:
                return css[abre + 1:j]
    raise AssertionError(f"el bloque {inicio!r} no cierra")


def _regla(css: str, selector: str) -> str:
    """Las declaraciones de la PRIMERA regla con ese selector exacto."""
    m = re.search(r"(?:^|[{}])\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert m, f"no hay una regla para `{selector}` en continental.css"
    return m.group(1)


def _variables(bloque: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z-]+)\s*:\s*([^;]+);", bloque))


# ------------------------------------------------------ tres archivos, tal cual


def test_la_pantalla_son_tres_archivos_enlazados_desde_static():
    html = _texto(HTML)

    assert html.count('<link rel="stylesheet" href="/static/continental.css">') == 1
    assert html.count('<script src="/static/continental.js"></script>') == 1
    # Nada de estilo ni de código escondido en el HTML: si lo hubiera, los
    # colores ya no vivirían en un solo lugar y las guardias del JavaScript
    # tendrían que mirar dos sitios.
    assert "<style" not in html
    assert re.search(r"<script>(?!</script>)", html) is None
    assert " style=" not in html


def test_nada_se_pide_afuera_de_la_torre():
    """Sin fuentes ni librerías de un CDN: en atlas la pantalla tiene que
    pintarse igual sin salir a internet, y detrás de Access un recurso de
    otro dominio es una puerta más."""
    html, css, js = _texto(HTML), _css(), _texto(JS)

    assert not re.search(r'(?:src|href)="(?:https?:)?//', html)
    assert "@import" not in css
    assert "url(" not in css
    assert "@font-face" not in css
    assert not re.search(r"fetch\(\s*['\"`]https?:", js)


def test_sin_cadena_de_compilacion_ni_marco_de_trabajo():
    """HTML, CSS y JS que se sirven como están escritos, igual que Doyle y
    Marlowe. Un `import` de módulo, un `package.json` o la carpeta de un
    empaquetador serían el primer paso de una cadena que atlas no tiene."""
    js = _texto(JS)

    assert not re.search(r"^\s*(?:import|export)\s", js, re.M)
    assert "require(" not in js
    for nombre in ("package.json", "node_modules", "vite.config.js", "webpack.config.js"):
        assert not (RAIZ / nombre).exists(), nombre


# ------------------------------------------------- los colores, en un lugar


#: Cualquier manera de escribir un color a mano.
_COLOR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\("
    r"|:\s*(?:white|black|red|green|blue|gray|grey|orange|yellow|silver)\b",
    re.I,
)


def test_los_colores_se_escriben_solo_en_las_dos_listas_de_root():
    css = _css()
    claro = _bloque(css, ":root")
    oscuro = _bloque(_bloque(css, "@media (prefers-color-scheme: dark)"), ":root")
    resto = css.replace(claro, "").replace(oscuro, "")

    assert _COLOR.search(claro), "la lista clara no tiene colores: ¿se movió?"
    fuera = _COLOR.findall(resto)
    assert not fuera, f"colores escritos a mano fuera de :root: {fuera}"


def test_el_javascript_no_pinta_colores():
    """El JavaScript pone clases, nunca colores: un `style.color` escrito ahí
    no cambiaría con el tema oscuro."""
    js = re.sub(r"//[^\n]*", "", _texto(JS))

    assert not _COLOR.search(js)
    assert ".style.color" not in js
    assert ".style.background" not in js


def test_el_tema_oscuro_redefine_cada_color_del_claro():
    css = _css()
    claro = _variables(_bloque(css, ":root"))
    oscuro = _variables(_bloque(_bloque(css, "@media (prefers-color-scheme: dark)"), ":root"))

    assert len(claro) >= 8
    assert set(oscuro) == set(claro), (
        "un color que el tema oscuro no redefine se queda claro sobre fondo "
        f"oscuro: faltan {sorted(set(claro) - set(oscuro))}"
    )
    assert all(oscuro[k] != claro[k] for k in claro)


def test_los_controles_del_navegador_siguen_el_tema():
    css = _css()

    assert "color-scheme: light" in _bloque(css, ":root")
    assert "color-scheme: dark" in _bloque(css, "@media (prefers-color-scheme: dark)")


def test_el_fondo_se_declara_explicito_en_html_y_en_body():
    css = _css()

    assert "background: var(--fondo)" in _regla(css, "html")
    assert "background: var(--fondo)" in _regla(css, "body")


# ---------------------------------------------------- la densidad y las cifras


@pytest.mark.parametrize("selector", ["td.numero, th.numero", "td.cantidad, th.cantidad"])
def test_las_columnas_de_cifras_van_a_la_derecha(selector):
    assert "text-align: right" in _regla(_css(), selector)


def test_las_cifras_usan_digitos_de_ancho_fijo():
    css = _css()

    assert "tabular-nums" in _regla(css, "td.numero")
    assert "tabular-nums" in _regla(css, "td.cantidad b")
    regla = _regla(css, ".precio b")
    assert "tabular-nums" in regla and "text-align: right" in regla


def test_el_encabezado_se_queda_arriba_en_una_lista_larga():
    regla = _regla(_css(), "thead th")

    assert "position: sticky" in regla
    assert "background: var(--fondo)" in regla


# ------------------------------------------- la jerarquía, sin solo el color

#: Cada cosa que la pantalla distingue por color, y lo que la distingue ADEMÁS.
#: (selector exacto de la regla, lo que tiene que declarar, qué es)
_SIN_SOLO_COLOR = [
    ("td.numero.urgente", "font-weight: 700", "agotado: negrita"),
    ("tr.agotado > td:first-child", "box-shadow: inset 4px", "agotado: barra continua"),
    (".precio.gana", "border-left: 3px solid", "el más barato: borde y fondo"),
    (".veredicto .ahorro.gana, .veredicto .ahorro.cuesta", "border: 1px solid", "el ahorro: recuadro"),
    (".veredicto .ahorro.cuesta", "border-style: dashed", "lo que cuesta de más: recuadro punteado"),
    (".veredicto .ahorro.nose", "font-style: italic", "sin ahorro que calcular: cursiva"),
    (".precio .sindato", "font-style: italic", "sin dato: cursiva"),
    (".precio .hay.notiene", "font-weight: 600", "no lo tiene: negrita"),
    (".marca.sin-clasificar::before", 'content: "?"', "sin clasificar: signo"),
    (".marca.en-transito::before", 'content: "→"', "en tránsito: signo"),
    (".marca.probable::before, .en-camino .recepcion-marca::before", "border-style: dashed",
     "probablemente recibido: círculo punteado"),
    (".marca.llego::before", 'content: "✓"', "recibido: signo"),
    ("tr.transito, li.transito", "opacity", "en tránsito: atenuado"),
    ("tr.transito > td:first-child", "dotted", "en tránsito: barra punteada"),
    ("tr.transito.atrasado > td:first-child", "double", "atrasado: barra doble"),
    (".captura li.hecho label, .captura li.hecho .cuantas, .captura li.hecho .costo",
     "line-through", "capturado: tachado"),
]


@pytest.mark.parametrize(("selector", "declara", "que"), _SIN_SOLO_COLOR,
                         ids=[q for _, _, q in _SIN_SOLO_COLOR])
def test_lo_que_se_distingue_por_color_se_distingue_tambien_sin_el(selector, declara, que):
    assert declara in _regla(_css(), selector), que


@pytest.mark.parametrize("clase", [
    "'agotado'", "'atrasado'", "' sin-clasificar'", "en-transito", "'marca probable'",
    "llego", "vuelve", "hueco-catalogo", "hay-que-mirar",
])
def test_el_javascript_pone_las_clases_que_la_hoja_distingue(clase):
    """Una regla de CSS sin nadie que ponga su clase es una distinción que no
    existe. Las clases repiten banderas que ya llegaron hechas del servidor:
    no deciden nada."""
    assert clase in _texto(JS)


def test_los_signos_no_se_le_leen_al_lector_de_pantalla():
    """La frase de al lado ya lo dice; el signo es para el ojo. Cada `content`
    de signo trae su versión con texto alternativo vacío."""
    css = _css()
    for signo in ("?", "!", "→", "✓", "↺"):
        assert f'content: "{signo}" / ""' in css, signo


# ------------------------------------------------------------- el teléfono


def test_la_tabla_se_apila_por_debajo_de_la_computadora():
    """Por debajo de 76rem (~1200 px) la tabla deja de ser rejilla: cada
    renglón es una tarjeta que se envuelve. Cubre la tableta y el teléfono;
    el recorrido midió `scrollWidth == innerWidth` a 375 px."""
    css = _css()
    apilada = _bloque(css, "@media (max-width: 76rem)")

    assert "clip-path: inset(50%)" in _regla(apilada, "thead")
    fila = _regla(apilada, "tr")
    assert "display: flex" in fila and "flex-wrap: wrap" in fila
    # Y el teléfono sigue con su bloque propio, que es donde el botón de
    # descartar se va a su renglón (`test_descarte`). Hay dos bloques de
    # 34rem —el de la captura y el de la tabla—: basta con que uno lo diga.
    telefono = [css[i:] for i in (m.start() for m in re.finditer(r"@media \(max-width: 34rem\)", css))]
    assert any("td.acciones" in _bloque(b, "@media") for b in telefono)


def test_nada_fija_un_ancho_minimo_mayor_que_un_telefono():
    """375 px son 23.4rem. Un `min-width` mayor, fuera de una media query de
    pantalla ancha, empujaría la página hacia los lados en el teléfono."""
    for valor, unidad in re.findall(r"min-width:\s*([\d.]+)(rem|px)", _css()):
        tope = 23.4 if unidad == "rem" else 375
        assert float(valor) <= tope, f"min-width: {valor}{unidad}"


def test_una_palabra_larga_se_parte_antes_de_empujar_la_pagina():
    assert "overflow-wrap: break-word" in _regla(_css(), "body")


# ------------------------------------------------------------------ la caché


@pytest.mark.parametrize(("ruta", "tipo"), [
    ("/", "text/html"),
    ("/static/continental.css", "text/css"),
    ("/static/continental.js", "javascript"),
])
def test_la_pantalla_se_revalida_cada_vez_que_se_abre(cliente, ruta, tipo):
    """Sin `Cache-Control`, el navegador decide solo cuánto tiempo le cree a
    su copia y en ese rato no pregunta: un HTML nuevo con el JavaScript de
    ayer. `no-cache` no es "no guardes", es "pregunta antes de usarlo"."""
    respuesta = cliente.get(ruta)

    assert respuesta.status_code == 200
    assert tipo in respuesta.headers["content-type"]
    assert respuesta.headers["cache-control"] == "no-cache"


def test_lo_que_no_cambio_contesta_304_y_sigue_diciendo_no_cache(cliente):
    """El costo de revalidar: una ida y vuelta sin cuerpo."""
    primera = cliente.get("/static/continental.js")
    segunda = cliente.get("/static/continental.js",
                          headers={"If-None-Match": primera.headers["etag"]})

    assert segunda.status_code == 304
    assert segunda.content == b""
    assert segunda.headers["cache-control"] == "no-cache"


# ------------------------------------------------ las pruebas de la pantalla


def test_lo_servido_es_lo_que_esta_en_el_disco(cliente):
    """Las dos maneras de leer la pantalla entera que usan las demás pruebas
    dan el mismo texto: ninguna guardia depende de cuál eligió."""
    assert pantalla_servida(cliente) == pantalla_completa()


def test_ninguna_prueba_lee_index_html_a_secas():
    """Desde que la pantalla son tres archivos, una prueba que lee solo
    `index.html` —del disco o pidiendo `/`— revisa un texto sin el CSS ni el
    JavaScript, y sus guardias de "esto NO está" pasan por vacío. Todas van
    por `conftest.pantalla_completa` o `conftest.pantalla_servida`."""
    culpables = []
    for ruta in sorted((RAIZ / "tests").glob("test_*.py")):
        # Ésta es la única que lee cada archivo por separado, y a propósito:
        # sus afirmaciones son sobre DÓNDE vive cada cosa.
        if ruta.name == Path(__file__).name:
            continue
        for n, linea in enumerate(_texto(ruta).splitlines(), 1):
            codigo = linea.split("#", 1)[0]
            if re.search(r'"index\.html"\)?\.read_|/ "index\.html"|get\("/"\)\.text', codigo):
                culpables.append(f"{ruta.name}:{n}")
    assert not culpables, culpables
