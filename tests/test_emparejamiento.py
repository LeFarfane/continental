"""El emparejamiento por EAN: que los cuatro hablen del mismo producto (ticket 13).

**La tabla de casos va antes que el código**, y este archivo es esa tabla. Lo
que se prueba aquí es una **función pura** —`precios.emparejar`, que recibe lo
que devolvió un proveedor y la clave buscada, y devuelve la fila aceptada o el
motivo del rechazo— así que ninguna prueba de este archivo abre una conexión,
duerme, mira el reloj ni llama a Doyle. Las dos que pasan por `TestClient` son
las dos últimas, y están para demostrar que el motivo llega hasta la fila
guardada y hasta el JSON de la pantalla.

## Las cuatro reglas, en una frase cada una

| Proveedor | Regla | Por qué |
|---|---|---|
| NADRO | EAN de 13 dígitos directo | el portal muestra el EAN |
| LEVIC | EAN de 13 dígitos directo | el portal muestra el EAN |
| QuePharma | EAN de 13 dígitos directo | usa código interno, así que **casi nunca va a emparejar**, y eso es lo esperado |
| VICMA | exactamente un resultado | muestra código interno pero **sí indexa el EAN** (ADR 0002) |

La diferencia entre QuePharma y VICMA es la que más cuesta ver y la que más
importa: los dos muestran código interno, pero de VICMA se sabe que su búsqueda
indexa el EAN y de QuePharma **ni siquiera está confirmado que encuentre por
EAN** (ADR 0002). Darle a QuePharma la regla de VICMA sería aceptar como "tu
producto" al único resultado de una búsqueda que quizá ni buscó lo que se le
pidió — que es exactamente el error de Marlowe con otro disfraz.

## Los cuatro casos que pide el ticket

`empareja`, `dos resultados`, `cero resultados`, `el proveedor falló`. Están
en cuatro secciones con ese nombre, y **por proveedor donde la regla difiere**.

## Lo que este archivo NO puede demostrar

Que VICMA con un solo resultado sea de verdad el producto buscado. Se acepta
porque el portal indexó el EAN, no porque aquí se compare nada: la evidencia
—código y descripción de la fila— se guarda para que una persona lo cace de un
vistazo. Está dicho con nombre y apellido en
`test_vicma_se_acepta_a_ciegas_y_por_eso_guarda_la_evidencia`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from continental.almacen import LineaDeVenta, Producto
from continental.consultas import lecturas_como_json
from continental.dobles import (
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_en_reconocimiento,
    respuesta_lista,
    respuesta_pendiente,
)
from continental.doyle import EstadoDeBusqueda, FilaDeProveedor, RespuestaDeProveedor
from continental.precios import (
    MOTIVOS,
    NO_EMPAREJA,
    POR_EAN,
    POR_UN_SOLO_RESULTADO,
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_SELECTORES,
    SIN_TIEMPO,
    VARIOS_RESULTADOS,
    congelar,
    emparejar,
    leer_el_precio,
    regla_del_proveedor,
)

#: El EAN que se busca. Es el del producto real con el que se midió Doyle el
#: 2026-09-19, para que la prueba y la corrida de verdad hablen del mismo caso.
CLAVE = "7501349028234"

#: Otro EAN de 13 dígitos, válido y distinto. Es la caja de 60 del error de
#: Marlowe: mismo medicamento, otra presentación, otro código de barras.
OTRO_EAN = "7501349099999"

#: Un código interno de proveedor: ni es EAN, ni tiene 13 dígitos. Es lo que
#: muestran VICMA y QuePharma.
INTERNO = "A-1"

#: Los cuatro del glosario, con la clave con la que los nombra Doyle.
LOS_CUATRO = ("levic", "nadro", "quepharma", "vicma")

#: Los tres que emparejan por EAN directo. VICMA queda fuera **a propósito**:
#: es el único con regla propia, y tenerlo aparte obliga a escribir su caso.
LOS_DEL_EAN = ("nadro", "levic", "quepharma")

NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
RUTA = "/api/pedido-sugerido"


# ------------------------------------------------------------- utilidades


def _fila(clave: str, descripcion: str, precio: str) -> FilaDeProveedor:
    return FilaDeProveedor(
        clave=clave,
        descripcion=descripcion,
        precio=precio,
        precio_publico="",
        existencia="40",
    )


def _listo(proveedor: str, filas, total: int | None = None) -> RespuestaDeProveedor:
    """Un proveedor que terminó, con `total` separado de `len(filas)`.

    El `total` se puede fijar aparte porque **Doyle corta la lista en 20** y esa
    diferencia es justo lo que decide VICMA. Un ayudante que los atara siempre
    haría imposible escribir el caso que importa.
    """
    filas = tuple(filas)
    return RespuestaDeProveedor(
        proveedor=proveedor,
        estado="listo",
        filas=filas,
        total=len(filas) if total is None else total,
    )


def _empareja(proveedor: str) -> RespuestaDeProveedor:
    """El caso feliz **de cada proveedor**, cada uno por su propia regla.

    NADRO, LEVIC y QuePharma: una fila con el EAN buscado. VICMA: una sola
    fila, con código interno, porque eso es todo lo que su regla pide.
    """
    if proveedor == "vicma":
        return _listo(proveedor, [_fila(INTERNO, "SIGDAN SPRAY", "86.05")])
    return _listo(proveedor, [_fila(CLAVE, "SIGDAN SPRAY", "86.05")])


def _producto(producto_id: int, clave: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=10.0,
        esta_activo=True,
        es_granel=False,
    )


def _venta(producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=HOY,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


# ====================================================================
# LA REGLA DE CADA PROVEEDOR, DICHA ANTES DE USARLA
# ====================================================================


@pytest.mark.parametrize("proveedor", LOS_DEL_EAN)
def test_nadro_levic_y_quepharma_emparejan_por_ean(proveedor):
    """Tres de los cuatro usan la regla estricta, y eso se puede preguntar.

    Que QuePharma esté aquí y no con VICMA es la decisión de este ticket: los
    dos muestran código interno, pero de VICMA se sabe que su búsqueda indexa
    el EAN y de QuePharma no (ADR 0002).
    """
    assert regla_del_proveedor(proveedor) == POR_EAN


def test_vicma_es_el_unico_que_se_acepta_por_cantidad_de_resultados():
    """La excepción es una y tiene nombre."""
    assert regla_del_proveedor("vicma") == POR_UN_SOLO_RESULTADO


def test_un_proveedor_que_nadie_conoce_cae_en_la_regla_estricta():
    """Un quinto proveedor no nace con una excepción regalada.

    Equivocarse hacia "sin dato con su motivo" cuesta un hueco visible que
    alguien completa con un clic; equivocarse hacia "este precio es el de tu
    producto" cuesta una compra mala que nadie ve. Por eso lo que no se conoce
    empareja por EAN, que es lo más estricto que hay.
    """
    assert regla_del_proveedor("un-mayorista-nuevo") == POR_EAN


# ====================================================================
# CASO 1 — EMPAREJA
# ====================================================================


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_empareja_deja_precio_y_no_deja_motivo(proveedor):
    """El caso feliz de los cuatro, cada uno con la regla que le toca."""
    elegido = emparejar(_empareja(proveedor), CLAVE)

    assert elegido.aceptado
    assert elegido.motivo is None
    assert elegido.fila is not None
    assert elegido.fila.precio == "86.05"


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_lo_que_empareja_llega_a_la_lectura_como_decimal(proveedor):
    """De la fila aceptada al `Decimal` que se congela, sin escalón intermedio."""
    lectura = leer_el_precio(_empareja(proveedor), CLAVE)

    assert lectura.precio == Decimal("86.05")
    assert lectura.motivo is None
    assert not lectura.sin_dato
    assert lectura.resultados == 1


@pytest.mark.parametrize("proveedor", ("nadro", "levic"))
def test_el_ean_elige_su_fila_aunque_lleguen_otras(proveedor):
    """NADRO y LEVIC **sí** aceptan con varias filas: el EAN desempata.

    Es la diferencia con VICMA dicha en una prueba. Un EAN de 13 dígitos
    identifica una presentación concreta, así que encontrarlo entre tres filas
    no es adivinar: es leer.
    """
    respuesta = _listo(
        proveedor,
        [
            _fila(OTRO_EAN, "SIGDAN SPRAY CAJA 60", "150.00"),
            _fila(CLAVE, "SIGDAN SPRAY CAJA 30", "86.05"),
            _fila("7501349011111", "OTRA COSA", "20.00"),
        ],
    )

    elegido = emparejar(respuesta, CLAVE)

    assert elegido.aceptado
    assert elegido.fila.precio == "86.05"
    assert elegido.fila.descripcion == "SIGDAN SPRAY CAJA 30"


def test_quepharma_tambien_empareja_el_dia_que_traiga_el_ean():
    """QuePharma va a quedar fuera seguido, **pero la puerta no está tapiada**.

    Si un día su portal devuelve el EAN en la columna de código, empareja como
    NADRO. La regla es la misma; lo que cambia es cuántas veces se cumple.
    """
    elegido = emparejar(_listo("quepharma", [_fila(CLAVE, "SIGDAN", "90.00")]), CLAVE)

    assert elegido.aceptado
    assert elegido.fila.precio == "90.00"


def test_el_ean_se_compara_por_digitos_y_no_por_el_adorno_del_portal():
    """`"750 1349 028234"` y `"7501349028234"` son el mismo código de barras.

    Los portales lo pintan con espacios o guiones. Comparar el texto crudo
    convertiría una presentación distinta de la MISMA cifra en un hueco, y un
    hueco de mentira hace que alguien vaya a teclear el precio a mano.
    """
    respuesta = _listo("nadro", [_fila("750 1349-028234", "SIGDAN", "86.05")])

    assert emparejar(respuesta, CLAVE).aceptado


def test_una_clave_que_no_es_un_ean_de_13_no_empareja_con_nada():
    """Sin EAN no hay emparejamiento, y se dice en vez de aceptar cualquier cosa.

    El glosario es explícito: **clave es el código de barras, EAN de 13
    dígitos**. Un renglón con una clave de otra cosa no tiene con qué
    emparejar, y la ruta ya se niega a consultarlo; si aun así llegara aquí,
    sale hueco con motivo y nunca precio.
    """
    respuesta = _listo("nadro", [_fila("123", "LO QUE SEA", "10.00")])

    elegido = emparejar(respuesta, "123")

    assert not elegido.aceptado
    assert elegido.motivo == NO_EMPAREJA


# ====================================================================
# CASO 2 — DOS RESULTADOS
# ====================================================================


def test_vicma_con_dos_resultados_no_da_precio():
    """La casilla literal del ticket: VICMA **únicamente** con un resultado.

    El portal muestra código interno, así que con dos filas no hay forma de
    saber cuál es el producto sin adivinar — y adivinar aquí es la caja de 60
    contra la de 30.
    """
    respuesta = _listo(
        "vicma",
        [_fila("A-1", "CAJA 30", "100.00"), _fila("A-2", "CAJA 60", "180.00")],
    )

    elegido = emparejar(respuesta, CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == VARIOS_RESULTADOS


def test_vicma_rechaza_dos_resultados_aunque_uno_traiga_el_ean_buscado():
    """"Únicamente si devuelve exactamente un resultado" es exactamente eso.

    Se consideró darle a VICMA una segunda puerta —aceptar la fila que trajera
    el EAN, aunque hubiera varias— y se descartó: el ADR 0002 no dice "y
    además", dice **únicamente**, y VICMA muestra código interno, así que un
    13 dígitos en esa columna es más raro que el caso que evitaría. Aflojarlo
    tiene que ser una decisión con su ADR, no un `or` que alguien agregó.
    """
    respuesta = _listo(
        "vicma",
        [_fila(CLAVE, "CAJA 30", "100.00"), _fila("A-2", "CAJA 60", "180.00")],
    )

    assert emparejar(respuesta, CLAVE).motivo == VARIOS_RESULTADOS


@pytest.mark.parametrize("proveedor", LOS_DEL_EAN)
def test_dos_resultados_y_ninguno_es_el_producto_es_no_empareja(proveedor):
    """El motivo que este ticket estrena. **Llegaron filas y ninguna es ésta.**

    Es distinto de `varios resultados`: ahí no se pudo elegir, aquí sí se
    pudo y la respuesta es que no está. Y es distinto de `sin resultados`: el
    portal sí encontró cosas. Las tres llevan a acciones distintas, que es lo
    único que justifica un motivo aparte.
    """
    respuesta = _listo(
        proveedor,
        [_fila("A-1", "CAJA 30", "100.00"), _fila("A-2", "CAJA 60", "180.00")],
    )

    elegido = emparejar(respuesta, CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == NO_EMPAREJA


def test_quepharma_con_codigo_interno_queda_sin_dato_y_eso_es_lo_esperado():
    """QuePharma va a quedar fuera seguido. **No es una falla: es la casilla.**

    Un hueco visible con su motivo es información; una comparación mal
    emparejada es una decisión de compra equivocada (ADR 0002).
    """
    respuesta = _listo(
        "quepharma",
        [_fila("QP-77", "SIGDAN SPRAY", "80.00"), _fila("QP-78", "SIGDAN 2", "82.00")],
    )

    lectura = leer_el_precio(respuesta, CLAVE)

    assert lectura.precio is None
    assert lectura.sin_dato
    assert lectura.motivo == NO_EMPAREJA
    assert lectura.resultados == 2


def test_dos_filas_con_el_mismo_ean_no_se_eligen_a_ciegas():
    """El EAN repetido en dos filas no desempata nada, y se dice.

    Pasa cuando un portal lista el mismo producto en dos presentaciones de
    venta —o dos almacenes— con precios distintos. Quedarse con la primera
    sería elegir por el orden en que el portal pintó la tabla.
    """
    respuesta = _listo(
        "nadro",
        [_fila(CLAVE, "SIGDAN", "86.05"), _fila(CLAVE, "SIGDAN", "91.00")],
    )

    elegido = emparejar(respuesta, CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == VARIOS_RESULTADOS


# ====================================================================
# CASO 3 — CERO RESULTADOS
# ====================================================================


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_cero_resultados_es_sin_resultados_y_no_es_no_empareja(proveedor):
    """El portal buscó y no encontró: ese producto no está en ese catálogo.

    No hay nada que hacer y el hueco es la respuesta correcta. Confundirlo con
    `no empareja` —"llegaron filas y ninguna es ésta"— mandaría a alguien a
    revisar un emparejamiento que nunca ocurrió.
    """
    elegido = emparejar(_listo(proveedor, []), CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == SIN_RESULTADOS


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_cero_resultados_no_se_ve_como_precio_cero(proveedor):
    """Regla 4 de `CLAUDE.md`, en el caso donde más fácil sería equivocarse.

    Cero resultados es "no lo tiene", no "vale cero". Un cero ganaría toda
    comparación de "el más barato" y dispararía la compra equivocada.
    """
    lectura = leer_el_precio(_listo(proveedor, []), CLAVE)

    assert lectura.precio is None
    assert lectura.precio != Decimal("0")
    assert lectura.precio_como_llego == ""
    assert lectura.sin_dato
    assert lectura.motivo == SIN_RESULTADOS


# ====================================================================
# CASO 4 — EL PROVEEDOR FALLÓ
# ====================================================================


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
@pytest.mark.parametrize(
    ("respuesta_de", "motivo"),
    [
        (lambda p: respuesta_con_error(p, "el portal no cargó"), PORTAL_SIN_CONTESTAR),
        (respuesta_con_sesion_caducada, SESION_CADUCADA),
        (respuesta_en_reconocimiento, SIN_SELECTORES),
        (respuesta_pendiente, SIN_TIEMPO),
    ],
)
def test_el_proveedor_fallo_da_su_motivo_en_los_cuatro(proveedor, respuesta_de, motivo):
    """Un proveedor caído no empareja con nada, y su motivo no lo tapa el EAN.

    Las cuatro maneras de fallar se leen igual en los cuatro proveedores: el
    emparejamiento es lo ÚLTIMO que se mira, porque sin filas no hay nada que
    emparejar y decir `no empareja` de un portal que ni contestó sería mentir
    sobre qué hay que arreglar.
    """
    elegido = emparejar(respuesta_de(proveedor), CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == motivo


@pytest.mark.parametrize("proveedor", LOS_CUATRO)
def test_un_estado_que_doyle_estrene_no_se_lee_como_no_empareja(proveedor):
    """Vocabulario nuevo del otro lado: se dice que no se conoce, no se inventa."""
    elegido = emparejar(RespuestaDeProveedor(proveedor, "reiniciando"), CLAVE)

    assert elegido.motivo == PORTAL_SIN_CONTESTAR
    assert "reiniciando" in elegido.detalle


def test_un_portal_que_dice_cuantas_encontro_y_no_manda_ninguna_no_empareja_solo():
    """`total = 1` con cero filas **no** es un precio de VICMA.

    Es el único camino por el que la regla de VICMA podría aceptar sin tener
    nada que leer: el portal dijo "encontré una" y la fila no llegó. Se trata
    como portal que no contestó —que lleva a reintentar— y nunca como una
    aceptación: no hay precio que congelar.
    """
    elegido = emparejar(_listo("vicma", [], total=1), CLAVE)

    assert not elegido.aceptado
    assert elegido.motivo == PORTAL_SIN_CONTESTAR
    assert "1" in elegido.detalle


# ====================================================================
# `total` CONTRA `len(filas)` — LA DECISIÓN DE VICMA
# ====================================================================


def test_vicma_decide_con_el_total_del_portal_y_no_con_lo_que_doyle_trajo():
    """**Manda `total`.** Doyle corta la lista en 20; el portal encontró 43.

    Con `len(filas)` el número que se compara contra 1 sería 20, y el que se
    guardaría en `resultados` —y se pintaría en la pantalla— sería un 20 que
    nadie contó: el portal encontró 43. La regla se leería igual de estricta
    por casualidad y el dato de al lado estaría mal.
    """
    respuesta = _listo(
        "vicma", [_fila(f"A-{i}", "CAJA", "10.00") for i in range(20)], total=43
    )

    elegido = emparejar(respuesta, CLAVE)

    assert elegido.motivo == VARIOS_RESULTADOS
    assert leer_el_precio(respuesta, CLAVE).resultados == 43


def test_una_lista_cortada_sin_el_ean_no_se_declara_no_empareja():
    """20 filas de 43 y el EAN no está entre ellas: **no se puede afirmar nada**.

    Decir `no empareja` —"llegaron filas y ninguna es ésta"— sería afirmar algo
    sobre las 23 que no llegaron. Sale `varios resultados`, que es lo que de
    verdad pasó: había demasiadas para decidir con lo que se trajo.
    """
    respuesta = _listo(
        "nadro", [_fila(f"75013490{i:05d}", "OTRA COSA", "10.00") for i in range(20)],
        total=43,
    )

    elegido = emparejar(respuesta, CLAVE)

    assert elegido.motivo == VARIOS_RESULTADOS
    assert "43" in elegido.detalle


def test_una_lista_completa_sin_el_ean_si_se_declara_no_empareja():
    """La otra mitad de la de arriba: 3 de 3 y ninguna es ésta.

    Aquí sí se vio la lista entera, así que `no empareja` es una afirmación
    sostenida por los datos y no una suposición.
    """
    respuesta = _listo(
        "nadro", [_fila(f"75013490{i:05d}", "OTRA COSA", "10.00") for i in range(3)]
    )

    assert emparejar(respuesta, CLAVE).motivo == NO_EMPAREJA


# ====================================================================
# EL ERROR DE MARLOWE — LA CAJA DE 60 CONTRA LA DE 30
# ====================================================================


def test_la_caja_de_60_mas_barata_por_pieza_no_se_cuela_como_precio_de_la_de_30():
    """Lo que este ticket existe para impedir, escrito como el caso que lo rompía.

    Se busca la caja de 30 y el portal devuelve **una sola fila**, la de 60, más
    barata en la etiqueta. Marlowe la habría tomado: un solo resultado, precio
    legible, nada que avisar. Con el EAN no empareja, y el hueco lo dice.
    """
    respuesta = _listo("nadro", [_fila(OTRO_EAN, "SIGDAN SPRAY CAJA 60", "60.00")])

    lectura = leer_el_precio(respuesta, CLAVE)

    assert lectura.precio is None
    assert lectura.motivo == NO_EMPAREJA
    assert lectura.resultados == 1


def test_vicma_se_acepta_a_ciegas_y_por_eso_guarda_la_evidencia():
    """**Lo que el emparejamiento NO protege, dicho aquí y no en un comentario.**

    A VICMA se le acepta el único resultado sin poder compararlo con nada: su
    portal muestra código interno. Quien garantiza que sea el producto buscado
    es el índice de VICMA, no este código. Si ese índice devolviera la caja de
    60 para el EAN de la de 30, aquí entraría un precio equivocado.

    Lo único que se puede hacer es dejar la evidencia a la vista —el código y
    la descripción del portal viajan hasta la pantalla— para que una persona lo
    cace de un vistazo. Esta prueba existe para que nadie lea el ticket 13 como
    "ya no puede pasar".
    """
    respuesta = _listo("vicma", [_fila("V-999", "SIGDAN SPRAY CAJA 60", "60.00")])

    lectura = leer_el_precio(respuesta, CLAVE)

    assert lectura.precio == Decimal("60.00")  # se acepta, y no se finge otra cosa
    assert lectura.clave_del_proveedor == "V-999"
    assert lectura.descripcion_del_proveedor == "SIGDAN SPRAY CAJA 60"


# ====================================================================
# LA CLAVE QUE MANDA ES LA QUE SE BUSCÓ
# ====================================================================


def test_congelar_empareja_contra_la_clave_que_se_busco_y_no_contra_el_eco_de_doyle():
    """La clave entra por argumento. **No se lee del `termino` que Doyle repite.**

    Son dos cosas distintas: una es lo que Continental pidió y la otra es lo
    que el otro proceso dice que le pidieron. Si Doyle devolviera un `termino`
    recortado, vacío o de otro trabajo, emparejar contra él movería la portería
    sin que nadie lo viera.
    """
    estado = EstadoDeBusqueda(
        termino="",  # Doyle no lo repitió: da igual, no es quien manda
        proveedores={
            "nadro": _listo("nadro", [_fila(CLAVE, "SIGDAN", "86.05")]),
            "levic": _listo("levic", [_fila(OTRO_EAN, "OTRA CAJA", "50.00")]),
        },
    )

    lecturas = {l.proveedor: l for l in congelar(estado, CLAVE)}

    assert lecturas["nadro"].precio == Decimal("86.05")
    assert lecturas["levic"].precio is None
    assert lecturas["levic"].motivo == NO_EMPAREJA


# ====================================================================
# LA INVARIANTE — NI PRECIO SIN FILA NI HUECO SIN MOTIVO
# ====================================================================


def _todos_los_casos():
    """Cada final posible de cada proveedor, para pasarles la misma afirmación."""
    for proveedor in LOS_CUATRO:
        yield _empareja(proveedor)
        yield _listo(proveedor, [])
        yield _listo(proveedor, [_fila(INTERNO, "CAJA 30", "100.00")])
        yield _listo(
            proveedor,
            [_fila("A-1", "CAJA 30", "100.00"), _fila("A-2", "CAJA 60", "180.00")],
        )
        yield _listo(proveedor, [_fila(OTRO_EAN, "CAJA 60", "60.00")])
        yield _listo(proveedor, [_fila(CLAVE, "CAJA 30", "no es un número")])
        yield _listo(proveedor, [], total=7)
        yield respuesta_con_error(proveedor, "el portal no cargó")
        yield respuesta_con_sesion_caducada(proveedor)
        yield respuesta_en_reconocimiento(proveedor)
        yield respuesta_pendiente(proveedor)
        yield RespuestaDeProveedor(proveedor, "algo-que-doyle-estrene")


def test_ninguna_regla_acepta_una_fila_y_un_motivo_a_la_vez():
    """O hay fila aceptada o hay motivo de rechazo. **Nunca las dos, nunca ninguna.**

    Es lo que hace que un precio faltante sea información y no un `NULL` mudo,
    y se comprueba sobre todos los caminos a la vez porque lo que no puede
    existir es **un camino** que devuelva las dos cosas o ninguna.
    """
    for respuesta in _todos_los_casos():
        elegido = emparejar(respuesta, CLAVE)
        assert (elegido.fila is None) == (elegido.motivo is not None), (
            f"{respuesta.proveedor}/{respuesta.estado!r} devolvió fila y motivo "
            "a la vez, o ninguno de los dos."
        )
        if elegido.motivo is not None:
            assert elegido.motivo in MOTIVOS


def test_ningun_hueco_del_emparejamiento_llega_sin_motivo_ni_con_un_cero():
    """La misma invariante una capa más arriba, y el cero prohibido con ella."""
    for respuesta in _todos_los_casos():
        lectura = leer_el_precio(respuesta, CLAVE)
        assert (lectura.precio is None) == (lectura.motivo is not None)
        assert lectura.precio is None or lectura.precio > 0


# ====================================================================
# HASTA LA FILA GUARDADA Y HASTA LA PANTALLA
# ====================================================================


def test_no_empareja_se_guarda_en_la_tabla_y_ya_no_es_un_motivo_que_nadie_escribe(
    cliente, almacen, almacenamiento, doyle
):
    """El motivo que el ticket 12 dejó reservado **ahora lo escribe alguien**.

    Camino entero: QuePharma contesta con su código interno, el emparejamiento
    lo rechaza, y la fila queda en `pedidos.precio_de_proveedor` con
    `no empareja` y su `resultados`.

    **Lo que la fila rechazada NO guarda es el código y la descripción de lo que
    el portal mostró**, y es una decisión, no un olvido: esas dos columnas
    significan "la fila **elegida**" —son la evidencia de que se comparó el
    mismo producto— y llenarlas con una fila que se descartó las convertiría en
    una mentira. Alguien leyendo la tabla vería `QP-77` al lado del renglón y
    entendería que se emparejó con eso. Lo que sí se guarda es el `detalle`, que
    dice cuántas filas llegaron y que ninguna traía el EAN.
    """
    almacen.catalogo_en_memoria = [_producto(1, CLAVE)]
    almacen.ventas_en_memoria = [_venta(1, 3)]
    doyle.resultados_por_termino[CLAVE] = {
        "quepharma": _listo("quepharma", [_fila("QP-77", "SIGDAN SPRAY", "80.00")])
    }

    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/precio")

    guardados = almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)
    assert [p.motivo for p in guardados] == [NO_EMPAREJA]
    assert guardados[0].precio is None
    assert guardados[0].resultados == 1
    assert guardados[0].clave_del_proveedor == ""
    assert guardados[0].descripcion_del_proveedor == ""
    assert CLAVE in guardados[0].detalle


def test_lo_que_no_empareja_viaja_a_la_pantalla_como_hueco_y_nunca_como_cero():
    """Quinta casilla: `sin dato` ni cero, ni vacío, ni "más caro".

    Lo que sale al navegador es `precio: null` con `sin_dato` en cierto y su
    motivo al lado. **Ni un `0`, ni una cadena vacía**: un cero ganaría la
    comparación del ticket 14 y un vacío se leería como "todavía no se
    consultó".
    """
    lectura = leer_el_precio(
        _listo("quepharma", [_fila("QP-77", "SIGDAN SPRAY", "80.00")]), CLAVE
    )

    (json,) = lecturas_como_json([_con_instante(lectura)])

    assert json["precio"] is None
    assert json["sin_dato"] is True
    assert json["motivo"] == NO_EMPAREJA
    assert json["nombre"] == "QuePharma"


def _con_instante(lectura):
    """La lectura como la devuelve el almacén: la misma, con su `consultado_en`.

    `lecturas_como_json` pinta lo **guardado**, y lo guardado tiene el instante
    que puso la base. Se arma aquí en vez de inventar un doble para que la
    prueba mire exactamente el objeto que la pantalla recibe.
    """
    from continental.almacenamiento import PrecioDeProveedor

    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=lectura.proveedor,
        consultado_en=dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC),
        precio_como_llego=lectura.precio_como_llego,
        precio=lectura.precio,
        existencia_como_llego=lectura.existencia_como_llego,
        existencia=lectura.existencia,
        motivo=lectura.motivo,
        detalle=lectura.detalle,
        clave_del_proveedor=lectura.clave_del_proveedor,
        descripcion_del_proveedor=lectura.descripcion_del_proveedor,
        resultados=lectura.resultados,
    )
