"""La pantalla de captura: tachar renglones conforme se capturan en el portal (22).

**El modo real de trabajo.** El encargado tiene el portal del proveedor abierto
en una ventana y esta pantalla en otra, y va tachando renglones conforme los
teclea allá. Con un pedido de 40 renglones son 40 idas y vueltas, y lo que el
ticket pide es que ninguna se pierda.

**La decisión cara es dónde vive el avance**, y está en el ADR 0010: en
`pedidos.renglon`, en dos columnas firmadas —`capturado_por`, `capturado_en`—, y
no en el `localStorage` del navegador. Dos pestañas no divergen, cambiar de
máquina no pierde nada, y cada marca dice quién la puso.

Los tres seams del repo, en este orden:

1. **Lo puro** —`particion.lo_que_hay_que_capturar`, `frase_del_avance` e
   `invitacion_a_enviar`—: qué renglones se capturan, cuántos faltan y qué se
   le dice al encargado. Sin base, sin red y sin reloj.
2. **Lo que se guarda** —`almacenamiento.marcar_capturado` contra el doble, que
   se niega a lo mismo que la tabla porque llama a los mismos validadores—, más
   el SQL leído como texto: desde la torre no hay Postgres alcanzable.
3. **Lo que se ve** —la ruta con sus bordes sustituidos, y la pantalla leída
   como texto.

## Las cinco casillas, y dónde se vigila cada una

1. **Un renglón por línea**, con clave, descripción, cantidad y precio, y una
   casilla para tacharlo.
2. **Lo tachado se distingue de lo que falta, y se ve cuántos faltan.**
3. **El avance sobrevive a recargar la página** — y a cambiar de pestaña y de
   máquina, que es lo que decidió el ADR.
4. **La clave se copia de un clic**, porque es lo que se pega en el buscador
   del portal.
5. **Tachar todo lleva a enviar SIN OBLIGAR a ello.** Enviar con cero renglones
   tachados sigue funcionando exactamente igual que en el ticket 21: el ADR 0009
   lo permite y no es un descuido.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    CERRADO,
    ENVIADO,
    PedidoGuardado,
    PrecioDeProveedor,
    RENGLON_ABIERTO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RenglonGuardado,
    columnas_del_renglon,
    revisar_el_renglon,
)
from continental.particion import (
    CAPTURA_COMPLETA,
    CAPTURA_NO_OBLIGA,
    SIN_CONSULTARLE,
    SIN_PRECIO_DE_ESE_PROVEEDOR,
    Captura,
    frase_del_avance,
    invitacion_a_enviar,
    lo_que_hay_que_capturar,
)
from continental.precios import LecturaDePrecio, SESION_CADUCADA
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0007-el-avance-de-la-captura.sql"
ALMACENAMIENTO = RAIZ / "src" / "continental" / "almacenamiento.py"
PANTALLA = RAIZ / "src" / "continental" / "web" / "static" / "index.html"
ADR = RAIZ / "docs" / "decisiones" / "0010-el-avance-de-la-captura-vive-en-la-tabla-del-renglon.md"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"
OTRO_CORREO = "duenio@farmacia.mx"
ARMADO = dt.datetime(2024, 3, 5, 9, 0, tzinfo=dt.UTC)


# ------------------------------------------------------------- utilidades


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    """El `.sql` **sin sus comentarios**, que es lo único que Postgres ejecuta.

    La misma función que `test_envio.py` y `test_pedidos.py`, y por la misma
    razón: los archivos de `sql/` de este repo son más prosa que sentencias.
    """
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def _sentencia_python(nombre: str) -> str:
    """El texto de una sentencia `text(...)` de `almacenamiento.py`, sin comentarios."""
    fuente = _texto(ALMACENAMIENTO)
    inicio = fuente.index('"""', fuente.index(f"{nombre} = text(")) + 3
    fin = fuente.index('"""', inicio)
    return re.sub(r"--[^\n]*", "", fuente[inicio:fin])


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=0.0,
        esta_activo=True,
        es_granel=False,
    )


def _poblar(almacen, cuantos: int = 1) -> None:
    almacen.catalogo_en_memoria = [
        _producto(n, f"750100000{n:04d}") for n in range(1, cuantos + 1)
    ]
    almacen.ventas_en_memoria = [_venta(HOY, n, 3) for n in range(1, cuantos + 1)]


def _lectura(
    proveedor: str,
    precio: str | None = None,
    existencia: str | None = "40",
    motivo: str | None = None,
) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="" if existencia is None else existencia,
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _pedido_con(cliente, almacen, almacenamiento, cuantos: int = 3) -> tuple[dict, dict]:
    """Una lista de `cuantos` renglones, todos a NADRO, partida en un pedido.

    Devuelve `(lista_partida, pedido)`: la respuesta de partir y el único pedido
    guardado que salió de ahí.
    """
    _poblar(almacen, cuantos)
    lista = cliente.get(RUTA).json()
    for i in range(cuantos):
        almacenamiento.guardar_precios(
            NEGOCIO,
            lista["renglones"][i]["renglon_id"],
            [_lectura("nadro", f"1{i}.50")],
        )
    lista = cliente.get(RUTA).json()
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    return partida, partida["pedidos"][0]


