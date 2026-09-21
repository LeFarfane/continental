# 0016 — Cerrar avisa lo que se pierde, y reabrir vale mientras nadie haya usado el corte

**Fecha:** 2026-09-21  ·  **Estado:** aceptada (por el dueño, 2026-09-21)

## Contexto

La revisión de código de los tickets 24 y 27 encontró un riesgo que ningún
ticket había nombrado:

> Que ninguna venta se proponga dos veces ni se pierda se sostiene con
> `_LO_YA_PEDIDO`: una lista posterior **cerrada** que contenía el producto
> cuenta como "ya atendida" aunque ahí el renglón siguiera `abierto` o
> `descartado`. Si se cerró sin pedirlo, **las piezas que faltaron de un
> parcial —y las ventas retenidas mientras viajaba— se pierden**, y nada avisa.

No es un error de `_LO_YA_PEDIDO`. Es lo que **cerrar** quiere decir desde el
ticket 09: *ya se pidió lo que se iba a pedir*. Cerrar mueve el corte, y la
siguiente lista acumula desde el día siguiente. Lo que la lista cerrada traía y
nadie pidió se da por atendido: con las ventas de su propia ventana eso es una
decisión del encargado (no pedir algo que se vendió), pero **con lo que venía de
otra lista** —lo que faltó de un parcial (ADR 0015), lo vendido mientras un
pedido viajaba (ADR 0012), lo de un cancelado (ADR 0013)— es la segunda y última
oportunidad de esas piezas, y se va sin que la pantalla lo diga.

El dueño decidió dos cosas:

1. **Una ventana de confirmación antes de cerrar**, que diga qué se va a dar por
   atendido sin haberse pedido. Avisa; no prohíbe.
2. **Un botón de deshacer** que solo funcione para la lista directamente
   anterior.

La primera no tiene decisión de arquitectura: es un cálculo puro sobre la lista
guardada (`cierre.al_cerrar`) y una ruta de lectura. La segunda sí, y es la de
este ADR: cerrar movió el corte, y **alguien pudo haber armado otra lista sobre
ese corte**.

## Qué se rompe si se reabre sin cuidado

Tres hechos, todos de tickets anteriores:

- **El corte lo usa quien arma la lista siguiente** (ticket 09):
  `corte_del_ultimo_cerrado` → `ventana_de_reposicion`. La lista de mañana —la
  que arma el lote de las 22:00, o la pantalla al abrirse con ventas nuevas—
  empieza al día siguiente del `hasta` de la cerrada, y **se guarda con esa
  ventana**: lo que se muestra es lo guardado.
- **La memoria de lo ya pedido también lo usa** (ADR 0012): al armar la
  siguiente, un renglón recibido cuyo producto está en la cerrada se da por
  atendido y no vuelve. Lo que faltó viaja en el renglón de la cerrada, no en el
  de la siguiente.
- **Una lista abierta de un día anterior se vence al abrir el día**
  (`vencer_las_de_dias_anteriores`, en la pantalla y en el lote), y `vencido` no
  se modifica.

Con la lista siguiente ya armada, reabrir la cerrada deja **dos listas abiertas
con ventanas que se tocan**: la de ayer `[a, h]` y la de hoy `[h+1, hoy]`. No se
enciman —ninguna venta se propone dos veces— pero la de ayer **ya no se puede
trabajar**: la primera carga de la pantalla la vence, porque su día pasó. Y
vencida, lo que tenía sin pedir tampoco vuelve: el corte que manda es el de la
siguiente en cuanto ésta se cierre. El botón habría hecho algo que no sirve para
lo que se apretó, y diría que sí.

## Opciones consideradas

1. **Reabrir cualquier cerrada, sin más condición.** Lo de arriba: dos listas
   abiertas, la vieja se vence al primer clic, y nadie sabe qué pasó.
2. **Reabrir la anterior y rehacer la siguiente**: volver a armar la lista de
   hoy con el corte de antes. La de hoy puede tener descartes, cantidades
   corregidas, proveedores elegidos, un pedido ya enviado; rehacerla es pisar
   decisiones firmadas por otra persona, y el rol no puede borrar renglones
   (regla 6).
