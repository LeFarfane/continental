"""El backend de Continental.

Dice si está vivo, quién está entrando, si los módulos contestan, arma el
pedido sugerido del día **y lo guarda**, y congela el precio que Doyle trae de
los cuatro proveedores **solo cuando empareja por EAN**: lo que no empareja
queda como hueco con su motivo, nunca como cero. Lo que falta de precios
—comparar los cuatro y decir cuál gana, contar los huecos, el lote de la
noche— son los tickets 14 en adelante.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from continental import __version__
from continental.almacen import LecturaDelAlmacen
from continental.almacenamiento import (
    ABIERTO,
    CANTIDAD_FINAL_MINIMA,
    CERRADO,
    RENGLON_ABIERTO,
    AlmacenamientoDelPedido,
    CorridaDelLote,
    PedidoGuardado,
    PedidoSugeridoGuardado,
    RenglonGuardado,
    LLAVE_DEL_ATRASO,
    Ventana,
    dias_en_transito_para_atrasado_configurados,
    dias_primera_vez_configurados,
    ventana_de_reposicion,
)
from continental.cierre import (
    al_cerrar,
    al_cerrar_sin_resumen,
    frase_de_la_reapertura,
    reapertura as boton_de_reabrir,
)
from continental.clasificacion import reglas_configuradas
from continental.comparacion import (
    comparacion_como_json,
    comparar,
    contar_la_lista,
    conteo_como_json,
)
from continental.config import cargar
from continental.consultas import (
    RegistroDeConsultas,
    ajustes_de_la_consulta,
    consultar_en_fila,
    consultar_y_congelar,
    lecturas_como_json,
    tope_del_completado_segundos,
)
from continental.doyle import ClienteDeDoyle
from continental.exportar import (
    TIPO_DEL_ARCHIVO,
    csv_del_pedido,
    disposicion_de_descarga,
    nombre_del_archivo,
)
from continental.fallas import (
    AL_GUARDAR,
    AL_LEER,
    CONFIGURACION,
    DOYLE,
    LOTE,
    PETICION,
    SERVIDOR,
    estado_de_las_ventas,
    frase_de_doyle_caido,
    frase_de_la_lista_vacia,
    frase_de_pedidos_sin_leer,
    frase_de_precios_sin_leer,
    frase_del_hueco,
    que_hacer,
)
from continental.faltantes import (
    NIVEL_FALLA,
    NUNCA_SE_CONSULTO,
    corrida_ausente_como_json,
    elegir_los_faltantes,
    faltantes_como_json,
    frase_de_la_corrida,
    hueco_como_json,
    huecos_que_se_pueden_reintentar,
    por_que_no_hay_lectura,
    proveedores_con_sesion_caducada,
)
from continental.particion import (
    Captura,
    captura_como_json,
    eleccion_como_json,
    elegir,
    frase_del_envio,
    frase_sin_nada_por_repartir,
    lo_que_hay_que_capturar,
    particion_como_json,
    partir,
)
from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor
from continental.proveedores import puente_como_json, puente_configurado
from continental.recepcion import (
    PedidoALaVista,
    Recepcion,
    desde_cuando_leer_compras,
    frase_de_lo_recibido,
    frase_de_lo_recibido_a_mano,
    frase_del_confirmado,
    frase_del_rechazado,
    piezas_escritas,
    proponer,
    recepcion_como_json,
    recepcion_con_hueco,
)
from continental.sugerido import armar_la_lista
from continental.transiciones import (
    motivo_para_no_cancelar,
    motivo_para_no_corregir,
    motivo_para_no_editar,
    motivo_para_no_enviar,
    motivo_para_no_reabrir,
    motivo_para_no_recibir_a_mano,
)
from continental.transito import (
    ETIQUETA_PARA_CORREGIR,
    MemoriaDeLoPedido,
    dias_en_transito,
    en_camino,
    en_camino_como_json,
    en_camino_con_hueco,
    enviado_antes_de,
    esta_atrasado,
    frase_de_la_ventana_propia,
    frase_de_lo_que_falto,
    frase_de_lo_que_ya_no_falta,
    frase_de_ya_en_camino,
    frase_del_atraso,
    PROBABLEMENTE_LLEGO,
    frase_del_pedido_cancelado,
    frase_del_renglon_cancelado,
    frase_del_renglon_devuelto,
    frase_del_transito,
    frase_para_cancelar,
    memoria_de_lo_pedido,
    vendido_desde_que_se_pidio,
)
from continental.vistas import VISTAS
from continental.web.dependencias import (
    obtener_almacen,
    obtener_almacenamiento,
    obtener_consultas,
    obtener_doyle,
    reloj,
)

ESTATICOS = Path(__file__).parent / "static"

log = logging.getLogger("continental")

app = FastAPI(title="Continental", version=__version__, docs_url="/docs")


def _ahora() -> dt.datetime:
    """El instante de ahora, con zona. **Solo para decir hace cuánto pasó algo.**

    Lo usa el ticket 24 para escribir "pedido el martes": compara el instante
    en que alguien apretó "Enviar" contra éste, y los dos son del reloj. Ninguna
    **fecha de venta** sale de aquí —ésas salen de `max(fecha)` del almacén—, y
    por eso el reloj de verdad vive en `dependencias.reloj`, con los otros
    bordes: este archivo tiene prohibido mirarlo. Es una función aparte para
    que una prueba la fije.
    """
    return reloj()


def _umbral_del_atraso() -> tuple[int | None, str | None]:
    """El N del ticket 25, o por qué no se pudo leer: `(umbral, detalle)`.

    `dias_en_transito_para_atrasado_configurados` truena si el YAML no lo trae
    bien (regla 4), y aquí se convierte en un hueco con su motivo: la lista y lo
    que viene en camino se enseñan igual; lo único que no se puede es decir qué
    está atrasado. El detalle nombra la llave y el tipo de la excepción, nunca
    su texto (regla 5), aunque aquí no lleve nada secreto: la costumbre es la
    garantía.
    """
    try:
        return dias_en_transito_para_atrasado_configurados(), None
    except Exception as exc:  # noqa: BLE001 — sin el número, la señal es un hueco
        log.exception("No se pudo leer pedido.%s", LLAVE_DEL_ATRASO)
        return None, (
            f"falta o está mal escrito pedido.{LLAVE_DEL_ATRASO} en "
            f"config/continental.yml ({type(exc).__name__})"
        )


def quien(request: Request) -> str:
    """Quién está entrando, según el encabezado que Cloudflare Access ya validó.

    Es una FIRMA, no un permiso (regla 3 de CLAUDE.md). Si alguien alcanza este
    puerto sin pasar por el túnel, puede escribir el encabezado que quiera: la
    autorización la hace Access, no esto. Sirve para saber quién armó un pedido,
    no para decidir si puede armarlo.
    """
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "sin-identificar"


def _que_hacer(caso: str) -> str:
    """Qué puede hacer la persona ante esa falla (ticket 29, `fallas.que_hacer`).

    A quién avisarle sale del YAML (`a_quien_avisar`) y no de un nombre escrito
    aquí: `cargar()` está cacheado, así que no relee el archivo por petición.
    """
    return que_hacer(caso, cargar().a_quien_avisar)


#: Lo que dice el 500 genérico. Es una frase fija a propósito: el detalle de
#: una excepción que nadie atrapó es justo lo que no puede salir de aquí.
ALGO_FALLO = "Algo falló del lado del servidor."


@app.exception_handler(Exception)
async def error_generico(request: Request, exc: Exception):
    """El detalle va a la consola del servidor; al navegador, un mensaje corto.

    Esto corre detrás de un túnel: un `str(exc)` de SQLAlchemy lleva la cadena
    de conexión con contraseña. Doyle puede darse el lujo de devolver el texto
    del error porque solo escucha en 127.0.0.1; aquí no.

    **Lleva `ok: false` desde el ticket 29**, con la misma forma que cualquier
    otra falla —`detalle`, `frase` y `que_hacer`—. Hasta entonces era
    `{"error": …}` a secas, y la pantalla, que pregunta por `ok`, lo leía como
    una lista sin ventas: "el almacén no tiene ni una venta registrada" sobre un
    servidor que había tronado. `error` se conserva por quien ya lo lea.
    """
    log.exception("Error atendiendo %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": ALGO_FALLO + " Revisa la bitácora.",
            "detalle": ALGO_FALLO,
            "frase": (
                ALGO_FALLO + " Esta respuesta no trae datos: lo que no se vea en "
                "la pantalla no quiere decir que no exista, quiere decir que no "
                "se pudo leer."
            ),
            "que_hacer": _que_hacer(SERVIDOR),
        },
    )


@app.exception_handler(RequestValidationError)
async def peticion_con_otra_forma(request: Request, exc: RequestValidationError):
    """Un cuerpo que no tiene la forma que la ruta espera: el 422 de validación.

    El de FastAPI contesta en inglés, sin `ok` ni `detalle`, y **devuelve lo
    que se le mandó**. Lo mandado no es un secreto del servidor, pero la forma
    es la de las demás fallas desde el ticket 29: `ok: false`, un motivo corto
    y qué hacer. Lo que pydantic dijo, entero, a la bitácora. En la práctica
    esto pasa con una pantalla vieja contra un servidor nuevo.
    """
    log.warning(
        "Petición con otra forma en %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "detalle": "la petición no tiene la forma que el servidor espera",
            "que_hacer": _que_hacer(PETICION),
        },
    )


@app.get("/api/salud")
async def salud(request: Request):
    """Vivo o no, y contra qué negocio está trabajando. No toca la base."""
    ajustes = cargar()
    return {
        "ok": True,
        "version": __version__,
        "negocio": ajustes.negocio,
        "quien": quien(request),
        "modulos": sorted(ajustes.modulos),
        # A quién avisarle (ticket 29). Viaja aquí porque la pantalla lo
        # necesita justo cuando NO hay respuesta del servidor: lo aprende al
        # cargar y lo usa en sus propias frases de "no llegó respuesta".
        "a_quien_avisar": ajustes.a_quien_avisar,
    }


@app.get("/api/modulos")
async def modulos():
    """Le pregunta a cada módulo si está vivo.

    Un módulo caído es un hueco con su motivo, nunca una pantalla colgada: por
    eso cada llamada lleva su timeout y el error se traduce a texto legible.
    """
    ajustes = cargar()
    resultado = []

    for modulo in ajustes.modulos.values():
        entrada = {"nombre": modulo.nombre, "url": modulo.url}
        try:
            async with httpx.AsyncClient(timeout=modulo.timeout_seg) as cliente:
                respuesta = await cliente.get(f"{modulo.url}/api/salud")
            entrada["ok"] = respuesta.status_code == 200
            if not entrada["ok"]:
                entrada["detalle"] = f"contestó {respuesta.status_code}"
        except httpx.TimeoutException:
            entrada["ok"] = False
            entrada["detalle"] = f"no contestó en {modulo.timeout_seg:g} s"
        except httpx.HTTPError as exc:
            entrada["ok"] = False
            entrada["detalle"] = f"no se pudo alcanzar ({type(exc).__name__})"
        resultado.append(entrada)

    return {"modulos": resultado}


@app.get("/api/bordes")
def bordes(
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
):
    """Le pregunta a los dos bordes del proceso si contestan de verdad.

    No es `/api/salud` con otro nombre: salud dice que el proceso vive sin
    tocar nada, y esto hace una lectura real. Sirve para saber, antes de armar
    un pedido, si el rol `continental` sigue pudiendo leer de `marts` —cada
    `dbt build` recrea las tablas y borra sus permisos, y a farmacia-data le
    pasó el 2026-09-07 a las 20:30— y si Doyle tiene sesiones vivas.

    Cada borde se atiende por separado: uno caído es un hueco con su motivo y
    no contagia al otro (regla 4). El motivo es el TIPO de la falla, nunca su
    texto: un `str(exc)` de SQLAlchemy lleva la cadena de conexión con
    contraseña y esto corre detrás de un túnel (regla 5).

    Es `def` y no `async def` a propósito: los dos bordes son síncronos
    —psycopg2 no es asíncrono— y así FastAPI los corre en su pool de hilos sin
    bloquear el bucle de eventos.
    """
    resultado = []

    entrada = {"nombre": "almacen"}
    try:
        entrada["productos"] = len(almacen.catalogo())
        ultima = almacen.ultima_fecha_con_ventas()
        entrada["ultima_venta"] = ultima.isoformat() if ultima else None
        entrada["ok"] = True
    except Exception as exc:  # noqa: BLE001 — cualquier falla del almacén es un hueco, no un 500
        log.exception("El almacén no contestó")
        entrada["ok"] = False
        entrada["detalle"] = f"el almacén no contestó ({type(exc).__name__})"
    resultado.append(entrada)

    entrada = {"nombre": "doyle"}
    try:
        sesiones = doyle.sesiones()
        entrada["sesiones"] = len(sesiones)
        entrada["sin_sesion"] = sorted(
            s.proveedor for s in sesiones if s.estado != "guardada"
        )
        entrada["ok"] = True
    except Exception as exc:  # noqa: BLE001 — Doyle caído no puede tumbar la pantalla
        log.exception("Doyle no contestó")
        entrada["ok"] = False
        entrada["detalle"] = f"Doyle no contestó ({type(exc).__name__})"
    resultado.append(entrada)

    return {"bordes": resultado}


@app.get("/api/doyle")
def doyle_contesta(doyle: ClienteDeDoyle = Depends(obtener_doyle)):
    """¿Doyle contesta? La pregunta de la casilla 1 del ticket 29, aparte de la lista.

    **La lista no depende de Doyle** —los precios que ya estaban guardados se
    leen de `pedidos`— y por eso esto es una ruta aparte y no una lectura más
    dentro de `GET /api/pedido-sugerido`: un Doyle colgado haría esperar a la
    lista entera sus diez segundos de timeout, y lo que la casilla pide es
    justo lo contrario, que la lista **igual se vea**. La pantalla pide las dos
    a la vez y pinta cada una cuando llega.

    `ok` es verdadero también cuando Doyle no contesta: la pregunta se atendió y
    la respuesta es "no". Lo que falló se dice en `contesta`, con su motivo
    —el TIPO, nunca el texto (regla 5)— y qué hacer.

    Pregunta por las sesiones porque es la llamada corta que el cliente ya
    tiene (`/api/bordes` hace lo mismo): ningún portal se visita. Es `def` por
    lo mismo que `bordes`: el cliente de Doyle es síncrono.
    """
    try:
        doyle.sesiones()
    except Exception as exc:  # noqa: BLE001 — Doyle caído es un hueco, no un 500
        log.exception("Doyle no contestó")
        detalle = f"Doyle no responde ({type(exc).__name__})"
        return {
            "ok": True,
            "contesta": False,
            "detalle": detalle,
            "frase": frase_de_doyle_caido(detalle),
            "que_hacer": _que_hacer(DOYLE),
        }
    return {"ok": True, "contesta": True, "frase": None, "que_hacer": None}


@app.get("/api/pedido-sugerido")
def pedido_sugerido(
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Abrir el día: la lista se crea si no existe y se lee si existe.

    **Lo que se muestra es lo guardado.** Hasta el ticket 07 esta ruta
    recalculaba la lista en cada carga y el resultado moría con la respuesta;
    desde aquí un renglón ya propuesto no cambia porque el catálogo se haya
    movido debajo —llegó mercancía, alguien corrigió un anaquel—. Es lo que el
    ticket 04 dejó dicho en `sugerido.Renglon`: los números viajan congelados, y
    congelados quiere decir guardados.

    **Es un `GET` que puede escribir, y es a propósito.** "Al abrir el día se
    crea el pedido sugerido si no existe" es literal: el día se abre cuando
    alguien carga la pantalla, no hay lote de la noche que lo haga todavía
    (ticket 18) y pedirle al encargado un clic de "crear la lista" sería un
    paso que no decide nada. La escritura es **idempotente**: la garantiza
    `ux_pedido_sugerido_dia` en la base, no este código, así que recargar tres
    veces —o dos pestañas a la vez— deja una sola lista.

    **La ventana se ancla en `max(fecha)` del almacén y nunca en el reloj.** El
    Postgres del contenedor corre en UTC y su `current_date` puede ir dos días
    adelante del último dato; a farmacia-data le costó 11.7 puntos de
    crecimiento inventados. Esa misma fecha es el día de la lista, el extremo
    de su ventana y el ancla contra la que vencen las anteriores.

    **La ventana de reposición acumula desde el corte del último cerrado.** No
    es el último día con datos: con el hueco de fin de semana eso tiraría al
    piso lo del sábado y lo del viernes por la tarde, que llegan juntos hasta el
    lunes en la noche —peor caso medido, 2.5 días— (ADR 0002). El día del corte
    **no** vuelve a entrar y el porqué está en `ventana_de_reposicion`, que es
    quien decide; aquí solo se le pasan los dos datos, los dos anclados en el
    dato y no en el reloj.

    Preguntar por el corte cuesta una consulta más por carga, también cuando la
    lista del día ya existe: `abrir_el_dia` recibe la ventana ya hecha porque es
    lo que va en el `INSERT`. Es un `max()` sobre un puñado de filas de
    `pedidos.pedido_sugerido` —una lista por día— contra las dos lecturas
    grandes que `armar` evita, así que el cambio del ticket 08 sigue pagándose
    solo.

    **Armar cuesta y por eso se arma solo cuando hace falta.** El cálculo viaja
    como función (`armar`) y no como lista: leer el catálogo entero (3,429
    filas) más 28 días de ventas (~600) es lo que esta ruta pagaba en cada
    carga y ahora paga una vez al día.

    Los dos bordes se atienden por separado y cada falla es un hueco con su
    motivo, nunca una lista vacía (regla 4): "hoy no se vendió nada" y "no pude
    leer" se ven idénticos si el único dato es una lista sin renglones, y el
    precio de confundirlos es que el pedido del día no se hace. El motivo es el
    **tipo** de la falla y nunca su texto: un `str(exc)` de SQLAlchemy lleva la
    cadena de conexión con contraseña y esto corre detrás de un túnel (regla 5).

    Es `def` y no `async def` a propósito: los dos bordes son síncronos
    —psycopg2 no es asíncrono— y así FastAPI los corre en su pool de hilos sin
    bloquear el bucle de eventos.
    """
    negocio = cargar().negocio

    try:
        ultima = almacen.ultima_fecha_con_ventas()
    except Exception as exc:  # noqa: BLE001 — el almacén caído es un hueco, no un 500
        log.exception("El almacén no contestó al preguntar por la última venta")
        return _hueco(f"el almacén no contestó ({type(exc).__name__})")

    # QUÉ TAN RECIENTES SON LAS VENTAS QUE SÍ SE LEYERON (ticket 29). Es un
    # hecho que el servidor afirma —leyó, y esto es lo que hay—, distinto del
    # hueco de arriba. El reloj entra solo para decir si lo más reciente es lo
    # más reciente que puede haber; la lista se sigue anclando en `ultima`.
    ventas = estado_de_las_ventas(ultima, _ahora(), cargar().a_quien_avisar)

    if ultima is None:
        # Un almacén sin una sola venta existe de verdad (una instalación
        # nueva). No se guarda una lista vacía —ocuparía el UNIQUE del día y el
        # rol no puede borrarla— y se distingue de la falla porque `ok` sigue
        # siendo verdadero y `ventas` lo afirma con su frase.
        #
        # OJO: esto NO es "el domingo". Un domingo no llega aquí: la lista se
        # ancla en `max(fecha)`, que es el último día que SÍ tuvo ventas, y
        # `ventas` dice si eso es lo normal para hoy.
        return _sin_ventas(ventas)

    try:
        # Primero vencer, después abrir. El orden importa: si se abriera
        # primero, la lista de hoy ya existiría cuando el barrido busca
        # "abiertas de un día anterior" y daría igual, pero al revés el
        # encargado vería por un instante dos listas abiertas.
        vencidas = almacenamiento.vencer_las_de_dias_anteriores(negocio, ultima)
        if vencidas:
            log.info(
                "%d pedido(s) sugerido(s) anteriores al %s quedaron vencidos: "
                "su día pasó y nadie los cerró.",
                vencidas,
                ultima,
            )

        ventana = ventana_de_reposicion(
            corte=almacenamiento.corte_del_ultimo_cerrado(negocio, ultima),
            hasta=ultima,
            dias_primera_vez=dias_primera_vez_configurados(),
            # El piso: días propuestos que nadie pidió. Sin esto, con la
            # ventana de un día hábil, un día desatendido se cae al suelo.
            piso_sin_pedir=almacenamiento.piso_sin_pedir(negocio, ultima),
        )
        guardado = almacenamiento.abrir_el_dia(
            negocio,
            ultima,
            ventana,
            # LA MEMORIA DE LO YA PEDIDO (ticket 24) se lee DENTRO de `armar`:
            # solo cuesta la consulta el día que la lista de verdad se arma. Y
            # si falla, falla la lista entera — con su hueco y su motivo. Armar
            # sin ella sería volver a proponer lo que ya viene en camino, en
            # silencio y guardado para todo el día.
            lambda: _armar(
                almacen,
                ventana,
                memoria_de_lo_pedido(almacenamiento.lo_ya_pedido(negocio, ultima)),
            ).renglones,
        )
    except Exception as exc:  # noqa: BLE001 — los dos bordes caídos son un hueco, no un 500
        log.exception("No se pudo abrir el pedido sugerido del %s", ultima)
        return _hueco(f"no se pudo abrir la lista del día ({type(exc).__name__})")

    if guardado.sin_catalogo:
        # A la bitácora con nombre y apellido: el hueco se ve en la pantalla,
        # pero quien vaya a arreglarlo en SICAR necesita los ids.
        log.warning(
            "%d producto(s) vendido(s) del %s no están en marts.dim_producto: %s",
            guardado.sin_catalogo,
            guardado.fecha_del_pedido,
            [
                r.propuesto.producto_id
                for r in guardado.renglones
                if not r.propuesto.esta_en_el_catalogo
            ],
        )

    # Los precios congelados viajan en la MISMA respuesta que la lista, y esa
    # es la mitad del ticket 12 que se ve al recargar: lo que se muestra es lo
    # guardado. Sin esto, una consulta lanzada hace diez minutos se vería como
    # si nunca hubiera pasado en cuanto alguien recarga la página.
    #
    # Es una consulta más por carga y una sola para toda la lista. Una por
    # renglón costaría tantas como productos distintos se vendieron, y —peor—
    # cada una leería en un momento distinto: la tabla podría dejar de
    # coincidir consigo misma mientras alguien la trabaja.
    #
    # Su falla es un hueco y no tumba la lista: un pedido sugerido sin precios
    # todavía sirve para pedir, y la quinta casilla del ticket dice que un
    # precio que no se pudo leer se ve como hueco, nunca como cero.
    # LO QUE NO SE PUDO LEER Y NO TUMBA LA LISTA (ticket 29). Cada lectura de
    # abajo que falla deja la lista viéndose —sirve para pedir— y agrega aquí
    # su aviso, para que el vacío que deja no se lea como un dato.
    avisos: list[dict] = []
    precios_sin_leer = False

    try:
        precios = almacenamiento.precios_de_la_lista(
            negocio, guardado.pedido_sugerido_id
        )
    except Exception as exc:  # noqa: BLE001 — sin precios la lista sigue sirviendo
        log.exception(
            "No se pudieron leer los precios congelados de la lista %s",
            guardado.pedido_sugerido_id,
        )
        # HASTA EL TICKET 29 ESTO ERA `{}` EN SILENCIO, y la tabla entera decía
        # "nadie lo consultó". Se sigue pintando sin precios —no hay otros—,
        # pero con un aviso arriba que dice que esos huecos no son de verdad.
        precios = {}
        precios_sin_leer = True
        avisos.append(
            {
                "detalle": (
                    f"no se pudieron leer los precios guardados ({type(exc).__name__})"
                ),
                "frase": frase_de_precios_sin_leer(),
                "que_hacer": _que_hacer(AL_LEER),
            }
        )

    # Los pedidos en que ya se partió esta lista (ticket 20). Una consulta más
    # por carga, de un puñado de filas -- como mucho una por proveedor--, y
    # viaja en la MISMA respuesta que la lista por la misma razón que los
    # precios y la corrida: dos lecturas en dos momentos pueden no coincidir y
    # nadie sabría cuál tiene razón.
    #
    # Su falla es un hueco y no tumba la lista: `None` quiere decir "no se
    # pudo saber en qué está partida", que la pantalla escribe en vez de
    # enseñar cero pedidos sobre una lista que sí está partida.
    try:
        pedidos = almacenamiento.pedidos_de_la_lista(
            negocio, guardado.pedido_sugerido_id
        )
    except Exception as exc:  # noqa: BLE001 — sin los pedidos la lista sigue sirviendo
        log.exception(
            "No se pudieron leer los pedidos de la lista %s",
            guardado.pedido_sugerido_id,
        )
        pedidos = None
        # La pantalla pinta `null` igual que "todavía no se parte" y ofrece
        # partir: sin este aviso, sobre una lista que quizá ya se envió.
        avisos.append(
            {
                "detalle": (
                    f"no se pudieron leer los pedidos de la lista ({type(exc).__name__})"
                ),
                "frase": frase_de_pedidos_sin_leer(),
                "que_hacer": _que_hacer(AL_LEER),
            }
        )

    # LO QUE VIENE EN CAMINO DE LISTAS ANTERIORES (ticket 24, casillas 2, 4 y
    # 5). Viaja en la MISMA respuesta que la lista por la razón de siempre: dos
    # lecturas en dos momentos pueden no coincidir. Su falla es un hueco dentro
    # del bloque y NO tumba la lista — la lista ya está armada y guardada, y lo
    # que se pierde es enseñar lo que viene en camino, no la protección.
    # LA RECEPCIÓN SUGERIDA (ticket 26, ADR 0014). Va ANTES del bloque de lo
    # que viene en camino porque ese bloque la usa: un renglón con propuesta no
    # ofrece devolver, y un pedido con algo recibido no ofrece cancelar. Su
    # falla es un hueco dentro de su bloque y NO tumba la lista.
    recepcion, con_propuesta, con_algo_recibido = _la_recepcion(
        almacen, almacenamiento, negocio
    )
    bloque, ya_en_camino, aun_faltan = _lo_que_viene_en_camino(
        almacen,
        almacenamiento,
        negocio,
        guardado,
        con_propuesta=con_propuesta,
        pedidos_con_algo_recibido=con_algo_recibido,
    )

    corrida, corrida_fallo = _ultima_corrida(
        almacenamiento, negocio, guardado.pedido_sugerido_id
    )
    respuesta = _como_json(
        guardado,
        precios,
        corrida,
        pedidos,
        en_camino=bloque,
        ya_en_camino=ya_en_camino,
        recepcion=recepcion,
        con_propuesta=con_propuesta,
        aun_faltan=aun_faltan,
        # EL DESHACER (ADR 0016): solo de una lista cerrada, y solo si la base
        # dice que ninguna lista se armó después y que no es de hace más de un
        # día (enmienda 2026-09-21). `ultima` es el mismo ancla que ya se leyó
        # arriba para abrir el día: no se vuelve a leer. Sin su respuesta, no
        # hay botón.
        reapertura=_la_reapertura(almacen, almacenamiento, negocio, guardado, ultima),
        corrida_fallo=corrida_fallo,
        # CORREGIR LO RECIBIDO (2026-09-21, propuesta 1 de la revisión de
        # arquitectura). Una lectura, UNA vez por respuesta —no una vez por
        # renglón recibido— de qué productos de esta lista ya atendió una
        # lista posterior: es lo que `se_puede_corregir` necesita para no
        # pintar un botón que el `WHERE` de `_CORREGIR_LO_RECIBIDO` iba a
        # rechazar.
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, guardado),
    )
    # LO QUE SOLO TRAE LA CARGA (ticket 29), igual que `en_camino`: partir,
    # enviar y tachar no lo cambian y la pantalla lo pinta una vez.
    respuesta["ventas"] = ventas
    respuesta["avisos"] = avisos
    # Una lista vacía que SÍ se leyó dice por qué está vacía, con palabras de
    # Python: "no se vendió nada" sería falso —su último día tiene ventas—.
    respuesta["lista_vacia"] = (
        None
        if guardado.renglones
        else frase_de_la_lista_vacia(guardado.ventana.desde, guardado.ventana.hasta)
    )
    if precios_sin_leer:
        # SIN LOS PRECIOS, LO QUE SALE DE ELLOS SE INVENTARÍA. Lo cazó el
        # recorrido del navegador del ticket 29: con `{}` el conteo decía "5 de
        # 5 sin comparar", cada renglón "nadie le ha pedido el precio", y el
        # botón ofrecía completar los cinco — cuatro visitas a portales ajenos
        # por renglón, por precios que sí existen. Viajan `null`, como ya hacen
        # las respuestas de un renglón cuando no pueden leerlos, y el aviso de
        # arriba dice por qué.
        respuesta["conteo_de_precios"] = None
        respuesta["faltantes"] = None
        respuesta["sesiones_caducadas"] = []
        for renglon in respuesta["renglones"]:
            renglon.pop("porque_no_hay_lectura", None)
            renglon["huecos_reintentables"] = []
    return respuesta


