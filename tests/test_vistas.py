"""El interruptor entre las dos vistas, y los renglones que nunca se esconden.

El ticket 06 entero. Lo que estas pruebas cuidan por encima de todo es **una
sola cosa**: que un producto `sin clasificar` siga apareciendo en las dos
vistas. 688 de 3,429 artículos no tienen anaquel (medido al 2026-09); si el
interruptor los filtra por no encajar en "medicamentos y botica", desaparece
mercancía de la lista sin que nadie se entere, y el encargado descubre el
faltante frente al anaquel vacío.

`test_un_producto_sin_clasificar_aparece_en_las_dos_vistas` es la que se pone
roja el día que alguien "arregle" el filtro para que la vista de medicamentos
quede limpia. Está escrita en tres alturas a propósito, porque la tentación
llega por tres caminos distintos:

1. Sobre `VISTAS`, que es donde vive la regla.
2. Sobre el JSON de la API, que es lo que la pantalla recibe.
3. Sobre los renglones ya filtrados con la regla que la pantalla aplica, que es
   lo que el encargado acaba viendo.

`test_la_pantalla_no_reinventa_la_regla_de_que_esconde_cada_vista` es su
gemela: el filtro se aplica en el navegador, así que hay que impedir que el
JavaScript escriba su propia lista de clasificaciones. La regla viaja como
dato desde Python; el JavaScript solo la obedece.

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from conftest import pantalla_servida
from continental.almacen import LineaDeVenta, Producto
from continental.clasificacion import ABARROTE, MEDICAMENTO, SIN_CLASIFICAR
from continental.vistas import VISTAS, Vista

RUTA = "/api/pedido-sugerido"
PORTADA = Path(__file__).resolve().parent.parent / "src" / "continental" / "web"

MEDICAMENTOS = "medicamentos-y-botica"
TODO = "todo-lo-vendido"


# ------------------------------------------------------- las dos vistas


def test_el_interruptor_ofrece_las_dos_vistas_con_el_nombre_de_la_historia_9():
    """Los nombres son los del spec, no sinónimos inventados al pintar.

    "Medicamentos y botica" y "Todo lo vendido" (historia 9). Viven en Python,
    al lado de la regla que cada una aplica, para que el nombre y lo que el
    nombre promete no puedan divergir: una vista que se llamara solo
    "Medicamentos" y siguiera trayendo botica mentiría sobre los dos anaqueles
    de material de curación que sí se le compran al mismo proveedor.
    """
    assert [v.clave for v in VISTAS] == [MEDICAMENTOS, TODO]
    assert [v.nombre for v in VISTAS] == ["Medicamentos y botica", "Todo lo vendido"]


def test_un_producto_sin_clasificar_aparece_en_las_dos_vistas(cliente, almacen):
    """**La prueba que no puede fallar.** 688 de 3,429 artículos sin anaquel.

    Si alguien quita `sin clasificar` de la vista de medicamentos para que
    quede "limpia", esto se pone rojo en las tres alturas: la regla, el JSON y
    la lista filtrada. Un producto que desaparece de la lista por no tener
    anaquel es mercancía que va a faltar sin que nadie se entere (regla 4 de
    CLAUDE.md), y el dato que falta —el anaquel— es justo el que nadie va a ir
    a capturar si el hueco no se ve.
    """
    # 1. La regla, donde vive.
    for vista in VISTAS:
        assert SIN_CLASIFICAR in vista.clasificaciones, vista.clave

    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "SABRITAS", anaquel="CANASTA"),
        _producto(3, "7501000000003", "MISTERIO", anaquel="", categoria="GRUP4"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3)
    ]
    cuerpo = cliente.get(RUTA).json()

    # 2. El JSON que la pantalla recibe.
    por_clave = {v["clave"]: v for v in cuerpo["vistas"]}
    assert SIN_CLASIFICAR in por_clave[MEDICAMENTOS]["clasificaciones"]
    assert SIN_CLASIFICAR in por_clave[TODO]["clasificaciones"]

    # 3. La lista que el encargado acaba viendo, con la regla ya aplicada.
    for clave in (MEDICAMENTOS, TODO):
        visibles = _renglones_de(cuerpo, clave)
        assert 3 in [r["producto_id"] for r in visibles], clave
        assert [r["clasificacion"] for r in visibles].count(SIN_CLASIFICAR) == 1


def test_en_la_vista_de_medicamentos_no_aparecen_abarrotes(cliente, almacen):
    """Lo único que el interruptor esconde: el abarrote.

    Es la historia 9 completa —"para no ver refrescos y botanas cuando estoy
    armando el pedido de la farmacia"— y el límite exacto de lo que se puede
    esconder. Botica entra como medicamento porque se le compra a los mismos
    proveedores (CONTEXT.md), y el `sin clasificar` se queda porque no hay
    evidencia de que sea abarrote.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "VENDA ELASTICA", anaquel="BOTICA 2"),
        _producto(3, "7501000000003", "REFRESCO", anaquel="REFRIGERADOR"),
        _producto(4, "7501000000004", "SABRITAS", anaquel="CANASTA"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3, 4)
    ]

    cuerpo = cliente.get(RUTA).json()
    visibles = _renglones_de(cuerpo, MEDICAMENTOS)

    assert ABARROTE not in [r["clasificacion"] for r in visibles]
    assert [r["producto_id"] for r in visibles] == [1, 2]  # la venda se queda
    # Y la otra vista no esconde nada: los cuatro siguen ahí.
    assert len(_renglones_de(cuerpo, TODO)) == 4


