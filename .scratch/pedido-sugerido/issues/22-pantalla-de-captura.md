# 22: La pantalla de captura

**Qué construir:** el modo real de trabajo. El encargado tiene el portal del proveedor abierto en una ventana y esta pantalla en otra, y va tachando renglones conforme los captura.

**Bloqueado por:** 21.

**Status:** ready-for-human

- [x] Un renglón por línea, con clave, descripción, cantidad y precio, y una casilla para marcarlo como capturado.

  Un bloque plegable **por pedido en borrador**, dentro de la fila de su
  pedido y **antes** del botón de enviar, que es adonde lleva:
  `pintarCaptura` (`web/static/index.html:2567`), llamado desde
  `pintarParticion` (`:2787`, y `:2872` para el borrador que ya no sale en la
  vista previa). Cada línea: la casilla (`:2595`), la clave (`:2616`), la
  descripción como **etiqueta de la casilla** —tocar el nombre también tacha,
  un blanco mucho más grande que el cuadrito— (`:2627`), las piezas (`:2632`) y
  el precio (`:2637`).
  Del lado de Python: `particion.lo_que_hay_que_capturar` (`particion.py:787`)
  arma `Captura` (`:718`) con las mismas `Linea` de la partición, que ganaron
  `clave` y la firma de la captura (`:308`); `captura_como_json` (`:970`) y
  `_pedido_como_json` (`web/app.py:2204`) la mandan dentro de cada pedido.
  Pruebas: `test_captura.test_cada_renglon_trae_clave_descripcion_cantidad_y_precio`,
  `test_captura.test_cada_linea_viaja_con_lo_que_se_teclea_en_el_portal`,
  `test_captura.test_la_pantalla_sabe_pintar_la_captura`.

  **El precio es el de ESE proveedor, no el más barato**: es el que el
  encargado va a ver en el carrito de ese portal.
  `test_captura.test_el_precio_es_el_de_ESE_proveedor_y_no_el_mas_barato`. Sin
  precio, el motivo con palabras y nunca `$0.00`:
  `test_captura.test_sin_precio_de_ese_proveedor_se_dice_y_nunca_es_cero`.

  **Lo que se lista es lo que el pedido GUARDADO tiene dentro**
  (`renglon.pedido_id`), **no la vista previa de la partición** — y ésa es la
  trampa del ticket, ver "Lo aprendido".
  `test_captura.test_solo_entran_los_renglones_que_de_verdad_estan_dentro_del_pedido`.

- [x] Lo tachado se distingue de un vistazo de lo que falta, y se ve cuántos faltan.

  **Tachado de verdad** —`line-through`, atenuado y con fondo—, no solo con
  color: se ve igual sin distinguir el verde (`index.html:311`). **Y no se mueve
  de sitio**: una lista que se reordena bajo el dedo pierde el renglón por el
  que uno iba.
  **Cuántos faltan** lo cuenta Python —`Captura.faltan` (`particion.py:754`)— y
  lo dice `frase_del_avance` (`:824`) en el **resumen del bloque**, que se ve
  con el bloque cerrado: *"3 de 5 tachados · faltan 2"*, *"Ninguno de los 5
  renglones está tachado todavía"* (nunca "0 de 5"), *"Los 5 renglones están
  tachados"*. El JavaScript no filtra ni suma.
  Pruebas: `test_captura.test_cuantos_faltan_sale_de_python`,
  `test_captura.test_la_frase_del_avance_dice_cuantos_faltan`,
  `test_captura.test_la_frase_con_uno_solo_por_capturar_no_dice_faltan_1`,
  `test_captura.test_la_frase_sin_nada_tachado_no_dice_cero_de`,
  `test_captura.test_el_orden_es_el_de_la_lista_y_no_cambia_al_tachar`,
  `test_captura.test_lo_tachado_se_distingue_con_una_clase_y_no_solo_con_color`,
  `test_captura.test_la_pantalla_no_cuenta_lo_que_falta_ella_sola`.

