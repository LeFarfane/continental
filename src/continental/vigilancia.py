"""La pestaña de Vigilancia: lo que falta, y el aviso cuando aparece.

Doyle la tenía en su propia web (su ADR 0007): productos que hacen falta y hoy
ningún proveedor tiene; Doyle los busca solo a las 9:30 y a las 19:30 y los
marca `disponible` en cuanto alguno aparece. Se quedó sin pantalla el
2026-09-21, igual que Buscar, cuando Doyle se mudó a atlas sin interfaz (su
ADR 0008). **Continental la dibuja; la lista, el reloj y las búsquedas siguen
siendo de Doyle** —en su SQLite y en su hilo—, así que nada de esto guarda
nada en `pedidos`.

Medido el 2026-09-28 en atlas: la lista está **vacía** (0 artículos), así que
el hilo de Doyle despierta a sus horas y no visita ningún portal; y atlas
corre en `America/Mexico_City`, así que las 9:30 y 19:30 de Doyle son hora de
la farmacia, y sus instantes sin zona también.

Dos mitades:

- **Las frases**, puras: el artículo de Doyle → lo que dice su renglón en la
  pantalla. La pantalla no compone lo que afirma (tickets 15 y 21).
- **El registro de «Revisar ahora»**, con estado de proceso: Doyle bloquea esa
  petición minutos enteros (una visita por artículo y proveedor), más de lo
  que el túnel aguanta, así que Continental la hace en un hilo y la pantalla
  pregunta cómo va. Es el mismo trato que `consultas.RegistroDeConsultas`.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from continental.doyle import ArticuloVigilado
from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor, recortar_el_mensaje
from continental.transito import ZONA_DE_LA_FARMACIA, fecha_en_palabras

log = logging.getLogger("continental")

# ------------------------------------------------------------- las frases

#: El vocabulario de Doyle (`estado`) → la etiqueta del renglón. Tres palabras
#: cortas; la frase de al lado dice el resto.
ETIQUETA_DEL_ESTADO: dict[str, str] = {
    "pendiente": "sin revisar",
    "disponible": "ya hay",
    "agotado": "no hay",
}

#: Cada cuánto pregunta la pantalla mientras Doyle revisa. Una revisión son
#: minutos; cada cinco segundos alcanza para verla terminar sin martillar.
SONDEO_DE_LA_REVISION_MS = 5000

HORAS_DE_DOYLE = "a las 9:30 y a las 19:30"


def instante_de_doyle_en_palabras(texto: str | None) -> str | None:
    """Un instante de Doyle → "el lunes 28 de septiembre a las 09:30".

    Doyle escribe `datetime.now().isoformat()`, **sin zona**, en la hora de la
    máquina donde corre, que en atlas es la de la farmacia (medido el
    2026-09-28). Uno que sí trajera zona se pasa a la de la farmacia. Uno que
    no se pueda leer se enseña tal cual: mejor el texto crudo que una fecha
    inventada.
    """
    if not texto:
        return None
    try:
        instante = dt.datetime.fromisoformat(texto)
    except ValueError:
        return texto
    if instante.tzinfo is not None:
        instante = instante.astimezone(ZONA_DE_LA_FARMACIA)
    return f"{fecha_en_palabras(instante.date())} a las {instante:%H:%M}"


def _en_cuales(proveedores: Iterable[str]) -> str:
    nombres = [nombre_del_proveedor(p) for p in proveedores]
    if not nombres:
        return "en los cuatro proveedores"
    if len(nombres) == 1:
        return f"solo en {nombres[0]}"
    return "en " + ", ".join(nombres[:-1]) + " y " + nombres[-1]


def frase_del_articulo(a: ArticuloVigilado) -> str:
    """Qué se sabe de ese artículo, en dos o tres oraciones."""
    donde = f"Se vigila {_en_cuales(a.proveedores)}."
    revisado = instante_de_doyle_en_palabras(a.ultima_revision)
    if revisado is None:
        return (
            f"{donde} Todavía no se revisa: Doyle lo hace {HORAS_DE_DOYLE}, o "
            "cuando alguien aprieta «Revisar ahora»."
        )
    if a.estado == "disponible":
        desde = instante_de_doyle_en_palabras(a.disponible_desde)
        return (
            f"{donde} Ya hay en al menos uno"
            + (f", desde {desde}" if desde else "")
            + ". Doyle no guarda en cuál: búscalo para ver dónde y a cómo."
            + f" Última revisión: {revisado}."
        )
    if a.estado == "agotado":
        return (
            f"{donde} En la última revisión, {revisado}, ninguno de los que "
            "contestaron lo tenía disponible."
        )
    # Un estado que Doyle estrene mañana se dice tal cual, no se esconde.
    return f"{donde} Doyle dice «{a.estado}». Última revisión: {revisado}."


def frase_del_error(a: ArticuloVigilado) -> str | None:
    """Lo que falló en la última revisión, si algo falló.

    **Si ningún proveedor contestó, Doyle no toca el estado** (su ADR 0007: no
    marca "agotado" lo que no se pudo ni consultar), así que la etiqueta puede
    ser de una revisión anterior. Se dice, porque "no hay" sobre una revisión
    que no llegó a ningún portal se lee como un hecho.
    """
    if not a.ultimo_error:
        return None
    return (
        "En la última revisión no todos contestaron, así que lo de arriba puede "
        f"venir de una revisión anterior. Doyle dijo: {recortar_el_mensaje(a.ultimo_error)}"
    )


def articulo_como_json(a: ArticuloVigilado) -> dict:
    return {
        "articulo_id": a.articulo_id,
        "termino": a.termino,
        "estado": a.estado,
        "etiqueta": ETIQUETA_DEL_ESTADO.get(a.estado, a.estado),
        "disponible": a.estado == "disponible",
        # El aviso de "ya hay" que nadie ha visto: es lo que sale arriba de
        # las pestañas y lo que apaga «Ya lo vi».
        "aviso_pendiente": a.estado == "disponible" and not a.avisado,
        "frase": frase_del_articulo(a),
        "error": frase_del_error(a),
    }


#: Una lista vacía, dicha: Doyle contestó y no tiene nada. No es lo mismo que
#: no poder leerla, que sale como falla con su qué hacer.
FRASE_SIN_ARTICULOS = (
    "No hay nada en la vigilancia. Agrega un producto que hoy no tenga "
    "ningún proveedor y Doyle avisa aquí cuando aparezca."
)


def frase_de_los_avisos(articulos: Iterable[ArticuloVigilado]) -> str | None:
    """El aviso de arriba de las pestañas: lo que ya hay y nadie ha visto."""
    nuevos = [a.termino for a in articulos if a.estado == "disponible" and not a.avisado]
    if not nuevos:
        return None
    return f"Ya hay de lo que se vigilaba: {', '.join(nuevos)}. Míralo en Vigilancia."


def proveedores_para_elegir() -> list[dict]:
    """Los cuatro, con el nombre del glosario, para las casillas de la pantalla."""
    return [{"proveedor": c, "nombre": n} for c, n in NOMBRES_DE_PROVEEDOR.items()]


def motivo_de_proveedores_desconocidos(proveedores: Iterable[str]) -> str | None:
    """Si llegó una clave que no es de ningún proveedor. Doyle las filtraría en
    silencio, y un artículo "vigilado en QPharma" quedaría vigilado en los
    cuatro sin que nadie lo supiera."""
    desconocidos = sorted(set(proveedores) - set(NOMBRES_DE_PROVEEDOR))
    if not desconocidos:
        return None
    return f"No hay ningún proveedor llamado {', '.join(desconocidos)}."


# ------------------------------------------------- «Revisar ahora», en un hilo


@dataclass(frozen=True, slots=True)
class Revision:
    """Una revisión pedida desde Continental, en curso o terminada. **En memoria.**

    Lo que la revisión produce vive en Doyle —el estado de cada artículo—;
    esto es solo el cascarón de la espera, para que la pantalla pueda decir
    "revisando desde las 10:14" y "no terminó" sin inventárselo. Si Continental
    se reinicia a la mitad se pierde el cascarón, no la revisión: Doyle sigue.
    """

    pedida_por: str
    pedida_en: dt.datetime
    terminada_en: dt.datetime | None = None
    ok: bool | None = None
    #: El TIPO de la falla, nunca su texto (regla 5).
    detalle: str = ""

    @property
    def en_curso(self) -> bool:
        return self.terminada_en is None


def _en_un_hilo(tarea: Callable[[], object]) -> None:
    """Un hilo suelto, `daemon` por lo mismo que `consultas._en_un_hilo`: una
    revisión a medias no puede impedir que el servicio se apague."""
    threading.Thread(target=tarea, daemon=True, name="continental-vigilancia").start()


def _ahora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class RegistroDeRevision:
    """La última revisión pedida desde aquí, para todo el proceso.

    **Una a la vez.** Mientras una está en curso, pedir otra devuelve esa
    misma: dos clics serían dos pasadas completas por los portales del dueño.
    La decisión se toma dentro del candado, por la carrera que ya describe
    `consultas.RegistroDeConsultas.apartar`.

    Lo que no puede saber: si Doyle está en su propia revisión de las 9:30. Su
    API no lo dice. Las dos se estorban poco —Doyle serializa por proveedor
    (su ADR 0007)— y lo peor que pasa es una pasada de más.
    """

    lanzar: Callable[[Callable[[], object]], object] = _en_un_hilo
    ahora: Callable[[], dt.datetime] = _ahora
    _ultima: Revision | None = None
    _candado: threading.Lock = field(default_factory=threading.Lock)

    def ultima(self) -> Revision | None:
        with self._candado:
            return self._ultima

    def pedir(self, quien: str, tarea: Callable[[], object]) -> tuple[Revision, bool]:
        """Arranca la revisión, salvo que ya haya una en curso. Devuelve la
        revisión y si es nueva."""
        with self._candado:
            if self._ultima is not None and self._ultima.en_curso:
                return self._ultima, False
            revision = Revision(pedida_por=quien, pedida_en=self.ahora())
            self._ultima = revision
        self.lanzar(lambda: self._correr(revision, tarea))
        return revision, True

    def _correr(self, revision: Revision, tarea: Callable[[], object]) -> None:
        try:
            tarea()
        except Exception as exc:  # noqa: BLE001 — la falla se guarda y se dice; el hilo no truena
            log.exception("La revisión de la vigilancia pedida por %s no terminó", revision.pedida_por)
            final = replace(
                revision,
                terminada_en=self.ahora(),
                ok=False,
                detalle=f"Doyle no terminó la revisión ({type(exc).__name__})",
            )
        else:
            final = replace(revision, terminada_en=self.ahora(), ok=True)
        with self._candado:
            if self._ultima is revision:
                self._ultima = final


def _hora(instante: dt.datetime) -> str:
    return f"{instante.astimezone(ZONA_DE_LA_FARMACIA):%H:%M}"


def revision_como_json(revision: Revision | None, que_hacer_si_fallo: str) -> dict | None:
    """Cómo va «Revisar ahora», dicho. `None` si no se ha pedido desde que
    arrancó Continental."""
    if revision is None:
        return None
    if revision.en_curso:
        return {
            "en_curso": True,
            "ok": None,
            "frase": (
                f"Doyle está revisando la lista desde las {_hora(revision.pedida_en)} "
                f"(la pidió {revision.pedida_por}). Tarda unos segundos por artículo "
                "y proveedor; esta pantalla se pone al día sola."
            ),
            "sondeo_ms": SONDEO_DE_LA_REVISION_MS,
        }
    if revision.ok:
        return {
            "en_curso": False,
            "ok": True,
            "frase": (
                f"La revisión que se pidió a las {_hora(revision.pedida_en)} terminó "
                f"a las {_hora(revision.terminada_en)}."
            ),
        }
    return {
        "en_curso": False,
        "ok": False,
        "detalle": revision.detalle,
        "frase": (
            f"La revisión que se pidió a las {_hora(revision.pedida_en)} no terminó: "
            "lo de abajo es lo que Doyle alcanzó a escribir."
        ),
        "que_hacer": que_hacer_si_fallo,
    }
