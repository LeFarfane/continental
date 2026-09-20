"""Los dos bordes que Continental no controla, y la costura para sustituirlos.

Este archivo existe por una falla ajena y medida: `Marlowe/src/marlowe/web/app.py`
abre SQLite, crea el motor de Postgres y verifica la pantalla **al importarse**,
y el precio es un fixture de ~100 líneas con un `DISPLAY` falso y una URL de
Postgres muerta para que `import app` no truene. Continental no hereda eso, y
`test_ningun_modulo_abre_conexion_ni_crea_motor_al_importarse` es lo que lo
impide: el día que alguien conecte al importar, esa prueba se pone roja.

Ninguna prueba de este archivo toca Postgres ni la red.
"""

from __future__ import annotations

import datetime as dt
import importlib
import pkgutil
import socket
import sys
import typing

import sqlalchemy

import continental
from continental.almacen import (
    AlmacenPostgres,
    LecturaDelAlmacen,
    LineaDeCompra,
    LineaDeVenta,
    Producto,
)
from continental.dobles import (
    AlmacenFalso,
    DoyleFalso,
    respuesta_con_error,
    respuesta_lista,
)
from continental.doyle import ClienteDeDoyle, DoylePorHttp
from continental.web.app import app

# --------------------------------------------------------------- la costura


def test_los_dos_bordes_entran_por_depends_y_se_sustituyen_en_pruebas(
    cliente, almacen, doyle
):
    """El criterio del ticket: `app.dependency_overrides` y nada más.

    Sin `monkeypatch`, sin parchear módulos, sin variables de entorno: se
    cambia la dependencia y la aplicación entera trabaja contra el doble.
    """
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PATENTE 1")]
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 3)]
    doyle.sesiones_en_memoria = [
        {
            "proveedor": "nadro",
            "nombre": "NADRO",
            "estado": "guardada",
            "guardada_en": "2026-09-17T08:00:00",
        }
    ]

    cuerpo = cliente.get("/api/bordes").json()
    bordes = {b["nombre"]: b for b in cuerpo["bordes"]}

    assert bordes["almacen"]["ok"] is True
    assert bordes["almacen"]["productos"] == 1
    assert bordes["almacen"]["ultima_venta"] == "2026-09-16"
    assert bordes["doyle"]["ok"] is True
    assert bordes["doyle"]["sesiones"] == 1


def test_el_almacen_caido_es_un_hueco_con_motivo_y_sin_cadena_de_conexion(
    cliente, almacen
):
    """Reglas 4 y 5 de CLAUDE.md, juntas en un solo borde.

    Un `str(exc)` de SQLAlchemy lleva la cadena de conexión con contraseña. Al
    navegador sale el tipo de la falla, nunca su texto. Es la misma lección que
    Marlowe aprendió el 2026-09-06.
    """
    almacen.falla = sqlalchemy.exc.OperationalError(
        "select 1",
        {},
        Exception("connection to 127.0.0.1 failed: password=SECRETO"),
    )

    respuesta = cliente.get("/api/bordes")
    borde = next(b for b in respuesta.json()["bordes"] if b["nombre"] == "almacen")

    assert borde["ok"] is False
    assert borde["detalle"]  # un hueco con su motivo, nunca vacío
    assert "SECRETO" not in respuesta.text
    assert "password" not in respuesta.text


def test_doyle_caido_es_un_hueco_con_motivo_y_el_otro_borde_no_se_contagia(
    cliente, almacen, doyle
):
    """Historia 53 del spec: Doyle caído no puede tumbar la pantalla."""
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "PATENTE 1")]
    doyle.falla = TimeoutError("no contestó")

    bordes = {b["nombre"]: b for b in cliente.get("/api/bordes").json()["bordes"]}

    assert bordes["doyle"]["ok"] is False
    assert bordes["doyle"]["detalle"]
    assert bordes["almacen"]["ok"] is True


