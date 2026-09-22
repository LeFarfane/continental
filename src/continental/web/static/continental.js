const fila = (texto, ok, detalle) => {
  const li = document.createElement('li');
  const punto = document.createElement('span');
  punto.className = 'punto' + (ok === true ? ' ok' : ok === false ? ' mal' : '');
  const nombre = document.createElement('span');
  nombre.textContent = texto;
  li.append(punto, nombre);
  if (detalle) {
    const d = document.createElement('span');
    d.className = 'detalle';
    d.textContent = detalle;
    li.append(d);
  }
  return li;
};

const pintar = (id, filas) => {
  const ul = document.getElementById(id);
  ul.replaceChildren(...filas);
};

// ------------------------------------------------------- el pedido sugerido

// La fecha se arma a mano y NO con `new Date('2026-09-16')`.
// Ese constructor interpreta una fecha sola como UTC, y aquí el reloj va en
// UTC-6: el navegador mostraría "lunes 15" para el dato del martes 16. Sería
// la misma trampa de zona horaria que ya costó 11.7 puntos de crecimiento
// inventados, pero del lado del cliente.
const enPalabras = (iso) => {
  const [a, m, d] = iso.split('-').map(Number);
  const fecha = new Date(a, m - 1, d);
  // El día de la semana va a propósito: "el viernes 12" y "el martes 16" no se
  // confunden, y una fecha sola sí. Es el criterio del ticket.
  return fecha.toLocaleDateString('es-MX', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
  }).replace(',', '');
};

// El día sin el mes ni el año, para el extremo izquierdo de un rango que cae
// en el mismo mes: "del viernes 11 al lunes 14 de septiembre de 2026" se lee de
// un vistazo, y repetir el mes y el año dos veces no agrega nada. Arma la fecha
// a mano por la misma razón que `enPalabras`.
const diaEnPalabras = (iso) => {
  const [a, m, d] = iso.split('-').map(Number);
  return new Date(a, m - 1, d)
    .toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric' })
    .replace(',', '');
};

// De qué día a qué día de ventas salió la lista. Desde el ticket 09 la ventana
// acumula desde el corte del último cerrado, así que casi nunca es un solo día:
// decir solo la fecha final sería ENGAÑOSO —"Ventas del lunes 14" con una
// ventana que arranca el viernes 11 hace creer que lo del fin de semana no
// está, y el encargado no tiene cómo saber que sí—. Los dos extremos entran.
const rangoEnPalabras = (desde, hasta) => {
  if (!desde || desde === hasta) return 'del ' + enPalabras(hasta);
  const mismoMes = desde.slice(0, 7) === hasta.slice(0, 7);
  return 'del ' + (mismoMes ? diaEnPalabras(desde) : enPalabras(desde)) +
    ' al ' + enPalabras(hasta);
};

// `armado_en` y `cerrado_en` SÍ pasan por `new Date(...)`, y eso no contradice
// la nota de arriba: aquélla es sobre una fecha SOLA —el constructor la
// interpreta como UTC y con el reloj en UTC-6 pintaría el día anterior—;
// éstos son instantes completos CON zona (`2026-09-19T19:04:33+00:00`), que es
// justo lo que ese constructor sabe leer sin adivinar nada. El servidor los
// manda con zona a propósito para que esto sea cierto.
const instanteEnPalabras = (iso) => new Date(iso).toLocaleString('es-MX', {
  weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'
}).replace(',', '');

const plural = (n, singular, pluralizado) => n + ' ' + (n === 1 ? singular : pluralizado);

// Un renglón de aviso. Recibe el id porque hay dos —el hueco del catálogo y
// el conteo de los sin anaquel—: son cosas distintas, se arreglan en dos
// lugares distintos de SICAR, y amontonarlas en un solo párrafo haría que la
// segunda tapara a la primera.
const nota = (id, texto, clase) => {
  const p = document.getElementById(id);
  p.className = 'nota' + (clase ? ' ' + clase : '');
  p.textContent = texto;
  p.hidden = !texto;
};

// ------------------------------------------ cuando no hay respuesta (ticket 29)

// LAS ÚNICAS FRASES DE FALLA QUE ESCRIBE ESTE ARCHIVO, y viven aquí juntas. Todas
// las demás llegan hechas del servidor —`detalle`, `frase` y `que_hacer`— desde
// Python, donde hay pruebas. Éstas no pueden: son justo los casos en que NO hay
// respuesta del servidor, o lo que llegó no es suyo.
//
// "Continental no contestó" seguido de que lo apretado seguía igual, que era
// lo que decían los botones, afirmaba algo que no se sabe: la petición pudo llegar y aplicarse
// antes de que se perdiera la respuesta (un 524 del túnel pasa a los 100 s con
// el servidor todavía trabajando). Por eso al guardar se manda a MIRAR.
const SIN_RESPUESTA = {
  red: 'No llegó respuesta de Continental: o se cortó la conexión, o Continental no está corriendo.',
  no_es_de_continental: 'Llegó una respuesta que no es de Continental (código {codigo}): lo que está en medio, el túnel, no lo alcanzó.',
  al_leer: 'Vuelve a cargar la página en un minuto. Si sigue igual, avísale {a_quien}.',
  al_guardar: 'No se sabe si se guardó: la petición pudo llegar antes de que se perdiera la respuesta. Vuelve a cargar la página para ver cómo quedó antes de intentarlo otra vez; si sigue igual, avísale {a_quien}.',
};

// A quién avisarle. Sale de `/api/salud` —del YAML, no de aquí— en cuanto la
// pantalla carga; mientras tanto, lo que el servidor dice por omisión.
let A_QUIEN_AVISAR = 'a quien administra atlas';

// TODA respuesta del servidor pasa por aquí, y aquí NUNCA se truena. Devuelve
// siempre un objeto; si algo salió mal, con `ok: false`, `detalle` y
// `que_hacer`, igual que las fallas que manda el servidor:
//
// - `fetch` rechaza (la red, o Continental apagado): `SIN_RESPUESTA.red`.
// - Llega algo que no es JSON (el 502 del túnel es HTML): hasta el ticket 29
//   dos botones se quedaban apagados para siempre con esto, porque su
//   lectura del JSON estaba fuera del `try`.
// - Llega un JSON que no es 2xx y no dice `ok` (un servidor viejo): se trata
//   como falla. Un 500 que se leyera como datos es exactamente cómo la lista
//   decía "el almacén no tiene ni una venta" sobre un servidor que tronó.
//
// `cuando` elige qué hacer: 'al_leer' (la de omisión) o 'al_guardar'.
const respuestaDe = async (peticion, cuando = 'al_leer') => {
  const sinRespuesta = (detalle) => ({
    ok: false,
    sin_respuesta: true,
    detalle,
    que_hacer: SIN_RESPUESTA[cuando].replace('{a_quien}', A_QUIEN_AVISAR),
  });
  let respuesta;
  try {
    respuesta = await peticion;
  } catch (e) {
    return sinRespuesta(SIN_RESPUESTA.red);
  }
  const ajena = SIN_RESPUESTA.no_es_de_continental.replace('{codigo}', respuesta.status);
  let datos;
  try {
    datos = await respuesta.json();
  } catch (e) {
    return sinRespuesta(ajena);
  }
  if (!datos || typeof datos !== 'object' || Array.isArray(datos)) return sinRespuesta(ajena);
  if (!respuesta.ok && datos.ok !== false) {
    return { ...sinRespuesta(ajena), ...datos, ok: false };
  }
  return datos;
};

// Una falla, pintada. Lo que dice llega hecho —del servidor, o de
// `SIN_RESPUESTA`—; aquí solo se acomoda. **No depende solo del color**
// (ticket 28): lleva un rótulo escrito delante y el qué hacer con su nombre.
// Con `que_hacer` es una falla de verdad (un borde que no contestó); sin él es
// un "eso ya no se puede" del servidor, que ya dice qué hacer en su `detalle`.
// `comoAviso` la rotula "Ojo:" aunque traiga qué hacer: lo que no es una falla
// de lectura —las ventas que no han llegado— no se pinta como una.
const notaDeFalla = (id, falla, comoAviso) => {
  const p = document.getElementById(id);
  const esFalla = !!falla.que_hacer && !comoAviso;
  p.className = 'nota falla ' + (esFalla ? 'mal' : 'aviso');
  const rotulo = document.createElement('b');
  rotulo.className = 'rotulo';
  rotulo.textContent = esFalla ? 'Falla:' : 'Ojo:';
  p.replaceChildren(rotulo, ' ', falla.frase || falla.detalle || '');
  if (falla.frase && falla.detalle && !falla.frase.includes(falla.detalle)) {
    const motivo = document.createElement('span');
    motivo.className = 'motivo';
    motivo.textContent = ' (' + falla.detalle + ')';
    p.append(motivo);
  }
  if (falla.que_hacer) {
    const hacer = document.createElement('span');
    hacer.className = 'que-hacer';
    const titulo = document.createElement('b');
    titulo.textContent = 'Qué hacer: ';
    hacer.append(titulo, falla.que_hacer);
    p.append(hacer);
  }
  p.hidden = false;
};

// Lo mismo en una sola línea de texto, para los sitios que solo tienen un
// `textContent` (la nota de la captura, el detalle del cierre).
const fallaEnUnaLinea = (falla) =>
  [falla.frase || falla.detalle, falla.que_hacer].filter(Boolean).join(' ');

// Las cifras se escriben cortas: "12" y no "12.0", "2.7" y no "2.7000000001".
// Solo el granel trae decimales de verdad (5 artículos con `granel = 1`).
const cifra = (n) => Number.isInteger(n) ? String(n) : n.toFixed(1);

// Existencia y días de cobertura salen del RENGLÓN, tal como venían cuando se
// propuso. La pantalla no vuelve a preguntarle al catálogo: si lo hiciera,
// mostraría un número y la lista estaría ordenada por otro, y el día que el
// renglón se guarde (ticket 08) lo guardado no coincidiría con lo que se vio.
// `etiqueta` es el encabezado de la columna repetido en el atributo: a ancho
// de teléfono la tabla se apila y el `<thead>` deja de estar arriba de la
// cifra, así que cada número lleva su nombre pegado. Sin eso, "3" y "42 días"
// serían dos cifras sueltas.
const celdaDeCifra = (valor, etiqueta, sufijo, urgente) => {
  const td = document.createElement('td');
  td.className = 'numero';
  td.dataset.etiqueta = etiqueta;
  // `null` es "no se sabe", nunca un cero: un cero aquí se leería "agotado".
  if (valor === null || valor === undefined) {
    td.className += ' sindato';
    td.textContent = 'sin dato';
    return td;
  }
  if (urgente) td.className += ' urgente';
  td.textContent = cifra(valor) + sufijo;
  return td;
};

// El estado del glosario que saca un renglón de la lista de trabajo. Constante
// y no una cadena suelta repetida: viaja en el JSON tal cual lo guarda la
// columna (`CONTEXT.md` manda sobre el nombre de cualquier cosa) y aquí se
// compara en tres lugares.
const DESCARTADO = 'descartado';

const botonDeAccion = (texto, alHacerClic) => {
  const boton = document.createElement('button');
  boton.type = 'button';
  boton.className = 'accion';
  boton.textContent = texto;
  boton.onclick = () => alHacerClic(boton);
  return boton;
};

// La celda de la cantidad, que desde el ticket 11 es dos cosas según el estado
// de la LISTA:
//
// - lista `abierta` → un campo que se puede corregir. Se edita en su lugar y no
//   detrás de un botón "editar": la corrección es parte de revisar la lista, no
//   una excepción, y un clic extra por renglón en una lista tan larga como
//   productos distintos se vendieron es justo lo que hace que no se use.
// - lista `cerrada` o `vencida` → la cifra, a secas. El servidor lo vuelve a
//   comprobar en el `WHERE` de su UPDATE —ahí está la garantía—, pero dejar
//   teclear algo que va a rebotar enseña a ignorar los avisos.
//
// `type="number"` con `min="1"`: el navegador ya sabe teclado numérico en el
// teléfono y flechas en la computadora. El `min` NO es la defensa contra el
// cero —se salta pegando texto, y el `step` no impide escribir a mano—: la
// defensa está en el CHECK de la tabla, en el validador compartido y en la
// ruta. Aquí es comodidad, y el aviso de abajo es el que explica.
const celdaDeCantidad = (r, editable, alAjustar) => {
  const td = document.createElement('td');
  // La clase extra es para el teléfono: ahí el `<thead>` se esconde y cada
  // cifra lleva su etiqueta pegada. El `<b>` la cuelga con un `::after`, pero
  // un `input` es un elemento reemplazado y no tiene dónde colgar nada, así que
  // la etiqueta va en la celda. Se marca con una clase y no con `:has(input)`:
  // `:has` es de 2022 y el navegador del mostrador puede no tenerlo, y entonces
  // el campo se quedaría sin nombre a la vista.
  td.className = 'cantidad' + (editable ? ' editable' : '');

  if (editable) {
    const campo = document.createElement('input');
    campo.type = 'number';
    campo.className = 'cantidad-campo';
    campo.min = '1';
    campo.step = '1';
    campo.inputMode = 'numeric';
    // Lo que se pide HOY: la corrección si la hubo, y si no la propuesta. Quién
    // decide eso es el servidor (`cantidad_a_pedir`), no este archivo.
    campo.value = r.cantidad_a_pedir;
    // Con veinte campos iguales, "3" a secas no dice de qué producto es.
    campo.setAttribute('aria-label', 'Cantidad a pedir de ' + r.descripcion);
    // `change` y no `input`: se manda al salir del campo o al dar Enter, no en
    // cada tecla. Con `input`, teclear "12" mandaría primero un 1 y después un
    // 12 — dos filas de bitácora y dos escrituras por una sola decisión.
    campo.onchange = () => alAjustar(r, campo);
    // Enter guarda. El navegador dispara `change` al salir del campo, y Enter
    // fuera de un formulario no siempre cuenta como salir: se vio el
    // 2026-09-19 en el recorrido, con el 12 tecleado quedándose en la pantalla
    // sin llegar al servidor -- lo peor que puede pasar aquí, porque la cifra
    // se ve guardada y no lo está. `blur()` lo vuelve explícito y de paso
    // funciona igual en los dos navegadores.
    campo.onkeydown = (evento) => { if (evento.key === 'Enter') campo.blur(); };
    td.append(campo);
  } else {
    const numero = document.createElement('b');
    numero.textContent = r.cantidad_a_pedir;
    td.append(numero);
  }

  // Las dos cifras a la vista cuando no son la misma. Es lo que el ticket pide
  // ver, y lo que hace evidente que la propuesta del sistema NO se sobreescribió.
  if (r.difiere_de_la_propuesta) {
    const propuesta = document.createElement('span');
    propuesta.className = 'propuesta';
    propuesta.textContent = 'el sistema propuso ' + r.cantidad_propuesta;
    td.append(propuesta);
  }

  // Solo para granel: si se vendieron 2.5 y se proponen 3, la diferencia se
  // dice. Callarla haría que la propuesta no cuadre con el ticket.
  if (r.piezas_vendidas !== r.cantidad_propuesta) {
    const vendido = document.createElement('span');
    vendido.className = 'vendido';
    vendido.textContent = 'se vendieron ' + r.piezas_vendidas;
    td.append(vendido);
  }

  // Quién la cambió, a la vista. Aparece aunque la cantidad haya quedado igual
  // que la propuesta: confirmar el número del sistema también es una decisión, y
  // es la que dice que la reposición 1 a 1 acertó ese día.
  if (r.fue_ajustada) {
    const firma = document.createElement('span');
    firma.className = 'ajustada';
    firma.textContent = 'ajustada por ' + (r.ajustada_por || 'sin-identificar');
    if (r.ajustada_en) firma.title = instanteEnPalabras(r.ajustada_en);
    td.append(firma);
  }

  return td;
};

// --------------------------------------------- el precio de los proveedores

// El veredicto de un renglón: quién gana y cuánto se ahorra contra NADRO.
//
// Va debajo de los cuatro y separado por una línea porque no es un quinto
// proveedor: es la conclusión de los de arriba. Y va con PALABRAS —"el más
// barato con existencia"— y no solo con la marca de la fila, porque es la
// frase que el encargado repite en voz alta cuando decide a quién llamarle.
//
// **Las cuatro frases del ahorro son cuatro hechos distintos** y por eso son
// cuatro y no una con un número adentro:
//
// 1. Se ahorra: la resta se pudo hacer y dio a favor.
// 2. NADRO ya es el más barato: la resta se pudo hacer y dio CERO. Es el único
//    cero legítimo, y se dice con palabras para que no se lea como un hueco.
// 3. Cuesta más: NADRO era más barato y no lo tiene. No es un ahorro negativo;
//    es lo que se paga de más por comprarle a quien sí lo tiene. Decirlo al
//    revés es exactamente el error que Marlowe ya cometió con el IVA.
// 4. No se puede calcular: NADRO no dio precio, o no se le consultó. **Sale el
//    motivo, nunca un $0.00** — un cero ahí diría "da lo mismo a quién
//    comprarle", que es lo contrario de lo que pasa (regla 4 de CLAUDE.md).
const veredicto = (comparacion) => {
  const caja = document.createElement('div');
  caja.className = 'veredicto';

  // CONTRA CUÁNTOS PROVEEDORES SE COMPARÓ ESTE RENGLÓN. Es el segundo número
  // de la primera casilla del ticket 15, y va **antes** que todo lo demás de
  // la celda porque es lo que dice cuánto vale lo demás: "el más barato" con
  // dos precios y con cuatro no son la misma afirmación, y sin este renglón
  // las dos se ven idénticas.
  //
  // Los dos números son distintos a propósito —a cuántos se preguntó y
  // cuántos contestaron con una cifra— porque se arreglan distinto: al que no
  // contestó se le mira el motivo, al que no se le preguntó se le pregunta.
  const cobertura = document.createElement('span');
  cobertura.className = 'cobertura' + (comparacion.se_comparo ? '' : ' escasa');
  cobertura.textContent = comparacion.se_comparo
    ? 'Comparado contra ' + comparacion.con_precio + ' de '
      + plural(comparacion.consultados, 'proveedor consultado', 'proveedores consultados') + '.'
    : (comparacion.con_precio === 1
        ? 'Un solo precio, de ' + plural(comparacion.consultados, 'proveedor consultado', 'proveedores consultados')
          + ': no hay contra qué compararlo.'
        : 'Se consultó a ' + plural(comparacion.consultados, 'proveedor', 'proveedores')
          + ' y ninguno dio precio.');
  caja.append(cobertura);

  // Cuando SÍ hay ganador, la marca ya está pegada a su proveedor allá arriba
  // —con su palabra— y repetirla aquí sería decir dos veces lo mismo en una
  // celda de 13 rem. Lo que aquí falta decir es por qué NO lo hay: sin ganador
  // el renglón no se esconde, se explica. Una fila sin marca y sin motivo se
  // lee como un error de la pantalla.
  if (!comparacion.ganador.proveedores.length) {
    const gano = document.createElement('span');
    gano.className = 'gano nadie';
    gano.textContent = comparacion.ganador.motivo || '';
    caja.append(gano);
  }

  const a = comparacion.ahorro;
  const ahorro = document.createElement('span');
  // EL QUINTO CASO, y lo cazó el recorrido del navegador del ticket 15, no el
  // suite: NADRO único proveedor con precio. La resta se puede hacer y da cero
  // —comprarle a NADRO en vez de a NADRO no ahorra nada—, así que la frase de
  // abajo se disparaba y escribía "NADRO ya es el más barato" **justo en el
  // renglón donde el ticket prohíbe decirlo**. La marca de arriba ya decía "el
  // único que contestó" y esta línea la contradecía tres renglones más abajo.
  //
  // Va primero porque es el caso más específico, y usa la misma bandera que la
  // marca: `ganador.es_unico`, resuelta en `comparacion.py`.
  if (a.hay && a.la_referencia_gana && comparacion.ganador.es_unico) {
    ahorro.className = 'ahorro nose';
    ahorro.textContent = comparacion.nombre_de_la_referencia
      + ' fue el único que dio precio: no hay otro costo contra el que medirlo.';
  } else if (a.hay && a.la_referencia_gana) {
    ahorro.className = 'ahorro';
    ahorro.textContent = comparacion.nombre_de_la_referencia
      + ' ya es el más barato: no hay nada que ahorrar.';
  } else if (a.es_ahorro) {
    ahorro.className = 'ahorro gana';
    ahorro.textContent = 'Ahorro contra ' + comparacion.nombre_de_la_referencia
      + ': $' + a.magnitud + ' en ' + plural(a.cantidad, 'pieza', 'piezas');
  } else if (a.es_sobrecosto) {
    ahorro.className = 'ahorro cuesta';
    ahorro.textContent = 'Cuesta $' + a.magnitud + ' más que '
      + comparacion.nombre_de_la_referencia + ' en '
      + plural(a.cantidad, 'pieza', 'piezas') + '.';
  } else {
    ahorro.className = 'ahorro nose';
    ahorro.textContent = 'Sin ahorro que calcular: ' + (a.motivo || '')
      + (a.detalle ? ' (' + a.detalle + ')' : '') + '.';
  }
  caja.append(ahorro);

  return caja;
};