def _tachar(cliente, renglon_id: int, capturado: bool = True, correo: str | None = CORREO):
    cabeceras = {} if correo is None else {"Cf-Access-Authenticated-User-Email": correo}
    return cliente.post(
        f"/api/renglon/{renglon_id}/capturado",
        json={"capturado": capturado},
        headers=cabeceras,
    )


def _enviar(cliente, pedido_id: int):
    return cliente.post(
        f"/api/pedido/{pedido_id}/enviar",
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )


def _el_pedido(respuesta: dict, pedido_id: int) -> dict:
    return next(p for p in respuesta["pedidos"] if p["pedido_id"] == pedido_id)


def _renglon(
    renglon_id: int,
    pedido_id: int | None = 7,
    clave: str = "7501000000001",
    estado: str = RENGLON_ABIERTO,
    capturado_por: str | None = None,
    cantidad: int = 3,
) -> RenglonGuardado:
    """Un `RenglonGuardado` a mano, para las pruebas de lo puro."""
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=renglon_id,
            clave=clave,
            descripcion=f"PRODUCTO {renglon_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=bool(clave),
            existencia=None if not clave else 0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        descartado_por=CORREO if estado == RENGLON_DESCARTADO else None,
        descartado_en=ARMADO if estado == RENGLON_DESCARTADO else None,
        pedido_id=pedido_id,
        capturado_por=capturado_por,
        capturado_en=None if capturado_por is None else ARMADO,
    )


def _pedido(estado: str = BORRADOR, pedido_id: int = 7, proveedor: str = "nadro") -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=pedido_id,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor=proveedor,
        proveedor_id=1,
        estado=estado,
        armado_en=ARMADO,
        total_sin_iva=Decimal("100.00"),
        enviado_por=CORREO if estado == ENVIADO else None,
        enviado_en=ARMADO if estado == ENVIADO else None,
    )


def _precio(renglon_id: int, proveedor: str, precio: str | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor=proveedor,
        consultado_en=ARMADO,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


# ==========================================================================
# LO PURO — qué se captura, cuántos faltan, y qué se le dice al encargado
# ==========================================================================


def test_cada_renglon_trae_clave_descripcion_cantidad_y_precio():
    """**Casilla 1.** Lo que se teclea en el portal, todo en la misma línea."""
    captura = lo_que_hay_que_capturar(
        _pedido(),
        [_renglon(1, cantidad=4)],
        {1: [_precio(1, "nadro", "12.50")]},
    )

    (linea,) = captura.lineas
    assert linea.clave == "7501000000001"
    assert linea.descripcion == "PRODUCTO 1"
    assert linea.cantidad == 4
    assert linea.precio == Decimal("12.50")
    assert linea.esta_capturado is False


def test_el_precio_es_el_de_ESE_proveedor_y_no_el_mas_barato():
    """El precio que el encargado va a ver en el portal de NADRO es el de NADRO.

    Enseñar el de LEVIC porque es más barato haría que el número de esta
    pantalla y el del carrito de allá no cuadraran, justo mientras se captura.
    """
    captura = lo_que_hay_que_capturar(
        _pedido(proveedor="nadro"),
        [_renglon(1)],
        {1: [_precio(1, "levic", "9.00"), _precio(1, "nadro", "12.50")]},
    )
    assert captura.lineas[0].precio == Decimal("12.50")


def test_sin_precio_de_ese_proveedor_se_dice_y_nunca_es_cero():
    """Regla 4: un hueco con su motivo, no un `0.00` que se lea "gratis"."""
    sin_consultar = lo_que_hay_que_capturar(_pedido(), [_renglon(1)], {})
    caducada = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1)], {1: [_precio(1, "nadro", None)]}
    )

    assert sin_consultar.lineas[0].precio is None
    assert sin_consultar.lineas[0].motivo == SIN_CONSULTARLE
    assert caducada.lineas[0].precio is None
    assert caducada.lineas[0].motivo == SIN_PRECIO_DE_ESE_PROVEEDOR


def test_solo_entran_los_renglones_que_de_verdad_estan_dentro_del_pedido():
    """**La trampa del ticket.** Lo que se captura es lo que el pedido GUARDADO
    tiene dentro (`renglon.pedido_id`), no la vista previa de la partición.

    La vista previa se recalcula con los precios de este instante: si llega un
    LEVIC más barato, la vista previa ya lo pone en LEVIC mientras el pedido de
    NADRO todavía lo tiene dentro. La lista de captura tiene que coincidir con lo
    que va a pasar a `en tránsito` al enviar — y eso es `pedido_id`.
    """
    captura = lo_que_hay_que_capturar(
        _pedido(pedido_id=7),
        [_renglon(1, pedido_id=7), _renglon(2, pedido_id=8), _renglon(3, pedido_id=None)],
        {},
    )
    assert [l.renglon_id for l in captura.lineas] == [1]


