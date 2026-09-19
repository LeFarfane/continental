# 23: Exportar el pedido a CSV

**Qué construir:** el respaldo que ya se sabe que sirve: el pedido en un archivo que se abre en Excel, se manda por correo o se guarda.

**Bloqueado por:** 21.

**Status:** ready-for-agent

- [ ] Un CSV por pedido, con clave, descripción, cantidad, precio unitario congelado, importe y proveedor.
- [ ] El archivo lleva la fecha y el proveedor en el nombre.
- [ ] Sobrevive a Excel: las claves de 13 dígitos **no** se convierten en notación científica ni pierden ceros a la izquierda. Marlowe tiene pruebas dedicadas a ese daño exacto.
- [ ] El CSV se regenera cuando se pida; no se guarda en git ni se respalda.
