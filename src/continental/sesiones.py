"""La pestaña de Sesiones: el «Inicio» de Doyle, sin creerle a `guardada`.

Doyle tenía en su web una pestaña de Inicio con una tarjeta por portal —sin
sesión, guardada, abriendo— y los botones para abrirla, confirmarla o cancelar.
Se quedó sin pantalla el 2026-09-21 con el resto de su interfaz (su ADR 0008);
la pidió el dueño el 2026-09-28.

**Lo único que se cambia al absorberla es qué se afirma.** Doyle dice
`guardada` en verde, y ese estado es un marcador en disco que sobrevive a que
el portal caduque la sesión: el 2026-09-19 los cuatro decían `guardada` con
las cuatro caducadas, y la sesión de LEVIC muere del lado del servidor sin
avisar. Aquí la tarjeta cruza lo que dice Doyle con lo que **las consultas
guardadas** vieron (`almacenamiento.EvidenciaDeLaSesion`): la última vez que
el portal dio precio y la última vez que mandó al login. Es la misma regla con
la que la lista ofrece «Abrir sesión»: se le cree al portal, no al marcador.

Funciones puras: no tocan la red, la base ni el reloj.
"""

from __future__ import annotations

import datetime as dt

from continental.almacenamiento import EvidenciaDeLaSesion
from continental.doyle import SesionDeProveedor
from continental.precios import NOMBRES_DE_PROVEEDOR, nombre_del_proveedor
from continental.transito import ZONA_DE_LA_FARMACIA, fecha_en_palabras
from continental.vigilancia import instante_de_doyle_en_palabras

#: Lo que dice la etiqueta de cada tarjeta. Cinco y no los tres de Doyle:
#: `guardada` se parte en lo que la evidencia sabe de ella.
SIN_SESION = "sin sesión"
ESPERANDO = "esperando a que alguien entre"
CADUCADA = "caducada"
SIRVIO = "sirvió"
SIN_PROBAR = "guardada, sin probar"


#: Cuando la evidencia no se pudo leer: la tarjeta dice lo de Doyle y que no
#: se pudo comprobar, en vez de callar (que se leería como "sin probar").
SIN_EVIDENCIA = (
    "No se pudieron leer las consultas guardadas, así que esto es solo lo que "
    "dice Doyle, y su «guardada» no quiere decir que sirva."
)


def _guardada_en(sesion: SesionDeProveedor) -> dt.datetime | None:
    """El instante del marcador de Doyle, con zona, para compararlo.

    Doyle lo escribe con `datetime.now().isoformat()`, sin zona, en la hora de
    la máquina: la de la farmacia en atlas (medido el 2026-09-28). `None` si
    no hay o no se puede leer: entonces no se compara contra nada.
    """
    if not sesion.guardada_en:
        return None
    try:
        instante = dt.datetime.fromisoformat(sesion.guardada_en)
    except ValueError:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=ZONA_DE_LA_FARMACIA)
    return instante


def _cuando(instante: dt.datetime) -> str:
    local = instante.astimezone(ZONA_DE_LA_FARMACIA)
    return f"{fecha_en_palabras(local.date())} a las {local:%H:%M}"