def test_un_descartado_dentro_del_pedido_no_se_captura_y_se_cuenta_aparte():
    """Descartar no suelta el renglón de su pedido (`_DESCARTAR` no toca
    `pedido_id`), así que un pedido en borrador puede tener dentro uno que ya
    nadie va a pedir. **No se lista para capturar** —teclearlo en el portal
    sería comprar lo que alguien decidió no comprar— y se dice cuántos hay, en
    vez de dejar que la cuenta del pedido y la de la captura difieran sin
    explicación.
    """
    captura = lo_que_hay_que_capturar(
        _pedido(),
        [_renglon(1), _renglon(2, estado=RENGLON_DESCARTADO)],
        {},
    )
    assert [l.renglon_id for l in captura.lineas] == [1]
    assert captura.descartados_dentro == 1
    assert "descartado" in frase_del_avance(captura)


def test_el_orden_es_el_de_la_lista_y_no_cambia_al_tachar():
    """Lo tachado NO se va al final. Una lista que se reordena bajo el dedo
    mientras alguien la recorre hace perder el renglón por el que iba."""
    captura = lo_que_hay_que_capturar(
        _pedido(),
        [_renglon(1, capturado_por=CORREO), _renglon(2), _renglon(3, capturado_por=CORREO)],
        {},
    )
    assert [l.renglon_id for l in captura.lineas] == [1, 2, 3]


def test_cuantos_faltan_sale_de_python():
    """**Casilla 2.** El número va arriba y lo cuenta Python, donde hay pruebas."""
    captura = lo_que_hay_que_capturar(
        _pedido(),
        [_renglon(1, capturado_por=CORREO), _renglon(2), _renglon(3)],
        {},
    )
    assert captura.cuantos == 3
    assert captura.capturados == 1
    assert captura.faltan == 2
    assert captura.todo_capturado is False


def test_la_frase_del_avance_dice_cuantos_faltan():
    captura = lo_que_hay_que_capturar(
        _pedido(),
        [_renglon(1, capturado_por=CORREO), _renglon(2), _renglon(3)],
        {},
    )
    frase = frase_del_avance(captura)
    assert "1 de 3" in frase
    assert "faltan 2" in frase


def test_la_frase_con_uno_solo_por_capturar_no_dice_faltan_1():
    captura = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1, capturado_por=CORREO), _renglon(2)], {}
    )
    frase = frase_del_avance(captura)
    assert "falta 1" in frase
    assert "faltan 1" not in frase


def test_la_frase_sin_nada_tachado_no_dice_cero_de():
    """"0 de 18" se lee como un marcador; "ninguno tachado todavía" como un
    punto de partida, que es lo que es."""
    captura = lo_que_hay_que_capturar(_pedido(), [_renglon(1), _renglon(2)], {})
    frase = frase_del_avance(captura)
    assert "0 de" not in frase
    assert "ninguno" in frase.lower()


def test_la_frase_con_todo_tachado():
    captura = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1, capturado_por=CORREO), _renglon(2, capturado_por=CORREO)], {}
    )
    assert captura.todo_capturado is True
    assert captura.faltan == 0
    assert "los 2" in frase_del_avance(captura).lower()


def test_un_pedido_sin_renglones_NO_esta_todo_capturado():
    """Nada que capturar no es todo capturado. Si lo fuera, el pedido vacío
    —el que se quedó sin renglones al volver a partir— invitaría a enviar, y
    `motivo_para_no_enviar` lo niega con razón (ticket 21)."""
    captura = lo_que_hay_que_capturar(_pedido(), [], {})
    assert captura.hay is False
    assert captura.todo_capturado is False
    assert invitacion_a_enviar(captura, se_puede_enviar=True) is None


def test_todo_tachado_LLEVA_a_enviar():
    """**Casilla 5, primera mitad.** Tachar el último es el empujón hacia
    enviar, con la frase hecha en Python."""
    captura = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1, capturado_por=CORREO)], {}
    )
    assert invitacion_a_enviar(captura, se_puede_enviar=True) == CAPTURA_COMPLETA


def test_con_renglones_por_tachar_la_pantalla_dice_que_NO_obliga():
    """**Casilla 5, segunda mitad, y la que se hace mal sola.** Enviar no espera
    a que se tache todo: si alguien capturó en el portal sin tachar aquí —o
    tachó en otra pestaña que cerró—, enviar sigue siendo lo correcto, y la
    pantalla lo dice en vez de dejar que se crea que el botón está condicionado.
    """
    captura = lo_que_hay_que_capturar(_pedido(), [_renglon(1), _renglon(2)], {})
    invitacion = invitacion_a_enviar(captura, se_puede_enviar=True)
    assert invitacion == CAPTURA_NO_OBLIGA
    assert "no" in invitacion.lower()


def test_todo_tachado_no_invita_a_enviar_lo_que_no_se_puede_enviar():
    """Si el total envejeció, el motivo del ticket 21 ya lo dice. Invitar a
    enviar al lado de un botón apagado serían dos frases que se contradicen."""
    captura = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1, capturado_por=CORREO)], {}
    )
    assert invitacion_a_enviar(captura, se_puede_enviar=False) is None


