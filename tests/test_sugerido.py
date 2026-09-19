"""El pedido sugerido del día: qué comprar, de qué ventas salió, y sin mirar el reloj.

Se prueba **por la API** porque es lo que el ticket 03 pide: el criterio no es
"la función devuelve una lista", es "el encargado abre Continental y ve la
lista". Una prueba que llamara solo a `calcular_pedido_sugerido` pasaría en
verde con la ruta rota, con el borde mal cableado o con la pantalla vacía.
`test_el_calculo_es_una_funcion_pura_que_recibe_ventas_y_catalogo` es la única
que la llama directo, y es a propósito: comprueba justo lo que por HTTP no se
ve, que la función no necesita almacén, conexión ni configuración.

La prueba que más vale de este archivo es
`test_la_ventana_se_ancla_en_el_ultimo_dato_y_nunca_en_el_reloj`: usa un
almacén cuyo último dato es de hace años, así que si alguien ancla la ventana
en `date.today()`, la lista sale vacía y esto se pone rojo. Es la trampa que a
farmacia-data le costó 11.7 puntos de crecimiento inventados —el Postgres del
contenedor corre en UTC y su `current_date` puede ir dos días adelante del
último dato—.

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import sqlalchemy

from continental.almacen import LineaDeVenta, Producto
from continental.sugerido import calcular_pedido_sugerido

RUTA = "/api/pedido-sugerido"


# ------------------------------------------------ la lista y sus cantidades


def test_hay_un_renglon_por_producto_vendido_con_la_cantidad_que_salio(
    cliente, almacen
):
    """El criterio del ticket: reposición 1 a 1, "se vendieron tres, se piden tres".

    Es aritmética que el encargado puede verificar de un vistazo, y eso importa
    más que ser óptima: una lista que no se entiende no se usa (ADR 0002).
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL 500MG TAB C/10"),
        _producto(2, "7501000000002", "NAPROXENO 250MG TAB C/20"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=3),
        _venta(dt.date(2026, 9, 16), producto_id=2, cantidad=1),
    ]

    cuerpo = cliente.get(RUTA).json()
    renglones = {r["clave"]: r for r in cuerpo["renglones"]}

    assert cuerpo["ok"] is True
    assert len(cuerpo["renglones"]) == 2
    assert renglones["7501000000001"]["cantidad_propuesta"] == 3
    assert renglones["7501000000001"]["descripcion"] == "PARACETAMOL 500MG TAB C/10"
    assert renglones["7501000000002"]["cantidad_propuesta"] == 1


def test_un_producto_vendido_en_dos_tickets_del_dia_es_un_solo_renglon(
    cliente, almacen
):
    """`fct_ventas` tiene grano ticket × artículo: el mismo producto aparece una
    vez por ticket. Un renglón por ticket sería pedir el mismo producto dos
    veces en la misma lista.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PARACETAMOL")]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=2),
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=4),
    ]

    renglones = cliente.get(RUTA).json()["renglones"]

    assert len(renglones) == 1
    assert renglones[0]["cantidad_propuesta"] == 6


# -------------------------------------------------- de qué fecha salió esto


def test_la_lista_dice_de_que_fecha_de_ventas_salio(cliente, almacen):
    """Historia 7 del spec: "para saber si estoy viendo datos de ayer o del
    viernes pasado". Sin esta fecha, una lista armada con datos viejos se lee
    igual que una recién hecha.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PARACETAMOL")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 3)]

    assert cliente.get(RUTA).json()["fecha_de_ventas"] == "2026-09-16"


