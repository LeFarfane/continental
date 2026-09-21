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
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import sqlalchemy
from sqlalchemy import text

from continental.clasificacion import ABARROTE, MEDICAMENTO, SIN_CLASIFICAR
from continental.precios import MOTIVOS, LecturaDePrecio, nombre_del_proveedor
from continental.sugerido import Renglon

if TYPE_CHECKING:  # pragma: no cover - solo para el tipo
    # `particion` importa ESTE módulo (necesita `RenglonGuardado` y
    # `PrecioDeProveedor`), así que importarlo aquí de verdad sería un ciclo. La
    # dirección correcta es ésta: el almacenamiento no sabe nada de la regla con
    # la que se parte, solo escribe lo que le den.
    from continental.particion import PedidoPorArmar

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

#: "Ya se le pidió a un proveedor y todavía no llega" (`CONTEXT.md`). **No se
#: vuelve a proponer mientras esté así**, que es lo que impide pedir dos veces
#: la misma mercancía.
#:
#: Lo escribe el ticket 21 al **enviar** el pedido, y no el 20 al armarlo: un
#: pedido en `borrador` todavía no se le pidió a nadie. Es constante desde aquí
#: porque ya hay código que la escribe; hasta el ticket 20 solo la nombraban
#: comentarios y pruebas.
RENGLON_EN_TRANSITO = "en tránsito"

#: Los dos de la recepción (tickets 26 y 27). Hoy **ningún código los
#: escribe**; son constantes desde el ticket 24 porque ya hay código que los
#: LEE: son los que cierran un tránsito. Ver `ESTADOS_QUE_CIERRAN_EL_TRANSITO`.
RENGLON_RECIBIDO = "recibido"
RENGLON_RECIBIDO_PARCIAL = "recibido parcial"

#: **Se dejó de esperar sin haber llegado** (ticket 25, ADR 0013): su pedido se
#: canceló porque nunca se capturó en el portal, o una persona lo devolvió a la
#: lista porque se atrasó. Lleva firma —`cancelado_por`, `cancelado_en`— y es
#: un final: no vuelve a `abierto` ni a `en tránsito`.
#:
#: **Por qué no vuelve a `abierto`, que es lo que el ticket decía.** Su lista
#: casi siempre es vieja —cerrada o vencida— y el glosario dice que solo una
#: lista `abierta` se deja modificar: un `abierto` dentro de una lista cerrada
#: sería trabajo pendiente en algo que dice "ya se pidió lo que se iba a pedir",
#: y nada lo volvería a proponer. Lo que vuelve es **el producto, a la
#: siguiente lista**, con todo lo que este renglón cubría: la memoria del
#: ticket 24 lo lee de aquí (`LoYaPedido.retiene_desde`).
RENGLON_CANCELADO = "cancelado"

#: Los seis del glosario, con el acento de `en tránsito`. Hoy se escriben
#: cuatro: `abierto` al nacer, `descartado` desde el ticket 10, `en tránsito`
#: desde el 21 y `cancelado` desde el 25. El 26 pone los dos de recepción.
#:
#: `cancelado` va AL FINAL y no junto a los de recepción, por la misma razón
#: que las columnas nuevas van al final de la tabla: el orden de esta tupla es
#: el del CHECK, y `test_sql_del_pedido.py` los compara como tuplas.
ESTADOS_DEL_RENGLON: tuple[str, ...] = (
    "abierto",
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    "descartado",
    RENGLON_CANCELADO,
)

#: **El enganche que el ticket 24 les deja a los tickets 26 y 27** (ADR 0012).
#:
#: Un renglón en uno de estos estados **ya no viene en camino**, y lo que se
#: vendió de su producto mientras venía **vuelve a proponerse**: la siguiente
#: lista lo cuenta desde el día siguiente al que repuso su pedido, aunque el
#: corte haya avanzado encima. Quien escriba cualquiera de los dos no tiene que
#: hacer nada más para que eso pase — ya está aquí y en `_LO_YA_PEDIDO`, que
#: repite la tupla con sus acentos y tiene una prueba que los compara.
#:
#: Lo que NO está aquí, a propósito: **`cancelado`** (ticket 25, ADR 0013). Un
#: renglón cancelado no se recibió nunca, así que lo que vuelve es **también** lo
#: que repuso, no solo lo de después del ancla: vuelve desde el principio de lo
#: que cubría. Es otra regla, y por eso otra tupla: ver
#: `ESTADOS_QUE_TERMINAN_EL_TRANSITO`.
ESTADOS_QUE_CIERRAN_EL_TRANSITO: tuple[str, ...] = (
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
)

#: **Todo lo que deja de venir en camino, llegara o no** (ticket 25). Los dos de
#: la recepción más `cancelado`. Un renglón en uno de éstos ya no saca su
#: producto de la lista, y lo que no se propuso por su culpa **vuelve**: desde
#: el día siguiente al ancla si llegó, desde el principio de lo que cubría si se
#: canceló. Es la segunda clase de fila de `_LO_YA_PEDIDO`.
ESTADOS_QUE_TERMINAN_EL_TRANSITO: tuple[str, ...] = (
    *ESTADOS_QUE_CIERRAN_EL_TRANSITO,
    RENGLON_CANCELADO,
)

#: Lo que, en una lista **posterior**, hace que otra lista ya no tenga que
#: recordar al producto (hasta el ticket 24 se llamaba `ESTADOS_YA_PEDIDOS` y
#: no traía `cancelado`): se volvió a pedir, llegó, o se canceló otra vez. En
#: los tres casos el renglón de después ya carga con lo que el de antes dejaba
#: pendiente —se armó con la memoria—, y recordar los dos serían dos intervalos
#: del mismo producto, que es sumar días dos veces. Es el `NOT EXISTS` de
#: `_LO_YA_PEDIDO`.
ESTADOS_QUE_ATIENDEN_EL_PRODUCTO: tuple[str, ...] = (
    RENGLON_EN_TRANSITO,
    *ESTADOS_QUE_TERMINAN_EL_TRANSITO,
)

CLASIFICACIONES = (MEDICAMENTO, ABARROTE, SIN_CLASIFICAR)

# --------------------------------------------- el estado de un pedido (20, 21)
#
# `CONTEXT.md` definía los estados del pedido sugerido y los del renglón, y NO
# los del pedido: hasta el ticket 20 un pedido no tenía estado porque no había
# nada que hacerle. `borrador` y `enviado` son vocabulario nuevo y por eso
# entraron también al glosario, que manda sobre el nombre de cualquier cosa.

#: Nace así y se puede modificar mientras siga así (tercera casilla del ticket
#: 20). Un borrador todavía **no se le ha pedido a nadie**: por eso repartir un
#: renglón no lo pone `en tránsito` —el glosario dice que eso es "ya se le pidió
#: a un proveedor"— y quien lo pone es el ticket 21, al enviar.
BORRADOR = "borrador"

#: **Una persona ya lo capturó en el portal del proveedor** (ticket 21).
#:
#: La palabra miente si se lee sola y por eso el glosario y la pantalla la
#: desmienten en el mismo sitio donde aparece: *Continental no le manda nada a
#: ningún proveedor* y no va a hacerlo (regla 1 de `CLAUDE.md`, y el ADR 0002 lo
#: dejó fuera de alcance). Lo que se guarda es la **declaración** de quien lo
#: capturó, firmada con el correo que verificó Access. Ver el ADR 0009.
#:
#: Dos cosas cuelgan de este valor y las dos son garantías de la tabla, no
#: costumbres del código: un pedido `enviado` ya no se modifica —el `WHERE` de
#: `_ABRIR_EL_PEDIDO`, `_ASIGNAR_RENGLONES` y `_SOLTAR_RENGLONES` lo protege— y
#: sus renglones pasan a `en tránsito`, que es lo que impide volver a
#: proponerlos mañana.
ENVIADO = "enviado"

#: **Una persona dijo que este pedido NO está en el portal del proveedor**
#: (ticket 25, ADR 0013): nunca se capturó, o se canceló allá también. Solo se
#: llega desde `enviado`, lleva firma —`cancelado_por`, `cancelado_en`— y es un
#: final.
#:
#: **No es "desenviar"**, que el ADR 0009 negó y sigue negado: un pedido
#: cancelado no vuelve a `borrador`, no se edita, no se vuelve a enviar y no se
#: descancela. Lo que hace es soltar sus renglones del tránsito —pasan a
#: `cancelado`— para que su mercancía se vuelva a proponer. Continental no
#: cancela nada en ningún portal, igual que no captura nada en ninguno.
CANCELADO = "cancelado"

#: Los dos, y ningún sinónimo. El DDL los repite en `ck_pedido_estado` y
#: `test_sql_del_pedido.py` compara esta tupla contra el archivo `.sql`.
#:
#: El ticket 20 se quedó con uno solo a propósito —el glosario no tenía el otro
#: todavía, y este repositorio ya pagó por adelantar un nombre ajeno— y dejó
#: anotado lo que costaría: *el ticket 21 paga una migración para ampliar
#: `ck_pedido_estado`*. Es la 0006, y se corre a mano con credenciales de dueño
#: — el código de arranque no aplica DDL nunca (ADR 0003), y hay una prueba que
#: se pone roja si este archivo llega siquiera a nombrar esa carpeta.
#:
#: **`cancelado` llegó con el ticket 25** (ADR 0013), y hasta ese día esta nota
#: decía que no existía "porque nadie lo ha pedido". El ticket lo pidió.
ESTADOS_DEL_PEDIDO: tuple[str, ...] = (BORRADOR, ENVIADO, CANCELADO)

# ------------------------------------------- cómo acaba una corrida del lote
#
# Viven aquí y no en `lote.py`, aunque sea el lote quien los escribe, y la
# razón es la misma por la que los estados de la lista viven aquí: **el DDL los
# repite en un CHECK** (`ck_corrida_final`), y lo que tiene CHECK tiene que
# estar donde está el resto del vocabulario de las tablas. `lote.py` los
# reexporta para que quien lea el lote los encuentre donde los busca, y
# `test_sql_del_pedido.py` compara esta tupla contra el archivo `.sql`.
#
# Importarlos al revés —que esto importara de `lote.py`— sería un ciclo: el
# lote ya importa este módulo entero.

#: Se consultaron todos los renglones de la lista y sobró tiempo.
TERMINO = "terminó"

#: Se acabaron los minutos del tope con renglones por consultar. **No es un
#: error**: es exactamente lo que el ticket 18 pide que pase, y es el hecho del
#: que sale la frase *"el lote se cortó por tiempo"* del ticket 19.
SE_ACABO_EL_TIEMPO = "se acabó el tiempo"

#: Algo tumbó la corrida entera: Postgres se cayó, alguien mató el proceso. Lo
#: que ya se había guardado sigue guardado — no hay nada que deshacer.
SE_INTERRUMPIO = "se interrumpió"

#: No hubo lista que consultar. La farmacia cierra los domingos y no hay una
#: sola venta en domingo en 33 meses: un lote que no encuentra ventas no falló.
SIN_LISTA = "no hubo lista"

#: Los cuatro, y ningún sinónimo. El DDL los repite en `ck_corrida_final`.
FINALES_DE_LA_CORRIDA: tuple[str, ...] = (
    TERMINO,
    SE_ACABO_EL_TIEMPO,
    SE_INTERRUMPIO,
    SIN_LISTA,
)

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

#: Lo menos que se le puede pedir a un proveedor cuando alguien corrige la
#: cantidad: **una pieza**. Es el `CHECK (cantidad_final >= 1)` del DDL escrito
#: en Python, y el número que la ruta cita al rechazar un cero.
#:
#: Un cero NO es una forma de descartar y por eso no se acepta aquí (ticket 11).
#: Guardado valdría "pídeme cero piezas": ni pedido ni descartado, sin firma de
#: descarte, invisible para el conteo del ADR 0002 y visible en la lista de
#: trabajo como si quedara algo por atender. El glosario ya tiene el estado para
#: eso —`descartado`, "una persona decidió no pedirlo"— y viene con su quién y
#: su cuándo.
#:
#: Ojo con la asimetría contra `ck_renglon_cantidad`, que sí admite el cero en
#: `cantidad_propuesta`: ahí el cero lo escribe el sistema y significa "de esto
#: no se vendió nada", que es un hecho aritmético sin nadie detrás. Aquí lo
#: escribiría una persona, y una persona que no quiere pedir algo tiene un botón
#: para decirlo.
CANTIDAD_FINAL_MINIMA = 1


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
    corte: dt.date | None,
    hasta: dt.date,
    dias_primera_vez: int,
    piso_sin_pedir: dt.date | None = None,
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

    ## El piso, que llegó el 2026-09-20 con la ventana corta

    `piso_sin_pedir` es el principio de la lista más vieja que se quedó
    `abierta` o `vencida`: ventas que **se propusieron y nadie pidió**. La
    ventana nunca empieza después de ese día.

    Hasta esa fecha `dias_primera_vez` valía 7 y esto no hacía falta: una
    ventana de una semana volvía a recoger, por accidente, lo que nadie había
    cerrado. Al bajarla a **un día hábil** —para que la lista sea corta y
    legible, que es lo que se pidió— esa red desapareció, y sin este piso las
    ventas de un día desatendido **se caen al suelo sin un solo error que ver**.
    Es la falla silenciosa que prohíbe la regla 4, y la alternativa —confiar en
    que el encargado cierre su lista todos los días— es justo la clase de
    garantía que este repo no acepta.

    **SOLO SE APLICA CUANDO NO HAY CORTE, y esa restricción es la que impide
    duplicar.** Con un corte ya existente, la ventana empieza en `corte + 1` y
    ahí el piso sobra — peor, haría daño: si el lunes quedó `abierta` y el
    martes se `cerró`, retroceder hasta el lunes volvería a proponer **también
    el martes**, que ya se pidió. Las piezas de los dos días se sumarían en un
    solo número por renglón y el pedido saldría del doble **sin que se vea**,
    que es exactamente lo que el ADR 0002 prohíbe. `Ventana` es un intervalo y
    no un conjunto de días, así que no puede saltarse el martes por dentro.

    > **Y no deja ningún día fuera, aunque al escribir esto se creyó que sí.**
    > Aquí quedó anotado que "un día sin cerrar anterior a un corte posterior
    > se pierde igual". **Es falso**, y lo mide
    > `test_un_dia_sin_cerrar_no_se_pierde_aunque_despues_se_cierre_otro`. El
    > corte es `max(...)` sobre las **cerradas**, así que una lista abierta o
    > vencida no lo mueve: el corte se queda atrás y `corte + 1` alcanza sola
    > cualquier racha de días sin cerrar, sea de uno o de diez.
    >
    > Las dos ramas juntas cubren el calendario entero sin huecos y sin
    > traslapes: con corte, desde el día siguiente al corte; sin corte, desde
    > lo más viejo que nadie pidió. Por eso **no hace falta ni una ventana más
    > larga ni segmentar la lista por día** — las dos se consideraron el
    > 2026-09-20 para tapar un hueco que no estaba abierto.

    Quien tiene que **decirlo en la pantalla** es quien la arma: una ventana de
    cinco días y una de uno se ven igual en los renglones, porque las piezas se
    suman en un solo número.
    """
    if corte is None:
        desde = hasta - dt.timedelta(days=dias_primera_vez - 1)
        if piso_sin_pedir is not None:
            desde = min(desde, piso_sin_pedir)
        return Ventana(desde=desde, hasta=hasta)

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


#: La llave del YAML, escrita una vez: la usan la lectura y los mensajes.
LLAVE_DEL_ATRASO = "dias_en_transito_para_atrasado"


def dias_en_transito_para_atrasado_configurados() -> int:
    """El N del ticket 25: **más** de cuántos días en camino es "atrasado".

    Sale de `config/continental.yml` (`pedido.dias_en_transito_para_atrasado`),
    con su comentario de por qué vale lo que vale. No hay un número de omisión
    en el código, y es a propósito.

    **Truena si falta o está mal escrito, al revés que sus vecinas.**
    `dias_primera_vez_configurados` y los topes del lote caen a un valor y
    avisan porque tronar ahí dejaría a la farmacia sin pedido del día o sin lote
    nocturno. Aquí tronar no deja a nadie sin nada: lo único que se pierde es la
    señal —y la ruta la enseña como un hueco con su motivo (regla 4)—. Caer a
    un número elegido en silencio sería peor: es el número que decide cuándo se
    ofrece **devolver a la lista** algo que se pidió, y una válvula que se abre
    en un día que nadie escogió es exactamente cómo se pide dos veces.

    Un entero y nada más: `"7"` entre comillas, `7.5`, `True` —que en Python
    es un `int`— y cualquier cosa menor que uno se rechazan. Un `7.5` no es un
    número de días de calendario, y truncarlo a 7 sería decidir por el dueño.
    """
    from continental.config import cargar

    crudo = cargar().pedido.get(LLAVE_DEL_ATRASO)
    if isinstance(crudo, bool) or not isinstance(crudo, int) or crudo < 1:
        raise ValueError(
            f"config/continental.yml no trae un `pedido.{LLAVE_DEL_ATRASO}` "
            f"utilizable ({crudo!r}): tiene que ser un entero de días, uno o más. "
            "Sin él no se puede decir qué tránsito está atrasado, y no se "
            "inventa uno."
        )
    return crudo


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

    `cantidad_final` es lo que una persona decidió pedir (ticket 11), y vive
    **aparte** de `propuesto.cantidad_propuesta`, que es lo que el sistema
    propuso y **no se sobreescribe nunca**. La diferencia entre las dos es el
    dato: es lo único que después va a decir si la reposición 1 a 1 está bien
    calibrada. Si al corregir se pisara la propuesta, esa diferencia valdría
    cero siempre y nadie se enteraría de que el dato se perdió.

    **`None` es "nadie la tocó", y no se copia la propuesta al nacer.** Nacer
    con las dos iguales haría indistinguibles dos hechos que no son el mismo:
    un renglón que nadie revisó y uno que alguien miró y confirmó igual. El
    segundo es evidencia de que la propuesta acertó; el primero no dice nada.

    `ajustada_por` y `ajustada_en` son la firma de esa corrección, con el mismo
    criterio que `descartado_por` / `descartado_en` y su mismo CHECK pareado
    (`ck_renglon_ajuste`): o están las dos con la cantidad, o no está ninguna.
    Firma y no permiso (regla 3 de `CLAUDE.md`).

    `proveedor_elegido` es **a quién decidió una persona pedírselo** (ticket
    20), con su firma pareada en `elegido_por` / `elegido_en`. `None` quiere
    decir *nadie eligió*, igual que `cantidad_final`.

    **Lo que el sistema sugiere NO está aquí y no se guarda**, y esa es la
    diferencia consciente con el ticket 11: la sugerencia se recalcula de
    `comparacion.elegir_ganador`, que es pura sobre una tabla de precios que
    solo crece, así que una copia guardada sería un segundo hecho que envejece
    sin avisar. `cantidad_propuesta` sí se guarda porque **no** se puede
    recalcular: las ventas de su ventana ya pasaron. El porqué completo está en
    el encabezado de `particion.py`.

    `pedido_id` es el pedido al que quedó repartido (ticket 20). Nace `None` y
    lo escribe `guardar_la_particion`. Es UNA columna y no una tabla de cruce:
    "un renglón pertenece a un solo pedido" se defiende en la tabla y no en un
    `if` — ver `sql/crear_tablas.sql`, donde `fk_renglon_pedido` además lleva
    `pedido_sugerido_id` para que el pedido sea de **esta** lista.

    `capturado_por` y `capturado_en` son **la marca de captura** (ticket 22): una
    persona dice que ya tecleó este renglón en el portal del proveedor de su
    pedido. Es el avance de la pantalla de captura, y vive aquí —en la tabla, y
    no en el navegador— por lo que razona el ADR 0010: dos pestañas no
    divergen, cambiar de máquina no lo pierde, y cada marca dice quién la puso.

    **No es un estado**, y es a propósito: un renglón dentro de un borrador sigue
    `abierto` (ticket 20) y tachar no lo mueve, porque `_ASIGNAR_RENGLONES`,
    `_SOLTAR_RENGLONES`, `_DESCARTAR` y `_AJUSTAR_LA_CANTIDAD` llevan `estado =
    'abierto'` en su `WHERE` y un estado nuevo los dejaría saltárselo en
    silencio. La firma va pareada por `ck_renglon_captura`, igual que las otras
    cuatro del esquema.
    """

    renglon_id: int
    estado: str
    propuesto: Renglon
    descartado_por: str | None = None
    descartado_en: dt.datetime | None = None
    cantidad_final: int | None = None
    ajustada_por: str | None = None
    ajustada_en: dt.datetime | None = None
    pedido_id: int | None = None
    proveedor_elegido: str | None = None
    elegido_por: str | None = None
    elegido_en: dt.datetime | None = None
    capturado_por: str | None = None
    capturado_en: dt.datetime | None = None
    cancelado_por: str | None = None
    cancelado_en: dt.datetime | None = None

    @property
    def esta_capturado(self) -> bool:
        """Si alguien dijo ya haberlo tecleado en el portal (ticket 22).

        Es una firma y nunca un permiso (regla 3 de `CLAUDE.md`), y **no es un
        estado del renglón**: ver el docstring de la clase y el ADR 0010.
        """
        return self.capturado_por is not None

    @property
    def cantidad_a_pedir(self) -> int:
        """Lo que de verdad se le va a pedir al proveedor.

        La corrección de la persona si la hubo, y si no la propuesta del
        sistema. Vive aquí —en Python, probado— y no repetida en el JavaScript
        de la pantalla ni en un `coalesce` de cada consulta futura: es la regla
        que decide qué cantidad se copia al pedido, y una regla escrita dos
        veces se cambia una sola.
        """
        return (
            self.propuesto.cantidad_propuesta
            if self.cantidad_final is None
            else self.cantidad_final
        )

    @property
    def fue_ajustada(self) -> bool:
        """Si alguien decidió la cantidad, aunque haya decidido la misma.

        Es lo que distingue "nadie lo revisó" de "alguien lo revisó", y por eso
        no se deduce comparando las dos cifras: confirmar el 3 que el sistema
        propuso es una decisión, y borrarla del dato sería tirar la única
        evidencia de que la reposición 1 a 1 acertó ese día.
        """
        return self.cantidad_final is not None

    @property
    def difiere_de_la_propuesta(self) -> bool:
        """Si lo que se va a pedir no es lo que el sistema propuso.

        Lo que la pantalla usa para mostrar las dos cifras juntas. Separado de
        `fue_ajustada` a propósito: enseñar "el sistema propuso 3" al lado de un
        3 es ruido, y el ruido se deja de leer justo antes de que aparezca el
        renglón donde la diferencia importaba.
        """
        return self.fue_ajustada and self.cantidad_final != self.propuesto.cantidad_propuesta

    @property
    def esta_descartado(self) -> bool:
        """Si una persona decidió no pedirlo (`CONTEXT.md`).

        Vive aquí y no repetida en cada consumidor por la misma razón que
        `esta_agotado` vive en `sugerido.Renglon`: es la regla que decide si un
        renglón sale de la lista de trabajo, y una regla que se escribe dos
        veces se cambia una sola.
        """
        return self.estado == RENGLON_DESCARTADO

    @property
    def fue_elegido(self) -> bool:
        """Si una persona decidió a quién pedírselo.

        Es el par de `fue_ajustada` y existe por lo mismo: distingue "nadie lo
        revisó" de "alguien lo revisó", **aunque haya elegido lo que el sistema
        sugería**. Confirmar la sugerencia es una decisión, y deducirla
        comparando con el ganador de hoy la borraría — el ganador de hoy puede
        no ser el de ayer, porque la tabla del precio solo crece.
        """
        return self.proveedor_elegido is not None

    @property
    def esta_repartido(self) -> bool:
        """Si ya quedó dentro de un pedido."""
        return self.pedido_id is not None

    @property
    def esta_en_transito(self) -> bool:
        """Si ya se le pidió a un proveedor y todavía no llega (`CONTEXT.md`).

        Lo escribe el envío del pedido (ticket 21) y es lo que lo saca de todo
        lo que queda por hacer: no se vuelve a repartir, no se vuelve a
        consultar su precio y no cuenta como hueco. Vive aquí —en Python,
        probado— por la misma razón que `esta_descartado`: una regla que decide
        si un renglón sigue pendiente no puede estar escrita dos veces.
        """
        return self.estado == RENGLON_EN_TRANSITO

    @property
    def esta_cancelado(self) -> bool:
        """Si se dejó de esperar sin haber llegado (ticket 25, ADR 0013).

        Su pedido se canceló, o alguien lo devolvió a la lista por atrasado.
        **No es "abierto otra vez"**: no se reparte, no se tacha y no se
        consulta; lo que vuelve es su producto, en la siguiente lista. Separado
        de `esta_en_transito` por la misma razón que `fue_cancelado` lo está de
        `fue_enviado` en el pedido.
        """
        return self.estado == RENGLON_CANCELADO

    @property
    def se_puede_repartir(self) -> bool:
        """Si todavía se le puede meter en un pedido.

        Solo lo `abierto`, que es exactamente el `WHERE` de
        `_ASIGNAR_RENGLONES`. Un descartado ya se atendió y uno `en tránsito` ya
        se pidió; los dos de recepción llegarán con el ticket 26.
        """
        return self.estado == RENGLON_ABIERTO


