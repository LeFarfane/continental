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
import dataclasses
from dataclasses import dataclass, field
from decimal import Decimal

from continental.almacen import DiaCalendario, LineaDeCompra, LineaDeVenta, Producto
from continental.almacenamiento import (
    ABIERTO,
    BORRADOR,
    CANCELADO,
    CERRADO,
    ENVIADO,
    RENGLON_ABIERTO,
    RENGLON_CANCELADO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_POSPUESTO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    ESTADOS_QUE_ATIENDEN_EL_PRODUCTO,
    ESTADOS_QUE_CIERRAN_EL_TRANSITO,
    ESTADOS_QUE_TERMINAN_EL_TRANSITO,
    VENCIDO,
    ConciliacionConfirmada,
    CorridaDelLote,
    EvidenciaDeLaSesion,
    LoYaPedido,
    PedidoCancelado,
    PedidoEnviado,
    PedidoMandadoAEspera,
    PedidoSugeridoDuplicado,
    PedidoSugeridoGuardado,
    PrecioDeProveedor,
    PruebaDeLaSesion,
    RenglonConciliado,
    RenglonGuardado,
    RenglonRecibido,
    Vecinos,
    Ventana,
    _firma_de_la_conciliacion,
    armar_guardado,
    columnas_de_la_corrida,
    columnas_de_la_lista,
    PedidoGuardado,
    columnas_del_pedido,
    columnas_del_precio,
    columnas_del_renglon,
    corrida_desde_columnas,
    lo_ya_pedido_desde_columnas,
    precio_desde_columnas,
    renglon_guardado_desde_columnas,
    renglon_recibido_desde_columnas,
    pedido_desde_columnas,
    revisar_el_pedido,
    revisar_el_precio,
    revisar_el_renglon,
    revisar_la_corrida,
    revisar_la_lista,
    revisar_la_prueba,
    ultimo_por_proveedor,
)
from continental.minimos import MinimoDelProveedor, revisar_el_minimo
from continental.doyle import (
    ArticuloVigilado,
    BusquedaDesconocida,
    BusquedaPedida,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
    SesionAbriendose,
    SesionConfirmada,
    PortalDeBusqueda,
    ProveedorDesconocido,
    SesionDeProveedor,
    VigiladoDesconocido,
    VisorOcupado,
    VistaAbierta,
    VistaDesconocida,
)
from continental.precios import (
    MOTIVOS_QUE_PASARON_DEL_LOGIN,
    NOMBRES_DE_PROVEEDOR,
    SESION_CADUCADA,
    LecturaDePrecio,
)
from continental.transiciones import (
    motivo_para_no_cancelar,
    motivo_para_no_corregir,
    motivo_para_no_editar,
    motivo_para_no_enviar,
    proveedor_de_la_espera,
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
    #: Días de calendario que una prueba quiere forzar (festivos, sobre todo):
    #: `{fecha: DiaCalendario}`. Un día que no está aquí se calcula solo —
    #: domingo por `weekday()`, nunca festivo—, igual que `dim_fecha` marca
    #: `es_cerrado` sin mirar el festivo (la trampa del 2026-09-27).
    dias_en_memoria: dict[dt.date, DiaCalendario] = field(default_factory=dict)
    #: La tasa de impuestos por producto, para `tasas_de_impuestos`. Un
    #: producto que no está aquí es uno cuya tasa no se sabe.
    tasas_en_memoria: dict[int, Decimal] = field(default_factory=dict)
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

    def productos_por_clave(self, claves) -> list[Producto]:
        self._revisar()
        buscadas = {c.strip() for c in claves if c and c.strip()}
        return [p for p in self.catalogo_en_memoria if p.clave.strip() in buscadas]

    def compras_desde(self, fecha: dt.date) -> list[LineaDeCompra]:
        self._revisar()
        return [c for c in self.compras_en_memoria if c.fecha >= fecha]

    def productos_con_compras(self, productos) -> frozenset[int]:
        self._revisar()
        productos = set(productos)
        return frozenset(c.producto_id for c in self.compras_en_memoria if c.producto_id in productos)

    def tasas_de_impuestos(self, productos) -> dict[int, Decimal]:
        self._revisar()
        return {p: self.tasas_en_memoria[p] for p in set(productos) if p in self.tasas_en_memoria}

    def ultima_fecha_con_ventas(self) -> dt.date | None:
        self._revisar()
        if not self.ventas_en_memoria:
            return None
        return max(v.fecha for v in self.ventas_en_memoria)

    def dia(self, fecha: dt.date) -> DiaCalendario:
        self._revisar()
        if fecha in self.dias_en_memoria:
            return self.dias_en_memoria[fecha]
        return DiaCalendario(
            fecha=fecha,
            es_cerrado=fecha.weekday() == 6,  # domingo, como `dim_fecha.es_cerrado`
            es_festivo_oficial=False,
            nombre_evento=None,
        )

    def dias_entre(self, desde: dt.date, hasta: dt.date) -> list[DiaCalendario]:
        self._revisar()
        dias = []
        cursor = desde
        while cursor <= hasta:
            dias.append(self.dia(cursor))
            cursor += dt.timedelta(days=1)
        return dias


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
    #: Las que se cerraron sin guardar, en orden (pestaña de Sesiones).
    sesiones_canceladas: list[str] = field(default_factory=list)
    #: Para los que se prepara el aviso honesto de Doyle: se confirmó y la
    #: página seguía viéndose como un login. Es la diferencia entre "ya está" y
    #: "vuelve a intentarlo", y sin poder prepararla no se puede probar que la
    #: pantalla la dice.
    sesiones_que_siguen_en_login: list[str] = field(default_factory=list)
    #: Las vistas del portal abiertas en el visor (ADR 0026): proveedor ->
    #: término con que se abrió. Es el `_vistas` del Doyle real: una sola a la
    #: vez, y un segundo `ver` del mismo proveedor NO abre otra.
    vistas_abiertas: dict[str, str] = field(default_factory=dict)
    #: Todo lo que se pidió ver, en orden: `(proveedor, término)`.
    vistas_pedidas: list[tuple[str, str]] = field(default_factory=list)
    #: Las vistas que se cerraron a petición, en orden.
    vistas_cerradas: list[str] = field(default_factory=list)
    #: Los proveedores cuya vista se prepara con el aviso «parece login».
    vistas_que_parecen_login: list[str] = field(default_factory=list)
    #: Los proveedores que Doyle está consultando ahora: ver ese portal rebota.
    proveedores_consultando: list[str] = field(default_factory=list)
    #: Lo que contesta `GET /api/portales`: la misma forma que el Doyle real
    #: (medido en su repo, commit 9c72f5e). NADRO busca por dirección, LEVIC
    #: tiene la página de búsqueda sola y QuePharma no tiene dirección.
    portales_en_memoria: dict[str, PortalDeBusqueda] = field(
        default_factory=lambda: {
            "nadro": PortalDeBusqueda(
                "https://i22.nadro.mx/{termino}?_q={termino}&map=ft", True
            ),
            "levic": PortalDeBusqueda(
                "https://www.levicventas.mx/frm_Catalogo_Levic.aspx", False
            ),
            "quepharma": PortalDeBusqueda(None, False),
        }
    )
    #: Cuántas veces se leyó `/api/portales`. Sirve para afirmar «una lectura
    #: por respuesta» sin mirar dentro de la ruta.
    lecturas_de_portales: int = 0
    falla: Exception | None = None
    #: Términos que se pidieron, en orden. Sirve para comprobar el ORDEN de
    #: importancia del lote nocturno sin mirar dentro de la implementación.
    pedidos: list[str] = field(default_factory=list)
    #: Cuántas veces se preguntó por el estado de cada trabajo. Es lo que
    #: permite afirmar "sondeó tres veces" sin mirar dentro de la
    #: implementación.
    consultas: list[str] = field(default_factory=list)
    #: La lista de vigilancia: dicts con los campos de `ArticuloVigilado`.
    vigilados_en_memoria: list[dict] = field(default_factory=list)
    #: Cuántas veces se le pidió «Revisar ahora».
    revisiones: int = 0
    #: El filtro de proveedores de cada búsqueda pedida, en orden (vacío = los cuatro).
    filtros: list[tuple[str, ...]] = field(default_factory=list)
    _trabajos: dict[str, str] = field(default_factory=dict)
    _filtro_del_trabajo: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    def pedir_busqueda(self, termino: str, proveedores: tuple[str, ...] = ()) -> BusquedaPedida:
        self._revisar()
        self.pedidos.append(termino)
        self.filtros.append(tuple(proveedores))
        job_id = f"trabajo-{len(self.pedidos)}"
        self._trabajos[job_id] = termino
        self._filtro_del_trabajo[job_id] = tuple(proveedores)
        todos = self._proveedores(termino)
        return BusquedaPedida(
            job_id=job_id,
            proveedores=tuple(p for p in todos if not proveedores or p in proveedores),
        )

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
        self.consultas.append(job_id)
        if job_id not in self._trabajos:
            # El Doyle real contesta 404 a un trabajo que no tiene —guarda sus
            # búsquedas en memoria y un reinicio las borra—, y el cliente lo
            # convierte en `BusquedaDesconocida`. Hasta el 2026-09-28 el doble
            # contestaba una búsqueda vacía: otro doble alejándose del real
            # (condición de revisión del ADR 0001, enmienda del 2026-09-27).
            raise BusquedaDesconocida(job_id)
        termino = self._trabajos[job_id]

        vueltas = self.vueltas_por_termino.get(termino)
        if vueltas:
            # La última se queda: un trabajo terminado sigue contestando lo
            # mismo si alguien vuelve a preguntar, igual que el Doyle real
            # mientras el trabajo siga en memoria.
            proveedores = vueltas.pop(0) if len(vueltas) > 1 else vueltas[0]
        else:
            proveedores = self.resultados_por_termino.get(termino, {})

        # El filtro de proveedores, igual que el Doyle real: solo contesta
        # por los que se pidieron.
        filtro = self._filtro_del_trabajo.get(job_id, ())
        if filtro:
            proveedores = {c: r for c, r in proveedores.items() if c in filtro}
        return EstadoDeBusqueda(termino=termino, proveedores=dict(proveedores))

    def sesiones(self) -> list[SesionDeProveedor]:
        self._revisar()
        return [
            SesionDeProveedor(
                proveedor=s["proveedor"],
                nombre=s.get("nombre", s["proveedor"]),
                # `abriendo` GANA sobre lo que diga la fila, porque así es el
                # Doyle real: su `listar()` saca ese estado del mismo
                # diccionario en memoria que `abrir()` acaba de poblar, no de
                # un marcador en disco. Sin esto el doble podía contestar
                # `sin_sesion` de un proveedor cuya ventana el propio doble
                # tenía abierta, y una prueba de la regla de una-ventana-a-la-
                # vez (ADR 0018) habría pasado en verde sin ejercitarla.
                estado=(
                    "abriendo"
                    if s["proveedor"] in self.sesiones_abriendose
                    else s.get("estado", "sin_sesion")
                ),
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

    def cancelar_sesion(self, proveedor: str) -> None:
        self._revisar()
        if proveedor not in self.sesiones_abriendose:
            # El 400 del Doyle real (`sesiones._tomar`): no hay ventana que cerrar.
            raise ValueError(f"No hay una sesión de {proveedor!r} abriéndose.")
        self.sesiones_abriendose.remove(proveedor)
        self.sesiones_canceladas.append(proveedor)

    # ------------------------------------------ ver en el portal (ADR 0026)
    #
    # Igual que abrir sesión: el doble no abre ningún navegador, apunta qué se
    # le pidió y rechaza lo mismo que rechaza el Doyle real (409 con su frase).

    def ver_en_portal(self, proveedor: str, termino: str) -> VistaAbierta | VisorOcupado:
        self._revisar()
        if proveedor not in NOMBRES_DE_PROVEEDOR:
            raise ProveedorDesconocido(proveedor)
        self.vistas_pedidas.append((proveedor, termino))
        if proveedor in self.proveedores_consultando:
            return VisorOcupado(
                f"{NOMBRES_DE_PROVEEDOR[proveedor]} está consultando ahora; "
                "espera a que termine."
            )
        if self.sesiones_abriendose:
            return VisorOcupado(
                "El visor lo usa una sesión que espera a que alguien entre; "
                "termínala primero."
            )
        # La vista de OTRO proveedor no estorba: el Doyle real la REEMPLAZA
        # (cierra la vieja y abre la nueva). `ya_abierta` es solo "ya había una
        # de este mismo proveedor".
        ya_abierta = proveedor in self.vistas_abiertas
        self.vistas_abiertas = {proveedor: termino}
        return VistaAbierta(
            proveedor=proveedor,
            ya_abierta=ya_abierta,
            parece_login=proveedor in self.vistas_que_parecen_login,
        )

    def cerrar_vista(self, proveedor: str) -> None:
        self._revisar()
        if proveedor not in self.vistas_abiertas:
            raise VistaDesconocida(proveedor)
        del self.vistas_abiertas[proveedor]
        self.vistas_cerradas.append(proveedor)

    def portales(self) -> dict[str, PortalDeBusqueda]:
        self._revisar()
        self.lecturas_de_portales += 1
        return dict(self.portales_en_memoria)

    # ----------------------------------------- la vigilancia (2026-09-28)
    #
    # La tabla `vigilancia` de Doyle, en una lista. Rechaza lo mismo que el
    # Doyle real —404 para un id que no tiene— y ordena igual: lo más nuevo
    # primero.

    def vigilados(self) -> list[ArticuloVigilado]:
        self._revisar()
        return [ArticuloVigilado(**v) for v in reversed(self.vigilados_en_memoria)]

    def vigilar(self, termino: str, proveedores: tuple[str, ...]) -> ArticuloVigilado:
        self._revisar()
        nuevo = {
            "articulo_id": max((v["articulo_id"] for v in self.vigilados_en_memoria), default=0) + 1,
            "termino": termino,
            "proveedores": tuple(proveedores),
        }
        self.vigilados_en_memoria.append(nuevo)
        return ArticuloVigilado(**nuevo)

    def _vigilado(self, articulo_id: int) -> dict:
        for v in self.vigilados_en_memoria:
            if v["articulo_id"] == articulo_id:
                return v
        raise VigiladoDesconocido(articulo_id)

    def dejar_de_vigilar(self, articulo_id: int) -> None:
        self._revisar()
        self.vigilados_en_memoria.remove(self._vigilado(articulo_id))

    def marcar_visto(self, articulo_id: int) -> None:
        self._revisar()
        self._vigilado(articulo_id)["avisado"] = True

    def revisar_la_vigilancia(self) -> None:
        self._revisar()
        self.revisiones += 1


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


#: «No tocar esta columna» en `poner_estado_del_renglon`: `None` es un valor
#: legítimo de `pedido_id` y de las columnas de la espera (lo sacan del pedido o
#: lo dejan sin dueño), así que no sirve para decir «igual que antes».
_IGUAL = object()


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
    #: Lo que contestó cada portal (`pedidos.lectura_de_portal`, 2026-09-28).
    lecturas_de_portal: list[dict] = field(default_factory=list)
    #: Las pruebas de sesión (`pedidos.prueba_de_sesion`, ADR 0024): una lista y
    #: no un diccionario por portal, porque la tabla solo crece y la última se
    #: elige al leer, no al escribir. Cada fila lleva `probada_en`, que el doble
    #: pone con la hora de ahora —lo que hace el `DEFAULT now()`—; una prueba
    #: puede sembrar la suya con la hora que necesite.
    pruebas_de_sesion: list[dict] = field(default_factory=list)
    #: Los mínimos de los proveedores (`pedidos.minimo_del_proveedor`, ticket 08):
    #: un diccionario por `(negocio, proveedor)`, igual que la llave primaria de
    #: la tabla. Sobreescribir es reemplazar la entrada; sin entrada es «sin
    #: mínimo capturado». Cada valor es un `MinimoDelProveedor`.
    minimos: dict = field(default_factory=dict)
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

    def vecinos(self, negocio: str, fecha_del_pedido: dt.date) -> Vecinos:
        """`_VECINOS` en memoria: el `max`/`min` de `fecha_del_pedido` a cada lado.

        Sin filtro de estado, igual que allá: un vecino `vencido` sigue siendo
        un día con lista.
        """
        self._revisar()
        anteriores = [
            lista["fecha_del_pedido"]
            for lista in self.listas
            if lista["negocio"] == negocio
            and lista["fecha_del_pedido"] < fecha_del_pedido
        ]
        siguientes = [
            lista["fecha_del_pedido"]
            for lista in self.listas
            if lista["negocio"] == negocio
            and lista["fecha_del_pedido"] > fecha_del_pedido
        ]
        return Vecinos(
            anterior=max(anteriores) if anteriores else None,
            siguiente=min(siguientes) if siguientes else None,
        )

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

    def piso_sin_pedir(self, negocio: str, antes_de: dt.date) -> dt.date | None:
        """El `min(ventas_consideradas_desde)` de las que NO cerraron.

        Las tres condiciones son el `WHERE` de `_PISO_SIN_PEDIR`, en el mismo
        orden. `estado != CERRADO` y no una lista de estados prohibidos, igual
        que allá: el día que aparezca un cuarto estado, entra solo.

        Y `min` y no `max`: si quedaron varias sin cerrar, el piso es el
        principio de la más vieja. Cubrirlas a medias esconde el hueco entre
        renglones que sí están.
        """
        self._revisar()
        pisos = [
            lista["ventas_consideradas_desde"]
            for lista in self.listas
            if lista["negocio"] == negocio
            and lista["estado"] != CERRADO
            and lista["fecha_del_pedido"] < antes_de
        ]
        return min(pisos) if pisos else None

    def lo_ya_pedido(
        self, negocio: str, antes_de: dt.date
    ) -> tuple[LoYaPedido, ...]:
        """`_LO_YA_PEDIDO`, en memoria y con las mismas condiciones (ticket 24).

        - **Todo lo `en tránsito`** de listas anteriores a `antes_de`, sin más
          condición.
        - **Lo recibido que nadie ha atendido**: el `NOT EXISTS` de allá. Una
          lista posterior (y anterior a `antes_de`) lo atendió si está
          **cerrada** y trae el producto, o si trae el producto **ya pedido**
          otra vez.
        - **Lo cancelado que nadie ha atendido** (ticket 25), con la misma
          condición. Y un cancelado posterior también atiende: se armó con la
          memoria y ya carga con lo pendiente.

        El negocio se mira en la lista **y** en el renglón, que son las dos
        uniones del lado real; y el pedido se busca con su negocio, que es la
        tercera. En el mismo orden: por día de la lista y luego por renglón.
        """
        self._revisar()
        propias = sorted(
            (
                lista
                for lista in self.listas
                if lista["negocio"] == negocio and lista["fecha_del_pedido"] < antes_de
            ),
            key=lambda lista: lista["fecha_del_pedido"],
        )

        def atendido_despues(producto_id: int, fecha: dt.date) -> bool:
            return any(
                otra["fecha_del_pedido"] > fecha
                and fila["negocio"] == negocio
                and fila["producto_id"] == producto_id
                and (
                    otra["estado"] == CERRADO
                    or fila["estado"] in ESTADOS_QUE_ATIENDEN_EL_PRODUCTO
                )
                for otra in propias
                for fila in otra["renglones"]
            )

        resultado = []
        for lista in propias:
            for fila in sorted(lista["renglones"], key=lambda f: f["renglon_id"]):
                if fila["negocio"] != negocio:
                    continue
                if fila["estado"] == RENGLON_EN_TRANSITO:
                    pass
                elif fila["estado"] in ESTADOS_QUE_TERMINAN_EL_TRANSITO:
                    if atendido_despues(fila["producto_id"], lista["fecha_del_pedido"]):
                        continue
                else:
                    continue
                pedido = next(
                    (
                        p
                        for p in self.pedidos
                        if p["pedido_id"] == fila.get("pedido_id")
                        and p["negocio"] == negocio
                    ),
                    None,
                )
                resultado.append(
                    lo_ya_pedido_desde_columnas(
                        {
                            **fila,
                            "fecha_del_pedido": lista["fecha_del_pedido"],
                            "ventas_consideradas_hasta": lista[
                                "ventas_consideradas_hasta"
                            ],
                            "ventas_consideradas_desde": lista[
                                "ventas_consideradas_desde"
                            ],
                            "proveedor": pedido["proveedor"] if pedido else None,
                            "enviado_por": pedido.get("enviado_por") if pedido else None,
                            "enviado_en": pedido.get("enviado_en") if pedido else None,
                            "estado_del_pedido": pedido["estado"] if pedido else None,
                            "proveedor_id": pedido.get("proveedor_id") if pedido else None,
                        }
                    )
                )
        return tuple(resultado)

    def lo_pospuesto(
        self, negocio: str, antes_de: dt.date
    ) -> tuple[RenglonGuardado, ...]:
        """`_LO_POSPUESTO`, en memoria: los `pospuesto` de la lista anterior (ADR 0025).

        **Solo la lista inmediatamente anterior** a `antes_de` —la de fecha más
        reciente que sea menor—, y de ninguna otra: pasan una vez. En el orden
        de los renglones, como el `order by renglon_id` de allá.
        """
        self._revisar()
        anteriores = [
            lista
            for lista in self.listas
            if lista["negocio"] == negocio and lista["fecha_del_pedido"] < antes_de
        ]
        if not anteriores:
            return ()
        ultima = max(anteriores, key=lambda lista: lista["fecha_del_pedido"])
        return tuple(
            renglon_guardado_desde_columnas(fila)
            for fila in sorted(ultima["renglones"], key=lambda f: f["renglon_id"])
            if fila["negocio"] == negocio and fila["estado"] == RENGLON_POSPUESTO
        )

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
        cerrado_por: str | None = None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado, revisado contra los CHECK antes de aplicarse.

        Aparte por la misma razón que `insertar_la_lista`: es donde se ve que
        el doble rechaza un `cerrado` sin hora, o una hora de cierre en una
        lista que no está cerrada, igual que `ck_pedido_sugerido_cierre`.

        `cerrado_por` (migración 0013) viaja aparte de `cerrado_en` por la
        misma razón que allá: `None` por omisión, para que quien llame sin
        firma —igual que `vencer_las_de_dias_anteriores`, que nunca cierra—
        no tenga que inventar una.
        """
        self._revisar()
        lista = self._por_id(pedido_sugerido_id)
        if lista is None:
            return None

        propuesta = {
            **lista,
            "estado": estado,
            "cerrado_en": cerrado_en,
            "cerrado_por": cerrado_por,
        }
        revisar_la_lista(propuesta)

        lista["estado"] = estado
        lista["cerrado_en"] = cerrado_en
        lista["cerrado_por"] = cerrado_por
        return armar_guardado(lista, lista["renglones"])

    def cerrar(
        self, negocio: str, pedido_sugerido_id: int, quien: str | None = None
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        lista = self._por_id(pedido_sugerido_id)
        # Las tres condiciones son el `WHERE` del UPDATE real, en el mismo
        # orden: el negocio, el id y que siga abierta. Sin la última, un
        # segundo clic movería `cerrado_en` y una vencida resucitaría.
        if lista is None or lista["negocio"] != negocio or lista["estado"] != ABIERTO:
            return None
        return self.poner_estado(
            pedido_sugerido_id,
            CERRADO,
            cerrado_en=dt.datetime.now(dt.UTC),
            cerrado_por=quien,
        )

    def cerrar_las_de_dias_anteriores(
        self, negocio: str, fecha_del_pedido: dt.date, quien: str
    ) -> tuple[PedidoSugeridoGuardado, ...]:
        """Igual que `vencer_las_de_dias_anteriores`, pero cierra en vez de vencer.

        Mismo `WHERE` en memoria —negocio, `abierto`, día anterior—, y por eso
        se apoya en `poner_estado` igual que `vencer_las_de_dias_anteriores` se
        apoyaba en él: el doble no reimplementa la validación, la reusa.
        """
        self._revisar()
        cerradas = []
        for lista in list(self.listas):
            if (
                lista["negocio"] == negocio
                and lista["estado"] == ABIERTO
                and lista["fecha_del_pedido"] < fecha_del_pedido
            ):
                cerradas.append(
                    self.poner_estado(
                        lista["pedido_sugerido_id"],
                        CERRADO,
                        cerrado_en=dt.datetime.now(dt.UTC),
                        cerrado_por=quien,
                    )
                )
        return tuple(cerradas)

    def _ninguna_lista_despues(self, lista: dict) -> bool:
        """`_NINGUNA_LISTA_DESPUES`, en memoria y escrita una vez (ADR 0016).

        La usan `reabrir` —el `WHERE`— y `se_puede_reabrir` —la lectura—, igual
        que allá las dos sentencias traen el mismo texto. Con el negocio en la
        comparación: una lista de otra farmacia no cuenta (regla 7).
        """
        return not any(
            otra["negocio"] == lista["negocio"]
            and otra["fecha_del_pedido"] > lista["fecha_del_pedido"]
            for otra in self.listas
        )

    def _hasta_un_dia_atras(self, lista: dict, ancla: dt.date) -> bool:
        """`_HASTA_UN_DIA_ATRAS`, en memoria (enmienda 2026-09-21 al ADR 0016).

        `ancla` es el último día con ventas del almacén, nunca el reloj: quien
        llama lo lee una vez y lo pasa. La usan `reabrir` y `se_puede_reabrir`,
        igual que `_ninguna_lista_despues`.
        """
        return lista["fecha_del_pedido"] >= ancla - dt.timedelta(days=1)

    def _se_puede_reabrir(
        self, negocio: str, pedido_sugerido_id: int, ancla: dt.date
    ) -> dict | None:
        """La lista que `_REABRIR` movería, o `None`. Las cinco condiciones de
        su `WHERE`, en el mismo orden.

        **No delega en `transiciones.motivo_para_no_reabrir`** (revisado
        2026-09-22, paso 3 de la revisión de arquitectura): esa función NO
        es equivalente a este `WHERE`. `motivo_para_no_reabrir` recibe **una**
        lista y su `ancla`, y cuando llega a la última rama —`estado ==
        CERRADO`, no vencida, dentro de la ventana de un día— **asume** que la
        razón es "ya se armó la siguiente", porque para entonces ya sabe que
        el `UPDATE` contestó cero filas y solo le queda explicar por qué. No
        comprueba esa condición por sí misma: no tiene con qué, porque no
        recibe las demás listas del negocio. `_ninguna_lista_despues` de aquí
        SÍ la comprueba —recorre `self.listas`—, y es justo el "conteo que el
        doble calcula distinto" que la propuesta 1 anticipó como motivo
        legítimo para no delegar. Unificar aquí obligaría a
        `motivo_para_no_reabrir` a recibir la lista completa de listas del
        negocio, lo que la sacaría de la familia de funciones puras "una
        lista, su ancla" que hoy mantiene.
        """
        lista = self._por_id(pedido_sugerido_id)
        if (
            lista is None
            or lista["negocio"] != negocio
            or lista["estado"] != CERRADO
            or not self._ninguna_lista_despues(lista)
            or not self._hasta_un_dia_atras(lista, ancla)
        ):
            return None
        return lista

    def se_puede_reabrir(
        self, negocio: str, pedido_sugerido_id: int, ancla: dt.date
    ) -> bool:
        self._revisar()
        return self._se_puede_reabrir(negocio, pedido_sugerido_id, ancla) is not None

    def reabrir(
        self, negocio: str, pedido_sugerido_id: int, quien: str, ancla: dt.date
    ) -> PedidoSugeridoGuardado | None:
        """`_REABRIR`: `cerrado` → `abierto`, `cerrado_en` a `None` y la firma.

        Todo se revisa contra los CHECK **antes** de escribir, igual que
        `poner_estado`: el doble no puede aceptar lo que la base rechazaría.
        """
        self._revisar()
        lista = self._se_puede_reabrir(negocio, pedido_sugerido_id, ancla)
        if lista is None:
            return None
        propuesta = {
            **lista,
            "estado": ABIERTO,
            "cerrado_en": None,
            # `cerrado_por` (migración 0013) se limpia igual que `cerrado_en`:
            # "quién cerró" deja de describir algo en cuanto la lista vuelve a
            # `abierto`. Lo mismo hace `_REABRIR` contra Postgres.
            "cerrado_por": None,
            "reabierto_por": quien,
            # El `now()` de la base: un instante real con zona.
            "reabierto_en": dt.datetime.now(dt.UTC),
        }
        revisar_la_lista(propuesta)
        for columna in (
            "estado",
            "cerrado_en",
            "cerrado_por",
            "reabierto_por",
            "reabierto_en",
        ):
            lista[columna] = propuesta[columna]
        return armar_guardado(lista, lista["renglones"])

    # ------------------------------------------------ el estado del renglón

    def poner_estado_del_renglon(
        self,
        renglon_id: int,
        estado: str,
        descartado_por: str | None = None,
        descartado_en: dt.datetime | None = None,
        cancelado_por: str | None = None,
        cancelado_en: dt.datetime | None = None,
        recibido_por: str | None = None,
        recibido_en: dt.datetime | None = None,
        recibido_con_compras: Sequence[int] | None = None,
        piezas_recibidas: float | None = None,
        pospuesto_por: str | None = None,
        pospuesto_en: dt.datetime | None = None,
        proveedor_de_la_espera=_IGUAL,
        espera_desde=_IGUAL,
        listas_en_espera=_IGUAL,
        pedido_id=_IGUAL,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado de un renglón, revisado contra los CHECK.

        Aparte por la misma razón que `poner_estado` lo está para la lista: es
        donde se ve que el doble **se niega** igual que Postgres —un
        `descartado` sin firma, una firma en un renglón abierto, un estado que
        el glosario no conoce—. Si el rechazo estuviera escondido dentro del
        camino que lo evita, nadie podría verlo.

        Lo usan también las pruebas para poner un renglón en `en tránsito` o
        `recibido` sin pasar por el envío o la recepción. **Desde el ticket 26
        lo recibido va firmado** (`ck_renglon_recepcion`): `recibido_por` y
        `recibido_en` entran por argumento, y sin ellos esto rebota igual que
        Postgres. **Desde el 27 dice también cuántas llegaron**
        (`ck_renglon_piezas_recibidas`, `ck_renglon_completo_o_parcial`):
        `piezas_recibidas` entra por argumento, y un `recibido` sin ella rebota.
        **Desde el ADR 0025 un `pospuesto` también va firmado**
        (`ck_renglon_pospuesto`): `pospuesto_por` y `pospuesto_en` entran por
        argumento, y sin ellos esto rebota igual que Postgres. **Y desde la
        lista de espera (migración 0020) un `pospuesto` trae además desde
        cuándo espera y cuántas listas lleva** (`ck_renglon_espera_pospuesto`).

        `proveedor_de_la_espera`, `espera_desde`, `listas_en_espera` y
        `pedido_id` valen «no tocar» si no se pasan: son columnas que otras
        transiciones dejan como estaban, y `None` es un valor de verdad en las
        cuatro.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado

        espera = {
            columna: valor
            for columna, valor in (
                ("proveedor_de_la_espera", proveedor_de_la_espera),
                ("espera_desde", espera_desde),
                ("listas_en_espera", listas_en_espera),
                ("pedido_id", pedido_id),
            )
            if valor is not _IGUAL
        }
        propuesta = {
            **fila,
            **espera,
            "estado": estado,
            "descartado_por": descartado_por,
            "descartado_en": descartado_en,
            "cancelado_por": cancelado_por,
            "cancelado_en": cancelado_en,
            "recibido_por": recibido_por,
            "recibido_en": recibido_en,
            "recibido_con_compras": (
                None if recibido_con_compras is None else list(recibido_con_compras)
            ),
            # `numeric(12,3)`: se redondea como lo haría la columna.
            "piezas_recibidas": (
                None if piezas_recibidas is None else round(float(piezas_recibidas), 3)
            ),
            "pospuesto_por": pospuesto_por,
            "pospuesto_en": pospuesto_en,
        }
        revisar_el_renglon(propuesta)

        fila.update(
            estado=estado,
            descartado_por=descartado_por,
            descartado_en=descartado_en,
            cancelado_por=cancelado_por,
            cancelado_en=cancelado_en,
            recibido_por=propuesta["recibido_por"],
            recibido_en=propuesta["recibido_en"],
            recibido_con_compras=propuesta["recibido_con_compras"],
            piezas_recibidas=propuesta["piezas_recibidas"],
            pospuesto_por=pospuesto_por,
            pospuesto_en=pospuesto_en,
            **espera,
        )
        return armar_guardado(lista, lista["renglones"])

    def descartar(
        self, negocio: str, renglon_id: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        # Las CUATRO condiciones son el `WHERE` del UPDATE real, en el mismo
        # orden: el negocio, el id, que el renglón siga abierto y **que su lista
        # lo esté**. Sin la tercera, un renglón `en tránsito` —que ya se le pidió
        # a un proveedor— se podría descartar, y el ticket 26 recibiría
        # mercancía contra un renglón que dice que nadie la pidió. Sin la
        # cuarta, una lista cerrada se seguiría dejando modificar y dejaría de
        # significar "ya se pidió lo que se iba a pedir" (pendiente 4, decidido
        # el 2026-09-20).
        #
        # Las DOS últimas —el renglón abierto y su lista abierta— ya no se
        # repiten aquí: las juzga `transiciones.motivo_para_no_editar`
        # (2026-09-22, paso 3 de la revisión de arquitectura), la misma
        # función que decide la bandera `se_puede_editar` de la pantalla y el
        # motivo del 409. El negocio y la existencia del renglón siguen siendo
        # la unión, no la regla, y se quedan aquí.
        if encontrado is None:
            return None
        fila, lista = encontrado
        if fila["negocio"] != negocio:
            return None
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "descartar",
            )
            is not None
        ):
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

    def posponer(
        self, negocio: str, renglon_id: int, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """`_POSPONER`, en memoria y con las mismas condiciones (ADR 0025).

        Las mismas que `descartar`: el negocio, el renglón y que sea `abierto`
        en una lista `abierta` —esas dos las juzga
        `transiciones.motivo_para_no_editar`, la misma función que decide la
        bandera de la pantalla y el motivo del 409—.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado
        if fila["negocio"] != negocio:
            return None
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "posponer",
            )
            is not None
        ):
            return None
        # Lo que hace el `SET` de `_POSPONER`: el proveedor de la espera (el del
        # pedido, si no el elegido), la fecha de la lista y el contador la
        # primera vez —lo que el renglón ya traía de una espera anterior se
        # conserva—, y el renglón SALE de su pedido, todo de una vez.
        pedido = self._pedido_del_renglon(fila)
        return self.poner_estado_del_renglon(
            renglon_id,
            RENGLON_POSPUESTO,
            pospuesto_por=quien,
            pospuesto_en=dt.datetime.now(dt.UTC),
            proveedor_de_la_espera=proveedor_de_la_espera(
                None if pedido is None else pedido["proveedor"],
                fila.get("proveedor_elegido"),
                fila.get("proveedor_de_la_espera"),
            ),
            espera_desde=fila.get("espera_desde") or lista["fecha_del_pedido"],
            listas_en_espera=fila.get("listas_en_espera") or 1,
            pedido_id=None,
        )

    def mandar_el_pedido_a_espera(
        self, negocio: str, pedido_id: int, quien: str
    ) -> PedidoMandadoAEspera | None:
        """`_POSPONER_EL_PEDIDO` en memoria: todo lo abierto y no tachado, o nada.

        Mismas condiciones que la sentencia: el pedido es de este negocio; si
        no es `borrador` o su lista no está `abierta` no se mueve nada y se
        dicen los dos estados. Cada renglón se manda con `posponer`, la misma
        función que el clic suelto, y por eso quedan idénticos. Lo tachado se
        deja y se cuenta.
        """
        self._revisar()
        pedido = next(
            (
                p
                for p in self.pedidos
                if p["pedido_id"] == pedido_id and p["negocio"] == negocio
            ),
            None,
        )
        if pedido is None:
            return None
        lista = self._por_id(pedido["pedido_sugerido_id"])
        if lista is None:
            return None
        resultado = PedidoMandadoAEspera(
            estado_del_pedido=pedido["estado"], estado_de_la_lista=lista["estado"]
        )
        if not resultado.se_mando:
            return resultado
        dentro = [
            f
            for f in lista["renglones"]
            if f.get("pedido_id") == pedido_id
            and f["negocio"] == negocio
            and f["estado"] == RENGLON_ABIERTO
        ]
        tachados = sum(1 for f in dentro if f.get("capturado_por") is not None)
        mandados = 0
        for fila in [f for f in dentro if f.get("capturado_por") is None]:
            if self.posponer(negocio, fila["renglon_id"], quien) is not None:
                mandados += 1
        return dataclasses.replace(
            resultado,
            mandados=mandados,
            tachados=tachados,
            lista=armar_guardado(lista, lista["renglones"]),
        )

    def devolver_pospuesto(
        self, negocio: str, renglon_id: int
    ) -> PedidoSugeridoGuardado | None:
        """`_DEVOLVER_DE_POSPUESTO`: `pospuesto` → `abierto`, sin firma (ADR 0025)."""
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado
        if fila["negocio"] != negocio:
            return None
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "devolver_pospuesto",
            )
            is not None
        ):
            return None
        # Las dos columnas se van a `None` juntas: lo exige ck_renglon_pospuesto.
        #
        # Y lo de la espera, como el `SET` de `_DEVOLVER_DE_POSPUESTO`: regresa
        # al pedido de su proveedor **de la misma lista y si sigue en
        # borrador** (`ux_pedido_proveedor`: a lo sumo uno), y si no, sin
        # repartir. Los datos de la espera se borran salvo que el renglón
        # venga de una espera anterior (`piezas_pospuestas > 0`).
        destino = next(
            (
                p
                for p in self.pedidos
                if p["negocio"] == fila["negocio"]
                and p["pedido_sugerido_id"] == fila["pedido_sugerido_id"]
                and p["proveedor"] == fila.get("proveedor_de_la_espera")
                and p["estado"] == BORRADOR
            ),
            None,
        )
        hereda = fila.get("piezas_pospuestas", 0) > 0
        return self.poner_estado_del_renglon(
            renglon_id,
            RENGLON_ABIERTO,
            pedido_id=None if destino is None else destino["pedido_id"],
            proveedor_de_la_espera=fila.get("proveedor_de_la_espera") if hereda else None,
            espera_desde=fila.get("espera_desde") if hereda else None,
            listas_en_espera=fila.get("listas_en_espera") if hereda else None,
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
        #
        # Las DOS últimas las juzga `transiciones.motivo_para_no_editar`, la
        # misma función que `descartar` (2026-09-22, paso 3).
        if fila["negocio"] != negocio:
            return None
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "ajustar_la_cantidad",
            )
            is not None
        ):
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
        #
        # Las DOS últimas, otra vez por `transiciones.motivo_para_no_editar`
        # (2026-09-22, paso 3): descartar, ajustar y elegir comparten la
        # misma regla exacta, y ahora comparten la misma función.
        if fila["negocio"] != negocio:
            return None
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "elegir_proveedor",
            )
            is not None
        ):
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
                # El `case` de `_ASIGNAR_RENGLONES` (ticket 22): el que CAMBIA
                # de pedido pierde su marca de captura —en el portal nuevo
                # nadie lo ha tecleado— y el que se queda la conserva.
                if renglon.get("pedido_id") != fila["pedido_id"]:
                    renglon["capturado_por"] = None
                    renglon["capturado_en"] = None
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
                # Y sin marca de captura, como `_SOLTAR_RENGLONES` (ticket 22).
                renglon["capturado_por"] = None
                renglon["capturado_en"] = None

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

    # ----------------------------------------------- enviar el pedido (21)

    def enviar_el_pedido(self, negocio: str, pedido_id: int, quien: str):
        """Los dos `UPDATE` del envío, en memoria y con las mismas condiciones.

        Tres cosas se copian del lado real y las tres tienen una prueba:

        - **Las tres condiciones del `WHERE`**, en el mismo orden: el negocio,
          el pedido todavía en `borrador`, y que tenga al menos un renglón
          dentro. Devuelve `None` donde el `UPDATE` real devolvería cero filas.
        - **La firma se revisa antes de escribirse.** Pasa por
          `revisar_el_pedido`, que es el mismo validador que llama la
          implementación real al armar: sin eso, el doble aceptaría en la torre
          un `enviado` sin firma que en atlas rebotaría contra
          `ck_pedido_envio`.
        - **Los renglones se mueven en la misma operación**, y solo los que
          siguen `abierto`: un descartado sigue descartado.
        - **El total no puede salir viejo**: si algún renglón de dentro se
          corrigió después de `armado_en`, cero filas. Es el `NOT EXISTS` del
          `WHERE` real y el hilo abierto 13 de `HANDOVER.md`.

        **No exige que la lista esté `abierta`**, al revés que descartar,
        ajustar, elegir y partir. Es la decisión del ADR 0009 y está razonada en
        `AlmacenamientoDelPedido.enviar_el_pedido`; en corto: enviar es decir
        que sí se pidió, y bloquearlo dejaría renglones `abierto` atrapados
        dentro de una lista cerrada.

        Las tres condiciones de estado —borrador, con renglones dentro, sin
        total viejo— las juzga `transiciones.motivo_para_no_enviar`
        (2026-09-22, paso 3 de la revisión de arquitectura), la misma función
        que decide el motivo del 409 real. El negocio y la existencia del
        pedido son la unión, no la regla, y se quedan aquí.
        """
        self._revisar()
        fila = None
        for candidato in self.pedidos:
            if candidato["pedido_id"] == pedido_id:
                fila = candidato
                break
        if fila is None or fila["negocio"] != negocio:
            return None

        lista = self._por_id(fila["pedido_sugerido_id"])
        dentro = [
            r
            for r in (lista["renglones"] if lista else [])
            if r.get("pedido_id") == pedido_id and r["negocio"] == negocio
        ]
        # El total no se envía viejo: `total_sin_iva` solo se reescribe al
        # partir, así que una cantidad corregida después de armar el pedido lo
        # deja enseñando lo que costaba hace un rato.
        total_envejecido = any(
            r.get("ajustada_en") is not None and r["ajustada_en"] > fila["armado_en"]
            for r in dentro
        )
        if (
            motivo_para_no_enviar(pedido_desde_columnas(fila), len(dentro), total_envejecido)
            is not None
        ):
            return None

        # El instante real con zona que en la tabla pone `now()`.
        cuando = dt.datetime.now(dt.UTC)
        propuesta = {**fila, "estado": ENVIADO, "enviado_por": quien, "enviado_en": cuando}
        revisar_el_pedido(propuesta)
        fila.update(estado=ENVIADO, enviado_por=quien, enviado_en=cuando)

        # `_RENGLONES_A_TRANSITO`: solo los que siguen `abierto`. Pasa por
        # `poner_estado_del_renglon` para que los CHECK del renglón se revisen
        # igual que los del pedido.
        movidos = []
        for renglon in dentro:
            if renglon["estado"] != RENGLON_ABIERTO:
                continue
            self.poner_estado_del_renglon(renglon["renglon_id"], RENGLON_EN_TRANSITO)
            movidos.append(renglon["renglon_id"])

        return PedidoEnviado(
            pedido=pedido_desde_columnas(fila), renglones=tuple(movidos)
        )

    # ------------------------------ cancelar y devolver lo atrasado (25)

    def cancelar_el_pedido(self, negocio: str, pedido_id: int, quien: str):
        """Los dos `UPDATE` de cancelar, en memoria y con las mismas condiciones.

        En el orden del `WHERE` real: el negocio, el pedido todavía `enviado`,
        y que **ninguno** de sus renglones se haya recibido. La lista **no se
        mira**, igual que la sentencia: cancelar no exige la lista abierta. La
        firma pasa por `revisar_el_pedido` y la de cada renglón por
        `revisar_el_renglon`, así que un `cancelado` sin firma rebota aquí
        igual que en atlas. Pedido y renglones con el MISMO instante: es el
        `now()` de una sola transacción.

        Las dos condiciones de estado —enviado, nada recibido— las juzga
        `transiciones.motivo_para_no_cancelar` (2026-09-22, paso 3), la misma
        función que decide el motivo del 409 real y la bandera
        `motivo_para_no_cancelar`/`se_puede_cancelar` de la pantalla de
        atrasados. El negocio y la existencia del pedido son la unión, no la
        regla, y se quedan aquí.
        """
        self._revisar()
        fila = next((p for p in self.pedidos if p["pedido_id"] == pedido_id), None)
        if fila is None or fila["negocio"] != negocio:
            return None
        lista = self._por_id(fila["pedido_sugerido_id"])
        dentro = [
            r
            for r in (lista["renglones"] if lista else [])
            if r.get("pedido_id") == pedido_id and r["negocio"] == negocio
        ]
        # El `NOT EXISTS` sobre lo recibido: si algo llegó, sí se capturó.
        recibidos = sum(1 for r in dentro if r["estado"] in ESTADOS_QUE_CIERRAN_EL_TRANSITO)
        if motivo_para_no_cancelar(pedido_desde_columnas(fila), recibidos) is not None:
            return None

        cuando = dt.datetime.now(dt.UTC)
        propuesta = {**fila, "estado": CANCELADO, "cancelado_por": quien, "cancelado_en": cuando}
        revisar_el_pedido(propuesta)
        fila.update(estado=CANCELADO, cancelado_por=quien, cancelado_en=cuando)

        # `_RENGLONES_CANCELADOS`: solo los que seguían en camino.
        soltados = []
        for renglon in dentro:
            if renglon["estado"] != RENGLON_EN_TRANSITO:
                continue
            self.poner_estado_del_renglon(
                renglon["renglon_id"],
                RENGLON_CANCELADO,
                cancelado_por=quien,
                cancelado_en=cuando,
            )
            soltados.append(renglon["renglon_id"])

        return PedidoCancelado(
            pedido=pedido_desde_columnas(fila), renglones=tuple(soltados)
        )

    def devolver_el_atrasado(
        self,
        negocio: str,
        renglon_id: int,
        quien: str,
        enviado_antes_de: dt.datetime,
    ):
        """`_DEVOLVER_EL_ATRASADO`, en memoria: las mismas cinco condiciones.

        El negocio del renglón, que esté `en tránsito`, que cuelgue de un pedido
        del mismo negocio, que ese pedido siga `enviado`, y que se haya enviado
        **antes del límite** —que es "lleva más de N días"—. La lista no se
        mira. Devuelve el renglón releído, con su firma.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _lista = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_EN_TRANSITO:
            return None
        pedido = next(
            (
                p
                for p in self.pedidos
                if p["pedido_id"] == fila.get("pedido_id")
                and p["negocio"] == fila["negocio"]
            ),
            None,
        )
        if pedido is None or pedido["estado"] != ENVIADO:
            return None
        enviado_en = pedido.get("enviado_en")
        if enviado_en is None or not enviado_en < enviado_antes_de:
            return None
        self.poner_estado_del_renglon(
            renglon_id,
            RENGLON_CANCELADO,
            cancelado_por=quien,
            cancelado_en=dt.datetime.now(dt.UTC),
        )
        return renglon_guardado_desde_columnas(fila)

    # ------------------------------------------ la recepción sugerida (26)

    def _pedido_del_renglon(self, fila: dict) -> dict | None:
        """La unión `p.pedido_id = r.pedido_id and p.negocio = r.negocio`."""
        return next(
            (
                p
                for p in self.pedidos
                if p["pedido_id"] == fila.get("pedido_id")
                and p["negocio"] == fila["negocio"]
            ),
            None,
        )

    def lo_que_esta_en_transito(self, negocio: str) -> tuple[LoYaPedido, ...]:
        """`_EN_TRANSITO`, en memoria: todo lo en tránsito, **sin mirar la fecha
        de la lista**, con el `pro_id` de su pedido. En el mismo orden."""
        self._revisar()
        resultado = []
        for lista in sorted(
            (l for l in self.listas if l["negocio"] == negocio),
            key=lambda l: l["fecha_del_pedido"],
        ):
            for fila in sorted(lista["renglones"], key=lambda f: f["renglon_id"]):
                if fila["negocio"] != negocio or fila["estado"] != RENGLON_EN_TRANSITO:
                    continue
                pedido = self._pedido_del_renglon(fila)
                resultado.append(
                    lo_ya_pedido_desde_columnas(
                        {
                            **fila,
                            "fecha_del_pedido": lista["fecha_del_pedido"],
                            "ventas_consideradas_hasta": lista["ventas_consideradas_hasta"],
                            "ventas_consideradas_desde": lista["ventas_consideradas_desde"],
                            "proveedor": pedido["proveedor"] if pedido else None,
                            "enviado_por": pedido.get("enviado_por") if pedido else None,
                            "enviado_en": pedido.get("enviado_en") if pedido else None,
                            "estado_del_pedido": pedido["estado"] if pedido else None,
                            "proveedor_id": pedido.get("proveedor_id") if pedido else None,
                        }
                    )
                )
        return tuple(resultado)

    def lo_recibido(self, negocio: str, productos, pedidos) -> tuple[RenglonRecibido, ...]:
        """`_LO_RECIBIDO`, en memoria: por producto o por pedido, del negocio."""
        self._revisar()
        productos, pedidos = set(productos), set(pedidos)
        filas = sorted(
            (
                fila
                for lista in self.listas
                for fila in lista["renglones"]
                if fila["negocio"] == negocio
                and fila["estado"] in ESTADOS_QUE_CIERRAN_EL_TRANSITO
                and (fila["producto_id"] in productos or fila.get("pedido_id") in pedidos)
            ),
            key=lambda f: f["renglon_id"],
        )
        return tuple(renglon_recibido_desde_columnas(f) for f in filas)

    def confirmar_la_recepcion(
        self, negocio: str, renglon_id: int, compras, piezas: float, quien: str
    ) -> RenglonGuardado | None:
        """`_CONFIRMAR_LA_RECEPCION`, en memoria: las mismas condiciones, en el
        mismo orden, y la firma revisada por `revisar_el_renglon`."""
        return self._recibir_con_compras(
            negocio, renglon_id, compras, piezas, quien, RENGLON_RECIBIDO
        )

    def recibir_parcial_con_compras(
        self, negocio: str, renglon_id: int, compras, piezas: float, quien: str
    ) -> RenglonGuardado | None:
        """`_RECIBIR_PARCIAL_CON_COMPRAS`, en memoria (ticket 27): lo mismo que
        confirmar, con la cantidad al revés."""
        return self._recibir_con_compras(
            negocio, renglon_id, compras, piezas, quien, RENGLON_RECIBIDO_PARCIAL
        )

    def _recibir_con_compras(
        self, negocio: str, renglon_id: int, compras, piezas: float, quien: str, estado: str
    ) -> RenglonGuardado | None:
        self._revisar()
        compras = [int(c) for c in compras]
        if not compras:
            return None
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _lista = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_EN_TRANSITO:
            return None
        pedido = self._pedido_del_renglon(fila)
        if pedido is None or pedido["estado"] != ENVIADO or pedido.get("proveedor_id") is None:
            return None
        pedidas = fila["cantidad_final"] if fila["cantidad_final"] is not None else fila["cantidad_propuesta"]
        # Confirmar: la evidencia alcanza lo pedido. Recibir parcial: trae
        # menos, y algo (`:piezas > 0`). Cada una en su `WHERE`.
        if estado == RENGLON_RECIBIDO and not pedidas <= piezas:
            return None
        if estado == RENGLON_RECIBIDO_PARCIAL and not 0 < piezas < pedidas:
            return None
        if set(fila.get("compras_rechazadas") or ()) & set(compras):
            return None
        ya_usadas = {
            c
            for lista in self.listas
            for otra in lista["renglones"]
            if otra["negocio"] == negocio
            for c in (otra.get("recibido_con_compras") or ())
        }
        if ya_usadas & set(compras):
            return None
        # El instante real con zona que en la tabla pone `now()`.
        self.poner_estado_del_renglon(
            renglon_id,
            estado,
            recibido_por=quien,
            recibido_en=dt.datetime.now(dt.UTC),
            recibido_con_compras=compras,
            piezas_recibidas=piezas,
        )
        return renglon_guardado_desde_columnas(fila)

    def recibir_a_mano(
        self, negocio: str, renglon_id: int, piezas: int, quien: str
    ) -> RenglonGuardado | None:
        """`_RECIBIR_A_MANO` y, si no movió nada, `_CORREGIR_LO_RECIBIDO` (27).

        Las mismas condiciones, en el mismo orden, y el estado sale de las
        piezas con la misma comparación del `case`. Lo que la corrección
        conserva —las compras de la evidencia, si las había— se conserva aquí.

        La rama de corrección —el renglón que ya estaba `recibido` o
        `recibido parcial`— juzga sus dos condiciones (atendido después, la
        misma cifra) con `transiciones.motivo_para_no_corregir` (2026-09-22,
        paso 3): es la misma función que decide el motivo del 409 real y la
        bandera `se_puede_corregir` de la pantalla. Lo de arriba —recibido,
        pedido enviado, piezas positivas— ya está garantizado en este punto
        por las líneas de arriba, así que las ramas de esa función que los
        vuelven a comprobar no se disparan.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None or piezas <= 0:
            return None
        fila, lista = encontrado
        if fila["negocio"] != negocio:
            return None
        pedido = self._pedido_del_renglon(fila)
        if pedido is None or pedido["estado"] != ENVIADO:
            return None
        if fila["estado"] == RENGLON_EN_TRANSITO:
            compras = None
        elif fila["estado"] in ESTADOS_QUE_CIERRAN_EL_TRANSITO:
            atendido_despues = self._ya_se_atendio(
                negocio, fila["producto_id"], lista["fecha_del_pedido"]
            )
            motivo = motivo_para_no_corregir(
                renglon_guardado_desde_columnas(fila),
                pedido_desde_columnas(pedido),
                atendido_despues,
                piezas,
            )
            if motivo is not None:
                return None
            compras = fila.get("recibido_con_compras")
        else:
            return None
        pedidas = fila["cantidad_final"] if fila["cantidad_final"] is not None else fila["cantidad_propuesta"]
        self.poner_estado_del_renglon(
            renglon_id,
            RENGLON_RECIBIDO if pedidas <= piezas else RENGLON_RECIBIDO_PARCIAL,
            recibido_por=quien,
            recibido_en=dt.datetime.now(dt.UTC),
            recibido_con_compras=compras,
            piezas_recibidas=piezas,
        )
        return renglon_guardado_desde_columnas(fila)

    # ------------------------------------------ la conciliación diaria (2026-09-27)

    def confirmar_la_conciliacion(
        self,
        negocio: str,
        pedido_sugerido_id: int,
        decisiones,
        quien: str,
    ) -> ConciliacionConfirmada:
        """El clic de la conciliación, en memoria, en las MISMAS tres pasadas
        que la implementación real (ver su docstring para el porqué: enviar
        saca al pedido de `borrador`, así que todo el lote de un proveedor
        tiene que estar asignado ANTES de que cualquiera de sus renglones lo
        envíe).

        Crear el pedido y asignarle el renglón **sin mirar el estado de la
        lista** son las dos partes nuevas, sin equivalente real hasta este
        ticket. Para lo demás —enviar, confirmar o recibir parcial— se
        **llama a los métodos de siempre**: `self.enviar_el_pedido` y
        `self.confirmar_la_recepcion` / `self.recibir_parcial_con_compras`.
        No hay una segunda copia de esas reglas aquí: si divergieran de la
        real, sería porque el archivo real cambió y éste no, que es justo lo
        que las pruebas de ambos lados existen para cazar.
        """
        self._revisar()
        firma = _firma_de_la_conciliacion(quien)
        lista = self._por_id(pedido_sugerido_id)
        ok_de: dict[int, bool] = {}

        # Paso 1: crear/reencontrar el pedido de cada proveedor y asignarle
        # cada renglón. Nada se envía todavía.
        pedidos_por_proveedor: dict[str, int] = {}
        pedidos_tocados: set[int] = set()
        for decision in decisiones:
            if lista is None or lista["negocio"] != negocio:
                ok_de[decision.renglon_id] = False
                continue

            pedido_id = pedidos_por_proveedor.get(decision.proveedor)
            if pedido_id is None:
                fila = self._pedido_de(negocio, pedido_sugerido_id, decision.proveedor)
                if fila is None:
                    fila = {
                        "negocio": negocio,
                        "pedido_sugerido_id": pedido_sugerido_id,
                        "proveedor": decision.proveedor,
                        "proveedor_id": decision.proveedor_id,
                        "estado": BORRADOR,
                        "total_sin_iva": None,
                        "pedido_id": self._siguiente_pedido,
                        "armado_en": dt.datetime.now(dt.UTC),
                    }
                    revisar_el_pedido(fila)
                    self._siguiente_pedido += 1
                    self.pedidos.append(fila)
                elif fila["estado"] != BORRADOR:
                    ok_de[decision.renglon_id] = False
                    continue
                else:
                    fila["proveedor_id"] = decision.proveedor_id
                pedido_id = fila["pedido_id"]
                pedidos_por_proveedor[decision.proveedor] = pedido_id

            # `_ASIGNAR_RENGLON_DEDUCIDO`: el renglón, de esta lista, abierto y
            # sin pedido todavía.
            renglon = next(
                (
                    r
                    for r in lista["renglones"]
                    if r["renglon_id"] == decision.renglon_id
                ),
                None,
            )
            if (
                renglon is None
                or renglon["estado"] != RENGLON_ABIERTO
                or renglon.get("pedido_id") is not None
            ):
                ok_de[decision.renglon_id] = False
                continue
            renglon["pedido_id"] = pedido_id
            pedidos_tocados.add(pedido_id)

        # Paso 2: enviar cada pedido tocado, una sola vez, con todos sus
        # renglones del lote ya dentro.
        for pedido_id in pedidos_tocados:
            self.enviar_el_pedido(negocio, pedido_id, firma)

        # Paso 3: confirmar la recepción de cada renglón que sí se asignó.
        resultados: list[RenglonConciliado] = []
        for decision in decisiones:
            if decision.renglon_id in ok_de:
                resultados.append(RenglonConciliado(decision.renglon_id, False))
                continue
            if decision.piezas >= decision.piezas_pedidas:
                recibido = self.confirmar_la_recepcion(
                    negocio, decision.renglon_id, decision.compras, decision.piezas, firma
                )
            else:
                recibido = self.recibir_parcial_con_compras(
                    negocio, decision.renglon_id, decision.compras, decision.piezas, firma
                )
            resultados.append(RenglonConciliado(decision.renglon_id, recibido is not None))

        return ConciliacionConfirmada(resultados=tuple(resultados))

    def _ya_se_atendio(self, negocio: str, producto_id: int, fecha: dt.date) -> bool:
        """El `NOT EXISTS` de `_CORREGIR_LO_RECIBIDO`: una lista POSTERIOR ya
        propuso el producto y se cerró, o el producto ya se volvió a pedir.
        Las mismas condiciones que el "atendido" de `lo_ya_pedido`."""
        return any(
            otra["negocio"] == negocio
            and otra["fecha_del_pedido"] > fecha
            and fila["negocio"] == negocio
            and fila["producto_id"] == producto_id
            and (otra["estado"] == CERRADO or fila["estado"] in ESTADOS_QUE_ATIENDEN_EL_PRODUCTO)
            for otra in self.listas
            for fila in otra["renglones"]
        )

    def productos_atendidos_despues(
        self, negocio: str, pedido_sugerido_id: int
    ) -> frozenset[int]:
        """`_PRODUCTOS_ATENDIDOS_DESPUES`, en memoria: reusa `_ya_se_atendio`.

        La misma pregunta de `_ya_se_atendio`, hecha una vez por cada
        `producto_id` de ESTA lista en vez de una vez por renglón suelto, para
        que el doble y Postgres no puedan divergir en qué cuenta como
        "atendido" (2026-09-21).
        """
        self._revisar()
        for lista in self.listas:
            if lista["negocio"] != negocio or lista["pedido_sugerido_id"] != pedido_sugerido_id:
                continue
            return frozenset(
                fila["producto_id"]
                for fila in lista["renglones"]
                if self._ya_se_atendio(
                    negocio, fila["producto_id"], lista["fecha_del_pedido"]
                )
            )
        return frozenset()

    def rechazar_la_recepcion(
        self, negocio: str, renglon_id: int, compras, quien: str
    ) -> RenglonGuardado | None:
        """`_RECHAZAR_LA_RECEPCION`, en memoria: el estado NO cambia, las compras
        se agregan (nunca se pisan) y la firma es la del último rechazo."""
        self._revisar()
        compras = [int(c) for c in compras]
        if not compras:
            return None
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _lista = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_EN_TRANSITO:
            return None
        pedido = self._pedido_del_renglon(fila)
        if pedido is None or pedido["estado"] != ENVIADO:
            return None
        anteriores = list(fila.get("compras_rechazadas") or ())
        if set(anteriores) & set(compras):
            return None
        propuesta = {
            **fila,
            "compras_rechazadas": anteriores + compras,
            "recepcion_rechazada_por": quien,
            "recepcion_rechazada_en": dt.datetime.now(dt.UTC),
        }
        revisar_el_renglon(propuesta)
        fila.update(
            compras_rechazadas=propuesta["compras_rechazadas"],
            recepcion_rechazada_por=propuesta["recepcion_rechazada_por"],
            recepcion_rechazada_en=propuesta["recepcion_rechazada_en"],
        )
        return renglon_guardado_desde_columnas(fila)

    # -------------------------------------------- la pantalla de captura (22)

    def poner_la_captura(
        self,
        renglon_id: int,
        capturado_por: str | None,
        capturado_en: dt.datetime | None,
    ) -> PedidoSugeridoGuardado | None:
        """El `UPDATE` pelado de la marca de captura, revisado contra los CHECK.

        Aparte de `marcar_capturado` por la misma razón que `poner_la_cantidad`
        lo está de `ajustar_la_cantidad`: es donde se ve que el doble **se
        niega** igual que Postgres —una firma vacía, una firma sin hora—. Si el
        rechazo estuviera escondido dentro del camino que lo evita, nadie
        podría verlo.
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado

        propuesta = {
            **fila,
            "capturado_por": capturado_por,
            "capturado_en": capturado_en,
        }
        revisar_el_renglon(propuesta)

        fila.update(capturado_por=capturado_por, capturado_en=capturado_en)
        return armar_guardado(lista, lista["renglones"])

    def marcar_capturado(
        self, negocio: str, renglon_id: int, capturado: bool, quien: str
    ) -> PedidoSugeridoGuardado | None:
        """Tachar o destachar, con las cuatro condiciones de `_MARCAR_CAPTURADO`.

        En el mismo orden que el `WHERE` real: el negocio, el renglón
        `abierto`, que cuelgue de un pedido, y que ese pedido siga en
        `borrador`. **Y la lista NO se mira**, igual que la sentencia: tachar
        no exige la lista abierta (ADR 0010).
        """
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, _lista = encontrado
        if fila["negocio"] != negocio or fila["estado"] != RENGLON_ABIERTO:
            return None
        pedido = next(
            (
                p
                for p in self.pedidos
                if p["pedido_id"] == fila.get("pedido_id")
                and p["negocio"] == fila["negocio"]
            ),
            None,
        )
        if pedido is None or pedido["estado"] != BORRADOR:
            return None
        if not capturado:
            return self.poner_la_captura(renglon_id, None, None)
        # El instante real con zona que en la tabla pone `now()`.
        return self.poner_la_captura(renglon_id, quien, dt.datetime.now(dt.UTC))

    def devolver_a_abierto(
        self, negocio: str, renglon_id: int
    ) -> PedidoSugeridoGuardado | None:
        self._revisar()
        encontrado = self._renglon_por_id(renglon_id)
        if encontrado is None:
            return None
        fila, lista = encontrado
        if fila["negocio"] != negocio:
            return None
        # La lista abierta también: deshacer es modificar. Ponerlo solo del lado
        # del descarte dejaría renglones `descartado` dentro de una lista
        # cerrada sin manera de volver.
        #
        # Las dos, otra vez por `transiciones.motivo_para_no_editar`
        # (2026-09-22, paso 3), con `"devolver_a_abierto"`: la única de las
        # cuatro acciones que exige lo contrario que las otras tres —el
        # renglón `descartado`, no `abierto`.
        if (
            motivo_para_no_editar(
                renglon_guardado_desde_columnas(fila),
                armar_guardado(lista, lista["renglones"]),
                "devolver_a_abierto",
            )
            is not None
        ):
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

    def guardar_lecturas_de_portal(self, negocio: str, lecturas) -> int:
        """El `insert ... on conflict do nothing` de `_GUARDAR_LECTURA_DE_PORTAL`."""
        self._revisar()
        llaves = {(f["negocio"], f["trabajo"], f["proveedor"], f["posicion"]) for f in self.lecturas_de_portal}
        nuevas = 0
        for lectura in lecturas:
            fila = {"negocio": negocio, **dataclasses.asdict(lectura)}
            llave = (negocio, fila["trabajo"], fila["proveedor"], fila["posicion"])
            if llave in llaves:
                continue
            llaves.add(llave)
            self.lecturas_de_portal.append(fila)
            nuevas += 1
        return nuevas

    def evidencia_de_las_sesiones(self, negocio: str) -> dict[str, EvidenciaDeLaSesion]:
        """El `group by` de `_EVIDENCIA_DE_LAS_SESIONES`, con sus dos `filter`."""
        self._revisar()
        por_proveedor: dict[str, dict] = {}
        for f in self.precios:
            if f["negocio"] != negocio:
                continue
            e = por_proveedor.setdefault(f["proveedor"], {"paso_el_login_en": None, "caduco_en": None})
            # La misma condición del `filter`: precio, o un motivo en que el
            # portal sí contestó algo suyo.
            if f.get("precio") is not None or f.get("motivo") in MOTIVOS_QUE_PASARON_DEL_LOGIN:
                e["paso_el_login_en"] = max(filter(None, (e["paso_el_login_en"], f["consultado_en"])))
            if f.get("motivo") == SESION_CADUCADA:
                e["caduco_en"] = max(filter(None, (e["caduco_en"], f["consultado_en"])))
        return {p: EvidenciaDeLaSesion(proveedor=p, **e) for p, e in por_proveedor.items()}

    def guardar_pruebas_de_las_sesiones(self, negocio: str, pruebas) -> int:
        """Los `INSERT` de `_GUARDAR_PRUEBA_DE_SESION`, con su `CHECK`.

        Todo o nada, como la transacción de verdad: se revisan todas antes de
        escribir ninguna. `probada_en` lo pone aquí el doble con la hora de
        ahora, que es lo que la tabla hace con su `DEFAULT now()`.
        """
        self._revisar()
        filas = [
            {"negocio": negocio, "proveedor": p.proveedor, "resultado": p.resultado}
            for p in pruebas
        ]
        for fila in filas:
            revisar_la_prueba(fila)
        for fila in filas:
            fila["probada_en"] = dt.datetime.now(dt.UTC)
            self.pruebas_de_sesion.append(fila)
        return len(filas)

    def ultimas_pruebas_de_las_sesiones(self, negocio: str) -> dict[str, PruebaDeLaSesion]:
        """El `distinct on (proveedor) ... order by probada_en desc` de
        `_ULTIMAS_PRUEBAS_DE_SESION`: la última por portal. El orden de las
        filas desempata, que es lo que el id hace allá."""
        self._revisar()
        ultimas: dict[str, dict] = {}
        for f in self.pruebas_de_sesion:
            if f["negocio"] != negocio:
                continue
            anterior = ultimas.get(f["proveedor"])
            if anterior is None or f["probada_en"] >= anterior["probada_en"]:
                ultimas[f["proveedor"]] = f
        return {
            p: PruebaDeLaSesion(proveedor=p, resultado=f["resultado"], probada_en=f["probada_en"])
            for p, f in ultimas.items()
        }

    # ------------------------------------------ el mínimo del proveedor (08)

    def minimos_de_los_proveedores(self, negocio: str) -> dict[str, MinimoDelProveedor]:
        """El `select` de `_LEER_MINIMOS`: solo los que tienen fila."""
        self._revisar()
        return {p: m for (n, p), m in self.minimos.items() if n == negocio}

    def guardar_el_minimo(
        self, negocio: str, proveedor: str, monto, incluye_iva: bool, quien: str
    ) -> MinimoDelProveedor:
        """El `insert ... on conflict do update` de `_GUARDAR_MINIMO`, con sus
        `CHECK`. `fijado_en` lo pone aquí el doble con la hora de ahora, que es
        lo que la tabla hace con `now()` en las dos ramas."""
        self._revisar()
        revisar_el_minimo(
            {
                "negocio": negocio,
                "proveedor": proveedor,
                "monto": monto,
                "incluye_iva": incluye_iva,
                "fijado_por": quien,
            }
        )
        guardado = MinimoDelProveedor(
            proveedor=proveedor,
            monto=monto,
            incluye_iva=incluye_iva,
            fijado_por=quien,
            fijado_en=dt.datetime.now(dt.UTC),
        )
        self.minimos[(negocio, proveedor)] = guardado
        return guardado

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
