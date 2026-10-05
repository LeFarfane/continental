# 0024 — Continental abre con las sesiones a la vista, y probarlas es un botón

**Fecha:** 2026-10-05  ·  **Estado:** aceptada

## Contexto

Sin sesión, un portal no da precios, y casi todo Continental depende de esos
precios: el lote nocturno, la comparación del pedido y buscar. Aun así, la
pestaña Sesiones es una más de la barra lateral, y lo que dice cada tarjeta
sale de lo que **otras** consultas encontraron de paso. Nadie la mira antes de
trabajar, y no hay forma de preguntarle al portal en ese momento si la sesión
sigue sirviendo.

El ADR 0019 ya demostró dos veces que el marcador `guardada` de Doyle miente
(2026-09-19 y 2026-09-26: LEVIC murió nueve horas y media después de abrirse).
Ese ADR resolvió el lote con una **sonda**: una búsqueda real antes de correr,
que se niega a escribir si algún portal manda al login. Durante el día, una
persona no tenía nada parecido.

## Decisión (del dueño, 2026-10-05)

1. **Al abrir Continental aparece una ventana flotante con las sesiones.** Es
   la imagen espejo de la pestaña Sesiones: las cuatro tarjetas con sus
   botones (abrir, «Ya entré», «Probar»), «Probar todas» arriba y
   «Continuar» para cerrarla. Esc también la cierra. No bloquea: se puede
   trabajar sin sesiones.
2. **Vuelve a salir** cada vez que se abre o se recarga la página, y cuando la
   pestaña pasa **una hora sin un clic ni una tecla**. Se mide en cada
   computadora por separado.
3. **Probar es un botón, nunca algo automático.** Hay uno por tarjeta y uno
   «Probar todas». Ni abrir la página ni «Ya entré» lanzan una prueba.
4. **La prueba busca «paracetamol 500»** por nombre, en vez de un EAN. El
   término vive en `config/continental.yml` y la sonda del lote usa el mismo.
5. **`sirvió` quiere decir que pasó del login**: precio, `sin resultados` o
   `no empareja`. `caducada` es que el portal mandó al login.
6. **La prueba se guarda**, solo como `sirvió` o `caducada`, con la hora y sin
   firma. Si no termina (Doyle no responde, el portal no contesta) se muestra
   el error y la tarjeta conserva su última etiqueta. **La sonda del lote no se
   guarda**: es una consulta de usar y tirar.
7. **Gana la etiqueta más reciente**, venga de una prueba o de una consulta.
8. **Una prueba a la vez, para todo Continental.** Mientras corre una, los
   botones de probar quedan apagados en todas las computadoras. El portal que
   espera en el visor no se prueba. «Probar todas» prueba los demás y se lo
   salta, diciendo por qué.

## Opciones consideradas

- **Que la ventana salga solo si alguna sesión está mal.** Se descartó: la
  etiqueta puede llevar horas sin actualizarse, y la ventana existe
  justamente para no confiar en un estado viejo.
- **Que la ventana bloquee la pantalla.** Se descartó: mirar la lista de ayer
  o En camino no necesita portales.
- **Probar sola al abrir la página.** Se descartó: cada apertura o recarga, en
  cada computadora, gastaría una búsqueda en los cuatro portales (~36 s, ADR
  0019).
- **Probar después de «Ya entré».** Se descartó por redundante: quien aprieta
  «Ya entré» acaba de ver con sus propios ojos que entró.
- **Buscar por EAN, como la sonda de antes.** Se descartó: un EAN que un
  proveedor no maneja da `sin resultados`, que demuestra que la sesión pasó
  del login pero no muestra precios. «Paracetamol 500» da resultados en los
  cuatro. La clave de la sonda de hoy es la de SIGDAN (`7502256040203`, el
  producto estrella, desde el commit `715285c`): es estable, pero solo
  demuestra precio en los portales que lo manejan.