// LA COMPARACIÓN DE LOS CUATRO (ticket 14), que es la razón de ser del módulo
// puesta en una fila: a cómo está el producto en cada proveedor, cuál gana y
// cuánto se ahorra.
//
// **Ninguna cifra se calcula aquí, y ninguna regla se decide aquí.** El precio
// llega como CADENA desde el servidor —el JSON de JavaScript solo tiene coma
// flotante, y meter dinero ahí justo en el borde donde acababa de salir es la
// falla que el `numeric(12,2)` del DDL existe para evitar—, y quién gana, la
// diferencia contra el ganador y el ahorro contra NADRO vienen resueltos de
// `comparacion.py`, que es una función pura con su tabla de casos. Aquí solo se
// pregunta por banderas: `es_ganador`, `es_ahorro`, `la_referencia_gana`.
//
// La razón es la misma que la de `vistas.py`: si la regla que decide a quién
// comprarle viviera en este archivo, viviría en el único que ninguna prueba de
// Python mira, y el día que alguien "limpiara" la vista se perdería sin que
// nada se pusiera rojo.
//
// Tres aspectos distintos y no tres tonos del mismo gris (quinta casilla):
// el ganador con fondo, borde y su palabra; los caros con la diferencia en
// ámbar y alineada como número; los huecos en cursiva, en gris y con su motivo.
// Un proveedor sin dato NUNCA se pinta como cero, como vacío ni como el más
// caro (regla 4 de CLAUDE.md).
const celdaDePrecios = (r, acciones) => {
  const td = document.createElement('td');
  td.className = 'precios';
  td.dataset.etiqueta = 'Precio';

  const precios = Array.isArray(r.precios) ? r.precios : [];
  const comparacion = r.comparacion || null;
  const consulta = r.consulta || null;
  // Las lecturas por clave, solo para colgar el `detalle` del motivo como
  // título. No es una regla: es el mismo dato que ya viajó, buscado por su
  // llave.
  const porClave = new Map(precios.map(p => [p.proveedor, p]));
  const casillas = (comparacion && comparacion.por_proveedor) || [];

  // POR QUÉ ESTE RENGLÓN NO TIENE NI UNA LECTURA (ticket 19, primera casilla).
  //
  // Hasta el ticket 18 aquí no había nada: un renglón sin lecturas se veía
  // como una celda con un botón, y "el lote se cortó por tiempo antes de
  // llegar a éste" se veía IGUAL que "nadie lo ha consultado nunca". Eran dos
  // cosas que se arreglan distinto y la diferencia solo vivía en el journal
  // del lote, o sea en un `ssh`.
  //
  // **La frase viene hecha del servidor** y esta pantalla no elige entre
  // literales suyos: la decide `faltantes.por_que_no_hay_lectura`, que es una
  // función pura con su tabla de casos y sus pruebas. Es exactamente el error
  // que el ticket 15 arregló con la certeza del ganador, y que estaba en el
  // único archivo que ninguna prueba de Python mira.
  //
  // `seguro` en falso no invalida el motivo: lo matiza. Esa noche el tope
  // cortó Y ADEMÁS hubo renglones que no se pudieron consultar, así que de
  // éste no se puede afirmar cuál de los dos le tocó (ADR 0007). Se escribe
  // "probablemente" en vez de elegir uno a cara o cruz.
  const porque = r.porque_no_hay_lectura;
  if (porque && !casillas.length) {
    const caja = document.createElement('span');
    caja.className = 'hueco-motivo'
      + (porque.motivo === 'al lote se le acabó el tiempo' ? ' tope' : '')
      + (porque.motivo === 'la corrida del lote se cortó'
         || porque.motivo === 'el lote lo intentó y no pudo' ? ' falla' : '');
    const titular = document.createElement('b');
    titular.textContent = porque.seguro ? porque.motivo : 'probablemente: ' + porque.motivo;
    if (!porque.seguro) titular.className = 'quiza';
    caja.append(titular, ' — ' + porque.explicacion);
    td.append(caja);
  }

  casillas.forEach(c => {
    const linea = document.createElement('div');
    // Dos avisos distintos y por eso dos clases: "nadie confirmó que lo tenga"
    // y "fue el único que contestó". Pueden darse los dos a la vez, y el verde
    // entero es solo para el ganador que no tiene ninguno de los dos.
    linea.className = 'precio'
      + (c.es_ganador ? ' gana' : '')
      + (c.es_ganador && !comparacion.ganador.con_existencia ? ' sinconfirmar' : '')
      + (c.es_ganador && comparacion.ganador.es_unico ? ' unico' : '');

    const quien = document.createElement('span');
    quien.className = 'quien';
    quien.textContent = c.nombre;

    // La cifra es un `<b>`; el hueco es un `<span>` en cursiva. Son dos
    // elementos distintos a propósito: la diferencia tiene que verse aunque
    // alguien mire la pantalla de lejos o con reflejo.
    const cifraOhueco = document.createElement(c.precio ? 'b' : 'span');
    if (c.precio) {
      cifraOhueco.textContent = c.precio;
    } else {
      cifraOhueco.className = 'sindato';
      cifraOhueco.textContent = c.estado === 'sin consultar' ? 'sin consultar' : 'sin dato';
    }

    // LA EXISTENCIA, en su propia columna (cuarta casilla): el más barato no
    // sirve si no lo tiene. Se pinta el texto tal como lo dijo el portal
    // —"+100" dice más que "100"— y el estado decide cómo se ve.
    const hay = document.createElement('span');
    hay.className = 'hay';
    if (c.estado === 'con existencia') {
      hay.textContent = c.existencia_como_llego;
    } else if (c.estado === 'sin existencia') {
      hay.className = 'hay notiene';
      hay.textContent = c.existencia_como_llego || '0';
      hay.title = 'no lo tiene: por eso no gana aunque sea el más barato';
      hay.setAttribute('aria-label', 'no lo tiene');
    } else if (c.estado === 'no dijo existencia') {
      hay.className = 'hay nodijo';
      hay.textContent = c.existencia_como_llego || 'no dijo';
      hay.title = 'dio precio y no dijo cuántas piezas tiene';
    }

    linea.append(quien, cifraOhueco, hay);

    // Cuánto más caro es que el ganador, ya restado en Python. Es lo que
    // convierte cuatro cifras sueltas en una comparación legible.
    //
    // Y puede ser MÁS BARATO y no haber ganado: el ganador es el más barato de
    // los que lo tienen, así que un proveedor con cero piezas queda debajo con
    // su precio a la vista. Ahí la frase es otra —"más barato, pero no lo
    // tiene"—, porque un "+-60.33" no es una cifra y no dice nada. El signo lo
    // decide Python; aquí solo se elige la frase.
    if (c.diferencia) {
      const caro = document.createElement('span');
      caro.className = 'caro';
      caro.textContent = c.mas_barato_que_el_ganador
        ? c.diferencia_magnitud + ' más barato por pieza, pero no lo tiene'
        : '+' + c.diferencia_magnitud + ' por pieza';
      linea.append(caro);
    }

    // La marca del ganador va con PALABRA además de color y borde: un verde
    // más oscuro no es una marca para quien no distingue verdes, ni en una
    // pantalla de mostrador con reflejo.
    if (c.es_ganador) {
      const marca = document.createElement('span');
      // LA FRASE VIENE HECHA DEL SERVIDOR (`ganador.certeza`), y eso es el
      // ticket 15. Hasta el 14, este archivo elegía entre dos cadenas suyas
      // mirando una bandera, y por eso un renglón con UNA sola lectura salía
      // rotulado "el más barato con existencia": el superlativo afirma algo
      // sobre otros tres precios que nadie vio, y la afirmación se escribía en
      // el único archivo que ninguna prueba de Python mira. Ahora son cuatro
      // frases —"el más barato con existencia", "el más barato, pero nadie
      // confirmó existencia", "el único que contestó" y "el único que contestó,
      // y no dijo si lo tiene"— y las cuatro se deciden en `comparacion.py`,
      // con su tabla de casos.
      marca.className = 'marca-gana'
        + (comparacion.ganador.con_existencia ? '' : ' sinconfirmar')
        + (comparacion.ganador.es_unico ? ' unico' : '');
      marca.textContent = '✔ ' + (comparacion.ganador.certeza || '');
      linea.append(marca);
    }

    td.append(linea);

    // El motivo del hueco. Es lo que distingue un hueco que el encargado puede
    // atender de uno que no: "la sesión caducó" se arregla en dos clics y "sin
    // resultados" no se arregla (historia 23). Desde el ticket 28 va DENTRO de
    // la línea de su proveedor —la cuarta columna de la rejilla—, y no debajo
    // de ella: en una lista de 40 renglones, cada hueco colgando en su propia
    // línea era lo que hacía medir 300 px a un renglón.
    if (c.motivo) {
      const motivo = document.createElement('span');
      motivo.className = 'precio-motivo';
      // El motivo DICHO PARA UNA PERSONA (segunda casilla del ticket 15: *cada
      // precio faltante dice su motivo: el producto no está en ese catálogo,
      // el EAN dio varios resultados, el portal no contestó, la sesión
      // caducó*). La cadena corta —"sin resultados"— es la que se guarda y la
      // que se cuenta; la larga es la que se lee, y las dos viven en
      // `precios.py`. Si el servidor no mandara la larga se escribe la corta:
      // dice menos, pero dice algo.
      motivo.textContent = c.motivo_explicado || c.motivo;
      const lectura = porClave.get(c.proveedor);
      if (lectura && lectura.detalle) motivo.title = lectura.detalle;
      linea.append(motivo);
    }
  });

  // EL VEREDICTO: quién gana con todas sus letras, y el ahorro contra NADRO.
  if (comparacion && comparacion.hay_lecturas) td.append(veredicto(comparacion));

  // CUÁNDO SE LEYÓ, a la vista. Sin esto, "$86.05 en NADRO" no dice si se leyó
  // hace una hora o hace tres semanas, y el ticket es literal: un pedido dice a
  // qué precio se decidió, no a cómo está hoy. Es el instante MÁS RECIENTE de
  // las lecturas que se comparan, calculado en Python: tomar la primera de la
  // lista diría que una lectura de hace tres semanas es de hoy en cuanto
  // alguien vuelva a consultar y solo dos proveedores contesten.
  if (comparacion && comparacion.leido_en) {
    const cuando = document.createElement('span');
    cuando.className = 'precio-cuando';
    cuando.textContent = 'leído el ' + instanteEnPalabras(comparacion.leido_en)
      + (comparacion.instantes_distintos ? ' (hay lecturas de varios momentos)' : '');
    td.append(cuando);
  }

  if (consulta && consulta.en_curso) {
    const esperando = document.createElement('span');
    esperando.className = 'precio-cuando';
    // Se dice cuánto tarda. Una espera sin número se lee como "se colgó" a los
    // quince segundos, y ésta tarda nueve por proveedor en el mejor caso.
    esperando.textContent = 'Consultando a los cuatro proveedores… tarda un minuto.';
    td.append(esperando);
    return td;
  }

  if (consulta && consulta.detalle && !precios.length) {
    // Doyle no contestó y no hay nada congelado: un hueco CON SU MOTIVO, nunca
    // una celda vacía. Vacío se lee "no tiene precio en ningún lado".
    const fallo = document.createElement('span');
    fallo.className = 'precio-motivo';
    fallo.textContent = consulta.detalle;
    td.append(fallo);
  }

  // Sin el botón cuando la lista ya no está abierta: los precios congelados
  // siguen viéndose —son la razón por la que se eligió un proveedor— pero
  // volver a consultar una lista cerrada sería molestar a cuatro portales para
  // cambiar un dato que ya no decide nada.
  if (acciones.editable) {
    const pedir = botonDeAccion(
      precios.length ? 'Volver a consultar' : 'Consultar precio',
      (boton) => acciones.consultarPrecio(r, boton));
    pedir.title = precios.length
      ? 'Vuelve a preguntarle a Doyle. Lo de hoy se guarda al lado; nada se borra.'
      : 'Le pregunta a Doyle el precio en los cuatro proveedores. Tarda hasta un minuto.';
    pedir.setAttribute('aria-label',
      'Consultar el precio de ' + r.descripcion + ' en los cuatro proveedores');
    td.append(pedir);
  }

  return td;
};

const renglon = (r, acciones) => {
  const tr = document.createElement('tr');
  // YA SE PIDIÓ (ticket 24, casilla 4): atenuado y no escondido. Y lo que se
  // dejó de esperar (ticket 25), igual: ya no se atiende en esta lista.
  // Y lo que ya llegó (ticket 26), igual: está en la lista, ya no se atiende.
  if (r.esta_en_transito || r.esta_cancelado || r.esta_recibido) tr.classList.add('transito');
  // AGOTADO Y ATRASADO (ticket 28): dos clases del renglón entero para que la
  // hoja de estilos les ponga su barra al borde —continua y doble—. No deciden
  // nada: repiten banderas que ya llegaron hechas del servidor.
  if (r.esta_agotado) tr.classList.add('agotado');
  if (r.frase_del_atraso) tr.classList.add('atrasado');

  const clave = document.createElement('td');
  clave.className = 'clave';
  clave.textContent = r.clave || '—';

  const producto = document.createElement('td');
  producto.className = 'producto';
  producto.textContent = r.descripcion;
  if (!r.esta_en_el_catalogo) {
    const marca = document.createElement('span');
    marca.className = 'marca hueco-catalogo';
    marca.textContent = 'No está en el catálogo: revísalo en SICAR.';
    producto.append(marca);
  }

  // La clasificación sale del RENGLÓN y no se vuelve a deducir aquí: la regla
  // —el anaquel le gana a la categoría— vive en un solo lugar probado, en
  // Python, y no repetida en este archivo.
  //
  // Se marca solo lo que NO es medicamento. Etiquetar como "medicamento" nueve
  // de cada diez renglones de una farmacia es ruido que se deja de leer a la
  // tercera pantalla; lo que cambia una decisión es lo que se sale de lo
  // esperado. El interruptor entre vistas y el conteo de los sin clasificar
  // son el ticket 06: aquí el dato solo se ve.
  if (r.clasificacion && r.clasificacion !== 'medicamento') {
    const sinAnaquel = r.clasificacion === 'sin clasificar';
    const marca = document.createElement('span');
    marca.className = 'marca' + (sinAnaquel ? ' sin-clasificar' : ' tenue abarrote');
    marca.textContent = sinAnaquel
      ? 'Sin clasificar: no tiene anaquel conocido.'
      : 'Abarrote: no se le compra a un proveedor.';
    producto.append(marca);
  }

  // YA SE PIDIÓ (ticket 21). El renglón NO desaparece: sigue en la tabla, con
  // sus precios y su proveedor a la vista, porque el encargado tiene que poder
  // mirar qué pidió. Lo que cambia es que se dice —y que deja de poder
  // tocarse—: `en tránsito` significa "ya se le pidió a un proveedor y todavía
  // no llega" (CONTEXT.md), y de ahí sale que no se vuelva a proponer mañana.
  //
  // Desde el ticket 24 la frase llega HECHA de Python —"Pedido hoy a NADRO,
  // sin recibir."—, con a quién y cuándo. Lo de abajo es solo lo que se dice
  // cuando el servidor no la mandó (una respuesta de un solo renglón): la
  // misma de antes, que no afirma ni proveedor ni día.
  if (r.esta_en_transito) {
    const marca = document.createElement('span');
    marca.className = 'marca tenue en-transito';
    marca.textContent = r.frase_del_transito
      || ('Ya se pidió: en tránsito. No se vuelve a proponer '
          + 'mientras esté así.');
    producto.append(marca);
  }

  // ATRASADO (ticket 25). En la lista de hoy casi nunca pasa —se envió hoy—,
  // salvo que el almacén lleve días sin ventas nuevas. La frase es de Python y
  // el botón hace lo mismo que el del bloque de abajo.
  if (r.frase_del_atraso) {
    const marca = document.createElement('span');
    marca.className = 'marca atrasado';
    marca.textContent = r.frase_del_atraso;
    producto.append(marca);
    if (r.se_puede_devolver) {
      producto.append(botonDeAccion('Devolver a la lista',
        (boton) => devolverAtrasado(r.renglon_id, boton)));
    }
  }

  // PROBABLEMENTE YA LLEGÓ (ticket 26): hay una compra que encaja, en la
  // recepción de arriba. Por eso el botón de devolver no se ofrece.
  if (r.frase_de_la_recepcion) {
    const marca = document.createElement('span');
    marca.className = 'marca probable';
    marca.textContent = r.frase_de_la_recepcion;
    producto.append(marca);
  }

  // YA LLEGÓ (ticket 26): con la firma de quien lo confirmó, hecha en Python.
  // Desde el 27 dice cuántas llegaron, y se puede CORREGIR la cifra —la
  // segunda factura, un error de captura—. La etiqueta viene de Python.
  if (r.esta_recibido && r.frase_de_lo_recibido) {
    const marca = document.createElement('span');
    marca.className = 'marca tenue llego';
    marca.textContent = r.frase_de_lo_recibido;
    producto.append(marca);
    if (r.se_puede_corregir && r.etiqueta_a_mano) {
      producto.append(controlAMano(r.renglon_id, r.etiqueta_a_mano, r.descripcion,
        r.piezas_recibidas));
    }
  }

  // SE DEJÓ DE ESPERAR (ticket 25): su pedido se canceló o se devolvió por
  // atrasado. NO vuelve a esta lista —ya se armó sin él—: vuelve en la
  // siguiente, y la frase de Python lo dice.
  if (r.esta_cancelado) {
    const marca = document.createElement('span');
    marca.className = 'marca tenue vuelve';
    marca.textContent = r.frase_de_lo_cancelado
      || 'Se dejó de esperar: vuelve a proponerse en la siguiente lista.';
    producto.append(marca);
  }

  // LO QUE SE VENDIÓ MIENTRAS VENÍA EN CAMINO (ticket 24, casilla 3). El
  // renglón que vuelve después de recibirse trae ventas de antes de la lista,
  // y sin decirlo "pide 4" en una lista de un día con una venta no se podría
  // verificar. La frase es de Python.
  if (r.frase_de_la_ventana) {
    const marca = document.createElement('span');
    marca.className = 'marca tenue';
    marca.textContent = r.frase_de_la_ventana;
    producto.append(marca);
  }

  // LO QUE FALTÓ Y ESTE RENGLÓN TRAE (ticket 27): "pide 6" con 2 vendidas no
  // se podría verificar sin decir que 4 faltaron en un pedido anterior.
  if (r.frase_de_lo_que_falto) {
    const marca = document.createElement('span');
    marca.className = 'marca tenue';
    marca.textContent = r.frase_de_lo_que_falto;
    producto.append(marca);
  }

  // EL BORDE QUE LA MEMORIA NO ALCANZA (ticket 24): este producto ya viene en
  // camino desde una lista anterior que se envió DESPUÉS de armar ésta. La
  // lista guardada no se recalcula; se avisa en ámbar, con la frase de Python.
  if (r.ya_viene_en_camino) {
    const marca = document.createElement('span');
    marca.className = 'marca hay-que-mirar';
    marca.textContent = r.ya_viene_en_camino;
    producto.append(marca);
  }

  // Y SU PAR DEL TICKET 27: este renglón trae lo que faltó en un pedido
  // anterior, pero el resto llegó en otra factura y se corrigió después de
  // armar la lista. Lo guardado no se recalcula; se avisa en ámbar.
  if (r.ya_no_falta) {
    const marca = document.createElement('span');
    marca.className = 'marca hay-que-mirar';
    marca.textContent = r.ya_no_falta;
    producto.append(marca);
  }

  const existencia = celdaDeCifra(r.existencia, 'Existencia', '', r.esta_agotado);

  // Agotado se dice con la palabra y no con un "0.0 días": es el renglón más
  // urgente de la lista y tiene que saltar a la vista sin hacer aritmética.
  let cobertura;
  if (r.esta_agotado) {
    cobertura = document.createElement('td');
    cobertura.className = 'numero urgente';
    cobertura.dataset.etiqueta = 'Cobertura';
    cobertura.textContent = 'agotado';
  } else {
    cobertura = celdaDeCifra(r.dias_de_cobertura, 'Cobertura',
      r.dias_de_cobertura === 1 ? ' día' : ' días');
  }

  // LO QUE SE PUEDE TOCAR SALE DE DOS COSAS Y NO DE UNA (ticket 21): del estado
  // de la LISTA —"se puede corregir mientras la lista esté abierta"— y del
  // estado del RENGLÓN. Un renglón `en tránsito` ya se le pidió a un proveedor,
  // y las tres rutas que lo tocan exigen `abierto` en su `WHERE`, así que
  // dejarlo editable sería ofrecer tres botones que contestan 409. Eso enseña a
  // ignorar los avisos, que es lo mismo que el campo de la cantidad ya decidió
  // para la lista cerrada.
  //
  // La garantía sigue siendo del `WHERE`, no de esto.
  const editable = acciones.editable && !r.esta_en_transito && !r.esta_cancelado
    && !r.esta_recibido;

  const cantidad = celdaDeCantidad(r, editable, acciones.ajustar);

  // Descartar: UN CLIC y sin diálogo de confirmación. Lo que hace segura la
  // operación es que se puede deshacer —el renglón baja al bloque de
  // descartados con su botón para devolverlo—, no un "¿estás seguro?" que a la
  // tercera pantalla se cierra sin leer. La lista trae tantos renglones como
  // productos distintos se vendieron: un diálogo por renglón sería el doble de
  // clics en la única acción que mantiene legible la lista (ADR 0002).
  const celdaAcciones = document.createElement('td');
  celdaAcciones.className = 'acciones';
  const quitar = botonDeAccion('Descartar', (boton) => acciones.descartar(r, boton));
  // Apagado con la lista cerrada o vencida, igual que el campo de la cantidad y
  // el de proveedor. Desde el 2026-09-20 el servidor también lo rechaza -la
  // condicion vive en el `WHERE` de `_DESCARTAR`-, asi que esto es comodidad y
  // no la garantia. Pero un boton que se deja tocar para contestar 409 enseña a
  // ignorar los avisos, y este es el que mas se toca de la pantalla.
  //
  // Apagado y no escondido: la columna de acciones tiene ancho fijo y quitarlo
  // movería todas las filas al cerrar la lista.
  quitar.disabled = !editable;
  quitar.title = editable
    ? 'No se pide. Se puede devolver a la lista.'
    : (r.esta_en_transito
       ? 'Ya se le pidió a un proveedor: descartarlo diría que nadie lo pidió.'
       : (r.esta_cancelado
          ? 'Se dejó de esperar: vuelve a proponerse en la siguiente lista.'
          : (r.esta_recibido
             ? 'Ya llegó: se pidió y se recibió.'
             : 'La lista ya se cerró: lo que se iba a pedir ya se pidió.')));
  // El nombre del producto va en el nombre accesible: con veinte botones
  // iguales, "Descartar" a secas no dice cuál se está tocando.
  quitar.setAttribute('aria-label', 'Descartar ' + r.descripcion);
  celdaAcciones.append(quitar);

  tr.append(clave, producto, existencia, cobertura, cantidad,
            celdaDePrecios(r, acciones),
            celdaDeProveedor(r, editable, acciones.elegirProveedor),
            celdaAcciones);
  return tr;
};

