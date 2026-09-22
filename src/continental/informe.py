"""El informe: el vocabulario que `forma.py` y `verificar.py` comparten sin
importarse el uno al otro.

Antes de este archivo, `verificar.py` definía `Informe`, `Resultado`,
`OK`/`FALLA`/`PENDIENTE` y sus tres constructores, y `forma.py` los tomaba
prestados con `from continental.verificar import _falla, _ok, _pendiente,
_plural, ...`. Funcionaba porque los dos archivos tienen la misma silueta
—una función pura que recibe datos y devuelve un `Informe`, una función de
recolección que lee de Postgres y no se prueba (la casilla 1 del ticket 17,
y después el ADR 0017)— pero el préstamo era de lo **privado** de un módulo
hacia otro, y privado quiere decir "esto es mío y puede cambiar sin avisar".
`verificar.py` a su vez importaba `forma` adentro de sus funciones y nunca
arriba del archivo, precisamente para no cerrar el círculo. Sacar el
vocabulario compartido a un tercer archivo es lo que permite que las dos
importaciones dejen de morderse la cola.

## Las dos mitades que este archivo NO decide

`forma.py` compara la **forma** de la base: qué columnas tiene cada tabla de
`pedidos`, contra lo que declara `sql/crear_tablas.sql` y lo que agrega cada
archivo bajo `sql/` que suma una columna. `verificar.py` compara los
**datos**: que no haya dos listas abiertas el mismo día, que un renglón en
tránsito tenga su pedido, que un pedido enviado traiga quién lo envió.
Ninguno de los dos sabe del otro más que esto: los dos terminan en un
`Informe`, y los dos lo arman con `ok`/`falla`/`pendiente`. Ese vocabulario
compartido —y solo él— es lo que vive aquí.

## Qué NO vive aquí

Nada que sea de la forma o de los datos. `LecturaDeForma` es de `forma.py`;
`FilaSugerido`, `FilaRenglon`, `FilaPedido` y `LecturaDeTabla` son de
`verificar.py`. Moverlos aquí habría escondido que un archivo lee la forma de
una tabla y el otro lee sus filas, y esa diferencia es la razón de que sean
dos archivos y no uno.

## Nombres públicos y no privados

`_ok`, `_falla` y `_pendiente` se llamaban así porque nacieron como detalle
interno de `verificar.py`. Aquí son la interfaz entera del módulo —lo único
que `forma.py` y `verificar.py` toman de este archivo—, así que se llaman
`ok`, `falla` y `pendiente`: un guion bajo en el nombre de una función que
otro módulo importa es la señal de que algo no debería estar pasando, y con
este archivo ya no pasa. Quien los usa los sigue nombrando `_ok`/`_falla`/
`_pendiente` puertas adentro, con un alias puesto en el propio `import`: es
la convención de cada archivo para decir "esto arma un renglón del informe",
y no tenía por qué cambiar en cada una de las llamadas que ya tenían escritas.

## `COMANDO_FORMA`

El comando con el que se corre `--forma` a mano estaba escrito dos veces, con
las mismas palabras: en `forma.py`, para cuando la revisión misma se cae, y
en `verificar.py`, para cuando falta una columna del envío. Que dijeran lo
mismo importaba tanto como el código —es lo primero que lee quien despierta
con el despliegue rojo—, y una cadena repetida en dos archivos es una que se
desactualiza en uno solo el día que cambie la ruta del venv y nadie note que
faltó el segundo lugar. Vive aquí, junto al resto del vocabulario del
informe, para que `verificar.py` la tenga sin depender de `forma.py` para
conseguirla.
"""

from __future__ import annotations

from dataclasses import dataclass

OK = "ok"
FALLA = "falla"
PENDIENTE = "pendiente"

_MARCA = {OK: "ok", FALLA: "!!", PENDIENTE: "··"}

#: El comando de psql con el que atlas corre cualquier cosa contra el
#: almacén, con las credenciales del dueño. Una sola cadena, para que las dos
#: mitades de recolección —la de `forma.py` y la de `verificar.py`— lo envuelvan
#: igual.
PSQL = "docker exec -i farmacia_warehouse psql -U farmacia -d farmacia"

#: El comando con el que se corre `--forma` a mano, tal cual se copia y pega
#: en la terminal de atlas. Antes vivía escrito dos veces, una en `forma.py`
#: y otra en `verificar.py`; ver la prosa de arriba.
COMANDO_FORMA = (
    "cd ~/proyectos/Continental && .venv/bin/python -m continental.verificar --forma"
)


def plural(cuantos: int, uno: str, varios: str) -> str:
    """"1 renglón" y no "1 renglón(es)".

    Cuesta cuatro líneas y lo lee una persona a las ocho de la mañana con el
    despliegue rojo. Un mensaje que se lee como plantilla se lee como algo que
    a nadie le importó revisar.
    """
    return f"{cuantos} {uno if cuantos == 1 else varios}"


def enumerar(cosas, conector: str = "ni") -> str:
    """"estado ni enviado_por", no "estado, enviado_por"."""
    cosas = list(cosas)
    if len(cosas) <= 1:
        return "".join(cosas)
    return f"{', '.join(cosas[:-1])} {conector} {cosas[-1]}"


def comando(sentencia: str) -> str:
    """Una sentencia envuelta en el `psql` con el que se corre en atlas.

    `docker exec -i` y no `-f`: con `docker exec`, el `-f` de psql busca el
    archivo DENTRO del contenedor, donde este repo no está montado. Y
    `ON_ERROR_STOP=1` porque sin él psql sigue tras un error y termina diciendo
    que todo salió bien.
    """
    return f'{PSQL} -v ON_ERROR_STOP=1 -c "{sentencia}"'