@dataclass(frozen=True, slots=True)
class PedidoGuardado:
    """Un pedido con fila: a quién se le pide, en qué estado y cuánto cuesta.

    **La identidad es `proveedor`, la clave de Doyle**, y `proveedor_id` es la
    correspondencia con SICAR — que puede faltar—. El porqué entero está en
    `docs/decisiones/0008-*` y en `proveedores.py`; en corto: se le pide a quien
    se le preguntó el precio, y que la farmacia nunca le haya comprado a
    QuePharma no es una razón para no empezar hoy.

    `total_sin_iva` es `None` cuando **no se puede saber** —alguna línea va sin
    precio, o el pedido se quedó sin renglones—, y jamás la suma de lo que sí se
    sabe. Ver `particion.PedidoPorArmar.total_sin_iva`.

    `enviado_por` y `enviado_en` son la **firma del envío** (ticket 21), y
    valen `None` en todo pedido que no esté `enviado` — lo exige
    `ck_pedido_envio`, el mismo par que `ck_renglon_descarte` y
    `ck_renglon_eleccion`.

    Firma y no acuse, y la diferencia importa (ADR 0009): el hecho que se
    guarda —*"ya lo capturé en el portal de NADRO"*— ocurrió en otra pantalla,
    con otras credenciales, y Continental no lo vio. Lo único verdadero que se
    puede escribir es **quién lo dice y cuándo lo dijo**. Es una firma y nunca
    un permiso (regla 3 de `CLAUDE.md`): sirve para saber a quién preguntarle
    qué se capturó cuando la factura no cuadre.
    """

    pedido_id: int
    negocio: str
    pedido_sugerido_id: int
    proveedor: str
    proveedor_id: int | None
    estado: str
    armado_en: dt.datetime
    total_sin_iva: Decimal | None = None
    enviado_por: str | None = None
    enviado_en: dt.datetime | None = None
    cancelado_por: str | None = None
    cancelado_en: dt.datetime | None = None

    @property
    def tiene_puente(self) -> bool:
        """Si a este proveedor le corresponde un `pro_id` de SICAR."""
        return self.proveedor_id is not None

    @property
    def es_borrador(self) -> bool:
        """Si todavía se puede modificar (tercera casilla del ticket 20)."""
        return self.estado == BORRADOR

    @property
    def fue_enviado(self) -> bool:
        """Si alguien ya declaró haberlo capturado en el portal (ticket 21).

        Separado de `not es_borrador` a propósito, aunque hoy sean lo mismo: el
        día que haya un tercer estado —cancelado, por ejemplo— "no es borrador"
        dejaría de querer decir "se capturó", y la pantalla escribiría la frase
        del envío sobre un pedido que nadie envió.
        """
        return self.estado == ENVIADO

    @property
    def fue_cancelado(self) -> bool:
        """Si alguien dijo que no está en el portal del proveedor (ticket 25).

        Es el caso que la nota de `fue_enviado` anticipó: "no es borrador" ya no
        quiere decir "se capturó". Un pedido cancelado conserva la firma de su
        envío —alguien SÍ dijo haberlo capturado, y eso también es su historia—
        y agrega la suya.
        """
        return self.estado == CANCELADO

    @property
    def nombre(self) -> str:
        """Cómo se escribe el proveedor, según el glosario."""
        return nombre_del_proveedor(self.proveedor)


@dataclass(frozen=True, slots=True)
class PedidoEnviado:
    """Lo que dejó el envío de un pedido: la fila nueva y qué se movió (21).

    Son **dos hechos y no uno**, y por eso no basta con devolver el pedido: el
    `UPDATE` del pedido y el de sus renglones son dos sentencias dentro de la
    misma transacción, y quien llama tiene que poder decir en la bitácora
    cuántos renglones pasaron a `en tránsito`. Un envío que marcara el pedido y
    no moviera un solo renglón es justo la falla silenciosa que hay que poder
    ver: la lista seguiría proponiendo mañana lo que ya se pidió hoy.

    `renglones` son los ids, en el orden en que el `RETURNING` los entrega. Se
    guardan los ids y no el conteo porque el conteo se saca de ellos y al revés
    no: si algún día hace falta decir *cuáles*, ya están.
    """

    pedido: PedidoGuardado
    renglones: tuple[int, ...] = ()

    @property
    def cuantos_renglones(self) -> int:
        return len(self.renglones)


@dataclass(frozen=True, slots=True)
class PedidoCancelado:
    """Lo que dejó cancelar un pedido: la fila nueva y qué renglones soltó (25).

    La misma forma que `PedidoEnviado`, y por lo mismo: son **dos** `UPDATE` en
    una transacción —el pedido y sus renglones— y quien llama tiene que poder
    decir en la bitácora cuántos renglones dejaron de estar en camino. Un pedido
    cancelado que no soltara ninguno sería la falla silenciosa al revés: su
    mercancía seguiría fuera de la lista para siempre.
    """

    pedido: PedidoGuardado
    renglones: tuple[int, ...] = ()

    @property
    def cuantos_renglones(self) -> int:
        return len(self.renglones)


@dataclass(frozen=True, slots=True)
class LoYaPedido:
    """Un renglón que ya se le pidió a un proveedor, con lo que hace falta saber (24).

    Es lo que `lo_ya_pedido` lee y lo que `transito.py` usa para dos cosas: la
    **memoria** con la que se arma la lista —qué no se vuelve a proponer, y
    desde qué día vuelve lo que ya llegó— y el **bloque** de la pantalla que
    enseña lo que viene en camino.

    `renglon` es el `RenglonGuardado` **entero**, y la composición es a
    propósito, igual que `RenglonGuardado.propuesto`: `cantidad_a_pedir` —lo
    que de verdad se le pidió— ya vive ahí, probada, y reescribirla con un
    `coalesce` en la consulta sería la misma regla dos veces.

    **`ventas_hasta` es el ancla, y es la decisión del ticket** (ADR 0012): el
    último día de ventas que ese renglón repuso, que es la
    `ventas_consideradas_hasta` de su lista y existe desde el ticket 08. Lo que
    se venda del producto **después** de ese día es lo que se retiene mientras
    viene en camino y lo que vuelve al recibirlo. No se copia ninguna venta: se
    vuelven a leer de `marts.fct_ventas`, que es donde ya estaban — y así las
    que llegan tarde (el sábado, que llega el lunes) entran solas.

    `proveedor`, `enviado_por` y `enviado_en` son del **pedido**, y valen `None`
    solo en un estado que ningún código escribe: un renglón en tránsito sin
    pedido enviado. Se dicen así en vez de tronar, porque este dato se enseña
    y esconder el renglón es justo lo que la casilla 4 prohíbe.
    """

    renglon: RenglonGuardado
    pedido_sugerido_id: int
    fecha_del_pedido: dt.date
    ventas_hasta: dt.date
    proveedor: str | None
    enviado_por: str | None
    enviado_en: dt.datetime | None
    #: El principio de la ventana de su lista (`ventas_consideradas_desde`).
    #: Lo necesita **solo** el renglón cancelado (ticket 25): vuelve desde el
    #: principio de lo que cubría, y eso es este día o su `ventas_desde`.
    ventas_desde_la_lista: dt.date | None = None
    #: El estado de su pedido: distingue "se canceló el pedido entero" de "lo
    #: devolvieron a la lista a él solo", que se dicen distinto en la pantalla.
    estado_del_pedido: str | None = None

    def __post_init__(self) -> None:
        # Un cancelado sin el principio de su lista no sabe desde cuándo vuelve.
        # Adivinarlo —el ancla, la fecha de la lista— sería perder ventas o
        # proponerlas dos veces, en silencio (regla 4): se truena.
        if self.renglon.esta_cancelado and self.ventas_desde_la_lista is None:
            raise ValueError(
                f"El renglón {self.renglon.renglon_id} está cancelado y no trae el "
                "principio de la ventana de su lista: no se sabe desde qué día "
                "vuelve su producto (ADR 0013)."
            )

    @property
    def producto_id(self) -> int:
        return self.renglon.propuesto.producto_id

    @property
    def esta_en_transito(self) -> bool:
        return self.renglon.esta_en_transito

    @property
    def ya_se_cerro(self) -> bool:
        """Si llegó: el tránsito se cerró y lo retenido vuelve a proponerse."""
        return self.renglon.estado in ESTADOS_QUE_CIERRAN_EL_TRANSITO

    @property
    def fue_cancelado(self) -> bool:
        """Si se dejó de esperar sin llegar (ticket 25)."""
        return self.renglon.esta_cancelado

    @property
    def se_cancelo_el_pedido(self) -> bool:
        """Si lo que lo canceló fue su pedido entero, y no una devolución suya."""
        return self.fue_cancelado and self.estado_del_pedido == CANCELADO

    @property
    def vuelve_a_proponerse(self) -> bool:
        """Si su producto ya no viene en camino y algo suyo falta por proponer.

        Llegó —`recibido`, `recibido parcial`— o se canceló. Los dos vuelven;
        lo que cambia es **desde cuándo**, y eso lo dice `retiene_desde`.
        """
        return self.renglon.estado in ESTADOS_QUE_TERMINAN_EL_TRANSITO

    @property
    def retiene_desde(self) -> dt.date:
        """El primer día de ventas cuyo producto **todavía no se pidió**.

        - **En camino o recibido** (ADR 0012): el día siguiente al ancla. Lo
          del ancla hacia atrás ya se pidió; lo de después es lo retenido.
        - **Cancelado** (ADR 0013): **el principio de lo que cubría**. Nunca se
          pidió —o nunca llegó y se dejó de esperar—, así que también vuelve lo
          que ese renglón repuso: desde su `ventas_desde` si tenía ventana
          propia, y si no desde el principio de su lista.
        """
        if self.fue_cancelado:
            return self.renglon.propuesto.ventas_desde or self.ventas_desde_la_lista
        return self.ventas_hasta + dt.timedelta(days=1)

    @property
    def nombre_del_proveedor(self) -> str | None:
        """Cómo se escribe el proveedor, según el glosario. `None` si no quedó escrito."""
        return None if self.proveedor is None else nombre_del_proveedor(self.proveedor)


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
    def en_transito(self) -> int:
        """Cuántos renglones de esta lista ya se le pidieron a un proveedor.

        Es el efecto visible de enviar un pedido (ticket 21) y se cuenta sobre
        lo guardado, no sobre los pedidos: la pregunta es cuánta de esta lista
        ya está pedida, y la contesta el estado del renglón —que es donde el
        glosario la puso—.
        """
        return sum(1 for r in self.renglones if r.esta_en_transito)

    @property
    def por_repartir(self) -> tuple[RenglonGuardado, ...]:
        """Los renglones que todavía se pueden meter en un pedido.

        Es `de_trabajo` **menos lo que ya se pidió**, y son dos propiedades y no
        una porque contestan dos preguntas distintas: `de_trabajo` es "qué no
        está descartado" —lo que se pinta en la tabla— y esto es "qué queda por
        hacer".

        Nace con el ticket 21 porque antes de él **ningún código escribía
        `en tránsito`**: `de_trabajo` nunca había visto uno, así que las cuatro
        cuentas que cuelgan de aquí —la partición, el conteo de huecos, la cola
        del botón de completar y el aviso de sesiones caducadas— daban lo mismo
        con las dos. A partir de aquí no: un renglón ya pedido que siguiera
        contando mandaría a consultar cuatro portales ajenos por mercancía que
        ya está en camino, y haría que la vista previa de la partición
        prometiera mover un renglón que el `WHERE` de `_ASIGNAR_RENGLONES` no
        puede mover.
        """
        return tuple(r for r in self.renglones if r.se_puede_repartir)

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

    `proveedor_elegido`, `elegido_por` y `elegido_en` van igual y en `None`:
    **un renglón nace sin que nadie haya decidido a quién pedírselo** (ticket
    20). Copiar aquí la sugerencia del sistema sería el mismo error que copiar
    la propuesta en `cantidad_final`, y uno peor encima: la sugerencia cambia
    sola cuando llega un precio nuevo, así que la columna envejecería sin que
    nadie pudiera distinguirla de una decisión.

    `cantidad_final`, `ajustada_por` y `ajustada_en` van igual, y las tres en
    `None`: **un renglón nace sin que nadie haya corregido su cantidad**. Poner
    aquí `cantidad_final = renglon.cantidad_propuesta` sería cómodo —la pantalla
    no tendría que elegir entre dos columnas— y borraría el dato del ticket 11:
    con las dos iguales desde el nacimiento no hay forma de saber si alguien la
    revisó. `ck_renglon_ajuste` relaciona a las tres igual que
    `ck_renglon_descarte` a las suyas.
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
        "cantidad_final": None,
        "ajustada_por": None,
        "ajustada_en": None,
        # Un renglón nace SIN pedido y SIN proveedor elegido, y las cuatro van
        # explícitas en `None` por la misma razón que las de arriba:
        # `ck_renglon_eleccion` relaciona a tres de ellas y escribirlas juntas
        # deja ver que se respeta. `pedido_id` nulo es "nadie lo ha repartido"
        # (lo dice el COMMENT de la columna desde el ticket 07).
        "pedido_id": None,
        "proveedor_elegido": None,
        "elegido_por": None,
        "elegido_en": None,
        # Y SIN TACHAR (ticket 22): nadie lo ha capturado en ningún portal. Las
        # dos explícitas por lo mismo que las de arriba: `ck_renglon_captura`
        # las relaciona.
        "capturado_por": None,
        "capturado_en": None,
        # Y SIN CANCELAR (ticket 25): nace esperándose. Explícitas por lo mismo
        # que las de arriba: `ck_renglon_cancelacion` las relaciona con el
        # estado.
        "cancelado_por": None,
        "cancelado_en": None,
        # DESDE QUÉ DÍA SE SUMARON SUS VENTAS, si no es el principio de la
        # lista (ticket 24, ADR 0012). Casi siempre `None`. Es un dato del
        # CÁLCULO —lo decide la memoria de lo ya pedido al armar— y por eso
        # viene en el renglón propuesto y no se inventa aquí.
        "ventas_desde": renglon.ventas_desde,
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
        # Con `.get` por la misma razón que las columnas de los tickets 20 y
        # 22: sin la migración 0008 la fila no la trae, y eso es "desde el
        # principio de la lista", no un KeyError que tumbe la pantalla.
        ventas_desde=fila.get("ventas_desde"),
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
    if (
        columnas["cantidad_final"] is not None
        and columnas["cantidad_final"] < CANTIDAD_FINAL_MINIMA
    ):
        raise ValueError(
            f"Cantidad final de {columnas['cantidad_final']}: lo rechaza "
            "ck_renglon_cantidad_final, que exige al menos "
            f"{CANTIDAD_FINAL_MINIMA}. **Un cero no es una forma de "
            "descartar**: para eso está el estado 'descartado', que además "
            "guarda quién y cuándo. Un cero guardado sería un renglón que no "
            "se pidió, no se descartó y sigue contando como trabajo por "
            "atender."
        )
    if columnas["ajustada_por"] == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (ajustada_por <> ''): o hay "
            "correo o es NULL, igual que en el descarte."
        )
    if (columnas["cantidad_final"] is not None) != (
        columnas["ajustada_por"] is not None and columnas["ajustada_en"] is not None
    ):
        raise ValueError(
            "Cantidad corregida sin decir quién ni cuándo, o firma de ajuste "
            "sin cantidad. Lo rechaza ck_renglon_ajuste. Sin la firma, la "
            "diferencia entre lo propuesto y lo pedido no se le puede "
            "preguntar a nadie; con la firma suelta, diría que alguien corrigió "
            "un renglón que nadie tocó."
        )
    # Las tres del ticket 20. Se leen con `.get` y no con `[...]` a propósito:
    # una fila leída de una base a la que todavía no se le corrió la migración
    # 0005 no las trae, y lo que tiene que pasar entonces es "nadie eligió" y no
    # un `KeyError` que tumbe la pantalla entera por una columna que falta.
    if columnas.get("proveedor_elegido") == "":
        raise ValueError(
            "Proveedor elegido vacío. La columna tiene CHECK "
            "(proveedor_elegido <> ''): o hay clave de proveedor o es NULL, "
            "igual que la clave y las dos firmas. Una cadena vacía se compara "
            "igual que un dato y empareja con cualquier otra vacía."
        )
    if columnas.get("elegido_por") == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (elegido_por <> ''): o hay "
            "correo o es NULL, igual que en el descarte y en el ajuste."
        )
    if (columnas.get("proveedor_elegido") is not None) != (
        columnas.get("elegido_por") is not None
        and columnas.get("elegido_en") is not None
    ):
        raise ValueError(
            "Proveedor elegido sin decir quién ni cuándo, o firma de elección "
            "sin proveedor. Lo rechaza ck_renglon_eleccion. Sin la firma no hay "
            "a quién preguntarle por qué se le compró a LEVIC habiendo NADRO "
            "más barato, que es la pregunta entera del ticket 20; con la firma "
            "suelta, diría que alguien eligió lo que nadie eligió."
        )
    # Las dos del ticket 22, con `.get` por lo mismo que las del 20: una fila
    # de una base sin la migración 0007 no las trae, y eso es "nadie tachó".
    if columnas.get("capturado_por") == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (capturado_por <> ''): o hay "
            "correo o es NULL, igual que las otras cuatro firmas del esquema."
        )
    if (columnas.get("capturado_por") is None) != (
        columnas.get("capturado_en") is None
    ):
        raise ValueError(
            "Captura sin decir quién o sin decir cuándo. Lo rechaza "
            "ck_renglon_captura. Una marca sin firma es un 'ya se capturó' en "
            "voz pasiva, y cuando la factura no cuadre no habría a quién "
            "preguntarle qué se tecleó en el portal (ADR 0010)."
        )
    # Las dos del ticket 25, con `.get` por lo mismo que las del 20 y el 22:
    # una fila de una base sin la migración 0009 no las trae, y eso es "nadie
    # canceló", no un KeyError.
    if columnas.get("cancelado_por") == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (cancelado_por <> ''): o hay "
            "correo o es NULL, igual que las otras firmas del esquema: "
            "ck_renglon_cancelado_por."
        )
    if (columnas["estado"] == RENGLON_CANCELADO) != (
        columnas.get("cancelado_por") is not None
        and columnas.get("cancelado_en") is not None
    ):
        raise ValueError(
            "Cancelado sin decir quién ni cuándo, o firma de cancelación en un "
            "renglón que no está cancelado. Lo rechaza ck_renglon_cancelacion. "
            "Un renglón cancelado vuelve a proponerse entero en la siguiente "
            "lista (ADR 0013): sin la firma no hay a quién preguntarle por qué "
            "se dejó de esperar algo que quizá sí venía."
        )



