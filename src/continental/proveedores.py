"""El puente entre la clave de Doyle y el proveedor de SICAR. Funciones puras.

Este módulo existe porque **hasta el ticket 20 ese puente no existía en ningún
sitio**, y el ticket lo necesita para poder escribir una fila de
`pedidos.pedido`.

## Las dos identidades de un proveedor, y por qué son dos

| | Quién la pone | Dónde vive | Qué es |
|---|---|---|---|
| `nadro`, `levic`, `vicma`, `quepharma` | Doyle | `precios.NOMBRES_DE_PROVEEDOR`, `pedidos.precio_de_proveedor.proveedor` | a quién se le preguntó el precio |
| `1`, `10`, `8`, … | SICAR | `marts.dim_proveedor.proveedor_id` (el `pro_id`) | a quién se le ha comprado |

La comparación entera (tickets 12–15) habla en claves de Doyle: el precio
congelado se guarda por `(renglón, proveedor)` con la clave dentro. La tabla
`pedidos.pedido`, en cambio, nació con `proveedor_id bigint` apuntando a
`marts.dim_proveedor`. **Nada las cruzaba.**

## Qué se decidió, en una frase

**La identidad del pedido es la clave de Doyle; el `proveedor_id` de SICAR es
una correspondencia, y puede faltar.** El porqué completo —con las tres
opciones descartadas— está en `docs/decisiones/0008-*`. Lo que hay que tener
presente al leer este módulo:

- Se le pide a quien se le preguntó el precio. Si un pedido se identificara por
  el `proveedor_id`, un proveedor sin fila en SICAR no se podría pedir, y eso
  es exactamente lo que pasa hoy con **QuePharma**.
- El id, y no el nombre, es lo que sobrevive a que SICAR renombre. Por eso el
  puente guarda números y el nombre se lee de `dim_proveedor` cada vez, solo
  para pintarlo.

## Medido el 2026-09-19 contra `marts.dim_proveedor` en atlas

22 proveedores. `NADRO` es el 1, `VICMA` el 8 y `LEVIC` el 10. **QuePharma no
está**: la farmacia nunca le ha comprado, así que SICAR no tiene una fila para
él — y el ADR 0002 ya daba por probable que QuePharma quedara fuera.

Eso no es un caso raro que haya que tapar: es el caso que prueba que el puente
tiene que poder faltar. Un pedido a QuePharma se arma igual, con
`proveedor_id` en `NULL` y la pantalla diciendo por qué, en vez de un id
inventado o un cero (regla 4 de `CLAUDE.md`).

## Por qué el mapa vive en el YAML

`config/continental.yml` ya es "la configuración de esta instalación, sin
secretos". Cuatro parejas que no cambian nunca no valen una tabla: una tabla
aquí cuesta `crear_tablas.sql`, una migración, **volver a correr
`crear_rol.sql`**, `verificar_rol.sql` y `verificar.py` (ADR 0007 lo dice con
todas sus letras). Y no valen una columna sola, porque una columna guarda el
resultado del cruce, no la regla con la que se cruza.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from continental.config import cargar
from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor

log = logging.getLogger("continental")

#: La clave del YAML donde vive el mapa, bajo `pedido:`.
CLAVE_DEL_PUENTE = "proveedores_en_sicar"

#: Lo que se dice de un proveedor al que no le corresponde ningún `pro_id`.
#: **No es un error y no impide pedir**: es el estado ordinario de QuePharma,
#: a quien la farmacia nunca le ha comprado. Se escribe para que la pantalla lo
#: diga en vez de enseñar un hueco mudo.
SIN_PUENTE = "no está emparejado con ningún proveedor de SICAR"

#: Lo que se dice cuando el mapa sí lo tiene. Viaja hecho, como las certezas de
#: `comparacion.py`, para que el JavaScript escriba y no deduzca.
CON_PUENTE = "emparejado con el proveedor de SICAR"


def leer_el_puente(crudo: Mapping | None) -> dict[str, int]:
    """El mapa `clave de Doyle -> proveedor_id de SICAR`, ya revisado.

    Puro: recibe el diccionario tal como sale del YAML y no abre nada. La
    lectura del archivo la hace `puente_configurado`, que es la que se cachea.

    **Una entrada mal escrita se descarta con un aviso, no tumba el arranque.**
    Un `nadro: "uno"` deja a NADRO sin puente, que es un estado que el módulo
    ya sabe decir y que se ve en la pantalla —"no está emparejado"—. Abortar
    dejaría la farmacia sin pedido del día por una línea de configuración; y
    aceptarlo callado metería basura en una columna `bigint`.

    **Una clave que Doyle no conoce también se descarta con aviso.** El mapa es
    para los proveedores a los que se les pregunta el precio; una entrada
    `farmasana: 7` no cruzaría con nada y se quedaría ahí pareciendo que sí.
    """
    if not crudo:
        return {}

    puente: dict[str, int] = {}
    for clave, valor in dict(crudo).items():
        texto = str(clave).strip()
        if texto not in NOMBRES_DE_PROVEEDOR:
            log.warning(
                "config/continental.yml: `%s.%s` nombra a %r, que no es un "
                "proveedor de Doyle (%s). Se ignora: un puente hacia una clave "
                "que nadie consulta no cruza con nada y parece que sí.",
                CLAVE_DEL_PUENTE,
                texto,
                texto,
                ", ".join(sorted(NOMBRES_DE_PROVEEDOR)),
            )
            continue
        # `bool` es subclase de `int` en Python y un `nadro: true` del YAML
        # llegaría aquí como `1`. Se rechaza antes de mirar el número: "sí" no
        # es un proveedor_id, y guardarlo escribiría el pedido contra NADRO.
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            log.warning(
                "config/continental.yml: `%s.%s` vale %r y un proveedor_id de "
                "SICAR es un entero positivo. Se ignora, así que %s queda sin "
                "puente — se puede pedir igual y la pantalla lo dice.",
                CLAVE_DEL_PUENTE,
                texto,
                valor,
                nombre_del_proveedor(texto),
            )
            continue
        puente[texto] = int(valor)

    return puente


def puente_configurado() -> dict[str, int]:
    """El mapa del YAML de esta instalación. Lee configuración, no la base.

    `cargar()` está cacheado, así que esto no relee el archivo por petición.
    """
    return leer_el_puente(cargar().pedido.get(CLAVE_DEL_PUENTE))


def id_en_sicar(clave: str, puente: Mapping[str, int]) -> int | None:
    """El `proveedor_id` de SICAR de ese proveedor, o `None` si no hay.

    `None` es un dato y no un fallo: quiere decir *"a este proveedor la
    farmacia no le ha comprado nunca, así que SICAR no lo conoce"*. **Nunca un
    cero**, que es lo que haría un `.get(clave, 0)` distraído: un cero es un id
    que no existe y que aun así se puede escribir en una columna `bigint`, y a
    partir de ahí todo `join` contra `dim_proveedor` saldría vacío sin error.
    """
    return puente.get(clave)


def estado_del_puente(clave: str, puente: Mapping[str, int]) -> str:
    """`CON_PUENTE` o `SIN_PUENTE`, ya en la frase que la pantalla escribe."""
    return CON_PUENTE if id_en_sicar(clave, puente) is not None else SIN_PUENTE


def los_que_no_estan_en_sicar(puente: Mapping[str, int]) -> tuple[str, ...]:
    """Los proveedores de Doyle que hoy no tienen `pro_id`, en orden.

    Sirve para decirlo **una vez arriba** en vez de repetirlo en cada renglón:
    "QuePharma no está emparejado con SICAR" es una propiedad de la instalación
    y no de un producto.
    """
    return tuple(c for c in NOMBRES_DE_PROVEEDOR if id_en_sicar(c, puente) is None)


def puente_como_json(puente: Mapping[str, int]) -> list[dict]:
    """El puente como la pantalla lo lee: los cuatro, con su id o con su hueco.

    **Los cuatro siempre**, igual que la fila de la comparación enseña a los
    cuatro proveedores aunque solo dos hayan contestado: si solo salieran los
    emparejados, un proveedor sin puente se vería como un proveedor que no
    existe, y son dos cosas distintas (regla 4 de `CLAUDE.md`).
    """
    return [
        {
            "proveedor": clave,
            "nombre": nombre_del_proveedor(clave),
            "proveedor_id": id_en_sicar(clave, puente),
            "tiene_puente": id_en_sicar(clave, puente) is not None,
            "estado": estado_del_puente(clave, puente),
        }
        for clave in NOMBRES_DE_PROVEEDOR
    ]