def test_un_renglon_sin_clave_se_dice_para_buscarlo_por_nombre():
    """**Casilla 4, el caso borde.** Un producto que el catálogo no conoce no
    tiene EAN que copiar. No es un hueco que esconder: se busca por nombre."""
    captura = lo_que_hay_que_capturar(_pedido(), [_renglon(1, clave="")], {})
    assert captura.lineas[0].tiene_clave is False
    assert captura.sin_clave == 1


def test_sin_clave_ya_tachado_no_manda_a_buscarlo_por_nombre():
    """**Lo cazó el recorrido del navegador, no el suite.** Con los cinco
    tachados, el resumen seguía diciendo "1 sin código de barras: búscalo por
    nombre" — mandaba a buscar algo que ya se capturó."""
    pendiente = lo_que_hay_que_capturar(_pedido(), [_renglon(1, clave="")], {})
    tachado = lo_que_hay_que_capturar(
        _pedido(), [_renglon(1, clave="", capturado_por=CORREO)], {}
    )

    assert "búscalo por nombre" in frase_del_avance(pendiente)
    assert "búscalo por nombre" not in frase_del_avance(tachado)
    # El total sin clave sigue contado: es un dato del pedido, no del avance.
    assert tachado.sin_clave == 1


def test_captura_es_un_dato_puro_sin_red_ni_reloj():
    """Se construye a mano y contesta sin tocar nada."""
    captura = Captura(proveedor="nadro")
    assert captura.nombre == "NADRO"
    assert captura.cuantos == 0


# ==========================================================================
# LO QUE SE GUARDA — la firma en la tabla del renglón, y cuándo se niega
# ==========================================================================


def test_un_renglon_nace_sin_tachar():
    columnas = columnas_del_renglon(
        Renglon(
            producto_id=1,
            clave="7501000000001",
            descripcion="X",
            piezas_vendidas=1.0,
            cantidad_propuesta=1,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        NEGOCIO,
        1,
    )
    assert columnas["capturado_por"] is None
    assert columnas["capturado_en"] is None


def _columnas_validas(**cambios) -> dict:
    columnas = columnas_del_renglon(
        Renglon(
            producto_id=1,
            clave="7501000000001",
            descripcion="X",
            piezas_vendidas=1.0,
            cantidad_propuesta=1,
            esta_en_el_catalogo=True,
            existencia=0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        NEGOCIO,
        1,
    )
    columnas.update(cambios)
    return columnas


def test_la_firma_de_la_captura_va_pareada_como_las_otras_cuatro():
    """`ck_renglon_captura`: o están quién y cuándo, o no está ninguno."""
    revisar_el_renglon(_columnas_validas(capturado_por=CORREO, capturado_en=ARMADO))
    with pytest.raises(ValueError, match="ck_renglon_captura"):
        revisar_el_renglon(_columnas_validas(capturado_por=CORREO, capturado_en=None))
    with pytest.raises(ValueError, match="ck_renglon_captura"):
        revisar_el_renglon(_columnas_validas(capturado_por=None, capturado_en=ARMADO))


def test_la_firma_vacia_se_rechaza():
    with pytest.raises(ValueError, match="capturado_por"):
        revisar_el_renglon(_columnas_validas(capturado_por="", capturado_en=ARMADO))


def test_tachar_firma_con_el_correo_y_la_hora(cliente, almacen, almacenamiento):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    renglon_id = partida["renglones"][0]["renglon_id"]

    guardado = almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO)

    renglon = next(r for r in guardado.renglones if r.renglon_id == renglon_id)
    assert renglon.capturado_por == CORREO
    assert renglon.capturado_en is not None
    assert renglon.capturado_en.tzinfo is not None
    assert renglon.esta_capturado is True


def test_tachar_no_cambia_el_estado_del_renglon(cliente, almacen, almacenamiento):
    """**Por qué columnas y no un estado nuevo** (ADR 0010, opción 4). Un
    renglón dentro de un borrador sigue `abierto` (ticket 20): si tachar lo
    moviera de estado, `_ASIGNAR_RENGLONES` dejaría de poder moverlo y volver a
    partir se lo saltaría en silencio."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]

    guardado = almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO)

    assert guardado.renglones[0].estado == RENGLON_ABIERTO
    assert guardado.renglones[0].pedido_id == pedido_id_de(partida)


def pedido_id_de(partida: dict) -> int:
    return partida["pedidos"][0]["pedido_id"]


def test_destachar_borra_las_dos_columnas(cliente, almacen, almacenamiento):
    """Un clic de más en una lista de 40 es ordinario, y mientras el pedido
    siga en borrador nada depende todavía de la marca."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]
    almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO)

    guardado = almacenamiento.marcar_capturado(NEGOCIO, renglon_id, False, CORREO)

    assert guardado.renglones[0].capturado_por is None
    assert guardado.renglones[0].capturado_en is None


def test_un_renglon_sin_pedido_no_se_tacha(cliente, almacen, almacenamiento):
    """Tachar es "ya lo tecleé en el portal de ESTE proveedor". Sin pedido no
    hay proveedor de cuyo portal hablar."""
    _poblar(almacen, 1)
    lista = cliente.get(RUTA).json()
    renglon_id = lista["renglones"][0]["renglon_id"]

    assert almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO) is None