def _la_recepcion(
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
) -> tuple[dict, frozenset[int], frozenset[int]]:
    """El bloque de la recepción, y lo que los otros dos bloques necesitan de él.

    Devuelve `(json, con_propuesta, pedidos_con_algo_recibido)`: los renglones
    que la recepción propone como probablemente recibidos —esos no ofrecen
    devolver— y los pedidos con algo ya recibido —esos no ofrecen cancelar—.

    **Cuatro lecturas, y cada una falla por su lado** (regla 4): lo que está en
    tránsito y lo recibido salen de `pedidos`; las compras y qué productos se
    han comprado alguna vez salen de `marts`. Si falla una de las tres
    primeras, el bloque es un hueco con su motivo —el TIPO de la falla, nunca
    su texto (regla 5)—. Si falla la cuarta, la recepción se calcula igual y no
    afirma que un producto nunca aparezca en compras.

    Las compras se leen **una vez**, desde el envío más viejo que puede tener
    propuesta, y **solo si hay algo que puede tenerla**. Ninguna fecha sale
    del reloj: sale de cuándo se envió cada pedido.
    """
    ahora = _ahora()
    try:
        en_transito = almacenamiento.lo_que_esta_en_transito(negocio)
    except Exception as exc:  # noqa: BLE001 — sin la recepción, la lista sigue
        log.exception("No se pudo leer lo que está en tránsito para la recepción")
        return (
            _recepcion_con_hueco(
                f"no se pudo leer lo que viene en camino ({type(exc).__name__})"
            ),
            frozenset(),
            frozenset(),
        )

    try:
        recibido = almacenamiento.lo_recibido(
            negocio,
            {ya.producto_id for ya in en_transito},
            {ya.renglon.pedido_id for ya in en_transito if ya.renglon.pedido_id},
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("No se pudo leer lo ya recibido para la recepción")
        return (
            _recepcion_con_hueco(
                f"no se pudo leer lo ya recibido ({type(exc).__name__})"
            ),
            frozenset(),
            frozenset(),
        )
    con_algo_recibido = frozenset(r.pedido_id for r in recibido if r.pedido_id)

    desde = desde_cuando_leer_compras(en_transito)
    compras = []
    if desde is not None:
        try:
            compras = almacen.compras_desde(desde)
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudieron leer las compras para la recepción")
            return (
                _recepcion_con_hueco(
                    f"no se pudieron leer las compras ({type(exc).__name__})"
                ),
                frozenset(),
                con_algo_recibido,
            )

    try:
        comprados = (
            almacen.productos_con_compras({ya.producto_id for ya in en_transito})
            if en_transito
            else frozenset()
        )
    except Exception:  # noqa: BLE001 — sin esto no se afirma "nunca"
        log.exception("No se pudo saber qué productos aparecen en compras")
        comprados = None

    calculada = proponer(
        en_transito,
        compras,
        ya_usadas={c for r in recibido for c in r.compras},
        productos_con_compras=comprados,
    )
    return (
        recepcion_como_json(calculada, ahora),
        frozenset(p.renglon_id for p in calculada.propuestas),
        con_algo_recibido,
    )


def _lo_que_viene_en_camino(
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    guardado: PedidoSugeridoGuardado,
    *,
    con_propuesta: frozenset[int] = frozenset(),
    pedidos_con_algo_recibido: frozenset[int] = frozenset(),
):
    """El bloque de lo que viene en camino, y lo que ya viene de cada producto.

    **Dos lecturas, y cada una falla por su lado.** Lo ya pedido sale de
    `pedidos`; lo que se ha vendido desde entonces sale de `marts`. Si falla la
    primera, el bloque entero es un hueco con su motivo. Si falla la segunda,
    los renglones se enseñan igual y lo vendido dice que no se pudo leer — un
    `null`, nunca un cero (regla 4).

    La lectura de ventas **solo ocurre si hay algo en camino**, y va desde el
    ancla más vieja hasta el último día con ventas: del orden de unos días, no
    de los 28 del ritmo. Es la única lectura del almacén que esta pantalla hace
    cuando la lista ya existía, y existe para decir la tercera casilla con
    números: *eso que se vendió mientras tanto no se pierde*.

    Y desde el ticket 27, `aun_faltan`: los productos de los que todavía hay
    algo que faltó y ninguna lista ha atendido. Un renglón de hoy que trae lo
    que faltó y cuyo producto ya NO está ahí —el resto llegó y se corrigió—
    lo dice (`transito.frase_de_lo_que_ya_no_falta`). `None` si no se pudo
    leer: entonces no se afirma nada.

    Devuelve también `ya_en_camino`, por producto: los renglones **de hoy** cuyo
    producto viene en camino desde una lista anterior lo dicen en su fila. Es
    el borde que la memoria no alcanza (ver `transito.frase_de_ya_en_camino`).
    """
    try:
        ya_pedidos = almacenamiento.lo_ya_pedido(negocio, guardado.fecha_del_pedido)
    except Exception as exc:  # noqa: BLE001 — sin el bloque, la lista sigue sirviendo
        log.exception("No se pudo leer lo que viene en camino para %s", negocio)
        return (
            _en_camino_con_hueco(
                f"no se pudo leer lo que viene en camino ({type(exc).__name__})"
            ),
            {},
            None,
        )

    viajando = en_camino(ya_pedidos)
    # LO QUE VUELVE EN LA SIGUIENTE LISTA (ticket 25): lo cancelado que todavía
    # no atendió ninguna lista. `lo_ya_pedido` ya lo trae —es la misma memoria—
    # y se enseña para que el número de mañana se pueda explicar hoy.
    vuelven = tuple(ya for ya in ya_pedidos if ya.fue_cancelado)
    # LO QUE LLEGÓ DE MENOS (ticket 27): los parciales que todavía no atendió
    # ninguna lista. Se enseñan para que lo que falta en la de mañana se pueda
    # explicar hoy, y para corregir la cifra si el resto llegó en otra factura.
    faltaron = tuple(ya for ya in ya_pedidos if ya.renglon.esta_recibido_parcial)
    vendido = {}
    if viajando:
        try:
            vendido = vendido_desde_que_se_pidio(
                almacen.ventas(
                    min(ya.retiene_desde for ya in viajando), guardado.ventana.hasta
                ),
                viajando,
                hasta=guardado.ventana.hasta,
            )
        except Exception:  # noqa: BLE001 — lo vendido es un hueco, no un 500
            log.exception("No se pudo leer lo vendido desde que se pidió")
            vendido = None

    ahora = _ahora()
    umbral, detalle_del_umbral = _umbral_del_atraso()
    return (
        en_camino_como_json(
            viajando,
            vendido,
            ahora,
            umbral=umbral,
            detalle_del_umbral=detalle_del_umbral,
            vuelven=vuelven,
            con_propuesta=con_propuesta,
            pedidos_con_algo_recibido=pedidos_con_algo_recibido,
            faltaron=faltaron,
            # La lista de hoy, si se armó después de recibirlo, ya trae lo que
            # faltó: se dice "ya viene en esta lista" (recorrido del navegador).
            faltaron_en_esta_lista={
                r.propuesto.producto_id
                for r in guardado.renglones
                if r.propuesto.piezas_que_faltaron
            },
        ),
        {ya.producto_id: ya for ya in viajando},
        frozenset(ya.producto_id for ya in ya_pedidos if ya.piezas_que_vuelven),
    )


@app.post("/api/pedido-sugerido/{pedido_sugerido_id}/cerrar")
def cerrar_pedido_sugerido(
    pedido_sugerido_id: int,
    request: Request,
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Dar la lista por cerrada: ya se pidió lo que se iba a pedir (`CONTEXT.md`).

    Cerrar **no borra nada**: la lista sigue ahí con sus renglones, cambia de
    estado y gana su hora de cierre. Y guarda hasta qué momento de ventas
    consideró —`ventas_consideradas_hasta`, que trae desde que se armó—, que es
    el corte desde el cual el ticket 09 va a acumular el siguiente sugerido. Por
    eso la respuesta lo devuelve: es el dato con el que el encargado sabe qué
    quedó cubierto.

    El identificador va en la ruta y no se deduce del día: se cierra **la lista
    que está en la pantalla**. Si se dedujera de `max(fecha)` del almacén, una
    pestaña abierta desde ayer cerraría la de hoy sin que nadie lo pidiera.

    Un 409 y no un 500 cuando no hay nada que cerrar: ya estaba cerrada, ya
    venció, o es de otro negocio. La transición vive en el `WHERE` del `UPDATE`,
    así que el segundo clic no mueve `cerrado_en` ni resucita una vencida.

    **Quién cierra es una firma, no un permiso** (regla 3 de `CLAUDE.md`): el
    correo llega en `Cf-Access-Authenticated-User-Email`, ya validado por
    Cloudflare Access, y aquí solo se anota en la bitácora. El ticket 08 no pide
    una columna con quién cerró —el 10 la va a pedir para quién descartó— y
    agregarla hoy costaría una visita a atlas para un dato que nadie consulta:
    el rol no puede alterar sus tablas (ADR 0003).
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        cerrado = almacenamiento.cerrar(negocio, pedido_sugerido_id)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco, no un 500
        log.exception("No se pudo cerrar el pedido sugerido %s", pedido_sugerido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo cerrar la lista ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if cerrado is None:
        log.info(
            "%s quiso cerrar el pedido sugerido %s y no había ninguno abierto "
            "con ese id en %s.",
            firma,
            pedido_sugerido_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Esa lista ya no estaba abierta. Vuelve a cargar la página "
                    "para ver cómo quedó."
                ),
            },
        )

    log.info(
        "%s cerró el pedido sugerido %s (%s), que consideró ventas hasta el %s.",
        firma,
        cerrado.pedido_sugerido_id,
        cerrado.fecha_del_pedido,
        cerrado.ventana.hasta,
    )
    # El botón de deshacer aparece en cuanto se cierra (ADR 0016) — si la base
    # dice que se puede: una pestaña vieja pudo cerrar una lista que ya no es
    # la última, o la lista ya es de hace más de un día (enmienda 2026-09-21),
    # y ahí el botón contestaría 409. Sin `ancla` a la mano —esta ruta no lo
    # leyó para nada más—, `_la_reapertura` lo lee ella misma.
    return _como_json(
        cerrado,
        reapertura=_la_reapertura(almacen, almacenamiento, negocio, cerrado),
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, cerrado),
    )


def _los_atendidos_despues(
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    guardado: PedidoSugeridoGuardado,
) -> frozenset[int]:
    """Qué `producto_id` de esta lista ya atendió una lista posterior.

    Una lectura por respuesta (`almacenamiento.productos_atendidos_despues`),
    igual de barata que la de `_la_reapertura`. **Si falla, el lado seguro no
    es "vacío"**: un conjunto vacío diría "nada se atendió" y pintaría
    "Corregir" en renglones que el `WHERE` de `_CORREGIR_LO_RECIBIDO` podría
    rechazar. En su lugar se marcan como atendidos **todos** los `producto_id`
    ya recibidos de esta lista —apaga el botón de los que sí importan, sin
    inventar un tercer valor que el resto de la firma no espera— y se
    registra el tipo de la falla (regla 5), nunca su texto. La lista se sigue
    viendo.
    """
    try:
        return almacenamiento.productos_atendidos_despues(
            negocio, guardado.pedido_sugerido_id
        )
    except Exception:  # noqa: BLE001 — sin la respuesta, ningún botón de corregir
        log.exception(
            "No se pudo saber qué productos de la lista %s ya atendió una "
            "lista posterior",
            guardado.pedido_sugerido_id,
        )
        return frozenset(
            r.propuesto.producto_id for r in guardado.renglones if r.esta_recibido
        )


def _la_reapertura(
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    guardado: PedidoSugeridoGuardado,
    ancla: dt.date | None = None,
) -> dict | None:
    """El botón de reabrir y su frase (`cierre.reapertura`). `None` si no está cerrada.

    `ancla` es el último día con ventas del almacén —el mismo `max(fecha)` que
    usa `abrir_el_dia`, nunca el reloj (enmienda 2026-09-21 al ADR 0016)—. Quien
    ya lo leyó para esta misma respuesta lo pasa aquí en vez de que se lea otra
    vez: dos lecturas en dos momentos podrían no coincidir. Si nadie lo trae
    (`None`), se lee aquí, dentro del mismo intento.

    Una lectura solo con la lista cerrada. Si algo falla —el almacén al leer
    el ancla, o el almacenamiento al preguntar si se puede—, no hay botón y se
    dice que no se pudo saber, con qué hacer (regla 4) — y el TIPO de la
    falla, nunca su texto (regla 5). La lista se sigue viendo.
    """
    if guardado.estado != CERRADO:
        return None
    try:
        dia_ancla = ancla
        if dia_ancla is None:
            dia_ancla = almacen.ultima_fecha_con_ventas()
        if dia_ancla is None:
            # Una lista cerrada existe porque hubo un ancla el día que se
            # armó (`abrir_el_dia` se niega sin ventas): que ahora no haya
            # ninguna es un estado imposible, no una falla de red.
            raise RuntimeError("el almacén no tiene ventas: no hay ancla")
        se_puede = almacenamiento.se_puede_reabrir(
            negocio, guardado.pedido_sugerido_id, dia_ancla
        )
    except Exception as exc:  # noqa: BLE001 — sin la respuesta, no hay botón
        log.exception(
            "No se pudo saber si la lista %s se puede reabrir",
            guardado.pedido_sugerido_id,
        )
        return boton_de_reabrir(
            guardado,
            None,
            falla={
                "detalle": (
                    f"no se pudo saber si se puede reabrir ({type(exc).__name__})"
                ),
                "que_hacer": _que_hacer(AL_LEER),
            },
        )
    return boton_de_reabrir(guardado, se_puede, ancla=dia_ancla)


