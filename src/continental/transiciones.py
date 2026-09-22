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

Este es el primer paso de la propuesta y **solo mueve el motivo de corregir
lo recibido** (ADR 0015) y el de recibir a mano lo que no está en tránsito.
Los demás —cancelar (`transito.motivo_para_no_cancelar`), reabrir
(`cierre.motivo_para_no_reabrir`), enviar
(`particion.motivo_para_no_enviar`)— siguen viviendo donde están hasta que un
ticket aparte los mueva aquí. Moverlos todos de un golpe habría mezclado el
arreglo del error visible (el botón que 409ea) con una reorganización mucho
más grande, y las dos no se pueden revisar por separado si llegan juntas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    from continental.almacenamiento import PedidoGuardado, RenglonGuardado


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
