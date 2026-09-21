# 29: Estados vacíos y de falla en la interfaz

**Qué construir:** que la interfaz falle ruidoso. El manejo de errores del servidor está desde el primer commit; lo que falta es que la pantalla diga qué pasó, en lugar de mostrar el vacío, que se lee como una respuesta.

**Bloqueado por:** 28.

**Status:** ready-for-human

- [x] Si Doyle no responde, la lista **igual se ve** y dice que los precios no están disponibles, con el motivo. — `GET /api/doyle` (`web/app.py`, `doyle_contesta`), aparte de la lista y al mismo tiempo; la frase en `fallas.frase_de_doyle_caido`, el qué hacer en `fallas.que_hacer(DOYLE)`; la pantalla la pinta en `#pedido-doyle`, arriba de la tabla (`continental.js`, `revisarDoyle`).
- [x] Si el almacén no responde, lo dice con claridad. **Una lista vacía por falla nunca se puede leer como "hoy no se vendió nada".** — `_hueco` lleva `frase` (`fallas.frase_del_hueco`: *"Que no se vea ningún renglón no quiere decir que no se vendió nada"*) y `que_hacer`; el 500 genérico lleva `ok: false` y ya no cae en la rama de "sin ventas"; los precios y los pedidos que no se leen dejan un aviso (`avisos`) y no se pintan como "sin consultar" / "sin partir".
- [x] Un día sin ventas de verdad (el domingo, que la farmacia cierra) se distingue de un fallo de lectura. — `fallas.estado_de_las_ventas`, en `ventas` de cada carga: el servidor **afirma** qué tan recientes son las ventas que sí leyó, contra el horario de la cadena (lun-vie, 20:30; se cuenta desde las 22:00). Un lunes por la mañana la lista del viernes dice que es lo más reciente que puede haber y que los domingos la farmacia cierra; si falta un día que ya debía estar, dice que **no sabe por qué** (puede ser un feriado) y a quién avisarle. Ni una venta en el almacén es `ok: true` con su frase. Una lista vacía dice por qué, desde Python (`frase_de_la_lista_vacia`).
- [x] Ningún error del servidor manda detalles al navegador: el detalle va a la bitácora, al cliente un mensaje genérico. — `tests/test_fallas.py::test_ninguna_falla_de_ningun_borde_lleva_detalles_al_navegador` recorre `app.routes` (26 rutas) e inyecta la falla en cada llamada a cada borde; `test_una_excepcion_no_atrapada_sale_como_500_generico` hace lo mismo con el manejador global; `test_la_excepcion_solo_se_usa_para_su_tipo` lo vigila en el código. El 422 de validación de FastAPI (en inglés, repetía el cuerpo) también pasa a la forma de las fallas.
- [x] Cada estado de falla dice **qué puede hacer la persona**, o que no hay nada que hacer y a quién avisarle. — `fallas.que_hacer`, seis casos; el recorrido exige `que_hacer` en cada `ok: false` provocado por un borde. El contacto es `a_quien_avisar` en `config/continental.yml` ("a quien administra atlas"), no un nombre: el JavaScript decía "Avísale a Eddie".

## Inventario (2026-09-21, antes de cambiar nada)

Medido, no leído: cada ruta de `app.routes` se llamó con los dobles y un borde
caído a la vez (una excepción cuyo texto lleva `postgresql://usuario:SECRETO@host/db`),
y cada `fetch` de `continental.js` se leyó contra cinco preguntas. **Ninguna
respuesta del servidor llevó `SECRETO`**: la regla 5 ya se cumplía ruta por
ruta. Lo que faltaba era casi todo del lado de la pantalla.

Claves: **alm** = el almacén (`marts`) no contesta · **ped** = la base de
pedidos (`pedidos.*`) no contesta · **doy** = Doyle no contesta · **html** = la
respuesta no es JSON (un 502 del túnel) · **red** = `fetch` rechaza ·
**500** = excepción no atrapada (el manejador global). ✓ bien · ✗ mal · — no
aplica.

### Las rutas (25)