# ------------------------------------------- el pedido por proveedor (20)


def columnas_del_pedido(
    negocio: str,
    pedido_sugerido_id: int,
    proveedor: str,
    proveedor_id: int | None,
    total_sin_iva: Decimal | None,
) -> dict:
    """Las columnas de `pedidos.pedido` al armarlo: en `borrador` y sin enviar.

    `estado` va explícito aunque el DDL tenga `DEFAULT 'borrador'`, por la misma
    razón que `columnas_de_la_lista` escribe el suyo: lo que se escribe se lee.

    `proveedor_id` puede ser `None` y **eso no impide armar el pedido**. Es el
    estado de QuePharma hoy (`proveedores.py`). Nunca un cero: un cero es un id
    que no existe y que aun así cabe en un `bigint`, y a partir de ahí todo
    `join` contra `dim_proveedor` sale vacío sin error.

    **La firma del envío no está aquí y no es un olvido** (ticket 21): un
    pedido nace sin ella porque nace en `borrador`, y `ck_pedido_envio` exige
    justo eso. Quien la escribe es `enviar_el_pedido`, en su `UPDATE`, que es el
    único momento en que hay algo que firmar.
    """
    return {
        "negocio": negocio,
        "pedido_sugerido_id": pedido_sugerido_id,
        "proveedor": proveedor,
        "proveedor_id": proveedor_id,
        "estado": BORRADOR,
        "total_sin_iva": total_sin_iva,
    }


def revisar_el_pedido(columnas: dict) -> None:
    """Los CHECK de `pedidos.pedido`, escritos en Python.

    Lo mismo que hacen `revisar_la_lista` y `revisar_el_renglon`, y por lo
    mismo: sin esto el doble aceptaría en la torre lo que en atlas rebota.
    """
    if not columnas["negocio"]:
        raise ValueError("negocio vacío: lo rechaza ck_pedido_negocio.")
    if not columnas["proveedor"]:
        raise ValueError(
            "Proveedor vacío: lo rechaza ck_pedido_proveedor. Sin saber a quién "
            "se le pide, el pedido no sirve para nada — y la clave de Doyle es "
            "la identidad del pedido, no el proveedor_id de SICAR (ADR 0008)."
        )
    if columnas["estado"] not in ESTADOS_DEL_PEDIDO:
        raise ValueError(
            f"Estado {columnas['estado']!r} fuera de ck_pedido_estado, que "
            f"conoce {ESTADOS_DEL_PEDIDO} y ninguno más. Un sinónimo que se "
            f"cuele parte el pedido en dos vocabularios y las consultas "
            f"empiezan a mentir por omisión."
        )
    # Las dos del ticket 21. Se leen con `.get` y no con `[...]` por la misma
    # razón que las tres del 20: una fila leída de una base a la que todavía no
    # se le corrió la migración 0006 no las trae, y lo que tiene que pasar
    # entonces es "nadie lo ha enviado" y no un `KeyError` que tumbe la pantalla
    # entera por una columna que falta.
    if columnas.get("enviado_por") == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (enviado_por <> ''): o hay "
            "correo o es NULL, igual que en el descarte, el ajuste y la "
            "elección. Sin encabezado de Access, `web.app.quien()` devuelve "
            "'sin-identificar', que sí es un dato: ck_pedido_enviado_por."
        )
    # `enviado` Y `cancelado` llevan la firma del envío (ticket 25): solo se
    # cancela lo que alguien dijo haber enviado, y esa palabra no se borra.
    if (columnas["estado"] in (ENVIADO, CANCELADO)) != (
        columnas.get("enviado_por") is not None
        and columnas.get("enviado_en") is not None
    ):
        raise ValueError(
            "Enviado sin decir quién ni cuándo, o firma de envío en un pedido "
            "que nunca se envió. Lo rechaza ck_pedido_envio. 'Enviado' "
            "significa 'yo ya lo capturé en el portal del proveedor' (ADR "
            "0009): es la declaración de una persona sobre algo que Continental "
            "no vio, así que sin su firma no queda ningún hecho guardado — solo "
            "un 'se envió' en voz pasiva y nadie a quien preguntarle qué se "
            "capturó."
        )
    # Las dos del ticket 25, con `.get` por la misma razón que las del 21.
    if columnas.get("cancelado_por") == "":
        raise ValueError(
            "Firma vacía. La columna tiene CHECK (cancelado_por <> ''): o hay "
            "correo o es NULL: ck_pedido_cancelado_por."
        )
    if (columnas["estado"] == CANCELADO) != (
        columnas.get("cancelado_por") is not None
        and columnas.get("cancelado_en") is not None
    ):
        raise ValueError(
            "Cancelado sin decir quién ni cuándo, o firma de cancelación en un "
            "pedido que no está cancelado. Lo rechaza ck_pedido_cancelacion. "
            "'Cancelado' es la palabra de una persona de que el pedido no está "
            "en el portal del proveedor (ADR 0013): sin su firma no hay a quién "
            "preguntarle cuando la mercancía llegue de todos modos."
        )
    if columnas["proveedor_id"] is not None and columnas["proveedor_id"] <= 0:
        raise ValueError(
            "proveedor_id de cero o negativo: lo rechaza ck_pedido_proveedor_id. "
            "NULL es 'SICAR no conoce a este proveedor' y se puede pedir igual; "
            "un cero es un id inventado que hace que todo join contra "
            "dim_proveedor salga vacío sin error."
        )
    if columnas["total_sin_iva"] is not None and columnas["total_sin_iva"] < 0:
        raise ValueError("total_sin_iva negativo: lo rechaza ck_pedido_total.")


def pedido_desde_columnas(fila) -> PedidoGuardado:
    """Una fila de `pedidos.pedido` → el pedido guardado.

    El total llega como `Decimal` desde Postgres y **así se queda**: convertirlo
    a `float` en el borde sería meter dinero en coma flotante justo donde
    `numeric(12,2)` acaba de sacarlo. Es lo contrario de lo que hace
    `renglon_desde_columnas` con las piezas, y la diferencia es que esto es
    dinero.

    Las dos del envío se leen con `.get` —una `RowMapping` de SQLAlchemy lo
    soporta igual que un diccionario— para que una base sin la migración 0006
    se vea como "nadie lo ha enviado" en vez de tumbar la pantalla entera.
    """
    return PedidoGuardado(
        pedido_id=int(fila["pedido_id"]),
        negocio=fila["negocio"],
        pedido_sugerido_id=int(fila["pedido_sugerido_id"]),
        proveedor=fila["proveedor"],
        proveedor_id=(
            None if fila["proveedor_id"] is None else int(fila["proveedor_id"])
        ),
        estado=fila["estado"],
        armado_en=fila["armado_en"],
        total_sin_iva=(
            None
            if fila["total_sin_iva"] is None
            else Decimal(str(fila["total_sin_iva"]))
        ),
        enviado_por=fila.get("enviado_por"),
        enviado_en=fila.get("enviado_en"),
        # Las dos del ticket 25, con `.get` por lo mismo: sin la migración 0009
        # es "nadie lo canceló".
        cancelado_por=fila.get("cancelado_por"),
        cancelado_en=fila.get("cancelado_en"),
    )


# ------------------------------------ el precio congelado (ticket 12)
#
# Todo lo de aquí abajo vive en `pedidos.precio_de_proveedor`, la cuarta tabla.
# Las mismas dos mitades que el renglón: `columnas_del_precio` arma las
# columnas y `revisar_el_precio` es el CHECK del DDL escrito en Python, y las
# llaman las DOS implementaciones.


@dataclass(frozen=True, slots=True)
class PrecioDeProveedor:
    """Lo que un proveedor dijo de un renglón, **con el instante de la lectura**.

    Es una `precios.LecturaDePrecio` que ya tiene fila: lo mismo más
    `consultado_en`, que es el dato que vuelve congelada a una cifra. Sin él,
    "$86.05 en NADRO" no dice si se leyó hace una hora o hace tres semanas, y la
    tercera casilla del ticket 12 es exactamente eso: *un pedido dice a qué
    precio se decidió, no a cómo está hoy*.

    `precio` es `Decimal` y no `float`, de punta a punta. La conversión desde el
    texto del portal ocurre una sola vez, en `precios.precio_a_numero`, y el
    número no vuelve a pasar por coma flotante ni siquiera para pintarlo: el
    JSON lo manda como cadena. En `float`, `0.1 + 0.2` no es `0.3` y el total de
    un pedido deja de cuadrar contra la factura por centavos que nadie puede
    explicar.

    **`precio is None` siempre viene con `motivo`.** Es lo que hace que un hueco
    sea información y no un `NULL` mudo, y lo garantizan tres cosas a la vez:
    `precios.leer_el_precio` no tiene un camino que produzca uno sin el otro,
    `revisar_el_precio` lo rechaza, y `ck_precio_sin_dato` lo rechaza en la
    tabla.
    """

    renglon_id: int
    proveedor: str
    consultado_en: dt.datetime
    precio_como_llego: str = ""
    precio: Decimal | None = None
    existencia_como_llego: str = ""
    existencia: Decimal | None = None
    motivo: str | None = None
    detalle: str = ""
    clave_del_proveedor: str = ""
    descripcion_del_proveedor: str = ""
    resultados: int = 0

    @property
    def sin_dato(self) -> bool:
        """Si este proveedor no dejó precio. **Jamás se deduce de un cero.**"""
        return self.precio is None


def _vacio_a_nulo(texto: str | None) -> str | None:
    """`""` → `NULL`, igual que la clave del renglón y por lo mismo.

    Una cadena vacía es un tercer valor que se compara igual que un dato y
    empareja con cualquier otra vacía. O hay texto o no se sabe. Cada columna de
    texto de esta tabla lleva su `CHECK (... <> '')` del otro lado.
    """
    return texto or None


def columnas_del_precio(
    lectura: LecturaDePrecio, negocio: str, renglon_id: int
) -> dict:
    """Las columnas de `pedidos.precio_de_proveedor` para una lectura.

    **`consultado_en` no está aquí, y es a propósito.** Lo pone la base con
    `now()`, por la misma razón que `descartado_en` y `cerrado_en`: la hora la
    escribe el servidor que guarda la fila, así que dos procesos con relojes
    distintos no dejan lecturas incomparables. Y trae de regalo justo lo que
    hace falta: `now()` es la hora de la **transacción**, así que los cuatro
    proveedores de una misma consulta quedan con el mismo instante —que es la
    verdad: fue una sola lectura— y dos consultas distintas nunca lo comparten.

    Los `numeric` **no se redondean aquí** y eso es distinto del renglón:
    `precios.precio_a_numero` ya devuelve el `Decimal` cuantizado a la escala de
    la columna, porque ahí es donde se sabe qué escala tiene cada cosa —dos
    decimales el precio, tres la existencia—. Redondear dos veces sería la misma
    regla escrita en dos lugares.
    """
    return {
        "negocio": negocio,
        "renglon_id": renglon_id,
        "proveedor": lectura.proveedor,
        "precio_como_llego": _vacio_a_nulo(lectura.precio_como_llego),
        "precio": lectura.precio,
        "existencia_como_llego": _vacio_a_nulo(lectura.existencia_como_llego),
        "existencia": lectura.existencia,
        "motivo": lectura.motivo,
        "detalle": _vacio_a_nulo(lectura.detalle),
        "clave_del_proveedor": _vacio_a_nulo(lectura.clave_del_proveedor),
        "descripcion_del_proveedor": _vacio_a_nulo(lectura.descripcion_del_proveedor),
        "resultados": lectura.resultados,
    }


def revisar_el_precio(columnas: dict) -> None:
    """Los CHECK de `pedidos.precio_de_proveedor`, escritos en Python.

    Postgres los aplica por su cuenta y no necesita esto; el doble sí. Cada
    `raise` nombra la restricción que estaría violando.
    """
    if not columnas["negocio"]:
        raise ValueError("negocio vacío: lo rechaza ck_precio_negocio.")
    if not columnas["proveedor"]:
        raise ValueError(
            "proveedor vacío: lo rechaza ck_precio_proveedor. Sin saber quién "
            "dio el precio, el precio no sirve para nada."
        )
    for columna in (
        "precio_como_llego",
        "existencia_como_llego",
        "detalle",
        "clave_del_proveedor",
        "descripcion_del_proveedor",
    ):
        if columnas[columna] == "":
            raise ValueError(
                f"{columna} en cadena vacía. La columna tiene CHECK "
                f"({columna} <> ''): o hay texto o es NULL. Ver "
                "columnas_del_precio."
            )
    if columnas["precio"] is not None and columnas["precio"] <= 0:
        raise ValueError(
            f"Precio de {columnas['precio']}: lo rechaza ck_precio_positivo. "
            "**Un cero no es un precio**: gana toda comparación de 'el más "
            "barato' y dispara la compra equivocada. Un precio que no se pudo "
            "leer es NULL con su motivo (regla 4 de CLAUDE.md)."
        )
    if columnas["existencia"] is not None and columnas["existencia"] < 0:
        raise ValueError(
            "Existencia negativa reportada por un proveedor: lo rechaza "
            "ck_precio_existencia. Un proveedor no tiene menos que cero; la "
            "existencia negativa de SICAR es otra cosa y vive en el renglón."
        )
    if columnas["resultados"] < 0:
        raise ValueError("resultados negativo: lo rechaza ck_precio_resultados.")
    if columnas["motivo"] is not None and columnas["motivo"] not in MOTIVOS:
        raise ValueError(
            f"Motivo {columnas['motivo']!r} fuera del vocabulario. Lo rechaza "
            f"ck_precio_motivo_conocido, que solo conoce {MOTIVOS}. El ticket "
            "15 cuenta los huecos por motivo, y un conteo sobre texto libre "
            "cuenta faltas de ortografía."
        )
    if (columnas["precio"] is None) != (columnas["motivo"] is not None):
        raise ValueError(
            "Un precio faltante sin motivo, o un motivo en una lectura que sí "
            "trajo precio. Lo rechaza ck_precio_sin_dato. **Un precio que no "
            "está no es un NULL mudo**: 'la sesión caducó' lo arregla el "
            "encargado en dos clics y 'no está en ese catálogo' no lo arregla "
            "nadie, y sin el motivo los dos se ven igual (historia 23)."
        )
    if columnas["precio"] is not None and not columnas["precio_como_llego"]:
        raise ValueError(
            "Precio guardado sin el texto del que salió. Lo rechaza "
            "ck_precio_con_su_texto: el texto original es lo único que permite "
            "auditar una conversión dudosa meses después."
        )


