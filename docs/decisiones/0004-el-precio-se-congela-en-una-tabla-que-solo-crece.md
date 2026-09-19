# 0004 — El precio de proveedor se congela en una tabla que solo crece, y quien espera a Doyle es el servidor

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

## Contexto

El ticket 12 mete el primer precio real dentro de Continental: el encargado
pide la consulta de un renglón, Doyle va a los cuatro portales, y lo que vuelve
se guarda. El ADR 0002 ya decidió **qué** se compara y con qué regla —solo lo
que empareja por EAN, "sin dato" antes que una comparación mal emparejada—.
Falta decidir **dónde vive ese precio, de qué tipo es, quién espera los noventa
segundos, y qué pasa cuando se consulta dos veces.**

Cinco hechos delimitan el problema, y los cinco están medidos:

1. **Una búsqueda tarda.** Piso de ~9 s por proveedor (5.6 s de scroll de carga
   diferida más 3 s de cortesía) y techo de 60-90 s. Por eso Doyle devuelve un
   `job_id` y se le pregunta después.
2. **El precio llega como texto.** `doyle.py` lo deja así a propósito:
   convertirlo en el borde obligaría a inventar un `0.0` para el hueco.
   Verificado contra el Doyle real el 2026-09-19: Doyle ya normaliza
   (`"$ 208.97"` → `"208.97"`) y devuelve `"—"` cuando el portal no dijo nada.
3. **Doyle emite `buscando`, no `pendiente`.** El trabajo nace en `pendiente` y
   el hilo lo mueve a `buscando` en su primera línea; los ~9 s se pasan enteros
   ahí. Medido el 2026-09-19 sondeando una búsqueda real: once vueltas, las
   cuatro primeras con los cuatro proveedores en `buscando`.
4. **El mismo EAN salió a $86.05 en NADRO y $146.38 en LEVIC el mismo día**
   (ADR 0002). Un precio equivocado aquí es una compra equivocada.
5. **El rol `continental` no tiene `DELETE`** y no puede hacer DDL (ADR 0003).
   Agregar una columna cuesta una visita a atlas; agregar una tabla cuesta eso
   más volver a correr `crear_rol.sql`.

## Opciones consideradas

**Dónde vive el precio**

1. Columnas en `pedidos.renglon`, una tanda por proveedor.
2. Una tabla nueva en `pedidos`, con grano (renglón, proveedor).

**Qué pasa con la segunda consulta del mismo renglón**

A. `UNIQUE (renglón, proveedor)` y `UPDATE` (o `UPSERT`): una fila por
   proveedor, siempre la de hoy.
B. Sin `UNIQUE`: cada consulta agrega, y la comparación usa la más reciente.

**Quién espera a Doyle**

- α. Continental espera dentro de la petición HTTP.
- β. El navegador sondea a Doyle y le manda el resultado a Continental.
- γ. Continental sondea en un hilo y guarda el resultado; el navegador le
  pregunta a Continental.

## Decisión

**2 + B + γ.** Una tabla nueva, `pedidos.precio_de_proveedor`, con grano
(renglón, proveedor), que **solo crece**; el precio se convierte a
`numeric(12,2)` en Python antes de escribir la fila y el texto original se
guarda al lado; y quien espera a Doyle es un hilo de Continental, que escribe
el precio congelado en cuanto llega.

Toda fila sin precio lleva **motivo**, de un vocabulario cerrado de ocho
valores con su `CHECK`.

## Razones

**La tabla, y no columnas.** Cuatro proveedores por nueve datos son treinta y
seis columnas cuyo nombre lleva dentro el nombre de un proveedor. El día que
entre un quinto —o que QuePharma salga, que el ADR 0002 ya da por probable— hay
que alterar la tabla y el rol no puede. Y la pregunta del ticket 15, "contra
cuántos proveedores se comparó este renglón", sería un `CASE` de nueve columnas
en vez de un `count(*)`. El grano (renglón, proveedor) es el hecho: una visita a
un portal con una clave devuelve el precio y la existencia de ese producto ahí.

**Solo crece, y ésta es la mitad que más duele si se hace al revés.** Con
`UPDATE`, el caso que la rompe no es el raro sino el ordinario: se consulta a
las 8 y NADRO da $86.05; a las 9 alguien vuelve a consultar, la sesión ya
caducó, y el $86.05 se convierte en un hueco. **Se habría perdido el dato por
intentar mejorarlo**, sin un solo error que ver — la falla silenciosa que la
regla 4 de `CLAUDE.md` prohíbe. Y es lo que hace cierta la frase del ticket: *un
pedido dice a qué precio se decidió, no a cómo está hoy*; con una fila por
proveedor, la cifra que el encargado vio al elegir desaparece en cuanto alguien
recarga los precios. Cuál vale hoy lo decide un `DISTINCT ON (renglon_id,
proveedor)` ordenado por `consultado_en DESC`, con su índice.

