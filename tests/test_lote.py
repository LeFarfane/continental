"""El lote nocturno: el tope de 60 minutos, el orden y la bitácora (ticket 18).

**Ninguna de estas pruebas duerme un segundo de verdad, y varias simulan una
hora entera.** El reloj entra por argumento (`ahora`) y la espera también
(`dormir`), igual que en `test_precio.py`: `_reloj()` devuelve un par en el que
el tiempo **solo avanza cuando alguien duerme**. Así una corrida de sesenta
minutos simulados cuesta microsegundos reales y mide exactamente lo que el
código pidió esperar, ni un segundo más. Una prueba de este archivo que tardara
estaría midiendo `time.monotonic`, no el lote.

Cómo está repartido, que es el mismo reparto que el módulo:

- **Lo puro** —`ordenar_por_importancia`, `Cronometro`, `contar_los_motivos`,
  `ResumenDeLaCorrida.como_texto`— se prueba con dataclasses en memoria, sin
  almacén y sin Doyle. Es la mayoría del archivo.
- **`correr_el_lote`** se prueba contra los tres dobles, que entran por
  argumento. No levanta la aplicación: el lote es otro proceso y no pasa por
  FastAPI.
- **`main`** no se prueba: es lo único que construye bordes de verdad y no
  tiene una sola decisión dentro.

**El bloqueo externo se prueba como bloqueo.** `marts.dim_producto` no tiene
`clase_abc` (ADR 0018 de farmacia-data, aceptado y sin implementar), así que
hay dos familias de casos: los que le pasan clase a mano —que demuestran que el
orden por importancia está construido y funciona— y los que no le pasan
ninguna, que son **lo que pasa hoy en atlas** y comprueban que el lote lo dice
en vez de fingir que cumplió.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

import pytest

from continental.almacen import SIN_CLASE_ABC, LineaDeVenta, Producto
from continental.almacenamiento import RenglonGuardado
from continental.dobles import (
    AlmacenamientoFalso,
    AlmacenFalso,
    DoyleFalso,
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_lista,
    respuesta_pendiente,
)
from continental.lote import (
    CONSULTADO,
    NO_SE_PUDO,
    SE_ACABO_EL_TIEMPO,
    SE_INTERRUMPIO,
    SIN_ALCANZAR,
    SIN_CLAVE,
    SIN_LISTA,
    TERMINO,
    TOPE_POR_OMISION_MIN,
    Cronometro,
    RenglonDelLote,
    ResumenDeLaCorrida,
    clases_del_catalogo,
    contar_los_motivos,
    correr_el_lote,
    ordenar_por_importancia,
    tope_del_lote_segundos,
)
from continental.precios import (
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_TIEMPO,
)
from continental.sugerido import Renglon

NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

RAIZ = Path(__file__).resolve().parent.parent
SERVICIO = RAIZ / "scripts" / "systemd" / "continental-lote.service"
TIMER = RAIZ / "scripts" / "systemd" / "continental-lote.timer"

#: Los cuatro del glosario, con la clave que usa Doyle.
LOS_CUATRO = ("levic", "nadro", "quepharma", "vicma")


# ------------------------------------------------------------- utilidades


def _reloj():
    """Un reloj que **solo avanza cuando alguien duerme**. Devuelve `(ahora, dormir)`.

    Copiado a propósito de `test_precio.py` y no importado de allá: una prueba
    que dependa del archivo de otro ticket se rompe cuando aquél se reordene, y
    son diez líneas. Lo que importa es que sea el mismo mecanismo — el tiempo
    que avanza es **el que el código pidió esperar**, y nada más.
    """
    transcurrido = [0.0]

    def ahora() -> float:
        return transcurrido[0]

    def dormir(segundos: float) -> None:
        transcurrido[0] += segundos

    return ahora, dormir


def _clave(n: int) -> str:
    """Un EAN de 13 dígitos distinto por producto."""
    return f"750100000{n:04d}"


def _renglon(
    n: int, *, clave: str | None = None, descripcion: str | None = None
) -> RenglonGuardado:
    """Un renglón guardado, con lo mínimo para ordenarlo y consultarlo."""
    return RenglonGuardado(
        renglon_id=n,
        estado="abierto",
        propuesto=Renglon(
            producto_id=n,
            clave=_clave(n) if clave is None else clave,
            descripcion=descripcion or f"PRODUCTO {n}",
            piezas_vendidas=1.0,
            cantidad_propuesta=1,
            esta_en_el_catalogo=True,
            existencia=5.0,
            dias_de_cobertura=5.0,
            clasificacion="medicamento",
        ),
    )


def _producto(n: int, clase: str = SIN_CLASE_ABC) -> Producto:
    return Producto(
        producto_id=n,
        clave=_clave(n),
        descripcion=f"PRODUCTO {n}",
        categoria="GRUP4",
        departamento="MED",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=100.0,
        costo=80.0,
        existencia=5.0,
        esta_activo=True,
        es_granel=False,
        clase_abc=clase,
    )


def _mundo(cuantos: int, clases: dict[int, str] | None = None):
    """Un almacén con `cuantos` productos vendidos hoy, listo para el lote."""
    clases = clases or {}
    almacen = AlmacenFalso(
        ventas_en_memoria=[
            LineaDeVenta(
                fecha=HOY,
                producto_id=n,
                cantidad=1.0,
                importe=100.0,
                costo=80.0,
                utilidad=20.0,
            )
            for n in range(1, cuantos + 1)
        ],
        catalogo_en_memoria=[
            _producto(n, clases.get(n, SIN_CLASE_ABC)) for n in range(1, cuantos + 1)
        ],
    )
    return almacen


def _doyle_que_contesta(cuantos: int, vueltas_pendientes: int = 0) -> DoyleFalso:
    """Un Doyle que le da precio a los cuatro proveedores de cada clave.

    `vueltas_pendientes` es cuántas vueltas de sondeo pasa cada búsqueda en
    `buscando` antes de terminar. **Es lo que hace avanzar el reloj**: cada
    vuelta cuesta un `dormir(cada_seg)`, y ése es el único tiempo que el lote
    consume en estas pruebas. Con cero, la primera vuelta ya viene terminada y
    la corrida entera cuesta cero segundos simulados.
    """
    doyle = DoyleFalso()
    for n in range(1, cuantos + 1):
        clave = _clave(n)
        listo = {
            proveedor: respuesta_lista(proveedor, [(clave, "86.05", "40")])
            for proveedor in LOS_CUATRO
        }
        if vueltas_pendientes:
            pendiente = {p: respuesta_pendiente(p) for p in LOS_CUATRO}
            doyle.vueltas_por_termino[clave] = [pendiente] * vueltas_pendientes + [
                listo
            ]
        else:
            doyle.resultados_por_termino[clave] = listo
    return doyle


def _correr(almacen, almacenamiento, doyle, **extra):
    """`correr_el_lote` con el reloj inyectado y los valores de siempre."""
    ahora, dormir = extra.pop("reloj", _reloj())
    return (
        correr_el_lote(
            almacen=almacen,
            almacenamiento=almacenamiento,
            doyle=doyle,
            negocio=NEGOCIO,
            tope_seg=extra.pop("tope_seg", 3600.0),
            tope_por_consulta_seg=extra.pop("tope_por_consulta_seg", 120.0),
            cada_seg=extra.pop("cada_seg", 1.0),
            dormir=dormir,
            ahora=ahora,
            **extra,
        ),
        ahora,
    )


# =========================================================================
# EL ORDEN DE IMPORTANCIA — la parte bloqueada por el ADR 0018
# =========================================================================


def test_sin_clase_abc_el_orden_no_se_cumple_y_se_dice():
    """**El caso de hoy en atlas.** Sin la columna, el orden no se puede cumplir.

    Es la casilla que el ticket deja sin marcar, y aquí está escrita como
    prueba: `cumple_el_orden` es falso y el motivo nombra la columna y el ADR.
    Lo que NO pasa es que se invente un orden alterno y se llame cumplido.
    """
    renglones = [_renglon(n) for n in (3, 1, 2)]

    orden = ordenar_por_importancia(renglones, {})

    assert orden.cumple_el_orden is False
    assert "clase_abc" in orden.motivo
    assert "0018" in orden.motivo
    assert orden.con_clase == 0
    assert orden.sin_clase == 3


def test_sin_clase_abc_no_se_reordena_nada():
    """Se consulta en el orden de urgencia con el que la lista se guardó.

    No reordenar es lo único honesto cuando el criterio no está: cualquier otro
    orden sería inventado. Y es además el orden que el encargado ve en la
    pantalla, así que el lote consulta de arriba hacia abajo como él leería.
    """
    renglones = [_renglon(n) for n in (7, 4, 9)]

    orden = ordenar_por_importancia(renglones, {})

    assert [r.renglon_id for r in orden.renglones] == [7, 4, 9]


def test_con_clase_abc_ordena_a_luego_b_luego_c():
    """El orden que el ticket pide, probado con dobles porque el dato no existe.

    Está construido entero y funciona: el día que `dim_producto` traiga la
    columna, esto ya está escrito y probado, y lo único que hay que mover es
    `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO`.
    """
    renglones = [_renglon(1), _renglon(2), _renglon(3)]
    clases = {1: "C", 2: "A", 3: "B"}

    orden = ordenar_por_importancia(renglones, clases)

    assert [r.renglon_id for r in orden.renglones] == [2, 3, 1]
    assert orden.cumple_el_orden is True
    assert orden.motivo == ""


def test_dentro_de_una_clase_se_respeta_la_urgencia():
    """El orden es **estable**: dentro de cada clase manda el orden de llegada.

    El segundo criterio no se reescribe aquí. La lista llega ordenada por
    urgencia desde `sugerido._urgencia` —agotado primero, luego menor
    cobertura— y un `sorted` estable lo conserva. Reimplementarlo sería tener
    dos reglas de urgencia que se separan al primer cambio.
    """
    renglones = [_renglon(n) for n in (10, 11, 12, 13)]
    clases = {10: "B", 11: "A", 12: "B", 13: "A"}

    orden = ordenar_por_importancia(renglones, clases)

    assert [r.renglon_id for r in orden.renglones] == [11, 13, 10, 12]


def test_lo_que_no_tiene_clase_va_al_final_y_no_desaparece():
    """Nada se filtra: sin clase se va al fondo, contado y dicho.

    Es la misma dirección que `sugerido._urgencia` le da a la cobertura
    desconocida. Un producto que se cayera del lote por no tener clase es
    mercancía que se queda sin precio sin que nadie se entere (regla 4).
    """
    renglones = [_renglon(n) for n in (1, 2, 3)]
    clases = {2: "A"}

    orden = ordenar_por_importancia(renglones, clases)

    assert [r.renglon_id for r in orden.renglones] == [2, 1, 3]
    assert orden.cuantos == 3


def test_media_lista_con_clase_tampoco_cumple_el_orden():
    """Estricto en la dirección segura: con un solo renglón sin clase, no cumple.

    Media lista ordenada por importancia y media al azar no es el orden que el
    ADR 0018 describe. Decir que sí lo es sería el "no falla y no avisa" que
    este repo persigue.
    """
    orden = ordenar_por_importancia([_renglon(1), _renglon(2)], {1: "A"})

    assert orden.cumple_el_orden is False
    assert orden.con_clase == 1
    assert orden.sin_clase == 1
    assert "1 de 2" in orden.motivo


def test_una_clase_que_no_es_a_b_ni_c_cuenta_como_no_saber():
    """Un valor raro no inventa una cuarta clase: se trata como "no se sabe"."""
    orden = ordenar_por_importancia([_renglon(1), _renglon(2)], {1: "D", 2: "A"})

    assert [r.renglon_id for r in orden.renglones] == [2, 1]
    assert orden.con_clase == 1


def test_una_lista_vacia_no_cumple_el_orden_y_no_truena():
    """Cero renglones: no hay nada que ordenar y tampoco nada que afirmar."""
    orden = ordenar_por_importancia([], {})

    assert orden.renglones == ()
    assert orden.cumple_el_orden is False


def test_las_clases_del_catalogo_salen_vacias_hoy():
    """Hoy `Producto.clase_abc` vale `SIN_CLASE_ABC` en todas las filas.

    Es el bloqueo externo visto desde el catálogo: la columna no existe, así
    que el mapa de clases sale vacío y el orden no se puede cumplir. El día que
    exista, esta misma función lo llena sin tocarse.
    """
    assert clases_del_catalogo([_producto(1), _producto(2)]) == {}


def test_las_clases_del_catalogo_solo_traen_las_conocidas():
    """"No está" y "está vacío" no son dos maneras de decir lo mismo."""
    catalogo = [_producto(1, "A"), _producto(2), _producto(3, "C")]

    assert clases_del_catalogo(catalogo) == {1: "A", 3: "C"}


# =========================================================================
# EL TOPE — el cronómetro con el reloj inyectado
# =========================================================================


def test_el_cronometro_mide_lo_que_alguien_durmio():
    """No mira `time.monotonic`: mira el reloj que le dieron."""
    ahora, dormir = _reloj()
    cronometro = Cronometro.arrancar(3600.0, ahora)

    assert cronometro.transcurrido == 0.0
    dormir(600.0)
    assert cronometro.transcurrido == pytest.approx(600.0)
    assert cronometro.se_acabo is False


def test_el_cronometro_se_acaba_justo_en_el_tope():
    """`>=` y no `>`: en el segundo 3600 ya no se empieza otro renglón."""
    ahora, dormir = _reloj()
    cronometro = Cronometro.arrancar(3600.0, ahora)

    dormir(3599.0)
    assert cronometro.se_acabo is False
    dormir(1.0)
    assert cronometro.se_acabo is True


def test_un_tope_en_cero_no_deja_consultar_ni_uno():
    """El borde que nadie mira hasta que alguien apaga el lote y no se apaga.

    Con `>` en vez de `>=`, un tope de cero dejaría pasar exactamente un
    renglón — o sea, cuatro visitas a los portales del dueño en una noche en la
    que se pidió que no hubiera ninguna.
    """
    ahora, _ = _reloj()

    assert Cronometro.arrancar(0.0, ahora).se_acabo is True


def test_el_tope_sale_del_yaml_y_son_sesenta_minutos():
    """`pedido.tope_lote_minutos` del YAML versionado, no una constante.

    El número es una decisión de operación —cuánto se le permite al lote
    molestar de noche a los portales del dueño— y por eso vive en el archivo
    con su comentario, igual que `dias_primera_vez` y el tope por consulta.
    """
    assert tope_del_lote_segundos() == pytest.approx(60 * 60.0)
    assert TOPE_POR_OMISION_MIN == 60.0


# =========================================================================
# EL RESUMEN — la bitácora de la corrida
# =========================================================================


def test_los_motivos_se_cuentan_por_hueco_y_no_por_renglon():
    """La mitad "y por qué" de la casilla. Un renglón puede traer cuatro huecos.

    Se cuentan huecos porque cada uno se arregla distinto: la sesión caducada
    la abre el encargado en dos clics, el portal caído se reintenta, y "no está
    en ese catálogo" no lo arregla nadie.
    """
    renglones = (
        RenglonDelLote(1, "x", "A", motivos=(SESION_CADUCADA, SIN_RESULTADOS)),
        RenglonDelLote(2, "y", "B", motivos=(SESION_CADUCADA,)),
        RenglonDelLote(3, "z", "C", motivos=(SESION_CADUCADA, PORTAL_SIN_CONTESTAR)),
    )

    assert contar_los_motivos(renglones) == (
        (SESION_CADUCADA, 3),
        (PORTAL_SIN_CONTESTAR, 1),
        (SIN_RESULTADOS, 1),
    )


def test_el_desempate_de_los_motivos_es_alfabetico():
    """Un resumen que cambia de orden entre dos noches iguales no se compara."""
    renglones = (RenglonDelLote(1, "x", "A", motivos=(SIN_TIEMPO, SIN_RESULTADOS)),)

    assert [m for m, _ in contar_los_motivos(renglones)] == sorted(
        [SIN_TIEMPO, SIN_RESULTADOS]
    )


def test_el_resumen_cuenta_lo_que_la_casilla_pide():
    """Cuántos consultó, cuántos quedaron sin precio, y cuántos por tope."""
    resumen = ResumenDeLaCorrida(
        fecha_del_pedido=HOY,
        pedido_sugerido_id=1,
        final=SE_ACABO_EL_TIEMPO,
        segundos=3600.0,
        tope_seg=3600.0,
        renglones=(
            RenglonDelLote(1, "a", "UNO", final=CONSULTADO, con_precio=4),
            RenglonDelLote(
                2, "b", "DOS", final=CONSULTADO, sin_precio=4, motivos=(SESION_CADUCADA,) * 4
            ),
            RenglonDelLote(3, "c", "TRES", final=SIN_ALCANZAR, motivos=(SIN_TIEMPO,)),
            RenglonDelLote(4, "", "CUATRO", final=SIN_CLAVE),
        ),
    )

    assert resumen.en_la_lista == 4
    assert resumen.consultados == 2
    assert resumen.con_precio == 1
    assert resumen.sin_precio == 3
    assert resumen.sin_alcanzar == 1
    assert resumen.sin_clave == 1
    assert resumen.se_paso_del_tope is True


def test_la_bitacora_dice_que_lo_que_falto_es_por_tope_y_no_error():
    """La frase que el ticket pide con todas sus letras, en el texto que se lee.

    Quien mire el journal en la mañana tiene que poder distinguir "se acabó el
    tiempo" de "algo falló", porque lo primero se completa con un botón y lo
    segundo hay que ir a arreglarlo.
    """
    resumen = ResumenDeLaCorrida(
        fecha_del_pedido=HOY,
        pedido_sugerido_id=7,
        final=SE_ACABO_EL_TIEMPO,
        segundos=3600.0,
        tope_seg=3600.0,
        renglones=(RenglonDelLote(1, "a", "UNO", final=SIN_ALCANZAR, motivos=(SIN_TIEMPO,)),),
    )

    texto = resumen.como_texto()

    assert "FALTANTES POR TOPE" in texto
    assert SIN_TIEMPO in texto
    assert "no con error" in texto
    assert SE_ACABO_EL_TIEMPO in texto


def test_la_bitacora_dice_cada_motivo_con_palabras_de_persona():
    """El motivo corto es lo que se cuenta; la explicación es lo que se lee.

    Son dos cadenas por motivo y las dos aparecen: `EXPLICACION_DEL_MOTIVO` de
    `precios.py` es lo que convierte "sin resultados" en algo accionable.
    """
    resumen = ResumenDeLaCorrida(
        fecha_del_pedido=HOY,
        pedido_sugerido_id=1,
        final=TERMINO,
        segundos=10.0,
        tope_seg=3600.0,
        renglones=(RenglonDelLote(1, "a", "UNO", sin_precio=1, motivos=(SESION_CADUCADA,)),),
    )

    texto = resumen.como_texto()

    assert SESION_CADUCADA in texto
    assert "ábrela y vuelve a consultar" in texto


def test_la_bitacora_dice_cuando_el_orden_no_se_cumplio():
    """El bloqueo externo se ve en la salida de cada noche, no solo en un ADR."""
    orden = ordenar_por_importancia([_renglon(1)], {})
    resumen = ResumenDeLaCorrida(
        fecha_del_pedido=HOY,
        pedido_sugerido_id=1,
        final=TERMINO,
        segundos=1.0,
        tope_seg=3600.0,
        orden=orden,
    )

    assert "SIN CUMPLIR" in resumen.como_texto()
    assert "clase_abc" in resumen.como_texto()


# =========================================================================
# LA CORRIDA — contra los tres dobles
# =========================================================================


def test_el_lote_arma_la_lista_del_dia_si_no_existe():
    """"Que en la mañana la lista ya traiga precios sin que nadie los pida".

    A las 22:00 nadie ha cargado la pantalla, así que la lista del día no
    existe: el lote la arma. La fecha sale de `max(fecha)` del almacén y nunca
    del reloj — un Postgres en UTC vería "mañana" como hoy.
    """
    almacen = _mundo(2)
    almacenamiento = AlmacenamientoFalso()

    resumen, _ = _correr(almacen, almacenamiento, _doyle_que_contesta(2))

    guardado = almacenamiento.leer(NEGOCIO, HOY)
    assert guardado is not None
    assert len(guardado.renglones) == 2
    assert resumen.fecha_del_pedido == HOY
    assert resumen.pedido_sugerido_id == guardado.pedido_sugerido_id


def test_el_lote_consulta_todos_los_renglones_y_los_congela():
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(3)

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert resumen.final == TERMINO
    assert resumen.consultados == 3
    assert resumen.con_precio == 3
    assert len(doyle.pedidos) == 3
    # Cuatro filas congeladas por renglón: una por proveedor, siempre.
    assert len(almacenamiento.precios) == 12


def test_sin_ventas_no_hay_lista_y_eso_no_es_una_falla():
    """La farmacia cierra los domingos: cero ventas es un día de verdad.

    Se distingue de una corrida rota con todas sus letras, porque si no alguien
    buscaría un problema que no existe.
    """
    almacenamiento = AlmacenamientoFalso()

    resumen, _ = _correr(AlmacenFalso(), almacenamiento, DoyleFalso())

    assert resumen.final == SIN_LISTA
    assert "no es una falla" in resumen.detalle
    assert almacenamiento.listas == []


# --------------------------------------------- se detiene a los 60 minutos


def test_se_detiene_al_tope_de_sesenta_minutos():
    """**La casilla principal del ticket, sin esperar una hora.**

    Cada búsqueda pasa una vuelta de sondeo en `buscando`, y esa vuelta cuesta
    un `dormir(cada_seg)`. Con `cada_seg` de 600 s simulados, cada renglón
    consume diez minutos: a los seis renglones el reloj marca 3600 y el lote no
    empieza el séptimo.

    El tiempo que avanza es **exactamente el que el código pidió esperar**: no
    hay un `monkeypatch` de `time.sleep` ni un reloj que corra solo.
    """
    almacen = _mundo(10)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(10, vueltas_pendientes=1)

    resumen, ahora = _correr(
        almacen, almacenamiento, doyle, tope_seg=3600.0, cada_seg=600.0
    )

    assert resumen.final == SE_ACABO_EL_TIEMPO
    assert resumen.consultados == 6
    assert resumen.sin_alcanzar == 4
    assert ahora() == pytest.approx(3600.0)
    # Solo se molestó a los portales seis veces, no diez.
    assert len(doyle.pedidos) == 6


def test_lo_que_no_alcanzo_queda_como_faltante_por_tope_y_no_como_error():
    """"Faltante por tope, no error" — y con el motivo que ya existía.

    `no alcanzó el tiempo` es el motivo de `precios.py` que la historia 31 pide
    distinguir de "el portal falló": uno se resuelve volviendo a consultar y el
    otro no. No se estrena un motivo nuevo porque no hace falta uno.
    """
    almacen = _mundo(4)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(4, vueltas_pendientes=1)

    resumen, _ = _correr(
        almacen, almacenamiento, doyle, tope_seg=1200.0, cada_seg=600.0
    )

    faltantes = [r for r in resumen.renglones if r.faltante_por_tope]
    assert len(faltantes) == 2
    assert all(r.motivos == (SIN_TIEMPO,) for r in faltantes)
    assert all(r.final != NO_SE_PUDO for r in faltantes)
    assert resumen.no_se_pudo == 0


def test_los_renglones_que_no_se_alcanzaron_no_desaparecen_del_resumen():
    """Un renglón que se cae del resumen es uno del que nadie sabe que faltó.

    El lote no rompe el bucle sin anotarlos: los cuenta a todos, hasta el
    último de la lista.
    """
    almacen = _mundo(5)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(5, vueltas_pendientes=1)

    resumen, _ = _correr(
        almacen, almacenamiento, doyle, tope_seg=600.0, cada_seg=600.0
    )

    assert resumen.en_la_lista == 5
    assert resumen.consultados + resumen.sin_alcanzar == 5


def test_el_tope_no_corta_una_consulta_a_la_mitad():
    """Se mira ANTES de arrancar un renglón, nunca en medio de uno.

    Cortar a la mitad dejaría a Doyle con navegadores abiertos y tiraría una
    búsqueda que ya costó ~9 s por proveedor. El precio de eso es que el lote
    se pasa del tope por lo que tarde el renglón en curso, y es a propósito:
    aquí el tope son 1 s simulado y el renglón cuesta 600, así que termina en
    600 con el primero **guardado entero**.
    """
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(3, vueltas_pendientes=1)

    resumen, ahora = _correr(
        almacen, almacenamiento, doyle, tope_seg=1.0, cada_seg=600.0
    )

    assert resumen.consultados == 1
    assert resumen.sin_alcanzar == 2
    assert ahora() == pytest.approx(600.0)
    assert len(almacenamiento.precios) == 4


def test_una_corrida_que_se_pasa_del_tope_no_es_una_falla():
    """El proceso sale con cero: detenerse a los 60 minutos es lo que se pidió.

    Si `se acabó el tiempo` se marcara como fallo, la unidad quedaría en rojo
    todas las noches y nadie volvería a mirar el journal, que es donde vive el
    resumen.
    """
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(3, vueltas_pendientes=1)

    resumen, _ = _correr(
        almacen, almacenamiento, doyle, tope_seg=1.0, cada_seg=600.0
    )

    # No hay excepción y el resumen lo dice: es un final, no un error.
    assert resumen.final == SE_ACABO_EL_TIEMPO
    assert resumen.no_se_pudo == 0


# ------------------------------- un proveedor que falla no tumba el lote


def test_un_proveedor_que_falla_no_tumba_el_renglon():
    """Los otros tres siguen: un hueco en su columna, nunca una consulta perdida.

    Lo garantiza `precios.congelar`, que devuelve una lectura **por cada**
    proveedor del acuse, y aquí se comprueba de punta a punta: cuatro filas
    guardadas, tres con precio y una con su motivo.
    """
    almacen = _mundo(1)
    almacenamiento = AlmacenamientoFalso()
    clave = _clave(1)
    doyle = DoyleFalso(
        resultados_por_termino={
            clave: {
                "nadro": respuesta_con_sesion_caducada("nadro"),
                "levic": respuesta_lista("levic", [(clave, "86.05", "40")]),
                "vicma": respuesta_lista("vicma", [(clave, "90.00", "10")]),
                "quepharma": respuesta_lista("quepharma", [(clave, "95.00", "2")]),
            }
        }
    )

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert resumen.consultados == 1
    anotado = resumen.renglones[0]
    assert anotado.con_precio == 3
    assert anotado.sin_precio == 1
    assert anotado.motivos == (SESION_CADUCADA,)
    assert len(almacenamiento.precios) == 4


def test_un_proveedor_que_falla_no_tumba_los_demas_renglones():
    """Y el lote sigue con los otros tres renglones, que es la casilla entera."""
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = DoyleFalso()
    for n in range(1, 4):
        clave = _clave(n)
        doyle.resultados_por_termino[clave] = {
            "nadro": respuesta_con_error("nadro", "el portal no contestó"),
            "levic": respuesta_lista("levic", [(clave, "86.05", "40")]),
            "vicma": respuesta_lista("vicma", [(clave, "90.00", "10")]),
            "quepharma": respuesta_lista("quepharma", [(clave, "95.00", "2")]),
        }

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert resumen.final == TERMINO
    assert resumen.consultados == 3
    assert resumen.con_precio == 3
    assert dict(resumen.motivos)[PORTAL_SIN_CONTESTAR] == 3


class _DoyleQueFallaEnUnaClave:
    """Doyle que truena al pedir la búsqueda de una clave y contesta el resto.

    `DoyleFalso.falla` es global —o truena siempre o nunca—, y lo que hace
    falta probar aquí es lo contrario: que **un** renglón que no se pudo
    consultar no se lleve por delante a los que venían detrás.
    """

    def __init__(self, bueno: DoyleFalso, clave_mala: str):
        self._bueno = bueno
        self._clave_mala = clave_mala
        self.pedidos: list[str] = []

    def pedir_busqueda(self, termino: str):
        self.pedidos.append(termino)
        if termino == self._clave_mala:
            raise ConnectionError("Doyle no contestó")
        return self._bueno.pedir_busqueda(termino)

    def estado_de_busqueda(self, job_id: str):
        return self._bueno.estado_de_busqueda(job_id)

    def sesiones(self):
        return self._bueno.sesiones()


def test_un_renglon_que_no_se_pudo_consultar_no_tumba_el_lote():
    """Doyle caído para un renglón: se anota `no se pudo` y se sigue.

    El motivo que viaja es el **tipo** de la falla y nunca su texto (regla 5 de
    `CLAUDE.md`): un `str(exc)` de SQLAlchemy lleva la cadena de conexión con
    contraseña, y esto acaba en el journal de atlas.
    """
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = _DoyleQueFallaEnUnaClave(_doyle_que_contesta(3), _clave(2))

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert resumen.final == TERMINO
    assert resumen.consultados == 2
    assert resumen.no_se_pudo == 1
    fallido = next(r for r in resumen.renglones if r.final == NO_SE_PUDO)
    assert "ConnectionError" in fallido.detalle
    assert "Doyle no contestó (" in fallido.detalle


def test_un_renglon_sin_clave_no_molesta_a_ningun_portal():
    """Sin EAN no hay con qué buscar, y buscarlo por su nombre trae otro producto.

    Es la misma negativa que da la pantalla (ADR 0002), con la misma razón, y
    se dice en el resumen: se arregla en SICAR, no aquí.
    """
    almacen = _mundo(2)
    # El producto 2 se vendió y no está en el catálogo: su renglón nace sin clave.
    almacen.catalogo_en_memoria = [_producto(1)]
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(2)

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert resumen.sin_clave == 1
    assert doyle.pedidos == [_clave(1)]


# ------------------------------- no dejar la lista peor que antes de correr


class _AlmacenamientoQueMuere(AlmacenamientoFalso):
    """El almacenamiento que se muere a la mitad de la corrida.

    `KeyboardInterrupt` y no un `Exception` cualquiera a propósito: lo que se
    quiere probar es **el lote matado a la mitad** —un `systemctl stop`, un
    Ctrl-C, la máquina que se apaga— y no una falla que el código ya atrapa. Es
    además lo que demuestra que el `except BaseException` del lote deja
    bitácora incluso ahí, en vez de morirse callado.
    """

    def __init__(self, morir_en: int):
        super().__init__()
        self.morir_en = morir_en
        self.guardadas = 0

    def guardar_precios(self, negocio, renglon_id, lecturas):
        self.guardadas += 1
        if self.guardadas > self.morir_en:
            raise KeyboardInterrupt("alguien mató el lote")
        return super().guardar_precios(negocio, renglon_id, lecturas)


def test_un_lote_muerto_a_la_mitad_deja_lo_consultado_guardado():
    """**La casilla de "no dejar la lista peor".** Lo que alcanzó, se queda.

    Lo garantiza el ADR 0004 —`pedidos.precio_de_proveedor` **solo crece**— más
    el hecho de que el lote no tiene un solo `UPDATE` de renglón. Aquí se
    comprueba de verdad matándolo: dos renglones guardados, el tercero muere, y
    las ocho filas de los dos primeros siguen ahí.
    """
    almacen = _mundo(5)
    almacenamiento = _AlmacenamientoQueMuere(morir_en=2)

    with pytest.raises(KeyboardInterrupt):
        _correr(almacen, almacenamiento, _doyle_que_contesta(5))

    assert len(almacenamiento.precios) == 8
    guardado = almacenamiento.leer(NEGOCIO, HOY)
    assert guardado is not None
    assert len(guardado.renglones) == 5


def test_un_lote_muerto_a_la_mitad_no_toca_un_solo_renglon():
    """La lista queda como estaba: mismos renglones, mismos estados, misma cantidad.

    "Peor que antes" sería un renglón descartado, una cantidad cambiada o una
    lista cerrada a medias. Nada de eso puede pasar porque el lote no lo
    escribe, y esto lo comprueba comparando la foto de antes con la de después.
    """
    almacen = _mundo(5)
    almacenamiento = _AlmacenamientoQueMuere(morir_en=2)

    # Primero se arma la lista sin morir, para tener la foto de antes.
    almacenamiento.morir_en = 99
    _correr(almacen, almacenamiento, _doyle_que_contesta(5))
    antes = almacenamiento.leer(NEGOCIO, HOY)
    precios_antes = len(almacenamiento.precios)

    # Y ahora el lote vuelve a correr y se muere a la mitad.
    almacenamiento.guardadas = 0
    almacenamiento.morir_en = 2
    with pytest.raises(KeyboardInterrupt):
        _correr(almacen, almacenamiento, _doyle_que_contesta(5))

    despues = almacenamiento.leer(NEGOCIO, HOY)
    assert despues is not None and antes is not None
    assert despues.estado == antes.estado
    assert [r.renglon_id for r in despues.renglones] == [
        r.renglon_id for r in antes.renglones
    ]
    assert [r.estado for r in despues.renglones] == [r.estado for r in antes.renglones]
    assert [r.cantidad_a_pedir for r in despues.renglones] == [
        r.cantidad_a_pedir for r in antes.renglones
    ]
    # Solo creció, y eso es lo que el ADR 0004 decidió.
    assert len(almacenamiento.precios) > precios_antes


def test_un_lote_muerto_a_la_mitad_deja_bitacora(caplog):
    """Una noche sin saber que el lote corrió es el hilo abierto 3 de HANDOVER.

    El resumen se escribe en un `finally`, así que sale hasta cuando alguien
    mata el proceso — con lo que alcanzó a hacer antes de morirse. Y la
    excepción **sigue subiendo**: tragársela sería la falla silenciosa que la
    regla 4 de `CLAUDE.md` prohíbe, y el proceso tiene que salir distinto de
    cero para que systemd lo marque en rojo.
    """
    almacen = _mundo(5)
    almacenamiento = _AlmacenamientoQueMuere(morir_en=2)

    with caplog.at_level(logging.INFO, logger="continental"):
        with pytest.raises(KeyboardInterrupt):
            _correr(almacen, almacenamiento, _doyle_que_contesta(5))

    assert SE_INTERRUMPIO in caplog.text
    assert "KeyboardInterrupt" in caplog.text
    assert "sigue guardado" in caplog.text
    # Y dice lo que SÍ alcanzó a hacer, que es la diferencia entre una bitácora
    # y un renglón de ruido: dos renglones consultados antes de morirse, no
    # cero. Una bitácora que dijera "0 renglones" sobre una noche en la que se
    # consultaron ciento veinte parece un dato y no lo es.
    assert "2 consultados" in caplog.text
    assert "después de 2 renglón(es)" in caplog.text


def test_el_lote_no_borra_ni_cambia_renglones(monkeypatch):
    """Ninguna de las cuatro operaciones que MODIFICAN un renglón se llama.

    Descartar, devolver a abierto, corregir la cantidad y cerrar la lista son
    las cuatro maneras de dejar la lista distinta, y el lote no usa ninguna.
    Lo comprueba una prueba y no un comentario: el día que alguien meta un
    "ya que estamos, cerramos la lista", esto se pone rojo.
    """
    almacenamiento = AlmacenamientoFalso()
    llamadas: list[str] = []

    for nombre in ("descartar", "devolver_a_abierto", "ajustar_la_cantidad", "cerrar"):
        monkeypatch.setattr(
            almacenamiento,
            nombre,
            lambda *a, _n=nombre, **k: llamadas.append(_n),
            raising=True,
        )

    _correr(_mundo(3), almacenamiento, _doyle_que_contesta(3))

    assert llamadas == []


# ------------------------------------------------------ orden en la corrida


def test_el_lote_consulta_en_el_orden_de_importancia():
    """Con clase en el catálogo, Doyle recibe las claves en orden A, B, C.

    Se mira desde fuera —`DoyleFalso.pedidos`, que guarda los términos en el
    orden en que llegaron— y no desde dentro de la implementación.
    """
    almacen = _mundo(3, clases={1: "C", 2: "A", 3: "B"})
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(3)

    resumen, _ = _correr(almacen, almacenamiento, doyle)

    assert doyle.pedidos == [_clave(2), _clave(3), _clave(1)]
    assert resumen.orden is not None and resumen.orden.cumple_el_orden is True


def test_hoy_el_lote_corre_pero_declara_que_el_orden_no_se_cumple():
    """**Lo que pasa hoy en atlas, escrito como prueba.**

    El lote corre y trae precios —eso sí se puede— pero deja dicho, en el
    resumen y en la bitácora, que el orden por clase ABC no se cumplió. La
    casilla del ticket se queda sin marcar por esto, no por olvido.
    """
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()

    resumen, _ = _correr(almacen, almacenamiento, _doyle_que_contesta(3))

    assert resumen.final == TERMINO
    assert resumen.con_precio == 3
    assert resumen.orden is not None
    assert resumen.orden.cumple_el_orden is False
    assert "SIN CUMPLIR" in resumen.como_texto()


def test_el_lote_es_secuencial_y_por_eso_doyle_puede_reutilizar_el_navegador():
    """Lo único de la casilla del ADR 0008 que a Continental le toca.

    Continental no abre navegadores nunca (regla 1) y el navegador reutilizado
    vive en Doyle. Lo que sí depende de aquí es **no pedirle cuatro búsquedas a
    la vez**: un lote concurrente sería justo lo que le impediría reutilizar lo
    que tenga abierto. Se comprueba que cada búsqueda terminó antes de que
    empezara la siguiente.
    """
    almacen = _mundo(3)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(3)
    orden_real: list[str] = []

    pedir = doyle.pedir_busqueda
    estado = doyle.estado_de_busqueda
    doyle.pedir_busqueda = lambda t: (orden_real.append(f"pide {t}"), pedir(t))[1]
    doyle.estado_de_busqueda = lambda j: (
        orden_real.append(f"lee {j}"),
        estado(j),
    )[1]

    _correr(almacen, almacenamiento, doyle)

    # pide/lee, pide/lee, pide/lee: nunca dos "pide" seguidos.
    assert orden_real == [
        "pide " + _clave(1),
        "lee trabajo-1",
        "pide " + _clave(2),
        "lee trabajo-2",
        "pide " + _clave(3),
        "lee trabajo-3",
    ]


# ------------------------------------------------------------- la bitácora


def test_la_corrida_escribe_su_resumen_en_la_bitacora(caplog):
    """La casilla de la bitácora: cuántos consultó, cuántos sin precio y por qué.

    Va al `journal` de systemd a través de `logging`, que es donde esta casa ya
    mira "cómo le fue anoche" —farmacia-data hace exactamente eso con
    `farmacia-diario`—. El porqué de que sea el journal y no una tabla nueva
    está en el ADR 0006.
    """
    almacen = _mundo(2)
    almacenamiento = AlmacenamientoFalso()
    clave = _clave(1)
    doyle = _doyle_que_contesta(2)
    doyle.resultados_por_termino[clave] = {
        p: respuesta_con_sesion_caducada(p) for p in LOS_CUATRO
    }

    with caplog.at_level(logging.INFO, logger="continental"):
        _correr(almacen, almacenamiento, doyle)

    bitacora = caplog.text
    assert "lote nocturno" in bitacora
    assert "2 en la lista" in bitacora
    assert "2 consultados" in bitacora
    assert "1 con precio" in bitacora
    assert "1 sin precio" in bitacora
    assert SESION_CADUCADA in bitacora


def test_el_resumen_que_se_devuelve_es_el_mismo_que_se_escribio(caplog):
    """Lo que se imprime y lo que se devuelve no pueden ser dos cosas distintas.

    Es el bicho que la caja de un elemento evita: el `finally` que manda el
    resumen a la bitácora corre **después** de que el `return` ya se llevó su
    valor, así que una reasignación ahí no llegaría a quien llama — y el
    journal diría "0.0 min" mientras el resumen devuelto dice otra cosa.
    """
    almacen = _mundo(2)
    almacenamiento = AlmacenamientoFalso()
    doyle = _doyle_que_contesta(2, vueltas_pendientes=1)

    with caplog.at_level(logging.INFO, logger="continental"):
        resumen, _ = _correr(
            almacen, almacenamiento, doyle, tope_seg=3600.0, cada_seg=60.0
        )

    assert resumen.segundos == pytest.approx(120.0)
    assert resumen.como_texto() in caplog.text


# =========================================================================
# EL TIMER Y SU UNIDAD — lo que se puede revisar sin atlas
# =========================================================================
#
# Ninguna de estas pruebas sale de la torre: no se instala nada, no se arranca
# nada y no se toca 192.168.100.14. Lo que se revisa es el **contenido de los
# archivos que se van a desplegar**, que es donde vive el daño — la lección
# cara de Marlowe: `StartLimitIntervalSec` en la sección equivocada, ignorado
# en silencio por systemd durante meses.
#
# Los finales de línea (LF y no CRLF) no se revisan aquí: ya los revisa
# `test_compila.py`, que camina el repo buscando `.sh`, `.service`, `.timer` y
# `.sql`. Estos dos archivos estrenan dos casos suyos.


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _seccion(texto: str, nombre: str) -> str:
    """El cuerpo de una sección de un `.ini`, sin las que vienen después.

    Anclada a principio de línea y no con un `index()`: los comentarios de
    estas unidades nombran `[Service]` y `[Install]` para explicar dónde va
    cada llave y por qué, y un `index()` encontraría primero la prosa.
    """
    encabezado = re.search(rf"^\[{nombre}\]", texto, re.MULTILINE)
    assert encabezado, f"No hay sección [{nombre}]."
    siguiente = re.search(r"^\[", texto[encabezado.end() :], re.MULTILINE)
    fin = encabezado.end() + siguiente.start() if siguiente else len(texto)
    return texto[encabezado.start() : fin]


def _llaves(seccion: str) -> dict[str, list[str]]:
    """Las llaves de una sección, **ignorando los comentarios**.

    Sin esto, la prueba de que no hay `Restart=` se pondría roja por el
    comentario que explica justamente por qué no lo hay.
    """
    pares: dict[str, list[str]] = {}
    for linea in seccion.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or limpia.startswith("["):
            continue
        if "=" in limpia:
            llave, _, valor = limpia.partition("=")
            pares.setdefault(llave.strip(), []).append(valor.strip())
    return pares


def test_la_unidad_y_el_timer_existen_y_son_utf8():
    assert SERVICIO.exists(), "Falta scripts/systemd/continental-lote.service."
    assert TIMER.exists(), "Falta scripts/systemd/continental-lote.timer."
    _texto(SERVICIO)
    _texto(TIMER)


def test_el_timer_dispara_despues_de_la_cadena_de_las_2030():
    """**La primera casilla del ticket.** La cadena es lun-vie 20:30 en atlas.

    El lote tiene que correr después porque la lista del día se arma con las
    ventas que esa cadena acaba de meter: uno que corriera antes armaría la
    lista de ayer y le traería precios.

    La prueba mira la hora escrita y comprueba que es **posterior** a las
    20:30, no que sea un literal concreto: el día que el hilo abierto 5 mueva
    la cadena a las 21:00 y esto a las 22:30, la prueba sigue valiendo.
    """
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    assert len(llaves["OnCalendar"]) == 1, (
        "Con dos OnCalendar el timer dispara dos veces por día y serían dos "
        "lotes contra los mismos portales."
    )
    calendario = llaves["OnCalendar"][0]

    dias, _, hora = calendario.rpartition(" ")
    horas, _, minutos = hora.partition(":")
    assert dias == "Mon-Fri", (
        "Lun-vie, igual que la cadena: el respaldo de SICAR sube de lunes a "
        "viernes y el sábado no hay datos nuevos que traer."
    )
    assert int(horas) * 60 + int(minutos) > 20 * 60 + 30, (
        f"El lote dispara a las {hora} y la cadena de farmacia-data corre a "
        "las 20:30. Tiene que ser después, con colchón."
    )


def test_el_timer_dispara_la_unidad_del_lote():
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    assert llaves["Unit"] == ["continental-lote.service"]


def test_el_timer_se_instala_en_timers_y_la_unidad_no_arranca_al_bootear():
    """El que se habilita es el timer; la unidad no lleva `[Install]`.

    Un `WantedBy=multi-user.target` en el servicio arrancaría el lote en cada
    arranque de atlas, a la hora que fuera, contra los portales del dueño en
    horario de mostrador.
    """
    assert _llaves(_seccion(_texto(TIMER), "Install"))["WantedBy"] == ["timers.target"]
    assert not re.search(r"^\[Install\]", _texto(SERVICIO), re.MULTILINE), (
        "continental-lote.service no debe tener [Install]: quien se habilita "
        "es el timer."
    )


def test_el_timer_no_es_persistente():
    """Sin `Persistent=true`, y es una decisión, no un olvido.

    Con él, un atlas que estuvo apagado a las 22:00 dispararía el lote en
    cuanto arrancara —a las nueve de la mañana— y serían cuatro navegadores
    contra los portales del dueño durante una hora, en horario de mostrador,
    por una lista que el encargado ya tiene enfrente y cuyos precios puede
    pedir con un botón.
    """
    assert "Persistent" not in _llaves(_seccion(_texto(TIMER), "Timer"))


def test_el_timer_avisa_de_que_hay_que_moverlo_con_la_cadena():
    """El hilo abierto 5 de HANDOVER, escrito donde lo va a leer quien edite esto.

    Si el respaldo de SICAR se mueve a las ~20:15, la cadena se mueve a las
    21:00 y **esto se mueve en el mismo movimiento**. Moverla a ella y no a
    esto dejaría el lote armando la lista con las ventas de ayer, sin fallar y
    sin avisar.
    """
    texto = _texto(TIMER)
    assert "20:15" in texto and "21:00" in texto
    assert "SI SE MUEVE LA CADENA" in texto


def test_la_unidad_es_de_una_corrida_y_no_un_servicio_persistente():
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    assert llaves["Type"] == ["oneshot"]
    assert "Restart" not in llaves, (
        "Un lote que falla a media noche NO se reintenta solo: lo consultado "
        "ya está guardado y volver a empezar molestaría otra vez a los cuatro "
        "portales por renglones que ya tienen precio."
    )


def test_la_unidad_le_da_tiempo_al_tope_de_sesenta_minutos():
    """**Sin esto el tope de 60 minutos no existiría.**

    `Type=oneshot` usa `TimeoutStartSec` para matar el proceso, y el valor por
    omisión de systemd son 90 segundos: el lote alcanzaría a consultar un
    puñado de renglones, la unidad quedaría en `failed` cada noche y el journal
    diría "timeout" en vez de decir que se consultaron nueve de trescientos.

    Tiene que ser mayor que el tope del YAML, y con margen: el tope se mira
    antes de cada renglón, no en medio de uno, así que el lote se puede pasar
    por lo que dure el que estaba en curso.
    """
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    crudo = llaves["TimeoutStartSec"][0]

    assert crudo.endswith("min"), f"TimeoutStartSec={crudo} no se lee en minutos."
    minutos = float(crudo.removesuffix("min"))
    assert minutos > TOPE_POR_OMISION_MIN, (
        f"TimeoutStartSec son {minutos} min y el tope del lote son "
        f"{TOPE_POR_OMISION_MIN}. systemd mataría el lote antes de que el tope "
        "llegara a cumplirse."
    )
    assert minutos >= TOPE_POR_OMISION_MIN + 2, (
        "El margen tiene que cubrir al menos el renglón en curso: el tope por "
        "consulta son 120 s."
    )


def test_la_unidad_corre_el_modulo_del_lote_con_el_venv_de_atlas():
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    ejecuta = llaves["ExecStart"][0]

    assert ejecuta.startswith("/home/eddie/proyectos/Continental/.venv/bin/python"), (
        "El venv de atlas se crea con --system-site-packages (Athlon II X4 de "
        "2010 sin SSSE3). El python del sistema no serviría."
    )
    assert ejecuta.endswith("-m continental.lote")
    assert llaves["WorkingDirectory"] == ["/home/eddie/proyectos/Continental"], (
        "En atlas el repo va PLANO, hermano de ~/proyectos/Marlowe."
    )
    assert llaves["Environment"] == ["PYTHONPATH=/home/eddie/proyectos/Continental/src"]


def test_la_unidad_no_abre_un_navegador():
    """Regla 1 de `CLAUDE.md`: Continental no toca un navegador nunca.

    Ni `xvfb-run` ni `DISPLAY`. Quien abre navegadores es Doyle, en su propio
    proceso y con su propio ADR 0008. Se mira el archivo **sin comentarios**:
    la unidad habla de `xvfb-run` en prosa justamente para dejar escrito por
    qué aquí no va.
    """
    sin_prosa = "\n".join(
        linea
        for linea in _texto(SERVICIO).splitlines()
        if not linea.strip().startswith("#")
    )

    assert "xvfb" not in sin_prosa.lower()
    assert "DISPLAY" not in sin_prosa


def test_la_unidad_no_escucha_en_ningun_puerto():
    """El lote no es un servidor: no tiene nada que ver con el gateway de `borde`.

    Un `CONTINENTAL_HOST` aquí sería copiar de `continental-web.service` sin
    preguntarse para qué, y dejaría a quien lo lea buscando un puerto que no
    existe.
    """
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    entorno = " ".join(llaves.get("Environment", []))

    assert "CONTINENTAL_HOST" not in entorno
    assert "8585" not in entorno


def test_la_unidad_depende_de_docker_y_no_de_doyle():
    """Docker sí —ahí vive el almacén—; Doyle no, y por dos razones.

    Doyle caído no es un lote fallido: es una corrida en la que cada renglón
    queda con su motivo (regla 4). Y `doyle-web.service` **no existe** en atlas
    al 2026-09-19 —el ADR 0008 de Doyle está sin hacer—, así que requerirla
    haría fallar el arranque de esta unidad.
    """
    llaves = _llaves(_seccion(_texto(SERVICIO), "Unit"))

    assert llaves["Requires"] == ["docker.service"]
    assert "doyle" not in " ".join(llaves.get("Requires", []) + llaves.get("After", []))


def test_la_unidad_no_finge_ordenarse_despues_de_la_cadena():
    """`After=farmacia-diario.service` no ordenaría nada y se leería como si sí.

    `After=` solo ordena unidades que arrancan en la misma transacción de
    systemd, y estas dos las disparan timers distintos a horas distintas. Lo
    que de verdad las separa es la hora del timer, con su colchón.
    """
    llaves = _llaves(_seccion(_texto(SERVICIO), "Unit"))

    assert "farmacia-diario" not in " ".join(
        llaves.get("After", []) + llaves.get("Requires", []) + llaves.get("Wants", [])
    )
    # Y lo dice en prosa, que es donde lo va a leer quien se lo pregunte.
    assert "misma transacción" in _texto(SERVICIO).lower()