def precio_desde_columnas(fila) -> PrecioDeProveedor:
    """Una fila leída → el dato congelado. Lo usan las dos implementaciones.

    `NULL` vuelve a ser `""` en las columnas de texto, que es como el resto del
    código y la pantalla dicen "no se sabe". Los `numeric` llegan como `Decimal`
    desde Postgres y **se quedan como `Decimal`**: es la única columna de dinero
    que Continental lee, y convertirla a `float` en el borde —como hace
    `almacen.py` con las piezas— sería volver a meter el dinero en coma
    flotante justo después de haberlo sacado.
    """
    return PrecioDeProveedor(
        renglon_id=int(fila["renglon_id"]),
        proveedor=fila["proveedor"],
        consultado_en=fila["consultado_en"],
        precio_como_llego=fila["precio_como_llego"] or "",
        precio=None if fila["precio"] is None else Decimal(fila["precio"]),
        existencia_como_llego=fila["existencia_como_llego"] or "",
        existencia=(
            None if fila["existencia"] is None else Decimal(fila["existencia"])
        ),
        motivo=fila["motivo"],
        detalle=fila["detalle"] or "",
        clave_del_proveedor=fila["clave_del_proveedor"] or "",
        descripcion_del_proveedor=fila["descripcion_del_proveedor"] or "",
        resultados=int(fila["resultados"]),
    )


def ultimo_por_proveedor(
    filas: Sequence[PrecioDeProveedor],
) -> tuple[PrecioDeProveedor, ...]:
    """De todas las lecturas de un renglón, **la más reciente de cada proveedor**.

    Es el `DISTINCT ON` de `_LEER_PRECIOS` escrito en Python, para que el doble
    conteste lo mismo que Postgres. Vive aquí y no dentro del doble por la misma
    razón que los validadores: si las dos implementaciones eligieran con reglas
    distintas, el suite quedaría en verde y la pantalla mostraría otro precio en
    atlas.

    El desempate es el **orden de escritura** cuando dos lecturas comparten
    instante, igual que el `precio_de_proveedor_id desc` del SQL. Puede pasar:
    `now()` es la hora de la transacción, así que dos consultas que se
    solapen en el mismo microsegundo lo comparten.
    """
    ultimas: dict[str, PrecioDeProveedor] = {}
    for fila in filas:
        previa = ultimas.get(fila.proveedor)
        if previa is None or fila.consultado_en >= previa.consultado_en:
            ultimas[fila.proveedor] = fila
    return tuple(ultimas[clave] for clave in sorted(ultimas))


# ---------------------------------------------- la corrida del lote (19)


@dataclass(frozen=True, slots=True)
class CorridaDelLote:
    """Cómo le fue al lote nocturno una noche. **Una fila por corrida.**

    Es el resumen del ticket 18 —`lote.ResumenDeLaCorrida`— guardado, y el ADR
    0007 explica por qué se guarda y por qué con este grano. En una frase:
    la pregunta que la pantalla no podía contestar era *"¿corrió el lote sobre
    esta lista y cómo acabó?"*, y esa pregunta tiene **una** respuesta por
    noche. Guardarla cuesta una fila; deducir de ahí el estado de un renglón es
    una resta que se hace al leer.

    **No es la bitácora.** La bitácora sigue siendo el journal
    (`journalctl -u continental-lote`), que tiene el relato renglón por renglón
    y que —esto es lo que la tabla no puede— **deja rastro aunque Postgres sea
    justo lo que se cayó**. Esto es el dato que la pantalla consulta.

    `pedido_sugerido_id` y `fecha_del_pedido` son nulos en una corrida que no
    llegó a abrir lista (`no hubo lista`, o una que se cortó antes). Nulo
    porque no hubo, no porque no se sepa.

    **`termino_en` es `None` mientras la corrida no se haya guardado**, y por
    eso va con default y después de `final`. La hora la pone la BASE con
    `now()` —igual que `consultado_en` del precio, y por lo mismo: la pone el
    servidor que guarda la fila, así que dos procesos con relojes distintos no
    dejan corridas incomparables—. El lote arma este objeto para escribirlo y
    ahí todavía no hay hora que poner: inventarle una del reloj local sería
    escribir un instante que no es el que la fila va a llevar. `None` quiere
    decir *"esto es lo que se va a guardar"*; con fecha, *"esto es lo que se
    leyó"*.

    Los conteos son los del resumen y **no se recalculan aquí**: se escriben
    tal como el lote los contó, que es lo mismo que imprimió en el journal. Dos
    versiones de la misma noche es justo lo que el ADR 0006 no quería.
    """

    corrida_del_lote_id: int
    negocio: str
    pedido_sugerido_id: int | None
    fecha_del_pedido: dt.date | None
    final: str
    termino_en: dt.datetime | None = None
    segundos: float = 0.0
    tope_minutos: float = 0.0
    en_la_lista: int = 0
    consultados: int = 0
    con_precio: int = 0
    sin_alcanzar: int = 0
    no_se_pudo: int = 0
    sin_clave: int = 0
    orden_cumplido: bool = False
    detalle: str = ""

    @property
    def sin_precio(self) -> int:
        """Renglones que acabaron sin un solo precio. **Derivado**, no guardado.

        Dos columnas que tienen que sumar lo mismo dejan de sumarlo el día que
        alguien escriba una y no la otra. Es el mismo criterio que
        `ConteoDeLaLista.sin_comparar`.
        """
        return self.en_la_lista - self.con_precio

    @property
    def se_corto_por_tiempo(self) -> bool:
        """Si se acabó el tope con renglones sin consultar. **No es un error.**"""
        return self.final == SE_ACABO_EL_TIEMPO

    @property
    def se_interrumpio(self) -> bool:
        return self.final == SE_INTERRUMPIO

    @property
    def llego_al_final(self) -> bool:
        """Si recorrió la lista entera. Distinto de "le fue bien"."""
        return self.final == TERMINO

    @property
    def hubo_fallas(self) -> bool:
        """Si algún renglón se intentó y no dejó ni una fila guardada.

        Es lo que vuelve **insegura** la atribución por renglón (ADR 0007): con
        fallas y tope a la vez, de un renglón sin lectura no se puede afirmar
        cuál de los dos le tocó.
        """
        return self.no_se_pudo > 0


def columnas_de_la_corrida(corrida: CorridaDelLote, negocio: str) -> dict:
    """Las columnas de `pedidos.corrida_del_lote` para un resumen.

    `termino_en` **no está aquí**, por la misma razón que `consultado_en` del
    precio: la pone la base con `now()`, que es la hora del servidor que guarda
    la fila. Dos procesos con relojes distintos no dejan corridas
    incomparables.

    `segundos` y `tope_minutos` sí vienen de aquí y son del reloj **monótono**
    del lote: no son instantes, son duraciones, y una duración no la puede
    medir el que la guarda.
    """
    return {
        "negocio": negocio,
        "pedido_sugerido_id": corrida.pedido_sugerido_id,
        "fecha_del_pedido": corrida.fecha_del_pedido,
        "final": corrida.final,
        "segundos": round(float(corrida.segundos), 1),
        "tope_minutos": round(float(corrida.tope_minutos), 1),
        "en_la_lista": int(corrida.en_la_lista),
        "consultados": int(corrida.consultados),
        "con_precio": int(corrida.con_precio),
        "sin_alcanzar": int(corrida.sin_alcanzar),
        "no_se_pudo": int(corrida.no_se_pudo),
        "sin_clave": int(corrida.sin_clave),
        "orden_cumplido": bool(corrida.orden_cumplido),
        "detalle": _vacio_a_nulo(corrida.detalle),
    }


def revisar_la_corrida(columnas: dict) -> None:
    """Los CHECK de `pedidos.corrida_del_lote`, escritos en Python.

    Postgres los aplica por su cuenta y no necesita esto; el doble sí. Cada
    `raise` nombra la restricción que estaría violando — un doble permisivo
    deja el suite en verde y rompe en atlas.
    """
    if not columnas["negocio"]:
        raise ValueError("negocio vacío: lo rechaza ck_corrida_negocio.")
    if columnas["final"] not in FINALES_DE_LA_CORRIDA:
        raise ValueError(
            f"Final {columnas['final']!r} fuera del vocabulario. Lo rechaza "
            f"ck_corrida_final, que solo conoce {FINALES_DE_LA_CORRIDA}. La "
            "pantalla decide con este valor qué frase le pone a un renglón sin "
            "lectura: un quinto valor sin migración se leería como 'el lote no "
            "corrió'."
        )
    if columnas["detalle"] == "":
        raise ValueError(
            "detalle en cadena vacía. La columna tiene CHECK (detalle <> ''): "
            "o hay texto o es NULL. Ver columnas_de_la_corrida."
        )
    for columna in (
        "en_la_lista",
        "consultados",
        "con_precio",
        "sin_alcanzar",
        "no_se_pudo",
        "sin_clave",
    ):
        if columnas[columna] < 0:
            raise ValueError(
                f"{columna} negativo: lo rechaza ck_corrida_conteos. Un conteo "
                "negativo no es 'menos que ninguno', es un error de quien contó."
            )
    if columnas["segundos"] < 0 or columnas["tope_minutos"] < 0:
        raise ValueError("Duración negativa: la rechaza ck_corrida_duracion.")
    if columnas["consultados"] > columnas["en_la_lista"]:
        raise ValueError(
            "Se consultaron más renglones de los que había en la lista: lo "
            "rechaza ck_corrida_consultados. Es el conteo que la pantalla usa "
            "para decir '210 de 380', y un numerador mayor que el denominador "
            "se lee como una pantalla rota."
        )
    if columnas["con_precio"] > columnas["consultados"]:
        raise ValueError(
            "Más renglones con precio que consultados: lo rechaza "
            "ck_corrida_con_precio. Un precio no llega de un renglón que no se "
            "consultó."
        )
    if (columnas["pedido_sugerido_id"] is None) != (
        columnas["fecha_del_pedido"] is None
    ):
        raise ValueError(
            "La lista y su fecha van juntas o no van: lo rechaza "
            "ck_corrida_lista. Una corrida con fecha y sin lista —o al revés— "
            "no se puede leer: la pantalla busca por id y escribiría la fecha "
            "de otra noche."
        )


def corrida_desde_columnas(fila) -> CorridaDelLote:
    """Una fila leída → el resumen guardado. Lo usan las dos implementaciones.

    `NULL` vuelve a ser `""` en `detalle`, como en el resto del módulo. Los
    `numeric` de duración sí salen como `float`: no son dinero, son segundos
    que se pintan con un decimal, y `Decimal` ahí solo complicaría la división
    entre sesenta.
    """
    return CorridaDelLote(
        corrida_del_lote_id=int(fila["corrida_del_lote_id"]),
        negocio=fila["negocio"],
        pedido_sugerido_id=(
            None
            if fila["pedido_sugerido_id"] is None
            else int(fila["pedido_sugerido_id"])
        ),
        fecha_del_pedido=fila["fecha_del_pedido"],
        termino_en=fila["termino_en"],
        final=fila["final"],
        segundos=float(fila["segundos"]),
        tope_minutos=float(fila["tope_minutos"]),
        en_la_lista=int(fila["en_la_lista"]),
        consultados=int(fila["consultados"]),
        con_precio=int(fila["con_precio"]),
        sin_alcanzar=int(fila["sin_alcanzar"]),
        no_se_pudo=int(fila["no_se_pudo"]),
        sin_clave=int(fila["sin_clave"]),
        orden_cumplido=bool(fila["orden_cumplido"]),
        detalle=fila["detalle"] or "",
    )


# --------------------------------------------------------------- interfaz


