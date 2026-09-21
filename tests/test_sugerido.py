"""El pedido sugerido del día: qué comprar, de qué ventas salió, y sin mirar el reloj.

Se prueba **por la API** porque es lo que el ticket 03 pide: el criterio no es
"la función devuelve una lista", es "el encargado abre Continental y ve la
lista". Una prueba que llamara solo a `calcular_pedido_sugerido` pasaría en
verde con la ruta rota, con el borde mal cableado o con la pantalla vacía.
`test_el_calculo_es_una_funcion_pura_que_recibe_ventas_y_catalogo` es la única
que la llama directo, y es a propósito: comprueba justo lo que por HTTP no se
ve, que la función no necesita almacén, conexión ni configuración.

Del ticket 04, la que más vale es
`test_la_lista_va_ordenada_por_urgencia_y_nada_se_filtra`: comprueba el orden y,
en la misma corrida, que los cinco renglones sigan ahí. Si alguien "limpia" la
lista escondiendo lo que tiene anaquel lleno —que es la lógica de la tarjeta O2
de Metabase, la que el dueño pidió explícitamente no usar como fuente del
pedido—, ese `== 5` se pone rojo.

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

import dataclasses
import datetime as dt
from pathlib import Path

import sqlalchemy

from conftest import pantalla_servida
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

    De paso comprueba la otra mitad: **sin un cierre anterior la ventana son los
    días de `pedido.dias_primera_vez`**, que desde el 2026-09-20 es **uno**.
    Entra el último día con datos y nada más — ni el día anterior ni el de hace
    un mes. El extremo derecho sigue siendo el último día con datos, y de ahí
    cuelga todo lo demás. La acumulación desde el corte tiene su propio
    archivo, `test_acumulacion.py`.

    **Y sigue probando el anclaje igual de bien con la ventana corta**, que era
    la duda al acortarla: si alguien anclara en `date.today()`, la ventana sería
    `[hoy, hoy]` de 2026 y no encontraría ni una venta de 2024. La lista saldría
    vacía y el `assert` de abajo caería.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL"),
        _producto(2, "7501000000002", "NAPROXENO"),
        _producto(3, "7501000000003", "AMOXICILINA"),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2024, 2, 5), producto_id=3, cantidad=7),  # un mes antes: fuera
        _venta(dt.date(2024, 3, 4), producto_id=2, cantidad=9),  # el día anterior: fuera
        _venta(dt.date(2024, 3, 5), producto_id=1, cantidad=3),  # el último con datos
    ]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["fecha_de_ventas"] == "2024-03-05"
    assert cuerpo["fecha_de_ventas"] != dt.date.today().isoformat()
    assert sorted(r["clave"] for r in cuerpo["renglones"]) == ["7501000000001"]


def test_el_calculo_no_menciona_el_reloj_en_ninguna_parte():
    """El cinturón del criterio de arriba, sobre el código en vez del resultado.

    La prueba de comportamiento solo se pone roja si el reloj **cambia** el
    resultado. Un `date.today()` colado en una rama que hoy no se recorre
    —"si no hay ventas, usa hoy"— pasaría en verde y mordería en producción.
    Esto lo caza al leer el archivo.

    `almacenamiento.py` entra a la lista con el ticket 09: ahí vive
    `ventana_de_reposicion`, que decide desde qué día se repone. Un "si no hay
    corte, usa hoy menos siete" sería la misma trampa con otro nombre, y en un
    almacén cuyo último dato es de 2024 dejaría la lista vacía sin un error que
    ver. Los instantes con zona de `armado_en` y `cerrado_en` no se cazan aquí
    porque no son fechas y no salen de Python: los pone `now()` en el servidor
    que guarda la fila.
    """
    raiz = Path(__file__).resolve().parent.parent / "src" / "continental"
    for nombre in ("sugerido.py", "almacenamiento.py", "web/app.py"):
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
    consulta y los cinco encabezados sigan ahí. Si alguien construye la API y
    se olvida de la pantalla, esto se pone rojo.
    """
    portada = pantalla_servida(cliente)

    assert "Pedido sugerido" in portada
    assert RUTA in portada
    for encabezado in (
        ">Clave<",
        ">Producto<",
        ">Cantidad a pedir<",
        ">Existencia<",
        ">Días de cobertura<",
    ):
        assert encabezado in portada, f"falta el encabezado {encabezado}"


