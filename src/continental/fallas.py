"""Qué dice la pantalla cuando algo falla o no hay nada (ticket 29).

Funciones puras: reciben lo que pasó —un motivo, una fecha, un instante— y
devuelven las frases. No leen el YAML, ni el reloj, ni tocan un borde; quien
las llama (`web/app.py`) les pasa todo. Viven aquí y no en el JavaScript por la
lección de los tickets 15 y 21: una frase que afirma algo y se compone en el
navegador se equivoca sin que ninguna prueba de Python se ponga roja.

Tres familias:

- **Qué hacer** (`que_hacer`): cada falla termina diciendo qué puede hacer la
  persona, o que no hay nada que hacer y a quién avisarle. Seis casos, uno por
  situación distinta; "vuelve a intentarlo" sobre un YAML mal escrito sería
  mandar a alguien a apretar un botón que nunca va a funcionar.
- **Las ventas** (`estado_de_las_ventas`): "no hubo ventas" es un hecho que el
  servidor **afirma** —leyó y no había—, distinto de "no pude leer". Y la lista
  del viernes vista un lunes por la mañana dice si eso es lo normal.
- **Los huecos** de la carga: el almacén que no contesta, los precios o los
  pedidos que no se leyeron, Doyle apagado. Cada uno dice que el vacío que se
  ve NO es un dato.

**El contacto no es un nombre.** `a_quien` entra por argumento y sale de
`config/continental.yml` (`a_quien_avisar`); si falta, se dice qué se hace
—avisarle a quien administra atlas— y no se inventa a nadie.
"""

from __future__ import annotations

import datetime as dt

from continental.transito import ZONA_DE_LA_FARMACIA, fecha_en_palabras

#: Lo que se dice cuando el YAML no trae a quién avisarle. Es una función, no
#: una persona: quien administre atlas el día que esto se lea.
A_QUIEN_AVISAR_POR_OMISION = "a quien administra atlas"

# ------------------------------------------------------------- qué hacer

#: Una lectura de las bases no contestó: el almacén (`marts`) o la base de
#: pedidos (`pedidos.*`). Volver a cargar arregla lo pasajero —un reinicio de
#: Postgres, la cadena de las 20:30 recreando tablas—; lo que no es pasajero
#: (el rol perdió su permiso) no se arregla desde el navegador.
AL_LEER = "al_leer"
#: Una escritura no contestó. **No se afirma si se guardó**: el `commit` pudo
#: pasar y la conexión caerse al contestar. Se manda a mirar.
AL_GUARDAR = "al_guardar"
#: Doyle no contesta. La lista no depende de él —los precios guardados se leen
#: de `pedidos`—, así que se trabaja igual; lo que no funciona es consultar.
DOYLE = "doyle"
#: `config/continental.yml` falta o está mal escrito. Desde el navegador no hay
#: nada que hacer, y decir "vuelve a intentarlo" sería mentir.
CONFIGURACION = "configuracion"
#: Una excepción que ninguna ruta atrapó: el 500 del manejador global.
SERVIDOR = "servidor"
#: La petición no tiene la forma que la ruta espera (el 422 de validación). En
#: la práctica es una pantalla vieja contra un servidor nuevo.
PETICION = "peticion"

CASOS = (AL_LEER, AL_GUARDAR, DOYLE, CONFIGURACION, SERVIDOR, PETICION)

_QUE_HACER = {
    AL_LEER: (
        "Vuelve a cargar la página en un minuto. Si sigue igual, desde aquí no "
        "hay nada más que hacer: avísale {a_quien}."
    ),
    AL_GUARDAR: (
        "Vuelve a cargar la página para ver cómo quedó y, si hace falta, "
        "inténtalo otra vez en un minuto. Si sigue fallando, avísale {a_quien}."
    ),
    DOYLE: (
        "Consultar o completar precios no va a funcionar hasta que Doyle "
        "vuelva. Levanta Doyle en la máquina donde corre, y si no sabes cómo, "
        "avísale {a_quien}."
    ),
    CONFIGURACION: (
        "Desde aquí no hay nada que hacer: avísale {a_quien} que hay que "
        "corregir config/continental.yml."
    ),
    SERVIDOR: (
        "Vuelve a cargar la página. Si vuelve a pasar, desde aquí no hay nada "
        "más que hacer: avísale {a_quien}. El detalle quedó en la bitácora del "
        "servidor."
    ),
    PETICION: (
        "Vuelve a cargar la página: puede que esté vieja. Si vuelve a pasar, "
        "avísale {a_quien}."
    ),
}


def que_hacer(caso: str, a_quien: str) -> str:
    """Qué puede hacer la persona ante esa falla, o a quién avisarle.

    Un caso que no existe **truena** (regla 4): una ruta con el caso mal
    escrito dejaría su falla sin frase, y eso se tiene que ver en una prueba y
    no en el mostrador.
    """
    if caso not in _QUE_HACER:
        raise ValueError(f"No hay un 'qué hacer' para el caso {caso!r}: son {CASOS}.")
    return _QUE_HACER[caso].format(a_quien=a_quien)


