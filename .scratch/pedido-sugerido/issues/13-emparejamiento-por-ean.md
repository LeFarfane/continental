# 13: El emparejamiento por EAN

**Qué construir:** la garantía de que los cuatro proveedores están hablando del mismo producto. Sin esto, la comparación puede poner una caja de 30 contra una de 60 y decir que la segunda es más barata.

**Bloqueado por:** 12.

**Status:** ready-for-agent

- [ ] Una función pura recibe lo que devolvió un proveedor y la clave buscada, y devuelve precio aceptado o **motivo de rechazo**.
- [ ] NADRO y LEVIC emparejan por EAN de 13 dígitos directo.
- [ ] **VICMA se acepta únicamente si la búsqueda del EAN devuelve exactamente un resultado**, porque muestra código interno y no el EAN.
- [ ] QuePharma usa código interno: lo que no empareja queda **sin dato**, con su motivo.
- [ ] `sin dato` nunca se muestra como cero, como vacío, ni como "más caro". Es un hueco declarado.
- [ ] Hay una prueba por caso: empareja, dos resultados, cero resultados, el proveedor falló.
- [ ] Marlowe ya se equivocó aquí: una caja de 60 más barata por pieza se veía como más cara, sin fallar y sin avisar.
