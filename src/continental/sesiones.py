"""La pestaña de Sesiones: el «Inicio» de Doyle, sin creerle a `guardada`.

Doyle tenía en su web una pestaña de Inicio con una tarjeta por portal —sin
sesión, guardada, abriendo— y los botones para abrirla, confirmarla o cancelar.
Se quedó sin pantalla el 2026-09-21 con el resto de su interfaz (su ADR 0008);
la pidió el dueño el 2026-09-28.

**Lo único que se cambia al absorberla es qué se afirma.** Doyle dice
`guardada` en verde, y ese estado es un marcador en disco que sobrevive a que
el portal caduque la sesión: el 2026-09-19 los cuatro decían `guardada` con
las cuatro caducadas, y la sesión de LEVIC muere del lado del servidor sin
avisar. Aquí la tarjeta cruza lo que dice Doyle con lo que el portal contestó
de verdad, y hay dos fuentes (ADR 0024): **las consultas guardadas**
(`almacenamiento.EvidenciaDeLaSesion`) y **las pruebas** del botón «Probar»
(`almacenamiento.PruebaDeLaSesion`). Gana la más reciente, y la frase dice cuál
fue y a qué hora. Es la misma regla con la que la lista ofrece «Abrir sesión»:
se le cree al portal, no al marcador.

`sirvió` quiere decir que la sesión **pasó del login** —con precio, `sin
resultados` o `no empareja`—, no que haya dado precio: lo que se pregunta es si
la sesión vive.

Funciones puras: no tocan la red, la base ni el reloj.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from continental.almacenamiento import (
    RESULTADO_CADUCADA,
    RESULTADO_SIRVIO,
    EvidenciaDeLaSesion,
    PruebaDeLaSesion,
)
from continental.doyle import SesionDeProveedor
from continental.precios import (
    MOTIVOS_QUE_PASARON_DEL_LOGIN,
    NOMBRES_DE_PROVEEDOR,
    SESION_CADUCADA,
    LecturaDePrecio,
    explicacion_del_motivo,
    nombre_del_proveedor,
)
from continental.transito import ZONA_DE_LA_FARMACIA, fecha_en_palabras
from continental.vigilancia import instante_de_doyle_en_palabras

#: Lo que dice la etiqueta de cada tarjeta. Cinco y no los tres de Doyle:
#: `guardada` se parte en lo que el portal contestó desde que se guardó.
SIN_SESION = "sin sesión"
ESPERANDO = "esperando a que alguien entre"
CADUCADA = RESULTADO_CADUCADA
SIRVIO = RESULTADO_SIRVIO
SIN_PROBAR = "guardada, sin probar"

#: De dónde salió la etiqueta: lo que una persona probó con el botón, o lo que
#: una consulta del pedido encontró de paso.
DE_UNA_PRUEBA = "prueba"
DE_UNA_CONSULTA = "consulta"


#: Cuando la evidencia no se pudo leer: la tarjeta dice lo de Doyle y que no
#: se pudo comprobar, en vez de callar (que se leería como "sin probar").
SIN_EVIDENCIA = (
    "No se pudieron leer las consultas ni las pruebas guardadas, así que esto "
    "es solo lo que dice Doyle, y su «guardada» no quiere decir que sirva."
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


def _lo_mas_reciente(
    guardada: dt.datetime | None,
    evidencia: EvidenciaDeLaSesion | None,
    prueba: PruebaDeLaSesion | None,
) -> tuple[str, dt.datetime, str] | None:
    """`(etiqueta, instante, origen)` de lo último que dijo el portal **después
    de guardada la sesión**, venga de una prueba o de una consulta; `None` si
    nada.

    Lo anterior a guardarla es de la sesión de antes: una prueba `caducada`
    de ayer no dice nada de la que alguien acaba de abrir. `caducada` pide ser
    **posterior** a guardarla y `sirvió` basta con que no sea anterior, que es
    lo que ya hacía la regla de las consultas.

    Con el mismo instante gana `sirvió`: así lo decidía la regla anterior (un
    login solo gana si es estrictamente posterior al último paso del login).
    """
    candidatos: list[tuple[dt.datetime, int, str, str]] = []

    def sirvio(instante: dt.datetime | None, origen: str) -> None:
        if instante and (guardada is None or instante >= guardada):
            candidatos.append((instante, 1, SIRVIO, origen))

    def caduco(instante: dt.datetime | None, origen: str) -> None:
        if instante and (guardada is None or instante > guardada):
            candidatos.append((instante, 0, CADUCADA, origen))

    if evidencia is not None:
        sirvio(evidencia.paso_el_login_en, DE_UNA_CONSULTA)
        caduco(evidencia.caduco_en, DE_UNA_CONSULTA)
    if prueba is not None:
        (sirvio if prueba.resultado == SIRVIO else caduco)(prueba.probada_en, DE_UNA_PRUEBA)

    if not candidatos:
        return None
    instante, _, etiqueta, origen = max(candidatos, key=lambda c: (c[0], c[1]))
    return etiqueta, instante, origen


def estado_de_la_sesion(
    sesion: SesionDeProveedor,
    evidencia: EvidenciaDeLaSesion | None,
    evidencia_leida: bool = True,
    prueba: PruebaDeLaSesion | None = None,
) -> tuple[str, str]:
    """`(etiqueta, frase)` de una tarjeta.

    `evidencia` es `None` cuando ese proveedor no tiene consultas guardadas, y
    `prueba` cuando nunca se probó; `evidencia_leida` es falso cuando no se
    pudieron leer, y entonces la tarjeta de una sesión guardada dice solo lo de
    Doyle, avisando.

    `guardada` se lee contra lo último que dijo el portal, **gane una prueba o
    una consulta** (`_lo_mas_reciente`):

    1. lo más reciente fue el login → `caducada`, aunque Doyle diga `guardada`;
    2. fue pasar del login → `sirvió`, con cuándo y de dónde, y sin afirmar
       que siga sirviendo;
    3. nada desde que se guardó —recién guardada, o sin consultas ni pruebas
       desde entonces— → `guardada, sin probar`: no se sabe todavía.
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

    ultimo = _lo_mas_reciente(guardada, evidencia, prueba)
    if ultimo is None:
        return SIN_PROBAR, (
            # "Ninguna consulta la ha usado" decía hasta el 2026-09-28, y en
            # atlas era falso para QuePharma: se le consulta, y contesta sin
            # precio porque no empareja por EAN. Desde el ADR 0024 eso ya
            # cuenta como pasar del login; lo que falta es que nada haya
            # contestado desde que se guardó, ni una consulta ni una prueba.
            f"{cuando_se_guardo} Desde entonces ni una consulta ni una prueba "
            "ha dicho si el portal la acepta, así que todavía no se sabe."
        )

    etiqueta, instante, origen = ultimo
    cuando = _cuando(instante)
    if etiqueta == CADUCADA:
        quien = (
            f"Probada {cuando}: el portal la mandó al login."
            if origen == DE_UNA_PRUEBA
            else f"Una consulta la encontró caducada {cuando}: el portal mandaba al login."
        )
        return CADUCADA, (
            f"{quien} {cuando_se_guardo} Doyle la sigue llamando «guardada» "
            "porque su marcador no se entera de que el portal ya no la acepta: "
            "ábrela otra vez."
        )
    quien = (
        f"Probada {cuando}: pasó del login."
        if origen == DE_UNA_PRUEBA
        else f"Una consulta pasó del login {cuando}."
    )
    return SIRVIO, (
        f"{quien} {cuando_se_guardo} Pudo caducar desde entonces: la "
        "siguiente consulta o prueba lo dice."
    )