@app.get("/api/pedido-sugerido/{pedido_sugerido_id}/al-cerrar")
def antes_de_cerrar(
    pedido_sugerido_id: int,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Lo que la ventana de confirmación enseña antes de cerrar (ADR 0016).

    **Solo lectura.** La lista se lee **en el momento del clic**, por su id: lo
    que importa es lo que hay al decidir, no lo que había al cargar la página
    —descartar sustituye un renglón en la pantalla sin reenviar la lista, y
    otra pestaña pudo haber enviado un pedido—.

    Todo lo que se enseña sale de `cierre.al_cerrar`: cuántos renglones quedan
    sin pedir, cuántos están en un borrador sin enviar, y **cuáles traen algo
    de otro pedido que se perdería** —lo que faltó de un parcial, lo vendido
    mientras viajaba—, con sus piezas y su frase. Avisa, no prohíbe: si esto no
    se puede leer, la respuesta lo dice y cerrar sigue disponible.
    """
    negocio = cargar().negocio
    try:
        lista = almacenamiento.leer_por_id(negocio, pedido_sugerido_id)
    except Exception as exc:  # noqa: BLE001 — sin resumen se cierra igual, avisado
        log.exception(
            "No se pudo leer la lista %s para confirmar el cierre", pedido_sugerido_id
        )
        return JSONResponse(
            status_code=200,
            content=al_cerrar_sin_resumen(
                f"no se pudo leer la lista ({type(exc).__name__})",
                _que_hacer(AL_LEER),
            ),
        )
    if lista is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "detalle": (
                    "No hay una lista con ese número en este negocio. Vuelve a "
                    "cargar la página."
                ),
            },
        )
    return al_cerrar(lista)


@app.post("/api/pedido-sugerido/{pedido_sugerido_id}/reabrir")
def reabrir_pedido_sugerido(
    pedido_sugerido_id: int,
    request: Request,
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Deshacer un cierre: `cerrado` → `abierto`, firmado (ADR 0016).

    **Solo la última lista del negocio, y solo hasta un día atrás** (enmienda
    2026-09-21): ninguna lista se haya armado después, y su
    `fecha_del_pedido` no sea de hace más de un día contra `ancla` —el último
    día con ventas del almacén, el mismo `max(fecha)` que usa `abrir_el_dia`,
    nunca el reloj—. Las dos condiciones viven en el `WHERE` de `_REABRIR`, no
    aquí. Cero filas es un 409, y la lista se lee otra vez para decir por qué
    —ya estaba abierta, está vencida, es de hace más de un día, o ya se armó
    la siguiente—.

    **Reabrir no deshace nada más**: lo enviado sigue enviado, lo recibido
    sigue recibido. Solo vuelve a dejar la lista abierta, que es lo que deja
    trabajar sus renglones.

    **Quién reabre es una firma, no un permiso** (regla 3): el correo de Access
    queda en `reabierto_por`. Se guarda en la fila —al revés que el cierre, que
    solo va a la bitácora— porque reabrir es deshacer una decisión, y "¿quién
    la reabrió?" es la pregunta que alguien va a hacer.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        ancla = almacen.ultima_fecha_con_ventas()
        if ancla is None:
            # Igual que en `_la_reapertura`: una lista cerrada solo existe si
            # hubo un ancla cuando se armó (`abrir_el_dia` se niega sin
            # ventas). Que ahora no haya ninguna es un estado imposible, no
            # una falla de red.
            raise RuntimeError("el almacén no tiene ventas: no hay ancla")
        reabierta = almacenamiento.reabrir(negocio, pedido_sugerido_id, firma, ancla)
    except Exception as exc:  # noqa: BLE001 — el almacén o el almacenamiento caídos son un hueco
        log.exception("No se pudo reabrir el pedido sugerido %s", pedido_sugerido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo reabrir la lista ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if reabierta is None:
        try:
            como_quedo = almacenamiento.leer_por_id(negocio, pedido_sugerido_id)
        except Exception as exc:  # noqa: BLE001 — sin el porqué, se dice que no se pudo
            log.exception(
                "No se pudo leer la lista %s para decir por qué no se reabrió",
                pedido_sugerido_id,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detalle": (
                        "La lista no se reabrió, y no se pudo leer por qué "
                        f"({type(exc).__name__})."
                    ),
                    "que_hacer": _que_hacer(AL_LEER),
                },
            )
        log.info(
            "%s quiso reabrir el pedido sugerido %s y no se pudo (%s).",
            firma,
            pedido_sugerido_id,
            como_quedo.estado if como_quedo else "no existe",
        )
        return JSONResponse(
            status_code=409,
            content={"ok": False, "detalle": motivo_para_no_reabrir(como_quedo, ancla)},
        )

    log.info(
        "%s reabrió el pedido sugerido %s (%s), con ventas hasta el %s.",
        firma,
        reabierta.pedido_sugerido_id,
        reabierta.fecha_del_pedido,
        reabierta.ventana.hasta,
    )
    return _como_json(
        reabierta,
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, reabierta),
    )


@app.post("/api/renglon/{renglon_id}/descartar")
def descartar_renglon(
    renglon_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Un clic: el renglón pasa a `descartado` y sale de la lista de trabajo.

    **Sin cuerpo y sin confirmación.** El ticket dice un clic, y lo que hace
    segura la operación no es un diálogo —que se aprende a cerrar sin leer a la
    tercera pantalla— sino que se puede deshacer con `/devolver`. "Nada se
    filtra, y se descarta con un clic" es la mitad de lo que mantiene legible
    una lista tan larga como productos distintos se vendieron (ADR 0002).

    **Descartar no borra nada**: el renglón sigue en su lista, con sus números
    congelados, y se ve aparte. El rol `continental` no tiene `DELETE` y eso no
    es una limitación que haya que sortear, es el diseño (ADR 0003).

    **Quién descartó se guarda en la fila, no solo en la bitácora**, y ahí está
    la diferencia con el cierre del ticket 08. No es celo de auditoría: es la
    evidencia de la **condición de revisión del ADR 0002** —"si después de un
    mes de uso los renglones descartados superan a los pedidos, la reposición
    1 a 1 no es la regla correcta"—. Una bitácora rota por `logrotate` no se
    puede consultar con un `GROUP BY`; una columna sí. Va junto con el cuándo,
    porque sin él no hay forma de acotar "un mes".

    Es una **firma y no un permiso** (regla 3 de `CLAUDE.md`): el correo lo
    validó Cloudflare Access y aquí solo se anota. Sin el túnel delante vale
    `sin-identificar`, que dice la verdad — que no se supo—.

    **Descartar NO es una lista negra**, y conviene tenerlo presente al leer
    esto al lado del ticket 09: el descarte es de un **renglón**, no del
    producto. La ventana de reposición acumula por fechas de venta desde el
    corte del último cerrado y `calcular_pedido_sugerido` no mira el estado de
    renglones anteriores, así que un producto que alguien decidió no pedir hoy
    vuelve a proponerse mañana si se vuelve a vender. Es lo correcto: "hoy no
    hace falta" no es "nunca hace falta", y lo contrario sería mercancía que
    deja de proponerse para siempre por un clic. Lo único que saca un producto
    de la lista siguiente es `en tránsito` (`CONTEXT.md`), y eso es el ticket
    24. Lo cubre
    `test_descarte.test_un_producto_descartado_vuelve_a_proponerse_si_se_vuelve_a_vender`.

    Un 409 y no un 500 cuando no hay nada que descartar: el renglón no existe,
    es de otro negocio, o ya no está `abierto` —`en tránsito` significa que ya
    se le pidió a un proveedor—. Los tres casos se ven igual desde fuera a
    propósito: distinguirlos sería contar qué ids hay en la tabla.

    El identificador es el del **renglón** y no va anidado bajo su lista: la
    llave es global (`GENERATED ALWAYS AS IDENTITY`) y el `negocio` sale de la
    configuración, así que un `pedido_sugerido_id` en la ruta sería un dato
    repetido que la pantalla tendría que mantener de acuerdo con el otro.

    Es `def` y no `async def` a propósito: el borde es síncrono —psycopg2 no es
    asíncrono— y así FastAPI lo corre en su pool de hilos.
    """
    return _mover_el_renglon(
        renglon_id,
        request,
        lambda negocio, firma: almacenamiento.descartar(negocio, renglon_id, firma),
        verbo="descartar el renglón",
        choque=(
            "Ese renglón ya no estaba abierto. Vuelve a cargar la página para "
            "ver cómo quedó."
        ),
        accion="descartar",
        almacenamiento=almacenamiento,
    )


@app.post("/api/renglon/{renglon_id}/devolver")
def devolver_renglon(
    renglon_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Deshacer el descarte: vuelve a `abierto` y se borra la firma.

    Es la otra dirección del ticket, y es lo que permite que descartar cueste
    un clic sin confirmación.

    **La firma y la hora se van juntas.** Un renglón devuelto a `abierto` no
    está descartado: dejarle `descartado_por` puesto haría que el conteo
    mensual del ADR 0002 sumara renglones que alguien está trabajando, y la
    condición de revisión se dispararía con evidencia falsa. Lo rechazaría
    además `ck_renglon_descarte`.

    Lo que cuesta, dicho con todas sus letras: **no queda rastro del descarte
    deshecho**. Un historial de cada clic sería otra tabla y otro ticket; el
    dato que el ADR necesita es cuántos renglones quedaron descartados, no
    cuántas veces alguien dudó.

    Un 409 si el renglón no estaba `descartado`: la transición vive en el
    `WHERE` del `UPDATE`, así que el segundo clic no mueve nada.
    """
    return _mover_el_renglon(
        renglon_id,
        request,
        lambda negocio, firma: almacenamiento.devolver_a_abierto(negocio, renglon_id),
        verbo="devolver a abierto el renglón",
        choque=(
            "Ese renglón ya no estaba descartado. Vuelve a cargar la página "
            "para ver cómo quedó."
        ),
        accion="devolver_a_abierto",
        almacenamiento=almacenamiento,
    )


class CantidadNueva(BaseModel):
    """Lo único que el navegador manda al corregir un renglón: cuántas piezas.

    Un cuerpo y no un parámetro en la ruta porque es un **dato** y no la
    identidad de nada: `/api/renglon/3/cantidad/0` se vería como un recurso que
    existe, y quedaría escrito en la bitácora de accesos del túnel junto a todo
    lo demás.

    `int` pelado, sin `ge=1` de pydantic, y esa es una decisión: con el `ge`
    puesto, FastAPI contestaría solo "Input should be greater than or equal to
    1" —en inglés, sin decir qué hacer en su lugar—. La mitad del valor de la
    casilla 3 del ticket es que **hay otro camino** y que la pantalla lo diga:
    para no pedir un renglón está `descartado`, con su firma y su hora. Así que
    el cero se rechaza aquí abajo, a mano, con el texto que explica.
    """

    cantidad: int


class ProveedorElegido(BaseModel):
    """Lo único que el navegador manda al elegir: la clave del proveedor.

    La **clave de Doyle** (`nadro`, `levic`, `vicma`, `quepharma`) y no el
    `proveedor_id` de SICAR, y esa es la decisión del ADR 0008 asomando por la
    interfaz: se le pide a quien se le preguntó el precio. Mandar el id de SICAR
    haría imposible elegir a QuePharma, que no tiene fila en `dim_proveedor`.

    Un cuerpo y no un parámetro en la ruta, por la misma razón que
    `CantidadNueva`: es un dato y no la identidad de nada, y quedaría escrito
    en la bitácora de accesos del túnel junto a todo lo demás.

    `str` pelado, sin `Literal[...]` de pydantic, y por lo mismo que la
    cantidad no lleva `ge=1`: FastAPI contestaría en inglés y sin decir cuáles
    son los cuatro. La comprobación se hace abajo, a mano, con el texto que los
    enumera.
    """

    proveedor: str


class MarcaDeCaptura(BaseModel):
    """Lo único que el navegador manda al tachar: si queda tachado o no.

    **Explícito y sin valor por omisión**, a propósito: la ruta no "alterna" el
    estado. Con dos pestañas abiertas, un "alterna" mandado desde la que iba
    atrasada destacharía lo que la otra acaba de tachar; "déjalo tachado" dicho
    dos veces deja lo mismo. Sin el campo, 422: un tachón por omisión firmaría
    algo que nadie dijo.
    """

    capturado: bool


@app.post("/api/renglon/{renglon_id}/cantidad")
def ajustar_la_cantidad_del_renglon(
    renglon_id: int,
    cuerpo: CantidadNueva,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Corregir cuánto se va a pedir de un renglón, **sin tocar lo que se propuso**.

    El encargado sabe cosas que el sistema no: que mañana es puente, que un
    cliente viene por una caja entera, que el proveedor surte de a seis. La
    reposición 1 a 1 es aritmética verificable —"se vendieron tres, se piden
    tres"— y por eso es defendible, pero no es adivina.

    **Las dos cantidades se guardan por separado y `cantidad_propuesta` es
    inmutable.** Ésa es la mitad del ticket que no se ve en la pantalla: la
    diferencia entre lo que el sistema propuso y lo que la persona pidió es lo
    único que después va a decir si la reposición 1 a 1 está bien calibrada. Una
    sola columna sobreescribible se vería igual y borraría el dato en silencio,
    que es la falla que la regla 4 de `CLAUDE.md` prohíbe.

    **Un cero no es una forma de descartar**, y aquí es donde se explica. La
    regla está en tres lugares a propósito, y cada uno hace algo distinto:

    1. `ck_renglon_cantidad_final` en la tabla es la **garantía**: no depende de
       qué código escriba la fila, y sigue puesta el día que alguien toque la
       base desde un `psql` o desde un módulo que todavía no existe.
    2. `revisar_el_renglon` en `almacenamiento.py` es lo que impide que **el
       doble sea más permisivo que Postgres**: sin él, el suite se quedaría en
       verde y el `UPDATE` rebotaría en atlas contra una violación de
       restricción que nadie sabría explicar.
    3. Este `if` es el que **explica**. Los otros dos rechazan; ninguno de los
       dos puede decirle al encargado que lo que quiere hacer se llama
       descartar y está a un clic. Un 500 genérico —que es en lo que se
       convertiría una violación de restricción, por la regla 5— habría sido
       "algo falló" para el camino más común de todos: teclear un cero.

    Un 409 y no un 500 cuando no hay nada que corregir: el renglón no existe, es
    de otro negocio, ya no está `abierto`, **o su lista ya no está abierta**.
    Los cuatro casos se ven igual desde fuera a propósito, igual que en el
    descarte.

    **Quién la cambió se guarda en la fila**, no solo en la bitácora, por la
    misma razón que el descarte: una bitácora rota por `logrotate` no se
    consulta con un `GROUP BY`, y la pregunta "¿por qué pediste diez de algo de
    lo que se vendieron tres?" necesita a quién hacérsela. Es una **firma y no
    un permiso** (regla 3 de `CLAUDE.md`).

    Es `def` y no `async def` a propósito: el borde es síncrono —psycopg2 no es
    asíncrono— y así FastAPI lo corre en su pool de hilos.
    """
    if cuerpo.cantidad < CANTIDAD_FINAL_MINIMA:
        log.info(
            "%s intentó dejar el renglón %s en %d piezas. Se rechazó: un cero no "
            "es una forma de descartar.",
            quien(request),
            renglon_id,
            cuerpo.cantidad,
        )
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "detalle": (
                    f"La cantidad tiene que ser de al menos {CANTIDAD_FINAL_MINIMA} "
                    "pieza. Un cero no es una forma de descartar: para no pedir "
                    "este renglón, usa Descartar — así queda guardado quién "
                    "decidió no pedirlo."
                ),
            },
        )

    return _mover_el_renglon(
        renglon_id,
        request,
        lambda negocio, firma: almacenamiento.ajustar_la_cantidad(
            negocio, renglon_id, cuerpo.cantidad, firma
        ),
        verbo="ajustar la cantidad del renglón",
        choque=(
            "Ese renglón ya no se puede cambiar: o la lista dejó de estar "
            "abierta, o el renglón ya no está abierto. Vuelve a cargar la "
            "página para ver cómo quedó."
        ),
        accion="ajustar_la_cantidad",
        nota=f"La cantidad a pedir queda en {cuerpo.cantidad}.",
        almacenamiento=almacenamiento,
    )


@app.post("/api/renglon/{renglon_id}/proveedor")
def elegir_el_proveedor_del_renglon(
    renglon_id: int,
    cuerpo: ProveedorElegido,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Marcar a quién se le pide este renglón. **La persona decide.**

    El sistema sugiere el más barato con existencia y esa sugerencia ya viaja en
    cada renglón, calculada. Lo que esta ruta guarda es **otra cosa**: que
    alguien la miró y decidió, aunque haya decidido lo mismo. *Hay razones que
    el sistema no ve —mínimo de pedido, días de entrega, crédito con cada
    proveedor—* (ADR 0002), y ninguna de las tres está en ningún dato que
    Continental tenga.

    **Lo sugerido no se guarda y lo decidido sí.** Es la misma pregunta que el
    ticket 11 resolvió con dos columnas y aquí la respuesta es distinta a
    propósito: la sugerencia se recalcula de una función pura sobre precios que
    solo crecen, así que una copia guardada sería un segundo hecho que envejece
    sin avisar. El porqué entero está en el encabezado de `particion.py`.

    **Se puede elegir a un proveedor que no dio precio**, y no es un descuido:
    es la quinta casilla del ticket. El renglón entra al pedido con la marca de
    *precio desconocido*, nunca con un cero. Por eso este `if` solo comprueba
    que la clave sea una de las que Doyle conoce —una clave inventada no
    cruzaría con ninguna lectura ni con el puente hacia SICAR— y no comprueba
    nada sobre el precio.

    Un 409 y no un 500 cuando no hay nada que elegir: el renglón no existe, es
    de otro negocio, ya no está `abierto`, **o su lista ya no está abierta**.
    Los cuatro casos se ven igual desde fuera, igual que en el descarte y en el
    ajuste.

    Es `def` y no `async def` a propósito: el borde es síncrono y así FastAPI lo
    corre en su pool de hilos.
    """
    if cuerpo.proveedor not in NOMBRES_DE_PROVEEDOR:
        log.info(
            "%s intentó elegir el proveedor %r para el renglón %s. Se rechazó: "
            "no es uno de los que Doyle consulta.",
            quien(request),
            cuerpo.proveedor,
            renglon_id,
        )
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "detalle": (
                    "Ese proveedor no es ninguno de los cuatro que se consultan: "
                    + ", ".join(NOMBRES_DE_PROVEEDOR.values())
                    + "."
                ),
            },
        )

    return _mover_el_renglon(
        renglon_id,
        request,
        lambda negocio, firma: almacenamiento.elegir_proveedor(
            negocio, renglon_id, cuerpo.proveedor, firma
        ),
        verbo="elegir el proveedor del renglón",
        choque=(
            "Ese renglón ya no se puede cambiar: o la lista dejó de estar "
            "abierta, o el renglón ya no está abierto. Vuelve a cargar la "
            "página para ver cómo quedó."
        ),
        accion="elegir_proveedor",
        nota=f"Se le pide a {nombre_del_proveedor(cuerpo.proveedor)}.",
        almacenamiento=almacenamiento,
    )


@app.post("/api/pedido-sugerido/{pedido_sugerido_id}/partir")
def partir_en_pedidos(
    pedido_sugerido_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Convertir la lista del día en pedidos, uno por proveedor (ticket 20).

    **Se puede partir cuantas veces haga falta mientras los pedidos sigan en
    `borrador`, y eso no es un descuido: es lo que los mantiene al día.** La
    garantía la da la base y no este código: `ux_pedido_proveedor` es *uno por
    proveedor dentro de la misma lista* y `_ABRIR_EL_PEDIDO` la nombra en su
    `ON CONFLICT ON CONSTRAINT`, así que la segunda partición reencuentra el
    pedido que ya estaba y le reescribe el total en vez de duplicarlo.

    Qué pasa si entre las dos particiones alguien cambió una elección: el
    renglón cambia de `pedido_id` —una columna, un solo pedido— y si el pedido
    de antes se quedó sin renglones **se queda ahí, con total `NULL`**. No se
    borra porque el rol no tiene `DELETE` (ADR 0003), y su total no es `0.00`
    porque un pedido vacío no cuesta nada por no tener nada, no por ser gratis.

    Qué pasa con lo que ya no sea `borrador` (ticket 21): no se toca. El `WHERE`
    del `DO UPDATE` y el `EXISTS` de `_SOLTAR_RENGLONES` lo protegen, así que
    volver a partir no puede vaciar un pedido que ya está en el portal del
    proveedor.

    **El cálculo es puro y viaja hecho.** `particion.partir` decide a quién se
    le pide cada renglón y cuánto suma cada pedido, con su tabla de casos y sin
    Postgres; esta ruta junta las tres lecturas que hacen falta y llama a
    escribir. Es el mismo reparto que `comparacion.contar_la_lista`.

    Un 409 cuando no había nada que partir: la lista no existe, es de otro
    negocio, o **ya no está abierta**. Una lista `cerrada` quiere decir "ya se
    pidió lo que se iba a pedir" (`CONTEXT.md`), y armar pedidos dentro de ella
    sería exactamente lo que ese estado significa que no debe pasar.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        guardado = almacenamiento.leer_por_id(negocio, pedido_sugerido_id)
        if guardado is None:
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detalle": (
                        "Esa lista ya no está: vuelve a cargar la página para "
                        "ver cómo quedó."
                    ),
                },
            )
        precios = almacenamiento.precios_de_la_lista(negocio, pedido_sugerido_id)
        comparaciones = {
            r.renglon_id: comparar(precios.get(r.renglon_id, ()), r.cantidad_a_pedir)
            for r in guardado.por_repartir
        }
        particion = partir(
            guardado.por_repartir, comparaciones, precios, puente_configurado()
        )
        pedidos = almacenamiento.guardar_la_particion(
            negocio, pedido_sugerido_id, particion.pedidos
        )
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        log.exception("No se pudo partir la lista %s", pedido_sugerido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo partir la lista ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if pedidos is None:
        log.info(
            "%s quiso partir la lista %s de %s y no estaba abierta.",
            firma,
            pedido_sugerido_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Esa lista ya no está abierta, así que no se puede partir en "
                    "pedidos. Vuelve a cargar la página para ver cómo quedó."
                ),
            },
        )

    log.info(
        "%s partió la lista %s de %s en %d pedido(s): %s. Quedaron %d renglón(es) "
        "sin proveedor.%s",
        firma,
        pedido_sugerido_id,
        negocio,
        len(pedidos),
        ", ".join(f"{p.nombre} ({p.estado_declarado})" for p in pedidos) or "ninguno",
        len(particion.sin_proveedor),
        (
            " SICAR no conoce a "
            + ", ".join(nombre_del_proveedor(p) for p in particion.sin_puente)
            + ", así que su pedido va sin proveedor_id."
            if particion.sin_puente
            else ""
        ),
    )

    # La lista entera se vuelve a leer para devolverla con los `pedido_id` ya
    # puestos en sus renglones. Cuesta una consulta y evita que la pantalla
    # tenga que adivinar cuál renglón quedó en cuál pedido — que es justo el
    # tipo de cuenta que el navegador no debe llevar.
    relectura = almacenamiento.leer_por_id(negocio, pedido_sugerido_id) or guardado
    corrida, corrida_fallo = _ultima_corrida(almacenamiento, negocio, pedido_sugerido_id)
    return _como_json(
        relectura,
        almacenamiento.precios_de_la_lista(negocio, pedido_sugerido_id),
        corrida,
        pedidos,
        corrida_fallo=corrida_fallo,
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, relectura),
    )


@app.post("/api/pedido/{pedido_id}/enviar")
def enviar_el_pedido(
    pedido_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Marcar un pedido como **enviado**: `borrador` -> `enviado` (ticket 21).

    **Continental no le manda nada a nadie al apretar esto, y esa es la mitad
    del ticket.** No entra a los portales de los proveedores y no va a entrar:
    lo prohíbe la regla 1 de `CLAUDE.md` y el ADR 0002 lo dejó fuera de alcance
    con su razón —cuatro portales con carritos distintos, sesiones que se caen
    solas, y un pedido capturado mal por un robot llega en cajas—. Lo que esta
    ruta guarda es la **declaración** de una persona: *yo ya lo capturé en el
    portal del proveedor*, con su correo y la hora. El ADR 0009 lo razona
    entero, con las tres alternativas descartadas.

    Por eso lleva firma y no acuse (regla 3): el hecho ocurrió en otra pantalla,
    con otras credenciales, y lo único verdadero que se puede escribir es quién
    lo dice y cuándo lo dijo.

    **No hay cuerpo que validar.** No se manda el total ni el estado: los dos ya
    están guardados, y aceptarlos por el cuerpo dejaría que el navegador dijera
    cuánto cuesta un pedido. Lo que el encargado ve antes de apretar es el total
    que esta misma ruta devolvió en la carga anterior.

    **Devuelve la lista entera**, como `partir`, porque enviar mueve muchas
    cosas a la vez: el estado del pedido, el de todos sus renglones, la vista
    previa de la partición, el conteo de huecos y la cola del botón de
    completar. Devolver solo el pedido obligaría a la pantalla a deducir el
    resto, que es justo lo que no debe hacer.

    Un 409 cuando no había nada que enviar, y son **tres** casos que no se
    distinguen desde fuera —igual que en el descarte—: el pedido no existe en
    este negocio, ya estaba `enviado`, o se quedó sin renglones al volver a
    partir. La condición vive en el `WHERE`, no en un `if`: dos pestañas
    abiertas en el mostrador bastan para que comprobar aquí y escribir después
    se pisen.

    Es `def` y no `async def` a propósito: el borde es síncrono y así FastAPI lo
    corre en su pool de hilos.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        enviado = almacenamiento.enviar_el_pedido(negocio, pedido_id, firma)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        # Regla 5 de `CLAUDE.md`: el detalle a la bitácora del servidor, nunca
        # al navegador. Un `str(exc)` de SQLAlchemy lleva la cadena de conexión
        # con contraseña.
        log.exception("No se pudo enviar el pedido %s", pedido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo enviar el pedido ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if enviado is None:
        log.info(
            "%s quiso enviar el pedido %s de %s y no se pudo: o ya estaba "
            "enviado, o se quedó sin renglones, o no es de este negocio.",
            firma,
            pedido_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese pedido ya no se puede enviar: o ya estaba enviado, o se "
                    "quedó sin renglones. Vuelve a cargar la página para ver "
                    "cómo quedó."
                ),
            },
        )

    log.info(
        "%s marcó como enviado el pedido %s (%s) de la lista %s de %s, con "
        "total %s. %d renglón(es) pasaron a «en tránsito». NO se le mandó nada "
        "al proveedor: Continental no entra a los portales (ADR 0009).",
        firma,
        pedido_id,
        enviado.pedido.nombre,
        enviado.pedido.pedido_sugerido_id,
        negocio,
        "sin saber" if enviado.pedido.total_sin_iva is None else enviado.pedido.total_sin_iva,
        enviado.cuantos_renglones,
    )

    # La lista entera se vuelve a leer para devolverla con los renglones ya en
    # `en tránsito`. Cuesta una consulta y evita que la pantalla tenga que
    # deducir qué renglones se movieron — que es justo el tipo de cuenta que el
    # navegador no debe llevar.
    lista_id = enviado.pedido.pedido_sugerido_id
    relectura = almacenamiento.leer_por_id(negocio, lista_id)
    if relectura is None:
        # No debería pasar —la fila que acabamos de escribir cuelga de esa
        # lista— pero si pasa se dice en vez de reventar con un `None`.
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": "el pedido se envió, pero no se pudo releer la lista",
                "que_hacer": _que_hacer(AL_LEER),
            },
        )
    corrida, corrida_fallo = _ultima_corrida(almacenamiento, negocio, lista_id)
    return _como_json(
        relectura,
        almacenamiento.precios_de_la_lista(negocio, lista_id),
        corrida,
        almacenamiento.pedidos_de_la_lista(negocio, lista_id),
        corrida_fallo=corrida_fallo,
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, relectura),
    )


@app.post("/api/pedido/{pedido_id}/cancelar")
def cancelar_el_pedido(
    pedido_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Cancelar un pedido que nunca se capturó: `enviado` -> `cancelado` (25).

    **Continental no cancela nada en ningún portal**, igual que no captura nada
    en ninguno (regla 1, ADR 0009 y 0013). Lo que se guarda es la palabra de una
    persona —*este pedido no está en el portal del proveedor*— con su correo y
    la hora. Firma y no permiso (regla 3): sin encabezado se firma
    `sin-identificar`, que es un dato, y no se niega nada.

    **No es "desenviar".** El pedido no vuelve a `borrador` y no se edita. Sus
    renglones en tránsito pasan a `cancelado` y lo que vuelve es su **producto,
    en la siguiente lista**, con todo lo que cubrían (ADR 0013). La lista de hoy
    no se recalcula —lo que se muestra es lo guardado—, así que la pantalla
    **vuelve a cargar** después de esto en vez de deducir qué cambió.

    Un 409 cuando no había nada que cancelar: no es de este negocio, es un
    borrador, ya estaba cancelado, o algo suyo ya se recibió. La condición vive
    en el `WHERE`, no en un `if`.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        cancelado = almacenamiento.cancelar_el_pedido(negocio, pedido_id, firma)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        # Regla 5: el detalle a la bitácora, al navegador solo el tipo.
        log.exception("No se pudo cancelar el pedido %s", pedido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo cancelar el pedido ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if cancelado is None:
        log.info(
            "%s quiso cancelar el pedido %s de %s y no se pudo: o no está "
            "enviado, o ya estaba cancelado, o algo suyo ya se recibió.",
            firma,
            pedido_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese pedido ya no se puede cancelar: o no está enviado, o ya "
                    "se canceló, o algo de él ya se recibió. Vuelve a cargar la "
                    "página para ver cómo quedó."
                ),
            },
        )

    log.info(
        "%s canceló el pedido %s (%s) de la lista %s de %s: dijo que no está en "
        "el portal. %d renglón(es) dejaron de estar en tránsito y vuelven a "
        "proponerse en la siguiente lista. NO se canceló nada en el portal "
        "(ADR 0013).",
        firma,
        pedido_id,
        cancelado.pedido.nombre,
        cancelado.pedido.pedido_sugerido_id,
        negocio,
        cancelado.cuantos_renglones,
    )
    return {
        "ok": True,
        "pedido": _pedido_como_json(cancelado.pedido),
        "renglones_cancelados": cancelado.cuantos_renglones,
        "frase": frase_del_pedido_cancelado(
            cancelado.pedido.nombre, cancelado.cuantos_renglones
        ),
    }


@app.post("/api/renglon/{renglon_id}/devolver-atrasado")
def devolver_el_renglon_atrasado(
    renglon_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Devolver a la lista UN renglón atrasado, sin cancelar su pedido (25).

    Solo lo que lleva **más de N días** en camino, con N de
    `config/continental.yml`. El límite se calcula aquí con el mismo reloj y la
    misma función con que la pantalla decidió ofrecer el botón
    (`transito.enviado_antes_de`), y viaja al `WHERE` como parámetro: la base
    no devuelve lo que todavía no se atrasa aunque alguien fabrique la petición.

    El renglón pasa a `cancelado`, firmado, y su **producto** vuelve en la
    siguiente lista con todo lo que cubría. Su pedido sigue `enviado`: lo demás
    de él puede estar llegando. Continental no cancela nada en el portal; la
    advertencia de la pantalla lo dice junto al botón.

    Sin el N —YAML mal escrito— **no se devuelve nada**, y se dice por qué:
    devolver con un número inventado sería abrir la válvula en un día que nadie
    escogió.
    """
    negocio = cargar().negocio
    firma = quien(request)

    umbral, detalle_del_umbral = _umbral_del_atraso()
    if umbral is None:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se puede decir qué está atrasado: {detalle_del_umbral}",
                "que_hacer": _que_hacer(CONFIGURACION),
            },
        )

    try:
        devuelto = almacenamiento.devolver_el_atrasado(
            negocio, renglon_id, firma, enviado_antes_de(_ahora(), umbral)
        )
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        log.exception("No se pudo devolver el renglón %s a la lista", renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": (
                    f"no se pudo devolver el renglón a la lista ({type(exc).__name__})"
                ),
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if devuelto is None:
        log.info(
            "%s quiso devolver a la lista el renglón %s de %s y no se pudo: o "
            "ya no está en tránsito, o todavía no lleva más de %d días.",
            firma,
            renglon_id,
            negocio,
            umbral,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese renglón no se puede devolver a la lista: o ya no está en "
                    f"camino, o todavía no lleva más de {umbral} días. Vuelve a "
                    "cargar la página para ver cómo quedó."
                ),
            },
        )

    log.info(
        "%s devolvió a la lista el renglón %s (%s) de %s por atrasado: pasó a "
        "«cancelado» y su producto vuelve en la siguiente lista. Su pedido sigue "
        "enviado. NO se canceló nada en el portal (ADR 0013).",
        firma,
        renglon_id,
        devuelto.propuesto.descripcion,
        negocio,
    )
    return {
        "ok": True,
        "renglon_id": devuelto.renglon_id,
        "frase": frase_del_renglon_devuelto(devuelto.propuesto.descripcion),
    }


