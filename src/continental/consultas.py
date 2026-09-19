"""Quién espera a Doyle, y dónde queda el resultado si nadie está mirando.

Doyle no contesta una búsqueda de golpe: devuelve un `job_id` y se le pregunta
después. Una búsqueda tiene un **piso medido de ~9 s por proveedor** (5.6 s de
scroll de carga diferida más 3 s de cortesía) y un **techo de 60-90 s** si se
estiran los timeouts. Este módulo decide qué hacer con esos noventa segundos.

## Las tres maneras de esperar, y por qué se eligió la tercera

1. **Continental espera dentro de la petición.** El navegador pide el precio y
   la respuesta HTTP no llega hasta que Doyle termina. Es lo más simple de
   escribir y lo peor de usar: la pantalla queda colgada hasta minuto y medio,
   la segunda casilla del ticket lo prohíbe con todas sus letras, y **una
   recarga tira la consulta** — el portal ya se visitó, la respuesta se pierde,
   y hay que volver a molestar al proveedor.

2. **El navegador sondea a Doyle y le manda el resultado a Continental.** La
   pantalla no se cuelga, pero el precio congelado pasaría a ser *lo que el
   navegador dijo que Doyle dijo*: un dato de compra que viaja por un campo de
   formulario. Y sigue perdiéndose al cerrar la pestaña, que es exactamente
   cuando más duele — el encargado lanza la consulta y se va a atender a
   alguien.

3. **Continental sondea en un hilo y guarda el resultado en cuanto llega; el
   navegador le pregunta a Continental, no a Doyle.** Es lo que se hace.

## Qué compra la tercera, dicho como consecuencias

- **Recargar o cerrar la pestaña no pierde nada.** El hilo sigue, la fila se
  escribe, y la siguiente carga de la página la encuentra: lo que se muestra es
  lo guardado. Es la misma propiedad que el ticket 08 le dio a la lista.
- **El precio congelado lo escribe el servidor**, que es quien habló con Doyle.
  Nada de lo que se guarda pasó por el navegador.
- **Pedir dos veces el mismo renglón no consulta dos veces.** Mientras una
  consulta esté en curso, un segundo clic devuelve *esa misma* consulta en vez
  de lanzar otra. No es comodidad: Doyle abre navegadores de verdad contra los
  portales con las credenciales del dueño, y dos clics nerviosos serían ocho
  visitas en lugar de cuatro.
- **Hay estado en memoria del proceso**, y eso hay que decirlo: si Continental
  se reinicia a media consulta, la consulta se pierde (lo congelado ya escrito,
  no). Es el mismo trato que Doyle hace con sus trabajos y por la misma razón:
  lo que vale la pena conservar ya está en una tabla, y lo demás es el
  cascarón de una espera que se puede repetir con un clic.

## Nada de esto duerme en una prueba

El reloj y la espera **entran por argumento** (`ahora` y `dormir`). El suite
pasa un reloj que avanza cuando alguien "duerme", así que un sondeo de noventa
segundos simulados cuesta microsegundos reales. Una prueba que tardara de
verdad estaría midiendo `time.sleep`, no este código.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from continental.doyle import ClienteDeDoyle
from continental.precios import LecturaDePrecio, congelar

log = logging.getLogger("continental")

# ------------------------------------------------------- el vocabulario

#: Se le pidió a Doyle y todavía se está esperando.
EN_CURSO = "en curso"

#: Terminó y los precios quedaron escritos. Lo que haya quedado sin precio
#: tiene su motivo en la fila; "guardada" no quiere decir "con precio".
GUARDADA = "guardada"

#: No se pudo guardar nada: Doyle no contestó, o el almacenamiento rebotó. El
#: renglón queda **sin precio y la pantalla lo dice** — nunca un cero ni una
#: lista vacía (regla 4 de `CLAUDE.md`, quinta casilla del ticket).
SIN_GUARDAR = "sin guardar"

ESTADOS_DE_LA_CONSULTA: tuple[str, ...] = (EN_CURSO, GUARDADA, SIN_GUARDAR)

#: Cuánto se espera como mucho, y cada cuánto se pregunta, si el YAML no lo
#: dice. El tope va por encima del techo medido de 60-90 s: cortar en 90
#: dejaría sin precio justo las búsquedas más lentas, que son las que nadie va
#: a repetir a mano. El intervalo es el mismo que usa la propia pantalla de
#: Doyle (~1 s) y la llamada que cuesta es un GET por loopback.
TOPE_POR_OMISION_SEG = 120.0
CADA_POR_OMISION_SEG = 1.0


@dataclass(frozen=True, slots=True)
class Consulta:
    """Una consulta de precios en curso o terminada, **en memoria**.

    No es una fila: lo que se guarda en `pedidos.precio_de_proveedor` es el
    resultado. Esto es el cascarón de la espera, y existe para que la pantalla
    pueda decir "consultando…" y "no se pudo" sin inventárselo.

    Congelada y se reemplaza entera al cambiar de estado (`dataclasses.replace`),
    en vez de mutarse: el hilo que sondea y el que atiende la petición del
    navegador miran el mismo diccionario, y un objeto que se sustituye entero no
    se puede leer a medias.
    """

    renglon_id: int
    clave: str
    estado: str
    pedida_en: dt.datetime
    job_id: str = ""
    terminada_en: dt.datetime | None = None
    detalle: str = ""
    #: Cuántas filas se escribieron. Cero con estado `guardada` significa que
    #: el renglón se descartó —o dejó de existir— mientras Doyle consultaba.
    guardadas: int = 0

    @property
    def en_curso(self) -> bool:
        return self.estado == EN_CURSO


@dataclass(frozen=True, slots=True)
class ResultadoDeConsulta:
    """Lo que Doyle acabó diciendo, listo para congelarse.

    `detalle` trae el motivo cuando la espera se cortó por tiempo. Va aparte de
    las lecturas porque describe **la consulta**, no a un proveedor: cada
    proveedor ya trae el suyo dentro de su `LecturaDePrecio`.
    """

    job_id: str
    lecturas: tuple[LecturaDePrecio, ...]
    detalle: str = ""


def consultar_a_doyle(
    doyle: ClienteDeDoyle,
    clave: str,
    *,
    tope_seg: float = TOPE_POR_OMISION_SEG,
    cada_seg: float = CADA_POR_OMISION_SEG,
    dormir: Callable[[float], object] = time.sleep,
    ahora: Callable[[], float] = time.monotonic,
) -> ResultadoDeConsulta:
    """Pide la búsqueda, sondea hasta que termine o se acabe el tiempo, y lee.

    **Las dos llamadas son cortas**: pedir la búsqueda y preguntar cómo va. El
    `timeout_seg` de `config/continental.yml` cubre esas dos y nunca la espera
    entera; quien mide la espera entera es el `tope_seg` de aquí.

    `ahora` es un reloj **monótono** y no la hora del día: lo que se mide es
    cuánto tiempo ha pasado, y `datetime.now()` puede saltar hacia atrás si el
    servidor ajusta su hora — con un salto de un minuto, el tope se cumpliría
    solo o no se cumpliría nunca.

    Si se acaba el tiempo **se congela lo que haya**, no se tira: dos
    proveedores que sí contestaron son dos precios, y los otros dos quedan con
    el motivo `no alcanzó el tiempo` —que la historia 31 pide distinguir de "el
    portal falló"—. Tirar la consulta entera por los que faltaron sería perder
    lo que ya costó nueve segundos por proveedor.

    Truena si Doyle no contesta o no devuelve `job_id`: quien llama lo convierte
    en un hueco con su motivo. **No devuelve una consulta vacía fingiendo que
    salió bien**, que es la falla silenciosa que este repo prohíbe.
    """
    inicio = ahora()
    pedida = doyle.pedir_busqueda(clave)
    if not pedida.job_id:
        raise RuntimeError(
            f"Doyle aceptó la búsqueda de {clave!r} y no devolvió `job_id`. Sin "
            "él no hay a qué preguntarle: se falla aquí en vez de congelar "
            "cuatro huecos y llamarlo consulta."
        )

    while True:
        estado = doyle.estado_de_busqueda(pedida.job_id)
        if estado.terminada:
            # Se empareja contra la `clave` con la que se pidió la búsqueda, no
            # contra el `termino` que Doyle repite: contra qué se compara no lo
            # decide el otro proceso (ticket 13).
            return ResultadoDeConsulta(pedida.job_id, congelar(estado, clave))

        transcurrido = ahora() - inicio
        if transcurrido >= tope_seg:
            if not estado.proveedores:
                # Ni un proveedor en la respuesta después de esperar el tope
                # entero: no es "tardó", es que no hay qué congelar. Se truena
                # para que salga como hueco con su motivo, porque congelar cero
                # lecturas y decir `guardada` sería llamar éxito a una consulta
                # que no preguntó nada.
                raise RuntimeError(
                    f"Doyle no dijo qué proveedores está consultando en el "
                    f"trabajo {pedida.job_id!r} después de {tope_seg:g} s."
                )
            return ResultadoDeConsulta(
                pedida.job_id,
                congelar(estado, clave),
                detalle=(
                    f"Doyle no terminó en {tope_seg:g} s. Lo que alcanzó a "
                    "contestar quedó guardado; el resto se puede volver a "
                    "consultar."
                ),
            )

        dormir(cada_seg)


# ----------------------------------------------------- quién lanza el hilo


def _en_un_hilo(tarea: Callable[[], object]) -> None:
    """Lanza la tarea en un hilo suelto y vuelve de inmediato.

    `daemon=True` a propósito: una consulta a medias no puede impedir que el
    servicio se apague. Lo que ya se guardó está en una tabla, y lo que no, se
    repite con un clic — hacer que `systemctl restart` espere noventa segundos
    por un renglón sería peor.
    """
    threading.Thread(target=tarea, daemon=True).start()


@dataclass
class RegistroDeConsultas:
    """Qué consultas hay en vuelo, para toda la aplicación.

    Es un objeto de proceso y no de petición, y ésa es la diferencia con los
    otros tres bordes: el almacén y Doyle se construyen por llamada porque no
    recuerdan nada, y esto existe precisamente **para recordar** —que ya se le
    está preguntando a Doyle por este renglón, y que la petición anterior
    terminó mal—.

    `lanzar` se sustituye en las pruebas por uno que ejecuta ahí mismo: el
    suite no arranca hilos, así que no hay nada que sincronizar ni que esperar,
    y una prueba que fallara no dejaría un hilo vivo contaminando a la
    siguiente.

    El candado no es decorativo: el hilo que sondea escribe el estado final
    mientras el hilo que atiende la petición del navegador lo lee.
    """

    lanzar: Callable[[Callable[[], object]], object] = _en_un_hilo
    _consultas: dict[int, Consulta] = field(default_factory=dict)
    _candado: threading.Lock = field(default_factory=threading.Lock)

    def de(self, renglon_id: int) -> Consulta | None:
        """La última consulta de ese renglón, en curso o terminada. `None` si nunca."""
        with self._candado:
            return self._consultas.get(renglon_id)

    def pedir(
        self, renglon_id: int, clave: str, tarea: Callable[[Consulta], object]
    ) -> tuple[Consulta, bool]:
        """Arranca una consulta, **salvo que ya haya una en vuelo**.

        Devuelve la consulta y si es nueva. El segundo dato es lo que deja a la
        ruta decir "ya se está consultando" en vez de fingir que lanzó algo:
        una pantalla que dice "pedido" dos veces para una sola visita al portal
        es una pantalla que miente.

        **La decisión de no lanzar se toma dentro del candado**, junto con la
        de registrar la nueva. Comprobar fuera y lanzar después tiene una
        carrera en medio, y dos pestañas en el mostrador bastan para colarse
        por ahí — y ahí la carrera no cuesta una fila duplicada, cuesta cuatro
        visitas de más a los portales del dueño.
        """
        with self._candado:
            previa = self._consultas.get(renglon_id)
            if previa is not None and previa.en_curso:
                return previa, False

            consulta = Consulta(
                renglon_id=renglon_id,
                clave=clave,
                estado=EN_CURSO,
                # Instante con zona: dice CUÁNDO PASÓ ALGO AQUÍ, que es lo que
                # un reloj sabe y el almacén no. Lo que se ancla en
                # `max(fecha)` son las fechas de venta.
                pedida_en=dt.datetime.now(dt.UTC),
            )
            self._consultas[renglon_id] = consulta

        self.lanzar(lambda: tarea(consulta))
        return consulta, True

    def terminar(
        self,
        consulta: Consulta,
        estado: str,
        *,
        job_id: str = "",
        detalle: str = "",
        guardadas: int = 0,
    ) -> Consulta:
        """Deja escrito cómo acabó. Sustituye la consulta entera, no la muta."""
        terminada = replace(
            consulta,
            estado=estado,
            job_id=job_id or consulta.job_id,
            terminada_en=dt.datetime.now(dt.UTC),
            detalle=detalle,
            guardadas=guardadas,
        )
        with self._candado:
            self._consultas[consulta.renglon_id] = terminada
        return terminada


# ------------------------------------------- consultar y dejarlo guardado


def consultar_y_congelar(
    consulta: Consulta,
    *,
    doyle: ClienteDeDoyle,
    almacenamiento,
    registro: RegistroDeConsultas,
    negocio: str,
    tope_seg: float = TOPE_POR_OMISION_SEG,
    cada_seg: float = CADA_POR_OMISION_SEG,
    dormir: Callable[[float], object] = time.sleep,
    ahora: Callable[[], float] = time.monotonic,
) -> Consulta:
    """La tarea entera: esperar a Doyle, congelar lo que dijo, y anotar cómo fue.

    Corre **fuera de la petición HTTP** —en un hilo, o ahí mismo en una prueba—
    así que aquí no hay `Request` ni `JSONResponse`: lo que produce es una fila
    y una anotación en el registro.

    Los dos bordes se atienden por separado y ninguna falla se escapa hacia
    arriba: una excepción en un hilo suelto no la ve nadie, así que aquí se
    atrapa, se escribe entera en la bitácora y se convierte en un estado que la
    pantalla puede leer. El motivo que viaja es el **tipo** de la falla y nunca
    su texto (regla 5 de `CLAUDE.md`): un `str(exc)` de SQLAlchemy lleva la
    cadena de conexión con contraseña.
    """
    try:
        resultado = consultar_a_doyle(
            doyle,
            consulta.clave,
            tope_seg=tope_seg,
            cada_seg=cada_seg,
            dormir=dormir,
            ahora=ahora,
        )
    except Exception as exc:  # noqa: BLE001 — Doyle caído es un hueco con su motivo
        log.exception(
            "Doyle no pudo consultar el precio del renglón %s (clave %s)",
            consulta.renglon_id,
            consulta.clave,
        )
        return registro.terminar(
            consulta,
            SIN_GUARDAR,
            detalle=f"Doyle no contestó ({type(exc).__name__})",
        )

    try:
        guardadas = almacenamiento.guardar_precios(
            negocio, consulta.renglon_id, resultado.lecturas
        )
    except Exception as exc:  # noqa: BLE001 — el almacenamiento caído tampoco es un 500
        log.exception(
            "No se pudieron guardar los precios del renglón %s", consulta.renglon_id
        )
        return registro.terminar(
            consulta,
            SIN_GUARDAR,
            job_id=resultado.job_id,
            detalle=f"no se pudo guardar el precio ({type(exc).__name__})",
        )

    if not guardadas:
        # Cero filas: el renglón ya no estaba cuando Doyle terminó. Se dice en
        # vez de callarse — "guardada" con cero precios se leería como "el
        # producto no está en ningún catálogo".
        log.info(
            "Los precios del renglón %s no se guardaron: no hay ese renglón en "
            "%s. Se consultó y se perdió; puede que la lista sea de otro "
            "negocio.",
            consulta.renglon_id,
            negocio,
        )
        return registro.terminar(
            consulta,
            SIN_GUARDAR,
            job_id=resultado.job_id,
            detalle="ese renglón ya no está en la lista",
        )

    log.info(
        "Precios del renglón %s (clave %s) congelados: %d proveedor(es), "
        "%d con precio. Trabajo de Doyle %s.%s",
        consulta.renglon_id,
        consulta.clave,
        guardadas,
        sum(1 for lectura in resultado.lecturas if not lectura.sin_dato),
        resultado.job_id,
        f" {resultado.detalle}" if resultado.detalle else "",
    )
    return registro.terminar(
        consulta,
        GUARDADA,
        job_id=resultado.job_id,
        detalle=resultado.detalle,
        guardadas=guardadas,
    )


# ---------------------------------------------------- lo que dice el YAML


def ajustes_de_la_consulta() -> tuple[float, float]:
    """`(tope_seg, cada_seg)` de `config/continental.yml`.

    La misma capa delgada que `dias_primera_vez_configurados`: los números son
    una decisión de operación —cuánto se le permite tardar a un portal ajeno— y
    viven en el YAML versionado con su comentario, no en una constante de
    Python que se quedaría desincronizada el día que el dueño los cambie.

    Un valor que falte o no sirva cae al de omisión **y se avisa**. Tronar aquí
    dejaría a la farmacia sin poder consultar un precio por una línea que falta
    en el YAML, y eso es peor que consultar con el número de omisión.
    """
    from continental.config import cargar

    crudo = cargar().pedido.get("consulta_de_precio") or {}
    return (
        _numero_positivo(crudo.get("tope_seg"), TOPE_POR_OMISION_SEG, "tope_seg"),
        _numero_positivo(crudo.get("cada_seg"), CADA_POR_OMISION_SEG, "cada_seg"),
    )


def _numero_positivo(crudo, omision: float, nombre: str) -> float:
    try:
        valor = float(crudo)
    except (TypeError, ValueError):
        valor = 0.0

    if valor <= 0:
        log.warning(
            "config/continental.yml no trae un `pedido.consulta_de_precio.%s` "
            "utilizable (%r). Se usa %g. Agrégalo al YAML para que la espera "
            "sea la que el negocio quiere.",
            nombre,
            crudo,
            omision,
        )
        return omision
    return valor


def lecturas_como_json(lecturas: Sequence) -> list[dict]:
    """Lecturas congeladas → lo que la pantalla lee. Vive aquí y no en el JS.

    `precio` viaja como **cadena** y no como número de JSON, y eso no es
    pedantería: el JSON de JavaScript solo tiene `double`, así que mandar
    `86.05` como número lo mete en coma flotante justo en el borde donde
    acababa de salir. Como cadena se pinta tal cual y el día que el ticket 14
    sume ahorros, va a sumar con la cifra exacta.

    `null` es **"no se sabe"** y siempre viene con su `motivo`. Nunca un cero:
    un cero gana toda comparación de "el más barato" y dispara la compra
    equivocada (regla 4).
    """
    from continental.precios import nombre_del_proveedor

    return [
        {
            "proveedor": lectura.proveedor,
            "nombre": nombre_del_proveedor(lectura.proveedor),
            "consultado_en": lectura.consultado_en.isoformat(),
            "precio": None if lectura.precio is None else str(lectura.precio),
            "precio_como_llego": lectura.precio_como_llego,
            "existencia": (
                None if lectura.existencia is None else str(lectura.existencia)
            ),
            "existencia_como_llego": lectura.existencia_como_llego,
            "sin_dato": lectura.sin_dato,
            "motivo": lectura.motivo,
            "detalle": lectura.detalle,
            "clave_del_proveedor": lectura.clave_del_proveedor,
            "descripcion_del_proveedor": lectura.descripcion_del_proveedor,
            "resultados": lectura.resultados,
        }
        for lectura in lecturas
    ]