- [x] El avance sobrevive a recargar la página: nadie quiere empezar de nuevo a la mitad de 40 renglones.

  **En la tabla, no en el navegador**, y es la decisión cara del ticket: ADR
  0010. Dos columnas firmadas en `pedidos.renglon`, `capturado_por` y
  `capturado_en`, pareadas por `ck_renglon_captura`
  (`sql/crear_tablas.sql:705`), con
  `sql/migraciones/0007-el-avance-de-la-captura.sql`.
  `RenglonGuardado.capturado_por` (`almacenamiento.py:530`),
  `marcar_capturado` (protocolo `:2140`, SQL `_MARCAR_CAPTURADO` `:2934` y
  `_DESMARCAR_CAPTURADO` `:2952`, real `:3501`, doble `dobles.py:1106`), ruta
  `POST /api/renglon/{renglon_id}/capturado` (`web/app.py:1023`), que devuelve
  la lista entera como `partir` y `enviar`.
  Pruebas: `test_captura.test_el_avance_sobrevive_a_recargar_la_pagina` (dos
  firmas distintas, releídas con un `GET` nuevo, que es lo mismo que hace otra
  pestaña u otra máquina), `test_captura.test_el_avance_sobrevive_a_releer`,
  `test_captura.test_el_avance_NO_vive_en_el_navegador`.

  **Al recargar a la mitad, el bloque que va a medias se abre solo**
  (`CAPTURAS_ABIERTAS`, `index.html:2559`): lo primero que se ve es por dónde
  se iba. Qué bloque está abierto sí vive en el navegador —en memoria—, porque
  es de quien mira y no del pedido.

- [x] La clave se puede copiar de un clic, porque es lo que se pega en el buscador del portal.

  La clave **es un botón** (`index.html:2616`) y `copiarClave` (`:2517`) usa el
  portapapeles moderno, cae al camino viejo (`execCommand('copy')`) si no está,
  y si **ninguno** sirve lo dice en el botón —*"no se pudo copiar: 750…"*—
  (regla 4): un clic que no copia y calla hace pegar en el portal la clave del
  renglón anterior. Un producto sin EAN dice *"sin código"* y el resumen manda a
  buscarlo por nombre.
  Pruebas: `test_captura.test_la_clave_se_copia_de_un_clic`,
  `test_captura.test_un_renglon_sin_clave_se_dice_para_buscarlo_por_nombre`,
  `test_captura.test_sin_clave_ya_tachado_no_manda_a_buscarlo_por_nombre`.
  En el recorrido: el clic dijo *"copiada ✓"*, y con `navigator.clipboard`
  anulado a mano el camino viejo también copió con un clic de verdad.

- [x] Marcar todo como capturado es lo que habilita enviar el pedido, sin obligar a ello.

  **Las dos mitades, y la segunda es la que se hace mal sola.**
  *Lleva*: con el último tachado, `invitacion_a_enviar` (`particion.py:867`)
  devuelve `CAPTURA_COMPLETA` (`:206`) —*"el siguiente paso es enviar el
  pedido"*—, el resumen se pone verde, el botón de enviar se resalta
  (`index.html:2811`) y **el foco salta a él** (`tacharRenglon`, `:1913`).
  *Sin obligar*: `se_puede_enviar` **no mira la captura** —la única línea que
  apaga el botón sigue siendo `boton.disabled = !guardado.se_puede_enviar`
  (`:2805`)—, y mientras falte algo la pantalla lo dice con `CAPTURA_NO_OBLIGA`
  (`particion.py:217`): *"tachar sirve para no perder la cuenta, no es
  requisito"*. La dirección de la dependencia es la casilla entera: la captura
  recibe `se_puede_enviar`, y el envío nunca recibe la captura.
  Pruebas: `test_captura.test_todo_tachado_LLEVA_a_enviar`,
  `test_captura.test_tachar_el_ultimo_invita_a_enviar`,
  `test_captura.test_con_renglones_por_tachar_la_pantalla_dice_que_NO_obliga`,
  `test_captura.test_enviar_SIN_haber_tachado_nada_sigue_funcionando`,
  `test_captura.test_enviar_con_la_mitad_tachada_tambien`,
  `test_captura.test_la_captura_no_apaga_el_boton_de_enviar`,
  `test_captura.test_todo_tachado_no_invita_a_enviar_lo_que_no_se_puede_enviar`,
  `test_captura.test_un_pedido_sin_renglones_NO_esta_todo_capturado`.
  En el recorrido: LEVIC se envió con **cero** renglones tachados y NADRO con
  los cinco; los dos pasaron a `enviado` igual.

## Lo que se decidió, y dónde está escrito