def test_la_vista_de_todo_lo_vendido_no_esconde_ni_una_clasificacion():
    """"Todo lo vendido" tiene que traer las tres respuestas posibles.

    Si mañana `clasificacion.py` agrega una cuarta —y podría: el día que haya
    una lista de categorías de medicamento—, esta prueba se pone roja y
    obliga a decidir en qué vista entra, en vez de dejar que se caiga de las
    dos en silencio.
    """
    todo = next(v for v in VISTAS if v.clave == TODO)

    assert set(todo.clasificaciones) == {MEDICAMENTO, ABARROTE, SIN_CLASIFICAR}


def test_la_api_manda_la_lista_completa_y_el_interruptor_no_le_pide_otra(
    cliente, almacen
):
    """El filtro vive en el navegador: una lectura, una lista, dos maneras de verla.

    La ruta no acepta un parámetro de vista **a propósito** (el porqué está en
    la docstring de `vistas.py`). Si alguien le agrega uno, el JSON dejaría de
    traer los cuatro renglones y esto se pone rojo.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "SABRITAS", anaquel="CANASTA"),
        _producto(3, "7501000000003", "MISTERIO", anaquel=""),
        _producto(4, "7501000000004", "VENDA", anaquel="BOTICA 1"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3, 4)
    ]

    # Con parámetro y sin él sale lo mismo: hoy la ruta no lo mira.
    completa = cliente.get(RUTA).json()["renglones"]
    con_parametro = cliente.get(RUTA, params={"vista": MEDICAMENTOS}).json()["renglones"]

    assert len(completa) == 4
    assert [r["producto_id"] for r in con_parametro] == [
        r["producto_id"] for r in completa
    ]


# ------------------------------------------- cuántos quedaron sin clasificar


def test_la_lista_dice_cuantos_renglones_quedaron_sin_clasificar(cliente, almacen):
    """Historia 12: para decidir si vale la pena ponerles anaquel en SICAR.

    Se cuenta en Python, junto a la lista, por lo mismo que `sin_catalogo`: un
    hueco que se cuenta es información; uno que se calla es una lista que
    miente por omisión.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "MISTERIO", anaquel=""),
        _producto(3, "7501000000003", "OTRO MISTERIO", anaquel="PASILLO 7"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3, 99)
    ]

    cuerpo = cliente.get(RUTA).json()

    # Los dos sin anaquel más el que no está en el catálogo: de ése tampoco hay
    # anaquel que mirar.
    assert cuerpo["sin_clasificar"] == 3
    assert cuerpo["sin_catalogo"] == 1  # son conteos distintos, no el mismo


