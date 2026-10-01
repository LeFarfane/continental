"""La pestaña de Buscar (2026-09-28): la que Doyle tenía y nadie podía ver.

Doyle se mudó a atlas el 2026-09-21 sin interfaz propia (su ADR 0008) y su
pestaña «Buscar» se quedó en `127.0.0.1:8383`, donde nadie de la farmacia
llega. Ahora la dibuja Continental y quien busca sigue siendo Doyle.

Lo que se fija aquí, por capas:

1. **Lo puro** (`busqueda.py`): qué se deja buscar, qué dice cada portal con
   palabras de esta pantalla, las cifras tal como llegaron —nunca un `$0.00`—,
   y qué es nuestro de lo encontrado sin afirmar "no es nuestro" cuando no se
   sabe.
2. **El borde**: una búsqueda que Doyle olvidó (se reinició) no es un Doyle
   caído, y el contrato de Doyle se lee con la forma que su código tiene hoy.
3. **Las rutas**: se pide y se pregunta cómo va; cada borde cae por separado.
4. **La pantalla**: dos pestañas con los nombres del glosario, y el sondeo
   que obedece al servidor.

Ninguna prueba toca Postgres, ni Doyle, ni la red, ni duerme.
"""

from __future__ import annotations

import re

import httpx
import pytest

from conftest import pantalla_completa
from continental import busqueda, config
from continental.almacen import AlmacenPostgres, Producto, _sql_del_catalogo
from continental.busqueda import (
    BUSQUEDA_OLVIDADA,
    LARGO_MAXIMO_DEL_TERMINO,
    QUE_PASO,
    SONDEO_MS,
    TOPE_SEGUNDOS,
    acuse_como_json,
    busqueda_como_json,
    cifras_de_la_fila,
    claves_por_cruzar,
    job_id_valido,
    lo_nuestro,
    motivo_del_proveedor,
    motivo_para_no_buscar,
    termino_limpio,
)
from continental.dobles import (
    AlmacenFalso,
    DoyleFalso,
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_en_reconocimiento,
    respuesta_lista,
    respuesta_pendiente,
)
from continental.doyle import (
    BusquedaDesconocida,
    BusquedaPedida,
    DoylePorHttp,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
)
from continental.fallas import AL_LEER, DOYLE, que_hacer
from continental.precios import (
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_SELECTORES,
    VENTANA_DE_SESION_ABIERTA,
)

EAN = "7501000000001"
LOS_CUATRO = ("nadro", "levic", "vicma", "quepharma")


