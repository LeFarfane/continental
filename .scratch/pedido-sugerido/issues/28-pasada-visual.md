# 28: La pasada visual

**Qué construir:** hasta aquí la interfaz fue fea a propósito, para que cada rebanada se demostrara por comportamiento. Este ticket es donde el trabajo **es** lo visual: que una tabla de 40 renglones con cuatro precios cada uno se pueda leer sin cansarse, en la pantalla del mostrador y en un teléfono.

**Bloqueado por:** 22 · 23.

**Status:** ready-for-human

- [x] Hoja de estilos propia, con los colores declarados como variables en un solo lugar: nada de colores escritos a mano por toda la página.
- [x] Funciona en claro y en oscuro, con el fondo declarado explícitamente.
- [x] Densidad pensada para 40+ renglones: la fila tiene que ser compacta sin volverse ilegible, y los números alineados a la derecha.
- [x] La jerarquía visual dice de un vistazo lo que importa: urgencia, el proveedor más barato, el ahorro, y los huecos (sin dato, sin clasificar, en tránsito) distinguibles **sin depender solo del color**.
- [x] Sirve en el teléfono: la tabla no obliga a desplazamiento horizontal de la página.
- [x] Sin cadena de compilación y sin marco de trabajo: HTML, CSS y JavaScript servidos como archivos, igual que Doyle, Marlowe y Max.
- [x] Las pantallas siguen siendo las mismas: este ticket no cambia comportamiento ni agrega funciones.

## Qué lo cumple

La pantalla pasó de un archivo (`index.html`, 3,764 líneas) a **tres**, en
`src/continental/web/static/`: `index.html` (97, solo el marcado),
`continental.css` (744) y `continental.js` (3,127). Se sirven tal cual desde
`/static`, que `app.py` ya montaba.

1. **Hoja propia, colores en un solo lugar.** `continental.css`: las dos listas
   de `:root` (claro, línea 23; oscuro, línea 44) son el único lugar del archivo
   donde se escribe un color. Once variables: las ocho de antes más tres fondos
   suaves (`--ok-fondo`, `--mal-fondo`, `--aviso-fondo`) para las etiquetas
   con recuadro. Escritos a mano y no con `color-mix()`, que es de 2023. El
   JavaScript no pinta colores: pone clases.
2. **Claro y oscuro, fondo explícito.** El bloque oscuro redefine las once.
   `color-scheme: light` / `dark` en cada lista, para que el desplegable, los
   campos y las casillas sigan el tema (en oscuro salían recuadros claros).
   El fondo se declara en `html` **y** en `body` (líneas 77-78).
3. **Densidad.** `main` pasa de 52rem a 90rem (la tabla no cabía y se salía de
   `main` 110 px por la derecha); la prosa se queda en 62rem. Tabla a .875rem
   con relleno .4rem .5rem y `vertical-align: top` (línea 230). La celda de
   precios crece de 13rem a `clamp(25rem, 38vw, 36rem)` (línea 407) y cada
   proveedor es **una línea** de cuatro columnas —quién, cuánto, cuántas, y la
   marca / la diferencia / el motivo del hueco— (línea 422), en vez de colgar
   todo debajo. La cobertura y el ahorro van en la misma línea cuando caben, y
   "leído el…" junto a su botón. Encabezado pegado arriba al bajar
   (`thead th { position: sticky }`, línea 238). Con ratón los botones y
   campos se compactan (`@media (pointer: fine)`, línea 536); con el dedo se
   quedan en 2.2rem. Cifras a la derecha con `tabular-nums`: existencia y
   cobertura (610), cantidad (247), precio (428).