def sesiones_como_json(
    sesiones: list[SesionDeProveedor],
    evidencia: dict[str, EvidenciaDeLaSesion] | None,
    pruebas: dict[str, PruebaDeLaSesion] | None = None,
) -> list[dict]:
    """Una tarjeta por proveedor, en el orden del glosario.

    `evidencia` es `None` cuando no se pudo leer (distinto de `{}`, que es "no
    hay ni una consulta todavía"); `pruebas` es lo último que se probó de cada
    portal, y `None` o `{}` quieren decir que nunca se probó. Quien no pudo
    leer las pruebas manda `evidencia=None`: una etiqueta decidida con la mitad
    de lo que se sabe sería afirmar de más.

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
            prueba=(pruebas or {}).get(s.proveedor),
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
            # El portal que espera en el visor no se prueba: esa ventana es de
            # quien está tecleando. El candado de una prueba a la vez y el
            # motivo de cada botón apagado llegan con el ticket 03.
            "se_puede_probar": not abriendo,
        })
    return tarjetas


# ------------------------------------------------- el veredicto de una prueba


def resultado_de_la_prueba(motivo: str | None, tiene_precio: bool) -> str | None:
    """Lo que una lectura de un portal dice de su sesión: `sirvió`, `caducada`
    o `None` si **no dice nada** y por eso no se guarda.

    - un precio, o un motivo de `MOTIVOS_QUE_PASARON_DEL_LOGIN` → `sirvió`;
    - `la sesión caducó` → `caducada`;
    - el portal no contestó, una ventana abierta, no se sabe leer, no alcanzó
      el tiempo → `None`: no saber no es lo mismo que `caducada`, y la tarjeta
      conserva su última etiqueta.

    Función pura sobre los dos datos de una `LecturaDePrecio`; aquí vive la
    definición de «pasó del login» que comparten la prueba y la etiqueta.
    """
    if tiene_precio or motivo in MOTIVOS_QUE_PASARON_DEL_LOGIN:
        return SIRVIO
    if motivo == SESION_CADUCADA:
        return CADUCADA
    return None


@dataclass(frozen=True, slots=True)
class ResultadoDeUnPortal:
    """Cómo le fue a un portal en una prueba. `resultado` es `None` cuando no
    terminó de probarse: entonces no se guarda y `motivo` dice por qué."""

    proveedor: str
    resultado: str | None
    motivo: str | None = None


def resultados_de_la_prueba(
    lecturas: Sequence[LecturaDePrecio], pedidos: Sequence[str] = ()
) -> list[ResultadoDeUnPortal]:
    """Lo que Doyle contestó de cada portal → su veredicto, en el orden del glosario.

    `pedidos` son los proveedores que se quisieron probar (vacío: los que
    contesten). **Uno que se pidió y Doyle no mencionó sale como no probado**,
    nunca se omite: callarlo se leería como "se probó y no hubo nada que decir".
    """
    por_proveedor = {l.proveedor: l for l in lecturas}
    quienes = list(pedidos) or list(por_proveedor)
    orden = {c: i for i, c in enumerate(NOMBRES_DE_PROVEEDOR)}
    resultados = []
    for proveedor in sorted(set(quienes), key=lambda c: (orden.get(c, len(orden)), c)):
        lectura = por_proveedor.get(proveedor)
        if lectura is None:
            resultados.append(ResultadoDeUnPortal(proveedor, None, None))
            continue
        resultados.append(ResultadoDeUnPortal(
            proveedor,
            resultado_de_la_prueba(lectura.motivo, lectura.precio is not None),
            lectura.motivo,
        ))
    return resultados


def frase_de_un_portal(r: ResultadoDeUnPortal) -> str:
    nombre = nombre_del_proveedor(r.proveedor)
    if r.resultado == SIRVIO:
        return f"{nombre}: pasó del login."
    if r.resultado == CADUCADA:
        return f"{nombre}: el portal la mandó al login, la sesión caducó. Ábrela otra vez."
    por_que = explicacion_del_motivo(r.motivo) if r.motivo else "Doyle no dijo nada de este portal"
    return f"{nombre}: no se pudo probar ({por_que}). Conserva lo que decía antes."


def prueba_como_json(resultados: Sequence[ResultadoDeUnPortal]) -> dict:
    """La respuesta de «Probar»: un resultado por portal y la frase de todos.

    `ok` es que **al menos un** portal terminó de probarse. Si ninguno, es una
    falla (la ruta le agrega su `que_hacer`); si solo algunos, `ok` y
    `algunos_sin_probar`, y la frase dice cuáles. Todo llega dicho: el
    JavaScript solo lo pinta.
    """
    sin_probar = [r for r in resultados if r.resultado is None]
    return {
        "ok": len(sin_probar) < len(resultados),
        "algunos_sin_probar": bool(sin_probar),
        "resultados": [
            {
                "proveedor": r.proveedor,
                "nombre": nombre_del_proveedor(r.proveedor),
                "resultado": r.resultado,
                "detalle": frase_de_un_portal(r),
            }
            for r in resultados
        ],
        "detalle": " ".join(frase_de_un_portal(r) for r in resultados),
    }
