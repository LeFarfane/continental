"""Qué se da por atendido al cerrar una lista, y cómo se deshace (ADR 0016).

**Funciones puras.** Reciben la lista guardada —y, para el botón de reabrir, si
la base dijo que se puede— y devuelven lo que la pantalla pinta: números y
frases hechas. No leen el reloj, ni el YAML, ni tocan un borde. Viven aquí y no
en el JavaScript por la lección de los tickets 15 y 21: una frase que afirma
algo y se compone en el navegador se equivoca sin que ninguna prueba se ponga
roja.

## Qué se pierde al cerrar

Cerrar es decir *ya se pidió lo que se iba a pedir* (`CONTEXT.md`): mueve el
corte, y la siguiente lista acumula desde el día siguiente (ticket 09). Lo que
esta lista tiene sin pedir se da por atendido. Con las ventas de su propia
ventana eso es la decisión de todos los días. Pero un renglón puede traer
**algo que no es de su ventana**:

- **lo que faltó de un parcial** (`piezas_que_faltaron`, ADR 0015), o
- **lo vendido mientras un pedido viajaba**, o lo de un cancelado
  (`ventas_desde` anterior a la ventana, ADRs 0012 y 0013), o
- **lo que volvió de la espera** (`piezas_pospuestas`, ADR 0025 y su enmienda
  del 2026-10-05): un renglón `abierto` que trae piezas que alguien mandó a
  esperar y que nadie pidió ni volvió a mandar a espera. Al cerrar se da por
  atendido como todo lo demás, y la frase lo dice **con desde cuándo esperaba**
  y con que reabrir deja de servir en cuanto se arma la lista siguiente.

Ésa es la segunda y última oportunidad de esas piezas: `_LO_YA_PEDIDO` ve la
lista cerrada con el producto y no lo vuelve a traer, esté el renglón
`abierto` o `descartado`. La confirmación lo enseña **antes**, renglón por
renglón y con sus piezas. **Avisa, no prohíbe**: hay días en que se decide no
pedirlo.

## Cómo se deshace

Reabrir solo vale mientras **ninguna lista se haya armado después**: es la
única condición en que nadie usó el corte que el cierre escribió. La regla
vive en el `WHERE` de `almacenamiento._REABRIR`; aquí solo se dice, con el sí o
el no que la base contestó.
"""

from __future__ import annotations

import datetime as dt

from continental.almacenamiento import (
    ABIERTO,
    CERRADO,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    SISTEMA,
    PedidoSugeridoGuardado,
    RenglonGuardado,
    Ventana,
)
from continental.transito import (
    ZONA_DE_LA_FARMACIA,
    fecha_en_palabras,
    frase_de_la_espera,
)

#: Los rótulos de los botones. Son de aquí y no del JavaScript: el de cerrar
#: cambia según haya algo que se perdería, y esa decisión es de Python.
CERRAR = "Cerrar la lista"
CERRAR_DE_TODOS_MODOS = "Cerrar de todos modos"
VOLVER = "Volver a la lista"
REABRIR = "Reabrir la lista"

#: Lo que la confirmación dice siempre sobre el deshacer. Sin fecha ni hora:
#: cuándo se arma la siguiente depende de quién abra la pantalla primero, o del
#: lote de la noche.
DESHACER = (
    "Si la cierras por error, puedes reabrirla mientras no se arme la lista "
    "siguiente —esta noche con el lote, o cuando alguien abra la pantalla con "
    "ventas nuevas—."
)

#: Lo que se dice cuando no se pudo leer el resumen. Cerrar sigue siendo
#: posible: el resumen avisa, no es un permiso.
SIN_RESUMEN = (
    "No se pudo leer qué quedaría sin pedir. La lista se puede cerrar igual, "
    "pero sin este resumen: revísala antes."
)


def _piezas(n: int) -> str:
    return f"{n} pieza" if n == 1 else f"{n} piezas"


def _renglones(n: int) -> str:
    return f"{n} renglón" if n == 1 else f"{n} renglones"


def trae_ventas_de_otros_dias(renglon: RenglonGuardado, ventana: Ventana) -> bool:
    """Si el renglón trae ventas de antes de la ventana de su lista.

    Un `ventas_desde` anterior al principio de la ventana es lo que retuvo un
    pedido en camino (ADR 0012) o lo que devuelve un cancelado (ADR 0013). Uno
    posterior ("solo cuenta desde el viernes") no trae nada de otro día: lo
    anterior ya venía en un pedido.
    """
    desde = renglon.propuesto.ventas_desde
    return desde is not None and desde < ventana.desde


