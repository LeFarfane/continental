# 06: Mandar a espera el pedido entero

**What to build:** en la pantalla de captura, cada pedido lleva un botón
«Mandar a espera» que manda de una vez **todos sus renglones abiertos y no
tachados** a la espera, con su proveedor. Lo tachado ya está en el carrito del
portal y se queda. La pantalla dice cuántos se mandaron y cuántos se quedaron.
Ver la enmienda 2026-10-05 al ADR 0025 (punto 6) y el spec, historias 16–19.

**Blocked by:** 04

**Status:** done

- [x] Es **una sola operación del servidor** en una transacción, no un ciclo de
      clics en el navegador.
- [x] Manda solo lo abierto y no tachado; contesta cuántos mandó y cuántos se
      quedaron por estar tachados.
- [x] La frase lo dice: *«Se mandaron 6 a espera; 3 ya tachados se quedan:
      bórralos del carrito del portal o destáchalos primero.»*
- [x] Un pedido que se queda sin renglones se ve vacío, no como enviado.
- [x] Solo con la lista editable y el pedido en `borrador`; si no, el motivo.
- [x] Pruebas: el doble y el SQL como texto (respeta lo tachado, una
      transacción), la ruta de punta a punta y la estática del JS para el botón.
