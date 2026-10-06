# 11: La lista de espera en el menú, por proveedor

**What to build:** una entrada nueva en el menú lateral, **«Lista de espera»**,
justo debajo de «Lista del día», con el número de renglones en espera en su
globo. La pantalla tiene una tarjeta por proveedor (LEVIC, NADRO, VICMA,
QuePharma). Cada tarjeta muestra:

- arriba, **el pedido de hoy** de ese proveedor: sus renglones con el precio
  de hoy;
- abajo, **lo que está en espera para ese proveedor**: sus renglones con el
  precio de hoy;
- un botón en cada renglón para pasarlo de un lado al otro: «Mandar a espera»
  o «Sacar de la espera»;
- en la cabecera, **solo el total en dinero** del pedido de hoy y una **barra de
  progreso** que se llena hasta el mínimo del proveedor.

Decisiones del dueño del 2026-10-06 (conversación de diseño, después de
desplegar los tickets 01–10):

1. Es una entrada nueva del menú, no una sección dentro de «Capturar y
   enviar».
2. El precio es **el de hoy**: el último consultado de ese proveedor, no el que
   tenía al mandarse a espera.
3. La cabecera de la tarjeta dice solo el total y la barra hacia el mínimo.
   Sin mínimo capturado, la barra no se pinta y se dice «sin mínimo
   capturado». Con mínimo cero, «no tiene mínimo».
4. La pantalla funciona **después de «Repartir»**: antes, dice que primero hay
   que repartir la lista, con un botón para ir a Repartir. No se inventa un
   segundo reparto.
5. Lo que se mandó a espera **sin proveedor** va en una quinta tarjeta, «Sin
   proveedor», con el selector de proveedor de siempre. Al elegir, el renglón
   pasa a la tarjeta de ese proveedor y se queda en espera.
6. **No cambia el modelo de la espera**: lo que espera entra solo a la lista
   siguiente, como dice la enmienda del 2026-10-05 al ADR 0025. Esta pantalla
   muestra la lista de hoy.

**Blocked by:** 01–10 (hechos y desplegados)

**Status:** done

- [x] Entrada «Lista de espera» en el menú lateral, debajo de «Lista del
      día», con su globo (renglones `pospuesto` de la lista abierta).
- [x] Una tarjeta por proveedor con dos bloques: el pedido de hoy (en
      `borrador`) y lo que espera con `proveedor_de_la_espera` de ese
      proveedor. Cada renglón con el precio de hoy de ese proveedor; «sin
      precio» si no lo hay, nunca $0.
- [x] La cabecera muestra el total del pedido de hoy (el mismo `total` del
      servidor que usan la captura y «Enviar») y una barra hacia el mínimo. El
      llenado y la frase los calcula el servidor en la base del mínimo, con el
      IVA bien llevado (`minimos.avisar_el_minimo`); el navegador no compara
      montos.
- [x] Mandar a espera y sacar de la espera desde aquí usan las rutas que ya
      existen, y la pantalla se repinta con lo que devuelven, sin recargar.
- [x] Tarjeta «Sin proveedor» con el selector; elegir guarda
      `proveedor_de_la_espera` firmado y mueve el renglón a la tarjeta de ese
      proveedor.
- [x] Antes de repartir: una frase y un botón a Repartir. Con la lista
      cerrada: se ve todo, pero sin botones.
- [x] Un pedido enviado no ofrece «Sacar de la espera» hacia él (regla del
      ticket 04: solo vuelve a un pedido en `borrador`).
- [x] Pruebas en los niveles del repo: lo puro (agrupar por proveedor, la
      barra y su frase), lo guardado si hay ruta o columna nueva, la ruta de
      punta a punta y la estática del JS (pinta lo del servidor, no suma ni
      compara). Si se agrega `fetch('/api/`, se actualiza el conteo.

## Cómo quedó

- **Lectura:** `GET /api/lista-de-espera` (solo lee, no abre el día). Todo llega
  armado por `lista_de_espera.py`: por proveedor `{pedido_id, frase_del_pedido,
  total, frase_del_total, minimo (+ progreso), hoy, en_espera}`, más
  `sin_proveedor`, `repartida`/`motivo`/`ir_a_repartir` y `solo_lectura`.
- **Barra:** `minimos.AvisoDelMinimo.progreso`, entero de 0 a 100 hacia abajo y con
  tope, en la base del mínimo; sin mínimo capturado o sin mínimo, `null` (sin barra).
- **Elegir proveedor de la espera:** `POST /api/renglon/{id}/proveedor-de-la-espera`,
  con la firma de la elección de siempre (`elegido_por`/`elegido_en`) y sin migración.
- **Globo:** lo cuenta el servidor en la lista del día (`pospuestos`) y se repinta con
  el `globo` de esta pantalla al abrirla; con la lista cerrada no cuenta.
- La lista del día que está en pantalla se vuelve a leer al volver a ella si desde
  aquí se movió algo.