class ComprasVistas(BaseModel):
    """Lo único que el navegador manda al confirmar o rechazar: qué compras vio.

    No es la evidencia —ésa la vuelve a calcular el servidor—: es **lo que la
    persona juzgó**. Si la propuesta de ahora ya no es esa misma —apareció otra
    compra, otra pestaña rechazó una—, se niega en vez de confirmar algo que
    nadie vio.
    """

    compras: list[int]


def _la_propuesta_de_ahora(
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    renglon_id: int,
):
    """La propuesta de ese renglón **recalculada ahora**, con las mismas cuatro
    lecturas que la pantalla. `None` si hoy ya no la tiene."""
    en_transito = almacenamiento.lo_que_esta_en_transito(negocio)
    if not any(ya.renglon.renglon_id == renglon_id for ya in en_transito):
        return None
    recibido = almacenamiento.lo_recibido(
        negocio, {ya.producto_id for ya in en_transito}, set()
    )
    desde = desde_cuando_leer_compras(en_transito)
    compras = [] if desde is None else almacen.compras_desde(desde)
    return proponer(
        en_transito, compras, ya_usadas={c for r in recibido for c in r.compras}
    ).propuesta_de(renglon_id)


def _recibir_o_rechazar(
    accion: str,
    renglon_id: int,
    cuerpo: ComprasVistas,
    request: Request,
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
):
    """Lo común de confirmar y rechazar (ticket 26): recalcular, comparar, escribir.

    Tres respuestas y ninguna más:

    - `409` si la propuesta de ahora no es la que la persona vio, si no se
      puede confirmar —la evidencia no alcanza lo pedido—, o si el `WHERE`
      dijo que no. Nada cambia.
    - `200` con `ok: false` y el **tipo** de la falla si un borde se cayó
      (regla 5: el texto no viaja).
    - `200` con la frase de lo que pasó.
    """
    negocio = cargar().negocio
    firma = quien(request)
    vistas = sorted(set(cuerpo.compras))
    confirmar = accion == "confirmar"
    parcial = accion == "parcial"

    try:
        propuesta = _la_propuesta_de_ahora(almacen, almacenamiento, negocio, renglon_id)
        if propuesta is None or vistas != sorted(propuesta.compras_ids):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detalle": (
                        "Esa propuesta ya no es la que se ve en la pantalla: o el "
                        "renglón ya no está en camino, o cambiaron las compras que "
                        "encajan. Vuelve a cargar la página para verla como está."
                    ),
                },
            )
        if confirmar and not propuesta.se_puede_confirmar:
            return JSONResponse(
                status_code=409,
                content={"ok": False, "detalle": propuesta.motivo_para_no_confirmar},
            )
        # RECIBIR PARCIAL (ticket 27): solo lo que trae de menos. Con lo pedido
        # completo, lo que corresponde es confirmar.
        if parcial and not propuesta.se_puede_recibir_parcial:
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detalle": (
                        "Esa compra trae lo que se pidió: confírmala como "
                        "recibida, no como parcial."
                    ),
                },
            )
        if confirmar:
            renglon = almacenamiento.confirmar_la_recepcion(
                negocio, renglon_id, propuesta.compras_ids, propuesta.piezas, firma
            )
        elif parcial:
            renglon = almacenamiento.recibir_parcial_con_compras(
                negocio, renglon_id, propuesta.compras_ids, propuesta.piezas, firma
            )
        else:
            renglon = almacenamiento.rechazar_la_recepcion(
                negocio, renglon_id, propuesta.compras_ids, firma
            )
    except Exception as exc:  # noqa: BLE001 — un borde caído es un hueco
        # Regla 5: el detalle a la bitácora, al navegador solo el tipo.
        log.exception("No se pudo %s la recepción del renglón %s", accion, renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": (
                    f"no se pudo {accion} la recepción ({type(exc).__name__})"
                ),
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if renglon is None:
        log.info(
            "%s quiso %s la recepción del renglón %s de %s y el WHERE dijo que no.",
            firma,
            accion,
            renglon_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese renglón ya no se puede "
                    + ("rechazar" if accion == "rechazar" else "recibir")
                    + ": o ya no está en camino, o esa compra ya se usó o se "
                    "rechazó. Vuelve a cargar la página para ver cómo quedó."
                ),
            },
        )

    log.info(
        "%s %s la recepción del renglón %s (%s) de %s con las compras %s de SICAR "
        "(%s piezas; ADR 0014 y 0015).",
        firma,
        {"confirmar": "confirmó", "parcial": "recibió parcial", "rechazar": "rechazó"}[accion],
        renglon_id,
        renglon.propuesto.descripcion,
        negocio,
        list(propuesta.compras_ids),
        propuesta.piezas,
    )
    if confirmar:
        frase = frase_del_confirmado(renglon.propuesto.descripcion)
    elif parcial:
        frase = frase_de_lo_recibido_a_mano(renglon, antes=None)
    else:
        frase = frase_del_rechazado(renglon.propuesto.descripcion)
    return {
        "ok": True,
        "renglon_id": renglon.renglon_id,
        "estado": renglon.estado,
        "frase": frase,
    }


@app.post("/api/renglon/{renglon_id}/recepcion/confirmar")
def confirmar_la_recepcion(
    renglon_id: int,
    cuerpo: ComprasVistas,
    request: Request,
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """"Sí llegó, completo": `en tránsito` → `recibido`, firmado (ticket 26).

    **Nunca pasa solo**: la propuesta se calcula y se enseña, y esto es el clic
    de una persona que la juzgó (ADR 0002, 0014). La firma es la de Access y es
    firma, no permiso (regla 3). Con esto lo retenido del ticket 24 vuelve solo
    en la siguiente lista: `recibido` cierra el tránsito.
    """
    return _recibir_o_rechazar(
        "confirmar", renglon_id, cuerpo, request, almacen, almacenamiento
    )


@app.post("/api/renglon/{renglon_id}/recepcion/rechazar")
def rechazar_la_recepcion(
    renglon_id: int,
    cuerpo: ComprasVistas,
    request: Request,
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """"Esa compra no es este pedido": el renglón **sigue en tránsito** (26).

    Se guarda qué compras no son suyas, firmado, para que no se vuelvan a
    proponer mañana; una compra distinta sí se propondrá.
    """
    return _recibir_o_rechazar(
        "rechazar", renglon_id, cuerpo, request, almacen, almacenamiento
    )


@app.post("/api/renglon/{renglon_id}/recepcion/parcial")
def recibir_parcial_con_la_evidencia(
    renglon_id: int,
    cuerpo: ComprasVistas,
    request: Request,
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """"Llegó solo eso": `en tránsito` → `recibido parcial` con la evidencia (27).

    La salida que el 26 no tenía para una propuesta que trae de menos: 3 de 5.
    La misma ida y vuelta que confirmar —el servidor recalcula la propuesta y
    se niega si ya no es la que la persona vio— y la misma firma (regla 3). Lo
    que faltó vuelve a proponerse en la siguiente lista (ADR 0015).
    """
    return _recibir_o_rechazar(
        "parcial", renglon_id, cuerpo, request, almacen, almacenamiento
    )


class PiezasRecibidas(BaseModel):
    """Lo único que el navegador manda al recibir a mano: cuántas llegaron.

    **Sin tipo**, a propósito, igual que `CantidadNueva` no lleva `ge=1`: con
    `int`, pydantic contestaría en inglés, aceptaría `true` como un 1 y `"6"`
    como un 6. La validación la hace `recepcion.piezas_escritas`, con palabras
    de persona y con pruebas. Sin el campo es `None`, y eso también se dice.
    """

    piezas: Any = None


def _motivo_del_409_a_mano(
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    antes: RenglonGuardado | None,
    piezas: int,
) -> dict:
    """El motivo real del 409 de `recibir_a_mano`, no la adivinanza de antes.

    Hasta el 2026-09-21 esto decidía con `antes.esta_recibido` y un texto
    catch-all —"...o la cifra ya era ésa"— que era el mismo para "ya lo
    atendió una lista posterior", "la cifra ya es ésa" y "el pedido ya no
    está enviado". Ahora se re-lee lo que `transiciones.motivo_para_no_corregir`
    y `transiciones.motivo_para_no_recibir_a_mano` necesitan y que `antes` —ya
    leído antes de intentar el `UPDATE`— no trae: **su pedido**, y si una
    lista posterior ya atendió su producto (ADR 0015). `antes.pedido_sugerido_id`
    viene poblado porque `leer_renglon` usa `_LEER_RENGLON_POR_ID`.

    Devuelve `{"detalle": ...}`, listo para mezclarse en el `content` del
    409. Si esta segunda lectura también falla, se agrega `"que_hacer"`
    —regla 4, ningún `ok: false` se queda sin decir qué hacer— con el TIPO de
    la falla y nunca su texto (regla 5): la escritura ya falló, y este `try`
    solo intenta explicar por qué, nunca reintenta nada.
    """
    if antes is None:
        return {"detalle": motivo_para_no_recibir_a_mano(None, None)}
    try:
        pedido = None
        if antes.pedido_id is not None and antes.pedido_sugerido_id is not None:
            pedido = next(
                (
                    p
                    for p in almacenamiento.pedidos_de_la_lista(
                        negocio, antes.pedido_sugerido_id
                    )
                    if p.pedido_id == antes.pedido_id
                ),
                None,
            )
        if not antes.esta_recibido:
            return {"detalle": motivo_para_no_recibir_a_mano(antes, pedido)}
        atendido_despues = antes.pedido_sugerido_id is not None and (
            antes.propuesto.producto_id
            in almacenamiento.productos_atendidos_despues(
                negocio, antes.pedido_sugerido_id
            )
        )
        motivo = motivo_para_no_corregir(antes, pedido, atendido_despues, piezas)
    except Exception as exc:  # noqa: BLE001 — sin el motivo real, se dice que no se pudo
        log.exception(
            "No se pudo leer por qué no se pudo recibir a mano el renglón %s",
            antes.renglon_id,
        )
        return {
            "detalle": (
                "Esa cifra no se guardó, y no se pudo saber por qué "
                f"({type(exc).__name__}). Vuelve a cargar la página."
            ),
            "que_hacer": _que_hacer(AL_LEER),
        }
    if motivo is None:
        # El `WHERE` ya dijo que no; si la relectura dice que ahora sí se
        # podría, alguien más cambió el renglón en el instante de en medio
        # (la misma carrera que el ADR 0016 ya mide y acepta en otras rutas).
        return {
            "detalle": (
                "Esa cifra ya no se pudo guardar: algo cambió en este renglón "
                "justo antes. Vuelve a cargar la página para ver cómo quedó."
            )
        }
    return {"detalle": motivo}


@app.post("/api/renglon/{renglon_id}/recepcion/a-mano")
def recibir_a_mano(
    renglon_id: int,
    cuerpo: PiezasRecibidas,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Decir cuántas piezas llegaron, **en total** (ticket 27, ADR 0015).

    Las casillas 1, 3 y 5 del ticket en una ruta: cuántas llegaron de un
    renglón, **a mano** —sin propuesta del sistema: lo que nunca va a tener
    una (QuePharma, el 17.7% del catálogo), o la compra de 10 que surtió dos
    pedidos—, firmado con quién y cuándo. Es **firma y nunca permiso** (regla
    3).

    - Si el renglón **viene en camino**, pasa a `recibido` o a `recibido
      parcial` según las piezas. Lo que faltó vuelve en la siguiente lista.
    - Si **ya se recibió**, la cifra se corrige: la segunda factura (6 hoy, el
      resto el jueves → 10), o un error de captura. Solo mientras lo que faltó
      no se haya atendido en una lista posterior; la respuesta avisa que una
      lista ya armada no se recalcula.

    Respuestas: `422` si las piezas no son un entero de 1 en adelante (se dice
    por qué, en español); `409` si el `WHERE` dijo que no; `200` con `ok:
    false` y el **tipo** de la falla si el almacenamiento se cayó (regla 5);
    `200` con la frase de lo que pasa después.
    """
    piezas, motivo = piezas_escritas(cuerpo.piezas)
    if motivo is not None:
        return JSONResponse(status_code=422, content={"ok": False, "detalle": motivo})

    negocio = cargar().negocio
    firma = quien(request)
    try:
        # Se lee ANTES solo para la frase: decir "de 6 a 10" necesita el 6. La
        # decisión es del `WHERE`, no de esta lectura.
        antes = almacenamiento.leer_renglon(negocio, renglon_id)
        renglon = almacenamiento.recibir_a_mano(negocio, renglon_id, piezas, firma)
    except Exception as exc:  # noqa: BLE001 — un borde caído es un hueco
        log.exception("No se pudo recibir a mano el renglón %s", renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo recibir a mano ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if renglon is None:
        log.info(
            "%s quiso decir que del renglón %s de %s llegaron %s piezas y el "
            "WHERE dijo que no.",
            firma,
            renglon_id,
            negocio,
            piezas,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                **_motivo_del_409_a_mano(almacenamiento, negocio, antes, piezas),
            },
        )

    corrigio = antes is not None and antes.esta_recibido
    log.info(
        "%s dijo que del renglón %s (%s) de %s llegaron %s piezas%s: quedó «%s», "
        "sin compra de SICAR (ADR 0015).",
        firma,
        renglon_id,
        renglon.propuesto.descripcion,
        negocio,
        piezas,
        f" (antes decía {antes.piezas_recibidas})" if corrigio else "",
        renglon.estado,
    )
    return {
        "ok": True,
        "renglon_id": renglon.renglon_id,
        "estado": renglon.estado,
        "frase": frase_de_lo_recibido_a_mano(renglon, antes if corrigio else None),
    }


@app.get("/api/pedido-sugerido/{pedido_sugerido_id}/pedido/{pedido_id}/csv")
def exportar_el_pedido(
    pedido_sugerido_id: int,
    pedido_id: int,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Un pedido como CSV, para Excel, el correo o una carpeta (ticket 23).

    **Se arma en memoria cada vez que se pide y no se guarda en ninguna
    parte**: ni en disco, ni en la base, ni en git. Es la cuarta casilla, y es
    también lo que impide que envejezca —un archivo guardado ayer seguiría
    diciendo "borrador" de un pedido que hoy ya se envió—.

    Cuelga de la lista y no solo del pedido, a propósito: con el id de la lista
    alcanzan tres lecturas que **ya existían** —la lista, sus pedidos y sus
    precios— y no hace falta una sentencia nueva que desde la torre no se puede
    probar contra Postgres. Un pedido que no es de esa lista es un 404.

    Las líneas son las de la pantalla de captura (`lo_que_hay_que_capturar`):
    el pedido GUARDADO, con el precio de **ese** proveedor. Todo el porqué del
    formato —la clave como fórmula de texto, el BOM, la coma— está en
    `continental/exportar.py`, medido contra el Excel de la torre.

    Se exporta en cualquiera de los cinco estados, y el archivo dice cuál es en
    su nombre y en su primer renglón: el del borrador sirve para capturar o
    revisar, y el del enviado es el respaldo de lo que se pidió. Ese estado es
    el **calculado** (ADR 0015): lo que llegó se llama `recibido`.

    **Lo que no se sirve es un archivo a medias.** Si los precios no se pueden
    leer, cada línea diría "no se le ha consultado el precio", que sería
    mentira: es un 503 con el tipo de la falla, y el detalle a la bitácora
    (regla 5). Un pedido que se quedó sin renglones es un 409: un archivo con
    solo el encabezado se leería "no se pidió nada", y lo que pasó es que sus
    renglones están en otro pedido.
    """
    negocio = cargar().negocio

    try:
        lista = almacenamiento.leer_por_id(negocio, pedido_sugerido_id)
        pedidos = (
            ()
            if lista is None
            else almacenamiento.pedidos_de_la_lista(negocio, pedido_sugerido_id)
        )
        pedido = next((p for p in pedidos if p.pedido_id == pedido_id), None)
        precios = (
            {}
            if pedido is None
            else almacenamiento.precios_de_la_lista(negocio, pedido_sugerido_id)
        )
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        # Regla 5 de `CLAUDE.md`: el detalle a la bitácora del servidor, nunca
        # al navegador. Un `str(exc)` de SQLAlchemy lleva la cadena de conexión
        # con contraseña.
        log.exception(
            "No se pudo exportar el pedido %s de la lista %s", pedido_id, pedido_sugerido_id
        )
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "detalle": f"no se pudo armar el archivo del pedido ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_LEER),
            },
        )

    if lista is None or pedido is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "detalle": "Ese pedido no está en esa lista. Vuelve a cargar la página.",
            },
        )

    captura = lo_que_hay_que_capturar(pedido, lista.renglones, precios)
    if not captura.hay:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese pedido no tiene renglones que exportar: o se quedó vacío "
                    "al volver a partir, o todos los suyos se descartaron."
                ),
            },
        )

    # EL ESTADO QUE DICE EL ARCHIVO ES EL CALCULADO (ADR 0015): un pedido que
    # ya llegó se baja como `recibido` o `recibido parcial`, igual que la
    # pantalla, aunque la columna siga diciendo `enviado`. `exportar` lo saca
    # de los renglones de la lista con `recepcion.PedidoALaVista`.
    nombre = nombre_del_archivo(pedido, lista.fecha_del_pedido, lista.renglones)
    log.info(
        "Se exportó el pedido %s (%s, %s) de la lista %s como %s: %d renglón(es).",
        pedido.pedido_id,
        pedido.nombre,
        PedidoALaVista.de(pedido, lista.renglones).estado,
        pedido_sugerido_id,
        nombre,
        captura.cuantos,
    )
    return Response(
        content=csv_del_pedido(
            pedido, captura, lista.fecha_del_pedido, lista.renglones
        ),
        media_type=TIPO_DEL_ARCHIVO,
        headers={"Content-Disposition": disposicion_de_descarga(nombre)},
    )