def test_un_renglon_de_un_pedido_enviado_ya_no_se_tacha_ni_se_destacha(
    cliente, almacen, almacenamiento
):
    """Un pedido `enviado` ya no se edita (ADR 0009), y sus marcas quedan como
    quedaron: son la historia de cómo se capturó."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    primero, segundo = (r["renglon_id"] for r in partida["renglones"])
    almacenamiento.marcar_capturado(NEGOCIO, primero, True, CORREO)
    assert _enviar(cliente, pedido["pedido_id"]).status_code == 200

    assert almacenamiento.marcar_capturado(NEGOCIO, segundo, True, CORREO) is None
    assert almacenamiento.marcar_capturado(NEGOCIO, primero, False, CORREO) is None


def test_enviar_conserva_las_marcas(cliente, almacen, almacenamiento):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    primero = partida["renglones"][0]["renglon_id"]
    almacenamiento.marcar_capturado(NEGOCIO, primero, True, CORREO)

    _enviar(cliente, pedido["pedido_id"])

    lista = almacenamiento.leer_por_id(NEGOCIO, partida["pedido_sugerido_id"])
    renglon = next(r for r in lista.renglones if r.renglon_id == primero)
    assert renglon.estado == RENGLON_EN_TRANSITO
    assert renglon.capturado_por == CORREO


def test_un_descartado_no_se_tacha(cliente, almacen, almacenamiento):
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 2)
    renglon_id = partida["renglones"][0]["renglon_id"]
    almacenamiento.descartar(NEGOCIO, renglon_id, CORREO)

    assert almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO) is None


def test_de_otro_negocio_no_se_tacha(cliente, almacen, almacenamiento):
    """Regla 7: el negocio va en el `WHERE`."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]

    assert almacenamiento.marcar_capturado("farmacia_02", renglon_id, True, CORREO) is None


def test_tachar_NO_exige_la_lista_abierta(cliente, almacen, almacenamiento):
    """**Igual que enviar, y por la misma razón** (ADR 0009 y 0010). Tachar es
    decir "ya lo tecleé en el portal", lo contrario de modificar lo que se va a
    pedir. Si lo exigiera, quien cierra la lista antes de terminar de capturar
    se queda sin la cuenta y sin el camino de la quinta casilla."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]
    almacenamiento.poner_estado(
        partida["pedido_sugerido_id"], CERRADO, cerrado_en=ARMADO
    )

    guardado = almacenamiento.marcar_capturado(NEGOCIO, renglon_id, True, CORREO)

    assert guardado is not None
    assert guardado.renglones[0].capturado_por == CORREO


def test_volver_a_partir_a_OTRO_proveedor_borra_la_marca(cliente, almacen, almacenamiento):
    """**La falla silenciosa que el `localStorage` tendría y la tabla no.**

    Tachado en el portal de NADRO, movido a LEVIC y vuelto a partir: en el
    portal de LEVIC nadie lo ha tecleado. Si la marca viajara con el renglón
    diría *capturado* en un pedido donde no lo está, y el encargado se lo
    saltaría.
    """
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 2)
    movido, quieto = (r["renglon_id"] for r in partida["renglones"])
    almacenamiento.marcar_capturado(NEGOCIO, movido, True, CORREO)
    almacenamiento.marcar_capturado(NEGOCIO, quieto, True, CORREO)

    cliente.post(
        f"/api/renglon/{movido}/proveedor",
        json={"proveedor": "levic"},
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    cliente.post(f"{RUTA}/{partida['pedido_sugerido_id']}/partir")

    lista = almacenamiento.leer_por_id(NEGOCIO, partida["pedido_sugerido_id"])
    por_id = {r.renglon_id: r for r in lista.renglones}
    assert por_id[movido].capturado_por is None
    assert por_id[movido].capturado_en is None
    # Y el que se quedó en su pedido CONSERVA la marca: volver a partir a
    # mitad de la captura no puede costar el avance entero.
    assert por_id[quieto].capturado_por == CORREO


def test_quedarse_sin_pedido_al_volver_a_partir_borra_la_marca(
    cliente, almacen, almacenamiento
):
    """`_SOLTAR_RENGLONES`: el renglón que ya no se reparte a nadie tampoco está
    capturado en ningún portal que este sistema vaya a mirar."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 2)
    soltado = partida["renglones"][0]["renglon_id"]
    almacenamiento.marcar_capturado(NEGOCIO, soltado, True, CORREO)
    # Una partición que ya no reparte nada. Desde la pantalla es difícil de
    # provocar —el precio solo crece (ADR 0004), así que el renglón sigue
    # teniendo a quién pedírsele—, y por eso se llama directo al almacenamiento:
    # lo que se prueba es `_SOLTAR_RENGLONES`, no cómo se llega a él.
    almacenamiento.guardar_la_particion(NEGOCIO, partida["pedido_sugerido_id"], ())

    releida = almacenamiento.leer_por_id(NEGOCIO, partida["pedido_sugerido_id"])
    renglon = next(r for r in releida.renglones if r.renglon_id == soltado)
    assert renglon.pedido_id is None
    assert renglon.capturado_por is None