def falla_como_json(detalle: str, caso: str, a_quien: str) -> dict:
    """La forma de toda falla que viaja al navegador: `ok`, el motivo y qué hacer.

    `detalle` es el motivo **corto** —"no se pudo X (RuntimeError)"—, con el
    tipo de la excepción y nunca su texto (regla 5).
    """
    return {"ok": False, "detalle": detalle, "que_hacer": que_hacer(caso, a_quien)}


# ------------------------------------------------------ los huecos de la carga


def frase_del_hueco(detalle: str) -> str:
    """La lista entera no se pudo armar ni leer.

    Dice con todas sus letras que el vacío que se ve **no** es un dato: "hoy no
    se vendió nada" y "no pude leer" se ven idénticos si lo único que hay es una
    lista sin renglones, y confundirlos es que el pedido del día no se hace.
    """
    return (
        f"No se pudo armar el pedido sugerido: {detalle}. Que no se vea ningún "
        "renglón no quiere decir que no se vendió nada: quiere decir que no se "
        "pudo leer."
    )


def frase_de_precios_sin_leer() -> str:
    """Los precios guardados no se pudieron leer, y la lista se ve igual."""
    return (
        "No se pudieron leer los precios guardados: la tabla se ve sin precios, "
        "y eso no quiere decir que falten. La lista sirve para ver qué se "
        "vendió; para comparar y partir, espera a que se lean."
    )


def frase_de_pedidos_sin_leer() -> str:
    """No se supo en qué pedidos está partida la lista.

    Sin esto la pantalla la pintaba como "sin partir" y ofrecía partirla, sobre
    una lista que quizá ya se partió y se envió.
    """
    return (
        "No se pudo leer en qué pedidos está partida esta lista: puede que ya "
        "esté partida, o enviada, aunque aquí no se vea. No partas ni envíes "
        "hasta que se lea."
    )


def frase_de_doyle_caido(detalle: str) -> str:
    """Doyle no contesta: los precios de proveedor no se pueden consultar.

    `detalle` ya dice quién y por qué —"Doyle no responde (TimeoutError)"—, y la
    frase empieza con él: el recorrido del navegador cazó un "Doyle no responde
    (no contestó (RuntimeError))" con los paréntesis anidados.

    La lista **no** depende de Doyle —los precios que ya estaban guardados se
    leen de `pedidos`—, así que se dice que se ve igual. Lo que no hay son
    precios nuevos.
    """
    return (
        f"{detalle}: los precios de proveedor no están disponibles ahora. La "
        "lista se ve igual, con los precios que ya estaban guardados."
    )


def frase_de_la_lista_vacia(desde: dt.date, hasta: dt.date) -> str:
    """Una lista que se armó y se guardó **sin renglones**.

    No es "no se vendió nada": el último día de la ventana es `max(fecha)` del
    almacén y siempre tiene ventas. Lo que deja una lista vacía es que todo lo
    vendido en su ventana ya venía en camino de una lista anterior, y eso no se
    vuelve a proponer (ticket 24).
    """
    return (
        f"Se leyeron las ventas {_rango(desde, hasta)} y no dejaron nada que "
        "reponer: todo lo que se vendió esos días ya venía en camino de una "
        "lista anterior, y eso no se vuelve a proponer."
    )


def _rango(desde: dt.date, hasta: dt.date) -> str:
    if desde >= hasta:
        return "del " + fecha_en_palabras(hasta).removeprefix("el ")
    izquierda = fecha_en_palabras(desde).removeprefix("el ")
    if (desde.year, desde.month) == (hasta.year, hasta.month):
        izquierda = izquierda.split(" de ")[0]
    return f"del {izquierda} al " + fecha_en_palabras(hasta).removeprefix("el ")


# ------------------------------------------------------------- las ventas
#
# CUÁNDO LLEGAN LAS VENTAS AL ALMACÉN, que es lo único que este módulo sabe del
# mundo y lo que permite distinguir "no hay porque todavía no llega" de "no hay
# y ya debía haber". Está en `CLAUDE.md`, trampas heredadas: el respaldo de
# SICAR sube hacia las 18:51 **de lunes a viernes** y la cadena de
# farmacia-data corre a las 20:30. Lo del sábado —y lo del viernes por la
# tarde— llega el lunes en la noche.

#: Los días en que sube respaldo y corre la cadena: lunes a viernes.
DIAS_CON_CADENA = frozenset({0, 1, 2, 3, 4})
#: Desde qué hora se cuenta con lo que trajo la cadena del día. La cadena
#: arranca a las 20:30; las 22:00 son la hora del lote nocturno
#: (`continental-lote.timer`), que ya da por hecho que la cadena terminó.
#: Entre las 20:30 y las 22:00 no se afirma que falte nada.
HORA_EN_QUE_YA_LLEGARON = dt.time(22, 0)
#: La hora de la cadena, escrita como la lee una persona.
HORA_DE_LA_CADENA = "20:30"
_DOMINGO = 6


