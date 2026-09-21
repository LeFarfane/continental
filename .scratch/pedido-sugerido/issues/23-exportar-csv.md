# 23: Exportar el pedido a CSV

**Qué construir:** el respaldo que ya se sabe que sirve: el pedido en un archivo que se abre en Excel, se manda por correo o se guarda.

**Bloqueado por:** 21.

**Status:** ready-for-human

- [x] Un CSV por pedido, con clave, descripción, cantidad, precio unitario congelado, importe y proveedor.

  `GET /api/pedido-sugerido/{lista}/pedido/{pedido}/csv`
  (`web/app.py:1029`, `exportar_el_pedido`) arma el archivo con
  `exportar.filas_del_csv` (`exportar.py:225`) y `csv_del_pedido` (`:315`).
  Las columnas están en `exportar.COLUMNAS` (`:84`): las seis del ticket, en
  su orden, más **"por qué no hay precio"**, que es la que vuelve un hueco
  información (regla 4). Las dos de dinero dicen **"sin IVA"** en su propio
  nombre y arriba del archivo va `LOS_PRECIOS_SON_SIN_IVA` (`:106`): es la
  trampa heredada de `CLAUDE.md`, y una nota que solo viva arriba se pierde en
  cuanto alguien copia la tabla a otra hoja.

  **El precio es el de ESE proveedor, congelado**, y no el más barato: las
  líneas salen de `particion.lo_que_hay_que_capturar` (`web/app.py:1102`), la
  misma función de la pantalla de captura del 22, así que el archivo y la
  pantalla no pueden contar distinto — y lo que entra es lo que el pedido
  GUARDADO tiene dentro (`renglon.pedido_id`), no la vista previa.
  **Sin precio no es `0.00` ni una celda vacía** —en Excel se ven iguales
  cuando alguien suma la columna—: es `sin precio` en precio e importe
  (`exportar.SIN_PRECIO`, `:96`) y el motivo al lado. **El total sale de
  `PedidoPorArmar.total_sin_iva`** (`exportar.py:263`), la regla del ticket 20:
  `sin saber` en cuanto una línea va sin precio, jamás la suma de las demás, con
  el parcial dicho con palabras. Y si el total guardado al armar el pedido —el
  del botón de enviar— **no coincide** con la suma de ahora, el archivo escribe
  los dos con el porqué (`:294`) en vez de elegir uno en silencio.

  Se exporta en `borrador` y en `enviado`, y el primer renglón dice cuál es:
  el borrador *"todavía no se le ha pedido a nadie; no es la constancia de un
  pedido hecho"* y el enviado lleva la firma en voz activa y el desmentido del
  ADR 0009. Los renglones descartados después de partir no van, y se dice
  cuántos. Un pedido vacío es un 409; uno que no es de esa lista, un 404; con la
  base caída, un 503 con el tipo de la falla y nunca `str(exc)` (regla 5), y
  **sin archivo a medias**: con los precios sin leer cada línea diría "no se le
  ha consultado", que sería mentira.

  La pantalla pinta el enlace en **los dos** recorridos de `pintarParticion`
  (`web/static/index.html:2818` y `:2909`) con `enlaceCsv` (`:2574`), que usa la
  URL que manda el servidor (`pedido.csv`, `web/app.py:2319`).

  Pruebas: `test_exportar.test_las_seis_columnas_del_ticket_estan_y_en_ese_orden`,
  `test_una_fila_por_renglon_del_pedido`,
  `test_el_precio_es_el_de_ESE_proveedor_y_no_el_mas_barato`,
  `test_el_importe_se_multiplica_en_decimal_y_no_en_coma_flotante`,
  `test_sin_precio_de_ese_proveedor_no_es_cero_ni_una_celda_vacia`,
  `test_con_una_linea_sin_precio_el_total_NO_es_la_suma_de_las_demas`,
  `test_el_total_guardado_al_armar_se_dice_solo_si_no_coincide`,
  `test_el_encabezado_dice_que_todo_es_sin_iva`,
  `test_un_pedido_enviado_tambien_se_exporta_y_lo_dice`,
  `test_sin_precio_la_ruta_escribe_sin_saber_y_nunca_cero`,
  `test_con_la_base_caida_el_error_no_viaja_al_navegador`.

