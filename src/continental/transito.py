"""En tránsito: la memoria de lo ya pedido (ticket 24, ADR 0012).

**Funciones puras y nada más.** Entran renglones ya pedidos, ventas, una
ventana y un `ahora`, y salen qué producto se queda fuera de la lista, desde
qué día vuelve el que ya llegó, cuánto se ha vendido de lo que viene en camino
y las frases que lo dicen. No abre una conexión, no lee el YAML y **no mira el
reloj**: el `ahora` entra por argumento, igual que en `consultas.py` y en el
lote.

## Lo que arregla

Si el lunes se piden 3 piezas y llegan el jueves, mientras tanto el producto
sigue vendido y con existencia baja, y la lista lo vuelve a proponer. El caso
más directo ni siquiera necesita una venta nueva: una lista que se envió y no se
cerró deja el corte donde estaba (ticket 09), así que la siguiente vuelve a
recoger sus mismos días — y lo que ya se le pidió a NADRO se propone otra vez,
sumado en el mismo número por renglón, sin que se vea.

## La decisión cara: dónde queda lo que se vende mientras tanto

El glosario dice que un renglón en tránsito **no se vuelve a proponer**. Si solo
se filtrara, sus ventas se perderían en cuanto la lista de ese día se cerrara:
el corte avanza encima de ellas y ninguna lista posterior las vuelve a mirar.

Lo que se hizo (ADR 0012, con las cinco alternativas que se descartaron): **la
venta se queda en `marts.fct_ventas`, que es donde ya estaba, y lo que se
recuerda es el ancla** — el último día de ventas que repuso el renglón en
tránsito, que es la `ventas_consideradas_hasta` de su lista y existe desde el
ticket 08. Mientras viene en camino, el producto no se propone. **En cuanto el
renglón se cierra** —`recibido` o `recibido parcial`, los estados de los
tickets 26 y 27—, la siguiente lista lo lee **desde el día siguiente al ancla**,
aunque el corte de la lista haya avanzado encima.

Nada de esto escribe una venta en ninguna parte, y por eso tampoco envejece: las
que llegan tarde —el sábado llega el lunes en la noche— se leen igual que las
demás la próxima vez que alguien arme una lista.

## La hora

`enviado_en` es un instante con zona y el contenedor corre en UTC: un envío del
martes a las 20:00 son las 02:00 del miércoles en UTC. El día de la semana se
calcula **en la zona de la farmacia**, fija (`ZONA_DE_LA_FARMACIA`).

Y aquí sí se compara contra el reloj, sin contradecir la regla del repo: la
regla es que las **fechas de venta** salen de `max(fecha)` y nunca de
`current_date`. Esto compara un **instante** —cuándo alguien apretó "Enviar"—
contra otro instante —ahora—, que es exactamente lo que un reloj sabe. Contra
`max(fecha)` saldría mal: los lunes, la última venta es del sábado y un pedido
de esa mañana saldría "enviado en el futuro".

## La válvula de escape (ticket 25, ADR 0013)

Un renglón en tránsito que nunca llega se quedaría fuera de la lista para
siempre. Dos salidas, las dos firmadas y las dos con el mismo destino:

- **Atrasado** —lleva **más** de N días en camino, N en
  `config/continental.yml`— es una **señal calculada**, no un estado: se
  deduce del instante del envío cada vez que se mira, y no se guarda. Se llama
  así y no "vencido" porque `vencido` ya es un estado de la **lista** en el
  glosario. Lo atrasado se puede **devolver a la lista** uno por uno.
- **Cancelar un pedido** que nunca se capturó en el portal.

En los dos casos el renglón pasa a `cancelado` —no a `abierto`: su lista casi
siempre está cerrada y no se deja modificar— y **lo que vuelve es el producto,
en la siguiente lista**, desde el principio de lo que ese renglón cubría:
nunca se pidió, así que también vuelve lo que repuso. Es la misma memoria del
ticket 24, con otro "desde" (`LoYaPedido.retiene_desde`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from continental.almacen import LineaDeVenta

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    # `almacenamiento` importa `sugerido`, y `sugerido.armar_la_lista` recibe
    # una `MemoriaDeLoPedido`: importarlo aquí de verdad cerraría el ciclo. Lo
    # que este módulo usa de `LoYaPedido` son sus propiedades, que no hace
    # falta importar para llamar.
    from continental.almacenamiento import LoYaPedido, Ventana

#: La hora del centro de México: **UTC-6 fijo**, sin horario de verano.
#:
#: México quitó el horario de verano el 30 de octubre de 2022 (Ley de los
#: Sistemas de Horario), así que para la zona centro el desfase es el mismo
#: todo el año. Fijo y no `ZoneInfo("America/Mexico_City")`: la torre no tiene
#: `tzdata` —lo midió el ticket 23— y ahí un `ZoneInfo` truena. Es la misma
#: cifra que la pantalla ya da por buena ("aquí el reloj va en UTC-6").
ZONA_DE_LA_FARMACIA = dt.timezone(dt.timedelta(hours=-6), "hora del centro")

#: A partir de cuántos días el día de la semana solo ya no alcanza. En seis días
#: cada día de la semana aparece una sola vez, así que "el martes" no se puede
#: confundir; al séptimo, "el martes" es también hoy. Desde ahí va la fecha y
#: cuántos días lleva — que es lo que el ticket 25 compara contra su N para
#: señalar el tránsito como **atrasado** (no "vencido": ése es de la lista).
DIAS_CON_NOMBRE = 7

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

#: **La quinta casilla, con todas sus letras.** Viaja siempre con el bloque de
#: lo que viene en camino, también cuando no viene nada: es cuando más se
#: necesita, porque un bloque vacío se lee "no hay nada pedido" y puede ser que
#: sí lo haya, capturado sin pasar por aquí.
ADVERTENCIA_DE_LO_QUE_PROTEGE = (
    "Esto solo sabe de lo que se envió desde Continental. Un pedido que se "
    "capturó en el portal por fuera, sin marcarlo como enviado aquí, no aparece "
    "en camino, y su mercancía se va a proponer otra vez."
)


# ----------------------------------------------------------- la memoria


@dataclass(frozen=True)
class MemoriaDeLoPedido:
    """Lo que la lista del día tiene que saber de lo que ya se pidió.

    Son dos mapas por producto, y un producto está como mucho en uno:

    - `en_camino` — el renglón en tránsito más reciente de ese producto. El
      producto **no se propone**: todas sus ventas se quedan fuera de la lista.
    - `desde` — el producto ya llegó y lo que se vendió mientras venía todavía
      no se propuso. Sus ventas se cuentan **desde ese día**, esté antes o
      después del principio de la ventana.

    Vacía, es exactamente la lista del ticket 09: recorta la ventana y nada
    más. Así la construye quien de verdad no tiene nada pedido.
    """

    en_camino: Mapping[int, "LoYaPedido"] = field(default_factory=dict)
    desde: Mapping[int, dt.date] = field(default_factory=dict)

    def esta_en_camino(self, producto_id: int) -> bool:
        return producto_id in self.en_camino

    def desde_de_la_lectura(self, ventana: "Ventana") -> dt.date:
        """Desde qué día hay que leer ventas para que quepa lo que vuelve.

        El `min` con el principio de la ventana: lo que vuelve casi siempre
        empieza antes —se vendió mientras venía en camino— y la lectura sigue
        siendo **una**, igual que desde el ticket 09.
        """
        return min((ventana.desde, *self.desde.values()))

    def ventas_desde(self, producto_id: int, ventana: "Ventana") -> dt.date | None:
        """El principio propio de ese producto, o `None` si es el de la ventana.

        `None` también cuando coinciden: el renglón solo lo anota si dice algo
        que la lista no dice ya.
        """
        propio = self.desde.get(producto_id)
        return None if propio is None or propio == ventana.desde else propio

    def recortar(
        self, ventas: Iterable[LineaDeVenta], ventana: "Ventana"
    ) -> list[LineaDeVenta]:
        """Las ventas que se reponen: la ventana, menos lo que viene en camino,
        más lo que vuelve.

        Para cada producto, **un solo intervalo** que termina en el `hasta` de
        la ventana: el de la ventana, el suyo propio, o ninguno si viene en
        camino. Nunca dos intervalos del mismo producto — eso sumaría días que
        ya se pidieron.
        """
        recortadas = []
        for venta in ventas:
            if venta.producto_id in self.en_camino:
                continue
            desde = self.desde.get(venta.producto_id, ventana.desde)
            if desde <= venta.fecha <= ventana.hasta:
                recortadas.append(venta)
        return recortadas


def memoria_de_lo_pedido(ya_pedidos: Iterable["LoYaPedido"]) -> MemoriaDeLoPedido:
    """Lo ya pedido → la memoria con la que se arma la lista.

    **Lo que viene en camino le gana a lo que ya llegó**: si un producto se
    pidió, llegó y se volvió a pedir, el último pedido manda y el producto sigue
    fuera. Entre dos del mismo tipo manda el ancla más reciente.

    **Lo cancelado cuenta como "ya no viene"** (ticket 25): su producto vuelve,
    desde el principio de lo que cubría. `lo_ya_pedido` ya se encarga de que no
    lleguen aquí dos filas que vuelvan del mismo producto —la de después
    atiende a la de antes—; si llegaran, manda la más reciente, igual que con
    dos recibidos.

    Un renglón que no está ni en tránsito ni en un estado que lo cierre —un
    `abierto` o un `descartado` que alguien pasara por error— **no entra**: la
    memoria solo puede sacar de la lista lo que de verdad se le pidió a alguien.
    """
    en_camino: dict[int, LoYaPedido] = {}
    llegados: dict[int, LoYaPedido] = {}
    for ya in ya_pedidos:
        if ya.esta_en_transito:
            destino = en_camino
        elif ya.vuelve_a_proponerse:
            # Llegó, o se canceló (ticket 25). Los dos vuelven, y la diferencia
            # —desde cuándo— la dice `retiene_desde`, no esta función.
            destino = llegados
        else:
            continue
        anterior = destino.get(ya.producto_id)
        if anterior is None or ya.ventas_hasta >= anterior.ventas_hasta:
            destino[ya.producto_id] = ya

    return MemoriaDeLoPedido(
        en_camino=en_camino,
        desde={
            producto_id: ya.retiene_desde
            for producto_id, ya in llegados.items()
            if producto_id not in en_camino
        },
    )


def en_camino(ya_pedidos: Iterable["LoYaPedido"]) -> tuple["LoYaPedido", ...]:
    """Los que siguen en tránsito, en el orden en que llegaron: lo que se enseña.

    **Todos**, no uno por producto: si el mismo producto se pidió dos veces y
    no ha llegado ninguna, los dos se ven. Esconder uno es justo lo que la
    casilla 4 prohíbe.
    """
    return tuple(ya for ya in ya_pedidos if ya.esta_en_transito)


def vendido_desde_que_se_pidio(
    ventas: Iterable[LineaDeVenta],
    ya_pedidos: Sequence["LoYaPedido"],
    hasta: dt.date,
) -> dict[int, float]:
    """Cuánto se ha vendido de cada renglón en camino desde que se pidió.

    Indexado por `renglon_id`, no por producto: dos renglones en camino del
    mismo producto tienen dos anclas distintas. Cuenta desde el **día
    siguiente** al ancla —lo del día del ancla ya venía en el pedido— hasta
    `hasta`, el último día con ventas. Cero es cero de verdad: se leyó y no se
    vendió nada. Quien no pudo leer no llama a esto — pasa `None` a la frase.
    """
    ventas = list(ventas)
    vendido: dict[int, float] = {}
    for ya in ya_pedidos:
        vendido[ya.renglon.renglon_id] = round(
            sum(
                v.cantidad
                for v in ventas
                if v.producto_id == ya.producto_id
                and ya.retiene_desde <= v.fecha <= hasta
            ),
            3,
        )
    return vendido


# ------------------------------------------------------------- las frases
#
# Las frases que AFIRMAN algo se componen aquí, en Python y con pruebas, y no en
# el JavaScript: es la lección del ticket 15, repetida en el 21.


def _en_la_farmacia(instante: dt.datetime) -> dt.datetime:
    """El instante en la hora de la farmacia. Uno sin zona se toma como UTC.

    Sin zona es como escribe este repo lo que viene de `timestamptz` cuando un
    driver la pierde; tomarlo como hora local sería correrlo seis horas.
    """
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=dt.UTC)
    return instante.astimezone(ZONA_DE_LA_FARMACIA)


def _dia_y_fecha(fecha: dt.date, con_anio: bool = False) -> str:
    """`martes 15 de septiembre`, sin artículo, para poder decir "del" o "el"."""
    texto = f"{_DIAS[fecha.weekday()]} {fecha.day} de {_MESES[fecha.month - 1]}"
    return f"{texto} de {fecha.year}" if con_anio else texto


def fecha_en_palabras(fecha: dt.date, con_anio: bool = False) -> str:
    """`el martes 15 de septiembre`, sin depender del locale del proceso.

    A mano y no con `strftime("%A")`: eso sale en el idioma del sistema, que
    en atlas es inglés.
    """
    return f"el {_dia_y_fecha(fecha, con_anio)}"


def cuando_se_envio(enviado_en: dt.datetime | None, ahora: dt.datetime) -> str:
    """Cuándo se envió, como lo diría el encargado: hoy, ayer, el martes…

    - el mismo día → `hoy` (también si el reloj de la base va unos segundos
      adelante del de la aplicación: eso no es "en el futuro");
    - el día anterior → `ayer`;
    - de dos a seis días → el día de la semana, que en ese tramo no se repite;
    - de siete en adelante → la fecha y cuántos días lleva. "El martes" hace
      ocho días se lee como el martes de hoy.

    Los días son de **calendario en la farmacia**, no bloques de 24 horas: lo
    de anoche a las 20:00 es "ayer" a las 8:00 de hoy.
    """
    if enviado_en is None:
        return "sin fecha de envío escrita"

    dia = _en_la_farmacia(enviado_en).date()
    hoy = _en_la_farmacia(ahora).date()
    dias = (hoy - dia).days

    if dias <= 0:
        return "hoy"
    if dias == 1:
        return "ayer"
    if dias < DIAS_CON_NOMBRE:
        return f"el {_DIAS[dia.weekday()]}"
    return f"{fecha_en_palabras(dia, con_anio=dia.year != hoy.year)} (hace {dias} días)"


def frase_del_transito(
    nombre_del_proveedor: str | None, enviado_en: dt.datetime | None, ahora: dt.datetime
) -> str:
    """"Pedido el martes a NADRO, sin recibir." — la cuarta casilla."""
    a_quien = nombre_del_proveedor or "un proveedor que no quedó escrito"
    return f"Pedido {cuando_se_envio(enviado_en, ahora)} a {a_quien}, sin recibir."


def frase_de_la_firma(ya: "LoYaPedido") -> str:
    """Quién lo marcó como enviado, a qué hora de la farmacia, y de qué lista salió.

    La segunda casilla entera: *con su proveedor y la fecha en que se enviaron*.
    El proveedor ya va en `frase_del_transito`; esto es la firma (regla 3: es
    la palabra de una persona, y cuando la factura no cuadre es a quién se le
    pregunta).

    **Nació del recorrido del navegador**: el JavaScript la armaba pegándole un
    punto a una hora que ya terminaba en "a.m.", y escribía "a.m..". Es el
    mismo tropiezo del ticket 21; aquí la hora va en 24 horas y la frase se
    prueba.
    """
    lista = f"Salió de la lista del {_dia_y_fecha(ya.fecha_del_pedido)}."
    if ya.enviado_por is None and ya.enviado_en is None:
        return (
            "Nadie quedó escrito como quien lo marcó enviado, y no quedó la "
            f"hora. {lista}"
        )
    quien = ya.enviado_por or "alguien que no quedó escrito"
    if ya.enviado_en is None:
        cuando = "sin hora escrita"
    else:
        local = _en_la_farmacia(ya.enviado_en)
        cuando = f"{fecha_en_palabras(local.date())} a las {local:%H:%M}"
    return f"Lo marcó como enviado {quien} {cuando}. {lista}"


def _piezas(cantidad: float) -> str:
    """`4` y no `4.0`; `2.5` sí, porque el granel existe."""
    return f"{cantidad:g}"


def frase_de_lo_vendido(piezas: float | None) -> str:
    """La tercera casilla, dicha: lo vendido mientras viene en camino no se pierde.

    `None` es "no se pudo leer", que **no es cero** (regla 4): cero se lee "no
    hay nada que reponer después", y quizá sí lo haya.
    """
    if piezas is None:
        return "No se pudo leer cuánto se ha vendido desde que se pidió."
    if piezas == 0:
        return "No se ha vendido desde que se pidió."
    if piezas == 1:
        return (
            "Desde que se pidió se vendió 1 pieza más: no se pierde, se propone "
            "al recibirlo."
        )
    return (
        f"Desde que se pidió se vendieron {_piezas(piezas)} piezas más: no se "
        "pierden, se proponen al recibirlo."
    )


def frase_del_bloque(cuantos: int) -> str:
    """El encabezado del bloque. **Nunca calla**: cero se dice con palabras.

    Callar dejaría el silencio con dos significados —"no viene nada" y "esta
    pantalla no lo cuenta"—, que es la misma razón por la que el conteo de
    huecos del ticket 15 se escribe también en verde.
    """
    if cuantos == 0:
        return "Nada de listas anteriores viene en camino."
    if cuantos == 1:
        return (
            "1 renglón de listas anteriores viene en camino: no se vuelve a "
            "proponer hasta que se reciba."
        )
    return (
        f"{cuantos} renglones de listas anteriores vienen en camino: no se "
        "vuelven a proponer hasta que se reciban."
    )


def frase_de_la_ventana_propia(
    ventas_desde: dt.date | None, ventana: "Ventana"
) -> str | None:
    """Lo que dice el renglón cuyas ventas no empiezan donde empieza la lista.

    Es lo que mantiene verificable la reposición 1 a 1 cuando lo retenido
    vuelve: sin esto, un renglón que pide 4 en una lista de un día con una
    venta no se puede explicar mirando la pantalla.
    """
    if ventas_desde is None or ventas_desde == ventana.desde:
        return None
    if ventas_desde < ventana.desde:
        return (
            f"Trae también lo vendido desde {fecha_en_palabras(ventas_desde)}, "
            "mientras venía en camino: esas ventas no se perdieron."
        )
    return (
        f"Solo cuenta lo vendido desde {fecha_en_palabras(ventas_desde)}: lo "
        "anterior ya venía en un pedido."
    )


def frase_de_ya_en_camino(ya: "LoYaPedido", ahora: dt.datetime) -> str:
    """El aviso para un renglón **de hoy** cuyo producto ya viene en camino.

    Es el borde que la memoria no alcanza: la lista de hoy se armó antes de que
    alguien enviara el pedido de una lista vieja con ese mismo producto (el ADR
    0009 permite enviar desde una lista vencida). Lo que se muestra es lo
    guardado y no se recalcula, así que lo honesto es decirlo en el renglón.
    """
    a_quien = ya.nombre_del_proveedor or "un proveedor que no quedó escrito"
    return (
        f"Ya viene en camino: se le pidió {cuando_se_envio(ya.enviado_en, ahora)} "
        f"a {a_quien} y no ha llegado. Pedirlo aquí también sería pedirlo dos "
        "veces."
    )


# ------------------------------------------------ atrasado (ticket 25)
#
# **Atrasado no es un estado**: es lo que se deduce de comparar el instante del
# envío contra ahora. No se guarda porque cambia solo con el paso del tiempo, y
# una columna que dijera "atrasado" envejecería sin avisar igual que una
# sugerencia guardada (ticket 20). Y no se llama "vencido", que ya es de la
# lista.


def dias_en_transito(enviado_en: dt.datetime | None, ahora: dt.datetime) -> int | None:
    """Cuántos días lleva en camino: de **calendario en la farmacia**.

    Los mismos días que cuenta `cuando_se_envio`, y por la misma razón: un envío
    del lunes a las 20:30 son las 02:30 del martes en UTC, y contado en UTC el
    renglón se atrasaría un día tarde. Nunca negativo —un reloj de la base unos
    segundos adelante no es un envío del futuro— y `None` si no quedó la hora:
    no se inventa.
    """
    if enviado_en is None:
        return None
    dias = (_en_la_farmacia(ahora).date() - _en_la_farmacia(enviado_en).date()).days
    return max(dias, 0)


def esta_atrasado(dias: int | None, umbral: int | None) -> bool:
    """**Más** de `umbral` días, como dice el ticket: con N = 7, el séptimo no."""
    return dias is not None and umbral is not None and dias > umbral


def enviado_antes_de(ahora: dt.datetime, umbral: int) -> dt.datetime:
    """El instante que el `WHERE` compara: lo enviado **antes** está atrasado.

    `dias > N` ⟺ el día del envío es anterior a `hoy - N` ⟺ se envió antes de la
    **medianoche de la farmacia** de ese día. Se calcula aquí y viaja como
    parámetro a `_DEVOLVER_EL_ATRASADO`, y es a propósito: la pantalla decide
    qué ofrecer con `dias_en_transito` y la base decide qué acepta con esto, y
    una prueba recorre doce días de hora en hora para que las dos no se separen
    ni un instante. Hacer la cuenta en SQL obligaría a escribir la zona allá, y
    en Postgres `at time zone '-06'` es la convención POSIX: se lee como UTC+6.
    """
    hoy = _en_la_farmacia(ahora).date()
    dia = hoy - dt.timedelta(days=umbral)
    return dt.datetime(dia.year, dia.month, dia.day, tzinfo=ZONA_DE_LA_FARMACIA)


def _dias(cuantos: int) -> str:
    return "1 día" if cuantos == 1 else f"{cuantos} días"


def frase_del_atraso(dias: int | None, umbral: int | None) -> str | None:
    """La primera casilla, dicha: **con el número de días a la vista**.

    `None` cuando no está atrasado, o cuando no se puede saber (sin hora de
    envío o sin umbral): esos casos se dicen en otra parte, no aquí con una
    frase que afirme algo.
    """
    if not esta_atrasado(dias, umbral):
        return None
    return (
        f"Atrasado: lleva {_dias(dias)} en camino, más de {_dias(umbral)}. "
        "Si no llegó, se puede devolver a la lista."
    )


def frase_del_umbral(umbral: int) -> str:
    """Qué quiere decir "atrasado" aquí, con su número. Va arriba del bloque."""
    return (
        f"Se da por atrasado lo que lleva más de {_dias(umbral)} en camino "
        "sin recibirse."
    )


def frase_sin_umbral(detalle: str) -> str:
    """El hueco cuando el número no se pudo leer (regla 4): dice qué falta.

    Los renglones se siguen enseñando; lo que no se puede es decir cuál está
    atrasado, y eso se dice en vez de callar —callar se leería "nada está
    atrasado"—.
    """
    return (
        "No se puede decir qué está atrasado: el número de días no se pudo leer "
        f"de la configuración ({detalle}). Lo que viene en camino se ve igual."
    )


def frase_de_los_atrasados(cuantos: int, umbral: int | None) -> str | None:
    """Cuántos están atrasados, arriba del bloque. Con cero, nada que decir."""
    if not cuantos or umbral is None:
        return None
    if cuantos == 1:
        return (
            f"1 renglón lleva más de {_dias(umbral)} en camino: está atrasado."
        )
    return (
        f"{cuantos} renglones llevan más de {_dias(umbral)} en camino: están "
        "atrasados."
    )


#: Lo que cuesta equivocarse al devolver, dicho junto al botón.
#:
#: **Hasta el ticket 26 nada pasa a `recibido`**: todo lo que llegó sigue en
#: tránsito y, a los N días, se ve atrasado igual que lo que no llegó. Devolver
#: lo que sí llegó es volverlo a proponer entero — pedirlo dos veces. Y
#: Continental no cancela nada en ningún portal: si el proveedor todavía lo tiene
#: pedido, allá sigue.
ADVERTENCIA_AL_DEVOLVER = (
    "Devolver a la lista es decir que no llegó ni va a llegar: se vuelve a "
    "proponer en la siguiente lista, con todo lo que cubría. Si sí llegó, no lo "
    "devuelvas: se pediría dos veces. Y si el proveedor todavía lo tiene pedido "
    "en su portal, cancélalo allá también — Continental no cancela nada en "
    "ningún portal."
)


# --------------------------------------------------- cancelar (ticket 25)


def _renglones(cuantos: int) -> str:
    return "1 renglón" if cuantos == 1 else f"{cuantos} renglones"


def frase_para_cancelar(nombre_del_proveedor: str, renglones_en_camino: int) -> str:
    """Qué declara quien aprieta "Cancelar", en el mismo bloque del botón.

    Es el par de `particion.frase_del_envio`: enviar dice *"ya lo capturé en el
    portal"*, cancelar dice *"no está en el portal"*. Y se desmiente igual:
    Continental no cancela nada allá, igual que no captura nada.
    """
    if renglones_en_camino == 0:
        # Todo lo suyo ya se devolvió uno por uno: cancelar solo deja dicho que
        # el pedido no está en el portal. Un "sus 0 renglones" no dice nada.
        que_pasa = (
            "Ya no le queda nada en camino: cancelarlo solo deja dicho que no "
            "está en el portal."
        )
    elif renglones_en_camino == 1:
        que_pasa = (
            "Su renglón deja de estar en camino y vuelve a proponerse en la "
            "siguiente lista, con todo lo que cubría."
        )
    else:
        que_pasa = (
            f"Sus {_renglones(renglones_en_camino)} dejan de estar en camino y "
            "vuelven a proponerse en la siguiente lista, con todo lo que cubrían."
        )
    return (
        f"Cancelar es decir que este pedido no está en el portal de "
        f"{nombre_del_proveedor}: nunca se capturó, o ya se canceló allá. "
        f"Continental no cancela nada en ningún portal. {que_pasa}"
    )


def motivo_para_no_cancelar(pedido) -> str | None:
    """Por qué no se puede cancelar, o `None` si sí se puede.

    La misma decisión que el `WHERE` de `_CANCELAR_EL_PEDIDO`, y **no la
    garantía**: sirve para no pintar un botón que contestaría 409. Lo recibido
    no se mira aquí —hoy nada lo escribe— y el `WHERE` sí lo mira.
    """
    if pedido.fue_cancelado:
        return "ese pedido ya está cancelado"
    if pedido.es_borrador:
        return (
            "un borrador todavía no se le pidió a nadie: no hay nada que "
            "cancelar, se vuelve a partir"
        )
    return None


def frase_del_pedido_cancelado(nombre_del_proveedor: str, cuantos: int) -> str:
    """Lo que contesta la ruta al cancelar: qué pasó y qué NO pasó."""
    if cuantos == 0:
        soltados = "No le quedaba nada en camino."
    elif cuantos == 1:
        soltados = (
            "Su renglón dejó de estar en camino y vuelve a proponerse en la "
            "siguiente lista."
        )
    else:
        soltados = (
            f"Sus {_renglones(cuantos)} dejaron de estar en camino y vuelven a "
            "proponerse en la siguiente lista."
        )
    return (
        f"Pedido a {nombre_del_proveedor} cancelado. {soltados} Continental no "
        f"canceló nada en el portal de {nombre_del_proveedor}."
    )


def frase_del_renglon_devuelto(descripcion: str) -> str:
    """Lo que contesta la ruta al devolver un renglón atrasado a la lista."""
    return (
        f"{descripcion} se devolvió a la lista: vuelve a proponerse en la "
        "siguiente lista, con todo lo que cubría. Su pedido sigue enviado."
    )


def frase_de_los_que_vuelven(cuantos: int) -> str | None:
    """El encabezado de lo que vuelve en la siguiente lista. Con cero, calla.

    Nació del recorrido del navegador: sin encabezado, la línea de lo que vuelve
    quedaba pegada al pedido de arriba y se leía como parte de él.
    """
    if not cuantos:
        return None
    if cuantos == 1:
        return (
            "1 renglón se dejó de esperar y vuelve en la siguiente lista, con "
            "todo lo que cubría:"
        )
    return (
        f"{cuantos} renglones se dejaron de esperar y vuelven en la siguiente "
        "lista, con todo lo que cubrían:"
    )


def _firma_de_la_cancelacion(quien: str | None, cuando: dt.datetime | None) -> str:
    quien = quien or "alguien que no quedó escrito"
    if cuando is None:
        return f"{quien}, sin hora escrita"
    local = _en_la_farmacia(cuando)
    return f"{quien} {fecha_en_palabras(local.date())} a las {local:%H:%M}"


def frase_de_lo_que_vuelve(ya: "LoYaPedido") -> str:
    """Un renglón cancelado de una lista anterior: vuelve en la siguiente.

    Dice quién lo soltó y cuándo —es una firma (regla 3)— y **desde qué día
    vuelve**, que es lo que deja verificar el número de la lista siguiente:
    sin esto, "pide 9" en una lista de un día no se podría explicar.
    """
    firma = _firma_de_la_cancelacion(ya.renglon.cancelado_por, ya.renglon.cancelado_en)
    a_quien = ya.nombre_del_proveedor or "un proveedor que no quedó escrito"
    vuelve = (
        "Vuelve a proponerse en la siguiente lista, con lo vendido desde "
        f"{fecha_en_palabras(ya.retiene_desde)}."
    )
    if ya.se_cancelo_el_pedido:
        return f"Su pedido a {a_quien} se canceló: lo canceló {firma}. {vuelve}"
    return (
        f"Lo devolvió a la lista {firma}: no llegó de {a_quien}. {vuelve}"
    )


def frase_del_renglon_cancelado(renglon, pedido_cancelado: bool, nombre: str | None) -> str:
    """Un renglón cancelado de **la lista de hoy**: vuelve en la siguiente, no aquí.

    Lo que se muestra es lo guardado y no se recalcula (ADR 0012): la lista de
    hoy ya se armó sin ese producto, y volverlo a `abierto` aquí sería reabrir
    el pedido de ese proveedor en esta lista —desenviar por la puerta de atrás,
    ADR 0013—. Así que se dice dónde va a aparecer.
    """
    a_quien = nombre or "un proveedor que no quedó escrito"
    if pedido_cancelado:
        return (
            f"Su pedido a {a_quien} se canceló: no se va a recibir. Vuelve a "
            "proponerse en la siguiente lista, no en ésta."
        )
    return (
        f"Se devolvió a la lista porque no llegó de {a_quien}. Vuelve a "
        "proponerse en la siguiente lista, no en ésta."
    )


# --------------------------------------------------------------- el JSON


def en_camino_como_json(
    ya_pedidos: Sequence["LoYaPedido"],
    vendido: Mapping[int, float] | None,
    ahora: dt.datetime,
    *,
    umbral: int | None = None,
    detalle_del_umbral: str | None = None,
    vuelven: Sequence["LoYaPedido"] = (),
) -> dict:
    """El bloque de lo que viene en camino, como la pantalla lo lee.

    `vendido` es `None` cuando no se pudieron leer las ventas: entonces cada
    renglón lleva `null` y la frase lo dice, en vez de enseñar un cero.

    **Desde el ticket 25** cada renglón dice cuántos días lleva y si está
    atrasado, y el bloque trae además los pedidos que se pueden cancelar y lo
    que **vuelve** en la siguiente lista. `umbral` es el N del YAML; si no se
    pudo leer, `detalle_del_umbral` dice por qué y `atrasado` va `null` en cada
    renglón —no se sabe, que no es "no"—.

    Las frases viajan **hechas**; los datos van además, porque la pantalla los
    usa para acomodar, no para decidir.
    """
    renglones = []
    pedidos: dict[int, dict] = {}
    for ya in ya_pedidos:
        piezas = None if vendido is None else vendido.get(ya.renglon.renglon_id)
        dias = dias_en_transito(ya.enviado_en, ahora)
        atrasado = None if umbral is None else esta_atrasado(dias, umbral)
        if ya.renglon.pedido_id is not None and ya.proveedor is not None:
            grupo = pedidos.setdefault(
                ya.renglon.pedido_id,
                {
                    "pedido_id": ya.renglon.pedido_id,
                    "proveedor": ya.proveedor,
                    "nombre": ya.nombre_del_proveedor,
                    "frase": frase_del_transito(
                        ya.nombre_del_proveedor, ya.enviado_en, ahora
                    ),
                    "renglones_en_camino": 0,
                },
            )
            grupo["renglones_en_camino"] += 1
        renglones.append(
            {
                "renglon_id": ya.renglon.renglon_id,
                "producto_id": ya.producto_id,
                "clave": ya.renglon.propuesto.clave,
                "descripcion": ya.renglon.propuesto.descripcion,
                "cantidad": ya.renglon.cantidad_a_pedir,
                "proveedor": ya.proveedor,
                "nombre": ya.nombre_del_proveedor,
                "pedido_id": ya.renglon.pedido_id,
                "fecha_del_pedido": ya.fecha_del_pedido.isoformat(),
                # En ISO con zona, como toda firma de este módulo: sin ella el
                # navegador la leería como hora local.
                "enviado_en": ya.enviado_en.isoformat() if ya.enviado_en else None,
                "enviado_por": ya.enviado_por,
                "cuando": cuando_se_envio(ya.enviado_en, ahora),
                "frase": frase_del_transito(
                    ya.nombre_del_proveedor, ya.enviado_en, ahora
                ),
                "firma": frase_de_la_firma(ya),
                "vendido_desde_que_se_pidio": piezas,
                "frase_de_lo_vendido": frase_de_lo_vendido(piezas),
                # EL ATRASO (ticket 25). `atrasado` es `null` cuando no se sabe
                # —sin umbral—, nunca `false` inventado.
                "dias_en_transito": dias,
                "atrasado": atrasado,
                "frase_del_atraso": frase_del_atraso(dias, umbral),
                "se_puede_devolver": bool(atrasado),
            }
        )
    for grupo in pedidos.values():
        grupo["frase_para_cancelar"] = frase_para_cancelar(
            grupo["nombre"], grupo["renglones_en_camino"]
        )
    atrasados = sum(1 for r in renglones if r["atrasado"])
    return {
        "ok": True,
        "detalle": None,
        "frase": frase_del_bloque(len(renglones)),
        "advertencia": ADVERTENCIA_DE_LO_QUE_PROTEGE,
        "renglones": renglones,
        "umbral_del_atraso": umbral,
        "frase_del_umbral": (
            frase_del_umbral(umbral)
            if umbral is not None
            else (frase_sin_umbral(detalle_del_umbral) if detalle_del_umbral else None)
        ),
        "frase_de_los_atrasados": frase_de_los_atrasados(atrasados, umbral),
        "advertencia_al_devolver": ADVERTENCIA_AL_DEVOLVER,
        "pedidos": list(pedidos.values()),
        "frase_de_los_que_vuelven": frase_de_los_que_vuelven(len(vuelven)),
        "vuelven": [
            {
                "renglon_id": ya.renglon.renglon_id,
                "producto_id": ya.producto_id,
                "clave": ya.renglon.propuesto.clave,
                "descripcion": ya.renglon.propuesto.descripcion,
                "frase": frase_de_lo_que_vuelve(ya),
            }
            for ya in vuelven
        ],
    }


def en_camino_con_hueco(detalle: str) -> dict:
    """El bloque cuando no se pudo leer lo ya pedido: un hueco con su motivo.

    **La advertencia viaja igual**: que no se haya podido leer lo que viene en
    camino no quita que lo capturado por fuera se vaya a proponer otra vez.
    """
    return {
        "ok": False,
        "detalle": detalle,
        "frase": "No se pudo leer lo que viene en camino.",
        "advertencia": ADVERTENCIA_DE_LO_QUE_PROTEGE,
        "renglones": [],
        "umbral_del_atraso": None,
        "frase_del_umbral": None,
        "frase_de_los_atrasados": None,
        "advertencia_al_devolver": ADVERTENCIA_AL_DEVOLVER,
        "pedidos": [],
        "frase_de_los_que_vuelven": None,
        "vuelven": [],
    }
