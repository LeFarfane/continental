# 04: Mandar a espera un renglón desde Captura, con su proveedor

**What to build:** cada renglón de la pantalla de captura lleva «Mandar a
espera». El renglón queda en espera (`pospuesto`), firmado, **recordando a qué
proveedor se le iba a pedir**, y sale del pedido y de su total. «Sacar de la
espera» lo regresa al pedido de ese proveedor. Mandar a espera desde Revisar
también guarda el proveedor si ya lo hay. Ver la enmienda 2026-10-05 al ADR
0025 (puntos 2 y 6) y el spec, «Mandar a espera», historias 7–15.

**Blocked by:** 02

**Status:** ready-for-agent

- [x] Migración nueva (después de la 0019) en el renglón: proveedor de la
      espera, desde cuándo espera, cuántas listas lleva. Con sus CHECK, y los
      mismos CHECK repetidos en Python.
- [x] Al mandar a espera se guarda el proveedor: el del pedido al que estaba
      repartido; si no estaba repartido, el elegido a mano; si no hay ninguno,
      vacío. El renglón deja de pertenecer a su pedido, en la misma
      transacción.
- [x] La primera vez, «desde cuándo» es la fecha de la lista y el contador vale 1.
- [x] Un renglón tachado (capturado) no se manda a espera: el servidor lo
      rechaza con su motivo (en `transiciones`), y el botón lo dice.
- [x] Sacar de la espera lo regresa al pedido de su proveedor si ese pedido
      sigue en `borrador`; si no, vuelve sin repartir y se dice por qué.
- [x] El total del pedido (ticket 03, si ya está) baja al mandar a espera.
- [x] Pruebas en los cuatro niveles: lo puro (de qué proveedor hereda), el doble
      y el SQL como texto (sale del pedido, respeta lo tachado), las rutas de
      punta a punta y la estática del JS para el botón de Captura.