- [x] El archivo lleva la fecha y el proveedor en el nombre.

  `exportar.nombre_del_archivo` (`exportar.py:343`):
  `pedido-2026-09-18-nadro-borrador.csv`. **La fecha es la de la lista**
  (`fecha_del_pedido`, anclada en `max(fecha)` del almacén), **nunca la del
  reloj**: un pedido armado a las 22:30 de la farmacia ya es del día siguiente
  en UTC. El proveedor es su clave de Doyle —la identidad del pedido, ADR 0008—
  pasada a ASCII. **El estado va en el nombre**, que el ticket no pide: un
  borrador guardado en una carpeta no debe poder confundirse con lo que se
  capturó. `disposicion_de_descarga` (`:358`) arma el `Content-Disposition` con
  `filename` en ASCII y `filename*` en UTF-8 (RFC 6266), porque Starlette
  codifica los encabezados en latin-1 y un carácter fuera de ahí no da un nombre
  feo: da un **500**.
  Pruebas: `test_el_nombre_lleva_la_fecha_de_la_lista_el_proveedor_y_el_estado`,
  `test_la_fecha_es_la_de_la_lista_y_no_la_del_reloj`,
  `test_un_proveedor_raro_no_rompe_el_nombre` (acentos, comillas, `../`, CRLF),
  `test_la_disposicion_es_de_descarga_y_cabe_en_un_encabezado_http`,
  `test_la_fecha_del_nombre_es_la_de_la_lista`.

- [x] Sobrevive a Excel: las claves de 13 dígitos **no** se convierten en notación científica ni pierden ceros a la izquierda. Marlowe tiene pruebas dedicadas a ese daño exacto.

  **Medido con el Excel 16 de la torre (es-MX) el 2026-09-21**, abriendo por
  COM y leyendo cada celda, antes de escribir código y otra vez con el archivo
  que el código produce. La clave va como **fórmula de texto**,
  `="7501234567890"` (`exportar.texto_para_excel`, `exportar.py:128`): cruda
  se ve `7.5012E+12` y `0012345678905` pasa a **valer** `12345678905`; con un
  tabulador o un apóstrofo al frente, Excel deja el tabulador o el apóstrofo
  **literales** en la celda. Una descripción que empieza con `=`, `+`, `-` o `@`
  también (`_celda`, `:139`): medido, `-GUION` sale `#¿NOMBRE?` y `=1+1` sale
  `2`. UTF-8 **con BOM** (sin él, `ÃCIDO FÃ“LICO`), coma y punto decimal —la
  configuración de México, medida— y **sin `sep=,`**, que en es-MX sobra y,
  medido, hace que Excel ignore el BOM. Con el archivo real: claves como texto
  con sus ceros, acentos bien, precios como número (`Double`) y **cero celdas
  con error**.
  Pruebas: `test_la_clave_va_como_formula_de_texto`,
  `test_la_clave_con_ceros_a_la_izquierda_los_conserva`,
  `test_ninguna_celda_lleva_un_numero_largo_desnudo`,
  `test_una_descripcion_que_empieza_como_formula_no_se_evalua` (seis casos),
  `test_la_proteccion_dobla_las_comillas_de_adentro`,
  `test_el_archivo_empieza_con_bom_para_que_excel_lea_los_acentos`,
  `test_separador_coma_decimal_punto_y_fin_de_linea_de_windows`,
  `test_lo_que_se_escribe_es_lo_que_se_lee` (en `tmp_path`).

