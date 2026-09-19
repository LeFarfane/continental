# Documentación de dominio

Cómo deben consumir las skills de ingeniería la documentación de dominio de este
repo al explorar el código.

## Antes de explorar, lee esto

- **`CONTEXT.md`** en la raíz: el glosario del negocio.
- **`docs/decisiones/`**: los ADRs que tocan el área en la que vas a trabajar.

> **Ojo con la ruta.** La plantilla original de estas skills dice `docs/adr/`.
> En este repo —y en sus hermanos `Doyle`, `Marlowe` y `farmacia-data`— los ADRs
> viven en **`docs/decisiones/`**, en español y numerados desde `0001`. No es un
> despiste: es la convención de los cuatro repos, escrita en sus `CLAUDE.md`.
> No crees `docs/adr/`.

Hay ADRs fuera de este repo que igual mandan aquí, porque las decisiones se
tomaron donde vivía el problema:

- `../Doyle/docs/decisiones/` — cómo se consultan los portales de proveedor.
  El **0008** describe la mudanza a atlas y la consulta en lote, de la que
  depende el módulo de Pedido.
- `../docs/decisiones/` (farmacia-data) — el almacén, la cadena nocturna y los
  modelos de dbt. El **0017** (horario del respaldo) y el **0018** (clase
  ABC-XYZ como columna) son prerrequisitos de este repo. Los ADRs de Marlowe
  también viven ahí, del 0008 al 0016.

Si alguno de estos archivos no existe, **sigue en silencio**. No señales su
ausencia ni propongas crearlos por adelantado: `/domain-modeling` los crea
cuando de verdad se resuelve un término o una decisión.

## Estructura

Contexto único. No hay `CONTEXT-MAP.md` ni contextos por paquete: es un solo
paquete de Python.

```
/
├── CONTEXT.md
├── docs/decisiones/
│   ├── 0001-suite-como-cascara-con-modulos-por-http.md
│   └── 0002-pedido-sugerido-por-reposicion-de-lo-vendido.md
└── src/continental/
```

## Usa el vocabulario del glosario

Cuando tu resultado nombre un concepto del negocio —el título de un issue, una
propuesta de refactor, una hipótesis, el nombre de una prueba— usa el término
tal como lo define `CONTEXT.md`, **en español**. Nada de derivar a sinónimos que
el glosario evita a propósito.

Dos que se confunden seguido y que el glosario separa:

- **Proveedor** (NADRO, LEVIC, VICMA, QuePharma) es a quien le compramos.
  **Cadena** (Guadalajara, Similares…) es un competidor. Su precio no significa
  lo mismo y no se comparan entre sí.
- **Pedido sugerido** es la lista del día que arma el sistema. **Pedido** es lo
  que se le pide a un proveedor. **Renglón** es una línea de la lista.

Si el concepto que necesitas todavía no está en el glosario, eso es una señal: o
estás inventando lenguaje que el proyecto no usa (reconsidera), o hay un hueco
real (anótalo para `/domain-modeling`).

## Señala los choques con un ADR

Si lo que propones contradice un ADR existente, dilo explícito en vez de pasarle
por encima en silencio:

> _Contradice el ADR 0002 (el pedido sugerido no filtra por cobertura), pero
> vale la pena reabrirlo porque…_