def test_el_borde_real_del_almacen_mal_configurado_es_un_hueco_y_no_tumba_nada(
    monkeypatch, doyle, cliente_de_sesion
):
    """La única prueba que NO sustituye el borde del almacén, y es a propósito.

    Sustituir siempre los dos bordes deja sin cubrir el camino que corre en
    producción: el `Depends` de verdad. Ahí se cruzan dos cosas que se
    descubrieron construyendo esto:

    1. Una dependencia que truena lo hace **antes** de entrar a la ruta, donde
       el `try` de `/api/bordes` ya no la alcanza. Por eso `obtener_almacen`
       entrega la factoría del motor y no el motor: la falla tiene que ocurrir
       dentro de la lectura para poder verse como un hueco.
    2. Si esa falla fuera `SystemExit` —el idioma que usa `config.cargar`— no
       la atraparían ni FastAPI ni Starlette, que filtran por `Exception`, y se
       llevaría al servidor por delante.

    No toca Postgres ni la red: sin `WAREHOUSE_URL` no se llega a crear el
    motor. Y el texto de la falla —que dice dónde está el archivo de
    configuración— se queda en la bitácora del servidor, no viaja al navegador
    (regla 5 de CLAUDE.md).

    **El `delenv` de abajo solo simula algo porque `_sin_env_del_disco` —la
    fixture autouse de `conftest.py`— ya neutralizó `load_dotenv`.** Sin ella,
    en una máquina **con** `.env` la variable reaparece del disco, el borde
    conecta de verdad y contesta `ok: True`. Esta prueba pasaba en la torre,
    donde no hay `.env`, y se puso roja en atlas el 2026-09-20, el día que el
    `.env` existió — con el suite siendo el paso 3 de `scripts/desplegar.sh`,
    o sea la capacidad de desplegar. Y mientras tanto la promesa de arriba —"no
    toca Postgres ni la red"— era falsa justo en la máquina donde importa.
    """
    from continental.almacen import motor
    from continental.config import cargar
    from continental.web.dependencias import obtener_doyle

    monkeypatch.delenv("WAREHOUSE_URL", raising=False)
    cargar.cache_clear()
    motor.cache_clear()
    app.dependency_overrides[obtener_doyle] = lambda: doyle
    try:
        respuesta = cliente_de_sesion.get("/api/bordes")
        borde = next(b for b in respuesta.json()["bordes"] if b["nombre"] == "almacen")
        assert respuesta.status_code == 200
        assert borde["ok"] is False
        assert borde["detalle"]
        assert "WAREHOUSE_URL" not in respuesta.text
        assert ".env" not in respuesta.text
    finally:
        app.dependency_overrides.clear()
        cargar.cache_clear()
        motor.cache_clear()


def test_el_env_del_disco_no_entra_al_suite():
    """El guardia de la prueba de arriba, porque su falla es invisible aquí.

    `_sin_env_del_disco` (autouse, en `conftest.py`) es lo que hace que un
    `monkeypatch.delenv(...)` signifique algo en una máquina con `.env`. Si
    alguien la quita, **nada se pone rojo en la torre**: el daño aparece en
    atlas, en el paso 3 de `scripts/desplegar.sh`, sobre una rama que aquí se
    veía verde. Exactamente lo que pasó el 2026-09-20.

    Por eso el guardia vive aquí, junto a la prueba que protege, y no en un
    archivo de utilería que nadie abre.

    Se compara **contra la función real** y no con su valor de retorno. Fue el
    primer intento y no servía: el `load_dotenv` de verdad también contesta
    `False` cuando no encuentra el archivo, así que en la torre —donde no hay
    `.env`— el guardia pasaba con la fixture apagada. Un guardia que solo sabe
    vigilar donde no hay nada que vigilar.
    """
    from dotenv import load_dotenv as el_de_verdad

    from continental import config

    import iniciar

    for modulo in (config, iniciar):
        assert modulo.load_dotenv is not el_de_verdad, (
            f"`{modulo.__name__}.load_dotenv` es el de verdad: la fixture "
            "autouse `_sin_env_del_disco` de conftest.py no corrió o alguien "
            "la quitó. Sin ella, cualquier prueba que borre una variable del "
            "entorno deja de simular nada en una máquina con `.env` — y eso "
            "solo se ve en atlas, en el paso 3 de desplegar.sh."
        )


# --------------------------------------------------- la lectura del almacén


