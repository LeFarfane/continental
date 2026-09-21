"""El primer precio real dentro de Continental: congelado, con motivo (ticket 12).

**Ninguna prueba de este archivo le habla a Doyle, duerme un segundo, ni toca
Postgres.** Las tres cosas son la misma regla del repo y las tres se resuelven
por inyección:

- Doyle se sustituye por `DoyleFalso`, que respeta el contrato de dos tiempos
  —acuse primero, estado después— y sabe representar los **cuatro finales**:
  listo con filas, error, sesión caducada y todavía buscando.
- La espera entra por argumento. `consultar_a_doyle` recibe `dormir` y `ahora`,
  y las pruebas que miden el tope pasan un reloj que **avanza cuando alguien
  duerme**: un sondeo de ciento veinte segundos simulados cuesta microsegundos
  reales. Si una prueba de aquí llegara a tardar, está mal planteada.
- El hilo se sustituye por un lanzador que ejecuta la tarea ahí mismo (la
  fixture `consultas` de `conftest.py`). Con hilos de verdad habría que
  esperar —que es dormir— o sincronizar con un `Event`, y eso probaría la
  sincronización y no el código.

Lo que este archivo **no** puede hacer es ejecutar el SQL: desde la torre no
hay Postgres alcanzable (verificado el 2026-09-19). Lo que sí hace, como
`test_guardado.py` y `test_descarte.py`, es revisar las sentencias como texto y
apoyarse en que las reglas de la tabla viven una sola vez —`columnas_del_precio`
y `revisar_el_precio` en `almacenamiento.py`— y las llaman las dos
implementaciones.

**Dos afirmaciones de este archivo valen más que el resto** y conviene
señalarlas:

1. `test_una_consulta_que_falla_no_borra_un_precio_bueno`. Es la decisión de
   diseño del ticket —la tabla agrega y nunca pisa— escrita como el caso
   ordinario que la rompería: se consulta a las 8 y hay precio, a las 9 la
   sesión ya caducó. Con un `UPDATE`, el precio bueno se habría perdido por
   intentar mejorarlo, sin un solo error que ver.
2. `test_un_proveedor_que_sigue_buscando_no_cuenta_como_terminado`. Es el
   desencuentro real con Doyle que este ticket encontró: Doyle emite
   `buscando`, no `pendiente`, durante casi toda la búsqueda. Sin esto, el
   primer sondeo habría dado por terminada una búsqueda de cero segundos y
   habría congelado cuatro huecos llamándolo éxito.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_servida
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    PrecioDeProveedor,
    columnas_del_precio,
    revisar_el_precio,
    ultimo_por_proveedor,
)
from continental.consultas import (
    EN_CURSO,
    GUARDADA,
    SIN_GUARDAR,
    RegistroDeConsultas,
    consultar_a_doyle,
    consultar_y_congelar,
)
from continental.dobles import (
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_en_reconocimiento,
    respuesta_lista,
    respuesta_pendiente,
)
from continental.doyle import (
    ESTADOS_PENDIENTES,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
)
from continental.precios import (
    MOTIVOS,
    NO_EMPAREJA,
    PORTAL_SIN_CONTESTAR,
    PRECIO_ILEGIBLE,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_SELECTORES,
    SIN_TIEMPO,
    VARIOS_RESULTADOS,
    LecturaDePrecio,
    congelar,
    existencia_a_numero,
    leer_el_precio,
    precio_a_numero,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0003-precio-congelado-por-renglon-y-proveedor.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

#: Los cuatro del glosario, con la clave que usa Doyle.
LOS_CUATRO = ("levic", "nadro", "quepharma", "vicma")

CLAVE = "7501000000001"


# ------------------------------------------------------------- utilidades


def _reloj():
    """Un reloj que **solo avanza cuando alguien duerme**. Devuelve `(ahora, dormir)`.

    Es lo que vuelve instantánea una prueba de una espera de dos minutos, y es
    más honesto que un `monkeypatch` de `time.sleep`: mide exactamente lo que
    el código pidió esperar, ni un segundo más.
    """
    transcurrido = [0.0]

    def ahora() -> float:
        return transcurrido[0]

    def dormir(segundos: float) -> None:
        transcurrido[0] += segundos

    return ahora, dormir


def _consultar(cliente, renglon_id: int):
    """El clic del botón. Sin cuerpo: la clave sale del renglón guardado."""
    return cliente.post(f"/api/renglon/{renglon_id}/precio")


def _mirar(cliente, renglon_id: int):
    """Lo que sondea la pantalla: cómo va y qué hay congelado."""
    return cliente.get(f"/api/renglon/{renglon_id}/precio")


def _lista(cliente) -> dict:
    return cliente.get(RUTA).json()


def _primer_renglon(cliente) -> dict:
    return _lista(cliente)["renglones"][0]


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str, existencia: float = 10.0) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=existencia,
        esta_activo=True,
        es_granel=False,
    )


def _poblar(almacen, clave: str = CLAVE) -> None:
    """Un solo producto vendido hoy, con EAN: el renglón que se va a consultar."""
    almacen.catalogo_en_memoria = [_producto(1, clave)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3)]


def _los_cuatro_contestan(doyle, clave: str = CLAVE) -> None:
    """Los cuatro finales en una sola búsqueda, que es el caso realista.

    NADRO da precio, LEVIC falla, QuePharma tiene la sesión caída y VICMA
    devuelve dos resultados. Un solo caso feliz habría dejado sin ejercitar
    justo los tres que el encargado tiene que poder distinguir.
    """
    doyle.resultados_por_termino[clave] = {
        "nadro": respuesta_lista("nadro", [(clave, "86.05", "40")]),
        "levic": respuesta_con_error("levic", "el portal no cargó"),
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
        "vicma": RespuestaDeProveedor(
            proveedor="vicma",
            estado="listo",
            filas=(
                FilaDeProveedor("A-1", "CAJA 30", "100.00", "", "5"),
                FilaDeProveedor("A-2", "CAJA 60", "180.00", "", "5"),
            ),
            total=2,
        ),
    }


def _texto(ruta: Path) -> str:
    """El archivo como texto, exigiendo UTF-8 — igual que `test_sql_del_pedido`."""
    return ruta.read_bytes().decode("utf-8")


# ====================================================================
# CASILLA 1 — un botón por renglón pide la consulta contra los cuatro
# ====================================================================


def test_un_clic_le_pide_a_doyle_la_busqueda_con_la_clave_del_renglon(
    cliente, almacen, doyle
):
    """La clave y nada más: el EAN es lo único que empareja (ADR 0002).

    No se busca por descripción ni por `producto_id`. "PARACETAMOL 500MG" en el
    portal de un proveedor trae el de otro laboratorio y otra presentación, y
    la comparación diría cualquier cosa.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon = _primer_renglon(cliente)

    respuesta = _consultar(cliente, renglon["renglon_id"])

    assert respuesta.status_code == 200
    assert doyle.pedidos == [CLAVE], (
        f"Se le pidió a Doyle {doyle.pedidos!r} en vez de la clave del renglón. "
        "El EAN es lo único que significa lo mismo en nuestro catálogo y en el "
        "del proveedor."
    )


