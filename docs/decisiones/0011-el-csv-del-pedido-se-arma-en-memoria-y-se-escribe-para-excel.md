# 0011 — El CSV del pedido se arma en memoria cada vez, y se escribe para el Excel de México

**Fecha:** 2026-09-21  ·  **Estado:** aceptada

## Contexto

El ticket 23 pide el pedido en un archivo que se abra en Excel, se mande por
correo o se guarde. Es lo que hacían las Órdenes de Doyle, que el ADR 0002
retira al entrar este módulo: *"su exportación a CSV y el costo congelado se
reproducen aquí"*.

Cuatro hechos delimitan el problema, y los cuatro están medidos:

1. **Excel estropea un CSV sin avisar.** Marlowe lo sufrió el 2026-09-03
   (`Marlowe/tests/test_excel.py`): los códigos de barras pasaron a
   `7.50222E+12` y los SKU perdieron sus ceros a la izquierda. Aquí se volvió a
   medir el 2026-09-21 con el Excel 16 de la torre, abriendo archivos por COM y
   leyendo cada celda: `7501234567890` se ve `7.5012E+12`, y `0012345678905`
   pasa a **valer** `12345678905`, que es otro producto.
2. **La configuración regional de la torre es es-MX**: separador de lista `,`,
   decimal `.`, página de códigos 1252 (medido con `Get-Culture` ese mismo día).
3. **El servidor no sabe la hora de la farmacia.** El contenedor corre en UTC y
   la torre no tiene `tzdata`: `ZoneInfo("America/Mexico_City")` truena.
4. **No hay una lectura de un pedido por su id.** `AlmacenamientoDelPedido`
   sabe leer la lista (`leer_por_id`), sus pedidos (`pedidos_de_la_lista`) y
   sus precios (`precios_de_la_lista`). Una sentencia nueva no se puede probar
   contra Postgres desde la torre.

## Opciones consideradas

**Dónde vive el archivo**

1. Escribirlo en `data/export/` (que `.gitignore` ya tapaba desde el día uno) y
   servirlo desde ahí.
2. Armarlo en memoria en cada petición y servirlo; no se escribe nunca.
   *(elegida)*

**Cómo sobrevive la clave a Excel**

- A. Cruda, como número.
- B. Con un tabulador al frente.
- C. Con un apóstrofo al frente.
- D. Como fórmula de texto: `="7501234567890"`. *(elegida)*
- E. Un `.xlsx` con la columna en formato texto, en vez de un CSV.
- F. Como Marlowe: detectar el daño **al leer**.

**Separador y codificación**

- a. Punto y coma, coma decimal, con `sep=;` arriba (la receta para España).
- b. Coma, punto decimal, UTF-8 con BOM, sin `sep=`. *(elegida)*

**Por dónde se pide**

- i. `/api/pedido/{id}/csv`, con una lectura nueva del pedido por su id.
- ii. `/api/pedido-sugerido/{lista}/pedido/{id}/csv`, con las tres lecturas que
  ya existen. *(elegida)*

## Decisión

**2 + D + b + ii.** `continental/exportar.py` son funciones puras que reciben
el pedido guardado y su captura (`particion.lo_que_hay_que_capturar`, la misma
del ticket 22) y devuelven **bytes**; la ruta los sirve con
`Content-Disposition: attachment`. Nada se escribe en disco.

## Razones

### Por qué en memoria y no en `data/export/`

Un archivo escrito envejece: el de ayer seguiría diciendo `borrador` de un
pedido que hoy ya se envió, y nadie sabría cuál de los dos es el bueno. Además
habría que decidir quién lo borra, excluirlo de los respaldos y cuidar que no
entre a git — tres cosas que no hacen falta si no existe. Un pedido son decenas
de renglones: armarlo cuesta menos que leerlo de disco. Y lo que el ticket pide
es exactamente esto: *se regenera cuando se pida*.

### Por qué la fórmula de texto, y no las otras

- **A** es el daño mismo.
- **B y C** son las recetas que circulan, y las dos **se midieron y fallan**: en
  un CSV, Excel deja el tabulador como tabulador y el apóstrofo como apóstrofo,
  visibles en la celda y dentro de lo que se copie al buscador del portal.
- **E** es lo más correcto en abstracto y lo que más cuesta aquí: una librería
  nueva para escribir `.xlsx` en un servidor sin SSSE3 donde cada dependencia
  compilada hay que buscarla primero en `apt`, y un archivo que ya no se abre en
  el Bloc de notas ni se lee con `csv`. El ticket pide un CSV.
