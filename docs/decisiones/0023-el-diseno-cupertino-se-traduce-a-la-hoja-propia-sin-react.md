# 0023 — El diseño Cupertino se traduce a la hoja propia, sin traer su librería

**Fecha:** 2026-09-30  ·  **Estado:** aceptada
**Complementa el ticket 28** (la pasada visual: tres archivos servidos tal cual)

## Contexto

El 2026-09-30 llegó un diseño nuevo de la pantalla entera, hecho en Claude
Design con el sistema **Cupertino UI** (`Continental.dc.html`): una barra
lateral con las secciones —"Pedido" con la lista del día y lo que viene en
camino; "Proveedores" con Buscar, Vigilancia y Sesiones; el estado abajo—, la
lista del día en **tres pasos** (revisar, repartir, capturar y enviar), un
**detalle del renglón** a la derecha, y la comparación de precios con una
columna por proveedor.

Cupertino UI se entrega como una librería de **React** (`_ds_bundle.js`, 23
componentes) más una hoja compilada. La pantalla de Continental es, desde el
ticket 28, tres archivos —HTML, CSS y JS— servidos tal cual desde `/static`, y
`tests/test_pasada_visual.py` fija por qué:

- sin cadena de compilación ni marco de trabajo (atlas no tiene Node, y un
  `package.json` es el primer paso de una cadena que hay que mantener);
- nada pedido afuera: ni fuentes ni librerías de un CDN, ni `@font-face`;
- los colores solo en las dos listas de `:root`, la oscura redefiniendo cada
  uno, para que el tema oscuro no deje un gris claro olvidado;
- ningún significado viaja solo en el color.

La hoja de Cupertino rompe tres de esas cuatro: usa `color-mix()` y colores
escritos fuera de `:root`, y carga Inter con `@font-face`.

## Opciones consideradas

1. **Traer la librería tal cual**: React y `_ds_bundle.js` en `/static`, y
   reescribir la pantalla como componentes.
2. **Traer solo su hoja** (`_ds_bundle.css`) como un segundo archivo de estilos
   y escribir el HTML con sus clases `cu-*`.
3. **Traducir el diseño a la hoja propia**: los mismos valores —colores,
   escala de letra, radios, sombras— escritos como variables del proyecto, y
   cada pieza del diseño (botón, insignia, control segmentado, panel) como
   reglas de `continental.css`.

## Decisión

La 3.

- **No a la 1**: React sin compilar se puede cargar como `<script>`, pero
  reescribir las 4,141 líneas de JavaScript que había (medido el 2026-09-30),
  que ya llevan sus pruebas de texto —que ninguna frase que afirma algo se
  componga en el navegador, que todo `fetch` pase por `respuestaDe`—, para
  cambiar cómo se ve sería pagar un riesgo alto por nada que el encargado
  note. Y mete dos dependencias, React y el bundle del diseño, que atlas
  tendría que servir y alguien actualizar.
- **No a la 2**: la hoja de Cupertino no pasa las guardias de colores ni la de
  fuentes, y mezclar sus nombres (`--cu-label-secondary`) con los del proyecto
  (`--tenue`) dejaría dos vocabularios para lo mismo.
- **La 3** deja el diseño como **referencia de valores**, no como código: la
  escala tipográfica de Apple, los radios, el lienzo gris con tarjetas
  blancas, la píldora de los botones. El JavaScript conserva su estructura y
  sus funciones; lo que cambia es dónde pinta y con qué clases.

### Lo que el diseño no traía y se decidió aquí

- **Los colores de texto no son los del diseño.** El naranja del sistema
  (`#ff9500`) sobre blanco da 2.1:1 de contraste y el verde 2.2:1: en una
  pantalla de mostrador con reflejo no se leen. Se usan las variantes de alto
  contraste que Apple publica para esos mismos tonos (`--aviso: #c93400`,
  `--ok: #248a3d`), y los tonos vivos se quedan para puntos, barras y fondos.
- **La letra es la del sistema.** El diseño pide Inter; se usa si la máquina
  la tiene, y si no Segoe UI en la torre. Cargarla sería el primer archivo
  pedido afuera de los tres.
- **El teléfono sigue funcionando.** El diseño fija un ancho mínimo de 1024 px;
  la pantalla de hoy se mide a 375 px desde el ticket 28. Por debajo de
  1280 px el detalle del renglón flota encima en vez de apretar la tabla; por
  debajo de 1024 px la barra lateral se vuelve una franja arriba; por debajo
  de 830 px la tabla se apila en tarjetas.
- **De las tres comparaciones del diseño (rejilla, solo el ganador, escala)
  se construyó la rejilla**, la que el diseño trae por omisión y la única que
  enseña los cuatro precios en la fila —que es lo que pidió el ticket 14—. El
  selector de variante del diseño era solo para elegir.