def trae_piezas_de_la_espera(renglon: RenglonGuardado) -> bool:
    """Si es un renglón **abierto** que trae piezas que volvieron de la espera.

    Solo `abierto`: uno `pospuesto` al cerrar ya tiene adónde ir (la siguiente
    lista lo trae otra vez) y volver a mandarlo a espera es justo la salida que
    el aviso ofrece. Uno `descartado` es una decisión de una persona y por sí
    solo no se señala (el ticket pide solo los `abierto`).
    """
    return renglon.estado == RENGLON_ABIERTO and renglon.propuesto.piezas_pospuestas > 0


def se_perderia(renglon: RenglonGuardado, ventana: Ventana) -> bool:
    """Si cerrar daría por atendido algo de este renglón que no es de esta lista.

    Solo lo `abierto` y lo `descartado`: lo que está en tránsito o llegó ya se
    pidió, y lo cancelado vuelve por su cuenta (ADR 0013). **Y un `pospuesto`
    tampoco** (ADR 0025): ya tiene adónde ir —la siguiente lista que se arme lo
    trae, con sus piezas—, así que cerrar no lo pierde. Señalarlo mandaría a
    "arreglar" justo lo que una persona decidió a propósito.
    """
    if renglon.estado not in (RENGLON_ABIERTO, RENGLON_DESCARTADO):
        return False
    return (
        bool(renglon.propuesto.piezas_que_faltaron)
        or trae_ventas_de_otros_dias(renglon, ventana)
        or trae_piezas_de_la_espera(renglon)
    )


def lo_que_se_perderia(lista: PedidoSugeridoGuardado) -> tuple[RenglonGuardado, ...]:
    """Los renglones que traen algo de otro pedido y se darían por atendidos."""
    return tuple(r for r in lista.renglones if se_perderia(r, lista.ventana))


def lo_que_volvio_de_la_espera(
    lista: PedidoSugeridoGuardado,
) -> tuple[RenglonGuardado, ...]:
    """De lo que se perdería, lo que volvió de la espera (para la bitácora del cierre automático)."""
    return tuple(r for r in lista.renglones if trae_piezas_de_la_espera(r))


def frase_de_lo_que_se_perderia(renglon: RenglonGuardado, ventana: Ventana) -> str:
    """Un renglón que se perdería, dicho con sus piezas y por qué.

    Las piezas son `cantidad_a_pedir`: lo que se iba a pedir, con la
    corrección de la persona si la hubo. No se parte en "de esta ventana" y "de
    otros días" porque el renglón no guarda cuántas de sus ventas son de cada
    día; lo que sí guarda —las que faltaron— se dice con su número.
    """
    nombre = renglon.propuesto.descripcion or renglon.propuesto.clave or "Sin nombre"
    piezas = renglon.cantidad_a_pedir
    if renglon.esta_descartado:
        cabeza = f"{nombre}: descartado (eran {_piezas(piezas)})."
    else:
        cabeza = f"{nombre}: {_piezas(piezas)} sin pedir."

    que_trae = []
    faltaron = renglon.propuesto.piezas_que_faltaron
    if faltaron:
        cuales = "que faltó" if faltaron == 1 else "que faltaron"
        que_trae.append(f"{_piezas(faltaron)} {cuales} en un pedido anterior")
    if trae_ventas_de_otros_dias(renglon, ventana):
        que_trae.append(
            f"lo vendido desde {fecha_en_palabras(renglon.propuesto.ventas_desde)} "
            "mientras venía en camino"
        )
    if trae_piezas_de_la_espera(renglon):
        pospuestas = renglon.propuesto.piezas_pospuestas
        edad = frase_de_la_espera(
            renglon.espera_desde,
            renglon.listas_en_espera,
            pospuestas,
        )
        cuales = "que volvió" if pospuestas == 1 else "que volvieron"
        de_la_espera = f"{_piezas(pospuestas)} {cuales} de la espera"
        que_trae.append(f"{de_la_espera} ({edad})" if edad else de_la_espera)
    frase = (
        f"{cabeza} Trae {' y '.join(que_trae)}: si se cierra así, ninguna lista "
        "vuelve a traerlas."
    )
    if trae_piezas_de_la_espera(renglon):
        # Lo que el dueño pidió que se diga (ADR 0025, enmienda 2026-10-05):
        # reabrir sirve solo mientras no se arme la lista siguiente, y a esa
        # altura lo de la espera ya se dio por atendido.
        frase += (
            " Si te equivocas, reabrir deja de servir en cuanto se arma la "
            "lista siguiente; para que siga esperando, mándalo a espera otra "
            "vez antes de cerrar."
        )
    return frase


