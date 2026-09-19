"""Medicamento, abarrote o sin clasificar, leyendo el anaquel físico.

**El anaquel manda sobre la categoría.** El glosario de `CONTEXT.md` lo dice y
este módulo solo lo obedece: el anaquel "es un lugar, no una etiqueta de
catálogo, y por eso se le cree más que a la categoría". Un producto que está
físicamente en la vitrina se le compra al mismo proveedor aunque alguien lo
haya capturado hace tres años en una categoría de abarrote. La categoría es el
**segundo** camino a abarrote y solo habla cuando el anaquel no dice nada.

**Las listas no viven aquí.** Están en `config/continental.yml`
(`pedido.anaqueles_medicamento`, `pedido.anaqueles_abarrote`,
`pedido.categorias_abarrote`) y entran por argumento: `clasificar()` es una
función pura que se prueba sin tocar un archivo. `reglas_configuradas()` es la
capa delgada que las lee, y es lo único de este módulo que sabe que existe un
YAML. Duplicar las listas en el código haría que el archivo y el código
divergieran el día que el dueño agregue un anaquel — y nadie se enteraría,
porque las dos versiones seguirían clasificando algo.

**Los typos tampoco se arreglan aquí.** `dim_producto.ubicacion` ya viene
normalizada por dbt con el macro `normalizar_ubicacion` de farmacia-data: pasa
a mayúsculas, colapsa espacios, corrige los cinco typos conocidos del catálogo
y convierte el vacío en `SIN UBICACION`. Reimplementar esa tabla aquí sería
tener dos listas de correcciones que divergen en cuanto aparezca el sexto typo.
Lo que sí se garantiza de este lado es lo otro: **un anaquel que no se
reconoce cae en `sin clasificar` sin excepción y sin reventar**, aunque llegue
vacío, con basura o en `None`.

Nada se esconde nunca: `sin clasificar` es una respuesta, no un descarte. 688
de 3,429 artículos no tienen anaquel (medido al 2026-09) y un producto que
desaparece de la lista por eso es mercancía que va a faltar sin que nadie se
entere (regla 4 de `CLAUDE.md`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Las tres respuestas posibles, con el nombre exacto del glosario. Son
#: constantes y no cadenas sueltas porque viajan hasta el JavaScript de la
#: pantalla: un `"sin_clasificar"` escrito con guion bajo en un solo lugar no
#: falla, solo deja de marcar el renglón.
MEDICAMENTO = "medicamento"
ABARROTE = "abarrote"
SIN_CLASIFICAR = "sin clasificar"


@dataclass(frozen=True, slots=True)
class ReglasDeClasificacion:
    """Las tres listas del YAML, ya como argumento de una función pura.

    Son **prefijos**, no valores exactos: los anaqueles reales llevan número
    —de `PATENTE 1` a `PATENTE 6`, `GENERICO 1` a `GENERICO 4`, `BOTICA 1` a
    `BOTICA 3`, `VITRINA 1` a `VITRINA 3`— y otros no —`SUPER`, `CANASTA`,
    `REFRIGERADOR`—, así que una lista de valores exactos habría que editarla
    cada vez que la farmacia agrega un anaquel.

    Vacías por omisión, y eso importa: unas reglas sin cargar dejan **todo**
    en `sin clasificar`, que se muestra siempre y marcado. Cualquier otro
    default —"si no sé, es medicamento"— escondería abarrotes dentro de la
    vista de farmacia el día que alguien despliegue con el YAML a medias.
    """

    anaqueles_medicamento: tuple[str, ...] = ()
    anaqueles_abarrote: tuple[str, ...] = ()
    categorias_abarrote: tuple[str, ...] = ()


def clasificar(
    anaquel: str | None, categoria: str | None, reglas: ReglasDeClasificacion
) -> str:
    """Anaquel + categoría → `medicamento`, `abarrote` o `sin clasificar`.

    Pura: no lee el YAML, no toca la base y no tiene estado. Las listas entran
    por `reglas`.

    El orden de las preguntas **es** la decisión, y es la del glosario:

    1. ¿El anaquel es de medicamento? Entonces medicamento, aunque la
       categoría diga otra cosa.
    2. ¿El anaquel es de abarrote? Entonces abarrote, aunque la categoría diga
       otra cosa.
    3. El anaquel no dice nada (vacío, `SIN UBICACION`, mal escrito o
       desconocido). Solo aquí habla la categoría, y solo para abarrote: no
       hay lista de categorías de medicamento y no se inventa una, porque una
       etiqueta de catálogo no es evidencia suficiente para meter algo al
       pedido de farmacia.
    4. Nada de lo anterior: `sin clasificar`, que se muestra igual.

    El caso 3 es el que hace que `categorias_abarrote` exista: un producto con
    anaquel de abarrote ya se resolvió en el paso 2, así que la lista de
    categorías solo puede rescatar a alguno de los que no tienen anaquel. Esos
    dejan de contarse como `sin clasificar`, y está bien: seguir mostrándolos
    como "no sé" cuando el catálogo dice `ELECT` sería tirar el único dato que
    hay.
    """
    lugar = _normalizar(anaquel)
    etiqueta = _normalizar(categoria)

    if _casa_con_alguno(lugar, reglas.anaqueles_medicamento):
        return MEDICAMENTO
    if _casa_con_alguno(lugar, reglas.anaqueles_abarrote):
        return ABARROTE
    if _casa_con_alguno(etiqueta, reglas.categorias_abarrote):
        return ABARROTE
    return SIN_CLASIFICAR


def reglas_configuradas() -> ReglasDeClasificacion:
    """Las reglas de `config/continental.yml`. La capa delgada, y nada más.

    Existe para que `clasificar()` no tenga que leer un archivo y para que el
    YAML se lea en un solo lugar. Una lista que falte queda vacía en vez de
    tronar: sin `anaqueles_abarrote` todo lo de super cae en `sin clasificar`
    —feo, visible y arreglable— mientras que tronar aquí dejaría a la farmacia
    sin pedido del día por una línea que falta en el YAML.
    """
    from continental.config import cargar

    pedido = cargar().pedido
    return ReglasDeClasificacion(
        anaqueles_medicamento=_lista(pedido.get("anaqueles_medicamento")),
        anaqueles_abarrote=_lista(pedido.get("anaqueles_abarrote")),
        categorias_abarrote=_lista(pedido.get("categorias_abarrote")),
    )


def _lista(valores: Iterable[str] | None) -> tuple[str, ...]:
    """Lo que venga del YAML, como tupla de textos. `None` es una tupla vacía."""
    return tuple(str(v) for v in (valores or ()))


def _normalizar(valor: str | None) -> str:
    """Mayúsculas y espacios colapsados, para comparar peras con peras.

    `dim_producto.ubicacion` ya llega así desde dbt; esto es el cinturón para
    cuando la función se llama con un dato de otro lado —una prueba, una
    captura a mano, un CSV— y para que `None` no reviente. **No corrige
    typos**: esa tabla vive en el macro `normalizar_ubicacion` de
    farmacia-data y tener dos copias es tener dos verdades.
    """
    if not valor:
        return ""
    return " ".join(str(valor).upper().split())


def _casa_con_alguno(valor: str, prefijos: Iterable[str]) -> bool:
    """Si `valor` empieza con alguno de los prefijos, **en frontera**.

    La frontera es lo que evita el falso positivo, y no es un detalle: con un
    `startswith` pelón, `SUPERFICIE` sería abarrote y `ELECTROLITOS ORALES`
    —una categoría perfectamente posible en una farmacia— vendería suero oral
    como si compitiera contra la tienda de la esquina. La regla es que lo que
    sigue al prefijo o no existe, o **no es una letra**: así el número pega
    (`PATENTE 1`, y también `PATENTE1` si alguna vez llega sin espacio) y la
    palabra más larga no (`BOTICARIO`, `CANASTAS VARIAS`, `VITRINERO`).

    Un prefijo vacío se ignora en vez de casar con todo: una línea de más en
    el YAML no puede convertir el catálogo entero en abarrote.
    """
    return any(_casa(valor, _normalizar(p)) for p in prefijos)


def _casa(valor: str, prefijo: str) -> bool:
    if not prefijo or not valor.startswith(prefijo):
        return False
    resto = valor[len(prefijo) :]
    return not resto or not resto[0].isalpha()
