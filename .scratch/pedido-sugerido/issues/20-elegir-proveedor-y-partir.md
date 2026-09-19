# 20: Elegir proveedor y partir el sugerido en pedidos

**Qué construir:** el paso donde la comparación se vuelve una decisión. El encargado marca a quién le pide cada renglón, y la lista del día se convierte en uno o varios pedidos, uno por proveedor.

**Bloqueado por:** 10 · 14.

**Status:** ready-for-human

- [x] Se elige proveedor por renglón. Por omisión se sugiere el más barato con existencia, pero **la persona decide**: hay razones que el sistema no ve —mínimo de pedido, días de entrega, crédito con cada proveedor—.

  `particion.sugerir` / `particion.elegir` (puras), `almacenamiento.elegir_proveedor`,
  `POST /api/renglon/{id}/proveedor`, `renglon.proveedor_elegido` + su firma.
  Pruebas: `test_particion.test_el_sistema_sugiere_al_mas_barato_con_existencia`,
  `test_particion.test_la_decision_le_gana_a_la_sugerencia_y_las_dos_se_ven`,
  `test_particion.test_con_empate_no_hay_sugerencia_y_los_empatados_se_ven`,
  `test_pedidos.test_el_mas_barato_con_existencia_viene_sugerido_por_omision`,
  `test_pedidos.test_la_persona_elige_y_queda_firmado`,
  `test_pedidos.test_una_decision_no_la_pisa_un_precio_mas_barato_que_llegue_despues`.

  **Lo sugerido no se guarda y lo decidido sí** —la respuesta a la pregunta del
  ticket 11, distinta a propósito y razonada en el encabezado de `particion.py`—:
  `test_pedidos.test_la_sugerencia_no_se_guarda_en_ninguna_columna`,
  `test_pedidos.test_no_hay_columna_para_lo_que_el_sistema_sugiere`,
  `test_pedidos.test_confirmar_la_sugerencia_tambien_se_guarda_como_decision`.

- [x] Un pedido sugerido se puede partir en varios pedidos, uno por proveedor.

  `particion.partir` (pura), `almacenamiento.guardar_la_particion`,
  `POST /api/pedido-sugerido/{id}/partir`, `ux_pedido_proveedor` sobre la clave
  de Doyle.
  Pruebas: `test_particion.test_la_lista_se_parte_en_un_pedido_por_proveedor`,
  `test_particion.test_dos_renglones_del_mismo_proveedor_van_en_un_solo_pedido`,
  `test_pedidos.test_la_lista_se_parte_en_un_pedido_por_proveedor`,
  `test_pedidos.test_partir_dos_veces_no_duplica_nada`,
  `test_pedidos.test_cambiar_una_eleccion_y_volver_a_partir_mueve_el_renglon`.

- [x] Los pedidos nacen en `borrador` y se pueden modificar mientras estén así.

  Columna `pedido.estado` con `ck_pedido_estado`, el `WHERE pedido.estado =
  'borrador'` del `ON CONFLICT ... DO UPDATE`, y el `EXISTS` de las otras dos
  sentencias.
  Pruebas: `test_pedidos.test_los_pedidos_nacen_en_borrador`,
  `test_pedidos.test_el_estado_del_pedido_del_ddl_es_el_que_escribe_el_codigo`,
  `test_pedidos.test_borrador_esta_en_el_glosario`,
  `test_pedidos.test_un_pedido_que_ya_no_es_borrador_no_lo_toca_volver_a_partir`
  (pone el estado a mano, como `poner_estado_del_renglon` hace desde el ticket
  10 con `en tránsito`: hoy ningún código escribe otro estado).

  **Lo que envejece y queda anotado** (hilo abierto 13 de `HANDOVER.md`):
  corregir la cantidad de un renglón ya repartido **no recalcula** el total de
  su pedido hasta que se vuelva a partir.

- [x] Un renglón pertenece a un solo pedido.

  Defendido en la tabla: `renglon.pedido_id` es **una columna** —no una tabla de
  cruce— y su `fk_renglon_pedido` pasó a llevar `pedido_sugerido_id`, apuntando
  a `ux_pedido_de_la_lista`, para que el pedido sea de **esa misma lista**.
  Pruebas: `test_pedidos.test_un_renglon_solo_cuelga_de_un_pedido_de_su_propia_lista`,
  `test_particion.test_un_renglon_pertenece_a_un_solo_pedido`,
  `test_pedidos.test_cambiar_una_eleccion_y_volver_a_partir_mueve_el_renglon`.

- [x] Un renglón sin precio de ese proveedor se puede pedir igual, marcado como precio desconocido.

  `particion.Linea` con su motivo, y `PedidoPorArmar.total_sin_iva` que da
  `None` —nunca la suma de las demás, nunca un cero— con el parcial y el conteo
  al lado.
  Pruebas: `test_particion.test_una_linea_sin_precio_deja_el_total_en_None_y_el_parcial_a_la_vista`,
  `test_particion.test_un_pedido_vacio_no_cuesta_cero`,
  `test_pedidos.test_un_renglon_sin_precio_de_ese_proveedor_se_pide_igual`,
  `test_pedidos.test_la_linea_sin_precio_va_marcada_y_nunca_en_cero`.

## El puente que este ticket escondía

`pedidos.pedido.proveedor_id` era el `pro_id` de SICAR y toda la comparación
hablaba en claves de Doyle. **El cruce no existía en ninguna parte.** Está
resuelto en `docs/decisiones/0008-*`: la identidad del pedido es la clave de
Doyle (`pedido.proveedor`, `NOT NULL`), el `proveedor_id` de SICAR es una
correspondencia que **puede faltar** (admite nulos), y el mapa vive en
`config/continental.yml` guardando el **id** y no el nombre.

Medido en atlas el 2026-09-19: `marts.dim_proveedor` tiene 22 filas, NADRO es el
1, VICMA el 8, LEVIC el 10, y **QuePharma no está** — nunca se le ha comprado.
Se le puede pedir igual:
`test_pedidos.test_a_quepharma_se_le_puede_pedir_aunque_sicar_no_lo_conozca`.