def test_la_ventana_se_ancla_en_el_ultimo_dato_y_nunca_en_el_reloj(cliente, almacen):
    """La trampa heredada, en forma de prueba que se pone roja sola.

    El último dato de este almacén es de 2024: si alguien ancla la ventana en
    `date.today()` —o en el `current_date` del Postgres del contenedor, que
    corre en UTC y puede ir dos días adelante— la consulta devuelve cero filas
    y la lista sale vacía, que es exactamente la falla silenciosa que
    farmacia-data pagó con 11.7 puntos de crecimiento inventados.

    De paso comprueba la otra mitad: hoy la ventana es **el último día con
    datos**, así que lo del día anterior no entra. La acumulación desde el
    corte es el ticket 09.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL"),
        _producto(2, "7501000000002", "NAPROXENO"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2024, 3, 4), producto_id=2, cantidad=9),  # el día anterior
        _venta(dt.date(2024, 3, 5), producto_id=1, cantidad=3),  # el último con datos
    ]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["fecha_de_ventas"] == "2024-03-05"
    assert cuerpo["fecha_de_ventas"] != dt.date.today().isoformat()
    assert [r["clave"] for r in cuerpo["renglones"]] == ["7501000000001"]


def test_el_calculo_no_menciona_el_reloj_en_ninguna_parte():
    """El cinturón del criterio de arriba, sobre el código en vez del resultado.

    La prueba de comportamiento solo se pone roja si el reloj **cambia** el
    resultado. Un `date.today()` colado en una rama que hoy no se recorre
    —"si no hay ventas, usa hoy"— pasaría en verde y mordería en producción.
    Esto lo caza al leer el archivo.
    """
    raiz = Path(__file__).resolve().parent.parent / "src" / "continental"
    for nombre in ("sugerido.py", "web/app.py"):
        fuente = (raiz / nombre).read_text(encoding="utf-8")
        # Se miran las llamadas, no la palabra: `dt.date` como anotación de
        # tipo es legítima y está por todos lados.
        for prohibida in ("date.today(", "datetime.now(", "utcnow(", "time.time("):
            assert prohibida not in fuente, (
                f"{nombre} mira el reloj con {prohibida!r}. Todo se ancla en "
                "max(fecha) del almacén: el Postgres del contenedor corre en "
                "UTC y su current_date puede ir dos días adelante del dato."
            )


# ----------------------------------------- lo que no encaja, no desaparece


def test_un_producto_vendido_que_no_esta_en_el_catalogo_se_ve_y_se_cuenta(
    cliente, almacen
):
    """Regla 4 de CLAUDE.md: falla ruidoso, nunca en silencio.

    Se vendió, así que hay que reponerlo. Descartarlo por no encontrarlo en
    `dim_producto` sería mercancía que va a faltar sin que nadie se entere
    —el mismo daño que los 688 productos sin anaquel, que por eso se muestran
    marcados—. El renglón aparece, dice que no está en el catálogo, y el total
    se cuenta aparte para que se pueda arreglar en SICAR.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PARACETAMOL")]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=3),
        _venta(dt.date(2026, 9, 16), producto_id=99, cantidad=2),
    ]

    cuerpo = cliente.get(RUTA).json()
    huerfano = next(r for r in cuerpo["renglones"] if r["producto_id"] == 99)

    assert cuerpo["sin_catalogo"] == 1
    assert huerfano["esta_en_el_catalogo"] is False
    assert huerfano["cantidad_propuesta"] == 2
    assert "99" in huerfano["descripcion"]  # se dice cuál es, no "sin nombre"
    assert huerfano["clave"] == ""  # sin clave inventada: no empareja con nadie