def _en_la_farmacia(instante: dt.datetime) -> dt.datetime:
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=dt.UTC)
    return instante.astimezone(ZONA_DE_LA_FARMACIA)


def ultimo_dia_que_ya_deberia_estar(ahora: dt.datetime) -> dt.date:
    """El día más reciente cuyas ventas ya debían estar en el almacén.

    Es el último día de lunes a viernes cuya cadena ya corrió, contado **en la
    hora de la farmacia** (UTC-6): las 03:00 UTC del martes son las 21:00 del
    lunes, y la cadena del lunes todavía no cuenta.

    **El reloj entra por argumento** y solo sirve para esto —decir si lo que
    hay es lo más reciente que puede haber—. Ninguna fecha de venta sale de
    aquí: la lista se sigue anclando en `max(fecha)`.
    """
    local = _en_la_farmacia(ahora)
    dia = local.date()
    if dia.weekday() in DIAS_CON_CADENA and local.time() >= HORA_EN_QUE_YA_LLEGARON:
        return dia
    dia -= dt.timedelta(days=1)
    while dia.weekday() not in DIAS_CON_CADENA:
        dia -= dt.timedelta(days=1)
    return dia


def _siguiente_cadena(ahora: dt.datetime) -> dt.date:
    """El día de la próxima cadena que todavía no se cuenta."""
    local = _en_la_farmacia(ahora)
    dia = local.date()
    if dia.weekday() in DIAS_CON_CADENA and local.time() < HORA_EN_QUE_YA_LLEGARON:
        return dia
    dia += dt.timedelta(days=1)
    while dia.weekday() not in DIAS_CON_CADENA:
        dia += dt.timedelta(days=1)
    return dia


def estado_de_las_ventas(
    ultima: dt.date | None, ahora: dt.datetime, a_quien: str
) -> dict:
    """Qué tan recientes son las ventas que el almacén **sí** contestó.

    Tres casos, y ninguno es "no pude leer" —ése es el hueco, con `ok: false`—:

    - **No hay ni una venta** (`ultima` es `None`): el almacén contestó y está
      vacío. Es un hecho, no una falla.
    - **Al día**: lo más reciente es lo más reciente que puede haber según el
      horario de la cadena. Un lunes por la mañana eso es el viernes: el
      domingo la farmacia cierra y lo del sábado llega el lunes en la noche.
      Se dice cuándo llega lo que sigue, y no hay nada que hacer.
    - **Falta un día que ya debía estar**: Continental **no sabe por qué**. Un
      día con cero filas no quiere decir "cerraron" —el 16 de septiembre, un
      feriado, se ve idéntico a un domingo—, así que se dicen las dos
      posibilidades y a quién avisarle si la farmacia sí abrió. La lista de
      abajo sigue sirviendo: es la del último día que sí llegó.
    """
    if ultima is None:
        return {
            "hay": False,
            "hasta": None,
            "al_dia": None,
            "frase": (
                "El almacén contestó y no tiene ni una venta registrada: no hay "
                "de qué armar la lista. No es una falla de lectura."
            ),
            "que_hacer": (
                "Si la farmacia ya vendió, sus ventas no han llegado al almacén: "
                f"avísale {a_quien}."
            ),
        }

    esperada = ultimo_dia_que_ya_deberia_estar(ahora)
    cuando = fecha_en_palabras(ultima)
    if ultima >= esperada:
        siguiente = _siguiente_cadena(ahora)
        hoy = _en_la_farmacia(ahora).date()
        llega = (
            f"esta noche ({fecha_en_palabras(siguiente)})"
            if siguiente == hoy
            else fecha_en_palabras(siguiente)
        )
        frase = (
            f"Las ventas más recientes del almacén son del {cuando.removeprefix('el ')}. "
            "Es lo más reciente que puede haber: lo que se vendió después llega "
            f"{llega}, después de la cadena de las {HORA_DE_LA_CADENA} (el "
            "respaldo de SICAR sube de lunes a viernes)."
        )
        entre = [ultima + dt.timedelta(days=d) for d in range(1, (hoy - ultima).days + 1)]
        if any(d.weekday() == _DOMINGO for d in entre):
            frase += " Los domingos la farmacia cierra."
        return {
            "hay": True,
            "hasta": ultima.isoformat(),
            "al_dia": True,
            "frase": frase,
            "que_hacer": None,
        }

    debia = fecha_en_palabras(esperada)
    return {
        "hay": True,
        "hasta": ultima.isoformat(),
        "al_dia": False,
        "frase": (
            f"Las ventas más recientes del almacén son del {cuando.removeprefix('el ')}, "
            f"y la cadena del {debia.removeprefix('el ')} ya debía traer las de ese "
            "día. Continental no sabe por qué no están: si la farmacia no abrió "
            "ese día, es normal; si abrió, no llegó el respaldo de SICAR o no "
            "corrió la cadena de farmacia-data."
        ),
        "que_hacer": (
            f"La lista de abajo es la del {cuando.removeprefix('el ')} y se puede "
            f"trabajar. Si la farmacia sí abrió {debia}, avísale {a_quien}."
        ),
    }