| Ruta | alm | ped | doy | Qué estaba mal |
|---|---|---|---|---|
| `GET /api/salud` | — | — | — | nada: no toca bordes |
| `GET /api/modulos` | — | — | ✓ | hueco con el tipo; sin frase de qué hacer |
| `GET /api/bordes` | ✓ | — | ✓ | nada (la pantalla no la usa) |
| `GET /api/pedido-sugerido` | ✓ hueco | ✓ hueco | ✗ | **Doyle caído no se dice en la lista** (solo abajo, en «Módulos»). **Los precios guardados que no se leen se vuelven `{}` en silencio**: la tabla entera dice «nadie lo consultó». **Los pedidos que no se leen se pintan como «sin partir»** y ofrecen partir otra vez. El hueco del almacén lo remataba el JS con «Avísale a Eddie» (un nombre escrito en el archivo sin pruebas). «Sin ventas» y «lista sin renglones» se componían en el JS, y la segunda («Ese día no se vendió nada que reponer») podía mentir: una lista vacía también sale cuando todo lo vendido ya viene en camino. Y **un lunes por la mañana la pantalla enseña la lista del viernes sin decir si eso es normal** |
| `POST …/cerrar`, `…/partir`, `…/completar` | — | ✓ | — | hueco con el tipo; sin qué hacer |
| `POST /api/renglon/{id}/descartar`, `devolver`, `cantidad`, `proveedor`, `capturado` | — | ✓ | — | ídem |
| `POST /api/pedido/{id}/enviar`, `cancelar` | — | ✓ | — | ídem |
| `POST …/devolver-atrasado` | — | ✓ | — | ídem; la config mala ya se decía |
| `POST …/recepcion/confirmar`, `rechazar`, `parcial`, `a-mano` | ✓ | ✓ | — | ídem |
| `GET …/pedido/{id}/csv` | — | ✓ 503 | — | ídem (se abre en otra pestaña, así que el JSON se lee) |
| `POST /api/renglon/{id}/precio` | — | ✓ | ✓ | ídem; Doyle caído termina la consulta con su motivo |
| `GET /api/renglon/{id}/precio` | — | ✗ | — | **los precios que no se leen salen como `[]`** y el sondeo borra de la fila los que ya estaban pintados |
| `POST /api/sesion/{p}/abrir`, `confirmar` | — | — | ✓ | ya decían qué hacer («mira si está encendido») |
| `GET /` y `/static/*` | — | — | — | nada |
| **500 no atrapado** | | | | ✓ genérico y a la bitácora, pero `{"error": …}` sin `ok`: ver `cargarPedido` abajo |
| **422 de validación de FastAPI** | | | | en inglés, con el cuerpo mandado de vuelta; sin `ok` ni `detalle` |

### Los `fetch` de la pantalla (17, más el enlace del CSV)

| `fetch` | html | red | 500 | Qué estaba mal |
|---|---|---|---|---|
| `cargarPedido` → `/api/pedido-sugerido` | ~ | ✓ | ✗✗ | **Un 500 caía en la rama de «sin ventas»: la pantalla decía «El almacén no tiene ni una venta registrada».** Es exactamente la casilla 2 |
| `cerrarLista` → `…/cerrar` | ✗ | ~ | ~ | `.json()` fuera del `try`: con HTML el botón se queda en «Cerrando…» para siempre |
| `moverRenglon` → descartar / devolver / cantidad / proveedor | ✗ | ~ | ~ | ídem: el control se queda apagado y no se dice nada |
| `partir`, `enviarPedido`, `tacharRenglon`, `consultarPrecio`, `completarLoQueFalta`, `abrirSesion`, `confirmarSesion`, `recibirORechazar`, `recibirAMano`, `cancelarPedido`, `devolverAtrasado` | ~ | ~ | ~ | con **red** o **html** decían «X se quedó como estaba», **que no se sabe**: un 524 del túnel o una conexión que se corta después de mandar la petición dejan la acción hecha. Con 500, «No se pudo …» sin qué hacer |
| `sondear` → `GET …/precio` | ~ | ✓ | ✗ | un 500 o `precios: []` por falla **borraban los precios pintados** |
| `cargar` → `/api/salud` | ~ | ✓ | ✗ | un 500 pintaba «Continental undefined» con el punto verde |
| `cargar` → `/api/modulos` | ~ | ✓ | ✓ | nada grave |

(~ = se atrapaba, pero la frase decía algo que no se sabe o no decía qué hacer.)

**Resumen:** 25 rutas y 17 `fetch`. En el servidor, 20 rutas ya estaban bien en
lo esencial —hueco con el tipo, nada del texto— y les faltaba decir qué hacer;
**3 tenían una falla silenciosa** (los precios y los pedidos de la carga, los
precios del sondeo) y **1 no decía lo que la casilla 1 pide** (Doyle, en la
lista). En la pantalla, **ninguno** de los 17 `fetch` distinguía «no hubo
respuesta» de «la respuesta no es de Continental», 2 se colgaban con HTML y 1
convertía un 500 en «no hay ventas».

## Qué se hizo

- **`src/continental/fallas.py`** (nuevo, puro): `que_hacer` (seis casos:
  al leer, al guardar, Doyle, configuración, servidor, petición),
  `falla_como_json`, las frases de los huecos de la carga, y
  `estado_de_las_ventas` / `ultimo_dia_que_ya_deberia_estar`. El reloj entra
  por argumento; no lee el YAML.