def _frase_de_lo_normal(lista: PedidoSugeridoGuardado, sin_pedir: int, en_borrador: int) -> str:
    """Lo que dice la confirmación siempre: cuánto queda sin pedir."""
    if sin_pedir == 0:
        cabeza = (
            "Todo lo de esta lista ya se pidió, se descartó o está en "
            "espera."
            if lista.pospuestos
            else "Todo lo de esta lista ya se pidió o se descartó."
        )
    elif sin_pedir == 1:
        cabeza = (
            "Queda 1 renglón sin pedir: al cerrarla se da por atendido y la "
            "siguiente lista no lo vuelve a proponer."
        )
    else:
        cabeza = (
            f"Quedan {sin_pedir} renglones sin pedir: al cerrarla se dan por "
            "atendidos y la siguiente lista no los vuelve a proponer."
        )
    if en_borrador == 1:
        cabeza += (
            " Uno de ellos está en un pedido en borrador que no se ha marcado "
            "como enviado."
        )
    elif en_borrador > 1:
        cabeza += (
            f" {en_borrador} de ellos están en un pedido en borrador que no se "
            "ha marcado como enviado."
        )
    if lista.pospuestos:
        # Lo que pasa a mañana NO se pierde al cerrar (ADR 0025): se dice, para
        # que quien cierra sepa que esos renglones sí vuelven.
        cabeza += (
            " 1 renglón está en espera y la siguiente lista lo trae."
            if lista.pospuestos == 1
            else f" {lista.pospuestos} renglones están en espera y la "
            "siguiente lista los trae."
        )
    siguiente = lista.ventana.hasta + dt.timedelta(days=1)
    return (
        f"{cabeza} La siguiente arranca con las ventas "
        f"{fecha_en_palabras(siguiente).replace('el ', 'del ', 1)}. No se borra nada."
    )


def al_cerrar(lista: PedidoSugeridoGuardado) -> dict:
    """Lo que la ventana de confirmación enseña, hecho. La pantalla solo lo pinta.

    - `sin_pedir`: los renglones `abierto` —lo que se da por atendido—.
    - `en_borrador`: de ésos, los que están en un pedido que no se envió (un
      renglón `abierto` con pedido es de un borrador: enviar lo pondría en
      tránsito, cancelar en cancelado).
    - `se_perderian`: los que traen algo de otro pedido, con sus piezas.
    - `boton`: "Cerrar de todos modos" si algo se perdería; `None` si la lista
      ya no está abierta (otra pestaña la cerró, o se venció).
    """
    base = {
        "ok": True,
        "pedido_sugerido_id": lista.pedido_sugerido_id,
        "titulo": "¿Cerrar la lista?",
        "volver": VOLVER,
    }
    if lista.estado != ABIERTO:
        return {
            **base,
            "se_puede_cerrar": False,
            "frase": (
                "Esta lista ya no está abierta: otra pestaña la cerró, o su día "
                "pasó. Vuelve a cargar la página para ver cómo quedó."
            ),
            "sin_pedir": 0,
            "en_borrador": 0,
            "se_perderian": [],
            "aviso": None,
            "que_hacer_con_lo_que_se_perderia": None,
            "deshacer": None,
            "boton": None,
        }

    abiertos = [r for r in lista.renglones if r.estado == RENGLON_ABIERTO]
    en_borrador = sum(1 for r in abiertos if r.pedido_id is not None)
    perdidas = lo_que_se_perderia(lista)
    return {
        **base,
        "se_puede_cerrar": True,
        "frase": _frase_de_lo_normal(lista, len(abiertos), en_borrador),
        "sin_pedir": len(abiertos),
        "en_borrador": en_borrador,
        "se_perderian": [
            {
                "renglon_id": r.renglon_id,
                "clave": r.propuesto.clave,
                "descripcion": r.propuesto.descripcion,
                "estado": r.estado,
                "piezas": r.cantidad_a_pedir,
                "piezas_que_faltaron": r.propuesto.piezas_que_faltaron,
                "piezas_de_la_espera": (
                    r.propuesto.piezas_pospuestas if trae_piezas_de_la_espera(r) else 0
                ),
                "ventas_desde": (
                    r.propuesto.ventas_desde.isoformat()
                    if trae_ventas_de_otros_dias(r, lista.ventana)
                    else None
                ),
                "frase": frase_de_lo_que_se_perderia(r, lista.ventana),
            }
            for r in perdidas
        ],
        "aviso": (
            None
            if not perdidas
            else (
                f"{_renglones(len(perdidas))} "
                + ("trae" if len(perdidas) == 1 else "traen")
                + " algo de un pedido anterior que se perdería al cerrar:"
            )
        ),
        "que_hacer_con_lo_que_se_perderia": (
            None
            if not perdidas
            else (
                "Si lo necesitas, vuelve a la lista y pídelo antes de cerrar. "
                "Cerrar sigue siendo posible: puede que se haya decidido no "
                "pedirlo."
            )
        ),
        "deshacer": DESHACER,
        "boton": CERRAR_DE_TODOS_MODOS if perdidas else CERRAR,
    }