def test_el_avance_sobrevive_a_releer(cliente, almacen, almacenamiento):
    """**Casilla 3, en el seam de lo que se guarda.** Releer es lo que hace la
    página al recargarse, desde esta pestaña o desde otra máquina."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 3)
    ids = [r["renglon_id"] for r in partida["renglones"]]
    almacenamiento.marcar_capturado(NEGOCIO, ids[0], True, CORREO)
    almacenamiento.marcar_capturado(NEGOCIO, ids[2], True, OTRO_CORREO)

    lista = almacenamiento.leer_por_id(NEGOCIO, partida["pedido_sugerido_id"])
    por_id = {r.renglon_id: r for r in lista.renglones}
    assert por_id[ids[0]].capturado_por == CORREO
    assert por_id[ids[1]].capturado_por is None
    assert por_id[ids[2]].capturado_por == OTRO_CORREO


def test_una_fila_sin_la_migracion_se_lee_como_sin_tachar():
    """`.get` y no `[...]`, como las cuatro del ticket 20: una fila sin las
    columnas es "nadie tachó", no un `KeyError` que tumbe la lista entera."""
    from continental.almacenamiento import renglon_guardado_desde_columnas

    fila = _columnas_validas()
    fila.pop("capturado_por")
    fila.pop("capturado_en")
    fila["renglon_id"] = 1
    renglon = renglon_guardado_desde_columnas(fila)
    assert renglon.capturado_por is None
    assert renglon.esta_capturado is False


# ---------------------------------------------------------- el SQL, como texto


def test_la_sentencia_de_tachar_exige_pedido_en_borrador_y_renglon_abierto():
    sentencia = _sentencia_python("_MARCAR_CAPTURADO")
    assert "capturado_por = :quien" in sentencia
    assert "capturado_en = now()" in sentencia
    assert "r.estado = 'abierto'" in sentencia
    assert "p.estado = 'borrador'" in sentencia
    assert "r.negocio = :negocio" in sentencia
    assert "p.pedido_id = r.pedido_id" in sentencia


def test_la_sentencia_de_tachar_NO_mira_el_estado_de_la_lista():
    """La decisión del ADR 0010, fijada: ni `pedido_sugerido` en el `FROM`."""
    for nombre in ("_MARCAR_CAPTURADO", "_DESMARCAR_CAPTURADO"):
        assert "pedido_sugerido as" not in _sentencia_python(nombre)


def test_la_sentencia_de_destachar_borra_las_dos():
    sentencia = _sentencia_python("_DESMARCAR_CAPTURADO")
    assert "capturado_por = null" in sentencia
    assert "capturado_en = null" in sentencia
    assert "p.estado = 'borrador'" in sentencia


def test_las_dos_devuelven_lo_que_la_relectura_necesita():
    """`_mover_el_renglon` relee la lista por `pedido_sugerido_id`."""
    for nombre in ("_MARCAR_CAPTURADO", "_DESMARCAR_CAPTURADO"):
        assert "returning r.renglon_id, r.pedido_sugerido_id" in _sentencia_python(nombre)


def test_asignar_a_otro_pedido_borra_la_marca_en_el_sql():
    sentencia = _sentencia_python("_ASIGNAR_RENGLONES")
    assert "is distinct from :pedido_id" in sentencia
    assert "capturado_por" in sentencia
    assert "capturado_en" in sentencia


def test_soltar_borra_la_marca_en_el_sql():
    sentencia = _sentencia_python("_SOLTAR_RENGLONES")
    assert "capturado_por = null" in sentencia
    assert "capturado_en = null" in sentencia


@pytest.mark.parametrize("nombre", ["_LEER_RENGLONES", "_LEER_RENGLON_POR_ID"])
def test_las_lecturas_traen_las_dos_columnas(nombre):
    sentencia = _sentencia_python(nombre)
    assert "capturado_por" in sentencia
    assert "capturado_en" in sentencia


def test_crear_tablas_declara_las_columnas_y_el_check():
    sql = _sentencias(CREAR_TABLAS)
    assert re.search(r"capturado_por\s+text", sql)
    assert re.search(r"capturado_en\s+timestamptz", sql)
    assert "ck_renglon_captura" in sql
    assert "ck_renglon_capturado_por" in sql


def test_la_migracion_0007_es_idempotente_y_no_crea_tabla():
    sql = _sentencias(MIGRACION)
    assert "ADD COLUMN IF NOT EXISTS capturado_por" in sql
    assert "ADD COLUMN IF NOT EXISTS capturado_en" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_renglon_captura" in sql
    assert "CREATE TABLE" not in sql
    # Con credenciales de dueño y en una transacción, como las seis anteriores.
    assert "current_user = 'continental'" in sql
    assert "BEGIN;" in sql and "COMMIT;" in sql


def test_la_migracion_no_trae_retorno_de_carro():
    assert b"\r" not in MIGRACION.read_bytes()


def test_verificar_rol_mira_la_firma_de_la_captura():
    sql = _sentencias(VERIFICAR_ROL)
    assert "(29," in sql
    assert "ck_renglon_captura" in sql


def test_el_adr_existe_y_nombra_lo_que_descarto():
    adr = _texto(ADR)
    assert "localStorage" in adr
    assert "dos pestañas" in adr.lower()
    assert "Estado:** aceptada" in adr


# ==========================================================================
# LO QUE SE VE — la ruta y la pantalla
# ==========================================================================


def test_la_ruta_tacha_firma_y_devuelve_la_lista_entera(cliente, almacen, almacenamiento):
    """Devuelve la lista entera, como `partir` y `enviar`: tachar cambia el
    avance de su pedido y la invitación a enviar, y deducirlo en el navegador
    es justo lo que esta pantalla no hace."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 3)
    renglon_id = partida["renglones"][0]["renglon_id"]

    respuesta = _tachar(cliente, renglon_id)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["ok"] is True
    captura = _el_pedido(datos, pedido["pedido_id"])["captura"]
    assert captura["capturados"] == 1
    assert captura["faltan"] == 2
    linea = next(l for l in captura["lineas"] if l["renglon_id"] == renglon_id)
    assert linea["esta_capturado"] is True
    assert linea["capturado_por"] == CORREO


