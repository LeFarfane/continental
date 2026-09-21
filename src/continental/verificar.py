"""Invariantes sobre los datos REALES de Continental. **Señala y no repara.**

    python -m continental.verificar

Sale con código distinto de cero si algo falla, y dice **todo** lo que falla,
junto y con el comando con el que se arregla cada cosa. Corre como último paso
de `scripts/desplegar.sh`, sin que nadie tenga que acordarse.

## Por qué existe, si ya hay 525 pruebas en verde

Porque dicen cosas distintas: **pytest dice que el código hace lo que dice;
esto dice que los datos de producción están sanos.** Ninguna función pura
puede notar que hay dos listas abiertas del mismo día — cada fila es
plausible por sí sola y el suite corre sin Postgres a propósito. Marlowe
aprendió esto a la mala: el 2026-09-07 el dueño encontró mirando la pantalla
cinco errores que 168 pruebas en verde no vieron.

## Qué NO hace

No repara nada. Reparar en automático es cómo un dato malo se vuelve
permanente y cómo una persona pierde la oportunidad de preguntarse por qué
pasó. Aquí se señala, se dice el comando, y se detiene.

## En qué se diferencia de `sql/verificar_rol.sql`, que también "verifica"

Los dos existen, ninguno sobra, y confundirlos es fácil porque se llaman
parecido. La diferencia es qué miran, con qué credenciales y cuándo:

|  | `sql/verificar_rol.sql` | este módulo |
|---|---|---|
| Qué mira | la **forma** de la base: que el rol no tenga CREATE, que los CHECK sigan puestos, que las llaves sean de identidad | los **datos**: que no haya dos listas abiertas del mismo día, que un renglón en tránsito tenga su pedido |
| Con qué credenciales | las del **dueño** (`farmacia`), que puede leer el catálogo entero | las del rol **acotado** (`continental`), las mismas del servicio |
| Cuándo | **a mano, una vez**, después de crear las tablas y el rol | **en cada despliegue**, automático |
| Cómo pregunta | leyendo `pg_*` e `information_schema` | **haciendo la lectura**: `SELECT 1 FROM marts.<tabla>` |

La última fila es la que más importa y es la casilla 5 del ticket 17. El
catálogo contesta lo que el catálogo cree; un `SELECT 1` contesta lo que este
rol puede hacer **ahora**. Y "ahora" cambia solo: cada `dbt build` recrea los
modelos de `marts` y **se lleva los permisos por delante** — un GRANT dado a
mano dura hasta las 20:30 de ese día (Marlowe lo midió el 2026-09-06). Por eso
la comprobación de permisos vive aquí, en lo que corre siempre, y no solo allá,
en lo que se corrió una vez.

## Las dos mitades, que es la casilla 1

- **Puras**: reciben listas y devuelven un `Informe`. No conocen Postgres, no
  abren un socket y no miran el reloj. **Ésas son las que se prueban**, en
  `tests/test_verificar.py`, con listas y dataclasses en memoria.
- **Recolección** (`correr`, `_intentar_leer`, `_filas_de`): leen de Postgres.
  **Ésas no se prueban**, y es correcto: probarlas exigiría un Postgres con
  datos rotos a propósito, que es justo lo que esto existe para encontrar en el
  mundo. Lo que sí está probado es que estén aisladas — importar este módulo no
  abre nada, y ninguna función pura nombra un motor.

## El detalle de un error va a la terminal; la contraseña no

La regla 5 de `CLAUDE.md` dice que los errores no viajan al navegador, porque
un `str(exc)` de SQLAlchemy lleva la cadena de conexión con contraseña dentro.
Aquí no hay navegador: hay una terminal de atlas, el scrollback de quien
desplegó y —si algún día esto corre desde el timer— el journal. La decisión es
**detalle sí, credenciales no**: el detalle hace falta para diagnosticar, así
que se imprime, pero pasa antes por `redactar`, una vez y en el borde.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Lo único que este módulo importa del paquete, y son dos constantes: el nombre
# de una columna y un booleano. **No abre nada** —`continental.almacen` solo
# importa sqlalchemy al cargarse y el motor vive detrás de un `lru_cache`— así
# que la regla de "las importaciones del almacén van dentro de las funciones"
# sigue valiendo para lo que de verdad la motiva: `motor()`, que se sigue
# importando dentro de `correr`. Se importan y no se copian porque una columna
# escrita en dos lugares se separa el día que uno de los dos cambie, y entonces
# el verificador diría que falta una columna que ya existe.
from continental.almacen import (
    COLUMNA_DE_LA_CLASE_ABC,
    LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO,
)

RAIZ = Path(__file__).resolve().parents[2]
CREAR_ROL = RAIZ / "sql" / "crear_rol.sql"

#: El estado del glosario, escrito **una vez** y usado tanto por el `WHERE` de
#: la recolección como por la mitad pura. Separarlos es cómo un día la consulta
#: busca `'en transito'` sin acento, no encuentra nada, y el invariante pasa en
#: verde para siempre sin revisar una sola fila.
EN_TRANSITO = "en tránsito"

OK = "ok"
FALLA = "falla"
PENDIENTE = "pendiente"

_MARCA = {OK: "ok", FALLA: "!!", PENDIENTE: "··"}

_PSQL = "docker exec -i farmacia_warehouse psql -U farmacia -d farmacia"


def _plural(cuantos: int, uno: str, varios: str) -> str:
    """"1 renglón" y no "1 renglón(es)".

    Cuesta cuatro líneas y lo lee una persona a las ocho de la mañana con el
    despliegue rojo. Un mensaje que se lee como plantilla se lee como algo que
    a nadie le importó revisar.
    """
    return f"{cuantos} {uno if cuantos == 1 else varios}"


def _enumerar(cosas, conector: str = "ni") -> str:
    """"estado ni enviado_por", no "estado, enviado_por"."""
    cosas = list(cosas)
    if len(cosas) <= 1:
        return "".join(cosas)
    return f"{', '.join(cosas[:-1])} {conector} {cosas[-1]}"


def _comando(sentencia: str) -> str:
    """Una sentencia envuelta en el `psql` con el que se corre en atlas.

    `docker exec -i` y no `-f`: con `docker exec`, el `-f` de psql busca el
    archivo DENTRO del contenedor, donde este repo no está montado. Y
    `ON_ERROR_STOP=1` porque sin él psql sigue tras un error y termina diciendo
    que todo salió bien.
    """
    return f'{_PSQL} -v ON_ERROR_STOP=1 -c "{sentencia}"'


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


def _ok(nombre: str, resumen: str = "") -> Informe:
    return Informe((Resultado(nombre=nombre, estado=OK, resumen=resumen),))


def _falla(nombre: str, resumen: str, detalle: str, reparacion: str) -> Informe:
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


def _pendiente(nombre: str, resumen: str, detalle: str) -> Informe:
    return Informe(
        (
            Resultado(
                nombre=nombre, estado=PENDIENTE, resumen=resumen, detalle=detalle
            ),
        )
    )


# ==========================================================================
# Las filas que las comprobaciones reciben
# ==========================================================================
#
# Congeladas y planas: lo que la recolección arma y lo que una prueba escribe a
# mano son exactamente la misma cosa, así que no hay un camino que solo se
# ejercite en producción.


@dataclass(frozen=True, slots=True)
class FilaSugerido:
    pedido_sugerido_id: int
    negocio: str
    fecha_del_pedido: object
    estado: str


@dataclass(frozen=True, slots=True)
class FilaRenglon:
    renglon_id: int
    negocio: str
    pedido_sugerido_id: int
    pedido_id: int | None
    estado: str
    descripcion: str = ""


@dataclass(frozen=True, slots=True)
class FilaPedido:
    """`estado` y `enviado_por` son `None` mientras las columnas no existan.

    **Desde el ticket 21 existen las dos**: `estado` llegó con el 20 —un pedido
    nace en `borrador`— y `enviado_por` con el 21, que es el que estrena
    `enviado`. Los `None` se quedan porque siguen siendo ciertos sobre una base
    a la que no se le haya corrido la migración de ese día: la recolección
    rellena con `None` lo que la tabla no tenga, y quien decide qué hacer con
    eso es la mitad pura, mirando la lista de columnas de verdad (ver
    `revisar_pedidos_enviados`).
    """

    pedido_id: int
    negocio: str
    estado: str | None = None
    enviado_por: str | None = None


@dataclass(frozen=True, slots=True)
class LecturaDeTabla:
    """El resultado de intentar `SELECT 1 FROM <esquema>.<tabla>`."""

    esquema: str
    tabla: str
    pudo_leer: bool
    motivo: str = ""


# ==========================================================================
# MITAD PURA — reciben datos, devuelven un informe. Éstas se prueban.
# ==========================================================================


_CREDENCIAL_EN_URL = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


def redactar(texto: str) -> str:
    """Le quita la contraseña a cualquier cadena de conexión que traiga dentro.

    `str(exc)` de SQLAlchemy incluye la URL del motor entera —usuario,
    contraseña, host, base— y esa cadena termina en la terminal de quien
    desplegó y en su scrollback. Se deja el usuario y el host, que es lo que
    sirve para diagnosticar; se tapa lo único que no debe viajar.
    """
    return _CREDENCIAL_EN_URL.sub(r"\1***\3", texto)


def _sin_comentarios(sql: str) -> str:
    """El SQL sin sus comentarios de línea.

    `sql/crear_rol.sql` es mitad prosa —explica qué NO se otorga y por qué—, y
    un `GRANT` nombrado en un comentario no es un permiso. No se intenta
    entender cadenas con `--` adentro porque ese archivo no tiene ninguna; si
    algún día la tuviera, esto contaría de más y la prueba que compara contra
    las cinco tablas esperadas lo diría.
    """
    return re.sub(r"--[^\n]*", "", sql)


def _tablas_otorgadas(sql: str, esquema: str) -> tuple[str, ...]:
    vistas: list[str] = []
    patron = re.compile(
        rf"GRANT\s+[A-Z,\s]+\s+ON\s+{esquema}\.(\w+)\s+TO\s+continental",
        re.IGNORECASE,
    )
    for tabla in patron.findall(_sin_comentarios(sql)):
        if tabla not in vistas:
            vistas.append(tabla)
    if not vistas:
        raise ValueError(
            f"No se encontró ni un GRANT sobre `{esquema}` en sql/crear_rol.sql. "
            f"Cero tablas no es 'todo en orden': es que el archivo cambió de "
            f"forma y el verificador se quedaría revisando nada, en verde."
        )
    return tuple(vistas)


def tablas_de_marts_en(sql: str) -> tuple[str, ...]:
    """Las tablas de `marts` que el rol necesita, **leídas de `crear_rol.sql`**.

    La lista no se escribe de memoria ni se copia aquí: se saca del archivo que
    de verdad otorga los permisos. Una segunda copia sería una lista que se
    queda vieja y que da luz verde sobre un rol al que le falta una tabla.
    """
    return _tablas_otorgadas(sql, "marts")


def tablas_de_pedidos_en(sql: str) -> tuple[str, ...]:
    """Las tablas propias, del mismo archivo y por la misma razón.

    Éstas no las recrea `dbt build` —no son suyas—, pero sí se quedan sin
    permiso por otro camino medido: una migración que **crea** una tabla nace
    sin GRANT, porque el `crear_rol.sql` que se corrió en su día no la
    alcanzaba. Le pasó a `pedidos.precio_de_proveedor` con la migración 0003.
    """
    return _tablas_otorgadas(sql, "pedidos")


def revisar_sugeridos_abiertos(listas: Sequence[FilaSugerido]) -> Informe:
    """Invariante 1: no hay dos pedidos sugeridos **abiertos** para el mismo
    día y negocio.

    Dos listas abiertas el mismo día se reparten los renglones: el encargado
    trabaja sobre una mientras la otra envejece, y lo que quedó en la otra no
    se pide y no se vuelve a proponer.

    **Lo que este invariante NO revisa**, a propósito: una lista abierta de un
    día anterior. Eso no está roto — es lo que
    `almacenamiento.vencer_las_de_dias_anteriores` atiende, y el glosario le
    tiene un estado propio (`vencido`).
    """
    nombre = "un solo pedido sugerido abierto por día y negocio"
    abiertas = [f for f in listas if f.estado == "abierto"]

    por_dia: dict[tuple[str, object], list[int]] = {}
    for f in abiertas:
        por_dia.setdefault((f.negocio, f.fecha_del_pedido), []).append(
            f.pedido_sugerido_id
        )
    duplicados = {k: sorted(v) for k, v in por_dia.items() if len(v) > 1}

    if not duplicados:
        return _ok(
            nombre, f"{_plural(len(abiertas), 'abierta', 'abiertas')}, ninguna duplicada"
        )

    # Se conserva abierta la más reciente y se cierran las demás. El id sirve
    # de orden porque es `GENERATED ALWAYS AS IDENTITY`: el mayor es el último
    # que se insertó.
    a_cerrar: list[int] = []
    renglones = []
    for (negocio, dia), ids in sorted(duplicados.items(), key=lambda kv: str(kv[0])):
        a_cerrar.extend(ids[:-1])
        renglones.append(
            f"negocio {negocio}, día {dia}: {len(ids)} listas abiertas "
            f"(ids {', '.join(str(i) for i in ids)}); se conservaría la {ids[-1]}."
        )

    lista = ", ".join(str(i) for i in sorted(a_cerrar))
    detalle = "\n".join(
        renglones
        + [
            "Dos listas abiertas el mismo día se reparten los renglones: se",
            "trabaja sobre una y lo que quedó en la otra no se pide.",
            "La restricción ux_pedido_sugerido_dia de sql/crear_tablas.sql",
            "debería impedirlo. Si esto falló, la tabla se creó sin ella:",
            "CREATE TABLE IF NOT EXISTS calla si la tabla ya existe con otra forma.",
            "cerrado_en va en el mismo UPDATE porque ck_pedido_sugerido_cierre",
            "exige los dos juntos.",
        ]
    )
    reparacion = "\n".join(
        [
            _comando(
                "UPDATE pedidos.pedido_sugerido SET estado = 'cerrado', "
                f"cerrado_en = now() WHERE pedido_sugerido_id IN ({lista});"
            ),
            "# y revisa que la restricción siga puesta, porque debería haberlo impedido:",
            f"{_PSQL} -c \"\\d pedidos.pedido_sugerido\"",
        ]
    )
    return _falla(
        nombre,
        f"{_plural(len(duplicados), 'día', 'días')} con más de una lista abierta",
        detalle,
        reparacion,
    )


def revisar_transito_con_pedido(renglones: Sequence[FilaRenglon]) -> Informe:
    """Invariante 2: ningún renglón en tránsito sin su pedido.

    `en tránsito` quiere decir que ya se le pidió a un proveedor, y el **pedido**
    es lo único que guarda a cuál. Un renglón así sin `pedido_id` no se vuelve a
    proponer (CONTEXT.md) y al mismo tiempo nadie puede decir a quién se le
    pidió: la mercancía deja de pedirse sin que nadie se entere, que es la forma
    exacta de falla silenciosa que este repo prohíbe.
    """
    nombre = "ningún renglón en tránsito sin su pedido"
    en_transito = [r for r in renglones if r.estado == EN_TRANSITO]
    huerfanos = sorted(
        (r for r in en_transito if r.pedido_id is None), key=lambda r: r.renglon_id
    )

    if not huerfanos:
        return _ok(
            nombre,
            f"{_plural(len(en_transito), 'renglón', 'renglones')} en tránsito, "
            f"{'con su pedido' if len(en_transito) == 1 else 'todos con su pedido'}",
        )

    ids = ", ".join(str(r.renglon_id) for r in huerfanos)
    detalle = "\n".join(
        [
            (
                f"el renglón {ids} está"
                if len(huerfanos) == 1
                else f"los renglones {ids} están"
            )
            + f" '{EN_TRANSITO}' y su pedido_id es NULL.",
            "El comando los devuelve a 'abierto', que es lo defendible cuando el",
            "pedido no existe: un renglón sin pedido no se le pidió a nadie. OJO,",
            "vuelven a proponerse en el siguiente sugerido — que es lo que se",
            "quiere, pero conviene saberlo antes de correrlo.",
            "Si el pedido SÍ existe y lo que se perdió es el enlace, la corrección",
            "es la otra (ponerle el pedido_id) y ésa la decide una persona: por eso",
            "el segundo comando enseña qué pedidos hay para esas listas.",
        ]
    )
    reparacion = "\n".join(
        [
            "# primero mira si el pedido existe y solo se perdió el enlace:",
            _comando(
                "SELECT r.renglon_id, p.pedido_id, p.proveedor_id "
                "FROM pedidos.renglon r "
                "LEFT JOIN pedidos.pedido p "
                "ON p.pedido_sugerido_id = r.pedido_sugerido_id "
                f"WHERE r.renglon_id IN ({ids});"
            ),
            "# si no hay pedido que les corresponda, devuélvelos a abierto:",
            _comando(
                "UPDATE pedidos.renglon SET estado = 'abierto' "
                f"WHERE renglon_id IN ({ids}) AND pedido_id IS NULL;"
            ),
        ]
    )
    return _falla(
        nombre,
        f"{_plural(len(huerfanos), 'renglón', 'renglones')} en tránsito sin pedido",
        detalle,
        reparacion,
    )


#: Lo mínimo que `pedidos.pedido` necesita para que el invariante 3 se pueda
#: revisar. **No incluye `enviado_en`**: la fecha no hace falta para preguntar
#: "¿quién lo envió?", y cada columna que se nombre de más es una apuesta sobre
#: un ticket que todavía no se escribió.
#:
#: **Esta tupla nunca cambió, y ahí está el punto.** Se escribió en el ticket
#: 17, cuando ninguna de las dos columnas existía. El ticket 20 puso `estado` y
#: el 21 puso `enviado_por`, los dos con el nombre que aquí ya estaba escrito,
#: así que el invariante pasó de PENDIENTE a revisar de verdad **sin que nadie
#: tocara este archivo**. Era exactamente lo que se quería: el pendiente se
#: imprimió en cada despliegue mientras faltó algo, y se apagó solo.
COLUMNAS_QUE_EXIGE_EL_ENVIO = ("estado", "enviado_por")


def revisar_pedidos_enviados(
    pedidos: Sequence[FilaPedido], columnas: frozenset[str] | set[str]
) -> Informe:
    """Invariante 3: ningún pedido enviado sin quién lo envió.

    **Desde el ticket 21 este invariante revisa de verdad.** Estuvo escrito y
    `PENDIENTE` desde el ticket 17, esperando dos columnas que no existían: el
    20 puso `estado` —un pedido nace en `borrador`— y el 21 puso `enviado_por`
    junto con el estado `enviado` (`borrador` -> `enviado`, firmado con el
    correo que verificó Access).

    Que `COLUMNAS_QUE_EXIGE_EL_ENVIO` no haya tenido que cambiar en ninguno de
    los dos es la prueba de que quedó bien planteado: los dos tickets usaron los
    nombres que aquí ya estaban escritos, y el invariante se encendió solo.

    **El mecanismo se queda, y cambió de veredicto con el ADR 0017.** La
    recolección trae las columnas **que la tabla tiene de verdad** y esta
    función decide. Si faltan, antes era `PENDIENTE`; ahora es `FALLA`, porque
    el código ya las nombra y faltar es una migración sin correr. El comando
    con el archivo exacto lo da la comprobación de forma (`--forma`, paso 4 de
    `desplegar.sh`), así que las dos dicen lo mismo y ninguna calla.

    **Qué revisa, exactamente:** que ningún pedido que diga `enviado` esté sin
    firma. `enviado` significa *"yo ya lo capturé en el portal del proveedor"*
    (ADR 0009): es la declaración de una persona sobre algo que Continental no
    vio, así que sin la firma no queda ningún hecho guardado y no hay a quién
    preguntarle qué se capturó. `ck_pedido_envio` lo impide en la tabla; esto lo
    revisa sobre las filas de verdad, porque un CHECK se puede quitar con un
    `ALTER` y nadie se entera — que es exactamente lo que este módulo existe
    para cazar.

    Ojo con una tentación: **`estado = 'borrador'` no es "no enviado" en un
    sentido que este invariante pueda usar**. Lo que se revisa es lo que dice
    `enviado`; contar borradores aquí sería contestar otra pregunta.
    """
    nombre = "ningún pedido enviado sin quién lo envió"
    faltantes = [c for c in COLUMNAS_QUE_EXIGE_EL_ENVIO if c not in columnas]

    if faltantes:
        # DESDE EL ADR 0017 ESTO FALLA, Y ANTES ERA UN PENDIENTE. Mientras las
        # columnas "llegaban con otro ticket" su ausencia no era nada roto;
        # desde el ticket 21 el código ya las nombra, así que faltar es una
        # migración sin correr. El comando exacto lo da la comprobación de
        # forma, que dice lo mismo con el archivo: las dos fallan juntas.
        return _falla(
            nombre,
            f"pedidos.pedido no tiene {_enumerar(faltantes)}",
            "\n".join(
                [
                    f"`pedidos.pedido` no tiene {_enumerar(faltantes)}, y el código",
                    "desplegado ya las nombra: falta correr una migración, y hasta",
                    "entonces la lista del día rebota con 'column ... does not exist'.",
                    "La comprobación de forma nombra el archivo exacto de la migración.",
                    "No se crean aquí: el rol `continental` no hace DDL (ADR 0003).",
                ]
            ),
            "# qué migración falta, con su comando (ADR 0017):\n"
            "cd ~/proyectos/Continental && .venv/bin/python -m continental.verificar --forma",
        )

    enviados = [p for p in pedidos if (p.estado or "") == "enviado"]
    sin_firma = sorted(
        (p for p in enviados if not (p.enviado_por or "").strip()),
        key=lambda p: p.pedido_id,
    )

    if not sin_firma:
        return _ok(
            nombre,
            f"{_plural(len(enviados), 'pedido enviado', 'pedidos enviados')}, "
            f"{'firmado' if len(enviados) == 1 else 'todos firmados'}",
        )

    ids = ", ".join(str(p.pedido_id) for p in sin_firma)
    detalle = "\n".join(
        [
            (
                f"el pedido {ids} dice 'enviado' y no dice quién lo envió."
                if len(sin_firma) == 1
                else f"los pedidos {ids} dicen 'enviado' y no dicen quién los envió."
            ),
            "'Enviado' significa 'yo ya lo capturé en el portal del proveedor'",
            "(ticket 21): sin la firma no hay a quién preguntarle qué se capturó.",
            "El correo es una FIRMA y no un permiso (regla 3 de CLAUDE.md), así que",
            "no se rellena a mano: el pedido vuelve a borrador y se envía otra vez.",
        ]
    )
    reparacion = _comando(
        "UPDATE pedidos.pedido SET estado = 'borrador' "
        f"WHERE pedido_id IN ({ids}) AND enviado_por IS NULL;"
    )
    return _falla(
        nombre,
        f"{_plural(len(sin_firma), 'pedido enviado', 'pedidos enviados')} sin firma",
        detalle,
        reparacion,
    )


#: La columna del ADR 0018 de farmacia-data que el lote nocturno necesita, y el
#: interruptor que la enciende del lado de Continental. Los dos salen de
#: `continental.almacen`, que es donde se lee el catálogo.
#:
#: **Sin `clase_abc`, la segunda casilla del ticket 18 no se puede cumplir.**
#: El orden de importancia del lote está construido y probado, pero no hay de
#: dónde leer la clase: `marts.dim_producto` tiene 18 columnas y ninguna es
#: ésa. Es un bloqueo externo, no un pendiente de este repo.
COLUMNAS_QUE_EXIGE_EL_ORDEN = (COLUMNA_DE_LA_CLASE_ABC,)


def revisar_clase_abc(columnas: frozenset[str] | set[str]) -> Informe:
    """Invariante 4: el lote nocturno puede ordenar por importancia.

    **Hoy no puede, y eso se dice en vez de fingirse.** Es exactamente el mismo
    trato que el invariante 3 le da a `estado` y `enviado_por` (ticket 17), y
    por la misma razón: la columna llega de otro repo y de otro ticket, y quien
    la implemente no tiene por qué acordarse de volver aquí.

    Mientras `marts.dim_producto` no traiga `clase_abc`, el resultado es
    `PENDIENTE`: **se ve en la salida de cada despliegue y no tumba nada**. El
    lote sigue corriendo —trae precios igual— pero consulta en el orden de
    urgencia con el que la lista se armó, y lo declara en su bitácora.

    El día que `dbt build` materialice la columna (ADR 0018 de farmacia-data),
    esto pasa a `ok` solo, y lo que dice entonces es **el único trabajo que
    queda**: mover `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO` a `True`. Es una
    línea, y el mensaje la nombra para que nadie tenga que buscarla.

    Los dos casos se distinguen a propósito. Que la columna exista y
    Continental siga sin leerla **también es un pendiente** —el dato está ahí y
    el pedido se sigue ordenando mal—, así que sale igual de visible.
    """
    nombre = "el lote nocturno puede ordenar por clase ABC"
    faltantes = [c for c in COLUMNAS_QUE_EXIGE_EL_ORDEN if c not in columnas]

    if faltantes:
        return _pendiente(
            nombre,
            f"pendiente: marts.dim_producto no tiene {_enumerar(faltantes)}",
            "\n".join(
                [
                    f"`marts.dim_producto` todavía no tiene {_enumerar(faltantes)}, así",
                    "que el lote nocturno (ticket 18) NO puede consultar en orden de",
                    "importancia: consulta en el orden de urgencia con el que la lista",
                    "se armó y lo dice en su bitácora. La columna la crea dbt en la",
                    "cadena de las 20:30 y la decide el ADR 0018 de farmacia-data,",
                    "que está ACEPTADO Y SIN IMPLEMENTAR. No se inventa aquí: el rol",
                    "`continental` solo lee de marts (regla 6 de CLAUDE.md), y un",
                    "orden alterno está descartado a propósito por ese mismo ADR.",
                    "Esto se enciende solo el día que la columna exista.",
                ]
            ),
        )

    if not LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO:
        return _pendiente(
            nombre,
            f"pendiente: ya existe {COLUMNA_DE_LA_CLASE_ABC} y Continental no la lee",
            "\n".join(
                [
                    f"`marts.dim_producto.{COLUMNA_DE_LA_CLASE_ABC}` YA EXISTE —llegó el",
                    "ADR 0018 de farmacia-data— y Continental sigue sin leerla, así que",
                    "el lote nocturno sigue ordenando por urgencia y no por importancia.",
                    "Falta UNA línea, y es la única que falta:",
                    "",
                    "  en src/continental/almacen.py,",
                    "  LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True",
                    "",
                    "Después, `pytest` y desplegar. El orden del lote ya está escrito y",
                    "probado (tests/test_lote.py): lo único que falta es leer el dato.",
                ]
            ),
        )

    return _ok(nombre, f"marts.dim_producto trae {COLUMNA_DE_LA_CLASE_ABC} y se lee")


def revisar_permisos(esquema: str, lecturas: Sequence[LecturaDeTabla]) -> Informe:
    """Casilla 5: el veredicto sobre los `SELECT 1` que ya se hicieron.

    Esta función es pura porque recibe el **resultado** de las lecturas, no el
    motor. Quien las hace es `_intentar_leer`, abajo, que es recolección y no se
    prueba. La línea está ahí a propósito: lo que hay que poder probar es qué se
    dice cuando un permiso falta, no que SQLAlchemy sepa ejecutar `SELECT 1`.
    """
    # El conteo va en el resumen y no en el nombre: el nombre es lo que se lee
    # dos veces —en la tabla de arriba y en el bloque de abajo— y tiene que
    # decir siempre lo mismo, aunque mañana `crear_rol.sql` otorgue una tabla
    # más o una menos.
    nombre = f"el rol lee las tablas de {esquema} que necesita"
    negadas = [l for l in lecturas if not l.pudo_leer]

    if not negadas:
        return _ok(
            nombre,
            f"{_plural(len(lecturas), 'tabla', 'tablas')}: "
            + ", ".join(l.tabla for l in lecturas),
        )

    lista = ", ".join(f"{esquema}.{l.tabla}" for l in negadas)
    motivos = " · ".join(
        f"{l.tabla}: {redactar(l.motivo)}" for l in negadas if l.motivo
    )

    if esquema == "marts":
        detalle = "\n".join(
            [
                f"permiso negado al hacer SELECT 1 sobre {lista}.",
                "Recrear una tabla en Postgres borra sus permisos, y cada `dbt build`",
                "recrea los modelos de `marts`: un GRANT dado a mano dura hasta las",
                "20:30 de hoy. Marlowe lo midió el 2026-09-06 — otorgó a mano, corrió",
                "el barrido, y la interfaz se cayó con 'permission denied'.",
                "Por eso la reparación tiene dos mitades y la segunda es la que dura.",
            ]
            + ([motivos] if motivos else [])
        )
        modelos = " y ".join(f"dbt/models/marts/{l.tabla}.sql" for l in negadas)
        reparacion = "\n".join(
            [
                "# levanta el servicio ahora, y se borra en la corrida de las 20:30:",
                _comando(f"GRANT SELECT ON {lista} TO continental;"),
                "# el arreglo que dura vive en el repo Farmacia (farmacia-data):",
                f"#   agrega 'continental' al grants de {modelos}",
                "#   y corre: cd dbt && ../.venv/bin/dbt build",
            ]
        )
    else:
        detalle = "\n".join(
            [
                f"permiso negado al hacer SELECT 1 sobre {lista}.",
                "Estas tablas no las recrea dbt, así que el permiso no se perdió solo:",
                "lo más probable es una migración que CREÓ una tabla después del último",
                "`crear_rol.sql` — un GRANT no alcanza a una tabla que no existía.",
                "Le pasó a pedidos.precio_de_proveedor con la migración 0003.",
            ]
            + ([motivos] if motivos else [])
        )
        reparacion = "\n".join(
            [
                "# desde ~/proyectos/Continental, con credenciales de dueño:",
                f"{_PSQL} -v ON_ERROR_STOP=1 < sql/crear_rol.sql;",
                "# el rol ya existe (si no, esto ni habría podido conectarse), así que",
                "# no hace falta -v password: crear_rol.sql no le toca la contraseña.",
            ]
        )

    return _falla(
        nombre, f"permiso negado en {', '.join(l.tabla for l in negadas)}",
        detalle, reparacion,
    )


# ==========================================================================
# MITAD DE RECOLECCIÓN — aquí sí se lee de Postgres. Esto NO se prueba.
# ==========================================================================
#
# Nada de aquí abajo se importa al cargar el módulo: los `import` de SQLAlchemy
# y de la configuración están DENTRO de las funciones, para que `import
# continental.verificar` no exija `.env` ni cree un motor. Es la misma razón por
# la que `almacen.motor` vive detrás de un `lru_cache`.


def _intentar_leer(motor, esquema: str, tablas: Sequence[str]) -> list[LecturaDeTabla]:
    """Un `SELECT 1` por tabla. **Haciendo la lectura, no preguntándole al
    catálogo** — la casilla 5 del ticket.

    Cada tabla en su propia transacción (`rollback` tras el fallo): sin eso, el
    primer "permission denied" aborta la transacción y las demás contestan
    "current transaction is aborted", o sea que una tabla sin permiso escondería
    el estado de las otras cuatro y habría que desplegar cinco veces.
    """
    from sqlalchemy import text

    lecturas: list[LecturaDeTabla] = []
    with motor.connect() as conexion:
        for tabla in tablas:
            try:
                conexion.execute(text(f"SELECT 1 FROM {esquema}.{tabla} LIMIT 1"))
                lecturas.append(LecturaDeTabla(esquema, tabla, True))
            except Exception as exc:  # noqa: BLE001
                conexion.rollback()
                lecturas.append(
                    LecturaDeTabla(
                        esquema,
                        tabla,
                        False,
                        redactar(f"{type(exc).__name__}: {exc}").splitlines()[0],
                    )
                )
    return lecturas


def columnas_de_dim_producto(motor) -> frozenset[str]:
    """Qué columnas tiene HOY `marts.dim_producto`. **LEE de Postgres.**

    Recolección, así que no se prueba: lo que sí está probado es la función
    pura que decide con lo que esto devuelva (`revisar_clase_abc`).

    `select * ... limit 1` y no una consulta al catálogo del sistema, por la
    misma razón que la casilla 5 del ticket 17: el catálogo contesta lo que el
    catálogo cree, y esto contesta lo que este rol ve al leer. Es además la
    forma en que el invariante 3 averigua la forma de `pedidos.pedido`.

    El `limit 1` es todo lo que hace falta: `CursorResult.keys()` trae los
    nombres de las columnas aunque no vuelva ni una fila, así que una
    `dim_producto` vacía contesta igual de bien.
    """
    from sqlalchemy import text

    with motor.connect() as conexion:
        filas = conexion.execute(
            text("select * from marts.dim_producto limit 1")
        ).mappings()
        return frozenset(filas.keys())


def _filas_de_los_invariantes(motor) -> tuple[list, list, list, frozenset[str]]:
    """Las filas que los tres invariantes necesitan, y la forma real de
    `pedidos.pedido`.

    Dos decisiones que no son obvias:

    - **No se filtra por negocio.** El verificador mira la base entera: una
      lista rota de otro negocio también es una base rota, y filtrar la
      escondería. Hoy hay un solo negocio y de todos modos se lee así.
    - **`select *` sobre `pedidos.pedido`, y a propósito.** Es la forma de
      averiguar qué columnas tiene la tabla HOY sin consultar el catálogo del
      sistema, que es justo lo que la casilla 5 descarta. Las claves del
      resultado son la tabla real; el invariante 3 decide con ellas.
    """
    from sqlalchemy import text

    with motor.connect() as conexion:
        sugeridos = [
            FilaSugerido(
                pedido_sugerido_id=int(f.pedido_sugerido_id),
                negocio=f.negocio,
                fecha_del_pedido=f.fecha_del_pedido,
                estado=f.estado,
            )
            for f in conexion.execute(
                text(
                    "select pedido_sugerido_id, negocio, fecha_del_pedido, estado "
                    "from pedidos.pedido_sugerido order by pedido_sugerido_id"
                )
            )
        ]

        # Éste sí se acota en el SQL, y es la única consulta que lo hace:
        # `renglon` tiene una fila por producto y por lista, o sea miles. El
        # estado se pasa como parámetro y sale de `EN_TRANSITO`, la misma
        # constante que usa la función pura, para que no puedan separarse.
        renglones = [
            FilaRenglon(
                renglon_id=int(f.renglon_id),
                negocio=f.negocio,
                pedido_sugerido_id=int(f.pedido_sugerido_id),
                pedido_id=int(f.pedido_id) if f.pedido_id is not None else None,
                estado=f.estado,
                descripcion=f.descripcion,
            )
            for f in conexion.execute(
                text(
                    "select renglon_id, negocio, pedido_sugerido_id, pedido_id, "
                    "estado, descripcion from pedidos.renglon "
                    "where estado = :en_transito order by renglon_id"
                ),
                {"en_transito": EN_TRANSITO},
            )
        ]

        crudos = conexion.execute(
            text("select * from pedidos.pedido order by pedido_id")
        ).mappings()
        columnas = frozenset(crudos.keys())
        pedidos = [
            FilaPedido(
                pedido_id=int(f["pedido_id"]),
                negocio=f["negocio"],
                estado=f.get("estado"),
                enviado_por=f.get("enviado_por"),
            )
            for f in crudos.all()
        ]

    return sugeridos, renglones, pedidos, columnas


def correr() -> Informe:
    """Recolecta y comprueba todo. **LEE de Postgres**; no se prueba.

    Acumula: una falla no interrumpe lo que sigue. Si los permisos sobre
    `pedidos` están rotos, los tres invariantes no se pueden mirar y eso se
    declara como pendiente en vez de tronar — la falla ya está dicha una vez y
    repetirla cuatro no agrega información.
    """
    informe = Informe()

    try:
        sql = CREAR_ROL.read_text(encoding="utf-8")
        de_marts = tablas_de_marts_en(sql)
        de_pedidos = tablas_de_pedidos_en(sql)
    except (OSError, ValueError) as exc:
        return informe + _falla(
            "la lista de tablas sale de sql/crear_rol.sql",
            "no se pudo leer sql/crear_rol.sql",
            redactar(f"{type(exc).__name__}: {exc}"),
            "git -C ~/proyectos/Continental checkout -- sql/crear_rol.sql;",
        )

    try:
        from continental.almacen import motor

        el_motor = motor()
    except Exception as exc:  # noqa: BLE001
        return informe + _falla(
            "hay almacén al que preguntarle",
            "no se pudo construir el motor",
            "\n".join(
                [
                    redactar(f"{type(exc).__name__}: {exc}"),
                    "Sin WAREHOUSE_URL no hay nada que verificar. Vive en el .env de",
                    "Continental y apunta al Postgres de farmacia-data con el rol",
                    "`continental` (ver .env.example).",
                ]
            ),
            "# revisa que el .env exista y traiga WAREHOUSE_URL:\n"
            "grep -c WAREHOUSE_URL ~/proyectos/Continental/.env;",
        )

    lecturas_marts = _intentar_leer(el_motor, "marts", de_marts)
    lecturas_pedidos = _intentar_leer(el_motor, "pedidos", de_pedidos)
    informe = (
        informe
        + revisar_permisos("marts", lecturas_marts)
        + revisar_permisos("pedidos", lecturas_pedidos)
    )

    # El invariante 4 mira `marts`, no `pedidos`, así que va aquí arriba y se
    # salta solo si el rol no puede leer esa tabla — la falla ya está dicha una
    # vez y repetirla no agrega información.
    if any(l.tabla == "dim_producto" and not l.pudo_leer for l in lecturas_marts):
        informe = informe + _pendiente(
            "el lote nocturno puede ordenar por clase ABC",
            "pendiente: no se pudo leer marts.dim_producto",
            "No se revisó porque el rol no alcanza la tabla. Arregla el permiso"
            " de arriba y vuelve a correr esto.",
        )
    else:
        try:
            informe = informe + revisar_clase_abc(columnas_de_dim_producto(el_motor))
        except Exception as exc:  # noqa: BLE001
            informe = informe + _falla(
                "el lote nocturno puede ordenar por clase ABC",
                "no se pudieron leer las columnas de marts.dim_producto",
                redactar(f"{type(exc).__name__}: {exc}"),
                f'{_PSQL} -c "\\d marts.dim_producto";',
            )

    if any(not l.pudo_leer for l in lecturas_pedidos):
        return informe + _pendiente(
            "los tres invariantes del pedido",
            "pendiente: no se pudieron leer las tablas de pedidos",
            "\n".join(
                [
                    "No se revisaron porque el rol no alcanza sus propias tablas.",
                    "Arregla el permiso de arriba y vuelve a correr esto.",
                ]
            ),
        )

    # La forma (ADR 0017) también en la corrida completa, no solo en `--forma`:
    # así el paso final de desplegar.sh y una corrida a mano dicen lo mismo.
    from continental import forma

    informe = informe + forma.revisar_con(el_motor)

    try:
        sugeridos, renglones, pedidos, columnas = _filas_de_los_invariantes(el_motor)
    except Exception as exc:  # noqa: BLE001
        return informe + _falla(
            "los tres invariantes del pedido",
            "no se pudieron leer las filas",
            redactar(f"{type(exc).__name__}: {exc}"),
            "# mira la forma real de las tablas antes de tocar nada:\n"
            f'{_PSQL} -c "\\d pedidos.renglon";',
        )

    return (
        informe
        + revisar_sugeridos_abiertos(sugeridos)
        + revisar_transito_con_pedido(renglones)
        + revisar_pedidos_enviados(pedidos, columnas)
    )


def main(argv: list[str] | None = None) -> int:
    """Imprime el informe entero y devuelve el código de salida.

    Lo imprime **todo de una vez** y hasta el final: ni una falla corta la
    corrida. `desplegar.sh` lo encadena como último paso y se detiene con su
    código, así que un despliegue con datos rotos no pasa de largo.
    """
    parseador = argparse.ArgumentParser(
        prog="python -m continental.verificar",
        description=(
            "Invariantes sobre los datos reales de Continental. Señala y no "
            "repara: cada falla sale con el comando con el que se arregla."
        ),
    )
    parseador.add_argument(
        "--forma",
        action="store_true",
        help=(
            "Solo la forma de la base: que cada columna que el código nombra "
            "exista, leída como el rol. Es el paso de desplegar.sh que va ANTES "
            "del reinicio (ADR 0017)."
        ),
    )
    if parseador.parse_args(argv).forma:
        from continental import forma

        informe = forma.correr()
        print(informe.como_texto(forma.TITULO))
        return informe.codigo_de_salida

    informe = correr()
    print(informe.como_texto())
    return informe.codigo_de_salida


if __name__ == "__main__":
    raise SystemExit(main())