- [x] El CSV se regenera cuando se pida; no se guarda en git ni se respalda.

  **Se arma en memoria en cada petición y nunca se escribe**: `exportar.py` no
  importa nada con qué abrir un archivo ni una conexión y devuelve bytes, y la
  ruta los sirve con un `Response` (`web/app.py:1029`). No hay copia en disco
  que respaldar ni que envejecer — el de ayer diría `borrador` de un pedido que
  hoy ya se envió. **`.gitignore` gana `pedido-*.csv`** (`.gitignore:21`), el
  cinturón para el archivo que una persona baje y guarde dentro del repo: lleva
  datos de compra de la farmacia. `data/export/` se queda donde estaba, con su
  comentario corregido: hoy nada escribe ahí.
  Pruebas: `test_exportar_no_toca_la_red_la_base_ni_el_disco`,
  `test_la_ruta_no_escribe_un_solo_archivo_en_el_repo`,
  `test_regenerarlo_da_el_mismo_archivo` (sin reloj dentro: mismos bytes),
  `test_regenerarlo_trae_lo_de_ahora`,
  `test_gitignore_tapa_el_csv_que_alguien_baje_dentro_del_repo`.

## Lo que se decidió, y dónde está escrito

`docs/decisiones/0011-el-csv-del-pedido-se-arma-en-memoria-y-se-escribe-para-excel.md`:
en memoria y no en `data/export/`; la fórmula de texto contra la clave cruda, el
tabulador, el apóstrofo, un `.xlsx` y la defensa de Marlowe al leer; coma y BOM
contra la receta de España; y la ruta colgada de la lista para no escribir SQL
nuevo. **No hay migración ni tabla nueva**: el despliegue de este ticket es solo
código.

## Lo aprendido

- **La defensa de Marlowe no se podía copiar, solo su lección.** Marlowe
  rechaza la clave en notación científica **al leer**, porque su CSV es de
  entrada. Éste es de salida: Continental no lo lee nunca, así que la defensa
  tiene que ir al escribir. Lo que sí se copió tal cual es el BOM.
- **Dos de las tres recetas que circulan para "texto en Excel" no sirven en un
  CSV.** El apóstrofo funciona al teclear en una celda, no al abrir un CSV: ahí
  queda como apóstrofo. El tabulador queda como tabulador. Solo lo supe
  midiéndolo; las dos habrían pasado cualquier prueba escrita a ciegas.
- **La coma no es un problema en México.** La preocupación "coma decimal contra
  coma separadora" es de España; la torre es es-MX, lista `,` y decimal `.`.
- **El recorrido del navegador cazó una cosa**, esta vez cosmética: el enlace
  salía con el azul por omisión del navegador, que en el tema oscuro casi no se
  lee. Ahora usa la tinta de la pantalla, subrayado. Lo demás salió bien:
  descarga con la pantalla de trabajo intacta (el enlace va en otra pestaña),
  y **el pedido recién enviado conserva su enlace** — cae en el segundo
  recorrido de `pintarParticion`, que es justo donde el ticket 21 perdió el
  pedido entero.

## Lo que quedó sin hacer, y por qué

- **El precio es la última lectura de ese proveedor, no la que había al
  enviar.** Para un pedido enviado, "el precio al que se decidió" sería la
  lectura más reciente **anterior** a `armado_en`, y `precios_de_la_lista` solo
  devuelve la última. Leer la historia pediría SQL nuevo que desde la torre no
  se puede probar contra Postgres. Mientras tanto el archivo **no miente**: si
  la suma de ahora no coincide con el total guardado, escribe los dos con el
  porqué. Es la mitad del hilo 13 de `HANDOVER.md` que sigue abierta; misma
  condición de disparo: un total que no cuadra contra una factura.
- **Las horas van en UTC**, diciéndolo. Escribirlas en hora de la farmacia pide
  una zona que el servidor no tiene (la torre no tiene `tzdata`). Solo hay una
  hora en el archivo, la del envío.
- **Solo se midió en es-MX.** Un Excel con coma decimal no se probó. Condición:
  si el archivo se va a abrir en otra configuración regional.
- **Una descripción que parezca fecha o número entero** (`1500`, `12-24`) no se
  protege: Excel la convertiría. No se vio ninguna así y protegerlas todas
  pondría `="..."` en cada renglón.
- **Qué escribe Excel si alguien guarda el archivo encima** no se midió. Nada
  en Continental lo vuelve a leer.
