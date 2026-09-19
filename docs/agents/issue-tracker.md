# Issue tracker: markdown local

Los issues y los specs de este repo viven como archivos markdown en `.scratch/`.

**Por qué aquí y no en GitHub:** Continental no tiene remoto todavía y el CLI
`gh` no está instalado en esta máquina (2026-09-18). Doyle y Marlowe sí están en
GitHub (`LeFarfane/Doyle`, `LeFarfane/marlowe`), así que lo natural es que este
repo termine ahí también. **El día que exista el remoto, esto se cambia
reescribiendo este archivo** con las convenciones de `gh issue create` / `gh
issue view`; nada más depende de esta decisión.

`.scratch/` **se versiona**: es git quien respalda el trabajo de diseño, igual
que respalda los ADRs.

## Convenciones

- Una funcionalidad por carpeta: `.scratch/<slug-de-la-funcionalidad>/`
- El spec es `.scratch/<slug>/spec.md`
- Los tickets de implementación van uno por archivo en
  `.scratch/<slug>/issues/<NN>-<slug>.md`, numerados desde `01`. **Nunca** un
  solo archivo con todos los tickets juntos.
- El estado de triage se anota en una línea `Status:` cerca del principio de
  cada archivo de ticket (los valores están en `triage-labels.md`).
- Los comentarios y la conversación se agregan al final del archivo, bajo un
  encabezado `## Comentarios`.

## Cuando una skill dice "publica al issue tracker"

Crea un archivo nuevo bajo `.scratch/<slug>/`, creando la carpeta si hace falta.

## Cuando una skill dice "trae el ticket correspondiente"

Lee el archivo en la ruta indicada. Normalmente el usuario pasa la ruta o el
número de ticket directo.

## Operaciones de wayfinding

Las usa `/wayfinder`. El **mapa** es un archivo con un archivo **hijo** por
ticket.

- **Mapa**: `.scratch/<esfuerzo>/map.md` (Notas / Decisiones hasta ahora /
  Niebla).
- **Ticket hijo**: `.scratch/<esfuerzo>/issues/NN-<slug>.md`, numerado desde
  `01`, con la pregunta en el cuerpo. Una línea `Type:` anota el tipo
  (`research`/`prototype`/`grilling`/`task`); una línea `Status:` anota
  `claimed`/`resolved`.
- **Bloqueo**: una línea `Blocked by: NN, NN` cerca del principio. Un ticket
  está desbloqueado cuando todos los archivos que lista están `resolved`.
- **Frontera**: recorre `.scratch/<esfuerzo>/issues/` buscando los abiertos, sin
  bloqueo y sin reclamar; gana el de número más bajo.
- **Reclamar**: pon `Status: claimed` y guarda antes de trabajar.
- **Resolver**: agrega la respuesta bajo un encabezado `## Respuesta`, pon
  `Status: resolved`, y agrega el puntero de contexto a las Decisiones hasta
  ahora del `map.md`.