4. **Jerarquía sin solo el color.** Urgencia: "agotado" y el "0" en negrita más
   una **barra continua** al borde del renglón (`tr.agotado`, 620-621). El más
   barato: fondo, borde y la palabra (ya estaba). El ahorro: **etiqueta con
   recuadro**; lo que cuesta de más, recuadro **punteado**; sin ahorro que
   calcular, cursiva sin recuadro (502-507). Sin dato: cursiva y **subrayado
   punteado**, igual que el total que no se sabe (465). Las marcas del renglón
   llevan un **signo con forma propia** (655 y siguientes): `?` en círculo sin
   clasificar, `!` en cuadro para lo que hay que ir a mirar (fuera del
   catálogo, atrasado, ya viene en camino), `→` en tránsito, `✓` en círculo
   **punteado** probablemente recibido, `✓` continuo recibido, `↺` se dejó de
   esperar. En tránsito, además de atenuado, **barra punteada** (673); atrasado,
   **barra doble** y sin atenuar (677). Los signos se le ocultan al lector de
   pantalla (`content: "?" / ""`): la frase de al lado ya lo dice.
5. **Teléfono.** La tabla se apila por debajo de **76rem** (línea 681) y no
   solo por debajo de 34rem: medido, entre 34 y ~60rem la tabla de antes se
   salía de la página (a 768 px, `scrollWidth` 958). El bloque de 34rem (727)
   conserva lo que es solo del teléfono y devuelve la cuarta columna de cada
   proveedor a colgar debajo. `body { overflow-wrap: break-word }`.
6. **Sin compilar, sin marco.** Tres archivos que se sirven como están
   escritos, sin fuentes ni librerías de fuera. **La caché**: `app.py`
   (línea 3612 y siguientes) sirve `/` y `/static/*` con
   `Cache-Control: no-cache` —`EstaticosQueSeRevalidan`, un `StaticFiles` de
   cinco líneas—: el navegador pregunta cada vez y Starlette contesta 304 si
   el archivo no cambió. Sin eso, un despliegue podía dejar al mostrador con el
   HTML nuevo y el JavaScript de ayer. Se descartó versionar la URL
   (`continental.js?v=…`): obligaría a plantillar el HTML para ahorrarse tres
   304.
7. **Las mismas pantallas.** El JavaScript es el de antes, carácter por
   carácter (comparado con `diff` contra el `<script>` del 27), salvo esto:
   nueve `className` que ganan una clase más
   (`hueco-catalogo`, `sin-clasificar`/`abarrote`, `en-transito`, `atrasado`,
   `probable`, `llego`, `vuelve`, `hay-que-mirar`), dos `classList.add` del
   renglón (`agotado`, `atrasado`) que repiten banderas que ya llegaban del
   servidor, y el motivo de un hueco que se anexa a la línea de su proveedor
   (`linea.append(motivo)`) en vez de a la celda, más sus comentarios. Ni una
   ruta, ni un `fetch`,
   ni una frase, ni una condición de qué se pinta. El HTML es el mismo salvo
   las dos etiquetas que enlazan los archivos.

## Las pruebas

**Ninguna se debilitó, y la manera de asegurarlo es una sola:**
`tests/conftest.py` gana `pantalla_completa()` y `pantalla_servida(cliente)`,
que devuelven la pantalla **armada como antes** —la hoja dentro de un
`<style>` y el script dentro de un `<script>`, en el mismo sitio donde
estaban—. Medido: ese texto es **idéntico línea por línea** al `index.html`
del ticket 27 salvo la sangría del CSS. Y exigen exactamente una hoja y un
script: un archivo más pone rojas todas las guardias en vez de quedar fuera
de ellas sin avisar (comprobado metiendo un segundo `<link>`).

Los 20 archivos de pruebas que leían la pantalla pasaron a esos dos ayudantes,
sin tocar una sola afirmación: `test_cancelar`, `test_captura`, `test_comparacion`,
`test_envio`, `test_exportar`, `test_huecos`, `test_motivos`, `test_parcial`,
`test_pedidos`, `test_recepcion`, `test_transito` (del disco) y
`test_acumulacion`, `test_ajuste`, `test_clasificacion`, `test_descarte`,
`test_despliegue`, `test_guardado`, `test_precio`, `test_sugerido`,
`test_vistas` (por HTTP: ahora también piden la hoja y el script, y un 404 las
pone rojas).

`tests/test_pasada_visual.py`, **47 nuevas**: los tres archivos y nada de
fuera; los colores solo en `:root` (comprobado metiendo un `#fff`); el oscuro
redefine cada variable; el fondo en `html` y `body`; cifras a la derecha; 16
distinciones que no dependen solo del color, con la clase que el JavaScript
pone para cada una; el apilado bajo 76rem; `no-cache` en los tres y el 304; lo
servido es lo del disco; y **que ninguna prueba vuelva a leer `index.html` a
secas**.

