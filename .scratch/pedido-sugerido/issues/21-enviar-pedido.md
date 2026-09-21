# 21: Enviar un pedido

**Qué construir:** el momento en que el pedido deja de ser un borrador y se convierte en algo que el sistema tiene que recordar. Marcarlo como enviado es lo que después evita pedir doble.

**Bloqueado por:** 20.

**Status:** ready-for-human

- [x] Antes de enviar se ve el total en pesos del pedido, para saber cuánto se va a comprometer.

  Dentro del **botón que se va a apretar** y no en una tabla aparte:
  `Enviar a LEVIC — $832.10`. Cuando no se puede saber dice `total sin saber`,
  nunca `$0.00`.
  `_pedido_como_json` (`web/app.py:2017`) con `total_sin_iva` como **cadena**,
  `_lo_que_hay_dentro` (`web/app.py:1988`), y `pintarParticion` en
  `web/static/index.html`.
  Pruebas: `test_envio.test_el_total_del_pedido_viaja_con_el_pedido_antes_de_enviarlo`,
  `test_envio.test_sin_total_el_pedido_lo_dice_y_se_puede_enviar_igual`.

  **Un pedido SIN total sí se envía**, y es lo contrario de un descuido: la
  quinta casilla del ticket 20 dice que un renglón sin precio se pide igual, y
  el precio de verdad lo ve el encargado en el portal mientras lo captura.
  Negarlo volvería el precio de Doyle un requisito para operar la farmacia.
  `test_envio.test_un_pedido_sin_total_SI_se_puede_enviar`.

  **Un pedido con el total VIEJO no se envía**, y eso cierra el hilo abierto 13
  de `HANDOVER.md`, que le dejó este caso a este ticket. `total_sin_iva` solo se
  reescribe al partir, así que corregir la cantidad de un renglón que ya está
  dentro lo deja enseñando lo que costaba hace un rato — y ésa es la cifra
  contra la que alguien compara la factura. El `NOT EXISTS` del `WHERE`
  (`almacenamiento.py:2624`) lo impide y `particion.TOTAL_ENVEJECIDO`
  (`particion.py:186`) lo dice
  antes del clic, mandando a "Volver a partir".
  `test_envio.test_un_pedido_con_el_total_viejo_no_se_envia`,
  `test_envio.test_corregir_una_cantidad_despues_de_partir_bloquea_el_envio`.

  **Se eligió negarse y no recalcular al enviar**, que era lo que el hilo
  proponía: recalcular cambiaría el número **después** de que el encargado leyó
  el del botón, o sea enviaría un total que nadie vio. Un total viejo enseñado
  es malo; uno nuevo escrito a espaldas de quien lo miró es peor.

- [x] `borrador` → `enviado`, con quién lo envió y cuándo, firmado con el correo que verificó Access.

  `almacenamiento.ENVIADO` (`almacenamiento.py:146`), `ESTADOS_DEL_PEDIDO`
  (`:161`), `PedidoGuardado.enviado_por` / `enviado_en` / `fue_enviado`
  (`:656`), `enviar_el_pedido` (protocolo `:2039`, SQL `_ENVIAR_EL_PEDIDO`
  `:2624`, real `:3298`, doble `dobles.py:993`), ruta
  `POST /api/pedido/{pedido_id}/enviar` (`web/app.py:890`).
  En la tabla: `enviado_por` / `enviado_en` + `ck_pedido_envio`
  (`sql/crear_tablas.sql:371`) y `ck_pedido_enviado_por` (`:358`), con
  `sql/migraciones/0006-enviar-el-pedido.sql`.
  Pruebas: `test_envio.test_enviar_cambia_el_estado_y_lo_firma`,
  `test_envio.test_el_enviado_en_viaja_con_zona`,
  `test_envio.test_sin_encabezado_de_access_la_firma_es_sin_identificar`,
  `test_envio.test_la_firma_y_el_estado_van_pareados_en_el_doble`,
  `test_envio.test_enviado_esta_en_el_glosario_y_en_la_tupla_del_codigo`,
  `test_envio.test_la_firma_del_envio_va_pareada_en_los_dos_archivos`.

  **Firma y no acuse** (ADR 0009): el hecho ocurrió en otra pantalla, con otras
  credenciales, y Continental no lo vio. Lo único verdadero que se puede
  escribir es quién lo dice y cuándo lo dijo. Es una firma y **nunca** un
  permiso (regla 3).

