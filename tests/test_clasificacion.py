"""Medicamento, abarrote o sin clasificar: quién decide y con qué evidencia.

El ticket 05 entero. Lo que estas pruebas cuidan por encima de todo es que
**nada caiga fuera de las tres categorías y que nada reviente**: el anaquel
viene de `dim_producto.ubicacion`, que es captura humana, y 688 de 3,429
artículos no lo tienen (medido al 2026-09). Una clasificación que truena con
un anaquel raro deja a la farmacia sin pedido del día.

`test_un_anaquel_desconocido_cae_en_sin_clasificar_y_no_revienta` es la que más
vale: recorre una lista de basura real y posible —typos, vacío, espacios,
acentos, un número suelto— y exige que todas salgan `sin clasificar` sin
excepción. Y `test_un_prefijo_no_casa_con_una_palabra_mas_larga` es su gemela
por el otro lado: las listas del YAML son prefijos, y un prefijo suelto
convertiría `ELECTROLITOS ORALES` en abarrote.

Ninguna prueba de este archivo toca Postgres ni la red. La función pura se
prueba sin leer un solo archivo; las que miran `config/continental.yml` lo
hacen a propósito, para comprobar justo que las listas salen de ahí.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from continental.almacen import LineaDeVenta, Producto
from continental.clasificacion import (
    ABARROTE,
    MEDICAMENTO,
    SIN_CLASIFICAR,
    ReglasDeClasificacion,
    clasificar,
    reglas_configuradas,
)
from continental.sugerido import calcular_pedido_sugerido

RUTA = "/api/pedido-sugerido"
RAIZ = Path(__file__).resolve().parent.parent

#: Reglas de juguete, escritas aquí y no leídas de ningún lado. Existen para
#: que la prueba de la función pura no dependa del YAML: si mañana el dueño
#: agrega un anaquel, estas pruebas no se mueven y las que sí miran el YAML
#: son las que tienen que verlo.
REGLAS_DE_JUGUETE = ReglasDeClasificacion(
    anaqueles_medicamento=("PATENTE", "BOTICA"),
    anaqueles_abarrote=("SUPER",),
    categorias_abarrote=("ELECT",),
)


# --------------------------------------------------- la función pura, sola


def test_la_funcion_pura_recibe_anaquel_y_categoria_y_no_lee_nada():
    """El criterio del ticket: anaquel + categoría entran, una de tres sale.

    Las listas entran por argumento. El día que alguien le meta un `cargar()`
    adentro "para no tener que pasarlas", esto seguiría en verde pero la
    función dejaría de poder probarse sin `config/continental.yml` — así que
    la costura que de verdad se cuida aquí es que **las reglas sean un
    argumento**, y eso es lo que estas llamadas demuestran.
    """
    assert clasificar("PATENTE 1", "GRUP4", REGLAS_DE_JUGUETE) == MEDICAMENTO
    assert clasificar("SUPER", "GRUP4", REGLAS_DE_JUGUETE) == ABARROTE
    assert clasificar("REFRIGERADOR", "GRUP4", REGLAS_DE_JUGUETE) == SIN_CLASIFICAR

    # Y las tres respuestas son exactamente las del glosario, no sinónimos.
    assert (MEDICAMENTO, ABARROTE, SIN_CLASIFICAR) == (
        "medicamento",
        "abarrote",
        "sin clasificar",
    )


def test_medicamento_es_patente_generico_naturista_botica_y_vitrina():
    """Los cinco anaqueles del glosario, con su número, sobre las reglas reales.

    **Botica entra** porque es material de curación que se le compra a los
    mismos proveedores (CONTEXT.md). Si alguien lo saca de la lista creyendo
    que "no es medicamento", dos anaqueles enteros dejarían de aparecer en la
    vista con la que se arma el pedido.
    """
    reglas = reglas_configuradas()

    for anaquel in (
        "PATENTE 1",
        "PATENTE 6",
        "GENERICO 1",
        "GENERICO 4",
        "NATURISTA",
        "BOTICA 1",
        "BOTICA 3",
        "VITRINA 1",
        "VITRINA 3",
    ):
        assert clasificar(anaquel, "", reglas) == MEDICAMENTO, anaquel


def test_abarrote_es_super_canasta_refrigerador_mas_dos_categorias():
    """Dos caminos a abarrote: el anaquel y, cuando el anaquel no dice nada, la
    categoría.

    Compite contra la tienda de la esquina, no contra una farmacia, y no se le
    compra a un proveedor de medicamentos (CONTEXT.md).
    """
    reglas = reglas_configuradas()

    for anaquel in ("SUPER", "CANASTA", "REFRIGERADOR"):
        assert clasificar(anaquel, "", reglas) == ABARROTE, anaquel

    # Por categoría, con el anaquel callado: es el otro camino y es el único
    # que justifica que `categorias_abarrote` exista en el YAML.
    assert clasificar("", "SUPER", reglas) == ABARROTE
    assert clasificar("", "ELECT", reglas) == ABARROTE


def test_el_anaquel_le_gana_a_la_categoria_cuando_se_contradicen():
    """Anaquel de medicamento + categoría de abarrote → **medicamento**.

    El glosario lo decide y no este código: el anaquel "es un lugar, no una
    etiqueta de catálogo, y por eso se le cree más que a la categoría". Un
    producto que está físicamente en VITRINA 2 se le compra al mismo proveedor
    aunque alguien lo haya capturado en la categoría SUPER hace tres años.

    La regla se prueba en los dos sentidos para que no quede como un accidente
    del orden de los `if`.
    """
    reglas = reglas_configuradas()

    assert clasificar("VITRINA 2", "SUPER", reglas) == MEDICAMENTO
    assert clasificar("BOTICA 1", "ELECT", reglas) == MEDICAMENTO
    # Y al revés: anaquel de abarrote manda aunque la categoría sea de
    # medicamento, que es lo que hace que la regla sea "el anaquel manda" y no
    # "medicamento gana siempre".
    assert clasificar("CANASTA", "GRUP4", reglas) == ABARROTE


def test_la_categoria_solo_habla_cuando_el_anaquel_no_dice_nada():
    """La categoría es el segundo camino, nunca el primero.

    Un anaquel desconocido no es lo mismo que un anaquel de medicamento: ahí
    sí se le pregunta a la categoría, porque no hay lugar físico que
    contradecirla. Lo que no puede pasar es que la categoría rescate a un
    producto que el anaquel ya clasificó.
    """
    reglas = reglas_configuradas()

    assert clasificar("ANAQUEL QUE NADIE CONOCE", "ELECT", reglas) == ABARROTE
    assert clasificar("SIN UBICACION", "SUPER", reglas) == ABARROTE
    # Sin categoría de abarrote tampoco, se queda sin clasificar: no hay lista
    # de categorías de medicamento y no se inventa una.
    assert clasificar("SIN UBICACION", "GRUP4", reglas) == SIN_CLASIFICAR


# ------------------------------------- lo que no se reconoce, no se esconde


def test_un_anaquel_desconocido_cae_en_sin_clasificar_y_no_revienta():
    """Lo que no se reconoce cae en `sin clasificar`, **sin excepción**.

    Los cinco typos conocidos —`GENRICO`, `VITRNA`, `VITRINAS`, `PTENTE`,
    `PATEN TE`— ya los corrige dbt río arriba con el macro
    `normalizar_ubicacion` de farmacia-data, y **aquí no se vuelven a
    corregir**: duplicar esa tabla haría que las dos divergieran el día que se
    agregue el sexto. Lo que sí se garantiza aquí es lo otro: que un anaquel
    que no se reconoce no tumbe la clasificación del resto de la lista.

    `None` entra en la lista a propósito. La dataclass lo tipa como `str`, pero
    esta función la puede llamar cualquiera, y un `AttributeError` aquí dejaría
    a la farmacia sin pedido del día por un producto.
    """
    reglas = reglas_configuradas()

    for anaquel in (
        "GENRICO 2",  # los cinco typos, por si dbt dejara de normalizar
        "VITRNA 1",
        "VITRINAS 2",
        "PTENTE 3",
        "PATEN TE 4",
        "",  # 688 de 3,429 artículos, medido al 2026-09
        "   ",
        "SIN UBICACION",  # lo que dbt pone cuando el campo viene vacío
        "PASILLO 7",
        "3",
        "—",
        "MOSTRADOR/VITRINA",  # parecido a uno bueno, pero no lo es
        None,
    ):
        assert clasificar(anaquel, "GRUP4", reglas) == SIN_CLASIFICAR, repr(anaquel)

    # Y la categoría tampoco puede tumbarlo.
    assert clasificar("PASILLO 7", None, reglas) == SIN_CLASIFICAR


def test_un_prefijo_no_casa_con_una_palabra_mas_larga():
    """Las listas son prefijos de un anaquel con número, no trozos de palabra.

    `PATENTE` tiene que casar con `PATENTE 1`; `SUPER` **no** puede casar con
    `SUPERFICIE` ni `ELECT` con `ELECTROLITOS ORALES`, que es una categoría
    perfectamente posible en una farmacia y acabaría vendiendo suero oral como
    abarrote. La frontera es la que separa una letra de un número: lo que sigue
    al prefijo o no existe, o no es una letra.
    """
    reglas = reglas_configuradas()

    for anaquel in ("SUPERFICIE", "CANASTAS VARIAS", "BOTICARIO", "VITRINERO"):
        assert clasificar(anaquel, "", reglas) == SIN_CLASIFICAR, anaquel

    for categoria in ("ELECTROLITOS", "ELECTROLITOS ORALES", "SUPERALIMENTOS"):
        assert clasificar("", categoria, reglas) == SIN_CLASIFICAR, categoria

    # El otro lado del cinturón: el número sí pega, con espacio o sin él.
    assert clasificar("PATENTE 1", "", reglas) == MEDICAMENTO
    assert clasificar("PATENTE1", "", reglas) == MEDICAMENTO


# ------------------------------------------- las listas viven en el YAML


def test_las_listas_salen_del_yaml_y_no_del_codigo():
    """El criterio del ticket, comprobado contra el archivo versionado.

    Se lee `config/continental.yml` a mano y se compara con lo que la capa
    delgada devuelve: si alguien copia las listas al código "para no leer el
    archivo", el YAML y el código empiezan a divergir y esto se pone rojo el
    día que se toque uno solo de los dos.
    """
    crudo = yaml.safe_load((RAIZ / "config" / "continental.yml").read_text("utf-8"))
    pedido = crudo["pedido"]
    reglas = reglas_configuradas()

    assert list(reglas.anaqueles_medicamento) == pedido["anaqueles_medicamento"]
    assert list(reglas.anaqueles_abarrote) == pedido["anaqueles_abarrote"]
    assert list(reglas.categorias_abarrote) == pedido["categorias_abarrote"]
    assert reglas.anaqueles_medicamento, "el YAML se leyó vacío: no prueba nada"


def test_ningun_anaquel_va_escrito_en_el_codigo():
    """El cinturón del criterio de arriba, sobre el código en vez del resultado.

    La prueba de comparación pasaría en verde con las listas duplicadas en un
    `if anaquel.startswith("PATENTE")` que nadie usa, y ese `if` sería el que
    mordiera el día que el dueño agregue `PATENTE 7` al YAML y nada cambie.
    Esto lo caza al leer el archivo.
    """
    for nombre in ("clasificacion.py", "sugerido.py", "web/app.py"):
        fuente = (RAIZ / "src" / "continental" / nombre).read_text("utf-8")
        # Se mira el código, no los comentarios: un ejemplo en una docstring
        # —"PATENTE 1 a 6"— es justo lo que hay que escribir.
        codigo = "\n".join(
            linea for linea in fuente.splitlines() if not linea.lstrip().startswith("#")
        )
        for prohibido in ('"PATENTE"', '"GENERICO"', '"BOTICA"', '"SUPER"', '"ELECT"'):
            assert prohibido not in codigo, (
                f"{nombre} trae {prohibido} escrito en el código. Las listas "
                "viven en config/continental.yml: duplicarlas hace que el "
                "YAML y el código digan cosas distintas sin que nadie avise."
            )


# ------------------------------------------- cada renglón lo dice de sí mismo


def test_cada_renglon_de_la_lista_expone_su_clasificacion(cliente, almacen):
    """El criterio del ticket: el renglón lo dice, no lo deduce quien lo pinta.

    Se prueba por la API porque es donde de verdad se ve: si la clasificación
    se calculara en el JavaScript de la pantalla, la lógica viviría en dos
    lugares y solo uno estaría probado.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "SABRITAS", anaquel="CANASTA"),
        _producto(3, "7501000000003", "PILAS AA", anaquel="", categoria="ELECT"),
        _producto(4, "7501000000004", "MISTERIO", anaquel="", categoria="GRUP4"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3, 4)
    ]

    cuerpo = cliente.get(RUTA).json()
    por_clave = {r["clave"]: r["clasificacion"] for r in cuerpo["renglones"]}

    assert por_clave == {
        "7501000000001": MEDICAMENTO,
        "7501000000002": ABARROTE,
        "7501000000003": ABARROTE,
        "7501000000004": SIN_CLASIFICAR,
    }