// A QUIÉN SE LE PIDE ESTE RENGLÓN (ticket 20).
//
// Un desplegable con los cuatro y **ninguna opción vacía**: siempre hay algo
// seleccionado, o no hay a quién pedirle y entonces no hay desplegable que
// tocar. La opción que viene marcada es la elección —la de la persona si la
// hubo, y si no la sugerencia del sistema— y **cuál de las dos es se dice con
// todas sus letras debajo**, porque son dos cosas distintas: el ticket 11 ya
// pagó por distinguir "nadie la tocó" de "alguien la confirmó" en la cantidad,
// y aquí vale lo mismo.
//
// Ninguna regla vive en este archivo. Qué proveedor va marcado, si eso es una
// decisión, si difiere de lo sugerido y qué frase le toca llegan resueltos en
// `r.eleccion`, de `particion.elegir` — que es una función pura con su tabla de
// casos. Elegir aquí el "más barato" habría metido la regla que decide a quién
// se le compra en el único archivo que ninguna prueba de Python mira.
const celdaDeProveedor = (r, editable, alElegir) => {
  const td = document.createElement('td');
  td.className = 'proveedor';
  td.dataset.etiqueta = 'Se le pide a';

  const e = r.eleccion || null;
  if (!e) return td;

  if (!e.hay) {
    // Sin a quién pedirle. NO es un error: o hay empate —y el sistema no
    // desempata, porque elegir por orden alfabético sería una decisión que
    // nadie tomó— o todavía no hay precios con los que sugerir. El renglón se
    // ve entero y espera.
    const sin = document.createElement('span');
    sin.className = 'eleccion-sin';
    sin.textContent = e.motivo || 'sin proveedor';
    td.append(sin);
    if (e.nombres_empatados && e.nombres_empatados.length) {
      const empate = document.createElement('span');
      empate.className = 'eleccion-de';
      empate.textContent = 'Igual de baratos: ' + e.nombres_empatados.join(' y ') + '.';
      td.append(empate);
    }
    // Y aun así se puede elegir: la elección no se revisa contra el precio.
    // Es lo que permite pedirle a quien no contestó hoy (quinta casilla).
  }

  const campo = document.createElement('select');
  campo.className = 'eleccion-campo';
  campo.disabled = !editable;
  campo.setAttribute('aria-label', 'A quién se le pide ' + r.descripcion);
  PROVEEDORES.forEach(p => {
    const opcion = document.createElement('option');
    opcion.value = p.proveedor;
    opcion.textContent = p.nombre;
    if (p.proveedor === e.proveedor) opcion.selected = true;
    campo.append(opcion);
  });
  if (!e.hay) {
    // Con "sin proveedor" no se puede dejar el desplegable enseñando el
    // primero de la lista como si estuviera elegido: eso sería exactamente
    // inventar una decisión. Se antepone una opción que dice lo que pasa.
    const ninguno = document.createElement('option');
    ninguno.value = '';
    ninguno.textContent = '— elige —';
    ninguno.selected = true;
    campo.prepend(ninguno);
  }
  campo.addEventListener('change', () => alElegir(r, campo));
  td.append(campo);

  if (e.hay) {
    const quien = document.createElement('span');
    if (e.es_decision) {
      quien.className = 'eleccion-de' + (e.difiere_de_la_sugerencia ? ' distinta' : '');
      quien.textContent = 'Lo eligió ' + (e.elegido_por || 'sin-identificar')
        + (e.difiere_de_la_sugerencia
            ? '. El sistema sugería ' + e.nombre_sugerido + '.'
            : '.');
    } else {
      // SUGERENCIA, no decisión. La certeza viene hecha del servidor —"el más
      // barato con existencia", "el único que contestó"— y se escribe tal
      // cual: es lo que dice QUÉ se está afirmando de ese proveedor, y el
      // ticket 15 ya pagó por que esa frase no se elija aquí.
      quien.className = 'eleccion-de sugerida';
      quien.textContent = 'Lo sugiere el sistema'
        + (e.certeza ? ': ' + e.certeza + '.' : '.');
    }
    td.append(quien);
  }

  return td;
};

// Un renglón ya descartado, en el bloque de abajo. Es una lista y no una tabla
// a propósito: de un renglón que no se va a pedir lo único que importa es cuál
// era, quién lo quitó y poder devolverlo. Repetir las cinco columnas daría el
// mismo peso visual a lo atendido que a lo pendiente.
const renglonDescartado = (r, alDevolver, editable) => {
  const li = document.createElement('li');

  const nombre = document.createElement('span');
  nombre.textContent = r.descripcion;

  const devolver = botonDeAccion('Devolver a la lista', (boton) => alDevolver(r, boton));
  devolver.setAttribute('aria-label', 'Devolver ' + r.descripcion + ' a la lista');
  // Deshacer también es modificar, así que sigue la misma regla que descartar.
  // Apagarlo solo de un lado sería lo peor de los dos mundos: un renglón que
  // alguien quitó por error se quedaría fuera de una lista cerrada sin manera
  // de volver, y el botón estaría ahí prometiendo que sí.
  devolver.disabled = !editable;
  devolver.title = editable
    ? 'Vuelve a la lista como estaba.'
    : 'La lista ya se cerró: lo que se iba a pedir ya se pidió.';

  // Quién y cuándo, a la vista. Es una firma, no un permiso (regla 3 de
  // CLAUDE.md), y se muestra porque es lo que permite preguntar "¿por qué
  // quitaste éste?" a la persona correcta. Sin el túnel delante vale
  // `sin-identificar`, y eso se dice tal cual en vez de dejar el hueco.
  const firma = document.createElement('span');
  firma.className = 'quien';
  firma.textContent = 'Descartado por ' + (r.descartado_por || 'sin-identificar') +
    (r.descartado_en ? ' · ' + instanteEnPalabras(r.descartado_en) : '');

  li.append(nombre, devolver, firma);
  return li;
};

// ------------------------------------------------------- las dos vistas

// Dónde se recuerda la última elección. En el navegador y no en el servidor
// porque hoy Continental no guarda nada —las tablas son el ticket 07— y no
// hay sesión de usuario: el correo de Cloudflare Access es una firma, no un
// lugar donde colgar preferencias (regla 3 de CLAUDE.md). El precio se paga y
// se dice: la elección es POR NAVEGADOR, así que el teléfono y la computadora
// del mostrador pueden quedar en vistas distintas. Para una preferencia de
// lectura eso no cuesta nada.
const CLAVE_DE_VISTA = 'continental.pedido.vista';

// Leer y escribir van cada uno con su `try`: `localStorage` no solo devuelve
// null cuando no hay nada, TRUENA al tocarlo en una ventana privada o con las
// cookies de sitio bloqueadas. Sin esto, la excepción subiría y la pantalla se
// quedaría en blanco — y en blanco, con el pedido del día, significa que no se
// hace. Una preferencia que no se pudo guardar es una molestia; una lista que
// no se ve es el trabajo del día detenido.
const vistaRecordada = () => {
  try {
    return localStorage.getItem(CLAVE_DE_VISTA);
  } catch (e) {
    return null;
  }
};

const recordarVista = (clave) => {
  try {
    localStorage.setItem(CLAVE_DE_VISTA, clave);
  } catch (e) {
    // Se sigue sin recordar nada. No se avisa en pantalla: el encargado no
    // puede hacer nada al respecto y el interruptor funciona igual dentro de
    // esta visita.
  }
};

// Una clave guardada que ya no existe —basura, un valor editado a mano, o el
// nombre de una vista que se quitó— NO puede dejar la lista sin ninguna vista
// activa. Se cae a la de omisión, que el servidor marca en el mismo JSON.
const elegirVista = (vistas, clave) =>
  vistas.find(v => v.clave === clave) ||
  vistas.find(v => v.es_la_de_omision) ||
  vistas[0];

// Qué esconde cada vista NO se decide aquí. La lista de clasificaciones viene
// dentro de la respuesta, calculada en `vistas.py`, y esto solo pregunta si la
// del renglón está en ella. Escribir la regla en este archivo la pondría en el
// único lugar que ninguna prueba de Python mira, que es justo donde no debe
// estar: es la regla que decide si los 688 artículos sin anaquel se ven o
// desaparecen.
const renglonesDe = (renglones, vista) =>
  renglones.filter(r => vista.clasificaciones.includes(r.clasificacion));

const pintarInterruptor = (vistas, activa, alElegir) => {
  const caja = document.getElementById('vistas');
  caja.replaceChildren(...vistas.map(v => {
    const etiqueta = document.createElement('label');
    etiqueta.className = v.clave === activa.clave ? 'activa' : '';

    const boton = document.createElement('input');
    boton.type = 'radio';
    boton.name = 'vista';
    boton.value = v.clave;
    boton.checked = v.clave === activa.clave;
    boton.addEventListener('change', () => alElegir(v));
    // El foco se ve: el interruptor se recorre con las flechas y quien navega
    // con teclado tiene que saber dónde está parado.
    boton.addEventListener('focus', () => etiqueta.classList.add('enfocada'));
    boton.addEventListener('blur', () => etiqueta.classList.remove('enfocada'));

    const nombre = document.createElement('span');
    nombre.textContent = v.nombre;

    // Cuántos renglones trae cada vista, dicho en el propio interruptor: así
    // se ve cuánto se está escondiendo ANTES de mover nada, y el encargado
    // que no encuentra un producto sabe de inmediato dónde buscarlo.
    const cuenta = document.createElement('span');
    cuenta.className = 'cuenta';
    cuenta.textContent = v.cuantos;

    etiqueta.append(boton, nombre, cuenta);
    return etiqueta;
  }));
  caja.hidden = false;
};

// ------------------------------------------- cuándo se armó, y cerrarla

// Cómo se lee cada estado del glosario. Las claves son las del servidor; si
// mandara uno que esta tabla no conoce se pinta su propia palabra en vez de
// dejar el hueco vacío — una pantalla que no dice en qué estado está la lista
// es peor que una que dice una palabra fea.
const ESTADOS = { abierto: 'Abierta', cerrado: 'Cerrada', vencido: 'Vencida' };

// Cuándo se armó la lista, que es lo que el ticket pide que se vea, y en qué
// estado está. Es distinto del corte: el corte dice DE QUÉ DÍA son las ventas
// y esto dice CUÁNDO SE HIZO la lista. Con el respaldo de SICAR llegando hasta
// 2.5 días tarde, confundirlos es exactamente lo que hay que poder evitar.
const pintarCabecera = (datos) => {
  const armado = document.getElementById('armado');
  armado.replaceChildren();

  const estado = document.createElement('span');
  estado.className = 'estado ' + (datos.estado || '');
  estado.textContent = ESTADOS[datos.estado] || datos.estado || 'Sin guardar';
  armado.append(estado);

  if (datos.armado_en) armado.append(' · Armada el ' + instanteEnPalabras(datos.armado_en));
  if (datos.cerrado_en) {
    armado.append(' · Se cerró el ' + instanteEnPalabras(datos.cerrado_en) +
      ', con las ventas ' +
      rangoEnPalabras(datos.ventas_consideradas_desde, datos.ventas_consideradas_hasta) +
      '. La siguiente lista arranca al día siguiente de ese corte.');
  } else if (datos.estado === 'vencido') {
    // Se dice con todas sus letras: una lista vencida no es un error del
    // sistema, es un día en que nadie la cerró, y lo que quedó sin atender
    // sigue ahí para verse.
    armado.append(' · Su día pasó y nadie la cerró.');
  }
  // La firma de la última reapertura (ADR 0016), hecha en Python con la hora
  // de la farmacia. Se queda aunque la lista se vuelva a cerrar.
  if (datos.frase_de_la_reapertura) armado.append(' · ' + datos.frase_de_la_reapertura);
  armado.hidden = false;
};

const pintarCierre = (datos, alCerrar, alReabrir) => {
  const caja = document.getElementById('cierre');
  const boton = document.getElementById('cerrar');
  const reabrir = document.getElementById('reabrir');
  const detalle = document.getElementById('cierre-detalle');

  // Solo se cierra lo que está abierto. El servidor lo vuelve a comprobar en
  // el `WHERE` de su UPDATE: esconder el botón es comodidad, no la garantía.
  if (datos.estado === 'abierto') {
    // Se dice de qué día a qué día, y qué implica cerrarla: el corte es desde
    // donde acumula la siguiente, así que cerrar es decidir que lo de esos días
    // ya se pidió. Decir solo la fecha final escondería los días de en medio.
    detalle.textContent = 'Al cerrarla queda guardado que consideró las ventas ' +
      rangoEnPalabras(datos.ventas_consideradas_desde, datos.ventas_consideradas_hasta) +
      '. La siguiente arranca al día siguiente. No se borra nada.';
    boton.hidden = false;
    boton.disabled = false;
    boton.onclick = () => alCerrar(boton, detalle);
    reabrir.hidden = true;
    caja.hidden = false;
    return;
  }
  boton.hidden = true;

  // DESHACER EL CIERRE (ADR 0016). Todo llega hecho: si se puede, el rótulo y
  // la frase; si no, por qué; si no se pudo saber, qué hacer. El botón solo se
  // pinta con `se_puede`: sin la respuesta de la base no se ofrece, y un botón
  // que contestaría 409 es un botón muerto.
  const reapertura = datos.reapertura;
  if (!reapertura) {
    reabrir.hidden = true;
    caja.hidden = true;
    return;
  }
  detalle.textContent = reapertura.que_hacer
    ? fallaEnUnaLinea(reapertura)
    : (reapertura.frase || '');
  reabrir.hidden = !reapertura.se_puede;
  if (reapertura.se_puede) {
    reabrir.textContent = reapertura.boton;
    reabrir.disabled = false;
    reabrir.onclick = () => alReabrir(reabrir, detalle);
  }
  caja.hidden = false;
};

// LA CONFIRMACIÓN ANTES DE CERRAR (ADR 0016). Todo lo que dice llega hecho de
// `cierre.al_cerrar`: cuánto queda sin pedir, y lo que se perdería renglón por
// renglón con sus piezas. Aquí se acomoda en el <dialog>. Si el resumen no se
// pudo leer, se dice con su qué hacer y cerrar sigue disponible: avisa, no
// prohíbe.
const pintarConfirmacion = (resumen) => {
  const parte = (nombre) => document.getElementById('confirmar-cierre-' + nombre);
  const cerrar = parte('cerrar');
  const volver = parte('volver');
  // Los rótulos del HTML son los de omisión; el servidor los cambia.
  if (!cerrar.dataset.porOmision) cerrar.dataset.porOmision = cerrar.textContent;
  if (resumen.volver) volver.textContent = resumen.volver;
  if (resumen.titulo) parte('titulo').textContent = resumen.titulo;

  const frase = parte('frase');
  if (!resumen.ok) {
    notaDeFalla('confirmar-cierre-frase', resumen);
    parte('perdidas').hidden = true;
    parte('deshacer').hidden = true;
    cerrar.hidden = false;
    cerrar.textContent = resumen.boton || cerrar.dataset.porOmision;
    return false;
  }
  frase.className = '';
  frase.textContent = resumen.frase || '';

  const perdidas = resumen.se_perderian || [];
  parte('perdidas').hidden = !perdidas.length;
  parte('aviso').textContent = resumen.aviso || '';
  parte('lista').replaceChildren(...perdidas.map((perdida) => {
    const li = document.createElement('li');
    li.textContent = perdida.frase;
    return li;
  }));
  parte('que-hacer').textContent = resumen.que_hacer_con_lo_que_se_perderia || '';
  parte('deshacer').textContent = resumen.deshacer || '';
  parte('deshacer').hidden = !resumen.deshacer;

  cerrar.hidden = !resumen.boton;
  if (resumen.boton) cerrar.textContent = resumen.boton;
  return perdidas.length > 0;
};

// Al apretar "Cerrar la lista": se pide el resumen EN ESE MOMENTO —no el de la
// carga: descartar cambia un renglón sin reenviar la lista, y otra pestaña pudo
// haber enviado un pedido— y se enseña. Solo "Cerrar" del diálogo cierra; Esc
// y "Volver" lo dejan como estaba.
const confirmarCierre = async (id, boton, detalle, alCerrarse) => {
  boton.disabled = true;
  const antes = detalle.textContent;
  const resumen = await respuestaDe(fetch('/api/pedido-sugerido/' + id + '/al-cerrar'));
  boton.disabled = false;
  detalle.textContent = antes;

  const dialogo = document.getElementById('confirmar-cierre');
  const hayPerdidas = pintarConfirmacion(resumen);
  dialogo.returnValue = '';
  dialogo.onclose = () => {
    if (dialogo.returnValue === 'cerrar') cerrarLista(id, boton, detalle, alCerrarse);
  };
  dialogo.showModal();
  // El foco va a la salida segura cuando algo se perdería o no se pudo leer:
  // un Enter distraído no cierra. En el caso normal, al botón de cerrar.
  const cerrar = document.getElementById('confirmar-cierre-cerrar');
  const volver = document.getElementById('confirmar-cierre-volver');
  (hayPerdidas || !resumen.ok || cerrar.hidden ? volver : cerrar).focus();
};