- [x] Un pedido `enviado` ya no se edita.

  El `WHERE` de las cuatro sentencias, no un `if`: `_ABRIR_EL_PEDIDO`,
  `_ASIGNAR_RENGLONES`, `_SOLTAR_RENGLONES` y
  `_VACIAR_LOS_PEDIDOS_SIN_RENGLONES` ya llevaban `estado = 'borrador'` desde el
  ticket 20; lo que este ticket agrega es **un estado que el código sí escribe**,
  así que la garantía dejó de estar solo escrita y pasó a estar ejercitada.
  Pruebas: `test_envio.test_un_pedido_enviado_no_se_vuelve_a_enviar`,
  `test_envio.test_volver_a_partir_no_toca_un_pedido_enviado`,
  `test_envio.test_un_renglon_enviado_ya_no_se_descarta_ni_se_ajusta`,
  `test_envio.test_un_pedido_vacio_no_se_puede_enviar`,
  `test_envio.test_un_pedido_de_otro_negocio_no_se_envia`,
  `test_envio.test_la_transicion_del_envio_va_en_el_where_y_no_en_un_if`.

  Y de este lado de la pantalla: un renglón `en tránsito` deja de poder tocarse
  —`const editable = acciones.editable && !r.esta_en_transito`,
  `index.html:1134`—, que es lo que evita tres botones que contestan 409.

- [x] Al enviar, sus renglones pasan a `en tránsito`.

  `_RENGLONES_A_TRANSITO` (`almacenamiento.py:2666`), en la **misma
  transacción** que el `UPDATE` del pedido: medio envío —el pedido marcado y sus
  renglones en `abierto`— es el modo de falla que este ticket viene a evitar.
  `RENGLON_EN_TRANSITO` (`:105`) es constante desde hoy porque hoy hay código
  que la escribe.
  Pruebas: `test_envio.test_al_enviar_los_renglones_pasan_a_en_transito`,
  `test_envio.test_solo_pasan_a_transito_los_renglones_de_ESE_pedido`,
  `test_envio.test_un_renglon_en_transito_no_vuelve_a_repartirse`,
  `test_envio.test_lo_ya_pedido_no_entra_en_la_cola_del_boton_de_completar`.

  **La consecuencia que no estaba en el ticket y sí en el código**: antes de
  hoy ningún renglón había estado nunca `en tránsito`, así que las cuatro
  cuentas de "qué falta" —la partición, el conteo de huecos, la cola del botón
  de completar y el aviso de sesiones caducadas— nunca lo habían visto. Ahora
  salen de `PedidoSugeridoGuardado.por_repartir` (`almacenamiento.py:782`) y no
  de `de_trabajo`.

- [x] La pantalla deja claro que enviar significa "yo ya lo capturé en el portal del proveedor", no que Continental se lo mandó a nadie: **Continental no hace pedidos en los portales** (fuera de alcance del ADR 0002).

  La frase viaja **hecha desde Python** —`particion.frase_del_envio`
  (`particion.py:593`), con `ENVIAR_ES_UNA_DECLARACION` y
  `CONTINENTAL_NO_PIDE_EN_PORTALES` (`:154`, `:157`)— y va en el mismo bloque
  del botón, no en una nota al pie. Después de enviar cambia y dice **quién** lo
  capturó, en voz activa, y vuelve a desmentirlo. También lo dice el aviso tras
  el clic y el glosario de `CONTEXT.md`.
  Pruebas: `test_envio.test_la_frase_de_un_borrador_dice_que_continental_no_manda_nada`,
  `test_envio.test_la_frase_de_un_pedido_enviado_dice_quien_lo_capturo`,
  `test_envio.test_la_frase_de_que_significa_enviar_viaja_hecha_desde_python`,
  `test_envio.test_la_pantalla_no_compone_la_frase_del_envio_ella_sola`.