`docs/decisiones/0010-el-avance-de-la-captura-vive-en-la-tabla-del-renglon.md`,
con cuatro alternativas descartadas: `localStorage` (dos pestañas divergen en
silencio, cambiar de máquina pierde el avance, no hay firma, y el avance es lo
que lleva a la única acción que compromete dinero), `sessionStorage` o cookie,
una tabla nueva (un hecho por renglón con un solo valor son dos columnas, y
una tabla obligaría a volver a correr `crear_rol.sql`), y **un estado nuevo del
renglón** — la que parece más limpia y la que rompe cosas: cuatro sentencias
llevan `estado = 'abierto'` en su `WHERE` y volver a partir se saltaría en
silencio un renglón `capturado`.

Tres decisiones del ADR que no se leen del ticket y conviene no reabrir a
ciegas:

- **Tachar NO exige la lista `abierta`**, igual que enviar (ADR 0009): es decir
  "ya lo tecleé en el portal", lo contrario de modificar lo que se va a pedir.
  `test_captura.test_tachar_NO_exige_la_lista_abierta`,
  `test_captura.test_la_sentencia_de_tachar_NO_mira_el_estado_de_la_lista`.
- **Se puede destachar, y enviar no se puede deshacer.** Son declaraciones de
  distinto tamaño: la marca no cambia nada fuera de esta pantalla mientras el
  pedido siga en borrador. Una vez `enviado`, ni tachar ni destachar
  (`test_captura.test_un_renglon_de_un_pedido_enviado_ya_no_se_tacha_ni_se_destacha`),
  y las marcas se quedan como la historia de cómo se capturó
  (`test_captura.test_enviar_conserva_las_marcas`).
- **La ruta recibe `{"capturado": true|false}` y nunca "alterna".** Con dos
  pestañas, un "alterna" mandado desde la que iba atrasada destacharía lo que
  la otra acaba de tachar; "déjalo tachado" dicho dos veces deja lo mismo.
  `test_captura.test_el_cuerpo_tiene_que_decir_si_o_no`.

**No hay que volver a correr `crear_rol.sql`**: la migración 0007 no crea
tabla. Sí `verificar_rol.sql`, por su comprobación **29**.

## Lo aprendido

**La trampa del ticket: la lista de captura NO puede salir de la vista previa
de la partición.** `particion.pedidos` se recalcula con los precios de este
instante; si a media mañana llega un LEVIC más barato, la vista previa ya pone
el renglón en LEVIC **mientras el pedido guardado de NADRO todavía lo tiene
dentro**. Lo que se captura tiene que ser exactamente lo que al enviar pasa a
`en tránsito`, y eso lo decide `renglon.pedido_id` —lo mismo que mira
`_RENGLONES_A_TRANSITO`—. Por eso `lo_que_hay_que_capturar` recibe el pedido
guardado y filtra por `pedido_id`, y por eso un borrador que ya no sale en la
vista previa **también** pinta su captura (`index.html:2872`).

**Volver a partir tiene que borrar la marca del renglón que CAMBIA de pedido, y
conservar la del que se queda.** Tachado en el portal de NADRO y movido a LEVIC:
en el portal de LEVIC nadie lo ha tecleado, y una marca que viajara con él le
diría al encargado que se lo salte. Es un `case ... is distinct from` sobre el
valor viejo en `_ASIGNAR_RENGLONES` (`almacenamiento.py:2807`) —en el `SET` de un
`UPDATE`, `r.pedido_id` es el valor de antes— y un `null` a secas en
`_SOLTAR_RENGLONES` (`:2851`). Con `localStorage` esta falla habría sido
silenciosa e inevitable: la llave del pedido seguiría diciendo "tachado" para
un renglón que ya se fue.
`test_captura.test_volver_a_partir_a_OTRO_proveedor_borra_la_marca`,
`test_captura.test_quedarse_sin_pedido_al_volver_a_partir_borra_la_marca`.

**Descartar no saca un renglón de su pedido** (`_DESCARTAR` no toca
`pedido_id`), así que un borrador puede tener dentro un renglón que ya nadie va
a pedir. No se lista para capturar —teclearlo sería comprar lo que alguien
decidió no comprar— y el resumen lo dice: *"1 renglón de este pedido está
descartado: no lo captures, y vuelve a partir para sacarlo"*. Ver "sin hacer".
`test_captura.test_un_descartado_dentro_del_pedido_no_se_captura_y_se_cuenta_aparte`.