def test_un_producto_fuera_del_catalogo_queda_sin_clasificar_y_sigue_en_la_lista(
    cliente, almacen
):
    """Sin catálogo no hay anaquel ni categoría que mirar: `sin clasificar`.

    Y **no se esconde**, que es la misma regla de los 688 sin anaquel: un
    producto que desaparece de la lista es mercancía que va a faltar sin que
    nadie se entere (regla 4 de CLAUDE.md).
    """
    almacen.catalogo_en_memoria = []
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), producto_id=99, cantidad=2)]

    cuerpo = cliente.get(RUTA).json()

    assert len(cuerpo["renglones"]) == 1
    assert cuerpo["renglones"][0]["clasificacion"] == SIN_CLASIFICAR


def test_sin_reglas_todo_queda_sin_clasificar_y_nada_se_pierde():
    """El default de la función pura no inventa: sin listas no clasifica nada.

    Importa cuál es el default. `sin clasificar` se muestra siempre y marcado,
    así que unas reglas vacías dejan una lista fea pero completa; cualquier
    otro default —"si no sé, es medicamento"— escondería abarrotes dentro de
    la vista de farmacia el día que alguien despliegue con el YAML a medias.
    """
    pedido = calcular_pedido_sugerido(
        ventas=[_venta(dt.date(2026, 9, 16), 1, 3)],
        catalogo=[_producto(1, "7501000000001", "PARACETAMOL")],
    )

    assert pedido.renglones[0].clasificacion == SIN_CLASIFICAR
    assert len(pedido.renglones) == 1