def test_sin_encabezado_de_access_firma_sin_identificar(cliente, almacen, almacenamiento):
    """Regla 3: el correo es una firma y nunca un permiso. Sin encabezado se
    tacha igual, firmado como `sin-identificar` —que sí es un dato—."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]

    datos = _tachar(cliente, renglon_id, correo=None).json()

    linea = _el_pedido(datos, pedido["pedido_id"])["captura"]["lineas"][0]
    assert linea["capturado_por"] == "sin-identificar"


def test_destachar_por_la_ruta(cliente, almacen, almacenamiento):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]
    _tachar(cliente, renglon_id)

    datos = _tachar(cliente, renglon_id, capturado=False).json()

    captura = _el_pedido(datos, pedido["pedido_id"])["captura"]
    assert captura["capturados"] == 0
    assert captura["lineas"][0]["capturado_por"] is None


def test_lo_que_no_se_puede_tachar_es_409_con_palabras(cliente, almacen, almacenamiento):
    _poblar(almacen, 1)
    lista = cliente.get(RUTA).json()

    respuesta = _tachar(cliente, lista["renglones"][0]["renglon_id"])

    assert respuesta.status_code == 409
    assert respuesta.json()["ok"] is False
    assert "pedido" in respuesta.json()["detalle"]


def test_el_cuerpo_tiene_que_decir_si_o_no(cliente, almacen, almacenamiento):
    """Sin `capturado` no se adivina: un tachón por omisión firmaría algo que
    nadie dijo."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]

    respuesta = cliente.post(f"/api/renglon/{renglon_id}/capturado", json={})

    assert respuesta.status_code == 422


def test_con_la_base_caida_el_error_no_viaja_al_navegador(
    cliente, almacen, almacenamiento
):
    """**Regla 5.** El detalle a la bitácora, al navegador solo el tipo."""
    partida, _ = _pedido_con(cliente, almacen, almacenamiento, 1)
    renglon_id = partida["renglones"][0]["renglon_id"]
    almacenamiento.falla = RuntimeError(
        "postgresql://continental:SECRETO@warehouse:5432/farmacia"
    )

    respuesta = _tachar(cliente, renglon_id)

    datos = respuesta.json()
    assert datos["ok"] is False
    assert "SECRETO" not in respuesta.text
    assert "RuntimeError" in datos["detalle"]


def test_el_avance_sobrevive_a_recargar_la_pagina(cliente, almacen, almacenamiento):
    """**Casilla 3, de punta a punta.** Tachar, recargar —un `GET` nuevo, que es
    lo que hace el navegador al recargar o lo que hace OTRA pestaña u OTRA
    máquina—, y el avance sigue ahí."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 3)
    ids = [r["renglon_id"] for r in partida["renglones"]]
    _tachar(cliente, ids[0])
    _tachar(cliente, ids[1], correo=OTRO_CORREO)

    recargada = cliente.get(RUTA).json()

    captura = _el_pedido(recargada, pedido["pedido_id"])["captura"]
    assert captura["capturados"] == 2
    assert captura["faltan"] == 1
    firmas = {l["renglon_id"]: l["capturado_por"] for l in captura["lineas"]}
    assert firmas == {ids[0]: CORREO, ids[1]: OTRO_CORREO, ids[2]: None}


def test_cada_linea_viaja_con_lo_que_se_teclea_en_el_portal(
    cliente, almacen, almacenamiento
):
    """**Casilla 1.** Y el precio como cadena, nunca como `double`."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 1)
    linea = _el_pedido(partida, pedido["pedido_id"])["captura"]["lineas"][0]

    assert linea["clave"] == "7501000000001"
    assert linea["descripcion"] == "PRODUCTO 1"
    assert linea["cantidad"] == 3
    assert linea["precio"] == "10.50"
    assert isinstance(linea["precio"], str)
    assert linea["tiene_clave"] is True
    assert linea["esta_capturado"] is False


