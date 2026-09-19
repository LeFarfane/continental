# 20: Elegir proveedor y partir el sugerido en pedidos

**Qué construir:** el paso donde la comparación se vuelve una decisión. El encargado marca a quién le pide cada renglón, y la lista del día se convierte en uno o varios pedidos, uno por proveedor.

**Bloqueado por:** 10 · 14.

**Status:** ready-for-agent

- [ ] Se elige proveedor por renglón. Por omisión se sugiere el más barato con existencia, pero **la persona decide**: hay razones que el sistema no ve —mínimo de pedido, días de entrega, crédito con cada proveedor—.
- [ ] Un pedido sugerido se puede partir en varios pedidos, uno por proveedor.
- [ ] Los pedidos nacen en `borrador` y se pueden modificar mientras estén así.
- [ ] Un renglón pertenece a un solo pedido.
- [ ] Un renglón sin precio de ese proveedor se puede pedir igual, marcado como precio desconocido.