def test_los_cuatro_proveedores_quedan_guardados_aunque_solo_uno_de_precio(
    cliente, almacen, doyle, almacenamiento
):
    """Cuatro filas, no una. Es lo que hace posible el conteo del ticket 15.

    Guardar solo al que dio precio haría indistinguible "a LEVIC no se le
    preguntó" de "LEVIC no contestó", y el ticket 15 tiene que decir contra
    cuántos proveedores se comparó cada renglón.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon = _primer_renglon(cliente)

    _consultar(cliente, renglon["renglon_id"])

    guardados = almacenamiento.precios_del_renglon(NEGOCIO, renglon["renglon_id"])
    assert tuple(p.proveedor for p in guardados) == LOS_CUATRO
    assert sum(1 for p in guardados if not p.sin_dato) == 1


def test_la_pantalla_trae_el_boton_de_consultar_precio_por_renglon(cliente):
    """Lo que se puede afirmar sobre el HTML sin ejecutar su JavaScript."""
    pagina = pantalla_servida(cliente)

    assert "Consultar precio" in pagina
    assert "Volver a consultar" in pagina
    assert "'/precio'" in pagina or "/precio'" in pagina
    assert "Precio de proveedor" in pagina


def test_continental_no_abre_un_navegador_para_esto(cliente):
    """ADR 0001: Continental no scrapea. El que abre Chrome es Doyle.

    Se revisa sobre el paquete entero y no solo sobre lo nuevo: la regla 1 de
    `CLAUDE.md` dice que el día que aparezca un `import playwright` aquí, la
    decisión se rompió — y este es el primer ticket que tenía una razón para
    tentarse, porque es el primero que necesita un dato de un portal.
    """
    fuentes = [
        f.read_text(encoding="utf-8")
        for f in (RAIZ / "src" / "continental").rglob("*.py")
    ]
    colados = [t for t in fuentes if re.search(r"^\s*(import|from)\s+playwright", t, re.M)]

    assert not colados, (
        "Apareció un import de playwright en Continental. El ADR 0001 dice que "
        "el que scrapea es Doyle y que esto se le pide por HTTP."
    )


# ====================================================================
# CASILLA 2 — Doyle no contesta de golpe y la pantalla no se cuelga
# ====================================================================


def test_pedir_el_precio_contesta_de_inmediato_con_la_consulta_en_curso(
    cliente, almacen, doyle, consultas
):
    """La petición vuelve antes de que Doyle termine, y lo dice.

    Se fuerza con un lanzador que **no** ejecuta la tarea: es lo que pasa de
    verdad, donde el hilo todavía no llegó a ninguna parte cuando la respuesta
    ya salió. Sin esto, la prueba mediría el lanzador síncrono del suite y no
    el contrato de la ruta.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    consultas.lanzar = lambda tarea: None
    renglon = _primer_renglon(cliente)

    cuerpo = _consultar(cliente, renglon["renglon_id"]).json()

    assert cuerpo["ok"] is True
    assert cuerpo["consulta"]["estado"] == EN_CURSO
    assert cuerpo["consulta"]["en_curso"] is True
    assert cuerpo["precios"] == []


def test_se_sondea_hasta_que_doyle_termina_y_no_se_cree_la_primera_vuelta(doyle):
    """Tres vueltas: buscando, buscando, listo. Se congela la tercera.

    Es el contrato de dos tiempos con todas sus letras. Una implementación que
    preguntara una sola vez y se quedara con lo primero que ve pasaría contra
    un doble que contesta de golpe — y contra el Doyle real congelaría cuatro
    huecos, porque los ~9 s del piso se pasan enteros en `buscando`.
    """
    doyle.vueltas_por_termino[CLAVE] = [
        {"nadro": respuesta_pendiente("nadro")},
        {"nadro": respuesta_pendiente("nadro")},
        {"nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])},
    ]
    ahora, dormir = _reloj()

    resultado = consultar_a_doyle(doyle, CLAVE, dormir=dormir, ahora=ahora)

    assert len(doyle.consultas) == 3
    assert resultado.lecturas[0].precio == Decimal("86.05")
    assert resultado.detalle == ""
    # Durmió dos veces entre las tres vueltas, un segundo cada una. Se afirma
    # el número: una espera que se duplicara por un `dormir` de más pasaría
    # callada y en producción serían minutos.
    assert ahora() == pytest.approx(2.0)


def test_un_proveedor_que_sigue_buscando_no_cuenta_como_terminado():
    """EL DESENCUENTRO CON EL DOYLE REAL, escrito como prueba.

    Doyle crea el trabajo con `pendiente` y el hilo lo mueve a **`buscando`** en
    su primera línea (`_buscar_en_hilo`, revisado el 2026-09-19). Antes de este
    ticket, `terminada` preguntaba solo por `pendiente`: contra el Doyle real
    habría dado cierto en la primera vuelta, con los cuatro proveedores todavía
    abriendo el portal, y el precio se habría congelado como cuatro huecos. Un
    lote en verde que no consultó nada.
    """
    assert "buscando" in ESTADOS_PENDIENTES
    assert "pendiente" in ESTADOS_PENDIENTES

    buscando = EstadoDeBusqueda(
        termino=CLAVE, proveedores={"nadro": respuesta_pendiente("nadro", "buscando")}
    )
    assert buscando.terminada is False

    lista = EstadoDeBusqueda(
        termino=CLAVE,
        proveedores={"nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])},
    )
    assert lista.terminada is True


def test_una_busqueda_sin_proveedores_no_esta_terminada():
    """El `all()` de una colección vacía es cierto, y aquí eso mentiría.

    Doyle contesta con los cuatro proveedores en cuanto existe el trabajo, así
    que un diccionario vacío significa que la respuesta no trae lo que debía.
    Declararla terminada congelaría cero precios y lo llamaría éxito.
    """
    assert EstadoDeBusqueda(termino=CLAVE, proveedores={}).terminada is False


def test_la_espera_se_corta_en_el_tope_y_lo_que_falto_dice_por_que(doyle):
    """Ni colgado para siempre, ni tirando lo que sí llegó.

    NADRO contestó y VICMA sigue buscando cuando se acaba el tiempo: se
    congelan los dos, uno con precio y el otro con `no alcanzó el tiempo` — que
    es el motivo que la historia 31 pide distinguir de "el portal falló",
    porque uno se resuelve volviendo a consultar y el otro no.
    """
    doyle.vueltas_por_termino[CLAVE] = [
        {
            "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")]),
            "vicma": respuesta_pendiente("vicma"),
        }
    ]
    ahora, dormir = _reloj()

    resultado = consultar_a_doyle(
        doyle, CLAVE, tope_seg=10, cada_seg=1, dormir=dormir, ahora=ahora
    )

    por_proveedor = {lectura.proveedor: lectura for lectura in resultado.lecturas}
    assert por_proveedor["nadro"].precio == Decimal("86.05")
    assert por_proveedor["vicma"].motivo == SIN_TIEMPO
    assert por_proveedor["vicma"].precio is None
    assert "10 s" in resultado.detalle
    # No esperó ni un segundo más del tope. Una espera que se pasara de largo
    # sería un renglón colgado en la pantalla sin que nadie sepa hasta cuándo.
    assert ahora() == pytest.approx(10.0)


def test_recargar_la_pagina_no_pierde_lo_que_doyle_ya_contesto(
    cliente, almacen, doyle
):
    """El precio congelado viaja **dentro del renglón** en la carga de la lista.

    Es la mitad de la decisión que se ve: quien espera a Doyle es el servidor y
    escribe la fila en cuanto llega, así que cerrar la pestaña a la mitad no
    tira la consulta. Lo que se muestra es lo guardado.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon = _primer_renglon(cliente)
    _consultar(cliente, renglon["renglon_id"])

    # Una carga nueva, como una recarga del navegador.
    recargada = _primer_renglon(cliente)

    assert [p["proveedor"] for p in recargada["precios"]] == list(LOS_CUATRO)
    assert next(p for p in recargada["precios"] if p["proveedor"] == "nadro")[
        "precio"
    ] == "86.05"


def test_pedir_dos_veces_el_mismo_renglon_no_visita_los_portales_dos_veces(
    cliente, almacen, doyle, consultas
):
    """Dos clics nerviosos serían ocho visitas en lugar de cuatro.

    Doyle abre navegadores de verdad contra los portales con las credenciales
    del dueño. Mientras una consulta esté en vuelo, el segundo clic devuelve
    **esa misma** consulta y lo dice con `nueva: false` — una pantalla que
    dijera "pedido" dos veces para una sola visita estaría mintiendo.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    consultas.lanzar = lambda tarea: None
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    primera = _consultar(cliente, renglon_id).json()
    segunda = _consultar(cliente, renglon_id).json()

    assert primera["nueva"] is True
    assert segunda["nueva"] is False
    assert doyle.pedidos == [], "El lanzador no corrió: nadie debió llamar a Doyle."