def test_la_pantalla_pinta_la_existencia_del_renglon_y_no_la_vuelve_a_buscar(cliente):
    """La existencia y la cobertura que se ven son las del renglón.

    Se comprueba sobre el código de la pantalla y no sobre el resultado porque
    es justo lo que un resultado no distingue: una pantalla que volviera a
    pedir el catálogo se vería igual hoy y mostraría otro número mañana, con
    la lista ya propuesta diciendo una cosa y el renglón guardado otra. La
    pantalla lee `r.existencia` y `r.dias_de_cobertura`, y la única consulta
    del pedido es la de la ruta.
    """
    portada = pantalla_servida(cliente)

    assert "r.existencia" in portada
    assert "r.dias_de_cobertura" in portada
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
    assert portada.count("fetch('/api/") == 15
    assert portada.count("fetch('/api/pedido-sugerido')") == 1


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


# --------------------------- existencia, cobertura y el orden por urgencia
#
# El ticket 04 entero. Lo que estas pruebas cuidan por encima de todo es que
# nada se filtre: un producto con el anaquel lleno baja, nunca desaparece.


def test_cada_renglon_dice_la_existencia_que_tenia_el_producto(cliente, almacen):
    """Primer criterio del ticket: "cada renglón muestra la existencia actual".

    Sin ella la lista es una enumeración: "se vendieron 3" se lee idéntico con
    el anaquel vacío que con 40 piezas guardadas, y el encargado no puede
    decidir nada de un vistazo.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", existencia=12)
    ]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 3)]

    renglon = cliente.get(RUTA).json()["renglones"][0]

    assert renglon["existencia"] == 12


def test_cada_renglon_dice_sus_dias_de_cobertura(cliente, almacen):
    """Segundo criterio, con la definición del glosario y nada más.

    "Cuántos días duraría la existencia actual al ritmo al que se ha vendido"
    (CONTEXT.md). Aquí el ritmo son 4 piezas en 4 días con datos —1 al día— y
    quedan 10 piezas: 10 días de cobertura. El ritmo sale de las ventas, que
    es lo único que la función tiene; no hay reloj que mirar.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "PARACETAMOL", existencia=10)
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 13), 1, 1),
        _venta(dt.date(2026, 9, 14), 1, 1),
        _venta(dt.date(2026, 9, 15), 1, 1),
        _venta(dt.date(2026, 9, 16), 1, 1),
    ]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["renglones"][0]["dias_de_cobertura"] == 10.0
    # **Las dos ventanas son distintas, y aquí se ve de un vistazo.** El ritmo
    # se mide sobre 28 días —de ahí salen las 4 piezas en 4 días y los 10 días
    # de cobertura—, pero la REPOSICIÓN es otra cosa: sin cierre anterior son
    # los `pedido.dias_primera_vez`, que desde el 2026-09-20 es **uno**. Así
    # que se propone 1, la pieza del último día, y no 4.
    #
    # Este número decía 4 cuando la primera ventana eran siete días, y el
    # cambio lo volvió una mejor demostración: antes las dos ventanas daban
    # cifras que podían confundirse, ahora se separan solas.
    assert cuerpo["renglones"][0]["cantidad_propuesta"] == 1


def test_la_lista_va_ordenada_por_urgencia_y_nada_se_filtra(cliente, almacen):
    """El criterio central del ticket, entero y en una sola corrida.

    Agotado primero, luego menor cobertura, y **los cinco renglones siguen
    ahí**: el de 900 días de cobertura baja hasta el fondo, no desaparece.
    Filtrarlo sería meter la lógica de la tarjeta O2 de Metabase por la puerta
    de atrás, y el dueño pidió explícitamente no usarla como fuente del pedido
    (ADR 0002). Si alguien agrega un filtro, este `== 5` se pone rojo.

    El último es el que no está en el catálogo: de ése no se sabe la
    existencia, y "no sé" no encabeza una lista de urgencias.
    """
    almacen.catalogo_en_memoria = [
        _producto(1, "7501000000001", "AMOXICILINA", existencia=0),
        _producto(2, "7501000000002", "BENZAL", existencia=900),
        _producto(3, "7501000000003", "CLORFENAMINA", existencia=2),
        _producto(4, "7501000000004", "DICLOFENACO", existencia=20),
    ]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=2, cantidad=1),
        _venta(dt.date(2026, 9, 16), producto_id=4, cantidad=1),
        _venta(dt.date(2026, 9, 16), producto_id=99, cantidad=1),  # sin catálogo
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=1),
        _venta(dt.date(2026, 9, 16), producto_id=3, cantidad=1),
    ]

    renglones = cliente.get(RUTA).json()["renglones"]

    assert len(renglones) == 5
    assert [r["producto_id"] for r in renglones] == [1, 3, 4, 2, 99]
    assert [r["dias_de_cobertura"] for r in renglones] == [0.0, 2.0, 20.0, 900.0, None]