@runtime_checkable
class AlmacenamientoDelPedido(Protocol):
    """El borde de escritura. Ocho operaciones y ninguna de ellas borra.

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

    def leer_por_id(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        """La misma lista, buscada **por su id**. `None` si no hay.

        La hermana de `leer`, y no una duplicada: quien tiene una lista en la
        pantalla tiene su id, no su fecha, y volver a anclar la fecha para
        releerla sería resolver dos veces el mismo `max(fecha)` —con la
        posibilidad de que la segunda vez dé otra cosa, que es exactamente lo
        que este repo evita anclando en el dato—.

        La estrena el botón de completar del ticket 19, que recibe el id y
        necesita los renglones de esa lista para saber cuáles faltan. Era la
        **condición de disparo escrita en el hilo abierto 2 de `HANDOVER.md`**:
        *"cuando entre un `leer_por_id` al almacenamiento por otra razón, esto
        se cierra en una línea"* — el "esto" es el conteo de huecos que
        envejece al consultar un precio.
        """
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

        Su espejo es `piso_sin_pedir`, que dice desde dónde hay días propuestos
        que nadie pidió. Los dos juntos son la ventana; ninguno basta solo.
        """
        ...

    def piso_sin_pedir(self, negocio: str, antes_de: dt.date) -> dt.date | None:
        """Desde qué día hay ventas **propuestas y nunca pedidas**.

        El principio de la lista más vieja que se quedó `abierta` o `vencida`.
        `None` es "no quedó nada pendiente", que es el caso ordinario cuando el
        encargado cierra su lista todos los días.

        **Existe desde que la ventana se acortó a un día hábil (2026-09-20).**
        Antes la primera ventana era de siete días y recogía por accidente lo
        que nadie había cerrado; con un día, sin este piso, las ventas de un
        día desatendido se caen al piso sin un solo error que ver.

        `antes_de` acota igual que en `corte_del_ultimo_cerrado`, y sale del
        dato (`max(fecha)`), nunca del reloj.
        """
        ...

    def lo_ya_pedido(
        self, negocio: str, antes_de: dt.date
    ) -> tuple[LoYaPedido, ...]:
        """Lo que ya se le pidió a un proveedor y todavía le importa a la lista (24).

        **Solo lectura.** Dos clases de renglón, de listas anteriores a
        `antes_de`:

        - **todo lo `en tránsito`** — no se vuelve a proponer y se enseña;
        - **lo recibido que ninguna lista posterior ha atendido** — lo que se
          vendió mientras venía en camino todavía no se propuso, y la siguiente
          lista lo tiene que traer (ADR 0012).

        Es el tercer dato con el que se abre el día, junto al corte y al piso,
        y es de la misma familia: los tres dicen **qué ventas ya se atendieron**
        y los tres salen de `pedidos`, nunca del reloj. La diferencia es de
        grano: el corte y el piso son de la lista entera; esto es por producto.

        En el orden de las listas y, dentro de cada una, de los renglones.
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

    def ajustar_la_cantidad(
        self, negocio: str, renglon_id: int, cantidad: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """Guarda la cantidad que una persona decidió pedir, firmada (ticket 11).

        **No toca `cantidad_propuesta`.** Escribe `cantidad_final` al lado, y
        esa separación es el ticket entero: la diferencia entre las dos es lo
        único que después dice si la reposición 1 a 1 está bien calibrada. Una
        sola columna que se sobreescriba se ve igual en la pantalla y borra el
        dato sin un solo error que ver.

        `None` es "no había ningún renglón al que se le pudiera cambiar la
        cantidad", y quien llame lo dice en vez de fingir. Son **dos**
        condiciones y las dos viven en el `WHERE`:

        - el renglón sigue `abierto` — uno `en tránsito` ya se le pidió a un
          proveedor con una cifra, y cambiarla aquí haría que el renglón dijera
          una cosa y el proveedor otra;
        - **y su lista sigue `abierta`**, que es lo que el ticket pide con todas
          sus letras. Una lista `cerrada` quiere decir "ya se pidió lo que se
          iba a pedir" (`CONTEXT.md`).

        Comprobar el estado de la lista en Python y actualizar después tiene una
        carrera en medio: una pestaña cierra mientras otra corrige, y la
        corrección entra en una lista que ya se pidió.

        `cantidad` tiene que ser de al menos `CANTIDAD_FINAL_MINIMA`: un cero no
        es una forma de descartar. Quien llame con un cero recibe un `ValueError`
        de `revisar_el_renglon` contra el doble y una violación de
        `ck_renglon_cantidad_final` contra Postgres — las dos son la misma regla
        y la ruta la atrapa antes, para poder explicarla.

        Devuelve la **lista entera** por la misma razón que `descartar`: los
        conteos que la pantalla pinta salen de lo guardado y no de una cuenta
        que el navegador lleve a mano.
        """
        ...

    def leer_renglon(self, negocio: str, renglon_id: int) -> RenglonGuardado | None:
        """Un renglón suelto, con sus números congelados. `None` si no hay.

        Existe desde el ticket 12 y para una sola cosa: antes de pedirle un
        precio a Doyle hay que saber **con qué clave buscar** y si el renglón
        sigue `abierto`. Leer la lista entera para mirar un renglón costaría
        traerse los cientos de filas del día por cada clic de un botón.

        Es lectura y no decide nada: la garantía de que el precio no se le
        pegue a un renglón de otro negocio vive en el `WHERE` de
        `guardar_precios`, no en lo que esta función devuelva.
        """
        ...

    def guardar_precios(
        self, negocio: str, renglon_id: int, lecturas: Sequence[LecturaDePrecio]
    ) -> int:
        """Congela lo que contestaron los proveedores. Cuántas filas escribió.

        **Agrega, nunca pisa**, y ésa es la cuarta decisión del ticket 12.
        Congelado quiere decir congelado: una segunda consulta del mismo renglón
        deja una lectura nueva al lado de la anterior y la comparación usa la
        más reciente (`ultimo_por_proveedor`). Las tres razones, en orden de
        cuánto duelen:

        1. **Un `UPDATE` haría que una consulta fallida borrara un precio
           bueno.** Es el caso ordinario, no el raro: se consulta a las 8, NADRO
           da $86.05; a las 9 alguien vuelve a consultar, la sesión ya caducó, y
           con un `UPDATE` el $86.05 se convierte en un hueco. Se habría perdido
           el dato **por intentar mejorarlo**.
        2. **El precio al que se decidió comprar tiene que seguir ahí.** Es
           literal la tercera casilla del ticket: *un pedido dice a qué precio se
           decidió, no a cómo está hoy*. Con una sola fila por proveedor, la
           cifra que el encargado vio cuando eligió NADRO desaparece en cuanto
           alguien recarga los precios.
        3. **El rol no tiene `DELETE`** (ADR 0003) y toda la zona de datos de la
           casa es append-only por convención. Una tabla que solo crece se
           audita; una que se sobreescribe no.

        Lo que cuesta, dicho: la tabla crece con cada consulta y nadie la poda.
        Son cuatro filas por renglón consultado —del orden de cientos al día en
        el peor caso— contra una base que hoy guarda 460 mil filas en total.
        Cuando estorbe, se archiva con el pedido sugerido que la originó, que
        es la unidad con la que se puede tirar sin perder el porqué.

        **El renglón y su negocio viven en el `WHERE`**, no en un `if`: se
        escribe contra el renglón que existe en ese negocio y no contra el que
        Python creyó haber leído un momento antes. Cero filas es "no había
        renglón al que guardarle precio", y quien llame lo dice.

        Lo que ese `WHERE` **no** lleva, a propósito, es el estado del renglón.
        Los estados van en el `WHERE` cuando lo que se escribe es una
        transición —descartar, cerrar, corregir la cantidad—, y esto no lo es:
        es un **hecho del mundo en un instante**. Si alguien descarta el renglón
        mientras Doyle todavía consulta, tirar la lectura no protege nada —nadie
        va a comprar un renglón descartado— y sí pierde la evidencia, que
        además vuelve a hacer falta en cuanto alguien lo devuelva a `abierto`.
        Quien decide si vale la pena molestar a los portales es la ruta, que
        mira el estado **antes** de pedir la búsqueda y puede explicarlo.
        """
        ...

    def precios_del_renglon(
        self, negocio: str, renglon_id: int
    ) -> tuple[PrecioDeProveedor, ...]:
        """La lectura más reciente de **cada** proveedor para ese renglón.

        Una por proveedor que alguna vez contestó, ordenadas por clave. Un
        renglón que nunca se consultó devuelve la tupla vacía, y eso es un dato:
        el ticket 15 cuenta exactamente los que quedaron *sin comparar*.
        """
        ...

    def precios_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> dict[int, tuple[PrecioDeProveedor, ...]]:
        """Lo mismo para la lista entera, en **una sola consulta**.

        Es lo que la pantalla necesita al cargar: sin esto haría una llamada por
        renglón y una lista trae tantos renglones como productos distintos se
        vendieron. Y hay algo peor que el costo — con una llamada por renglón,
        cada una leería en un momento distinto y la tabla podría dejar de
        coincidir consigo misma mientras alguien la trabaja. Es la misma razón
        por la que las dos vistas del ticket 06 salen de una sola lectura.

        Un renglón sin ninguna consulta **no aparece** en el diccionario, en vez
        de aparecer con una tupla vacía: "no está" y "está vacío" quieren decir
        lo mismo aquí y tener dos maneras de decirlo invita a que alguien
        compruebe solo una.
        """
        ...

    def elegir_proveedor(
        self, negocio: str, renglon_id: int, proveedor: str, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """Guarda a quién decidió una persona pedirle este renglón, firmado (20).

        **Solo se guarda la decisión.** Lo que el sistema sugiere —el más barato
        con existencia— no se escribe en ninguna columna: se recalcula de
        `comparacion.elegir_ganador` sobre los precios congelados, que solo
        crecen. Guardarlo sería una segunda copia del mismo hecho, y una que
        además envejece sin avisar: si a las 8 la sugerencia era NADRO y a las 9
        llega un LEVIC más barato, la columna seguiría diciendo NADRO y nadie
        podría distinguir esa cifra vieja de una decisión que alguien tomó.

        Se aparta a propósito del ticket 11, que sí guarda las dos cifras
        (`cantidad_propuesta` y `cantidad_final`): aquella propuesta **no se
        puede recalcular**, porque sale de las ventas de una ventana que ya
        pasó. El porqué entero está en el encabezado de `particion.py`.

        `None` es "no había ningún renglón al que se le pudiera elegir
        proveedor", y quien llame lo dice en vez de fingir. Son **dos**
        condiciones y las dos viven en el `WHERE`, las mismas de
        `ajustar_la_cantidad`:

        - el renglón sigue `abierto` — uno `en tránsito` ya se le pidió a un
          proveedor, y cambiarle el destinatario aquí haría que el renglón
          dijera una cosa y el proveedor otra;
        - **y su lista sigue `abierta`** — una lista `cerrada` quiere decir "ya
          se pidió lo que se iba a pedir" (`CONTEXT.md`).

        **La elección NO se revisa contra la comparación**, y eso es el ticket:
        se puede elegir a un proveedor que no dio precio, o al que nadie le
        preguntó. Hay razones que el sistema no ve —mínimo de pedido, días de
        entrega, crédito—. El renglón entra al pedido con `precio desconocido`,
        que es la quinta casilla.

        `quien` es una **firma, no un permiso** (regla 3 de `CLAUDE.md`): sirve
        para saber a quién preguntarle por qué se le compró a LEVIC habiendo
        NADRO más barato.

        Devuelve la **lista entera**, por la misma razón que `descartar` y
        `ajustar_la_cantidad`: los conteos que la pantalla pinta salen de lo
        guardado y no de una cuenta que el navegador lleve a mano.
        """
        ...

    def pedidos_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> tuple[PedidoGuardado, ...]:
        """Los pedidos en que ya se partió esa lista. Vacío si no se ha partido.

        Ordenados por proveedor y no por id: el orden de creación depende de en
        qué orden alguien apretó el botón, y dos cargas de la misma pantalla no
        deben enseñar las columnas cambiadas de sitio. Es el mismo criterio que
        `comparacion.ORDEN_DE_LA_FILA`.
        """
        ...

    def guardar_la_particion(
        self,
        negocio: str,
        pedido_sugerido_id: int,
        pedidos: Sequence[PedidoPorArmar],
    ) -> tuple[PedidoGuardado, ...] | None:
        """Parte la lista: un pedido por proveedor, con sus renglones dentro.

        Recibe la partición **ya calculada** (`particion.partir`) y solo la
        escribe. La regla de a quién se le pide cada renglón y cuánto suma cada
        pedido vive en un módulo puro, probado sin Postgres, por la misma razón
        que `comparacion.py`: una regla dentro de un `SELECT` solo se puede
        probar levantando una base.

        `None` es "esa lista no existe en este negocio, o ya no está abierta", y
        quien llame lo dice. La condición vive en el `INSERT ... SELECT` contra
        `pedido_sugerido`, no en un `if` de Python: comprobar y escribir después
        tiene una carrera en medio.

        **Se puede partir dos veces, y no duplica nada.** El `ON CONFLICT ON
        CONSTRAINT ux_pedido_proveedor DO UPDATE` reencuentra el pedido que ya
        existía para ese proveedor —la restricción es de la tabla desde el
        ticket 07— y le reescribe el total. Si entre las dos particiones alguien
        cambió una elección, el renglón cambia de `pedido_id` (una columna, un
        solo pedido) y el pedido que se quedó vacío sigue ahí con total `NULL`:
        el rol no tiene `DELETE` y un pedido sin renglones no cuesta `0.00`,
        cuesta "no se sabe".

        **Lo que ya no es borrador no se toca**: el `WHERE` del `DO UPDATE` y el
        `EXISTS` de `_SOLTAR_RENGLONES` lo protegen. Desde el ticket 21 eso ya
        no es una garantía sobre un estado hipotético: volver a partir deja
        intacto lo `enviado` en vez de pisarlo, y hay una prueba que lo envía de
        verdad para comprobarlo.

        Todo en **una transacción**: una partición a medias dejaría renglones
        repartidos entre pedidos cuyos totales no cuentan.
        """
        ...

    def enviar_el_pedido(
        self, negocio: str, pedido_id: int, quien: str
    ) -> PedidoEnviado | None:
        """`borrador` → `enviado`, firmado, y sus renglones a `en tránsito` (21).

        **Lo que se guarda es la declaración de una persona**, no un hecho que
        Continental haya observado: *"yo ya lo capturé en el portal del
        proveedor"*. Continental no entra a los portales y no va a entrar (regla
        1 de `CLAUDE.md`; el ADR 0002 lo dejó fuera de alcance y el ADR 0009 lo
        razona entero). Por eso lleva **firma** —`quien`, el correo que verificó
        Access— y no acuse: no hay nadie de quien recibir uno.

        `quien` es una firma y **nunca un permiso** (regla 3): sirve para saber
        a quién preguntarle qué se capturó cuando la factura no cuadre.

        Son **dos sentencias en una transacción**, y ninguna de las dos sobra:
        el pedido cambia de estado y sus renglones pasan a `en tránsito`. Medio
        envío —el pedido marcado y los renglones en `abierto`— sería exactamente
        el modo de falla que este ticket viene a evitar: la lista de mañana
        volvería a proponer lo que ya se pidió hoy.

        `None` es "no había nada que enviar", y quien llame lo dice en vez de
        fingir. Son **tres** condiciones y las tres viven en el `WHERE`:

        - el pedido es de este negocio (regla 7);
        - **sigue en `borrador`** — uno `enviado` ya se capturó, y volver a
          firmarlo movería la hora de un hecho que ya pasó;
        - **tiene al menos un renglón dentro**. Un pedido que se quedó vacío al
          volver a partir sigue existiendo —el rol no tiene `DELETE`— con su
          total en `NULL`; marcarlo `enviado` diría "capturé esto en el portal"
          sobre nada, y ni siquiera habría qué pasar a `en tránsito`;
        - **y su total no envejeció**: ningún renglón de dentro se corrigió
          después de `armado_en`. `total_sin_iva` solo se reescribe al partir,
          así que una corrección posterior lo deja enseñando lo que costaba
          hace un rato — y ésa es la cifra contra la que alguien va a comparar
          la factura del proveedor. Se niega en vez de recalcular aquí, porque
          recalcular cambiaría el número **después** de que el encargado leyó el
          del botón. Es el hilo abierto 13 de `HANDOVER.md`.

        **Lo que NO se exige, y es una decisión (ADR 0009): que la lista siga
        `abierta`.** Todas las demás operaciones sí lo exigen, porque una lista
        `cerrada` quiere decir "ya se pidió lo que se iba a pedir" y cambiarla
        después separaría el renglón de lo que de verdad se pidió. Enviar es lo
        contrario: es decir que sí se pidió. Si lo exigiera, quien cierre la
        lista antes de marcar el último pedido se queda con renglones `abierto`
        dentro de una lista cerrada y sin manera de moverlos — mercancía pedida
        que el sugerido volvería a proponer y que la recepción (ticket 26) no
        podría cruzar.

        **Un pedido sin total SÍ se envía**, y eso no choca con lo de arriba: un
        `total_sin_iva` en `NULL` quiere decir que alguna línea va sin precio, y
        la quinta casilla del ticket 20 dice que esa línea se pide igual. El
        precio de verdad lo ve el encargado en el portal mientras lo captura.
        """
        ...

    def cancelar_el_pedido(
        self, negocio: str, pedido_id: int, quien: str
    ) -> PedidoCancelado | None:
        """`enviado` → `cancelado`, firmado, y sus renglones en tránsito también (25).

        **Lo que se guarda es la palabra de una persona**, igual que al enviar:
        *"este pedido no está en el portal del proveedor"* —nunca se capturó, o
        se canceló allá—. Continental no cancela nada en ningún portal (regla
        1, ADR 0013), así que lleva **firma** y no acuse. `quien` es una firma y
        nunca un permiso (regla 3).

        **No es "desenviar"** (ADR 0009, enmendado por el 0013 en este punto):
        el pedido no vuelve a `borrador`, no se edita y no se vuelve a enviar.
        Sus renglones pasan a `cancelado` —no a `abierto`—, y lo que vuelve es
        su **producto, en la siguiente lista**, con todo lo que cubrían.

        Son **dos sentencias en una transacción**, y `None` es "no había nada
        que cancelar". Las condiciones viven en el `WHERE`:

        - el pedido es de este negocio (regla 7);
        - **está `enviado`** — un borrador no se le ha pedido a nadie y se
          vuelve a partir; uno ya cancelado no mueve su firma con otro clic;
        - **ninguno de sus renglones se recibió** — si algo llegó, el pedido sí
          se capturó, y "nunca se capturó" sería falso.

        **Lo que NO exige, igual que enviar: que la lista siga `abierta`.**
        Cancelar no cambia lo que se iba a pedir: dice que no se pidió. Exigirlo
        dejaría atrapado para siempre lo que se envió desde una lista cerrada.
        """
        ...

    def devolver_el_atrasado(
        self,
        negocio: str,
        renglon_id: int,
        quien: str,
        enviado_antes_de: dt.datetime,
    ) -> RenglonGuardado | None:
        """Un renglón atrasado, **él solo**, de `en tránsito` a `cancelado` (25).

        La cuarta casilla del ticket: devolver a la lista uno por uno, sin
        cancelar el pedido entero. El pedido sigue `enviado` —lo demás de él
        puede estar llegando— y el renglón queda firmado con `quien`.

        `enviado_antes_de` es el límite que calcula
        `transito.enviado_antes_de(ahora, N)`: el renglón se devuelve **solo si
        su pedido se envió antes de ese instante**, que es exactamente "lleva
        más de N días en camino" contado en la hora de la farmacia. La
        condición vive en el `WHERE` —con el límite como parámetro— y no en un
        `if`: dos pestañas no se pisan, y la pantalla no puede devolver lo que
        todavía no se atrasó aunque alguien fabrique la petición.

        `None` es "no había nada que devolver": no es de este negocio, no está
        en tránsito, o todavía no se atrasa. Devuelve el renglón releído.
        """
        ...

    def marcar_capturado(
        self, negocio: str, renglon_id: int, capturado: bool, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """Tachar —o destachar— un renglón en la pantalla de captura (ticket 22).

        **Lo que se guarda es lo que una persona dice**: *ya tecleé este
        renglón en el portal del proveedor*. Por eso va firmado con `quien`, el
        correo que verificó Access, y es una firma y nunca un permiso (regla 3).

        **Vive en la tabla y no en el navegador**, y es la decisión del ticket
        (ADR 0010): con el avance en `localStorage`, dos pestañas del mismo
        pedido divergen en silencio, cambiar de máquina a la mitad lo pierde
        entero, y la marca que lleva a enviar —la quinta casilla— no diría
        quién la puso.

        `capturado=False` **destacha**: borra las dos columnas. Un clic de más
        en una lista de 40 es ordinario, y mientras el pedido siga en borrador
        nada depende todavía de la marca. No se guarda quién destachó: la
        columna afirma "está capturado" y lo contrario es su ausencia, no otra
        afirmación (ADR 0010).

        `None` es "no había nada que tachar", y son **cuatro** condiciones en el
        `WHERE`, las cuatro en las dos direcciones:

        - el renglón es de este negocio (regla 7);
        - **sigue `abierto`** — uno descartado no se va a pedir, y teclearlo en
          el portal sería comprar lo que alguien decidió no comprar;
        - **cuelga de un pedido** — sin pedido no hay proveedor de cuyo portal
          hablar;
        - **y ese pedido sigue en `borrador`** — uno `enviado` ya no se edita
          (ADR 0009), y sus marcas se quedan como quedaron: son la historia de
          cómo se capturó.

        **Lo que NO se exige es que la lista siga `abierta`**, igual que enviar
        y por la misma razón: tachar es decir "esto ya lo tecleé en el portal",
        que es lo contrario de modificar lo que se va a pedir. Si lo exigiera,
        quien cierra la lista antes de terminar de capturar se quedaría sin la
        cuenta —y sin el camino de la quinta casilla— a la mitad de 40
        renglones.

        **Tachar no cambia el estado del renglón**: sigue `abierto` hasta que se
        envíe su pedido. Ver `RenglonGuardado` y el ADR 0010, opción 4.
        """
        ...

    def guardar_la_corrida(self, negocio: str, corrida: CorridaDelLote) -> int:
        """Deja escrito cómo le fue al lote esta noche. Devuelve el id.

        **Solo inserta**, igual que el precio congelado y por la misma razón:
        una corrida es un hecho del pasado, y la de anoche no se corrige porque
        hoy haya otra. Cero significa "no se escribió" y quien llame lo dice.

        Quien la llama es `lote.correr_el_lote`, en el mismo `finally` donde
        imprime el resumen, y **envuelta en su propio `try`**: una corrida de
        sesenta minutos no se marca como rota porque esta fila no se pudo
        escribir (ADR 0007).
        """
        ...

    def ultima_corrida(
        self, negocio: str, pedido_sugerido_id: int
    ) -> CorridaDelLote | None:
        """La última corrida del lote **sobre esa lista**, o `None` si no hubo.

        `None` es un dato y es medio ticket 19: quiere decir *"el lote no corrió
        sobre esta lista"*, que es lo que distingue "nadie lo consultó" de "el
        lote no llegó" (hilo abierto 10 de `HANDOVER.md`). No es un hueco que
        haya que disimular.

        Por la lista y no por la fecha: dos listas del mismo día no pueden
        existir —`ux_pedido_sugerido_dia`— pero la pantalla ya tiene el id a la
        mano y buscar por él no depende de volver a anclar una fecha.
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
           descartado_por, descartado_en,
           cantidad_final, ajustada_por, ajustada_en,
           pedido_id, proveedor_elegido, elegido_por, elegido_en,
           capturado_por, capturado_en, ventas_desde,
           cancelado_por, cancelado_en
    from pedidos.renglon
    where negocio = :negocio and pedido_sugerido_id = :pedido_sugerido_id
    order by renglon_id
    """
)

# Un renglón suelto (ticket 12): con qué clave buscar y si sigue abierto. Las
# MISMAS columnas que `_LEER_RENGLONES` porque las dos desembocan en
# `armar_guardado`; pedir menos aquí obligaría a un segundo camino de lectura
# que se desincronizaría con el primero a la tercera columna nueva.
_LEER_RENGLON_POR_ID = text(
    """
    select renglon_id, pedido_sugerido_id, producto_id, clave, descripcion,
           piezas_vendidas, cantidad_propuesta, esta_en_el_catalogo, existencia,
           dias_de_cobertura, clasificacion, estado,
           descartado_por, descartado_en,
           cantidad_final, ajustada_por, ajustada_en,
           pedido_id, proveedor_elegido, elegido_por, elegido_en,
           capturado_por, capturado_en, ventas_desde,
           cancelado_por, cancelado_en
    from pedidos.renglon
    where negocio = :negocio and renglon_id = :renglon_id
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

# El día más viejo que se propuso y **nadie pidió**: el piso de la ventana.
#
# ES EL ESPEJO DE `_ULTIMO_CORTE` Y LLEGÓ EL 2026-09-20, con la ventana corta.
# Aquel dice hasta dónde llegó lo ya pedido; éste dice desde dónde hay ventas
# propuestas que nunca se convirtieron en un pedido, porque su lista se quedó
# `abierta` o se `venció`.
#
# **Por qué hizo falta, con su fecha:** hasta ese día la primera ventana era de
# siete días, ancha por accidente, y casi siempre volvía a recoger lo que nadie
# había cerrado. Al bajarla a un día hábil —decisión del dueño, para que la
# lista sea corta y legible— esa red desapareció: sin un solo cierre en la base
# no hay corte, la ventana se acota al último día, y **las ventas de un día que
# nadie atendió se caen al piso sin un error que ver**. Es la falla silenciosa
# de la regla 4 y por eso la ventana ahora tiene dos extremos, no uno.
#
# `min(ventas_consideradas_desde)` y no `max`: si hay varias sin cerrar, el
# piso es el principio de la más vieja. Cubrirlas a medias sería peor que no
# cubrirlas, porque el hueco quedaría escondido entre renglones que sí están.
#
# `estado <> 'cerrado'` en vez de nombrar `abierto` y `vencido`: el día que
# aparezca un cuarto estado, entra solo. La lista de estados prohibidos es la
# que se queda vieja.
_PISO_SIN_PEDIR = text(
    """
    select min(ventas_consideradas_desde) as piso
    from pedidos.pedido_sugerido
    where negocio = :negocio
      and estado <> 'cerrado'
      and fecha_del_pedido < :antes_de
    """
)