def test_una_consulta_ya_terminada_si_deja_pedir_otra(cliente, almacen, doyle):
    """Lo que se impide es la consulta DUPLICADA, no la segunda consulta.

    "Volver a consultar los precios que faltan para completarlos en la mañana"
    es la historia 24 del spec: un renglón que ya se consultó tiene que poder
    volver a consultarse.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    assert _consultar(cliente, renglon_id).json()["nueva"] is True
    assert _consultar(cliente, renglon_id).json()["nueva"] is True
    assert doyle.pedidos == [CLAVE, CLAVE]


def test_la_ruta_de_mirar_dice_como_va_y_lo_que_hay_guardado(cliente, almacen, doyle):
    """Las dos cosas en una respuesta: es lo que sondea la pantalla.

    Separarlas obligaría al navegador a decidir cuál tiene razón cuando no
    coincidan —"terminada" con los precios de antes, o "en curso" con los de
    después—. Aquí salen de la misma lectura.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    cuerpo = _mirar(cliente, renglon_id).json()

    assert cuerpo["consulta"]["estado"] == GUARDADA
    assert cuerpo["consulta"]["en_curso"] is False
    assert len(cuerpo["precios"]) == 4


def test_mirar_un_renglon_que_nadie_consulto_no_es_un_error(cliente, almacen):
    """Sin consulta y sin precios: es un dato, no un fallo.

    Es lo que el ticket 15 va a contar como *sin comparar*, y por eso no puede
    verse como una falla ni como una lista vacía de proveedores caros.
    """
    _poblar(almacen)
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    cuerpo = _mirar(cliente, renglon_id).json()

    assert cuerpo["ok"] is True
    assert cuerpo["consulta"] is None
    assert cuerpo["precios"] == []


# ====================================================================
# CASILLA 3 — el precio se guarda CONGELADO, con el momento de la lectura
# ====================================================================


def test_el_precio_se_guarda_con_el_instante_en_que_se_leyo(
    cliente, almacen, doyle, almacenamiento
):
    """Sin el instante, "$86.05 en NADRO" no dice si se leyó hoy o hace un mes.

    El instante es lo que vuelve congelada a una cifra: *un pedido dice a qué
    precio se decidió, no a cómo está hoy*.
    """
    antes = dt.datetime.now(dt.UTC)
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)

    nadro = next(
        p
        for p in almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)
        if p.proveedor == "nadro"
    )
    assert nadro.consultado_en >= antes
    assert nadro.consultado_en.tzinfo is not None, (
        "El instante viaja sin zona. El contenedor corre en UTC y sin zona el "
        "navegador lo leería seis horas en el futuro."
    )


def test_los_cuatro_proveedores_comparten_el_instante_de_su_consulta(
    cliente, almacen, doyle, almacenamiento
):
    """Fue UNA lectura, así que es UN instante.

    Es lo que `now()` da gratis del lado real —es la hora de la transacción— y
    lo que el doble copia a mano. Cuatro instantes distintos harían que la
    pantalla mostrara cuatro fechas donde hubo una, y que el ticket 14 no
    supiera cuál poner al lado de la comparación.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)

    instantes = {
        p.consultado_en for p in almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)
    }
    assert len(instantes) == 1


def test_una_segunda_consulta_agrega_y_no_pisa_la_anterior(
    cliente, almacen, doyle, almacenamiento
):
    """CONGELADO QUIERE DECIR CONGELADO: la tabla solo crece.

    Ocho filas después de dos consultas, no cuatro. Lo que la comparación usa
    es la más reciente de cada proveedor, y lo que sigue estando es la cifra
    que el encargado vio cuando decidió.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)
    _consultar(cliente, renglon_id)

    assert len(almacenamiento.precios) == 8, (
        "La segunda consulta pisó a la primera. Esta tabla AGREGA: el precio al "
        "que se decidió comprar tiene que seguir ahí, y un UPDATE haría que una "
        "consulta fallida borrara un precio bueno."
    )
    # Y lo que se lee sigue siendo uno por proveedor.
    assert len(almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)) == 4


def test_una_consulta_que_falla_no_borra_un_precio_bueno(
    cliente, almacen, doyle, almacenamiento
):
    """EL CASO ORDINARIO QUE UN `UPDATE` ROMPERÍA, escrito entero.

    A las 8 NADRO da $86.05. A las 9 alguien vuelve a consultar y la sesión ya
    caducó. Con una sola fila por proveedor, el $86.05 se convertiría en un
    hueco: se habría perdido el dato **por intentar mejorarlo**, sin un solo
    error que ver. Con la tabla que agrega, el precio viejo sigue guardado y lo
    que se muestra es la lectura nueva con su motivo — las dos cosas son
    ciertas y ninguna borra a la otra.
    """
    _poblar(almacen)
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])
    }
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_con_sesion_caducada("nadro")
    }
    _consultar(cliente, renglon_id)

    todas = [p for p in almacenamiento.precios if p["proveedor"] == "nadro"]
    assert [p["precio"] for p in todas] == [Decimal("86.05"), None], (
        "El precio bueno desapareció al volver a consultar con la sesión caída."
    )
    ultima = almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)[0]
    assert ultima.motivo == SESION_CADUCADA


def test_la_comparacion_usa_la_lectura_mas_reciente_de_cada_proveedor():
    """`ultimo_por_proveedor` es el `DISTINCT ON` del SQL, en Python.

    Vive en `almacenamiento.py` y lo llaman las dos implementaciones: si cada
    una eligiera con su propia regla, el suite quedaría en verde y la pantalla
    mostraría otro precio en atlas.
    """
    viejo = dt.datetime(2024, 3, 5, 8, 0, tzinfo=dt.UTC)
    nuevo = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)
    filas = [
        PrecioDeProveedor(1, "nadro", viejo, "86.05", Decimal("86.05")),
        PrecioDeProveedor(1, "nadro", nuevo, "91.00", Decimal("91.00")),
        PrecioDeProveedor(1, "levic", viejo, "146.38", Decimal("146.38")),
    ]

    ultimas = ultimo_por_proveedor(filas)

    assert [(p.proveedor, p.precio) for p in ultimas] == [
        ("levic", Decimal("146.38")),
        ("nadro", Decimal("91.00")),
    ]


def test_los_precios_de_otra_lista_no_se_cuelan_en_esta(
    cliente, almacen, doyle, almacenamiento
):
    """La lectura de la lista trae los precios de SUS renglones y de nadie más.

    Es el `join` contra `renglon` del `_LEER_PRECIOS`, que el doble copia
    filtrando por los renglones de esa lista.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    lista = _lista(cliente)
    _consultar(cliente, lista["renglones"][0]["renglon_id"])

    de_la_lista = almacenamiento.precios_de_la_lista(
        NEGOCIO, lista["pedido_sugerido_id"]
    )
    assert set(de_la_lista) == {lista["renglones"][0]["renglon_id"]}
    assert almacenamiento.precios_de_la_lista(NEGOCIO, 999) == {}


def test_descartar_un_renglon_no_le_borra_el_precio_de_la_pantalla(
    cliente, almacen, doyle
):
    """El renglón que vuelve de `/descartar` trae sus precios congelados.

    La pantalla sustituye el renglón entero por el que llega, así que un
    renglón sin precios borraría de la vista datos que siguen en la tabla — y
    un dato que desaparece de la pantalla sin desaparecer de la base es peor
    que uno que nunca estuvo: nadie sabe cuál de los dos creer.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    movido = cliente.post(f"/api/renglon/{renglon_id}/descartar").json()

    assert len(movido["renglon"]["precios"]) == 4


# ====================================================================
# CASILLA 4 — se guarda también la existencia que reporta el proveedor
# ====================================================================


def test_se_guarda_la_existencia_que_reporta_el_proveedor(
    cliente, almacen, doyle, almacenamiento
):
    """El más barato no sirve si no lo tiene (historia 21 del spec)."""
    _poblar(almacen)
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])
    }
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)

    nadro = almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)[0]
    assert nadro.existencia_como_llego == "40"
    assert nadro.existencia == Decimal("40.000")