1395 → **1442**, 0 saltadas, 5.20-5.26 s.

## Lo que se midió (2026-09-21, recorrido con los dobles, 47 renglones)

| | antes (ticket 27) | ahora |
|---|---|---|
| alto de la tabla a 1366 px | 19,306 px | 8,962 px |
| alto medio de un renglón a 1366 px | 409 px | 189 px |
| la tabla, dentro de `main` a 1366 px | se salía 110 px | sí |
| `scrollWidth` a 768 px (tableta) | 958 (desplaza) | 753 = ancho útil |
| `scrollWidth` a 375 px (teléfono), claro y oscuro | 375 | 375 = `innerWidth` |
| alto de la página en el teléfono | 30,210 px | 28,103 px |

## Lo aprendido

- **La prueba que "no está" es la que se debilita en silencio.** Separar
  archivos deja rojas las que buscan algo que se fue —ruidoso, bien—, pero las
  que afirman que el JavaScript *no* compone una frase pasarían por vacío
  leyendo un HTML sin JavaScript. Por eso el ayudante reconstruye la pantalla
  entera y no "HTML + JS" pegados en otro orden: las pruebas que cortan el
  texto entre dos funciones siguen cortando lo mismo.
- **La tabla ya se salía antes del teléfono.** El apilado estaba en 34rem; a
  768 px la página desplazaba 190 px, y en la computadora del mostrador la
  tabla rebasaba `main`. No lo vio nadie porque los recorridos anteriores
  miraron 375 px y escritorio ancho.
- **Lo que hacía alto un renglón era el motivo de cada hueco**, colgado en su
  propia línea bajo un proveedor de 13rem. Moverlo a una cuarta columna de la
  misma línea fue más que la mitad de la ganancia.
- **`pointer: coarse` y no el ancho** decide si algo se toca: la pantalla del
  mostrador puede ser táctil y ancha.
- **Chrome sin ventana no baja de ~500 px de ancho**: para capturar el teléfono
  hubo que meter la pantalla en un `iframe` de 375 px servido desde el mismo
  origen (un archivo temporal, borrado al terminar). El `scrollWidth` se midió
  aparte, con la emulación de teléfono del navegador integrado.

## Lo que quedó sin hacer, y por qué

- **Un botón para elegir tema** a mano (claro/oscuro sin importar el sistema).
  Sería una función nueva, y la séptima casilla lo prohíbe; hoy manda
  `prefers-color-scheme`.
- **Separar el JavaScript en módulos.** Son 3,127 líneas en un archivo; partirlo
  en varios pediría o `import` de módulos o varios `<script>` en orden, y
  cualquiera de los dos es una decisión de estructura que no pide este ticket.
  El ayudante de las pruebas exige un solo script a propósito, para que esa
  decisión se tome de frente.
- **El 304 de la portada.** `/static/*` revalida con 304; `/` (un `FileResponse`
  suelto) contesta 200 entero cada vez, porque ese `FileResponse` no mira
  `If-None-Match`. Son 6 KB: no vale una ruta más.

## Lo que se vio en el recorrido y NO se arregló (comportamiento, no es de este ticket)

- **El veredicto de un renglón sin ningún precio dice lo mismo dos veces**:
  *"Se consultó a 4 proveedores y ninguno dio precio."* y debajo *"ninguno de
  los proveedores dio precio"* (el `ganador.motivo`), antes de *"Sin ahorro que
  calcular…"*. Son dos frases de dos lugares (`veredicto` en el JavaScript y
  `comparacion.py`) que afirman lo mismo; quitar una es cambiar lo que se dice.
- **En el bloque de la recepción los botones se reparten a lo ancho**
  ("Confirmar que llegó" queda al centro, lejos de su renglón) porque cada
  `.accion` de `.en-camino` lleva `margin-left: auto`. Es de estilo, pero
  tocarlo cambia qué botón queda junto a qué frase en una pantalla donde se
  confirma una recepción: se deja para cuando alguien la mire con el encargado.
