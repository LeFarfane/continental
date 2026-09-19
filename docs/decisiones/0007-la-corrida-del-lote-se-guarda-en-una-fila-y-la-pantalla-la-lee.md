# 0007 — La corrida del lote se guarda en **una fila por noche**, y es de ahí de donde la pantalla saca "el lote no llegó"

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

**Reabre, en su condición de disparo, la opción β del ADR 0006.** No lo
contradice: el ADR 0006 dejó escrito *"cuando la pantalla tenga que decir «el
lote de anoche consultó 210 de 380», eso es la tabla y no un `journalctl`
parseado"*. El ticket 19 es exactamente esa frase convertida en casilla.

## Contexto

La primera casilla del ticket 19 pide que **la pantalla distinga tres motivos**:
*el lote se cortó por tiempo*, *el portal no contestó*, *la sesión caducó*.

Los dos últimos ya están y no cuestan nada: son motivos de
`pedidos.precio_de_proveedor` desde el ticket 12 (`el portal no contestó`,
`la sesión caducó`), con su `CHECK`, su explicación para una persona y su
conteo.

**El primero no está, y no está a propósito.** El ticket 18 decidió que un
renglón al que el tope no alcanzó **no deja fila** (ADR 0006, opción B), por
dos razones que siguen valiendo íntegras:

1. **Habría que inventarse a qué proveedores se le iba a preguntar.** Esa
   lista sale del acuse de Doyle y a un renglón que no se consultó no hubo
   acuse que darle. Es el hilo abierto 3 de `HANDOVER.md`.
2. **Dispararía la condición de revisión del ADR 0004**: una noche que corte
   al 20% dejaría ~11,000 filas de puro hueco, cada una afirmando algo que no
   pasó.

Consecuencia, anotada como hilo abierto 10: **hoy la pantalla no distingue
"el lote no llegó a este renglón" de "nadie lo consultó nunca"**. Los dos se
ven como `no se le ha consultado el precio` (ticket 15), que es verdad y es
menos de lo que se sabe. La diferencia solo vive en el journal, o sea en un
`ssh`.

Seis hechos delimitan el problema:

1. **El vocabulario de motivos del precio es cerrado y tiene `CHECK`** (ocho
   valores, ADR 0004). Ampliarlo cuesta una migración, y `no alcanzó el
   tiempo` —el que haría falta— **ya existe**.
2. **`pedidos.precio_de_proveedor` solo crece y nadie la poda.** Su propio ADR
   puso la condición de revisión por número de filas.
3. **El lote ya calcula todo lo que haría falta.** `ResumenDeLaCorrida` tiene
   `en_la_lista`, `consultados`, `con_precio`, `sin_precio`, `sin_alcanzar`,
   `no_se_pudo`, `sin_clave`, `final` y el `Orden`. Hoy eso se imprime y se
   tira.
4. **El lote no hace un solo `UPDATE` de renglón**, y esa es una propiedad que
   el ticket 18 demuestra con una prueba que lo mata a la mitad: un lote
   muerto deja la lista *exactamente* como estaba más los precios que alcanzó.
5. **Una corrida por noche.** El timer es `OnCalendar=Mon-Fri 22:00`, sin
   `Persistent=true` (ADR 0006): como mucho cinco filas por semana.
6. **El rol `continental` no puede hacer DDL** (ADR 0003). Una tabla nueva
   cuesta `crear_tablas.sql`, una migración, **volver a correr
   `crear_rol.sql`**, `verificar_rol.sql` y `continental.verificar`.

## Opciones consideradas

**A. Escribir las filas de hueco de todos modos.** Cuatro filas con motivo
`no alcanzó el tiempo` por cada renglón que el tope no alcanzó, contra una
lista fija de proveedores.

**B. Guardar el resumen de la corrida** en una tabla nueva,
`pedidos.corrida_del_lote`, con grano **una fila por corrida**, y que la
pantalla la lea.

**C. Marcar el renglón en vez del par renglón-proveedor.** Una columna
—`ultimo_lote`, o un estado— en `pedidos.renglon`, o una fila por renglón no
alcanzado en una tabla aparte.

## Decisión

