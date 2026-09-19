# 07: Las tablas del pedido y el rol acotado

**Qué construir:** el lugar donde va a vivir el pedido, con un rol de Postgres que solo puede hacer lo suyo. El permiso es la garantía; las reglas escritas son un cinturón adicional.

**Bloqueado por:** 03.

**Status:** ready-for-agent

- [x] Tres tablas: el pedido sugerido (uno por día y negocio, con **hasta qué momento de ventas consideró**), el renglón y el pedido por proveedor.
- [x] **Toda fila lleva el código de negocio**, aunque hoy siempre valga el mismo.
- [x] El dinero es decimal explícito, nunca coma flotante.
- [x] El DDL se corre **a mano**, una vez, con credenciales de dueño, separado del código de todos los días: el rol acotado no debe poder crear tablas.
- [x] `crear_rol.sql` otorga lo mínimo: escribir sus tres tablas, y **solo leer** de `marts` lo que necesita (ventas, catálogo, fechas, compras, proveedores).
- [ ] Verificado a mano que el rol **no** puede crear tablas ni leer el resto del almacén.

> **La última casilla queda pendiente de una persona.** No hay Postgres
> alcanzable desde la torre: el almacén vive en Docker en atlas, Docker Desktop
> no está corriendo y nada escucha en el 5432 (verificado el 2026-09-19). La
> verificación quedó escrita como un guion que se corre y **da un veredicto**,
> caso por caso, con lo que esperaba y lo que encontró:
>
> ```bash
> docker exec -i farmacia_warehouse psql -U farmacia -d farmacia -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
> ```
>
> Salida 0 = el rol quedó bien. Distinta de cero = alguna de las 17
> comprobaciones falló, y la tabla dice cuál. Antes hay que correr
> `sql/crear_tablas.sql` y `sql/crear_rol.sql`, en ese orden y con las mismas
> credenciales de dueño.