def _producto(clave: str = EAN, descripcion: str = "PARACETAMOL 500 MG", existencia: float = 12.0):
    return Producto(
        producto_id=1,
        clave=clave,
        descripcion=descripcion,
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="GENERICO 1",
        precio_lista_sin_iva=20.0,
        costo=8.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


def _fila(precio: str = "86.05", existencia: str = "40", clave: str = EAN, **otros) -> FilaDeProveedor:
    return FilaDeProveedor(
        clave=clave,
        descripcion=otros.pop("descripcion", "PARACETAMOL 500MG C/10"),
        precio=precio,
        precio_publico=otros.pop("precio_publico", ""),
        existencia=existencia,
        **otros,
    )


def _terminada(**por_proveedor: RespuestaDeProveedor) -> EstadoDeBusqueda:
    return EstadoDeBusqueda(termino=EAN, proveedores=dict(por_proveedor))


# =========================================================================
# 1. LO PURO
# =========================================================================

# ------------------------------------------------------------- el término


def test_el_termino_se_limpia_de_espacios_de_sobra():
    assert termino_limpio("  paracetamol   500 ") == "paracetamol 500"
    assert termino_limpio(None) == ""


def test_un_campo_vacio_no_se_le_pide_a_doyle():
    assert motivo_para_no_buscar("") is not None


def test_un_texto_pegado_por_error_no_viaja_a_cuatro_portales_ajenos():
    """Lo que se busca, Doyle lo teclea en el buscador de cada portal con las
    credenciales del dueño."""
    assert motivo_para_no_buscar("x" * (LARGO_MAXIMO_DEL_TERMINO + 1)) is not None
    assert motivo_para_no_buscar("x" * LARGO_MAXIMO_DEL_TERMINO) is None


@pytest.mark.parametrize("job_id", ["0f8e1c2d3b4a59687766554433221100", "trabajo-1"])
def test_el_job_id_de_doyle_y_el_del_doble_se_dejan_preguntar(job_id):
    assert job_id_valido(job_id)


@pytest.mark.parametrize("job_id", ["", "..", "a/b", "a.b", "a?b=1", "x" * 65])
def test_un_job_id_que_saldria_de_la_ruta_de_doyle_no_se_pregunta(job_id):
    """Viaja pegado a `/api/buscar/` de Doyle: con `..` o `/` saldría de ahí."""
    assert not job_id_valido(job_id)


# ------------------------------------------------ lo que dice cada portal


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        (respuesta_con_sesion_caducada("nadro"), SESION_CADUCADA),
        (
            respuesta_con_error(
                "vicma",
                "No se encontraron artículos. Si este error continúa, notifíquelo al administrador.",
            ),
            SIN_RESULTADOS,
        ),
        (
            respuesta_con_error(
                "vicma",
                "falla inesperada: BrowserType.launch_persistent_context: Opening in "
                "existing browser session.",
            ),
            VENTANA_DE_SESION_ABIERTA,
        ),
        (respuesta_con_error("levic", "falla inesperada: Page.wait_for_timeout"), PORTAL_SIN_CONTESTAR),
        (respuesta_en_reconocimiento("quepharma"), SIN_SELECTORES),
        (respuesta_lista("nadro", []), SIN_RESULTADOS),
        (respuesta_lista("nadro", [(EAN, "86.05", "40")]), None),
        (respuesta_pendiente("nadro"), None),
    ],
    ids=["sesion", "no-encontro", "ventana", "otro-error", "reconocimiento", "vacio", "con-filas", "buscando"],
)
def test_el_mensaje_de_doyle_quiere_decir_lo_mismo_aqui_que_en_la_lista(respuesta, motivo):
    """Se reusa `precios.motivo_del_error`: el mismo mensaje de Doyle no puede
    leerse de una manera en la lista y de otra en Buscar."""
    assert motivo_del_proveedor(respuesta) == motivo


def test_cada_motivo_que_una_busqueda_puede_dar_tiene_su_frase_de_esta_pantalla():
    """Las de la lista dicen "se vuelve a intentar" por el lote; aquí nadie
    reintenta solo."""
    for motivo in (SIN_RESULTADOS, PORTAL_SIN_CONTESTAR, SESION_CADUCADA,
                   VENTANA_DE_SESION_ABIERTA, SIN_SELECTORES):
        assert QUE_PASO[motivo]
    assert "se vuelve a intentar" not in " ".join(QUE_PASO.values())


# ------------------------------------------------------------ las cifras


@pytest.mark.parametrize(
    ("fila", "esperadas"),
    [
        (_fila("86.05", "40", precio_publico="120.00"),
         ["Compra $86.05", "Público $120.00", "Existencia 40"]),
        (_fila("1,234.50", "+100"), ["Compra $1,234.50", "Existencia 100"]),
        (_fila("86.05", "0"), ["Compra $86.05", "Sin existencia"]),
        (_fila("86.05", "NO DISPONIBLE"), ["Compra $86.05", "Existencia: NO DISPONIBLE"]),
        (_fila("86.05", ""), ["Compra $86.05", "No dijo existencia"]),
        (_fila("", "40"), ["Sin precio de compra", "Existencia 40"]),
        (_fila("1.234,50", "40"), ["Compra «1.234,50» (no se lee como precio)", "Existencia 40"]),
    ],
    ids=["completa", "miles-y-cota", "cero", "con-palabras", "sin-existencia-dicha",
         "sin-precio", "formato-europeo"],
)
def test_las_cifras_se_dicen_tal_como_las_dio_el_portal(fila, esperadas):
    assert cifras_de_la_fila(fila) == esperadas