3. **Reabrir la anterior y pasar lo perdido a la de hoy**: agregarle a la lista
   de hoy los renglones que la cerrada tenía sin pedir. Es otra función
   —"recuperar"—, choca con `ux_renglon_producto` cuando el producto ya está hoy
   (habría que sumar cantidades y ventanas de dos listas en un solo renglón, que
   es justo lo que la reposición 1 a 1 no deja verificar), y no es lo que el
   dueño pidió.
4. **Una ventana de tiempo**: se puede deshacer durante N minutos. El reloj no
   mide lo que importa. Lo que decide si reabrir es seguro es **si alguien ya
   armó algo sobre ese corte**, y eso puede pasar a los cinco minutos (alguien
   abre la pantalla después de la cadena de las 20:30) o no pasar en todo un
   domingo.
5. **Prohibir cerrar si algo se perdería.** El dueño dijo avisar, no prohibir:
   hay días en que se decide no pedir lo que faltó (el proveedor ya no lo
   surte, llegó por otra vía).
6. **Reabrir solo mientras ninguna lista se haya armado después de ella.**
   *(elegida)*

## Decisión

**La sexta: se reabre solo la lista cerrada más reciente del negocio, mientras
no exista ninguna lista de un día posterior.** En una frase para el mostrador:
*se puede deshacer el cierre hasta que se arme la lista siguiente.*

Es **una sola regla**, y la escribe **una sola cadena de SQL**
(`almacenamiento._NINGUNA_LISTA_DESPUES`) que usan las dos sentencias que la
necesitan:

- `_REABRIR` — el `UPDATE` que la hace cumplir:
  `estado = 'cerrado'` **y** `not exists` una lista del mismo negocio con
  `fecha_del_pedido` mayor. Cero filas es "no se pudo", y la ruta lee la lista
  para decir por qué.
- `_SE_PUEDE_REABRIR` — la lectura con la que la pantalla decide si pinta el
  botón. **Es comodidad, no la garantía**: entre que se pinta y que se aprieta,
  otra pestaña —o el lote— puede armar la siguiente, y el `WHERE` contesta cero
  filas.

El doble (`AlmacenamientoFalso`) repite la misma condición con una sola función
(`_ninguna_lista_despues`), usada por sus dos métodos.

**"Directamente anterior" quiere decir eso**: la última lista que existe. En
cuanto se arma otra, la cerrada deja de ser la última y ya no se reabre.
"Posterior" es por `fecha_del_pedido` y no por `armado_en`: el día de la lista
sale del dato (`max(fecha)`), y dos listas del mismo negocio no comparten día
(`ux_pedido_sugerido_dia`).

**Reabrir es `cerrado → abierto`, firmado**: `reabierto_por` (el correo de
Access: firma, nunca permiso, regla 3) y `reabierto_en` (`now()` de la base,
como `cerrado_en`). `cerrado_en` vuelve a `NULL` porque
`ck_pedido_sugerido_cierre` lo exige; la hora del cierre deshecho queda en la
bitácora. Si la lista se vuelve a cerrar, `cerrado_en` es la del segundo cierre
y la firma de la reapertura se queda: dice que hubo una.

**`vencido` no se reabre**: su día pasó sin que nadie la cerrara, y el corte
nunca se movió por ella —sus ventas ya se arrastran a la lista que siguió
(ticket 09)—. Reabrirla sería el caso de la opción 1.

## Lo que reabrir NO deshace, dicho

Reabrir devuelve **el estado de la lista**, nada más:

- **Un pedido que se envió** (ADR 0009) sigue `enviado`, y sus renglones siguen
  `en tránsito`. Lo que se capturó en un portal no se descaptura con un clic, y
  reabrir no es "desenviar" por la puerta de atrás (ADR 0013).
- **Lo que se recibió** sigue recibido, con su firma y sus piezas.
- **Lo cancelado** sigue cancelado.
- **Lo descartado** sigue descartado; en la lista reabierta se puede devolver a
  la lista con el botón de siempre, porque vuelve a estar `abierta`.

Lo que **sí** cambia, porque cuelga del estado y no de un renglón:

- **El corte retrocede** mientras la lista siga abierta: la lista cerrada
  anterior vuelve a ser el corte. Como no hay ninguna lista posterior, nadie lo
  lee hasta que se arme la siguiente, y para entonces la reabierta está cerrada
  otra vez (el corte vuelve) o se venció (y sus días se arrastran, como con
  cualquier lista que nadie cerró).
- **Lo que la cerrada "atendía" deja de estar atendido** (`_LO_YA_PEDIDO` mira
  `s2.estado = 'cerrado'`): lo que faltó y la lista traía sin pedir vuelve a
  ser memoria para la siguiente, y `_CORREGIR_LO_RECIBIDO` vuelve a dejar
  corregir la cifra de un parcial que sólo esa lista atendía. Las dos cosas son
  lo correcto: una lista abierta no ha pedido nada.

## Los números (`tests/test_cierre.py`)

**Cerrar por error y reabrir a tiempo.** Lunes se venden 10 del producto 1 y se
piden 10. Martes 3, miércoles 2 (las dos listas se cierran; viene en camino).
Jueves llegan 6 —faltan 4— y se vende 1: la lista del jueves trae **3 + 2 + 1 =
6 vendidas mientras venía + 4 que faltaron = 10**. La confirmación lo enseña:
*10 piezas sin pedir, trae 4 que faltaron y lo vendido desde el martes 15*. Se
cierra igual —por error—. Nadie ha armado nada: **se reabre**, se piden las 10,
se cierra. El viernes llegan las 10 y se vende 1: la del viernes propone **1**.
Vendidas 17; repuesto 6 + 10 + 1 = **17**.

**Demasiado tarde.** Lo mismo, pero antes de reabrir se arma la del viernes
(se vendió 1): trae **1**, empezando donde terminó la del jueves. Reabrir la del
jueves contesta 409 —*después de cerrarla ya se armó la lista siguiente*— y la
del jueves sigue cerrada. Las 10 se perdieron, que es exactamente lo que la
confirmación avisó antes de cerrar.

**El borde: la cadena ya trajo ventas y nadie ha abierto el día.** Jueves
cerrado por error; a las 20:30 entra la venta del viernes (1) pero nadie ha
cargado la pantalla ni corrió el lote. La del jueves sigue siendo la última
lista, así que **se reabre** —es el caso de una pestaña que se quedó abierta—.
La siguiente carga la vence (su día pasó) y arma la del viernes desde el corte
del miércoles: el producto 1 vuelve con **3 + 2 + 1 + 1 = 7 vendidas + 4 que
faltaron = 11 = las 10 del jueves + 1 del viernes**. Ninguna perdida y ninguna
dos veces: es lo que ya pasa con cualquier lista que nadie cerró (ticket 09).

## Razones

### Por qué la regla es "ninguna lista después" y no "la de hoy"

La condición que hace segura la reapertura es que **nadie haya leído el corte
que el cierre escribió**. Quien lo lee es quien arma una lista; sin lista
posterior no lo leyó nadie. "La lista de hoy" (`fecha_del_pedido = max(fecha)`)
sería una segunda condición —y la ruta de reabrir tendría que leer el almacén
para saber qué día es—, y la única diferencia con la elegida es el borde de
arriba, que se probó seguro: la lista reabierta se vence como cualquier otra
que nadie cerró, y sus días vuelven.

### Por qué en el `WHERE` y no en un `if`

Dos pestañas del mostrador, o una pestaña y el lote de las 22:00. Un `if` en
Python que mira si hay una lista posterior y después hace el `UPDATE` tiene una
carrera entre los dos pasos. La condición dentro del `UPDATE` se evalúa sobre la
fila que se va a cambiar, en el mismo instante.

**La carrera que queda, medida y dicha.** Con `READ COMMITTED`, el `not exists`
no ve una lista posterior **que se está insertando y todavía no confirma**. Si
alguien reabre en el mismo segundo en que otra pestaña arma la siguiente —con
el corte de la cerrada, leído un instante antes—, quedan la reabierta y la
siguiente con ventanas contiguas. No se propone nada dos veces (las ventanas no
se enciman, y la memoria de la siguiente se armó con la reabierta cerrada), y la
primera carga vence la reabierta: lo que tenía sin pedir se pierde, que es
**lo mismo que habría pasado sin reabrir**. Cerrar esa ventana de milisegundos
pedía un candado compartido con `abrir_el_dia`, que es la sentencia más
delicada del módulo; no se paga.