// Deshacer el cierre. El servidor decide en su `WHERE` si todavía se puede; si
// contesta que ya no (un 409 sin qué hacer: la siguiente ya existe), el
// botón se esconde en vez de quedarse vivo para rebotar otra vez.
const reabrirLista = async (id, boton, detalle, alReabrirse) => {
  boton.disabled = true;
  detalle.textContent = 'Reabriendo…';
  const datos = await respuestaDe(fetch('/api/pedido-sugerido/' + id + '/reabrir',
    { method: 'POST' }), 'al_guardar');
  if (!datos.ok) {
    boton.disabled = false;
    boton.hidden = !datos.que_hacer;
    detalle.textContent = fallaEnUnaLinea(datos);
    return;
  }
  alReabrirse(datos);
};

const cerrarLista = async (id, boton, detalle, alCerrarse) => {
  // Se desarma el botón antes de salir: cerrar dos veces no rompe nada —el
  // servidor contesta 409 y no mueve la hora— pero un botón que sigue vivo
  // mientras la petición viaja invita a un segundo clic que no hace falta.
  boton.disabled = true;
  detalle.textContent = 'Cerrando…';

  const datos = await respuestaDe(fetch('/api/pedido-sugerido/' + id + '/cerrar',
    { method: 'POST' }), 'al_guardar');
  if (!datos.ok) {
    // El motivo viene del servidor y es genérico a propósito (regla 5): el
    // detalle está en la bitácora. Hasta el ticket 29 el botón se quedaba
    // apagado aquí para siempre si la respuesta no era JSON.
    boton.disabled = false;
    detalle.textContent = fallaEnUnaLinea(datos);
    return;
  }

  // La cabecera, el cierre —ahora con su deshacer— y la tabla se vuelven a
  // pintar porque el estado de la lista cambió, y con él cambia lo que se
  // puede hacer: una lista cerrada ya no deja corregir cantidades. Sin esto,
  // los campos se quedarían editables hasta que alguien recargara, y cada
  // corrección rebotaría con un 409 — la pantalla diciendo que se puede algo
  // que el servidor no permite.
  alCerrarse(datos);
};

// QUÉ TAN RECIENTES SON LAS VENTAS (ticket 29, casilla 3). Todo llega hecho:
// si es lo más reciente que puede haber (un lunes por la mañana, el viernes),
// o si falta un día que ya debía estar —y entonces con qué hacer—. Aquí no se
// mira el reloj ni se decide nada.
const pintarVentas = (ventas) => {
  const p = document.getElementById('pedido-ventas');
  if (!ventas || !ventas.frase) { p.hidden = true; return; }
  if (ventas.que_hacer) {
    // Falta un día que ya debía estar, o no hay ni una venta: el servidor LEYÓ
    // —no es una falla de lectura— y dice qué hacer. Se rotula como aviso.
    notaDeFalla('pedido-ventas', ventas, true);
    return;
  }
  nota('pedido-ventas', ventas.frase, 'ventas');
};

// Lo que no se pudo leer y NO tumbó la lista (ticket 29): los precios o los
// pedidos. Cada aviso llega con su frase —que dice que ese vacío no es un
// dato— y su qué hacer.
const pintarAvisos = (avisos) => {
  const caja = document.getElementById('pedido-avisos');
  caja.replaceChildren();
  (avisos || []).forEach((aviso, i) => {
    const p = document.createElement('p');
    p.id = 'pedido-aviso-' + i;
    caja.append(p);
    notaDeFalla(p.id, aviso);
  });
  caja.hidden = !caja.children.length;
};

async function cargarPedido() {
  const corte = document.getElementById('corte');
  const tabla = document.getElementById('pedido-tabla');
  let datos = await respuestaDe(fetch('/api/pedido-sugerido'));

  // Un hueco con su motivo, nunca una lista vacía: vacío se lee "hoy no se
  // vendió nada" y el pedido del día no se hace. Entra aquí TODO lo que no es
  // la lista: el hueco del servidor, su 500 y la falta de respuesta. Hasta el
  // ticket 29 el 500 se colaba a la rama de abajo y la pantalla decía que el
  // almacén no tenía ni una venta.
  if (datos.ok === false) {
    // Si el servidor mandó su frase, ésa ya dice qué no se pudo armar: el
    // titular se esconde para no decirlo dos veces (recorrido del ticket 29).
    // Sin respuesta no hay frase, y el titular da el contexto.
    corte.textContent = 'No se pudo armar el pedido sugerido.';
    corte.hidden = !!datos.frase;
    notaDeFalla('pedido-nota', datos);
    return;
  }

  // Qué tan recientes son las ventas que SÍ se leyeron, dicho por el servidor
  // (ticket 29): un lunes por la mañana, la lista del viernes es lo normal, y
  // esto lo dice. Si falta un día que ya debía estar, lo dice también.
  pintarVentas(datos.ventas);

  // Ni una venta en el almacén: el servidor lo AFIRMA —leyó y no había—, con
  // su frase en `ventas`. No se escribe nada más.
  if (!datos.fecha_de_ventas) {
    corte.hidden = true;
    return;
  }

  // Lo que se leyó y no tumbó la lista, pero dejó un vacío que no es un dato:
  // los precios o los pedidos que no se pudieron leer (ticket 29).
  pintarAvisos(datos.avisos);

  // Quiénes son los cuatro y cómo se escribe cada nombre, del SERVIDOR. No
  // escritos a mano aquí: el glosario manda sobre el nombre de cualquier cosa
  // y `precios.NOMBRES_DE_PROVEEDOR` es donde vive. De paso viene cuál tiene
  // `pro_id` de SICAR y cuál no (ticket 20).
  if (Array.isArray(datos.puente)) PROVEEDORES = datos.puente;

  corte.innerHTML = '';
  corte.append('Ventas ');
  const cuando = document.createElement('strong');
  cuando.textContent = rangoEnPalabras(
    datos.ventas_consideradas_desde, datos.fecha_de_ventas);
  corte.append(cuando);
  // Cuántos días son, dicho con el número. "Del viernes al lunes" son cuatro
  // días y no tres: los dos extremos entran, y el domingo cuenta aunque la
  // farmacia cierre —no se vendió nada, pero tampoco se dejó de mirar—.
  const dias = Math.round(
    (Date.parse(datos.fecha_de_ventas) - Date.parse(datos.ventas_consideradas_desde))
    / 86400000) + 1;
  if (dias > 1) {
    const cuantos = document.createElement('span');
    cuantos.className = 'dias-acumulados';
    // DECÍA "acumulados desde el último cierre" Y PODÍA MENTIR. Desde que la
    // ventana se acortó a un día hábil (2026-09-20), una lista de varios días
    // tiene dos causas posibles: el fin de semana, o que alguien dejó una
    // lista sin cerrar y sus días se arrastran para que no se pierdan. En el
    // segundo caso NO hay ningún cierre del cual acumular, así que la frase
    // vieja nombraba algo que no existía.
    //
    // Se dice el número y no la causa porque el número es lo que cambia la
    // decisión: esta lista trae más piezas que un día normal. La causa se lee
    // en las fechas, que están al lado.
    cuantos.textContent = dias + ' días de ventas en esta lista, no uno';
    cuantos.title = 'La lista cubre un solo día hábil salvo que haya de por '
      + 'medio un fin de semana o un día que nadie cerró. Esos días se '
      + 'arrastran a propósito para que sus ventas no se pierdan.';
    corte.append(' ', cuantos);
  }

  // LO QUE SOLO TRAE LA CARGA (ticket 24). Partir, enviar y tachar devuelven
  // la lista ENTERA y la pantalla la sustituye, pero esas respuestas no leen
  // lo que viene en camino —no lo cambian—, así que el bloque y los avisos de
  // "ya viene en camino" se conservan de la carga en vez de borrarse al primer
  // clic. Esto copia datos, no compone ni una palabra.
  const conservarLoDeLaCarga = (nuevo, anterior) => {
    if (!nuevo.en_camino) nuevo.en_camino = anterior.en_camino;
    if (!nuevo.recepcion) nuevo.recepcion = anterior.recepcion;
    const avisos = new Map((anterior.renglones || [])
      .filter(r => r.ya_viene_en_camino)
      .map(r => [r.renglon_id, r.ya_viene_en_camino]));
    (nuevo.renglones || []).forEach(r => {
      if (!('ya_viene_en_camino' in r) && avisos.has(r.renglon_id)) {
        r.ya_viene_en_camino = avisos.get(r.renglon_id);
      }
    });
    return nuevo;
  };

  // Qué hacer cuando la lista se cierre. Se declara aquí, vacío, porque
  // `pintarCierre` va ANTES de que exista `repintar` —una lista sin renglones
  // también se puede cerrar y sale por la puerta de abajo— y llamar a `repintar`
  // desde una lista vacía tronaría con un `vistas` que nunca se inicializó. Se
  // rellena más abajo, cuando ya hay tabla que repintar.
  let alCerrarse = () => {};

  // Antes de cualquier salida temprana: una lista sin renglones también se
  // guardó, también tiene hora de armado y también se puede cerrar.
  //
  // Y lo que viene en camino (ticket 24) también va antes: un día sin nada que
  // reponer puede tener, igual, tres renglones de ayer que no han llegado.
  pintarRecepcion(datos.recepcion);
  pintarEnCamino(datos.en_camino);
  pintarCabecera(datos);
  // Cerrar pasa por la confirmación, y cerrar y reabrir terminan igual: la
  // cabecera, el cierre y la tabla con el estado nuevo (ADR 0016).
  const alCambiarDeEstado = (nueva) => {
    pintarCabecera(nueva);
    pintarElCierre(nueva);
    alCerrarse(nueva);
  };
  const pintarElCierre = (conEstado) => pintarCierre(conEstado,
    (boton, detalle) => confirmarCierre(
      datos.pedido_sugerido_id, boton, detalle, alCambiarDeEstado),
    (boton, detalle) => reabrirLista(
      datos.pedido_sugerido_id, boton, detalle, alCambiarDeEstado));
  pintarElCierre(datos);

  if (!datos.renglones.length) {
    // La frase llega de Python (ticket 29): "no se vendió nada" era falso —el
    // último día de la ventana siempre tiene ventas—.
    nota('pedido-nota', datos.lista_vacia || '', 'aviso');
    return;
  }

  nota('pedido-nota', datos.sin_catalogo
    ? (datos.sin_catalogo === 1
        ? 'Un renglón es de un producto que el catálogo no conoce. Se muestra igual: se vendió y hay que reponerlo.'
        : datos.sin_catalogo + ' renglones son de productos que el catálogo no conoce. Se muestran igual: se vendieron y hay que reponerlos.')
    : '', datos.sin_catalogo ? 'aviso' : '');

  // El conteo de los sin anaquel es de la LISTA COMPLETA, no de la vista, y
  // vale lo mismo en las dos justamente porque esos renglones nunca se
  // esconden. Responde una pregunta sobre el catálogo —"¿vale la pena ponerles
  // anaquel en SICAR?"— y un número que bajara al mover el interruptor se
  // leería como que hay menos productos sin anaquel.
  nota('pedido-sin-clasificar', datos.sin_clasificar
    ? plural(datos.sin_clasificar, 'renglón se quedó', 'renglones se quedaron') +
      ' sin clasificar: no tienen anaquel en SICAR. Se muestran en las dos ' +
      'vistas, marcados. Ponerles anaquel es lo que los saca de aquí.'
    : '', 'aviso');

  // Si el servidor no mandó las vistas —una versión vieja, un despliegue a
  // medias—, se pinta la lista COMPLETA y sin interruptor. Falla hacia mostrar
  // de más, nunca hacia esconder: lo que no se ve es lo que hace falta sin que
  // nadie se entere.
  const vistas = Array.isArray(datos.vistas) && datos.vistas.length ? datos.vistas : null;

  // Cuál vista está encendida. Es el único estado que la pantalla guarda: la
  // lista es `datos`, tal como el servidor la mandó, y descartar solo
  // sustituye un renglón dentro de ella.
  let vistaActiva = vistas ? elegirVista(vistas, vistaRecordada()) : null;

  // Si se consultó algún precio después de que llegó el conteo de arriba. Ver
  // `aplicarPrecios`: descartar y devolver traen el conteo recalculado, pero
  // consultar un precio no, y esta bandera es lo que hace que la pantalla lo
  // diga en vez de enseñar un número viejo como si fuera de ahora.
  let conteoEnvejecido = false;

  // Descartar saca el renglón de la lista de trabajo y lo baja al bloque de
  // abajo. El reparto se hace por el ESTADO que trae cada renglón, que es el
  // del glosario y el de la columna: la pantalla no decide qué es descartado,
  // solo dónde se pinta.
  const repintar = () => {
    const trabajables = datos.renglones.filter(r => r.estado !== DESCARTADO);
    // Lo que se puede hacer sale del ESTADO DE LA LISTA, no de cada renglón:
    // "la cantidad se puede cambiar mientras la lista esté abierta" es literal
    // (ticket 11). Se calcula en cada repintado y no una sola vez al cargar,
    // porque cerrar la lista lo cambia sin recargar la página.
    const acciones = {
      editable: datos.estado === 'abierto',
      descartar: descartar,
      ajustar: ajustar,
      elegirProveedor: elegirProveedor,
      consultarPrecio: consultarPrecio,
      completar: completarLoQueFalta,
      abrirSesion: abrirSesion,
      confirmarSesion: confirmarSesion,
    };
    if (vistas) {
      // Los conteos del interruptor son de la lista DE TRABAJO: decir "18" en
      // una vista donde se ven 12 porque seis están descartados haría buscar
      // seis renglones que no están escondidos, sino atendidos.
      vistas.forEach(v => { v.cuantos = renglonesDe(trabajables, v).length; });
      pintarInterruptor(vistas, vistaActiva, mostrar);
      pintarRenglones(
        renglonesDe(trabajables, vistaActiva),
        trabajables.length,
        vistas.find(v => v.clave !== vistaActiva.clave) || vistaActiva,
        datos.descartados,
        acciones);
    } else {
      pintarRenglones(trabajables, trabajables.length, null, datos.descartados, acciones);
    }
    // El bloque de descartados NO se filtra por vista, y es a propósito: la
    // vista de medicamentos esconde abarrotes de lo que falta por pedir, pero
    // un abarrote que alguien descartó por error tiene que poder devolverse sin
    // adivinar en qué vista aparece.
    pintarDescartados(
      datos.renglones.filter(r => r.estado === DESCARTADO),
      datos.descartados,
      devolver,
      acciones.editable);
    // El conteo de huecos, arriba y en cada repintado: descartar, devolver y
    // consultar un precio lo cambian, y un número que envejece en la pantalla
    // se lee como verdad igual que uno al día.
    pintarConteoDePrecios(datos.conteo_de_precios, conteoEnvejecido);
    // Cómo le fue al lote de anoche, y lo que se puede completar. Los dos en
    // cada repintado y por lo mismo que el conteo: descartar un renglón saca
    // un faltante de la cola del botón, y un botón que siga ofreciendo
    // "completar 12" después de descartar cuatro de esos doce mandaría a
    // molestar a cuatro portales por mercancía que alguien ya decidió no pedir.
    pintarCorrida(datos.corrida, datos.corrida_ausente);
    pintarCompletar(datos.faltantes, datos.sesiones_caducadas, acciones);
    // En qué se parte la lista, en cada repintado y por lo mismo que el
    // conteo: elegir proveedor la cambia de la manera obvia, y descartar y
    // ajustar también — uno saca un renglón de un pedido y el otro le cambia
    // el importe. Una vista previa vieja mandaría a apretar "Partir" sobre
    // números que ya no son.
    pintarParticion(datos.particion, datos.pedidos, acciones.editable, partir, enviarPedido, tacharRenglon);
    tabla.hidden = false;
  };

  const mostrar = (vista) => {
    vistaActiva = vista;
    recordarVista(vista.clave);
    repintar();
  };

  // El renglón que vuelve del servidor tiene la misma forma que el que llegó
  // en la carga, así que se sustituye entero: nada se deduce aquí del estado
  // nuevo, ni la firma ni la hora.
  const aplicar = (respuesta) => {
    const i = datos.renglones.findIndex(r => r.renglon_id === respuesta.renglon.renglon_id);
    if (i >= 0) {
      // El aviso de "ya viene en camino" solo lo trae la carga (ticket 24).
      if (!('ya_viene_en_camino' in respuesta.renglon)) {
        respuesta.renglon.ya_viene_en_camino = datos.renglones[i].ya_viene_en_camino;
      }
      datos.renglones[i] = respuesta.renglon;
    }
    datos.descartados = respuesta.descartados;
    datos.tiene_renglones_sin_atender = respuesta.tiene_renglones_sin_atender;
    // El conteo viene recalculado porque descartar y devolver lo mueven: el
    // que se cuenta es el de los renglones DE TRABAJO. Va `null` cuando el
    // servidor no pudo releer los precios, y entonces se conserva el anterior:
    // viejo pero verdadero, en vez de estrenar uno inventado.
    if (respuesta.conteo_de_precios) {
      datos.conteo_de_precios = respuesta.conteo_de_precios;
      conteoEnvejecido = false;
    }
    // Y los faltantes, por lo mismo: descartar saca un renglón de la cola del
    // botón de completar y devolver lo mete. `null` cuando el servidor no pudo
    // releer los precios — ahí se conserva el anterior, viejo pero verdadero.
    if (respuesta.faltantes) datos.faltantes = respuesta.faltantes;
    // Y la partición, por lo mismo: `null` cuando el servidor no pudo releer
    // los precios, y entonces se conserva la anterior — vieja pero verdadera.
    if (respuesta.particion) datos.particion = respuesta.particion;
    repintar();
  };

  function descartar(r, boton) {
    moverRenglon(r.renglon_id, '/descartar', boton, aplicar);
  }

  // Elegir a quién se le pide un renglón. **La persona decide**, y por eso
  // esto se manda aunque el proveedor elegido sea el que el sistema ya
  // sugería: confirmar la sugerencia ES una decisión, igual que confirmar la
  // cantidad propuesta en el ticket 11, y es lo único que después distingue un
  // renglón que alguien miró de uno que nadie miró.
  //
  // No se comprueba nada del precio: se puede elegir a un proveedor que no
  // contestó hoy. Hay razones que el sistema no ve — mínimo de pedido, días de
  // entrega, crédito—, y el renglón entra al pedido con la marca de precio
  // desconocido.
  function elegirProveedor(r, campo) {
    const proveedor = campo.value;
    if (!proveedor) return;
    moverRenglon(r.renglon_id, '/proveedor', campo, aplicar, { proveedor },
      () => {
        const antes = (r.eleccion && r.eleccion.proveedor) || '';
        campo.value = antes;
      });
  }

  function devolver(r, boton) {
    moverRenglon(r.renglon_id, '/devolver', boton, aplicar);
  }

  // Corregir la cantidad. Lo que se teclea se revisa aquí ANTES de mandarlo, y
  // no porque el servidor no lo revise —lo revisa, y la tabla también—, sino
  // porque éste es el único de los tres lugares que puede decirlo mientras el
  // dedo sigue en el campo.
  //
  // **Un cero no es una forma de descartar.** Es el camino más común de todos:
  // "no quiero pedir esto" se teclea como un 0 antes que como un clic en
  // Descartar. Así que el 0 no se manda, se deshace lo tecleado y se dice cuál
  // es el botón que sí lo hace — y que además guarda quién lo decidió.
  function ajustar(r, campo) {
    const cantidad = Number(campo.value);
    if (!Number.isInteger(cantidad) || cantidad < 1) {
      campo.value = r.cantidad_a_pedir;
      nota('pedido-accion',
        'Un cero —o un campo vacío, o media pieza— no se puede pedir, y un cero ' +
        'tampoco es una forma de descartar: para no pedir «' + r.descripcion +
        '» usa Descartar, así queda guardado quién lo decidió.', 'aviso');
      return;
    }
    // Volver a escribir el mismo número en un renglón que ya se corrigió no se
    // manda. `change` no se dispara al salir de un campo intacto, pero sí al
    // teclear "03" sobre un "3" o al deshacer un tecleo a medias, y eso no es
    // una decisión nueva: movería la hora y la firma de una corrección que ya
    // estaba. En un renglón que nadie ha tocado sí se manda, porque confirmar
    // la propuesta del sistema SÍ es una decisión — es la que dice que la
    // reposición 1 a 1 acertó.
    if (r.fue_ajustada && cantidad === r.cantidad_a_pedir) return;
    moverRenglon(r.renglon_id, '/cantidad', campo, aplicar, { cantidad },
      () => { campo.value = r.cantidad_a_pedir; });
  }

  // PARTIR LA LISTA EN PEDIDOS (ticket 20).
  //
  // Se puede apretar cuantas veces haga falta: la garantía de que no se
  // dupliquen es de la BASE —`ux_pedido_proveedor`, uno por proveedor dentro
  // de la misma lista— y no de deshabilitar el botón. Deshabilitarlo mientras
  // viaja es solo para no invitar a un segundo clic que no hace falta.
  //
  // La respuesta trae la lista ENTERA, no un renglón: partir mueve el
  // `pedido_id` de muchos a la vez y los totales de todos los pedidos. Es la
  // única operación de esta pantalla que lo hace, y por eso no pasa por
  // `moverRenglon`.
  async function partir(boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch(
        '/api/pedido-sugerido/' + datos.pedido_sugerido_id + '/partir',
        { method: 'POST' }), 'al_guardar');

    if (!respuesta.ok) {
      boton.disabled = false;
      // Genérico a propósito (regla 5 de CLAUDE.md): el detalle está en la
      // bitácora del servidor.
      notaDeFalla('pedido-accion', respuesta);
      return;
    }

    datos = conservarLoDeLaCarga(respuesta, datos);
    if (Array.isArray(datos.puente)) PROVEEDORES = datos.puente;
    conteoEnvejecido = false;
    repintar();
    nota('pedido-accion',
      'Lista partida en ' + plural((datos.pedidos || []).length, 'pedido', 'pedidos')
      + '. Siguen en borrador: se pueden cambiar y volver a partir.', 'todo');
  }

  // MARCAR UN PEDIDO COMO ENVIADO (ticket 21).
  //
  // **Esto no le manda nada a nadie**, y el botón lo dice arriba con la frase
  // que llega hecha del servidor: Continental no entra a los portales de los
  // proveedores (regla 1 de CLAUDE.md, ADR 0002 y ADR 0009). Lo que se guarda
  // es que el encargado declara haberlo capturado él, con su correo y la hora.
  //
  // Por eso NO se pregunta "¿estás seguro?": el diálogo de confirmación que se
  // ve en cada clic se aprende a despachar sin leerlo, y lo que de verdad hace
  // segura esta acción es que el total esté escrito DENTRO del botón. Es el
  // mismo criterio con el que descartar va sin diálogo.
  //
  // La respuesta trae la lista ENTERA, como partir: enviar mueve el estado del
  // pedido, el de todos sus renglones, la vista previa de la partición, el
  // conteo de huecos y la cola del botón de completar.
  async function enviarPedido(pedidoId, nombre, boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch(
        '/api/pedido/' + pedidoId + '/enviar', { method: 'POST' }), 'al_guardar');

    if (!respuesta.ok) {
      boton.disabled = false;
      // Genérico a propósito (regla 5 de CLAUDE.md): el detalle está en la
      // bitácora del servidor.
      notaDeFalla('pedido-accion', respuesta);
      return;
    }

    datos = conservarLoDeLaCarga(respuesta, datos);
    if (Array.isArray(datos.puente)) PROVEEDORES = datos.puente;
    conteoEnvejecido = false;
    repintar();
    nota('pedido-accion',
      'Pedido a ' + nombre + ' marcado como enviado. Sus renglones pasaron a '
      + '«en tránsito», así que la lista de mañana ya no los va a volver a '
      + 'proponer. Recuerda: esto no se lo mandó a ' + nombre + ' — lo capturas '
      + 'tú en su portal.', 'todo');
  }

  // TACHAR UN RENGLÓN EN LA PANTALLA DE CAPTURA (ticket 22).
  //
  // El avance se guarda EN EL SERVIDOR y no en el navegador (ADR 0010): con
  // `localStorage` dos pestañas del mismo pedido divergirían en silencio, y el
  // encargado que cambia de máquina a la mitad de 40 renglones empezaría de
  // cero. Por eso aquí no se lleva ninguna cuenta: se manda "déjalo tachado" o
  // "déjalo sin tachar" —explícito, nunca "alterna", para que la pestaña que
  // iba atrasada no deshaga lo que hizo la otra— y se pinta lo que vuelve.
  //
  // La respuesta trae la lista ENTERA, como partir y enviar: tachar cambia
  // cuántos faltan en su pedido y, con el último, la invitación a enviar.
  //
  // El foco vuelve a la misma casilla después de repintar, para que se pueda
  // seguir con el teclado; y cuando el que se tachó fue el ÚLTIMO, va al botón
  // de enviar. Eso es la quinta casilla: tachar todo LLEVA a enviar. El botón
  // no se apaga ni se enciende por la captura — solo se le lleva el foco.
  async function tacharRenglon(renglonId, pedidoId, capturado, casilla) {
    casilla.disabled = true;
    const aviso = casilla.closest('.captura')?.querySelector('.nota-captura');
    if (aviso) aviso.textContent = '';

    const respuesta = await respuestaDe(fetch('/api/renglon/' + renglonId + '/capturado', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capturado: capturado }),
      }), 'al_guardar');

    if (!respuesta.ok) {
      // Falla ruidoso (regla 4): la casilla vuelve a como estaba y se dice por
      // qué, al lado de la lista y no arriba de la tabla, que queda lejos.
      // Genérico a propósito (regla 5): el detalle vive en la bitácora. Sin
      // respuesta NO se afirma que la marca no se guardó: se manda a mirar.
      casilla.checked = !capturado;
      casilla.disabled = false;
      if (aviso) aviso.textContent = fallaEnUnaLinea(respuesta);
      return;
    }

    datos = conservarLoDeLaCarga(respuesta, datos);
    if (Array.isArray(datos.puente)) PROVEEDORES = datos.puente;
    repintar();

    const pedido = (datos.pedidos || []).find(p => p.pedido_id === pedidoId);
    const destino = pedido && pedido.captura && pedido.captura.todo_capturado && capturado
      ? document.querySelector('[data-enviar="' + pedidoId + '"]')
      : document.querySelector('[data-captura-renglon="' + renglonId + '"]');
    if (destino) {
      destino.focus();
      destino.scrollIntoView({ block: 'nearest' });
    }
  }

  // Consultar el precio en los cuatro proveedores (ticket 12).
  //
  // **La petición vuelve de inmediato y la consulta sigue del lado del
  // servidor.** Una búsqueda tarda nueve segundos por proveedor en el mejor
  // caso y hasta minuto y medio en el peor: si esta llamada esperara el
  // resultado, la pantalla se quedaría colgada todo ese rato y una recarga
  // tiraría una visita al portal que ya se hizo. Quien espera es un hilo de
  // Continental, que **escribe el precio en cuanto llega**; aquí solo se
  // pregunta cómo va.
  //
  // Por eso cerrar la pestaña a la mitad no pierde nada: la siguiente carga de
  // la página trae los precios congelados dentro de cada renglón.
  async function consultarPrecio(r, boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch('/api/renglon/' + r.renglon_id + '/precio',
                                     { method: 'POST' }), 'al_guardar');

    if (!respuesta.ok) {
      boton.disabled = false;
      // El motivo viene del servidor y es genérico a propósito (regla 5): el
      // detalle está en la bitácora.
      notaDeFalla('pedido-accion', respuesta);
      return;
    }

    aplicarPrecios(r.renglon_id, respuesta);
    if (respuesta.consulta && respuesta.consulta.en_curso) sondear(r.renglon_id);
  }

  // COMPLETAR SOLO LOS PRECIOS QUE FALTAN (ticket 19, segunda casilla).
  //
  // La petición vuelve de inmediato y el trabajo sigue del lado del servidor,
  // igual que el botón de un renglón: doce renglones son dos minutos largos.
  // Lo que cambia es que aquí el servidor consulta UNO TRAS OTRO en un solo
  // hilo —pedirle a Doyle doce búsquedas a la vez es justo lo que le impide
  // reutilizar el navegador que tenga abierto— así que esta pantalla sondea
  // cada renglón de la cola y los va pintando conforme llegan.
  //
  // **QUIÉN ENTRA A LA COLA LO DECIDIÓ EL SERVIDOR.** Aquí no se filtra nada:
  // la regla de qué cuenta como faltante cuesta ~36 s de navegador por renglón
  // de más, y vive en una función pura con pruebas (`faltantes.por_que_falta`),
  // no en este archivo.
  async function completarLoQueFalta(boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch('/api/pedido-sugerido/' +
        datos.pedido_sugerido_id + '/completar', { method: 'POST' }), 'al_guardar');

    if (!respuesta.ok) {
      boton.disabled = false;
      // El motivo viene del servidor y es genérico a propósito (regla 5).
      notaDeFalla('pedido-accion', respuesta);
      return;
    }

    if (!respuesta.lanzados) {
      boton.disabled = false;
      nota('pedido-accion', respuesta.detalle || 'No falta ningún precio.', 'aviso');
      return;
    }

    // Se dice cuánto tarda y de qué depende. Una espera sin número se lee como
    // "se colgó" a los quince segundos, y ésta son ~36 s por renglón.
    nota('pedido-accion',
      'Consultando ' + respuesta.lanzados + ' renglón(es), uno tras otro. Tarda ' +
      'alrededor de medio minuto por renglón y se van pintando conforme llegan. ' +
      'Puedes cerrar la pestaña: los precios se guardan solos. Lo que no alcance ' +
      'en ' + respuesta.tope_minutos + ' min se queda como está, con su botón.', 'aviso');

    // Un sondeo por renglón de la cola, con el mismo mecanismo que el botón de
    // uno solo: la ruta de sondeo es de UN renglón y no hay una de lista, así
    // que esto son N sondeos de un GET corto cada dos segundos. Es más ruido
    // del que gustaría y es lo honesto con lo que hay: inventar aquí un estado
    // de la cola sería una segunda versión de lo que el servidor sabe.
    (respuesta.faltantes.renglones || []).forEach(f => sondear(f.renglon_id));
  }

  // ABRIR LA SESIÓN DE UN PROVEEDOR, en dos pasos y sin salir de aquí
  // (ticket 19, tercera casilla).
  //
  // **Continental no abre el navegador y no podría** (regla 1 de CLAUDE.md):
  // se lo pide a Doyle por HTTP, y Doyle lo abre en la máquina donde Doyle
  // corre. Lo que esta pantalla evita es tener que ir a OTRA aplicación a
  // disparar los dos pasos; lo que no puede evitar es que alguien tenga que
  // teclear la contraseña en esa ventana, que es de lo que se trata.
  async function abrirSesion(sesion, boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch('/api/sesion/' + sesion.proveedor + '/abrir',
                                     { method: 'POST' }), 'al_guardar');

    boton.disabled = false;
    if (!respuesta.ok) {
      notaDeFalla('pedido-accion', respuesta);
      return;
    }
    // LO QUE FALTA, DICHO, y por eso no se escribe "listo": lo que hay es una
    // ventana esperando. Un botón que contesta "listo" sobre una sesión que
    // sigue caducada es la falla silenciosa que la regla 4 prohíbe.
    nota('pedido-accion', respuesta.detalle + ' ' + respuesta.siguiente, 'aviso');
  }

  async function confirmarSesion(sesion, boton) {
    boton.disabled = true;
    nota('pedido-accion', '');

    const respuesta = await respuestaDe(fetch('/api/sesion/' + sesion.proveedor + '/confirmar',
                                     { method: 'POST' }), 'al_guardar');

    boton.disabled = false;
    if (!respuesta.ok) {
      notaDeFalla('pedido-accion', respuesta);
      return;
    }
    // El aviso honesto de Doyle —"la página seguía viéndose como un login"— se
    // escribe en ámbar y no en verde: es la diferencia entre "ya está" y
    // "vuelve a intentarlo".
    nota('pedido-accion', respuesta.detalle,
      respuesta.todavia_parece_login ? 'aviso' : '');
  }

  // Lo que llega del servidor se mete DENTRO del renglón, que es donde vive el
  // precio congelado en todo lo demás. Nada se deduce aquí: ni el motivo, ni
  // la fecha, ni si hay dato — todo eso viene calculado de Python, que es
  // donde hay pruebas.
  const aplicarPrecios = (renglonId, respuesta) => {
    const r = datos.renglones.find(x => x.renglon_id === renglonId);
    if (!r) return;
    // LOS PRECIOS QUE NO SE PUDIERON LEER NO BORRAN LOS QUE HAY (ticket 29).
    // Hasta entonces llegaban como `[]` y se pintaban encima: un renglón con
    // tres cotizaciones pasaba a "sin consultar" porque una lectura falló.
    // Ahora llegan `null` con `precios_sin_leer`, y la fila se queda como
    // estaba —con el estado de la consulta al día— y la falla se dice.
    if (respuesta.precios_sin_leer) {
      r.consulta = respuesta.consulta || r.consulta;
      notaDeFalla('pedido-accion', respuesta.precios_sin_leer);
      repintar();
      return;
    }
    r.precios = respuesta.precios || [];
    // La comparación llega ya hecha: quién gana, la diferencia de cada uno y el
    // ahorro contra NADRO. Recalcularla aquí pondría la regla que decide a
    // quién comprarle en dos lugares, y uno de los dos no tendría pruebas.
    r.comparacion = respuesta.comparacion || null;
    r.consulta = respuesta.consulta || null;
    // CONSULTAR UN PRECIO CAMBIA EL CONTEO DE ARRIBA Y ESTA RESPUESTA NO LO
    // TRAE: es de un renglón, y el conteo es de la lista.
    //
    // No se recuenta aquí —sería la regla de "qué es sin comparar" escrita por
    // segunda vez, en el archivo sin pruebas— y **no se vuelve a pedir la
    // lista**: la pantalla la pide UNA sola vez a propósito, y tres pruebas lo
    // fijan (`test_vistas`, `test_sugerido`, `test_clasificacion`). Dos
    // lecturas en momentos distintos pueden no coincidir y nadie sabría cuál
    // tiene razón; ese acuerdo es más viejo que este ticket y no se rompe por
    // un número.
    //
    // Lo que queda es decirlo: el conteo se marca como viejo y la pantalla
    // escribe que lo es. Un número envejecido que se presenta como fresco es
    // exactamente la falla silenciosa que la regla 4 de CLAUDE.md prohíbe — y
    // envejece hacia el lado seguro, diciendo más huecos de los que quedan.
    if (!r.consulta || !r.consulta.en_curso) conteoEnvejecido = true;
    repintar();
  };

  // Cada cuánto se le pregunta a Continental, y hasta cuándo. Dos segundos
  // porque la consulta tarda decenas de segundos y no décimas: preguntar cada
  // 200 ms serían trescientas peticiones para enterarse de lo mismo.
  //
  // El tope de aquí es más largo que el del servidor (120 s en
  // `config/continental.yml`) a propósito: el que decide cuándo se acaba la
  // espera es el servidor, y este número solo existe para que el navegador no
  // se quede preguntando para siempre si el servidor se reinició a la mitad.
  const CADA_MS = 2000;
  const HASTA_MS = 180000;

  function sondear(renglonId) {
    const desde = Date.now();
    const vuelta = async () => {
      const respuesta = await respuestaDe(fetch('/api/renglon/' + renglonId + '/precio'));
      if (!respuesta.ok) {
        // Sin respuesta, o un 500: la fila se queda como estaba —no se pinta
        // una respuesta que no es de precios— y se deja de preguntar. Lo que
        // Doyle haya contestado se guarda solo, del lado del servidor.
        notaDeFalla('pedido-accion', respuesta);
        return;
      }

      aplicarPrecios(renglonId, respuesta);

      if (!respuesta.consulta || !respuesta.consulta.en_curso) return;
      if (Date.now() - desde > HASTA_MS) {
        // No se dice "falló": no se sabe. Lo que se sabe es que esta pantalla
        // dejó de preguntar, y que lo que Doyle haya contestado está guardado.
        nota('pedido-accion',
          'La consulta está tardando más de lo normal. Vuelve a cargar la página ' +
          'en un rato: el precio se guarda solo en cuanto Doyle conteste.', 'aviso');
        return;
      }
      setTimeout(vuelta, CADA_MS);
    };
    setTimeout(vuelta, CADA_MS);
  }

  // Un servidor viejo que no mande el conteo no puede dejar la pantalla
  // diciendo "undefined renglones descartados". Se cae a contarlos aquí, que
  // es lo mismo mientras haya una sola pestaña abierta.
  if (typeof datos.descartados !== 'number') {
    datos.descartados = datos.renglones.filter(r => r.estado === DESCARTADO).length;
  }

  // Ya hay tabla: cerrar la lista tiene que volver a pintarla con el estado
  // nuevo, que es lo que apaga los campos de cantidad. Y reabrirla (ADR 0016),
  // que los vuelve a encender.
  alCerrarse = (cambiada) => {
    datos.estado = cambiada.estado;
    repintar();
  };

  if (vistas) mostrar(vistaActiva); else repintar();
}

