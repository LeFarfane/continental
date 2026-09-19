"""Las dos vistas del pedido sugerido: qué deja ver cada una.

**El interruptor esconde abarrotes y nada más.** "Medicamentos y botica" trae
lo de farmacia y **también lo que no se pudo clasificar**; "todo lo vendido"
trae las tres cosas. Ese `sin clasificar` en las dos listas es la decisión
entera de este módulo: 688 de 3,429 artículos no tienen anaquel (medido al
2026-09), y esconderlos por no encajar en el filtro sería mercancía que va a
faltar sin que nadie se entere —el encargado lo descubriría frente al anaquel
vacío, que es tarde— (regla 4 de `CLAUDE.md`, glosario de `CONTEXT.md`).

**La regla vive aquí y el filtro se aplica en el navegador.** Son dos cosas
distintas y esa separación es a propósito:

- *Por qué no un parámetro en la ruta.* El interruptor es una manera de mirar
  la misma lista, no otra pregunta al almacén. Cada llamada a
  `/api/pedido-sugerido` lee el catálogo completo (3,429 filas) más 28 días de
  ventas (~600 filas), así que un ida y vuelta por cada vez que alguien mueve
  el interruptor le cuesta a Postgres una consulta entera para devolver un
  subconjunto de lo que ya estaba en la pantalla. Y hay algo peor que el
  costo: dos lecturas pueden caer en momentos distintos, así que las dos
  vistas podrían mostrar listas que no coinciden —un renglón en una y no en la
  otra— sin que nadie pueda decir cuál de las dos tiene razón. Una lectura, una
  lista, dos maneras de verla.
- *Por qué la regla no se escribe en el JavaScript.* Porque entonces viviría en
  el único archivo que ninguna prueba de Python mira, y el día que alguien
  quisiera "limpiar" la vista de medicamentos quitaría los `sin clasificar` sin
  que nada se pusiera rojo. Así que las clasificaciones de cada vista viajan
  **como dato** dentro de la respuesta de la ruta y el JavaScript solo pregunta
  si la del renglón está en la lista. La regla se prueba en Python; la pantalla
  la obedece.

**La lista larga es el otro dato de la decisión.** El sugerido trae tantos
renglones como productos distintos se vendieron, y con el ticket 09 la ventana
dejará de ser un día para acumular desde el último cierre —con el hueco de fin
de semana, hasta 2.5 días—. Mandar la lista completa una vez y filtrarla en el
navegador es el camino que **no** crece con el número de veces que alguien
mueve el interruptor.

**Dónde se recuerda la elección.** En el navegador (`localStorage`), no aquí.
Hoy Continental no guarda nada —las tablas son el ticket 07— y no hay sesión de
usuario: el correo de `Cf-Access-Authenticated-User-Email` es una firma, no un
permiso ni un lugar donde colgar preferencias (regla 3 de `CLAUDE.md`).
Guardarlo del lado del servidor exigiría una tabla y un concepto de "usuario"
que el módulo todavía no tiene, para una preferencia que cabe en una cadena.
El precio se paga y se dice: la elección es **por navegador**, así que el mismo
encargado en el teléfono y en la computadora del mostrador puede tener vistas
distintas. Para una preferencia de lectura eso no cuesta nada; el día que haya
que compartirla entre dispositivos, se mueve a las tablas del ticket 07.
"""

from __future__ import annotations

from dataclasses import dataclass

from continental.clasificacion import ABARROTE, MEDICAMENTO, SIN_CLASIFICAR


@dataclass(frozen=True, slots=True)
class Vista:
    """Una manera de mirar la lista: un nombre y qué clasificaciones deja ver.

    Es un **dato**, no un filtro: no recibe renglones, no consulta el almacén
    y no lee archivos. Quien pinta la lista se queda con los renglones cuya
    clasificación está en `clasificaciones`, y esa es toda la operación. Tener
    aquí un método que filtrara sería tener una segunda implementación del
    mismo `includes` que hace el navegador, y la que corre de verdad sería la
    que no se prueba.

    `clave` es lo que se guarda en el navegador y viaja en el JSON; `nombre` es
    lo que el encargado lee en el interruptor. Van juntos a propósito: una
    vista que se llamara solo "Medicamentos" y siguiera trayendo botica
    mentiría sobre los dos anaqueles de material de curación, y el nombre y la
    regla no pueden separarse si viven en el mismo objeto.
    """

    clave: str
    nombre: str
    clasificaciones: tuple[str, ...]
    #: Cuál se enciende cuando el navegador no tiene nada guardado, o tiene algo
    #: que ya no existe. Es un campo y no una constante aparte para que viaje en
    #: el mismo JSON: así la pantalla no tiene que saberse de memoria cuál era.
    es_la_de_omision: bool = False


#: Las dos vistas, en el orden en que se pintan. El nombre de cada una es el de
#: la historia 9 del spec, literal.
#:
#: **La de omisión es "todo lo vendido"**, y esa elección importa: es la que
#: menos daño hace cuando nadie ha tocado el interruptor todavía. Arrancar en
#: "medicamentos y botica" escondería abarrotes en la primera pantalla que
#: alguien ve, sin que esa persona haya decidido esconder nada —el mismo
#: criterio por el que unas reglas de clasificación sin cargar dejan todo en
#: `sin clasificar` en vez de suponer "será medicamento"—. Esconder es una
#: decisión, y una decisión la toma una persona; después se recuerda.
VISTAS: tuple[Vista, ...] = (
    Vista(
        clave="medicamentos-y-botica",
        nombre="Medicamentos y botica",
        # Botica entra como medicamento —material de curación que se le compra a
        # los mismos proveedores, CONTEXT.md— y por eso no necesita renglón
        # propio aquí: `clasificar()` ya la devuelve como `medicamento`. Lo que
        # sí necesita renglón propio es `SIN_CLASIFICAR`, que es lo único que
        # esta vista podría tener la tentación de esconder y no puede.
        clasificaciones=(MEDICAMENTO, SIN_CLASIFICAR),
    ),
    Vista(
        clave="todo-lo-vendido",
        nombre="Todo lo vendido",
        clasificaciones=(MEDICAMENTO, ABARROTE, SIN_CLASIFICAR),
        es_la_de_omision=True,
    ),
)
