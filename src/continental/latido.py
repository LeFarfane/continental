"""El latido a Uptime Kuma: que el dueño se entere si el lote NO corrió.

**El silencio es el modo de falla que de verdad muerde.** Un lote que truena
deja un journal rojo y una unidad en `failed`; un lote que *no corre* —atlas
apagado a las 22:00, el timer sin habilitar, un `daemon-reload` a medias— no
deja nada. A la mañana la lista está sin precios y eso se ve igual que una
noche en la que Doyle no contestó. Kuma existe para exactamente eso: es lo
único que se queja **cuando no pasa nada**.

## Este módulo sirve a DOS monitores, cada uno con su variable

El lote (`KUMA_PUSH_URL_CONTINENTAL`, `VARIABLE_DEL_LATIDO`) y la verificación
diaria de los datos de producción (`KUMA_PUSH_URL_VERIFICAR`,
`VARIABLE_DEL_LATIDO_VERIFICAR`, `python -m continental.verificar --latido`,
`continental-verificar.timer`). El porqué de que sean dos y no uno es la MISMA
razón que hace propio al del lote frente a los de farmacia-data y Marlowe: un
monitor compartido confunde "los datos están rotos" con "no se trajeron
precios", y son dos preguntas que se arreglan de maneras distintas.

## MONITOR PROPIO, y por qué eso es la casilla entera

El ticket lo dice con su razón dentro: *"si compartieran monitor, una noche sin
lote no avisaría nada"*. Kuma ya vigila la cadena de farmacia-data y a Marlowe;
si este latido entrara por el mismo *push monitor*, la cadena de las 20:30
seguiría latiendo todas las noches y el monitor se vería verde con el lote de
las 22:00 muerto desde hace una semana. Un monitor compartido convierte el
aviso en ruido de fondo: mide "algo de esta casa sigue vivo", que no es una
pregunta que nadie se haga.

## EL TOKEN ES UN SECRETO Y VIVE EN `.env`

Un *push monitor* de Kuma es una URL con un token dentro
(`http://.../api/push/<token>`). **Quien la tenga puede decirle a Kuma que
todo está bien**, que es justamente la afirmación que este archivo existe para
hacer honesta. Va en `KUMA_PUSH_URL_CONTINENTAL` del `.env`, que está en
`.gitignore`, y **nunca** en `config/continental.yml`, que sí se versiona. Es
la misma frontera que ya separa `WAREHOUSE_URL` del YAML.

Crear el monitor es un paso de dueño en la interfaz de Kuma y no se puede
hacer desde aquí: el procedimiento, campo por campo, está en
`docs/despliegue-en-atlas.md`, parte D.

## Si falla el latido, la corrida NO se aborta

*"Marcar como rota una corrida buena es peor que perderse un latido."*
`mandar_el_latido` **no levanta nunca**: atrapa todo lo que pueda salir del
borde HTTP y devuelve un `ResultadoDelLatido` que dice si se mandó y por qué
no. Un Kuma caído, un token borrado, un DNS que no resuelve — ninguno de esos
convierte sesenta minutos de precios bien traídos en una corrida fallida.

Lo que sí hace es **decirlo en la bitácora**, y ahí no es silencioso: un latido
que no salió es una noche en la que Kuma va a avisar de una falla que no
existe, y quien lea el journal a la mañana tiene que poder saber que eso fue lo
que pasó.

## Nada de esto toca la red al importarse, y ninguna prueba manda un latido

`pedir` entra por argumento, igual que `dormir` y `ahora` en el lote, y el
suite le pasa uno de mentira. **Ninguna prueba hace una petición HTTP de
verdad, ni a la Kuma real ni a ninguna otra**: la Kuma de atlas la comparten
Marlowe y la cadena de farmacia-data, y un latido de prueba escribiría en el
historial de un monitor que alguien mira.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

log = logging.getLogger("continental")

#: El nombre de la variable de entorno, escrito una vez. Lo citan el `.env.example`,
#: el despliegue y el aviso de "no está configurado": tres copias del mismo
#: texto se separan el día que alguien la renombre.
VARIABLE_DEL_LATIDO = "KUMA_PUSH_URL_CONTINENTAL"

#: El monitor propio de `python -m continental.verificar --latido`, y es la
#: MISMA casilla que `VARIABLE_DEL_LATIDO`: monitor propio, no compartido. Si
#: `--latido` mandara por `VARIABLE_DEL_LATIDO`, una noche en la que la
#: verificación diaria falla se vería IDÉNTICA a una noche en la que el lote
#: falló —los dos pintarían el mismo monitor rojo— y quien mire Kuma no podría
#: distinguir "los datos están rotos" de "no se trajeron precios". Son
#: preguntas distintas y necesitan monitores distintos, por la misma razón por
#: la que ADR 0006/ticket 19 le dieron uno propio al lote frente a la cadena de
#: farmacia-data y a Marlowe.
VARIABLE_DEL_LATIDO_VERIFICAR = "KUMA_PUSH_URL_VERIFICAR"

#: Lo que Kuma entiende. `up` pinta el monitor en verde y reinicia su cuenta de
#: gracia; `down` lo declara caído sin esperar a que venza el intervalo.
#:
#: **`down` ya no es rojo instantáneo, y aquí decía que sí.** El monitor lleva
#: `Retries = 2` con reintento de una hora —para que el cierre de la ventana
#: del fin de semana no sea un falso rojo cada lunes, parte D de
#: `docs/despliegue-en-atlas.md`—, así que un `down` pasa ~2 h por `PENDING`
#: antes del rojo. Sigue siendo mucho antes que el intervalo de 26 h, que es lo
#: que esta línea quería decir.
ARRIBA = "up"
ABAJO = "down"

ESTADOS: tuple[str, ...] = (ARRIBA, ABAJO)

#: Cuánto texto cabe en el `msg`. Kuma lo guarda en su base y lo enseña en el
#: historial del monitor; un resumen de cuatro líneas ahí no se lee y además
#: viaja en una URL. Se corta con puntos suspensivos en vez de reventar.
LARGO_DEL_MENSAJE = 180

#: Cuánto se espera al mandar el latido. Corto a propósito: Kuma está en el
#: mismo atlas, en loopback, y **este es el último paso de una corrida que ya
#: terminó**. Esperar treinta segundos por un contenedor que no levanta sería
#: tener al lote vivo sin hacer nada útil.
TIMEOUT_SEG = 5.0


@dataclass(frozen=True, slots=True)
class ResultadoDelLatido:
    """Si el latido salió, y si no, por qué. **Nunca una excepción.**

    Se devuelve en vez de levantarse porque quien llama es el `finally` de una
    corrida que ya terminó bien: lo único que puede hacer con una excepción
    aquí es tragársela, y entonces el motivo se pierde. Así el motivo llega
    entero a la bitácora y la corrida sigue valiendo lo que valía.
    """

    se_mando: bool
    estado: str = ""
    motivo: str = ""

    @property
    def se_omitio(self) -> bool:
        """Si ni siquiera se intentó, por no haber URL configurada."""
        return not self.se_mando and self.estado == ""


def url_del_latido(variable: str = VARIABLE_DEL_LATIDO) -> str | None:
    """La URL del *push monitor*, del entorno. `None` si no está configurada.

    **Se lee dentro de una función y nunca como constante de módulo**, y eso no
    es estilo: es la falla exacta que el ADR 0005 documenta. `cargar()` es
    quien llama a `load_dotenv`, así que una constante de módulo se evaluaría
    antes de que nadie hubiera leído el `.env` y el latido quedaría apagado sin
    un solo mensaje de error — con Kuma avisando de una falla que no existe
    todas las noches.

    Por eso aquí se llama a `cargar()` primero aunque no se use su resultado:
    es lo que garantiza que el `.env` ya esté puesto en el entorno. El orden de
    precedencia es el de siempre: entorno (systemd) → `.env` → nada.

    `variable` entra por argumento y no está fija en `VARIABLE_DEL_LATIDO`
    porque este módulo ya sirve a **dos** monitores propios (el lote y
    `continental.verificar --latido`, ver `VARIABLE_DEL_LATIDO_VERIFICAR`): la
    función que pregunta al entorno no puede llevar el nombre de uno solo de
    los dos escrito adentro.
    """
    import os

    from continental.config import cargar

    cargar()
    return (os.environ.get(variable) or "").strip() or None


def recortar(mensaje: str) -> str:
    """El mensaje, en una línea y acotado. Función pura.

    Una línea porque viaja en una URL y se pinta en una celda del historial de
    Kuma; acotado porque el resumen entero del lote son ocho renglones y ahí no
    caben — el sitio del resumen entero es el journal, que es donde vive la
    bitácora (ADR 0006).
    """
    plano = " ".join(mensaje.split())
    if len(plano) <= LARGO_DEL_MENSAJE:
        return plano
    return plano[: LARGO_DEL_MENSAJE - 1].rstrip() + "…"


def armar_la_url(
    base: str, *, estado: str, mensaje: str, segundos: float = 0.0
) -> str:
    """La URL del latido con sus tres parámetros. **Función pura.**

    `status`, `msg` y `ping`, que son los tres que un *push monitor* de Kuma
    lee. El `ping` va en **milisegundos** porque es lo que Kuma grafica como
    tiempo de respuesta, y aquí se usa para algo que de verdad interesa: cuánto
    duró la corrida. Una noche que empiece a tardar el doble se ve en esa
    gráfica antes de que nadie mire un journal.

    Los parámetros se construyen con `urlencode` y no pegando cadenas: el
    mensaje lleva acentos y espacios —"se acabó el tiempo"— y un `&` suelto
    dentro partiría la URL en dos.

    **LO QUE LA BASE TRAIGA DE QUERY SE TIRA, y eso llegó el 2026-09-20.**
    Kuma enseña su Push URL con un ejemplo pegado —
    `?status=up&msg=OK&ping=`— y así se copia al `.env`. Aquí se conservaba a
    propósito, añadiendo los parámetros de verdad con `&`: la intención era no
    romper una URL con parámetros dentro, pero la conclusión estaba al revés.
    El resultado era una petición con `status`, `msg` y `ping` **por
    duplicado**, y cuál gana lo decide Kuma.

    Pasó en la primera corrida real del lote: salió
    `status=up&msg=OK&ping=&status=down&msg=…&ping=2458`. Esa vez Kuma leyó el
    último y el latido quedó bien — pero un latido que depende de cómo el
    servidor ordena duplicados no es una garantía. El día que ganara el
    primero, el monitor diría *"todo bien"* sobre un lote roto.

    El fragmento (`#algo`) se tira por lo mismo: pegado al final se comería el
    último parámetro sin un solo error.
    """
    if estado not in ESTADOS:
        raise ValueError(
            f"Estado {estado!r} fuera de lo que Kuma entiende ({ESTADOS}). Un "
            "estado inventado no lo rechaza Kuma: lo ignora, y el monitor se "
            "queda esperando un latido que ya se mandó."
        )
    parametros = urlencode(
        {
            "status": estado,
            "msg": recortar(mensaje),
            "ping": int(max(segundos, 0.0) * 1000),
        }
    )
    limpia = urlsplit(base)._replace(query="", fragment="").geturl()
    return f"{limpia}?{parametros}"


def _pedir_por_http(url: str) -> None:
    """El borde de verdad. Lo único de este archivo que toca la red.

    Se importa `httpx` **dentro** para que `import continental.latido` no
    arrastre el cliente HTTP: es el mismo criterio que usan `verificar.py` y
    `lote.main` con el motor del almacén.

    `raise_for_status` a propósito: un 404 de Kuma —el token que alguien borró
    al recrear el monitor— tiene que contarse como latido fallido y no como
    latido bueno. Un monitor borrado que se vea verde es peor que no tener
    monitor.
    """
    import httpx

    respuesta = httpx.get(url, timeout=TIMEOUT_SEG)
    respuesta.raise_for_status()


def mandar_el_latido(
    *,
    estado: str,
    mensaje: str,
    segundos: float = 0.0,
    url: str | None = None,
    variable: str = VARIABLE_DEL_LATIDO,
    pedir: Callable[[str], object] | None = None,
) -> ResultadoDelLatido:
    """Manda el latido y **no levanta nunca**. Devuelve cómo fue.

    Es la casilla *"si falla el latido, la corrida NO se aborta"* puesta donde
    no se puede cumplir a medias: el `except` es de `BaseException` y la
    función no tiene un solo `raise` hacia afuera. Quien la llama —el `finally`
    del lote, o `continental.verificar --latido`— no necesita envolverla en
    otro `try`, y si algún día alguien la llama desde otro sitio, hereda la
    garantía sin acordarse.

    `url` y `pedir` entran por argumento por la misma razón que `ahora` y
    `dormir` en el lote: **ninguna prueba manda un latido de verdad**. Sin URL
    —ni por argumento ni en el entorno— no se intenta nada y se dice con todas
    sus letras, porque una corrida que cree estar latiendo y no late es la
    falla silenciosa que este repo persigue.

    `variable` es qué nombre de `.env` se pregunta cuando `url` no viene puesta
    (por omisión, la del lote). `continental.verificar --latido` pasa
    `VARIABLE_DEL_LATIDO_VERIFICAR` aquí, porque tiene su propio monitor y su
    propio aviso: el mensaje de "no se mandó" tiene que nombrar la variable
    que de verdad falta, no siempre la del lote.

    El `mensaje` lo compone quien llama y **nunca lleva el texto de una
    excepción** (regla 5 de `CLAUDE.md`): un `str(exc)` de SQLAlchemy lleva la
    cadena de conexión con contraseña, y esto acaba en la base de un Kuma que
    también sirve a Marlowe.
    """
    destino = url if url is not None else url_del_latido(variable)
    if not destino:
        log.warning(
            "NO se mandó latido a Uptime Kuma: falta %s en el .env. Mientras "
            "no esté, una noche sin corrida no avisa nada — que es justamente "
            "lo que el monitor existe para cazar. Ver docs/despliegue-en-atlas.md, "
            "parte D.",
            variable,
        )
        return ResultadoDelLatido(
            se_mando=False,
            motivo=f"no hay {variable} en el entorno",
        )

    try:
        completa = armar_la_url(
            destino, estado=estado, mensaje=mensaje, segundos=segundos
        )
    except ValueError as exc:
        # Un estado inventado es un error de programación de este repo, no una
        # falla del mundo: se dice entero porque no lleva nada de nadie.
        log.error("No se pudo armar el latido: %s", exc)
        return ResultadoDelLatido(se_mando=False, estado=estado, motivo=str(exc))

    try:
        (pedir or _pedir_por_http)(completa)
    except BaseException as exc:  # noqa: BLE001 — un latido perdido no rompe la corrida
        # EL TIPO Y NUNCA EL TEXTO (regla 5): el texto de un error de httpx
        # trae la URL completa, y la URL completa ES el token del monitor.
        # Escribirla en el journal de atlas sería publicar el secreto en el
        # sitio donde más gente mira.
        log.warning(
            "El latido a Uptime Kuma no salió (%s). LA CORRIDA NO SE ABORTA: "
            "marcar como rota una corrida buena es peor que perderse un "
            "latido. Lo que sí pasa es que el monitor va a avisar de una falla "
            "que no existe hasta el próximo latido.",
            type(exc).__name__,
        )
        return ResultadoDelLatido(
            se_mando=False, estado=estado, motivo=type(exc).__name__
        )

    log.info("Latido a Uptime Kuma: %s — %s", estado, recortar(mensaje))
    return ResultadoDelLatido(se_mando=True, estado=estado)