// El resumen dice el orden a propósito: una lista larga ordenada por un
// criterio que no se anuncia se lee como si no tuviera ninguno. Y dice
// cuántos renglones se quedaron fuera de esta vista, que es lo que distingue
// "el interruptor los escondió" de "no se vendieron": son dos cosas que en
// pantalla se ven idénticas —el renglón no está— y solo una se arregla
// moviendo el interruptor.
// LO QUE VIENE EN CAMINO DE LISTAS ANTERIORES (ticket 24, casillas 2, 4 y 5).
//
// Ninguna frase se compone aquí: el encabezado, "Pedido el martes a NADRO, sin
// recibir.", lo vendido desde entonces y la advertencia de que esto solo sabe
// de lo que pasó por Continental llegan hechos de `transito.py`, con pruebas.
// Aquí se acomodan.
//
// Se pinta SIEMPRE que hay lista, también sin nada en camino: "nada viene en
// camino" es un dato, y la advertencia importa justo entonces — un bloque vacío
// se lee "no hay nada pedido" y puede que sí, capturado por fuera.
//
// Un servidor viejo que no mande el bloque no pinta nada, en vez de inventar
// "nada en camino". Falla hacia no decir, nunca hacia decir de más.
const pintarEnCamino = (en_camino) => {
  const caja = document.getElementById('en-camino');
  if (!en_camino) { caja.hidden = true; caja.replaceChildren(); return; }

  const resumen = document.createElement('p');
  resumen.className = 'resumen' + (en_camino.ok === false ? ' mal' : '');
  resumen.textContent = en_camino.frase
    + (en_camino.ok === false && en_camino.detalle ? ' (' + en_camino.detalle + ')' : '');

  const advertencia = document.createElement('p');
  advertencia.className = 'advertencia';
  advertencia.textContent = en_camino.advertencia;

  // QUÉ ES "ATRASADO" AQUÍ (ticket 25), con su número, o por qué no se sabe.
  // Las dos frases llegan hechas de Python; la de los atrasados solo si hay.
  const umbral = document.createElement('p');
  umbral.className = 'umbral' + (en_camino.umbral_del_atraso == null ? ' mal' : '');
  // Una u otra, no las dos: la de los atrasados ya lleva el número, y repetir
  // "más de 7 días" dos veces seguidas lo cazó el recorrido del navegador.
  umbral.textContent = en_camino.frase_de_los_atrasados || en_camino.frase_del_umbral || '';
  const hayAtrasados = (en_camino.renglones || []).some(v => v.se_puede_devolver);
  const alDevolver = document.createElement('p');
  alDevolver.className = 'advertencia';
  alDevolver.textContent = en_camino.advertencia_al_devolver || '';

  const lista = document.createElement('ul');
  (en_camino.renglones || []).forEach(v => {
    const li = document.createElement('li');
    li.className = 'transito' + (v.atrasado ? ' atrasado' : '');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = (v.clave ? v.clave + ' · ' : '') + v.descripcion;
    const cuanto = document.createElement('span');
    cuanto.className = 'cuanto';
    cuanto.textContent = plural(v.cantidad, 'pieza', 'piezas');
    const cuando = document.createElement('span');
    cuando.className = 'cuando';
    cuando.textContent = v.frase;
    // La firma —quién, a qué hora, de qué lista— a la vista y no en un
    // `title`, que en una pantalla táctil no se ve nunca. Hecha en Python: la
    // primera versión se armaba aquí y escribía "a.m..", igual que en el 21.
    const firma = document.createElement('span');
    firma.className = 'vendido-desde';
    firma.textContent = v.firma || '';
    const vendido = document.createElement('span');
    vendido.className = 'vendido-desde';
    vendido.textContent = v.frase_de_lo_vendido;
    li.append(que, cuanto, cuando, vendido, firma);
    // ATRASADO, CON LOS DÍAS A LA VISTA (ticket 25). La frase y la decisión de
    // ofrecer el botón son de Python; el servidor lo vuelve a comprobar en el
    // `WHERE` con el mismo límite.
    if (v.frase_del_atraso) {
      const atraso = document.createElement('span');
      atraso.className = 'atraso';
      atraso.textContent = v.frase_del_atraso;
      li.append(atraso);
    }
    // CON PROPUESTA DE RECEPCIÓN (ticket 26): en lugar del botón de devolver,
    // la frase que manda a confirmar o rechazar primero. Viene de Python.
    if (v.frase_de_la_recepcion) {
      const recepcion = document.createElement('span');
      recepcion.className = 'recepcion-marca';
      recepcion.textContent = v.frase_de_la_recepcion;
      li.append(recepcion);
    }
    if (v.se_puede_devolver) {
      const boton = botonDeAccion('Devolver a la lista',
        (b) => devolverAtrasado(v.renglon_id, b));
      boton.setAttribute('aria-label', 'Devolver a la lista ' + v.descripcion);
      li.append(boton);
    }
    lista.append(li);
  });

  // CANCELAR UN PEDIDO DE UNA LISTA ANTERIOR (ticket 25). Uno por pedido, con
  // lo que declara quien lo aprieta escrito AL LADO del botón — la misma
  // lección que el total dentro del botón de enviar: el diálogo de "¿seguro?"
  // se aprende a despachar sin leer; la frase junto al botón, no.
  const pedidos = document.createElement('ul');
  pedidos.className = 'pedidos-en-camino';
  (en_camino.pedidos || []).forEach(p => {
    const li = document.createElement('li');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = p.frase;
    const explica = document.createElement('span');
    explica.className = 'explica';
    // Un pedido con algo ya recibido (ticket 26) sí se capturó: no se ofrece
    // cancelarlo, y se dice por qué en vez de pintar un botón que da 409.
    if (p.se_puede_cancelar === false) {
      explica.textContent = 'No se puede cancelar: ' + p.motivo_para_no_cancelar + '.';
      li.append(que, explica);
    } else {
      explica.textContent = p.frase_para_cancelar;
      const boton = botonDeAccion('Cancelar: no está en el portal de ' + p.nombre,
        (b) => cancelarPedido(p.pedido_id, b));
      li.append(que, boton, explica);
    }
    pedidos.append(li);
  });

  // LO QUE VUELVE EN LA SIGUIENTE LISTA (ticket 25): lo que se canceló o se
  // devolvió y ninguna lista ha vuelto a traer todavía. Se enseña para que el
  // número de mañana se pueda explicar hoy.
  const vuelven = document.createElement('ul');
  vuelven.className = 'vuelven';
  // El encabezado viene de Python: sin él, esta lista se leía como parte del
  // pedido de arriba (recorrido del navegador, ticket 25).
  if (en_camino.frase_de_los_que_vuelven) {
    const encabezado = document.createElement('li');
    encabezado.className = 'explica';
    encabezado.textContent = en_camino.frase_de_los_que_vuelven;
    vuelven.append(encabezado);
  }
  (en_camino.vuelven || []).forEach(v => {
    const li = document.createElement('li');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = (v.clave ? v.clave + ' · ' : '') + v.descripcion;
    const explica = document.createElement('span');
    explica.className = 'explica';
    explica.textContent = v.frase;
    li.append(que, explica);
    vuelven.append(li);
  });

  // LO QUE LLEGÓ DE MENOS (ticket 27): lo que faltó vuelve en la siguiente
  // lista, y aquí se ve —con su firma— y se corrige si el resto llegó en otra
  // factura. Todas las frases y la etiqueta son de Python.
  const faltaron = document.createElement('ul');
  faltaron.className = 'faltaron';
  if (en_camino.frase_de_los_que_faltaron) {
    const encabezado = document.createElement('li');
    encabezado.className = 'explica';
    encabezado.textContent = en_camino.frase_de_los_que_faltaron;
    faltaron.append(encabezado);
  }
  (en_camino.faltaron || []).forEach(f => {
    const li = document.createElement('li');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = (f.clave ? f.clave + ' · ' : '') + f.descripcion;
    const explica = document.createElement('span');
    explica.className = 'explica';
    explica.textContent = f.frase;
    li.append(que, explica,
      controlAMano(f.renglon_id, f.etiqueta_a_mano, f.descripcion, f.piezas_recibidas));
    faltaron.append(li);
  });

  caja.replaceChildren(
    resumen,
    advertencia,
    ...(umbral.textContent ? [umbral] : []),
    ...(hayAtrasados && alDevolver.textContent ? [alDevolver] : []),
    ...(lista.children.length ? [lista] : []),
    ...(pedidos.children.length ? [pedidos] : []),
    ...(vuelven.children.length ? [vuelven] : []),
    ...(faltaron.children.length ? [faltaron] : []));
  caja.hidden = false;
};

