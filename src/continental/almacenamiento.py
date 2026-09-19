"""Donde el pedido sugerido deja de ser una respuesta HTTP y pasa a ser una fila.

Hasta el ticket 07 la lista se recalculaba en cada carga de la página y moría
con la respuesta. Desde aquí **lo que se muestra es lo guardado**: al abrir el
día se crea si no existe y se lee si existe, y un renglón ya propuesto no
cambia porque el catálogo se haya movido debajo. Es la otra mitad de lo que el
ticket 04 dejó escrito en `sugerido.Renglon`: los números viajan congelados, y
congelados quiere decir *guardados*, no *recalculados igual*.

**La misma costura que el almacén** (ticket 01): un `Protocol` con su doble en
memoria —que es lo que las pruebas ejercitan—, una implementación real contra
Postgres, y la entrega por `Depends` para que una prueba la sustituya con
`app.dependency_overrides`. No es simetría por gusto: **no hay Postgres
alcanzable desde la torre** (Docker Desktop apagado, nada en el 5432,
verificado el 2026-09-19) y la regla del repo es que ninguna prueba toque la
base y el suite corra en menos de un segundo.

Esa restricción tiene un peligro con nombre: **un doble que acepta lo que
Postgres rechazaría deja pruebas en verde que en atlas truenan.** Por eso este
módulo, y no el doble, es dueño de las reglas de la tabla:

- `columnas_de_la_lista` y `columnas_del_renglon` arman las columnas **una
  sola vez**, y las usan el SQL real y el doble. Ahí viven la traducción de la
  clave vacía a `NULL` y el redondeo a la escala de cada `numeric`.
- `revisar_la_lista` y `revisar_el_renglon` son los CHECK del DDL escritos en
  Python. El doble los llama antes de guardar; Postgres los aplica por su
  cuenta. Si alguien relaja uno de los dos lados, la prueba de
  `test_guardado.py` que lo cubre se pone roja.

**Lo único que no se puede verificar aquí es que el SQL corra.** Está escrito
para leerse: cada sentencia dice de qué restricción del DDL depende, y las
decisiones que se pueden comprobar sobre el texto —el `ON CONFLICT` nombrando
`ux_pedido_sugerido_dia`, que no haya un `DELETE`, que ninguna fecha salga del
reloj— tienen su prueba.

**Escritura acotada** (regla 6 de `CLAUDE.md` y ADR 0003): el rol
`continental` tiene `SELECT`, `INSERT` y `UPDATE` sobre `pedidos.*` y **no
tiene `DELETE` ni `TRUNCATE`**. Cerrar una lista, vencerla y descartar un
renglón son cambios de estado. Si algún día un diseño de aquí necesita borrar
una fila, el diseño está mal antes que el permiso.

**El reloj se mira para dos cosas y ninguna es una fecha.** `armado_en` y
`cerrado_en` son instantes reales con zona: dicen *cuándo pasó algo aquí*, que
es justo lo que un reloj sabe y el almacén no. Toda **fecha** —qué día es la
lista, hasta dónde llegan las ventas, cuál lista ya venció— sale de
`max(fecha)` del almacén, porque el Postgres del contenedor corre en UTC y su
`current_date` puede ir dos días adelante del último dato (a farmacia-data le
costó 11.7 puntos de crecimiento inventados).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import sqlalchemy
from sqlalchemy import text

from continental.clasificacion import ABARROTE, MEDICAMENTO, SIN_CLASIFICAR
from continental.sugerido import Renglon

log = logging.getLogger("continental")

# ------------------------------------------------------- el vocabulario
#
# Los mismos textos del glosario de `CONTEXT.md` y de los CHECK del DDL. Son
# constantes y no cadenas sueltas porque viajan hasta el JavaScript de la
# pantalla, y porque `test_sql_del_pedido.py` compara estas tuplas contra lo
# que `sql/crear_tablas.sql` dice de verdad: el día que una de las dos cambie
# sin la otra, esa prueba se pone roja en vez de dejar que el `UPDATE` rebote
# en atlas contra una violación de restricción que nadie sabría explicar.

ABIERTO = "abierto"
CERRADO = "cerrado"
VENCIDO = "vencido"

#: `abierto` → `cerrado` → `vencido`, y ningún sinónimo. Un "finalizado" que se
#: cuele parte la lista en dos vocabularios y las consultas empiezan a mentir
#: por omisión.
ESTADOS_DE_LA_LISTA: tuple[str, ...] = (ABIERTO, CERRADO, VENCIDO)

RENGLON_ABIERTO = "abierto"
RENGLON_DESCARTADO = "descartado"

#: Los cinco del glosario, con el acento de `en tránsito`. Hoy se escriben dos:
#: `abierto` al nacer y `descartado` desde el ticket 10. El 24 pone
#: `en tránsito` y el 26 los dos de recepción.
ESTADOS_DEL_RENGLON: tuple[str, ...] = (
    "abierto",
    "en tránsito",
    "recibido",
    "recibido parcial",
    "descartado",
)

CLASIFICACIONES = (MEDICAMENTO, ABARROTE, SIN_CLASIFICAR)

#: Los decimales de cada columna `numeric`, tal como los declara el DDL.
#: **Redondear aquí no es cosmético**: Postgres redondea al guardar, así que un
#: doble que conservara el float entero devolvería `4.000000000000001` donde la
#: base devuelve `4.000`, y una prueba de igualdad pasaría en la torre para
#: fallar en atlas. Los tres decimales de las piezas son los mismos de
#: `sugerido._DECIMALES_DE_GRANEL`; el uno de la cobertura, el de
#: `_DECIMALES_DE_COBERTURA`.
DECIMALES_DE_PIEZAS = 3
DECIMALES_DE_EXISTENCIA = 3
DECIMALES_DE_COBERTURA = 1


class PedidoSugeridoDuplicado(Exception):
    """Ya había una lista de ese día y negocio.

    Es el nombre en Python de `ux_pedido_sugerido_dia`, el `UNIQUE (negocio,
    fecha_del_pedido)` del DDL. No es un error que el encargado deba ver: lo
    atrapa `abrir_el_dia`, que vuelve a leer y devuelve la lista que ya existe
    —que es la que esa persona va a trabajar—.

    Contra Postgres el mismo suceso llega como *cero filas insertadas* por el
    `ON CONFLICT ... DO NOTHING`, y no como excepción. Son la misma cosa dicha
    de dos maneras, y las dos desembocan en la misma relectura.
    """


# ------------------------------------------------------------------ datos


@dataclass(frozen=True, slots=True)
class Ventana:
    """De qué día a qué día de **ventas** consideró la lista, extremos incluidos.

    Es un rango y no un solo extremo porque guardar únicamente el derecho haría
    imposible auditar de dónde salió un renglón. Desde el ticket 09 los dos
    extremos casi nunca valen lo mismo: `hasta` sigue siendo el último día con
    datos y `desde` es el día siguiente al corte del último cerrado. Quién
    decide eso es `ventana_de_reposicion`, aquí abajo.

    **Los dos extremos entran**, y eso no es un detalle de implementación: es lo
    que hace que una lista cerrada cubra su `hasta` y que la siguiente pueda
    arrancar en el día de después sin dejar hueco. `almacen.ventas(desde,
    hasta)` cuenta el rango igual (`between` de SQL).

    Fechas y no instantes: el grano más fino que existe en el almacén es el
    día. `marts.fct_ventas` se une a `marts.dim_fecha` por `fecha_id` y no
    guarda hora, así que un `timestamptz` aquí inventaría una precisión que el
    dato no tiene.

    Valida su propio orden porque el DDL también lo hace
    (`ck_pedido_sugerido_ventana`). Un rango al revés no es un dato raro: es
    una lista que dice haber mirado ventas que nunca miró.
    """

    desde: dt.date
    hasta: dt.date

    def __post_init__(self) -> None:
        if self.desde > self.hasta:
            raise ValueError(
                f"La ventana va al revés: desde {self.desde} hasta {self.hasta}. "
                "Lo rechaza ck_pedido_sugerido_ventana."
            )


def ventana_de_reposicion(
    corte: dt.date | None, hasta: dt.date, dias_primera_vez: int
) -> Ventana:
    """Desde dónde repone el sugerido nuevo: **desde el corte del último cerrado**.

    Función pura: no mira el reloj, no lee el YAML y no toca la base. Los dos
    datos que necesita —el corte y el último día con ventas— le llegan por
    argumento, los dos anclados en el dato (ADR 0002 y regla del repo: todo
    sale de `max(fecha)`, nunca de `current_date`).

    **El día del corte NO entra en la ventana nueva: se arranca al día
    siguiente.** Era la decisión de este ticket y tenía dos opciones:

    - *Incluirlo* (`desde = corte`). `Ventana` incluye los dos extremos, así
      que la lista cerrada ya propuso —y alguien ya pidió— todo lo de ese día.
      Volver a meterlo lo propone por segunda vez, y **la duplicación no se ve
      en el renglón**: las piezas del día del corte se suman con las de los
      demás días y salen como un solo número. Un sugerido que pide el doble en
      silencio es exactamente la falla que la regla 4 de `CLAUDE.md` prohíbe, y
      rompe lo que hace defendible a la reposición 1 a 1: "se vendieron tres,
      se piden tres", aritmética que el encargado verifica de un vistazo.
    - *Excluirlo* (`desde = corte + 1 día`), que es lo que se hace. Las ventanas
      **embaldosan el calendario**: `[…, corte]` y `[corte + 1, hasta]` no se
      traslapan ni dejan un día en medio, así que cada día de ventas cae en
      exactamente una lista. Eso es lo que se puede afirmar y probar.

    Lo que sí cuesta esta decisión, dicho con su número: el respaldo de SICAR
    corta a las **18:51**, así que el último día del almacén siempre está a
    medias y lo que se venda después llega al día siguiente. Si se cierra una
    lista cuyo `hasta` es ese día a medias, el pedacito de la tarde queda fuera
    —el grano de `marts.fct_ventas` es el **día** (se une a `dim_fecha` por
    `fecha_id` y no guarda hora), así que no hay forma de partirlo—. No se
    resuelve moviendo este límite: incluir el día entero cuesta duplicar todo lo
    demás de ese día. Se resolvería con hora en el almacén o cerrando solo
    ventanas de días completos, y las dos son otra decisión. Queda anotado en
    `HANDOVER.md`, hilo 6.

    Esto **no aplica al día que nadie cerró**: una lista `abierta` o `vencida`
    no movió el corte —nada se pidió— así que sus días siguen adentro. Quién
    decide qué cuenta como corte es `corte_del_ultimo_cerrado`.

    Sin corte —la primera vez— la ventana es de `dias_primera_vez` días
    contando los dos extremos, y ese número sale de
    `config/continental.yml`, nunca de aquí.
    """
    if corte is None:
        return Ventana(
            desde=hasta - dt.timedelta(days=dias_primera_vez - 1), hasta=hasta
        )

    desde = corte + dt.timedelta(days=1)
    if desde <= hasta:
        return Ventana(desde=desde, hasta=hasta)

    # Los dos casos que llegan aquí NO son el mismo, y confundirlos costaba una
    # falsa alarma en el camino más ordinario que hay.
    #
    # `corte == hasta` es la lista de hoy ya cerrada y alguien que recarga la
    # página. Pasa todos los días y no tiene nada de malo: la ventana que se
    # devuelve ni siquiera se usa, porque `abrir_el_dia` encuentra la lista y la
    # lee. Avisar aquí era gritar "revisa si al almacén le faltan días" cada vez
    # que alguien cierra y recarga, y una alarma que suena cuando todo está bien
    # deja de leerse justo cuando importa.
    #
    # `corte > hasta` sí es un estado que no sale de datos sanos: el corte de un
    # cerrado nunca es posterior al último día con ventas. Solo se llega ahí si
    # al almacén le quitaron días. Eso se dice (regla 4).
    if corte > hasta:
        log.warning(
            "El corte del último pedido sugerido cerrado (%s) es posterior al "
            "último día con ventas (%s). La ventana se acota a ese día: revisa "
            "si al almacén le faltan días.",
            corte,
            hasta,
        )

    # Se acota al propio día en los dos casos: `ck_pedido_sugerido_ventana`
    # rechazaría una ventana al revés, y el pedido del día tiene que poder
    # hacerse.
    return Ventana(desde=hasta, hasta=hasta)


def dias_primera_vez_configurados() -> int:
    """Cuántos días toma el PRIMER sugerido, leídos de `config/continental.yml`.

    La capa delgada que lee el archivo, igual que `reglas_configuradas` para los
    anaqueles: el número es una decisión del negocio y vive en el YAML
    versionado —con su comentario—, no en una constante de Python que se
    quedaría desincronizada el día que el dueño lo cambie.

    Si la clave falta o no es un entero positivo, la ventana es de **un día** y
    se avisa. Un día es el último con datos: lo que el módulo hacía antes de
    este ticket y el único valor que no inventa una política. Tronar aquí
    dejaría a la farmacia sin pedido del día por una línea que falta en el YAML,
    y adivinar un 7 metería en el código justo el número que se sacó de él.
    """
    from continental.config import cargar

    crudo = cargar().pedido.get("dias_primera_vez")
    try:
        dias = int(crudo)
    except (TypeError, ValueError):
        dias = 0

    if dias < 1:
        log.warning(
            "config/continental.yml no trae un `pedido.dias_primera_vez` "
            "utilizable (%r). El primer pedido sugerido va a mirar un solo día "
            "de ventas; agrégalo al YAML para que mire los que el negocio "
            "quiere.",
            crudo,
        )
        return 1
    return dias


@dataclass(frozen=True, slots=True)
class RenglonGuardado:
    """Un renglón que ya tiene fila: su id, su estado y lo que se propuso.

    `propuesto` es el `sugerido.Renglon` **entero y sin tocar**, y la
    composición es deliberada: los números congelados siguen viviendo en un
    solo tipo, probado en un solo lugar, y `esta_agotado` no se reimplementa
    aquí. Aplanar los campos habría duplicado esa regla.

    `estado` nace en `abierto`. Atenderlo —descartarlo (ticket 10), pedirlo
    (20), recibirlo (26)— es un cambio de estado y nunca un borrado: el rol no
    tiene `DELETE`.

    `descartado_por` y `descartado_en` son la **firma** del descarte y valen
    `None` en todo renglón que no esté descartado, que es lo que exige
    `ck_renglon_descarte`. Son una firma y no un permiso (regla 3 de
    `CLAUDE.md`): el correo lo validó Cloudflare Access y sirve para saber
    quién decidió no pedir un producto, nunca para decidir si podía.

    El `cuándo` está aquí por una razón concreta y medible: la **condición de
    revisión del ADR 0002** —"si después de un mes de uso los renglones
    descartados superan a los pedidos, la reposición 1 a 1 no es la regla
    correcta"— es una consulta con un rango de fechas. Sin este instante, esa
    condición se puede cumplir sin que nadie pueda demostrarlo.
    """

    renglon_id: int
    estado: str
    propuesto: Renglon
    descartado_por: str | None = None
    descartado_en: dt.datetime | None = None

    @property
    def esta_descartado(self) -> bool:
        """Si una persona decidió no pedirlo (`CONTEXT.md`).

        Vive aquí y no repetida en cada consumidor por la misma razón que
        `esta_agotado` vive en `sugerido.Renglon`: es la regla que decide si un
        renglón sale de la lista de trabajo, y una regla que se escribe dos
        veces se cambia una sola.
        """
        return self.estado == RENGLON_DESCARTADO


@dataclass(frozen=True, slots=True)
class PedidoSugeridoGuardado:
    """La lista de un día, tal como quedó guardada (`CONTEXT.md`).

    Es lo que la pantalla pinta desde este ticket. Trae su `estado`, su
    `ventana` y sus dos instantes, y por eso una recarga no puede mostrar
    números distintos de los que se usaron para ordenarla.

    **El orden de `renglones` es el que se guardó**, no uno que se vuelva a
    calcular al leer. La urgencia se decide una sola vez, al armar; los
    renglones se insertan en ese orden y se releen por `renglon_id`, que la
    secuencia entrega creciente. Reordenar al leer sería recalcular por la
    puerta de atrás: un renglón subiría o bajaría solo porque alguien surtió
    el anaquel.
    """

    pedido_sugerido_id: int
    negocio: str
    fecha_del_pedido: dt.date
    estado: str
    ventana: Ventana
    armado_en: dt.datetime
    cerrado_en: dt.datetime | None
    renglones: tuple[RenglonGuardado, ...]

    @property
    def sin_catalogo(self) -> int:
        """Cuántos renglones son de productos que el catálogo no conoce.

        Se cuenta sobre lo guardado y no sobre el catálogo de hoy: la pregunta
        es qué se vio al armar la lista. El porqué de contarlo está en
        `sugerido.PedidoSugerido.sin_catalogo`.
        """
        return sum(1 for r in self.renglones if not r.propuesto.esta_en_el_catalogo)

    @property
    def sin_clasificar(self) -> int:
        """Cuántos renglones se quedaron sin anaquel conocido."""
        return sum(
            1 for r in self.renglones if r.propuesto.clasificacion == SIN_CLASIFICAR
        )

    @property
    def descartados(self) -> int:
        """Cuántos renglones de **esta lista** decidió alguien no pedir.

        "Cuántos se descartaron en el día" se cuenta sobre la lista del día y
        **no** con un `descartado_en::date`, y esa es la decisión: el día de la
        lista sale de `max(fecha)` del almacén, mientras que la fecha de un
        instante saldría del reloj del servidor. El Postgres del contenedor
        corre en UTC y su idea de "hoy" puede ir dos días adelante del último
        dato —a farmacia-data le costó 11.7 puntos de crecimiento inventados—,
        así que contar por el reloj dejaría el número en cero justo los días en
        que las dos fechas no coinciden.

        Es el numerador de la **condición de revisión del ADR 0002**: si esto
        supera sistemáticamente a lo que sí se pidió, la reposición 1 a 1 no es
        la regla correcta y hay que volver a la opción 2 del ADR.
        """
        return sum(1 for r in self.renglones if r.esta_descartado)

    @property
    def de_trabajo(self) -> tuple[RenglonGuardado, ...]:
        """Los renglones que siguen en la lista de trabajo.

        "Sale de la lista de trabajo" **no es** "desaparece": el descartado
        sigue guardado, se ve aparte y se puede devolver a `abierto`. Lo que
        esta propiedad define es qué se muestra como pendiente, y vive aquí —en
        Python, probado— y no en el JavaScript de la pantalla, por la misma
        razón que las vistas de `vistas.py`: la regla que decide qué se ve no
        puede vivir en el único archivo que ninguna prueba mira.
        """
        return tuple(r for r in self.renglones if not r.esta_descartado)

    @property
    def tiene_renglones_sin_atender(self) -> bool:
        """Si queda algo en `abierto`, que es lo que el glosario llama "sin atender".

        Es lo que describe a una lista `vencida`: pasó su día y quedaron
        renglones sin atender. Se expone para poder decirlo en la pantalla, no
        como condición del vencimiento — ver `vencer_las_de_dias_anteriores`.

        **Un renglón `descartado` ya se atendió**: alguien lo miró y decidió no
        pedirlo. Contarlo como pendiente diría que quedó trabajo por hacer en
        una lista que se revisó entera.
        """
        return any(r.estado == RENGLON_ABIERTO for r in self.renglones)


# ----------------------------------- las reglas de la tabla, en un solo lugar
#
# Todo lo de aquí abajo lo usan las DOS implementaciones. Es lo que impide que
# el doble mienta: no "se parece" a la tabla, arma sus columnas con el mismo
# código y se niega con los mismos motivos.


def _redondear(valor: float | None, decimales: int) -> float | None:
    """A la escala de la columna, dejando pasar el "no se sabe"."""
    return None if valor is None else round(valor, decimales)


def columnas_de_la_lista(
    negocio: str, fecha_del_pedido: dt.date, ventana: Ventana
) -> dict:
    """Las columnas de `pedidos.pedido_sugerido` al nacer: abierta y sin cierre.

    `estado` y `cerrado_en` van explícitos aunque el DDL tenga `DEFAULT
    'abierto'`: el `CHECK ((estado = 'cerrado') = (cerrado_en IS NOT NULL))`
    relaciona a los dos, y escribirlos juntos deja ver que se respeta.
    """
    return {
        "negocio": negocio,
        "fecha_del_pedido": fecha_del_pedido,
        "estado": ABIERTO,
        "ventas_consideradas_desde": ventana.desde,
        "ventas_consideradas_hasta": ventana.hasta,
        "cerrado_en": None,
    }


def columnas_del_renglon(
    renglon: Renglon, negocio: str, pedido_sugerido_id: int | None = None
) -> dict:
    """Las columnas de `pedidos.renglon`, con las dos traducciones que importan.

    1. **La clave vacía se vuelve `NULL`.** `sugerido.Renglon.clave` vale `""`
       cuando el producto no está en el catálogo, y la columna tiene `CHECK
       (clave <> '')`. La cadena vacía no es un tercer valor inocente: se
       compara igual que un dato y empareja con cualquier otra vacía, que es
       exactamente cómo se emparejan productos que no tienen nada que ver. O
       hay EAN o no se sabe.
    2. **Los `numeric` se redondean a su escala.** Ver `DECIMALES_DE_PIEZAS`.

    `esta_en_el_catalogo` no se deduce de que haya clave: es un dato propio del
    renglón y deducirlo daría un producto "sin catálogo" el día que el catálogo
    traiga un EAN vacío, que pasa.

    `descartado_por` y `descartado_en` van explícitos en `None` aunque las
    columnas admitan nulos, por la misma razón que `estado` y `cerrado_en` van
    explícitos en `columnas_de_la_lista`: `ck_renglon_descarte` relaciona los
    tres, y escribirlos juntos deja ver que se respeta. Un renglón nace
    `abierto` y nadie lo ha descartado.
    """
    return {
        "negocio": negocio,
        "pedido_sugerido_id": pedido_sugerido_id,
        "producto_id": renglon.producto_id,
        "clave": renglon.clave or None,
        "descripcion": renglon.descripcion,
        "piezas_vendidas": _redondear(renglon.piezas_vendidas, DECIMALES_DE_PIEZAS),
        "cantidad_propuesta": renglon.cantidad_propuesta,
        "esta_en_el_catalogo": renglon.esta_en_el_catalogo,
        "existencia": _redondear(renglon.existencia, DECIMALES_DE_EXISTENCIA),
        "dias_de_cobertura": _redondear(
            renglon.dias_de_cobertura, DECIMALES_DE_COBERTURA
        ),
        "clasificacion": renglon.clasificacion,
        "estado": RENGLON_ABIERTO,
        "descartado_por": None,
        "descartado_en": None,
    }


def renglon_desde_columnas(fila) -> Renglon:
    """El camino de vuelta: una fila leída se vuelve el mismo `Renglon` congelado.

    `NULL` en la clave vuelve a ser `""`, que es como el resto del código y la
    pantalla dicen "no se sabe" para un EAN. Los `numeric` llegan como
    `Decimal` desde Postgres y se convierten a `float` aquí, en el borde, para
    que nadie más se entere del tipo — misma idea que `almacen.py`.
    """
    return Renglon(
        producto_id=int(fila["producto_id"]),
        clave=fila["clave"] or "",
        descripcion=fila["descripcion"],
        piezas_vendidas=float(fila["piezas_vendidas"]),
        cantidad_propuesta=int(fila["cantidad_propuesta"]),
        esta_en_el_catalogo=bool(fila["esta_en_el_catalogo"]),
        existencia=None if fila["existencia"] is None else float(fila["existencia"]),
        dias_de_cobertura=(
            None
            if fila["dias_de_cobertura"] is None
            else float(fila["dias_de_cobertura"])
        ),
        clasificacion=fila["clasificacion"],
    )


def revisar_la_lista(columnas: dict) -> None:
    """Los CHECK de `pedidos.pedido_sugerido`, escritos en Python.

    Postgres los aplica por su cuenta y no necesita esto; el doble sí, porque
    sin ellos aceptaría en la torre lo que en atlas rebota. Cada `raise` de
    aquí nombra la restricción que estaría violando.
    """
    if not columnas["negocio"]:
        raise ValueError("negocio vacío: lo rechaza ck_pedido_sugerido_negocio.")
    if columnas["estado"] not in ESTADOS_DE_LA_LISTA:
        raise ValueError(
            f"Estado {columnas['estado']!r} fuera del glosario. Lo rechaza "
            f"ck_pedido_sugerido_estado, que solo conoce {ESTADOS_DE_LA_LISTA}."
        )
    if (columnas["estado"] == CERRADO) != (columnas["cerrado_en"] is not None):
        raise ValueError(
            "Cerrado sin hora, u hora de cierre en una lista que no está "
            "cerrada. Lo rechaza ck_pedido_sugerido_cierre."
        )
    if columnas["ventas_consideradas_desde"] > columnas["ventas_consideradas_hasta"]:
        raise ValueError("La ventana va al revés: ck_pedido_sugerido_ventana.")


def revisar_el_renglon(columnas: dict) -> None:
    """Los CHECK de `pedidos.renglon`, escritos en Python."""
    if not columnas["negocio"]:
        raise ValueError("negocio vacío: lo rechaza ck_renglon_negocio.")
    if columnas["clave"] == "":
        raise ValueError(
            "Clave vacía. La columna tiene CHECK (clave <> ''): o hay EAN o es "
            "NULL. Ver columnas_del_renglon."
        )
    if not columnas["descripcion"]:
        raise ValueError("descripcion nula: la columna es NOT NULL.")
    if columnas["piezas_vendidas"] is None or columnas["piezas_vendidas"] < 0:
        raise ValueError("piezas_vendidas negativa o nula: ck_renglon_piezas.")
    if columnas["cantidad_propuesta"] < 0:
        raise ValueError("cantidad_propuesta negativa: ck_renglon_cantidad.")
    if (
        columnas["dias_de_cobertura"] is not None
        and columnas["dias_de_cobertura"] < 0
    ):
        raise ValueError("dias_de_cobertura negativa: ck_renglon_cobertura.")
    if not columnas["esta_en_el_catalogo"] and (
        columnas["clave"] is not None or columnas["existencia"] is not None
    ):
        raise ValueError(
            "Un producto fuera del catálogo no tiene EAN ni existencia que "
            "mirar: ck_renglon_sin_catalogo."
        )
    if columnas["clasificacion"] not in CLASIFICACIONES:
        raise ValueError(
            f"Clasificación {columnas['clasificacion']!r} desconocida: "
            "ck_renglon_clasificacion."
        )
    if columnas["estado"] not in ESTADOS_DEL_RENGLON:
        raise ValueError(
            f"Estado {columnas['estado']!r} fuera del glosario: ck_renglon_estado."
        )
    if columnas["descartado_por"] == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (descartado_por <> ''): o hay "
            "correo o es NULL. Sin encabezado, `web.app.quien()` devuelve "
            "'sin-identificar', que sí es un dato."
        )
    if (columnas["estado"] == RENGLON_DESCARTADO) != (
        columnas["descartado_por"] is not None and columnas["descartado_en"] is not None
    ):
        raise ValueError(
            "Descartado sin decir quién ni cuándo, o firma de descarte en un "
            "renglón que no está descartado. Lo rechaza ck_renglon_descarte. "
            "Sin el cuándo, la condición de revisión del ADR 0002 —los "
            "descartados de un mes— no se puede medir; con la firma puesta en "
            "un renglón devuelto a 'abierto', ese mismo conteo mentiría al "
            "revés."
        )


# --------------------------------------------------------------- interfaz


@runtime_checkable
class AlmacenamientoDelPedido(Protocol):
    """El borde de escritura. Siete operaciones y ninguna de ellas borra.

    Es aparte de `LecturaDelAlmacen` a propósito, igual que Doyle lo es del
    almacén: una prueba tiene que poder sustituir una sola, y un borde caído no
    puede arrastrar al otro. Aquí eso importa más que en el ticket 01, porque
    los dos bordes viven en el **mismo** Postgres y sería fácil pasarse una
    conexión entre ellos — y entonces la lectura de `marts` y la escritura de
    `pedidos` dejarían de poder fallar por separado.
    """

    def abrir_el_dia(
        self,
        negocio: str,
        fecha_del_pedido: dt.date,
        ventana: Ventana,
        armar: Callable[[], Sequence[Renglon]],
    ) -> PedidoSugeridoGuardado:
        """La lista de ese día: la crea si no existe, la lee si existe.

        `armar` es una **función y no una lista** porque armar cuesta: leer el
        catálogo entero (3,429 filas) más 28 días de ventas (~600). Cuando la
        lista ya existe no se llama ni una vez, y esa es la diferencia
        medible entre este ticket y el anterior — antes cada carga de la página
        pagaba las dos consultas.

        **Nunca duplica.** Lo garantiza `ux_pedido_sugerido_dia` en la base, no
        un `SELECT` previo: entre mirar si existe e insertarla hay una carrera,
        y dos pestañas abiertas a la misma hora bastan para colarse por ahí sin
        un solo error. Quien pierde la carrera se queda con la lista del que
        ganó.
        """
        ...

    def leer(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> PedidoSugeridoGuardado | None:
        """La lista de ese día con sus renglones, o `None` si no hay."""
        ...

    def corte_del_ultimo_cerrado(
        self, negocio: str, antes_de: dt.date
    ) -> dt.date | None:
        """Hasta qué día de ventas llegó el último pedido sugerido **cerrado**.

        Es el dato desde el cual acumula el siguiente (ADR 0002), y la razón por
        la que el ticket 08 guardó `ventas_consideradas_hasta`. `None` es "nunca
        se ha cerrado uno", que es la primera vez.

        **Solo cuenta lo `cerrado`, y eso es la mitad de la decisión.** Una
        lista `abierta` o `vencida` no pidió nada —`vencida` es literalmente
        "pasó su día y quedaron renglones sin atender"—, así que tomarla como
        corte dejaría fuera días que nadie repuso: la venta se caería al piso
        sin un solo error que ver. Puede haber listas anteriores y ninguna
        cerrada: entonces no hay corte y la ventana es la de la primera vez.

        `antes_de` acota a los días anteriores al que se está abriendo y viene
        del dato (`max(fecha)` del almacén), nunca del reloj.
        """
        ...

    def cerrar(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        """Da por cerrada una lista **abierta**. `None` si no había ninguna así.

        La transición vive en el `WHERE`: solo se cierra lo que está `abierto`,
        así que un segundo clic no mueve `cerrado_en` ni resucita una vencida.
        `None` es "no había nada que cerrar" y quien llame lo dice; fingir que
        cerró sería la falla silenciosa que este repo prohíbe.
        """
        ...

    def vencer_las_de_dias_anteriores(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> int:
        """Pasa a `vencido` lo que siga `abierto` de un día anterior. Cuántas movió.

        **`fecha_del_pedido` es el ancla y viene del dato**, no del reloj: es
        el último día con ventas del almacén. Contra `current_date` toda lista
        estaría vencida desde el primer segundo —el contenedor corre en UTC y
        puede ir dos días adelante—, y el encargado vería vencerse la lista que
        tiene abierta enfrente.

        Vence **toda** lista abierta de un día anterior, tenga o no renglones
        sin atender, y ahí hay una decisión que el ticket no especificaba: el
        glosario describe `vencido` como "pasó su día y quedaron renglones sin
        atender", pero una lista de ayer con todo atendido y sin cerrar no
        tiene a dónde ir. Dejarla `abierta` es justo el "abierta para siempre"
        que el ticket prohíbe, y cerrarla sola sería inventar una decisión que
        nadie tomó —con un `cerrado_en` que miente—. `vencido` dice la verdad:
        su día pasó y nadie la cerró.
        """
        ...

    def descartar(
        self, negocio: str, renglon_id: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """Pone un renglón **abierto** en `descartado`, firmado. Devuelve la lista.

        `None` es "no había ningún renglón abierto con ese id en este negocio",
        y quien llame lo dice: fingir que descartó sería la falla silenciosa que
        este repo prohíbe. Desde fuera no se distingue "no existe" de "no estaba
        abierto", y es a propósito — decirlo sería contar qué ids hay en la
        tabla.

        **La transición vive en el `WHERE`**, no en un `if` de Python. Solo se
        descarta lo `abierto`: un renglón `en tránsito` ya se le pidió a un
        proveedor —y el ticket 26 va a recibir esa mercancía contra él—, y
        `recibido` / `recibido parcial` son hechos consumados que descartar
        reescribiría. Comprobar el estado en Python y actualizar después tiene
        una carrera en medio.

        `quien` es una **firma, no un permiso** (regla 3 de `CLAUDE.md`). Se
        guarda junto con la hora porque sin las dos la condición de revisión del
        ADR 0002 no se puede evaluar.

        Devuelve la **lista entera** y no solo el renglón: el conteo de
        descartados tiene que salir de lo guardado y no de un número que el
        navegador vaya sumando, o dos pestañas abiertas en el mostrador se
        separan de la verdad sin un solo error que ver.
        """
        ...

    def devolver_a_abierto(
        self, negocio: str, renglon_id: int
    ) -> PedidoSugeridoGuardado | None:
        """Deshace un descarte: `descartado` → `abierto`, sin firma ni hora.

        Es lo que hace segura la operación de un clic, y por eso descartar no
        pide confirmación. `None` si el renglón no estaba `descartado`.

        **Las dos columnas se limpian**, y eso es una decisión: un renglón
        devuelto a `abierto` no está descartado, así que dejarle la firma haría
        que el conteo mensual del ADR 0002 sumara renglones que alguien está
        trabajando. Lo que cuesta, dicho: **no queda rastro del descarte
        deshecho**. Un historial de cada clic sería otra tabla, y el dato que el
        ADR necesita es cuántos renglones quedaron descartados, no cuántas veces
        alguien dudó.
        """
        ...


# ------------------------------------------------- la implementación real
#
# Estas sentencias NO se pudieron ejecutar: desde la torre no hay Postgres
# alcanzable. Están escritas para leerse, y cada una dice de qué restricción
# del DDL depende.

_LEER_LISTA = text(
    """
    select pedido_sugerido_id, negocio, fecha_del_pedido, estado,
           ventas_consideradas_desde, ventas_consideradas_hasta,
           armado_en, cerrado_en
    from pedidos.pedido_sugerido
    where negocio = :negocio and fecha_del_pedido = :fecha_del_pedido
    """
)

_LEER_LISTA_POR_ID = text(
    """
    select pedido_sugerido_id, negocio, fecha_del_pedido, estado,
           ventas_consideradas_desde, ventas_consideradas_hasta,
           armado_en, cerrado_en
    from pedidos.pedido_sugerido
    where negocio = :negocio and pedido_sugerido_id = :pedido_sugerido_id
    """
)

_LEER_RENGLONES = text(
    """
    select renglon_id, producto_id, clave, descripcion, piezas_vendidas,
           cantidad_propuesta, esta_en_el_catalogo, existencia,
           dias_de_cobertura, clasificacion, estado,
           descartado_por, descartado_en
    from pedidos.renglon
    where negocio = :negocio and pedido_sugerido_id = :pedido_sugerido_id
    order by renglon_id
    """
)

# El corte desde el cual acumula el siguiente sugerido (ADR 0002).
#
# `max(...)` y no un `order by ... limit 1`: lo que se busca es **hasta dónde
# llegó lo ya pedido**, no cuál fila se cerró al final. Si alguien cierra hoy
# una lista vieja que había dejado abierta, el corte no debe retroceder: los
# días que ya cubrió una lista más nueva se volverían a proponer y se pedirían
# dos veces.
#
# `estado = 'cerrado'` es la otra mitad: una abierta o una vencida no pidió
# nada, así que no mueve el corte. Cero filas -o un `max` nulo, que es lo que
# Postgres devuelve cuando no hay ninguna- significa "nunca se ha cerrado una",
# y eso es la primera vez.
_ULTIMO_CORTE = text(
    """
    select max(ventas_consideradas_hasta) as corte
    from pedidos.pedido_sugerido
    where negocio = :negocio
      and estado = 'cerrado'
      and fecha_del_pedido < :antes_de
    """
)

# `ON CONFLICT ON CONSTRAINT ux_pedido_sugerido_dia DO NOTHING` es el corazón
# de "nunca se duplica", y por eso nombra la restricción en vez de las
# columnas: si alguien la renombra en el DDL, esto falla ruidoso en lugar de
# seguir funcionando contra otra restricción parecida.
#
# `DO NOTHING` y no `DO UPDATE`: la lista que ya está es la que el encargado
# está trabajando, y pisarle la ventana o la hora de armado por una segunda
# pestaña sería reescribir su historia. Cero filas devueltas es la señal de que
# se perdió la carrera, y quien llama vuelve a leer.
_INSERTAR_LISTA = text(
    """
    insert into pedidos.pedido_sugerido
        (negocio, fecha_del_pedido, estado,
         ventas_consideradas_desde, ventas_consideradas_hasta)
    values
        (:negocio, :fecha_del_pedido, :estado,
         :ventas_consideradas_desde, :ventas_consideradas_hasta)
    on conflict on constraint ux_pedido_sugerido_dia do nothing
    returning pedido_sugerido_id, negocio, fecha_del_pedido, estado,
              ventas_consideradas_desde, ventas_consideradas_hasta,
              armado_en, cerrado_en
    """
)

# Una sola sentencia con todos los renglones: SQLAlchemy la ejecuta con una
# lista de diccionarios y los `renglon_id` salen crecientes en el orden en que
# van, que es el orden por urgencia. Eso es lo que hace que releer por
# `renglon_id` devuelva la lista como se vio.
_INSERTAR_RENGLONES = text(
    """
    insert into pedidos.renglon
        (negocio, pedido_sugerido_id, producto_id, clave, descripcion,
         piezas_vendidas, cantidad_propuesta, esta_en_el_catalogo, existencia,
         dias_de_cobertura, clasificacion, estado)
    values
        (:negocio, :pedido_sugerido_id, :producto_id, :clave, :descripcion,
         :piezas_vendidas, :cantidad_propuesta, :esta_en_el_catalogo,
         :existencia, :dias_de_cobertura, :clasificacion, :estado)
    """
)

# Descartar un renglón (ticket 10). Es un UPDATE y nunca un borrado: el rol no
# tiene DELETE y descartar es un cambio de estado del glosario.
#
# `and estado = 'abierto'` es la transición metida en el WHERE, igual que en
# `_CERRAR`. Solo se descarta lo abierto: `en tránsito` ya se le pidió a un
# proveedor, y `recibido` / `recibido parcial` son hechos consumados. Cero filas
# es "no había nada que descartar", y quien llama lo dice en vez de fingir.
#
# `now()` y no una hora calculada en Python, por la misma razón que el cierre:
# la pone el servidor que guarda la fila, así que dos procesos con relojes
# distintos no escriben descartes incomparables. Es un INSTANTE con zona y no
# una fecha -- lo que se ancla en `max(fecha)` son las fechas de VENTA--, y es
# lo que vuelve medible la condición de revisión del ADR 0002.
#
# Las dos columnas se escriben juntas porque `ck_renglon_descarte` las exige
# juntas: descartado si y solo si hay firma Y hora.
_DESCARTAR = text(
    """
    update pedidos.renglon
       set estado = 'descartado',
           descartado_por = :quien,
           descartado_en = now()
     where negocio = :negocio
       and renglon_id = :renglon_id
       and estado = 'abierto'
    returning renglon_id, pedido_sugerido_id
    """
)

# Deshacer el descarte. Lo que hace segura la operación de un clic.
#
# `descartado_por` y `descartado_en` vuelven a NULL **las dos**: un renglón
# abierto no está descartado, y `ck_renglon_descarte` rechaza la mitad. Dejar
# la firma puesta haría que el conteo mensual del ADR 0002 sumara renglones que
# alguien está trabajando.
#
# `and estado = 'descartado'` es la otra mitad de la transición: no se "abre"
# un renglón recibido ni uno en tránsito por esta puerta.
_DEVOLVER_A_ABIERTO = text(
    """
    update pedidos.renglon
       set estado = 'abierto',
           descartado_por = null,
           descartado_en = null
     where negocio = :negocio
       and renglon_id = :renglon_id
       and estado = 'descartado'
    returning renglon_id, pedido_sugerido_id
    """
)

# `now()` y no una hora calculada en Python: la hora del cierre la pone el
# servidor que guarda la fila, así que dos procesos con relojes distintos no
# escriben cierres incomparables. Es un INSTANTE con zona, no una fecha.
#
# El `and estado = 'abierto'` es la transición del glosario metida en el
# `WHERE`: cerrar lo ya cerrado no mueve `cerrado_en`, y una vencida no
# resucita. Cero filas es "no había nada que cerrar".
_CERRAR = text(
    """
    update pedidos.pedido_sugerido
       set estado = 'cerrado', cerrado_en = now()
     where negocio = :negocio
       and pedido_sugerido_id = :pedido_sugerido_id
       and estado = 'abierto'
    returning pedido_sugerido_id, negocio, fecha_del_pedido, estado,
              ventas_consideradas_desde, ventas_consideradas_hasta,
              armado_en, cerrado_en
    """
)

# `fecha_del_pedido < :fecha_del_pedido` compara CONTRA EL DATO que llega por
# parámetro —el último día con ventas del almacén— y nunca contra
# `current_date`. `cerrado_en` se queda en NULL, que es lo que
# ck_pedido_sugerido_cierre exige de todo lo que no está cerrado.
_VENCER = text(
    """
    update pedidos.pedido_sugerido
       set estado = 'vencido'
     where negocio = :negocio
       and estado = 'abierto'
       and fecha_del_pedido < :fecha_del_pedido
    returning pedido_sugerido_id
    """
)


class AlmacenamientoPostgres:
    """`AlmacenamientoDelPedido` contra el esquema `pedidos` (ADR 0003).

    Recibe la **factoría** del motor, no el motor: `AlmacenamientoPostgres(motor)`,
    sin paréntesis, por la misma razón que `AlmacenPostgres`. Construir este
    objeto no crea nada y no puede fallar — una dependencia de FastAPI que
    truena lo hace *antes* de entrar a la ruta, donde el `try` del manejador ya
    no la alcanza, y una base caída se convertiría en un 500 genérico en vez de
    un hueco con su motivo (regla 4).

    Escribe con `begin()` y no con `connect()`: cada operación es una
    transacción, así que **una lista nunca queda guardada sin sus renglones**.
    Si el `INSERT` de los renglones falla a la mitad, el de la cabecera se va
    con él — y sin eso habría una lista vacía ocupando el `UNIQUE` del día, que
    ninguna carga posterior podría arreglar porque el rol no puede borrarla.
    """

    def __init__(self, fabrica_de_motor: Callable[[], sqlalchemy.Engine] | None):
        self._fabrica = fabrica_de_motor

    def _motor(self) -> sqlalchemy.Engine:
        if self._fabrica is None:
            raise RuntimeError(
                "Este AlmacenamientoPostgres se construyó sin factoría de motor. "
                "Úsalo con `motor` o sustitúyelo por un doble."
            )
        return self._fabrica()

    # ---------------------------------------------------------- lectura

    def leer(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> PedidoSugeridoGuardado | None:
        with self._motor().connect() as conexion:
            return self._leer(conexion, negocio, fecha_del_pedido)

    def _leer(
        self, conexion, negocio: str, fecha_del_pedido: dt.date
    ) -> PedidoSugeridoGuardado | None:
        fila = conexion.execute(
            _LEER_LISTA, {"negocio": negocio, "fecha_del_pedido": fecha_del_pedido}
        ).mappings().first()
        return None if fila is None else self._con_renglones(conexion, fila)

    def _con_renglones(self, conexion, cabecera) -> PedidoSugeridoGuardado:
        """La cabecera más sus renglones, en el orden en que se guardaron."""
        filas = (
            conexion.execute(
                _LEER_RENGLONES,
                {
                    "negocio": cabecera["negocio"],
                    "pedido_sugerido_id": cabecera["pedido_sugerido_id"],
                },
            )
            .mappings()
            .all()
        )
        return armar_guardado(cabecera, filas)

    def corte_del_ultimo_cerrado(
        self, negocio: str, antes_de: dt.date
    ) -> dt.date | None:
        with self._motor().connect() as conexion:
            fila = (
                conexion.execute(
                    _ULTIMO_CORTE, {"negocio": negocio, "antes_de": antes_de}
                )
                .mappings()
                .first()
            )
        return None if fila is None else fila["corte"]

    # --------------------------------------------------------- escritura

    def abrir_el_dia(
        self,
        negocio: str,
        fecha_del_pedido: dt.date,
        ventana: Ventana,
        armar: Callable[[], Sequence[Renglon]],
    ) -> PedidoSugeridoGuardado:
        ya_estaba = self.leer(negocio, fecha_del_pedido)
        if ya_estaba is not None:
            return ya_estaba

        renglones = tuple(armar())

        with self._motor().begin() as conexion:
            cabecera = conexion.execute(
                _INSERTAR_LISTA,
                columnas_de_la_lista(negocio, fecha_del_pedido, ventana),
            ).mappings().first()

            if cabecera is None:
                # Cero filas: otra pestaña ganó la carrera entre el `leer` de
                # arriba y este `insert`. Lo que se acaba de armar se tira y se
                # devuelve la lista que ya existe, que es la que esa persona
                # está viendo. Esto es lo que la restricción de la base compra
                # y un `SELECT` previo no.
                #
                # La relectura encuentra la fila porque `ON CONFLICT` espera a
                # que la otra transacción termine: si hubiera abortado, este
                # `INSERT` habría entrado. Aun así se comprueba y se truena, en
                # vez de devolver `None` contra un tipo que promete una lista:
                # un vacío silencioso aquí se vería como "hoy no se vendió
                # nada" tres capas más arriba (regla 4).
                ganadora = self._leer(conexion, negocio, fecha_del_pedido)
                if ganadora is None:
                    raise RuntimeError(
                        "ux_pedido_sugerido_dia rechazó el INSERT del pedido "
                        f"sugerido de {negocio} para {fecha_del_pedido} y "
                        "después no hay ninguna fila que leer. Es un estado "
                        "imposible: revisa si alguien le dio DELETE al rol."
                    )
                return ganadora

            if renglones:
                conexion.execute(
                    _INSERTAR_RENGLONES,
                    [
                        columnas_del_renglon(
                            r, negocio, cabecera["pedido_sugerido_id"]
                        )
                        for r in renglones
                    ],
                )
            return self._con_renglones(conexion, cabecera)

    def cerrar(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        with self._motor().begin() as conexion:
            cabecera = conexion.execute(
                _CERRAR,
                {"negocio": negocio, "pedido_sugerido_id": pedido_sugerido_id},
            ).mappings().first()
            return None if cabecera is None else self._con_renglones(conexion, cabecera)

    def vencer_las_de_dias_anteriores(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> int:
        with self._motor().begin() as conexion:
            return len(
                conexion.execute(
                    _VENCER,
                    {"negocio": negocio, "fecha_del_pedido": fecha_del_pedido},
                ).fetchall()
            )

    def descartar(
        self, negocio: str, renglon_id: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        return self._mover_el_renglon(
            _DESCARTAR,
            {"negocio": negocio, "renglon_id": renglon_id, "quien": quien},
        )

    def devolver_a_abierto(
        self, negocio: str, renglon_id: int
    ) -> PedidoSugeridoGuardado | None:
        return self._mover_el_renglon(
            _DEVOLVER_A_ABIERTO, {"negocio": negocio, "renglon_id": renglon_id}
        )

    def _mover_el_renglon(self, sentencia, parametros: dict):
        """El `UPDATE` de un renglón y la relectura de su lista, en una transacción.

        Las dos operaciones del ticket 10 comparten esto entero y solo cambian
        de sentencia: la transición está en el `WHERE` de cada una, así que
        aquí no hay un solo `if` sobre el estado — cero filas es "no había nada
        que mover" y sale como `None`.

        **Se relee dentro de la misma transacción** para que el conteo de
        descartados que vuelve sea el de después del cambio y no el de una foto
        tomada un instante antes.
        """
        with self._motor().begin() as conexion:
            movido = conexion.execute(sentencia, parametros).mappings().first()
            if movido is None:
                return None
            cabecera = (
                conexion.execute(
                    _LEER_LISTA_POR_ID,
                    {
                        "negocio": parametros["negocio"],
                        "pedido_sugerido_id": movido["pedido_sugerido_id"],
                    },
                )
                .mappings()
                .first()
            )
            if cabecera is None:
                # Imposible con la llave foránea puesta: el renglón que se acaba
                # de actualizar apunta a una lista que existe. Se truena en vez
                # de devolver `None`, que quien llama leería como "no había nada
                # que descartar" -- y sí lo había (regla 4).
                raise RuntimeError(
                    f"El renglón {parametros['renglon_id']} cambió de estado y "
                    "su pedido sugerido no aparece. Es un estado imposible con "
                    "fk_renglon_sugerido puesta: revisa el DDL."
                )
            return self._con_renglones(conexion, cabecera)


def armar_guardado(cabecera, filas) -> PedidoSugeridoGuardado:
    """Filas leídas → el dato congelado. Lo usan la implementación real y el doble.

    Compartirlo no es ahorro de líneas: es lo que garantiza que el doble
    devuelva **la misma forma** que Postgres, incluida la vuelta de `NULL` a
    `""` en la clave.
    """
    return PedidoSugeridoGuardado(
        pedido_sugerido_id=int(cabecera["pedido_sugerido_id"]),
        negocio=cabecera["negocio"],
        fecha_del_pedido=cabecera["fecha_del_pedido"],
        estado=cabecera["estado"],
        ventana=Ventana(
            desde=cabecera["ventas_consideradas_desde"],
            hasta=cabecera["ventas_consideradas_hasta"],
        ),
        armado_en=cabecera["armado_en"],
        cerrado_en=cabecera["cerrado_en"],
        renglones=tuple(
            RenglonGuardado(
                renglon_id=int(f["renglon_id"]),
                estado=f["estado"],
                propuesto=renglon_desde_columnas(f),
                descartado_por=f["descartado_por"],
                descartado_en=f["descartado_en"],
            )
            for f in filas
        ),
    )