- **`web/app.py`**: `_que_hacer` en las 17 respuestas de falla de las rutas;
  `GET /api/doyle`; el manejador global con `ok: false`, `frase` y
  `que_hacer`; un manejador del 422; `ventas`, `avisos` y `lista_vacia` en la
  carga; los precios o pedidos que no se leen ya no se callan; y sin precios
  leídos no se calcula nada de lo que sale de ellos (conteo, faltantes,
  sesiones caducadas, el porqué de cada hueco). `GET …/precio` con la lectura
  caída manda `precios: null` y `precios_sin_leer` en vez de `[]`.
  `/api/salud` dice `a_quien_avisar`.
- **`continental.js`**: `respuestaDe` —toda respuesta pasa por ahí y ahí no se
  truena: red caída, HTML del túnel, JSON sin `ok`— y `SIN_RESPUESTA`, el único
  lugar con frases de falla escritas en el JavaScript. `notaDeFalla` pinta con
  rótulo ("Falla:" / "Ojo:") y "Qué hacer:" escritos, no solo con color.
  Ningún botón afirma ya "se quedó como estaba" sin respuesta: manda a mirar.
- **`index.html` / `continental.css`**: `#pedido-ventas`, `#pedido-doyle`,
  `#pedido-avisos`; `.nota.falla` con barra, `.rotulo`, `.que-hacer`.
- **`config/continental.yml` / `config.py`**: `a_quien_avisar`.

## Lo aprendido

- **El recorrido del navegador volvió a cazar lo que el suite no** (la novena
  vez: 14, 15, 21, 22, 24, 25, 26, 27, 29). Con los precios sin leer, el aviso
  de arriba decía la verdad y **todo lo de abajo seguía calculándose sobre
  `{}`**: "5 de 5 sin comparar", "nadie le ha pedido el precio" en cada
  renglón, y un botón "Completar los 5 que faltan" que habría mandado a
  visitar cuatro portales por renglón, por precios que sí existen. Ahora tiene
  prueba (`test_sin_los_precios_no_se_calcula_nada_de_lo_que_sale_de_ellos`).
  También cazó "Doyle no responde (no contestó (RuntimeError))" y un qué hacer
  que repetía la frase de encima.
- **El reloj entra, pero solo para una pregunta.** Distinguir "el domingo no
  hay ventas" de "no llegaron" no se puede con `max(fecha)` solo: hace falta
  saber qué hora es para saber qué *debería* haber llegado. La lista se sigue
  anclando en `max(fecha)`; el reloj (`_ahora`, el mismo borde que ya decía
  "pedido el martes") solo decide si lo que hay es lo más reciente posible.
- **Cero filas no es "cerraron"** (ya lo decía el YAML, medido el
  2026-09-20 con el 16 de septiembre). La frase de un día que falta no afirma
  la causa: dice las dos posibles y a quién avisarle si la farmacia sí abrió.
- **"Se quedó como estaba" era una afirmación sin respaldo.** Sin respuesta no
  se sabe si la petición llegó: un 524 del túnel pasa con el servidor todavía
  trabajando. Todas las acciones mandan a recargar y mirar.
- **Un recorrido que no duerme tiene que preparar a Doyle.** La primera
  versión de la prueba de la casilla 4 tardó 243 s: la consulta de precio,
  con una búsqueda pendiente, sondeaba con el `time.sleep` de verdad hasta su
  tope. Con Doyle contestando terminado a la primera, 26 rutas y 71 fallas
  inyectadas cuestan ~1 s.

## Lo que quedó sin hacer, y por qué

- **Con los precios sin leer, la vista previa de la partición sigue diciendo
  "todavía no hay a quién pedírselo" en cada renglón.** Es lo mismo que se
  calcula con `{}`; no se tocó porque el aviso de arriba ya dice "no partas ni
  envíes hasta que se lea" y cambiar la partición es otra superficie
  (`particion.py`). Si se ve en la operación, es el siguiente.
- **`pintarCorrida` sigue componiendo en el JavaScript "El lote no corrió
  sobre esta lista…"** (ticket 19). No es un estado de falla de este ticket
  —la fila de la corrida que falta es un dato, ADR 0007— y moverla a Python
  no cambia lo que dice.
- **Las respuestas 409 y 422 de negocio no llevan `que_hacer`**: su `detalle`
  ya dice qué hacer ("Vuelve a cargar la página para ver cómo quedó", "Ponle la
  clave en SICAR…"). El recorrido exige `que_hacer` solo en las fallas que
  provoca un borde.
- **`/api/modulos` sigue sin costura de pruebas** (usa `httpx` directo). El
  recorrido lo cubre sustituyendo `httpx.AsyncClient`; darle un `Depends` es
  trabajo aparte.
- **La hora de la cadena (20:30, contada desde las 22:00) es constante de
  `fallas.py`, no del YAML.** Es el horario de farmacia-data, no una
  preferencia de Continental; el día que cambie, cambia ahí y en
  `continental-lote.timer`.