// LA RECEPCIÓN SUGERIDA (ticket 26, ADR 0014). Lo que probablemente ya
// llegó, con su evidencia —proveedor, fecha, piezas, folio— para que una
// persona la juzgue, y dos botones: confirmar (pasa a recibido, firmado) y
// rechazar (sigue en camino; esa compra ya no se le propone). NADA pasa a
// recibido solo.
//
// Todas las frases llegan hechas de `recepcion.py`, con pruebas: aquí se
// acomodan. Lo que se manda al servidor es QUÉ COMPRAS SE VIERON: el servidor
// recalcula la propuesta y se niega si ya no es la misma.
//
// Un servidor viejo que no mande el bloque no pinta nada.
const pintarRecepcion = (recepcion) => {
  const caja = document.getElementById('recepcion');
  if (!recepcion) { caja.hidden = true; caja.replaceChildren(); return; }

  const resumen = document.createElement('p');
  resumen.className = 'resumen' + (recepcion.ok === false ? ' mal' : '');
  resumen.textContent = recepcion.frase
    + (recepcion.ok === false && recepcion.detalle ? ' (' + recepcion.detalle + ')' : '');

  // El aviso del retraso de una noche (casilla 6) va SIEMPRE.
  const retraso = document.createElement('p');
  retraso.className = 'umbral';
  retraso.textContent = recepcion.aviso_del_retraso || '';

  const advertencia = document.createElement('p');
  advertencia.className = 'advertencia';
  advertencia.textContent = recepcion.advertencia || '';

  // Qué declara quien recibe a mano (ticket 27), una vez arriba.
  const aMano = document.createElement('p');
  aMano.className = 'advertencia';
  aMano.textContent = recepcion.como_se_recibe_a_mano || '';

  const lista = document.createElement('ul');
  (recepcion.propuestas || []).forEach(p => {
    const li = document.createElement('li');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = (p.clave ? p.clave + ' · ' : '') + p.descripcion;
    const cuanto = document.createElement('span');
    cuanto.className = 'cuanto';
    cuanto.textContent = plural(p.cantidad, 'pieza', 'piezas');
    const encabezado = document.createElement('span');
    encabezado.className = 'cuando';
    encabezado.textContent = p.frase;
    const cuando = document.createElement('span');
    cuando.className = 'vendido-desde';
    cuando.textContent = p.frase_del_transito || '';
    // LA EVIDENCIA, compra por compra: es lo que la persona juzga.
    const evidencia = document.createElement('ul');
    evidencia.className = 'evidencia';
    (p.evidencia || []).forEach(e => {
      const item = document.createElement('li');
      item.textContent = e.frase;
      evidencia.append(item);
    });
    const cantidad = document.createElement('span');
    cantidad.className = 'cantidad';
    cantidad.textContent = p.frase_de_la_cantidad;
    li.append(que, cuanto, encabezado, cuando, evidencia, cantidad);
    if (p.compartida) {
      const compartida = document.createElement('span');
      compartida.className = 'compartida';
      compartida.textContent = p.compartida;
      li.append(compartida);
    }
    // Sin botón de confirmar cuando la evidencia no alcanza lo pedido: la
    // frase de la cantidad, que viene de Python, ya dice por qué (y el
    // recorrido del navegador cazó que el motivo repetido debajo la duplicaba).
    if (p.se_puede_confirmar) {
      const confirmar = botonDeAccion('Confirmar que llegó',
        (b) => recibirORechazar('confirmar', p.renglon_id, p.compras, b));
      confirmar.setAttribute('aria-label', 'Confirmar que llegó ' + p.descripcion);
      li.append(confirmar);
    }
    // Lo que trae de menos (ticket 27): la etiqueta, con sus números, viene
    // hecha de Python.
    if (p.se_puede_recibir_lo_que_trae && p.etiqueta_de_lo_que_trae) {
      li.append(botonDeAccion(p.etiqueta_de_lo_que_trae,
        (b) => recibirParcial(p.renglon_id, p.compras, b)));
    }
    const rechazar = botonDeAccion('Rechazar: no es este pedido',
      (b) => recibirORechazar('rechazar', p.renglon_id, p.compras, b));
    rechazar.setAttribute('aria-label', 'Rechazar la compra de ' + p.descripcion);
    li.append(rechazar);
    // Y siempre a mano: la compra de 10 que surtió dos pedidos solo confirma
    // uno, y el otro se recibe así.
    if (p.etiqueta_a_mano) li.append(controlAMano(p.renglon_id, p.etiqueta_a_mano, p.descripcion));
    lista.append(li);
  });

  // LO QUE NO TIENE PROPUESTA, agrupado por motivo, en el orden de Python: lo
  // que no la va a tener va primero y lo dice —no se deja esperando callado—.
  const esperan = document.createElement('ul');
  esperan.className = 'esperan';
  (recepcion.esperan || []).forEach(g => {
    const li = document.createElement('li');
    const explica = document.createElement('span');
    explica.className = 'explica';
    explica.textContent = g.frase;
    // Uno por renglón, cada uno con su salida a mano (ticket 27): hasta el 26
    // iban en una sola línea, porque no había nada que hacer con ninguno.
    const cuales = document.createElement('ul');
    cuales.className = 'cuales';
    (g.renglones || []).forEach(r => {
      const fila = document.createElement('li');
      const que = document.createElement('span');
      que.className = 'que';
      que.textContent = (r.clave ? r.clave + ' · ' : '') + r.descripcion;
      fila.append(que);
      if (r.etiqueta_a_mano) fila.append(controlAMano(r.renglon_id, r.etiqueta_a_mano, r.descripcion));
      cuales.append(fila);
    });
    li.append(explica, cuales);
    esperan.append(li);
  });

  const hayRenglones = lista.children.length || esperan.children.length;
  caja.replaceChildren(
    resumen,
    ...(retraso.textContent ? [retraso] : []),
    ...(lista.children.length && advertencia.textContent ? [advertencia] : []),
    ...(hayRenglones && aMano.textContent ? [aMano] : []),
    ...(lista.children.length ? [lista] : []),
    ...(esperan.children.length ? [esperan] : []));
  caja.hidden = false;
};

// Confirmar o rechazar: la misma ida y vuelta, y después SE VUELVE A CARGAR la
// pantalla entera —cambian la recepción, lo que viene en camino y quizá el
// renglón de hoy—, en vez de deducir aquí qué cambió.
const recibirORechazar = async (accion, renglonId, compras, boton) => {
  boton.disabled = true;
  nota('pedido-accion', '');
  const respuesta = await respuestaDe(fetch('/api/renglon/' + renglonId + '/recepcion/' + accion, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ compras }),
    }), 'al_guardar');
  if (!respuesta.ok) {
    boton.disabled = false;
    // Genérico a propósito (regla 5): el detalle está en la bitácora.
    notaDeFalla('pedido-accion', respuesta);
    return;
  }
  await cargarPedido();
  nota('pedido-accion', respuesta.frase, 'todo');
};

// RECIBIR PARCIAL CON LA EVIDENCIA (ticket 27, ADR 0015): la misma ida y vuelta
// que confirmar y rechazar —el servidor recalcula la propuesta y se niega si ya
// no es la que se vio—, con su propia acción.
const recibirParcial = (renglonId, compras, boton) =>
  recibirORechazar('parcial', renglonId, compras, boton);

// RECIBIR A MANO Y CORREGIR LA CIFRA (ticket 27, ADR 0015). Un campo y un
// botón: cuántas llegaron EN TOTAL. Es el mismo control para lo que viene en
// camino y para lo que ya llegó —la segunda factura, un error de captura—,
// porque para quien lo escribe es la misma pregunta. La etiqueta llega de
// Python; aquí no se compone ninguna palabra.
//
// `min="1"` es comodidad: la defensa —entero, mayor que cero— es del servidor
// (`recepcion.piezas_escritas`) y del CHECK de la tabla, igual que la cantidad.
const controlAMano = (renglonId, etiqueta, descripcion, valor) => {
  const caja = document.createElement('span');
  caja.className = 'a-mano';
  const campo = document.createElement('input');
  campo.type = 'number';
  campo.min = '1';
  campo.step = '1';
  campo.inputMode = 'numeric';
  if (valor != null) campo.value = valor;
  campo.setAttribute('aria-label', etiqueta + ': ' + descripcion);
  const boton = botonDeAccion(etiqueta, (b) => recibirAMano(renglonId, campo.value, b));
  boton.setAttribute('aria-label', etiqueta + ': ' + descripcion);
  caja.append(campo, boton);
  return caja;
};

// La ida y vuelta, y después SE VUELVE A CARGAR la pantalla entera —cambian la
// recepción, lo que viene en camino, el renglón de hoy y el estado de su
// pedido— en vez de deducir aquí qué cambió.
const recibirAMano = async (renglonId, escrito, boton) => {
  // Lo escrito viaja como número si lo es y tal cual si no: quien dice si
  // sirve —entero, de 1 en adelante— es el servidor, con sus palabras.
  const numero = Number(escrito);
  const piezas = escrito === '' ? null : (Number.isFinite(numero) ? numero : escrito);
  boton.disabled = true;
  nota('pedido-accion', '');
  const respuesta = await respuestaDe(fetch('/api/renglon/' + renglonId + '/recepcion/a-mano', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ piezas }),
    }), 'al_guardar');
  if (!respuesta.ok) {
    boton.disabled = false;
    // Genérico a propósito (regla 5): el detalle está en la bitácora.
    notaDeFalla('pedido-accion', respuesta);
    return;
  }
  await cargarPedido();
  nota('pedido-accion', respuesta.frase, 'todo');
};

// CANCELAR UN PEDIDO Y DEVOLVER UN ATRASADO (ticket 25, ADR 0013).
//
// Las dos cambian lo que viene en camino, lo que vuelve en la siguiente lista y
// el estado de los renglones de hoy, y el bloque de lo que viene en camino solo
// lo trae la carga. Así que al terminar **se vuelve a cargar la pantalla
// entera** en vez de deducir aquí qué cambió: es la misma regla de siempre, las
// cuentas las lleva el servidor. Continental no cancela nada en ningún portal;
// la frase de al lado del botón lo dice, y la respuesta también.
const cancelarPedido = async (pedidoId, boton) => {
  boton.disabled = true;
  nota('pedido-accion', '');
  const respuesta = await respuestaDe(fetch('/api/pedido/' + pedidoId + '/cancelar',
      { method: 'POST' }), 'al_guardar');
  if (!respuesta.ok) {
    boton.disabled = false;
    // Genérico a propósito (regla 5): el detalle está en la bitácora.
    notaDeFalla('pedido-accion', respuesta);
    return;
  }
  await cargarPedido();
  nota('pedido-accion', respuesta.frase, 'todo');
};

const devolverAtrasado = async (renglonId, boton) => {
  boton.disabled = true;
  nota('pedido-accion', '');
  const respuesta = await respuestaDe(fetch('/api/renglon/' + renglonId + '/devolver-atrasado',
      { method: 'POST' }), 'al_guardar');
  if (!respuesta.ok) {
    boton.disabled = false;
    notaDeFalla('pedido-accion', respuesta);
    return;
  }
  await cargarPedido();
  nota('pedido-accion', respuesta.frase, 'todo');
};

const pintarRenglones = (visibles, total, otra, descartados, acciones) => {
  const escondidos = total - visibles.length;
  // LOS QUE YA SE PIDIERON NO SON "POR ATENDER" (ticket 21). Siguen en la
  // tabla —no desaparecen— pero contarlos aquí diría que queda trabajo donde
  // ya no queda, y ése es el número que se lee de un vistazo. Se cuentan sobre
  // los VISIBLES y no sobre la lista entera porque es el número que acompaña a
  // lo que se está viendo; el de la lista entera viaja aparte en `en_transito`.
  const enTransito = visibles.filter(r => r.esta_en_transito).length;
  // Y LOS CANCELADOS (ticket 25), por lo mismo: siguen en la tabla y ya no se
  // atienden aquí — vuelven en la siguiente lista.
  const cancelados = visibles.filter(r => r.esta_cancelado).length;
  // Y LO QUE YA LLEGÓ (ticket 26): se pidió y se recibió. Lo cazó el recorrido
  // del navegador: un renglón recibido seguía contando "por atender".
  const recibidos = visibles.filter(r => r.esta_recibido).length;
  document.getElementById('pedido-resumen').textContent =
    plural(visibles.length - enTransito - cancelados - recibidos,
      'renglón por atender', 'renglones por atender') +
    ', uno por producto vendido. Se propone reponer lo que salió, pieza por ' +
    'pieza. Arriba lo que se va a acabar primero. ' +
    (escondidos
      ? 'Esta vista esconde ' + plural(escondidos, 'renglón de abarrote', 'renglones de abarrote') +
        ' y nada más: los sin clasificar siguen aquí. Cámbiala a «' + otra.nombre +
        '» para verlos todos. '
      : 'Nada se escondió de esta vista. ') +
    // Se dice aquí además de en el bloque de abajo: "por atender" bajó de
    // número y la razón tiene que estar donde se lee el número, o parecería
    // que se vendió menos.
    // La frase entera pasa por `plural` y no solo su primera mitad: "1 renglón
    // descartado no aparece aquí: están abajo" es lo que sale de pegar un
    // sujeto en singular a un verbo en plural, y se vio así al recorrer la
    // pantalla el 2026-09-19.
    (descartados
      ? plural(descartados,
          'renglón descartado no aparece aquí y se puede devolver desde abajo. ',
          'renglones descartados no aparecen aquí y se pueden devolver desde abajo. ')
      : '') +
    // Y los que ya se pidieron, por lo mismo que los descartados: el número de
    // arriba bajó y la razón tiene que estar donde se lee el número, o
    // parecería que se vendió menos. Éstos SÍ siguen en la tabla, y eso se
    // dice: "no aparecen aquí" sería mentira.
    (enTransito
      ? plural(enTransito,
          'renglón más ya se pidió y sigue aquí, marcado como en tránsito. ',
          'renglones más ya se pidieron y siguen aquí, marcados como en tránsito. ')
      : '') +
    (cancelados
      ? plural(cancelados,
          'renglón más se dejó de esperar: sigue aquí, marcado, y vuelve en la siguiente lista. ',
          'renglones más se dejaron de esperar: siguen aquí, marcados, y vuelven en la siguiente lista. ')
      : '') +
    (recibidos
      ? plural(recibidos,
          'renglón más ya se pidió y llegó: sigue aquí, marcado como recibido.',
          'renglones más ya se pidieron y llegaron: siguen aquí, marcados como recibidos.')
      : '');
  document.getElementById('pedido-renglones').replaceChildren(
    ...visibles.map(r => renglon(r, acciones)));
};

