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
from dataclasses import dataclass, field

from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
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