**La B.** Una tabla nueva, `pedidos.corrida_del_lote`, con **una fila por
corrida del lote** —no por renglón y no por proveedor—, que solo crece, y que
el lote escribe en el mismo `finally` donde ya imprime su resumen. La pantalla
la lee junto con la lista, en la misma respuesta, y de ahí sale la frase de
cada renglón sin lectura.

La regla de qué frase le toca a cada renglón es una **función pura**
(`faltantes.por_que_no_hay_lectura`), con su tabla de casos y sin Postgres.

## Razones

### Por qué la A no, aunque sea la que "se ve en la pantalla"

Las dos razones del ADR 0006 no han cambiado, y la primera es la que de verdad
la hunde: **escribir cuatro filas diciendo "le preguntamos a NADRO y no
contestó a tiempo" cuando a NADRO no se le preguntó es escribir un hecho que
no ocurrió.** Este repositorio prohíbe el cero inventado por la misma razón
(regla 4 de `CLAUDE.md`): un dato falso es peor que un hueco, porque se cuenta,
se compara y se cree.

Hay una tentación aritmética que conviene desactivar por escrito, porque
volverá: *"si el lote completo escribe 4×N filas igual, escribir las de los no
alcanzados no crece la tabla más allá de una noche buena"*. Es cierto como
suma y **no rescata la opción**: el problema no es el tamaño, es que esas filas
mienten. El tamaño es el segundo argumento, no el primero, y por eso no
importa que el número exacto del ADR 0006 (~11,000) haya salido del catálogo
entero y no de una lista de un día.

### Por qué la C no

Marcar el renglón cuesta menos filas que la A —una por renglón, no cuatro— y
tiene dos problemas que la B no tiene:

- **Si la marca vive en `pedidos.renglon`, el lote empieza a hacer `UPDATE` de
  renglones.** Hoy no hace ninguno, y eso no es una casualidad: es la
  propiedad que hace que un lote muerto a la mitad **no pueda dejar la lista
  peor que antes**, y hay una prueba escrita para demostrarlo. Cambiarla para
  ganar una frase en la pantalla es vender la garantía más fuerte del ticket
  18 por la casilla más barata del 19.
- **Si la marca vive en una tabla aparte, es una fila por renglón no
  alcanzado**: ~2,750 en la noche del 20% contra **una**. Y sigue sin poder
  contestar *"¿corrió el lote anoche?"*, que es la otra mitad del hilo abierto
  10 y la mitad del hilo 3 que quedó abierta — un renglón sin marca y un lote
  que no corrió se seguirían viendo igual.

### Por qué la B sí

**Porque el dato que falta es de la corrida, no del renglón.** La pregunta que
la pantalla no puede contestar hoy es *"¿corrió el lote sobre esta lista, y
cómo acabó?"*. Esa pregunta tiene **una** respuesta por noche, y guardarla
cuesta **una** fila. Derivar de ahí el estado de un renglón concreto es una
resta que se hace al leer y que no cuesta almacenamiento.

**Porque no se estrena un dato: se deja de tirar el que ya se calcula.** El
`ResumenDeLaCorrida` del ticket 18 ya tiene los ocho números. No hay dos
versiones de la misma noche —que es lo que el ADR 0006 temía de la opción γ—
porque **el resumen que se guarda es literalmente el mismo objeto que se
imprime**: sale de la misma `caja[0]` del `finally`.

**Porque cierra los dos hilos abiertos, y uno de ellos con SQL.** El 3
—*"¿corrió el lote anoche?" no se puede contestar con SQL*— pasa a ser un
`select` de una fila. El 10 —*la pantalla no distingue "no llegó" de "no
corrió"*— es exactamente la diferencia entre encontrar la fila y no
encontrarla.

**Porque el costo se paga una vez y está acotado.** Cinco filas por semana,
con una decena de columnas de enteros. La tabla del precio crece ~4×N por
noche; ésta crece 1.

### Lo que se renuncia, dicho con todas sus letras

**Precisión por renglón.** Lo que se guarda es *cuántos* quedaron sin
alcanzar, no *cuáles*. Así que para un renglón sin lectura la frase se deduce
del final de la corrida, y hay un caso en el que la deducción no es segura:
una noche en la que el tope cortó **y además** hubo renglones `no se pudo`
(Doyle caído a media corrida). Ahí, de un renglón concreto sin lectura, no se
puede afirmar cuál de los dos le tocó.