def estado_de_la_sesion(
    sesion: SesionDeProveedor,
    evidencia: EvidenciaDeLaSesion | None,
    evidencia_leida: bool = True,
) -> tuple[str, str]:
    """`(etiqueta, frase)` de una tarjeta.

    `evidencia` es `None` cuando ese proveedor no tiene consultas guardadas;
    `evidencia_leida` es falso cuando no se pudieron leer, y entonces la
    tarjeta de una sesión guardada dice solo lo de Doyle, avisando.

    `guardada` se lee contra la evidencia, en este orden:

    1. el portal mandó al login **después** del último precio y del último
       guardado → `caducada`, aunque Doyle diga `guardada`;
    2. dio precio **después** del último guardado → `sirvió`, con cuándo, y
       sin afirmar que siga sirviendo;
    3. lo demás —recién guardada, o sin consultas desde entonces— → `sin
       probar`: no se sabe todavía.
    """
    if sesion.estado == "abriendo":
        return ESPERANDO, (
            "La ventana del portal está abierta en el visor. Entra ahí con el "
            "usuario y la contraseña y vuelve a darle a «Ya entré». Si ya no vas "
            "a entrar, «Cancelar» la cierra sin guardar nada, y los otros "
            "portales se pueden abrir otra vez."
        )
    if sesion.estado != "guardada":
        return SIN_SESION, (
            "Doyle no tiene una sesión guardada de este portal: mientras no se "
            "abra, no trae precios de aquí."
        )

    guardada = _guardada_en(sesion)
    cuando_se_guardo = (
        f"Se guardó {instante_de_doyle_en_palabras(sesion.guardada_en)}."
        if sesion.guardada_en
        else "No quedó cuándo se guardó."
    )
    if not evidencia_leida:
        return "guardada", f"{cuando_se_guardo} {SIN_EVIDENCIA}"
    dio = evidencia.dio_precio_en if evidencia else None
    caduco = evidencia.caduco_en if evidencia else None

    if caduco and (dio is None or caduco > dio) and (guardada is None or caduco > guardada):
        return CADUCADA, (
            f"{_cuando(caduco).capitalize()}, una consulta encontró que el portal "
            f"mandaba al login. {cuando_se_guardo} Doyle la sigue llamando «guardada» "
            "porque su marcador no se entera de que el portal ya no la acepta: "
            "ábrela otra vez."
        )
    if dio and (guardada is None or dio >= guardada):
        return SIRVIO, (
            f"Dio precio por última vez {_cuando(dio)}. {cuando_se_guardo} "
            "Pudo caducar desde entonces: la siguiente consulta lo dice."
        )
    return SIN_PROBAR, (
        f"{cuando_se_guardo} Ninguna consulta la ha usado desde entonces, así "
        "que todavía no se sabe si el portal la acepta."
    )


def sesiones_como_json(
    sesiones: list[SesionDeProveedor],
    evidencia: dict[str, EvidenciaDeLaSesion] | None,
) -> list[dict]:
    """Una tarjeta por proveedor, en el orden del glosario.

    `evidencia` es `None` cuando no se pudo leer (distinto de `{}`, que es "no
    hay ni una consulta todavía").

    Los botones los decide aquí la regla del ADR 0018 —**un portal esperando a
    la vez**—: mientras uno espera, los otros dicen por qué no se abren. La
    ruta lo vuelve a comprobar; esto es para no pintar un botón que va a
    rebotar.
    """
    esperando = next((s for s in sesiones if s.estado == "abriendo"), None)
    orden = {c: i for i, c in enumerate(NOMBRES_DE_PROVEEDOR)}
    tarjetas = []
    for s in sorted(sesiones, key=lambda s: (orden.get(s.proveedor, len(orden)), s.proveedor)):
        etiqueta, frase = estado_de_la_sesion(
            s,
            None if evidencia is None else evidencia.get(s.proveedor),
            evidencia_leida=evidencia is not None,
        )
        abriendo = s.estado == "abriendo"
        otro = esperando if (esperando is not None and not abriendo) else None
        tarjetas.append({
            "proveedor": s.proveedor,
            "nombre": nombre_del_proveedor(s.proveedor),
            "estado": s.estado,
            "etiqueta": etiqueta,
            "frase": frase,
            "hay_que_abrirla": etiqueta in (SIN_SESION, CADUCADA),
            "se_puede_abrir": not abriendo and otro is None,
            "por_que_no_se_abre": (
                None if otro is None
                else f"Primero termina con {nombre_del_proveedor(otro.proveedor)}: "
                "su ventana sigue esperando, y con dos abiertas el visor no dice "
                "cuál es cuál."
            ),
            "rotulo_de_abrir": "Abrir sesión" if s.estado == "sin_sesion" else "Volver a abrir",
            "se_puede_confirmar": abriendo,
        })
    return tarjetas
