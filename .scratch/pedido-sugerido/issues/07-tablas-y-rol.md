# 07: Las tablas del pedido y el rol acotado

**Qué construir:** el lugar donde va a vivir el pedido, con un rol de Postgres que solo puede hacer lo suyo. El permiso es la garantía; las reglas escritas son un cinturón adicional.

**Bloqueado por:** 03.

**Status:** ready-for-agent

- [ ] Tres tablas: el pedido sugerido (uno por día y negocio, con **hasta qué momento de ventas consideró**), el renglón y el pedido por proveedor.
- [ ] **Toda fila lleva el código de negocio**, aunque hoy siempre valga el mismo.
- [ ] El dinero es decimal explícito, nunca coma flotante.
- [ ] El DDL se corre **a mano**, una vez, con credenciales de dueño, separado del código de todos los días: el rol acotado no debe poder crear tablas.
- [ ] `crear_rol.sql` otorga lo mínimo: escribir sus tres tablas, y **solo leer** de `marts` lo que necesita (ventas, catálogo, fechas, compras, proveedores).
- [ ] Verificado a mano que el rol **no** puede crear tablas ni leer el resto del almacén.