def test_el_conteo_de_sin_clasificar_no_cambia_al_mover_el_interruptor(
    cliente, almacen
):
    """El conteo es de la lista completa, y por eso vale lo mismo en las dos vistas.

    No es una coincidencia que se pueda decir de las dos maneras: **vale lo
    mismo precisamente porque `sin clasificar` nunca se esconde**. El día que
    el número de una vista se separe del de la otra, la causa solo puede ser
    que alguien empezó a filtrar los sin anaquel — así que esta prueba es el
    mismo cinturón de arriba, mirado desde el conteo.

    Se muestra el de la lista completa porque la pregunta que responde
    —"¿vale la pena ponerles anaquel en SICAR?"— es sobre el catálogo, no
    sobre lo que hay en pantalla en este momento. Un número que baja al mover
    un interruptor se leería como que hay menos productos sin anaquel.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1"),
        _producto(2, "7501000000002", "SABRITAS", anaquel="CANASTA"),
        _producto(3, "7501000000003", "MISTERIO", anaquel=""),
        _producto(4, "7501000000004", "OTRO MISTERIO", anaquel="PASILLO 7"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=n, cantidad=1) for n in (1, 2, 3, 4)
    ]

    cuerpo = cliente.get(RUTA).json()
    en_vista = {
        clave: sum(
            1
            for r in _renglones_de(cuerpo, clave)
            if r["clasificacion"] == SIN_CLASIFICAR
        )
        for clave in (MEDICAMENTOS, TODO)
    }

    assert cuerpo["sin_clasificar"] == 2
    assert en_vista[MEDICAMENTOS] == en_vista[TODO] == cuerpo["sin_clasificar"]


def test_una_lista_sin_huecos_cuenta_cero_y_no_finge_un_aviso(cliente, almacen):
    """Cero es cero: sin productos sin anaquel, no hay nada que ir a capturar."""
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", anaquel="PATENTE 1")
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 1)]

    assert cliente.get(RUTA).json()["sin_clasificar"] == 0


# --------------------------------------------------------------- la pantalla


def test_la_pantalla_trae_el_interruptor_con_los_dos_nombres(cliente):
    """El ticket pide una pantalla, no solo un JSON.

    La portada es HTML+JS a mano, sin framework, sin npm y sin CDN —atlas es un
    Athlon II X4 de 2010—, así que lo que se comprueba barato es que el
    interruptor y sus dos nombres sigan ahí. Los nombres se pintan desde el
    JSON, así que lo que se busca en el archivo es el armado, no el texto.
    """
    portada = pantalla_servida(cliente)

    assert 'id="vistas"' in portada
    assert "cuerpo.vistas" in portada or "datos.vistas" in portada
    # Y la pantalla sigue haciendo una sola consulta del pedido: el interruptor
    # no vuelve a preguntarle al almacén.
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
    #
    # La del ticket 27: recibir a mano —o corregir cuántas llegaron—, que
    # también vuelve a `cargarPedido`. Recibir parcial con la evidencia NO
    # suma: reusa la llamada de confirmar y rechazar.
    #
    # La del ticket 29: `/api/doyle`, que pregunta si Doyle contesta APARTE de
    # la lista y al mismo tiempo —la lista no depende de Doyle, y un Doyle
    # colgado no la puede hacer esperar—. No vuelve a pedir la lista.
    assert portada.count("fetch('/api/") == 16
    assert portada.count("fetch('/api/pedido-sugerido')") == 1


def test_la_pantalla_recuerda_la_eleccion_y_aguanta_un_localStorage_roto(cliente):
    """Hoy no hay base de datos ni sesión de usuario: la memoria es del navegador.

    Se comprueba sobre el código porque es justo lo que un resultado no
    distingue: una pantalla sin `try`/`catch` alrededor de `localStorage` se ve
    idéntica hasta que alguien la abre en una ventana privada o con las cookies
    bloqueadas, y ahí el `localStorage` **lanza al leerlo** y la pantalla se
    queda en blanco. Con el pedido del día, en blanco significa que no se hace.

    El otro caso es la basura: una clave con un valor que ya no existe —o que
    alguien editó a mano— no puede dejar la lista sin ninguna vista activa.
    """
    portada = pantalla_servida(cliente)

    assert "localStorage" in portada
    assert portada.count("try {") >= 2  # leer y escribir, cada uno con el suyo
    assert "es_la_de_omision" in portada  # el respaldo cuando la clave no casa


def test_la_pantalla_no_reinventa_la_regla_de_que_esconde_cada_vista(cliente):
    """El filtro se aplica en el navegador; la **regla** sigue viviendo en Python.

    La diferencia es todo el ticket. Si el JavaScript escribiera su propia
    lista —`r.clasificacion !== 'abarrote'`—, la regla viviría en dos lugares
    y solo uno estaría probado: el día que alguien quisiera "limpiar" la vista
    de medicamentos, tocaría el archivo que ninguna prueba mira. Por eso el
    JavaScript recibe las clasificaciones de cada vista como dato y solo
    pregunta si la del renglón está en la lista.
    """
    portada = pantalla_servida(cliente)

    assert "clasificaciones.includes" in portada
    # Ni una clasificación escrita a mano en el filtro. `'medicamento'` sí
    # aparece, pero para la marca del renglón (ticket 05), no para esconder.
    assert "'abarrote'" not in portada
    assert '"abarrote"' not in portada


# ------------------------------------------------------- la regla, directo


def test_una_vista_es_un_nombre_y_una_lista_de_clasificaciones_y_nada_mas():
    """`Vista` no sabe filtrar, no lee archivos y no toca el almacén.

    Es un dato: una clave, un nombre y qué clasificaciones deja ver. El día
    que alguien le meta una consulta adentro "para contar los renglones de la
    vista", la discusión ocurre aquí y no tres módulos más abajo.
    """
    vista = Vista(clave="x", nombre="X", clasificaciones=(MEDICAMENTO,))

    assert vista.es_la_de_omision is False
    assert sum(1 for v in VISTAS if v.es_la_de_omision) == 1


# ------------------------------------------------------------------ ayudas


def _renglones_de(cuerpo: dict, clave_de_vista: str) -> list[dict]:
    """Los renglones que la pantalla pinta en esa vista, con la regla del JSON.

    Aplica exactamente lo que hace el JavaScript —quedarse con los renglones
    cuya clasificación está en la lista de la vista— y no una copia de la
    regla: la lista de clasificaciones sale del cuerpo de la respuesta. Si
    Python empezara a mandar otra cosa, estas pruebas lo verían.
    """
    vista = next(v for v in cuerpo["vistas"] if v["clave"] == clave_de_vista)
    return [
        r for r in cuerpo["renglones"] if r["clasificacion"] in vista["clasificaciones"]
    ]


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