# LO YA PEDIDO (ticket 24, ADR 0012): la memoria con la que se arma la lista y
# lo que la pantalla enseña como "en camino".
#
# Dos clases de fila, y la diferencia entre las dos es la decisión del ticket:
#
#   - **Todo lo `en tránsito`, siempre.** No se vuelve a proponer mientras esté
#     así, y se ve en la pantalla. No lleva ninguna otra condición: esconder un
#     tránsito porque otra lista trae el mismo producto sería esconder lo que
#     la casilla 4 dice que no se esconde.
#   - **Lo `recibido` o `recibido parcial` que ninguna lista posterior ha
#     atendido todavía.** Sus ventas retenidas —las de después de su ancla—
#     siguen sin proponerse, así que hay que recordarlo. "Atendido" es que una
#     lista posterior **cerrada** trajo el producto (sus ventas ya se
#     propusieron), o que el producto se **volvió a pedir** (el ancla nueva
#     manda). En cuanto pasa, esta fila deja de salir: recordarla más
#     propondría esas ventas dos veces.
#
# Los dos estados de la recepción van escritos a mano y con acento, igual que
# `'en tránsito'`: son el enganche de los tickets 26 y 27 y hay una prueba que
# los compara contra `ESTADOS_QUE_CIERRAN_EL_TRANSITO`.
#
# `s.fecha_del_pedido < :antes_de` —la lista del día NO entra— y `:antes_de`
# sale del dato (`max(fecha)`), nunca del reloj. La lista del día se está
# armando justo con esto, y lo que ella misma envíe se ve en su propia tabla.
#
# `left join` al pedido y no `join`: un tránsito sin pedido no lo escribe
# ningún código, pero si existe se ENSEÑA diciendo que no tiene proveedor, en
# vez de desaparecer de la pantalla por culpa de un `join`.
#
# El negocio va en CADA unión, no solo en el `WHERE` de afuera (regla 7): un id
# de lista o de pedido de otra farmacia no puede colarse por un `join`.
#
# **Y DESDE EL TICKET 25, LO `cancelado`** (ADR 0013), en la misma clase que lo
# recibido y con el mismo "que nadie lo haya atendido": se dejó de esperar sin
# llegar, así que su producto vuelve. La diferencia es DESDE CUÁNDO —desde el
# principio de lo que cubría, y no desde el día siguiente al ancla— y por eso
# la sentencia trae ahora `s.ventas_consideradas_desde`: es ese principio
# cuando el renglón no tenía ventana propia. Va en su propia cláusula
# (`r.estado = 'cancelado'`) y no dentro de la tupla de la recepción: son dos
# reglas, y la tupla de allá es el enganche de los tickets 26 y 27.
#
# Una lista posterior que CANCELÓ el producto también lo atiende
# (`r2.estado = 'cancelado'`): ese renglón se armó con la memoria, así que ya
# carga con lo que el de antes dejaba pendiente, y se recuerda él. Recordar los
# dos serían dos intervalos del mismo producto.
#
# `p.estado as estado_del_pedido` distingue "se canceló el pedido entero" de
# "lo devolvieron a la lista a él solo", que la pantalla dice distinto.
_LO_YA_PEDIDO = text(
    """
    select r.renglon_id, r.pedido_sugerido_id, r.producto_id, r.clave,
           r.descripcion, r.piezas_vendidas, r.cantidad_propuesta,
           r.esta_en_el_catalogo, r.existencia, r.dias_de_cobertura,
           r.clasificacion, r.estado, r.descartado_por, r.descartado_en,
           r.cantidad_final, r.ajustada_por, r.ajustada_en,
           r.pedido_id, r.proveedor_elegido, r.elegido_por, r.elegido_en,
           r.capturado_por, r.capturado_en, r.ventas_desde,
           r.cancelado_por, r.cancelado_en,
           s.fecha_del_pedido, s.ventas_consideradas_hasta,
           s.ventas_consideradas_desde,
           p.proveedor, p.enviado_por, p.enviado_en,
           p.estado as estado_del_pedido
    from pedidos.renglon as r
    join pedidos.pedido_sugerido as s
      on s.pedido_sugerido_id = r.pedido_sugerido_id
     and s.negocio = r.negocio
    left join pedidos.pedido as p
      on p.pedido_id = r.pedido_id
     and p.negocio = r.negocio
    where r.negocio = :negocio
      and s.fecha_del_pedido < :antes_de
      and (r.estado = 'en tránsito'
           or ((r.estado in ('recibido', 'recibido parcial')
                or r.estado = 'cancelado')
               and not exists (
                   select 1
                   from pedidos.renglon as r2
                   join pedidos.pedido_sugerido as s2
                     on s2.pedido_sugerido_id = r2.pedido_sugerido_id
                    and s2.negocio = r2.negocio
                   where r2.negocio = r.negocio
                     and r2.producto_id = r.producto_id
                     and s2.fecha_del_pedido > s.fecha_del_pedido
                     and s2.fecha_del_pedido < :antes_de
                     and (s2.estado = 'cerrado'
                          or r2.estado in ('en tránsito', 'recibido', 'recibido parcial')
                          or r2.estado = 'cancelado'))))
    order by s.fecha_del_pedido, r.renglon_id
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
         dias_de_cobertura, clasificacion, estado, ventas_desde)
    values
        (:negocio, :pedido_sugerido_id, :producto_id, :clave, :descripcion,
         :piezas_vendidas, :cantidad_propuesta, :esta_en_el_catalogo,
         :existencia, :dias_de_cobertura, :clasificacion, :estado,
         :ventas_desde)
    """
)

