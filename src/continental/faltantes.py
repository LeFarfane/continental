"""Por qué le falta el precio a un renglón, y cuál se puede arreglar apretando
un botón. **Funciones puras.**

No abre una conexión, no llama a Doyle, no mira el reloj y no lee un archivo:
recibe la corrida del lote —la fila de `pedidos.corrida_del_lote`, o `None` si
no hubo— y las comparaciones ya hechas, y contesta dos preguntas del ticket 19:

1. **¿Por qué este renglón no tiene ni una lectura?** Hasta el ticket 18 la
   pantalla sabía decir *"nadie lo consultó"* (ticket 15) y nada más. Eso es
   verdad y es **menos de lo que se sabe**: el lote pudo haberse cortado por
   tiempo antes de llegar a él, pudo no haber corrido, o pudo intentarlo y no
   poder. Las cuatro se arreglan distinto y por eso se dicen distinto.
2. **¿Cuáles faltan de verdad?**, que es lo que el botón de completar va a
   consultar. La respuesta de esa pregunta cuesta dinero de verdad: cada
   renglón que entre son cuatro visitas a portales ajenos, ~9 s por proveedor.

## Los tres motivos del ticket, y de dónde sale cada uno

| Motivo | Dónde vive hoy |
|---|---|
| *el portal no contestó* | `precio_de_proveedor.motivo` (ticket 12) |
| *la sesión caducó* | `precio_de_proveedor.motivo` (ticket 12) |
| *el lote se cortó por tiempo* | **de aquí**: `corrida_del_lote.final` |

Los dos primeros son de un **proveedor** de un renglón: hubo lectura y no hubo
precio. El tercero es de un **renglón entero**: no hubo lectura de nadie,
porque al lote se le acabó el tiempo antes de llegar. Son preguntas de dos
granos distintos y por eso viven en dos tablas distintas — el porqué completo,
con las dos opciones descartadas, está en el ADR 0007.

## Lo que este módulo NO puede afirmar, y lo dice

`pedidos.corrida_del_lote` guarda **cuántos** renglones quedaron sin alcanzar,
no **cuáles**. Así que el motivo de un renglón concreto se deduce del final de
la corrida, y hay una noche en la que la deducción no es segura: aquella en la
que el tope cortó **y además** hubo renglones que no se pudieron consultar
—Doyle caído a media corrida—. Ahí `seguro` viene en falso y la pantalla
escribe "probablemente" con el otro número al lado.

Decir "probablemente" es más barato que guardar miles de ids para tener razón
en un caso que además avisa de sí mismo: una noche con `no se pudo` es una
noche con Doyle caído, y eso es ruidoso por su cuenta.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from continental.almacenamiento import CorridaDelLote, RenglonGuardado
from continental.comparacion import Comparacion
from continental.precios import (
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_TIEMPO,
    explicacion_del_motivo,
)

# =========================================================================
# POR QUÉ ESTE RENGLÓN NO TIENE NI UNA LECTURA
# =========================================================================
#
# Vocabulario cerrado, como el de los motivos del precio y por la misma razón:
# viaja hasta el JavaScript de la pantalla y se cuenta. Cada uno existe porque
# **lleva a una acción distinta**; si dos se atienden igual, sobra uno.

#: El renglón no tiene EAN, así que no hay con qué buscarlo en ningún portal.
#: **Se arregla en SICAR, no aquí**, y por eso no entra al botón de completar:
#: apretarlo mil veces no le pone código de barras. Buscarlo por su nombre
#: traería el producto de otro (ADR 0002).
SIN_CLAVE_QUE_BUSCAR = "no tiene código de barras"

#: No hay ni una corrida del lote sobre esta lista. O no corrió anoche —atlas
#: apagado, el timer sin habilitar, el lote en `failed`— o la lista se armó
#: desde la pantalla y el lote todavía no ha pasado por ella.
#:
#: **Es la mitad del hilo abierto 10 que solo se veía con `journalctl`.** Hasta
#: el ticket 19, "el lote no corrió" y "el lote no llegó a este renglón" se
#: veían idénticos en la pantalla: los dos como *"nadie lo consultó"*.
EL_LOTE_NO_CORRIO = "el lote no corrió sobre esta lista"

#: Al lote se le acabó el tope antes de llegar a este renglón. **El motivo que
#: el ticket 19 pide con todas sus letras**, y el que el ticket 18 dejó sin
#: poder decir. Se arregla volviendo a consultar —el botón de completar— o
#: esperando al lote de mañana, que arranca por el mismo sitio.
EL_LOTE_SE_CORTO_POR_TIEMPO = "al lote se le acabó el tiempo"

#: La corrida se cortó a la mitad: algo la tumbó. Distinto del anterior con
#: todas sus letras —uno es el lote haciendo lo que se le pidió y el otro es
#: una falla— y por eso lo primero que hay que mirar no es el mismo sitio:
#: aquí, el journal de esa noche.
EL_LOTE_SE_INTERRUMPIO = "la corrida del lote se cortó"

#: El lote lo intentó y no dejó ni una fila: Doyle no contestó al pedir la
#: búsqueda. Es el hilo abierto 3 de `HANDOVER.md` visto desde la pantalla. Se
#: arregla levantando Doyle y volviendo a consultar.
EL_LOTE_NO_PUDO = "el lote lo intentó y no pudo"

#: El lote recorrió la lista entera, sin fallas, y este renglón sigue sin
#: lectura. Lo que eso quiere decir es que **no estaba en la lista de trabajo
#: cuando el lote corrió**: el caso ordinario es un renglón que estaba
#: `descartado` esa noche y que alguien devolvió a `abierto` después.
#:
#: No se le dice "no alcanzó el tiempo" porque el tope no tuvo nada que ver, y
#: decirlo mandaría a alguien a subir `pedido.tope_lote_minutos` por un renglón
#: que el tope nunca vio.
EL_LOTE_NO_LO_MIRO = "el lote no lo miró"

#: Los seis, del que no se arregla aquí al que casi no pasa.
MOTIVOS_DEL_HUECO: tuple[str, ...] = (
    SIN_CLAVE_QUE_BUSCAR,
    EL_LOTE_NO_CORRIO,
    EL_LOTE_SE_CORTO_POR_TIEMPO,
    EL_LOTE_SE_INTERRUMPIO,
    EL_LOTE_NO_PUDO,
    EL_LOTE_NO_LO_MIRO,
)


@dataclass(frozen=True, slots=True)
class PorQueNoHayLectura:
    """El motivo corto, la frase para una persona, y si se puede afirmar.

    Los tres juntos en un objeto y no tres valores sueltos, por lo mismo que
    `Orden` del lote: quien recibe solo el motivo supondría que es seguro, y
    quien recibe solo la frase no puede contarlo.

    `seguro` en falso **no invalida el motivo**: lo matiza. La pantalla escribe
    "probablemente" y deja el otro número a la vista, que es más honesto que
    elegir uno de los dos a cara o cruz y más útil que no decir nada.
    """

    motivo: str
    explicacion: str
    seguro: bool = True


def por_que_no_hay_lectura(
    *, tiene_clave: bool, corrida: CorridaDelLote | None
) -> PorQueNoHayLectura:
    """Un renglón sin una sola lectura + la corrida de su lista → por qué.

    **La función pura del ticket 19.** Dos argumentos, ningún borde, y la misma
    respuesta siempre: su tabla de casos se escribe entera sin Postgres.

    La tabla, en el orden en que se resuelve:

    | Situación | Motivo |
    |---|---|
    | el renglón no tiene EAN | `no tiene código de barras` |
    | no hay corrida de esta lista | `el lote no corrió sobre esta lista` |
    | la corrida se detuvo al tope | `al lote se le acabó el tiempo` |
    | la corrida se cortó | `la corrida del lote se cortó` |
    | la corrida acabó con renglones `no se pudo` | `el lote lo intentó y no pudo` |
    | la corrida recorrió todo y sin fallas | `el lote no lo miró` |

    **La clave va primero y le gana a todo lo demás**, aunque el lote haya
    corrido: un renglón sin EAN no se consultó porque no había con qué, no
    porque se acabara el tiempo, y quien lo lea tiene que ir a SICAR y no a
    apretar un botón. Es la misma negativa que da la ruta del precio desde el
    ticket 12, con la misma razón.

    `seguro` es falso **exactamente cuando la corrida tuvo renglones que no se
    pudieron consultar**: entonces hay dos maneras de haberse quedado sin
    lectura en la misma noche y de un renglón concreto no se puede decir cuál
    le tocó. Lo que se guarda es cuántos, no cuáles (ADR 0007).
    """
    if not tiene_clave:
        return PorQueNoHayLectura(
            motivo=SIN_CLAVE_QUE_BUSCAR,
            explicacion=(
                "este renglón no tiene código de barras, y el código de barras "
                "es lo único que significa lo mismo en nuestro catálogo y en el "
                "del proveedor. Ni el lote ni el botón lo consultan: se le pone "
                "la clave en SICAR."
            ),
        )

    if corrida is None:
        return PorQueNoHayLectura(
            motivo=EL_LOTE_NO_CORRIO,
            explicacion=(
                "no hay ninguna corrida del lote sobre esta lista: o no corrió "
                "(atlas apagado a las 22:00, el timer sin habilitar) o la lista "
                "se armó desde esta pantalla y el lote todavía no ha pasado. "
                "Nadie le ha pedido el precio a este renglón."
            ),
        )

    seguro = not corrida.hubo_fallas
    cuantos = f"{corrida.consultados} de {corrida.en_la_lista}"
    ademas = (
        ""
        if seguro
        else (
            f" Ojo: esa misma corrida dejó {corrida.no_se_pudo} renglón(es) "
            "que sí intentó y no pudo consultar, así que de éste no se puede "
            "afirmar cuál de los dos le tocó."
        )
    )

    if corrida.se_corto_por_tiempo:
        return PorQueNoHayLectura(
            motivo=EL_LOTE_SE_CORTO_POR_TIEMPO,
            explicacion=(
                f"el lote consultó {cuantos} renglones y se detuvo al tope de "
                f"{corrida.tope_minutos:.0f} minutos antes de llegar a éste. "
                "No es un error: detenerse es lo que se le pide. Se arregla "
                "con el botón de completar, o esperando al lote de mañana."
                + ademas
            ),
            seguro=seguro,
        )

    if corrida.se_interrumpio:
        return PorQueNoHayLectura(
            motivo=EL_LOTE_SE_INTERRUMPIO,
            explicacion=(
                f"el lote alcanzó a consultar {cuantos} renglones y la corrida "
                "se cortó antes de llegar a éste. Eso sí es una falla y está "
                "en el journal de esa noche: "
                "`journalctl -u continental-lote`." + ademas
            ),
            seguro=seguro,
        )

    if corrida.hubo_fallas:
        return PorQueNoHayLectura(
            motivo=EL_LOTE_NO_PUDO,
            explicacion=(
                f"el lote recorrió la lista entera y {corrida.no_se_pudo} "
                "renglón(es) se intentaron sin dejar ni una lectura —Doyle no "
                "contestó al pedir la búsqueda—. Éste es uno de ellos, o uno "
                "que no estaba en la lista de trabajo esa noche."
            ),
            seguro=False,
        )

    return PorQueNoHayLectura(
        motivo=EL_LOTE_NO_LO_MIRO,
        explicacion=(
            f"el lote recorrió la lista entera ({cuantos}) sin fallas, así que "
            "este renglón no estaba en ella cuando corrió: lo ordinario es que "
            "estuviera descartado esa noche y que alguien lo devolviera "
            "después. Se consulta con su botón."
        ),
    )


def frase_de_la_corrida(corrida: CorridaDelLote | None) -> str:
    """Cómo le fue al lote, en una línea, para arriba de la tabla.

    Se escribe **también cuando fue bien**, igual que el conteo del ticket 15 y
    por la misma razón: callar cuando todo salió bien dejaría el silencio con
    dos significados —"corrió y le fue bien" y "esta pantalla no lo cuenta"— y
    el encargado no puede distinguirlos. **El silencio es el modo de falla que
    de verdad muerde**, y eso vale para la pantalla igual que para Kuma.

    Cadena vacía **solo** cuando no hay corrida: ahí quien escribe es la
    pantalla, con otra frase y otro color, porque "no corrió" no es un grado de
    "corrió".
    """
    if corrida is None:
        return ""

    cuanto = corrida.segundos / 60.0
    if corrida.se_corto_por_tiempo:
        cabeza = (
            f"El lote consultó {corrida.consultados} de {corrida.en_la_lista} "
            f"renglones y se detuvo al tope de {corrida.tope_minutos:.0f} "
            "minutos. No es un error: detenerse es lo que se le pide."
        )
    elif corrida.se_interrumpio:
        cabeza = (
            f"La corrida del lote SE CORTÓ después de {corrida.consultados} de "
            f"{corrida.en_la_lista} renglones. Mira el journal de esa noche."
        )
    else:
        cabeza = (
            f"El lote consultó los {corrida.en_la_lista} renglones de la lista "
            f"en {cuanto:.0f} min."
        )

    # El singular se escribe porque pasa, y pasa seguido: una noche con UN
    # renglón que no se pudo consultar es lo ordinario cuando Doyle se cae un
    # momento. "1 no dejaron ni una lectura" se lee como una pantalla rota, y
    # una pantalla que parece rota se deja de creer justo donde este ticket
    # necesita que se le crea. Lo cazó el recorrido del navegador del
    # 2026-09-19.
    cola = []
    if corrida.no_se_pudo:
        cola.append(
            f"{corrida.no_se_pudo} "
            + ("no dejó" if corrida.no_se_pudo == 1 else "no dejaron")
            + " ni una lectura (Doyle no contestó)"
        )
    if corrida.sin_clave:
        cola.append(
            f"{corrida.sin_clave} "
            + ("no tiene" if corrida.sin_clave == 1 else "no tienen")
            + " código de barras"
        )
    # Se lee, no se recalcula: `orden_cumplido` es falso solo si la lista
    # tenía renglones y ninguno traía clase ABC (la regla vive en
    # `lote.ordenar_por_importancia`, enmienda del 2026-09-21 al ADR 0006).
    # Unos cuantos sin clase —el NULL a propósito— no llegan aquí.
    if not corrida.orden_cumplido:
        cola.append(
            "y no fue en orden de importancia por clase ABC (el motivo está "
            "en la bitácora del lote)"
        )

    return cabeza + (" " + "; ".join(cola) + "." if cola else "")


# =========================================================================
# QUÉ CUENTA COMO FALTANTE PARA EL BOTÓN DE COMPLETAR
# =========================================================================
#
# **Esta es la decisión cara del ticket**, y no por el código: cada renglón que
# entre aquí son cuatro visitas a portales ajenos con las credenciales del
# dueño, ~9 s por proveedor. Un "faltante" de más son treinta y seis segundos
# de navegador por nada.

#: Los tres motivos que **se arreglan volviendo a consultar**, y ningún otro.
#:
#: - `el portal no contestó` — se reintenta, es literalmente lo que dice su
#:   explicación.
#: - `la sesión caducó` — se abre la sesión (la otra casilla de este ticket) y
#:   se vuelve a consultar.
#: - `no alcanzó el tiempo` — se acabó el tope con ese proveedor todavía
#:   buscando; volver a preguntarle es exactamente lo que falta.
#:
#: Los otros cinco NO están, y cada ausencia es una decisión:
#:
#: - `sin resultados` y `no empareja` — el portal ya contestó y ese producto no
#:   está en ese catálogo con ese EAN. Volver a preguntar da lo mismo y cuesta
#:   nueve segundos. `no empareja` es además el final ORDINARIO de QuePharma
#:   (ADR 0002): meterlo aquí haría que el botón consultara media lista todas
#:   las veces.
#: - `varios resultados` — el EAN devolvió varias filas. Mañana devolverá las
#:   mismas; lo que hace falta es una regla, no otra visita.
#: - `precio ilegible` — el texto llegó y no se pudo leer sin adivinar. Se
#:   arregla mirando `precio_como_llego`, no repitiendo la búsqueda.
#: - `no se sabe leer la página` — Doyle está en `reconocimiento` para ese
#:   portal. Se arregla escribiendo selectores en Doyle.
MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO: tuple[str, ...] = (
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_TIEMPO,
)

#: Falta porque **no tiene ni una lectura**. Es el caso del lote que no llegó y
#: el del renglón que nadie consultó: los dos se atienden igual, preguntando.
NUNCA_SE_CONSULTO = "no tiene ni una lectura"

#: Falta porque tiene lecturas, **ninguna con precio**, y al menos un hueco de
#: los que se arreglan volviendo a preguntar.
SE_PUEDE_REINTENTAR = "se consultó, no dio precio, y se puede reintentar"

MOTIVOS_DE_FALTANTE: tuple[str, ...] = (NUNCA_SE_CONSULTO, SE_PUEDE_REINTENTAR)


@dataclass(frozen=True, slots=True)
class Faltante:
    """Un renglón que el botón de completar sí va a consultar.

    Lleva la `clave` dentro porque es con lo que se busca y quien la tiene es
    el renglón: quien recorra los faltantes no debería volver a buscarla.
    """

    renglon_id: int
    clave: str
    descripcion: str
    motivo: str


def por_que_falta(comparacion: Comparacion, *, tiene_clave: bool) -> str | None:
    """Por qué le falta el precio a este renglón, o `None` si **no le falta**.

    "Faltar" aquí no quiere decir "estar incompleto": quiere decir **que
    volver a preguntarle a los portales puede cambiar algo**. Es la definición
    que el botón necesita, porque el botón cuesta ~36 s de navegador por
    renglón, y es más estrecha que la de "sin comparar" del ticket 15 a
    propósito. Las tres diferencias, que son las tres decisiones:

    1. **Un renglón sin EAN no falta.** No hay con qué buscarlo y apretar el
       botón no le pone clave. Su hueco se arregla en SICAR y la pantalla ya lo
       dice con esas palabras.
    2. **Un renglón con AL MENOS UN precio no falta**, aunque tenga huecos
       reintentables en los otros tres proveedores. Volver a consultarlo son
       cuatro visitas —Doyle no sabe preguntarle a un proveedor suelto: su
       `POST /api/buscar` va a los cuatro— para ganar como mucho una
       cotización más, y eso es justo lo que el ticket prohíbe con
       *"sin volver a visitar portales por lo que ya tiene precio"*.
       **Lo que se renuncia:** un renglón con un solo precio —el
       `UN_SOLO_PRECIO` del ticket 15— no lo completa este botón. Sigue
       teniendo el suyo, que consulta ese renglón y nada más, y ahí el gasto lo
       decide una persona mirándolo.
    3. **Un renglón consultado cuyos huecos son todos definitivos tampoco
       falta.** `sin resultados`, `no empareja`, `varios resultados`,
       `precio ilegible` y `no se sabe leer la página` van a contestar lo mismo
       mañana. Meterlos convertiría el botón en el lote completo con otro
       nombre, que es lo que el ticket dice que NO es.
    """
    if not tiene_clave:
        return None
    if comparacion.con_precio:
        return None
    if comparacion.consultados == 0:
        return NUNCA_SE_CONSULTO
    if any(
        casilla.motivo in MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
        for casilla in comparacion.por_proveedor
    ):
        return SE_PUEDE_REINTENTAR
    return None


def elegir_los_faltantes(
    renglones: Sequence[RenglonGuardado],
    comparaciones: Mapping[int, Comparacion],
) -> tuple[Faltante, ...]:
    """Los renglones que el botón va a consultar, **en el orden de la lista**.

    Quién entra lo decide `por_que_falta`, una vez por renglón. Quién se le
    pasa lo decide quien llama, y son **los de trabajo**: un renglón descartado
    ya se atendió —alguien lo miró y decidió no pedirlo— y gastar cuatro
    visitas a portales en mercancía que nadie va a comprar es exactamente lo
    que no se quiere. Es el mismo criterio de `comparacion.contar_la_lista`.

    **El orden es el de la lista y no otro**: es el de urgencia con el que se
    armó y el que el encargado ve en la pantalla, así que si el tope corta el
    completado, corta por donde él esperaría. Reordenar aquí por clase ABC
    sería otro orden distinto al que el encargado ve, y el 55% del catálogo
    no tiene clase a propósito (NULL en `dim_producto.clase_abc` si no vendió
    en 365 días).
    """
    faltantes = []
    for renglon in renglones:
        comparacion = comparaciones.get(renglon.renglon_id)
        if comparacion is None:
            continue
        motivo = por_que_falta(
            comparacion, tiene_clave=bool(renglon.propuesto.clave)
        )
        if motivo is None:
            continue
        faltantes.append(
            Faltante(
                renglon_id=renglon.renglon_id,
                clave=renglon.propuesto.clave,
                descripcion=renglon.propuesto.descripcion,
                motivo=motivo,
            )
        )
    return tuple(faltantes)


def huecos_que_se_pueden_reintentar(
    comparacion: Comparacion,
) -> tuple[tuple[str, str], ...]:
    """Qué proveedores de este renglón tienen un hueco reintentable.

    Devuelve parejas `(proveedor, motivo)`, ordenadas como vienen en la fila.
    La pantalla las usa para dos cosas distintas: saber a quién le caducó la
    sesión —y ofrecer el botón que la abre, que es otra casilla de este
    ticket— y explicar por qué un renglón con precio sigue teniendo huecos que
    el botón de completar **no** va a atender.
    """
    return tuple(
        (casilla.proveedor, casilla.motivo)
        for casilla in comparacion.por_proveedor
        if casilla.motivo in MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
    )


def proveedores_con_sesion_caducada(
    comparaciones: Sequence[Comparacion],
) -> tuple[str, ...]:
    """Los proveedores cuya sesión caducó **en alguna lectura de esta lista**.

    Es lo que decide si la pantalla ofrece el botón de abrir sesión y para
    quién. Sale de las lecturas congeladas y no de `GET /api/sesiones` de
    Doyle, y eso es deliberado: el `guardada` de Doyle **no quiere decir que la
    sesión sirva** —el marcador solo dice que alguien confirmó una alguna vez,
    y el 2026-09-19 los cuatro decían `guardada` con las cuatro caducadas—. Lo
    que sí lo demuestra es un portal que mandó al login, y eso es exactamente
    el motivo `la sesión caducó`.
    """
    caducadas: list[str] = []
    for comparacion in comparaciones:
        for casilla in comparacion.por_proveedor:
            if casilla.motivo == SESION_CADUCADA and casilla.proveedor not in caducadas:
                caducadas.append(casilla.proveedor)
    return tuple(sorted(caducadas))


def hueco_como_json(porque: PorQueNoHayLectura) -> dict:
    """El motivo del hueco como la pantalla lo lee. Vive aquí y no en el JS.

    Las tres cosas viajan: el motivo corto —el que se cuenta y el que
    identifica el caso—, la frase larga para una persona, y si se puede
    afirmar. La pantalla escribe la frase tal cual y **no elige entre
    literales suyos**: es exactamente el error que el ticket 15 arregló con la
    certeza del ganador, y que estaba en el único archivo que ninguna prueba de
    Python mira.
    """
    return {
        "motivo": porque.motivo,
        "explicacion": porque.explicacion,
        "seguro": porque.seguro,
    }


def faltantes_como_json(faltantes: Sequence[Faltante]) -> dict:
    """Los faltantes como la pantalla los lee: el total y sus ids.

    El total va aparte de la lista aunque se pueda contar, por lo mismo que
    `descartados` en la carga de la lista: es el número que el botón escribe en
    su etiqueta, y un conteo que el navegador lleve a mano se separa de la
    verdad en cuanto hay dos pestañas abiertas en el mostrador.
    """
    return {
        "cuantos": len(faltantes),
        "renglones": [
            {
                "renglon_id": f.renglon_id,
                "clave": f.clave,
                "descripcion": f.descripcion,
                "motivo": f.motivo,
                # La explicación del motivo del hueco NO viaja aquí: la de cada
                # renglón ya va dentro del renglón. Esto es la cola de trabajo
                # del botón, no una segunda manera de contar lo mismo.
            }
            for f in faltantes
        ],
        "sin_consultar": sum(1 for f in faltantes if f.motivo == NUNCA_SE_CONSULTO),
        "reintentables": sum(
            1 for f in faltantes if f.motivo == SE_PUEDE_REINTENTAR
        ),
        # Qué quiere decir cada uno de los tres motivos que SÍ se reintentan,
        # dicho para una persona. Viaja aquí y no se escribe en el JavaScript
        # por lo mismo que la certeza del ganador del ticket 15: la pantalla
        # tiene que poder explicar por qué el botón va a consultar unos
        # renglones y no otros, y esa explicación no puede vivir en el único
        # archivo que ninguna prueba de Python mira.
        #
        # A quién le caducó la sesión NO se cuenta aquí: es de un proveedor,
        # no de un renglón, y viaja por su cuenta —`sesiones_caducadas` en la
        # carga de la lista, `huecos_reintentables` dentro de cada renglón—.
        # Un número de renglones no dice a qué portal hay que entrar.
        "explicacion_de_los_motivos": {
            motivo: explicacion_del_motivo(motivo)
            for motivo in MOTIVOS_QUE_SE_ARREGLAN_REINTENTANDO
        },
    }
