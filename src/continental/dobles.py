"""Dobles de los dos bordes, usables desde cualquier prueba.

Viven en `src/` y no en `tests/` por una razón concreta: un doble que se aleja
de la interfaz real deja de probar nada, y aquí está al lado del `Protocol` que
implementa, cubierto por el mismo `isinstance` que las implementaciones de
verdad. Además evita el truco de `sys.path` que haría falta para importarlos
desde un `tests/` sin paquete, y deja disponibles los mismos dobles para el
chequeo de despliegue.

**Filtran igual que el SQL.** `ventas()` recorta por rango y `compras_desde()`
por fecha, porque un doble que devuelve todo miente: dejaría pasar en verde una
prueba que contra Postgres habría fallado.

No importan pytest ni nada de pruebas: son objetos normales.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import (
    ABIERTO,
    BORRADOR,
    CERRADO,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    VENCIDO,
    CorridaDelLote,
    PedidoSugeridoDuplicado,
    PedidoSugeridoGuardado,
    PrecioDeProveedor,
    Ventana,
    armar_guardado,
    columnas_de_la_corrida,
    columnas_de_la_lista,
    PedidoGuardado,
    columnas_del_pedido,
    columnas_del_precio,
    columnas_del_renglon,
    corrida_desde_columnas,
    precio_desde_columnas,
    renglon_guardado_desde_columnas,
    pedido_desde_columnas,
    revisar_el_pedido,
    revisar_el_precio,
    revisar_el_renglon,
    revisar_la_corrida,
    revisar_la_lista,
    ultimo_por_proveedor,
)
from continental.doyle import (
    BusquedaPedida,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
    SesionAbriendose,
    SesionConfirmada,
    SesionDeProveedor,
)
from continental.precios import LecturaDePrecio


@dataclass
class AlmacenFalso:
    """Doble de `LecturaDelAlmacen`: se le cargan filas y las devuelve.

    `falla` es lo que hace probable el caso que de verdad muerde: el almacén
    que no responde tiene que verse como un hueco con su motivo, no como una
    lista vacía que se lee "hoy no se vendió nada" (historia 54 del spec).
    """

    ventas_en_memoria: list[LineaDeVenta] = field(default_factory=list)
    catalogo_en_memoria: list[Producto] = field(default_factory=list)
    compras_en_memoria: list[LineaDeCompra] = field(default_factory=list)
    falla: Exception | None = None

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    def ventas(self, desde: dt.date, hasta: dt.date) -> list[LineaDeVenta]:
        self._revisar()
        return [v for v in self.ventas_en_memoria if desde <= v.fecha <= hasta]

    def catalogo(self) -> list[Producto]:
        self._revisar()
        return list(self.catalogo_en_memoria)

    def compras_desde(self, fecha: dt.date) -> list[LineaDeCompra]:
        self._revisar()
        return [c for c in self.compras_en_memoria if c.fecha >= fecha]

    def ultima_fecha_con_ventas(self) -> dt.date | None:
        self._revisar()
        if not self.ventas_en_memoria:
            return None
        return max(v.fecha for v in self.ventas_en_memoria)


@dataclass
class DoyleFalso:
    """Doble de `ClienteDeDoyle`. Guarda lo pedido y contesta lo preparado.

    Respeta el contrato de dos tiempos —acuse primero, estado después— porque
    si el doble contestara de golpe, una prueba en verde no diría nada sobre
    un lote que de verdad tarda ~9 s por proveedor.

    Un término sin resultado preparado sale `pendiente`, que es justo lo que
    pasa en la realidad mientras el portal carga: nunca un precio en cero.
    """

    resultados_por_termino: dict[str, dict[str, RespuestaDeProveedor]] = field(
        default_factory=dict
    )
    #: Cómo va cambiando una búsqueda entre una consulta y la siguiente: una
    #: entrada por vuelta de sondeo. Se consume en orden y **la última se
    #: repite** cuando se acaban, que es lo que hace un trabajo ya terminado.
    #:
    #: Existe porque sin esto no se puede probar que Continental **sondea**.
    #: Con un solo resultado fijo, una implementación que preguntara una vez y
    #: se quedara con lo primero que vio pasaría en verde — y contra el Doyle
    #: real congelaría cuatro huecos, porque los ~9 s del piso se pasan enteros
    #: en `buscando`.
    vueltas_por_termino: dict[str, list[dict[str, RespuestaDeProveedor]]] = field(
        default_factory=dict
    )
    sesiones_en_memoria: list[dict] = field(default_factory=list)
    #: Los proveedores a los que se les pidió abrir el navegador y todavía
    #: nadie confirmó. Es el `_abiertas` del Doyle real, con la misma regla: un
    #: segundo `abrir` del mismo proveedor NO abre otra ventana.
    sesiones_abriendose: list[str] = field(default_factory=list)
    #: Los que se confirmaron, en orden. Sirve para afirmar "se le pidió a
    #: Doyle que guardara la sesión de LEVIC" sin mirar dentro de la ruta.
    sesiones_confirmadas: list[str] = field(default_factory=list)
    #: Para los que se prepara el aviso honesto de Doyle: se confirmó y la
    #: página seguía viéndose como un login. Es la diferencia entre "ya está" y
    #: "vuelve a intentarlo", y sin poder prepararla no se puede probar que la
    #: pantalla la dice.
    sesiones_que_siguen_en_login: list[str] = field(default_factory=list)
    falla: Exception | None = None
    #: Términos que se pidieron, en orden. Sirve para comprobar el ORDEN de
    #: importancia del lote nocturno sin mirar dentro de la implementación.
    pedidos: list[str] = field(default_factory=list)
    #: Cuántas veces se preguntó por el estado de cada trabajo. Es lo que
    #: permite afirmar "sondeó tres veces" sin mirar dentro de la
    #: implementación.
    consultas: list[str] = field(default_factory=list)
    _trabajos: dict[str, str] = field(default_factory=dict)

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    def pedir_busqueda(self, termino: str) -> BusquedaPedida:
        self._revisar()
        self.pedidos.append(termino)
        job_id = f"trabajo-{len(self.pedidos)}"
        self._trabajos[job_id] = termino
        return BusquedaPedida(job_id=job_id, proveedores=self._proveedores(termino))

    def _proveedores(self, termino: str) -> tuple[str, ...]:
        """Los cuatro proveedores del trabajo, salgan de donde salgan.

        Doyle contesta el acuse con **todos** los proveedores que va a
        consultar, sin esperar a que ninguno termine, así que la lista sale de
        la primera vuelta preparada y no del resultado final.
        """
        vueltas = self.vueltas_por_termino.get(termino)
        if vueltas:
            return tuple(sorted(vueltas[0]))
        return tuple(sorted(self.resultados_por_termino.get(termino, {})))

    def estado_de_busqueda(self, job_id: str) -> EstadoDeBusqueda:
        self._revisar()
        termino = self._trabajos.get(job_id, "")
        self.consultas.append(job_id)

        vueltas = self.vueltas_por_termino.get(termino)
        if vueltas:
            # La última se queda: un trabajo terminado sigue contestando lo
            # mismo si alguien vuelve a preguntar, igual que el Doyle real
            # mientras el trabajo siga en memoria.
            proveedores = vueltas.pop(0) if len(vueltas) > 1 else vueltas[0]
        else:
            proveedores = self.resultados_por_termino.get(termino, {})

        return EstadoDeBusqueda(termino=termino, proveedores=dict(proveedores))

    def sesiones(self) -> list[SesionDeProveedor]:
        self._revisar()
        return [
            SesionDeProveedor(
                proveedor=s["proveedor"],
                nombre=s.get("nombre", s["proveedor"]),
                estado=s.get("estado", "sin_sesion"),
                guardada_en=s.get("guardada_en"),
            )
            for s in self.sesiones_en_memoria
        ]

    # ------------------------------------------- abrir sesión (ticket 19)
    #
    # El doble **no abre ningún navegador y no puede abrirlo**: apunta quién
    # se lo pidió y contesta. Eso no es una limitación del doble, es el punto
    # entero de que exista — Continental no toca un navegador nunca (regla 1
    # de `CLAUDE.md`), y una prueba que abriera Chrome estaría probando Doyle.

    def abrir_sesion(self, proveedor: str) -> SesionAbriendose:
        self._revisar()
        ya_abierta = proveedor in self.sesiones_abriendose
        if not ya_abierta:
            self.sesiones_abriendose.append(proveedor)
        return SesionAbriendose(proveedor=proveedor, ya_abierta=ya_abierta)

    def confirmar_sesion(self, proveedor: str) -> SesionConfirmada:
        self._revisar()
        if proveedor not in self.sesiones_abriendose:
            # El Doyle real contesta 400 con este mismo sentido: no hay
            # ventana que confirmar. Se levanta para que el doble rechace lo
            # mismo que rechaza el de verdad; un doble permisivo deja el suite
            # en verde y rompe en atlas.
            raise ValueError(
                f"No hay una sesión de {proveedor!r} abriéndose: primero se "
                "aprieta el botón que abre el navegador."
            )
        self.sesiones_abriendose.remove(proveedor)
        self.sesiones_confirmadas.append(proveedor)
        return SesionConfirmada(
            proveedor=proveedor,
            todavia_parece_login=proveedor in self.sesiones_que_siguen_en_login,
        )


def respuesta_lista(
    proveedor: str, filas: list[tuple[str, str, str]]
) -> RespuestaDeProveedor:
    """Un proveedor que sí contestó. Cada fila es `(clave, precio, existencia)`.

    El precio va como texto igual que en la interfaz real: una prueba que
    escriba `86.05` y no `"86.05"` estaría probando una conversión que el
    borde no hace, y que no debe hacer.
    """
    return RespuestaDeProveedor(
        proveedor=proveedor,
        estado="listo",
        filas=tuple(
            FilaDeProveedor(
                clave=clave,
                descripcion=f"RESULTADO {clave}",
                precio=precio,
                precio_publico="",
                existencia=existencia,
            )
            for clave, precio, existencia in filas
        ),
        total=len(filas),
    )


def respuesta_con_error(proveedor: str, mensaje: str) -> RespuestaDeProveedor:
    """Un proveedor que no dio dato, con el motivo que el encargado va a leer."""
    return RespuestaDeProveedor(proveedor=proveedor, estado="error", mensaje=mensaje)


#: El texto con el que Doyle anuncia una sesión caducada, copiado de
#: `Doyle/src/doyle/web/buscador.py` (revisado el 2026-09-19). Se copia entero
#: y no se inventa uno parecido: lo que `precios.leer_el_precio` distingue es
#: **este** mensaje, y una prueba escrita contra un texto inventado diría que
#: la sesión caducada se reconoce cuando en realidad no.
MENSAJE_DE_SESION_CAIDA = (
    "[nadro] la sesión caducó (o el portal rechazó esta sesión): "
    "el portal mandó al login."
)


def respuesta_con_sesion_caducada(proveedor: str) -> RespuestaDeProveedor:
    """El tercero de los cuatro finales: la sesión de ese portal ya no vale.

    Llega como un `error` cualquiera —Doyle no tiene un estado aparte para
    esto— y lo que lo distingue es el mensaje. Es el final que MÁS importa
    separar de los otros: es el único que el encargado arregla él, en dos clics
    (historia 33 del spec).
    """
    return RespuestaDeProveedor(
        proveedor=proveedor,
        estado="error",
        mensaje=MENSAJE_DE_SESION_CAIDA.replace("[nadro]", f"[{proveedor}]"),
    )


def respuesta_pendiente(proveedor: str, estado: str = "buscando") -> RespuestaDeProveedor:
    """El cuarto final, que no es un final: el proveedor sigue trabajando.

    `buscando` por omisión y no `pendiente`, porque es el estado en el que el
    Doyle real pasa los ~9 s de una búsqueda: `iniciar_busqueda` crea el
    trabajo en `pendiente` y el hilo lo mueve a `buscando` en su primera línea.
    Una prueba que solo usara `pendiente` dejaría sin ejercitar justo el estado
    que llega de verdad.
    """
    return RespuestaDeProveedor(proveedor=proveedor, estado=estado)


def respuesta_en_reconocimiento(proveedor: str) -> RespuestaDeProveedor:
    """Doyle todavía no sabe leer esa página.

    No es un fallo del portal y no se puede confundir con uno: lo primero se
    arregla escribiendo selectores y lo segundo volviendo a intentar.
    """
    return RespuestaDeProveedor(
        proveedor=proveedor,
        estado="reconocimiento",
        mensaje="Doyle todavía no sabe leer esta página",
    )


@dataclass
class AlmacenamientoFalso:
    """Doble de `AlmacenamientoDelPedido`: las mismas tablas, en memoria.

    **Este doble no puede ser permisivo.** Es lo único que las pruebas
    ejercitan —desde la torre no hay Postgres alcanzable— así que un doble que
    acepte lo que la base rechazaría deja el suite en verde y rompe en atlas.
    Por eso no reimplementa las reglas: llama a `revisar_la_lista`,
    `revisar_el_renglon` y `columnas_del_renglon` de `almacenamiento.py`, que
    son las mismas que arman y validan lo que va al `INSERT` real. Lo que aquí
    se agrega son las restricciones que no son de columna:

    - `UNIQUE (negocio, fecha_del_pedido)` → `PedidoSugeridoDuplicado`, que es
      el nombre en Python de `ux_pedido_sugerido_dia`.
    - `UNIQUE (pedido_sugerido_id, producto_id)` → un producto una vez por
      lista (`ux_renglon_producto`).
    - **Todo o nada**: se valida la lista entera antes de escribir el primer
      renglón, igual que la transacción de `AlmacenamientoPostgres`. Sin eso,
      una lista a medias quedaría ocupando el `UNIQUE` del día y ninguna carga
      posterior podría arreglarla — el rol no tiene `DELETE`.
    - **Las transiciones de estado**, que en la base viven en el `WHERE` de
      cada `UPDATE` y no en un CHECK: solo se descarta lo `abierto`, solo se
      devuelve a `abierto` lo `descartado`, y solo se corrige la cantidad de un
      renglón `abierto` **cuya lista siga `abierta`**. Aquí son las mismas
      condiciones, en el mismo orden, y devuelven `None` donde el `UPDATE` real
      devolvería cero filas.

    `falla` es el almacenamiento caído, que tiene que verse como un hueco con
    su motivo y no como una lista vacía (regla 4).

    `antes_de_insertar` es el gancho de la carrera: se dispara **una sola
    vez**, entre mirar si la lista existe e insertarla, que es exactamente el
    hueco por el que se cuela una segunda pestaña. Es la única manera honesta
    de probar que "nunca se duplica" no depende de ganar esa carrera.

    Guarda diccionarios con los nombres de las columnas de verdad, y no
    objetos cómodos, para que una prueba pueda afirmar sobre lo que *quedó
    escrito* —por ejemplo, que la clave vacía se guardó como `NULL`—.
    """

    listas: list[dict] = field(default_factory=list)
    #: Las filas de `pedidos.precio_de_proveedor`, en el orden en que se
    #: escribieron. Una LISTA y no un diccionario por pareja (renglón,
    #: proveedor): la tabla **agrega y nunca pisa**, y un diccionario haría que
    #: el doble sobreescribiera lo que Postgres conserva — el suite quedaría en
    #: verde sobre la decisión más importante del ticket 12.
    precios: list[dict] = field(default_factory=list)
    #: Las filas de `pedidos.corrida_del_lote` (ticket 19), en el orden en que
    #: se escribieron. También una LISTA: esa tabla solo crece igual que la del
    #: precio, y `ultima_corrida` elige la más reciente al leer, no al escribir.
    corridas: list[dict] = field(default_factory=list)
    #: Las filas de `pedidos.pedido` (ticket 20). Un diccionario por fila, con
    #: los nombres de las columnas de verdad, igual que las listas y los
    #: renglones: una prueba tiene que poder afirmar sobre lo que **quedó
    #: escrito** —que `proveedor_id` es `None` y no un cero, por ejemplo—.
    pedidos: list[dict] = field(default_factory=list)
    falla: Exception | None = None
    antes_de_insertar: Callable[[], object] | None = None
    _siguiente_lista: int = 1
    _siguiente_renglon: int = 1
    _siguiente_precio: int = 1
    _siguiente_corrida: int = 1
    _siguiente_pedido: int = 1

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    # ------------------------------------------------------------ lectura

    def _fila(self, negocio: str, fecha_del_pedido: dt.date) -> dict | None:
        for lista in self.listas:
            if (
                lista["negocio"] == negocio
                and lista["fecha_del_pedido"] == fecha_del_pedido
            ):
                return lista
        return None

    def _por_id(self, pedido_sugerido_id: int) -> dict | None:
        for lista in self.listas:
            if lista["pedido_sugerido_id"] == pedido_sugerido_id:
                return lista
        return None

    def _renglon_por_id(self, renglon_id: int) -> tuple[dict, dict] | None:
        """El renglón y la lista a la que pertenece, o `None` si no hay.

        Devuelve los dos porque toda operación sobre un renglón termina
        releyendo su lista entera: es lo que hace el `RETURNING
        pedido_sugerido_id` del `UPDATE` real, seguido de `_LEER_LISTA_POR_ID`.
        """
        for lista in self.listas:
            for fila in lista["renglones"]:
                if fila["renglon_id"] == renglon_id:
                    return fila, lista
        return None

    def leer(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        fila = self._fila(negocio, fecha_del_pedido)
        return None if fila is None else armar_guardado(fila, fila["renglones"])

    def leer_por_id(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        """El `WHERE` de `_LEER_LISTA_POR_ID`: el negocio y el id, nada más.

        **Con el negocio y no solo con el id**, igual que allá: una lista de
        otro negocio no se ve desde éste (regla 7), y un doble que la enseñara
        dejaría en verde una ruta que en atlas leería lo ajeno.
        """
        self._revisar()
        for fila in self.listas:
            if (
                fila["negocio"] == negocio
                and fila["pedido_sugerido_id"] == pedido_sugerido_id
            ):
                return armar_guardado(fila, fila["renglones"])
        return None

    def leer_renglon(self, negocio: str, renglon_id: int):
        """El `WHERE` de `_LEER_RENGLON_POR_ID`: el negocio y el id, nada más."""
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _ = encontrado
        if fila["negocio"] != negocio:
            return None
        return renglon_guardado_desde_columnas(fila)

    def corte_del_ultimo_cerrado(
        self, negocio: str, antes_de: dt.date
    ) -> dt.date | None:
        """El `max(ventas_consideradas_hasta)` de las cerradas, en memoria.

        Las tres condiciones son el `WHERE` de `_ULTIMO_CORTE`, en el mismo
        orden, y el `max` es el mismo: lo que se busca es hasta dónde llegó lo
        ya pedido, no cuál fila se cerró al final. Un doble que devolviera la
        última cerrada por orden de cierre haría retroceder el corte cuando
        alguien cierra hoy una lista vieja — y esos días se pedirían dos veces.
        """
        self._revisar()
        cortes = [
            lista["ventas_consideradas_hasta"]
            for lista in self.listas
            if lista["negocio"] == negocio
            and lista["estado"] == CERRADO
            and lista["fecha_del_pedido"] < antes_de
        ]
        return max(cortes) if cortes else None

    # ----------------------------------------------------------- escritura

    def abrir_el_dia(
        self,
        negocio: str,
        fecha_del_pedido: dt.date,
        ventana: Ventana,
        armar: Callable[[], Sequence[Renglon]],
    ) -> PedidoSugeridoGuardado:
        self._revisar()
        ya_estaba = self.leer(negocio, fecha_del_pedido)
        if ya_estaba is not None:
            return ya_estaba

        renglones = tuple(armar())

        if self.antes_de_insertar is not None:
            # Se desarma antes de llamarlo: el gancho vuelve a entrar aquí y si
            # siguiera puesto la recursión no pararía. Una carrera se pierde
            # una vez.
            gancho, self.antes_de_insertar = self.antes_de_insertar, None
            gancho()

        try:
            return self.insertar_la_lista(negocio, fecha_del_pedido, ventana, renglones)
        except PedidoSugeridoDuplicado:
            # Perdió la carrera. Lo que acaba de armar se tira y se devuelve la
            # lista que ya existe, que es la que esa persona está viendo. Contra
            # Postgres esto mismo llega como cero filas del `ON CONFLICT ... DO
            # NOTHING`, y desemboca en la misma relectura.
            return self.leer(negocio, fecha_del_pedido)

    def insertar_la_lista(
        self,
        negocio: str,
        fecha_del_pedido: dt.date,
        ventana: Ventana,
        renglones: Sequence[Renglon],
    ) -> PedidoSugeridoGuardado:
        """El `INSERT` pelado, con las restricciones de la base y sin reintentos.

        Existe aparte de `abrir_el_dia` para que una prueba pueda comprobar que
        el doble **se niega** igual que Postgres: si el rechazo estuviera
        escondido dentro del camino que lo atrapa, nadie podría verlo.
        """
        self._revisar()

        columnas = columnas_de_la_lista(negocio, fecha_del_pedido, ventana)
        revisar_la_lista(columnas)

        if self._fila(negocio, fecha_del_pedido) is not None:
            raise PedidoSugeridoDuplicado(
                f"Ya hay un pedido sugerido de {negocio} para {fecha_del_pedido}. "
                "Lo rechaza ux_pedido_sugerido_dia."
            )

        # Todo se revisa ANTES de escribir nada: es la transacción del lado
        # real, traducida.
        filas: list[dict] = []
        productos: set[int] = set()
        for renglon in renglones:
            fila = columnas_del_renglon(renglon, negocio)
            revisar_el_renglon(fila)
            if fila["producto_id"] in productos:
                raise ValueError(
                    f"El producto {fila['producto_id']} aparece dos veces en la "
                    "misma lista: lo rechaza ux_renglon_producto. Serían dos "
                    "veces la misma mercancía."
                )
            productos.add(fila["producto_id"])
            filas.append(fila)

        lista = {
            **columnas,
            "pedido_sugerido_id": self._siguiente_lista,
            # El instante real con zona que en la tabla pone `DEFAULT now()`.
            # Es un INSTANTE y no una fecha: decir cuándo se armó la lista es
            # justo lo que un reloj sabe y el almacén no.
            "armado_en": dt.datetime.now(dt.UTC),
            "renglones": [],
        }
        self._siguiente_lista += 1

        for fila in filas:
            fila["pedido_sugerido_id"] = lista["pedido_sugerido_id"]
            fila["renglon_id"] = self._siguiente_renglon
            self._siguiente_renglon += 1
            lista["renglones"].append(fila)

        self.listas.append(lista)
        return armar_guardado(lista, lista["renglones"])

    def poner_estado(
        self,
        pedido_sugerido_id: int,
        estado: str,
        cerrado_en: dt.datetime | None = None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado, revisado contra los CHECK antes de aplicarse.

        Aparte por la misma razón que `insertar_la_lista`: es donde se ve que
        el doble rechaza un `cerrado` sin hora, o una hora de cierre en una
        lista que no está cerrada, igual que `ck_pedido_sugerido_cierre`.
        """
        self._revisar()
        lista = self._por_id(pedido_sugerido_id)
        if lista is None:
            return None

        propuesta = {**lista, "estado": estado, "cerrado_en": cerrado_en}
        revisar_la_lista(propuesta)

        lista["estado"] = estado
        lista["cerrado_en"] = cerrado_en
        return armar_guardado(lista, lista["renglones"])

    def cerrar(
        self, negocio: str, pedido_sugerido_id: int
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        lista = self._por_id(pedido_sugerido_id)
        # Las tres condiciones son el `WHERE` del UPDATE real, en el mismo
        # orden: el negocio, el id y que siga abierta. Sin la última, un
        # segundo clic movería `cerrado_en` y una vencida resucitaría.
        if lista is None or lista["negocio"] != negocio or lista["estado"] != ABIERTO:
            return None
        return self.poner_estado(
            pedido_sugerido_id, CERRADO, cerrado_en=dt.datetime.now(dt.UTC)
        )

    # ------------------------------------------------ el estado del renglón

    def poner_estado_del_renglon(
        self,
        renglon_id: int,
        estado: str,
        descartado_por: str | None = None,
        descartado_en: dt.datetime | None = None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado de un renglón, revisado contra los CHECK.

        Aparte por la misma razón que `poner_estado` lo está para la lista: es
        donde se ve que el doble **se niega** igual que Postgres —un
        `descartado` sin firma, una firma en un renglón abierto, un estado que
        el glosario no conoce—. Si el rechazo estuviera escondido dentro del
        camino que lo evita, nadie podría verlo.

        Lo usan también las pruebas para poner un renglón en `en tránsito` o
        `recibido`, que son estados que **todavía ningún código escribe** (son
        los tickets 24 y 26): sin esto no habría forma de comprobar hoy que
        descartar no los toca.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado

        propuesta = {
            **fila,
            "estado": estado,
            "descartado_por": descartado_por,
            "descartado_en": descartado_en,
        }
        revisar_el_renglon(propuesta)

        fila.update(
            estado=estado,
            descartado_por=descartado_por,
            descartado_en=descartado_en,
        )
        return armar_guardado(lista, lista["renglones"])

    def descartar(
        self, negocio: str, renglon_id: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        # Las tres condiciones son el `WHERE` del UPDATE real, en el mismo
        # orden: el negocio, el id y que siga abierto. Sin la última, un
        # renglón `en tránsito` —que ya se le pidió a un proveedor— se podría
        # descartar, y el ticket 26 recibiría mercancía contra un renglón que
        # dice que nadie la pidió.
        if encontrado is None:
            return None
        fila, _ = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_ABIERTO:
            return None
        # El instante real con zona que en la tabla pone `now()`. Es un
        # INSTANTE y no una fecha: lo que se ancla en `max(fecha)` son las
        # fechas de venta.
        return self.poner_estado_del_renglon(
            renglon_id,
            RENGLON_DESCARTADO,
            descartado_por=quien,
            descartado_en=dt.datetime.now(dt.UTC),
        )

    def poner_la_cantidad(
        self,
        renglon_id: int,
        cantidad_final: int | None,
        ajustada_por: str | None = None,
        ajustada_en: dt.datetime | None = None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado de la cantidad, revisado contra los CHECK.

        Aparte de `ajustar_la_cantidad` por la misma razón que
        `poner_estado_del_renglon` lo está de `descartar`: es donde se ve que el
        doble **se niega** igual que Postgres —una cantidad de cero, una
        cantidad sin firma, una firma sin cantidad—. Si el rechazo estuviera
        escondido dentro del camino que lo evita, nadie podría verlo.

        **No escribe `cantidad_propuesta` por ninguna parte**, igual que el
        `UPDATE` real: la propuesta del sistema se escribe una sola vez, al
        armar la lista.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado

        propuesta = {
            **fila,
            "cantidad_final": cantidad_final,
            "ajustada_por": ajustada_por,
            "ajustada_en": ajustada_en,
        }
        revisar_el_renglon(propuesta)

        fila.update(
            cantidad_final=cantidad_final,
            ajustada_por=ajustada_por,
            ajustada_en=ajustada_en,
        )
        return armar_guardado(lista, lista["renglones"])

    def ajustar_la_cantidad(
        self, negocio: str, renglon_id: int, cantidad: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado
        # Las CUATRO condiciones son el `WHERE` de `_AJUSTAR_LA_CANTIDAD`, en el
        # mismo orden: el negocio, el renglón abierto, y **la lista abierta**,
        # que es lo que el ticket 11 pide con todas sus letras. Sin la última,
        # una cantidad nueva entraría en una lista que ya se pidió.
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_ABIERTO:
            return None
        if lista["estado"] != ABIERTO:
            return None
        # El instante real con zona que en la tabla pone `now()`. Es un INSTANTE
        # y no una fecha: lo que se ancla en `max(fecha)` son las fechas de
        # venta.
        return self.poner_la_cantidad(
            renglon_id,
            cantidad,
            ajustada_por=quien,
            ajustada_en=dt.datetime.now(dt.UTC),
        )

    # ------------------------------------- elegir proveedor y partir (20)

    def poner_el_proveedor(
        self,
        renglon_id: int,
        proveedor_elegido: str | None,
        elegido_por: str | None = None,
        elegido_en: dt.datetime | None = None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado de la elección, revisado contra los CHECK.

        Aparte de `elegir_proveedor` por la misma razón que `poner_la_cantidad`
        lo está de `ajustar_la_cantidad`: es donde se ve que el doble **se
        niega** igual que Postgres —una clave vacía, una elección sin firma, una
        firma sin elección—. Si el rechazo estuviera escondido dentro del camino
        que lo evita, nadie podría verlo.

        **No escribe ninguna sugerencia por ninguna parte**, igual que el
        `UPDATE` real: lo único que se guarda es lo que una persona decidió.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado

        propuesta = {
            **fila,
            "proveedor_elegido": proveedor_elegido,
            "elegido_por": elegido_por,
            "elegido_en": elegido_en,
        }
        revisar_el_renglon(propuesta)

        fila.update(
            proveedor_elegido=proveedor_elegido,
            elegido_por=elegido_por,
            elegido_en=elegido_en,
        )
        return armar_guardado(lista, lista["renglones"])

    def elegir_proveedor(
        self, negocio: str, renglon_id: int, proveedor: str, quien: str
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado
        # Las CUATRO condiciones son el `WHERE` de `_ELEGIR_PROVEEDOR`, en el
        # mismo orden y las mismas que el ajuste: el negocio, el renglón
        # abierto y **la lista abierta**. Sin la última, se armaría un pedido
        # dentro de una lista que ya se pidió.
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_ABIERTO:
            return None
        if lista["estado"] != ABIERTO:
            return None
        # El instante real con zona que en la tabla pone `now()`.
        return self.poner_el_proveedor(
            renglon_id,
            proveedor,
            elegido_por=quien,
            elegido_en=dt.datetime.now(dt.UTC),
        )

    def pedidos_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> tuple[PedidoGuardado, ...]:
        self._revisar()
        # El `order by proveedor` de `_LEER_PEDIDOS`, y no el orden de
        # escritura: dos cargas de la misma pantalla no deben enseñar las
        # columnas cambiadas de sitio.
        filas = [
            f
            for f in self.pedidos
            if f["negocio"] == negocio
            and f["pedido_sugerido_id"] == pedido_sugerido_id
        ]
        return tuple(
            pedido_desde_columnas(f) for f in sorted(filas, key=lambda f: f["proveedor"])
        )

    def _pedido_de(self, negocio: str, pedido_sugerido_id: int, proveedor: str):
        """El `ux_pedido_proveedor` del DDL: uno por proveedor dentro de la lista."""
        for fila in self.pedidos:
            if (
                fila["negocio"] == negocio
                and fila["pedido_sugerido_id"] == pedido_sugerido_id
                and fila["proveedor"] == proveedor
            ):
                return fila
        return None

    def guardar_la_particion(
        self,
        negocio: str,
        pedido_sugerido_id: int,
        pedidos,
    ) -> tuple[PedidoGuardado, ...] | None:
        """El `INSERT ... ON CONFLICT DO UPDATE` y los dos `UPDATE`, en memoria.

        Cuatro cosas se copian del lado real y las cuatro tienen una prueba:

        - **La lista y su estado son el `WHERE` del `INSERT ... SELECT`.** Si no
          existe en ese negocio, o ya no está `abierta`, no se escribe nada y se
          devuelve `None`.
        - **Uno por proveedor.** Volver a partir reencuentra el pedido que ya
          estaba y le reescribe el total, en vez de duplicarlo: es
          `ux_pedido_proveedor`, que está en la tabla desde el ticket 07.
        - **Solo lo que sigue en borrador se modifica**, que es el `WHERE` del
          `DO UPDATE`.
        - **Todo o nada**: se validan todos los pedidos antes de escribir el
          primero, igual que la transacción del lado real.
        """
        self._revisar()
        lista = self._por_id(pedido_sugerido_id)
        if lista is None or lista["negocio"] != negocio or lista["estado"] != ABIERTO:
            return None

        columnas_por_pedido = []
        for pedido in pedidos:
            columnas = columnas_del_pedido(
                negocio,
                pedido_sugerido_id,
                pedido.proveedor,
                pedido.proveedor_id,
                pedido.total_sin_iva,
            )
            revisar_el_pedido(columnas)
            columnas_por_pedido.append((pedido, columnas))

        # Los pedidos de esta lista que siguen en borrador. Se mira ANTES de
        # escribir nada, igual que el `EXISTS` de las dos sentencias reales:
        # lo que ya no es borrador no se toca, ni para reescribirlo, ni para
        # soltar sus renglones, ni para movérselos a otro pedido.
        borradores_antes = {
            f["pedido_id"]
            for f in self.pedidos
            if f["negocio"] == negocio and f["estado"] == BORRADOR
        }

        asignados: list[int] = []
        for pedido, columnas in columnas_por_pedido:
            fila = self._pedido_de(negocio, pedido_sugerido_id, pedido.proveedor)
            if fila is None:
                fila = {
                    **columnas,
                    "pedido_id": self._siguiente_pedido,
                    "armado_en": dt.datetime.now(dt.UTC),
                }
                self._siguiente_pedido += 1
                self.pedidos.append(fila)
            elif fila["estado"] == BORRADOR:
                # El `SET` del `DO UPDATE`: el estado NO se toca y el proveedor
                # tampoco —es la identidad—; lo que se reescribe es el puente,
                # el total y la hora de armado.
                fila.update(
                    proveedor_id=columnas["proveedor_id"],
                    total_sin_iva=columnas["total_sin_iva"],
                    armado_en=dt.datetime.now(dt.UTC),
                )
            else:
                # El `WHERE pedido.estado = 'borrador'` que no se cumplió: cero
                # filas, y sus renglones tampoco se mueven.
                continue

            for linea in pedido.lineas:
                renglon = next(
                    (
                        r
                        for r in lista["renglones"]
                        if r["renglon_id"] == linea.renglon_id
                    ),
                    None,
                )
                # El `WHERE` de `_ASIGNAR_RENGLONES`: de esta lista, abierto, y
                # sin colgar de un pedido que dejó de ser borrador.
                if renglon is None or renglon["estado"] != RENGLON_ABIERTO:
                    continue
                if (
                    renglon.get("pedido_id") is not None
                    and renglon["pedido_id"] not in borradores_antes
                ):
                    continue
                renglon["pedido_id"] = fila["pedido_id"]
                asignados.append(renglon["renglon_id"])

        # `_SOLTAR_RENGLONES`: lo que esta partición ya no reparte sale de su
        # pedido, salvo lo que cuelgue de un pedido que ya no es borrador.
        borradores = {
            f["pedido_id"]
            for f in self.pedidos
            if f["negocio"] == negocio and f["estado"] == BORRADOR
        }
        for renglon in lista["renglones"]:
            if (
                renglon.get("pedido_id") is not None
                and renglon["estado"] == RENGLON_ABIERTO
                and renglon["renglon_id"] not in asignados
                and renglon["pedido_id"] in borradores
            ):
                renglon["pedido_id"] = None

        # `_VACIAR_LOS_PEDIDOS_SIN_RENGLONES`: el pedido que se quedó sin
        # ninguno pierde su total. A NULL y no a cero — un pedido vacío no
        # cuesta nada porque no tiene nada. Sin esto, el pedido de la partición
        # anterior seguiría enseñando su total con la mercancía ya movida a
        # otro proveedor, y nadie lo vería como un error.
        con_renglones = {
            r.get("pedido_id")
            for r in lista["renglones"]
            if r.get("pedido_id") is not None
        }
        for fila in self.pedidos:
            if (
                fila["negocio"] == negocio
                and fila["pedido_sugerido_id"] == pedido_sugerido_id
                and fila["estado"] == BORRADOR
                and fila["pedido_id"] not in con_renglones
            ):
                fila["total_sin_iva"] = None

        return self.pedidos_de_la_lista(negocio, pedido_sugerido_id)

    def devolver_a_abierto(
        self, negocio: str, renglon_id: int
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _ = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_DESCARTADO:
            return None
        # Las dos columnas se van a `None` juntas: lo exige ck_renglon_descarte
        # y lo comprueba `poner_estado_del_renglon`.
        return self.poner_estado_del_renglon(renglon_id, RENGLON_ABIERTO)

    # ------------------------------------------- el precio congelado (12)

    def guardar_precios(
        self, negocio: str, renglon_id: int, lecturas: Sequence[LecturaDePrecio]
    ) -> int:
        """El `INSERT ... SELECT` de `_GUARDAR_PRECIO`, con sus mismas reglas.

        Tres cosas se copian del lado real y las tres tienen una prueba:

        - **El renglón y el negocio son el `WHERE`.** Si no hay renglón con ese
          id en ese negocio no se escribe nada y se devuelve cero, igual que
          cero filas del `INSERT ... SELECT`. El estado del renglón NO entra:
          congelar un precio no es una transición (ver `guardar_precios` en
          `almacenamiento.py`).
        - **Todo o nada.** Se validan las cuatro lecturas antes de escribir la
          primera, igual que la transacción del lado real. Una consulta a
          medias diría que a dos proveedores no se les preguntó.
        - **Agrega, nunca pisa.** Una segunda consulta del mismo renglón deja
          filas nuevas y las anteriores siguen ahí.
        """
        self._revisar()
        if not lecturas:
            return 0

        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None or encontrado[0]["negocio"] != negocio:
            return 0

        filas = []
        for lectura in lecturas:
            columnas = columnas_del_precio(lectura, negocio, renglon_id)
            revisar_el_precio(columnas)
            filas.append(columnas)

        # El instante real con zona que en la tabla pone `DEFAULT now()`. Se
        # calcula UNA vez para las cuatro filas porque `now()` es la hora de la
        # TRANSACCIÓN: fue una sola lectura y las cuatro lo comparten. Un
        # `now()` por fila daría cuatro instantes distintos y la pantalla
        # mostraría cuatro fechas donde hubo una.
        instante = dt.datetime.now(dt.UTC)
        for columnas in filas:
            columnas["consultado_en"] = instante
            columnas["precio_de_proveedor_id"] = self._siguiente_precio
            self._siguiente_precio += 1
            self.precios.append(columnas)
        return len(filas)

    def precios_del_renglon(
        self, negocio: str, renglon_id: int
    ) -> tuple[PrecioDeProveedor, ...]:
        self._revisar()
        return ultimo_por_proveedor(
            [
                precio_desde_columnas(f)
                for f in self.precios
                if f["negocio"] == negocio and f["renglon_id"] == renglon_id
            ]
        )

    def precios_de_la_lista(
        self, negocio: str, pedido_sugerido_id: int
    ) -> dict[int, tuple[PrecioDeProveedor, ...]]:
        self._revisar()
        de_la_lista = {
            fila["renglon_id"]
            for lista in self.listas
            if lista["pedido_sugerido_id"] == pedido_sugerido_id
            and lista["negocio"] == negocio
            for fila in lista["renglones"]
        }

        por_renglon: dict[int, list] = {}
        for f in self.precios:
            if f["negocio"] != negocio or f["renglon_id"] not in de_la_lista:
                continue
            por_renglon.setdefault(f["renglon_id"], []).append(precio_desde_columnas(f))

        # Un renglón sin ninguna consulta no aparece, igual que en el SQL: son
        # las filas que el `DISTINCT ON` no devuelve porque no existen.
        return {
            renglon_id: ultimo_por_proveedor(filas)
            for renglon_id, filas in por_renglon.items()
        }

    # ------------------------------------------ la corrida del lote (19)

    def guardar_la_corrida(self, negocio: str, corrida: CorridaDelLote) -> int:
        """El `INSERT` de `_GUARDAR_CORRIDA`, con sus mismas reglas.

        **Sin `WHERE` contra la lista**, igual que el de verdad: una corrida en
        la que no hubo lista es justo la que más hace falta poder escribir.

        `termino_en` lo pone aquí el doble con la hora de ahora, que es lo que
        la tabla hace con su `DEFAULT now()`.
        """
        self._revisar()
        columnas = columnas_de_la_corrida(corrida, negocio)
        revisar_la_corrida(columnas)
        columnas["corrida_del_lote_id"] = self._siguiente_corrida
        columnas["termino_en"] = dt.datetime.now(dt.UTC)
        self._siguiente_corrida += 1
        self.corridas.append(columnas)
        return columnas["corrida_del_lote_id"]

    def ultima_corrida(
        self, negocio: str, pedido_sugerido_id: int
    ) -> CorridaDelLote | None:
        """El `order by termino_en desc, corrida_del_lote_id desc limit 1`.

        El desempate por id va aquí igual que allá: dos corridas escritas en el
        mismo microsegundo —alguien lanzando el lote a mano dos veces— dejarían
        que el orden lo decidiera el plan de Postgres.
        """
        self._revisar()
        de_la_lista = [
            f
            for f in self.corridas
            if f["negocio"] == negocio
            and f["pedido_sugerido_id"] == pedido_sugerido_id
        ]
        if not de_la_lista:
            return None
        ultima = max(
            de_la_lista, key=lambda f: (f["termino_en"], f["corrida_del_lote_id"])
        )
        return corrida_desde_columnas(ultima)

    def vencer_las_de_dias_anteriores(
        self, negocio: str, fecha_del_pedido: dt.date
    ) -> int:
        self._revisar()
        movidas = 0
        for lista in self.listas:
            if (
                lista["negocio"] == negocio
                and lista["estado"] == ABIERTO
                and lista["fecha_del_pedido"] < fecha_del_pedido
            ):
                # `cerrado_en` se queda en None: lo exige ck_pedido_sugerido_cierre
                # y lo comprueba `poner_estado`.
                self.poner_estado(lista["pedido_sugerido_id"], VENCIDO)
                movidas += 1
        return movidas