**`numeric` y `Decimal` de punta a punta, y la conversión en Python.** El dinero
en coma flotante deja de cuadrar contra la factura por centavos que nadie puede
explicar; es la lección que farmacia-data pagó al dejar que una librería
dedujera los tipos. Y la conversión no va en el SQL con un `::numeric` porque
`'1,234.50'::numeric` **truena** y un error de conversión aborta la transacción
entera: se perderían también los tres proveedores que sí contestaron bien. En
Python, un texto ilegible es una fila más con motivo `precio ilegible`. El
precio viaja al navegador **como cadena**, porque el JSON de JavaScript solo
tiene coma flotante y mandarlo como número lo metería ahí justo al salir.

**El cero está prohibido por restricción, no por costumbre** (`CHECK (precio >
0)`). Es el único número que aquí hace daño: gana toda comparación de "el más
barato" y dispara la compra equivocada. Un `"0.00"` que escriba un portal
tampoco es un regalo — es un portal que no supo decir cuánto cuesta.

**El motivo es una columna con vocabulario cerrado.** "NADRO no dio precio"
quiere decir cinco cosas y cada una se arregla distinto: la sesión caducada la
arregla el encargado en dos clics, el portal caído se reintenta, y "no está en
ese catálogo" no lo arregla nadie. Sin el motivo las cinco se ven iguales.
Cerrado y no texto libre porque el ticket 15 tiene que **contarlos**, y un
conteo sobre texto libre cuenta faltas de ortografía.

**Espera el servidor, y no la petición ni el navegador.** La opción α cuelga la
pantalla hasta minuto y medio —lo prohíbe el ticket— y pierde la consulta si
alguien recarga: el portal ya se visitó y hay que molestarlo otra vez. La β no
cuelga nada, pero convierte el precio congelado en *lo que el navegador dijo que
Doyle dijo*, y sigue perdiéndose al cerrar la pestaña, que es justo cuando el
encargado se va a atender a alguien. Con γ, cerrar la pestaña no pierde nada y
nada de lo que se guarda pasó por el navegador.

**Una consulta en vuelo bloquea la siguiente del mismo renglón.** Doyle abre
navegadores de verdad contra los portales con las credenciales del dueño: dos
clics nerviosos serían ocho visitas en lugar de cuatro. La decisión de no lanzar
se toma dentro del mismo candado que registra la nueva, porque comprobar fuera y
lanzar después tiene una carrera en medio. Lo que **no** se bloquea es una
segunda consulta después de que la primera terminó: eso es la historia 24 del
spec ("completar en la mañana los precios que faltan").

**El estado del renglón no entra al `WHERE` del `INSERT`,** al revés que en
descartar, cerrar o corregir la cantidad. Los estados van en el `WHERE` cuando
lo que se escribe es una **transición**, y una lectura de precio no lo es: es un
hecho del mundo en un instante. Si alguien descarta el renglón mientras Doyle
consulta, tirar la lectura no protege nada —nadie va a comprar un renglón
descartado— y sí pierde evidencia que vuelve a hacer falta si lo devuelven a
`abierto`. Quien mira el estado es la ruta, **antes** de molestar a los portales,
que es donde además puede explicarlo.

## Consecuencias

- **La tabla crece y nadie la poda.** Cuatro filas por renglón consultado, del
  orden de cientos al día en el peor caso, contra una base que hoy guarda ~460
  mil filas. Cuando estorbe, se archiva junto con el pedido sugerido que la
  originó, que es la unidad con la que se puede tirar sin perder el porqué.
- **La migración 0003 obliga a volver a correr `sql/crear_rol.sql`**, al revés
  que las 0001 y 0002: un `GRANT` no se puede dar sobre una tabla que no
  existía. Sin ese paso, el primer precio rebota en atlas con "permission denied
  for table precio_de_proveedor" — y lo hace dentro del hilo, así que la
  pantalla solo diría "no se pudo guardar". Las comprobaciones 4 y 6 de
  `verificar_rol.sql` lo cazan.
- **Hay estado en memoria del proceso.** Si Continental se reinicia a media
  consulta, la consulta se pierde; lo ya escrito, no. Es el mismo trato que
  Doyle hace con sus trabajos: lo que vale la pena conservar está en una tabla.
- **Si Doyle no contesta al pedir la búsqueda, no se guarda ninguna fila.** No
  se sabe siquiera a qué proveedores se iba a preguntar, y la lista de los
  cuatro sale del acuse. El motivo vive solo en el registro en memoria, así que
  **una recarga lo pierde** y el renglón se ve como "sin consultar". Es honesto
  —no se consultó— pero es menos información de la que se tenía un segundo
  antes. Anotado en `HANDOVER.md`.
- **Se otorga `UPDATE` sobre una tabla que nunca se actualiza.** Es la excepción
  al principio "otorga exactamente lo que el código ejercita" y va razonada en
  `crear_rol.sql`: un GRANT distinto por tabla convertiría la comprobación 6 del
  verificador en una lista de parejas que hay que mantener a mano.
- **Condición de revisión:** si el lote nocturno (ticket 18) hace que la tabla
  crezca un renglón por producto vendido **por noche** —y no solo cuando alguien
  aprieta un botón—, hay que volver a medir: con 3,429 artículos y cuatro
  proveedores serían ~13,700 filas por corrida, y ahí el "solo crece" deja de
  ser gratis y toca decidir el archivado, no improvisarlo.