def test_una_existencia_que_no_es_un_numero_no_tira_el_precio(
    cliente, almacen, doyle, almacenamiento
):
    """Los portales dicen "+100" o "Disponible", y eso no invalida el precio.

    El texto se guarda siempre; el número es un extra. Que la existencia no se
    pueda convertir NUNCA es motivo para quedarse sin precio — sería tirar el
    dato que costó nueve segundos por una palabra.
    """
    _poblar(almacen)
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "Disponible")])
    }
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)

    nadro = almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)[0]
    assert nadro.precio == Decimal("86.05")
    assert nadro.existencia_como_llego == "Disponible"
    assert nadro.existencia is None
    assert nadro.motivo is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("40", Decimal("40.000")),
        ("+100", Decimal("100.000")),
        ("1,200", Decimal("1200.000")),
        ("0", Decimal("0.000")),
        ("Disponible", None),
        ("No disponible", None),
        ("—", None),  # lo que Doyle manda cuando el portal no dijo nada
        ("", None),
    ],
)
def test_la_existencia_se_lee_cuando_se_puede_y_el_cero_si_es_un_dato(texto, esperado):
    """Un cero de existencia **sí** se conserva, y no se parece a un precio en cero.

    "El proveedor no lo tiene" es un hecho y decide una compra; un precio en
    cero es un portal que no supo decir cuánto cuesta.
    """
    assert existencia_a_numero(texto) == esperado


# ====================================================================
# CASILLA 5 — sin precio con su motivo, NUNCA un cero ni un hueco mudo
# ====================================================================


def test_doyle_caido_deja_el_renglon_sin_precio_y_la_pantalla_lo_dice(
    cliente, almacen, doyle, almacenamiento
):
    """Regla 4 de `CLAUDE.md`: un hueco con su motivo, nunca una lista vacía.

    No se guarda ninguna fila —no se sabe ni a qué proveedores se le preguntó—
    y la consulta queda en `sin guardar` con su motivo. Eso lo pinta la
    pantalla; lo que **no** pasa es que el renglón se quede con un cero o con
    una celda vacía que se lee "no tiene precio en ningún lado".
    """
    _poblar(almacen)
    doyle.falla = TimeoutError("no contestó")
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    cuerpo = _consultar(cliente, renglon_id).json()

    assert cuerpo["ok"] is True
    assert cuerpo["consulta"]["estado"] == SIN_GUARDAR
    assert cuerpo["consulta"]["detalle"]
    assert cuerpo["precios"] == []
    assert almacenamiento.precios == []


def test_el_detalle_de_una_falla_nuestra_no_viaja_al_navegador(
    cliente, almacen, doyle
):
    """Regla 5: al cliente el tipo genérico, el detalle al log.

    Esto corre detrás de un túnel y un `str(exc)` de SQLAlchemy lleva la cadena
    de conexión con contraseña. El mensaje de Doyle sí viaja —lo redacta para
    que una persona lo lea, historia 23— y es otra cosa.
    """
    _poblar(almacen)
    doyle.falla = RuntimeError("postgresql://continental:SUPERSECRETA@atlas/farmacia")
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    cuerpo = _consultar(cliente, renglon_id).json()

    assert "SUPERSECRETA" not in str(cuerpo)
    assert "RuntimeError" in cuerpo["consulta"]["detalle"]


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        (respuesta_con_error("levic", "el portal no cargó"), PORTAL_SIN_CONTESTAR),
        (respuesta_con_sesion_caducada("nadro"), SESION_CADUCADA),
        (respuesta_en_reconocimiento("quepharma"), SIN_SELECTORES),
        (respuesta_pendiente("vicma"), SIN_TIEMPO),
        (RespuestaDeProveedor("nadro", "listo", (), 0), SIN_RESULTADOS),
    ],
)
def test_cada_final_de_doyle_deja_su_propio_motivo(respuesta, motivo):
    """Cinco finales, cinco motivos, y cada uno lleva a una acción distinta.

    Si dos motivos se atendieran igual, sobraría uno. `la sesión caducó` la
    arregla el encargado en dos clics; `el portal no contestó` se reintenta;
    `no se sabe leer la página` se arregla escribiendo selectores; `no alcanzó
    el tiempo` se arregla volviendo a consultar; `sin resultados` no lo arregla
    nadie y el hueco es la respuesta correcta.
    """
    lectura = leer_el_precio(respuesta, CLAVE)

    assert lectura.motivo == motivo
    assert lectura.precio is None


def test_el_mensaje_real_de_una_sesion_caida_se_reconoce_como_tal():
    """El texto EXACTO que el Doyle real devolvió el 2026-09-19, sin retocar.

    Se pegó de una corrida de verdad contra los cuatro portales —las cuatro
    sesiones estaban caducadas, con marcadores de agosto— y va entero, con sus
    saltos de línea y sus instrucciones, porque eso es lo que llega.

    Prueba dos cosas de golpe: que el motivo sale `la sesión caducó` —el único
    hueco que el encargado arregla él— y que el `detalle` que viaja a la
    pantalla es **la primera línea y acotado**, no las diez líneas de
    instrucciones que Doyle escribe para su propia interfaz.
    """
    real = (
        "[nadro] la sesión caducó (o el portal rechazó esta sesión): se pidió\n"
        "    https://i22.nadro.mx/{termino}?_q={termino}&map=ft\n"
        "y el portal dejó la página en\n"
        "    https://login.nadro.mx/login?lang=es&client_id=4k626...\n\n"
        "Ábrela de nuevo (un minuto, navegador visible) — o con el botón "
        "'Iniciar sesión' de la pestaña Inicio de la web:\n"
        "    python -m doyle.sesion --proveedor nadro\n"
    )

    lectura = leer_el_precio(
        RespuestaDeProveedor("nadro", "error", mensaje=real), CLAVE
    )

    assert lectura.motivo == SESION_CADUCADA
    assert "\n" not in lectura.detalle
    assert len(lectura.detalle) <= 201
    assert lectura.detalle.startswith("[nadro] la sesión caducó")


def test_una_falla_de_playwright_no_se_confunde_con_una_sesion_caida():
    """El otro mensaje real de esa misma corrida: LEVIC, con el navegador cerrado.

    No menciona la sesión, así que sale `el portal no contestó` — que es el
    motivo correcto y el que lleva a la acción correcta: volver a intentar, no
    ir a abrir una sesión que estaba bien.
    """
    real = (
        "falla inesperada: Page.wait_for_timeout: Target page, context or "
        "browser has been closed"
    )

    assert leer_el_precio(
        RespuestaDeProveedor("levic", "error", mensaje=real), CLAVE
    ).motivo == PORTAL_SIN_CONTESTAR


def test_la_sesion_caducada_se_distingue_del_portal_caido():
    """La distinción que más importa, dicha aparte.

    Las dos llegan como `error` —Doyle no tiene un estado propio para la sesión
    caída— y lo único que las separa es el mensaje. Confundirlas le quita al
    encargado el único hueco que puede resolver él (historia 33).
    """
    caida = leer_el_precio(respuesta_con_sesion_caducada("nadro"), CLAVE)
    portal = leer_el_precio(
        respuesta_con_error("nadro", "el portal no cargó"), CLAVE
    )

    assert caida.motivo == SESION_CADUCADA
    assert portal.motivo == PORTAL_SIN_CONTESTAR
    assert caida.motivo != portal.motivo


def test_varios_resultados_no_produce_precio_y_guarda_cuantos_fueron():
    """VICMA con dos resultados **no** produce precio (spec, ADR 0002).

    Y `resultados` guarda el 2, que es el dato con el que el ticket 13 decide:
    "VICMA se acepta únicamente si la búsqueda del EAN devuelve exactamente un
    resultado". La regla por proveedor y su tabla de casos viven en
    `tests/test_emparejamiento.py`; aquí se cuida que el número no se pierda.
    """
    respuesta = RespuestaDeProveedor(
        proveedor="vicma",
        estado="listo",
        filas=(
            FilaDeProveedor("A-1", "CAJA 30", "100.00", "", "5"),
            FilaDeProveedor("A-2", "CAJA 60", "180.00", "", "5"),
        ),
        total=2,
    )

    lectura = leer_el_precio(respuesta, CLAVE)

    assert lectura.motivo == VARIOS_RESULTADOS
    assert lectura.precio is None
    assert lectura.resultados == 2


