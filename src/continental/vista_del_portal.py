"""«Ver en el portal»: las frases de la vista que Doyle deja en el visor (ADR 0026).

La encargada ve a veces «no dijo cuántas tiene» en NADRO, o un precio raro, y
quiere mirar el portal con sus propios ojos sin ir a buscarlo. Continental no
abre navegadores (regla 1 de `CLAUDE.md`): le pide a Doyle que deje en el visor
el portal con la búsqueda del EAN puesta, y la pantalla abre el visor, igual que
«Abrir sesión».

Funciones puras: no tocan la red ni la base. **Las frases se componen aquí y no
en el JavaScript**, que solo las pinta. Ninguna incluye el texto de una
excepción: lo único que llega de Doyle es el `detail` de un 409, que Doyle
escribe para personas (regla 5 de `CLAUDE.md`).
"""

from __future__ import annotations

from continental.precios import nombre_del_proveedor

#: Qué se dice cuando falta la dirección del visor: la vista quedó abierta en
#: la pantalla de atlas y desde aquí no hay a dónde mandar a nadie. Es la misma
#: honestidad que la de abrir una sesión, con la misma llave del YAML.
SIN_VISOR = (
    "Falta configurar «visor_de_doyle» en config/continental.yml: la vista se "
    "abrió en la pantalla de atlas y desde aquí no hay a dónde mandarte a verla."
)


def frase_de_ver(
    proveedor: str,
    clave: str,
    *,
    ya_abierta: bool,
    parece_login: bool,
    hay_visor: bool,
) -> str:
    """Lo que se le dice a la persona cuando Doyle ya dejó el portal en el visor.

    `parece_login` pesa más que todo lo demás y va en la misma frase: ver un
    login donde se esperaba un precio **es** la respuesta, y callarlo dejaría
    a la encargada buscando un producto en una página que no deja buscar.
    """
    nombre = nombre_del_proveedor(proveedor)
    if ya_abierta:
        frase = (
            f"{nombre} ya estaba abierto en el visor: es la misma vista, no se "
            "abrió otra."
        )
    else:
        frase = f"Doyle abrió {nombre} en el visor con la búsqueda de {clave}."
    if parece_login:
        frase += (
            f" Ojo: la sesión de {nombre} parece caída, porque en el visor se "
            "ve el login. Ábrela desde Sesiones."
        )
    frase += (
        " Mira ahí lo que el portal dice y, cuando termines, dale a «Ya vi»."
        if hay_visor
        else " " + SIN_VISOR
    )
    return frase


def frase_de_cerrar(proveedor: str, *, ya_estaba_cerrada: bool) -> str:
    """Lo que se dice al cerrar la vista. Que Doyle ya no la tuviera no es una
    falla: la cierra sola por tope, y el resultado que la persona quería —que
    el portal quede libre— es el mismo."""
    nombre = nombre_del_proveedor(proveedor)
    if ya_estaba_cerrada:
        return (
            f"La vista de {nombre} ya estaba cerrada (Doyle la cierra sola "
            "pasado un rato). Ese portal ya se puede consultar."
        )
    return f"Se cerró la vista de {nombre}. Ese portal ya se puede consultar."
