# 17: `continental.verificar`

**Qué construir:** un chequeo contra los datos reales, que corre en cada despliegue y señala sin reparar. No es pytest: pytest dice que el código hace lo que dice; esto dice que los datos de producción están sanos.

**Bloqueado por:** 16.

**Status:** ready-for-human

- [x] Partido en dos mitades: funciones **puras** que reciben datos y devuelven un informe (esas se prueban con pytest) y funciones de recolección que leen de Postgres (esas no se prueban).
- [x] Acumula **todas** las fallas y las imprime juntas, en vez de detenerse en la primera.
- [x] **Cada mensaje de falla incluye el comando de reparación.**
- [x] Sale con código distinto de cero si algo falla, y `desplegar.sh` lo encadena al final.
- [x] Invariantes mínimos: no hay dos pedidos sugeridos abiertos para el mismo día y negocio; ningún renglón en tránsito sin su pedido; ningún pedido enviado sin quién lo envió.
- [x] Comprueba los permisos **haciendo un `SELECT 1`** sobre cada tabla de `marts` que necesita, no leyendo el catálogo del sistema: cada `dbt build` recrea tablas y se lleva los permisos por delante.

---

## Cómo quedó (2026-09-19)

`src/continental/verificar.py` y `tests/test_verificar.py` (37 pruebas, ninguna
toca Postgres). `scripts/desplegar.sh` pasó de cinco pasos a seis y los rótulos
`N/5` se ajustaron todos a `N/6`.

**La línea entre las dos mitades**, que es la casilla 1: las funciones puras
—`redactar`, `tablas_de_marts_en`, `tablas_de_pedidos_en`,
`revisar_sugeridos_abiertos`, `revisar_transito_con_pedido`,
`revisar_pedidos_enviados`, `revisar_permisos`— reciben listas y devuelven un
`Informe`, y son las únicas que se prueban. La recolección —`correr`,
`_intentar_leer`, `_filas_de_los_invariantes`— lee de Postgres y no se prueba.
`test_la_funcion_pura_no_nombra_un_motor_ni_el_reloj` lo comprueba **sobre el
árbol de sintaxis**, no de palabra: si una función pura empieza a llamar a
`motor()`, `connect()` o `now()`, la prueba se pone roja.

**La casilla 2 no se puede cumplir a medias**: `Resultado.__post_init__` se
niega a construir una falla sin comando de reparación. El olvido revienta en la
corrida, no en la revisión de código.

**El tercer invariante quedó PENDIENTE y dicho.** `pedidos.pedido` no tiene
`estado` ni `enviado_por` —llegan con los tickets 20 y 21—, así que no se
inventan: la recolección lee `select *` para averiguar la forma real de la
tabla sin consultar el catálogo, y el invariante se enciende solo el día que
las columnas existan. Está anotado en `HANDOVER.md`, hilo abierto 4.

**Falta por hacer, y no lo puede hacer un agente:** correrlo contra el Postgres
real. Continental todavía no está clonado en atlas y las tablas no se han
creado (`HANDOVER.md`). Hasta entonces, de la mitad de recolección lo único
demostrado es que falla con criterio cuando no hay `WAREHOUSE_URL`.