def test_un_precio_en_cero_nunca_se_escribe_como_cero_pesos():
    """Regla 4: un cero gana toda comparación de "el más barato"."""
    cifras = " ".join(cifras_de_la_fila(_fila("0.00", "40", precio_publico="0")))

    assert "$0" not in cifras
    assert "«0.00»" in cifras


def test_lo_dicho_con_palabras_no_se_lee_como_sin_existencia():
    """"NO DISPONIBLE" de QuePharma se enseña tal cual; lo que se marca como
    sin existencia es solo el cero que el portal escribió."""
    estado = _terminada(
        quepharma=RespuestaDeProveedor("quepharma", "listo", (_fila("10", "NO DISPONIBLE"),), 1),
        nadro=RespuestaDeProveedor("nadro", "listo", (_fila("10", "0"),), 1),
    )
    por_proveedor = {p["proveedor"]: p for p in busqueda_como_json(estado, [])["proveedores"]}

    assert por_proveedor["quepharma"]["filas"][0]["sin_existencia"] is False
    assert por_proveedor["nadro"]["filas"][0]["sin_existencia"] is True


# ----------------------------------------------------------- lo nuestro


def test_ningun_producto_nuestro_no_se_dice_como_que_no_es_nuestro():
    """QuePharma y VICMA muestran código interno: casi nunca empatan aunque el
    producto sí sea nuestro. Callar es lo honesto; "no es nuestro" no."""
    assert lo_nuestro([]) is None


def test_un_producto_nuestro_se_dice_con_su_existencia():
    nuestro = lo_nuestro([_producto(existencia=12.0)])

    assert nuestro["frase"] == "Nuestro: PARACETAMOL 500 MG · 12 en existencia"


def test_dos_articulos_con_el_mismo_ean_se_ven_los_dos():
    """SICAR deja guardar el mismo EAN dos veces: uno no tapa al otro."""
    nuestro = lo_nuestro([_producto(descripcion="UNO"), _producto(descripcion="DOS")])

    assert nuestro["cuantos"] == 2
    assert "UNO" in nuestro["frase"] and "DOS" in nuestro["frase"]


def test_sin_catalogo_ninguna_fila_afirma_nada_de_lo_nuestro():
    estado = _terminada(nadro=respuesta_lista("nadro", [(EAN, "86.05", "40")]))
    falla = {"detalle": "no se pudo leer", "que_hacer": "algo"}

    datos = busqueda_como_json(estado, None, falla)

    assert datos["catalogo_sin_leer"] == falla
    assert datos["proveedores"][0]["filas"][0]["nuestro"] is None
    assert datos["lo_buscado"] is None


def test_se_cruzan_las_claves_de_los_resultados_y_el_termino_si_es_un_codigo():
    estado = _terminada(
        nadro=respuesta_lista("nadro", [("7501000000002", "1", "1")]),
        quepharma=respuesta_lista("quepharma", [("QP-77", "1", "1")]),
    )

    assert claves_por_cruzar(estado) == {EAN, "7501000000002", "QP-77"}
    por_nombre = EstadoDeBusqueda(termino="paracetamol", proveedores=estado.proveedores)
    assert "paracetamol" not in claves_por_cruzar(por_nombre)


def test_lo_buscado_por_codigo_dice_que_es_nuestro():
    estado = _terminada(nadro=respuesta_lista("nadro", []))

    assert busqueda_como_json(estado, [_producto()])["lo_buscado"]["cuantos"] == 1