- **F** no aplica: Marlowe se defiende al leer porque su CSV es **de entrada**
  —lo edita una persona y el programa lo vuelve a leer—. Éste es **de salida**:
  Continental no lo lee nunca, así que no hay lectura donde cazar el daño.
- **D** fue la única que, medida, dejó la clave intacta, con sus ceros, como
  texto. Lo que cuesta: otro programa que no evalúe fórmulas (LibreOffice con su
  opción por omisión) enseña `="7501234567890"` — los dígitos siguen intactos, y
  el ruido es preferible al daño.

**La misma receta protege las descripciones** que empiezan con `=`, `+`, `-` o
`@`: medido, `-GUION` sale `#¿NOMBRE?` y `=1+1` sale `2` — Excel la evaluó. Se
aplica solo a las que lo necesitan, porque Excel limita a 255 caracteres la
cadena dentro de una fórmula; una más larga se protege con un espacio al frente
(también medido).

### Por qué coma y BOM, y no la receta de España

Porque la farmacia está en México y su Excel parte por coma y lee punto
decimal: `86.05` entra como número sin preguntar (medido: la celda es `Double`).
El BOM es lo que hace que los acentos se lean (medido: sin él, `ÁCIDO FÓLICO`
se ve `ÃCIDO FÃ“LICO`), y es lo mismo que Marlowe escribe en
`alta.escribir_csv`. `sep=,` sobra en es-MX y **hace que Excel ignore el
BOM** (medido: con BOM y `sep=,`, `ÁCIDO FÓLICO` vuelve a salir `ÃCIDO FÃ“LICO`).

### Por qué la ruta cuelga de la lista

Con el id de la lista alcanzan tres lecturas que ya existen y ya están probadas
contra los dobles, y que la pantalla ya hace en cada carga. Una sentencia nueva
—`leer_pedido(pedido_id)`— sería SQL que desde la torre solo se puede probar
como texto, a cambio de una URL un poco más corta. La pantalla recibe la URL
hecha (`pedido.csv`) y no la arma. Un pedido que no es de esa lista es un 404.

### Qué precio y qué total

El precio es el **de ese proveedor**, su última lectura congelada (ADR 0004) —
no el más barato de los cuatro—: es el de su carrito y el de su factura. Sale de
`lo_que_hay_que_capturar`, así que el archivo y la pantalla de captura no pueden
contar distinto. El total sale de `PedidoPorArmar.total_sin_iva` (ticket 20):
`sin saber` en cuanto una línea va sin precio, con el parcial dicho aparte. Si
el total guardado al armar el pedido —el del botón de enviar— no coincide con
la suma de ahora, el archivo **escribe los dos** con el porqué, en vez de elegir
uno en silencio.

### Por qué las horas van en UTC

El archivo no lleva la hora en que se generó: sería el reloj del servidor, y
haría distintos dos archivos idénticos. La única hora es la firma del envío, en
UTC **diciéndolo**; escribirla "local" exigiría una zona que el servidor no
tiene, y una hora sin zona son seis horas que nadie ve. La fecha del nombre es
la de la lista (`fecha_del_pedido`, anclada en `max(fecha)`), nunca la del
reloj: un pedido armado a las 22:30 de la farmacia ya es del día siguiente en
UTC.

## Consecuencias

- **No hay migración, ni tabla, ni permiso nuevo.** El despliegue de este
  ticket es solo código.
- **Se puede exportar un borrador y un enviado**, y el nombre y el primer
  renglón dicen cuál es (`pedido-2026-09-21-nadro-borrador.csv`): un borrador
  guardado en una carpeta no debe confundirse con lo que se capturó.
- **El archivo es para leerlo, no para volver a subirlo.** Si alguien lo abre en
  Excel y lo guarda, Excel lo reescribe a su manera: al abrirlo la fecha de la
  lista ya se enseña `05/03/2024` (medido), y qué escribe al guardar no se midió.
  Nada en Continental lo vuelve a leer; el día que algo lo lea, necesita la
  defensa de Marlowe al leer.
- **Medido en es-MX y solo en es-MX.** Qué hace un Excel con coma decimal con
  `86.05` no se midió, y lo probable es que no lo lea como número. Condición de revisión: si el archivo se va a
  abrir en una máquina con otra configuración regional.
- **`.gitignore` tapa `pedido-*.csv`**: el servidor no escribe nada, pero una
  persona puede guardar el archivo bajado dentro del repo, y lleva datos de
  compra de la farmacia.