@app.post("/api/renglon/{renglon_id}/capturado")
def marcar_el_renglon_como_capturado(
    renglon_id: int,
    marca: MarcaDeCaptura,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
):
    """Tachar —o destachar— un renglón en la pantalla de captura (ticket 22).

    El modo real de trabajo: el portal del proveedor en una ventana, esta
    pantalla en otra, y el encargado tachando conforme teclea allá. **El avance
    se guarda aquí, en la tabla, y no en el navegador** (ADR 0010): dos
    pestañas del mismo pedido no divergen, cambiar de máquina a la mitad no lo
    pierde, y cada marca dice quién la puso. Es una firma y nunca un permiso
    (regla 3).

    **Devuelve la lista entera**, como `partir` y `enviar`: tachar cambia el
    avance de su pedido —cuántos faltan— y la invitación a enviar cuando se
    tacha el último, y deducir eso en el navegador es justo lo que esta
    pantalla no hace. Cuesta una relectura; `_mover_el_renglon` no sirve aquí
    porque devuelve un renglón suelto y no los pedidos, que es donde vive la
    captura.

    **Tachar no condiciona enviar**, y ésa es la mitad de la quinta casilla que
    se hace mal sola: esta ruta no toca el pedido y `se_puede_enviar` no mira
    la captura. Enviar con cero renglones tachados sigue funcionando igual que
    en el ticket 21.

    Un 409 cuando no había nada que tachar: el renglón no cuelga de un pedido,
    su pedido ya se envió, se descartó, o no es de este negocio. No se
    distinguen desde fuera, igual que en el descarte, y la condición vive en el
    `WHERE` y no en un `if`.
    """
    negocio = cargar().negocio
    firma = quien(request)
    verbo = "tachar" if marca.capturado else "destachar"

    try:
        guardado = almacenamiento.marcar_capturado(
            negocio, renglon_id, marca.capturado, firma
        )
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco
        # Regla 5 de `CLAUDE.md`: el detalle a la bitácora del servidor, nunca
        # al navegador. Un `str(exc)` de SQLAlchemy lleva la cadena de conexión
        # con contraseña.
        log.exception("No se pudo %s el renglón %s", verbo, renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo {verbo} el renglón ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if guardado is None:
        log.info(
            "%s quiso %s el renglón %s de %s y no se pudo: o no está en ningún "
            "pedido, o su pedido ya se envió, o está descartado.",
            firma,
            verbo,
            renglon_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese renglón ya no se puede tachar: o su pedido ya se envió, "
                    "o salió del pedido al volver a partir, o se descartó. "
                    "Vuelve a cargar la página para ver cómo quedó."
                ),
            },
        )

    movido = next(r for r in guardado.renglones if r.renglon_id == renglon_id)
    # Las DOS direcciones van a la bitácora con su firma. La columna guarda solo
    # la última —destachar la borra, ADR 0010—, y ésta es la única huella de
    # que alguien tachó y destachó un renglón a la mitad de la captura.
    log.info(
        "%s acaba de %s el renglón %s (%s) del pedido %s. Es la palabra de una "
        "persona sobre lo que tecleó en el portal: Continental no lo vio.",
        firma,
        verbo,
        renglon_id,
        movido.propuesto.descripcion,
        movido.pedido_id,
    )

    lista_id = guardado.pedido_sugerido_id
    corrida, corrida_fallo = _ultima_corrida(almacenamiento, negocio, lista_id)
    return _como_json(
        guardado,
        _precios_de_la_lista(almacenamiento, negocio, lista_id),
        corrida,
        almacenamiento.pedidos_de_la_lista(negocio, lista_id),
        corrida_fallo=corrida_fallo,
        atendidos_despues=_los_atendidos_despues(almacenamiento, negocio, guardado),
    )


@app.post("/api/renglon/{renglon_id}/precio")
def consultar_el_precio(
    renglon_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
    consultas: RegistroDeConsultas = Depends(obtener_consultas),
):
    """Le pide a Doyle el precio de este renglón en los cuatro proveedores.

    **Contesta de inmediato y la consulta sigue por su cuenta.** Una búsqueda
    tiene un piso medido de ~9 s por proveedor y un techo de 60-90 s: dejar la
    petición HTTP abierta hasta que Doyle termine colgaría la pantalla minuto y
    medio, y una recarga tiraría una visita al portal que ya se hizo. Quien
    espera es un hilo de Continental, que **escribe el precio congelado en
    cuanto llega** — así que cerrar la pestaña no pierde la consulta y la
    siguiente carga de la página la encuentra guardada. El porqué entero, con
    las dos alternativas descartadas, está en `consultas.py`.

    **Un segundo clic no consulta dos veces.** Si ya hay una consulta en vuelo
    para este renglón se devuelve ésa, con `nueva: false`. No es comodidad:
    Doyle abre navegadores de verdad contra los portales con las credenciales
    del dueño, y dos clics nerviosos serían ocho visitas en lugar de cuatro.

    **Se busca por la clave, que es el EAN.** Es lo único que significa lo
    mismo en nuestro catálogo y en el de un proveedor (`CONTEXT.md`), y por eso
    un renglón sin clave no se consulta: se contesta 422 diciendo por qué. Los
    688 artículos sin anaquel y los que el catálogo no conoce caen aquí, y el
    hueco con su motivo es la respuesta honesta — buscar por descripción traería
    el producto de otro y la comparación diría cualquier cosa (ADR 0002).

    Un 409 si el renglón no existe, es de otro negocio, o ya no está `abierto`.
    Lo último es lo que evita molestar a cuatro portales por un renglón que ya
    se descartó o que ya se le pidió a alguien. **Esa comprobación vive aquí y
    no en el `WHERE` del `INSERT`**, y es deliberado: lo que se guarda es un
    hecho del mundo en un instante, no una transición del renglón, así que si
    alguien lo descarta mientras Doyle consulta la lectura se guarda igual — ver
    `almacenamiento.guardar_precios`.

    Es `def` y no `async def` a propósito: los dos bordes son síncronos y así
    FastAPI los corre en su pool de hilos sin bloquear el bucle de eventos.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        renglon = almacenamiento.leer_renglon(negocio, renglon_id)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco, no un 500
        log.exception("No se pudo leer el renglón %s para consultar su precio", renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo leer el renglón ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_LEER),
            },
        )

    if renglon is None or renglon.estado != RENGLON_ABIERTO:
        log.info(
            "%s quiso consultar el precio del renglón %s y no había ninguno "
            "abierto con ese id en %s.",
            firma,
            renglon_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Ese renglón ya no está abierto. Vuelve a cargar la página "
                    "para ver cómo quedó."
                ),
            },
        )

    if not renglon.propuesto.clave:
        log.info(
            "%s quiso consultar el precio del renglón %s (%s) y no tiene clave.",
            firma,
            renglon_id,
            renglon.propuesto.descripcion,
        )
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "detalle": (
                    "Este renglón no tiene código de barras, y el código de "
                    "barras es lo único que significa lo mismo en nuestro "
                    "catálogo y en el del proveedor. Buscarlo por su nombre "
                    "traería el producto de otro. Ponle la clave en SICAR y "
                    "vuelve a intentarlo."
                ),
            },
        )

    tope_seg, cada_seg = ajustes_de_la_consulta()
    consulta, nueva = consultas.pedir(
        renglon_id,
        renglon.propuesto.clave,
        lambda en_curso: consultar_y_congelar(
            en_curso,
            doyle=doyle,
            almacenamiento=almacenamiento,
            registro=consultas,
            negocio=negocio,
            tope_seg=tope_seg,
            cada_seg=cada_seg,
        ),
    )

    if nueva:
        log.info(
            "%s pidió el precio del renglón %s (%s, clave %s) en los cuatro "
            "proveedores.",
            firma,
            renglon_id,
            renglon.propuesto.descripcion,
            renglon.propuesto.clave,
        )
    else:
        log.info(
            "%s volvió a pedir el precio del renglón %s y ya había una consulta "
            "en curso: no se lanzó otra.",
            firma,
            renglon_id,
        )

    # La consulta que se devuelve es la del registro y no la que se acaba de
    # crear: con el lanzador síncrono del suite —y con un Doyle muy rápido— ya
    # terminó para cuando se llega aquí, y devolver la de antes diría "en
    # curso" sobre algo que ya está guardado.
    return _consulta_como_json(
        consultas.de(renglon_id) or consulta,
        nueva,
        _precios_del_renglon(almacenamiento, negocio, renglon_id),
        # El renglón ya se leyó arriba, así que el ahorro se calcula con la
        # cantidad de verdad sin una consulta más.
        cantidad=renglon.cantidad_a_pedir,
    )


@app.post("/api/pedido-sugerido/{pedido_sugerido_id}/completar")
def completar_lo_que_falta(
    pedido_sugerido_id: int,
    request: Request,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
    consultas: RegistroDeConsultas = Depends(obtener_consultas),
):
    """Vuelve a consultar **solo los precios que faltan**, sin lanzar el lote.

    La segunda casilla del ticket 19, y la cara: cada renglón que entre aquí
    son cuatro visitas a portales ajenos con las credenciales del dueño, ~9 s
    por proveedor. Por eso *faltar* es más estrecho que *estar incompleto*, y
    la definición vive en una función pura con su tabla de casos
    (`faltantes.por_que_falta`). En una línea: **falta lo que volver a
    preguntar puede cambiar**.

    Quién entra:

    - los que **no tienen ni una lectura** —el lote no llegó, o nadie los
      consultó—, y
    - los que se consultaron, **no dieron ni un precio**, y tienen al menos un
      hueco de los tres que se arreglan reintentando (`el portal no contestó`,
      `la sesión caducó`, `no alcanzó el tiempo`).

    Quién **no**, y cada ausencia es una decisión: un renglón **sin EAN** (se
    arregla en SICAR, no apretando esto), uno con **al menos un precio** —esas
    cuatro visitas ganarían como mucho una cotización más, y eso es justo lo
    que el ticket prohíbe con *"sin volver a visitar portales por lo que ya
    tiene precio"*—, y uno cuyos huecos son todos **definitivos**
    (`sin resultados`, `no empareja`, `varios resultados`, `precio ilegible`,
    `no se sabe leer la página`): mañana contestarían lo mismo. Meterlos
    convertiría este botón en el lote completo con otro nombre.

    **Contesta de inmediato y el trabajo sigue en un hilo**, igual que el botón
    de un solo renglón, y por la misma razón: doce renglones son dos minutos
    largos y la pantalla no se puede quedar colgada. La diferencia es que aquí
    se lanza **un** hilo para todos y se consulta **uno tras otro**: un hilo
    por faltante serían doce búsquedas simultáneas, que es exactamente lo que
    le impide a Doyle reutilizar el navegador que tenga abierto (su ADR 0008).

    **No lanza dos veces lo mismo.** Cada renglón se aparta en su turno dentro
    del candado del registro (`consultas.apartar`), así que un segundo clic
    —o la otra pestaña del mostrador— se salta los que ya vienen en camino en
    vez de duplicar la visita.

    Solo sobre una lista **abierta**: volver a consultar una cerrada sería
    molestar a cuatro portales para cambiar un dato que ya no decide nada.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        guardado = almacenamiento.leer_por_id(negocio, pedido_sugerido_id)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco, no un 500
        log.exception("No se pudo leer la lista %s para completarla", pedido_sugerido_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo leer la lista ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_LEER),
            },
        )

    if guardado is None or guardado.estado != ABIERTO:
        log.info(
            "%s quiso completar los precios de la lista %s y no había ninguna "
            "abierta con ese id en %s.",
            firma,
            pedido_sugerido_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detalle": (
                    "Esa lista ya no está abierta. Vuelve a cargar la página "
                    "para ver cómo quedó."
                ),
            },
        )

    por_renglon = _precios_de_la_lista(almacenamiento, negocio, pedido_sugerido_id)
    if por_renglon is None:
        # Sin poder leer lo congelado no se sabe qué falta, y "no se sabe" no
        # se atiende preguntándole a los cuatro portales por la lista entera
        # (regla 4): se dice.
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": (
                    "no se pudieron leer los precios guardados, así que no se "
                    "sabe cuáles faltan"
                ),
                "que_hacer": _que_hacer(AL_LEER),
            },
        )

    faltantes = elegir_los_faltantes(
        guardado.por_repartir,
        {
            r.renglon_id: comparar(
                por_renglon.get(r.renglon_id, ()), r.cantidad_a_pedir
            )
            for r in guardado.por_repartir
        },
    )

    if not faltantes:
        log.info(
            "%s pidió completar los precios de la lista %s y no falta ninguno.",
            firma,
            pedido_sugerido_id,
        )
        return {
            "ok": True,
            "lanzados": 0,
            "faltantes": faltantes_como_json(faltantes),
            "detalle": "No falta ningún precio que volver a consultar.",
        }

    tope_seg, cada_seg = ajustes_de_la_consulta()
    tope_total_seg = tope_del_completado_segundos()
    # El tope se arma AQUÍ y entra como predicado, no se calcula dentro: la
    # política de cuánto puede durar el completado es de esta ruta, que es
    # quien lee el YAML, y `consultar_en_fila` se queda sin una sola constante
    # de tiempo. El reloj es el MONÓTONO: no es un instante, es una duración.
    arranque = time.monotonic()

    log.info(
        "%s pidió completar los precios de la lista %s: %d renglón(es) "
        "faltantes (%d sin una sola lectura), con un tope de %.0f min.",
        firma,
        pedido_sugerido_id,
        len(faltantes),
        sum(1 for f in faltantes if f.motivo == NUNCA_SE_CONSULTO),
        tope_total_seg / 60.0,
    )

    consultas.lanzar(
        lambda: consultar_en_fila(
            [(f.renglon_id, f.clave) for f in faltantes],
            doyle=doyle,
            almacenamiento=almacenamiento,
            registro=consultas,
            negocio=negocio,
            tope_seg=tope_seg,
            cada_seg=cada_seg,
            se_acabo=lambda: time.monotonic() - arranque >= tope_total_seg,
        )
    )

    return {
        "ok": True,
        "lanzados": len(faltantes),
        # La cola que se lanzó, para que la pantalla marque esos renglones como
        # "consultando" sin adivinar cuáles eran. Es la MISMA lista que se le
        # pasó al hilo, no una segunda manera de calcularla.
        "faltantes": faltantes_como_json(faltantes),
        "tope_minutos": round(tope_total_seg / 60.0, 1),
    }


@app.get("/api/renglon/{renglon_id}/precio")
def precio_del_renglon(
    renglon_id: int,
    almacenamiento: AlmacenamientoDelPedido = Depends(obtener_almacenamiento),
    consultas: RegistroDeConsultas = Depends(obtener_consultas),
):
    """Cómo va la consulta y **qué hay congelado**. Es lo que sondea la pantalla.

    Las dos cosas en una respuesta a propósito: separarlas obligaría al
    navegador a hacer dos llamadas en dos momentos distintos y a decidir él cuál
    tiene razón cuando no coincidan —"terminada" con los precios de antes, o
    "en curso" con los de después—. Aquí el estado y lo guardado salen de la
    misma lectura.

    Lo congelado sale de la **tabla** y no de lo que el hilo recuerde: si
    Continental se reinició a media consulta, el estado se perdió y los precios
    que ya se habían escrito siguen ahí. Eso es lo que hace que recargar la
    página no pierda nada.
    """
    negocio = cargar().negocio
    return _consulta_como_json(
        consultas.de(renglon_id),
        nueva=False,
        precios=_precios_del_renglon(almacenamiento, negocio, renglon_id),
        cantidad=_cantidad_a_pedir(almacenamiento, negocio, renglon_id),
    )


# ------------------------------------------ la sesión caducada (ticket 19)
#
# **Continental no abre un navegador aquí, y no podría** (regla 1 de
# `CLAUDE.md`, ADR 0001). Lo que hace es pedírselo a Doyle por HTTP, que es
# literalmente lo que la regla manda: *"si una pantalla necesita un dato de un
# portal de proveedor, se lo pide a Doyle"*. El navegador lo abre Doyle, **en
# la máquina donde Doyle corre**, y quien teclea la contraseña es una persona.
#
# QUÉ PASA DEL OTRO LADO Y QUÉ NO, dicho con precisión porque es la mitad que
# este repo no controla (ADR 0001 de Doyle):
#
# - `abrir` deja una ventana de Chrome **visible** esperando. Vuelve de
#   inmediato y **la sesión todavía no sirve**.
# - La persona teclea usuario y contraseña EN ESA VENTANA. Eso no se puede
#   automatizar y no se quiere: son las credenciales del dueño.
# - `confirmar` le dice a Doyle que ya entró. Doyle exporta las cookies
#   **antes** de cerrar el navegador —Chrome tira las de sesión al cerrarse y
#   LEVIC quedaría sin sesión aunque alguien acabara de entrar (ADR 0006 de
#   Doyle)— y deja el marcador.
#
# Así que desde Continental se aprietan los dos botones sin cambiar de
# aplicación, **y aun así hace falta estar frente a la máquina de Doyle** para
# la parte de en medio. Hoy Doyle corre en la torre y Continental va a atlas:
# hasta que Doyle se mude con su visor remoto sobre Xvfb (su ADR 0008, sin
# hacer), la ventana se abriría en una máquina donde no hay nadie sentado. Eso
# no lo arregla esta ruta y no se disimula: la pantalla lo dice.


@app.post("/api/sesion/{proveedor}/abrir")
def abrir_la_sesion(
    proveedor: str,
    request: Request,
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
):
    """Le pide a Doyle que abra el navegador del login de ese proveedor.

    Es el botón de la tercera casilla del ticket 19 — *"si una sesión caducó,
    la pantalla lo dice con el botón que la abre"*—, y **lo que devuelve no es
    una sesión abierta**: es una ventana esperando a que alguien teclee. Se
    dice con esas palabras, porque un botón que contesta "listo" sobre una
    sesión que sigue caducada es la falla silenciosa que la regla 4 prohíbe.

    A quién se le ofrece el botón no lo decide esta ruta: sale de las lecturas
    congeladas con motivo `la sesión caducó` (`sesiones_caducadas` de la carga
    de la lista). **No de `GET /api/sesiones` de Doyle**, y eso es deliberado:
    el `guardada` de Doyle solo dice que alguien confirmó una alguna vez, y el
    2026-09-19 los cuatro decían `guardada` con las cuatro caducadas. Lo que
    demuestra que una sesión no sirve es un portal que mandó al login.

    Un Doyle apagado sale como hueco con su motivo y no como 500, igual que
    todo lo demás que depende de él. El motivo es el **tipo** de la falla y
    nunca su texto (regla 5).
    """
    firma = quien(request)
    try:
        abriendose = doyle.abrir_sesion(proveedor)
    except Exception as exc:  # noqa: BLE001 — Doyle caído es un hueco, no un 500
        log.exception("Doyle no pudo abrir la sesión de %s", proveedor)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": (
                    f"Doyle no pudo abrir la sesión de "
                    f"{nombre_del_proveedor(proveedor)} ({type(exc).__name__}). "
                    "Mira si está encendido."
                ),
                "que_hacer": _que_hacer(DOYLE),
            },
        )

    log.info(
        "%s pidió abrir la sesión de %s en Doyle%s.",
        firma,
        proveedor,
        " (ya había una ventana esperando)" if abriendose.ya_abierta else "",
    )
    return {
        "ok": True,
        "proveedor": proveedor,
        "nombre": nombre_del_proveedor(proveedor),
        "ya_abierta": abriendose.ya_abierta,
        "detalle": (
            "Ya había una ventana de ese portal esperando: es la misma, no se "
            "abrió otra."
            if abriendose.ya_abierta
            else "Doyle abrió el navegador del portal."
        ),
        # LO QUE FALTA, DICHO. Sin esto el botón parecería haber terminado el
        # trabajo, y lo que hizo fue empezarlo.
        "siguiente": (
            "Entra con el usuario y la contraseña EN LA VENTANA QUE SE ABRIÓ, "
            "en la máquina donde corre Doyle, y vuelve aquí a darle a «Ya "
            "entré». Hasta entonces la sesión sigue caducada."
        ),
    }


