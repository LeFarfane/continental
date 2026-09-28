"""Tres motivos que colapsaban en uno solo: `el portal no contestó` (2026-09-23).

Medido con los cuatro portales reales abiertos el 2026-09-23, consultando dos
EAN de verdad, tres situaciones muy distintas volvían todas con el mismo
motivo:

1. QuePharma, EAN `7501300420541` → `estado: error`, mensaje `No se
   encontraron artículos. Si este error continúa, notifíquelo al
   administrador.` El portal SÍ contestó: buscó y no encontró el artículo.
   Es **permanente** — reintentar no cambia la respuesta.
2. VICMA, el mismo EAN → mensaje idéntico al anterior. Mismo caso, otro
   proveedor: probablemente porque VICMA también busca por código interno
   para este producto.
3. VICMA, EAN `7502235760115` → mensaje `falla inesperada:
   BrowserType.launch_persistent_context: Opening in existing browser
   session. This usually means that the profile is already in use by another
   instance of Chromium.` **No es el portal**: es nuestro lado, con una
   ventana de sesión de ese proveedor que quedó abierta de antes reteniendo
   el perfil de Chromium. Se arregla cerrando esa ventana, no reintentando la
   búsqueda ni abriendo una sesión nueva.

Antes de esto, `precios.emparejar` solo sabía distinguir dos cosas dentro de
un `estado: error`: "el mensaje menciona la palabra sesión" (→ `la sesión
caducó`) y "cualquier otra cosa" (→ `el portal no contestó`). Los tres casos
de arriba caían los tres en el segundo cajón, y ahí se rompía la regla 4 de
`CLAUDE.md` —un hueco se muestra con SU motivo, nunca como una falla
genérica— porque un hueco permanente (1 y 2) y un problema nuestro (3) le
pedían al encargado la misma acción equivocada: esperar y reintentar.

Este archivo prueba `precios.motivo_del_error`, la función que ahora separa
los tres, con los textos EXACTOS que Doyle devolvió ese día — no unos
parecidos: una prueba escrita contra un texto inventado diría que el caso se
reconoce cuando en realidad no. Las pruebas del final pasan por `TestClient`,
con Doyle sustituido por `DoyleFalso` (el mismo doble de siempre, sin tocar un
navegador), para demostrar que la distinción llega hasta la fila guardada en
`pedidos.precio_de_proveedor` y hasta el JSON que lee la pantalla.

**Ninguna prueba de este archivo toca Postgres, abre un navegador ni le habla
a un Doyle de verdad.**
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from continental.almacen import LineaDeVenta, Producto
from continental.dobles import (
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_lista,
)
from continental.doyle import RespuestaDeProveedor
from continental.faltantes import MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
from continental.precios import (
    EXPLICACION_DEL_MOTIVO,
    MOTIVOS,
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    VENTANA_DE_SESION_ABIERTA,
    motivo_del_error,  # pública desde que Buscar también la usa (2026-09-28)
    emparejar,
    explicacion_del_motivo,
    leer_el_precio,
)

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0013-nuevo-motivo-ventana-de-sesion-abierta.sql"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

#: El EAN del caso 1 y 2 (QuePharma y VICMA, medido el 2026-09-23).
EAN_SIN_RESULTADOS = "7501300420541"

#: El EAN del caso 3 (VICMA, medido el mismo día).
EAN_VENTANA_OCUPADA = "7502235760115"

#: El texto EXACTO que QuePharma y VICMA devolvieron para el EAN de arriba.
#: Doyle lo entrega dentro de `estado: error`, no de una búsqueda vacía —esa
#: es la razón de que antes se leyera como "el portal no contestó"—.
MENSAJE_SIN_RESULTADOS = (
    "No se encontraron artículos. Si este error continúa, notifíquelo al "
    "administrador."
)

#: El texto EXACTO que Doyle devolvió para VICMA con el otro EAN: Playwright
#: no pudo abrir el navegador porque el perfil ya estaba en uso.
MENSAJE_VENTANA_OCUPADA = (
    "falla inesperada: BrowserType.launch_persistent_context: Opening in "
    "existing browser session. This usually means that the profile is "
    "already in use by another instance of Chromium."
)


# ------------------------------------------------------------- utilidades


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


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


# ====================================================================
# `motivo_del_error`: la función pura que separa los tres casos
# ====================================================================


@pytest.mark.parametrize(
    ("mensaje", "motivo", "caso"),
    [
        (MENSAJE_SIN_RESULTADOS, SIN_RESULTADOS, "QuePharma/VICMA, EAN 7501300420541"),
        (MENSAJE_VENTANA_OCUPADA, VENTANA_DE_SESION_ABIERTA, "VICMA, EAN 7502235760115"),
        ("se cayó la conexión", PORTAL_SIN_CONTESTAR, "cualquier otra falla real"),
    ],
)
def test_los_tres_casos_reales_del_2026_09_23_dejan_tres_motivos_distintos(
    mensaje, motivo, caso
):
    """Los tres textos reales, cada uno a su propio motivo y no al mismo cajón.

    Antes del 2026-09-23 los tres devolvían `PORTAL_SIN_CONTESTAR` porque
    ninguno menciona la palabra "sesión". Que hoy salgan tres motivos
    distintos es exactamente lo que estaba roto.
    """
    assert motivo_del_error(mensaje) == motivo, (
        f"El caso real de {caso} debía dar {motivo!r} y dio "
        f"{motivo_del_error(mensaje)!r}."
    )


def test_sesion_caducada_le_gana_a_los_otros_dos_si_algun_dia_coinciden():
    """El orden de revisión importa: sesión primero, y por una razón concreta.

    Ninguno de los tres mensajes reales de este archivo menciona una sesión,
    pero si algún día uno lo hiciera, "se arregla en dos clics abriendo
    sesión" sigue siendo la lectura más útil de las cuatro posibles.
    """
    assert motivo_del_error("la sesión de nadro caducó") == SESION_CADUCADA


def test_un_mensaje_que_no_calza_con_ningun_patron_sigue_siendo_reintentable():
    """La red de seguridad: lo que este código no reconoce hoy no se pierde.

    Es la regla 4 de `CLAUDE.md` aplicada al clasificador mismo: un mensaje de
    Doyle que estrene mañana un texto nuevo cae en `el portal no contestó`, el
    motivo por omisión, y no en un hueco mudo.
    """
    assert motivo_del_error("algo que Doyle todavía no dijo nunca") == (
        PORTAL_SIN_CONTESTAR
    )


def test_la_ventana_ocupada_no_se_confunde_con_una_sesion_caducada():
    """`"existing browser session"` es inglés y no la palabra española "sesión".

    Si algún día `_HUELE_A_SESION` se volviera más laxo (por ejemplo,
    `r"sesi[oó]n|session"`), este texto real empezaría a leerse como `la
    sesión caducó` y mandaría al encargado a abrir una sesión que ya está
    abierta -de más- en vez de cerrarla. Esta prueba existe para que ese
    cambio se note aquí primero.
    """
    assert motivo_del_error(MENSAJE_VENTANA_OCUPADA) != SESION_CADUCADA
    assert motivo_del_error(MENSAJE_VENTANA_OCUPADA) == VENTANA_DE_SESION_ABIERTA


# ====================================================================
# De ahí hasta `emparejar` y `leer_el_precio`: el camino completo
# ====================================================================


@pytest.mark.parametrize(
    ("mensaje", "motivo"),
    [
        (MENSAJE_SIN_RESULTADOS, SIN_RESULTADOS),
        (MENSAJE_VENTANA_OCUPADA, VENTANA_DE_SESION_ABIERTA),
    ],
)
def test_emparejar_no_acepta_nada_y_deja_el_motivo_nuevo(mensaje, motivo):
    """`emparejar` nunca inventa una fila para un proveedor que no contestó."""
    elegido = emparejar(
        RespuestaDeProveedor(proveedor="vicma", estado="error", mensaje=mensaje),
        EAN_VENTANA_OCUPADA,
    )

    assert not elegido.aceptado
    assert elegido.motivo == motivo


@pytest.mark.parametrize(
    ("mensaje", "motivo"),
    [
        (MENSAJE_SIN_RESULTADOS, SIN_RESULTADOS),
        (MENSAJE_VENTANA_OCUPADA, VENTANA_DE_SESION_ABIERTA),
    ],
)
def test_leer_el_precio_guarda_el_motivo_nuevo_y_el_texto_de_doyle_como_detalle(
    mensaje, motivo
):
    """La lectura completa: sin precio, con motivo, y con el texto de Doyle al
    lado — el mismo que hoy se lee en el `detalle`, para poder auditar el caso
    seis meses después sin tener que confiar en la memoria de nadie."""
    lectura = leer_el_precio(
        RespuestaDeProveedor(proveedor="vicma", estado="error", mensaje=mensaje),
        EAN_VENTANA_OCUPADA,
    )

    assert lectura.precio is None
    assert lectura.motivo == motivo
    assert lectura.detalle == mensaje


# ====================================================================
# Lo que la pantalla dice: cada motivo, con su acción
# ====================================================================


def test_los_nueve_motivos_siguen_teniendo_cada_uno_su_explicacion():
    """El noveno motivo entra al mapa igual que los otros ocho: nada se cae."""
    assert len(MOTIVOS) == 9
    assert VENTANA_DE_SESION_ABIERTA in MOTIVOS
    assert set(EXPLICACION_DEL_MOTIVO) == set(MOTIVOS)
    assert len(set(EXPLICACION_DEL_MOTIVO.values())) == len(MOTIVOS)


def test_la_ventana_ocupada_dice_que_es_nuestro_problema_y_que_hacer():
    """Sigue el mismo precedente que los otros motivos: no solo el hecho, la
    acción. `la sesión caducó` dice "ábrela"; éste dice "ciérrala", y dice
    además que no es culpa del portal, para que nadie vaya a mirar el portal
    equivocado."""
    explicacion = explicacion_del_motivo(VENTANA_DE_SESION_ABIERTA)

    assert "nuestro" in explicacion
    assert "portal" in explicacion
    assert "ciérrala" in explicacion or "cierra" in explicacion
    assert "consulta" in explicacion


def test_sin_resultados_sigue_diciendo_lo_mismo_de_siempre():
    """El caso 1 y 2 no estrenan explicación: se reclasifican al motivo que ya
    existía, y esa frase no cambia por el camino nuevo que ahora llega a
    ella."""
    assert explicacion_del_motivo(SIN_RESULTADOS) == "el producto no está en ese catálogo"


def test_el_boton_completar_no_reintenta_todavia_la_ventana_ocupada():
    """Decisión deliberada y no un olvido — se deja anotada porque alguien la
    va a cuestionar mirando el código.

    `quedó una ventana de sesión abierta` se parece a `la sesión caducó` en
    que las dos son "nuestro problema, se arregla en unos clics". Pero abrir
    sesión tiene su propio botón (`proveedores_con_sesion_caducada` +
    `POST /api/sesion/{proveedor}/abrir`); cerrar una ventana abandonada no
    lo tiene todavía —el ADR 0018 construyó el candado que evita abrir una
    SEGUNDA ventana, no un botón para cerrar la primera desde Continental—.
    Meter este motivo en el reintento automático de "completar lo que falta"
    quemaría ~9 s por proveedor, en cada clic, contra un navegador que sigue
    exactamente igual de bloqueado hasta que alguien entre al visor.
    """
    assert VENTANA_DE_SESION_ABIERTA not in MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
    assert SESION_CADUCADA in MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO


# ====================================================================
# La costura única: TestClient + DoyleFalso, hasta la fila y hasta el JSON
# ====================================================================


def test_los_tres_casos_reales_llegan_distintos_hasta_la_fila_guardada(
    cliente, almacen, almacenamiento, doyle
):
    """Camino entero para el caso que más importaba separar: QuePharma con
    `sin resultados` (permanente) y VICMA con `quedó una ventana de sesión
    abierta` (nuestro problema) no pueden guardarse con el mismo motivo que
    NADRO, que de verdad no contestó."""
    clave = EAN_VENTANA_OCUPADA
    almacen.catalogo_en_memoria = [_producto(1, clave)]
    almacen.ventas_en_memoria = [_venta(1, 3)]
    doyle.resultados_por_termino[clave] = {
        "nadro": respuesta_con_error("nadro", "se cayó la conexión"),
        "levic": respuesta_con_sesion_caducada("levic"),
        "quepharma": respuesta_con_error("quepharma", MENSAJE_SIN_RESULTADOS),
        "vicma": respuesta_con_error("vicma", MENSAJE_VENTANA_OCUPADA),
    }

    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/precio")

    por_proveedor = {
        p.proveedor: p
        for p in almacenamiento.precios_del_renglon(NEGOCIO, renglon_id)
    }
    assert por_proveedor["nadro"].motivo == PORTAL_SIN_CONTESTAR
    assert por_proveedor["levic"].motivo == SESION_CADUCADA
    assert por_proveedor["quepharma"].motivo == SIN_RESULTADOS
    assert por_proveedor["vicma"].motivo == VENTANA_DE_SESION_ABIERTA
    # Los cuatro son distintos entre sí EN LA FILA GUARDADA, que es lo que el
    # ticket 15 necesita para poder contar huecos por motivo sin mentir.
    assert len({p.motivo for p in por_proveedor.values()}) == 4


def test_los_tres_casos_reales_llegan_distintos_hasta_el_json_de_la_pantalla(
    cliente, almacen, doyle
):
    """La misma consulta, mirada desde donde la ve el encargado: la lista."""
    clave = EAN_VENTANA_OCUPADA
    almacen.catalogo_en_memoria = [_producto(1, clave)]
    almacen.ventas_en_memoria = [_venta(1, 3)]
    doyle.resultados_por_termino[clave] = {
        "nadro": respuesta_lista("nadro", []),  # sin resultados "normal", de control
        "levic": respuesta_con_sesion_caducada("levic"),
        "quepharma": respuesta_con_error("quepharma", MENSAJE_SIN_RESULTADOS),
        "vicma": respuesta_con_error("vicma", MENSAJE_VENTANA_OCUPADA),
    }

    renglon_id = cliente.get(RUTA).json()["renglones"][0]["renglon_id"]
    cliente.post(f"/api/renglon/{renglon_id}/precio")

    renglon = cliente.get(RUTA).json()["renglones"][0]
    casillas = {
        c["proveedor"]: c for c in renglon["comparacion"]["por_proveedor"]
    }

    # NADRO (sin resultados "de siempre", `estado: listo` con total 0) y
    # QuePharma (sin resultados vía `estado: error`, el bug de este ticket)
    # tienen que verse EXACTAMENTE igual en la pantalla: es la misma noticia,
    # solo que Doyle la empaquetó distinto.
    assert casillas["nadro"]["motivo"] == SIN_RESULTADOS
    assert casillas["quepharma"]["motivo"] == SIN_RESULTADOS
    assert casillas["nadro"]["motivo_explicado"] == casillas["quepharma"]["motivo_explicado"]

    assert casillas["vicma"]["motivo"] == VENTANA_DE_SESION_ABIERTA
    assert "nuestro" in casillas["vicma"]["motivo_explicado"]

    assert casillas["levic"]["motivo"] == SESION_CADUCADA

    assert len({c["motivo"] for c in casillas.values()}) == 3


# ====================================================================
# El DDL y la migración: el noveno motivo también existe fuera de Python
# ====================================================================


def test_el_ddl_conoce_el_motivo_nuevo():
    """`ck_precio_motivo_conocido` tiene que aceptar lo que Python ya escribe.

    La comparación exacta orden-por-orden ya la hace
    `test_precio.py::test_los_motivos_del_ddl_son_exactamente_los_del_codigo`;
    esto es la comprobación de humo específica de este ticket, que falla con
    un mensaje que nombra al motivo si algún día alguien toca el CHECK sin
    tocar `precios.MOTIVOS`."""
    assert "'quedó una ventana de sesión abierta'" in _texto(CREAR_TABLAS)


def test_la_migracion_0013_existe_y_es_solo_un_check_mas_ancho():
    """A diferencia de la 0003, ésta NO crea tabla ni columna: solo reemplaza
    `ck_precio_motivo_conocido` por uno que acepta un valor más. Por eso NO
    hace falta volver a correr `crear_rol.sql` -el GRANT es sobre la tabla
    entera- y la migración lo dice."""
    assert MIGRACION.exists(), (
        "Falta sql/migraciones/0013-*.sql. La convención del ADR 0003 es que "
        "cada cambio de esquema se escribe en los dos lados: el CHECK y su "
        "migración."
    )
    texto = _texto(MIGRACION)

    assert "DROP CONSTRAINT IF EXISTS ck_precio_motivo_conocido" in texto
    assert "'quedó una ventana de sesión abierta'" in texto
    assert "ON_ERROR_STOP=1" in texto
    # Idempotente y con el candado de credenciales, igual que las doce
    # anteriores (mismo criterio que `test_precio.py` exige para la 0003).
    assert "current_user = 'continental'" in texto
    assert "BEGIN;" in texto and "COMMIT;" in texto


def test_el_sql_de_este_ticket_va_en_utf8_y_sin_retorno_de_carro():
    """Los nueve motivos llevan acento, y un CRLF los rompe dentro del CHECK —
    la misma trampa que ya cazaba `test_precio.py` para los ocho de antes,
    repetida aquí porque el CHECK y la migración de este ticket son archivos
    nuevos que esa prueba no conocía."""
    for ruta in (CREAR_TABLAS, VERIFICAR_ROL, MIGRACION):
        crudo = ruta.read_bytes()
        crudo.decode("utf-8")
        assert b"\r\n" not in crudo, f"{ruta.name} tiene CRLF y corre en atlas."
