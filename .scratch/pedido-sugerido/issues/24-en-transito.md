# 24: En tránsito

**Qué construir:** la memoria de lo ya pedido. Es lo que arregla el problema que hoy existe: si el martes se piden 3 piezas y llegan el jueves, el miércoles el producto sigue vendido y con existencia baja, y se vuelve a pedir.

**Bloqueado por:** 09 · 21.

**Status:** ready-for-agent

- [ ] Un renglón `en tránsito` **no** vuelve a proponerse en el siguiente pedido sugerido.
- [ ] Los renglones en tránsito se ven en algún lado, con su proveedor y la fecha en que se enviaron.
- [ ] Si el mismo producto se vuelve a vender mientras está en tránsito, esa venta no se pierde: queda contabilizada para cuando el renglón se cierre.
- [ ] La pantalla del día muestra los renglones en tránsito atenuados con "pedido el martes, sin recibir" en vez de esconderlos: un hueco visible es información.
- [ ] Queda claro que esto solo protege si el pedido pasó por Continental: un pedido capturado por fuera se va a proponer otra vez.