@app.post("/api/sesion/{proveedor}/confirmar")
def confirmar_la_sesion(
    proveedor: str,
    request: Request,
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
):
    """La otra mitad: la persona ya entró, que Doyle guarde las cookies.

    Sin esto, abrir el navegador no deja nada: Chrome tira las cookies de
    sesión al cerrarse. Doyle las exporta **antes** de cerrar y por eso hacen
    falta las dos peticiones (su ADR 0006).

    `todavia_parece_login` es el aviso honesto de Doyle —se confirmó y la
    página seguía viéndose como un login— y **viaja hasta la pantalla**: es la
    diferencia entre "ya está" y "vuelve a intentarlo", y esconderlo dejaría al
    encargado creyendo que abrió una sesión que no abrió. Es exactamente la
    trampa del hilo abierto 1 de `HANDOVER.md`, donde los cuatro proveedores
    decían `guardada` sin servir ninguno.
    """
    firma = quien(request)
    try:
        confirmada = doyle.confirmar_sesion(proveedor)
    except Exception as exc:  # noqa: BLE001 — Doyle caído es un hueco, no un 500
        log.exception("Doyle no pudo confirmar la sesión de %s", proveedor)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": (
                    f"Doyle no pudo guardar la sesión de "
                    f"{nombre_del_proveedor(proveedor)} ({type(exc).__name__}). "
                    "Puede que la ventana se cerrara antes de confirmar: "
                    "vuelve a darle a «Abrir sesión»."
                ),
                "que_hacer": _que_hacer(DOYLE),
            },
        )

    log.info(
        "%s confirmó la sesión de %s en Doyle%s.",
        firma,
        proveedor,
        " — Doyle avisa que la página SEGUÍA viéndose como un login"
        if confirmada.todavia_parece_login
        else "",
    )
    return {
        "ok": True,
        "proveedor": proveedor,
        "nombre": nombre_del_proveedor(proveedor),
        "todavia_parece_login": confirmada.todavia_parece_login,
        "detalle": (
            "Doyle guardó la sesión, pero la página SEGUÍA viéndose como un "
            "login. Puede ser que la redirección no hubiera terminado; si el "
            "siguiente precio vuelve a decir «la sesión caducó», ábrela otra "
            "vez."
            if confirmada.todavia_parece_login
            else (
                "Sesión guardada. Ya se le puede volver a consultar el precio "
                "a ese proveedor."
            )
        ),
    }


def _cantidad_a_pedir(almacenamiento, negocio: str, renglon_id: int) -> int | None:
    """Las piezas que se van a pedir de ese renglón, o `None` si no se pudieron leer.

    Es una lectura de una sola fila por su id, y se paga por sondeo porque el
    ahorro **tiene que ir multiplicado por la cantidad que de verdad se va a
    pedir**: si alguien corrigió el renglón a diez piezas mientras Doyle
    consultaba, un ahorro calculado sobre las tres propuestas sería una cifra
    que no corresponde a la compra que está por hacerse.

    `None` cuando el almacenamiento no contesta, y no una excepción hacia
    arriba: el precio congelado y el ganador siguen siendo información aunque la
    cantidad no se sepa, y `calcular_ahorro` ya sabe decir el ahorro por pieza y
    callar el total con su motivo. La falla entera queda en la bitácora; al
    navegador no viaja nada (regla 5 de `CLAUDE.md`).
    """
    try:
        renglon = almacenamiento.leer_renglon(negocio, renglon_id)
    except Exception:  # noqa: BLE001 — sin la cantidad el resto sigue sirviendo
        log.exception(
            "No se pudo releer el renglón %s para el ahorro de su comparación",
            renglon_id,
        )
        return None
    return None if renglon is None else renglon.cantidad_a_pedir


@dataclasses.dataclass(frozen=True)
class _SinLeer:
    """Una lectura que falló, con su motivo corto (el tipo, nunca el texto)."""

    detalle: str


def _precios_del_renglon(almacenamiento, negocio: str, renglon_id: int):
    """Lo congelado de un renglón, o `_SinLeer` si el almacenamiento no contestó.

    No una excepción hacia arriba: el estado de la consulta sigue siendo
    información aunque la tabla no conteste, y la falla ya quedó entera en la
    bitácora.

    **Hasta el ticket 29 devolvía una tupla vacía**, y eso era la falla
    silenciosa que la regla 4 prohíbe: la pantalla la pintaba encima de los
    precios que ya tenía, y un renglón con tres cotizaciones pasaba a "sin
    consultar" porque una lectura no contestó.
    """
    try:
        return almacenamiento.precios_del_renglon(negocio, renglon_id)
    except Exception as exc:  # noqa: BLE001 — leer precios caído no puede tumbar la pantalla
        log.exception("No se pudieron leer los precios del renglón %s", renglon_id)
        return _SinLeer(f"no se pudieron leer los precios guardados ({type(exc).__name__})")


def _precios_de_la_lista(almacenamiento, negocio: str, pedido_sugerido_id: int):
    """Lo congelado de **toda** la lista, o `None` si el almacenamiento no contestó.

    `None` y no `{}`, y la diferencia importa: un diccionario vacío quiere decir
    "ningún renglón tiene precio", que es un dato de verdad y el que hace decir
    al conteo *los 18 están sin comparar*. Una lectura que falló no dice eso
    —no dice nada— y afirmarlo sería inventarse un número, que es exactamente
    la falla silenciosa que la regla 4 de `CLAUDE.md` prohíbe. Quien recibe el
    `None` omite el conteo y la pantalla se queda con el que ya tenía.

    Una sola consulta para la lista entera, por lo mismo que en la carga: una
    por renglón leería en momentos distintos y la tabla podría dejar de
    coincidir consigo misma mientras alguien la trabaja.
    """
    try:
        return almacenamiento.precios_de_la_lista(negocio, pedido_sugerido_id)
    except Exception:  # noqa: BLE001 — leer precios caído no puede tumbar la pantalla
        log.exception(
            "No se pudieron leer los precios congelados de la lista %s",
            pedido_sugerido_id,
        )
        return None


def _ultima_corrida(
    almacenamiento, negocio: str, pedido_sugerido_id: int
) -> tuple[CorridaDelLote | None, bool]:
    """Cómo le fue al lote sobre esta lista, o `None` si no hay fila (ADR 0007).

    **`None` es un dato y no un hueco**, y esa es la mitad del ticket 19 que se
    ve al cargar: quiere decir *"el lote no corrió sobre esta lista"*, que es
    lo que hasta hoy no se distinguía de *"nadie consultó este renglón"* (hilo
    abierto 10 de `HANDOVER.md`). La diferencia entre encontrar la fila y no
    encontrarla es exactamente la diferencia entre los dos.

    Devuelve `(corrida, fallo)`. **Hasta la enmienda del 2026-09-21** una
    lectura que fallaba se veía idéntica a "no hay fila" —las dos como
    `None`— y las dos se leían igual: "el lote no corrió", en rojo. Desde la
    decisión del dueño, ese "no hay fila" se abre en dos colores —ámbar si la
    lista es más nueva que la última corrida programada, rojo si no— y una
    LECTURA que se cae no puede entrar a esa cuenta: de ahí no se sabe nada,
    ni siquiera si hubo o no una corrida. Por eso `fallo` viaja aparte, en
    `true` exactamente cuando la EXCEPCIÓN —no la ausencia de fila— es la
    causa, y quien arma la respuesta (`_corrida_ausente_como_json`) lo lee
    para no comparar fechas sobre un dato que no se pudo leer.

    La alternativa a atrapar la falla sería tumbar la lista entera porque una
    consulta de una fila no contestó, y una lista sin precios todavía sirve
    para pedir. La falla queda entera en la bitácora (regla 5: el tipo, nunca
    el texto de la excepción).

    Es **una** consulta más por carga, de una fila, con su índice
    `ix_corrida_ultima`.
    """
    try:
        return almacenamiento.ultima_corrida(negocio, pedido_sugerido_id), False
    except Exception:  # noqa: BLE001 — la bitácora caída no tumba la lista
        log.exception(
            "No se pudo leer la última corrida del lote de la lista %s.",
            pedido_sugerido_id,
        )
        return None, True


def _consulta_como_json(
    consulta, nueva: bool, precios, cantidad: int | None = None
) -> dict:
    """El estado de una consulta más lo congelado, como la pantalla lo lee.

    `ok` es cierto también cuando la consulta terminó mal, y eso no es
    contradictorio: la petición se atendió. Lo que salió mal se dice en `estado`
    y en `detalle`, que es lo que la pantalla pinta como hueco con su motivo.
    Un `ok: false` aquí haría que el JavaScript lo tratara como "no se pudo
    preguntar", que es otra cosa.

    `precios` puede ser `_SinLeer` (ticket 29): la tabla no contestó. Entonces
    `precios` y `comparacion` viajan `null` —no vacíos— y `precios_sin_leer`
    dice por qué y qué hacer.
    """
    sin_leer = isinstance(precios, _SinLeer)
    return {
        "ok": True,
        "nueva": nueva,
        "consulta": (
            None
            if consulta is None
            else {
                "estado": consulta.estado,
                "en_curso": consulta.en_curso,
                "clave": consulta.clave,
                "job_id": consulta.job_id,
                "pedida_en": consulta.pedida_en.isoformat(),
                "terminada_en": (
                    consulta.terminada_en.isoformat()
                    if consulta.terminada_en
                    else None
                ),
                "detalle": consulta.detalle,
            }
        ),
        "precios": None if sin_leer else lecturas_como_json(precios),
        # La comparación viaja también por aquí y no solo dentro del renglón de
        # la lista: cuando el botón vuelve, la pantalla sustituye la celda
        # entera con lo que llegó. Si tuviera que recalcular el ganador ahí, la
        # regla viviría en dos lugares y uno de los dos no tendría pruebas.
        "comparacion": (
            None if sin_leer else comparacion_como_json(comparar(precios, cantidad))
        ),
        # `null` en los dos de arriba quiere decir "no se pudieron leer", no "no
        # hay": la pantalla conserva lo que ya tenía pintado y dice esto.
        "precios_sin_leer": (
            {"detalle": precios.detalle, "que_hacer": _que_hacer(AL_LEER)}
            if sin_leer
            else None
        ),
    }


def _motivo_del_409_al_editar(
    almacenamiento: AlmacenamientoDelPedido | None,
    negocio: str,
    antes: RenglonGuardado | None,
    accion: str,
    choque: str,
) -> dict:
    """El motivo real del 409 de `_mover_el_renglon`, no el texto fijo de antes.

    Hasta el 2026-09-22 (paso 2 de la revisión de arquitectura) `choque` era
    lo único que el 409 decía, igual para "el renglón no existe", "ya está en
    tránsito" y "la lista se cerró". Ahora se relee lo que
    `transiciones.motivo_para_no_editar` necesita y que `antes` —leído justo
    **antes** de intentar el `UPDATE`, el mismo patrón que
    `_motivo_del_409_a_mano` usa con `recibir_a_mano`— no trae por sí solo: su
    lista. `antes.pedido_sugerido_id` viene poblado porque `leer_renglon` usa
    `_LEER_RENGLON_POR_ID`.

    Devuelve `{"detalle": ...}`, listo para mezclarse en el `content` del 409
    —el mismo contrato que `_motivo_del_409_a_mano`—. `choque` se queda como
    red de seguridad —regla 4, un texto vago es mejor que ninguno— para
    cuando `almacenamiento` es `None` o `antes` es `None` porque el renglón
    no existe en este negocio.

    **Si la relectura misma falla**, se agrega `"que_hacer"` —regla 4,
    ningún `ok: false` se queda sin decir qué hacer (lo cazó
    `test_fallas.test_ninguna_falla_de_ningun_borde_lleva_detalles_al_navegador`
    al agregar esta relectura: antes de esa prueba, `choque` a secas parecía
    inofensivo aquí también)— con el TIPO de la falla y nunca su texto (regla
    5): la escritura ya falló, y este `try` solo intenta explicar por qué,
    nunca reintenta nada.
    """
    if almacenamiento is None or antes is None:
        return {"detalle": choque}
    try:
        lista = (
            almacenamiento.leer_por_id(negocio, antes.pedido_sugerido_id)
            if antes.pedido_sugerido_id is not None
            else None
        )
        motivo = motivo_para_no_editar(antes, lista, accion)
    except Exception as exc:  # noqa: BLE001 — sin el motivo real, se dice que no se pudo
        log.exception(
            "No se pudo leer por qué no se pudo %s el renglón %s", accion, antes.renglon_id
        )
        return {
            "detalle": (
                "Ese renglón no se pudo mover, y no se pudo saber por qué "
                f"({type(exc).__name__}). Vuelve a cargar la página."
            ),
            "que_hacer": _que_hacer(AL_LEER),
        }
    if motivo is None:
        # El `WHERE` ya dijo que no; si la relectura dice que ahora sí se
        # podría, alguien más cambió el renglón en el instante de en medio
        # (la misma carrera que el ADR 0016 ya mide y acepta en otras rutas).
        return {
            "detalle": (
                "Ese renglón ya no se pudo mover: algo cambió en él justo "
                "antes. Vuelve a cargar la página para ver cómo quedó."
            )
        }
    return {"detalle": motivo}


