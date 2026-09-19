# 05: Clasificación por anaquel

**Qué construir:** cada renglón sabe si es medicamento, abarrote o algo que nadie clasificó, leyendo el anaquel físico y no la etiqueta de catálogo.

**Bloqueado por:** 03.

**Status:** ready-for-agent

- [ ] Una función pura recibe anaquel y categoría y devuelve `medicamento`, `abarrote` o `sin clasificar`.
- [ ] Medicamento son los anaqueles de patente, genérico, naturista, botica y vitrina. Botica entra porque se le compra a los mismos proveedores.
- [ ] Abarrote son super, canasta y refrigerador, más las categorías de super y electrónica: compiten contra la tienda de la esquina, no contra una farmacia.
- [ ] Las listas se leen de `config/continental.yml`, no van escritas en el código.
- [ ] Un anaquel mal escrito (hay 5 así en el catálogo) no revienta la clasificación: cae en `sin clasificar`.
- [ ] Cada renglón de la lista expone su clasificación.
