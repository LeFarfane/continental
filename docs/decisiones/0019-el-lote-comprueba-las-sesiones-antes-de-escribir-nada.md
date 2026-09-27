# 0019 — El lote nocturno comprueba las sesiones antes de escribir un solo precio

**Fecha:** 2026-09  ·  **Estado:** aceptada

## Contexto

El 2026-09-26 se abrieron a mano las cuatro sesiones de proveedor desde el
visor, y esa misma noche corrió el primer lote de precios real sobre 174
renglones. Lo medido:

| Hora | Hecho |
|---|---|
| 10:23 | Se abre la sesión de LEVIC. Queda `guardada`. |
| 19:58 | Arranca el lote. |
| 20:08 | Los 19 primeros renglones traen LEVIC con `la sesión caducó`. **Cero precios de LEVIC.** |
| 20:45 | Se detiene a mano. **86 renglones congelados sin LEVIC.** |

**Nueve horas y treinta y cinco minutos** entre abrir la sesión y que dejara de
servir. Los otros tres aguantaron: de 19 renglones, NADRO dio 15 precios y
VICMA 9.

Tres hechos hacen que esto no sea un tropiezo sino un defecto:

1. **LEVIC es el único proveedor que le ha ganado a NADRO.** El 2026-09-23,
   ALIREN `7501300420541`: LEVIC $122.50 contra NADRO $126.25. Un lote sin
   LEVIC compara NADRO contra VICMA y poco más, y encontrar esos $3.75 es la
   razón de ser del módulo.
2. **Los precios se congelan en una tabla que solo crece** (ADR 0004). Un lote
   tuerto no se corrige: se queda escrito. No hay `UPDATE` que lo arregle
   porque no debe haberlo.
3. **El lote corre solo, lun–vie a las 22:00, sin nadie mirando.** Si una
   sesión abierta en la mañana no llega viva a la noche, *todas* las corridas
   nocturnas salen tuertas.

Y la señal que existía no servía: **`GET /api/sesiones` decía `guardada` para
las cuatro** mientras LEVIC estaba muerta. Ese marcador es de disco y solo dice
que alguien confirmó una sesión alguna vez. Ya había mordido igual el
2026-09-19, cuando las cuatro decían `guardada` con las cuatro caídas.

## Opciones consideradas

1. **Dejarlo como estaba** y confiar en que alguien note los huecos al mirar la
   lista en la mañana.
2. **Creerle a `GET /api/sesiones`** y no correr si alguna dice algo distinto
   de `guardada`.
3. **Correr igual, marcando los renglones** cuya sesión estaba caída, para
   volver a consultarlos después.
4. **Sondear con una búsqueda real antes de empezar, y negarse a correr** si
   alguna sesión no sirve.

## Decisión

La 4. Antes del primer renglón, el lote lanza **una sola búsqueda** que Doyle
reparte entre los cuatro proveedores. Si alguno responde con `la sesión
caducó`, el lote **se niega a correr**: cero renglones consultados, cero filas
escritas, salida distinta de cero, y el rastro completo en el journal, en
`pedidos.corrida_del_lote` y en el latido a Uptime Kuma.

## Razones

- **Un marcador de disco no demuestra nada (descarta la 2).** `guardada` dice
  que alguien confirmó alguna vez, no que el portal siga aceptando la sesión.
  Lo único que lo demuestra es una búsqueda que vuelva sin `la sesión caducó`.
  Dos veces ya —el 19 y el 26 de septiembre— ese marcador afirmó lo contrario
  de la realidad.
- **El discriminante es `la sesión caducó` y nada más.** `sin resultados` y
  `no empareja` son el portal **contestando**: la sesión está viva y el
  producto no está o no empareja. Confundirlos dejaría al lote negándose a
  correr por un EAN que un proveedor simplemente no maneja.
- **Negarse entero y no a medias (descarta la 3).** Marcar renglones para
  reconsultar suena más suave, pero la fila tuerta ya quedó escrita en la tabla
  que solo crece, y el daño de este ADR es precisamente ése. Media hora de
  trabajo perdida se recupera; 174 renglones congelados sin LEVIC, no.
- **La sonda no escribe.** Reutiliza `consultar_a_doyle` pero **no** pasa por
  `consultar_y_congelar`. Si persistiera algo, negarse a correr dejaría escrita
  justo la fila que todo esto evita. Que no persista nada es lo que permite
  negarse **sin rastro parcial**.
- **Una sonda y no cuatro.** `pedir_busqueda` ya reparte un término entre los
  cuatro proveedores en el mismo trabajo y Doyle arranca sus cuatro hilos de
  una vez (ADR 0006). Cuatro búsquedas sueltas cuadruplicarían la espera sin
  comprobar nada más. Con el piso medido de ~9 s por portal, la sonda cuesta
  ~36 s contra un presupuesto de 60 minutos: 1%.
- **`SE_INTERRUMPIO` y no un desenlace nuevo.** Negarse a correr es "algo tumbó
  la corrida entera", que es lo que ese final ya significa. Inventar un
  desenlace obligaría a tocar el `CHECK` de `corrida_del_lote`, la pantalla y
  el verificador, para expresar algo que el vocabulario existente ya dice.
- **No confiar en que alguien lo note (descarta la 1).** Nadie lo notó. El lote
  corrió 47 minutos escribiendo renglones tuertos y lo que lo detuvo fue una
  revisión que pudo no haber ocurrido.

## Consecuencias

- **Un proveedor caído bloquea a los cuatro.** Con las sesiones durando menos
  de diez horas, es probable que el lote se niegue a correr casi todas las
  noches hasta que se resuelva por qué caduca LEVIC. **Eso es a propósito**: un
  lote que no corre se ve, y uno tuerto no. Pero significa que esta decisión
  **no sustituye** al arreglo de fondo, solo evita que el daño sea permanente.
- **El timer quedó desarmado el 2026-09-26**
  (`systemctl disable --now continental-lote.timer`), porque hasta que la
  verificación estuviera desplegada cada noche escribía ~112 renglones tuertos.
  Volver a armarlo pide las dos cosas: esta verificación desplegada **y** saber
  por qué caduca la sesión. Con la primera sola, el lote se negaría casi todas
  las noches; queda anotado como pendiente.
- **La sonda gasta una búsqueda real contra los cuatro portales**, cada noche,
  sobre un producto que quizá el lote consulte después. Es el precio de no
  creerle a un marcador.
- **La clave de la sonda es configuración, no código** —`pedido.clave_de_sonda`
  en `config/continental.yml`, junto a `tope_lote_minutos`—, porque es una
  decisión de operación. Hoy está **sin valor**, y mientras lo esté el respaldo
  usa la clave del primer renglón con EAN de la lista del día: funciona, pero
  duplica una búsqueda sobre ese renglón y cambia de identidad cada noche. El
  journal lo avisa en cada corrida.
- **Si algún día un proveedor deja de poder sondearse** —por ejemplo, uno que
  nunca encuentre por EAN, como parece ser QuePharma— habrá que decidir si se
  le excluye de la verificación. Hoy no estorba porque `sin resultados` no
  descalifica, pero conviene tenerlo escrito antes de que sorprenda.
- **Condición de revisión:** si las sesiones llegan a durar de forma confiable
  más que el hueco entre abrirlas y el lote, la sonda pasa de red de seguridad
  a peaje. Si eso ocurre, se revisa si vale sus ~36 s y su búsqueda.
