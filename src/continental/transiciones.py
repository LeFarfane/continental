"""El motivo real de cada transición, en un solo lugar (propuesta 1 de la
revisión de arquitectura, 2026-09-21).

**Funciones puras y nada más.** Reciben lo que ya se leyó —un renglón, su
pedido, si una lista posterior ya lo atendió— y devuelven `None` si la
transición se puede hacer, o la frase en español de por qué no, con qué
hacer. No abren una conexión, no leen el YAML y no miran el reloj.

## Por qué existe

La revisión encontró que la regla de cada transición se escribía en 4 o 5
lugares distintos —el `WHERE` de la sentencia SQL, `dobles.py`, una bandera
del JSON en `app.py`, una frase `motivo_*`, y a veces el JavaScript— y que
podían divergir sin que ninguna prueba se pusiera roja. La encontró con un
caso concreto: `app.py` pintaba el botón "Corregir" con
`"se_puede_corregir": renglon.esta_recibido`, sin mirar que el pedido
siguiera `enviado`, que las piezas escritas fueran válidas, o que una lista
posterior ya hubiera atendido el producto —las mismas condiciones que
`almacenamiento._CORREGIR_LO_RECIBIDO` exige en su `WHERE`—. La pantalla
ofrecía un botón que iba a contestar 409, y el 409 adivinaba el motivo con
`antes.esta_recibido` y un texto genérico que mentía en el caso de "no viene
en camino".

Este módulo es la copia legible y probada de esas reglas. **El `WHERE` sigue
siendo el candado** —comprobar aquí y escribir después tiene una carrera en
medio, la misma razón de siempre—; lo de aquí es la bandera de la pantalla y
la frase del 409, nunca la garantía.

## Qué mueve, y qué no (a propósito)

El primer paso (2026-09-21) solo movió el motivo de corregir lo recibido (ADR
0015) y el de recibir a mano lo que no está en tránsito. Este segundo paso
mueve los tres que ese primer paso dejó anotados —cancelar, reabrir, enviar—
y agrega uno nuevo que antes no vivía en ningún lado como función pura: editar
un renglón (descartar, devolver a abierto, ajustar la cantidad, elegir
proveedor), que hasta ahora `continental.js` recalculaba a mano a partir del
estado de la lista y del renglón (ADR 0015, revisión de arquitectura).

- `motivo_para_no_cancelar` — movida de `transito.py`. El helper
  `motivo_para_no_cancelar_por_lo_recibido` **se quedó en `transito.py`**: es
  el único caso de esta ronda con una carrera real de import —`transito.py`
  ya lo usa internamente para la bandera `motivo_para_no_cancelar` de cada
  grupo de renglones en tránsito (`transito.py`, cerca de la línea 969)—, y
  moverlo también habría obligado a `transito.py` a importar de vuelta desde
  aquí. `motivo_para_no_cancelar`, aquí, importa ese helper de `transito.py`
  en vez de copiarlo: una sola dirección, `transiciones` → `transito`.
- `motivo_para_no_enviar` — movida de `particion.py`, junto con sus cuatro
  frases (`YA_ESTA_ENVIADO`, `YA_ESTA_CANCELADO`, `SIN_RENGLONES_QUE_ENVIAR`,
  `TOTAL_ENVEJECIDO`): no las usaba nada más en ese módulo.
- `motivo_para_no_reabrir` — movida de `cierre.py`. Sigue necesitando
  `fecha_en_palabras` de `transito.py` para las frases con fecha; se importa
  de ahí, no se copia. `cierre.py` conserva su propio import de
  `fecha_en_palabras` para todo lo demás que no se movió (las frases del
  cierre en sí).
- `motivo_para_no_editar` — nueva. Es la misma decisión que llevan, IDÉNTICA
  las cuatro, los `WHERE` de `almacenamiento._DESCARTAR`,
  `_AJUSTAR_LA_CANTIDAD` y `_ELEGIR_PROVEEDOR` —el renglón `abierto` y su
  lista `abierta`— y, con la condición del renglón invertida, el de
  `_DEVOLVER_A_ABIERTO` —el renglón `descartado` y su lista `abierta`—. Hasta
  este paso esa regla solo vivía en el `WHERE` y, copiada a mano y sin
  prueba, en `continental.js` (`editable = acciones.editable &&
  !r.esta_en_transito && !r.esta_cancelado && !r.esta_recibido`, más el
  `editable` de nivel de lista que se le pasaba a los renglones
  descartados). Ninguna de las dos copias había divergido del `WHERE`
  —se verificó al mover— pero nada lo garantizaba: la del JavaScript
  no la prueba ningún test de Python.

Ninguna de las tres movidas cambia una sola frase ni una sola condición: se
copian tal cual, con su prueba, y lo único nuevo es dónde viven.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from continental.almacenamiento import (
    ABIERTO,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    VENCIDO,
)
from continental.transito import fecha_en_palabras, motivo_para_no_cancelar_por_lo_recibido

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    from continental.almacenamiento import PedidoGuardado, PedidoSugeridoGuardado, RenglonGuardado


def motivo_para_no_corregir(
    renglon: "RenglonGuardado",
    pedido: "PedidoGuardado | None",
    atendido_despues: bool,
    piezas: int | None = None,
) -> str | None:
    """Por qué no se puede corregir cuánto llegó, o `None` si sí se puede.

    La misma decisión que el `WHERE` de `almacenamiento._CORREGIR_LO_RECIBIDO`,
    y **no la garantía**: sirve para no pintar un botón que 409earía y para
    contestar ese 409 con el motivo real en vez de adivinarlo.

    - `renglon` es el renglón tal como está guardado.
    - `pedido` es el suyo (`PedidoGuardado`). `None` quiere decir dos cosas
      distintas, y las dos bloquean igual —el `WHERE` exige `p.estado =
      'enviado'`, así que sin saberlo no se puede afirmar que sí—: que este
      renglón de verdad no tiene pedido (no debería pasar con algo recibido,
      pero la función no le apuesta a eso), o que quien llama no lo leyó —la
      misma convención que `_transito_del_renglon_como_json` ya usa para
      `pedido`: "sin él, no se afirma".
    - `atendido_despues` es si una lista de fecha posterior ya atendió el
      producto de este renglón —cerrada con él dentro, o vuelto a pedir,
      recibido o cancelado otra vez—: la misma pregunta que
      `almacenamiento.AlmacenamientoDelPedido.productos_atendidos_despues`
      contesta por lista entera. Quien llama la calcula una sola vez por
      lista y prueba la pertenencia del `producto_id` de este renglón.
    - `piezas` es lo que una persona está por escribir. Con `None` —la
      pregunta de la pantalla, "¿se podría ofrecer corregir, en general?"—
      no se juzga una cifra que todavía no existe: solo lo que no depende de
      ella. Con un número, se evalúa completo, como hace la ruta antes de
      escribir.
    """
    if not renglon.esta_recibido:
        return (
            "ese renglón no está recibido: no hay ninguna cifra que corregir. "
            "Recíbelo primero."
        )
    if pedido is None or not pedido.fue_enviado:
        return (
            "su pedido no está enviado, o no se pudo confirmar que lo esté: "
            "sin eso no hay recepción que corregir. Vuelve a cargar la "
            "página para ver cómo quedó."
        )
    if atendido_despues:
        return (
            "lo que faltó ya se volvió a proponer en una lista posterior que "
            "se cerró, o el producto ya se volvió a pedir: corregir la cifra "
            "ya no cambiaría nada que se vaya a pedir. Si llegó de más, "
            "descuéntalo en la lista de hoy."
        )
    if piezas is not None:
        if piezas <= 0:
            return (
                "cero no es recibir: si en verdad no llegó nada, la cifra no "
                "se corrige a cero. Anótalo aparte y avisa."
            )
        if renglon.piezas_recibidas == piezas:
            return "esa cifra ya es la que está guardada: decir lo mismo otra vez no mueve la firma."
    return None


def motivo_para_no_recibir_a_mano(
    renglon: "RenglonGuardado | None", pedido: "PedidoGuardado | None"
) -> str:
    """Por qué `_RECIBIR_A_MANO` no movió un renglón que no estaba ya recibido.

    Es la otra mitad de la puerta única de `recibir_a_mano` (ADR 0015): la de
    un renglón que **ya estaba** `recibido` o `recibido parcial` la contesta
    `motivo_para_no_corregir`, con su propio motivo (atendido después, cifra
    igual). Aquí solo llega lo que nunca estuvo recibido —no existe, no viene
    en camino, o su pedido dejó de estar enviado—, siempre con `renglon` como
    quedó **antes** de intentar el `UPDATE`: quien llama ya sabe que el
    intento falló y solo pregunta por qué.
    """
    if renglon is None:
        return (
            "no hay un renglón con ese número en este negocio. Vuelve a "
            "cargar la página."
        )
    if renglon.esta_recibido:
        # No debería llegar aquí: quien recibió esta respuesta se equivocó de
        # motivo. Se dice igual, sin tronar (regla 4): un texto vago es mejor
        # que ninguno.
        return "ese renglón ya está recibido: corrige la cifra en vez de recibirlo de nuevo."
    if not renglon.esta_en_transito:
        return (
            "ese renglón no viene en camino: no hay nada que recibir a mano. "
            "Vuelve a cargar la página para ver cómo quedó."
        )
    if pedido is None or not pedido.fue_enviado:
        return (
            "su pedido no está enviado, o no se pudo confirmar que lo esté: "
            "sin eso no hay nada en camino que recibir a mano. Vuelve a "
            "cargar la página para ver cómo quedó."
        )
    return (
        "ese renglón no se pudo recibir a mano. Vuelve a cargar la página "
        "para ver cómo quedó."
    )


# ============================================================ cancelar (25)
#
# Movida de `transito.py` el 2026-09-22 (paso 2 de la revisión de
# arquitectura). El helper `motivo_para_no_cancelar_por_lo_recibido` se quedó
# allá — ver el porqué en el docstring del módulo — y se importa aquí en vez
# de copiarse.


def motivo_para_no_cancelar(pedido: "PedidoGuardado", recibidos: int = 0) -> str | None:
    """Por qué no se puede cancelar, o `None` si sí se puede.

    La misma decisión que el `WHERE` de `_CANCELAR_EL_PEDIDO`, y **no la
    garantía**: sirve para no pintar un botón que contestaría 409. Desde el
    ticket 26 lo recibido sí existe, y quien llama dice cuántos renglones de ese
    pedido llegaron: si algo llegó, el pedido sí se capturó.
    """
    if pedido.fue_cancelado:
        return "ese pedido ya está cancelado"
    if pedido.es_borrador:
        return (
            "un borrador todavía no se le pidió a nadie: no hay nada que "
            "cancelar, se vuelve a partir"
        )
    if recibidos:
        return motivo_para_no_cancelar_por_lo_recibido()
    return None


# ============================================================= enviar (21)
#
# Movida de `particion.py` el 2026-09-22 (paso 2), con sus cuatro frases: no
# las usaba nada más en ese módulo.

#: El segundo clic de un botón que ya viajó, o dos pestañas abiertas en el
#: mostrador. No es un error de nadie y por eso se dice con palabras.
YA_ESTA_ENVIADO = "ese pedido ya está enviado: no se vuelve a enviar"

#: Un pedido cancelado (ticket 25, ADR 0013) no vuelve a enviarse: cancelar es
#: un final, no una vuelta a `borrador`. Lo que no llegó vuelve a proponerse en
#: la siguiente lista, y ahí se pide otra vez si hace falta.
YA_ESTA_CANCELADO = (
    "ese pedido se canceló: no se vuelve a enviar, y lo suyo vuelve a "
    "proponerse en la siguiente lista"
)

#: El pedido que se quedó sin renglones al volver a partir (ticket 20). Sigue
#: existiendo —el rol no tiene `DELETE`— con su total en `NULL`. Enviarlo diría
#: "capturé esto en el portal" sobre nada, y sus renglones ya se fueron a otro
#: pedido, así que ni siquiera hay qué pasar a `en tránsito`.
SIN_RENGLONES_QUE_ENVIAR = (
    "ese pedido se quedó sin renglones: no hay nada que capturar"
)

#: El total envejeció: alguien corrigió la cantidad de un renglón **después** de
#: armar el pedido, y `pedido.total_sin_iva` solo se reescribe al partir (hilo
#: abierto 13 de `HANDOVER.md`, que le dejó este caso a este ticket).
#:
#: Se NIEGA el envío en vez de recalcular en silencio, y las dos cosas se
#: consideraron. Recalcular cambiaría el número **después** de que el encargado
#: leyó el del botón: enviaría un total que nadie vio, que es peor que enseñar
#: uno viejo. Negarse manda a apretar "Volver a partir", que es un botón que ya
#: existe, cuesta un clic y deja el total y la hora de armado coherentes.
#:
#: Un total viejo importa porque es la cifra contra la que alguien va a comparar
#: la factura del proveedor: si no cuadra, nadie sabe si falta mercancía o si el
#: número estaba rancio.
TOTAL_ENVEJECIDO = (
    "alguien corrigió una cantidad después de armar este pedido, así que su "
    "total es de antes: vuelve a partir y se pone al día"
)


def motivo_para_no_enviar(
    pedido: "PedidoGuardado",
    renglones_dentro: int,
    total_envejecido: bool = False,
) -> str | None:
    """Por qué no se puede enviar este pedido, o `None` si sí se puede.

    Es la **misma decisión** que el `WHERE` de `almacenamiento._ENVIAR_EL_PEDIDO`
    y no la garantía: la garantía vive en la sentencia, porque comprobar en
    Python y escribir después tiene una carrera en medio. Lo que esto hace es
    poder **decirlo antes** —un botón apagado con su motivo al lado, en vez de
    un 409 que llega cuando ya se apretó—, y decirlo con las mismas dos
    condiciones para que las dos respuestas no se separen.

    **Que el total sea `None` no está en la lista, y es deliberado.** Un pedido
    con una línea sin precio se envía igual: la quinta casilla del ticket 20 dice
    que ese renglón se pide igual, y el precio de verdad lo ve el encargado en el
    portal mientras lo captura. Negarlo aquí volvería el precio de Doyle un
    requisito para operar la farmacia, que es lo contrario de la regla 4 —"sin
    dato" nunca es un cero, y tampoco es un bloqueo—. Lo que la pantalla sí hace
    es escribir "total sin saber" en vez de una cifra.

    **Que el total esté VIEJO sí lo está, y no es lo mismo.** `None` es "no se
    puede saber" y es honesto; una cifra con dos decimales calculada antes de
    que alguien corrigiera una cantidad es una mentira con formato de dato, y
    además la que alguien va a comparar contra la factura. Es el hilo abierto 13
    de `HANDOVER.md`, que le dejó este caso a este ticket. `total_envejecido` lo
    decide quien llama comparando `armado_en` con el `ajustada_en` de los
    renglones de dentro; la garantía vive en el `WHERE` de
    `almacenamiento._ENVIAR_EL_PEDIDO`, que lleva la misma condición.
    """
    if pedido.fue_enviado:
        return YA_ESTA_ENVIADO
    # Antes del conteo: un cancelado conserva sus renglones dentro —son su
    # historia— y sin esta línea saldría "se puede enviar".
    if pedido.fue_cancelado:
        return YA_ESTA_CANCELADO
    if renglones_dentro <= 0:
        return SIN_RENGLONES_QUE_ENVIAR
    if total_envejecido:
        return TOTAL_ENVEJECIDO
    return None


# ============================================================= reabrir (ADR 0016)
#
# Movida de `cierre.py` el 2026-09-22 (paso 2). Sigue necesitando
# `fecha_en_palabras` de `transito.py`; se importa de ahí y no se copia.
# `cierre.py` conserva su propio import de `fecha_en_palabras` para todo lo
# demás que no se movió.


def motivo_para_no_reabrir(
    lista: "PedidoSugeridoGuardado | None", ancla: "dt.date"
) -> str:
    """Por qué `reabrir` no movió la lista, leída **después** de intentarlo.

    La lectura es posterior al `UPDATE` que contestó cero filas, así que puede
    haber cambiado en medio (otra pestaña la reabrió): lo que se dice es cómo
    quedó, que es lo que la persona va a ver al recargar.

    `ancla` es el último día con ventas del almacén, el mismo que decidió si
    `reabrir` movía la fila (enmienda 2026-09-21 al ADR 0016). Si la lista
    sigue `cerrado` y es de hace más de un día, esa es la razón —se sabe sin
    otra lectura, comparando las dos fechas—; si no, la única otra forma de
    llegar aquí con la lista todavía `cerrado` es que ya se armó la
    siguiente.
    """
    recarga = " Vuelve a cargar la página para ver cómo quedó."
    if lista is None:
        return "No hay una lista con ese número en este negocio." + recarga
    if lista.estado == ABIERTO:
        return "Esta lista ya está abierta: alguien la reabrió antes." + recarga
    if lista.estado == VENCIDO:
        return (
            "Una lista vencida no se reabre: su día pasó sin que nadie la "
            "cerrara, y sus ventas ya se arrastran a la lista que siguió." + recarga
        )
    if lista.fecha_del_pedido < ancla - dt.timedelta(days=1):
        return (
            f"{fecha_en_palabras(lista.fecha_del_pedido).capitalize()} es de "
            "hace más de un día: ya no se puede deshacer el cierre. Solo se "
            "puede reabrir la lista de hoy o la de ayer." + recarga
        )
    return (
        "Ya no se puede reabrir: después de cerrarla ya se armó la lista "
        "siguiente, que empezó a contar las ventas donde ésta terminó. "
        "Reabrirla ahora dejaría dos listas abiertas con ventanas que se tocan."
        + recarga
    )


# ==================================================== editar un renglón
#
# Nueva (2026-09-22, paso 2): antes solo vivía en el `WHERE` de
# `almacenamiento._DESCARTAR`, `_DEVOLVER_A_ABIERTO`, `_AJUSTAR_LA_CANTIDAD` y
# `_ELEGIR_PROVEEDOR`, y una copia sin prueba en `continental.js`.

#: Las tres acciones que exigen el renglón **abierto** (y su lista abierta):
#: el mismo `WHERE`, letra por letra, en `_DESCARTAR`, `_AJUSTAR_LA_CANTIDAD`
#: y `_ELEGIR_PROVEEDOR`. `devolver_a_abierto` es la única que exige lo
#: contrario —el renglón **descartado**— y por eso no está en esta tupla.
ACCIONES_QUE_EXIGEN_RENGLON_ABIERTO = (
    "descartar",
    "ajustar_la_cantidad",
    "elegir_proveedor",
)

#: Y la que exige lo contrario.
DEVOLVER_A_ABIERTO = "devolver_a_abierto"

#: Todas las acciones que `motivo_para_no_editar` conoce, en el orden en que
#: `almacenamiento.py` las declara. Sirve para que quien llama con una
#: cadena mal escrita reciba un error claro y no un "sí se puede" por
#: accidente.
ACCIONES_DE_EDICION = ACCIONES_QUE_EXIGEN_RENGLON_ABIERTO + (DEVOLVER_A_ABIERTO,)


def _motivo_por_estado_del_renglon(renglon: "RenglonGuardado", accion: str) -> str:
    """La frase de por qué el renglón mismo ya no califica para `accion`.

    Distingue el estado para que el 409 diga la verdad y no un genérico —la
    misma cortesía que `continental.js` ya le daba a `quitar.title` antes de
    este paso, ahora hecha en Python y no adivinada dos veces.
    """
    verbo = {
        "descartar": "descartarlo",
        "ajustar_la_cantidad": "corregir su cantidad",
        "elegir_proveedor": "elegir a quién pedírselo",
    }[accion]
    if renglon.esta_en_transito:
        return f"ya se le pidió a un proveedor: {verbo} diría que nadie lo pidió."
    if renglon.esta_cancelado:
        return (
            "se dejó de esperar: vuelve a proponerse en la siguiente lista, "
            "no se edita aquí."
        )
    if renglon.esta_recibido:
        return "ya llegó: se pidió y se recibió, no se edita."
    if renglon.estado == RENGLON_DESCARTADO:
        return (
            "ese renglón está descartado: primero hay que devolverlo a la "
            "lista."
        )
    return f"ese renglón ya no está abierto: no se puede {verbo}."


def motivo_para_no_editar(
    renglon: "RenglonGuardado",
    lista: "PedidoSugeridoGuardado | None",
    accion: str,
) -> str | None:
    """Por qué no se puede `accion` este renglón, o `None` si sí se puede.

    La misma decisión que el `WHERE` de la sentencia de `almacenamiento.py`
    que le toca a `accion`, y **no la garantía** —la garantía sigue siendo el
    `WHERE`, comprobar aquí y escribir después tiene la misma carrera de
    siempre—. Sirve para no pintar un botón que 409earía (la bandera
    `se_puede_editar` del JSON) y para contestar ese 409 con el motivo real.

    `accion` es una de `ACCIONES_DE_EDICION`: `"descartar"`,
    `"ajustar_la_cantidad"` y `"elegir_proveedor"` exigen el renglón
    `abierto`; `"devolver_a_abierto"` exige lo contrario, `descartado`. Las
    cuatro exigen además la lista `abierta` — la condición que el
    2026-09-20 unificó en las cuatro sentencias (ver `almacenamiento.py`).

    `lista` es la lista guardada del renglón (`PedidoSugeridoGuardado`).
    `None` bloquea igual que una lista que no está abierta: sin poder leerla,
    no se puede afirmar que sí lo esté — la misma convención que
    `motivo_para_no_corregir` usa con `pedido=None`.
    """
    if accion not in ACCIONES_DE_EDICION:
        raise ValueError(f"acción de edición desconocida: {accion!r}")

    if accion == DEVOLVER_A_ABIERTO:
        if renglon.estado != RENGLON_DESCARTADO:
            return (
                "ese renglón no está descartado: no hay nada que devolver a "
                "la lista."
            )
    elif renglon.estado != RENGLON_ABIERTO:
        return _motivo_por_estado_del_renglon(renglon, accion)

    if lista is None or lista.estado != ABIERTO:
        return (
            "la lista ya no está abierta: lo que se iba a pedir ya se "
            "pidió. Vuelve a cargar la página para ver cómo quedó."
        )
    return None