def test_un_producto_fuera_del_catalogo_no_tiene_existencia_de_cero(cliente, almacen):
    """Regla 4 de CLAUDE.md: `0` y "no sé" no son lo mismo.

    De un producto que `dim_producto` no conoce no se sabe cuánto queda. Un
    cero ahí lo mandaría a lo más urgente de la lista **mintiendo**, y un
    "agotado" falso arriba empuja hacia abajo a lo que de verdad se acabó. Se
    muestra igual, al final, marcado y contado.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PARACETAMOL")]
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 16), producto_id=1, cantidad=1),
        _venta(dt.date(2026, 9, 16), producto_id=99, cantidad=2),
    ]

    renglones = cliente.get(RUTA).json()["renglones"]
    huerfano = next(r for r in renglones if r["producto_id"] == 99)

    assert huerfano["existencia"] is None
    assert huerfano["dias_de_cobertura"] is None
    assert huerfano["esta_agotado"] is False  # no sabemos que se acabó
    assert renglones[-1]["producto_id"] == 99


def test_un_producto_que_no_se_vendio_en_la_ventana_no_tiene_cobertura_de_cero():
    """Existencia 30 y ritmo cero no son cero días de cobertura: son "sin dato".

    Pintarlo como `0` se leería **agotado**, que es lo contrario de lo que
    pasa: hay mercancía y no se está moviendo. Dividir entre cero tampoco es
    opción, y un infinito no se puede serializar a JSON ni leer en una
    pantalla. Se prueba llamando a la función directo porque es una rama del
    cálculo, pero **ya no es hipotética por la ruta**: desde el ticket 09 la
    ventana de reposición acumula desde el cierre y puede ser más larga que la
    del ritmo, así que un producto que solo se movió hace dos meses sale en la
    lista sin haberse vendido en las últimas cuatro semanas. Ése es justo este
    renglón.
    """
    pedido = calcular_pedido_sugerido(
        ventas=[_venta(dt.date(2026, 9, 16), producto_id=1, cantidad=2)],
        catalogo=[_producto(1, "7501000000001", "PARACETAMOL", existencia=30)],
        ventas_del_ritmo=[_venta(dt.date(2026, 9, 16), producto_id=2, cantidad=5)],
    )

    assert pedido.renglones[0].dias_de_cobertura is None
    assert pedido.renglones[0].esta_agotado is False


def test_el_desempate_es_determinista_y_el_orden_no_baila_entre_corridas():
    """Dos corridas seguidas tienen que dar el mismo orden.

    "Sin desempate definido" acaba siendo "el orden en que Python recorrió un
    diccionario": la pantalla cambia bajo los pies de quien la lee dos días
    seguidos y deja de ser confiable. Con la misma cobertura manda la
    descripción, y con la misma descripción el `producto_id`, que es único.
    """
    catalogo = [
        _producto(1, "7501000000001", "NAPROXENO", existencia=4),
        _producto(2, "7501000000002", "AMOXICILINA", existencia=4),
        _producto(3, "7501000000003", "PARACETAMOL", existencia=4),
    ]
    ventas = [
        _venta(dt.date(2026, 9, 16), 1, 1),
        _venta(dt.date(2026, 9, 16), 2, 1),
        _venta(dt.date(2026, 9, 16), 3, 1),
    ]

    primera = calcular_pedido_sugerido(ventas=ventas, catalogo=catalogo)
    # Las mismas filas en otro orden: el almacén no promete uno, y un `order
    # by` de Postgres que cambie no debe mover la pantalla.
    segunda = calcular_pedido_sugerido(
        ventas=list(reversed(ventas)), catalogo=list(reversed(catalogo))
    )

    assert [r.descripcion for r in primera.renglones] == [
        "AMOXICILINA",
        "NAPROXENO",
        "PARACETAMOL",
    ]
    assert [r.producto_id for r in primera.renglones] == [
        r.producto_id for r in segunda.renglones
    ]


def test_la_existencia_y_la_cobertura_viajan_congeladas_dentro_del_renglon():
    """Son las del momento en que se propuso el renglón, no las de después.

    El renglón se lleva el número dentro, copiado; no guarda una referencia al
    catálogo ni una manera de volver a preguntarle. Por eso, cuando el
    catálogo cambia debajo —llegó mercancía—, la lista que ya se propuso sigue
    diciendo lo que se vio al proponerla. El día que el renglón se guarde
    (ticket 08), ese número se guarda con él.
    """
    catalogo = [_producto(1, "7501000000001", "PARACETAMOL", existencia=4)]

    pedido = calcular_pedido_sugerido(
        ventas=[_venta(dt.date(2026, 9, 16), 1, 2)], catalogo=catalogo
    )
    catalogo[0] = dataclasses.replace(catalogo[0], existencia=400)

    assert pedido.renglones[0].existencia == 4
    assert pedido.renglones[0].dias_de_cobertura == 2.0


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
    producto_id: int, clave: str, descripcion: str, existencia: float = 4
) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=descripcion,
        categoria="GRUP4",
        departamento="MEDICAMENTO",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )
