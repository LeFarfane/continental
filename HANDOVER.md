# Estado de Continental — 2026-09-18

Describe **el estado actual**, no una lista de parches por aplicar. Si algo aquí
no coincide con el código, el código manda.

**Directorio de trabajo:** `D:\AAA\5_proyectos\Farmacia\Continental`

## Qué es

La suite que junta `Doyle` (precios de proveedor), `Marlowe` (precios de
competencia) y los módulos propios detrás de una sola puerta,
`farmacia.farfanlab.uk`, para que el encargado no tenga que saber que son tres
programas distintos.

Nació el 2026-09-17 de una sesión de diseño completa: 51 preguntas, cinco ADRs
escritos antes de la primera línea de código. El glosario está en `CONTEXT.md`
y **manda sobre el nombre de cualquier cosa**.

## Qué hay hoy

**Solo el esqueleto, y está honestamente vacío.** Corre, dice si está vivo, dice
quién entró según Cloudflare Access, y le pregunta a Doyle y a Marlowe si
contestan. Nada más.

```bash
python iniciar.py     # http://127.0.0.1:8585
pytest                # 4 pruebas
```

| Archivo | Qué es |
|---|---|
| `CONTEXT.md` | el glosario del negocio: pedido sugerido, renglón, pedido, sus estados |
| `CLAUDE.md` | las reglas no negociables y las trampas heredadas |
| `docs/decisiones/0001` | la suite como cáscara con módulos por HTTP |
| `docs/decisiones/0002` | el módulo de Pedido: reposición 1 a 1, EAN, recepción sugerida |
| `config/continental.yml` | puertos de los módulos y los parámetros del pedido |
| `src/continental/web/app.py` | `/api/salud`, `/api/modulos`, la portada |

## Lo que falta, en orden

1. **Doyle se muda a atlas** (ADR 0008 de Doyle): visor remoto sobre Xvfb para
   abrir sesión, lote que reutiliza un navegador por proveedor, y Doyle sin
   interfaz propia. **Va primero a propósito**: es lo que puede fallar por
   razones que no controlamos —VICMA sin ventana, el captcha de LEVIC, si el
   Chrome de Google arranca en ese CPU de 2010—, y descubrirlo mientras además
   se construye la suite mezclaría dos fallas distintas.
2. **`clase_abc` y `clase_xyz` como columnas de `dim_producto`** en
   farmacia-data (ADR 0018). El lote nocturno necesita un orden de importancia
   desde el primer día.
3. **El módulo de Pedido.**
4. **Absorber la interfaz de Marlowe**, que pasa a ser API como Doyle. Después
   del Pedido: es reescribir una interfaz que ya funciona y no agrega ninguna
   capacidad nueva.

**Terminado, para el módulo de Pedido**, quiere decir esto y no "ya corre": un
día de operación real en que la lista se armó sola de noche con las ventas del
día anterior, trajo precios de los cuatro proveedores, una persona la revisó,
descartó lo que no iba, capturó el pedido en NADRO leyendo de la pantalla, y al
día siguiente los renglones se marcaron como probablemente recibidos cuando la
compra apareció en el almacén. **Con al menos un renglón donde NADRO no era el
más barato y se le pidió a otro.**

## Lo que todavía no existe y va a hacer falta

- `scripts/desplegar.sh` y `continental-web.service`, calcados de Marlowe:
  `pull`, compila, pruebas, y **solo entonces** reinicia. Marlowe aprendió el
  2026-09-08 por qué: se desplegó un `app.py` que no compilaba y el servicio
  quedó en bucle mientras el dueño trabajaba contra un servidor que no existía.
- El rol `continental` en Postgres y sus tablas (`sql/crear_rol.sql`).
- El remoto de GitHub y la llave de despliegue de solo lectura para atlas.
- La ruta del túnel de Cloudflare para `farmacia.farfanlab.uk`, con Access
  delante.

## Hilos abiertos

1. **El horario del respaldo de SICAR está en `propuesta`** (ADR 0017 de
   farmacia-data): lo decide el dueño. Si se acepta mover el respaldo a las
   ~20:15, **hay que mover el timer de la cadena a las 21:00 en el mismo
   movimiento**, o el colchón baja de hora y media a 15 minutos.
2. **Falta probar `google-chrome --version` en atlas.** Si ese CPU de 2010 no
   lo aguanta, Doyle usa el Chromium de `apt` —que ya está medido— y la parte
   del ADR 0004 que dependía de Chrome queda cerrada.
3. **Qué hay en VITRINA 1-3.** Entró a la lista blanca de "medicamento" a
   petición del dueño, pero nadie escribió qué se guarda ahí.
4. **QuePharma casi seguro va a quedar fuera de la comparación**: usa código
   interno y no está confirmado que encuentre por EAN. Hay dos pendientes
   viejos de Doyle que responden esto —probar el EAN en QuePharma, y confirmar
   VICMA por cantidad de resultados—, y ahora sí importan.
5. **El almacén de contraseñas de atlas baja una garantía.** Hoy no hay ninguna
   contraseña de proveedor en disco; después de la mudanza habrá cuatro,
   ofuscadas pero recuperables. Está aceptado con mitigación (permisos `700`,
   fuera de respaldos) en el ADR 0008 de Doyle. Si alguien saca una copia del
   disco, se cambian las cuatro contraseñas.