# ------------------------------------------------------ el conjunto


def test_los_proveedores_salen_siempre_en_el_mismo_orden_y_ninguno_se_esconde():
    estado = _terminada(
        quepharma=respuesta_pendiente("quepharma"),
        zeta=respuesta_pendiente("zeta"),
        levic=respuesta_pendiente("levic"),
        nadro=respuesta_pendiente("nadro"),
        vicma=respuesta_pendiente("vicma"),
    )

    orden = [p["proveedor"] for p in busqueda_como_json(estado, [])["proveedores"]]

    assert orden == ["nadro", "levic", "vicma", "quepharma", "zeta"]


def test_solo_la_sesion_caducada_ofrece_abrir_sesion():
    """El botón sale de un portal que mandó al login, no del `guardada` de
    Doyle (la misma regla que en la lista)."""
    estado = _terminada(
        nadro=respuesta_con_sesion_caducada("nadro"),
        levic=respuesta_con_error("levic", "falla inesperada"),
    )
    por_proveedor = {p["proveedor"]: p for p in busqueda_como_json(estado, [])["proveedores"]}

    assert por_proveedor["nadro"]["sesion_caducada"] is True
    assert por_proveedor["levic"]["sesion_caducada"] is False
    assert por_proveedor["nadro"]["que_paso"] == QUE_PASO[SESION_CADUCADA]


def test_lo_que_doyle_corto_en_veinte_se_dice():
    muchas = RespuestaDeProveedor(
        "nadro", "listo", tuple(_fila(clave=f"750100000{i:04d}") for i in range(20)), total=57
    )

    [nadro] = busqueda_como_json(_terminada(nadro=muchas), [])["proveedores"]

    assert "57" in nadro["frase_del_total"] and "20" in nadro["frase_del_total"]


def test_la_frase_dice_cuantos_contestaron_mientras_busca_y_cuantos_trajeron_algo_al_final():
    en_curso = _terminada(
        nadro=respuesta_lista("nadro", [(EAN, "1", "1")]),
        levic=respuesta_pendiente("levic"),
    )
    final = _terminada(
        nadro=respuesta_lista("nadro", [(EAN, "1", "1")]),
        levic=respuesta_lista("levic", []),
    )

    assert "1 de 2 ya contestaron" in busqueda_como_json(en_curso, [])["frase"]
    assert busqueda_como_json(en_curso, [])["terminada"] is False
    assert "1 de 2 portales trajeron resultados" in busqueda_como_json(final, [])["frase"]


def test_una_busqueda_sin_proveedores_no_se_da_por_terminada():
    """La misma regla de `EstadoDeBusqueda.terminada`: un diccionario vacío es
    una respuesta que no trae lo que debía, no "todos terminaron"."""
    vacia = EstadoDeBusqueda(termino=EAN, proveedores={})

    assert busqueda_como_json(vacia, [])["terminada"] is False


def test_el_acuse_trae_como_sondear_y_las_cuatro_tarjetas_en_espera():
    acuse = acuse_como_json(BusquedaPedida(job_id="trabajo-1", proveedores=LOS_CUATRO), EAN)

    assert acuse["job_id"] == "trabajo-1"
    assert acuse["sondeo_ms"] == SONDEO_MS and acuse["tope_segundos"] == TOPE_SEGUNDOS
    assert acuse["frase_al_tope"]
    assert [p["etiqueta"] for p in acuse["proveedores"]] == ["en espera"] * 4


# =========================================================================
# 2. EL BORDE
# =========================================================================