// EL CONTEO DE LA LISTA (ticket 15): cuántos renglones quedaron sin comparar.
//
// Es la frase que define el ticket puesta en una línea: *que nadie lea la lista
// como si estuviera completa*. Veinte renglones con su tabla de cuatro
// proveedores se ven exactamente igual tengan cuatro precios o ninguno, y la
// única forma de saberlo sin esto es abrirlos uno por uno — que es justo lo que
// la cuarta casilla prohíbe.
//
// **Ningún número se calcula aquí.** Los seis llegan de `contar_la_lista`, que
// es una función pura con su tabla de casos; este archivo los acomoda en una
// frase. Contar renglones en el navegador habría puesto la regla de qué es
// "sin comparar" —que no es obvia: consultado sin precios y no consultado son
// dos cosas— en el único archivo que ninguna prueba de Python mira.
//
// El desglose va porque las tres se atienden distinto: la primera es un botón,
// la segunda es mirar el motivo de cada hueco, y la tercera no se arregla —es
// una advertencia sobre lo que ese precio puede decir de sí mismo—.
const pintarConteoDePrecios = (conteo, envejecido) => {
  const p = document.getElementById('pedido-sin-comparar');
  // Un servidor viejo que no mande el conteo no escribe nada, en vez de
  // escribir "undefined renglones sin comparar". Falla hacia no decir, nunca
  // hacia decir un número inventado.
  if (!conteo || !conteo.renglones) { p.hidden = true; p.textContent = ''; return; }

  p.className = 'nota conteo ' + (conteo.hay_sin_comparar ? 'aviso' : 'todo');
  p.replaceChildren();

  // Lo que se consultó desde que llegó este conteo no está dentro de él, y se
  // dice con todas sus letras. Va al final de la frase y no en lugar de ella:
  // el número sigue siendo el último que el servidor calculó, y sigue siendo
  // la cota alta de lo que falta.
  const coletilla = envejecido
    ? ' Se han consultado precios desde que se cargó la lista: este conteo es '
      + 'de antes de eso. Recarga la página para ponerlo al día.'
    : '';

  if (!conteo.hay_sin_comparar) {
    // El singular se escribe porque pasa: una lista donde se descartó todo
    // menos un renglón. "los 1 renglones" se lee como un error de la pantalla,
    // y una pantalla que parece rota se deja de creer justo donde este ticket
    // necesita que se le crea.
    p.append('Precios: ' + (conteo.renglones === 1
      ? 'el único renglón de la lista se comparó'
      : 'los ' + conteo.renglones + ' renglones de la lista se compararon')
      + ' contra dos o más proveedores.' + coletilla);
    p.hidden = false;
    return;
  }

  const titular = document.createElement('b');
  titular.textContent = conteo.sin_comparar + ' de ' + conteo.renglones
    + (conteo.renglones === 1 ? ' renglón' : ' renglones') + ' sin comparar';
  p.append(titular, ' — la lista NO está completa: ' + (conteo.comparados === 1
    ? 'solo 1 tiene dos precios o más.'
    : conteo.comparados + ' tienen dos precios o más.'));

  // Las tres partes, y solo las que valen algo: un "0 sin consultar" en medio
  // de la frase es ruido que hace más difícil leer las que sí importan.
  const partes = [];
  if (conteo.sin_consultar) {
    partes.push(conteo.sin_consultar + ' sin consultar (nadie ha pedido su precio)');
  }
  if (conteo.sin_un_solo_precio) {
    partes.push(conteo.sin_un_solo_precio + (conteo.sin_un_solo_precio === 1
      ? ' se consultó y ningún proveedor dio precio'
      : ' se consultaron y ningún proveedor dio precio') + ' (cada hueco dice su motivo)');
  }
  if (conteo.con_un_solo_precio) {
    partes.push(conteo.con_un_solo_precio + (conteo.con_un_solo_precio === 1
      ? ' tiene un solo precio' : ' tienen un solo precio')
      + ': eso no es «el más barato», es el único que contestó');
  }

  const desglose = document.createElement('span');
  desglose.className = 'desglose';
  desglose.textContent = partes.join(' · ') + '.' + coletilla;
  p.append(desglose);

  p.hidden = false;
};

// CÓMO LE FUE AL LOTE DE ANOCHE SOBRE ESTA LISTA (ticket 19, ADR 0007).
//
// Las frases largas vienen HECHAS del servidor —`corrida.frase`
// (`faltantes.frase_de_la_corrida`) cuando SÍ hay fila, `corridaAusente.frase`
// (`faltantes.corrida_ausente_como_json`) cuando NO la hay— y aquí no se
// compone ninguna: lo único que decide esta función es la CLASE CSS, que es
// lo único que le toca decidir a una pantalla.
//
// `corrida` nulo YA NO es una sola cosa (decisión del dueño, 2026-09-21):
// puede ser que el lote todavía no haya tenido su turno sobre esta lista
// —ámbar, nada está mal— o que ya debía haber pasado y no dejó fila, o que
// la LECTURA misma se cayera —las dos, rojo—. Cuál de las dos es viene en
// `corridaAusente.nivel`, decidido en Python contra el horario real del
// timer y no adivinado aquí. Es la otra mitad del hilo abierto 10: hasta el
// ticket 19, un lote que no corrió y un lote que no llegó a este renglón se
// veían idénticos; hasta esta enmienda, un lote que no corrió y uno que
// todavía no le tocaba también.
const pintarCorrida = (corrida, corridaAusente) => {
  const p = document.getElementById('pedido-corrida');
  p.replaceChildren();

  if (!corrida) {
    if (!corridaAusente) {
      // Ni corrida ni el porqué de que no la haya (las rutas que no la leen,
      // como cerrar y reabrir, la mandan igual — esto es solo el cinturón):
      // no hay nada que pintar, y un hueco vacío no es mejor que nada.
      p.hidden = true;
      return;
    }
    p.className = 'nota corrida ' + corridaAusente.nivel;
    const titular = document.createElement('b');
    titular.textContent = corridaAusente.frase;
    p.append(titular);
    if (corridaAusente.que_hacer) {
      const queHacer = document.createElement('span');
      queHacer.className = 'cuando';
      queHacer.textContent = corridaAusente.que_hacer;
      p.append(queHacer);
    }
    p.hidden = false;
    return;
  }

  p.className = 'nota corrida '
    + (corrida.se_corto_por_tiempo ? 'tope'
      : corrida.se_interrumpio ? 'falla' : 'bien');

  const titular = document.createElement('b');
  titular.textContent = corrida.consultados + ' de ' + corrida.en_la_lista
    + (corrida.en_la_lista === 1 ? ' renglón consultado' : ' renglones consultados')
    + ' por el lote';
  p.append(titular, ' — ' + corrida.frase);

  // Cuándo fue. Sin esto, "el lote consultó 210 de 380" no dice si eso pasó
  // anoche o hace tres días, y son dos cosas distintas: la lista es del día,
  // pero una lista que nadie cerró se puede quedar abierta y envejecer.
  if (corrida.termino_en) {
    const cuando = document.createElement('span');
    cuando.className = 'cuando';
    // Sin punto al final: `instanteEnPalabras` ya acaba en "p.m.", y con el
    // punto salía "02:29 p.m..". Lo cazó el recorrido del navegador del
    // 2026-09-19, que es donde se ven estas cosas y no en un `assert`.
    cuando.textContent = 'La corrida terminó el ' + instanteEnPalabras(corrida.termino_en);
    p.append(cuando);
  }
  p.hidden = false;
};

// EL BOTÓN DE COMPLETAR SOLO LO QUE FALTA, y el de abrir una sesión caducada.
// Las dos últimas casillas del ticket 19, en el mismo recuadro.
//
// El número de la etiqueta viene del SERVIDOR (`faltantes.cuantos`) y no de
// una cuenta de aquí: es el mismo recorrido que decide a quién se le va a
// preguntar, y un conteo que el navegador lleve a mano se separa de la verdad
// en cuanto hay dos pestañas abiertas en el mostrador.
//
// El bloque se esconde entero cuando no falta nada Y no hay sesiones
// caducadas. Eso no deja el caso bueno mudo: quien lo dice es la nota del
// conteo de huecos, en verde, justo encima.
const pintarCompletar = (faltantes, sesiones, acciones) => {
  const caja = document.getElementById('completar');
  const cuantos = (faltantes && faltantes.cuantos) || 0;
  const caducadas = sesiones || [];

  if ((!cuantos && !caducadas.length) || !acciones.editable) {
    // Sin el bloque cuando la lista ya no está abierta: volver a consultar una
    // lista cerrada sería molestar a cuatro portales para cambiar un dato que
    // ya no decide nada. Es el mismo criterio que el botón de cada renglón.
    caja.hidden = true;
    caja.replaceChildren();
    return;
  }

  caja.replaceChildren();

  if (cuantos) {
    const titular = document.createElement('b');
    titular.textContent = cuantos + (cuantos === 1
      ? ' renglón se puede completar' : ' renglones se pueden completar');
    caja.append(titular, ' sin lanzar el lote entero.');

    // QUÉ CUENTA COMO FALTANTE, dicho, porque el número de arriba es más
    // pequeño que "los que están sin comparar" y esa diferencia confunde si no
    // se explica: un renglón con UN precio no entra —consultarlo son cuatro
    // visitas para ganar como mucho una cotización más— y uno sin código de
    // barras tampoco, porque no hay con qué buscarlo.
    const partes = [];
    if (faltantes.sin_consultar) {
      partes.push(faltantes.sin_consultar + ' sin ninguna lectura');
    }
    if (faltantes.reintentables) {
      partes.push(faltantes.reintentables + ' que se consultaron, no dieron ' +
        'precio, y su hueco se puede reintentar');
    }
    const detalle = document.createElement('span');
    detalle.className = 'detalle';
    detalle.textContent = partes.join(' · ')
      + '. No entran los que ya tienen precio, los que no tienen código de '
      + 'barras, ni los huecos que mañana contestarían lo mismo.';
    caja.append(detalle);

    const fila = document.createElement('div');
    fila.className = 'fila';
    // El singular se escribe porque pasa, y con esta frase pasa seguido: se
    // aprieta el botón, quedan dos, se aprieta otra vez y queda uno. "los 1
    // que faltan" se lee como un error de la pantalla, y una pantalla que
    // parece rota se deja de creer justo donde este ticket necesita que se le
    // crea. Lo encontró el recorrido del navegador del 2026-09-19.
    const boton = botonDeAccion(
      cuantos === 1 ? 'Completar el que falta' : 'Completar los ' + cuantos + ' que faltan',
      (b) => acciones.completar(b));
    boton.title = 'Le pregunta a Doyle SOLO por estos renglones, uno tras otro. '
      + 'Tarda alrededor de medio minuto por renglón.';
    fila.append(boton);
    caja.append(fila);
  }

  // LAS SESIONES CADUCADAS, con su botón. Salen de las lecturas congeladas
  // —un portal que mandó al login— y NO del `guardada` de Doyle, que no quiere
  // decir que la sesión sirva: el 2026-09-19 los cuatro decían `guardada` con
  // las cuatro caducadas.
  if (caducadas.length) {
    const bloque = document.createElement('span');
    bloque.className = 'sesiones';
    const titular = document.createElement('b');
    titular.textContent = caducadas.length === 1
      ? 'A un proveedor se le caducó la sesión'
      : 'A ' + caducadas.length + ' proveedores se les caducó la sesión';
    bloque.append(titular,
      ': ' + caducadas.map(s => s.nombre).join(', ') +
      '. Mientras siga así, volver a consultar su precio va a dar el mismo ' +
      'hueco. Se abre en dos pasos, y en medio hay que teclear la contraseña ' +
      'EN LA VENTANA que Doyle abre, en la máquina donde Doyle corre.');
    caducadas.forEach(s => {
      const fila = document.createElement('div');
      fila.className = 'fila';
      const nombre = document.createElement('span');
      nombre.textContent = s.nombre;
      const abrir = botonDeAccion('Abrir sesión', (b) => acciones.abrirSesion(s, b));
      abrir.title = 'Le pide a Doyle que abra el navegador del portal. '
        + 'Continental no abre navegadores: se lo pide a Doyle.';
      const confirmar = botonDeAccion('Ya entré', (b) => acciones.confirmarSesion(s, b));
      confirmar.title = 'Dile a Doyle que ya tecleaste la contraseña, para que '
        + 'guarde las cookies antes de cerrar el navegador.';
      fila.append(nombre, abrir, confirmar);
      bloque.append(fila);
    });
    caja.append(bloque);
  }

  caja.hidden = false;
};

// Los cuatro proveedores tal como el servidor los nombra, para el desplegable
// de cada renglón. Se llena en la carga desde `datos.puente` y **no está
// escrito a mano aquí**: la lista de quiénes son, cómo se escribe cada nombre y
// cuál tiene `pro_id` de SICAR vive en Python, en un solo lugar.
let PROVEEDORES = [];

// EN QUÉ SE PARTE LA LISTA (ticket 20).
//
// Dos cosas distintas en el mismo bloque, y se dicen por separado:
//
//   - la PARTICIÓN, que es el cálculo de ahora mismo: en cuántos pedidos
//     quedaría y cuánto sumaría cada uno si se apretara el botón;
//   - los PEDIDOS, que son las filas que ya existen, con su estado.
//
// Ningún número se calcula aquí. Los totales, el parcial, cuántas líneas van
// sin precio y cuáles proveedores no tiene SICAR llegan de `particion.partir`,
// que es puro y tiene su tabla de casos.
// COPIAR LA CLAVE DE UN CLIC (ticket 22, casilla 4). Es lo que se pega en el
// buscador del portal del proveedor, y es un EAN de trece dígitos: teclearlo a
// mano cuarenta veces es cuarenta oportunidades de pedir otra cosa.
//
// El portapapeles moderno solo existe en un contexto seguro —https o
// 127.0.0.1—, y Continental llega por el túnel con https, así que es el camino
// normal. Si no está, el camino viejo (`execCommand('copy')`, obsoleto pero
// vivo en todos los navegadores). Y si NINGUNO sirve, se DICE en el botón
// (regla 4): un clic que no copia y no avisa hace pegar en el portal lo que
// había antes en el portapapeles — la clave del renglón anterior.
const copiarClave = async (clave, boton) => {
  let copiada = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(clave);
      copiada = true;
    }
  } catch (e) {
    copiada = false;
  }
  if (!copiada) {
    const area = document.createElement('textarea');
    area.value = clave;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    try { copiada = document.execCommand('copy'); } catch (e) { copiada = false; }
    area.remove();
  }
  boton.classList.remove('hecho', 'fallo');
  boton.classList.add(copiada ? 'hecho' : 'fallo');
  boton.textContent = copiada
    ? 'copiada ✓'
    : 'no se pudo copiar: ' + clave;
  // Vuelve a enseñar la clave después de un momento. Si falló, se queda más:
  // es lo que hay que copiar a mano.
  setTimeout(() => {
    boton.classList.remove('hecho', 'fallo');
    boton.textContent = clave;
  }, copiada ? 1200 : 6000);
};

// Qué bloque de captura está abierto, por pedido. Es ESTADO DE LA VISTA y vive
// en memoria —ni en el servidor ni en `localStorage`—: repintar recrea el
// `<details>`, y sin esto cada tachón cerraría la lista que uno está
// recorriendo. Lo que se guarda en el servidor es el AVANCE, que es un dato del
// pedido; si un bloque está abierto es de quien mira.
//
// Sin entrada, el bloque se abre solo si la captura va a medias: al recargar a
// la mitad de 40 renglones, lo primero que se ve es por dónde se iba.
const CAPTURAS_ABIERTAS = new Map();

// EL ARCHIVO DEL PEDIDO (ticket 23). La URL viene HECHA del servidor
// (`pedido.csv`): aquí no se arma nada, y `null` quiere decir que no hay qué
// exportar —un pedido vacío contestaría 409—. Un enlace y no un `fetch`: la
// descarga la hace el navegador con el `Content-Disposition` del servidor. En
// otra pestaña, para que un error se lea ahí sin tirar la pantalla de trabajo;
// y sin el atributo de descarga, que haría guardar el JSON de un error con
// nombre de CSV.
const enlaceCsv = (pedido) => {
  if (!pedido.csv) return null;
  const enlace = document.createElement('a');
  enlace.className = 'exportar';
  enlace.href = pedido.csv;
  enlace.target = '_blank';
  enlace.rel = 'noopener';
  enlace.textContent = 'Bajar este pedido en CSV (para Excel)';
  enlace.title = 'Se arma en este momento con lo que el pedido tiene ahora, y no '
    + 'se guarda en ninguna parte: cada vez que lo bajes sale al día.';
  return enlace;
};

// LA PANTALLA DE CAPTURA DE UN PEDIDO (ticket 22). Todo lo que dice viene
// HECHO del servidor: la frase del avance —con cuántos faltan—, la invitación a
// enviar y cada conteo. Aquí no se filtra ni se suma nada, por lo mismo que el
// conteo de descartados sale de Python desde el ticket 10: dos pestañas
// bastan para que un número que el navegador va llevando se separe de la
// verdad. Lo único que decide esta función es cómo se ve.
const pintarCaptura = (pedido, alTachar, conBoton) => {
  const captura = pedido.captura;
  const caja = document.createElement('details');
  caja.className = 'captura' + (captura.todo_capturado ? ' completa' : '');
  const recordado = CAPTURAS_ABIERTAS.get(pedido.pedido_id);
  caja.open = recordado === undefined
    ? (captura.capturados > 0 && !captura.todo_capturado)
    : recordado;
  caja.addEventListener('toggle', () => CAPTURAS_ABIERTAS.set(pedido.pedido_id, caja.open));

  const resumen = document.createElement('summary');
  const titulo = document.createElement('b');
  titulo.textContent = 'Capturar en el portal de ' + captura.nombre;
  const avance = document.createElement('span');
  avance.className = 'avance';
  // La frase trae "faltan N" dentro (casilla 2), y va en el resumen para que
  // se vea con el bloque cerrado.
  avance.textContent = captura.frase;
  resumen.append(titulo, ' · ', avance);
  caja.append(resumen);

  const lista = document.createElement('ol');
  captura.lineas.forEach(linea => {
    const li = document.createElement('li');
    li.className = linea.esta_capturado ? 'hecho' : '';

    // LA CASILLA (casilla 1). Se manda lo que quedó marcado y no un "alterna".
    const casilla = document.createElement('input');
    casilla.type = 'checkbox';
    casilla.id = 'captura-' + linea.renglon_id;
    casilla.checked = linea.esta_capturado;
    casilla.dataset.capturaRenglon = linea.renglon_id;
    // Quién la tachó y cuándo, a la vista con el puntero encima. Es una firma
    // y nunca un permiso (regla 3).
    casilla.title = linea.esta_capturado && linea.capturado_por
      ? 'Tachado por ' + linea.capturado_por
        + (linea.capturado_en ? ', ' + instanteEnPalabras(linea.capturado_en) : '')
      : 'Tacha el renglón en cuanto lo captures en el portal';
    casilla.onchange = () => alTachar(linea.renglon_id, pedido.pedido_id, casilla.checked, casilla);

    // LA CLAVE, UN CLIC Y COPIADA (casilla 4). Sin EAN no hay qué copiar: se
    // dice con palabras, y la frase del avance lo cuenta.
    let clave;
    if (linea.tiene_clave) {
      clave = document.createElement('button');
      clave.type = 'button';
      clave.className = 'clave';
      clave.textContent = linea.clave;
      clave.title = 'Copiar la clave para pegarla en el buscador de ' + captura.nombre;
      clave.onclick = () => copiarClave(linea.clave, clave);
    } else {
      clave = document.createElement('span');
      clave.className = 'clave sin';
      clave.textContent = 'sin código';
      clave.title = 'Este producto no tiene código de barras en el catálogo: búscalo por nombre.';
    }

    // La descripción es la etiqueta de la casilla: tocar el nombre también
    // tacha, que es un blanco mucho más grande que el cuadrito.
    const que = document.createElement('label');
    que.htmlFor = casilla.id;
    que.textContent = linea.descripcion;

    const cuantas = document.createElement('span');
    cuantas.className = 'cuantas';
    cuantas.textContent = plural(linea.cantidad, 'pieza', 'piezas');

    // EL PRECIO DE ESTE PROVEEDOR, o por qué no lo hay. Nunca "$0.00".
    const costo = document.createElement('span');
    costo.className = 'costo' + (linea.tiene_precio ? '' : ' nose');
    costo.textContent = linea.tiene_precio ? '$' + linea.precio : (linea.motivo || 'sin dato');
    costo.title = linea.tiene_precio
      ? 'Por pieza, sin IVA, como lo dio ' + captura.nombre + '. El que manda es el del portal.'
      : 'El precio lo vas a ver en el portal mientras lo capturas.';

    li.append(casilla, clave, que, cuantas, costo);
    lista.append(li);
  });
  caja.append(lista);

  const aviso = document.createElement('p');
  aviso.className = 'nota-captura';
  aviso.setAttribute('role', 'status');
  caja.append(aviso);

  // LLEVA A ENVIAR, SIN OBLIGAR (casilla 5). La frase viene hecha: con todo
  // tachado dice que el siguiente paso es enviar; a medias, que tachar no es
  // requisito. `null` cuando el botón está apagado por otra razón —el motivo
  // del ticket 21 ya lo dice— y entonces no se escribe nada. Y tampoco cuando
  // este pedido no tiene su botón al lado (`conBoton`): la frase la decide
  // Python, pero si hay adónde llevar lo sabe la pantalla.
  if (captura.invitacion && conBoton) {
    const invitacion = document.createElement('p');
    invitacion.className = 'invitacion' + (captura.todo_capturado ? ' lista' : '');
    invitacion.textContent = captura.invitacion + '.';
    caja.append(invitacion);
  }
  return caja;
};

