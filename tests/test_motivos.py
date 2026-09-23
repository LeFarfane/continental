"""Los tres motivos distinguibles y el botón de completar (ticket 19).

La frase que define el ticket: **que el encargado pueda arreglar solo lo que
falló de noche**. De ahí salen las tres cosas que este archivo vigila.

1. **"Sin precio" son seis cosas y no una.** Hasta el ticket 18 un renglón sin
   lecturas se veía como *"nadie lo consultó"*, y eso es verdad y es **menos de
   lo que se sabe**: el lote pudo cortarse por tiempo antes de llegar, pudo no
   haber corrido, pudo intentarlo y no poder. Cada una se arregla distinto y
   por eso se dice distinto. Los otros dos motivos que el ticket nombra —*el
   portal no contestó* y *la sesión caducó*— son de un PROVEEDOR de un renglón
   y ya viven en `precio_de_proveedor.motivo` desde el ticket 12: son
   preguntas de dos granos distintos y salen de dos tablas distintas (ADR
   0007).

2. **"Faltar" es más estrecho que "estar incompleto", y ahí está el dinero.**
   Cada renglón que entre al botón de completar son cuatro visitas a portales
   ajenos con las credenciales del dueño, ~9 s por proveedor. Un renglón con
   UN precio no falta; uno sin EAN no falta; uno cuyos huecos son definitivos
   no falta. Las tres son decisiones y las tres están escritas como pruebas.

3. **La regla vive en Python y no en el JavaScript.** `por_que_no_hay_lectura`
   es una función pura con su tabla de casos; la pantalla escribe la frase que
   llega. Es exactamente el error que el ticket 15 arregló con la certeza del
   ganador, y que estaba en el único archivo que ninguna prueba de Python mira.

Casi todo se prueba **sin levantar la aplicación**. Las que pasan por
`TestClient` son las que demuestran que esto llega hasta el JSON de la lista y
que el botón consulta lo que dice consultar; las que leen `index.html`, que la
pantalla lo escribe en vez de inventárselo; las que leen `sql/`, que la quinta
tabla existe también fuera de Python.

**Ninguna prueba de este archivo duerme ni hace una petición HTTP.** El
lanzador del registro ejecuta la tarea ahí mismo (`conftest`), y la espera a
Doyle entra por argumento.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    FINALES_DE_LA_CORRIDA,
    SE_ACABO_EL_TIEMPO,
    SE_INTERRUMPIO,
    SIN_LISTA,
    TERMINO,
    CorridaDelLote,
    PrecioDeProveedor,
    Renglon,
    RenglonGuardado,
    columnas_de_la_corrida,
    revisar_la_corrida,
)
from continental.comparacion import comparar
from continental.consultas import (
    Completado,
    RegistroDeConsultas,
    consultar_en_fila,
    tope_del_completado_segundos,
)
from continental.dobles import (
    AlmacenamientoFalso,
    DoyleFalso,
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_lista,
)
from continental.faltantes import (
    DIAS_DEL_LOTE,
    EL_LOTE_NO_CORRIO,
    EL_LOTE_NO_LO_MIRO,
    EL_LOTE_NO_PUDO,
    EL_LOTE_SE_CORTO_POR_TIEMPO,
    EL_LOTE_SE_INTERRUMPIO,
    FRASE_EL_LOTE_NO_CORRIO,
    FRASE_NO_SE_PUDO_LEER_SI_CORRIO,
    HORA_DEL_LOTE,
    MOTIVOS_DEL_HUECO,
    MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO,
    NIVEL_ESPERA,
    NIVEL_FALLA,
    NUNCA_SE_CONSULTO,
    SE_PUEDE_REINTENTAR,
    SIN_CLAVE_QUE_BUSCAR,
    corrida_ausente_como_json,
    elegir_los_faltantes,
    faltantes_como_json,
    frase_de_espera,
    frase_de_la_corrida,
    hueco_como_json,
    huecos_que_se_pueden_reintentar,
    nivel_de_ausencia,
    por_que_falta,
    por_que_no_hay_lectura,
    proveedores_con_sesion_caducada,
    siguiente_corrida_programada,
    ultima_corrida_programada,
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
)
from continental.transito import ZONA_DE_LA_FARMACIA
from continental.web import app as modulo_app

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0004-la-corrida-del-lote-en-una-fila.sql"
LOTE_TIMER = RAIZ / "scripts" / "systemd" / "continental-lote.timer"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
INSTANTE = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.timezone.utc)

SIN_LECTURA_CLAVE = "7501000000001"
SIN_PRECIOS_CLAVE = "7501000000002"
UN_PRECIO_CLAVE = "7501000000003"
DEFINITIVO_CLAVE = "7501000000004"


# ------------------------------------------------------------- utilidades


def _texto(ruta: Path) -> str:
    """El archivo como texto, exigiendo UTF-8.

    En binario y decodificando a mano a propósito, igual que en
    `test_sql_del_pedido.py`: si alguien lo guarda en latin1, los acentos de
    `ck_corrida_final` se rompen y esta prueba se pone roja aquí, que es
    barato. La alternativa es descubrirlo en atlas a las 22:00, con el CHECK ya
    creado con el acento deformado y sin nadie mirando.
    """
    return ruta.read_bytes().decode("utf-8")


def _en_la_farmacia(fecha: dt.date, hora: int, minuto: int = 0) -> dt.datetime:
    """Un instante con la zona de la farmacia, sin pasar por `dt.time`."""
    return dt.datetime(
        fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=ZONA_DE_LA_FARMACIA
    )


def _fijar_la_hora(monkeypatch: pytest.MonkeyPatch, instante: dt.datetime) -> None:
    """Congela `_ahora()` de `web.app`, igual que `test_fallas._fijar_la_hora`.

    Sin esto, la ruta comparándose contra la HORA DE VERDAD haría que estas
    pruebas pasaran o fallaran según cuándo se corra el suite — exactamente
    lo que este repo prohíbe medir sin fecha (regla de `CLAUDE.md`: "lo que
    se mide se anota con la fecha y el número, no como afirmación general").
    """
    monkeypatch.setattr(modulo_app, "_ahora", lambda: instante)


def _corrida(**cambios) -> CorridaDelLote:
    base = dict(
        corrida_del_lote_id=1,
        negocio=NEGOCIO,
        pedido_sugerido_id=7,
        fecha_del_pedido=HOY,
        final=TERMINO,
        termino_en=INSTANTE,
        segundos=600.0,
        tope_minutos=60.0,
        en_la_lista=380,
        consultados=380,
        con_precio=300,
    )
    base.update(cambios)
    return CorridaDelLote(**base)


def _lectura(proveedor: str, precio: str | None = None, motivo: str | None = None):
    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=proveedor,
        consultado_en=INSTANTE,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        motivo=motivo,
    )


def _renglon(n: int, clave: str = "7501000000001") -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=n,
        estado="abierto",
        propuesto=Renglon(
            producto_id=n,
            clave=clave,
            descripcion=f"PRODUCTO {n}",
            piezas_vendidas=1.0,
            cantidad_propuesta=2,
            esta_en_el_catalogo=True,
            existencia=5.0,
            dias_de_cobertura=5.0,
            clasificacion="medicamento",
        ),
    )


def _producto(producto_id: int, clave: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="GRUP4",
        departamento="MED",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=250.0,
        costo=30.0,
        existencia=10.0,
        esta_activo=True,
        es_granel=False,
    )


def _venta(producto_id: int) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=HOY,
        producto_id=producto_id,
        cantidad=3.0,
        importe=30.0,
        costo=18.0,
        utilidad=12.0,
    )


_CLAVES = (
    SIN_LECTURA_CLAVE,
    SIN_PRECIOS_CLAVE,
    UN_PRECIO_CLAVE,
    DEFINITIVO_CLAVE,
)


def _poblar(almacen, doyle) -> None:
    """Los cuatro casos que el botón de completar tiene que saber distinguir.

    Uno sin ninguna lectura, uno consultado con huecos REINTENTABLES, uno con
    un solo precio, y uno consultado con huecos DEFINITIVOS. De los cuatro,
    solo dos faltan — y eso es la decisión cara del ticket.
    """
    almacen.catalogo_en_memoria = [
        _producto(i + 1, clave) for i, clave in enumerate(_CLAVES)
    ]
    almacen.ventas_en_memoria = [_venta(i + 1) for i in range(len(_CLAVES))]

    # Nadie lo ha consultado todavía, PERO Doyle tiene su respuesta preparada:
    # es el que el botón de completar sí va a preguntar, y si no la tuviera el
    # `DoyleFalso` se quedaría en `pendiente` —que es lo que hace un portal que
    # carga— y la consulta esperaría el tope entero. **Ninguna prueba de este
    # repo espera**, así que lo que no se prepara no se consulta.
    doyle.resultados_por_termino[SIN_LECTURA_CLAVE] = {
        p: respuesta_lista(p, [(SIN_LECTURA_CLAVE, "99.00", "10")])
        for p in ("nadro", "levic", "vicma", "quepharma")
    }

    # Se consultó, no dio ni un precio, y sus huecos SE ARREGLAN REINTENTANDO.
    doyle.resultados_por_termino[SIN_PRECIOS_CLAVE] = {
        "nadro": respuesta_con_sesion_caducada("nadro"),
        "levic": respuesta_con_error("levic", "se cayó la conexión"),
        "vicma": respuesta_con_sesion_caducada("vicma"),
        "quepharma": respuesta_con_error("quepharma", "se cayó la conexión"),
    }
    # Un solo proveedor con precio: NO falta, aunque tenga tres huecos
    # reintentables. Cuatro visitas para ganar como mucho una cotización más.
    doyle.resultados_por_termino[UN_PRECIO_CLAVE] = {
        "nadro": respuesta_lista("nadro", [(UN_PRECIO_CLAVE, "86.05", "40")]),
        "levic": respuesta_con_sesion_caducada("levic"),
        "vicma": respuesta_con_sesion_caducada("vicma"),
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
    }
    # Se consultó, no dio precio, y sus cuatro huecos son DEFINITIVOS: el
    # portal ya contestó y ese producto no está en ese catálogo con ese EAN.
    # Mañana contestaría lo mismo.
    doyle.resultados_por_termino[DEFINITIVO_CLAVE] = {
        p: respuesta_lista(p, []) for p in ("nadro", "levic", "vicma", "quepharma")
    }


def _por_clave(cliente) -> dict[str, dict]:
    return {r["clave"]: r for r in cliente.get(RUTA).json()["renglones"]}


def _pantalla() -> str:
    return pantalla_completa()


# =========================================================================
# CASILLA 1 — LOS TRES MOTIVOS, y los tres que hacen falta para no confundirlos
# =========================================================================


def test_sin_corrida_se_dice_que_el_lote_no_corrio():
    """**La mitad del hilo abierto 10.** No es lo mismo que "no llegó a éste".

    Hasta el ticket 19 los dos se veían idénticos —*"nadie lo consultó"*—, y
    se arreglan en sitios distintos: uno mirando por qué el timer no disparó,
    el otro apretando el botón de completar.
    """
    porque = por_que_no_hay_lectura(tiene_clave=True, corrida=None)

    assert porque.motivo == EL_LOTE_NO_CORRIO
    assert porque.seguro is True
    assert "timer" in porque.explicacion


def test_el_tope_se_dice_con_todas_sus_letras_y_no_como_error():
    """**El motivo que el ticket pide**, y el que el 18 dejó sin poder decir.

    Y se dice que NO es un error: detenerse al tope es lo que se le pide al
    lote. Un renglón marcado en rojo por el tope mandaría a alguien a buscar
    una falla que no existe.
    """
    porque = por_que_no_hay_lectura(
        tiene_clave=True,
        corrida=_corrida(final=SE_ACABO_EL_TIEMPO, consultados=210, en_la_lista=380),
    )

    assert porque.motivo == EL_LOTE_SE_CORTO_POR_TIEMPO
    assert porque.seguro is True
    assert "210 de 380" in porque.explicacion
    assert "No es un error" in porque.explicacion
    assert "botón de completar" in porque.explicacion


def test_una_corrida_cortada_no_se_confunde_con_el_tope():
    """Uno es el lote haciendo lo que se le pidió; el otro es una falla.

    Y lo primero que hay que mirar no es el mismo sitio: aquí, el journal de
    esa noche. Decirle "no alcanzó el tiempo" mandaría a subir el tope por una
    corrida que se cayó.
    """
    porque = por_que_no_hay_lectura(
        tiene_clave=True,
        corrida=_corrida(final=SE_INTERRUMPIO, consultados=7, en_la_lista=380),
    )

    assert porque.motivo == EL_LOTE_SE_INTERRUMPIO
    assert "journalctl -u continental-lote" in porque.explicacion


def test_una_corrida_entera_con_fallas_dice_que_lo_intento_y_no_pudo():
    """Doyle caído a media corrida. Se arregla levantándolo y reintentando."""
    porque = por_que_no_hay_lectura(
        tiene_clave=True, corrida=_corrida(final=TERMINO, no_se_pudo=12)
    )

    assert porque.motivo == EL_LOTE_NO_PUDO
    assert porque.seguro is False


def test_una_corrida_entera_y_limpia_dice_que_el_lote_no_lo_miro():
    """El renglón que estaba descartado esa noche y alguien devolvió después.

    **No se le dice "no alcanzó el tiempo"** porque el tope no tuvo nada que
    ver, y decirlo mandaría a subir `pedido.tope_lote_minutos` por un renglón
    que el tope nunca vio.
    """
    porque = por_que_no_hay_lectura(tiene_clave=True, corrida=_corrida(final=TERMINO))

    assert porque.motivo == EL_LOTE_NO_LO_MIRO
    assert porque.seguro is True
    assert "descartado" in porque.explicacion


def test_sin_clave_le_gana_a_todo_lo_demas():
    """Un renglón sin EAN no se consultó porque no había con qué.

    Le gana al tope y a la corrida cortada a propósito: quien lo lea tiene que
    ir a SICAR y no a apretar un botón, y buscarlo por su nombre traería el
    producto de otro (ADR 0002). Es la misma negativa que da la ruta del precio
    desde el ticket 12.
    """
    for corrida in (None, _corrida(final=SE_ACABO_EL_TIEMPO), _corrida()):
        porque = por_que_no_hay_lectura(tiene_clave=False, corrida=corrida)
        assert porque.motivo == SIN_CLAVE_QUE_BUSCAR
        assert "SICAR" in porque.explicacion


def test_con_tope_Y_fallas_la_misma_noche_no_se_afirma_cual_le_toco():
    """**Lo que el ADR 0007 renunció, dicho en vez de tapado.**

    Se guarda cuántos quedaron sin alcanzar, no cuáles. Esa noche hay dos
    maneras de haberse quedado sin lectura y de un renglón concreto no se puede
    decir cuál le tocó. La pantalla escribe "probablemente" con el otro número
    al lado, que es más honesto que elegir uno a cara o cruz y más útil que no
    decir nada.
    """
    porque = por_que_no_hay_lectura(
        tiene_clave=True,
        corrida=_corrida(final=SE_ACABO_EL_TIEMPO, consultados=210, no_se_pudo=4),
    )

    assert porque.motivo == EL_LOTE_SE_CORTO_POR_TIEMPO
    assert porque.seguro is False
    assert "4 renglón(es)" in porque.explicacion
    assert "no se puede afirmar" in porque.explicacion


def test_los_seis_motivos_del_hueco_son_alcanzables_y_ninguno_sobra():
    """Un motivo que nada produce es vocabulario muerto: se cuenta y nunca sale.

    Al revés también importa: un motivo que saliera sin estar en la tupla no se
    podría contar ni traducir. Los seis, y ninguno más.
    """
    salidos = {
        por_que_no_hay_lectura(tiene_clave=False, corrida=None).motivo,
        por_que_no_hay_lectura(tiene_clave=True, corrida=None).motivo,
        por_que_no_hay_lectura(
            tiene_clave=True, corrida=_corrida(final=SE_ACABO_EL_TIEMPO)
        ).motivo,
        por_que_no_hay_lectura(
            tiene_clave=True, corrida=_corrida(final=SE_INTERRUMPIO)
        ).motivo,
        por_que_no_hay_lectura(
            tiene_clave=True, corrida=_corrida(final=TERMINO, no_se_pudo=1)
        ).motivo,
        por_que_no_hay_lectura(tiene_clave=True, corrida=_corrida(final=TERMINO)).motivo,
    }

    assert salidos == set(MOTIVOS_DEL_HUECO)
    assert len(MOTIVOS_DEL_HUECO) == len(set(MOTIVOS_DEL_HUECO))


def test_los_otros_dos_motivos_del_ticket_siguen_siendo_del_PROVEEDOR():
    """*El portal no contestó* y *la sesión caducó* no se mudan aquí.

    Son de un proveedor de un renglón —hubo lectura y no hubo precio— y el
    tercero es del renglón entero. Dos granos distintos, dos tablas distintas
    (ADR 0007). Meterlos en el vocabulario del hueco los haría contarse dos
    veces.
    """
    assert PORTAL_SIN_CONTESTAR in MOTIVOS
    assert SESION_CADUCADA in MOTIVOS
    assert PORTAL_SIN_CONTESTAR not in MOTIVOS_DEL_HUECO
    assert SESION_CADUCADA not in MOTIVOS_DEL_HUECO


def test_el_hueco_viaja_con_su_frase_y_con_si_se_puede_afirmar():
    """Las tres cosas, porque la pantalla necesita las tres y no inventa ninguna."""
    json = hueco_como_json(
        por_que_no_hay_lectura(
            tiene_clave=True, corrida=_corrida(final=SE_ACABO_EL_TIEMPO, no_se_pudo=2)
        )
    )

    assert set(json) == {"motivo", "explicacion", "seguro"}
    assert json["motivo"] == EL_LOTE_SE_CORTO_POR_TIEMPO
    assert json["seguro"] is False


# ------------------------------------------- la frase de arriba de la tabla


def test_la_frase_de_la_corrida_se_escribe_TAMBIEN_cuando_fue_bien():
    """Callar en el caso bueno dejaría el silencio con dos significados.

    "Corrió y le fue bien" y "esta pantalla no lo cuenta" se verían idénticos,
    y el encargado no puede distinguirlos. **El silencio es el modo de falla
    que de verdad muerde**, y eso vale para la pantalla igual que para Kuma.
    """
    frase = frase_de_la_corrida(_corrida(final=TERMINO, segundos=1800.0))

    assert "consultó los 380 renglones" in frase
    assert "30 min" in frase


def test_la_frase_del_tope_dice_que_no_es_un_error():
    frase = frase_de_la_corrida(
        _corrida(final=SE_ACABO_EL_TIEMPO, consultados=210, en_la_lista=380)
    )

    assert "210 de 380" in frase
    assert "tope de 60 minutos" in frase
    assert "No es un error" in frase


def test_la_frase_de_una_corrida_cortada_manda_al_journal():
    frase = frase_de_la_corrida(_corrida(final=SE_INTERRUMPIO, consultados=7))

    assert "SE CORTÓ" in frase
    assert "journal" in frase


def test_la_frase_suma_lo_que_paso_ademas_y_solo_si_paso():
    """Un "0 no se pudo" en medio de la frase es ruido que tapa lo que importa."""
    limpia = frase_de_la_corrida(_corrida(final=TERMINO))
    fea = frase_de_la_corrida(_corrida(final=TERMINO, no_se_pudo=3, sin_clave=12))

    assert "ni una lectura" not in limpia
    assert "3 no dejaron ni una lectura" in fea
    assert "12 no tienen código de barras" in fea


def test_la_frase_escribe_el_singular_porque_pasa():
    """"1 no dejaron ni una lectura" se lee como una pantalla rota.

    Y pasa seguido: una noche con UN renglón que no se pudo consultar es lo
    ordinario cuando Doyle se cae un momento. Una pantalla que parece rota se
    deja de creer justo donde este ticket necesita que se le crea. Lo cazó el
    recorrido del navegador del 2026-09-19, no un `assert`.
    """
    frase = frase_de_la_corrida(_corrida(final=TERMINO, no_se_pudo=1, sin_clave=1))

    assert "1 no dejó ni una lectura" in frase
    assert "1 no tiene código de barras" in frase


def test_la_frase_repite_el_orden_sin_cumplir_solo_si_la_corrida_lo_guardo_asi():
    """La pantalla dice lo que `orden_cumplido` dice, y nada más.

    Desde el 2026-09-21 (enmienda del ADR 0006) ese campo es falso **solo**
    cuando ningún renglón de la lista traía clase ABC: una noche con algunos
    sin clase —el NULL a propósito del ADR 0018 de farmacia-data— se guarda en
    verdadero y aquí no aparece la queja. La regla no se repite en este
    módulo; se lee.
    """
    cumplido = frase_de_la_corrida(_corrida(final=TERMINO, orden_cumplido=True))
    sin_cumplir = frase_de_la_corrida(_corrida(final=TERMINO, orden_cumplido=False))

    assert "clase ABC" not in cumplido
    assert "no fue en orden de importancia por clase ABC" in sin_cumplir


def test_sin_corrida_la_frase_es_vacia_porque_escribe_la_pantalla():
    """"No corrió" no es un grado de "corrió": lleva otra frase y otro color."""
    assert frase_de_la_corrida(None) == ""


def test_la_frase_de_sin_lista_explica_y_no_se_lee_como_falla():
    """El pedido del dueño: una corrida sin lista, con su mensaje breve.

    `SIN_LISTA` nunca calcula `orden` (`lote.correr_el_lote` regresa antes de
    llegar ahí), así que `orden_cumplido` se guarda en falso —no porque el
    orden se haya incumplido, sino porque nunca hubo nada que ordenar. Sin la
    rama dedicada, esta frase heredaría el "y no fue en orden de importancia
    por clase ABC" de una corrida cualquiera, y una noche sin ventas se leería
    como una noche con un problema.
    """
    frase = frase_de_la_corrida(
        _corrida(
            final=SIN_LISTA,
            pedido_sugerido_id=None,
            fecha_del_pedido=None,
            en_la_lista=0,
            consultados=0,
            con_precio=0,
            orden_cumplido=False,
        )
    )

    assert "no armó lista" in frase
    assert "no había nada que reponer" in frase
    assert "clase ABC" not in frase
    assert "SE CORTÓ" not in frase
    assert "no fue en orden" not in frase


def test_la_frase_de_sin_lista_no_inventa_un_dia_concreto():
    """No hay `fecha_del_pedido` que anclar: `SIN_LISTA` es "nunca hubo una
    venta", no "hoy no vendió" (`almacen.ultima_fecha_con_ventas` es
    `max(fecha)` de toda la tabla). Decir "domingo" o "feriado" aquí sería
    afirmar un dato que esta corrida no trae.
    """
    frase = frase_de_la_corrida(_corrida(final=SIN_LISTA, pedido_sugerido_id=None))

    assert "domingo" not in frase.lower()
    assert "feriado" not in frase.lower()


# =========================================================================
# CUÁNDO NO HAY FILA: ¿ESPERA, O FALLA? (decisión del dueño, 2026-09-21)
# =========================================================================
#
# Hasta esta enmienda `corrida is None` se leía siempre igual — rojo, "el
# lote no corrió"—, compuesto en JavaScript. Ahora se distinguen tres causas
# y dos colores, decididos aquí contra el horario real de
# `continental-lote.timer` y no adivinados en la pantalla.

# Una semana de septiembre de 2026, con nombre — la misma que usa
# `test_fallas.py`, y la misma semana en la que corre esta sesión.
LUNES_14 = dt.date(2026, 9, 14)
MARTES_15 = dt.date(2026, 9, 15)
VIERNES_18 = dt.date(2026, 9, 18)
SABADO_19 = dt.date(2026, 9, 19)
DOMINGO_20 = dt.date(2026, 9, 20)
LUNES_21 = dt.date(2026, 9, 21)
MARTES_22 = dt.date(2026, 9, 22)


def test_el_horario_del_lote_no_se_separa_del_timer():
    """`DIAS_DEL_LOTE` y `HORA_DEL_LOTE`, contra el `OnCalendar` real.

    Si alguien mueve el timer —el aviso del propio archivo: "SI SE MUEVE LA
    CADENA, HAY QUE MOVER ESTO"— y no toca la constante, esta prueba se pone
    roja antes de que la pantalla empiece a decir un horario que ya no es el
    de atlas.
    """
    texto = _texto(LOTE_TIMER)
    encontrado = re.search(r"OnCalendar=(\S[^\n]*)", texto)
    assert encontrado, "no está OnCalendar en continental-lote.timer"
    assert encontrado.group(1).strip() == "Mon-Fri 22:00"
    assert DIAS_DEL_LOTE == frozenset({0, 1, 2, 3, 4})  # Mon-Fri = weekday() 0-4
    assert HORA_DEL_LOTE == dt.time(22, 0)


def test_la_ultima_programada_es_hoy_si_ya_paso_su_hora():
    ahora = _en_la_farmacia(MARTES_15, 23, 0)

    assert ultima_corrida_programada(ahora) == _en_la_farmacia(MARTES_15, 22, 0)


def test_la_ultima_programada_es_ayer_si_todavia_no_llega_su_hora():
    ahora = _en_la_farmacia(MARTES_15, 20, 0)

    assert ultima_corrida_programada(ahora) == _en_la_farmacia(LUNES_14, 22, 0)


def test_la_ultima_programada_en_fin_de_semana_es_el_viernes():
    """Sábado y domingo, cualquier hora: el lote no corre en fin de semana."""
    assert ultima_corrida_programada(_en_la_farmacia(SABADO_19, 8, 0)) == _en_la_farmacia(
        VIERNES_18, 22, 0
    )
    assert ultima_corrida_programada(_en_la_farmacia(DOMINGO_20, 23, 0)) == _en_la_farmacia(
        VIERNES_18, 22, 0
    )
    assert ultima_corrida_programada(_en_la_farmacia(LUNES_21, 8, 0)) == _en_la_farmacia(
        VIERNES_18, 22, 0
    )


def test_la_siguiente_programada_un_viernes_de_noche_es_el_lunes():
    """El viernes por la noche, después de las 22:00: no hay sábado que cuente."""
    assert siguiente_corrida_programada(_en_la_farmacia(VIERNES_18, 23, 0)) == (
        _en_la_farmacia(LUNES_21, 22, 0)
    )


def test_la_siguiente_programada_en_fin_de_semana_es_el_lunes():
    assert siguiente_corrida_programada(_en_la_farmacia(SABADO_19, 8, 0)) == (
        _en_la_farmacia(LUNES_21, 22, 0)
    )
    assert siguiente_corrida_programada(_en_la_farmacia(DOMINGO_20, 23, 0)) == (
        _en_la_farmacia(LUNES_21, 22, 0)
    )


def test_la_siguiente_programada_hoy_si_todavia_no_llega_su_hora():
    assert siguiente_corrida_programada(_en_la_farmacia(MARTES_15, 8, 0)) == (
        _en_la_farmacia(MARTES_15, 22, 0)
    )


def test_nivel_espera_cuando_la_lista_es_mas_nueva_que_la_ultima_programada():
    """Nada está mal: el lote todavía no ha tenido su turno sobre esta lista."""
    ahora = _en_la_farmacia(MARTES_15, 10, 0)  # última programada: lunes 22:00
    armado_en = _en_la_farmacia(MARTES_15, 9, 0)  # después del lunes 22:00

    assert nivel_de_ausencia(armado_en, ahora) == NIVEL_ESPERA


def test_nivel_falla_cuando_la_lista_es_mas_vieja_que_la_ultima_programada():
    """Ya debía haber pasado una corrida sobre esta lista y no dejó fila."""
    ahora = _en_la_farmacia(MARTES_15, 10, 0)  # última programada: lunes 22:00
    armado_en = _en_la_farmacia(LUNES_14, 20, 0)  # antes del lunes 22:00

    assert nivel_de_ausencia(armado_en, ahora) == NIVEL_FALLA


def test_nivel_espera_de_viernes_de_noche_a_lunes_pese_al_fin_de_semana():
    """El caso que pidió la ronda: viernes en la noche → lunes, con el fin de
    semana de por medio y SIN que el lote corra en él. Una lista armada el
    viernes a las 22:30 —después de la corrida de esa misma noche— sigue en
    espera el lunes por la mañana: no hay ninguna corrida programada entre
    medio (el lote no corre sábado ni domingo), así que el lunes 22:00 sigue
    siendo la primera que le toca.
    """
    armado_en = _en_la_farmacia(VIERNES_18, 22, 30)
    ahora_el_lunes_de_manana = _en_la_farmacia(LUNES_21, 8, 0)

    assert nivel_de_ausencia(armado_en, ahora_el_lunes_de_manana) == NIVEL_ESPERA


def test_nivel_falla_de_viernes_de_noche_a_lunes_si_se_armo_antes_de_las_22():
    """El contraste: armada ANTES de la corrida del viernes —no después—, esa
    misma corrida ya debía haber pasado por ella. Sin fila el lunes por la
    mañana, es una falla y no una espera larga por el fin de semana.
    """
    armado_en = _en_la_farmacia(VIERNES_18, 21, 0)
    ahora_el_lunes_de_manana = _en_la_farmacia(LUNES_21, 8, 0)

    assert nivel_de_ausencia(armado_en, ahora_el_lunes_de_manana) == NIVEL_FALLA


def test_nivel_falla_gana_siempre_a_la_hora_cuando_la_lectura_se_cae():
    """Una LECTURA que se cae es rojo siempre, sin importar cuándo se armó la
    lista: de ahí no se sabe nada, ni siquiera si hubo o no una corrida.
    """
    ahora = _en_la_farmacia(MARTES_15, 10, 0)
    recien_armada = _en_la_farmacia(MARTES_15, 9, 59)  # sería ámbar sin el fallo

    assert (
        nivel_de_ausencia(recien_armada, ahora, fallo_de_lectura=True) == NIVEL_FALLA
    )


def test_la_frase_de_espera_dice_hoy_cuando_la_proxima_es_hoy():
    ahora = _en_la_farmacia(MARTES_15, 8, 0)  # la siguiente: hoy a las 22:00

    frase = frase_de_espera(ahora)

    assert "le toca hoy a las 22:00" in frase


def test_la_frase_de_espera_dice_el_dia_cuando_no_es_hoy():
    ahora = _en_la_farmacia(VIERNES_18, 23, 0)  # la siguiente: el lunes

    frase = frase_de_espera(ahora)

    assert "le toca el lunes a las 22:00" in frase


def test_corrida_ausente_como_json_en_ambar_no_tiene_las_causas_de_falla():
    ahora = _en_la_farmacia(MARTES_15, 10, 0)
    armado_en = _en_la_farmacia(MARTES_15, 9, 0)

    ausente = corrida_ausente_como_json(armado_en, ahora)

    assert ausente["nivel"] == NIVEL_ESPERA
    assert "atlas" not in ausente["frase"]
    assert "que_hacer" not in ausente  # lo agrega `web.app`, no esta función


def test_corrida_ausente_como_json_en_rojo_trae_las_causas_utiles():
    ahora = _en_la_farmacia(MARTES_15, 10, 0)
    armado_en = _en_la_farmacia(LUNES_14, 20, 0)

    ausente = corrida_ausente_como_json(armado_en, ahora)

    assert ausente["nivel"] == NIVEL_FALLA
    assert ausente["frase"] == FRASE_EL_LOTE_NO_CORRIO
    assert "atlas" in ausente["frase"] and "timer" in ausente["frase"]


def test_corrida_ausente_como_json_con_fallo_de_lectura_no_habla_de_atlas():
    """La lectura que se cae no sabe nada de por qué: no hereda las causas de
    "el lote no corrió", que sí sabe que no hay fila."""
    ahora = _en_la_farmacia(MARTES_15, 10, 0)
    armado_en = _en_la_farmacia(MARTES_15, 9, 0)  # sería ámbar sin el fallo

    ausente = corrida_ausente_como_json(armado_en, ahora, fallo_de_lectura=True)

    assert ausente["nivel"] == NIVEL_FALLA
    assert ausente["frase"] == FRASE_NO_SE_PUDO_LEER_SI_CORRIO
    assert "atlas" not in ausente["frase"]


# ------------------------------------------------------------- la ruta


def test_la_ruta_dice_espera_para_una_lista_recien_armada(
    cliente, almacen, doyle, almacenamiento, monkeypatch
):
    """La lista recién se armó: el lote todavía no ha tenido su turno."""
    almacen.catalogo_en_memoria = [_producto(1, SIN_LECTURA_CLAVE)]
    almacen.ventas_en_memoria = [_venta(1)]
    _fijar_la_hora(monkeypatch, _en_la_farmacia(MARTES_15, 10, 0))
    cliente.get(RUTA)  # arma la lista (con `armado_en` real; se fija abajo)
    almacenamiento.listas[0]["armado_en"] = _en_la_farmacia(MARTES_15, 9, 0)

    datos = cliente.get(RUTA).json()

    assert datos["corrida"] is None
    assert datos["corrida_ausente"]["nivel"] == NIVEL_ESPERA
    assert "todavía no pasa" in datos["corrida_ausente"]["frase"]
    assert datos["corrida_ausente"]["que_hacer"] is None


def test_la_ruta_dice_falla_para_una_lista_mas_vieja_que_la_ultima_programada(
    cliente, almacen, doyle, almacenamiento, monkeypatch
):
    """La lista ya llevaba encima una corrida programada y no dejó fila:
    atlas pudo estar apagado, el timer sin habilitar, la unidad en «failed».
    """
    almacen.catalogo_en_memoria = [_producto(1, SIN_LECTURA_CLAVE)]
    almacen.ventas_en_memoria = [_venta(1)]
    _fijar_la_hora(monkeypatch, _en_la_farmacia(MARTES_15, 10, 0))
    datos = cliente.get(RUTA).json()
    almacenamiento.listas[0]["armado_en"] = _en_la_farmacia(LUNES_14, 20, 0)

    despues = cliente.get(RUTA).json()

    assert despues["corrida"] is None
    assert despues["corrida_ausente"]["nivel"] == NIVEL_FALLA
    assert despues["corrida_ausente"]["frase"] == FRASE_EL_LOTE_NO_CORRIO
    assert "continental-lote" in despues["corrida_ausente"]["que_hacer"]


def test_la_ruta_dice_falla_cuando_la_lectura_de_la_corrida_se_cae(
    cliente, almacen, doyle, almacenamiento, monkeypatch
):
    """Una LECTURA que se cae es rojo siempre, y su `que_hacer` es el de
    cualquier otro hueco de lectura —vuelve a cargar la página—, no el de un
    lote que de verdad no corrió: de la lectura caída no se sabe cuál de las
    dos es.
    """
    almacen.catalogo_en_memoria = [_producto(1, SIN_LECTURA_CLAVE)]
    almacen.ventas_en_memoria = [_venta(1)]
    _fijar_la_hora(monkeypatch, _en_la_farmacia(MARTES_15, 10, 0))
    cliente.get(RUTA)  # arma la lista
    # Sería ÁMBAR sin el fallo: la lectura caída le gana igual (contraste con
    # `test_nivel_falla_gana_siempre_a_la_hora_cuando_la_lectura_se_cae`).
    almacenamiento.listas[0]["armado_en"] = _en_la_farmacia(MARTES_15, 9, 0)

    original = almacenamiento.ultima_corrida

    def caido(*a, **k):
        raise RuntimeError("se cayó Postgres")

    almacenamiento.ultima_corrida = caido
    try:
        despues = cliente.get(RUTA).json()
    finally:
        almacenamiento.ultima_corrida = original

    assert despues["corrida"] is None
    assert despues["corrida_ausente"]["nivel"] == NIVEL_FALLA
    assert despues["corrida_ausente"]["frase"] == FRASE_NO_SE_PUDO_LEER_SI_CORRIO
    assert "Vuelve a cargar" in despues["corrida_ausente"]["que_hacer"]


def test_la_ruta_no_confunde_una_lectura_caida_con_una_corrida_interrumpida(
    cliente, almacen, doyle, almacenamiento, monkeypatch
):
    """El contraste: cuando SÍ hay fila, una lectura caída no la tapa con el
    aviso de ausencia — las dos llaves son mutuamente excluyentes."""
    almacen.catalogo_en_memoria = [_producto(1, SIN_LECTURA_CLAVE)]
    almacen.ventas_en_memoria = [_venta(1)]
    _fijar_la_hora(monkeypatch, _en_la_farmacia(MARTES_15, 10, 0))
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_la_corrida(
        NEGOCIO,
        _corrida(pedido_sugerido_id=lista["pedido_sugerido_id"], final=TERMINO),
    )

    despues = cliente.get(RUTA).json()

    assert despues["corrida"] is not None
    assert despues["corrida_ausente"] is None


# =========================================================================
# CASILLA 2 — QUÉ CUENTA COMO FALTANTE. La decisión cara del ticket.
# =========================================================================


def test_un_renglon_sin_ninguna_lectura_falta():
    assert por_que_falta(comparar([]), tiene_clave=True) == NUNCA_SE_CONSULTO


def test_los_tres_reintentables_son_esos_tres_y_ningun_otro():
    """La lista está escrita a mano y eso es el punto: cada uno cuesta ~36 s.

    Un motivo que se cuele aquí son cuatro visitas a portales ajenos por cada
    renglón que lo tenga, todas las veces que alguien apriete el botón.
    """
    assert MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO == (
        PORTAL_SIN_CONTESTAR,
        SESION_CADUCADA,
        SIN_TIEMPO,
    )


@pytest.mark.parametrize("motivo", MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO)
def test_un_hueco_reintentable_hace_que_el_renglon_falte(motivo: str):
    """Los tres que se arreglan volviendo a preguntar, y ningún otro.

    `el portal no contestó` se reintenta; `la sesión caducó` se abre y se
    vuelve a consultar; `no alcanzó el tiempo` es literalmente que se acabó el
    tope con ese proveedor todavía buscando.
    """
    comparacion = comparar([_lectura("nadro", motivo=motivo)])

    assert por_que_falta(comparacion, tiene_clave=True) == SE_PUEDE_REINTENTAR


@pytest.mark.parametrize(
    "motivo",
    [SIN_RESULTADOS, NO_EMPAREJA, VARIOS_RESULTADOS, PRECIO_ILEGIBLE, SIN_SELECTORES],
)
def test_un_hueco_definitivo_NO_hace_que_el_renglon_falte(motivo: str):
    """Cada ausencia es una decisión, y ésta es la que acota el gasto.

    El portal ya contestó y ese producto no está en ese catálogo con ese EAN:
    volver a preguntar da lo mismo y cuesta nueve segundos. `no empareja` es
    además el final ORDINARIO de QuePharma (ADR 0002): meterlo aquí haría que
    el botón consultara media lista todas las veces, que es el lote completo
    con otro nombre.
    """
    comparacion = comparar([_lectura("nadro", motivo=motivo)])

    assert por_que_falta(comparacion, tiene_clave=True) is None


def test_un_renglon_con_UN_precio_no_falta_aunque_tenga_huecos_reintentables():
    """**La decisión que cuesta dinero, escrita como prueba.**

    Doyle no sabe preguntarle a un proveedor suelto: su `POST /api/buscar` va a
    los cuatro. Así que completar este renglón son cuatro visitas —~36 s— para
    ganar como mucho una cotización más, y eso es justo lo que el ticket
    prohíbe con *"sin volver a visitar portales por lo que ya tiene precio"*.

    **Lo que se renuncia:** ese renglón sigue teniendo su botón, el de uno
    solo, y ahí el gasto lo decide una persona mirándolo.
    """
    comparacion = comparar(
        [
            _lectura("nadro", precio="86.05"),
            _lectura("levic", motivo=SESION_CADUCADA),
            _lectura("vicma", motivo=PORTAL_SIN_CONTESTAR),
        ]
    )

    assert comparacion.con_precio == 1
    assert huecos_que_se_pueden_reintentar(comparacion)  # los tiene…
    assert por_que_falta(comparacion, tiene_clave=True) is None  # …y aun así no falta


def test_un_renglon_sin_EAN_no_falta_aunque_no_tenga_ni_una_lectura():
    """Apretar el botón mil veces no le pone código de barras: se arregla en SICAR."""
    assert por_que_falta(comparar([]), tiene_clave=False) is None


def test_los_faltantes_van_en_el_orden_de_la_lista():
    """El de urgencia con el que se armó, que es el que el encargado ve.

    Si el tope corta el completado, corta por donde él esperaría. Reordenar
    aquí por clase ABC sería un orden distinto al que el encargado ve.
    """
    renglones = [_renglon(n, clave=f"750100000000{n}") for n in (1, 2, 3)]
    comparaciones = {
        1: comparar([]),
        2: comparar([_lectura("nadro", precio="86.05")]),
        3: comparar([_lectura("nadro", motivo=PORTAL_SIN_CONTESTAR)]),
    }

    faltantes = elegir_los_faltantes(renglones, comparaciones)

    assert [f.renglon_id for f in faltantes] == [1, 3]
    assert [f.motivo for f in faltantes] == [NUNCA_SE_CONSULTO, SE_PUEDE_REINTENTAR]
    # La clave viaja dentro: es con lo que se busca, y quien recorra los
    # faltantes no debería tener que volver a buscarla.
    assert faltantes[0].clave == "7501000000001"


def test_un_renglon_sin_comparacion_no_entra_en_vez_de_reventar():
    """Falla hacia no gastar, nunca hacia gastar de más (regla 4)."""
    assert elegir_los_faltantes([_renglon(1)], {}) == ()


def test_los_faltantes_como_json_traen_el_total_aparte_de_la_lista():
    """El total va aparte aunque se pueda contar: es la etiqueta del botón.

    Un conteo que el navegador lleve a mano se separa de la verdad en cuanto
    hay dos pestañas abiertas en el mostrador.
    """
    renglones = [_renglon(n, clave=f"750100000000{n}") for n in (1, 2)]
    json = faltantes_como_json(
        elegir_los_faltantes(
            renglones,
            {
                1: comparar([]),
                2: comparar([_lectura("nadro", motivo=SESION_CADUCADA)]),
            },
        )
    )

    assert json["cuantos"] == 2
    assert json["sin_consultar"] == 1
    assert json["reintentables"] == 1
    assert [r["renglon_id"] for r in json["renglones"]] == [1, 2]
    # Y la explicación de los tres motivos que sí se reintentan, para que la
    # pantalla pueda decir por qué unos entran y otros no sin escribir la regla
    # por segunda vez.
    assert set(json["explicacion_de_los_motivos"]) == set(
        MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
    )


# ------------------------------------------------- a quién le caducó la sesión


def test_la_sesion_caducada_sale_de_las_lecturas_y_no_del_marcador_de_doyle():
    """El `guardada` de Doyle **no quiere decir que la sesión sirva**.

    El marcador solo dice que alguien confirmó una alguna vez, y el 2026-09-19
    los cuatro decían `guardada` con las cuatro caducadas (hilo abierto 1 de
    `HANDOVER.md`). Lo que sí lo demuestra es un portal que mandó al login, y
    eso es exactamente el motivo `la sesión caducó`.
    """
    caducadas = proveedores_con_sesion_caducada(
        [
            comparar([_lectura("vicma", motivo=SESION_CADUCADA)]),
            comparar(
                [
                    _lectura("nadro", motivo=SESION_CADUCADA),
                    _lectura("levic", motivo=PORTAL_SIN_CONTESTAR),
                ]
            ),
        ]
    )

    assert caducadas == ("nadro", "vicma")


def test_los_huecos_reintentables_de_un_renglon_dicen_de_quien_son():
    """La pantalla los usa para dos cosas: el botón de sesión y la explicación."""
    comparacion = comparar(
        [
            _lectura("nadro", precio="86.05"),
            _lectura("levic", motivo=SESION_CADUCADA),
            _lectura("vicma", motivo=NO_EMPAREJA),
        ]
    )

    assert huecos_que_se_pueden_reintentar(comparacion) == (
        ("levic", SESION_CADUCADA),
    )


# =========================================================================
# LA CORRIDA GUARDADA — el dato, sus reglas y el doble
# =========================================================================


def test_los_cuatro_finales_son_los_que_el_DDL_acepta():
    """El vocabulario vive en un sitio y el DDL lo repite en un CHECK.

    Se compara contra el archivo `.sql` como texto, que es lo que se puede
    hacer sin Postgres. Si los dos se separan, el lote escribe un valor que la
    base rechaza — a las 22:00 y sin nadie mirando.
    """
    for archivo in (CREAR_TABLAS, MIGRACION):
        sql = _texto(archivo)
        check = re.search(
            r"ck_corrida_final\s*\n?\s*CHECK \(final IN \(\s*([^)]+)\)", sql
        )
        assert check, f"No está ck_corrida_final en {archivo.name}"
        valores = tuple(v.strip().strip("'") for v in check.group(1).split(","))
        assert valores == FINALES_DE_LA_CORRIDA


def test_sin_precio_es_derivado_y_no_una_columna_mas():
    """Dos columnas que tienen que sumar lo mismo dejan de sumarlo.

    El día que alguien escriba una y no la otra. Mismo criterio que
    `ConteoDeLaLista.sin_comparar`.
    """
    corrida = _corrida(en_la_lista=380, con_precio=300)

    assert corrida.sin_precio == 80
    assert "sin_precio" not in columnas_de_la_corrida(corrida, NEGOCIO)


@pytest.mark.parametrize(
    "final, propiedad",
    [
        (TERMINO, "llego_al_final"),
        (SE_ACABO_EL_TIEMPO, "se_corto_por_tiempo"),
        (SE_INTERRUMPIO, "se_interrumpio"),
    ],
)
def test_cada_final_enciende_su_propiedad_y_solo_la_suya(final, propiedad):
    corrida = _corrida(final=final)
    encendidas = {
        p
        for p in ("llego_al_final", "se_corto_por_tiempo", "se_interrumpio")
        if getattr(corrida, p)
    }

    assert encendidas == {propiedad}


def test_hubo_fallas_es_lo_que_vuelve_insegura_la_atribucion():
    assert _corrida(no_se_pudo=0).hubo_fallas is False
    assert _corrida(no_se_pudo=1).hubo_fallas is True


def test_el_instante_lo_pone_la_base_y_no_el_proceso():
    """Por lo mismo que `consultado_en` del precio: dos relojes, dos verdades.

    `termino_en` no está entre las columnas que se escriben, así que la pone
    `now()` — la hora del servidor que guarda la fila.
    """
    assert "termino_en" not in columnas_de_la_corrida(_corrida(), NEGOCIO)


@pytest.mark.parametrize(
    "cambios, restriccion",
    [
        ({"final": "casi"}, "ck_corrida_final"),
        ({"en_la_lista": -1}, "ck_corrida_conteos"),
        ({"segundos": -1.0}, "ck_corrida_duracion"),
        ({"consultados": 400, "en_la_lista": 380}, "ck_corrida_consultados"),
        ({"con_precio": 400, "consultados": 380}, "ck_corrida_con_precio"),
        ({"pedido_sugerido_id": None}, "ck_corrida_lista"),
        ({"fecha_del_pedido": None}, "ck_corrida_lista"),
    ],
)
def test_el_doble_rechaza_lo_mismo_que_los_CHECK_y_nombra_cual(cambios, restriccion):
    """**Un doble permisivo deja el suite en verde y rompe en atlas.**

    Cada `raise` nombra la restricción que estaría violando, para que quien lea
    el error sepa que lo que falta es una migración y no un `if`.
    """
    with pytest.raises(ValueError) as fallo:
        revisar_la_corrida(columnas_de_la_corrida(_corrida(**cambios), NEGOCIO))

    assert restriccion in str(fallo.value)


def test_una_corrida_sin_lista_si_se_puede_guardar():
    """Es justo la que contesta "el lote corrió y no encontró ventas".

    Por eso la llave foránea de `corrida_del_lote` admite nulos y el `INSERT`
    es pelado, sin `select` que lo acote contra `pedido_sugerido`.
    """
    revisar_la_corrida(
        columnas_de_la_corrida(
            _corrida(
                final=SIN_LISTA,
                pedido_sugerido_id=None,
                fecha_del_pedido=None,
                en_la_lista=0,
                consultados=0,
                con_precio=0,
            ),
            NEGOCIO,
        )
    )


def test_el_doble_guarda_y_devuelve_la_ULTIMA_corrida_de_esa_lista(almacenamiento):
    """La tabla solo crece: quien elige la más reciente es la LECTURA."""
    almacenamiento.guardar_la_corrida(
        NEGOCIO, _corrida(final=SE_ACABO_EL_TIEMPO, consultados=100, con_precio=90)
    )
    almacenamiento.guardar_la_corrida(NEGOCIO, _corrida(final=TERMINO, consultados=380))

    ultima = almacenamiento.ultima_corrida(NEGOCIO, 7)

    assert len(almacenamiento.corridas) == 2
    assert ultima.final == TERMINO
    assert ultima.consultados == 380
    assert ultima.termino_en is not None


def test_una_lista_sin_corrida_devuelve_None_y_eso_es_un_dato(almacenamiento):
    """`None` no es un hueco que disimular: es "el lote no corrió sobre ésta"."""
    almacenamiento.guardar_la_corrida(NEGOCIO, _corrida(pedido_sugerido_id=7))

    assert almacenamiento.ultima_corrida(NEGOCIO, 99) is None
    assert almacenamiento.ultima_corrida("otra_farmacia", 7) is None


# =========================================================================
# CONSULTAR EN FILA — uno tras otro, en un solo hilo
# =========================================================================


def _registro() -> RegistroDeConsultas:
    """Sin hilos: la tarea se ejecuta ahí mismo. Igual que la fixture."""
    return RegistroDeConsultas(lanzar=lambda tarea: tarea())


def _reloj():
    """Un reloj que **solo avanza cuando alguien duerme**. Devuelve `(ahora, dormir)`.

    El mismo mecanismo que `test_precio.py` y `test_lote.py`, y por la misma
    razón: **ninguna prueba de este repo duerme de verdad**. Lo que avanza es
    exactamente lo que el código pidió esperar, no lo que un reloj de pared
    diga — así una espera de dos minutos simulados cuesta microsegundos.
    """
    transcurrido = [0.0]
    return (
        lambda: transcurrido[0],
        lambda segundos: transcurrido.__setitem__(0, transcurrido[0] + segundos),
    )


def _lista_con(almacenamiento, claves) -> dict[str, int]:
    """Una lista guardada con un renglón por clave. Devuelve `clave -> renglon_id`.

    Se siembra de verdad —y no se le pasan ids sueltos a `consultar_en_fila`—
    porque el precio congelado cuelga de un renglón que tiene que existir:
    contra un almacenamiento vacío, `guardar_precios` rebota y la prueba
    quedaría comprobando el hueco en vez del camino bueno.
    """
    from continental.almacenamiento import Ventana

    guardado = almacenamiento.abrir_el_dia(
        NEGOCIO,
        HOY,
        Ventana(desde=HOY, hasta=HOY),
        lambda: tuple(
            _renglon(n + 1, clave=clave).propuesto for n, clave in enumerate(claves)
        ),
    )
    return {r.propuesto.clave: r.renglon_id for r in guardado.renglones}


def _doyle_que_contesta(claves) -> DoyleFalso:
    doyle = DoyleFalso()
    for clave in claves:
        doyle.resultados_por_termino[clave] = {
            p: respuesta_lista(p, [(clave, "86.05", "40")])
            for p in ("nadro", "levic", "vicma", "quepharma")
        }
    return doyle


def test_se_consulta_uno_tras_otro_y_en_el_orden_que_llegan():
    """**Secuencial a propósito**, por la misma razón que el lote nocturno.

    Cada renglón son cuatro visitas a portales ajenos, y pedirle a Doyle varias
    búsquedas a la vez es justo lo que le impide reutilizar el navegador que
    tenga abierto (su ADR 0008). Un botón que lanzara doce hilos serían
    cuarenta y ocho navegadores.
    """
    claves = ["7501000000001", "7501000000002", "7501000000003"]
    doyle = _doyle_que_contesta(claves)
    almacenamiento = AlmacenamientoFalso()
    ids = _lista_con(almacenamiento, claves)
    ahora, dormir = _reloj()

    hecho = consultar_en_fila(
        [(ids[c], c) for c in claves],
        doyle=doyle,
        almacenamiento=almacenamiento,
        registro=_registro(),
        negocio=NEGOCIO,
        dormir=dormir,
        ahora=ahora,
    )

    assert hecho == Completado(pedidos=3)
    assert doyle.pedidos == claves
    # Y lo consultado quedó CONGELADO: cuatro filas por renglón, que es el
    # grano de `pedidos.precio_de_proveedor`.
    assert len(almacenamiento.precios) == 12


def test_el_tope_se_mira_ANTES_de_cada_renglon_y_nunca_en_medio():
    """Cortar una consulta a la mitad tiraría una búsqueda que ya costó ~9 s.

    Y lo que queda sin consultar **no deja fila y no se inventa ninguna** (ADR
    0006): se cuenta y se dice. El renglón se sigue viendo como lo que es, un
    renglón sin lectura, y su botón sigue ahí.
    """
    claves = ["7501000000001", "7501000000002", "7501000000003"]
    doyle = _doyle_que_contesta(claves)
    almacenamiento = AlmacenamientoFalso()
    ids = _lista_con(almacenamiento, claves)
    ahora, dormir = _reloj()
    vueltas = [0]

    def se_acabo() -> bool:
        vueltas[0] += 1
        return vueltas[0] > 2

    hecho = consultar_en_fila(
        [(ids[c], c) for c in claves],
        doyle=doyle,
        almacenamiento=almacenamiento,
        registro=_registro(),
        negocio=NEGOCIO,
        se_acabo=se_acabo,
        dormir=dormir,
        ahora=ahora,
    )

    assert hecho.pedidos == 2
    assert hecho.sin_tiempo == 1
    assert hecho.se_quedo_sin_tiempo is True
    # El tercero no dejó rastro de ninguna clase: ni fila, ni motivo inventado.
    assert doyle.pedidos == claves[:2]
    assert len(almacenamiento.precios) == 8


def test_un_renglon_que_ya_se_esta_consultando_no_se_pide_dos_veces():
    """El candado haciendo su trabajo, y eso NO es un fallo: se cuenta aparte.

    Serían cuatro visitas de más por un renglón que ya viene en camino — el
    segundo clic, o la otra pestaña del mostrador.
    """
    claves = ["7501000000001", "7501000000002"]
    doyle = _doyle_que_contesta(claves)
    almacenamiento = AlmacenamientoFalso()
    ids = _lista_con(almacenamiento, claves)
    ahora, dormir = _reloj()

    # Ese renglón ya está apartado y nadie lo terminó: es lo que deja una
    # consulta en vuelo de la otra pestaña.
    registro = RegistroDeConsultas(lanzar=lambda tarea: tarea())
    registro.apartar(ids[claves[0]], claves[0])

    hecho = consultar_en_fila(
        [(ids[c], c) for c in claves],
        doyle=doyle,
        almacenamiento=almacenamiento,
        registro=registro,
        negocio=NEGOCIO,
        dormir=dormir,
        ahora=ahora,
    )

    assert hecho.pedidos == 1
    assert hecho.ya_en_curso == 1
    assert doyle.pedidos == ["7501000000002"]


def test_apartar_no_lanza_nada_y_pedir_si():
    """Las dos mitades de `pedir`, separadas para el botón de completar.

    `apartar` decide y no lanza; `pedir` decide y lanza. El botón necesita la
    primera porque consulta muchos renglones **en un solo hilo**: con `pedir`
    serían tantos hilos como faltantes.
    """
    lanzadas = []
    registro = RegistroDeConsultas(lanzar=lambda tarea: lanzadas.append(tarea))

    consulta, nueva = registro.apartar(1, "7501000000001")
    assert nueva is True and consulta.en_curso and lanzadas == []

    # Y el segundo no aparta: ya hay una en curso.
    _, otra_vez = registro.apartar(1, "7501000000001")
    assert otra_vez is False

    registro.pedir(2, "7501000000002", lambda c: None)
    assert len(lanzadas) == 1


def test_el_tope_del_completado_sale_del_yaml_y_no_es_el_del_lote():
    """Dos números distintos a propósito.

    El lote corre de noche con el horario entero por delante; esto lo aprieta
    alguien que está esperando con la farmacia abierta. Compartirlos haría que
    subir uno subiera el otro sin que nadie lo decidiera.
    """
    from continental.lote import tope_del_lote_segundos

    assert tope_del_completado_segundos() == pytest.approx(20 * 60.0)
    assert tope_del_completado_segundos() != tope_del_lote_segundos()


# =========================================================================
# LA RUTA — que esto llegue hasta el JSON y hasta los portales
# =========================================================================


def test_el_motivo_del_hueco_llega_dentro_de_cada_renglon(cliente, almacen, doyle,
                                                          almacenamiento):
    """Sin corrida guardada, los cuatro dicen "el lote no corrió sobre esta lista"."""
    _poblar(almacen, doyle)

    renglones = _por_clave(cliente)

    assert renglones[SIN_LECTURA_CLAVE]["porque_no_hay_lectura"]["motivo"] == (
        EL_LOTE_NO_CORRIO
    )


def test_con_la_corrida_guardada_el_renglon_dice_que_el_tope_no_llego(
    cliente, almacen, doyle, almacenamiento
):
    """**La casilla 1 de punta a punta**, con la fila del ADR 0007 de por medio.

    La lista se carga una vez para saber su id, se guarda la corrida como la
    guardaría el lote de las 22:00, y se vuelve a cargar: el mismo renglón que
    antes decía "el lote no corrió" ahora dice "al lote se le acabó el tiempo"
    con sus dos números.
    """
    _poblar(almacen, doyle)
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_la_corrida(
        NEGOCIO,
        _corrida(
            pedido_sugerido_id=lista["pedido_sugerido_id"],
            final=SE_ACABO_EL_TIEMPO,
            en_la_lista=4,
            consultados=1,
            con_precio=1,
            sin_alcanzar=3,
        ),
    )

    despues = cliente.get(RUTA).json()
    porque = {r["clave"]: r.get("porque_no_hay_lectura") for r in despues["renglones"]}

    assert porque[SIN_LECTURA_CLAVE]["motivo"] == EL_LOTE_SE_CORTO_POR_TIEMPO
    assert porque[SIN_LECTURA_CLAVE]["seguro"] is True
    assert despues["corrida"]["se_corto_por_tiempo"] is True
    assert "1 de 4" in despues["corrida"]["frase"]


def test_una_corrida_sin_lista_no_se_lee_como_falla_en_la_ruta(
    cliente, almacen, doyle, almacenamiento
):
    """El pedido del dueño, de punta a punta: una corrida `SIN_LISTA` en la
    lista que la pantalla tiene abierta se pinta como 'bien', con la frase
    breve, y no arrastra el "no fue en orden" que `orden_cumplido=False`
    dejaría si nadie la distinguiera (`lote.py`, `como_corrida`).
    """
    _poblar(almacen, doyle)
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_la_corrida(
        NEGOCIO,
        _corrida(
            pedido_sugerido_id=lista["pedido_sugerido_id"],
            final=SIN_LISTA,
            en_la_lista=0,
            consultados=0,
            con_precio=0,
            orden_cumplido=False,
        ),
    )

    despues = cliente.get(RUTA).json()

    assert despues["corrida"]["final"] == SIN_LISTA
    assert despues["corrida"]["se_corto_por_tiempo"] is False
    assert despues["corrida"]["se_interrumpio"] is False
    assert "no armó lista" in despues["corrida"]["frase"]
    assert "no fue en orden" not in despues["corrida"]["frase"]


def test_una_corrida_interrumpida_SI_se_lee_como_falla_en_la_ruta(
    cliente, almacen, doyle, almacenamiento
):
    """El contraste que prueba que lo de arriba no tapa una falla de verdad:
    una corrida que sí se cortó sigue marcada `se_interrumpio` y mandando al
    journal, exactamente igual que antes de esta rama.
    """
    _poblar(almacen, doyle)
    lista = cliente.get(RUTA).json()
    almacenamiento.guardar_la_corrida(
        NEGOCIO,
        _corrida(
            pedido_sugerido_id=lista["pedido_sugerido_id"],
            final=SE_INTERRUMPIO,
            en_la_lista=4,
            consultados=1,
            con_precio=0,
        ),
    )

    despues = cliente.get(RUTA).json()

    assert despues["corrida"]["se_interrumpio"] is True
    assert "SE CORTÓ" in despues["corrida"]["frase"]
    assert "journal" in despues["corrida"]["frase"]


def test_un_renglon_con_lecturas_no_trae_el_motivo_del_hueco(cliente, almacen, doyle):
    """Es la pregunta que contesta: por qué NO HAY lectura.

    Ponerlo en un renglón con cuatro precios sería una llave que la pantalla
    tendría que aprender a ignorar.
    """
    _poblar(almacen, doyle)
    renglon = _por_clave(cliente)[UN_PRECIO_CLAVE]
    cliente.post(f"/api/renglon/{renglon['renglon_id']}/precio")

    despues = _por_clave(cliente)[UN_PRECIO_CLAVE]

    assert "porque_no_hay_lectura" not in despues
    # Y sus huecos reintentables sí viajan: es lo que explica por qué el botón
    # de completar NO va a atenderlos.
    assert {h["proveedor"] for h in despues["huecos_reintentables"]} == {
        "levic",
        "vicma",
        "quepharma",
    }


def test_la_lista_dice_cuantos_faltan_y_cuales(cliente, almacen, doyle):
    """**Qué cuenta como faltante, medido contra los cuatro casos sembrados.**

    De los cuatro renglones: entra el que no tiene lectura y el que se consultó
    con huecos reintentables. **No entran** el que ya tiene un precio ni el que
    se consultó y sus cuatro huecos son definitivos.
    """
    _poblar(almacen, doyle)
    renglones = _por_clave(cliente)
    for clave in (SIN_PRECIOS_CLAVE, UN_PRECIO_CLAVE, DEFINITIVO_CLAVE):
        cliente.post(f"/api/renglon/{renglones[clave]['renglon_id']}/precio")

    datos = cliente.get(RUTA).json()
    faltan = {r["clave"] for r in datos["faltantes"]["renglones"]}

    assert datos["faltantes"]["cuantos"] == 2
    assert faltan == {SIN_LECTURA_CLAVE, SIN_PRECIOS_CLAVE}
    assert datos["faltantes"]["sin_consultar"] == 1
    assert datos["faltantes"]["reintentables"] == 1


def test_el_boton_consulta_SOLO_los_faltantes(cliente, almacen, doyle):
    """La casilla 2, contra lo que de verdad se le pidió a Doyle.

    Después del botón, Doyle recibió exactamente las dos claves que faltaban y
    **ni una vez más** la del renglón que ya tenía precio. Cada visita de más
    son ~36 s de navegador contra los portales del dueño.
    """
    _poblar(almacen, doyle)
    datos = cliente.get(RUTA).json()
    renglones = {r["clave"]: r for r in datos["renglones"]}
    for clave in (SIN_PRECIOS_CLAVE, UN_PRECIO_CLAVE, DEFINITIVO_CLAVE):
        cliente.post(f"/api/renglon/{renglones[clave]['renglon_id']}/precio")

    antes = list(doyle.pedidos)
    respuesta = cliente.post(
        f"{RUTA}/{datos['pedido_sugerido_id']}/completar"
    ).json()

    assert respuesta["ok"] is True
    assert respuesta["lanzados"] == 2
    assert doyle.pedidos[len(antes):] == [SIN_LECTURA_CLAVE, SIN_PRECIOS_CLAVE]


def test_el_boton_no_lanza_nada_cuando_no_falta_ninguno(cliente, almacen, doyle):
    """Y lo dice, en vez de contestar "listo" sobre una lista que no se tocó."""
    almacen.catalogo_en_memoria = [_producto(1, UN_PRECIO_CLAVE)]
    almacen.ventas_en_memoria = [_venta(1)]
    doyle.resultados_por_termino[UN_PRECIO_CLAVE] = {
        p: respuesta_lista(p, [(UN_PRECIO_CLAVE, "86.05", "40")])
        for p in ("nadro", "levic", "vicma", "quepharma")
    }
    datos = cliente.get(RUTA).json()
    cliente.post(f"/api/renglon/{datos['renglones'][0]['renglon_id']}/precio")

    respuesta = cliente.post(f"{RUTA}/{datos['pedido_sugerido_id']}/completar").json()

    assert respuesta["ok"] is True
    assert respuesta["lanzados"] == 0
    assert "No falta ningún precio" in respuesta["detalle"]


def test_el_boton_no_corre_sobre_una_lista_cerrada(cliente, almacen, doyle):
    """Molestar a cuatro portales por un dato que ya no decide nada.

    El 409 sale del estado de la lista y no de un `if` de la pantalla: dos
    pestañas abiertas bastan para que una de ellas siga creyendo que está
    abierta.
    """
    _poblar(almacen, doyle)
    datos = cliente.get(RUTA).json()
    cliente.post(f"{RUTA}/{datos['pedido_sugerido_id']}/cerrar")

    respuesta = cliente.post(f"{RUTA}/{datos['pedido_sugerido_id']}/completar")

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False


def test_el_almacenamiento_caido_no_es_un_500_ni_consulta_a_ciegas(
    cliente, almacen, doyle, almacenamiento
):
    """Sin poder leer lo congelado NO SE SABE qué falta, y eso no se atiende
    preguntándole a los cuatro portales por la lista entera (regla 4): se dice.
    """
    _poblar(almacen, doyle)
    datos = cliente.get(RUTA).json()
    antes = list(doyle.pedidos)
    almacenamiento.falla = RuntimeError("se cayó Postgres")

    respuesta = cliente.post(f"{RUTA}/{datos['pedido_sugerido_id']}/completar")

    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is False
    assert doyle.pedidos == antes


def test_descartar_un_renglon_lo_saca_de_la_cola_del_boton(cliente, almacen, doyle):
    """Un descartado ya se atendió: alguien lo miró y decidió no pedirlo.

    Gastar cuatro visitas a portales en mercancía que nadie va a comprar es
    exactamente lo que no se quiere, y el número recalculado vuelve en la misma
    respuesta del clic — sin una consulta más.
    """
    _poblar(almacen, doyle)
    datos = cliente.get(RUTA).json()
    renglones = {r["clave"]: r for r in datos["renglones"]}
    # Los cuatro faltan de entrada: ninguno tiene lectura todavía.
    assert datos["faltantes"]["cuantos"] == 4

    respuesta = cliente.post(
        f"/api/renglon/{renglones[SIN_LECTURA_CLAVE]['renglon_id']}/descartar"
    ).json()

    assert respuesta["faltantes"]["cuantos"] == 3
    assert SIN_LECTURA_CLAVE not in {
        r["clave"] for r in respuesta["faltantes"]["renglones"]
    }


def test_la_lista_dice_a_quien_le_caduco_la_sesion(cliente, almacen, doyle):
    """Con su nombre escrito como el glosario lo escribe, no con la clave."""
    _poblar(almacen, doyle)
    renglones = _por_clave(cliente)
    cliente.post(f"/api/renglon/{renglones[SIN_PRECIOS_CLAVE]['renglon_id']}/precio")

    datos = cliente.get(RUTA).json()

    assert [s["proveedor"] for s in datos["sesiones_caducadas"]] == ["nadro", "vicma"]
    assert datos["sesiones_caducadas"][0]["nombre"] == "NADRO"


def test_el_boton_de_abrir_sesion_se_lo_pide_a_doyle_y_dice_lo_que_falta(
    cliente, doyle
):
    """**Continental no abre un navegador**: se lo pide a Doyle (regla 1).

    Y lo que contesta no es "listo": es una ventana esperando a que alguien
    teclee. Un botón que contesta "listo" sobre una sesión que sigue caducada
    es la falla silenciosa que la regla 4 prohíbe.
    """
    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is True
    assert respuesta["ya_abierta"] is False
    assert doyle.sesiones_abriendose == ["nadro"]
    assert "Hasta entonces la sesión sigue caducada" in respuesta["siguiente"]


def test_el_segundo_clic_no_abre_una_segunda_ventana(cliente, doyle):
    """Dos Chromes peleándose por el mismo login. No es un error y se dice."""
    cliente.post("/api/sesion/nadro/abrir")
    respuesta = cliente.post("/api/sesion/nadro/abrir").json()

    assert respuesta["ok"] is True
    assert respuesta["ya_abierta"] is True
    assert doyle.sesiones_abriendose == ["nadro"]


def test_confirmar_guarda_la_sesion_y_el_aviso_honesto_de_doyle_viaja(cliente, doyle):
    """`todavia_parece_login` es la diferencia entre "ya está" y "otra vez".

    Esconderlo dejaría al encargado creyendo que abrió una sesión que no abrió,
    que es la trampa del hilo abierto 1: los cuatro decían `guardada` sin
    servir ninguno.
    """
    doyle.sesiones_que_siguen_en_login.append("levic")
    cliente.post("/api/sesion/levic/abrir")

    respuesta = cliente.post("/api/sesion/levic/confirmar").json()

    assert respuesta["ok"] is True
    assert respuesta["todavia_parece_login"] is True
    assert doyle.sesiones_confirmadas == ["levic"]
    assert "ábrela otra vez" in respuesta["detalle"]


def test_doyle_apagado_sale_como_hueco_con_su_motivo_y_no_como_500(cliente, doyle):
    """Regla 4 y regla 5 juntas: hueco con su motivo, y el motivo es el TIPO."""
    doyle.falla = RuntimeError("connection refused a 127.0.0.1:8383")

    respuesta = cliente.post("/api/sesion/nadro/abrir")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert "127.0.0.1" not in cuerpo["detalle"]


# =========================================================================
# EL SQL — la quinta tabla existe también fuera de Python
# =========================================================================


def test_la_quinta_tabla_esta_en_el_DDL_y_en_su_migracion():
    """El precio completo de una tabla en este repo (ADR 0003).

    `crear_tablas.sql` para una base desde cero, y `migraciones/0004-*` para la
    base que ya existe: sobre ella el `IF NOT EXISTS` del primero calla y la
    tabla nueva no aparecería.
    """
    for archivo in (CREAR_TABLAS, MIGRACION):
        assert "CREATE TABLE IF NOT EXISTS pedidos.corrida_del_lote" in _texto(archivo)


def test_la_migracion_no_trae_retorno_de_carro_y_es_utf8():
    """Lo mismo que vigila `test_compila.py` para todo `.sql`, escrito aquí
    porque el acento de `ck_corrida_final` depende de ello."""
    datos = MIGRACION.read_bytes()

    assert b"\r" not in datos
    datos.decode("utf-8")


def test_la_migracion_recuerda_volver_a_correr_crear_rol():
    """**El olvido más caro de este esquema**, y el único que no avisa.

    Un GRANT no se puede dar sobre una tabla que no existía. Sin ese paso el
    lote rebota a las 22:00 con "permission denied", la corrida NO se aborta
    —los precios se guardan igual— y lo único que pasa es que a la mañana la
    pantalla dice "el lote no corrió" sobre una noche en la que sí corrió.
    """
    sql = _texto(MIGRACION)

    assert "sql/crear_rol.sql" in sql
    assert "permission denied for table corrida_del_lote" in sql


def test_el_rol_tiene_GRANT_sobre_la_quinta_tabla():
    otorgadas = set(
        re.findall(r"GRANT [A-Z, ]+ ON (pedidos\.\w+)", _texto(CREAR_ROL))
    )

    assert "pedidos.corrida_del_lote" in otorgadas


def test_la_corrida_dice_a_que_negocio_pertenece_y_sin_DEFAULT():
    """Regla 7, igual que las otras cuatro tablas."""
    sql = _texto(CREAR_TABLAS)
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.corrida_del_lote (")
    cuerpo = sql[inicio : sql.index("\n);", inicio)]

    assert re.search(r"negocio\s+text\s+NOT NULL", cuerpo)
    assert "negocio" in cuerpo.split("DEFAULT")[0]


def test_la_corrida_no_guarda_numeros_en_coma_flotante():
    """Las duraciones son `numeric`, como todo número de este esquema.

    La comprobación 13 de `verificar_rol.sql` lo mira sobre el esquema entero;
    esto lo mira en el archivo, que es donde se rompe al editarlo.
    """
    sql = _texto(CREAR_TABLAS)
    inicio = sql.index("CREATE TABLE IF NOT EXISTS pedidos.corrida_del_lote (")
    cuerpo = sql[inicio : sql.index("\n);", inicio)]

    for prohibido in ("double precision", "real", "float", "money"):
        assert prohibido not in cuerpo


def test_el_indice_de_la_ultima_corrida_es_el_orden_de_la_consulta():
    """Un índice que no coincida con su consulta es trabajo por fila a cambio
    de nada. Aquí son la misma tupla, columna por columna."""
    for archivo in (CREAR_TABLAS, MIGRACION):
        sql = _texto(archivo)
        assert "ix_corrida_ultima" in sql
        assert "(negocio, pedido_sugerido_id, termino_en DESC)" in sql


def test_el_verificador_mira_la_forma_de_la_corrida():
    """Dos comprobaciones nuevas: los acentos y los conteos imposibles.

    `CREATE TABLE IF NOT EXISTS` calla si la tabla ya existe con otra forma, así
    que comprobar solo los permisos dejaría pasar un DDL editado a medias.
    """
    verificador = _texto(VERIFICAR_ROL)

    assert "ck_corrida_final" in verificador
    assert "ck_corrida_consultados" in verificador
    assert "ck_corrida_lista" in verificador
    for final in FINALES_DE_LA_CORRIDA:
        assert f"%{final}%" in verificador


def test_el_verificador_ya_no_espera_TRES_llaves_de_identidad():
    """**Un arreglo, no una casilla**: esperaba `3` cuando ya eran cuatro.

    Habría salido [MAL] sobre una base correcta la primera vez que alguien lo
    corriera —y nadie lo ha corrido nunca—. Un verificador que da un falso
    [MAL] es tan malo como uno que da un falso [BIEN]: los dos enseñan a no
    creerle. Ahora se compara contra el número de tablas del esquema, así que
    la sexta entra sola.
    """
    verificador = _texto(VERIFICAR_ROL)

    assert "'3'," not in verificador
    assert "count(DISTINCT c.oid)" in verificador


# =========================================================================
# LA PANTALLA — que lo escriba en vez de inventárselo
# =========================================================================


def test_la_pantalla_pinta_el_motivo_del_hueco_y_no_lo_compone():
    """La frase viene hecha del servidor; aquí solo se elige el color.

    Es el error que el ticket 15 arregló con la certeza del ganador: una
    afirmación compuesta a partir de banderas, en el único archivo que ninguna
    prueba de Python mira.
    """
    portada = _pantalla()

    assert "porque_no_hay_lectura" in portada
    assert "porque.explicacion" in portada
    # El "probablemente" del caso inseguro, que es lo único que la pantalla
    # agrega, y lo agrega para decir de menos y nunca de más.
    assert "probablemente" in portada
    assert "porque.seguro" in portada


def test_la_pantalla_escribe_la_frase_de_la_corrida_que_llega():
    portada = _pantalla()

    assert "corrida.frase" in portada
    # Los tres colores de la corrida en sí, que son tres acciones distintas:
    # nada, apretar el botón, mirar el journal.
    assert "corrida.se_corto_por_tiempo ? 'tope'" in portada
    # Y cuando no hay corrida, el NIVEL —ámbar o rojo— decide la clase, y la
    # frase viene hecha igual que la de arriba: nada se compone aquí.
    assert "corridaAusente.frase" in portada
    assert "corridaAusente.nivel" in portada


def test_la_pantalla_ya_no_compone_la_frase_de_que_el_lote_no_corrio():
    """La lección de los tickets 15 y 21, otra vez: eso lo compone Python.

    Hasta la enmienda del dueño (2026-09-21), "El lote no corrió sobre esta
    lista" y sus causas —atlas apagado a las 22:00, el timer sin habilitar,
    la unidad en «failed»— se escribían aquí, sin distinguir esa falla de
    "todavía no le toca". Ahora vienen hechas en `corridaAusente.frase`
    (`faltantes.corrida_ausente_como_json`) y este archivo solo las pinta.
    """
    portada = _pantalla()

    assert "Nadie le ha pedido el precio a estos renglones de noche" not in portada
    assert "el timer sin habilitar, la unidad en" not in portada


def test_la_pantalla_saca_el_numero_del_boton_del_servidor():
    """Un conteo que el navegador lleve a mano se separa de la verdad."""
    portada = _pantalla()

    assert "faltantes.cuantos" in portada
    assert "/completar" in portada
    # Y el singular: "Completar los 1 que faltan" se lee como una pantalla
    # rota, y con este botón pasa seguido —se aprieta, quedan dos, se aprieta
    # otra vez y queda uno—.
    assert "Completar el que falta" in portada


def test_la_pantalla_ofrece_los_dos_pasos_de_la_sesion():
    """Abrir y confirmar, porque en medio hay un humano tecleando.

    Y dice dónde. **La frase cambió el 2026-09-22 y el cambio es el arreglo**:
    decía *"en la máquina donde Doyle corre"*, escrita cuando Doyle vivía en la
    torre, y desde la mudanza del 21 esa máquina es un servidor sin monitor.
    Ahora manda al visor, que es donde de verdad se puede teclear. El resto de
    esa falla vive en `test_visor.py`.
    """
    portada = _pantalla()

    assert "/abrir" in portada and "/confirmar" in portada
    assert "Abrir sesión" in portada and "Ya entré" in portada
    assert "EN LA VENTANA DEL VISOR" in portada


def test_la_pantalla_no_abre_un_navegador_ni_le_habla_a_doyle():
    """Reglas 1 y 2 sobre el archivo que no compila nadie.

    El navegador lo abre Doyle; quien se lo pide es Continental por HTTP. Esta
    pantalla solo habla con Continental —nunca con el 8383— y eso se puede
    comprobar barato: no hay una sola URL de módulo aquí dentro.
    """
    portada = _pantalla()

    assert "8383" not in portada
    assert "8484" not in portada
    assert "playwright" not in portada.lower()