def _doyle_que_contesta(estado: int, cuerpo: dict) -> DoylePorHttp:
    def contestar(peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(estado, json=cuerpo)

    return DoylePorHttp(url="http://127.0.0.1:8383", transporte=httpx.MockTransport(contestar))


def test_una_busqueda_que_doyle_olvido_no_es_un_doyle_caido():
    """Doyle guarda sus búsquedas en memoria (`_trabajos` de su `app.py`) y
    contesta 404 a una que no tiene: `"Esa búsqueda no existe (o el servidor se
    reinició)"`. Eso se arregla buscando otra vez, no levantando a Doyle."""
    doyle = _doyle_que_contesta(
        404, {"detail": "Esa búsqueda no existe (o el servidor se reinició)"}
    )

    with pytest.raises(BusquedaDesconocida):
        doyle.estado_de_busqueda("0f8e1c2d")


def test_el_contrato_de_doyle_se_lee_con_la_forma_que_su_codigo_tiene_hoy():
    """La forma, copiada del código de Doyle el 2026-09-28: `estado_busqueda`
    de su `web/app.py` y el resultado de `buscador.buscar_producto` (con
    `modo: consulta`, `filas` cortadas en 20 y `total` sin cortar). Doyle no
    tiene pruebas; esto es lo que avisa aquí si la forma que se lee se aleja
    de la que Doyle escribe (ADR 0001, enmienda del 2026-09-27)."""
    doyle = _doyle_que_contesta(200, {
        "termino": EAN,
        "proveedores": {
            "nadro": {
                "estado": "listo", "modo": "consulta", "total": 57,
                "filas": [{
                    "clave": EAN, "descripcion": "PARACETAMOL", "precio": "86.05",
                    "precio_publico": "120.00", "existencia": "40",
                    "imagen_url": "https://portal.example/x.png", "advertencia": "",
                }],
            },
            "levic": {"estado": "buscando"},
            "vicma": {"estado": "error", "mensaje": "falla inesperada: algo"},
            "quepharma": {"estado": "listo", "modo": "reconocimiento"},
        },
    })

    estado = doyle.estado_de_busqueda("0f8e1c2d")

    nadro = estado.proveedores["nadro"]
    assert (nadro.estado, nadro.total, nadro.filas[0].precio) == ("listo", 57, "86.05")
    assert estado.proveedores["levic"].estado == "buscando"
    assert estado.proveedores["vicma"].mensaje == "falla inesperada: algo"
    assert estado.proveedores["quepharma"].estado == "reconocimiento"
    assert not estado.terminada


def test_el_doble_olvida_igual_que_doyle():
    with pytest.raises(BusquedaDesconocida):
        DoyleFalso().estado_de_busqueda("trabajo-99")


def test_la_octava_lectura_pide_las_mismas_columnas_que_el_catalogo_con_la_clave_como_parametro():
    """Un producto buscado por su EAN tiene que llegar igual que uno leído del
    catálogo entero; y las claves viajan como parámetro, nunca pegadas."""
    entero = _sql_del_catalogo(True)
    por_clave = _sql_del_catalogo(True, por_clave=True)

    assert por_clave.split("from")[0] == entero.split("from")[0]
    assert "trim(clave) = any(:claves)" in por_clave


def test_sin_claves_la_octava_lectura_no_toca_la_base():
    assert AlmacenPostgres(None).productos_por_clave(["", "  "]) == []


def test_el_doble_del_almacen_encuentra_por_clave_sin_espacios():
    almacen = AlmacenFalso(catalogo_en_memoria=[_producto(clave=EAN + " ")])

    assert [p.producto_id for p in almacen.productos_por_clave([EAN])] == [1]


# =========================================================================
# 3. LAS RUTAS
# =========================================================================


def test_pedir_una_busqueda_devuelve_el_trabajo_y_las_cuatro_tarjetas(cliente, doyle):
    doyle.resultados_por_termino = {
        EAN: {p: respuesta_pendiente(p) for p in LOS_CUATRO}
    }

    acuse = cliente.post("/api/buscar", json={"termino": f"  {EAN} "}).json()

    assert acuse["ok"] is True
    assert doyle.pedidos == [EAN]
    assert [p["nombre"] for p in acuse["proveedores"]] == ["NADRO", "LEVIC", "VICMA", "QuePharma"]


def test_un_campo_vacio_contesta_que_hacer_sin_molestar_a_doyle(cliente, doyle):
    respuesta = cliente.post("/api/buscar", json={"termino": "   "})

    assert respuesta.status_code == 400
    assert respuesta.json()["ok"] is False and respuesta.json()["que_hacer"]
    assert doyle.pedidos == []


def test_doyle_caido_al_pedir_es_un_hueco_con_su_tipo_y_que_hacer(cliente, doyle):
    doyle.falla = RuntimeError("postgresql://usuario:SECRETO@host")

    respuesta = cliente.post("/api/buscar", json={"termino": EAN})

    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert cuerpo["detalle"] == "Doyle no responde (RuntimeError)"
    assert cuerpo["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text


def test_la_pantalla_sondea_hasta_que_los_cuatro_terminan(cliente, doyle, almacen):
    """Sin vueltas, una implementación que preguntara una vez pasaría en verde
    — contra el Doyle real se quedaría con cuatro "buscando…"."""
    almacen.catalogo_en_memoria = [_producto()]
    doyle.vueltas_por_termino = {EAN: [
        {p: respuesta_pendiente(p) for p in LOS_CUATRO},
        {
            "nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")]),
            "levic": respuesta_con_sesion_caducada("levic"),
            "vicma": respuesta_lista("vicma", []),
            "quepharma": respuesta_lista("quepharma", [("QP-77", "90.00", "DISPONIBLE")]),
        },
    ]}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]

    primera = cliente.get(f"/api/buscar/{job_id}").json()
    segunda = cliente.get(f"/api/buscar/{job_id}").json()

    assert primera["terminada"] is False
    assert segunda["terminada"] is True
    nadro, levic, vicma, quepharma = segunda["proveedores"]
    assert nadro["filas"][0]["nuestro"]["frase"].startswith("Nuestro: PARACETAMOL")
    assert quepharma["filas"][0]["nuestro"] is None
    assert levic["sesion_caducada"] is True
    assert vicma["etiqueta"] == "sin resultados"
    assert segunda["lo_buscado"]["cuantos"] == 1


