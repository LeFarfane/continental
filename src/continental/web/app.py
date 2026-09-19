"""El backend de Continental.

Dice si está vivo, quién está entrando, si los módulos contestan, arma el
pedido sugerido del día **y lo guarda**. Todavía no trae precios: eso son los
tickets 12 en adelante.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from continental import __version__
from continental.almacen import LecturaDelAlmacen
from continental.almacenamiento import (
    AlmacenamientoDelPedido,
    PedidoSugeridoGuardado,
    Ventana,
    dias_primera_vez_configurados,
    ventana_de_reposicion,
)
from continental.clasificacion import reglas_configuradas
from continental.config import cargar
from continental.doyle import ClienteDeDoyle
from continental.sugerido import DIAS_DE_RITMO, calcular_pedido_sugerido
from continental.vistas import VISTAS
from continental.web.dependencias import (
    obtener_almacen,
    obtener_almacenamiento,
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

    return _como_json(guardado)


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


def _armar(almacen: LecturaDelAlmacen, ventana: Ventana):
    """Las dos lecturas y el cálculo. Solo corre cuando la lista **no** existía.

    **Son dos ventanas distintas y este ticket alargó solo una.** La de
    reposición es la que llega por argumento —lo acumulado desde el corte— y la
    del ritmo son `DIAS_DE_RITMO` días fijos, que es cuánta historia se mira
    para estimar "a este ritmo, ¿cuánto dura lo que queda?". El porqué de los 28
    está junto a la constante, en `sugerido.py`.

    Hasta el ticket 08 la de reposición era un solo día y por tanto un
    subconjunto de la del ritmo: bastaba leer 28 días y recortar. **Eso dejó de
    valer**: una lista cerrada hace dos meses hace que la de reposición sea la
    más larga de las dos. Así que se lee **el rango unión** —el `min` de los dos
    extremos izquierdos— en una sola consulta y se recortan las dos en memoria.

    Recortar la del ritmo no es opcional aunque la lectura la contenga: el
    divisor de `_ritmo_diario` sale de las fechas que recibe, así que pasarle la
    lectura entera estiraría el rango, bajaría el ritmo e inflaría la cobertura
    — y lo urgente se hundiría al fondo de la lista.

    Una sola lectura y no dos: le ahorra a Postgres un recorrido de
    `fct_ventas` por carga y, sobre todo, evita que la reposición y el ritmo
    salgan de dos fotos tomadas en momentos distintos. Son del orden de 600
    filas por cada 28 días (21,035 líneas en 33 meses, medido sobre el respaldo
    del 2026-07-27).

    El `- 1` es el rango completo menos el propio día: de `hasta - 27` a
    `hasta` son 28 días, porque el almacén incluye los dos extremos.

    Las listas de anaqueles se leen aquí y se pasan hacia adentro: el cálculo es
    una función pura y no abre archivos, igual que no mira el reloj. `cargar()`
    está cacheado, así que esto no relee el YAML por petición.
    """
    desde_del_ritmo = ventana.hasta - dt.timedelta(days=DIAS_DE_RITMO - 1)
    leidas = almacen.ventas(min(ventana.desde, desde_del_ritmo), ventana.hasta)
    catalogo = almacen.catalogo()

    return calcular_pedido_sugerido(
        ventas=[v for v in leidas if ventana.desde <= v.fecha <= ventana.hasta],
        catalogo=catalogo,
        ventas_del_ritmo=[v for v in leidas if v.fecha >= desde_del_ritmo],
        reglas=reglas_configuradas(),
    )


def _como_json(guardado: PedidoSugeridoGuardado) -> dict:
    """La lista guardada, como la pantalla la lee.

    `fecha_de_ventas` se conserva con ese nombre y apunta a
    `ventas_consideradas_hasta`: es lo que la pantalla ya pinta como "Ventas
    del ...", y renombrarlo no agregaría nada. Al lado van los dos extremos de
    la ventana con su nombre completo, que es lo que se audita.

    `armado_en` y `cerrado_en` viajan en ISO **con zona**. Sin la zona, el
    navegador los leería como hora local y el contenedor corre en UTC: seis
    horas de diferencia, que es la misma trampa que ya costó 11.7 puntos de
    crecimiento inventados, solo que del lado del cliente.
    """
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
        # `esta_agotado` va explícito porque `asdict` no incluye propiedades, y
        # la regla —existencia conocida y en cero o negativa— tiene que vivir
        # en un solo lugar probado, no repetida en el JavaScript de la
        # pantalla. `renglon_id` y `estado` son del renglón guardado: el ticket
        # 10 los necesita para descartar uno.
        "renglones": [
            {
                **dataclasses.asdict(r.propuesto),
                "esta_agotado": r.propuesto.esta_agotado,
                "renglon_id": r.renglon_id,
                "estado": r.estado,
            }
            for r in guardado.renglones
        ],
        "sin_catalogo": guardado.sin_catalogo,
        # De la lista completa, no de la vista: la pregunta que responde es si
        # vale la pena ir a ponerles anaquel en SICAR. El porqué está en
        # `PedidoSugerido.sin_clasificar`.
        "sin_clasificar": guardado.sin_clasificar,
        "vistas": _vistas(),
    }


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