def _mover_el_renglon(
    renglon_id: int,
    request: Request,
    mover,
    verbo: str,
    choque: str,
    accion: str,
    nota: str = "",
    almacenamiento: AlmacenamientoDelPedido | None = None,
):
    """Lo que las cuatro rutas que mueven un renglón comparten entero.

    `almacenamiento` entra para releer los **precios congelados** del
    renglón movido (ticket 12) y, desde el 2026-09-22, el renglón **antes**
    de intentar moverlo — lo que el 409 necesita para decir el motivo real en
    vez de `choque`. Sigue siendo opcional por comodidad de quien llama y no
    por duda: sin él, el renglón que vuelve tendría la misma forma pero con la
    lista de precios vacía, y la pantalla —que sustituye el renglón entero por
    el que llega— borraría de la vista precios que siguen guardados. Un dato
    que desaparece de la pantalla sin desaparecer de la tabla es peor que uno
    que nunca estuvo: nadie sabe cuál de los dos creer.

    Cambia la operación y cambia el texto; el resto —la firma, el `try` que
    convierte una base caída en un hueco con su motivo, el 409 con el motivo
    real y la respuesta con los conteos— es el mismo, y escribirlo cuatro
    veces sería cuatro oportunidades de que una deje de cumplir la regla 5.

    `verbo` trae su propio sustantivo —"descartar el renglón", "ajustar la
    cantidad del renglón"— en vez de dejarlo en la plantilla: pegarle "el
    renglón" a "ajustar la cantidad de" daba "de el renglón", y una bitácora
    que se lee mal se deja de leer.

    `accion` es una de `transiciones.ACCIONES_DE_EDICION`
    (`"descartar"`, `"devolver_a_abierto"`, `"ajustar_la_cantidad"`,
    `"elegir_proveedor"`): la que `transiciones.motivo_para_no_editar` va a
    juzgar si el `mover` que se intentó no movió nada.

    `nota` es lo que solo esa operación sabe y la bitácora necesita. Hoy la usa
    el ajuste, para dejar escrita **cada** cantidad que alguien tecleó: la
    columna guarda la última, y sin esto no habría forma de ver que se puso 100
    y se corrigió a 10 un minuto después.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        # Se lee ANTES de intentar, en la misma línea que `recibir_a_mano`
        # (ver `_motivo_del_409_a_mano`): si el `UPDATE` contesta cero filas,
        # es lo único que permite decir POR QUÉ. La decisión sigue siendo del
        # `WHERE` y no de esta lectura — el renglón pudo cambiar en el
        # instante de en medio, y eso se dice aparte si pasa.
        antes = (
            None if almacenamiento is None else almacenamiento.leer_renglon(negocio, renglon_id)
        )
        guardado = mover(negocio, firma)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco, no un 500
        log.exception("No se pudo %s %s", verbo, renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo {verbo} ({type(exc).__name__})",
                "que_hacer": _que_hacer(AL_GUARDAR),
            },
        )

    if guardado is None:
        log.info(
            "%s quiso %s %s y no había ninguno en el estado que lo permite en %s.",
            firma,
            verbo,
            renglon_id,
            negocio,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                **_motivo_del_409_al_editar(almacenamiento, negocio, antes, accion, choque),
            },
        )

    movido = next(r for r in guardado.renglones if r.renglon_id == renglon_id)
    # Una sola lectura para las dos cosas: los precios del renglón que se movió
    # —para que la pantalla no borre de la vista precios que siguen guardados—
    # y los de la lista entera, que son los que vuelven a contar cuántos
    # renglones quedaron sin comparar. Descartar y devolver **cambian ese
    # número**: sacan y meten renglones de la lista de trabajo, que es sobre la
    # que se cuenta. Antes del ticket 15 aquí se leía un solo renglón; leer la
    # lista cuesta la misma consulta y deja el número de arriba al día, en vez
    # de un conteo que envejece con cada clic.
    por_renglon = (
        None
        if almacenamiento is None
        else _precios_de_la_lista(almacenamiento, negocio, guardado.pedido_sugerido_id)
    )
    precios = () if por_renglon is None else por_renglon.get(renglon_id, ())
    log.info(
        "%s acaba de %s %s (%s) de la lista %s.%s Van %d descartado(s) de %d "
        "renglones.",
        firma,
        verbo,
        renglon_id,
        movido.propuesto.descripcion,
        guardado.pedido_sugerido_id,
        f" {nota}" if nota else "",
        guardado.descartados,
        len(guardado.renglones),
    )
    return {
        "ok": True,
        "pedido_sugerido_id": guardado.pedido_sugerido_id,
        "renglon": _renglon_como_json(
            movido,
            precios,
            ventana=guardado.ventana,
            # `lista=guardado`: la relectura de arriba, ya con el renglón en
            # su estado nuevo — es de lo que `se_puede_editar` y
            # `se_puede_devolver_a_abierto` necesitan saber si sigue abierta.
            lista=guardado,
            # `atendidos_despues=frozenset()` está bien aquí y no es el
            # descuido que tenía `_como_json` (ver su docstring): las cuatro
            # rutas que llaman a `_mover_el_renglon` —descartar, devolver,
            # ajustar, elegir proveedor— solo mueven renglones `abierto` o
            # `descartado` (el `WHERE`, ahora también en
            # `transiciones.motivo_para_no_editar`), así que `movido` NUNCA
            # está `recibido` y `se_puede_corregir` va a valer `False` por esa
            # razón sola, sin que `atendidos_despues` cambie nada. Leerlo de
            # verdad costaría una consulta más por clic para un valor que no
            # se usa.
            atendidos_despues=frozenset(),
        ),
        # Los conteos salen del servidor y no de una cuenta del navegador: dos
        # pestañas abiertas en el mostrador bastan para que un número que el
        # JavaScript va sumando se separe de la verdad, y ese número es el que
        # el ADR 0002 va a mirar después de un mes.
        "descartados": guardado.descartados,
        "de_trabajo": len(guardado.de_trabajo),
        "tiene_renglones_sin_atender": guardado.tiene_renglones_sin_atender,
        # El conteo de huecos, recalculado. Va `null` cuando no se pudieron
        # leer los precios: la pantalla se queda entonces con el que tenía, que
        # es viejo pero verdadero, en vez de estrenar uno inventado.
        "conteo_de_precios": (
            None
            if por_renglon is None
            else conteo_como_json(
                contar_la_lista(
                    comparar(por_renglon.get(r.renglon_id, ()), r.cantidad_a_pedir)
                    for r in guardado.por_repartir
                )
            )
        ),
        # LOS FALTANTES, RECALCULADOS, por la misma razón que el conteo de
        # arriba y con la misma lectura: descartar saca un renglón de la cola
        # del botón de completar y devolver lo mete. Un botón que siga
        # ofreciendo "completar 12" después de descartar cuatro de esos doce
        # mandaría a molestar a cuatro portales por mercancía que alguien ya
        # decidió no pedir.
        #
        # `null` cuando no se pudieron leer los precios: la pantalla se queda
        # con el que tenía, viejo pero verdadero.
        "faltantes": (
            None
            if por_renglon is None
            else faltantes_como_json(
                elegir_los_faltantes(
                    guardado.por_repartir,
                    {
                        r.renglon_id: comparar(
                            por_renglon.get(r.renglon_id, ()), r.cantidad_a_pedir
                        )
                        for r in guardado.por_repartir
                    },
                )
            )
        ),
        # EN QUÉ SE PARTIRÍA LA LISTA AHORA MISMO, recalculada, por la misma
        # razón que el conteo y los faltantes y con la misma lectura: las
        # cuatro operaciones que pasan por aquí la mueven. Elegir proveedor la
        # mueve de la manera más obvia -- el renglón cambia de pedido--, pero
        # descartar y ajustar también: uno saca un renglón de un pedido y el
        # otro le cambia el importe. Una vista previa que se quedara vieja
        # mandaría a apretar "Partir" sobre números que ya no son.
        #
        #  cuando no se pudieron leer los precios: la pantalla se queda
        # con la que tenía, vieja pero verdadera.
        "particion": (
            None
            if por_renglon is None
            else particion_como_json(
                partir(
                    guardado.por_repartir,
                    {
                        r.renglon_id: comparar(
                            por_renglon.get(r.renglon_id, ()), r.cantidad_a_pedir
                        )
                        for r in guardado.por_repartir
                    },
                    por_renglon,
                    puente_configurado(),
                )
            )
        ),
    }


def _armar(
    almacen: LecturaDelAlmacen, ventana: Ventana, memoria: MemoriaDeLoPedido
):
    """Las dos lecturas y el cálculo. Solo corre cuando la lista **no** existía.

    El cuerpo vive en `sugerido.armar_la_lista` desde el ticket 18, y no por
    gusto de mover código: desde ese ticket hay **dos** cosas que arman la
    lista del mismo día —esta pantalla cuando alguien la carga, y el lote
    nocturno a las 22:00—. Con dos copias, el día que una cambie el lote habría
    consultado precios de una lista y la pantalla mostraría otra, sin un solo
    error que ver. Todo el porqué de las dos ventanas, del rango unión y del
    recorte en memoria está en el docstring de allá.

    Esto se queda como la puerta de esta ruta: lee las reglas de clasificación
    del YAML —`cargar()` está cacheado, así que no relee el archivo por
    petición— y se las pasa hacia adentro, porque el cálculo no abre archivos
    igual que no mira el reloj.

    `memoria` es lo ya pedido (ticket 24): lo que viene en camino no se
    propone, y lo que ya llegó trae lo que se vendió mientras venía.
    """
    return armar_la_lista(almacen, ventana, memoria, reglas=reglas_configuradas())


def _como_json(
    guardado: PedidoSugeridoGuardado,
    precios: dict | None = None,
    corrida: CorridaDelLote | None = None,
    pedidos: tuple | None = None,
    en_camino: dict | None = None,
    ya_en_camino: dict | None = None,
    recepcion: dict | None = None,
    con_propuesta: frozenset[int] = frozenset(),
    aun_faltan: frozenset[int] | None = None,
    reapertura: dict | None = None,
    corrida_fallo: bool = False,
    *,
    atendidos_despues: frozenset[int],
) -> dict:
    """La lista guardada, como la pantalla la lee.

    `corrida` es cómo le fue al lote sobre **esta** lista, o `None` si no hay
    fila. Viaja en la misma respuesta que la lista y por la misma razón que los
    precios: es lo que convierte *"nadie lo consultó"* en *"al lote se le acabó
    el tiempo antes de llegar a éste"*, y pedirla aparte serían dos lecturas en
    dos momentos que podrían no coincidir. De ella salen tres cosas de esta
    respuesta —la frase de arriba, el motivo de cada renglón sin lectura, y
    nada más— y **la regla que las decide es una función pura**
    (`faltantes.por_que_no_hay_lectura`), no un `if` del JavaScript.

    `precios` es lo congelado por renglón, indexado por `renglon_id`. Va por
    omisión en `None` y no en `{}` para que los dos caminos que devuelven una
    lista sin precios —cerrar la lista, que no los toca— no tengan que
    inventarse un diccionario vacío.

    **Cuando `corrida` es `None`**, la respuesta trae además
    `corrida_ausente` (decisión del dueño, 2026-09-21): ámbar si esta lista
    —`guardado.armado_en`— es más nueva que la última corrida programada del
    lote, rojo si ya debía haber pasado y no dejó fila, o si `corrida_fallo`
    dice que la LECTURA misma se cayó. `corrida_fallo` viene de
    `_ultima_corrida`, no se adivina aquí.

    `fecha_de_ventas` se conserva con ese nombre y apunta a
    `ventas_consideradas_hasta`: es lo que la pantalla ya pinta como "Ventas
    del ...", y renombrarlo no agregaría nada. Al lado van los dos extremos de
    la ventana con su nombre completo, que es lo que se audita.

    `armado_en` y `cerrado_en` viajan en ISO **con zona**. Sin la zona, el
    navegador los leería como hora local y el contenedor corre en UTC: seis
    horas de diferencia, que es la misma trampa que ya costó 11.7 puntos de
    crecimiento inventados, solo que del lado del cliente.

    **La comparación de cada renglón se calcula UNA vez aquí** y se usa dos: la
    pinta el renglón y la cuenta el conteo de arriba. Hacerla dos veces sería
    barato —son cuatro restas— y aun así está mal: el número de arriba tiene que
    salir exactamente de la misma `Comparacion` que la fila enseña, o el día que
    una de las dos llamadas cambie de argumentos la pantalla y su resumen dirán
    cosas distintas sobre el mismo renglón.

    `atendidos_despues` es el conjunto de `producto_id` que una lista
    posterior ya atendió (`almacenamiento.productos_atendidos_despues`),
    leído **una vez por respuesta y no una vez por renglón recibido** —quien
    llama lo trae ya calculado, con su propio `try`/`except` (regla 4)—. De
    ahí sale `se_puede_corregir` de cada renglón, con
    `transiciones.motivo_para_no_corregir`.

    **Obligatorio y sin omisión** (2026-09-22, paso 2 de la revisión de
    arquitectura): hasta entonces el valor por omisión era `frozenset()`, y
    cinco de las seis rutas que arman una respuesta con `_como_json` —cerrar,
    reabrir, partir, enviar, tachar— lo dejaban puesto sin darse cuenta, así
    que sus respuestas pintaban "Corregir" como si ninguna lista posterior
    hubiera atendido nada. Un valor por omisión que calla en vez de avisar es
    exactamente lo que la regla 4 de `CLAUDE.md` prohíbe —"nunca en
    silencio"—, y aquí lo prohíbe además una prueba: quien llame sin este
    argumento ahora revienta con un `TypeError` en vez de servir una
    respuesta con un botón que 409ea. Quien llama lo calcula con
    `_los_atendidos_despues`, que ya trae su propio hueco con motivo si la
    lectura falla.
    """
    comparaciones = {
        r.renglon_id: comparar((precios or {}).get(r.renglon_id, ()), r.cantidad_a_pedir)
        for r in guardado.renglones
    }
    por_pedido = {p.pedido_id: p for p in (pedidos or ())}
    # LA PARTICIÓN, calculada una vez: la pinta la vista previa y de ella sale
    # si hay algo que partir, que decide la frase de abajo (ticket 27).
    la_particion = partir(
        guardado.por_repartir, comparaciones, precios or {}, puente_configurado()
    )
    ahora = _ahora()
    # EL N DEL TICKET 25, leído una vez por respuesta. Si el YAML no lo trae
    # bien, los renglones en tránsito se enseñan sin decir si están atrasados.
    umbral, detalle_del_umbral = _umbral_del_atraso()
    return {
        "ok": True,
        "pedido_sugerido_id": guardado.pedido_sugerido_id,
        # Qué quiere decir "atrasado" en esta respuesta (ticket 25): el número,
        # o por qué no se pudo leer. Los renglones lo usan; va aquí una vez.
        "atraso": {"umbral": umbral, "detalle": detalle_del_umbral},
        "estado": guardado.estado,
        "fecha_de_ventas": guardado.ventana.hasta.isoformat(),
        "ventas_consideradas_desde": guardado.ventana.desde.isoformat(),
        "ventas_consideradas_hasta": guardado.ventana.hasta.isoformat(),
        "armado_en": guardado.armado_en.isoformat(),
        "cerrado_en": (
            guardado.cerrado_en.isoformat() if guardado.cerrado_en else None
        ),
        # LA ÚLTIMA REAPERTURA (ADR 0016): la firma, y su frase hecha en Python
        # en la hora de la farmacia. `reapertura` es el botón de deshacer —solo
        # lo traen la carga y el cierre, que son las que preguntan a la base—.
        "reabierto_por": guardado.reabierto_por,
        "reabierto_en": (
            guardado.reabierto_en.isoformat() if guardado.reabierto_en else None
        ),
        "frase_de_la_reapertura": frase_de_la_reapertura(
            guardado.reabierto_por, guardado.reabierto_en
        ),
        "reapertura": reapertura,
        "tiene_renglones_sin_atender": guardado.tiene_renglones_sin_atender,
        # **Van TODOS los renglones, descartados incluidos**, y con su estado.
        # Mandar solo los de trabajo dejaría a la pantalla sin con qué pintar el
        # bloque de descartados, y pedirlos en una segunda llamada sería leer
        # dos veces la misma lista en dos momentos distintos: las dos partes
        # podrían no coincidir y nadie sabría cuál tiene razón. Es el mismo
        # criterio por el que el interruptor de vistas filtra en el navegador
        # (`vistas.py`).
        "renglones": [
            _renglon_como_json(
                r,
                (precios or {}).get(r.renglon_id, ()),
                comparaciones.get(r.renglon_id),
                corrida,
                ventana=guardado.ventana,
                pedido=por_pedido.get(r.pedido_id),
                lista=guardado,
                ya_en_camino=ya_en_camino,
                ahora=ahora,
                umbral=umbral,
                con_propuesta=con_propuesta,
                aun_faltan=aun_faltan,
                atendidos_despues=atendidos_despues,
            )
            for r in guardado.renglones
        ],
        # Los dos conteos se calculan en Python —donde hay pruebas— y no en el
        # JavaScript. `descartados` es lo que el ticket pide que se vea y, de
        # paso, el numerador de la condición de revisión del ADR 0002.
        "descartados": guardado.descartados,
        "de_trabajo": len(guardado.de_trabajo),
        # CUÁNTOS YA SE PIDIERON (ticket 21). Se cuenta en Python, donde hay
        # pruebas, y sale del ESTADO del renglón y no de los pedidos: la
        # pregunta es cuánta de esta lista ya está en camino, y el glosario la
        # puso ahí. Un renglón `en tránsito` sigue viéndose en la tabla —no
        # desaparece— pero ya no cuenta como trabajo pendiente.
        "en_transito": guardado.en_transito,
        "sin_catalogo": guardado.sin_catalogo,
        # De la lista completa, no de la vista: la pregunta que responde es si
        # vale la pena ir a ponerles anaquel en SICAR. El porqué está en
        # `PedidoSugerido.sin_clasificar`.
        "sin_clasificar": guardado.sin_clasificar,
        # CUÁNTOS RENGLONES QUEDARON SIN COMPARAR (ticket 15), y por qué cada
        # uno. Es lo que impide que la lista se lea como si estuviera completa:
        # sin este número, veinte renglones con su tabla de cuatro proveedores
        # se ven igual tengan cuatro precios o ninguno, y la única manera de
        # saberlo es abrirlos uno por uno.
        #
        # Sobre los que quedan **por repartir** y no sobre la lista entera: un
        # descartado ya se atendió y uno `en tránsito` ya se pidió (ticket 21).
        # El porqué entero está en `comparacion.contar_la_lista` y en
        # `PedidoSugeridoGuardado.por_repartir`.
        "conteo_de_precios": conteo_como_json(
            contar_la_lista(comparaciones[r.renglon_id] for r in guardado.por_repartir)
        ),
        # CÓMO LE FUE AL LOTE DE ANOCHE SOBRE ESTA LISTA (ticket 19, ADR 0007).
        # Se escribe **también cuando fue bien**, por lo mismo que el conteo de
        # huecos: callar en el caso bueno dejaría el silencio con dos
        # significados —"corrió y le fue bien" y "esta pantalla no lo cuenta"—
        # y el encargado no puede distinguirlos.
        #
        # `null` quiere decir "no hay corrida de esta lista", que es un dato:
        # o el lote no corrió, o la lista se armó desde esta pantalla antes de
        # que pasara por ella.
        "corrida": _corrida_como_json(corrida),
        # POR QUÉ NO HAY CORRIDA, cuando no la hay (decisión del dueño,
        # 2026-09-21): ámbar —el lote todavía no ha tenido su turno— o rojo
        # —ya debía haber pasado, o la lectura se cayó—. `None` cuando SÍ hay
        # fila: los dos son mutuamente excluyentes y la pantalla no tiene que
        # elegir entre dos verdades.
        "corrida_ausente": (
            None
            if corrida is not None
            else _corrida_ausente_como_json(
                guardado.armado_en, ahora, fallo_de_lectura=corrida_fallo
            )
        ),
        # LO QUE EL BOTÓN DE COMPLETAR VA A CONSULTAR, contado aquí y no en el
        # navegador. El número va en la etiqueta del botón, y un conteo que el
        # JavaScript llevara a mano se separa de la verdad en cuanto hay dos
        # pestañas abiertas en el mostrador.
        #
        # Sobre los que quedan **por repartir**: un renglón descartado ya se
        # atendió y uno `en tránsito` ya se pidió, y gastar cuatro visitas a
        # portales ajenos en mercancía que nadie va a comprar —o que ya viene
        # en camino— es justo lo que no se quiere. Mismo criterio que el conteo.
        "faltantes": faltantes_como_json(
            elegir_los_faltantes(guardado.por_repartir, comparaciones)
        ),
        # A QUIÉN LE CADUCÓ LA SESIÓN, para el botón que la abre. Sale de las
        # lecturas congeladas y NO de `GET /api/sesiones` de Doyle: el
        # `guardada` de Doyle no quiere decir que la sesión sirva —el
        # 2026-09-19 los cuatro decían `guardada` con las cuatro caducadas—, y
        # lo que sí lo demuestra es un portal que mandó al login.
        "sesiones_caducadas": [
            {"proveedor": clave, "nombre": nombre_del_proveedor(clave)}
            for clave in proveedores_con_sesion_caducada(
                [comparaciones[r.renglon_id] for r in guardado.por_repartir]
            )
        ],
        # EN QUÉ SE PARTIRÍA LA LISTA SI SE PARTIERA AHORA (ticket 20), y en
        # qué está partida ya. Son dos cosas distintas y las dos viajan:
        #
        # - `particion` es el cálculo, hecho con las elecciones y los precios
        #   de este instante. Es lo que el botón va a escribir, enseñado antes
        #   de apretarlo — nadie debería partir a ciegas.
        # - `pedidos` son las filas que ya existen, con su estado y su total.
        #   `null` mientras la lista no se haya partido nunca; `[]` cuando se
        #   partió y no quedó ninguno, que no es lo mismo.
        #
        # `puente` va una vez arriba y no repetido en cada renglón: que SICAR
        # no conozca a QuePharma es una propiedad de la instalación, no de un
        # producto.
        "particion": {
            **particion_como_json(la_particion),
            # POR QUÉ NO QUEDA NADA QUE PARTIR, cuando es porque ya se atendió
            # (ticket 25). Solo si de verdad no queda nada por repartir: con
            # renglones abiertos sin precio, "no hay en qué partir" es otra
            # cosa y la pantalla dice lo suyo.
            #
            # DESDE EL TICKET 27, también cuando la partición no tiene nada que
            # partir aunque quede algo abierto SIN PROVEEDOR (hilo abierto 18):
            # la pantalla caía en su texto de reserva —"esta lista ya se pidió
            # entera… sus renglones están en tránsito"—, que con lo recibido
            # mentía dos veces. Ahora lo dice Python, con cuántos faltan.
            "sin_nada_por_repartir": (
                None
                if la_particion.hay
                else frase_sin_nada_por_repartir(
                    guardado.en_transito,
                    sum(1 for r in guardado.renglones if r.esta_cancelado),
                    sum(1 for r in guardado.renglones if r.esta_recibido),
                    sin_proveedor=len(la_particion.sin_proveedor),
                )
            ),
        },
        # LA CAPTURA DE CADA PEDIDO (ticket 22) viaja DENTRO del pedido y sale
        # de los renglones que el pedido GUARDADO tiene dentro — no de la vista
        # previa de arriba, que se recalcula con los precios de este instante y
        # puede ya haber movido un renglón a otro proveedor. Lo que se captura
        # es lo que al enviar pasa a `en tránsito`, y eso lo decide `pedido_id`.
        "pedidos": (
            None
            if pedidos is None
            else [
                _pedido_como_json(
                    p,
                    *_lo_que_hay_dentro(guardado, p),
                    captura=lo_que_hay_que_capturar(p, guardado.renglones, precios or {}),
                    en_camino_dentro=sum(
                        1
                        for r in guardado.renglones
                        if r.pedido_id == p.pedido_id and r.esta_en_transito
                    ),
                    recibidos_dentro=sum(
                        1
                        for r in guardado.renglones
                        if r.pedido_id == p.pedido_id and r.esta_recibido
                    ),
                    renglones_de_la_lista=guardado.renglones,
                )
                for p in pedidos
            ]
        ),
        "puente": puente_como_json(puente_configurado()),
        "vistas": _vistas(),
        # LO QUE VIENE EN CAMINO DE LISTAS ANTERIORES (ticket 24). Solo lo trae
        # la carga de la lista: `null` en las respuestas de partir, enviar,
        # tachar y cerrar, que no lo cambian — la pantalla conserva el de la
        # carga en vez de leerlo otra vez por cada clic.
        "en_camino": en_camino,
        # LA RECEPCIÓN SUGERIDA (ticket 26). Igual que `en_camino`: solo la trae
        # la carga de la lista, y la pantalla conserva la de la carga.
        "recepcion": recepcion,
    }


def _lo_que_hay_dentro(
    guardado: PedidoSugeridoGuardado, pedido: PedidoGuardado
) -> tuple[int, bool]:
    """Cuántos renglones cuelgan de ese pedido, y si su total ya envejeció.

    Sale de los renglones que ya viajaban en la respuesta y no de una consulta
    más: `renglon.pedido_id` es UNA columna —un renglón pertenece a un solo
    pedido— así que recorrerla aquí es recorrer una lista que ya está en
    memoria.

    Las dos cosas son lo que `particion.motivo_para_no_enviar` necesita para
    apagar el botón **antes** de que alguien lo apriete, con su motivo al lado.
    **Ninguna de las dos es la garantía**: ésa vive en el `EXISTS` y el
    `NOT EXISTS` de `_ENVIAR_EL_PEDIDO`, porque comprobar aquí y escribir
    después tiene una carrera en medio.

    "Envejeció" es `ajustada_en > armado_en` en algún renglón de dentro:
    `pedido.total_sin_iva` solo se reescribe al partir, así que una cantidad
    corregida después lo deja enseñando lo que costaba hace un rato (hilo
    abierto 13 de `HANDOVER.md`).
    """
    dentro = [r for r in guardado.renglones if r.pedido_id == pedido.pedido_id]
    envejecido = any(
        r.ajustada_en is not None and r.ajustada_en > pedido.armado_en
        for r in dentro
    )
    return len(dentro), envejecido


def _pedido_como_json(
    pedido: PedidoGuardado,
    renglones_dentro: int = 0,
    total_envejecido: bool = False,
    captura: Captura | None = None,
    en_camino_dentro: int = 0,
    recibidos_dentro: int = 0,
    renglones_de_la_lista=(),
) -> dict:
    """Un pedido ya guardado, como la pantalla lo lee.

    `total_sin_iva` viaja como **cadena** o como `null`, nunca como número de
    JSON ni como cero: el JSON de JavaScript solo tiene `double` y meterlo ahí
    sería tirar el `numeric(12,2)` justo al salir. `null` quiere decir "no se
    puede saber" —alguna línea va sin precio, o el pedido se quedó sin
    renglones— y la pantalla escribe eso, no un `$0.00`. **Es el total que el
    encargado ve ANTES de enviar**, que es la primera casilla del ticket 21.

    `tiene_puente` va resuelto para que el JavaScript no pregunte por un
    `!== null`: es la misma razón de siempre, y aquí además decide qué frase se
    escribe cuando SICAR no conoce al proveedor.

    **Las tres del envío viajan RESUELTAS desde Python** (ticket 21):
    `frase_del_envio` dice qué significa enviar —o quién lo capturó—,
    `se_puede_enviar` y `motivo_para_no_enviar` deciden si el botón va apagado y
    por qué. La frase no se compone en el JavaScript, y eso es la lección del
    ticket 15 aplicada al sitio donde más caro sale: es la frase que impide que
    el encargado crea que Continental le mandó el pedido a NADRO.
    """
    motivo = motivo_para_no_enviar(pedido, renglones_dentro, total_envejecido)
    # Un pedido con algo recibido sí se capturó (ticket 26): no se cancela.
    motivo_de_cancelar = motivo_para_no_cancelar(pedido, recibidos_dentro)
    # LOS OTROS DOS ESTADOS (ticket 27, ADR 0015): `recibido` y `recibido
    # parcial` se CALCULAN de sus renglones y no se guardan.
    # `PedidoALaVista` junta esa cuenta en un solo lugar, para que
    # `estado_del_pedido(` no se vuelva a llamar aquí.
    vista = PedidoALaVista.de(pedido, renglones_de_la_lista)
    return {
        "pedido_id": pedido.pedido_id,
        "proveedor": pedido.proveedor,
        "nombre": pedido.nombre,
        "proveedor_id": pedido.proveedor_id,
        "tiene_puente": pedido.tiene_puente,
        "estado": pedido.estado_declarado,
        # `estado` sigue diciendo lo guardado —`enviado` es verdad: alguien lo
        # capturó—, y las tres banderas de abajo siguen significando lo mismo;
        # lo que la pantalla enseña de la recepción viaja aparte, hecho frase.
        "estado_a_la_vista": vista.estado,
        "frase_de_la_recepcion": vista.frase_de_la_recepcion,
        "es_borrador": pedido.es_borrador,
        "fue_enviado": pedido.fue_enviado,
        # CANCELAR (ticket 25, ADR 0013). La firma y lo que la pantalla dice
        # junto al botón, ya decidido aquí. `se_puede_cancelar` es la misma
        # decisión que el `WHERE` de `_CANCELAR_EL_PEDIDO` y NO la garantía.
        "fue_cancelado": pedido.fue_cancelado,
        "cancelado_por": pedido.cancelado_por,
        "cancelado_en": (
            pedido.cancelado_en.isoformat() if pedido.cancelado_en else None
        ),
        "se_puede_cancelar": motivo_de_cancelar is None,
        "motivo_para_no_cancelar": motivo_de_cancelar,
        "frase_para_cancelar": (
            frase_para_cancelar(pedido.nombre, en_camino_dentro)
            if motivo_de_cancelar is None
            else None
        ),
        "armado_en": pedido.armado_en.isoformat(),
        "total_sin_iva": (
            None if pedido.total_sin_iva is None else str(pedido.total_sin_iva)
        ),
        "hay_total": pedido.total_sin_iva is not None,
        "renglones": renglones_dentro,
        # LA FIRMA DEL ENVÍO. En ISO **con zona**, por la misma razón que
        # `armado_en`: sin ella el navegador la leería como hora local y el
        # contenedor corre en UTC, que son seis horas de diferencia.
        "enviado_por": pedido.enviado_por,
        "enviado_en": (
            pedido.enviado_en.isoformat() if pedido.enviado_en else None
        ),
        # Y LO QUE LA PANTALLA ESCRIBE, ya decidido aquí. `se_puede_enviar` es
        # la misma decisión que el `WHERE` de `_ENVIAR_EL_PEDIDO` y NO la
        # garantía —comprobar aquí y escribir después tiene una carrera en
        # medio—: sirve para apagar el botón con su motivo al lado en vez de
        # dejar que alguien lo apriete y reciba un 409.
        "frase_del_envio": frase_del_envio(pedido),
        "se_puede_enviar": motivo is None,
        "motivo_para_no_enviar": motivo,
        # LO QUE HAY QUE TECLEAR EN EL PORTAL, y cuánto va (ticket 22). Recibe
        # `se_puede_enviar` y no al revés, y esa dirección es la quinta casilla
        # entera: la captura puede INVITAR a enviar, pero el envío no mira la
        # captura. `null` cuando quien llama no la calculó.
        "captura": (
            None if captura is None else captura_como_json(captura, motivo is None)
        ),
        # EL ARCHIVO (ticket 23), con la URL hecha aquí y no en el JavaScript.
        # `null` cuando no hay nada que exportar —sin captura calculada, o sin
        # renglones—: la pantalla no pinta un enlace que contestaría 409.
        "csv": (
            None
            if captura is None or not captura.hay
            else f"/api/pedido-sugerido/{pedido.pedido_sugerido_id}"
            f"/pedido/{pedido.pedido_id}/csv"
        ),
    }


def _corrida_como_json(corrida: CorridaDelLote | None) -> dict | None:
    """La corrida del lote como la pantalla la lee, o `None` si no hubo.

    La frase larga viene **hecha** (`faltantes.frase_de_la_corrida`) y no se
    arma en el JavaScript, por lo mismo que la certeza del ganador del ticket
    15: una frase compuesta a partir de banderas en el único archivo que
    ninguna prueba de Python mira es una afirmación sin pruebas. Los números
    viajan además de la frase porque la pantalla los usa para decidir el color,
    que es lo único que sí le toca decidir a ella.
    """
    if corrida is None:
        return None
    return {
        "final": corrida.final,
        "frase": frase_de_la_corrida(corrida),
        "termino_en": (
            corrida.termino_en.isoformat() if corrida.termino_en else None
        ),
        "se_corto_por_tiempo": corrida.se_corto_por_tiempo,
        "se_interrumpio": corrida.se_interrumpio,
        "llego_al_final": corrida.llego_al_final,
        "hubo_fallas": corrida.hubo_fallas,
        "en_la_lista": corrida.en_la_lista,
        "consultados": corrida.consultados,
        "con_precio": corrida.con_precio,
        "sin_precio": corrida.sin_precio,
        "sin_alcanzar": corrida.sin_alcanzar,
        "no_se_pudo": corrida.no_se_pudo,
        "sin_clave": corrida.sin_clave,
        "orden_cumplido": corrida.orden_cumplido,
        "tope_minutos": corrida.tope_minutos,
        "minutos": round(corrida.segundos / 60.0, 1),
    }


def _corrida_ausente_como_json(
    armado_en: dt.datetime, ahora: dt.datetime, *, fallo_de_lectura: bool
) -> dict:
    """Por qué no hay corrida, cuando no la hay: ámbar o rojo (2026-09-21).

    El nivel y la frase son de `faltantes.corrida_ausente_como_json`, pura y
    sin YAML. `que_hacer` se agrega aquí porque necesita `a_quien_avisar`, que
    sale de `config/continental.yml` y `cargar()` no se llama desde una
    función pura. En ámbar no hay `que_hacer`: nada está mal, no hay nada que
    hacer.

    Dos causas de rojo, dos casos de `_que_hacer`: si la LECTURA se cayó, es
    el mismo consejo que cualquier otro hueco de lectura (`AL_LEER` — vuelve a
    cargar la página); si de verdad no hay fila y ya debía haberla, es un
    problema de atlas o del timer (`LOTE`), no de la conexión de esta visita.
    """
    ausente = corrida_ausente_como_json(
        armado_en, ahora, fallo_de_lectura=fallo_de_lectura
    )
    ausente["que_hacer"] = (
        _que_hacer(AL_LEER if fallo_de_lectura else LOTE)
        if ausente["nivel"] == NIVEL_FALLA
        else None
    )
    return ausente


def _renglon_como_json(
    renglon,
    precios=(),
    comparacion=None,
    corrida: CorridaDelLote | None = None,
    *,
    ventana: Ventana | None = None,
    pedido: PedidoGuardado | None = None,
    lista: PedidoSugeridoGuardado | None,
    ya_en_camino: dict | None = None,
    ahora: dt.datetime | None = None,
    umbral: int | None = None,
    con_propuesta: frozenset[int] = frozenset(),
    aun_faltan: frozenset[int] | None = None,
    atendidos_despues: frozenset[int],
) -> dict:
    """Un renglón guardado, como la pantalla lo lee.

    `lista` es la lista guardada a la que pertenece este renglón
    (`PedidoSugeridoGuardado`), y **es obligatoria y sin omisión** (2026-09-22,
    paso 2 de la revisión de arquitectura): de ella sale `se_puede_editar` y
    `se_puede_devolver_a_abierto`, con `transiciones.motivo_para_no_editar`.
    Un valor por omisión de `None` habría hecho lo mismo que le pasó a
    `atendidos_despues` antes de este paso —una bandera que calla en vez de
    avisar que faltó pasarla— y aquí el error sería al revés y más difícil de
    notar: los botones se apagarían siempre, en vez de ofrecerse de más.
    Quien llama en general ya tiene la lista a la mano (`_como_json` la
    recibió como `guardado`; las rutas de un solo renglón la releyeron para
    devolver la respuesta).

    `corrida` es cómo le fue al lote sobre la lista de este renglón, y de ella
    sale `porque_no_hay_lectura` (ticket 19). Va por omisión en `None` porque
    las rutas que devuelven **un** renglón —descartar, devolver, ajustar— no
    tienen la corrida a la mano y no la necesitan: su respuesta sustituye una
    fila que ya estaba pintada con su motivo, y releerla costaría una consulta
    por clic para no cambiar nada. Lo que sí pasa es que un renglón sin lectura
    que alguien devuelve a la lista vuelve sin su motivo hasta la siguiente
    carga; se ve como el "nadie lo consultó" de antes, que es de menos y nunca
    de más.

    `precios` son las lecturas congeladas de ese renglón, una por proveedor que
    contestó alguna vez. Viaja **dentro del renglón** por la misma razón que la
    existencia y la clasificación: se leyó para ese renglón, en ese instante, y
    quien pinte la lista no tiene que volver a emparejarlo con nada. Por omisión
    va vacío, que es un renglón que nadie ha consultado — y eso es un dato, no
    un hueco: es lo que el ticket 15 va a contar como *sin comparar*.

    `esta_agotado` va explícito porque `asdict` no incluye propiedades, y la
    regla —existencia conocida y en cero o negativa— tiene que vivir en un solo
    lugar probado, no repetida en el JavaScript de la pantalla.

    `descartado_en` viaja en ISO **con zona**, por la misma razón que
    `armado_en`: sin ella el navegador lo leería como hora local y el contenedor
    corre en UTC.

    Lo usan la lista entera y las dos rutas del ticket 10, y eso es el punto: el
    renglón que vuelve después de descartarlo tiene exactamente la misma forma
    que el que llegó en la carga, así que la pantalla puede sustituirlo sin
    traducir nada.
    """
    return {
        **dataclasses.asdict(renglon.propuesto),
        "esta_agotado": renglon.propuesto.esta_agotado,
        "renglon_id": renglon.renglon_id,
        "estado": renglon.estado,
        # YA SE LE PIDIÓ A UN PROVEEDOR (ticket 21). Va resuelto y no deducido
        # del estado en el JavaScript, por la misma razón que `esta_agotado`:
        # la regla que decide si un renglón sigue pendiente vive en
        # `RenglonGuardado.esta_en_transito`, probada, y de ella cuelgan tres
        # cosas de la pantalla —la marca, los controles apagados y el conteo de
        # "por atender"—.
        "esta_en_transito": renglon.esta_en_transito,
        # SE DEJÓ DE ESPERAR (ticket 25). Resuelto aquí por la misma razón que
        # `esta_en_transito`: de él cuelgan la marca, los controles apagados y
        # el conteo de "por atender", y la regla vive en `RenglonGuardado`.
        "esta_cancelado": renglon.esta_cancelado,
        # YA LLEGÓ (ticket 26): resuelto aquí por lo mismo que los dos de
        # arriba. De él cuelgan la marca, los controles apagados y el conteo.
        "esta_recibido": renglon.esta_recibido,
        # SE PUEDE DESCARTAR, AJUSTAR LA CANTIDAD O ELEGIR PROVEEDOR
        # (2026-09-22, paso 2 de la revisión de arquitectura). Hasta este paso
        # `continental.js` lo recalculaba solo —`!esta_en_transito &&
        # !esta_cancelado && !esta_recibido`, combinado con el estado de la
        # LISTA— sin que ninguna prueba de Python comprobara que esa copia
        # seguía de acuerdo con el `WHERE` de `_DESCARTAR`,
        # `_AJUSTAR_LA_CANTIDAD` y `_ELEGIR_PROVEEDOR`. Ahora es **la misma
        # decisión**, con `transiciones.motivo_para_no_editar`, y el
        # JavaScript solo lee la bandera.
        "se_puede_editar": (
            motivo_para_no_editar(renglon, lista, "descartar") is None
        ),
        # SE PUEDE DEVOLVER A LA LISTA (el renglón `descartado`), por la misma
        # razón y con la misma función: `_DEVOLVER_A_ABIERTO` exige lo
        # contrario que las tres de arriba —el renglón `descartado`— y por eso
        # es una bandera aparte y no la negación de `se_puede_editar`.
        "se_puede_devolver_a_abierto": (
            motivo_para_no_editar(renglon, lista, "devolver_a_abierto") is None
        ),
        "frase_de_lo_recibido": frase_de_lo_recibido(renglon),
        # CUÁNTAS LLEGARON, Y CORREGIRLO (ticket 27, ADR 0015). Hasta el
        # 2026-09-21 esta bandera era solo `renglon.esta_recibido`, sin mirar
        # que el pedido siguiera `enviado` ni que ninguna lista posterior
        # hubiera atendido el producto: pintaba "Corregir" en casos que el
        # `WHERE` de `_CORREGIR_LO_RECIBIDO` iba a rechazar con un 409. Ahora
        # es **la misma decisión**, con `transiciones.motivo_para_no_corregir`
        # — `piezas=None` porque aquí se pregunta si se podría ofrecer
        # corregir EN GENERAL, no si una cifra concreta se aceptaría.
        "piezas_recibidas": renglon.piezas_recibidas,
        "se_puede_corregir": (
            motivo_para_no_corregir(
                renglon,
                pedido,
                renglon.propuesto.producto_id in atendidos_despues,
            )
            is None
        ),
        "etiqueta_a_mano": ETIQUETA_PARA_CORREGIR if renglon.esta_recibido else None,
        # LO QUE FALTÓ Y ESTE RENGLÓN TRAE (ticket 27): sin la frase, "pide 6"
        # con 2 vendidas no se puede verificar. La cifra ya viene de `asdict`.
        "frase_de_lo_que_falto": frase_de_lo_que_falto(
            renglon.propuesto.piezas_que_faltaron
        ),
        "cancelado_por": renglon.cancelado_por,
        "cancelado_en": (
            renglon.cancelado_en.isoformat() if renglon.cancelado_en else None
        ),
        "descartado_por": renglon.descartado_por,
        "descartado_en": (
            renglon.descartado_en.isoformat() if renglon.descartado_en else None
        ),
        # Las DOS cantidades viajan, y `cantidad_propuesta` ya viene de
        # `asdict(propuesto)`: son dos datos distintos y la pantalla los pinta
        # juntos cuando difieren. `cantidad_final` es `null` mientras nadie la
        # haya tocado — nunca la propuesta copiada, que borraría la diferencia.
        "cantidad_final": renglon.cantidad_final,
        # Lo que de verdad se le va a pedir al proveedor. Se manda calculado en
        # vez de dejar que el JavaScript elija entre las dos columnas: esa regla
        # vive en un solo lugar probado (`RenglonGuardado.cantidad_a_pedir`), y
        # el día que el pedido por proveedor (ticket 20) tome la cifra, va a
        # tomar exactamente la que se vio en la pantalla.
        "cantidad_a_pedir": renglon.cantidad_a_pedir,
        # Dos preguntas distintas y por eso dos campos: `fue_ajustada` dice si
        # alguien la decidió —aunque haya decidido la misma cifra— y es lo que
        # justifica mostrar la firma; `difiere_de_la_propuesta` dice si hay dos
        # números que enseñar. Enseñar "el sistema propuso 3" al lado de un 3
        # es ruido, y el ruido se deja de leer justo antes del renglón donde la
        # diferencia importaba.
        "fue_ajustada": renglon.fue_ajustada,
        "difiere_de_la_propuesta": renglon.difiere_de_la_propuesta,
        "ajustada_por": renglon.ajustada_por,
        "ajustada_en": (
            renglon.ajustada_en.isoformat() if renglon.ajustada_en else None
        ),
        # Lo congelado: el precio con el que se va a decidir, no el de hoy. La
        # traducción a JSON vive en `consultas.lecturas_como_json` —con el
        # precio como cadena, para que no pase por la coma flotante de
        # JavaScript justo al salir— y no aquí, porque las dos rutas de precio
        # la usan igual.
        "precios": lecturas_como_json(precios),
        # La comparación de los cuatro (ticket 14): quién gana, cuánto se
        # ahorra contra NADRO y cómo se ve cada proveedor. Sale de `comparar`,
        # que es una función pura con su tabla de casos, y **no del
        # JavaScript**: la regla que decide a quién comprarle no puede vivir en
        # el único archivo que ninguna prueba de Python mira.
        #
        # Las piezas que multiplican el ahorro son `cantidad_a_pedir` —la
        # corrección de la persona si la hubo, y si no la propuesta del
        # sistema—, que es la misma cifra que se pinta en la columna de
        # cantidad y la que el ticket 20 va a copiar al pedido. La regla vive en
        # `RenglonGuardado.cantidad_a_pedir` y aquí solo se usa.
        #
        # `comparacion` puede venir ya hecha —la lista la calcula una vez para
        # todos sus renglones, porque el conteo de arriba tiene que salir de la
        # misma—. Cuando no viene, se hace aquí: las rutas que devuelven **un**
        # renglón no tienen ni necesitan la lista entera.
        "comparacion": comparacion_como_json(
            comparar(precios, renglon.cantidad_a_pedir)
            if comparacion is None
            else comparacion
        ),
        # A QUIÉN SE LE PIDE ESTE RENGLÓN (ticket 20): lo que una persona
        # decidió, y si nadie decidió, lo que el sistema sugiere. Las dos
        # viajan juntas y ya resueltas, con la bandera que dice cuál de las dos
        # es — la pantalla escribe, no deduce.
        #
        # **Lo sugerido no está guardado en ninguna columna**: se calcula aquí,
        # de la misma `Comparacion` que la fila de precios enseña. Es a
        # propósito, y es la diferencia consciente con el ticket 11 — el porqué
        # entero está en el encabezado de `particion.py`. La consecuencia buena
        # está a la vista: el sugerido no puede decir otra cosa que el ganador
        # que se está pintando al lado, porque es el mismo objeto.
        "eleccion": eleccion_como_json(
            elegir(
                renglon,
                comparar(precios, renglon.cantidad_a_pedir)
                if comparacion is None
                else comparacion,
            )
        ),
        # En qué pedido quedó, o `null` si todavía no se ha partido. Es UNA
        # columna: un renglón pertenece a un solo pedido.
        "pedido_id": renglon.pedido_id,
        **_porque_no_hay_lectura_como_json(renglon, comparacion, precios, corrida),
        **_transito_del_renglon_como_json(
            renglon, ventana, pedido, ya_en_camino, ahora, umbral, con_propuesta, aun_faltan
        ),
    }


def _transito_del_renglon_como_json(
    renglon,
    ventana,
    pedido,
    ya_en_camino,
    ahora,
    umbral=None,
    con_propuesta=frozenset(),
    aun_faltan=None,
) -> dict:
    """Las tres frases del ticket 24 que cuelgan de un renglón de la lista.

    - **`frase_del_transito`** — el renglón de hoy que ya se envió: *"Pedido
      hoy a NADRO, sin recibir."* Necesita su pedido (a quién y cuándo); sin él
      va `null` y la pantalla dice lo que ya decía desde el ticket 21.
    - **`frase_de_la_ventana`** — el renglón cuyas ventas no empiezan donde
      empieza la lista: trae lo que se vendió mientras venía en camino, o se
      salta lo que ya venía pedido. Sin esta frase, "pide 4" en una lista de
      un día con una venta no se puede verificar.
    - **`ya_viene_en_camino`** — un renglón abierto de hoy cuyo producto ya se
      pidió desde una lista anterior. **La llave solo va cuando se calculó**
      (la carga de la lista): las rutas de un solo renglón no la mandan, y la
      pantalla conserva la de la carga.

    Y las del ticket 25:

    - **`frase_de_lo_cancelado`** — el renglón de hoy que se dejó de esperar:
      vuelve a proponerse en la siguiente lista, no en ésta.
    - **`dias_en_transito`, `atrasado`, `frase_del_atraso`,
      `se_puede_devolver`** — el renglón de hoy que sigue en tránsito. Casi
      nunca se atrasa —se envió desde la lista de hoy—, salvo que el almacén
      lleve días sin ventas nuevas y "la lista de hoy" sea vieja. Por eso se
      calcula también aquí y no solo en el bloque de listas anteriores.

    Todas se componen en `transito.py`, en Python y con pruebas: el JavaScript
    las pinta y no decide ni una palabra (la lección del ticket 15).
    """
    ahora = ahora or _ahora()
    en_transito_con_pedido = renglon.esta_en_transito and pedido is not None
    dias = dias_en_transito(pedido.enviado_en, ahora) if en_transito_con_pedido else None
    atrasado = (
        esta_atrasado(dias, umbral)
        if en_transito_con_pedido and umbral is not None
        else None
    )
    salida: dict = {
        "frase_de_lo_cancelado": (
            frase_del_renglon_cancelado(
                renglon,
                pedido_cancelado=pedido is not None and pedido.fue_cancelado,
                nombre=None if pedido is None else pedido.nombre,
            )
            if renglon.esta_cancelado
            else None
        ),
        "dias_en_transito": dias,
        "atrasado": atrasado,
        "frase_del_atraso": frase_del_atraso(dias, umbral),
        # Con una compra que encaja (ticket 26), no se ofrece devolverlo: lo
        # probable es que llegó, y devolverlo sería pedirlo dos veces.
        "se_puede_devolver": bool(atrasado) and renglon.renglon_id not in con_propuesta,
        "frase_de_la_recepcion": (
            PROBABLEMENTE_LLEGO if renglon.renglon_id in con_propuesta else None
        ),
        "frase_del_transito": (
            frase_del_transito(pedido.nombre, pedido.enviado_en, ahora)
            if renglon.esta_en_transito and pedido is not None
            else None
        ),
        "frase_de_la_ventana": (
            None
            if ventana is None
            else frase_de_la_ventana_propia(renglon.propuesto.ventas_desde, ventana)
        ),
    }
    if ya_en_camino is not None:
        ya = ya_en_camino.get(renglon.propuesto.producto_id)
        salida["ya_viene_en_camino"] = (
            frase_de_ya_en_camino(ya, ahora)
            if ya is not None and renglon.se_puede_repartir
            else None
        )
    # LO QUE FALTÓ… Y YA LLEGÓ (ticket 27): la segunda factura se corrigió
    # después de armar esta lista. Solo si se pudo leer lo que aún falta
    # (`None` no afirma nada) y solo mientras el renglón se pueda repartir.
    if aun_faltan is not None:
        faltaron = renglon.propuesto.piezas_que_faltaron
        salida["ya_no_falta"] = (
            frase_de_lo_que_ya_no_falta(faltaron)
            if faltaron
            and renglon.se_puede_repartir
            and renglon.propuesto.producto_id not in aun_faltan
            else None
        )
    return salida


def _porque_no_hay_lectura_como_json(
    renglon, comparacion, precios, corrida: CorridaDelLote | None
) -> dict:
    """Los dos campos del ticket 19 que cuelgan de un renglón, o ninguno.

    **`porque_no_hay_lectura`** solo aparece cuando el renglón no tiene NI UNA
    lectura: es la pregunta que contesta, y ponerlo en un renglón con cuatro
    precios sería una llave que la pantalla tendría que aprender a ignorar.
    Son los tres motivos que el ticket pide, más los tres que hacen falta para
    que no se confundan entre sí:

    - `al lote se le acabó el tiempo` — **el motivo del ticket**, y el que el
      18 dejó sin poder decir. Sale del `final` de la corrida;
    - `el lote no corrió sobre esta lista` — no hay fila de corrida;
    - `la corrida del lote se cortó`, `el lote lo intentó y no pudo`,
      `el lote no lo miró`, `no tiene código de barras`.

    Los otros dos motivos del ticket —*el portal no contestó* y *la sesión
    caducó*— **no viven aquí**: son de un proveedor de un renglón y ya viajan
    dentro de `comparacion.por_proveedor` desde el ticket 12, cada uno con su
    explicación. Son preguntas de dos granos distintos y por eso salen de dos
    sitios distintos (ADR 0007).

    **`huecos_reintentables`** son los proveedores de este renglón a los que
    volver a preguntar puede cambiar algo. La pantalla los usa para ofrecer el
    botón de abrir sesión al lado del renglón que lo necesita, y para explicar
    por qué un renglón **con** precio sigue teniendo huecos que el botón de
    completar no va a atender.
    """
    comparacion = (
        comparar(precios, renglon.cantidad_a_pedir)
        if comparacion is None
        else comparacion
    )
    salida: dict = {
        "huecos_reintentables": [
            {
                "proveedor": proveedor,
                "nombre": nombre_del_proveedor(proveedor),
                "motivo": motivo,
            }
            for proveedor, motivo in huecos_que_se_pueden_reintentar(comparacion)
        ]
    }
    if not comparacion.hay_lecturas:
        salida["porque_no_hay_lectura"] = hueco_como_json(
            por_que_no_hay_lectura(
                tiene_clave=bool(renglon.propuesto.clave), corrida=corrida
            )
        )
    return salida


def _recepcion_con_hueco(detalle: str) -> dict:
    """El bloque de la recepción que no se pudo leer, con qué hacer (ticket 29)."""
    return {**recepcion_con_hueco(detalle), "que_hacer": _que_hacer(AL_LEER)}


def _en_camino_con_hueco(detalle: str) -> dict:
    """El bloque de lo que viene en camino que no se pudo leer, con qué hacer."""
    return {**en_camino_con_hueco(detalle), "que_hacer": _que_hacer(AL_LEER)}


def _sin_ventas(ventas: dict | None = None) -> dict:
    """Ni una venta en el almacén. No es un error y no se guarda nada.

    `ventas` es lo que el servidor afirma sobre eso (ticket 29), con su frase:
    el almacén contestó y está vacío. `None` en el hueco, que no leyó nada.
    """
    return {
        "ventas": ventas,
        "avisos": [],
        "lista_vacia": None,
        "ok": True,
        "pedido_sugerido_id": None,
        "estado": None,
        "fecha_de_ventas": None,
        "ventas_consideradas_desde": None,
        "ventas_consideradas_hasta": None,
        "armado_en": None,
        "cerrado_en": None,
        "tiene_renglones_sin_atender": False,
        "renglones": [],
        "descartados": 0,
        "de_trabajo": 0,
        "sin_catalogo": 0,
        "sin_clasificar": 0,
        "vistas": _vistas(),
    }


def _hueco(detalle: str) -> dict:
    """Un borde caído, con su motivo y sin una sola lista vacía que lo disfrace.

    Desde el ticket 29 dice además, con palabras de Python, que el vacío NO es
    "no se vendió nada", y qué hacer: hasta entonces esas dos frases las
    remataba el JavaScript, con un nombre de persona escrito dentro.
    """
    return {
        **_sin_ventas(),
        "ok": False,
        "detalle": detalle,
        "frase": frase_del_hueco(detalle),
        "que_hacer": _que_hacer(AL_LEER),
    }


def _vistas() -> list[dict]:
    """Las dos vistas como JSON, para que la pantalla no se sepa la regla.

    Viaja en la misma respuesta que la lista y no en una ruta aparte: es lo
    que hace que el interruptor no cueste ni una consulta más, y que la vista
    y los renglones que filtra vengan siempre de la misma lectura.
    """
    return [dataclasses.asdict(v) for v in VISTAS]


#: LA PANTALLA SE REVALIDA CADA VEZ QUE SE ABRE (ticket 28). Desde que son tres
#: archivos —`index.html`, `continental.css` y `continental.js`— una versión
#: nueva desplegada en atlas puede encontrarse en el navegador del mostrador con
#: la hoja o el script de ayer: sin `Cache-Control`, el navegador calcula solo
#: cuánto le cree a su copia (una fracción de lo viejo que es el archivo) y en
#: ese rato no pregunta. Un HTML nuevo con un JavaScript viejo es la peor de las
#: mezclas: pinta llaves que el servidor ya no manda, o no pinta las nuevas.
#:
#: `no-cache` NO quiere decir "no guardes": quiere decir "pregunta antes de
#: usar lo guardado". El navegador manda su `ETag`, Starlette contesta 304 sin
#: cuerpo si no cambió, y el costo es una ida y vuelta corta por archivo al
#: abrir la pantalla. Se descartó ponerle la versión a la URL
#: (`continental.css?v=…`): obligaría a plantillar el HTML, que hoy se sirve
#: tal cual del disco, para ahorrarse tres 304 al día.
SIN_CADUCAR = {"Cache-Control": "no-cache"}


class EstaticosQueSeRevalidan(StaticFiles):
    """`StaticFiles` con `Cache-Control: no-cache` en cada archivo que sirve."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers.update(SIN_CADUCAR)
        return respuesta


@app.get("/")
async def inicio():
    return FileResponse(ESTATICOS / "index.html", headers=SIN_CADUCAR)


app.mount("/static", EstaticosQueSeRevalidan(directory=ESTATICOS), name="static")