- **Los encabezados cortos del diseño** ("Hay", "Alcanza", "Pedir") se ven;
  el nombre del glosario ("Existencia", "Días de cobertura", "Cantidad a
  pedir") va para el lector de pantalla y en el `title`.
- **El filtro de texto de la lista es de la persona, no del sistema**: lo que
  esconde lo esconde porque alguien tecleó algo, y se dice cuántos quedan a la
  vista. "Nada se filtra" (ADR 0002) habla de lo que el sistema propone.

## Consecuencias

- Las guardias del ticket 28 siguen en pie; cinco cambiaron de forma, cada una
  con su porqué escrito en la prueba: los rótulos de las pestañas, el fondo
  del encabezado de la tabla (ahora el de la tarjeta), el ganador distinguido
  por negrita y fondo, el corte en que la tabla se apila (52rem y no 76rem,
  porque la tabla nueva mide ~800 px y no ~1,200) y una lista explícita de los
  colores que valen lo mismo en los dos temas (hoy uno: el blanco sobre el
  acento). Una sexta, en `test_parcial`, se anclaba en el primer
  `const titular` del archivo y pasaba por casualidad; ahora se ancla en
  `pintarParticion`.
- Dos guardias que buscan los puertos de Doyle y Marlowe como texto ("8383",
  "8484") chocaron con dos colores del diseño (`#38383a`, `#48484a`). El
  primero no se usaba y se quitó; el segundo es el pulgar del control
  segmentado en oscuro, y se cambió por `#636366` —el `--cu-gray-2` oscuro
  del mismo sistema de diseño—. La guardia busca el número como texto en
  toda la pantalla, así que un color nuevo puede volver a chocar con ella.
- El detalle del renglón enseña el **anaquel** que dibuja el diseño, y viaja
  **en el renglón** (`"anaquel"` en el JSON de la lista) desde la migración
  0017: se guarda junto a la clasificación, congelado como ella, y no se relee
  del catálogo al responder. `""` es "sin anaquel que enseñar" y `null` es "no
  se sabe" (renglones guardados antes de la 0017).
- "Recibido — hoy y ayer" del diseño no tiene una lectura que lo alimente:
  "En camino" enseña lo que llegó de menos, con su corrección, y lo recibido
  de cada lista sigue marcado en su renglón.

## Enmienda del 2026-10-05 — la segunda versión del diseño, y la apariencia

Llegó una segunda versión del mismo diseño (`Continental Cupertino.dc.html`, en
el mismo proyecto de Claude Design). Se tradujo igual que la primera —a la hoja
y al JavaScript de siempre, sin React ni la hoja de Cupertino—, así que la
decisión de arriba sigue en pie. Lo que cambia es el acomodo, y cuatro cosas
que el dueño decidió ese día:

1. **A quién se le pide se elige en el detalle del renglón**, tocando uno de
   los cuatro proveedores, y no en un desplegable de cada fila. La fila solo lo
   dice, en una píldora con el punto del proveedor. Cuesta un clic más por
   renglón; a cambio la elección se hace donde se ven los cuatro precios con
   sus motivos. Tocar el que ya era una decisión no se manda (movería la firma
   de algo ya decidido); tocar la sugerencia sí, porque es confirmarla.
2. **Los avisos van plegados siempre, y se abren solos si hay una falla.** Si
   alguien los pliega con una falla a la vista, se quedan plegados hasta que
   aparezca una falla que no estaba: plegar no es "no me avises de las que
   vengan".
3. **Lo que salió bien de un clic va en un aviso pasajero** que se va solo,
   abajo al centro. **Lo que salió mal no**: se queda escrito en su nota hasta
   el siguiente clic. Un "no se pudo" que se borra a los tres segundos sería
   una falla silenciosa con un paso de más (regla 4). El aviso dura más cuanto
   más larga es la frase, nunca menos de cuatro segundos: la del envío dice
   que Continental no le mandó nada al proveedor, y eso hay que alcanzarlo a
   leer.
4. **Apariencia Auto, Claro y Oscuro**, abajo de la barra lateral, como en
   Marlowe. Se recuerda por navegador (`localStorage`), igual que la vista de
   la lista.

Y lo que se decidió al traducir:

- **La cantidad también se corrige en el detalle**, con − y + y el campo en
  medio, porque así la dibuja el diseño. En la fila es una cifra que solo se
  lee, con "ajustada" o "confirmada" debajo si alguien la decidió. Los botones
  solo le suman o le restan al campo y lo mandan: hay un solo camino de
  escritura.
- **El detalle flota siempre encima**, a la derecha, y se abre al tocar un
  renglón. Ya no hay corte de 1280 px que lo ponga al lado de la tabla.
- **Se desplaza la página entera**, con la barra lateral pegada, en vez de
  cada sección por dentro. El encabezado de la tabla sigue pegado arriba, ahora
  de la ventana; por eso la tarjeta de la tabla no lleva `overflow`.
- **La lista oscura vive dos veces en la hoja**: dentro de la media query
  (para "Auto", detenida por `data-tema="claro"`) y en `:root[data-tema="oscuro"]`
  (para "Oscuro"). CSS no deja decir "si el sistema es oscuro o si alguien
  eligió oscuro" en un solo bloque. Se descartó `light-dark()`, que lo diría en
  una línea por color, porque es de 2024 y sin ella la pantalla entera se queda
  sin color en un navegador viejo. `test_pasada_visual` exige que las dos
  copias sean idénticas, valor por valor.
- **Los íconos de la barra lateral son SVG en línea**, después del rótulo en el
  HTML y puestos delante por la hoja: el rótulo sigue siendo lo primero que se
  lee de cada pestaña. Ningún archivo nuevo, nada pedido afuera.
- **Los cuatro proveedores llevan un punto de color** (índigo, verde azulado,
  gris y morado, por su lugar en la lista del servidor), siempre junto a su
  nombre.
- **La letra sigue siendo la del sistema** y los naranjas y verdes de texto los
  de alto contraste, como decidió este ADR. El diseño insiste en Inter.
- **La clase ABC que el diseño dibuja junto a la clave no se enseña**: no viaja
  en el renglón. Ponerla es un cambio del servidor, no de la pantalla.
