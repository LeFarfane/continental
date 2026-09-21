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

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from continental import __version__
from continental.almacen import LecturaDelAlmacen
from continental.almacenamiento import (
    ABIERTO,
    CANTIDAD_FINAL_MINIMA,
    RENGLON_ABIERTO,
    AlmacenamientoDelPedido,
    CorridaDelLote,
    PedidoGuardado,
    PedidoSugeridoGuardado,
    Ventana,
    dias_primera_vez_configurados,
    ventana_de_reposicion,
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
from continental.faltantes import (
    NUNCA_SE_CONSULTO,
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
    lo_que_hay_que_capturar,
    motivo_para_no_enviar,
    particion_como_json,
    partir,
)
from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor
from continental.proveedores import puente_como_json, puente_configurado
from continental.sugerido import armar_la_lista
from continental.vistas import VISTAS
from continental.web.dependencias import (
    obtener_almacen,
    obtener_almacenamiento,
    obtener_consultas,
    obtener_doyle,
)

ESTATICOS = Path(__file__).parent / "static"

log = logging.getLogger("continental")

app = FastAPI(title="Continental", version=__version__, docs_url="/docs")


def quien(request: Request) -> str:
    """Quién está entrando, según el encabezado que Cloudflare Access ya validó.

    Es una FIRMA, no un permiso (regla 3 de CLAUDE.md). Si alguien alcanza este
    puerto sin pasar por el túnel, puede escribir el encabezado que quiera: la
    autorización la hace Access, no esto. Sirve para saber quién armó un pedido,
    no para decidir si puede armarlo.
    """
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "sin-identificar"


@app.exception_handler(Exception)
async def error_generico(request: Request, exc: Exception):
    """El detalle va a la consola del servidor; al navegador, un mensaje corto.

    Esto corre detrás de un túnel: un `str(exc)` de SQLAlchemy lleva la cadena
    de conexión con contraseña. Doyle puede darse el lujo de devolver el texto
    del error porque solo escucha en 127.0.0.1; aquí no.
    """
    log.exception("Error atendiendo %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Algo falló del lado del servidor. Revisa la bitácora."},
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

    if ultima is None:
        # Un día sin ventas existe de verdad: la farmacia cierra los domingos y
        # no hay una sola venta en domingo en 33 meses. No se guarda una lista
        # vacía —ocuparía el UNIQUE del día y el rol no puede borrarla— y se
        # distingue de la falla porque `ok` sigue siendo verdadero.
        return _sin_ventas()

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
            lambda: _armar(almacen, ventana).renglones,
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
    try:
        precios = almacenamiento.precios_de_la_lista(
            negocio, guardado.pedido_sugerido_id
        )
    except Exception:  # noqa: BLE001 — sin precios la lista sigue sirviendo
        log.exception(
            "No se pudieron leer los precios congelados de la lista %s",
            guardado.pedido_sugerido_id,
        )
        precios = {}

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
    except Exception:  # noqa: BLE001 — sin los pedidos la lista sigue sirviendo
        log.exception(
            "No se pudieron leer los pedidos de la lista %s",
            guardado.pedido_sugerido_id,
        )
        pedidos = None

    return _como_json(
        guardado,
        precios,
        _ultima_corrida(almacenamiento, negocio, guardado.pedido_sugerido_id),
        pedidos,
    )


@app.post("/api/pedido-sugerido/{pedido_sugerido_id}/cerrar")
def cerrar_pedido_sugerido(
    pedido_sugerido_id: int,
    request: Request,
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
    return _como_json(cerrado)


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
        ", ".join(f"{p.nombre} ({p.estado})" for p in pedidos) or "ninguno",
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
    return _como_json(
        relectura,
        almacenamiento.precios_de_la_lista(negocio, pedido_sugerido_id),
        _ultima_corrida(almacenamiento, negocio, pedido_sugerido_id),
        pedidos,
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
            },
        )
    return _como_json(
        relectura,
        almacenamiento.precios_de_la_lista(negocio, lista_id),
        _ultima_corrida(almacenamiento, negocio, lista_id),
        almacenamiento.pedidos_de_la_lista(negocio, lista_id),
    )


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

    Se exporta en `borrador` y en `enviado`, y el archivo dice cuál es en su
    nombre y en su primer renglón: el del borrador sirve para capturar o
    revisar, y el del enviado es el respaldo de lo que se pidió.

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

    nombre = nombre_del_archivo(pedido, lista.fecha_del_pedido)
    log.info(
        "Se exportó el pedido %s (%s, %s) de la lista %s como %s: %d renglón(es).",
        pedido.pedido_id,
        pedido.nombre,
        pedido.estado,
        pedido_sugerido_id,
        nombre,
        captura.cuantos,
    )
    return Response(
        content=csv_del_pedido(pedido, captura, lista.fecha_del_pedido),
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
    return _como_json(
        guardado,
        _precios_de_la_lista(almacenamiento, negocio, lista_id),
        _ultima_corrida(almacenamiento, negocio, lista_id),
        almacenamiento.pedidos_de_la_lista(negocio, lista_id),
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


def _precios_del_renglon(almacenamiento, negocio: str, renglon_id: int):
    """Lo congelado de un renglón, o nada si el almacenamiento no contestó.

    Una tupla vacía cuando la lectura falla y no una excepción hacia arriba: el
    estado de la consulta sigue siendo información aunque la tabla no conteste,
    y la falla ya quedó entera en la bitácora. Lo que no puede pasar es que un
    borde caído deje la pantalla sin decir nada (regla 4).
    """
    try:
        return almacenamiento.precios_del_renglon(negocio, renglon_id)
    except Exception:  # noqa: BLE001 — leer precios caído no puede tumbar la pantalla
        log.exception("No se pudieron leer los precios del renglón %s", renglon_id)
        return ()


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
) -> CorridaDelLote | None:
    """Cómo le fue al lote sobre esta lista, o `None` si no hay fila (ADR 0007).

    **`None` es un dato y no un hueco**, y esa es la mitad del ticket 19 que se
    ve al cargar: quiere decir *"el lote no corrió sobre esta lista"*, que es
    lo que hasta hoy no se distinguía de *"nadie consultó este renglón"* (hilo
    abierto 10 de `HANDOVER.md`). La diferencia entre encontrar la fila y no
    encontrarla es exactamente la diferencia entre los dos.

    Una lectura que **falla** también devuelve `None`, y sí, eso confunde los
    dos casos hacia el lado de "no corrió" — que dice de menos, nunca de más.
    Es el trato que el ADR 0007 ya acepta para la corrida que muere sin poder
    escribir su fila. La alternativa sería tumbar la lista entera porque una
    consulta de una fila no contestó, y una lista sin precios todavía sirve
    para pedir. La falla queda entera en la bitácora.

    Es **una** consulta más por carga, de una fila, con su índice
    `ix_corrida_ultima`.
    """
    try:
        return almacenamiento.ultima_corrida(negocio, pedido_sugerido_id)
    except Exception:  # noqa: BLE001 — la bitácora caída no tumba la lista
        log.exception(
            "No se pudo leer la última corrida del lote de la lista %s. La "
            "pantalla va a decir «el lote no corrió sobre esta lista», que "
            "dice de menos.",
            pedido_sugerido_id,
        )
        return None


def _consulta_como_json(
    consulta, nueva: bool, precios, cantidad: int | None = None
) -> dict:
    """El estado de una consulta más lo congelado, como la pantalla lo lee.

    `ok` es cierto también cuando la consulta terminó mal, y eso no es
    contradictorio: la petición se atendió. Lo que salió mal se dice en `estado`
    y en `detalle`, que es lo que la pantalla pinta como hueco con su motivo.
    Un `ok: false` aquí haría que el JavaScript lo tratara como "no se pudo
    preguntar", que es otra cosa.
    """
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
        "precios": lecturas_como_json(precios),
        # La comparación viaja también por aquí y no solo dentro del renglón de
        # la lista: cuando el botón vuelve, la pantalla sustituye la celda
        # entera con lo que llegó. Si tuviera que recalcular el ganador ahí, la
        # regla viviría en dos lugares y uno de los dos no tendría pruebas.
        "comparacion": comparacion_como_json(comparar(precios, cantidad)),
    }


def _mover_el_renglon(
    renglon_id: int,
    request: Request,
    mover,
    verbo: str,
    choque: str,
    nota: str = "",
    almacenamiento: AlmacenamientoDelPedido | None = None,
):
    """Lo que las tres rutas que mueven un renglón comparten entero.

    `almacenamiento` entra solo para releer los **precios congelados** del
    renglón movido (ticket 12). Es opcional por comodidad de quien llama, y no
    por duda: sin él, el renglón que vuelve tendría la misma forma pero con la
    lista de precios vacía, y la pantalla —que sustituye el renglón entero por
    el que llega— borraría de la vista precios que siguen guardados. Un dato
    que desaparece de la pantalla sin desaparecer de la tabla es peor que uno
    que nunca estuvo: nadie sabe cuál de los dos creer.

    Cambia la operación y cambia el texto; el resto —la firma, el `try` que
    convierte una base caída en un hueco con su motivo, el 409 de "no había
    nada que mover" y la respuesta con los conteos— es el mismo, y escribirlo
    tres veces sería tres oportunidades de que una deje de cumplir la regla 5.

    `verbo` trae su propio sustantivo —"descartar el renglón", "ajustar la
    cantidad del renglón"— en vez de dejarlo en la plantilla: pegarle "el
    renglón" a "ajustar la cantidad de" daba "de el renglón", y una bitácora
    que se lee mal se deja de leer.

    `nota` es lo que solo esa operación sabe y la bitácora necesita. Hoy la usa
    el ajuste, para dejar escrita **cada** cantidad que alguien tecleó: la
    columna guarda la última, y sin esto no habría forma de ver que se puso 100
    y se corrigió a 10 un minuto después.
    """
    negocio = cargar().negocio
    firma = quien(request)

    try:
        guardado = mover(negocio, firma)
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído es un hueco, no un 500
        log.exception("No se pudo %s %s", verbo, renglon_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "detalle": f"no se pudo {verbo} ({type(exc).__name__})",
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
        return JSONResponse(status_code=409, content={"ok": False, "detalle": choque})

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
        "renglon": _renglon_como_json(movido, precios),
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


def _armar(almacen: LecturaDelAlmacen, ventana: Ventana):
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
    """
    return armar_la_lista(almacen, ventana, reglas=reglas_configuradas())


def _como_json(
    guardado: PedidoSugeridoGuardado,
    precios: dict | None = None,
    corrida: CorridaDelLote | None = None,
    pedidos: tuple | None = None,
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
    """
    comparaciones = {
        r.renglon_id: comparar((precios or {}).get(r.renglon_id, ()), r.cantidad_a_pedir)
        for r in guardado.renglones
    }
    return {
        "ok": True,
        "pedido_sugerido_id": guardado.pedido_sugerido_id,
        "estado": guardado.estado,
        "fecha_de_ventas": guardado.ventana.hasta.isoformat(),
        "ventas_consideradas_desde": guardado.ventana.desde.isoformat(),
        "ventas_consideradas_hasta": guardado.ventana.hasta.isoformat(),
        "armado_en": guardado.armado_en.isoformat(),
        "cerrado_en": (
            guardado.cerrado_en.isoformat() if guardado.cerrado_en else None
        ),
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
        "particion": particion_como_json(
            partir(
                guardado.por_repartir,
                comparaciones,
                precios or {},
                puente_configurado(),
            )
        ),
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
                )
                for p in pedidos
            ]
        ),
        "puente": puente_como_json(puente_configurado()),
        "vistas": _vistas(),
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
    return {
        "pedido_id": pedido.pedido_id,
        "proveedor": pedido.proveedor,
        "nombre": pedido.nombre,
        "proveedor_id": pedido.proveedor_id,
        "tiene_puente": pedido.tiene_puente,
        "estado": pedido.estado,
        "es_borrador": pedido.es_borrador,
        "fue_enviado": pedido.fue_enviado,
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


def _renglon_como_json(
    renglon, precios=(), comparacion=None, corrida: CorridaDelLote | None = None
) -> dict:
    """Un renglón guardado, como la pantalla lo lee.

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
    }


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


def _sin_ventas() -> dict:
    """Ni una venta en el almacén. No es un error y no se guarda nada."""
    return {
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
    """Un borde caído, con su motivo y sin una sola lista vacía que lo disfrace."""
    return {**_sin_ventas(), "ok": False, "detalle": detalle}


def _vistas() -> list[dict]:
    """Las dos vistas como JSON, para que la pantalla no se sepa la regla.

    Viaja en la misma respuesta que la lista y no en una ruta aparte: es lo
    que hace que el interruptor no cueste ni una consulta más, y que la vista
    y los renglones que filtra vengan siempre de la misma lectura.
    """
    return [dataclasses.asdict(v) for v in VISTAS]


@app.get("/")
async def inicio():
    return FileResponse(ESTATICOS / "index.html")


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
