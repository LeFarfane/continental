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
    CERRADO,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    VENCIDO,
    PedidoSugeridoDuplicado,
    PedidoSugeridoGuardado,
    Ventana,
    armar_guardado,
    columnas_de_la_lista,
    columnas_del_renglon,
    revisar_el_renglon,
    revisar_la_lista,
)
from continental.doyle import (
    BusquedaPedida,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
    SesionDeProveedor,
)


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
    sesiones_en_memoria: list[dict] = field(default_factory=list)
    falla: Exception | None = None
    #: Términos que se pidieron, en orden. Sirve para comprobar el ORDEN de
    #: importancia del lote nocturno sin mirar dentro de la implementación.
    pedidos: list[str] = field(default_factory=list)
    _trabajos: dict[str, str] = field(default_factory=dict)

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    def pedir_busqueda(self, termino: str) -> BusquedaPedida:
        self._revisar()
        self.pedidos.append(termino)
        job_id = f"trabajo-{len(self.pedidos)}"
        self._trabajos[job_id] = termino
        return BusquedaPedida(
            job_id=job_id,
            proveedores=tuple(sorted(self.resultados_por_termino.get(termino, {}))),
        )

    def estado_de_busqueda(self, job_id: str) -> EstadoDeBusqueda:
        self._revisar()
        termino = self._trabajos.get(job_id, "")
        return EstadoDeBusqueda(
            termino=termino,
            proveedores=dict(self.resultados_por_termino.get(termino, {})),
        )

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
    falla: Exception | None = None
    antes_de_insertar: Callable[[], object] | None = None
    _siguiente_lista: int = 1
    _siguiente_renglon: int = 1

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
