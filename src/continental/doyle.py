"""El otro borde: lo que Continental le pregunta a Doyle por HTTP.

Está aparte de la lectura del almacén a propósito. Son dos cosas que fallan por
razones distintas —una base que no contesta no es un portal de proveedor con la
sesión caducada— y una prueba tiene que poder sustituir una sola. Regla 1 de
`CLAUDE.md`: aquí no se abre un navegador nunca; el que scrapea es Doyle.

**La búsqueda se pide y se consulta después, en dos llamadas cortas.** No es
un capricho de estilo: una búsqueda en un portal tiene un piso medido de ~9 s
por proveedor (5.6 s de scroll de carga diferida más 3 s de cortesía) y un
techo de 60-90 s si se estiran los timeouts. Por eso Doyle devuelve un `job_id`
y el `timeout_seg` de `config/continental.yml` solo cubre las llamadas cortas.

**Los precios viajan como texto, tal cual los dio el portal.** Convertirlos a
`float` aquí obligaría a inventar un `0.0` para el hueco, y un cero se lee como
"el más barato" y dispara una compra equivocada — regla 4 de `CLAUDE.md`. Quien
decida qué es un precio válido es el emparejamiento por EAN, que sí puede decir
"sin dato" con su motivo.

**Nada se conecta al importar este archivo:** el cliente HTTP nace por llamada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

# ------------------------------------------------------------------- datos


@dataclass(frozen=True, slots=True)
class FilaDeProveedor:
    """Un resultado del portal de un proveedor, tal cual lo entregó Doyle.

    `clave` es lo que el portal muestra como código: NADRO y LEVIC dan el EAN
    de 13 dígitos, VICMA da código interno pero sí indexa el EAN, y QuePharma
    usa código interno. Solo empareja lo que coincide por EAN (ADR 0002): una
    caja de 60 comparada contra una de 30 se ve más cara y no lo es.

    `advertencia` es lo que Doyle notó al leer la fila —varios precios sin
    tachar, por ejemplo—. Viaja hasta la pantalla: un dato con reserva es
    información, un dato limpio que no lo era es una decisión mal tomada.
    """

    clave: str
    descripcion: str
    precio: str  # precio de COMPRA, texto; "" es "sin dato", nunca 0
    precio_publico: str
    existencia: str
    advertencia: str = ""


#: Los estados en los que un proveedor **todavía no terminó**, con el
#: vocabulario exacto de Doyle.
#:
#: Son DOS y no uno, y eso está medido contra el Doyle real el 2026-09-19: el
#: trabajo nace con `pendiente` (`iniciar_busqueda` lo pone al crear el
#: diccionario) y el hilo lo cambia a **`buscando`** en cuanto arranca
#: (`_buscar_en_hilo`, primera línea). Los ~9 s de una búsqueda se pasan casi
#: enteros en `buscando`, no en `pendiente`.
#:
#: Antes de este ticket `terminada` preguntaba solo por `pendiente`, así que
#: contra el Doyle real habría dado **cierto en la primera vuelta** —con los
#: cuatro proveedores todavía abriendo el portal— y el precio se habría
#: congelado como cuatro huecos. Un lote en verde que no consultó nada: la
#: falla silenciosa exacta que la regla 4 de `CLAUDE.md` prohíbe.
ESTADOS_PENDIENTES: tuple[str, ...] = ("pendiente", "buscando")


@dataclass(frozen=True, slots=True)
class RespuestaDeProveedor:
    """Cómo le fue a un proveedor dentro de una búsqueda.

    `estado` vale `pendiente`, `buscando`, `listo`, `reconocimiento` o `error`,
    con el mismo vocabulario que usa Doyle y **sin traducirlo**: decir
    `pendiente` donde Doyle dijo `buscando` sería inventar un segundo nombre
    para lo mismo, que es justo lo que el repo prohíbe. Quien necesita saber si
    todavía no terminó pregunta por `ESTADOS_PENDIENTES`.

    `mensaje` es el motivo cuando no hay dato: sesión caducada, el portal no
    contestó, o que Doyle todavía no sabe leer esa página. Sin motivo, el
    encargado no puede saber si lo puede resolver él (historia 23 del spec).
    """

    proveedor: str
    estado: str
    filas: tuple[FilaDeProveedor, ...] = ()
    total: int = 0
    mensaje: str = ""

    @property
    def sin_dato(self) -> bool:
        return self.estado != "listo" or not self.filas


@dataclass(frozen=True, slots=True)
class BusquedaPedida:
    """Lo que se recibe al pedir una búsqueda: un acuse, no un resultado."""

    job_id: str
    proveedores: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EstadoDeBusqueda:
    """La foto de una búsqueda en curso, proveedor por proveedor."""

    termino: str
    proveedores: dict[str, RespuestaDeProveedor] = field(default_factory=dict)

    @property
    def terminada(self) -> bool:
        """Cierto cuando ningún proveedor sigue pendiente.

        Un proveedor en `error` cuenta como terminado: el lote nocturno tiene
        un tope de 60 minutos y esperar a algo que ya falló es gastarlo.

        **Una búsqueda sin proveedores NO está terminada**, y eso no es
        pedantería sobre el `all()` de una colección vacía: Doyle contesta con
        los cuatro proveedores en cuanto existe el trabajo, así que un
        diccionario vacío significa que la respuesta no trae lo que debía —otra
        versión, un cuerpo recortado—. Declararla terminada congelaría cero
        precios y lo llamaría éxito, que es la falla silenciosa que la regla 4
        de `CLAUDE.md` prohíbe. Quien espera lo distingue y lo dice.
        """
        return bool(self.proveedores) and all(
            r.estado not in ESTADOS_PENDIENTES for r in self.proveedores.values()
        )


@dataclass(frozen=True, slots=True)
class SesionDeProveedor:
    """El estado de la sesión de un proveedor en Doyle.

    `estado` vale `guardada`, `sin_sesion` o `abriendo`. Sin esto, una sesión
    caducada se ve desde Continental como un precio que simplemente no llegó, y
    el encargado no tiene forma de saber que lo arregla él en dos clics.
    """

    proveedor: str
    nombre: str
    estado: str
    guardada_en: str | None = None


@dataclass(frozen=True, slots=True)
class SesionAbriendose:
    """Doyle dejó un navegador esperando. **Todavía no hay sesión.**

    `ya_abierta` es verdadero cuando ya había una ventana de ese proveedor
    esperando de antes —alguien apretó el botón dos veces, o dos pestañas del
    mostrador lo apretaron a la vez—. **No es un error y no se le dice como
    tal**: es la misma ventana, y abrir una segunda dejaría dos Chromes
    peleándose por el mismo login.

    Que este objeto exista **no quiere decir que la sesión sirva**, y eso es lo
    que hay que no olvidar: lo que hace servible una sesión es que alguien
    teclee la contraseña y se confirme. El 2026-09-19 los cuatro proveedores
    decían `guardada` con las cuatro sesiones caducadas.
    """

    proveedor: str
    ya_abierta: bool = False


@dataclass(frozen=True, slots=True)
class SesionConfirmada:
    """La persona ya entró y Doyle guardó las cookies.

    `todavia_parece_login` es el aviso honesto de Doyle: confirma de todos
    modos —la redirección puede no haber terminado cuando se dio el clic— y
    dice que la página seguía viéndose como un login. Viaja hasta la pantalla
    porque es la diferencia entre "ya está" y "vuelve a intentarlo", y
    esconderlo dejaría al encargado creyendo que abrió una sesión que no abrió.
    """

    proveedor: str
    todavia_parece_login: bool = False


# --------------------------------------------------------------- interfaz


@runtime_checkable
class ClienteDeDoyle(Protocol):
    """El borde hacia Doyle. Cinco verbos y ninguno más.

    Eran tres hasta el ticket 19. Los dos nuevos —`abrir_sesion` y
    `confirmar_sesion`— son las dos mitades de un solo acto del encargado, y
    **no rompen la regla 1 de `CLAUDE.md`**: Continental sigue sin tocar un
    navegador. Lo que hace es pedírselo a Doyle por HTTP, que es exactamente
    lo que la regla manda hacer cuando una pantalla necesita algo de un portal.
    El navegador lo abre Doyle, en la máquina donde Doyle corre, y quien teclea
    la contraseña es una persona (ADR 0001 de Doyle, sin cambios).

    Son **dos** peticiones y no una porque en medio hay un humano: la primera
    deja el navegador esperando y vuelve de inmediato —abrirlo tarda, y la
    sesión no está lista cuando vuelve—, y la segunda se manda cuando esa
    persona ya entró. Es el mismo reparto que Doyle usa en su propia pantalla.
    """

    def pedir_busqueda(self, termino: str) -> BusquedaPedida:
        """Lanza la búsqueda en los proveedores y devuelve el acuse."""
        ...

    def estado_de_busqueda(self, job_id: str) -> EstadoDeBusqueda:
        """Cómo va esa búsqueda. Llamada corta: no espera a que termine."""
        ...

    def sesiones(self) -> list[SesionDeProveedor]:
        """Qué proveedores tienen sesión viva en Doyle."""
        ...

    def abrir_sesion(self, proveedor: str) -> SesionAbriendose:
        """Le pide a Doyle que abra el navegador del login de ese proveedor.

        **Vuelve de inmediato y la sesión NO está lista.** Lo que queda abierto
        es una ventana de Chrome esperando a que una persona teclee usuario y
        contraseña; hasta que alguien confirme, el portal sigue mandando al
        login y el motivo `la sesión caducó` sigue siendo verdad.
        """
        ...

    def confirmar_sesion(self, proveedor: str) -> SesionConfirmada:
        """Le dice a Doyle que la persona ya entró: guarda las cookies y cierra.

        Es la otra mitad, y la que de verdad deja la sesión servible: Doyle
        exporta las cookies **antes** de cerrar el navegador, porque Chrome
        tira las de sesión al cerrarse y portales como LEVIC quedarían sin
        sesión aunque alguien acabara de entrar (ADR 0006 de Doyle).
        """
        ...


# --------------------------------------------------------- implementación


class DoylePorHttp:
    """`ClienteDeDoyle` contra el Doyle real, en loopback.

    Síncrono a propósito, aunque `/api/modulos` use `httpx.AsyncClient`: el otro
    borde es SQLAlchemy con psycopg2, que no es asíncrono, y tener dos estilos
    de borde obligaría a cada consumidor a saber cuál le tocó. FastAPI corre las
    rutas `def` en su pool de hilos, así que una llamada lenta no bloquea el
    bucle.
    """

    def __init__(self, url: str, timeout_seg: float = 10.0):
        self._url = url.rstrip("/")
        self._timeout = timeout_seg

    def _cliente(self) -> httpx.Client:
        # Por llamada, no en `__init__`: construir este objeto no debe abrir
        # nada, ni siquiera un pool de conexiones ocioso.
        return httpx.Client(base_url=self._url, timeout=self._timeout)

    def pedir_busqueda(self, termino: str) -> BusquedaPedida:
        with self._cliente() as cliente:
            cuerpo = cliente.post("/api/buscar", json={"termino": termino})
        cuerpo.raise_for_status()
        datos = cuerpo.json()
        return BusquedaPedida(
            job_id=str(datos.get("job_id", "")),
            proveedores=tuple(datos.get("proveedores") or ()),
        )

    def estado_de_busqueda(self, job_id: str) -> EstadoDeBusqueda:
        with self._cliente() as cliente:
            respuesta = cliente.get(f"/api/buscar/{job_id}")
        respuesta.raise_for_status()
        datos = respuesta.json()
        return EstadoDeBusqueda(
            termino=str(datos.get("termino", "")),
            proveedores={
                clave: _leer_respuesta(clave, crudo)
                for clave, crudo in (datos.get("proveedores") or {}).items()
            },
        )

    def sesiones(self) -> list[SesionDeProveedor]:
        with self._cliente() as cliente:
            respuesta = cliente.get("/api/sesiones")
        respuesta.raise_for_status()
        return [
            SesionDeProveedor(
                proveedor=clave,
                nombre=str(datos.get("nombre") or clave),
                estado=str(datos.get("estado") or "sin_sesion"),
                guardada_en=datos.get("guardada_en"),
            )
            for clave, datos in sorted((respuesta.json() or {}).items())
        ]

    def abrir_sesion(self, proveedor: str) -> SesionAbriendose:
        # `POST` y sin cuerpo, que es como Doyle lo expone
        # (`POST /api/sesion/{clave}/abrir`). El `raise_for_status` importa:
        # Doyle contesta 400 cuando la clave no es de un proveedor suyo, y sin
        # esto un proveedor mal escrito se vería como una sesión abriéndose.
        with self._cliente() as cliente:
            respuesta = cliente.post(f"/api/sesion/{proveedor}/abrir")
        respuesta.raise_for_status()
        datos = respuesta.json() or {}
        return SesionAbriendose(
            proveedor=proveedor, ya_abierta=bool(datos.get("ya_abierta"))
        )

    def confirmar_sesion(self, proveedor: str) -> SesionConfirmada:
        with self._cliente() as cliente:
            respuesta = cliente.post(f"/api/sesion/{proveedor}/confirmar")
        respuesta.raise_for_status()
        datos = respuesta.json() or {}
        return SesionConfirmada(
            proveedor=proveedor,
            todavia_parece_login=bool(datos.get("todavia_parece_login")),
        )


def _leer_respuesta(proveedor: str, crudo: dict) -> RespuestaDeProveedor:
    """Traduce lo que Doyle contesta por proveedor.

    Doyle mezcla dos formas en la misma clave: el estado del hilo (`pendiente`,
    `listo`, `error`) y, cuando terminó, el resultado con su `modo`. El modo
    `reconocimiento` significa "todavía no sé leer esta página": no es un fallo
    del portal y no se puede confundir con uno, porque lo primero se arregla
    escribiendo selectores y lo segundo volviendo a intentar.
    """
    estado = str(crudo.get("estado") or "pendiente")
    if estado == "error":
        return RespuestaDeProveedor(
            proveedor=proveedor, estado="error", mensaje=str(crudo.get("mensaje") or "")
        )
    if estado != "listo":
        return RespuestaDeProveedor(proveedor=proveedor, estado=estado)

    if crudo.get("modo") == "reconocimiento":
        return RespuestaDeProveedor(
            proveedor=proveedor,
            estado="reconocimiento",
            mensaje="Doyle todavía no sabe leer esta página",
        )

    filas = tuple(
        FilaDeProveedor(
            clave=str(f.get("clave") or ""),
            descripcion=str(f.get("descripcion") or ""),
            precio=str(f.get("precio") or ""),
            precio_publico=str(f.get("precio_publico") or ""),
            existencia=str(f.get("existencia") or ""),
            advertencia=str(f.get("advertencia") or ""),
        )
        for f in (crudo.get("filas") or ())
    )
    return RespuestaDeProveedor(
        proveedor=proveedor,
        estado="listo",
        filas=filas,
        # `total` es cuántas encontró el portal y `filas` cuántas trajo Doyle
        # (corta en 20). VICMA solo se acepta con EXACTAMENTE un resultado, así
        # que esa diferencia decide y no se puede perder aquí.
        total=int(crudo.get("total") or len(filas)),
    )