def al_cerrar_sin_resumen(detalle: str, que_hacer: str) -> dict:
    """La falla de leer el resumen. `ok: false`, y aun así se puede cerrar."""
    return {
        "ok": False,
        "detalle": detalle,
        "frase": SIN_RESUMEN,
        "que_hacer": que_hacer,
        "boton": CERRAR,
        "volver": VOLVER,
    }


# ------------------------------------------------------------ la reapertura


def reapertura(
    lista: PedidoSugeridoGuardado,
    se_puede: bool | None,
    ancla: dt.date | None = None,
    falla: dict | None = None,
) -> dict | None:
    """El botón de reabrir y su frase, o `None` si la lista no está cerrada.

    `se_puede` es lo que contestó la base (`se_puede_reabrir`), con la misma
    regla que el `WHERE`. `None` con `falla` es "no se pudo saber": no hay
    botón, y se dice qué hacer (regla 4). **Nunca se pinta un botón que
    contestaría 409**: sin la respuesta de la base, no se ofrece.

    `ancla` es el último día con ventas del almacén, el mismo que se le pasó a
    `se_puede_reabrir` (enmienda 2026-09-21 al ADR 0016). Con `se_puede`
    falso y sin `falla`, sirve para no decir "ya se armó la lista siguiente"
    cuando en realidad la lista es de hace más de un día y esa —no una
    siguiente que no existe— es la razón; es opcional y `None` cae en el
    texto de antes, que sigue siendo cierto cuando sí se armó la siguiente.
    """
    if lista.estado != CERRADO:
        return None
    if se_puede:
        return {
            "se_puede": True,
            "boton": REABRIR,
            "frase": (
                "¿Se cerró por error? Se puede reabrir hasta que se arme la "
                "lista siguiente. Reabrir no deshace lo que ya se envió ni lo "
                "que ya se recibió: solo vuelve a dejar la lista abierta."
            ),
        }
    if falla is not None:
        return {
            "se_puede": False,
            "boton": None,
            "frase": "No se pudo saber si esta lista se puede reabrir.",
            "detalle": falla.get("detalle"),
            "que_hacer": falla.get("que_hacer"),
        }
    if ancla is not None and lista.fecha_del_pedido < ancla - dt.timedelta(days=1):
        return {
            "se_puede": False,
            "boton": None,
            "frase": (
                f"{fecha_en_palabras(lista.fecha_del_pedido).capitalize()} es "
                "de hace más de un día: ya no se puede deshacer el cierre."
            ),
        }
    return {
        "se_puede": False,
        "boton": None,
        "frase": (
            "Ya no se puede reabrir: después de cerrarla ya se armó la lista "
            "siguiente, que empezó a contar las ventas donde ésta terminó."
        ),
    }


def frase_de_la_reapertura(quien: str | None, cuando: dt.datetime | None) -> str | None:
    """La firma de la última reapertura, en la hora de la farmacia. `None` si no hubo.

    Un instante sin zona se toma como UTC, igual que en `transito`: así lo
    deja un driver que pierde la zona de un `timestamptz`.
    """
    if quien is None or cuando is None:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=dt.UTC)
    local = cuando.astimezone(ZONA_DE_LA_FARMACIA)
    return f"Se reabrió {fecha_en_palabras(local.date())} a las {local:%H:%M}; lo firmó {quien}."


def frase_del_cierre(quien: str | None, cuando: dt.datetime | None) -> str | None:
    """Quién cerró esta lista la última vez, y cuándo (migración 0013). `None` si no se sabe.

    `None` cubre dos casos que esta frase no distingue —la lista sigue
    abierta, o se cerró antes de la migración 0013— y ninguno de los dos es
    "hubo un cierre y no se sabe quién": es más honesto callar la frase entera
    que afirmar una firma que no existe.

    `quien == SISTEMA` (decisión del dueño, 2026-09-27) se dice distinto de un
    correo: "se cerró sola" y no "la cerró sistema", que leería como si
    `sistema` fuera una persona con ese nombre.
    """
    if quien is None or cuando is None:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=dt.UTC)
    local = cuando.astimezone(ZONA_DE_LA_FARMACIA)
    dicho = f"{fecha_en_palabras(local.date())} a las {local:%H:%M}"
    if quien == SISTEMA:
        return f"Se cerró sola {dicho}, al abrirse la lista del día siguiente."
    return f"Se cerró {dicho}; lo firmó {quien}."


# `motivo_para_no_reabrir` se movió a `transiciones.py` el 2026-09-22 (paso 2
# de la revisión de arquitectura). Nada más en este módulo la usaba; quien la
# necesite, la importa de `continental.transiciones`.
