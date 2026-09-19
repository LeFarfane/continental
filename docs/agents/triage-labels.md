# Etiquetas de triage

Las skills hablan de cinco papeles canónicos de triage. Esta tabla los mapea a
las cadenas de texto que de verdad se usan en el tracker de este repo.

Como el tracker es markdown local y nació con este archivo, **no había
vocabulario previo con el que chocar**: cada etiqueta vale igual que su papel.

| Papel en las skills | Etiqueta en nuestro tracker | Significado                                     |
| ------------------- | --------------------------- | ----------------------------------------------- |
| `needs-triage`      | `needs-triage`              | Falta que una persona lo evalúe                 |
| `needs-info`        | `needs-info`                | Esperando información de quien lo reportó       |
| `ready-for-agent`   | `ready-for-agent`           | Especificado por completo, listo para un agente |
| `ready-for-human`   | `ready-for-human`           | Necesita que lo implemente una persona          |
| `wontfix`           | `wontfix`                   | No se va a atender                              |

Cuando una skill mencione un papel ("aplica la etiqueta de listo para agente"),
usa la cadena de la columna de en medio.

En el tracker local, la etiqueta se escribe en la línea `Status:` del archivo,
cerca del principio. Ver `issue-tracker.md`.
