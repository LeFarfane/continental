# 15: Los huecos, visibles y contados

**Qué construir:** que nadie lea la lista como si estuviera completa. La pregunta "¿NADRO nos da el mejor precio?" solo vale lo que valga su cobertura, y eso tiene que estar a la vista.

**Bloqueado por:** 14.

**Status:** ready-for-agent

- [x] Se ve cuántos renglones quedaron **sin comparar**, y contra cuántos proveedores se comparó cada uno.
- [x] Cada precio faltante dice su motivo: el producto no está en ese catálogo, el EAN dio varios resultados, el portal no contestó, la sesión caducó.
- [x] Un renglón comparado contra un solo proveedor no se presenta como "el más barato": se presenta como "el único que contestó".
- [x] El conteo es legible sin abrir cada renglón.

## Lo que se decidió, con su porqué (2026-09-19)

**Dónde vive el conteo de la lista: una función pura en `comparacion.py`**
(`contar_la_lista`), y no una propiedad de `PedidoSugeridoGuardado` ni algo que
arme la ruta. Las tres propiedades vecinas —`sin_catalogo`, `sin_clasificar`,
`descartados`— se calculan sobre los renglones que ese dato **ya trae dentro**;
ésta no puede, porque depende de `precios_de_la_lista`, que es otra lectura.
Ponerla ahí obligaría a meter los precios dentro del objeto que representa "la
lista tal como se guardó" —que no los tiene— o a dejar que una propiedad abra
una conexión, que es peor: una consulta que no se ve en el código que la usa.
Armarla en la ruta dejaría la regla dentro de un `if` de FastAPI, probable solo
levantando la aplicación. La ruta trae las dos lecturas —ya las hacía las dos— y
las junta en una línea.

**Qué cuenta como "sin comparar": todo renglón del que no salieron DOS
precios**, y se desglosa en tres porque cada uno se arregla distinto:

| | se arregla | cuenta |
|---|---|---|
| nadie lo consultó | con el botón, o con el lote de la noche (18) | `sin_consultar` |
| se consultó y ninguno dio precio | mirando el motivo de cada hueco | `sin_un_solo_precio` |
| hay un solo precio | no se arregla: es una advertencia | `con_un_solo_precio` |

El tercero es la decisión que se puede discutir y es deliberada: **tiene dato y
aun así no está comparado.** Contarlo como comparado metería en el número de "ya
está" justo los renglones donde una compra se decidiría sobre una sola
cotización, que es lo que este ticket existe para impedir.

**Se cuenta sobre los renglones DE TRABAJO**, no sobre la lista entera. Un
descartado ya se atendió y nadie va a comprarlo. Se aparta a propósito de
`sin_clasificar`, que sí mira la lista entera porque su pregunta es sobre el
catálogo de SICAR y no cambia porque alguien descarte algo hoy.

**"El único que contestó" es la `certeza` del ganador, un dato puro.** Las
certezas pasan de dos a cuatro, cruzando dos preguntas que no son la misma:
¿confirmó alguien la existencia? y ¿hubo con qué comparar?

| | confirmó existencia | no la dijo |
|---|---|---|
| dos o más precios | `el más barato con existencia` | `el más barato, pero nadie confirmó existencia` |
| un solo precio | `el único que contestó` | `el único que contestó, y no dijo si lo tiene` |

La frase viaja **hecha** y la pantalla la escribe tal cual. Hasta el ticket 14
el JavaScript elegía entre dos literales suyos mirando una bandera, y por eso el
caso salía mal sin que nada se pusiera rojo: la afirmación vivía en el único
archivo que ninguna prueba de Python mira. Son cuatro y no tres porque el único
que además no dijo su existencia es el caso **peor informado de todos**, y
colapsarlo callaría la advertencia justo donde más falta hace.

**"Único" se mide sobre los precios, no sobre los elegibles.** Un renglón con
NADRO a $146.38 con 40 piezas y LEVIC a $86.05 con cero SÍ se comparó: se vieron
dos cifras y las dos están en la fila, aunque solo una pudiera ganar.

**El motivo tiene dos cadenas y no una.** La corta (`MOTIVOS`) es la que se
guarda, la que el `CHECK` del DDL repite y la que se cuenta; la larga
(`EXPLICACION_DEL_MOTIVO`) es la que se lee en la pantalla, con las palabras del
ticket. La primera no cambia sin una migración, la segunda se reescribe cuando
haga falta. Un `.title()` no convierte "sin resultados" en "el producto no está
en ese catálogo", y ese salto es el que hace que un hueco se pueda atender.

**Los cuatro motivos del ticket contra los ocho que existen.** Los cuatro están,
distintos entre sí, y ninguno se fusiona: `sin resultados`, `varios resultados`,
`el portal no contestó` y `la sesión caducó`. Lo que sí pasa es lo contrario de
una fusión: la frase *"el producto no está en ese catálogo"* la cubren **dos**
motivos —`sin resultados` (el portal no encontró nada) y `no empareja` (llegaron
filas y ninguna es este producto)—, y se mantienen separados a propósito porque
el segundo es el final ordinario de QuePharma (ADR 0002) y fundirlos escondería
cuán seguido ese portal no empareja.

**El esquema no se toca.** No hay columna ni motivo nuevo: los ocho motivos ya
existían con su `CHECK`, y todo lo de este ticket se calcula al leer. Por eso no
hay `sql/migraciones/0004-*`.

## Lo que quedó sin cerrar

**El conteo de arriba envejece al consultar un precio.** La respuesta de
`/api/renglon/{id}/precio` es de **un** renglón y no trae el conteo de la lista;
recalcularlo ahí necesitaría leer la lista entera por su id, y el
almacenamiento solo sabe leerla por fecha. Volver a pedir la lista está
descartado por un acuerdo más viejo que este ticket —*la lista se pide una sola
vez*, fijado por tres pruebas— porque dos lecturas en momentos distintos pueden
no coincidir. Así que el conteo **se marca como viejo y la pantalla lo dice**:
"este conteo es de antes de eso; recarga la página". Envejece hacia el lado
seguro —dice más huecos de los que quedan—, pero es un remiendo. Se cerraría
con un `leer_por_id` en `AlmacenamientoDelPedido`, y eso es otra decisión.
Descartar, devolver y ajustar sí lo traen recalculado, y sin una consulta más:
esas rutas cambiaron su lectura de un renglón por la de la lista entera.
