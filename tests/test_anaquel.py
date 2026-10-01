"""El anaquel viaja en el renglón, congelado con él (migración 0017).

El detalle del renglón enseña "GENERICO 3". El anaquel se guarda JUNTO a la
clasificación que sale de él y se relee del renglón, no del catálogo: lo mismo
que existencia, cobertura y clasificación, que son "tal como venían cuando se
propuso".

Tres valores en el JSON, y las pruebas los distinguen:

- el texto del anaquel, tal como vino de SICAR;
- `""`, cuando no hay anaquel que enseñar (sin ubicación, o sin catálogo);
- `null`, cuando **no se sabe**: un renglón de antes de la 0017.

**Ninguna toca Postgres.** Lo que no se puede ejecutar desde la torre se
revisa como texto, igual que `test_cierre_automatico.py` con la 0014.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

import continental.almacenamiento as almacenamiento_modulo
from continental import forma as f
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import columnas_del_renglon, renglon_desde_columnas
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "sql"
CREAR_TABLAS = SQL / "crear_tablas.sql"
CREAR_ROL = SQL / "crear_rol.sql"
VERIFICAR_ROL = SQL / "verificar_rol.sql"
MIGRACION = SQL / "migraciones" / "0017-el-anaquel-congelado-en-el-renglon.sql"

RUTA = "/api/pedido-sugerido"
FECHA = dt.date(2024, 3, 5)
NEGOCIO = "farmacia_01"


def _producto(producto_id: int, anaquel: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000000{producto_id}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel=anaquel,
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=4.0,
        esta_activo=True,
        es_granel=False,
    )


def _venta(producto_id: int) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=FECHA,
        producto_id=producto_id,
        cantidad=2,
        importe=20.0,
        costo=12.0,
        utilidad=8.0,
    )


def _por_producto(cuerpo: dict) -> dict[int, dict]:
    return {r["producto_id"]: r for r in cuerpo["renglones"]}


# ==========================================================================
# Lo que dice el JSON de la lista
# ==========================================================================


def test_un_renglon_nuevo_trae_su_anaquel_tal_como_viene_de_sicar(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1, "GENERICO 3")]
    almacen.ventas_en_memoria = [_venta(1)]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert _por_producto(cuerpo)[1]["anaquel"] == "GENERICO 3"


def test_un_producto_sin_anaquel_trae_cadena_vacia_y_no_null(cliente, almacen):
    """El catálogo lo conoce y no lo tiene ubicado (688 de 3,429): se sabe que
    no hay anaquel, y eso no es "no se sabe"."""
    almacen.catalogo_en_memoria = [_producto(1, "")]
    almacen.ventas_en_memoria = [_venta(1)]

    renglon = _por_producto(cliente.get(RUTA).json())[1]

    assert renglon["anaquel"] == ""
    assert renglon["anaquel"] is not None


def test_un_producto_fuera_del_catalogo_trae_cadena_vacia(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1, "GENERICO 3")]
    almacen.ventas_en_memoria = [_venta(1), _venta(99)]

    renglones = _por_producto(cliente.get(RUTA).json())

    assert renglones[99]["esta_en_el_catalogo"] is False
    assert renglones[99]["anaquel"] == ""


def test_el_anaquel_se_relee_del_renglon_y_no_del_catalogo(cliente, almacen):
    """El principio del renglón: lo que se ve es lo que se propuso. Si el
    producto cambia de anaquel mañana, la lista de hoy sigue diciendo el de
    cuando se armó, que es el que explica su clasificación."""
    almacen.catalogo_en_memoria = [_producto(1, "GENERICO 3")]
    almacen.ventas_en_memoria = [_venta(1)]
    cliente.get(RUTA)

    almacen.catalogo_en_memoria = [_producto(1, "PATENTE 7")]
    segunda = cliente.get(RUTA).json()

    assert _por_producto(segunda)[1]["anaquel"] == "GENERICO 3"


def test_una_fila_guardada_antes_de_la_0017_trae_null(cliente, almacen, almacenamiento):
    """Sin el dato no se inventa uno: ni el de hoy ni una cadena vacía."""
    almacen.catalogo_en_memoria = [_producto(1, "GENERICO 3")]
    almacen.ventas_en_memoria = [_venta(1)]
    cliente.get(RUTA)
    # La fila como la dejó la base de antes: sin el dato. En el doble las filas
    # son diccionarios; en Postgres la columna valdría NULL.
    for lista in almacenamiento.listas:
        for fila in lista["renglones"]:
            fila.pop("anaquel", None)

    renglon = _por_producto(cliente.get(RUTA).json())[1]

    assert renglon["anaquel"] is None


# ==========================================================================
# Los dos caminos del renglón a las columnas y de vuelta
# ==========================================================================


def _renglon(anaquel: str | None) -> Renglon:
    return Renglon(
        producto_id=1,
        clave="7501000000001",
        descripcion="PRODUCTO 1",
        piezas_vendidas=2.0,
        cantidad_propuesta=2,
        esta_en_el_catalogo=True,
        existencia=4.0,
        dias_de_cobertura=2.0,
        clasificacion="medicamento",
        anaquel=anaquel,
    )


@pytest.mark.parametrize("anaquel", ["GENERICO 3", "", None])
def test_ida_y_vuelta_conserva_los_tres_valores(anaquel):
    columnas = columnas_del_renglon(_renglon(anaquel), NEGOCIO, 1)

    assert columnas["anaquel"] == anaquel
    assert renglon_desde_columnas(columnas).anaquel == anaquel


def test_una_fila_sin_la_columna_se_lee_como_no_se_sabe():
    columnas = columnas_del_renglon(_renglon("GENERICO 3"), NEGOCIO, 1)
    del columnas["anaquel"]

    assert renglon_desde_columnas(columnas).anaquel is None


# ==========================================================================
# El SQL como texto: la migración 0017 y los archivos que la acompañan
# ==========================================================================


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _sentencias(ruta: Path) -> str:
    return re.sub(r"--[^\n]*", "", _texto(ruta))


def test_la_migracion_existe_con_su_forma():
    sentencias = _sentencias(MIGRACION)

    assert MIGRACION.exists()
    assert "ALTER TABLE pedidos.renglon ADD COLUMN IF NOT EXISTS anaquel text;" in sentencias
    assert "CREATE TABLE" not in sentencias
    assert "GRANT" not in sentencias
    assert "current_user = 'continental'" in sentencias
    assert "SET client_encoding TO 'UTF8'" in sentencias
    assert "BEGIN;" in sentencias and "COMMIT;" in sentencias


def test_la_migracion_no_rompe_el_codigo_viejo_de_atlas():
    """Nullable, sin DEFAULT y sin CHECK: el `INSERT` de antes no la nombra y
    queda en NULL, que es "no se sabe"."""
    sentencias = _sentencias(MIGRACION)

    assert "NOT NULL" not in sentencias.replace("IS NOT NULL", "")
    assert "DEFAULT" not in sentencias
    assert "CONSTRAINT" not in sentencias


def test_la_migracion_es_utf8_y_con_lf():
    crudo = MIGRACION.read_bytes()
    crudo.decode("utf-8")
    assert b"\r" not in crudo, "Los .sql van con LF (.gitattributes)."


def test_crear_tablas_declara_la_columna_nullable_y_nombra_la_0017():
    sentencias = _sentencias(CREAR_TABLAS)

    assert re.search(r"\n\s+anaquel\s+text,\r?\n", sentencias)
    assert "0017-el-anaquel-congelado-en-el-renglon.sql" in _texto(CREAR_TABLAS)


def test_forma_atribuye_la_columna_a_la_0017():
    migraciones = {
        m.name: m.read_bytes().decode("utf-8")
        for m in sorted((SQL / "migraciones").glob("*.sql"))
    }
    esperadas = f.columnas_de_crear_tablas(_texto(CREAR_TABLAS))

    assert "anaquel" in esperadas["renglon"]
    assert (
        f.migracion_de_cada_columna(migraciones)[("renglon", "anaquel")]
        == "0017-el-anaquel-congelado-en-el-renglon.sql"
    )


def test_verificar_rol_mira_la_columna():
    texto = _texto(VERIFICAR_ROL)

    assert "(40," in texto
    assert "a.attname = 'anaquel'" in texto


def test_el_grant_es_de_la_tabla_entera_y_cubre_la_columna():
    """Sin permisos por columna: no hace falta volver a correr crear_rol.sql."""
    sentencias = _sentencias(CREAR_ROL)

    assert "GRANT SELECT, INSERT, UPDATE ON pedidos.renglon" in sentencias
    assert not re.search(r"GRANT[^;]*\(\s*anaquel", sentencias)


@pytest.mark.parametrize(
    "nombre",
    [
        "_LEER_RENGLONES",
        "_LEER_RENGLON_POR_ID",
        "_LO_YA_PEDIDO",
        "_EN_TRANSITO",
        "_INSERTAR_RENGLONES",
    ],
)
def test_las_lecturas_y_la_escritura_del_renglon_nombran_el_anaquel(nombre):
    """Sin esto, el JSON diría `null` para toda lista nueva aunque la columna
    exista, y nadie lo notaría hasta mirar el detalle."""
    assert "anaquel" in str(getattr(almacenamiento_modulo, nombre)), nombre
