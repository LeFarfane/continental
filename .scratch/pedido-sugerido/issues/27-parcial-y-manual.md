# 27: Recibido parcial y marcado manual

**Qué construir:** el caso real de todos los días: el proveedor manda la mitad. Lo que no llegó tiene que volver a la lista solo, y lo que el sistema no pudo emparejar tiene que poderse cerrar a mano.

**Bloqueado por:** 26.

**Status:** ready-for-agent

- [ ] Se puede indicar cuántas piezas llegaron de un renglón.
- [ ] Si llegó menos, el renglón queda `recibido parcial` y **la diferencia vuelve a proponerse** en el siguiente pedido sugerido.
- [ ] Se puede marcar un renglón como recibido a mano, sin propuesta del sistema: un pedido puede llegar en dos facturas, y SICAR no tiene estado parcial (`status` solo vale 1 o -1).
- [ ] Un pedido cuyos renglones llegaron todos queda `recibido`; si alguno quedó corto, `recibido parcial`.
- [ ] Todo marcado manual queda firmado con quién y cuándo.