# ==========================================================================
# El informe
# ==========================================================================


@dataclass(frozen=True, slots=True)
class Resultado:
    """Una comprobación con su veredicto.

    Tres estados y no dos. `PENDIENTE` es el que se gana el sueldo: un
    invariante que **todavía no se puede revisar** —porque la columna que
    necesita llega con otro ticket— no es un `ok` (mentiría) ni una falla (no
    hay nada roto). Se declara, se ve en la salida, y no tumba el despliegue.

    `resumen` es la línea corta de la tabla; `detalle` es el párrafo que se
    imprime debajo, solo para lo que no está en orden.
    """

    nombre: str
    estado: str
    resumen: str = ""
    detalle: str = ""
    reparacion: str = ""

    def __post_init__(self) -> None:
        if self.estado not in _MARCA:
            raise ValueError(
                f"Estado desconocido: {self.estado!r}. Son {sorted(_MARCA)}."
            )
        # LA CASILLA 2 DEL TICKET, PUESTA DONDE NO SE PUEDE CUMPLIR A MEDIAS.
        # "Cada mensaje de falla incluye el comando de reparación" escrito como
        # convención es cómo la tercera comprobación que alguien agregue el año
        # que viene sale sin él, y nadie lo nota hasta las ocho de la mañana de
        # un día malo. Aquí el olvido revienta en la corrida.
        if self.estado == FALLA and not self.reparacion.strip():
            raise ValueError(
                f"La falla {self.nombre!r} no trae comando de reparación. Una "
                f"falla sin el comando con el que se arregla obliga a quien la "
                f"lea a inventárselo con prisa."
            )

    @property
    def fallo(self) -> bool:
        return self.estado == FALLA


@dataclass(frozen=True, slots=True)
class Informe:
    """Lo que devuelven las funciones puras. Se suma con `+`.

    Inmutable y sumable en vez de un acumulador que se pasa por parámetro —que
    es como lo hace Marlowe—: así cada comprobación se puede llamar sola desde
    una prueba y devolver algo que se mira, sin montar un objeto compartido
    antes.
    """

    resultados: tuple[Resultado, ...] = ()

    def __add__(self, otro: "Informe") -> "Informe":
        return Informe(self.resultados + otro.resultados)

    @property
    def fallas(self) -> tuple[Resultado, ...]:
        return tuple(r for r in self.resultados if r.estado == FALLA)

    @property
    def pendientes(self) -> tuple[Resultado, ...]:
        return tuple(r for r in self.resultados if r.estado == PENDIENTE)

    @property
    def codigo_de_salida(self) -> int:
        """1 si algo falló. Un pendiente **no** cuenta: lo que le falta es una
        columna de un ticket que todavía no llega, no un dato roto."""
        return 1 if self.fallas else 0

    def como_texto(
        self, titulo: str = "Continental · invariantes sobre los datos de producción"
    ) -> str:
        """La salida entera, tal como la lee una persona en la terminal.

        Primero la tabla de una línea por comprobación —para ver de un vistazo
        cuántas y cuáles—, y después un bloque por cada cosa que no está en
        orden, con su párrafo y su comando. Esa es la casilla de **acumular**:
        detenerse en la primera falla obliga a desplegar cinco veces para
        enterarse de cinco cosas.
        """
        lineas = [titulo, ""]

        if not self.resultados:
            lineas.append("  ninguna comprobación se pudo correr.")
            lineas.append("")
            lineas.append("==> no se revisó nada. Eso no es un almacén sano.")
            return "\n".join(lineas)

        ancho = max(len(r.nombre) for r in self.resultados)
        for r in self.resultados:
            lineas.append(f"  {_MARCA[r.estado]}  {r.nombre:<{ancho}}  {r.resumen}")

        for r in self.resultados:
            if r.estado == OK:
                continue
            lineas.append("")
            lineas.append(f"  {_MARCA[r.estado]} {r.nombre}")
            for parrafo in (r.detalle or r.resumen).splitlines():
                lineas.append(f"     {parrafo}")
            if r.reparacion:
                lineas.append("     repara con:")
                for orden in r.reparacion.splitlines():
                    lineas.append(f"       {orden}")

        lineas.append("")
        if self.fallas:
            lineas.append(
                f"==> {len(self.fallas)} de {len(self.resultados)} comprobaciones "
                f"FALLARON. No se reparó nada: eso lo decide una persona."
            )
        else:
            pendientes = (
                f", {len(self.pendientes)} pendiente(s)" if self.pendientes else ""
            )
            lineas.append(
                f"==> {len(self.resultados)} comprobaciones en orden{pendientes}."
            )
        return "\n".join(lineas)


def ok(nombre: str, resumen: str = "") -> Informe:
    return Informe((Resultado(nombre=nombre, estado=OK, resumen=resumen),))


def falla(nombre: str, resumen: str, detalle: str, reparacion: str) -> Informe:
    return Informe(
        (
            Resultado(
                nombre=nombre,
                estado=FALLA,
                resumen=resumen,
                detalle=detalle,
                reparacion=reparacion,
            ),
        )
    )


def pendiente(nombre: str, resumen: str, detalle: str) -> Informe:
    return Informe(
        (
            Resultado(
                nombre=nombre, estado=PENDIENTE, resumen=resumen, detalle=detalle
            ),
        )
    )


__all__ = [
    "COMANDO_FORMA",
    "FALLA",
    "Informe",
    "OK",
    "PENDIENTE",
    "PSQL",
    "Resultado",
    "comando",
    "enumerar",
    "falla",
    "ok",
    "pendiente",
    "plural",
]
