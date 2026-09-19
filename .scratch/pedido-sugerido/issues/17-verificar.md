# 17: `continental.verificar`

**Qué construir:** un chequeo contra los datos reales, que corre en cada despliegue y señala sin reparar. No es pytest: pytest dice que el código hace lo que dice; esto dice que los datos de producción están sanos.

**Bloqueado por:** 16.

**Status:** ready-for-agent

- [ ] Partido en dos mitades: funciones **puras** que reciben datos y devuelven un informe (esas se prueban con pytest) y funciones de recolección que leen de Postgres (esas no se prueban).
- [ ] Acumula **todas** las fallas y las imprime juntas, en vez de detenerse en la primera.
- [ ] **Cada mensaje de falla incluye el comando de reparación.**
- [ ] Sale con código distinto de cero si algo falla, y `desplegar.sh` lo encadena al final.
- [ ] Invariantes mínimos: no hay dos pedidos sugeridos abiertos para el mismo día y negocio; ningún renglón en tránsito sin su pedido; ningún pedido enviado sin quién lo envió.
- [ ] Comprueba los permisos **haciendo un `SELECT 1`** sobre cada tabla de `marts` que necesita, no leyendo el catálogo del sistema: cada `dbt build` recrea tablas y se lleva los permisos por delante.