def test_la_lectura_del_almacen_devuelve_datos_y_no_conexiones():
    """El criterio literal del ticket, comprobado sobre la interfaz misma.

    Si alguien empieza a devolver un `Connection`, un `Result` o una `Session`,
    esto se pone rojo antes de que el préstamo se propague al módulo entero.
    """
    for nombre in ("ventas", "catalogo", "compras_desde", "ultima_fecha_con_ventas"):
        devuelto = repr(typing.get_type_hints(getattr(LecturaDelAlmacen, nombre))["return"])
        assert "sqlalchemy" not in devuelto, f"{nombre} devuelve algo de SQLAlchemy"
        assert "Connection" not in devuelto and "Session" not in devuelto
        assert "Cursor" not in devuelto and "Result" not in devuelto


def test_el_almacen_da_ventas_de_un_rango_catalogo_y_compras_posteriores(almacen):
    """Las tres lecturas que el ticket pide, y que el doble recorte igual que
    el SQL: un doble que no filtra miente, y deja pasar una prueba que contra
    Postgres habría fallado.
    """
    almacen.ventas_en_memoria = [
        _venta(dt.date(2026, 9, 11), 1, 2),  # viernes
        _venta(dt.date(2026, 9, 12), 1, 5),  # sábado
        _venta(dt.date(2026, 9, 14), 2, 1),  # lunes, fuera del rango
    ]
    almacen.catalogo_en_memoria = [_producto(1, "7501000000001", "GENERICO 3")]
    almacen.compras_en_memoria = [
        _compra(dt.date(2026, 9, 10), 1),
        _compra(dt.date(2026, 9, 13), 1),
    ]

    ventas = almacen.ventas(dt.date(2026, 9, 11), dt.date(2026, 9, 12))
    assert [v.cantidad for v in ventas] == [2, 5]
    assert all(isinstance(v, LineaDeVenta) for v in ventas)

    catalogo = almacen.catalogo()
    # El glosario manda: se llama anaquel, aunque la columna sea `ubicacion`.
    assert catalogo[0].anaquel == "GENERICO 3"
    assert catalogo[0].existencia == 4
    assert isinstance(catalogo[0], Producto)

    compras = almacen.compras_desde(dt.date(2026, 9, 12))
    assert [c.fecha for c in compras] == [dt.date(2026, 9, 13)]
    assert isinstance(compras[0], LineaDeCompra)


def test_la_ultima_fecha_de_ventas_sale_del_dato_y_no_del_reloj(almacen):
    """Trampa heredada: el Postgres del contenedor corre en UTC y su
    `current_date` puede ir dos días adelante del último dato. A farmacia-data
    le costó 11.7 puntos de crecimiento inventados. Por eso el borde expone
    `max(fecha)` y nadie de arriba tiene excusa para mirar el reloj.
    """
    assert almacen.ultima_fecha_con_ventas() is None  # almacén vacío: se dice
    almacen.ventas_en_memoria = [_venta(dt.date(2026, 9, 16), 1, 1)]
    assert almacen.ultima_fecha_con_ventas() == dt.date(2026, 9, 16)


# ------------------------------------------------------ el cliente de Doyle


def test_pedir_una_busqueda_devuelve_job_id_y_el_estado_se_consulta_despues(doyle):
    """Doyle no contesta de golpe y el cliente no puede fingir que sí.

    Una búsqueda en un portal tiene un piso medido de ~9 s por proveedor
    (5.6 s de scroll de carga diferida + 3 s de cortesía) y un techo de 60-90 s.
    Por eso la interfaz son dos llamadas cortas y no una larga.
    """
    doyle.resultados_por_termino["7501000000001"] = {
        "nadro": respuesta_lista("nadro", [("7501000000001", "86.05", "40")])
    }

    pedida = doyle.pedir_busqueda("7501000000001")
    assert pedida.job_id
    assert "nadro" in pedida.proveedores

    estado = doyle.estado_de_busqueda(pedida.job_id)
    assert estado.termino == "7501000000001"
    assert estado.proveedores["nadro"].filas[0].precio == "86.05"


def test_un_proveedor_que_no_contesto_queda_sin_dato_y_nunca_en_cero(doyle):
    """Regla 4 de CLAUDE.md: "sin dato", jamás un cero ni un "más caro".

    Por eso el precio viaja como el texto que dio el portal y no como `float`:
    convertirlo aquí obligaría a inventar un 0.0 para el hueco, y un cero se
    lee como "el más barato" y dispara una compra mala.
    """
    doyle.resultados_por_termino["7501000000001"] = {
        "quepharma": respuesta_con_error("quepharma", "sesión caducada")
    }

    estado = doyle.estado_de_busqueda(doyle.pedir_busqueda("7501000000001").job_id)
    respuesta = estado.proveedores["quepharma"]

    assert respuesta.estado == "error"
    assert respuesta.filas == ()
    assert respuesta.mensaje == "sesión caducada"
    assert not hasattr(respuesta, "precio")  # no existe un cero que confundir