def test_una_respuesta_real_de_doyle_se_lee_sin_perder_el_total():
    """La forma EXACTA que devuelve `buscador.buscar_producto` con `modo: consulta`.

    Copiada del Doyle real (`src/doyle/web/buscador.py`, revisado el
    2026-09-19), incluido el `imagen_url` que `FilaDeProveedor` no tiene y el
    `mostradas` que `_leer_respuesta` ignora: si un campo de más tronara la
    lectura, se descubriría en atlas y no aquí.

    Lo que esta prueba cuida con nombre y apellido es **el `total`**. Doyle lo
    calcula como `len(filas)` —todas las que encontró el portal— y corta
    `filas` en 20, así que las dos cifras son distintas a propósito. El ticket
    13 acepta VICMA "únicamente si la búsqueda del EAN devuelve exactamente un
    resultado", y ese uno es el `total`: perderlo aquí obligaría a releer el
    portal mañana o a mentir.
    """
    from continental.doyle import _leer_respuesta

    crudo = {
        "estado": "listo",
        "modo": "consulta",
        "filas": [
            {
                "clave": "7501349028234",
                "descripcion": "SIGDAN 0.05MG/18ML SOL SPRAY",
                "precio": "86.05",
                "precio_publico": "150.00",
                "existencia": "8700",
                "imagen_url": "https://ejemplo/imagen.png",
                "advertencia": "",
            }
        ],
        "total": 1,
        "mostradas": 1,
    }

    respuesta = _leer_respuesta("nadro", crudo)

    assert respuesta.estado == "listo"
    assert respuesta.total == 1
    assert respuesta.filas[0].clave == "7501349028234"
    assert respuesta.filas[0].precio == "86.05"

    lectura = leer_el_precio(respuesta, "7501349028234")
    assert lectura.precio == Decimal("86.05")
    assert lectura.existencia == Decimal("8700.000")
    assert lectura.resultados == 1
    assert lectura.motivo is None
    assert lectura.descripcion_del_proveedor == "SIGDAN 0.05MG/18ML SOL SPRAY"


def test_resultados_es_lo_que_encontro_el_portal_y_no_lo_que_doyle_trajo():
    """Doyle corta la lista en 20; `total` dice cuántas encontró de verdad.

    Con `len(filas)`, un portal con 43 resultados diría 20 — y el ticket 13,
    que compara ese número contra 1, estaría mirando un dato falso.
    """
    respuesta = RespuestaDeProveedor(
        proveedor="vicma",
        estado="listo",
        filas=tuple(
            FilaDeProveedor(f"A-{i}", "CAJA", "10.00", "", "5") for i in range(20)
        ),
        total=43,
    )

    assert leer_el_precio(respuesta, CLAVE).resultados == 43


def test_un_hueco_nunca_se_queda_sin_motivo():
    """Los seis finales posibles, y ninguno produce un `NULL` mudo.

    Es la afirmación que hace que un precio faltante sea información. Se
    comprueba sobre todos a la vez y no caso por caso, porque lo que no puede
    existir es **un camino** que devuelva `precio=None, motivo=None`.
    """
    finales = [
        respuesta_lista("nadro", [(CLAVE, "86.05", "40")]),
        respuesta_con_error("levic", "el portal no cargó"),
        respuesta_con_sesion_caducada("quepharma"),
        respuesta_en_reconocimiento("vicma"),
        respuesta_pendiente("nadro"),
        RespuestaDeProveedor("levic", "listo", (), 0),
        RespuestaDeProveedor("levic", "algo-que-doyle-estrene"),
    ]

    for respuesta in finales:
        lectura = leer_el_precio(respuesta, CLAVE)
        assert (lectura.precio is None) == (lectura.motivo is not None), (
            f"{respuesta.estado!r} produjo precio y motivo a la vez, o ninguno "
            "de los dos. Un precio faltante no es un NULL mudo."
        )
        if lectura.motivo is not None:
            assert lectura.motivo in MOTIVOS


def test_el_motivo_que_el_ticket_12_reservo_cabe_en_la_tabla():
    """`no empareja` estaba reservado antes de que nadie lo escribiera.

    Lo dejó puesto el ticket 12 y **lo escribe el 13**: el emparejamiento por
    EAN lo produce cada vez que llegan filas y ninguna es este producto, que es
    el final ordinario de QuePharma. Tenerlo en el `CHECK` desde el día anterior
    ahorró exactamente lo que costaba agregarlo después: una migración y una
    visita a atlas con credenciales de dueño (ADR 0003), porque el rol no puede
    alterar sus tablas.

    Quién lo produce se prueba en `tests/test_emparejamiento.py`. Lo que se
    cuida aquí es que la tabla lo acepte.
    """
    assert NO_EMPAREJA in MOTIVOS

    columnas = columnas_del_precio(
        LecturaDePrecio(proveedor="quepharma", motivo=NO_EMPAREJA, resultados=3),
        NEGOCIO,
        1,
    )
    revisar_el_precio(columnas)  # la tabla ya lo acepta


def test_un_estado_que_doyle_estrene_no_tumba_la_consulta():
    """Un vocabulario nuevo del otro lado no puede dejar sin pedido a la farmacia.

    Sale como "el portal no contestó" y con el estado desconocido escrito en el
    detalle: ni se truena, ni pasa callado.
    """
    lectura = leer_el_precio(RespuestaDeProveedor("nadro", "reiniciando"), CLAVE)

    assert lectura.motivo == PORTAL_SIN_CONTESTAR
    assert "reiniciando" in lectura.detalle


# ------------------------------------- el cero, que es el único que hace daño


@pytest.mark.parametrize("texto", ["0", "0.00", "0.0", "$0.00"])
def test_un_precio_en_cero_del_portal_no_se_guarda_como_precio(texto):
    """"0.00" no es un regalo: es un portal que no supo decir cuánto cuesta.

    Y un cero guardado ganaría toda comparación de "el más barato" y dispararía
    la compra equivocada. Sale `None`, que con su motivo es información.
    """
    assert precio_a_numero(texto) is None


def test_un_precio_en_cero_llega_a_la_fila_como_hueco_con_motivo():
    """El camino completo: fila con "0.00" → sin precio, con `precio ilegible`.

    Y el texto original se conserva, que es lo que permite ver DESPUÉS que el
    portal escribió un cero — un hueco sin su texto no se puede investigar.
    """
    lectura = leer_el_precio(
        respuesta_lista("nadro", [(CLAVE, "0.00", "40")]), CLAVE
    )

    assert lectura.precio is None
    assert lectura.motivo == PRECIO_ILEGIBLE
    assert lectura.precio_como_llego == "0.00"


def test_la_tabla_rechaza_un_cero_aunque_alguien_lo_arme_a_mano():
    """La segunda puerta para el mismo cero: `ck_precio_positivo`.

    `revisar_el_precio` es esa restricción escrita en Python, y es lo que
    impide que el doble sea más permisivo que Postgres: sin ella el suite
    quedaría en verde y el INSERT rebotaría en atlas.
    """
    columnas = columnas_del_precio(
        LecturaDePrecio(proveedor="nadro", precio_como_llego="0", precio=Decimal("0")),
        NEGOCIO,
        1,
    )

    with pytest.raises(ValueError, match="ck_precio_positivo"):
        revisar_el_precio(columnas)


def test_la_tabla_rechaza_un_hueco_sin_motivo():
    """`ck_precio_sin_dato`, en las dos direcciones."""
    sin_motivo = columnas_del_precio(LecturaDePrecio(proveedor="nadro"), NEGOCIO, 1)
    sin_motivo["motivo"] = None
    with pytest.raises(ValueError, match="ck_precio_sin_dato"):
        revisar_el_precio(sin_motivo)

    con_los_dos = columnas_del_precio(
        LecturaDePrecio(
            proveedor="nadro",
            precio_como_llego="86.05",
            precio=Decimal("86.05"),
            motivo=SIN_RESULTADOS,
        ),
        NEGOCIO,
        1,
    )
    with pytest.raises(ValueError, match="ck_precio_sin_dato"):
        revisar_el_precio(con_los_dos)