def test_la_pantalla_marca_el_renglon_que_no_es_medicamento(cliente):
    """La clasificación se ve, y se ve donde molesta menos.

    El ticket no pide columna ni interruptor —eso es el 06—, así que hoy el
    renglón lleva una marca discreta y solo cuando **no** es medicamento:
    etiquetar como "medicamento" nueve de cada diez renglones de una farmacia
    es ruido que se deja de leer a la tercera pantalla, y el dato que de
    verdad cambia una decisión es el que se sale de lo esperado.

    Se comprueba sobre el código de la pantalla porque es HTML+JS a mano, sin
    framework ni build: atlas es un Athlon II X4 de 2010.
    """
    portada = cliente.get("/").text

    assert "r.clasificacion" in portada
    assert "sin clasificar" in portada
    # **La lista se pide UNA sola vez**, y eso es lo que de verdad se está
    # afirmando: ni el interruptor, ni descartar, ni consultar un precio
    # vuelven a pedirla. Dos lecturas en momentos distintos pueden no coincidir
    # y nadie sabría cuál tiene razón.
    assert portada.count("fetch('/api/pedido-sugerido')") == 1

    # DIEZ llamadas en total y ni una más. Fueron cinco, siete con el ticket 12
    # y diez con el 19, y el número está escrito a mano a propósito: cada
    # llamada nueva desde esta pantalla es una decisión —qué se le pide al
    # servidor y qué se calcula aquí— y agregarla sin querer es cómo la regla
    # que decide algo se muda al único archivo que ninguna prueba de Python
    # mira.
    #
    # Las cinco primeras: la lista, la salud y los módulos al cargar, y dos
    # POST que ocurren cuando alguien los pide —el cierre del ticket 08 y el
    # mover un renglón, que es UNA sola llamada compartida por descartar,
    # devolver (ticket 10) y ajustar la cantidad (ticket 11)—.
    #
    # Las dos del ticket 12 son las del precio: el POST que pide la consulta y
    # el GET que la sondea.
    #
    # Las tres del ticket 19: completar lo que falta, y los dos pasos de abrir
    # una sesión caducada (abrir y confirmar). **Las tres van a Continental y
    # ninguna a Doyle** —el navegador no le habla a un módulo, regla 2 de
    # CLAUDE.md—: quien le pide a Doyle que abra el navegador es Continental
    # por HTTP, no esta pantalla.
    #
    # La del ticket 22: tachar un renglón en la pantalla de captura. Es un POST
    # que devuelve la lista entera, como partir y enviar —que no salen en esta
    # cuenta porque su `fetch(` parte la línea antes de la ruta—, y **no vuelve
    # a pedir la lista**: la de arriba sigue siendo una sola.
    #
    # Las dos del ticket 25: cancelar un pedido y devolver un renglón atrasado.
    # Las dos van a Continental, y al terminar **vuelven a cargar la pantalla
    # con la misma función** —`cargarPedido`—, así que la lectura de la lista
    # sigue escrita una sola vez.
    #
    # La del ticket 26: confirmar o rechazar una recepción, UNA sola llamada
    # para las dos acciones, que al terminar también vuelve a `cargarPedido`.
    assert portada.count("fetch('/api/") == 14
    assert portada.count("fetch('/api/pedido-sugerido')") == 1


# ------------------------------------------------------------------ ayudas


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 50.0,
        costo=cantidad * 30.0,
        utilidad=cantidad * 20.0,
    )


def _producto(
    producto_id: int,
    clave: str,
    descripcion: str,
    anaquel: str = "PATENTE 1",
    categoria: str = "GRUP4",
) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=descripcion,
        categoria=categoria,
        departamento="MEDICAMENTO",
        anaquel=anaquel,
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=4,
        esta_activo=True,
        es_granel=False,
    )