def test_listar_sesiones_dice_cual_proveedor_no_tiene_sesion(doyle):
    """Historia 33 del spec: una sesión caducada se ve en la pantalla, en vez
    de aparecer como un precio faltante sin explicación.
    """
    doyle.sesiones_en_memoria = [
        {
            "proveedor": "nadro",
            "nombre": "NADRO",
            "estado": "guardada",
            "guardada_en": "2026-09-17T08:00:00",
        },
        {"proveedor": "levic", "nombre": "LEVIC", "estado": "sin_sesion", "guardada_en": None},
    ]

    sesiones = {s.proveedor: s for s in doyle.sesiones()}
    assert sesiones["levic"].estado == "sin_sesion"
    assert sesiones["nadro"].guardada_en == "2026-09-17T08:00:00"


# --------------------------------------------- las dos son interfaces aparte


def test_las_implementaciones_reales_y_los_dobles_cumplen_la_misma_interfaz():
    """Un doble que se desvía de la interfaz real prueba otra cosa."""
    assert isinstance(AlmacenFalso(), LecturaDelAlmacen)
    assert isinstance(AlmacenPostgres(fabrica_de_motor=None), LecturaDelAlmacen)
    assert isinstance(DoyleFalso(), ClienteDeDoyle)
    assert isinstance(DoylePorHttp(url="http://127.0.0.1:8383"), ClienteDeDoyle)


def test_el_almacen_y_doyle_son_dos_interfaces_separadas():
    """El ticket las pide aparte: una prueba tiene que poder sustituir una sola
    y un borde caído no puede arrastrar al otro.
    """
    del_almacen = {n for n in dir(LecturaDelAlmacen) if not n.startswith("_")}
    de_doyle = {n for n in dir(ClienteDeDoyle) if not n.startswith("_")}
    assert del_almacen & de_doyle == set()


# --------------------------------------------- nada se conecta al importarse


def _modulos_de_continental() -> list[str]:
    return ["continental"] + [
        m.name for m in pkgutil.walk_packages(continental.__path__, "continental.")
    ]


def test_ningun_modulo_abre_conexion_ni_crea_motor_al_importarse(monkeypatch):
    """El criterio duro del ticket, y la única forma honesta de comprobarlo:
    importar todo con una URL de Postgres envenenada y un `socket.connect` que
    truena.

    Si esto se pone rojo, alguien sacó la creación del motor de su factoría
    perezosa y el suite acaba de heredar el fixture de ~100 líneas de Marlowe.
    """
    nombres = _modulos_de_continental()
    originales = {
        n: sys.modules[n]
        for n in list(sys.modules)
        if n == "continental" or n.startswith("continental.")
    }

    monkeypatch.setenv(
        "WAREHOUSE_URL", "postgresql+psycopg2://continental:SECRETO@127.0.0.1:1/nada"
    )
    motores: list[tuple] = []
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: motores.append(a))

    def sin_red(self, *a, **k):
        raise AssertionError("un módulo abrió una conexión al importarse")

    monkeypatch.setattr(socket.socket, "connect", sin_red)

    for n in originales:
        del sys.modules[n]
    try:
        for nombre in nombres:
            importlib.import_module(nombre)
        assert motores == [], "alguien creó el motor al importar un módulo"
    finally:
        for n in [k for k in sys.modules if k == "continental" or k.startswith("continental.")]:
            del sys.modules[n]
        sys.modules.update(originales)


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


def _producto(producto_id: int, clave: str, anaquel: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion="PRODUCTO DE PRUEBA 500MG",
        categoria="GRUP4",
        departamento="MEDICAMENTO",
        anaquel=anaquel,
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=4,
        esta_activo=True,
        es_granel=False,
    )


def _compra(fecha: dt.date, producto_id: int) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=1,
        producto_id=producto_id,
        proveedor_id=7,
        fecha=fecha,
        cantidad=6,
        precio_unitario_pagado=28.0,
        importe_pagado=168.0,
        folio="A-1",
    )
