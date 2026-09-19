# 13: El emparejamiento por EAN

**Qué construir:** la garantía de que los cuatro proveedores están hablando del mismo producto. Sin esto, la comparación puede poner una caja de 30 contra una de 60 y decir que la segunda es más barata.

**Bloqueado por:** 12.

**Status:** ready-for-agent

- [x] Una función pura recibe lo que devolvió un proveedor y la clave buscada, y devuelve precio aceptado o **motivo de rechazo**.
- [x] NADRO y LEVIC emparejan por EAN de 13 dígitos directo.
- [x] **VICMA se acepta únicamente si la búsqueda del EAN devuelve exactamente un resultado**, porque muestra código interno y no el EAN.
- [x] QuePharma usa código interno: lo que no empareja queda **sin dato**, con su motivo.
- [x] `sin dato` nunca se muestra como cero, como vacío, ni como "más caro". Es un hueco declarado.
- [x] Hay una prueba por caso: empareja, dos resultados, cero resultados, el proveedor falló.
- [x] Marlowe ya se equivocó aquí: una caja de 60 más barata por pieza se veía como más cara, sin fallar y sin avisar.

**Sobre la última casilla, con precisión (2026-09-19).** El emparejamiento por
EAN **sí** impide el error de Marlowe en NADRO, LEVIC y QuePharma: la caja de 60
tiene otro código de barras, así que su precio no puede entrar como el de la de
30 (`test_la_caja_de_60_mas_barata_por_pieza_no_se_cuela_como_precio_de_la_de_30`).

**En VICMA no lo impide, y hay que decirlo en vez de suponerlo.** A VICMA se le
acepta el único resultado sin poder compararlo con nada, porque su portal
muestra código interno: quien garantiza que sea el producto buscado es el
índice de VICMA, no este código. Si ese índice devolviera la presentación
equivocada para un EAN, entraría un precio equivocado sin que nada fallara. Lo
único que se hace contra eso es dejar la evidencia a la vista —el código y la
descripción del portal se guardan y viajan a la pantalla— para que una persona
lo cace de un vistazo. Está escrito como prueba, con ese nombre, en
`test_vicma_se_acepta_a_ciegas_y_por_eso_guarda_la_evidencia`.

**Nada de esto se demostró contra los portales reales**: las cuatro sesiones de
Doyle siguen caducadas (hilo 1 de `HANDOVER.md`) y este ticket no las abrió. Lo
que hay son 64 pruebas sobre la función pura, escritas contra la forma exacta
que devuelve Doyle.

**No hizo falta una migración `0004`:** el ticket 13 no estrenó vocabulario.
`no empareja` ya estaba en el `CHECK` desde el ticket 12 —reservado justo para
esto— y lo que cambió es **quién lo escribe**. Los motivos siguen siendo ocho.
