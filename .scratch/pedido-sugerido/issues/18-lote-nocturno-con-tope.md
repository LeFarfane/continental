# 18: El lote nocturno corre y respeta el tope

**Qué construir:** que en la mañana la lista ya traiga precios sin que nadie los pida. Consulta sola después de la cadena nocturna, en orden de importancia, y se detiene a los 60 minutos.

**Bloqueado por:** 15 · 16 · **bloqueo externo:** la columna de clase ABC en el catálogo (ADR 0018 de farmacia-data) y Doyle corriendo en atlas (ADR 0008 de Doyle).

**Status:** ready-for-agent

- [ ] Un timer de systemd lo dispara después de la cadena de las 20:30.
- [ ] Consulta en orden de importancia, leyendo la **clase ABC** del catálogo. Sin esa columna el orden especificado no se puede cumplir: es prerrequisito, no detalle.
- [ ] Se detiene a los 60 minutos. Lo que no alcanzó queda marcado como faltante por tope, no como error.
- [ ] Reutiliza el navegador por proveedor en vez de arrancar uno por consulta (ADR 0008 de Doyle), y respeta la cortesía entre productos.
- [ ] Un proveedor que falla no tumba el lote: los otros tres siguen.
- [ ] La corrida queda en bitácora con cuántos renglones consultó, cuántos quedaron sin precio y por qué.
- [ ] El lote no puede dejar la lista en un estado peor que antes de correr: si truena a la mitad, lo consultado se queda guardado.
