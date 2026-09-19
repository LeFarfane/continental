"""La prueba que exige borrar `pendientes.md` cuando ya no describe trabajo.

**Es la única prueba del suite que falla porque las cosas salieron bien**, y
está escrita así a propósito.

`pendientes.md` es una lista de acarreo con fecha de caducidad: los once pendientes
—16 casillas— que ponen a Continental en pie en atlas. El modo de falla que existe para
evitar no es que alguien olvide un paso —para eso están las casillas— sino el
otro, el silencioso: que el archivo siga en el repo en diciembre, con todo
hecho, diciéndole a quien llegue que nada se ha hecho. Un archivo de pendientes
vencido es peor que no tenerlo, porque se lee con la misma confianza.

`HANDOVER.md` describe **el estado actual** y lo dice en su primera línea; esto
es una lista de parches por aplicar, que es justo lo que el HANDOVER no quiere
ser. Por eso vive aparte, y por eso se va.

**El precio de esto, dicho antes de que sorprenda a nadie:** cuando se marque
la última casilla, esta prueba se pone roja y `scripts/desplegar.sh` se detiene
en su paso 3, que es el del suite. Si la última casilla se marca en atlas, hay
que borrar el archivo **antes** del siguiente despliegue. Es un `git rm` y el
mensaje de la falla lo dice con el comando pegado. Se aceptó ese precio a
cambio de que el borrado ocurra: un `TODO: borrar este archivo` dentro del
propio archivo es exactamente lo que nadie lee.

Las dos direcciones están cubiertas y ninguna es un descuido:

- **El archivo no existe** → verde y en silencio. Ya se borró, o nunca hubo que
  acarrear nada. No se exige que exista: sería obligar a un repo sano a cargar
  un archivo vacío.
- **El archivo existe con casillas sin marcar** → verde. Es su estado normal y
  no se dice nada; el suite no es el lugar donde se recuerdan tareas.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PENDIENTES = RAIZ / "pendientes.md"

#: Una casilla de Markdown al principio de un renglón, con o sin sangría.
#: `[ ]` sin marcar, `[x]` o `[X]` marcada. No se miran las de dentro de un
#: bloque de código porque `pendientes.md` no tiene ninguna, y una expresión
#: regular que entendiera de bloques sería más frágil que el problema.
_CASILLA = re.compile(r"^\s*- \[([ xX])\]", re.MULTILINE)


def _casillas() -> list[str]:
    return _CASILLA.findall(PENDIENTES.read_text(encoding="utf-8"))


def test_el_archivo_de_acarreo_se_borra_cuando_ya_no_describe_trabajo():
    """Si no queda una sola casilla sin marcar, el archivo sobra.

    El mensaje trae el comando: una falla que obliga a pensar qué hacer es una
    falla a medio escribir.
    """
    if not PENDIENTES.exists():
        return  # ya se borró, que es el final feliz

    casillas = _casillas()
    assert casillas, (
        f"{PENDIENTES.name} no tiene ni una casilla `- [ ]`. O se vació sin "
        "borrarse, o alguien le cambió el formato y este recordatorio dejó de "
        "vigilar nada. Bórralo o devuélvele sus casillas."
    )

    sin_marcar = [c for c in casillas if c == " "]
    assert sin_marcar, (
        f"Las {len(casillas)} casillas de {PENDIENTES.name} están marcadas: "
        "Continental ya está en pie en atlas y esa lista de acarreo ya no "
        "describe trabajo. Bórrala junto con este recordatorio, que también "
        "sobra:\n\n"
        "    git rm pendientes.md tests/test_pendientes.py\n\n"
        "Lo que sigue vivo va en Notion (base `Pendientes`, proyecto "
        "`Continental`) y el estado del repo en `HANDOVER.md`."
    )


def test_mientras_haya_trabajo_el_archivo_lo_dice_con_casillas():
    """Que el archivo sea legible como lista, no como prosa con viñetas.

    Sin esto, `pendientes.md` podría degradarse a un párrafo y la prueba de
    arriba se quedaría sin nada que contar, en verde y sin vigilar.
    """
    if not PENDIENTES.exists():
        return

    texto = PENDIENTES.read_text(encoding="utf-8")
    assert "pendientes.md" in texto, (
        "El archivo no se nombra a sí mismo, así que no puede decir cómo se "
        "borra. Es lo único que de verdad tiene que explicar."
    )
    assert "git rm pendientes.md" in texto, (
        "Falta el comando de borrado dentro del propio archivo. Quien llegue "
        "con todo hecho tiene que encontrar ahí qué hacer, sin leer esta "
        "prueba."
    )