### Por qué el botón se decide con una lectura y no "si está cerrada"

Porque la pantalla puede tener una lista cerrada que ya no es la última: la
respuesta de cerrar desde una pestaña vieja, o un almacén al que le quitaron
días. Un botón que siempre contesta 409 es un botón muerto. La lectura cuesta
un `exists` sobre una tabla de una fila por día, y solo se hace con la lista
cerrada. Si falla, el botón no se pinta y se dice que no se pudo saber, con qué
hacer (regla 4).

### Por qué la confirmación es una ruta aparte y no viaja con la lista

Porque tiene que decir **lo que hay en el momento de cerrar**, no lo que había
al cargar: descartar sustituye un renglón en la pantalla sin reenviar la lista,
y otra pestaña pudo haber enviado un pedido. `GET
/api/pedido-sugerido/{id}/al-cerrar` lee la lista por su id y devuelve el
resumen hecho en Python —cuántos renglones quedan sin pedir, cuántos en un
borrador sin enviar, y cuáles traen algo de otro pedido, con sus piezas y su
frase—. La pantalla solo lo pinta en un `<dialog>`. El acuerdo de "la lista se
pide una sola vez" (hilo abierto 2) sigue en pie: esto no es la lista, es la
pregunta de un clic.

### Por qué la migración, si cerrar tampoco guarda quién

Cerrar no guarda quién porque el ticket 08 no lo pidió y nadie lo consulta.
Reabrir es otra cosa: es **deshacer una decisión**, y "¿quién la reabrió?" es la
pregunta que alguien va a hacer cuando una lista diga cerrada a las 14:00 y
abierta a las 14:05. La firma va en la fila, pareada, como las otras seis del
esquema.

## Consecuencias

- **Migración 0012** (`sql/migraciones/0012-reabrir-la-lista-cerrada.sql`) y lo
  mismo en `sql/crear_tablas.sql`: dos columnas en `pedido_sugerido`
  (`reabierto_por text`, `reabierto_en timestamptz`), **las dos admiten nulos y
  sin `DEFAULT`**, y dos CHECK (`ck_pedido_sugerido_reabierto_por`,
  `ck_pedido_sugerido_reapertura`: las dos o ninguna). No crea tabla:
  **`crear_rol.sql` no se vuelve a correr**. `verificar_rol.sql` gana la 38.
- **No rompe el código viejo de atlas.** Ninguna sentencia de antes nombra las
  columnas; las filas existentes y las que inserte el código viejo quedan en
  `NULL`, que los dos CHECK aceptan; `_CERRAR` y `_VENCER` viejos no tocan la
  firma, y el CHECK pareado no mira el estado. Se puede correr antes de
  desplegar sin que el servicio de hoy lo note.
- **Va ANTES de desplegar el código nuevo**: `_LEER_LISTA`, `_LEER_LISTA_POR_ID`,
  `_INSERTAR_LISTA` y `_CERRAR` devuelven las columnas nuevas. Sin la 0012 la
  lista del día no se lee.
- **Dos rutas**: `GET /api/pedido-sugerido/{id}/al-cerrar` (la confirmación) y
  `POST /api/pedido-sugerido/{id}/reabrir`. La pantalla pasa de 16 a 18
  `fetch('/api/`.
- **`CONTEXT.md` gana la transición** `cerrado → abierto` con su condición.
- **Lo que no protege**: la carrera de milisegundos de arriba, y lo que la
  persona decida cerrar a sabiendas después de leer el aviso.
- **Condición de revisión.** Si en un mes de uso se reabre seguido **después**
  del lote —o sea, se pide y ya no se puede—, la ventana del deshacer es
  demasiado corta para el mostrador, y lo que hace falta es la opción 3
  ("recuperar en la lista de hoy lo que se perdió"), no aflojar esta regla.