## Lo que se decidió, y dónde está escrito

`docs/decisiones/0009-enviar-es-la-firma-de-que-ya-se-capturo-en-el-portal.md`,
con las tres alternativas descartadas: que Continental capture el pedido en el
portal (regla 1 y ADR 0002), que le mande un correo al proveedor (la farmacia no
pide por correo, y estrenaría un borde de salida), y que no se guarde nada (es
justo lo que hace que se pida doble).

Dos decisiones del ADR que no se leen del ticket y conviene no reabrir a ciegas:

- **Enviar NO exige que la lista siga `abierta`**, al revés que descartar,
  ajustar, elegir y partir. Enviar es lo contrario de modificar una lista
  cerrada: es decir que sí se pidió. Con esa condición puesta, quien cierre la
  lista antes de marcar el último pedido se queda con renglones `abierto`
  atrapados dentro de una lista cerrada y sin manera de moverlos a
  `en tránsito` — mercancía pedida que el sugerido volvería a proponer y que la
  recepción (ticket 26) no podría cruzar.
- **Un pedido vacío no se envía** (el `EXISTS` del `WHERE`), y **uno sin total
  sí**. Se parecen y son opuestos: el primero no tiene nada que capturar; el
  segundo tiene mercancía y le falta un precio.
- **Un pedido con el total viejo no se envía** (el `NOT EXISTS`), y eso también
  se parece a "sin total" y tampoco es lo mismo: `None` es "no se puede saber" y
  es honesto; una cifra con dos decimales calculada antes de que alguien
  corrigiera una cantidad es una mentira con formato de dato.

## Lo aprendido

**El recorrido del navegador volvió a cazar lo que el suite no, y esta vez lo
más grave del ticket.** Es la tercera vez (14, 15 y ahora 21). Las cuatro cosas,
las cuatro con prueba ahora:

1. **El pedido recién enviado DESAPARECÍA de la pantalla.** Al enviar, sus
   renglones salen de `por_repartir`, así que el pedido sale de
   `particion.pedidos` —donde está bien que no esté: es el cálculo de lo que
   queda por hacer—. Pero `pintarParticion` recorría **solo** esa lista, así que
   el pedido que el encargado acababa de crear, con su firma y su total, se
   borraba de la vista. Mercancía pedida que desaparece de la pantalla sin que
   nadie se entere es exactamente lo que `CONTEXT.md` prohíbe para los productos
   sin anaquel. Ahora se pinta la **unión**: lo que se partiría ahora, más los
   pedidos guardados que ya no están ahí (`fueraDeLaParticion`,
   `index.html:2406`).
   `test_envio.test_el_pedido_enviado_NO_desaparece_de_la_pantalla`.
2. **"3 renglones por atender" seguía diciendo 3 con dos ya pedidos**, y sus
   tres controles seguían encendidos para contestar 409.
   `test_envio.test_un_renglon_en_transito_sigue_en_la_tabla_pero_no_se_puede_tocar`,
   `test_envio.test_lo_ya_pedido_no_cuenta_como_renglon_por_atender`.
3. **Con todo enviado, la pantalla decía "Todavía no hay en qué partir esta
   lista · Elige a quién se le pide cada renglón"** — sobre una lista que ya se
   pidió entera. "Nada que partir" son dos situaciones opuestas y decirlas con
   la misma frase manda a rehacer un trabajo hecho.
   `test_envio.test_una_lista_ya_pedida_entera_no_dice_que_falta_elegir_proveedor`.
4. **`armado ... 02:07 a.m..`**, con dos puntos. Es del ticket 20:
   `instanteEnPalabras` ya termina en "a.m." y el `+ '.'` sobraba. Cosmético y
   aun así fijado — lo que no tiene prueba vuelve.
   `test_envio.test_la_hora_no_se_escribe_con_dos_puntos_al_final`.