def test_la_tabla_rechaza_un_motivo_que_nadie_conoce():
    """El vocabulario es cerrado porque el ticket 15 cuenta huecos por motivo.

    Un conteo sobre texto libre cuenta faltas de ortografía.
    """
    columnas = columnas_del_precio(
        LecturaDePrecio(proveedor="nadro", motivo="ni idea"), NEGOCIO, 1
    )

    with pytest.raises(ValueError, match="ck_precio_motivo_conocido"):
        revisar_el_precio(columnas)


def test_la_tabla_rechaza_un_precio_sin_el_texto_del_que_salio():
    """`ck_precio_con_su_texto`: un número sin procedencia no se puede auditar."""
    columnas = columnas_del_precio(
        LecturaDePrecio(proveedor="nadro", precio=Decimal("86.05")), NEGOCIO, 1
    )

    with pytest.raises(ValueError, match="ck_precio_con_su_texto"):
        revisar_el_precio(columnas)


def test_la_cadena_vacia_se_guarda_como_nulo_y_no_como_dato():
    """La misma traducción que la clave del renglón, y por lo mismo.

    Una cadena vacía se compara igual que un dato y empareja con cualquier otra
    vacía. O hay texto o no se sabe.
    """
    columnas = columnas_del_precio(
        LecturaDePrecio(proveedor="nadro", motivo=SIN_RESULTADOS), NEGOCIO, 1
    )

    assert columnas["precio_como_llego"] is None
    assert columnas["existencia_como_llego"] is None
    assert columnas["detalle"] is None
    assert columnas["clave_del_proveedor"] is None
    revisar_el_precio(columnas)  # y con los nulos puestos, pasa


# ====================================================================
# NUMÉRICO, NO COMA FLOTANTE
# ====================================================================


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("86.05", Decimal("86.05")),
        ("1,234.50", Decimal("1234.50")),
        ("$86.05", Decimal("86.05")),
        ("$ 1,234.50", Decimal("1234.50")),
        ("\xa01,234.50", Decimal("1234.50")),
        ("1234", Decimal("1234.00")),
        ("146.38 MXN", Decimal("146.38")),
    ],
)
def test_el_precio_del_portal_se_convierte_a_decimal(texto, esperado):
    """Las formas en que un portal escribe un precio, y el `Decimal` que sale.

    El espacio duro (`\\xa0`) está en la lista a propósito: es con lo que muchos
    portales separan el símbolo de la cifra, no es un espacio normal, y
    `.strip()` no lo quita — la conversión fallaría por una razón invisible en
    la pantalla.
    """
    assert precio_a_numero(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "—",  # lo que Doyle manda cuando el portal no dijo nada (medido 2026-09-19)
        "No disponible",
        "Bajo pedido",
        "1.234,50",
        "Consultar",
        "-86.05",
        "86.05.10",
        "N/D",
        "$",
    ],
)
def test_un_precio_que_no_se_puede_leer_no_se_inventa(texto):
    """`None`, nunca un cero y nunca un número adivinado.

    `1.234,50` —formato europeo— es el caso que más importa: leerlo como
    `1.234` convertiría un producto de mil doscientos pesos en el más barato de
    los cuatro. Adivinar cuál separador es cuál sobre un solo número es
    imposible, y adivinar mal aquí compra al proveedor equivocado.
    """
    assert precio_a_numero(texto) is None


def test_el_precio_viaja_al_navegador_como_cadena_y_nunca_como_flotante(
    cliente, almacen, doyle
):
    """El JSON de JavaScript solo tiene coma flotante.

    Mandar `86.05` como número lo mete en coma flotante justo en el borde donde
    acababa de salir del `numeric(12,2)`. Como cadena se pinta tal cual, y el
    día que el ticket 14 sume ahorros va a sumar con la cifra exacta.
    """
    _poblar(almacen)
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "1,234.50", "40")])
    }
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    precio = _mirar(cliente, renglon_id).json()["precios"][0]

    assert precio["precio"] == "1234.50"
    assert isinstance(precio["precio"], str)
    assert precio["precio_como_llego"] == "1,234.50"


def test_el_precio_se_queda_en_decimal_de_punta_a_punta(
    cliente, almacen, doyle, almacenamiento
):
    """Ni un `float` en el camino: el dinero es `Decimal` o no es.

    En coma flotante `0.1 + 0.2` no es `0.3`, y un total de pedido deja de
    cuadrar contra la factura del proveedor por centavos que nadie puede
    explicar.
    """
    _poblar(almacen)
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])
    }
    renglon_id = _primer_renglon(cliente)["renglon_id"]

    _consultar(cliente, renglon_id)

    guardado = almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)[0]
    assert isinstance(guardado.precio, Decimal)
    assert not isinstance(guardado.precio, float)


# ====================================================================
# LO QUE NO SE CONSULTA, Y POR QUÉ
# ====================================================================


def test_un_renglon_sin_ean_no_se_consulta_y_se_dice_por_que(cliente, almacen, doyle):
    """Sin clave no hay con qué buscar, y buscar por nombre traería otro producto.

    Es el caso de los productos que el catálogo no conoce. El 422 explica qué
    hacer —ponerle la clave en SICAR— en vez de dejar un botón que no hace
    nada.
    """
    almacen.catalogo_en_memoria = []
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3)]
    renglon = _primer_renglon(cliente)
    assert renglon["clave"] == ""

    respuesta = _consultar(cliente, renglon["renglon_id"])

    assert respuesta.status_code == 422
    assert respuesta.json()["ok"] is False
    assert "código de barras" in respuesta.json()["detalle"]
    assert doyle.pedidos == []


def test_un_renglon_descartado_no_molesta_a_los_cuatro_portales(
    cliente, almacen, doyle
):
    """409 y ninguna visita al portal.

    Consultar el precio de algo que alguien decidió no pedir sería cuatro
    sesiones de Chrome contra los portales del dueño para un dato que no decide
    nada.
    """
    _poblar(almacen)
    _los_cuatro_contestan(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/descartar")

    respuesta = _consultar(cliente, renglon_id)

    assert respuesta.status_code == 409
    assert doyle.pedidos == []


def test_un_renglon_que_no_existe_se_ve_igual_que_uno_de_otro_negocio(
    cliente, almacen
):
    """409 en los dos casos, a propósito: distinguirlos sería contar qué ids hay."""
    _poblar(almacen)
    _lista(cliente)

    assert _consultar(cliente, 99999).status_code == 409


def test_el_precio_se_guarda_aunque_alguien_descarte_el_renglon_a_media_consulta(
    almacen, almacenamiento, doyle
):
    """La lectura es un HECHO DEL MUNDO, no una transición del renglón.

    Por eso el estado del renglón **no** está en el `WHERE` del `INSERT`, al
    revés que en descartar o cerrar. Tirar la lectura no protege nada —nadie va
    a comprar un renglón descartado— y sí pierde evidencia que vuelve a hacer
    falta en cuanto alguien lo devuelva a `abierto`.

    Se ejercita contra el almacenamiento directo porque la ruta ni siquiera
    deja llegar aquí: el que mira el estado es el botón, antes de molestar a los
    portales.
    """
    from continental.almacenamiento import Ventana
    from continental.sugerido import Renglon

    almacenamiento.insertar_la_lista(
        NEGOCIO,
        HOY,
        Ventana(HOY, HOY),
        [
            Renglon(
                producto_id=1,
                clave=CLAVE,
                descripcion="PRODUCTO 1",
                piezas_vendidas=3.0,
                cantidad_propuesta=3,
                esta_en_el_catalogo=True,
                existencia=7.0,
                dias_de_cobertura=2.3,
                clasificacion="medicamento",
            )
        ],
    )
    renglon_id = almacenamiento.listas[0]["renglones"][0]["renglon_id"]
    almacenamiento.descartar(NEGOCIO, renglon_id, "encargado@farmacia.mx")

    guardadas = almacenamiento.guardar_precios(
        NEGOCIO,
        renglon_id,
        [
            LecturaDePrecio(
                proveedor="nadro",
                precio_como_llego="86.05",
                precio=Decimal("86.05"),
            )
        ],
    )

    assert guardadas == 1


def test_un_precio_no_se_le_puede_pegar_a_un_renglon_que_no_existe(almacenamiento):
    """Cero filas, que es lo que el `INSERT ... SELECT` devuelve. No se finge."""
    assert (
        almacenamiento.guardar_precios(
            NEGOCIO, 12345, [LecturaDePrecio(proveedor="nadro", motivo=SIN_RESULTADOS)]
        )
        == 0
    )


# ====================================================================
# EL DOBLE DE DOYLE Y LOS CUATRO FINALES (lo que el ticket 15 va a pedir)
# ====================================================================


def test_el_doble_de_doyle_representa_los_cuatro_finales(doyle):
    """Listo con filas, error, sesión caducada y todavía buscando.

    El ticket 15 va a tener que distinguirlos para contar los huecos por
    motivo. Un doble que solo supiera decir "salió bien" o "salió mal" dejaría
    ese ticket sin con qué probarse.
    """
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")]),
        "levic": respuesta_con_error("levic", "el portal no cargó"),
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
        "vicma": respuesta_pendiente("vicma"),
    }

    estado = doyle.estado_de_busqueda(doyle.pedir_busqueda(CLAVE).job_id)
    motivos = {
        lectura.proveedor: lectura.motivo for lectura in congelar(estado, CLAVE)
    }

    assert motivos == {
        "nadro": None,
        "levic": PORTAL_SIN_CONTESTAR,
        "quepharma": SESION_CADUCADA,
        "vicma": SIN_TIEMPO,
    }


