"""La pestaña de Buscar: un producto en los cuatro portales, cuando alguien pregunta.

Es la pestaña «Buscar» que Doyle tenía en su propia web. Se quedó sin nadie que
la viera el 2026-09-21: Doyle se mudó a atlas sin interfaz propia (su ADR 0008)
y escucha en `127.0.0.1:8383`, donde nadie de la farmacia llega. La dibuja
Continental; **quien busca sigue siendo Doyle** (regla 1 de `CLAUDE.md`).

**Mirar no es pedir.** Lo que se encuentra aquí no entra a la lista del día ni
se congela en `pedidos.precio_de_proveedor`: es una consulta para leer. Agregar
a mano un producto que no se vendió es otra decisión, con su propio ADR (0022).

Por eso esto **no empareja por EAN**, al revés que `precios.emparejar`: allá
se decide a quién comprarle y una caja de 60 contra una de 30 es una compra
equivocada; aquí una persona está mirando los resultados con la descripción
de cada uno a la vista, y buscar por nombre es justo para lo que sirve.

Funciones puras: lo que Doyle contestó + lo que el almacén sabe de esas claves
→ el JSON de la pantalla, **con las frases ya hechas** (la lección de los
tickets 15 y 21: la pantalla no compone lo que afirma). No toca la red, la
base ni el reloj.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal

from continental.almacen import Producto
from continental.doyle import (
    ESTADOS_PENDIENTES,
    BusquedaPedida,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
)
from continental.precios import (
    NOMBRES_DE_PROVEEDOR,
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_SELECTORES,
    VENTANA_DE_SESION_ABIERTA,
    existencia_a_numero,
    explicacion_del_motivo,
    motivo_del_error,
    nombre_del_proveedor,
    precio_a_numero,
    recortar_el_mensaje,
)

# --------------------------------------------------------------- los números

#: Cada cuánto pregunta la pantalla cómo va. La de Doyle preguntaba cada
#: segundo; aquí son dos saltos en loopback en vez de uno, y el piso medido de
#: un portal es de ~9 s, así que medio segundo más no se nota y son un tercio
#: menos de llamadas.
SONDEO_MS = 1500

#: Cuándo deja de preguntar. Los cuatro portales se consultan **a la vez**
#: —un hilo por proveedor en Doyle—, así que el techo es el del más lento:
#: 60-90 s medidos si se estiran los timeouts (ADR 0008 de Doyle). Tres minutos
#: es el doble del peor caso; pasado eso, algo se atoró y seguir preguntando
#: solo esconde que no va a llegar.
TOPE_SEGUNDOS = 180

#: Lo más largo que se deja buscar. Es lo que Doyle teclea en el buscador de
#: cada portal: un EAN son 13 dígitos y un nombre de SICAR rara vez pasa de 60.
#: Un párrafo pegado por error viajaría a cuatro portales ajenos con las
#: credenciales del dueño.
LARGO_MAXIMO_DEL_TERMINO = 100

#: El `job_id` que se deja preguntar. Doyle los hace con `uuid4().hex` y el
#: doble de pruebas con `trabajo-N`; los dos caben. Viaja pegado a una URL
#: de Doyle, así que nada de `/`, `.` ni `?`: con `..` la petición saldría de
#: `/api/buscar/`.
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------- el término


def termino_limpio(texto: str | None) -> str:
    """Lo que la persona escribió, sin espacios de sobra. `""` si no hay nada."""
    return " ".join((texto or "").split())


def motivo_para_no_buscar(termino: str) -> str | None:
    """Por qué no se le pide esto a Doyle, o `None` si se puede buscar."""
    if not termino:
        return "No hay nada que buscar: el campo está vacío."
    if len(termino) > LARGO_MAXIMO_DEL_TERMINO:
        return (
            f"Eso tiene {len(termino)} caracteres y lo más que se busca son "
            f"{LARGO_MAXIMO_DEL_TERMINO}: parece un texto pegado por error."
        )
    return None


#: Qué hacer cuando el término no sirve. Va aparte de `fallas.que_hacer`
#: porque no es una falla de nadie: es un campo por llenar.
QUE_HACER_CON_EL_TERMINO = (
    "Escribe el código de barras del producto, o parte de su nombre, y vuelve "
    "a buscar."
)


def job_id_valido(job_id: str) -> bool:
    """Si ese identificador se le puede preguntar a Doyle."""
    return bool(_JOB_ID.match(job_id or ""))


#: Doyle ya no tiene esa búsqueda (`doyle.BusquedaDesconocida`).
BUSQUEDA_OLVIDADA = (
    "Doyle ya no tiene esa búsqueda: guarda las búsquedas en memoria, y lo más "
    "probable es que se haya reiniciado a la mitad."
)
QUE_HACER_CON_LA_OLVIDADA = "Vuelve a buscar: se empieza de cero."


# ---------------------------------------------------- lo que dice cada portal

#: Cómo se lee cada estado de Doyle en la tarjeta del proveedor. El
#: vocabulario de Doyle (`pendiente`, `buscando`, `listo`...) no se traduce en
#: el JSON —viaja tal cual en `estado`—; esto es solo la etiqueta.
ETIQUETA_DEL_ESTADO: dict[str, str] = {
    "pendiente": "en espera",
    "buscando": "buscando…",
    "listo": "contestó",
    "reconocimiento": "no se sabe leer",
    "error": "sin dato",
}

#: Qué pasó con un proveedor, dicho para quien busca. Son los motivos de
#: `precios.MOTIVOS` que una búsqueda puede dar —no `no empareja` ni `varios
#: resultados`: aquí no se empareja—, con palabras de esta pantalla. Las de
#: `EXPLICACION_DEL_MOTIVO` son para un renglón de la lista ("se vuelve a
#: intentar" lo dice por el lote), y aquí nadie reintenta solo.
QUE_PASO: dict[str, str] = {
    SIN_RESULTADOS: "El portal buscó y no encontró nada con eso.",
    PORTAL_SIN_CONTESTAR: "El portal no contestó. Vuelve a buscar en un momento.",
    SESION_CADUCADA: (
        "La sesión de este proveedor caducó: ábrela con los botones de abajo y "
        "vuelve a buscar."
    ),
    VENTANA_DE_SESION_ABIERTA: (
        "Problema nuestro, no del portal: quedó abierta una ventana de sesión "
        "de este proveedor y bloquea su navegador. Ciérrala en el visor (o "
        "confírmala con «Ya entré») y vuelve a buscar."
    ),
    SIN_SELECTORES: "Doyle todavía no sabe leer la página de resultados de este portal.",
}


def _orden_de_los_proveedores(claves: Iterable[str]) -> list[str]:
    """Siempre en el mismo orden —NADRO, LEVIC, VICMA, QuePharma—, y después
    los que no se conozcan. Un proveedor desconocido se enseña, nunca se
    esconde (regla 4)."""
    claves = set(claves)
    conocidos = [c for c in NOMBRES_DE_PROVEEDOR if c in claves]
    return conocidos + sorted(claves - set(NOMBRES_DE_PROVEEDOR))


def motivo_del_proveedor(respuesta: RespuestaDeProveedor) -> str | None:
    """Por qué este proveedor no trajo resultados, o `None` si los trajo o
    todavía no termina.

    Reusa la lectura del error de `precios.motivo_del_error`: el mismo mensaje
    de Doyle tiene que querer decir lo mismo en la lista y aquí.
    """
    if respuesta.estado == "error":
        return motivo_del_error(respuesta.mensaje or "")
    if respuesta.estado == "reconocimiento":
        return SIN_SELECTORES
    if respuesta.estado == "listo" and not respuesta.filas:
        return SIN_RESULTADOS
    return None


def _pesos(valor: Decimal) -> str:
    return f"${valor:,.2f}"


def _cifra(valor: float | Decimal) -> str:
    """`12` y no `12.0`; el granel sí trae decimales."""
    numero = Decimal(str(valor))
    return str(numero.to_integral()) if numero == numero.to_integral() else f"{numero.normalize()}"


def cifras_de_la_fila(fila: FilaDeProveedor) -> list[str]:
    """Precio de compra, precio público y existencia, cada uno ya dicho.

    **Tal como los dio el portal.** Si el texto no se puede leer como número
    se enseña entre comillas y se dice, en vez de adivinar: `1.234,50` puede
    ser mil doscientos o uno con fracción. Y **no se restan**: el de compra y
    el de mostrador no están en la misma base de IVA, y Marlowe ya pintó una
    flecha al revés por restarlos (`CLAUDE.md`, trampas heredadas).
    """
    partes = []

    precio = precio_a_numero(fila.precio)
    if precio is not None:
        partes.append(f"Compra {_pesos(precio)}")
    elif fila.precio.strip():
        # "no se lee como precio" y no "no se pudo leer como número": un
        # `0.00` sí es un número, y tampoco es un precio (`precio_a_numero`).
        partes.append(f"Compra «{fila.precio.strip()}» (no se lee como precio)")
    else:
        partes.append("Sin precio de compra")

    publico = precio_a_numero(fila.precio_publico)
    if publico is not None:
        partes.append(f"Público {_pesos(publico)}")
    elif fila.precio_publico.strip():
        partes.append(f"Público «{fila.precio_publico.strip()}»")

    existencia = existencia_a_numero(fila.existencia)
    if existencia is None and fila.existencia.strip():
        # QuePharma dice su existencia con palabras ("NO DISPONIBLE"). Se
        # enseñan tal cual: son más claras que cualquier traducción, y no se
        # deduce de ellas un número que el portal no dio.
        partes.append(f"Existencia: {fila.existencia.strip()}")
    elif existencia is None:
        partes.append("No dijo existencia")
    elif existencia == 0:
        partes.append("Sin existencia")
    else:
        partes.append(f"Existencia {_cifra(existencia)}")

    return partes


def _sin_existencia(fila: FilaDeProveedor) -> bool:
    """Solo el cero que el portal **escribió**. Lo dicho con palabras no se
    lee como cero: no es lo mismo "no lo tiene" que "no dijo"."""
    existencia = existencia_a_numero(fila.existencia)
    return existencia is not None and existencia == 0


def lo_nuestro(productos: list[Producto]) -> dict | None:
    """Qué artículo nuestro lleva ese código de barras, dicho en una frase.

    `None` cuando ninguno: **no es "no está en el catálogo"**. QuePharma y
    VICMA muestran código interno y no el EAN, así que casi nunca van a
    empatar aunque el producto sí sea nuestro.
    """
    if not productos:
        return None
    if len(productos) == 1:
        [p] = productos
        return {
            "cuantos": 1,
            "frase": f"Nuestro: {p.descripcion} · {_cifra(p.existencia)} en existencia",
        }
    return {
        "cuantos": len(productos),
        "frase": (
            f"En nuestro catálogo hay {len(productos)} artículos con este código: "
            + "; ".join(f"{p.descripcion} ({_cifra(p.existencia)} en existencia)" for p in productos)
        ),
    }


def _nuestros_por_clave(nuestros: Iterable[Producto]) -> dict[str, list[Producto]]:
    por_clave: dict[str, list[Producto]] = {}
    for p in nuestros:
        por_clave.setdefault(p.clave.strip(), []).append(p)
    return por_clave


def _fila_como_json(fila: FilaDeProveedor, nuestros: Mapping[str, list[Producto]] | None) -> dict:
    return {
        "clave": fila.clave,
        "descripcion": fila.descripcion.strip() or "(el portal no trajo descripción)",
        "cifras": cifras_de_la_fila(fila),
        "sin_existencia": _sin_existencia(fila),
        "advertencia": recortar_el_mensaje(fila.advertencia),
        "nuestro": None if nuestros is None else lo_nuestro(nuestros.get(fila.clave.strip(), [])),
    }


def frase_del_total(respuesta: RespuestaDeProveedor) -> str | None:
    """Cuando el portal encontró más de lo que Doyle trae (corta en 20)."""
    if respuesta.total > len(respuesta.filas) and respuesta.filas:
        return (
            f"El portal encontró {respuesta.total}; aquí van las primeras "
            f"{len(respuesta.filas)}. Si no está, busca con el código de barras "
            "o con un nombre más completo."
        )
    return None


def proveedor_como_json(
    clave: str,
    respuesta: RespuestaDeProveedor,
    nuestros: Mapping[str, list[Producto]] | None,
) -> dict:
    motivo = motivo_del_proveedor(respuesta)
    etiqueta = (
        "sin resultados"
        if motivo == SIN_RESULTADOS and respuesta.estado == "listo"
        else ETIQUETA_DEL_ESTADO.get(respuesta.estado, respuesta.estado)
    )
    return {
        "proveedor": clave,
        "nombre": nombre_del_proveedor(clave),
        "estado": respuesta.estado,
        "etiqueta": etiqueta,
        "terminado": respuesta.estado not in ESTADOS_PENDIENTES,
        "motivo": motivo,
        "que_paso": None if motivo is None else QUE_PASO.get(motivo, explicacion_del_motivo(motivo)),
        # Lo que Doyle dijo, en su primera línea. Es un mensaje que Doyle
        # redactó para que una persona lo lea, no una excepción nuestra (ver el
        # comentario de `precios._LARGO_DEL_DETALLE`); se enseña aparte y en
        # chico, porque "qué pasó" ya lo dijo arriba con palabras de aquí.
        "detalle": recortar_el_mensaje(respuesta.mensaje) if motivo else "",
        "sesion_caducada": motivo == SESION_CADUCADA,
        "filas": [_fila_como_json(f, nuestros) for f in respuesta.filas],
        "frase_del_total": frase_del_total(respuesta),
    }


def claves_por_cruzar(estado: EstadoDeBusqueda) -> set[str]:
    """Qué claves hay que buscar en el catálogo: las de los resultados, y el
    término si parece un código de barras."""
    claves = {
        f.clave.strip()
        for r in estado.proveedores.values()
        for f in r.filas
        if f.clave.strip()
    }
    if estado.termino.strip().isdigit():
        claves.add(estado.termino.strip())
    return claves


def frase_de_la_busqueda(estado: EstadoDeBusqueda) -> str:
    """Cómo va, en una línea. Arriba de las cuatro tarjetas."""
    termino = f"«{estado.termino}»"
    respuestas = list(estado.proveedores.values())
    if not respuestas:
        return f"Buscando {termino}: Doyle todavía no dice a qué portales va a preguntar."
    cuantos = len(respuestas)
    contestaron = sum(1 for r in respuestas if r.estado not in ESTADOS_PENDIENTES)
    con_resultados = sum(1 for r in respuestas if r.estado == "listo" and r.filas)
    if not estado.terminada:
        return (
            f"Buscando {termino} en {cuantos} portales, todos a la vez: "
            f"{contestaron} de {cuantos} ya contestaron."
        )
    if not con_resultados:
        return f"Ningún portal trajo resultados para {termino}. Abajo, por qué, portal por portal."
    return f"{termino}: {con_resultados} de {cuantos} portales trajeron resultados."


def busqueda_como_json(
    estado: EstadoDeBusqueda,
    nuestros: Iterable[Producto] | None,
    catalogo_sin_leer: dict | None = None,
) -> dict:
    """Lo que la pantalla pinta. `nuestros` es `None` si el catálogo no se
    pudo leer: entonces ninguna fila dice nada de lo nuestro —ni sí ni no— y
    `catalogo_sin_leer` dice por qué."""
    por_clave = None if nuestros is None else _nuestros_por_clave(nuestros)
    termino = estado.termino.strip()
    return {
        "ok": True,
        "termino": estado.termino,
        "terminada": estado.terminada,
        "frase": frase_de_la_busqueda(estado),
        "lo_buscado": (
            lo_nuestro(por_clave.get(termino, []))
            if por_clave is not None and termino.isdigit()
            else None
        ),
        "catalogo_sin_leer": catalogo_sin_leer,
        "proveedores": [
            proveedor_como_json(clave, estado.proveedores[clave], por_clave)
            for clave in _orden_de_los_proveedores(estado.proveedores)
        ],
    }


def acuse_como_json(pedida: BusquedaPedida, termino: str) -> dict:
    """Lo que contesta `POST /api/buscar`: el trabajo, cómo sondearlo, y las
    cuatro tarjetas en espera para pintarlas de una vez."""
    en_espera = EstadoDeBusqueda(
        termino=termino,
        proveedores={
            c: RespuestaDeProveedor(proveedor=c, estado="pendiente")
            for c in pedida.proveedores
        },
    )
    return {
        **busqueda_como_json(en_espera, []),
        "job_id": pedida.job_id,
        "sondeo_ms": SONDEO_MS,
        "tope_segundos": TOPE_SEGUNDOS,
        "frase_al_tope": (
            f"Doyle no terminó en {TOPE_SEGUNDOS // 60} minutos y se dejó de "
            "preguntar. Lo que ya contestó se queda arriba; lo que sigue "
            "«buscando…» no llegó. Vuelve a buscar en un momento."
        ),
    }