- **Guardar también la sonda del lote.** Se descartó: decide si el lote corre
  y nada más. Lo que ella sabe ya queda en el journal y en
  `pedidos.corrida_del_lote`.
- **Firmar cada prueba.** Se descartó: probar no cambia nada del pedido, así
  que no hay nada que auditar.
- **Dejar que dos pruebas corran a la vez.** Se descartó: dos búsquedas
  encimadas en los mismos portales no comprueban nada nuevo y duplican la
  espera.

## Consecuencias

- La sonda del lote deja de buscar SIGDAN por EAN y busca el término de prueba.
  `pedido.clave_de_sonda` se sustituye por el término, y el respaldo de "la
  clave del primer renglón" ya no hace falta, porque el término no depende de
  la lista del día.
- `sirvió` cambia de significado: antes era "dio precio", ahora es "pasó del
  login". Cambió primero en `CONTEXT.md`, y el código de `sesiones.py` tiene
  que alcanzarlo.
- Hace falta una tabla nueva que solo crece, con el resultado de cada prueba,
  y que el rol `continental` pueda escribir (regla 6). `sesiones.py` la lee
  junto con las consultas guardadas para decidir la etiqueta.
- El candado de "una prueba a la vez" vive en el servidor, no en el
  navegador, porque tiene que valer entre computadoras.
- La ventana y la pestaña tienen que verse iguales. Lo más barato es que las
  dos pinten con la misma función: si cada una tiene su copia, se separan
  solas.
- **Condición de revisión:** si la ventana cada hora termina cerrándose sin
  leerla, se revisa el intervalo o la regla de cuándo aparece.

## Enmienda del 2026-10-05 — cómo quedó el botón «Probar» (ticket 02)

- **Ruta:** `POST /api/sesiones/probar`, con `{"proveedores": [...]}`; vacía o
  sin cuerpo quiere decir los cuatro. Espera a que Doyle termine con el mismo
  patrón de la sonda (`consultas.consultar_a_doyle`), una sola búsqueda del
  término de prueba para todos los pedidos.
- **Tabla:** `pedidos.prueba_de_sesion` (migración `0018`), la séptima: negocio,
  proveedor, `probada_en` (`timestamptz`, `DEFAULT now()`) y `resultado`, que el
  `CHECK` limita a `sirvió` o `caducada`. Sin firma y sin precio. **Es la
  primera tabla a la que el rol `continental` solo hace `SELECT` e `INSERT`**:
  las demás llevan `UPDATE` por la razón de `crear_rol.sql`; a ésta se le quita
  porque una prueba es un hecho del pasado y el permiso, no el código, es lo que
  garantiza que solo crece (regla 6). `verificar_rol.sql` lo exceptúa en la
  comprobación 6 y lo comprueba en la 41; la 42 lee el acento del `CHECK`.
- **Qué cuenta como «pasó del login»:** un precio, o los motivos `sin
  resultados`, `no empareja`, `varios resultados` y `precio ilegible`
  (`precios.MOTIVOS_QUE_PASARON_DEL_LOGIN`). Los dos últimos no los nombraba la
  decisión 5, pero en los dos el portal devolvió filas suyas: con otra lectura
  la prueba de un portal que contestó quedaría en «no se pudo probar». Una sola
  definición para la prueba, para la etiqueta y para el SQL de la evidencia.
  Los que no dicen nada de la sesión (el portal no contestó, ventana abierta,
  no se sabe leer, no alcanzó el tiempo) no se guardan.
- **Fallas:** si ningún portal terminó, `ok: false` con el motivo de cada uno y
  el caso `portal` de `fallas.py`; si solo algunos, `ok: true` y
  `algunos_sin_probar`. Doyle caído, o no poder guardar, no escriben nada y la
  tarjeta conserva su etiqueta.
- **Se queda para los tickets 03 y 04:** el candado de una prueba a la vez, el
  motivo de cada botón apagado, saltarse el portal del visor y «Probar todas».
  La ruta ya acepta la lista, y guarda una fila por portal que terminó.