# Descartar un renglón (ticket 10). Es un UPDATE y nunca un borrado: el rol no
# tiene DELETE y descartar es un cambio de estado del glosario.
#
# `and r.estado = 'abierto'` es la transición metida en el WHERE, igual que en
# `_CERRAR`. Solo se descarta lo abierto: `en tránsito` ya se le pidió a un
# proveedor, y `recibido` / `recibido parcial` son hechos consumados. Cero filas
# es "no había nada que descartar", y quien llama lo dice en vez de fingir.
#
# `and p.estado = 'abierto'` **es la segunda condición, y llegó el 2026-09-20.**
# Hasta ese día esta sentencia miraba solo el renglón, y por eso una lista
# cerrada se seguía dejando descartar mientras el ajuste (11) y la elección de
# proveedor (20) ya no lo permitían. El ticket 10 nunca pidió la condición, así
# que no era un incumplimiento: era una incoherencia, y `_ELEGIR_PROVEEDOR` la
# dejó anotada pidiendo que se arreglara a propósito. De cara al encargado, una
# lista cerrada que todavía se deja modificar es una lista que no está cerrada
# —`cerrado` significa "ya se pidió lo que se iba a pedir" (`CONTEXT.md`)—, y un
# descarte posterior separa el renglón de lo que de verdad se le pidió al
# proveedor: el ticket 26 recibiría mercancía contra un renglón que dice que
# nadie la pidió.
#
# Va en la sentencia y no en un `if` de Python, por lo mismo que la otra: leer
# el estado de la lista y actualizar después tiene una carrera en medio —una
# pestaña cierra mientras otra descarta—.
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
    update pedidos.renglon as r
       set estado = 'descartado',
           descartado_por = :quien,
           descartado_en = now()
      from pedidos.pedido_sugerido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'abierto'
       and p.pedido_sugerido_id = r.pedido_sugerido_id
       and p.negocio = r.negocio
       and p.estado = 'abierto'
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Deshacer el descarte. Lo que hace segura la operación de un clic.
#
# `descartado_por` y `descartado_en` vuelven a NULL **las dos**: un renglón
# abierto no está descartado, y `ck_renglon_descarte` rechaza la mitad. Dejar
# la firma puesta haría que el conteo mensual del ADR 0002 sumara renglones que
# alguien está trabajando.
#
# `and r.estado = 'descartado'` es la otra mitad de la transición: no se "abre"
# un renglón recibido ni uno en tránsito por esta puerta.
#
# **Y la lista abierta también, desde el 2026-09-20.** Deshacer es modificar, y
# poner la condición solo en el descarte habría sido peor que no tocar nada: un
# renglón podría quedar `descartado` dentro de una lista cerrada y no poder
# volver. Las dos direcciones o ninguna.
_DEVOLVER_A_ABIERTO = text(
    """
    update pedidos.renglon as r
       set estado = 'abierto',
           descartado_por = null,
           descartado_en = null
      from pedidos.pedido_sugerido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'descartado'
       and p.pedido_sugerido_id = r.pedido_sugerido_id
       and p.negocio = r.negocio
       and p.estado = 'abierto'
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Ajustar la cantidad de un renglón (ticket 11).
#
# `set cantidad_final = ...` y NUNCA `cantidad_propuesta`: la propuesta del
# sistema es inmutable y se escribe una sola vez, en el INSERT que arma la
# lista. La diferencia entre las dos es lo que después dice si la reposición 1 a
# 1 está bien calibrada, y una sentencia que pisara la propuesta dejaría esa
# diferencia en cero para siempre sin un solo error que ver.
#
# **DOS condiciones de transición, y las dos en el WHERE.** La primera es la
# misma del descarte —solo se corrige lo `abierto`—. La segunda es lo que este
# ticket agrega: `p.estado = 'abierto'`, la LISTA. Un `UPDATE ... FROM` y no un
# `SELECT` previo porque comprobar el estado de la lista en Python y actualizar
# después tiene una carrera en medio: dos pestañas en el mostrador, una cierra y
# la otra corrige, y la corrección entra en una lista que ya se pidió.
#
# La unión lleva `p.negocio = r.negocio` además del id: es la misma pareja de
# columnas de `fk_renglon_sugerido`, y con ella el `negocio` del parámetro acota
# a las dos tablas (regla 7).
#
# Las tres columnas se escriben juntas porque `ck_renglon_ajuste` las exige
# juntas: cantidad final si y solo si hay firma Y hora. `now()` y no una hora de
# Python, por la misma razón que el descarte y el cierre.
_AJUSTAR_LA_CANTIDAD = text(
    """
    update pedidos.renglon as r
       set cantidad_final = :cantidad,
           ajustada_por = :quien,
           ajustada_en = now()
      from pedidos.pedido_sugerido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'abierto'
       and p.pedido_sugerido_id = r.pedido_sugerido_id
       and p.negocio = r.negocio
       and p.estado = 'abierto'
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Congelar lo que contestaron los proveedores (ticket 12).
#
# `INSERT ... SELECT` y no `INSERT ... VALUES`, y ahí está la garantía: el
# renglón y su negocio se comprueban DENTRO de la sentencia contra
# `pedidos.renglon`, así que una lectura no se le puede pegar a un renglón que
# no existe ni a uno de otro negocio (regla 7). Un `SELECT` previo en Python y
# un `INSERT` después tienen una carrera en medio; esto no.
#
# La llave foránea `fk_precio_renglon` lo volvería a rechazar de todas formas,
# pero con un error de restricción que no explica nada. Cero filas sí explica:
# "no había renglón al que guardarle precio".
#
# `consultado_en` NO se escribe: lo pone el DEFAULT `now()` de la columna, que
# es la hora de la TRANSACCIÓN. Los cuatro proveedores de una consulta quedan
# con el mismo instante —fue una sola lectura— y dos consultas distintas nunca
# lo comparten. Una hora calculada en Python dejaría lecturas incomparables
# entre dos procesos con relojes distintos, que es la misma razón del cierre y
# del descarte.
#
# **Sin `ON CONFLICT` y sin `UPDATE`**: esta tabla solo crece. El porqué entero
# está en el docstring de `guardar_precios`; en corto, un `UPDATE` haría que
# una consulta fallida borrara un precio bueno.
_GUARDAR_PRECIO = text(
    """
    insert into pedidos.precio_de_proveedor
        (negocio, renglon_id, proveedor, precio_como_llego, precio,
         existencia_como_llego, existencia, motivo, detalle,
         clave_del_proveedor, descripcion_del_proveedor, resultados)
    select r.negocio, r.renglon_id, :proveedor, :precio_como_llego, :precio,
           :existencia_como_llego, :existencia, :motivo, :detalle,
           :clave_del_proveedor, :descripcion_del_proveedor, :resultados
      from pedidos.renglon as r
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
    """
)

# La lectura MÁS RECIENTE de cada proveedor, de todos los renglones de una
# lista. `DISTINCT ON` es de Postgres y es justo la herramienta: pide una fila
# por pareja (renglón, proveedor) y el `ORDER BY` decide cuál.
#
# El `precio_de_proveedor_id desc` del desempate no es adorno: `now()` es la
# hora de la transacción, así que dos consultas que se solapen pueden compartir
# `consultado_en` y sin el desempate cuál gana dependería del plan de Postgres.
# `ultimo_por_proveedor` desempata igual en el doble.
#
# El `join` contra `renglon` lleva las DOS columnas de `fk_precio_renglon`
# —id y negocio—, así que el `negocio` del parámetro acota las dos tablas.
_LEER_PRECIOS = text(
    """
    select distinct on (p.renglon_id, p.proveedor)
           p.renglon_id, p.proveedor, p.consultado_en,
           p.precio_como_llego, p.precio,
           p.existencia_como_llego, p.existencia,
           p.motivo, p.detalle,
           p.clave_del_proveedor, p.descripcion_del_proveedor, p.resultados
      from pedidos.precio_de_proveedor as p
      join pedidos.renglon as r
        on r.renglon_id = p.renglon_id and r.negocio = p.negocio
     where p.negocio = :negocio
       and r.pedido_sugerido_id = :pedido_sugerido_id
     order by p.renglon_id, p.proveedor,
              p.consultado_en desc, p.precio_de_proveedor_id desc
    """
)

# Lo mismo para un renglón solo. Sin el `join`, porque no hace falta llegar a
# la lista: `negocio` y `renglon_id` ya identifican la fila.
_LEER_PRECIOS_DEL_RENGLON = text(
    """
    select distinct on (p.proveedor)
           p.renglon_id, p.proveedor, p.consultado_en,
           p.precio_como_llego, p.precio,
           p.existencia_como_llego, p.existencia,
           p.motivo, p.detalle,
           p.clave_del_proveedor, p.descripcion_del_proveedor, p.resultados
      from pedidos.precio_de_proveedor as p
     where p.negocio = :negocio
       and p.renglon_id = :renglon_id
     order by p.proveedor, p.consultado_en desc, p.precio_de_proveedor_id desc
    """
)

# Elegir a quién se le pide un renglón (ticket 20).
#
# **La misma forma que `_AJUSTAR_LA_CANTIDAD`, y no es copia perezosa**: las dos
# son la decisión de una persona sobre un renglón, y las dos tienen las MISMAS
# dos condiciones de transición en el `WHERE` —el renglón `abierto` y su lista
# `abierta`—. Un renglón `en tránsito` ya se le pidió a un proveedor y cambiarle
# el destinatario aquí haría que el renglón dijera una cosa y el proveedor otra;
# una lista `cerrada` quiere decir "ya se pidió lo que se iba a pedir".
#
# LA INCOHERENCIA QUE ESTE COMENTARIO DENUNCIABA YA SE ARREGLÓ (2026-09-20).
# Aquí decía que `_DESCARTAR` dejaba descartar aunque la lista estuviera
# cerrada, porque el ticket 10 solo le había puesto el estado del RENGLÓN al
# `WHERE`, y pedía que el arreglo se hiciera "a propósito y no de paso". Se
# hizo: `_DESCARTAR` y `_DEVOLVER_A_ABIERTO` llevan ahora las mismas dos
# condiciones que esta sentencia, así que **las tres acciones que una persona
# hace sobre un renglón dicen lo mismo**: descartar, ajustar la cantidad y
# elegir proveedor exigen el renglón `abierto` y su lista `abierta`.
#
# Se deja escrito porque la razón sigue valiendo para la siguiente acción que se
# agregue: armar un pedido dentro de una lista que ya se pidió es exactamente lo
# que `cerrado` significa que no debe pasar.
#
# Las tres columnas se escriben juntas porque `ck_renglon_eleccion` las exige
# juntas, igual que `ck_renglon_ajuste` con las suyas. `now()` y no una hora de
# Python, por la misma razón que el descarte y el cierre.
_ELEGIR_PROVEEDOR = text(
    """
    update pedidos.renglon as r
       set proveedor_elegido = :proveedor,
           elegido_por = :quien,
           elegido_en = now()
      from pedidos.pedido_sugerido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'abierto'
       and p.pedido_sugerido_id = r.pedido_sugerido_id
       and p.negocio = r.negocio
       and p.estado = 'abierto'
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Los pedidos de una lista, para pintarlos y para saber cuáles siguen en
# borrador. Ordenados por proveedor y no por id: el orden de creación depende de
# en qué orden alguien apretó el botón, y dos cargas de la misma pantalla no
# deben enseñar las columnas cambiadas de sitio.
_LEER_PEDIDOS = text(
    """
    select pedido_id, negocio, pedido_sugerido_id, proveedor, proveedor_id,
           estado, armado_en, total_sin_iva, enviado_por, enviado_en,
           cancelado_por, cancelado_en
      from pedidos.pedido
     where negocio = :negocio and pedido_sugerido_id = :pedido_sugerido_id
     order by proveedor
    """
)

# Abrir —o volver a abrir— el pedido de UN proveedor dentro de una lista.
#
# `INSERT ... SELECT` contra `pedido_sugerido` y no `INSERT ... VALUES`, igual
# que `_GUARDAR_PRECIO`: **la lista y su estado se comprueban DENTRO de la
# sentencia**. Cero filas es "esa lista no existe en este negocio, o ya no está
# abierta", y quien llama lo dice en vez de fingir. Un `SELECT` previo en Python
# y un `INSERT` después tienen una carrera en medio: una pestaña cierra la lista
# mientras la otra parte.
#
# `ON CONFLICT ON CONSTRAINT ux_pedido_proveedor DO UPDATE` es la respuesta a
# "¿qué pasa si se parte dos veces?": **no se duplica nada**. La restricción ya
# existía desde el ticket 07 —"uno por proveedor dentro de la misma lista"— y
# aquí se usa para reencontrar el pedido que ya estaba en vez de chocar contra
# ella. Se nombra la RESTRICCIÓN y no las columnas: si alguien la renombra en el
# DDL, esto falla ruidoso en lugar de seguir funcionando contra otra parecida.
#
# `where pedido.estado = 'borrador'` es la tercera casilla del ticket metida en
# el `WHERE` y no en un `if`: **solo se modifica lo que sigue en borrador**.
# Desde el ticket 21 hay un pedido que puede estar en "enviado", y volver a
# partir lo deja intacto y devuelve cero filas — que es lo que hay que decir, no
# lo que hay que pisar.
#
# Se reescriben `proveedor_id` y `total_sin_iva` porque las dos pueden haber
# cambiado entre dos particiones: el puente se pudo configurar, y una cantidad
# corregida cambia el total. `armado_en = now()` deja ver **de cuándo es** ese
# total, que es lo único que permite notar que envejeció.
_ABRIR_EL_PEDIDO = text(
    """
    insert into pedidos.pedido
        (negocio, pedido_sugerido_id, proveedor, proveedor_id, estado,
         total_sin_iva)
    select s.negocio, s.pedido_sugerido_id, :proveedor, :proveedor_id,
           :estado, :total_sin_iva
      from pedidos.pedido_sugerido as s
     where s.negocio = :negocio
       and s.pedido_sugerido_id = :pedido_sugerido_id
       and s.estado = 'abierto'
    on conflict on constraint ux_pedido_proveedor do update
       set proveedor_id = excluded.proveedor_id,
           total_sin_iva = excluded.total_sin_iva,
           armado_en = now()
     where pedido.estado = 'borrador'
    returning pedido_id, negocio, pedido_sugerido_id, proveedor, proveedor_id,
              estado, armado_en, total_sin_iva, enviado_por, enviado_en
    """
)

# ENVIAR UN PEDIDO (ticket 21). `borrador` -> `enviado`, firmado.
#
# Lo que esta sentencia escribe **no es un hecho que Continental haya visto**:
# es la declaración de una persona de que ya capturó este pedido en el portal
# del proveedor. Continental no entra a los portales (regla 1 de CLAUDE.md, ADR
# 0002 y ADR 0009). De ahí que lleve firma y no acuse.
#
# `now()` y no una hora calculada en Python, igual que en `_CERRAR` y en el
# descarte: la pone el servidor que guarda la fila, así que dos procesos con
# relojes distintos no escriben firmas incomparables.
#
# Las condiciones del `WHERE`, y cada una defiende algo distinto:
#
#   - `p.negocio` — regla 7. Toda sentencia dice a qué negocio pertenece.
#   - `p.estado = 'borrador'` — la transición en el `WHERE` y no en un `if`.
#     Cero filas es "ya estaba enviado", y el segundo clic de un botón que viajó
#     no mueve la firma ni la hora de un hecho que ya pasó. Comprobar en Python
#     y escribir después tiene una carrera en medio.
#   - **`exists` sobre sus renglones** — un pedido vacío no se envía. El que se
#     quedó sin ninguno al volver a partir sigue ahí, con total `NULL`, porque
#     el rol no tiene `DELETE`; marcarlo `enviado` diría "capturé esto en el
#     portal" sobre nada.
#   - **`not exists` sobre las cantidades corregidas después de armarlo** — el
#     total no puede quedar viejo al enviarse. `total_sin_iva` solo se reescribe
#     al partir, así que corregir la cantidad de un renglón que ya está dentro
#     de un pedido lo deja enseñando lo que costaba hace un rato (hilo abierto
#     13 de `HANDOVER.md`, que le dejó este caso al ticket 21). Se NIEGA en vez
#     de recalcular aquí: recalcular cambiaría el número después de que el
#     encargado leyó el del botón, y enviaría un total que nadie vio. Cero filas
#     manda a "Volver a partir", que es un botón que ya existe y cuesta un clic.
#     Un total viejo es la cifra contra la que alguien va a comparar la factura:
#     si no cuadra, nadie sabe si falta mercancía o si el número estaba rancio.
#
# **NO lleva `s.estado = 'abierto'`, y es una decisión (ADR 0009).** Todas las
# demás sentencias de este módulo exigen la lista abierta porque `cerrada`
# quiere decir "ya se pidió lo que se iba a pedir" y cambiarla después separaría
# el renglón de lo que de verdad se pidió. Enviar es lo contrario: es decir que
# sí se pidió. Con esa condición puesta, quien cierre la lista antes de marcar
# el último pedido se queda con renglones `abierto` dentro de una lista cerrada
# y sin manera de moverlos a `en tránsito` — o sea, con mercancía pedida que el
# sugerido de mañana volvería a proponer.
_ENVIAR_EL_PEDIDO = text(
    """
    update pedidos.pedido as p
       set estado = 'enviado',
           enviado_por = :quien,
           enviado_en = now()
     where p.negocio = :negocio
       and p.pedido_id = :pedido_id
       and p.estado = 'borrador'
       and exists (select 1
                     from pedidos.renglon as r
                    where r.pedido_id = p.pedido_id
                      and r.negocio = p.negocio)
       and not exists (select 1
                         from pedidos.renglon as r
                        where r.pedido_id = p.pedido_id
                          and r.negocio = p.negocio
                          and r.ajustada_en is not null
                          and r.ajustada_en > p.armado_en)
    returning p.pedido_id, p.negocio, p.pedido_sugerido_id, p.proveedor,
              p.proveedor_id, p.estado, p.armado_en, p.total_sin_iva,
              p.enviado_por, p.enviado_en
    """
)

# Y sus renglones pasan a `en tránsito`: "ya se le pidió a un proveedor y
# todavía no llega" (CONTEXT.md). **Es lo que impide pedir dos veces lo mismo**,
# porque un renglón así no se vuelve a proponer.
#
# Va en la MISMA transacción que la de arriba, y no es un detalle: medio envío
# —el pedido marcado y los renglones en `abierto`— es exactamente el modo de
# falla que este ticket viene a evitar.
#
#   - `r.pedido_id = :pedido_id` — solo los de ESTE pedido. Sin esto, enviar a
#     NADRO marcaría como pedido lo que todavía está en el borrador de LEVIC.
#   - `r.estado = 'abierto'` — un descartado sigue descartado y uno que ya
#     estaba `en tránsito` no se vuelve a mover. Y es lo que hace que esto sea
#     idempotente por su cuenta, aunque el `WHERE` de arriba ya lo garantice.
#
# El acento de `en tránsito` va en la sentencia: es el valor del glosario y el
# del CHECK. `test_compila.py` vigila que este archivo no traiga un retorno de
# carro que lo convierta en `'en tránsito\r'`.
_RENGLONES_A_TRANSITO = text(
    """
    update pedidos.renglon as r
       set estado = 'en tránsito'
     where r.negocio = :negocio
       and r.pedido_id = :pedido_id
       and r.estado = 'abierto'
    returning r.renglon_id
    """
)

# CANCELAR UN PEDIDO (ticket 25, ADR 0013). `enviado` -> `cancelado`, firmado.
#
# Es la palabra de una persona de que este pedido NO está en el portal del
# proveedor: nunca se capturó, o se canceló allá también. Continental no
# cancela nada en ningún portal, igual que no captura nada en ninguno.
#
#   - `p.negocio` — regla 7.
#   - `p.estado = 'enviado'` — la transición en el `WHERE`. Un borrador no se
#     le ha pedido a nadie (se vuelve a partir) y uno ya cancelado no mueve su
#     firma con el segundo clic. Cero filas y quien llama lo dice.
#   - **`not exists` sobre lo recibido** — si algo de este pedido llegó, sí se
#     capturó, y "nunca se capturó" sería falso. Hoy nada escribe `recibido`
#     (ticket 26); la condición está desde ya para que ese ticket no tenga que
#     acordarse de venir aquí.
#
# `enviado_por` y `enviado_en` NO se tocan: alguien SÍ dijo haberlo capturado, y
# esa palabra es parte de la historia del pedido. `ck_pedido_envio` las exige
# desde el ticket 25 para `enviado` y para `cancelado`.
#
# **NO mira la lista, igual que enviar (ADR 0009).** Cancelar no modifica lo
# que se iba a pedir: dice que no se pidió.
_CANCELAR_EL_PEDIDO = text(
    """
    update pedidos.pedido as p
       set estado = 'cancelado',
           cancelado_por = :quien,
           cancelado_en = now()
     where p.negocio = :negocio
       and p.pedido_id = :pedido_id
       and p.estado = 'enviado'
       and not exists (select 1
                         from pedidos.renglon as r
                        where r.pedido_id = p.pedido_id
                          and r.negocio = p.negocio
                          and r.estado in ('recibido', 'recibido parcial'))
    returning p.pedido_id, p.negocio, p.pedido_sugerido_id, p.proveedor,
              p.proveedor_id, p.estado, p.armado_en, p.total_sin_iva,
              p.enviado_por, p.enviado_en, p.cancelado_por, p.cancelado_en
    """
)

# Y sus renglones que seguían en camino pasan a `cancelado`, con la MISMA
# firma: `now()` es el mismo instante en toda la transacción, así que el pedido
# y sus renglones dicen la misma hora.
#
#   - `r.pedido_id = :pedido_id` — solo los de ESTE pedido.
#   - `r.estado = 'en tránsito'` — uno que ya se había devuelto por atrasado
#     conserva su firma, y uno descartado sigue descartado.
#
# El renglón NO se suelta de su pedido (`pedido_id` se queda): es la historia
# de qué se pidió y qué se canceló. `fk_renglon_pedido` sigue apuntando a un
# pedido de su misma lista.
_RENGLONES_CANCELADOS = text(
    """
    update pedidos.renglon as r
       set estado = 'cancelado',
           cancelado_por = :quien,
           cancelado_en = now()
     where r.negocio = :negocio
       and r.pedido_id = :pedido_id
       and r.estado = 'en tránsito'
    returning r.renglon_id
    """
)

# DEVOLVER A LA LISTA UN RENGLÓN ATRASADO (ticket 25, casilla 4). Él solo: el
# pedido sigue `enviado`.
#
#   - `r.negocio`, y `p.negocio = r.negocio` en la unión — regla 7.
#   - `r.estado = 'en tránsito'` — la transición en el `WHERE`.
#   - `p.estado = 'enviado'` — de un pedido cancelado ya no queda nada en
#     tránsito, y uno en borrador no tiene renglones en tránsito.
#   - **`p.enviado_en < :enviado_antes_de`** — "lleva más de N días en
#     camino". El límite lo calcula `transito.enviado_antes_de` en la hora de
#     la farmacia y viaja como PARÁMETRO: la aritmética de zonas no vive aquí,
#     porque en Postgres `at time zone '-06'` es la convención POSIX y se lee
#     como UTC+6. Es la misma función con la que la pantalla decide qué
#     ofrecer, así que las dos no pueden separarse. Nada de esto depende del
#     reloj del contenedor.
_DEVOLVER_EL_ATRASADO = text(
    """
    update pedidos.renglon as r
       set estado = 'cancelado',
           cancelado_por = :quien,
           cancelado_en = now()
      from pedidos.pedido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'en tránsito'
       and p.pedido_id = r.pedido_id
       and p.negocio = r.negocio
       and p.estado = 'enviado'
       and p.enviado_en < :enviado_antes_de
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Meter renglones en un pedido. **Un renglón pertenece a un solo pedido**: es un
# `SET pedido_id = ...` sobre una columna, no una fila en una tabla de cruce, y
# por eso moverlo de pedido no puede dejarlo en dos.
#
# `= any(:renglon_ids)` y no un `IN` armado con cadenas: los ids viajan como un
# parámetro, así que no hay SQL construido a mano en ningún punto.
#
# Las condiciones del `WHERE`, y cada una defiende algo distinto:
#
#   - `r.pedido_sugerido_id` — el renglón es de ESTA lista. Sin esto, un id
#     equivocado metería en el pedido un renglón de la lista de otro día, y el
#     total del pedido dejaría de poder explicarse.
#   - `r.estado = 'abierto'` — un renglón `en tránsito` ya se le pidió a alguien
#     y uno `descartado` ya se atendió. Es la transición en el `WHERE`.
#   - `s.estado = 'abierto'` — la lista sigue abierta, igual que en el ajuste.
#   - **y el renglón no cuelga ya de un pedido que dejó de ser borrador.** Es la
#     misma condición que `_SOLTAR_RENGLONES` lleva, y aquí hacía más falta:
#     sin ella, volver a partir **sacaría** un renglón de un pedido ya enviado
#     para meterlo en otro, y el pedido enviado quedaría diciendo un total que
#     ya no corresponde a lo que tiene dentro. El ticket 21 lo protege además
#     por el otro lado —sus renglones pasan a `en tránsito` al enviar, y eso ya
#     no es `abierto`—, y aun así esta condición se queda: una restricción que
#     depende de que otra parte del sistema haga la suya no es una restricción,
#     y el día que la recepción (ticket 26) devuelva un renglón a `abierto` esta
#     sería la única que lo sostendría.
#
# **Y desde el ticket 22 le borra la marca de captura al que CAMBIA de
# pedido.** Tachado en el portal de NADRO y movido a LEVIC: en el portal de
# LEVIC nadie lo ha tecleado, y una marca que viajara con él le diría al
# encargado que se lo salte. El que se queda en el mismo pedido la CONSERVA —
# volver a partir a mitad de la captura no puede costar el avance entero—, y
# por eso es un `case` sobre el valor viejo y no un `null` a secas. En el `SET`
# de un `UPDATE`, `r.pedido_id` es el valor de ANTES del cambio.
#
# `is distinct from` y no `<>`: con `pedido_id` nulo, `<>` da nulo y el `case`
# se iría por el `else`, conservando una marca de un renglón que no estaba en
# ningún pedido. No puede pasar hoy —sin pedido no se tacha— y aun así se
# escribe bien: la sentencia no depende de que otra parte haga la suya.
_ASIGNAR_RENGLONES = text(
    """
    update pedidos.renglon as r
       set pedido_id = :pedido_id,
           capturado_por = case when r.pedido_id is distinct from :pedido_id
                                then null else r.capturado_por end,
           capturado_en = case when r.pedido_id is distinct from :pedido_id
                               then null else r.capturado_en end
      from pedidos.pedido_sugerido as s
     where r.negocio = :negocio
       and r.pedido_sugerido_id = :pedido_sugerido_id
       and r.renglon_id = any(:renglon_ids)
       and r.estado = 'abierto'
       and s.pedido_sugerido_id = r.pedido_sugerido_id
       and s.negocio = r.negocio
       and s.estado = 'abierto'
       and (r.pedido_id is null
            or exists (select 1
                         from pedidos.pedido as p
                        where p.pedido_id = r.pedido_id
                          and p.negocio = r.negocio
                          and p.estado = 'borrador'))
    returning r.renglon_id
    """
)

# Sacar de su pedido a los renglones que esta partición ya no reparte.
#
# Es la otra mitad de "¿y si se parte, se cambia una elección, y se vuelve a
# partir?". Mover un renglón de un pedido a otro lo hace `_ASIGNAR_RENGLONES`
# solo —le pisa el `pedido_id`—; lo que esta sentencia atiende es el caso en
# que un renglón deja de tener a quién pedírsele: llegó un precio nuevo y ahora
# ninguno lo tiene, o alguien lo descartó. Dejarlo colgando de su pedido viejo
# haría que el pedido tuviera un renglón más de los que su total cuenta.
#
# `exists (... p.estado = 'borrador')` protege lo que ya no es borrador: un
# renglón que cuelgue de un pedido enviado (ticket 21) no se suelta por volver a
# partir. Sin esa condición, repartir de nuevo vaciaría un pedido que ya está en
# el portal del proveedor.
#
# Y desde el ticket 22 le borra también la marca de captura: un renglón que ya
# no se reparte a nadie no está capturado en ningún portal que este sistema vaya
# a mirar, y una marca colgada lo haría aparecer tachado el día que vuelva a
# entrar en un pedido.
_SOLTAR_RENGLONES = text(
    """
    update pedidos.renglon as r
       set pedido_id = null,
           capturado_por = null,
           capturado_en = null
      from pedidos.pedido_sugerido as s
     where r.negocio = :negocio
       and r.pedido_sugerido_id = :pedido_sugerido_id
       and r.pedido_id is not null
       and r.estado = 'abierto'
       and not (r.renglon_id = any(:renglon_ids))
       and s.pedido_sugerido_id = r.pedido_sugerido_id
       and s.negocio = r.negocio
       and s.estado = 'abierto'
       and exists (select 1
                     from pedidos.pedido as p
                    where p.pedido_id = r.pedido_id
                      and p.negocio = r.negocio
                      and p.estado = 'borrador')
    returning r.renglon_id
    """
)

# Un pedido que se quedó sin renglones deja de tener total.
#
# Es la esquina del "¿y si se parte, se cambia una elección, y se vuelve a
# partir?" que se hace mal sola: el pedido que perdió todos sus renglones **ya
# no está en la partición**, así que `_ABRIR_EL_PEDIDO` no lo toca y se quedaría
# enseñando el total de la partición anterior — treinta pesos de mercancía que
# ahora se le pide a otro. Nadie lo vería como un error: es una cifra con dos
# decimales al lado de un pedido que existe.
#
# El total se va a NULL y NO a cero, que es la misma regla que en todo este
# esquema: un pedido vacío no cuesta nada porque no tiene nada, no porque sea
# gratis, y un `0.00` en una lista de totales pasa desapercibido. La columna es
# nullable a propósito y su COMMENT ya lo dice: "NULL = todavía no se sabe,
# nunca cero".
#
# El pedido **no se borra**: el rol no tiene DELETE (ADR 0003) y descartar,
# cerrar y cancelar son cambios de estado. Se queda, vacío y visible, que
# además es lo honesto — alguien armó ese pedido y después lo deshizo.
#
# `p.estado = 'borrador'` por lo mismo que en las otras dos: lo que ya se envió
# (ticket 21) no se toca.
_VACIAR_LOS_PEDIDOS_SIN_RENGLONES = text(
    """
    update pedidos.pedido as p
       set total_sin_iva = null
     where p.negocio = :negocio
       and p.pedido_sugerido_id = :pedido_sugerido_id
       and p.estado = 'borrador'
       and p.total_sin_iva is not null
       and not exists (select 1
                         from pedidos.renglon as r
                        where r.pedido_id = p.pedido_id
                          and r.negocio = p.negocio)
    returning p.pedido_id
    """
)

# Tachar un renglón en la pantalla de captura (ticket 22, ADR 0010).
#
# Las cuatro condiciones del `WHERE`, y cada una defiende algo distinto:
#
#   - `r.negocio` — regla 7.
#   - `r.estado = 'abierto'` — uno descartado no se va a pedir, y uno `en
#     tránsito` ya se envió.
#   - `p.pedido_id = r.pedido_id` — el renglón cuelga de un pedido. Sin pedido
#     no hay proveedor de cuyo portal hablar. El `join` por `pedido_id` deja
#     fuera, solo, a un renglón con `pedido_id` nulo.
#   - `p.estado = 'borrador'` — uno `enviado` ya no se edita (ADR 0009), ni
#     para tachar ni para destachar.
#
# **Y lo que NO lleva, a propósito: `pedido_sugerido` en el `FROM`.** Tachar no
# exige que la lista siga abierta, igual que enviar: es decir "ya lo tecleé en
# el portal", lo contrario de modificar lo que se va a pedir.
#
# **No toca `estado`.** Tachar no es un estado del renglón: sigue `abierto`
# hasta que se envíe su pedido (ADR 0010, opción 4).
#
# `now()` y no una hora de Python, por lo mismo que en el descarte. Devuelve
# `pedido_sugerido_id` porque `_mover_el_renglon` relee la lista por él.
_MARCAR_CAPTURADO = text(
    """
    update pedidos.renglon as r
       set capturado_por = :quien,
           capturado_en = now()
      from pedidos.pedido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'abierto'
       and p.pedido_id = r.pedido_id
       and p.negocio = r.negocio
       and p.estado = 'borrador'
    returning r.renglon_id, r.pedido_sugerido_id
    """
)

# Destachar: las dos columnas a NULL, con las MISMAS condiciones. Un pedido
# enviado no se destacha: sus marcas son la historia de cómo se capturó.
_DESMARCAR_CAPTURADO = text(
    """
    update pedidos.renglon as r
       set capturado_por = null,
           capturado_en = null
      from pedidos.pedido as p
     where r.negocio = :negocio
       and r.renglon_id = :renglon_id
       and r.estado = 'abierto'
       and p.pedido_id = r.pedido_id
       and p.negocio = r.negocio
       and p.estado = 'borrador'
    returning r.renglon_id, r.pedido_sugerido_id
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

# La corrida del lote (ticket 19, ADR 0007). **Un INSERT pelado**, sin `SELECT`
# que lo acote: al revés que el precio, esto no cuelga de un renglón que tenga
# que existir. Una corrida en la que no hubo lista es justamente la que más
# hace falta poder escribir —es la que contesta "el lote corrió y no encontró
# ventas"— y un `insert ... select` contra `pedido_sugerido` no escribiría ni
# una fila en ese caso.
#
# `termino_en` lo pone la base con `now()`, igual que `consultado_en`.
_GUARDAR_CORRIDA = text(
    """
    insert into pedidos.corrida_del_lote
        (negocio, pedido_sugerido_id, fecha_del_pedido, final, segundos,
         tope_minutos, en_la_lista, consultados, con_precio, sin_alcanzar,
         no_se_pudo, sin_clave, orden_cumplido, detalle)
    values
        (:negocio, :pedido_sugerido_id, :fecha_del_pedido, :final, :segundos,
         :tope_minutos, :en_la_lista, :consultados, :con_precio, :sin_alcanzar,
         :no_se_pudo, :sin_clave, :orden_cumplido, :detalle)
    returning corrida_del_lote_id
    """
)

# La última corrida sobre una lista. `limit 1` con el orden del índice
# `ix_corrida_ultima`: `termino_en desc` y el id como desempate, por lo mismo
# que en `_LEER_PRECIOS` —`now()` es la hora de la transacción y dos corridas
# lo podrían compartir si alguien lanzara el lote dos veces a mano—.
_ULTIMA_CORRIDA = text(
    """
    select corrida_del_lote_id, negocio, pedido_sugerido_id, fecha_del_pedido,
           termino_en, final, segundos, tope_minutos, en_la_lista, consultados,
           con_precio, sin_alcanzar, no_se_pudo, sin_clave, orden_cumplido,
           detalle
      from pedidos.corrida_del_lote
     where negocio = :negocio
       and pedido_sugerido_id = :pedido_sugerido_id
     order by termino_en desc, corrida_del_lote_id desc
     limit 1
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

    def leer_por_id(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        # `connect` y no `begin`: esto solo lee. Las dos consultas —la cabecera
        # y sus renglones— van en la MISMA conexión, igual que en `leer`, para
        # que no se pueda leer una cabecera de un momento y unos renglones de
        # otro.
        with self._motor().connect() as conexion:
            cabecera = (
                conexion.execute(
                    _LEER_LISTA_POR_ID,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                    },
                )
                .mappings()
                .first()
            )
            if cabecera is None:
                return None
            return self._con_renglones(conexion, cabecera)

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

    def piso_sin_pedir(self, negocio: str, antes_de: dt.date) -> dt.date | None:
        with self._motor().connect() as conexion:
            fila = (
                conexion.execute(
                    _PISO_SIN_PEDIR, {"negocio": negocio, "antes_de": antes_de}
                )
                .mappings()
                .first()
            )
        return None if fila is None else fila["piso"]

    def lo_ya_pedido(
        self, negocio: str, antes_de: dt.date
    ) -> tuple[LoYaPedido, ...]:
        # `connect` y no `begin`: solo lee.
        with self._motor().connect() as conexion:
            filas = (
                conexion.execute(
                    _LO_YA_PEDIDO, {"negocio": negocio, "antes_de": antes_de}
                )
                .mappings()
                .all()
            )
        return tuple(lo_ya_pedido_desde_columnas(f) for f in filas)

    def leer_renglon(self, negocio: str, renglon_id: int) -> RenglonGuardado | None:
        with self._motor().connect() as conexion:
            fila = (
                conexion.execute(
                    _LEER_RENGLON_POR_ID,
                    {"negocio": negocio, "renglon_id": renglon_id},
                )
                .mappings()
                .first()
            )
        return None if fila is None else renglon_guardado_desde_columnas(fila)

    def precios_del_renglon(
        self, negocio: str, renglon_id: int
    ) -> tuple[PrecioDeProveedor, ...]:
        with self._motor().connect() as conexion:
            filas = (
                conexion.execute(
                    _LEER_PRECIOS_DEL_RENGLON,
                    {"negocio": negocio, "renglon_id": renglon_id},
                )
                .mappings()
                .all()
            )
        return tuple(precio_desde_columnas(f) for f in filas)

    def precios_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> dict[int, tuple[PrecioDeProveedor, ...]]:
        with self._motor().connect() as conexion:
            filas = (
                conexion.execute(
                    _LEER_PRECIOS,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                    },
                )
                .mappings()
                .all()
            )

        por_renglon: dict[int, list[PrecioDeProveedor]] = {}
        for fila in filas:
            precio = precio_desde_columnas(fila)
            por_renglon.setdefault(precio.renglon_id, []).append(precio)
        return {
            renglon_id: tuple(precios)
            for renglon_id, precios in por_renglon.items()
        }

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

    def ajustar_la_cantidad(
        self, negocio: str, renglon_id: int, cantidad: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        return self._mover_el_renglon(
            _AJUSTAR_LA_CANTIDAD,
            {
                "negocio": negocio,
                "renglon_id": renglon_id,
                "cantidad": cantidad,
                "quien": quien,
            },
        )

    def guardar_precios(
        self, negocio: str, renglon_id: int, lecturas: Sequence[LecturaDePrecio]
    ) -> int:
        if not lecturas:
            # Sin lecturas no hay nada que escribir y no es un error: una
            # búsqueda que no alcanzó a preguntarle a ningún proveedor deja el
            # renglón sin comparar, que es lo que el ticket 15 cuenta.
            return 0

        filas = []
        for lectura in lecturas:
            columnas = columnas_del_precio(lectura, negocio, renglon_id)
            # Se revisa TODO antes de escribir la primera fila, igual que al
            # insertar la lista: los cuatro proveedores de una consulta entran
            # juntos o no entra ninguno. Una consulta a medias diría que a dos
            # proveedores no se les preguntó, y el conteo del ticket 15
            # mentiría.
            revisar_el_precio(columnas)
            filas.append(columnas)

        # UNA EJECUCIÓN POR FILA, y no un `executemany` con las cuatro. No es
        # descuido: **psycopg2 no tiene `supports_sane_multi_rowcount`**
        # (comprobado sobre el dialecto el 2026-09-19), así que el `rowcount`
        # de una ejecución con varias parejas de parámetros no es de fiar —
        # viene en -1 o con el de la última—. Y ese número es justo el que
        # distingue "se guardó" de "no había renglón": una consulta buena se
        # habría anotado como `sin guardar` con el motivo "ese renglón ya no
        # está en la lista", en atlas y solo en atlas, después de que aquí todo
        # se viera verde.
        #
        # Lo que cuesta son cuatro idas y vueltas en vez de una, por loopback y
        # una vez por clic. Contra los ~9 s por proveedor que acaba de costar la
        # consulta, no se mide.
        #
        # Siguen siendo UNA transacción: los cuatro proveedores entran juntos o
        # no entra ninguno.
        with self._motor().begin() as conexion:
            return sum(
                max(conexion.execute(_GUARDAR_PRECIO, fila).rowcount, 0)
                for fila in filas
            )

    def pedidos_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> tuple[PedidoGuardado, ...]:
        with self._motor().connect() as conexion:
            filas = (
                conexion.execute(
                    _LEER_PEDIDOS,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                    },
                )
                .mappings()
                .all()
            )
        return tuple(pedido_desde_columnas(f) for f in filas)

    def elegir_proveedor(
        self, negocio: str, renglon_id: int, proveedor: str, quien: str
    ) -> PedidoSugeridoGuardado | None:
        return self._mover_el_renglon(
            _ELEGIR_PROVEEDOR,
            {
                "negocio": negocio,
                "renglon_id": renglon_id,
                "proveedor": proveedor,
                "quien": quien,
            },
        )

    def guardar_la_particion(
        self,
        negocio: str,
        pedido_sugerido_id: int,
        pedidos: Sequence[PedidoPorArmar],
    ) -> tuple[PedidoGuardado, ...] | None:
        # `begin()` y no `connect()`: todo lo de aquí abajo es UNA transacción.
        # Una partición a medias dejaría renglones colgando de pedidos cuyos
        # totales no los cuentan, y el rol no tiene DELETE para deshacerlo.
        with self._motor().begin() as conexion:
            guardados: list[PedidoGuardado] = []
            asignados: list[int] = []
            alguna_lista = False

            for pedido in pedidos:
                columnas = columnas_del_pedido(
                    negocio,
                    pedido_sugerido_id,
                    pedido.proveedor,
                    pedido.proveedor_id,
                    pedido.total_sin_iva,
                )
                # El mismo validador que llama el doble. Si esto se negara solo
                # de un lado, el suite quedaría en verde y el INSERT rebotaría
                # en atlas contra una restricción que nadie sabría explicar.
                revisar_el_pedido(columnas)
                fila = (
                    conexion.execute(_ABRIR_EL_PEDIDO, columnas).mappings().first()
                )
                if fila is None:
                    # Cero filas quiere decir una de dos, y las dos son "no se
                    # escribió": la lista no está abierta, o ese pedido ya no es
                    # borrador. No se distinguen desde fuera a propósito, igual
                    # que en el descarte.
                    continue
                alguna_lista = True
                guardados.append(pedido_desde_columnas(fila))

                ids = [linea.renglon_id for linea in pedido.lineas]
                if not ids:
                    continue
                movidos = conexion.execute(
                    _ASIGNAR_RENGLONES,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                        "pedido_id": fila["pedido_id"],
                        "renglon_ids": ids,
                    },
                ).all()
                asignados.extend(int(f[0]) for f in movidos)

            if not alguna_lista and pedidos:
                return None

            # Los que esta partición ya no reparte se sueltan. Si no hubiera
            # ningún asignado, `any(array[])` seguiría siendo la comparación
            # correcta: `NOT (x = ANY('{}'))` es cierto para todo x, que es
            # exactamente "suéltalos todos".
            conexion.execute(
                _SOLTAR_RENGLONES,
                {
                    "negocio": negocio,
                    "pedido_sugerido_id": pedido_sugerido_id,
                    "renglon_ids": asignados,
                },
            )

            # Y el que se quedó sin ninguno pierde su total. Va DESPUÉS de las
            # dos sentencias anteriores porque es su consecuencia: un pedido se
            # vacía cuando sus renglones se van a otro.
            conexion.execute(
                _VACIAR_LOS_PEDIDOS_SIN_RENGLONES,
                {
                    "negocio": negocio,
                    "pedido_sugerido_id": pedido_sugerido_id,
                },
            )

            filas = (
                conexion.execute(
                    _LEER_PEDIDOS,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                    },
                )
                .mappings()
                .all()
            )
        return tuple(pedido_desde_columnas(f) for f in filas)

    def enviar_el_pedido(
        self, negocio: str, pedido_id: int, quien: str
    ) -> PedidoEnviado | None:
        # `begin()` y no `connect()`: las dos sentencias son UNA transacción.
        # Medio envío —el pedido marcado y sus renglones todavía `abierto`— es
        # el modo de falla que este ticket viene a evitar, y el rol no tiene
        # `DELETE` para deshacerlo a mano.
        with self._motor().begin() as conexion:
            fila = (
                conexion.execute(
                    _ENVIAR_EL_PEDIDO,
                    {"negocio": negocio, "pedido_id": pedido_id, "quien": quien},
                )
                .mappings()
                .first()
            )
            if fila is None:
                # Cero filas quiere decir una de tres, y las tres son "no se
                # envió": el pedido no existe en este negocio, ya no es
                # borrador, o se quedó sin renglones. No se distinguen desde
                # fuera, igual que en el descarte.
                return None
            movidos = conexion.execute(
                _RENGLONES_A_TRANSITO,
                {"negocio": negocio, "pedido_id": pedido_id},
            ).all()
        return PedidoEnviado(
            pedido=pedido_desde_columnas(fila),
            renglones=tuple(int(f[0]) for f in movidos),
        )

    def cancelar_el_pedido(
        self, negocio: str, pedido_id: int, quien: str
    ) -> PedidoCancelado | None:
        # `begin()`: las dos sentencias son UNA transacción, igual que enviar.
        # Medio cancelar —el pedido cancelado y sus renglones todavía en
        # tránsito— dejaría su mercancía fuera de la lista para siempre.
        parametros = {"negocio": negocio, "pedido_id": pedido_id, "quien": quien}
        with self._motor().begin() as conexion:
            fila = (
                conexion.execute(_CANCELAR_EL_PEDIDO, parametros).mappings().first()
            )
            if fila is None:
                # Cero filas es una de cuatro, y las cuatro son "no se canceló":
                # no existe en este negocio, es un borrador, ya estaba
                # cancelado, o algo suyo ya se recibió.
                return None
            soltados = conexion.execute(_RENGLONES_CANCELADOS, parametros).all()
        return PedidoCancelado(
            pedido=pedido_desde_columnas(fila),
            renglones=tuple(int(f[0]) for f in soltados),
        )

    def devolver_el_atrasado(
        self,
        negocio: str,
        renglon_id: int,
        quien: str,
        enviado_antes_de: dt.datetime,
    ) -> RenglonGuardado | None:
        with self._motor().begin() as conexion:
            movido = (
                conexion.execute(
                    _DEVOLVER_EL_ATRASADO,
                    {
                        "negocio": negocio,
                        "renglon_id": renglon_id,
                        "quien": quien,
                        "enviado_antes_de": enviado_antes_de,
                    },
                )
                .mappings()
                .first()
            )
            if movido is None:
                return None
            # Se relee DENTRO de la transacción: lo que vuelve es el renglón
            # después del cambio, con su firma.
            fila = (
                conexion.execute(
                    _LEER_RENGLON_POR_ID,
                    {"negocio": negocio, "renglon_id": renglon_id},
                )
                .mappings()
                .first()
            )
        return None if fila is None else renglon_guardado_desde_columnas(fila)

    def marcar_capturado(
        self, negocio: str, renglon_id: int, capturado: bool, quien: str
    ) -> PedidoSugeridoGuardado | None:
        # Por `_mover_el_renglon`, como descartar y ajustar: el `UPDATE` y la
        # relectura de la lista en una sola transacción, y cero filas es
        # `None`. `quien` solo viaja al tachar: destachar no firma nada.
        if capturado:
            return self._mover_el_renglon(
                _MARCAR_CAPTURADO,
                {"negocio": negocio, "renglon_id": renglon_id, "quien": quien},
            )
        return self._mover_el_renglon(
            _DESMARCAR_CAPTURADO, {"negocio": negocio, "renglon_id": renglon_id}
        )

    def guardar_la_corrida(self, negocio: str, corrida: CorridaDelLote) -> int:
        columnas = columnas_de_la_corrida(corrida, negocio)
        # Se revisa antes de escribir, igual que el precio: el `final` decide
        # qué frase le pone la pantalla a cada renglón sin lectura, y un valor
        # fuera del vocabulario se leería como "el lote no corrió".
        revisar_la_corrida(columnas)
        with self._motor().begin() as conexion:
            fila = (
                conexion.execute(_GUARDAR_CORRIDA, columnas).mappings().first()
            )
        return 0 if fila is None else int(fila["corrida_del_lote_id"])

    def ultima_corrida(
        self, negocio: str, pedido_sugerido_id: int
    ) -> CorridaDelLote | None:
        with self._motor().connect() as conexion:
            fila = (
                conexion.execute(
                    _ULTIMA_CORRIDA,
                    {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                    },
                )
                .mappings()
                .first()
            )
        return None if fila is None else corrida_desde_columnas(fila)

    def _mover_el_renglon(self, sentencia, parametros: dict):
        """El `UPDATE` de un renglón y la relectura de su lista, en una transacción.

        Las tres operaciones sobre un renglón —descartar, devolver y corregir la
        cantidad— comparten esto entero y solo cambian de sentencia: la
        transición está en el `WHERE` de cada una, así que aquí no hay un solo
        `if` sobre el estado — cero filas es "no había nada que mover" y sale
        como `None`.

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
        renglones=tuple(renglon_guardado_desde_columnas(f) for f in filas),
    )


def renglon_guardado_desde_columnas(fila) -> RenglonGuardado:
    """Una fila de `pedidos.renglon` → el renglón guardado, entero.

    Sale de dentro de `armar_guardado` con el ticket 12, que estrenó la lectura
    de un renglón suelto (`leer_renglon`): dos caminos que arman el mismo objeto
    con dos códigos distintos se separan a la tercera columna nueva, y el que
    menos se usa es el que se queda viejo.
    """
    return RenglonGuardado(
        renglon_id=int(fila["renglon_id"]),
        estado=fila["estado"],
        propuesto=renglon_desde_columnas(fila),
        descartado_por=fila["descartado_por"],
        descartado_en=fila["descartado_en"],
        # `int(...)` en el borde, igual que el resto: Postgres devuelve
        # `integer` como `int`, pero el día que la columna cambie de tipo esto
        # no se entera a medias.
        cantidad_final=(
            None if fila["cantidad_final"] is None else int(fila["cantidad_final"])
        ),
        ajustada_por=fila["ajustada_por"],
        ajustada_en=fila["ajustada_en"],
        # Las cuatro del ticket 20, con `.get` y no `[...]`: una base a la que
        # todavía no se le corrió la migración 0005 no las trae, y lo correcto
        # entonces es "nadie eligió y nadie repartió" en vez de un KeyError que
        # tumbe la lista entera por una columna que falta. Es el mismo criterio
        # con el que `verificar.py` lee `select *` de `pedidos.pedido` en vez de
        # nombrar columnas que quizá no existan.
        pedido_id=(
            None if fila.get("pedido_id") is None else int(fila["pedido_id"])
        ),
        proveedor_elegido=fila.get("proveedor_elegido"),
        elegido_por=fila.get("elegido_por"),
        elegido_en=fila.get("elegido_en"),
        # Las dos del ticket 22, con `.get` por la misma razón: sin la
        # migración 0007 es "nadie tachó", no un KeyError.
        capturado_por=fila.get("capturado_por"),
        capturado_en=fila.get("capturado_en"),
        # Las dos del ticket 25, con `.get` por la misma razón: sin la
        # migración 0009 es "nadie lo canceló", no un KeyError.
        cancelado_por=fila.get("cancelado_por"),
        cancelado_en=fila.get("cancelado_en"),
    )


def lo_ya_pedido_desde_columnas(fila) -> LoYaPedido:
    """Una fila de `_LO_YA_PEDIDO` → `LoYaPedido`. La usan Postgres y el doble.

    El renglón se arma con `renglon_guardado_desde_columnas`, **el mismo** que
    arma la lista: dos caminos que arman el mismo objeto se separan a la
    tercera columna nueva.
    """
    return LoYaPedido(
        renglon=renglon_guardado_desde_columnas(fila),
        pedido_sugerido_id=int(fila["pedido_sugerido_id"]),
        fecha_del_pedido=fila["fecha_del_pedido"],
        ventas_hasta=fila["ventas_consideradas_hasta"],
        proveedor=fila["proveedor"],
        enviado_por=fila["enviado_por"],
        enviado_en=fila["enviado_en"],
        # Las dos del ticket 25: desde cuándo vuelve lo cancelado, y si fue el
        # pedido entero o el renglón solo.
        ventas_desde_la_lista=fila.get("ventas_consideradas_desde"),
        estado_del_pedido=fila.get("estado_del_pedido"),
    )