const pintarParticion = (particion, pedidos, editable, alPartir, alEnviar, alTachar) => {
  const caja = document.getElementById('particion');
  if (!particion) { caja.hidden = true; caja.replaceChildren(); return; }

  caja.replaceChildren();

  // LOS QUE YA NO ESTÁN EN LA PARTICIÓN, Y POR QUÉ HAY QUE PINTARLOS IGUAL
  // (ticket 21). Al enviar un pedido, sus renglones pasan a `en tránsito` y
  // dejan de contar como "por repartir": el pedido enviado desaparece de
  // `particion.pedidos`, que es el cálculo de lo que queda por hacer. Si esta
  // función solo recorriera esa lista, **el pedido recién enviado se borraría
  // de la pantalla** — justo el que el encargado acaba de crear y el único del
  // que necesita ver la firma.
  //
  // Así que se pinta la UNIÓN: primero lo que se partiría ahora, y después los
  // pedidos guardados que ya no aparecen ahí.
  const guardados = new Map((pedidos || []).map(p => [p.proveedor, p]));
  const enLaParticion = new Set(particion.pedidos.map(p => p.proveedor));
  const fueraDeLaParticion = (pedidos || []).filter(p => !enLaParticion.has(p.proveedor));
  const enviados = (pedidos || []).filter(p => p.fue_enviado).length;
  const cancelados = (pedidos || []).filter(p => p.fue_cancelado).length;

  const titular = document.createElement('b');
  titular.textContent = (particion.hay
    ? 'Esta lista se parte en ' + plural(particion.pedidos.length, 'pedido', 'pedidos')
      + ', uno por proveedor'
    // SIN NADA QUE PARTIR SON DOS COSAS DISTINTAS, y decirlas igual sería el
    // peor de los mensajes: "todavía no hay en qué partir" sobre una lista que
    // ya se pidió entera manda a elegir proveedores que ya se eligieron.
    // Y con algo SIN PROVEEDOR no se pidió entera (hilo abierto 18, cerrado
    // en el ticket 27): se pidió en parte, y falta elegir.
    : (cancelados && particion.sin_nada_por_repartir && !particion.cuantos_sin_proveedor
       ? 'Esta lista ya no tiene nada por repartir'
       : (enviados
          ? (particion.cuantos_sin_proveedor
             ? 'Esta lista se pidió en parte'
             : 'Esta lista ya se pidió entera')
          : 'Todavía no hay en qué partir esta lista')))
    + (enviados
       ? ' · ' + plural(enviados, 'pedido ya enviado', 'pedidos ya enviados')
       : '')
    + (cancelados
       ? ' · ' + plural(cancelados, 'pedido cancelado', 'pedidos cancelados')
       : '');
  caja.append(titular);

  const detalle = document.createElement('span');
  detalle.className = 'detalle';
  detalle.textContent = particion.hay
    ? plural(particion.renglones_repartidos, 'renglón repartido', 'renglones repartidos')
      + '. Cada pedido se puede volver a armar mientras siga en borrador: '
      + 'cambia el proveedor de un renglón y vuelve a partir.'
    // Con algo cancelado, la frase es de Python (ticket 25): la vieja decía
    // "todo lo que había se capturó en los portales", y no es verdad. Y desde
    // el 26 también con algo recibido: la vieja decía "están en tránsito" sobre
    // renglones que ya llegaron (lo cazó el recorrido del navegador).
    // La de Python se usa SIEMPRE que llega: dice cuántos van en camino,
    // cuántos se cancelaron y cuántos llegaron, y la de abajo queda de reserva.
    : (particion.sin_nada_por_repartir
       ? particion.sin_nada_por_repartir
       : (enviados
          ? 'No queda nada por repartir: todo lo que había se capturó en los '
            + 'portales y sus renglones están en tránsito. Ya se puede cerrar.'
          : 'Elige a quién se le pide cada renglón, o consulta los precios para '
            + 'que el sistema pueda sugerirlo.'));
  caja.append(detalle);

  // Un pedido por proveedor, con su total. El estado sale del pedido GUARDADO
  // cuando lo hay: "borrador" es un hecho de la tabla, no de este cálculo.
  particion.pedidos.forEach(p => {
    const fila = document.createElement('div');
    fila.className = 'pedido';

    const quien = document.createElement('span');
    quien.className = 'quien';
    quien.textContent = p.nombre;

    const que = document.createElement('span');
    que.textContent = plural(p.renglones, 'renglón', 'renglones')
      + ' · ' + plural(p.piezas, 'pieza', 'piezas');

    // EL TOTAL, O POR QUÉ NO SE SABE. `null` no se pinta como una cifra y
    // jamás como "$0.00": un cero ahí se leería "este pedido no cuesta nada",
    // que es lo contrario de lo que pasa. El parcial sí se enseña, con el
    // conteo de lo que le falta al lado — el dato que hay no se esconde.
    const cuanto = document.createElement('span');
    cuanto.className = 'cuanto' + (p.hay_total ? '' : ' nose');
    cuanto.textContent = p.hay_total ? '$' + p.total_sin_iva : 'total sin saber';
    fila.append(quien, que, cuanto);

    if (!p.hay_total && p.renglones) {
      const marca = document.createElement('span');
      marca.className = 'marca';
      marca.textContent = plural(p.sin_precio, 'renglón va sin precio', 'renglones van sin precio')
        + ' de ' + p.nombre + ', así que el total no se puede sumar. Lo que sí '
        + 'se sabe suma $' + p.parcial_sin_iva + '. Se pide igual.';
      fila.append(marca);
    }

    // SICAR NO LO CONOCE. Se dice y no se esconde: el pedido se arma igual,
    // con `proveedor_id` en NULL. Hoy es el caso de QuePharma, a quien la
    // farmacia nunca le ha comprado.
    if (!p.tiene_puente) {
      const marca = document.createElement('span');
      marca.className = 'marca tenue';
      marca.textContent = p.nombre + ' ' + p.estado_del_puente
        + ': se le puede pedir igual, pero la compra no se va a poder cruzar '
        + 'sola con SICAR cuando llegue.';
      fila.append(marca);
    }

    const guardado = guardados.get(p.proveedor);
    if (guardado) {
      const marca = document.createElement('span');
      marca.className = 'marca tenue';
      // Sin punto al final: `instanteEnPalabras` ya termina en "a.m." o "p.m.",
      // y el punto extra salía como "02:07 a.m..". Lo cazó el recorrido del
      // navegador del 2026-09-21, no el suite.
      // `estado_a_la_vista` (ticket 27): recibido y recibido parcial se
      // CALCULAN de sus renglones; `estado` es lo guardado.
      marca.textContent = 'Pedido ' + guardado.pedido_id + ', '
        + (guardado.estado_a_la_vista || guardado.estado)
        + ', armado ' + instanteEnPalabras(guardado.armado_en);
      fila.append(marca);
      if (guardado.frase_de_la_recepcion) {
        const llegada = document.createElement('span');
        llegada.className = 'envio hecho';
        llegada.textContent = guardado.frase_de_la_recepcion;
        fila.append(llegada);
      }

      // QUÉ SIGNIFICA ENVIAR, y ya lo dice el servidor (ticket 21). La frase
      // viene HECHA de `particion.frase_del_envio`: aquí no se elige entre dos
      // literales ni se compone nada. Es la lección del ticket 15 aplicada al
      // sitio donde más caro sale — es la frase que impide que alguien crea
      // que Continental le mandó el pedido a NADRO.
      const envio = document.createElement('span');
      envio.className = 'envio' + (guardado.fue_enviado ? ' hecho' : '');
      envio.textContent = guardado.frase_del_envio
        + (guardado.fue_enviado && guardado.enviado_en
           ? ' Fue ' + instanteEnPalabras(guardado.enviado_en)
           : '');
      fila.append(envio);

      // LA PANTALLA DE CAPTURA (ticket 22), entre la frase del envío y el
      // botón: se captura, y lo que sigue es enviar.
      // Solo un BORRADOR se captura: `!fue_enviado` era lo mismo hasta el
      // ticket 25, y un cancelado le habría pintado casillas a un pedido que
      // ya no existe en ningún portal.
      if (guardado.es_borrador && guardado.captura && guardado.captura.cuantos) {
        fila.append(pintarCaptura(guardado, alTachar, true));
      }

      // EL CSV (ticket 23), en borrador y en enviado: el primero sirve para
      // capturar o revisar, y el segundo es el respaldo de lo que se pidió.
      const archivo = enlaceCsv(guardado);
      if (archivo) fila.append(archivo);

      // EL BOTÓN, CON EL TOTAL DENTRO. La primera casilla del ticket pide que
      // el total en pesos se vea ANTES de enviar, y el sitio donde de verdad
      // se ve es la etiqueta del botón que se va a apretar. Cuando no se puede
      // saber, dice eso — nunca "$0.00".
      if (guardado.es_borrador) {
        const acciones = document.createElement('div');
        acciones.className = 'acciones';
        const boton = botonDeAccion(
          'Enviar a ' + p.nombre + ' — '
            + (guardado.hay_total ? '$' + guardado.total_sin_iva : 'total sin saber'),
          (b) => alEnviar(guardado.pedido_id, p.nombre, b));
        // `se_puede_enviar` lo decide `particion.motivo_para_no_enviar`, que es
        // la MISMA decisión que el `WHERE` del UPDATE. Esto no es la garantía:
        // es poder decirlo antes, en vez de dejar que alguien lo apriete y
        // reciba un 409.
        boton.disabled = !guardado.se_puede_enviar;
        boton.title = guardado.motivo_para_no_enviar || guardado.frase_del_envio;
        // Adonde lleva tachar el último (ticket 22): el foco viene aquí, y con
        // todo tachado se resalta. NUNCA se apaga por la captura — la línea de
        // arriba es la única que decide eso.
        boton.dataset.enviar = guardado.pedido_id;
        if (guardado.captura && guardado.captura.todo_capturado) boton.classList.add('listo');
        acciones.append(boton);
        if (guardado.motivo_para_no_enviar) {
          const porque = document.createElement('span');
          porque.className = 'marca';
          porque.textContent = guardado.motivo_para_no_enviar + '.';
          acciones.append(porque);
        }
        fila.append(acciones);
      }
    }

    caja.append(fila);
  });

  // LOS PEDIDOS QUE YA NO ESTÁN EN LA PARTICIÓN. Son los enviados -sus
  // renglones ya no se reparten- y los que se quedaron vacíos. Se pintan desde
  // el pedido GUARDADO, que trae todo lo suyo: su nombre, su total, cuántos
  // renglones tiene dentro y su frase de envío. No hay vista previa que
  // enseñar porque no hay nada que volver a partir, y eso es lo correcto: un
  // pedido enviado ya no se edita.
  fueraDeLaParticion.forEach(g => {
    const fila = document.createElement('div');
    fila.className = 'pedido';

    const quien = document.createElement('span');
    quien.className = 'quien';
    quien.textContent = g.nombre;

    const que = document.createElement('span');
    que.textContent = plural(g.renglones, 'renglón', 'renglones');

    const cuanto = document.createElement('span');
    cuanto.className = 'cuanto' + (g.hay_total ? '' : ' nose');
    cuanto.textContent = g.hay_total ? '$' + g.total_sin_iva : 'total sin saber';
    fila.append(quien, que, cuanto);

    const marca = document.createElement('span');
    marca.className = 'marca tenue';
    marca.textContent = 'Pedido ' + g.pedido_id + ', ' + (g.estado_a_la_vista || g.estado)
      + ', armado ' + instanteEnPalabras(g.armado_en);
    fila.append(marca);
    // LO QUE LLEGÓ (ticket 27): la frase del pedido recibido, de Python.
    if (g.frase_de_la_recepcion) {
      const llegada = document.createElement('span');
      llegada.className = 'envio hecho';
      llegada.textContent = g.frase_de_la_recepcion;
      fila.append(llegada);
    }

    const envio = document.createElement('span');
    envio.className = 'envio' + (g.fue_enviado ? ' hecho' : '');
    envio.textContent = g.frase_del_envio
      + (g.fue_enviado && g.enviado_en
         ? ' Fue ' + instanteEnPalabras(g.enviado_en)
         : '')
      + (g.fue_cancelado && g.cancelado_en
         ? ' Se canceló ' + instanteEnPalabras(g.cancelado_en)
         : '');
    fila.append(envio);

    // CANCELAR (ticket 25): solo un pedido enviado, y con lo que se declara
    // escrito junto al botón. La frase y la decisión son de Python; la
    // garantía es el `WHERE` de `_CANCELAR_EL_PEDIDO`.
    if (g.se_puede_cancelar && g.frase_para_cancelar) {
      const acciones = document.createElement('div');
      acciones.className = 'acciones';
      const boton = botonDeAccion('Cancelar: no está en el portal de ' + g.nombre,
        (b) => cancelarPedido(g.pedido_id, b));
      const porque = document.createElement('span');
      porque.className = 'marca tenue';
      porque.textContent = g.frase_para_cancelar;
      acciones.append(boton, porque);
      fila.append(acciones);
    }

    // UN BORRADOR TAMBIÉN PUEDE CAER AQUÍ CON RENGLONES DENTRO, y ésa es la
    // trampa del ticket 22: la vista previa se recalcula con los precios de
    // este instante, y si llegó un LEVIC más barato ya no pone a NADRO... pero
    // el pedido GUARDADO de NADRO todavía los tiene. Se capturan igual: lo que
    // se captura es lo que al enviar pasa a `en tránsito`, y eso es
    // `pedido_id`. Su botón de enviar NO se pinta aquí —así quedó desde el
    // ticket 21—, y por eso la invitación a enviar tampoco: una frase que dice
    // "el siguiente paso es enviar" sin botón al lado manda a buscar uno que no
    // está.
    if (g.es_borrador && g.captura && g.captura.cuantos) {
      fila.append(pintarCaptura(g, alTachar, false));
    }

    // EL CSV también aquí, y sobre todo aquí: los enviados caen en este
    // recorrido, y son justo el pedido que más interesa respaldar. Pintarlo
    // solo arriba repetiría el error del ticket 21.
    const archivo = enlaceCsv(g);
    if (archivo) fila.append(archivo);

    // Un pedido que se quedó SIN renglones también cae aquí, y sigue sin
    // poderse enviar: el motivo viene hecho de `particion.motivo_para_no_enviar`
    // y se escribe en vez de esconder la fila. El rol no tiene DELETE, así que
    // ese pedido existe; esconderlo sería la falla silenciosa.
    if (g.es_borrador && g.motivo_para_no_enviar) {
      const porque = document.createElement('span');
      porque.className = 'marca';
      porque.textContent = g.motivo_para_no_enviar + '.';
      fila.append(porque);
    }

    caja.append(fila);
  });

  // LOS QUE NO SE REPARTEN A NADIE. Se cuentan y se dicen: un renglón que se
  // cayera de la partición en silencio es mercancía que va a faltar sin que
  // nadie se entere, que es lo mismo que CONTEXT.md prohíbe para los productos
  // sin anaquel.
  if (particion.cuantos_sin_proveedor) {
    const sin = document.createElement('span');
    sin.className = 'detalle';
    sin.textContent = plural(particion.cuantos_sin_proveedor,
      'renglón se queda fuera', 'renglones se quedan fuera')
      + ': todavía no hay a quién pedírselos. No se pierden — siguen en la '
      + 'lista y entran en cuanto alguien elija proveedor.';
    caja.append(sin);
  }

  if (particion.hay) {
    const fila = document.createElement('div');
    fila.className = 'fila';
    const boton = botonDeAccion(
      pedidos && pedidos.length ? 'Volver a partir' : 'Partir en pedidos',
      (b) => alPartir(b));
    boton.disabled = !editable;
    boton.title = 'Arma un pedido por proveedor con los renglones de arriba. '
      + 'Se puede volver a hacer mientras los pedidos sigan en borrador.';
    fila.append(boton);
    caja.append(fila);
  }

  caja.hidden = false;
};

// Los descartados, aparte. El bloque se esconde entero cuando no hay ninguno:
// un "0 descartados" permanente es ruido en una pantalla que ya tiene dos
// avisos y un interruptor.
//
// `cuantos` viene del SERVIDOR y no de `renglones.length`, aunque hoy valgan
// lo mismo: es el número que el ADR 0002 va a mirar después de un mes, y un
// conteo que el navegador lleve a mano se separa de la verdad en cuanto hay
// dos pestañas abiertas en el mostrador.
const pintarDescartados = (renglones, cuantos, alDevolver, editable) => {
  const caja = document.getElementById('descartados');
  document.getElementById('descartados-resumen').textContent =
    plural(cuantos, 'renglón descartado', 'renglones descartados') +
    ' de esta lista. Queda guardado quién y cuándo.';
  document.getElementById('descartados-lista').replaceChildren(
    ...renglones.map(r => renglonDescartado(r, alDevolver, editable)));
  caja.hidden = !cuantos;
};

// Descartar, devolver y corregir la cantidad son la misma petición con otro
// final de ruta. El control —el botón, o el campo de la cantidad— se desarma
// mientras viaja: repetir la operación no rompe nada —el servidor contesta 409
// y no mueve la firma— pero un control vivo invita a un segundo clic que no
// hace falta.
//
// `cuerpo` es lo que solo el ajuste manda (la cantidad); sin él va un POST
// pelado, que es lo que descartar y devolver necesitan: no llevan parámetros.
//
// `alFallar` deshace lo que el control mostraba cuando la petición no llegó.
// Un botón vuelve a habilitarse y ya; un campo se quedaría enseñando el número
// que el encargado tecleó como si se hubiera guardado, que es mentir en la
// única cifra que se copia al pedido.
//
// **No se vuelve a pedir la lista entera.** El servidor devuelve el renglón
// movido y los conteos; releer todo sería una segunda lectura en otro momento,
// y la lista podría dejar de coincidir consigo misma mientras alguien la
// trabaja. Es la misma razón por la que las dos vistas salen de una sola
// lectura.
const moverRenglon = async (id, ruta, control, alTerminar, cuerpo, alFallar) => {
  control.disabled = true;
  nota('pedido-accion', '');

  const peticion = { method: 'POST' };
  if (cuerpo) {
    peticion.headers = { 'Content-Type': 'application/json' };
    peticion.body = JSON.stringify(cuerpo);
  }

  // Hasta el ticket 29 la lectura del JSON iba fuera del `try`: con el HTML de un 502
  // el control se quedaba apagado y la pantalla no decía nada.
  const datos = await respuestaDe(fetch('/api/renglon/' + id + ruta, peticion), 'al_guardar');
  if (!datos.ok) {
    // El motivo viene del servidor y es genérico a propósito (regla 5): el
    // detalle está en la bitácora.
    control.disabled = false;
    if (alFallar) alFallar();
    notaDeFalla('pedido-accion', datos);
    return;
  }
  alTerminar(datos);
};

// ------------------------------------------------------------- el esqueleto

async function cargar() {
  const salud = await respuestaDe(fetch('/api/salud'));
  if (salud.ok) {
    // A quién avisarle, del YAML: lo usan las frases de `SIN_RESPUESTA`.
    if (salud.a_quien_avisar) A_QUIEN_AVISAR = salud.a_quien_avisar;
    pintar('estado', [
      fila('Continental ' + salud.version, true, 'negocio: ' + salud.negocio),
      fila('Entrando como', null, salud.quien),
    ]);
  } else {
    // Hasta el ticket 29 un 500 pintaba "Continental undefined" en verde.
    pintar('estado', [fila('Continental no contesta', false, salud.detalle)]);
  }

  const respuesta = await respuestaDe(fetch('/api/modulos'));
  if (Array.isArray(respuesta.modulos)) {
    pintar('modulos', respuesta.modulos.length
      ? respuesta.modulos.map(m => fila(m.nombre, m.ok, m.detalle || m.url))
      : [fila('Ninguno configurado', null)]);
  } else {
    pintar('modulos', [fila('No se pudo consultar', false, respuesta.detalle)]);
  }
}

// ¿DOYLE CONTESTA? (ticket 29, casilla 1). Aparte de la lista y al mismo
// tiempo: la lista no depende de Doyle —los precios guardados se leen de la
// base— y un Doyle colgado no la puede hacer esperar. Si no contesta, arriba
// de la tabla se dice que no hay precios nuevos, por qué y qué
// hacer; todo eso llega hecho del servidor.
async function revisarDoyle() {
  const doyle = await respuestaDe(fetch('/api/doyle'));
  // Sin respuesta del servidor no se sabe nada de Doyle, y la carga de la
  // lista ya lo va a decir en su propia nota: no se repite aquí.
  if (doyle.sin_respuesta) return;
  if (doyle.ok === false || doyle.contesta === false) {
    notaDeFalla('pedido-doyle', doyle);
    return;
  }
  document.getElementById('pedido-doyle').hidden = true;
}

cargarPedido();
revisarDoyle();
cargar();