No se tapa: `por_que_no_hay_lectura` devuelve `seguro=False` en ese caso y la
pantalla escribe *"probablemente"* con el otro número al lado. Decir
"probablemente" es más barato que guardar 2,750 ids para tener razón en un
caso que además avisa de sí mismo —una noche con `no se pudo > 0` es una noche
con Doyle caído, que es ruidosa por su cuenta—.

**"Cuáles" se puede agregar después sin tocar nada de esto**: sería una
segunda tabla de detalle colgada de `corrida_del_lote_id`, y la función pura
ya tiene el sitio donde dejar de adivinar. **Condición de disparo:** si el
`seguro=False` aparece dos noches seguidas, o si el encargado pregunta por un
renglón concreto y la respuesta tiene que ser exacta.

**Una corrida que muere sin poder escribir en Postgres no deja fila.** Si lo
que tumbó el lote fue el propio almacén, la tabla no se entera. El journal sí
—por eso sigue siendo la bitácora del relato, y esto no lo sustituye— y la
pantalla lo ve como "el lote no corrió", que en ese caso dice de menos. Es el
mismo trato que el ADR 0006 le dio a la opción α y la razón por la que **las
dos siguen existiendo**: un `journal` no necesita que Postgres esté vivo.

## Consecuencias

- **El esquema `pedidos` pasa de cuatro tablas a cinco**, y eso cuesta el
  precio completo de una tabla en este repo: `sql/crear_tablas.sql`,
  `sql/migraciones/0004-*`, **volver a correr `sql/crear_rol.sql`** —un GRANT
  no se puede dar sobre una tabla que no existía, y es el mismo olvido que la
  migración 0003 documentó—, `sql/verificar_rol.sql` y
  `src/continental/verificar.py`. La lista de tablas de `verificar.py` sale de
  parsear `crear_rol.sql`, así que la quinta entra sola en cuanto el GRANT
  está escrito.
- **El lote escribe en una segunda tabla, y esa escritura no puede tumbarlo.**
  Va en el `finally`, después de imprimir el resumen, envuelta en su propio
  `try`: una corrida entera de sesenta minutos no se marca como rota porque la
  fila de la bitácora no se pudo escribir. Es la misma regla que el ticket 19
  pide para el latido, aplicada a la otra escritura de la misma función.
- **`pedidos.corrida_del_lote` solo crece y no se actualiza**, igual que el
  precio congelado: una corrida es un hecho del pasado. El GRANT lleva `UPDATE`
  por la misma razón escrita en `crear_rol.sql` para la tabla del precio —que
  la comprobación 6 del verificador pueda seguir siendo "no le falta ninguno
  sobre ninguna"— y ningún código lo ejercita.
- **El lote deja de ser lo único que lee esa tabla**: la pantalla la lee en
  cada carga de la lista. Es **una** consulta más por carga, de una fila, con
  su índice por `(negocio, pedido_sugerido_id, termino_en desc)`.
- **La marca del renglón es derivada y puede envejecer**: si alguien devuelve a
  `abierto` un renglón que estaba descartado cuando el lote corrió, ese renglón
  no tiene lectura y el lote **nunca lo miró**. La función pura lo distingue
  (`el lote no lo miró`) mirando que la corrida haya terminado entera y sin
  fallos, en vez de decir "no alcanzó el tiempo" sobre algo que el tope no tuvo
  que ver.
- **El journal sigue siendo la bitácora del relato** y esta tabla es el dato
  que la pantalla consulta. No son dos copias de lo mismo: el journal tiene el
  renglón por renglón y esta tabla tiene el total, y el total sale del mismo
  objeto que se imprime.
- **Se corrige de paso un error de la comprobación 16 de
  `verificar_rol.sql`**: esperaba `3` llaves `GENERATED AS IDENTITY` cuando ya
  eran cuatro desde el ticket 12, así que habría salido `[MAL]` sobre una base
  correcta la primera vez que alguien la corriera. Ahora se compara contra el
  número de tablas del esquema, que es lo que de verdad se quiere afirmar.