def test_una_busqueda_que_doyle_olvido_se_dice_y_manda_a_buscar_otra_vez(cliente):
    cuerpo = cliente.get("/api/buscar/trabajo-99").json()

    assert cuerpo["ok"] is False
    assert cuerpo["detalle"] == BUSQUEDA_OLVIDADA
    assert cuerpo["que_hacer"] == busqueda.QUE_HACER_CON_LA_OLVIDADA


def test_un_job_id_que_saldria_de_la_ruta_no_llega_a_doyle(cliente, doyle):
    respuesta = cliente.get("/api/buscar/a.b")

    assert respuesta.status_code == 400
    assert respuesta.json()["que_hacer"]
    assert doyle.consultas == []


def test_doyle_caido_al_preguntar_es_un_hueco_con_que_hacer(cliente, doyle):
    doyle.resultados_por_termino = {EAN: {"nadro": respuesta_pendiente("nadro")}}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]
    doyle.falla = RuntimeError("SECRETO")

    respuesta = cliente.get(f"/api/buscar/{job_id}")

    assert respuesta.json()["ok"] is False
    assert respuesta.json()["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text


def test_el_almacen_caido_no_esconde_los_resultados_y_dice_que_no_sabe_que_es_nuestro(
    cliente, doyle, almacen
):
    doyle.resultados_por_termino = {EAN: {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")])}}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]
    almacen.falla = RuntimeError("SECRETO")

    respuesta = cliente.get(f"/api/buscar/{job_id}")

    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["proveedores"][0]["filas"][0]["cifras"][0] == "Compra $86.05"
    assert cuerpo["proveedores"][0]["filas"][0]["nuestro"] is None
    assert cuerpo["catalogo_sin_leer"]["que_hacer"] == que_hacer(AL_LEER, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text


def test_buscar_no_escribe_nada_en_el_pedido(cliente, doyle, almacenamiento):
    """Mirar no es pedir: ni una lista, ni un precio congelado."""
    doyle.resultados_por_termino = {EAN: {"nadro": respuesta_lista("nadro", [(EAN, "86.05", "40")])}}
    job_id = cliente.post("/api/buscar", json={"termino": EAN}).json()["job_id"]
    cliente.get(f"/api/buscar/{job_id}")

    assert almacenamiento.listas == [] and almacenamiento.precios == []


# =========================================================================
# 4. LA PANTALLA
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_las_pestanas_se_llaman_como_el_glosario():
    """"Pedido" y no "Órdenes": el glosario manda sobre el nombre (decisión
    del dueño, 2026-09-28).

    Desde el diseño del 2026-09-30 las pestañas van en una barra lateral, en
    dos grupos: "Pedido" —la lista del día y lo que viene en camino— y
    "Proveedores". Más el estado, abajo, que no lleva rótulo de texto suelto
    sino su tarjeta."""
    pantalla = pantalla_completa()

    [pestanas] = re.findall(r'<nav class="pestanas" role="tablist".*?</nav>', pantalla, re.S)
    rotulos = re.findall(r'role="tab"[^>]*>([^<]+)', pestanas)
    grupos = re.findall(r'data-grupo="([^"]+)"', pestanas)

    assert rotulos == ["Lista del día", "En camino", "Buscar", "Vigilancia", "Sesiones"]
    assert grupos == ["Pedido", "Proveedores"]
    assert "rdenes" not in pestanas


def test_la_pestana_de_buscar_nace_escondida_y_la_del_pedido_no():
    """Sin JavaScript —o antes de que cargue— se ve el pedido, que es la
    pantalla de siempre."""
    pantalla = pantalla_completa()
    [buscar] = re.findall(r'<section id="panel-buscar"[^>]*>', pantalla)
    [pedido] = re.findall(r'<section id="panel-pedido"[^>]*>', pantalla)

    assert " hidden" in buscar
    assert " hidden" not in pedido


def test_la_pestana_sigue_a_la_direccion_aunque_la_pagina_no_se_recargue():
    """De `#pedido` a `#buscar` sin recargar, la carga no vuelve a correr: la
    dirección decía Buscar con el pedido a la vista. Lo cazó el recorrido del
    navegador el 2026-09-28."""
    script = _script()

    assert "addEventListener('hashchange'" in script
    assert "location.hash.slice(1)" in script


def test_la_pantalla_dice_que_mirar_no_es_pedir():
    assert "no entra a la lista" in pantalla_completa()


def test_la_pantalla_sondea_con_lo_que_dice_el_servidor():
    """Cada cuánto, hasta cuándo y qué decir al tope: del servidor. La pantalla
    no inventa ni el número ni la frase."""
    script = _script()

    for llave in ("sondeo_ms", "tope_segundos", "frase_al_tope", "datos.terminada"):
        assert llave in script, llave
    assert "respuestaDe(fetch('/api/buscar'" in script


def test_la_pantalla_de_buscar_pinta_las_frases_del_servidor():
    script = _script()

    for llave in ("p.que_paso", "p.etiqueta", "f.cifras", "f.nuestro", "catalogo_sin_leer", "lo_buscado"):
        assert llave in script, llave


def test_la_sesion_caducada_de_una_busqueda_reusa_los_botones_de_la_lista():
    """Los mismos «Abrir sesión» y «Ya entré» (ADR 0018: un portal a la vez),
    escribiendo su resultado en la pestaña de Buscar y no en la del pedido."""
    script = _script()

    assert "abrirSesion(p, b, 'buscar-accion')" in script
    assert "confirmarSesion(p, b, 'buscar-accion')" in script