def test_la_frase_del_avance_y_la_invitacion_viajan_hechas(
    cliente, almacen, almacenamiento
):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    captura = _el_pedido(partida, pedido["pedido_id"])["captura"]

    assert captura["frase"]
    assert captura["invitacion"] == CAPTURA_NO_OBLIGA


def test_tachar_el_ultimo_invita_a_enviar(cliente, almacen, almacenamiento):
    """**Casilla 5, de punta a punta, primera mitad.**"""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    ids = [r["renglon_id"] for r in partida["renglones"]]
    _tachar(cliente, ids[0])

    datos = _tachar(cliente, ids[1]).json()

    captura = _el_pedido(datos, pedido["pedido_id"])["captura"]
    assert captura["todo_capturado"] is True
    assert captura["invitacion"] == CAPTURA_COMPLETA
    assert _el_pedido(datos, pedido["pedido_id"])["se_puede_enviar"] is True


def test_enviar_SIN_haber_tachado_nada_sigue_funcionando(
    cliente, almacen, almacenamiento
):
    """**Casilla 5, segunda mitad, y la que no se puede romper.** El ticket 21
    ya permite enviar sin tachar, y no es un descuido: tachar habilita el
    camino, no lo condiciona. `se_puede_enviar` no mira la captura."""
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 3)
    antes = _el_pedido(partida, pedido["pedido_id"])
    assert antes["captura"]["capturados"] == 0
    assert antes["se_puede_enviar"] is True
    assert antes["motivo_para_no_enviar"] is None

    respuesta = _enviar(cliente, pedido["pedido_id"])

    assert respuesta.status_code == 200
    assert _el_pedido(respuesta.json(), pedido["pedido_id"])["fue_enviado"] is True


def test_enviar_con_la_mitad_tachada_tambien(cliente, almacen, almacenamiento):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 2)
    _tachar(cliente, partida["renglones"][0]["renglon_id"])

    assert _enviar(cliente, pedido["pedido_id"]).status_code == 200


def test_la_ruta_no_deja_tachar_un_pedido_enviado(cliente, almacen, almacenamiento):
    partida, pedido = _pedido_con(cliente, almacen, almacenamiento, 1)
    _enviar(cliente, pedido["pedido_id"])

    respuesta = _tachar(cliente, partida["renglones"][0]["renglon_id"])

    assert respuesta.status_code == 409


# ------------------------------------------------------------- la pantalla


def test_la_pantalla_sabe_pintar_la_captura():
    """HTML+JS plano: lo que cabe probar es que el archivo lo diga."""
    pantalla = _texto(PANTALLA)
    for pedazo in (
        "'/capturado'",
        "pintarCaptura",
        "type = 'checkbox'",
        "captura.frase",
        "captura.invitacion",
        "esta_capturado",
        "faltan",
    ):
        assert pedazo in pantalla, f"La pantalla no sabe pintar {pedazo!r}."


def test_la_clave_se_copia_de_un_clic():
    """**Casilla 4.** Con el portapapeles del navegador y, si no está, con el
    camino viejo — y si ninguno sirve, se DICE (regla 4), no se calla."""
    pantalla = _texto(PANTALLA)
    assert "navigator.clipboard" in pantalla
    assert "copiarClave" in pantalla
    assert "execCommand('copy')" in pantalla
    assert "no se pudo copiar" in pantalla


def test_el_avance_NO_vive_en_el_navegador():
    """**Casilla 3, la decisión del ADR 0010 fijada.** Nada de la captura se
    escribe en `localStorage` ni en `sessionStorage`."""
    pantalla = _texto(PANTALLA)
    inicio = pantalla.index("const pintarCaptura")
    fin = pantalla.index("const pintarParticion")
    bloque = pantalla[inicio:fin]
    assert "localStorage" not in bloque
    assert "sessionStorage" not in bloque


def test_la_pantalla_no_cuenta_lo_que_falta_ella_sola():
    """El número de arriba viene de Python: el JavaScript no filtra ni suma."""
    pantalla = _texto(PANTALLA)
    inicio = pantalla.index("const pintarCaptura")
    fin = pantalla.index("const pintarParticion")
    bloque = pantalla[inicio:fin]
    assert ".filter(" not in bloque
    assert "reduce(" not in bloque
    assert "parseFloat" not in bloque


def test_lo_tachado_se_distingue_con_una_clase_y_no_solo_con_color():
    """**Casilla 2.** Tachado de verdad —`line-through`— y atenuado: se ve sin
    distinguir colores."""
    pantalla = _texto(PANTALLA)
    assert ".captura li.hecho" in pantalla
    assert "line-through" in pantalla


def test_la_captura_no_apaga_el_boton_de_enviar():
    """**Casilla 5.** El botón se apaga por `se_puede_enviar` y por nada más:
    en el JavaScript no puede aparecer una condición de captura sobre él."""
    pantalla = _texto(PANTALLA)
    assert "boton.disabled = !guardado.se_puede_enviar;" in pantalla
    assert "todo_capturado && " not in pantalla.split("boton.disabled")[1].split("\n")[0]