def test_congelar_deja_una_lectura_por_proveedor_en_orden_de_clave(doyle):
    """Una por proveedor, siempre, y en un orden que no depende de los hilos.

    Dos consultas del mismo renglón se pueden leer en paralelo sin que el orden
    confunda a nadie.
    """
    doyle.resultados_por_termino[CLAVE] = {
        "vicma": respuesta_pendiente("vicma"),
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")]),
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
        "levic": respuesta_con_error("levic", "x"),
    }

    estado = doyle.estado_de_busqueda(doyle.pedir_busqueda(CLAVE).job_id)

    assert tuple(l.proveedor for l in congelar(estado, CLAVE)) == LOS_CUATRO


def test_el_registro_no_deja_dos_consultas_del_mismo_renglon_a_la_vez():
    """La decisión de no lanzar se toma DENTRO del candado, junto con la de lanzar.

    Comprobar fuera y lanzar después tiene una carrera en medio, y ahí la
    carrera no cuesta una fila duplicada: cuesta cuatro visitas de más a los
    portales del dueño.
    """
    lanzadas = []
    registro = RegistroDeConsultas(lanzar=lambda tarea: lanzadas.append(tarea))

    primera, es_nueva = registro.pedir(1, CLAVE, lambda c: None)
    segunda, es_otra = registro.pedir(1, CLAVE, lambda c: None)

    assert es_nueva is True
    assert es_otra is False
    assert segunda.pedida_en == primera.pedida_en
    assert len(lanzadas) == 1


def test_una_consulta_terminada_deja_pedir_otra():
    """Lo que bloquea es "en curso", no "ya se consultó alguna vez"."""
    registro = RegistroDeConsultas(lanzar=lambda tarea: None)
    consulta, _ = registro.pedir(1, CLAVE, lambda c: None)
    registro.terminar(consulta, GUARDADA, guardadas=4)

    _, es_nueva = registro.pedir(1, CLAVE, lambda c: None)

    assert es_nueva is True


def test_un_guardado_que_rebota_se_anota_como_sin_guardar(doyle, almacenamiento):
    """El almacenamiento caído tampoco es un 500, y el hilo no se lo traga.

    Una excepción en un hilo suelto no la ve nadie: aquí se atrapa, se escribe
    entera en la bitácora, y se convierte en un estado que la pantalla puede
    leer — con el TIPO de la falla, nunca su texto (regla 5).
    """
    doyle.resultados_por_termino[CLAVE] = {
        "nadro": respuesta_lista("nadro", [(CLAVE, "86.05", "40")])
    }
    almacenamiento.falla = RuntimeError("postgresql://usuario:SECRETA@atlas/farmacia")
    registro = RegistroDeConsultas(lanzar=lambda tarea: None)
    consulta, _ = registro.pedir(1, CLAVE, lambda c: None)
    ahora, dormir = _reloj()

    terminada = consultar_y_congelar(
        consulta,
        doyle=doyle,
        almacenamiento=almacenamiento,
        registro=registro,
        negocio=NEGOCIO,
        dormir=dormir,
        ahora=ahora,
    )

    assert terminada.estado == SIN_GUARDAR
    assert "RuntimeError" in terminada.detalle
    assert "SECRETA" not in terminada.detalle


def test_doyle_sin_job_id_no_se_da_por_bueno(doyle):
    """Sin `job_id` no hay a qué preguntarle.

    Se truena en vez de congelar cuatro huecos y llamarlo consulta: un lote en
    verde que no consultó nada es la falla silenciosa que este repo prohíbe.
    """
    class SinAcuse:
        def pedir_busqueda(self, termino):
            from continental.doyle import BusquedaPedida

            return BusquedaPedida(job_id="", proveedores=())

        def estado_de_busqueda(self, job_id):
            raise AssertionError("no debió preguntar con un job_id vacío")

        def sesiones(self):
            return []

    ahora, dormir = _reloj()
    with pytest.raises(RuntimeError, match="job_id"):
        consultar_a_doyle(SinAcuse(), CLAVE, dormir=dormir, ahora=ahora)


# ====================================================================
# EL SQL, revisado como texto (no hay Postgres alcanzable desde la torre)
# ====================================================================


def test_los_motivos_del_ddl_son_exactamente_los_del_codigo():
    """El CHECK y `precios.MOTIVOS` no pueden divergir.

    Si el código escribiera un motivo que el CHECK no conoce, el INSERT
    rebotaría en atlas con una violación de restricción que no explica nada; si
    el CHECK aceptara uno que nadie escribe, sería vocabulario muerto invitando
    a que alguien lo use.

    Los ocho siguen siendo ocho después del ticket 13: el emparejamiento por
    EAN no estrenó vocabulario, estrenó **quién escribe** `no empareja` —que el
    ticket 12 había dejado reservado— y dos casos más de `varios resultados`.
    Por eso no hay una migración `0004`: si hubiera hecho falta un motivo nuevo,
    iría en este CHECK **y** en `sql/migraciones/` (ADR 0003).
    """
    sql = _texto(CREAR_TABLAS)
    bloque = sql[sql.index("CONSTRAINT ck_precio_motivo_conocido") :]
    bloque = bloque[: bloque.index("))")]
    del_ddl = tuple(re.findall(r"'([^']+)'", bloque))

    assert del_ddl == MOTIVOS, (
        f"El DDL conoce {del_ddl} y el código escribe {MOTIVOS}."
    )


def test_el_precio_congelado_no_tiene_unique_que_obligue_a_pisarlo():
    """Un UNIQUE sobre (renglón, proveedor) convertiría la tabla en pisable.

    Y entonces alguien lo "arreglaría" con un UPSERT, y una consulta fallida
    borraría un precio bueno. Esta tabla SOLO CRECE.
    """
    sql = _texto(CREAR_TABLAS)
    cuerpo = sql[sql.index("CREATE TABLE IF NOT EXISTS pedidos.precio_de_proveedor (") :]
    cuerpo = cuerpo[: cuerpo.index("\n);")]

    assert "UNIQUE" not in cuerpo, (
        "Apareció un UNIQUE en pedidos.precio_de_proveedor. Si de verdad hace "
        "falta, relee el porqué del append-only antes de agregarlo."
    )


