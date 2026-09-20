"""El lote nocturno de precios: que en la mañana la lista ya los traiga.

    python -m continental.lote

Corre una vez, sin nadie mirando, después de la cadena de las 20:30 de
farmacia-data. Arma la lista del día si no existe, le pide a Doyle el precio de
cada renglón **en orden de importancia**, y **se detiene a los 60 minutos**.
Lo que no alcanzó queda marcado como *faltante por tope*, que no es un error.

## Las tres mitades, y por qué están separadas

Es la misma división que el ticket 17 le dio al verificador, por la misma
razón: lo que se puede probar sin Postgres y sin red hay que poder probarlo.

- **Puro**: `ordenar_por_importancia`, `Cronometro`, `contar_los_motivos` y
  `ResumenDeLaCorrida.como_texto`. Reciben listas y devuelven objetos
  congelados. No abren una conexión, no llaman a Doyle y **no miran el reloj**
  —el reloj entra por argumento—. Ésas son las que prueba `tests/test_lote.py`.
- **Orquestación**: `correr_el_lote`. Habla con los tres bordes y no decide
  nada que no esté arriba. Se prueba igual, contra los dobles, porque los tres
  bordes entran por argumento.
- **Arranque**: `main`. Construye los bordes de verdad y es lo único que lee
  `.env`. No se prueba, y por eso no tiene ni una decisión dentro.

## El tope de 60 minutos, que es de lo que va el ticket

El número vive en `config/continental.yml` (`pedido.tope_lote_minutos`) con su
comentario, no en una constante de Python: es una decisión de operación —cuánto
se le permite al lote molestar a los portales del dueño de noche— y el día que
el dueño lo cambie no debería haber que tocar código.

**Se mira ANTES de arrancar cada renglón y no en medio de uno.** Cortar una
consulta a la mitad dejaría a Doyle con cuatro navegadores abiertos y la fila a
medio escribir; además, una búsqueda que ya costó ~9 s por proveedor es
justamente lo que no hay que tirar. Así que el tope es "no empiezo otro", y el
lote puede pasarse del minuto 60 por lo que tarde el renglón que ya estaba en
curso. Eso está medido y acotado: el tope por consulta son 120 s
(`pedido.consulta_de_precio.tope_seg`), así que el desbordamiento máximo es de
dos minutos sobre sesenta.

**Y el reloj entra por argumento** (`ahora`), igual que en `consultas.py`. Es
lo que hace que la prueba de una corrida de sesenta minutos cueste
microsegundos: el suite pasa un reloj que avanza cuando alguien duerme. Una
prueba de este módulo que tardara segundos estaría midiendo `time.monotonic`.

Es un reloj **monótono** y no la hora del día, por lo mismo que allá: lo que se
mide es cuánto tiempo ha pasado, y `datetime.now()` puede saltar hacia atrás si
el servidor ajusta su hora — con un salto de un minuto, el tope se cumpliría
solo o no se cumpliría nunca.

## Lo que NO hace este módulo, dicho para que nadie lo busque aquí

**No abre un navegador ni sabe qué es un portal** (regla 1 de `CLAUDE.md`). Le
pide a Doyle por HTTP y Doyle hace el resto. Por eso la casilla del ticket que
dice *"reutiliza el navegador por proveedor en vez de arrancar uno por
consulta"* **no se cierra aquí**: eso es el ADR 0008 de Doyle y vive en el otro
repo. Lo único que a Continental le toca de esa casilla es no pedirle a Doyle
cuatro búsquedas a la vez — y no se las pide: este lote es **estrictamente
secuencial**, un renglón tras otro, y por eso Doyle puede reutilizar lo que
tenga abierto. Un lote concurrente sería justo lo que impediría esa reutilización.

**No duerme entre renglones.** La cortesía entre productos la aplica Doyle
dentro de su búsqueda (3 s medidos, ver `consultas.py`), y agregarle aquí otra
espera sería cortesía contada dos veces: gastaría del tope de 60 minutos sin
que ningún portal lo notara.

**No borra ni corrige nada de la lista.** Lo único que escribe son filas
nuevas en `pedidos.precio_de_proveedor` —la tabla que solo crece del ADR
0004—, **una fila en `pedidos.corrida_del_lote`** —la del ticket 19, ADR
0007, también de las que solo crecen— más la lista del día si no existía. No
hay un solo `UPDATE` de renglón aquí, y por eso un lote que muera a la mitad
deja la lista exactamente como estaba más los precios que alcanzó a traer:
nunca peor.

## Lo que deja dicho al terminar, y por qué son tres sitios y no uno

Las tres salen del **mismo** `ResumenDeLaCorrida`, en el mismo `finally`, y
cada una contesta una pregunta que las otras no pueden:

| Dónde | Quién lo lee | Lo que puede decir que las otras no |
|---|---|---|
| el journal de systemd | una persona, por `ssh` | el relato renglón por renglón, **y deja rastro aunque lo que se cayera fuera Postgres** |
| `pedidos.corrida_del_lote` | la pantalla, por SQL | *"el lote consultó 210 de 380 y se detuvo al tope"*, a la mañana y sin `ssh` |
| el *push monitor* de Uptime Kuma | el dueño, sin pedirlo | **que no hubo corrida**, que es lo único que ninguna de las dos de arriba puede decir: una noche sin lote no escribe nada en ningún sitio |

Ninguna de las dos últimas puede tumbar la corrida. *"Marcar como rota una
corrida buena es peor que perderse un latido."*
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from continental.almacen import CLASES_ABC, SIN_CLASE_ABC, LecturaDelAlmacen, Producto
from continental.almacenamiento import (
    FINALES_DE_LA_CORRIDA,
    SE_ACABO_EL_TIEMPO,
    SE_INTERRUMPIO,
    SIN_LISTA,
    TERMINO,
    AlmacenamientoDelPedido,
    CorridaDelLote,
    PedidoSugeridoGuardado,
    RenglonGuardado,
    dias_primera_vez_configurados,
    ventana_de_reposicion,
)
from continental.clasificacion import reglas_configuradas
from continental.consultas import (
    GUARDADA,
    RegistroDeConsultas,
    ajustes_de_la_consulta,
    consultar_y_congelar,
)
from continental.doyle import ClienteDeDoyle
from continental.latido import ABAJO, ARRIBA, ResultadoDelLatido, mandar_el_latido
from continental.precios import SIN_TIEMPO, explicacion_del_motivo
from continental.sugerido import armar_la_lista

log = logging.getLogger("continental")


# =========================================================================
# EL VOCABULARIO
# =========================================================================

#: Cuánto puede durar el lote si el YAML no lo dice. Sesenta minutos es lo que
#: pide el ticket 18 y lo que `config/continental.yml` trae escrito con su
#: comentario; esto es el suelo para el caso en que el archivo llegue a medias.
TOPE_POR_OMISION_MIN = 60.0

# ------------------------------------------------ cómo acaba una corrida
#
# **Los cuatro se REEXPORTAN desde `almacenamiento.py`, no se definen aquí**, y
# la mudanza es del ticket 19. Hasta el 18 vivían en este archivo, que es donde
# se escriben; desde que la corrida se guarda en `pedidos.corrida_del_lote`
# (ADR 0007), **el DDL los repite en un CHECK** (`ck_corrida_final`), y lo que
# tiene CHECK vive donde está el resto del vocabulario de las tablas — junto a
# `ESTADOS_DEL_RENGLON` y `ESTADOS_DE_LA_LISTA`, y donde
# `tests/test_sql_del_pedido.py` los compara contra el archivo `.sql`.
#
# Se siguen citando desde aquí con su nombre corto, y eso es el punto de
# reexportarlos en vez de obligar a cambiar cada uso: quien lee el lote los
# encuentra donde los busca. Importarlos al revés —que `almacenamiento.py`
# importara de aquí— sería un ciclo: este módulo ya importa aquél entero.
#
# - `TERMINO` — se consultaron todos los renglones y sobró tiempo.
# - `SE_ACABO_EL_TIEMPO` — se acabaron los 60 minutos con renglones por
#   consultar. **No es un error**: es lo que el ticket 18 pide que pase, lo que
#   quedó fuera lleva el motivo `no alcanzó el tiempo`, y es el hecho del que
#   sale la frase *"el lote se cortó por tiempo"* del ticket 19.
# - `SE_INTERRUMPIO` — algo tumbó la corrida entera. Lo que ya se había
#   guardado sigue guardado.
# - `SIN_LISTA` — no hubo lista que consultar. La farmacia cierra los domingos
#   y no hay una sola venta en domingo en 33 meses: un lote que no encuentra
#   ventas no falló, y decirle `se interrumpió` haría que alguien buscara un
#   problema que no existe.

#: Los cuatro, con el nombre que este módulo usaba antes del ticket 19.
FINALES: tuple[str, ...] = FINALES_DE_LA_CORRIDA

# ------------------------------------------- cómo acaba un renglón suelto

#: Se le preguntó a Doyle y lo que contestó quedó congelado. **No quiere decir
#: "con precio"**: un renglón consultado puede acabar con cuatro huecos, cada
#: uno con su motivo, y eso es información.
CONSULTADO = "consultado"

#: El tope llegó antes que este renglón. Es *faltante por tope* y su motivo es
#: `no alcanzó el tiempo`, el mismo de `precios.py`.
SIN_ALCANZAR = "sin alcanzar"

#: Se intentó y no se pudo guardar nada: Doyle no contestó al pedir la
#: búsqueda, o el almacenamiento rebotó. Es lo que la consulta de un renglón
#: llama `sin guardar` (ticket 12).
NO_SE_PUDO = "no se pudo"

#: El renglón no tiene EAN, así que no hay con qué buscarlo. Se salta **sin
#: molestar a ningún portal** y se dice, igual que hace la pantalla: buscarlo
#: por su nombre traería el producto de otro (ADR 0002). Se arregla en SICAR,
#: no aquí.
SIN_CLAVE = "sin clave"

FINALES_DEL_RENGLON: tuple[str, ...] = (
    CONSULTADO,
    SIN_ALCANZAR,
    NO_SE_PUDO,
    SIN_CLAVE,
)


# =========================================================================
# PURO — EL ORDEN DE IMPORTANCIA
# =========================================================================
#
# **Esta parte está BLOQUEADA por fuera y el código lo dice en vez de
# disimularlo.** El orden que el ticket 18 pide es por clase ABC del catálogo,
# y `marts.dim_producto` no tiene esa columna: el ADR 0018 de farmacia-data
# está aceptado y sin implementar (verificado el 2026-09-19 — `clase_abc` no
# aparece en un solo modelo de dbt).
#
# Lo que se construyó hoy es la función entera, probada con dobles que sí
# traen clase. Lo que no se puede hacer hoy es LEERLA, y por eso
# `ordenar_por_importancia` devuelve, además del orden, **si ese orden es el
# que el ticket pidió**. Cuando no lo es, el lote lo escribe en la bitácora
# con todas sus letras y la casilla del ticket se queda sin marcar.
#
# Lo que NO se hizo, a propósito: inventar un orden alterno y llamarlo
# cumplido. El ADR 0018 consideró exactamente eso —su opción 2, "que
# Continental ordene por la utilidad de la ventana"— y lo descartó con su
# razón escrita: *"deja el orden de un módulo de compras dependiendo de la
# utilidad de siete días, que en un producto de rotación lenta es ruido"*.
# Implementarlo aquí sería reabrir un ADR por la puerta de atrás.

#: Cuánto pesa cada clase al ordenar: A primero, luego B, luego C.
PESO_DE_LA_CLASE: dict[str, int] = {
    clase: posicion for posicion, clase in enumerate(CLASES_ABC)
}

#: Dónde va lo que no tiene clase conocida: **al final**, detrás de la C.
#:
#: La dirección no es casual y es la misma que `sugerido._urgencia` le da a la
#: cobertura desconocida: un "no sé" arriba se leería como una importancia que
#: nadie midió, y se llevaría los primeros minutos del lote por delante de
#: productos que sí se sabe que pesan. Abajo sigue estando en la lista,
#: contado y dicho.
PESO_SIN_CLASE = len(CLASES_ABC)


@dataclass(frozen=True, slots=True)
class Orden:
    """Los renglones ordenados **y si ese orden es el que el ticket pidió**.

    Las dos cosas van juntas en un solo objeto a propósito. Devolver nada más
    la lista ordenada dejaría que quien la recibe supusiera que se cumplió el
    orden por clase ABC, que es justo lo que hoy no pasa; y devolver solo el
    booleano obligaría a ordenar dos veces.

    `cumple_el_orden` es **falso mientras un solo renglón no tenga clase**, y
    no "falso solo si no la tiene ninguno". Es estricto en la dirección segura:
    media lista ordenada por importancia y media al azar no es el orden que el
    ADR 0018 describe, y decir que sí lo es sería exactamente el "no falla y no
    avisa" que este repo persigue.
    """

    renglones: tuple[RenglonGuardado, ...]
    cumple_el_orden: bool
    motivo: str
    con_clase: int
    sin_clase: int

    @property
    def cuantos(self) -> int:
        return len(self.renglones)


def clases_del_catalogo(catalogo: Sequence[Producto]) -> dict[int, str]:
    """`producto_id` → su clase ABC, **solo de los que la tienen**.

    Función pura sobre el catálogo ya leído. Los que no la tienen no entran al
    diccionario en vez de entrar con cadena vacía: "no está" y "está vacío"
    querrían decir lo mismo, y tener dos maneras de decirlo invita a que
    alguien compruebe solo una — es el mismo criterio de
    `precios_de_la_lista`.

    Hoy devuelve el diccionario **vacío** para las 3,429 filas, porque la
    columna no existe y `Producto.clase_abc` vale `SIN_CLASE_ABC` en todas.
    """
    return {
        p.producto_id: p.clase_abc for p in catalogo if p.clase_abc in CLASES_ABC
    }


def ordenar_por_importancia(
    renglones: Sequence[RenglonGuardado],
    clase_por_producto: Mapping[int, str] | None = None,
) -> Orden:
    """Los renglones de la lista + su clase ABC → el orden en que se consultan.

    **La función pura del ticket 18.** No abre una conexión, no llama a Doyle,
    no lee un archivo y no mira el reloj: los mismos dos argumentos dan siempre
    el mismo orden, y por eso su tabla de casos se escribe entera sin Postgres
    (`tests/test_lote.py`).

    El orden es **A, B, C, y al final lo que no se sabe**. Dentro de cada
    grupo se respeta el orden en que venían, que es el de urgencia con el que
    la lista se armó y se guardó (`sugerido._urgencia`): agotado primero, luego
    menor cobertura. Es un ordenamiento **estable**, y eso es lo que hace que
    el segundo criterio no haya que volver a escribirlo aquí — ya está decidido
    y probado un módulo más abajo.

    **Nada se filtra**, igual que en toda la lista: un renglón sin clase no
    desaparece, se va al final. Un producto que se cayera del lote por no tener
    clase es mercancía que se queda sin precio sin que nadie se entere, que es
    el daño de la regla 4 de `CLAUDE.md`.

    `clase_por_producto` vacío o `None` es el caso de **hoy**: la columna
    `clase_abc` no existe en `marts.dim_producto` (ADR 0018 de farmacia-data,
    aceptado y sin implementar). Entonces esto devuelve los renglones **en el
    orden en que llegaron** —el de urgencia, que es el que la lista ya tiene y
    el que el encargado ve en la pantalla— con `cumple_el_orden` en falso y el
    motivo escrito. No es un orden inventado para tapar el hueco: es no
    reordenar nada, que es lo único honesto cuando el criterio no está.
    """
    clases = dict(clase_por_producto or {})
    renglones = tuple(renglones)

    con_clase = sum(
        1 for r in renglones if clases.get(r.propuesto.producto_id) in CLASES_ABC
    )
    sin_clase = len(renglones) - con_clase

    if not con_clase:
        return Orden(
            renglones=renglones,
            cumple_el_orden=False,
            motivo=(
                "el orden por clase ABC no se pudo cumplir: marts.dim_producto "
                "todavía no tiene la columna `clase_abc` (ADR 0018 de "
                "farmacia-data, aceptado y sin implementar). Se consulta en el "
                "orden de urgencia con el que la lista se armó, que es el que "
                "la pantalla muestra. NO es el orden que pide el ticket 18."
            ),
            con_clase=0,
            sin_clase=sin_clase,
        )

    ordenados = tuple(
        sorted(
            renglones,
            key=lambda r: PESO_DE_LA_CLASE.get(
                clases.get(r.propuesto.producto_id, SIN_CLASE_ABC), PESO_SIN_CLASE
            ),
        )
    )

    if sin_clase:
        return Orden(
            renglones=ordenados,
            cumple_el_orden=False,
            motivo=(
                f"{sin_clase} de {len(renglones)} renglones no tienen clase ABC "
                "en el catálogo y quedaron al final. El orden de esos no es el "
                "que pide el ticket 18: ponles clase en dim_producto."
            ),
            con_clase=con_clase,
            sin_clase=sin_clase,
        )

    return Orden(
        renglones=ordenados,
        cumple_el_orden=True,
        motivo="",
        con_clase=con_clase,
        sin_clase=0,
    )


# =========================================================================
# PURO — EL TOPE
# =========================================================================


@dataclass(frozen=True, slots=True)
class Cronometro:
    """Cuánto lleva el lote y si ya se pasó del tope. **Con el reloj inyectado.**

    `ahora` es un reloj **monótono** —`time.monotonic` en producción— y no la
    hora del día: lo que se mide es cuánto tiempo ha pasado.
    `datetime.now()` puede saltar hacia atrás si el servidor ajusta su hora, y
    con un salto de un minuto el tope se cumpliría solo o no se cumpliría
    nunca. Es la misma decisión, escrita con las mismas palabras, que
    `consultas.consultar_a_doyle`.

    Que entre por argumento es lo que permite probar una corrida de sesenta
    minutos en microsegundos: el suite pasa un reloj que avanza cuando alguien
    duerme. Sin esto, la única prueba posible de esta casilla sería esperar una
    hora — o sea, ninguna.
    """

    tope_seg: float
    inicio: float
    ahora: Callable[[], float]

    @classmethod
    def arrancar(
        cls, tope_seg: float, ahora: Callable[[], float] = time.monotonic
    ) -> "Cronometro":
        return cls(tope_seg=tope_seg, inicio=ahora(), ahora=ahora)

    @property
    def transcurrido(self) -> float:
        """Segundos desde que arrancó."""
        return self.ahora() - self.inicio

    @property
    def se_acabo(self) -> bool:
        """Si ya no se puede **empezar** otro renglón.

        `>=` y no `>`: con el tope en cero, el lote no consulta ni uno, que es
        lo que un cero quiere decir. Un `>` dejaría pasar exactamente un
        renglón con el tope apagado, y ése es el tipo de borde que nadie mira
        hasta que alguien pone el número en cero para detener el lote y el lote
        no se detiene.
        """
        return self.transcurrido >= self.tope_seg


def tope_del_lote_segundos() -> float:
    """El tope del lote, en segundos, sacado de `config/continental.yml`.

    La misma capa delgada que `consultas.ajustes_de_la_consulta` y
    `almacenamiento.dias_primera_vez_configurados`, por la misma razón: el
    número es una decisión de operación —cuánto se le permite al lote molestar
    de noche a los portales del dueño— y vive en el YAML versionado con su
    comentario, no en una constante de Python que se quedaría desincronizada el
    día que el dueño lo cambie.

    Un valor que falte o no sirva cae al de omisión **y se avisa**. Tronar aquí
    dejaría a la farmacia sin lote nocturno por una línea que falta en el YAML,
    y eso es peor que correrlo con sesenta minutos.
    """
    from continental.config import cargar

    crudo = cargar().pedido.get("tope_lote_minutos")
    try:
        minutos = float(crudo)
    except (TypeError, ValueError):
        minutos = 0.0

    if minutos <= 0:
        log.warning(
            "config/continental.yml no trae un `pedido.tope_lote_minutos` "
            "utilizable (%r). Se usan %g minutos. Agrégalo al YAML para que el "
            "tope sea el que el negocio quiere.",
            crudo,
            TOPE_POR_OMISION_MIN,
        )
        minutos = TOPE_POR_OMISION_MIN

    return minutos * 60.0


# =========================================================================
# PURO — EL RESUMEN QUE VA A LA BITÁCORA
# =========================================================================


@dataclass(frozen=True, slots=True)
class RenglonDelLote:
    """Cómo le fue a un renglón en la corrida. Es lo que se cuenta al final.

    No es una fila de ninguna tabla: lo que se guarda son las lecturas de
    `pedidos.precio_de_proveedor`. Esto es el relato de la noche, y existe para
    que el resumen pueda decir *cuántos consultó, cuántos quedaron sin precio y
    por qué* sin volver a preguntarle a Postgres.

    `motivos` son los de los proveedores que **no** dieron precio, del
    vocabulario cerrado de `precios.MOTIVOS`. Cerrado y no texto libre porque
    el resumen los **cuenta**, y un conteo sobre texto libre cuenta faltas de
    ortografía (ADR 0004).

    Para un renglón `sin alcanzar` el motivo es `no alcanzó el tiempo` — el que
    ya existía, no uno nuevo. Es literalmente lo que pasó: se acabó el tiempo
    con ese renglón todavía sin consultar, y la historia 31 pide distinguir eso
    de "el portal falló" con todas sus letras.
    """

    renglon_id: int
    clave: str
    descripcion: str
    clase_abc: str = SIN_CLASE_ABC
    final: str = CONSULTADO
    con_precio: int = 0
    sin_precio: int = 0
    motivos: tuple[str, ...] = ()
    detalle: str = ""

    @property
    def faltante_por_tope(self) -> bool:
        """Si a este renglón no le alcanzó el tiempo. **No es un error.**"""
        return self.final == SIN_ALCANZAR

    @property
    def se_consulto(self) -> bool:
        return self.final == CONSULTADO


def contar_los_motivos(
    renglones: Sequence[RenglonDelLote],
) -> tuple[tuple[str, int], ...]:
    """Cuántos huecos hubo de cada motivo, del más frecuente al menos.

    Función pura sobre lo que la corrida fue anotando. Es la mitad *"y por
    qué"* de la casilla de la bitácora: cuenta **huecos**, no renglones, porque
    un renglón puede tener cuatro y cada uno se arregla distinto —la sesión
    caducada la abre el encargado en dos clics, el portal caído se reintenta, y
    "no está en ese catálogo" no lo arregla nadie—.

    El desempate es alfabético y no el orden de aparición: un resumen que
    cambia de orden entre dos noches con los mismos números es un resumen que
    nadie compara.
    """
    cuenta: dict[str, int] = {}
    for renglon in renglones:
        for motivo in renglon.motivos:
            cuenta[motivo] = cuenta.get(motivo, 0) + 1
    return tuple(sorted(cuenta.items(), key=lambda par: (-par[1], par[0])))


@dataclass(frozen=True, slots=True)
class ResumenDeLaCorrida:
    """Lo que el lote deja dicho. **Es la bitácora de la corrida.**

    Congelado y con los conteos como propiedades derivadas de `renglones`: un
    resumen con contadores propios puede dejar de coincidir con su propio
    detalle, y entonces hay dos versiones de la misma noche.

    Dónde acaba esto y por qué, en una línea: se imprime al `journal` de
    systemd —`journalctl -u continental-lote`—, que es donde esta casa ya mira
    "cómo le fue anoche" (farmacia-data hace exactamente eso con
    `farmacia-diario`). El *por qué* de cada hueco, además, **ya está en una
    tabla**: `pedidos.precio_de_proveedor.motivo`, con su vocabulario cerrado y
    su `CHECK`. El razonamiento completo —y por qué NO se estrenó una tabla de
    bitácora— está en el ADR 0006.
    """

    fecha_del_pedido: dt.date | None
    pedido_sugerido_id: int | None
    final: str
    segundos: float
    tope_seg: float
    renglones: tuple[RenglonDelLote, ...] = ()
    orden: Orden | None = None
    detalle: str = ""

    # ------------------------------------------------------ los conteos

    @property
    def en_la_lista(self) -> int:
        """Renglones de trabajo que el lote tenía enfrente."""
        return len(self.renglones)

    @property
    def consultados(self) -> int:
        """Cuántos se le preguntaron a Doyle. La primera mitad de la casilla."""
        return sum(1 for r in self.renglones if r.se_consulto)

    @property
    def con_precio(self) -> int:
        """Cuántos renglones acabaron con al menos un precio de un proveedor.

        **Al menos uno y no los cuatro**: un renglón con un solo precio ya
        sirve para pedir, aunque el ticket 15 tenga razón en que "el más
        barato" ahí quiere decir "el único que contestó".
        """
        return sum(1 for r in self.renglones if r.con_precio)

    @property
    def sin_precio(self) -> int:
        """Cuántos renglones se quedaron sin un solo precio. La segunda mitad."""
        return self.en_la_lista - self.con_precio

    @property
    def sin_alcanzar(self) -> int:
        """Cuántos quedaron **faltantes por tope**. No son errores."""
        return sum(1 for r in self.renglones if r.faltante_por_tope)

    @property
    def no_se_pudo(self) -> int:
        """Cuántos se intentaron y no dejaron ni una fila guardada."""
        return sum(1 for r in self.renglones if r.final == NO_SE_PUDO)

    @property
    def intentados(self) -> int:
        """A cuántos se les fue a preguntar de verdad, salga como salga.

        No es `en_la_lista`: de ahí hay que descontar los que ni se intentaron
        —los que no tienen EAN (`sin clave`) y los que no alcanzaron el tope—.
        Es el denominador de la única pregunta que distingue "el lote corrió y
        los portales fallaron" de "el lote no pudo preguntarle a nadie".
        """
        return self.consultados + self.no_se_pudo

    @property
    def sin_clave(self) -> int:
        """Cuántos se saltaron por no tener EAN. Se arregla en SICAR."""
        return sum(1 for r in self.renglones if r.final == SIN_CLAVE)

    @property
    def motivos(self) -> tuple[tuple[str, int], ...]:
        return contar_los_motivos(self.renglones)

    @property
    def se_paso_del_tope(self) -> bool:
        return self.final == SE_ACABO_EL_TIEMPO

    # ------------------------------------------------- lo que se guarda

    def como_corrida(self, negocio: str) -> CorridaDelLote:
        """Este mismo resumen, con la forma de la fila que se guarda (ADR 0007).

        **Función pura y una sola traducción.** El ADR 0007 lo pide con todas
        sus letras: *"el resumen que se guarda es literalmente el mismo objeto
        que se imprime"*, porque dos versiones de la misma noche es justo lo
        que el ADR 0006 no quería. Aquí no se recuenta nada — cada campo sale
        de la propiedad que ya alimenta el journal.

        Dos campos van sin valor a propósito:

        - `corrida_del_lote_id=0` — todavía no hay fila, así que no hay id. El
          de verdad lo devuelve `guardar_la_corrida`.
        - `termino_en=None` — la hora la pone la base con `now()`. Ponerle aquí
          el reloj del proceso sería escribir un instante que no es el que la
          fila va a llevar.

        `tope_minutos` sale de `tope_seg` porque es lo que la pantalla escribe
        —*"se detuvo al tope de 60 minutos"*—, y quien lee una pantalla no
        divide entre sesenta.
        """
        return CorridaDelLote(
            corrida_del_lote_id=0,
            negocio=negocio,
            pedido_sugerido_id=self.pedido_sugerido_id,
            fecha_del_pedido=self.fecha_del_pedido,
            final=self.final,
            segundos=self.segundos,
            tope_minutos=self.tope_seg / 60.0,
            en_la_lista=self.en_la_lista,
            consultados=self.consultados,
            con_precio=self.con_precio,
            sin_alcanzar=self.sin_alcanzar,
            no_se_pudo=self.no_se_pudo,
            sin_clave=self.sin_clave,
            # `None` cuando no hubo orden que calcular —una corrida sin lista—
            # se guarda como falso, que es lo honesto: no se cumplió el orden
            # que el ticket 18 pide, porque no hubo nada que ordenar.
            orden_cumplido=bool(self.orden and self.orden.cumple_el_orden),
            detalle=self.detalle,
        )

    # ------------------------------------------------------ la bitácora

    def como_texto(self) -> str:
        """El resumen entero, para el journal. Lo lee una persona en la mañana.

        Función pura: no imprime, devuelve. Quien imprime es `correr_el_lote`,
        una vez y al final, y así esto se puede comparar en una prueba sin
        capturar la salida.

        Cada línea contesta una pregunta de la casilla del ticket, en el orden
        en que alguien las hace: ¿corrió?, ¿cuántos?, ¿cuántos sin precio?,
        ¿por qué?, ¿en qué orden fue?
        """
        minutos = self.segundos / 60.0
        tope_min = self.tope_seg / 60.0
        lineas = [
            f"lote nocturno — lista del {self.fecha_del_pedido or '(ninguna)'} "
            f"(pedido sugerido {self.pedido_sugerido_id or '—'})",
            f"  final:      {self.final} en {minutos:.1f} min de {tope_min:.0f} "
            "de tope",
        ]

        if self.detalle:
            lineas.append(f"              {self.detalle}")

        lineas.append(
            f"  renglones:  {self.en_la_lista} en la lista · "
            f"{self.consultados} consultados · {self.con_precio} con precio · "
            f"{self.sin_precio} sin precio"
        )

        if self.sin_alcanzar:
            lineas.append(
                f"  por tope:   {self.sin_alcanzar} renglón(es) quedaron "
                f"FALTANTES POR TOPE ({SIN_TIEMPO}), no con error: no se les "
                "preguntó. Se completan con su botón o mañana."
            )
        if self.no_se_pudo:
            lineas.append(
                f"  no se pudo: {self.no_se_pudo} renglón(es) se intentaron y no "
                "dejaron fila guardada (mira arriba en este mismo journal)."
            )
        if self.sin_clave:
            lineas.append(
                f"  sin clave:  {self.sin_clave} renglón(es) no tienen EAN y no "
                "se consultaron. Se arregla en SICAR, no aquí."
            )

        if self.motivos:
            lineas.append("  sin precio, por qué (huecos, no renglones):")
            lineas.extend(
                f"      {cuantos:>5} · {motivo} — {explicacion_del_motivo(motivo)}"
                for motivo, cuantos in self.motivos
            )

        if self.orden is not None:
            if self.orden.cumple_el_orden:
                lineas.append(
                    f"  orden:      por clase ABC, {self.orden.con_clase} "
                    "renglón(es) con clase."
                )
            else:
                lineas.append(f"  orden:      SIN CUMPLIR — {self.orden.motivo}")

        return "\n".join(lineas)


# =========================================================================
# PURO — EL LATIDO QUE LE TOCA A ESTA CORRIDA
# =========================================================================
#
# Qué se le dice a Uptime Kuma, decidido con una tabla de casos y sin tocar la
# red. Lo que toca la red es `latido.mandar_el_latido`, que entra por argumento.
#
# **El monitor es PROPIO, distinto del de la cadena de farmacia-data y del de
# Marlowe**, y ésa es la casilla entera del ticket 19: *"si compartieran
# monitor, una noche sin lote no avisaría nada"*. Medido en atlas el
# 2026-09-19: los tres nombres de variable son distintos —`KUMA_PUSH_URL` en
# farmacia-data, `KUMA_PUSH_URL_MARLOWE` en Marlowe y
# `KUMA_PUSH_URL_CONTINENTAL` aquí—, así que son tres URLs con tres tokens y
# tres monitores. Crear el de aquí es un paso de dueño en la interfaz de Kuma:
# `docs/despliegue-en-atlas.md`, parte D.


def estado_del_latido(resumen: ResumenDeLaCorrida) -> str:
    """`up` o `down` para esta corrida. **Función pura, con su tabla.**

    | Final | Qué se manda | Por qué |
    |---|---|---|
    | `terminó` | `up` | recorrió la lista entera |
    | `se acabó el tiempo` | `up` | **no es un error**: detenerse es lo que se le pide (ticket 18). Un monitor rojo todas las noches por el tope es un monitor que nadie vuelve a mirar |
    | `no hubo lista` | `up` | el lote corrió y el almacén no tenía ventas. La farmacia cierra los domingos |
    | `se interrumpió` | `down` | eso sí es una falla |

    Y un quinto caso que **no sale del final** y por eso no cabía en la tabla:
    **se intentó preguntar y no se pudo ni una sola vez** → `down`. Doyle no
    está, o el almacenamiento rebotó todo: la lista amanece sin un solo precio.

    Hasta el 2026-09-20 esto decidía con una sola variable y ese caso salía
    `up`. Los renglones acaban en `no se pudo`, la corrida recorre la lista y
    termina, así que `final = terminó` — y el monitor habría dicho *"todo
    bien"* sobre un lote que no pudo preguntarle a nadie. Es el estado de hoy,
    porque Doyle todavía no está en atlas.

    **Es la regla más estrecha que caza el caso**, a propósito. Si se consultó
    aunque sea un renglón, la corrida hizo su trabajo y el `msg` ya dice
    cuántos huecos hubo. Se descartó `con_precio == 0 → down`, que es más
    ancha: pintaría rojo la noche en que Doyle contesta y los cuatro portales
    fallan —eso es *"sin dato"*, se ve en la pantalla con su motivo y se
    arregla abriendo sesiones, no reparando el lote— y también una lista entera
    sin EAN, que se arregla en SICAR.

    Lo que Kuma caza **no está en esta tabla**: es la noche en la que no llega
    ningún latido —atlas apagado a las 22:00, el timer sin habilitar—. Para eso
    hace falta que las noches buenas sí latan, y por eso `se acabó el tiempo`
    late en verde: un monitor que se pone rojo por algo que no es una falla
    deja de distinguirse del silencio, que es lo único que de verdad muerde.

    > **Un `down` ya no pinta rojo al instante.** Decía aquí que sí, y dejó de
    > ser cierto cuando el monitor tomó `Retries = 2` para que el cierre de la
    > ventana del fin de semana no fuera un falso rojo cada lunes (parte D de
    > `docs/despliegue-en-atlas.md`). Ahora pasa ~2 h por `PENDING` antes del
    > rojo. A las 22:30 no hay nadie mirando el panel, así que el aviso sirve
    > igual a las 00:30.
    """
    if resumen.final == SE_INTERRUMPIO:
        return ABAJO
    if resumen.intentados and not resumen.consultados:
        return ABAJO
    return ARRIBA


def mensaje_del_latido(resumen: ResumenDeLaCorrida) -> str:
    """Una línea para el historial de Kuma. **Función pura.**

    Una línea porque viaja en una URL y se pinta en una celda; el relato entero
    es el journal (`como_texto`), que es donde vive la bitácora (ADR 0006).
    `latido.recortar` la acota.

    **Nunca lleva el texto de una excepción** (regla 5 de `CLAUDE.md`): un
    `str(exc)` de SQLAlchemy lleva la cadena de conexión con contraseña, y esto
    acaba en la base de un Kuma que también sirve a Marlowe. Lo que sí lleva es
    el `detalle` del resumen, que este módulo redacta con el **tipo** de la
    falla y nada más.
    """
    cabeza = (
        f"{resumen.final}: {resumen.consultados}/{resumen.en_la_lista} "
        f"consultados, {resumen.con_precio} con precio, "
        f"{resumen.segundos / 60.0:.0f} min"
    )
    cola = []
    if resumen.sin_alcanzar:
        cola.append(f"{resumen.sin_alcanzar} sin alcanzar")
    if resumen.no_se_pudo:
        cola.append(f"{resumen.no_se_pudo} no se pudo")
    if resumen.sin_clave:
        cola.append(f"{resumen.sin_clave} sin clave")
    if resumen.detalle:
        cola.append(resumen.detalle)
    return cabeza + (" · " + "; ".join(cola) if cola else "")


# =========================================================================
# ORQUESTACIÓN — LA CORRIDA
# =========================================================================


def _guardar_la_corrida(
    almacenamiento: AlmacenamientoDelPedido,
    negocio: str,
    resumen: ResumenDeLaCorrida,
) -> int:
    """Escribe la fila de `pedidos.corrida_del_lote`. **No levanta nunca.**

    Es la segunda escritura del `finally` y lleva la misma garantía que el
    latido, por la misma razón escrita en el ADR 0007: *"una corrida entera de
    sesenta minutos no se marca como rota porque la fila de la bitácora no se
    pudo escribir"*. Devuelve el id, o `0` si no se pudo.

    Lo que sí hace es decirlo, y ruidosamente (regla 4): sin esa fila, a la
    mañana la pantalla va a decir *"el lote no corrió sobre esta lista"* sobre
    una noche en la que sí corrió — que es de menos, y hay que poder saber por
    qué. El motivo que se escribe es el **tipo** y nunca el texto (regla 5).
    """
    try:
        return almacenamiento.guardar_la_corrida(negocio, resumen.como_corrida(negocio))
    except BaseException as exc:  # noqa: BLE001 — la bitácora no rompe la corrida
        log.error(
            "NO se pudo guardar la corrida del lote en pedidos.corrida_del_lote "
            "(%s). LA CORRIDA NO SE ABORTA: lo de arriba ya está guardado. Lo "
            "que cuesta es que la pantalla va a decir «el lote no corrió sobre "
            "esta lista» sobre una noche en la que sí corrió, porque es la "
            "ausencia de esa fila lo que significa eso (ADR 0007).",
            type(exc).__name__,
        )
        return 0


def _renglon_sin_alcanzar(
    renglon: RenglonGuardado, clases: Mapping[int, str]
) -> RenglonDelLote:
    """Un renglón al que el tope le ganó. **Faltante por tope, no error.**

    Lo que se le pone es `no alcanzó el tiempo`, el motivo que `precios.py` ya
    tenía y que existe para exactamente esto: *"se acabó el tiempo con ese
    proveedor todavía buscando"*, aquí con la lista entera todavía por
    consultar. No se estrena un motivo nuevo porque no hace falta uno: los dos
    casos se arreglan igual —volver a consultar— y un motivo que se atiende
    como otro sobra (la nota de `MOTIVOS`).

    **No se escribe ninguna fila por esto**, y es una decisión con su porqué en
    el ADR 0006: escribir cuatro filas de hueco por cada renglón que no se
    alcanzó obligaría a inventarse a qué proveedores se le iba a preguntar —esa
    lista sale del acuse de Doyle y aquí no hubo acuse— y dispararía la
    condición de revisión del ADR 0004 sobre cuánto crece la tabla. Lo que sí
    queda es el conteo y el porqué, en el resumen de esta misma corrida.
    """
    return RenglonDelLote(
        renglon_id=renglon.renglon_id,
        clave=renglon.propuesto.clave,
        descripcion=renglon.propuesto.descripcion,
        clase_abc=clases.get(renglon.propuesto.producto_id, SIN_CLASE_ABC),
        final=SIN_ALCANZAR,
        motivos=(SIN_TIEMPO,),
    )


def _consultar_un_renglon(
    renglon: RenglonGuardado,
    *,
    doyle: ClienteDeDoyle,
    almacenamiento: AlmacenamientoDelPedido,
    registro: RegistroDeConsultas,
    negocio: str,
    clases: Mapping[int, str],
    tope_por_consulta_seg: float,
    cada_seg: float,
    dormir: Callable[[float], object],
    ahora: Callable[[], float],
) -> RenglonDelLote:
    """Un renglón: se le pregunta a Doyle y se anota cómo le fue.

    **Reutiliza entero el camino del ticket 12** (`consultar_y_congelar`) y no
    escribe una segunda manera de pedirle precios a Doyle. Eso compra tres
    cosas medidas que aquí no hay que volver a escribir: una lectura por
    proveedor aunque no conteste ninguno, el emparejamiento por EAN del ticket
    13, y el guardado en cuanto llega.

    **Y es lo que hace que un proveedor que falla no tumbe el lote**, que es
    una casilla entera del ticket: `precios.congelar` devuelve una lectura por
    cada proveedor del acuse —la del que falló con su motivo, la del que
    contestó con su precio— y las cuatro se guardan juntas. Un proveedor caído
    es un hueco en su columna, nunca una consulta perdida.

    `consultar_y_congelar` ya atrapa todo lo que puede fallar de los dos bordes
    y lo convierte en un estado, así que aquí no hay un `try` más: lo que
    devuelve siempre es una consulta con su final escrito.
    """
    consulta, _ = registro.pedir(
        renglon.renglon_id,
        renglon.propuesto.clave,
        lambda en_curso: consultar_y_congelar(
            en_curso,
            doyle=doyle,
            almacenamiento=almacenamiento,
            registro=registro,
            negocio=negocio,
            tope_seg=tope_por_consulta_seg,
            cada_seg=cada_seg,
            dormir=dormir,
            ahora=ahora,
        ),
    )
    # La del registro y no la que se acaba de crear: para cuando se llega aquí
    # la tarea ya terminó y devolver la de antes diría "en curso" sobre algo
    # que ya está guardado. Es lo mismo que hace la ruta del ticket 12.
    consulta = registro.de(renglon.renglon_id) or consulta

    base = RenglonDelLote(
        renglon_id=renglon.renglon_id,
        clave=renglon.propuesto.clave,
        descripcion=renglon.propuesto.descripcion,
        clase_abc=clases.get(renglon.propuesto.producto_id, SIN_CLASE_ABC),
        detalle=consulta.detalle,
    )

    if consulta.estado != GUARDADA:
        return replace(base, final=NO_SE_PUDO)

    # Se lee lo GUARDADO y no lo que la consulta creyó traer: lo que cuenta la
    # bitácora tiene que ser lo que quedó en la tabla, que es lo que el
    # encargado va a ver en la mañana. Si el guardado se hubiera comido una
    # lectura, el resumen lo diría en vez de taparlo.
    lecturas = almacenamiento.precios_del_renglon(negocio, renglon.renglon_id)
    return replace(
        base,
        final=CONSULTADO,
        con_precio=sum(1 for l in lecturas if not l.sin_dato),
        sin_precio=sum(1 for l in lecturas if l.sin_dato),
        motivos=tuple(sorted(l.motivo for l in lecturas if l.motivo)),
    )


def correr_el_lote(
    *,
    almacen: LecturaDelAlmacen,
    almacenamiento: AlmacenamientoDelPedido,
    doyle: ClienteDeDoyle,
    negocio: str,
    tope_seg: float,
    tope_por_consulta_seg: float,
    cada_seg: float,
    registro: RegistroDeConsultas | None = None,
    reglas=None,
    dormir: Callable[[float], object] = time.sleep,
    ahora: Callable[[], float] = time.monotonic,
    latir: Callable[..., ResultadoDelLatido] = mandar_el_latido,
) -> ResumenDeLaCorrida:
    """La corrida entera. Arma la lista del día, consulta en orden, y se detiene.

    Los tres bordes entran por argumento —el mismo criterio que las
    dependencias de FastAPI— y por eso esto se prueba completo contra los
    dobles, sin Postgres, sin red y sin `.env`. `main` es quien construye los
    de verdad.

    **El orden de los pasos importa y es el mismo de la pantalla:** primero
    vencer las listas de días anteriores, después abrir la de hoy. Al revés, la
    de hoy ya existiría cuando el barrido busca "abiertas de un día anterior".

    **La fecha se ancla en `max(fecha)` del almacén y nunca en el reloj.** Un
    lote que corre a las 22:00 contra un Postgres en UTC vería "mañana" como
    hoy, y armaría una lista de un día que no tiene ventas. A farmacia-data le
    costó 11.7 puntos de crecimiento inventados.

    **Lo que escribe, y nada más:** la lista del día si no existía, y filas
    nuevas en `pedidos.precio_de_proveedor`, que solo crece (ADR 0004). No hay
    un `UPDATE` de renglón en toda la función. Por eso un lote muerto a la
    mitad no puede dejar la lista peor que antes: lo consultado ya está escrito
    y lo demás simplemente no pasó.

    **El tope se mira antes de cada renglón**, así que el lote nunca corta una
    consulta a medias — ver la nota del encabezado. Lo que queda por consultar
    se anota como *faltante por tope*, con el motivo `no alcanzó el tiempo`, y
    la corrida acaba en `se acabó el tiempo`, que **no es un error**: el
    proceso sale con cero.

    El resumen se devuelve y **además se escribe en la bitácora pase lo que
    pase**, incluso si algo tumba la corrida a la mitad: está en un `finally`.
    Una noche en la que el lote murió sin decir cuánto alcanzó a hacer es
    justo el hilo abierto 3 de `HANDOVER.md`.

    **Lo que el ticket 19 agregó a ese `finally` son dos cosas más, y ninguna
    puede tumbar la corrida:**

    - la fila de `pedidos.corrida_del_lote` —una por noche, ADR 0007—, que es
      de donde la pantalla saca *"el lote se cortó por tiempo antes de llegar
      a este renglón"*. Sin ella, a la mañana la pantalla dice *"el lote no
      corrió sobre esta lista"*, que es de menos;
    - el latido a Uptime Kuma, con **monitor propio** (`latir`, que entra por
      argumento igual que `ahora` y `dormir`, para que ninguna prueba mande un
      latido de verdad). *"Marcar como rota una corrida buena es peor que
      perderse un latido."*
    """
    if registro is None:
        # Sin hilos: el lote es secuencial a propósito (ver el encabezado), así
        # que la tarea se ejecuta ahí mismo. Un registro nuevo por corrida y no
        # el del proceso web: éste es otro proceso.
        registro = RegistroDeConsultas(lanzar=lambda tarea: tarea())
    cronometro = Cronometro.arrancar(tope_seg, ahora)

    # El resumen vive en una lista de un elemento y no en una variable suelta
    # por una razón concreta: el `finally` que lo manda a la bitácora corre
    # DESPUÉS de que el `return` ya se llevó su valor, así que una reasignación
    # ahí no llegaría a quien llama. Con la caja, los dos ven lo mismo — lo que
    # se imprime es exactamente lo que se devuelve.
    caja = [
        ResumenDeLaCorrida(
            fecha_del_pedido=None,
            pedido_sugerido_id=None,
            final=SIN_LISTA,
            segundos=0.0,
            tope_seg=tope_seg,
        )
    ]

    def sellar(**cambios) -> ResumenDeLaCorrida:
        """Actualiza el resumen y le pone el tiempo transcurrido de verdad."""
        caja[0] = replace(caja[0], segundos=cronometro.transcurrido, **cambios)
        return caja[0]

    # Fuera del `try` a propósito: si algo corta la corrida, la rama de abajo
    # tiene que poder decir **cuánto alcanzó a hacer** antes de morirse. Una
    # bitácora que dice "0 renglones" sobre una noche en la que se consultaron
    # ciento veinte es peor que no tenerla, porque parece un dato.
    anotados: list[RenglonDelLote] = []

    try:
        ultima = almacen.ultima_fecha_con_ventas()
        if ultima is None:
            return sellar(
                detalle=(
                    "el almacén no tiene una sola venta: no hay lista que armar. "
                    "La farmacia cierra los domingos y no hay una venta en "
                    "domingo en 33 meses — esto no es una falla."
                ),
            )

        catalogo = almacen.catalogo()
        clases = clases_del_catalogo(catalogo)

        vencidas = almacenamiento.vencer_las_de_dias_anteriores(negocio, ultima)
        if vencidas:
            log.info(
                "%d pedido(s) sugerido(s) anteriores al %s quedaron vencidos "
                "antes de arrancar el lote.",
                vencidas,
                ultima,
            )

        ventana = ventana_de_reposicion(
            corte=almacenamiento.corte_del_ultimo_cerrado(negocio, ultima),
            hasta=ultima,
            dias_primera_vez=dias_primera_vez_configurados(),
        )
        guardado: PedidoSugeridoGuardado = almacenamiento.abrir_el_dia(
            negocio,
            ultima,
            ventana,
            # El catálogo ya está leído: se lo pasamos para no recorrer las
            # 3,429 filas dos veces en la misma corrida.
            lambda: armar_la_lista(
                almacen, ventana, reglas=reglas, catalogo=catalogo
            ).renglones,
        )

        orden = ordenar_por_importancia(guardado.de_trabajo, clases)
        if not orden.cumple_el_orden:
            # A la bitácora ANTES de empezar, no solo al final: si la corrida
            # se muere a la mitad, esto tiene que haberse dicho igual.
            log.warning("Lote nocturno: %s", orden.motivo)

        log.info(
            "Lote nocturno: lista del %s (pedido sugerido %s), %d renglón(es) "
            "de trabajo, tope de %.0f min.",
            guardado.fecha_del_pedido,
            guardado.pedido_sugerido_id,
            orden.cuantos,
            tope_seg / 60.0,
        )

        sellar(
            fecha_del_pedido=guardado.fecha_del_pedido,
            pedido_sugerido_id=guardado.pedido_sugerido_id,
            final=TERMINO,
            orden=orden,
        )

        for posicion, renglon in enumerate(orden.renglones):
            if cronometro.se_acabo:
                # Se acabó el tiempo: TODO lo que queda —éste incluido— es
                # faltante por tope. No se rompe el bucle sin anotarlos: un
                # renglón que desaparece del resumen es un renglón del que
                # nadie sabe que no se consultó.
                faltan = orden.renglones[posicion:]
                anotados.extend(_renglon_sin_alcanzar(r, clases) for r in faltan)
                sellar(final=SE_ACABO_EL_TIEMPO)
                log.warning(
                    "Lote nocturno: se acabó el tope de %.0f min con %d "
                    "renglón(es) sin consultar. Quedan FALTANTES POR TOPE (%s), "
                    "no con error.",
                    tope_seg / 60.0,
                    len(faltan),
                    SIN_TIEMPO,
                )
                break

            if not renglon.propuesto.clave:
                # Sin EAN no hay con qué buscar, y buscarlo por su nombre
                # traería el producto de otro (ADR 0002). Ni se molesta a un
                # portal: es la misma negativa que da la pantalla, con la misma
                # razón, y se dice en el resumen.
                anotados.append(
                    RenglonDelLote(
                        renglon_id=renglon.renglon_id,
                        clave="",
                        descripcion=renglon.propuesto.descripcion,
                        clase_abc=clases.get(
                            renglon.propuesto.producto_id, SIN_CLASE_ABC
                        ),
                        final=SIN_CLAVE,
                    )
                )
                continue

            anotado = _consultar_un_renglon(
                renglon,
                doyle=doyle,
                almacenamiento=almacenamiento,
                registro=registro,
                negocio=negocio,
                clases=clases,
                tope_por_consulta_seg=tope_por_consulta_seg,
                cada_seg=cada_seg,
                dormir=dormir,
                ahora=ahora,
            )
            anotados.append(anotado)
            log.info(
                "Lote nocturno: renglón %s (%s) — %s, %d con precio, %d sin "
                "precio%s",
                anotado.renglon_id,
                anotado.descripcion,
                anotado.final,
                anotado.con_precio,
                anotado.sin_precio,
                f" ({', '.join(anotado.motivos)})" if anotado.motivos else "",
            )

        return sellar(renglones=tuple(anotados))

    except BaseException as exc:  # noqa: BLE001 — hasta un Ctrl-C deja bitácora
        # Se atrapa TODO, incluido `KeyboardInterrupt` y `SystemExit`, y
        # **se vuelve a levantar**: lo único que se hace aquí es dejar dicho en
        # qué punto se murió. Tragarse la excepción sería la falla silenciosa
        # que la regla 4 de `CLAUDE.md` prohíbe, y el proceso tiene que salir
        # con código distinto de cero para que el journal lo marque en rojo.
        #
        # El motivo que se escribe es el **tipo** de la falla y nunca su texto
        # (regla 5): un `str(exc)` de SQLAlchemy lleva la cadena de conexión
        # con contraseña, y esto acaba en el journal de atlas.
        sellar(
            final=SE_INTERRUMPIO,
            # Lo que alcanzó a procesar, no una lista vacía: es la diferencia
            # entre una bitácora y un renglón de ruido.
            renglones=tuple(anotados),
            detalle=(
                f"la corrida se cortó ({type(exc).__name__}) después de "
                f"{len(anotados)} renglón(es). Lo que ya estaba guardado sigue "
                "guardado: nada de lo de arriba se deshace, y los que faltaban "
                "no aparecen abajo porque no se llegó a mirarlos."
            ),
        )
        raise
    finally:
        # LAS TRES COSAS DEL FINAL, EN ESTE ORDEN Y NINGUNA PUEDE TUMBAR A LAS
        # OTRAS. Están aquí y no después del `return` porque tienen que pasar
        # **también** cuando el tope cortó y cuando algo mató la corrida a la
        # mitad: las dos noches raras son justo las que hay que poder contar.
        #
        #   1. el journal, que es la bitácora del relato (ADR 0006) y lo único
        #      que deja rastro aunque Postgres sea lo que se cayó;
        #   2. la fila de `pedidos.corrida_del_lote`, que es lo que la pantalla
        #      lee a la mañana (ADR 0007);
        #   3. el latido a Uptime Kuma, que es lo único que se queja cuando NO
        #      pasa nada.
        #
        # Las dos últimas atrapan `BaseException` cada una por su cuenta, y eso
        # es la casilla del ticket puesta donde no se puede cumplir a medias:
        # **marcar como rota una corrida buena es peor que perderse un latido**
        # — y lo mismo vale para la fila de la bitácora.
        log.info("%s", caja[0].como_texto())

        _guardar_la_corrida(almacenamiento, negocio, caja[0])

        # El latido va DESPUÉS de guardar, y el orden no es al azar: si algo va
        # a fallar, que falle antes de decirle a Kuma que todo salió bien.
        #
        # `mandar_el_latido` ya no levanta nunca por su cuenta —su `except` es
        # de `BaseException` y no tiene un solo `raise` hacia afuera—, y aun
        # así aquí hay otro `try`. No es cinturón sobre tirante por gusto: el
        # que se llama es `latir`, que ENTRA POR ARGUMENTO, y una excepción
        # levantada dentro de un `finally` mientras otra va subiendo **la
        # sustituye** — o sea que un doble mal escrito no solo rompería una
        # corrida buena, sino que además se llevaría el motivo por el que la
        # corrida se había muerto. La garantía se pone donde se ejerce.
        try:
            resultado = latir(
                estado=estado_del_latido(caja[0]),
                mensaje=mensaje_del_latido(caja[0]),
                segundos=caja[0].segundos,
            )
        except BaseException as exc:  # noqa: BLE001 — un latido perdido no rompe la corrida
            # El TIPO y nunca el texto (regla 5): el texto de un error de httpx
            # trae la URL completa, y la URL completa ES el token del monitor.
            log.warning(
                "El latido a Uptime Kuma levantó (%s), que es algo que "
                "mandar_el_latido promete no hacer. LA CORRIDA NO SE ABORTA.",
                type(exc).__name__,
            )
        else:
            if not resultado.se_mando and not resultado.se_omitio:
                log.warning(
                    "El lote terminó (%s) y el latido NO salió: %s. La corrida "
                    "vale lo que valía; lo que pasa es que el monitor va a "
                    "avisar de una falla que no existe hasta el próximo latido.",
                    caja[0].final,
                    resultado.motivo,
                )


# =========================================================================
# ARRANQUE — lo único que construye bordes de verdad
# =========================================================================
#
# Igual que en `verificar.py`: las importaciones del almacén y de la
# configuración están DENTRO de `main`, para que `import continental.lote` no
# exija `.env` ni cree un motor. Es lo que deja que `tests/test_lote.py`
# importe este módulo sin nada levantado.


def main(argv: list[str] | None = None) -> int:
    """Arma los bordes de verdad y corre el lote una vez. Lo que el timer llama.

    Devuelve **cero también cuando se acabó el tiempo**, y eso es el ticket: un
    lote que se detiene a los 60 minutos hizo exactamente lo que se le pidió.
    Marcarlo como fallido dejaría `continental-lote.service` en rojo todas las
    noches y nadie volvería a mirar el journal, que es donde vive el resumen.

    Lo que sí sale distinto de cero es una corrida que se cortó: ahí la
    excepción sube y systemd la marca.
    """
    parseador = argparse.ArgumentParser(
        prog="python -m continental.lote",
        description=(
            "El lote nocturno de precios: arma la lista del día, consulta a "
            "Doyle en orden de importancia y se detiene al tope."
        ),
    )
    parseador.add_argument(
        "--tope-minutos",
        type=float,
        default=None,
        help=(
            "Cuánto puede durar como mucho. Por omisión, lo que diga "
            "`pedido.tope_lote_minutos` de config/continental.yml (60). Está "
            "para poder correr el lote a mano con un tope corto y ver qué hace, "
            "no para dejarlo puesto en la unidad de systemd."
        ),
    )
    argumentos = parseador.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    from continental.almacen import AlmacenPostgres, motor
    from continental.almacenamiento import AlmacenamientoPostgres
    from continental.config import cargar

    ajustes = cargar()
    doyle_configurado = ajustes.modulos.get("doyle")
    if doyle_configurado is None:
        # Igual que en `web/dependencias.py`: un YAML sin la entrada `doyle` es
        # un despliegue roto, no un problema de operación, y adivinar el puerto
        # sería la falla silenciosa que este repo prohíbe.
        raise RuntimeError(
            "Falta el módulo `doyle` en config/continental.yml. Sin él el lote "
            "nocturno no tiene a quién pedirle precios."
        )

    from continental.doyle import DoylePorHttp

    tope_seg = (
        tope_del_lote_segundos()
        if argumentos.tope_minutos is None
        else max(argumentos.tope_minutos, 0.0) * 60.0
    )
    tope_por_consulta_seg, cada_seg = ajustes_de_la_consulta()

    resumen = correr_el_lote(
        almacen=AlmacenPostgres(motor),
        almacenamiento=AlmacenamientoPostgres(motor),
        doyle=DoylePorHttp(
            url=doyle_configurado.url, timeout_seg=doyle_configurado.timeout_seg
        ),
        negocio=ajustes.negocio,
        tope_seg=tope_seg,
        tope_por_consulta_seg=tope_por_consulta_seg,
        cada_seg=cada_seg,
        reglas=reglas_configuradas(),
    )
    # El resumen ya fue a la bitácora desde dentro; esto es para quien corra el
    # lote a mano y esté mirando la terminal.
    print(resumen.como_texto())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