**El recorrido del navegador cazó una cosa que el suite no** —cuarta vez: 14,
15, 21 y 22—. Con los cinco renglones tachados, el resumen seguía diciendo *"1
sin código de barras: búscalo por nombre"*: mandaba a buscar algo que ya se
capturó. Ahora cuenta solo los que faltan (`Captura.sin_clave_por_tachar`,
`particion.py:773`).
`test_captura.test_sin_clave_ya_tachado_no_manda_a_buscarlo_por_nombre`.

Lo demás que el recorrido comprobó y quedó bien: el bloque **no se cierra** al
tachar (repintar recrea el `<details>`, y sin `CAPTURAS_ABIERTAS` cada tachón lo
habría cerrado), el foco vuelve a la misma casilla, con el último va al botón de
enviar, la recarga trae el avance y abre el bloque que va a medias, con la red
caída la casilla vuelve a como estaba con *"Continental no contestó: la marca NO
se guardó"*, y a 375 px nada se sale del bloque (el desborde horizontal que se
ve a 800 px es de la tabla principal y es de antes).

**El censo de `fetch('/api/` de tres pruebas viejas pasó de 10 a 11**
(`test_vistas`, `test_clasificacion`, `test_sugerido`). Es una cuenta y no la
garantía —la garantía es que `fetch('/api/pedido-sugerido')` aparezca una sola
vez, y sigue así—. Partir y enviar no salían en ese censo porque su `fetch(`
parte la línea antes de la ruta; tachar sí, y se contó en vez de esconderlo con
un salto de línea.

## Lo que quedó sin hacer, y por qué

- **`sql/migraciones/0007` no se ha corrido.** No se puede: desde la torre no
  hay Postgres alcanzable. **Hay que correrla ANTES de desplegar este código**:
  `_LEER_RENGLONES` nombra las dos columnas nuevas, así que con la base vieja la
  lista del día no se puede leer. **No hace falta volver a correr
  `crear_rol.sql`**; **sí `verificar_rol.sql`** (comprobación 29).
- **`continental.verificar` no avisa si falta una migración de columnas.** Si
  alguien despliega sin correr la 0007, el paso 6 de `desplegar.sh` no lo caza y
  la pantalla se cae con "column capturado_por does not exist". No es nuevo —la
  0005 y la 0006 tienen el mismo hueco— y por eso no se arregló aquí: es un
  invariante general ("las columnas que el código nombra existen"), que merece
  su propio ticket. Hoy lo cubre la comprobación 29 de `verificar_rol.sql`, que
  se corre a mano.
- **El renglón descartado dentro de un borrador** se señala y no se arregla. La
  cuenta del pedido (`renglones` en `_lo_que_hay_dentro`) y su total lo siguen
  contando hasta que alguien vuelva a partir. Es de los tickets 10 y 20, no de
  éste; la captura ya no lo lista y lo dice.
- **Un borrador que ya no sale en la vista previa no tiene botón de enviar**, y
  así quedó desde el ticket 21. Por eso ahí la captura se pinta **sin** la
  invitación a enviar: una frase que dice "el siguiente paso es enviar" sin
  botón al lado manda a buscar uno que no está.
- **Mover a otro proveedor un renglón ya tecleado en el portal** le borra la
  marca aquí, pero **sigue en el carrito del portal viejo**, y la pantalla no lo
  advierte. Advertirlo pediría recordar dónde estuvo tachado, que es justo lo
  que la marca deja de afirmar al moverse.
- **No se guarda quién destachó.** La columna afirma "está capturado" y lo
  contrario es su ausencia. Queda en la bitácora de la ruta, que escribe las dos
  direcciones con su firma. Razonado en el ADR 0010.
- **No se demostró contra un portal real**, por lo mismo que los tickets 13, 14
  y 21: las cuatro sesiones de Doyle siguen caducadas. Aquí duele poco —tachar
  no le pregunta nada a Doyle—, pero los precios que la captura enseña salen de
  los dobles.
- **El portapapeles del sistema no se pudo leer desde el recorrido**: el
  navegador del panel dijo "copiada ✓" y `Get-Clipboard` de la torre vino vacío,
  así que el panel tiene su propio portapapeles. Hay que probar un clic en el
  navegador del mostrador antes de darlo por visto.
- **Teclado: Tab + espacio para tachar no se pudo comprobar** —la herramienta
  del recorrido no dispara la acción por omisión del espacio—; el foco sí
  vuelve a la casilla correcta después de repintar. Tocar el nombre tacha, que
  es lo que se va a usar con el ratón.