def test_el_codigo_no_actualiza_ni_borra_un_precio_congelado():
    """Ni un `UPDATE`, ni un `DELETE`, ni un `ON CONFLICT` sobre esa tabla.

    El rol no tiene DELETE (ADR 0003) y el diseño no tiene UPDATE. Se revisa
    sobre el archivo porque es una decisión que se rompe editando, no
    ejecutando.
    """
    fuente = (RAIZ / "src" / "continental" / "almacenamiento.py").read_text(
        encoding="utf-8"
    )
    sentencias = re.findall(r"text\(\s*\"\"\"(.*?)\"\"\"\s*\)", fuente, re.S)
    del_precio = [s for s in sentencias if "precio_de_proveedor" in s]

    assert del_precio, "No hay ninguna sentencia sobre precio_de_proveedor."
    for sentencia in del_precio:
        bajo = sentencia.lower()
        assert "update pedidos.precio_de_proveedor" not in bajo
        assert "delete" not in bajo
        assert "on conflict" not in bajo


def test_los_precios_se_escriben_de_uno_en_uno_y_no_con_executemany():
    """psycopg2 **no** tiene `supports_sane_multi_rowcount`, y eso decide aquí.

    Con un `executemany`, el `rowcount` de la ejecución viene en -1 o con el de
    la última fila — y ese número es justo el que distingue "se guardó" de "no
    había renglón". Una consulta buena se habría anotado como `sin guardar` con
    el motivo "ese renglón ya no está en la lista", **en atlas y solo en
    atlas**, después de que en la torre todo se viera verde.

    Se comprueba sobre el dialecto y no de memoria: si algún día psycopg2 gana
    el `rowcount` sano, esta prueba se pone roja y ahí se decide volver al
    `executemany` a propósito.
    """
    from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2

    assert PGDialect_psycopg2.supports_sane_multi_rowcount is False

    fuente = (RAIZ / "src" / "continental" / "almacenamiento.py").read_text(
        encoding="utf-8"
    )
    # Desde `class AlmacenamientoPostgres` y no desde la primera aparición del
    # nombre: la del `Protocol` es un docstring y un `...`, y buscar ahí habría
    # dado un falso rojo que enseña a "arreglar" la prueba en vez del código.
    fuente = fuente[fuente.index("class AlmacenamientoPostgres") :]
    cuerpo = fuente[fuente.index("    def guardar_precios(") :]
    cuerpo = cuerpo[: cuerpo.index("\n    def ", 10)]

    assert "_GUARDAR_PRECIO, fila)" in cuerpo, (
        "guardar_precios volvió a pasarle la lista entera a execute(). Con "
        "psycopg2 el rowcount de eso no es de fiar, y de ese número depende "
        "que una consulta buena no se anote como 'sin guardar'."
    )


def test_el_instante_de_la_lectura_lo_pone_el_servidor():
    """`DEFAULT now()` en la columna, y ninguna hora calculada en Python.

    La pone el servidor que guarda la fila, así que dos procesos con relojes
    distintos no dejan lecturas incomparables. Y `now()` es la hora de la
    TRANSACCIÓN: los cuatro proveedores de una consulta la comparten.
    """
    sql = _texto(CREAR_TABLAS)
    assert re.search(
        r"consultado_en\s+timestamptz\s+NOT NULL DEFAULT now\(\)", sql
    ), "consultado_en dejó de tener DEFAULT now() con zona."

    fuente = (RAIZ / "src" / "continental" / "almacenamiento.py").read_text(
        encoding="utf-8"
    )
    guardar = fuente[fuente.index("_GUARDAR_PRECIO = text(") :]
    guardar = guardar[: guardar.index('"""\n)')]
    assert "consultado_en" not in guardar, (
        "El INSERT escribe consultado_en. Ese instante lo pone la base."
    )


def test_el_rol_puede_escribir_la_cuarta_tabla():
    """Sin este GRANT, el primer precio rebota en atlas con permission denied.

    Es el olvido más caro de este ticket y por eso tiene prueba: un GRANT no se
    puede dar sobre una tabla que no existía, así que la migración 0003 obliga
    a volver a correr `crear_rol.sql` — al revés que las dos anteriores, que
    solo agregaban columnas.
    """
    rol = _texto(CREAR_ROL)

    assert re.search(
        r"GRANT SELECT, INSERT, UPDATE ON pedidos\.precio_de_proveedor\s+TO continental;",
        rol,
    ), (
        "sql/crear_rol.sql no otorga nada sobre pedidos.precio_de_proveedor. En "
        "atlas eso es 'permission denied for table precio_de_proveedor' en el "
        "primer clic de Consultar precio."
    )


def test_el_verificador_espera_todas_las_tablas():
    """La comprobación 4 cuenta tablas, y el número está escrito a mano.

    Si se queda corto, el verificador da luz verde sobre un esquema al que le
    falta una tabla — la peor de las fallas posibles en un archivo cuyo único
    trabajo es decir la verdad. Eran cuatro con el ticket 12 y son **cinco**
    desde el ticket 19, que estrenó `pedidos.corrida_del_lote`.

    El número se cuenta **sobre el propio `crear_tablas.sql`** y no se escribe
    aquí: lo que esta prueba afirma es que el DDL y el verificador dicen lo
    mismo, y con un literal de este archivo habría tres listas que mantener en
    vez de dos. Quien agregue una tabla al DDL sin tocar el verificador ve
    fallar esto, que es el sitio barato.
    """
    verificador = _texto(VERIFICAR_ROL)
    cuantas = len(
        re.findall(r"CREATE TABLE IF NOT EXISTS pedidos\.", _texto(CREAR_TABLAS))
    )

    assert f"count(*) = {cuantas}" in verificador
    assert f"'{cuantas} tablas, con otro propietario'" in verificador


def test_el_verificador_revisa_la_forma_del_precio_congelado():
    """Tres comprobaciones nuevas: el append-only, los acentos y el cero.

    `CREATE TABLE IF NOT EXISTS` calla si la tabla ya existe con otra forma, así
    que comprobar solo los permisos dejaría pasar un DDL editado a medias.
    """
    verificador = _texto(VERIFICAR_ROL)

    assert "ck_precio_positivo" in verificador
    assert "ck_precio_sin_dato" in verificador
    assert "ck_precio_motivo_conocido" in verificador


def test_la_migracion_0003_existe_y_recuerda_volver_a_correr_el_rol():
    """Las dos mitades del ADR 0003: el DDL y lo que le falta a una base viva.

    `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS` y **calla** si la tabla
    ya existe con otra forma, así que sobre la base de atlas no agrega nada. Y
    esta migración, además, crea una tabla: sin volver a correr `crear_rol.sql`
    el primer INSERT rebota por permisos.
    """
    assert MIGRACION.exists(), (
        "Falta sql/migraciones/0003-*.sql. La convención del ADR 0003 es que "
        "cada cambio de esquema se escribe en los dos lados."
    )
    texto = _texto(MIGRACION)

    assert "crear_rol.sql" in texto
    assert "permission denied" in texto
    assert "~/proyectos/Continental" in texto, (
        "La migración no dice desde dónde se corre en atlas. Allá los repos son "
        "hermanos y planos, al revés que en la torre."
    )
    assert "ON_ERROR_STOP=1" in texto


@pytest.mark.parametrize(
    "ruta", [CREAR_TABLAS, CREAR_ROL, VERIFICAR_ROL, MIGRACION]
)
def test_el_sql_va_en_utf8_y_sin_retorno_de_carro(ruta):
    """Los ocho motivos llevan acento, y un CRLF los rompe dentro del CHECK.

    Es la misma trampa de `'en tránsito'`, multiplicada por ocho: psql tolera el
    retorno de carro entre sentencias pero **no lo quita de dentro de una
    cadena**, y el CHECK guardaría `'precio ilegible\\r'`.
    """
    crudo = ruta.read_bytes()
    crudo.decode("utf-8")
    assert b"\r\n" not in crudo, f"{ruta.name} tiene CRLF y corre en atlas."