**El invariante 3 de `continental.verificar` se encendió solo**, sin tocar
`verificar.py`. Estaba escrito desde el ticket 17 esperando `estado` y
`enviado_por`; el 20 puso la primera y el 21 la segunda, los dos con el nombre
que ya estaba escrito ahí. `COLUMNAS_QUE_EXIGE_EL_ENVIO` nunca cambió. Es el
mejor argumento que este repo tiene para escribir un invariante antes de que se
pueda revisar.

**El ticket 20 pagó su deuda exacta.** Se negó a adelantar el nombre `enviado`
porque el glosario no lo tenía, y dejó anotado el precio con todas sus letras:
*"el ticket 21 paga una migración para ampliar `ck_pedido_estado`"*. Fue eso y
nada más. A cambio, este ticket eligió el nombre con el glosario delante.

**`test_pedidos.test_el_estado_del_pedido_del_ddl_es_el_que_escribe_el_codigo`
tuvo que partirse en dos, y la razón vale para la próxima migración.** Comparaba
`ESTADOS_DEL_PEDIDO` contra `crear_tablas.sql` **y contra la migración 0005**.
Eso solo funciona mientras la última migración sea la única: una migración es un
hecho del pasado, y reescribir la 0005 para que diga lo de hoy dejaría distintas
a una base que ya la corrió y a otra que la corra mañana. Ahora esa prueba exige
que la 0005 **siga diciendo lo que dijo**, y quien compara con el presente es
`test_envio.test_el_check_del_estado_se_amplio_en_los_dos_archivos`.

## Lo que quedó sin hacer, y por qué

- **No hay "desenviar".** No se pidió, y serviría para exactamente un caso
  —apretar Enviar por error antes de capturar— a cambio de abrir el camino a
  editar un pedido que sí está en el portal, que es lo que la tercera casilla
  viene a impedir. El caso del error se atiende con credenciales de dueño, con
  el `UPDATE` que `continental.verificar` ya imprime como comando de reparación
  de su invariante 3. Está razonado en el ADR 0009.
- **No hay estado de `cancelado`.** Tampoco se pidió, y un valor en un CHECK que
  ningún código escribe es vocabulario muerto invitando a que alguien lo use con
  otro significado. Cuando haga falta, entra con su ticket y su nombre en el
  glosario.
- **`sql/migraciones/0006` no se ha corrido.** No se puede: el almacén vive en
  Docker en atlas y desde la torre no hay Postgres alcanzable (verificado el
  2026-09-19, sigue igual). Va en `HANDOVER.md` con su comando. **No hace falta
  volver a correr `crear_rol.sql`** —esta migración no crea ninguna tabla— pero
  **sí conviene correr `verificar_rol.sql`**: sus comprobaciones 27 y 28 son
  nuevas.
- **No se demostró contra un portal real**, por lo mismo que los tickets 13 y
  14: las cuatro sesiones de Doyle siguen caducadas (hilo abierto 1 de
  `HANDOVER.md`). Aquí duele menos que allá — enviar no le pregunta nada a
  Doyle— pero el total que se ve antes de enviar sale de precios que hoy solo
  existen contra los dobles.
- **La marca "Lo que sí se sabe suma $0.00" de un pedido con CERO precios sigue
  ahí**, y es del ticket 20. Es literalmente cierta —nada se sabe, así que la
  suma de lo que se sabe es cero— y aun así se lee como un precio. No se tocó
  porque no es de este ticket y cambiarla es una decisión de redacción sobre
  `particion.PedidoPorArmar.parcial_sin_iva`, no un arreglo. **Condición de
  disparo:** si alguien pregunta por qué un pedido "cuesta $0.00", eso deja de
  ser cosmético.
- **Un renglón `en tránsito` sigue pudiendo consultar su precio.** El botón no
  se apagó: `guardar_precios` no mira el estado del renglón —la tabla del precio
  solo crece (ADR 0004)— así que no rebota, y volver a leer un precio no cambia
  nada de lo ya pedido. Lo que sí se hizo es sacarlo de la **cola del botón de
  completar**, que es donde costaba tiempo de portal. Apagar el botón individual
  sería decidir que un precio de referencia no sirve para nada, y eso no está
  decidido.