def test_una_cantidad_de_granel_se_redondea_hacia_arriba_y_dice_lo_vendido(
    cliente, almacen
):
    """`fct_ventas.cantidad` no siempre es entera: hay 5 artículos a granel.

    A un proveedor no se le piden 2.5 piezas. Se redondea **hacia arriba**
    —hacia abajo sería reponer menos de lo que salió, en silencio— y el renglón
    sigue diciendo cuánto se vendió de verdad, para que la propuesta se pueda
    verificar de un vistazo (historia 5 del spec).
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "ALCOHOL GRANEL")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 2.5)]

    renglon = cliente.get(RUTA).json()["renglones"][0]

    assert renglon["piezas_vendidas"] == 2.5
    assert renglon["cantidad_propuesta"] == 3


def test_la_suma_de_granel_no_pide_una_pieza_de_mas_por_un_float():
    """1.1 + 2.2 + 0.7 da 4.000000000000001 en coma flotante.

    Redondear hacia arriba sin más propondría **5** piezas de algo de lo que
    salieron 4: un error que nadie sabría explicar mirando el ticket.

    Esta va directo a la función y no por la API, al revés que sus vecinas: es
    aritmética de coma flotante, no un criterio del ticket, y pasarla por HTTP
    solo le agregaría ~20 ms al suite sin cubrir nada que las otras no cubran.
    """
    pedido = calcular_pedido_sugerido(
        ventas=[
            _venta(dt.date(2026, 9, 16), 1, 1.1),
            _venta(dt.date(2026, 9, 16), 1, 2.2),
            _venta(dt.date(2026, 9, 16), 1, 0.7),
        ],
        catalogo=[_producto(1, "7501000000001", "ALCOHOL GRANEL")],
    )

    assert pedido.renglones[0].cantidad_propuesta == 4


# ------------------------------------------------ el vacío y el hueco, aparte


def test_un_almacen_sin_una_sola_venta_lo_dice_y_no_finge_una_lista(cliente):
    """Un día sin ventas existe de verdad: la farmacia cierra los domingos y no
    hay ni una venta en 33 meses. Se distingue del fallo de lectura porque
    `ok` sigue siendo verdadero y la fecha es nula, no porque la lista esté
    vacía —eso es lo que las dos tienen en común—.
    """
    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["fecha_de_ventas"] is None
    assert cuerpo["renglones"] == []


def test_el_almacen_caido_es_un_hueco_con_motivo_y_sin_cadena_de_conexion(
    cliente, almacen
):
    """Reglas 4 y 5 de CLAUDE.md sobre la ruta que el encargado abre cada día.

    Una lista vacía por falla se lee "hoy no se vendió nada" y el pedido del
    día no se hace (historia 54). Y el motivo que viaja es el TIPO de la
    falla: un `str(exc)` de SQLAlchemy lleva la cadena de conexión con
    contraseña, y esto corre detrás de un túnel.
    """
    almacen.falla = sqlalchemy.exc.OperationalError(
        "select 1", {}, Exception("connection to 127.0.0.1 failed: password=SECRETO")
    )

    respuesta = cliente.get(RUTA)
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["ok"] is False
    assert cuerpo["detalle"]  # un hueco con su motivo, nunca vacío
    assert "SECRETO" not in respuesta.text
    assert "password" not in respuesta.text


# --------------------------------------------------------------- la pantalla


def test_la_pantalla_trae_la_lista_con_clave_descripcion_y_cantidad(cliente):
    """El ticket pide una pantalla, no solo un JSON.

    La portada es HTML+JS a mano, sin framework ni build —atlas es un Athlon II
    X4 de 2010—, así que lo que se puede comprobar barato es que la sección, la
    consulta y los tres encabezados sigan ahí. Si alguien construye la API y se
    olvida de la pantalla, esto se pone rojo.
    """
    portada = cliente.get("/").text

    assert "Pedido sugerido" in portada
    assert RUTA in portada
    for encabezado in (">Clave<", ">Producto<", ">Cantidad a pedir<"):
        assert encabezado in portada, f"falta el encabezado {encabezado}"


# ------------------------------------------------------- la función, directo


def test_el_calculo_es_una_funcion_pura_que_recibe_ventas_y_catalogo():
    """Lo único que por HTTP no se ve: que no haga falta nada más.

    Sin almacén, sin conexión y sin configuración —dos listas entran, un
    pedido sugerido sale—. El día que alguien le pase el almacén "para leer
    una cosita más", esto deja de llamarse igual y la discusión ocurre aquí y
    no tres módulos más abajo.
    """
    pedido = calcular_pedido_sugerido(
        ventas=[_venta(dt.date(2026, 9, 16), 1, 3)],
        catalogo=[_producto(1, "7501000000001", "PARACETAMOL")],
    )

    assert pedido.fecha_de_ventas == dt.date(2026, 9, 16)
    assert pedido.renglones[0].cantidad_propuesta == 3
    assert pedido.sin_catalogo == 0

    # Dos listas vacías no son un error: son un domingo.
    assert calcular_pedido_sugerido(ventas=[], catalogo=[]).fecha_de_ventas is None


def test_el_orden_es_estable_y_legible_mientras_llega_el_de_urgencia():
    """El orden por urgencia es el ticket 04. Hasta entonces, alfabético.

    Se prueba porque "sin orden definido" en la práctica significa "el orden en
    que Python recorrió un diccionario", y eso cambia bajo los pies de quien
    lea la pantalla dos días seguidos.
    """
    pedido = calcular_pedido_sugerido(
        ventas=[
            _venta(dt.date(2026, 9, 16), 1, 1),
            _venta(dt.date(2026, 9, 16), 2, 1),
            _venta(dt.date(2026, 9, 16), 3, 1),
        ],
        catalogo=[
            _producto(1, "7501000000001", "NAPROXENO"),
            _producto(2, "7501000000002", "AMOXICILINA"),
            _producto(3, "7501000000003", "PARACETAMOL"),
        ],
    )

    assert [r.descripcion for r in pedido.renglones] == [
        "AMOXICILINA",
        "NAPROXENO",
        "PARACETAMOL",
    ]


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


def _producto(producto_id: int, clave: str, descripcion: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=descripcion,
        categoria="GRUP4",
        departamento="MEDICAMENTO",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=4,
        esta_activo=True,
        es_granel=False,
    )
