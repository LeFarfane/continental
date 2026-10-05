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

// ------------------------------------------------------------- la apariencia

// AUTO, CLARO U OSCURO (2026-10-05), el mismo interruptor de Marlowe. "Auto"
// es quitar el atributo y dejar que mande el sistema; los otros dos lo ponen
// en `<html>`, donde la hoja tiene sus listas de colores. Se aplica AQUÍ, en
// cuanto el archivo carga y antes de pedir nada, para que la pantalla no se
// pinte un instante en el tema del sistema y luego brinque al elegido.
//
// Se recuerda en el navegador y no en el servidor, por lo mismo que la vista de
// la lista (`CLAVE_DE_VISTA`): es una comodidad de quien mira, no un dato. Y
// cada acceso a `localStorage` va con su `try`, porque truena en una ventana
// privada: una apariencia que no se recuerda es una molestia, una pantalla en
// blanco es el día detenido.
const CLAVE_DEL_TEMA = 'continental.tema';
const TEMAS = ['auto', 'claro', 'oscuro'];

const temaRecordado = () => {
  try {
    const tema = localStorage.getItem(CLAVE_DEL_TEMA);
    return TEMAS.includes(tema) ? tema : 'auto';
  } catch (e) {
    return 'auto';
  }
};

const aplicarTema = (tema) => {
  if (tema === 'auto') delete document.documentElement.dataset.tema;
  else document.documentElement.dataset.tema = tema;
};

aplicarTema(temaRecordado());

// Los tres radios de la barra lateral, como el interruptor de las vistas: la
// marca de cuál está activa va con una clase y no con `:has(input:checked)`.
const iniciarApariencia = () => {
  const actual = temaRecordado();
  document.querySelectorAll('#apariencia input[name="tema"]').forEach(boton => {
    const etiqueta = boton.closest('label');
    boton.checked = boton.value === actual;
    etiqueta.classList.toggle('activa', boton.checked);
    boton.addEventListener('change', () => {
      aplicarTema(boton.value);
      try {
        localStorage.setItem(CLAVE_DEL_TEMA, boton.value);
      } catch (e) {
        // Se sigue sin recordar; dentro de esta visita el tema ya cambió.
      }
      document.querySelectorAll('#apariencia label').forEach(l => {
        l.classList.toggle('activa', l.contains(boton));
      });
    });
    boton.addEventListener('focus', () => etiqueta.classList.add('enfocada'));
    boton.addEventListener('blur', () => etiqueta.classList.remove('enfocada'));
  });
};

// ---------------------------------------------------------- el aviso pasajero

// LO QUE SALIÓ BIEN DE UN CLIC (decisión del dueño, 2026-10-05): en una cápsula
// abajo al centro que se va sola. **Solo lo que salió bien**: una falla se
// queda escrita en su nota (`notaDeFalla`) hasta el siguiente clic, porque un
// "no se pudo" que se borra solo a los tres segundos es una falla silenciosa
// con un paso de más (regla 4 de CLAUDE.md).
//
// Se queda más tiempo cuanto más larga es la frase —la del envío dice que
// Continental no le mandó nada al proveedor, y eso hay que alcanzar a leerlo—,
// y nunca menos de cuatro segundos. Limpia la nota del último clic: lo que
// estaba escrito ahí era de un clic anterior.
let RELOJ_DEL_AVISO = null;

const exito = (texto) => {
  nota('pedido-accion', '');
  const caja = document.getElementById('aviso-pasajero');
  if (!texto) { caja.hidden = true; return; }
  caja.textContent = texto;
  caja.hidden = false;
  clearTimeout(RELOJ_DEL_AVISO);
  RELOJ_DEL_AVISO = setTimeout(() => { caja.hidden = true; }, Math.max(4000, texto.length * 60));
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

// Lo mismo, con un enlace pegado al final. Existe por el visor de Doyle: el
// popup es la ruta buena, pero un bloqueador de ventanas lo puede impedir sin
// avisar, y entonces la pantalla volvería a no decir a dónde ir. El enlace es
// el seguro, y se pone SIEMPRE: cuesta un renglón y evita el único caso en
// que la persona se queda otra vez sin saber qué hacer.
//
// Con `createElement` y no con `innerHTML` por lo mismo que el resto del
// archivo: el texto viene del servidor y no hay razón para interpretarlo.
const notaConEnlace = (id, texto, url, etiqueta, clase) => {
  const p = document.getElementById(id);
  p.className = 'nota' + (clase ? ' ' + clase : '');
  p.textContent = texto + ' ';
  const a = document.createElement('a');
  a.href = url;
  a.target = 'visor-doyle';
  a.rel = 'noopener';
  a.textContent = etiqueta;
  p.append(a);
  p.hidden = false;
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

// `estilo` es la variante del botón del diseño (2026-09-30): sin ella es el
// gris chico de siempre; 'llena' es la acción principal de un lugar —una
// sola—, 'tenida' la que se ofrece al lado, y 'plana' la que casi no pesa.
const botonDeAccion = (texto, alHacerClic, estilo) => {
  const boton = document.createElement('button');
  boton.type = 'button';
  boton.className = 'accion' + (estilo ? ' ' + estilo : '');
  boton.textContent = texto;
  boton.onclick = () => alHacerClic(boton);
  return boton;
};

// Una insignia: una palabra en una cápsula teñida. El tono acompaña a la
// palabra, nunca la sustituye.
const insignia = (texto, tono, clase) => {
  const span = document.createElement('span');
  span.className = 'insignia' + (tono ? ' ' + tono : '') + (clase ? ' ' + clase : '');
  span.textContent = texto;
  return span;
};

// La hora sola, "7:40 a. m.", para donde el día ya se lee al lado (la barra
// del día, la firma de un envío de hoy). Es el mismo instante con zona que
// `instanteEnPalabras`, dicho más corto.
const horaEnPalabras = (iso) => new Date(iso).toLocaleTimeString('es-MX', {
  hour: 'numeric', minute: '2-digit'
});

/// LA CANTIDAD A PEDIR, en dos lugares desde la segunda versión del diseño
// (2026-10-05):
//
// - **En la fila, solo se lee**: la cifra grande y, si alguien la decidió, una
//   palabra debajo. Antes era un campo en cada fila; el diseño la deja quieta
//   para que la tabla se lea como tabla, y la corrección vive en el detalle.
// - **En el detalle, se corrige** (`controlDeCantidad`), con la lista abierta.
//
// Con la lista `cerrada` o `vencida` es la cifra a secas en los dos lugares. El
// servidor lo vuelve a comprobar en el `WHERE` de su UPDATE —ahí está la
// garantía—, pero dejar teclear algo que va a rebotar enseña a ignorar los
// avisos.
const celdaDeCantidad = (r) => {
  const td = document.createElement('td');
  td.className = 'cantidad';
  const numero = document.createElement('b');
  numero.textContent = r.cantidad_a_pedir;
  td.append(numero);

  // QUE ALGUIEN LA DECIDIÓ, en la fila: "ajustada" si quedó distinta de la que
  // propuso el sistema, "confirmada" si alguien dejó la misma —confirmar
  // también es decidir (ticket 11)—. Las dos cifras, quién y cuándo se dicen
  // enteras en el detalle del renglón (`firmasDelRenglon`).
  if (r.fue_ajustada) {
    const quien = document.createElement('span');
    quien.className = 'ajustada';
    quien.textContent = r.difiere_de_la_propuesta ? 'ajustada' : 'confirmada';
    quien.title = (r.difiere_de_la_propuesta ? 'El sistema propuso ' + r.cantidad_propuesta + '. ' : '')
      + 'Decidida por ' + (r.ajustada_por || 'sin-identificar');
    td.append(quien);
  }
  return td;
};

// LA CANTIDAD, EN EL DETALLE: un campo con − y + a los lados. El campo es lo
// que se manda —los botones solo le suman o le restan una pieza y lo mandan—,
// así que hay UN camino de escritura y no tres.
//
// `type="number"` con `min="1"`: el navegador ya sabe teclado numérico en el
// teléfono y flechas en la computadora. El `min` NO es la defensa contra el
// cero —se salta pegando texto, y el `step` no impide escribir a mano—: la
// defensa está en el CHECK de la tabla, en el validador compartido y en la
// ruta. Aquí es comodidad, y el aviso de `ajustar` es el que explica.
const controlDeCantidad = (r, alAjustar) => {
  const caja = document.createElement('div');
  caja.className = 'control-cantidad';
  const campo = document.createElement('input');
  campo.type = 'number';
  campo.className = 'cantidad-campo';
  campo.min = '1';
  campo.step = '1';
  campo.inputMode = 'numeric';
  // Lo que se pide HOY: la corrección si la hubo, y si no la propuesta. Quién
  // decide eso es el servidor (`cantidad_a_pedir`), no este archivo.
  campo.value = r.cantidad_a_pedir;
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

  // − y +: mientras la petición viaja el campo está apagado (`moverRenglon`),
  // y entonces los botones no hacen nada: dos clics seguidos no mandan dos
  // cifras que se crucen en el aire.
  const paso = (cuanto, rotulo, signo) => {
    const boton = botonDeAccion(signo, () => {
      if (campo.disabled) return;
      campo.value = Number(campo.value) + cuanto;
      alAjustar(r, campo);
    });
    boton.setAttribute('aria-label', rotulo + ' de ' + r.descripcion);
    return boton;
  };
  caja.append(paso(-1, 'Una pieza menos', '−'), campo, paso(1, 'Una pieza más', '+'));
  return caja;
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
// Desde el diseño del 2026-09-30 vive en DOS sitios, y cada uno dice lo suyo:
//
// - **La fila**: una columna por proveedor, con su precio y debajo cuántas
//   tiene (`celdasDePrecio`). El más barato salta solo, con fondo y negrita, y
//   las cuatro cifras quedan alineadas entre sí.
// - **El detalle del renglón**: cada proveedor con todo lo que hay que saber
//   de él —el más barato con todas sus letras, cuánto más caro es, el motivo
//   de su hueco—, el veredicto y cuándo se leyó (`preciosDelDetalle`).
//
// **Ninguna cifra se calcula aquí, y ninguna regla se decide aquí.** El precio
// llega como CADENA desde el servidor —el JSON de JavaScript solo tiene coma
// flotante, y meter dinero ahí justo en el borde donde acababa de salir es la
// falla que el `numeric(12,2)` del DDL existe para evitar—, y quién gana, la
// diferencia contra el ganador y el ahorro contra NADRO vienen resueltos de
// `comparacion.py`, que es una función pura con su tabla de casos. Aquí solo se
// pregunta por banderas: `es_ganador`, `es_ahorro`, `la_referencia_gana`.
//
// Tres aspectos distintos y no tres tonos del mismo gris: el ganador con fondo
// y negrita; el que no lo tiene, tachado y con "no tiene"; los huecos en
// cursiva, en gris y con su motivo. Un proveedor sin dato NUNCA se pinta como
// cero, como vacío ni como el más caro (regla 4 de CLAUDE.md).

// Las columnas de precio, en el orden y con los nombres que manda el servidor
// (`datos.puente`). Un servidor viejo que no los mande: las casillas de la
// comparación, en su orden.
const columnasDeProveedor = (casillas) => PROVEEDORES.length
  ? PROVEEDORES
  : casillas.map(c => ({ proveedor: c.proveedor, nombre: c.nombre }));

// El punto de color de cada proveedor, por su LUGAR en la lista del servidor
// (`--prov-1` a `--prov-4` en la hoja). Va siempre junto a su nombre: es para
// el ojo que ya aprendió los cuatro, no un dato.
const puntoDeProveedor = (clave) => {
  const punto = document.createElement('span');
  const i = PROVEEDORES.findIndex(p => p.proveedor === clave);
  punto.className = 'punto' + (i >= 0 ? ' prov-' + ((i % 4) + 1) : '');
  punto.setAttribute('aria-hidden', 'true');
  return punto;
};

// Lo que dice la existencia que reportó el portal, en corto. Se pinta tal como
// llegó —"+100" dice más que "100"—, y "pzs" solo se agrega a una cifra.
const existenciaEnCorto = (c) => {
  if (c.estado === 'sin existencia') return 'no tiene';
  if (c.estado === 'no dijo existencia') return '¿hay?';
  const dicho = c.existencia_como_llego || '';
  return /^\+?\d+$/.test(dicho) ? dicho + ' pzs' : dicho;
};

// POR QUÉ ESTE RENGLÓN NO TIENE NI UNA LECTURA (ticket 19, primera casilla).
//
// Hasta el ticket 18 aquí no había nada: "el lote se cortó por tiempo antes de
// llegar a éste" se veía IGUAL que "nadie lo ha consultado nunca". Eran dos
// cosas que se arreglan distinto.
//
// **La frase viene hecha del servidor** y esta pantalla no elige entre
// literales suyos: la decide `faltantes.por_que_no_hay_lectura`, que es una
// función pura con su tabla de casos y sus pruebas.
//
// `seguro` en falso no invalida el motivo: lo matiza. Esa noche el tope cortó
// Y ADEMÁS hubo renglones que no se pudieron consultar, así que de éste no se
// puede afirmar cuál de los dos le tocó (ADR 0007). Se escribe "probablemente"
// en vez de elegir uno a cara o cruz. `completo` agrega la explicación: en la
// fila no cabe, en el detalle sí.
const motivoSinLectura = (porque, completo) => {
  const caja = document.createElement('span');
  // ÁMBAR y no ROJO para «el lote se negó a correr»: es la sonda de sesiones
  // (ADR 0019) haciendo justo lo que se le pide -negarse antes de escribir
  // precios tuertos-, no una falla desconocida que manda al journal.
  caja.className = 'hueco-motivo'
    + (porque.motivo === 'al lote se le acabó el tiempo'
       || porque.motivo === 'el lote se negó a correr: falta abrir una sesión'
         ? ' tope' : '')
    + (porque.motivo === 'la corrida del lote se cortó'
       || porque.motivo === 'el lote lo intentó y no pudo' ? ' falla' : '');
  const titular = document.createElement('b');
  titular.textContent = porque.seguro ? porque.motivo : 'probablemente: ' + porque.motivo;
  if (!porque.seguro) titular.className = 'quiza';
  caja.append(titular);
  if (completo) caja.append(' — ' + porque.explicacion);
  else caja.title = porque.explicacion;
  return caja;
};

// LA FILA, VARIANTE «REJILLA»: una celda por proveedor. Si el renglón no tiene
// ni una lectura, una sola celda que ocupa las cuatro, con el motivo.
const celdasDeRejilla = (r) => {
  const comparacion = r.comparacion || null;
  const casillas = (comparacion && comparacion.por_proveedor) || [];
  const columnas = columnasDeProveedor(casillas);
  const porque = r.porque_no_hay_lectura;

  if (porque && !casillas.length) {
    const td = document.createElement('td');
    td.className = 'hueco-celda';
    td.colSpan = columnas.length || 4;
    td.dataset.etiqueta = 'Precio';
    td.append(motivoSinLectura(porque, false));
    return [td];
  }

  const porProveedor = new Map(casillas.map(c => [c.proveedor, c]));
  // A quién se le pide hoy: la elección que ya llegó resuelta del servidor
  // (`r.eleccion`). Su caja lleva el borde de acento.
  const elegido = r.eleccion && r.eleccion.hay ? r.eleccion.proveedor : null;
  return columnas.map(p => {
    const td = document.createElement('td');
    td.className = 'precio-celda';
    td.dataset.etiqueta = p.nombre;
    const caja = document.createElement('div');
    const c = porProveedor.get(p.proveedor);
    // Dos avisos distintos y por eso dos clases: "nadie confirmó que lo tenga"
    // y "fue el único que contestó". El verde entero es solo para el ganador
    // que no tiene ninguno de los dos.
    caja.className = 'precio'
      + (c && c.es_ganador ? ' gana' : '')
      + (c && c.es_ganador && !comparacion.ganador.con_existencia ? ' sinconfirmar' : '')
      + (c && c.es_ganador && comparacion.ganador.es_unico ? ' unico' : '')
      + (c && c.estado === 'sin existencia' ? ' notiene' : '')
      + (p.proveedor === elegido && !r.esta_en_transito ? ' elegido' : '');

    // La cifra es un `<b>`; el hueco es un `<span>` en cursiva. Son dos
    // elementos distintos a propósito: la diferencia tiene que verse aunque
    // alguien mire la pantalla de lejos o con reflejo.
    const cifraOhueco = document.createElement(c && c.precio ? 'b' : 'span');
    const hay = document.createElement('span');
    hay.className = 'hay';
    if (c && c.precio) {
      cifraOhueco.textContent = '$' + c.precio;
      // DEBAJO DE LA CIFRA, lo que el diseño pone ahí: el más barato con su
      // "✓", cuánto más caro es cada uno de los otros, o que no lo tiene. La
      // diferencia viene restada de Python (`diferencia_magnitud`). Lo que no
      // cabe —la certeza del ganador, la existencia de los demás— va en el
      // `title` y entero en el detalle.
      hay.textContent = c.es_ganador
        ? '✓ ' + existenciaEnCorto(c)
        : c.diferencia && !c.mas_barato_que_el_ganador && c.estado !== 'sin existencia'
          ? '+$' + c.diferencia_magnitud
          : existenciaEnCorto(c);
      if (c.estado === 'sin existencia') hay.className = 'hay notiene';
      if (c.estado === 'no dijo existencia') hay.className = 'hay nodijo';
    } else {
      cifraOhueco.className = 'sindato';
      cifraOhueco.textContent = !c || c.estado === 'sin consultar' ? 'sin consultar' : 'sin dato';
    }
    caja.append(cifraOhueco, hay);

    // Lo que no cabe en la casilla va en su `title` —el motivo del hueco, la
    // diferencia contra el ganador— y entero en el detalle del renglón, que es
    // donde se lee en una pantalla táctil.
    const dicho = [p.nombre];
    if (c && c.precio) dicho.push(existenciaEnCorto(c));
    if (c && c.es_ganador) dicho.push(comparacion.ganador.certeza);
    if (c && c.diferencia) {
      dicho.push(c.mas_barato_que_el_ganador
        ? c.diferencia_magnitud + ' más barato por pieza, pero no lo tiene'
        : '+$' + c.diferencia_magnitud + ' por pieza');
    }
    if (c && c.motivo) dicho.push(c.motivo_explicado || c.motivo);
    td.title = dicho.filter(Boolean).join(' · ');
    td.append(caja);
    return td;
  });
};

// LA FILA, VARIANTE «ESCALA»: UNA sola celda por renglón. A la izquierda el
// ganador —su precio y quién es—; a la derecha, si hay dos precios o más, una
// recta de más barato a más caro con un punto por proveedor que dio precio, y
// debajo el mínimo, cuántos contestaron y el máximo.
//
// **Ninguna cifra que se lee se calcula aquí.** El precio llega como cadena y
// se escribe tal cual (`'$' + c.precio`); el mínimo y el máximo del pie son las
// cadenas de las casillas que tienen el precio menor y el mayor. La ÚNICA
// conversión a número es `posicionEnLaEscala`, y su resultado es un porcentaje
// de ancho para colocar un punto: posición en pantalla, nunca una cifra que se
// enseñe ni una regla. Quién gana, el empate y la certeza vienen del servidor.
const posicionEnLaEscala = (casillas) => {
  const numerico = (c) => parseFloat(c.precio);
  let menor = casillas[0];
  let mayor = casillas[0];
  casillas.forEach(c => {
    if (numerico(c) < numerico(menor)) menor = c;
    if (numerico(c) > numerico(mayor)) mayor = c;
  });
  const ancho = numerico(mayor) - numerico(menor);
  // Todos al mismo precio: no hay escala que dibujar, y dividir entre cero
  // pondría los puntos fuera de la recta. Se centran.
  const donde = (c) => ancho > 0 ? ((numerico(c) - numerico(menor)) / ancho) * 100 : 50;
  return { menor, mayor, donde };
};

const celdaDeEscala = (r) => {
  const comparacion = r.comparacion || null;
  const casillas = (comparacion && comparacion.por_proveedor) || [];
  const porque = r.porque_no_hay_lectura;

  const td = document.createElement('td');
  td.dataset.etiqueta = 'Precio';

  // Sin una sola lectura: el motivo, igual que en la rejilla.
  if (porque && !casillas.length) {
    td.className = 'escala-celda hueco-celda';
    td.append(motivoSinLectura(porque, false));
    return td;
  }
  td.className = 'escala-celda';
  const caja = document.createElement('div');
  caja.className = 'escala';

  // ---- A la izquierda: el ganador.
  const g = comparacion ? comparacion.ganador : null;
  const hayGanador = !!(g && g.proveedores && g.proveedores.length && g.precio);
  const empate = hayGanador && g.proveedores.length > 1;
  const izquierda = document.createElement('div');
  izquierda.className = 'escala-ganador'
    + (hayGanador && !g.con_existencia ? ' sinconfirmar' : '')
    + (hayGanador && g.es_unico ? ' unico' : '');
  const cifraOhueco = document.createElement(hayGanador ? 'b' : 'span');
  const quien = document.createElement('span');
  quien.className = 'escala-quien';
  if (hayGanador) {
    cifraOhueco.textContent = '$' + g.precio;
    quien.textContent = empate
      ? 'empate ' + (g.nombres || []).join(' y ')
      : (g.nombres && g.nombres[0]) || '';
    // La certeza, tal como la dice el servidor: es lo que el verde, el ámbar y
    // el "?" solo insinúan.
    if (g.certeza) izquierda.title = g.certeza;
  } else {
    cifraOhueco.className = 'sindato';
    cifraOhueco.textContent = 'sin dato';
    // La frase la dice el servidor (`ganador.motivo`); lo único propio es el
    // caso sin comparación alguna, que es "nadie lo ha consultado".
    quien.textContent = (g && g.motivo) || 'sin consultar';
    if (g && g.motivo) izquierda.title = g.motivo;
  }
  izquierda.append(cifraOhueco, quien);

  // ---- A la derecha: la recta, solo con dos precios o más.
  const conPrecio = casillas.filter(c => c.precio);
  const total = (comparacion && comparacion.consultados) || PROVEEDORES.length;
  const dieron = comparacion ? comparacion.con_precio : 0;
  // El ámbar lo decide el servidor (`se_comparo`, la misma bandera de
  // `veredicto()` para `.cobertura.escasa`); aquí no hay umbral. Con cero
  // proveedores no hay conteo que enseñar.
  const cuantos = document.createElement('span');
  cuantos.className = 'escala-cuantos'
    + (comparacion && !comparacion.se_comparo ? ' poco' : '');
  cuantos.textContent = dieron + ' de ' + total + ' dieron precio';
  const cuantosCorto = document.createElement('span');
  cuantosCorto.className = cuantos.className;
  cuantosCorto.textContent = dieron + '/' + total + ' con precio';
  cuantosCorto.title = cuantos.textContent;

  const derecha = document.createElement('div');
  derecha.className = 'escala-recta';
  if (conPrecio.length >= 2) {
    derecha.setAttribute('role', 'img');
    derecha.setAttribute('aria-label', conPrecio.length + ' proveedores con precio');
    const { menor, mayor, donde } = posicionEnLaEscala(conPrecio);
    const linea = document.createElement('div');
    linea.className = 'escala-linea';
    conPrecio.forEach(c => {
      const punto = document.createElement('span');
      punto.className = 'escala-punto'
        + (c.es_ganador ? ' gana' : '')
        + (c.es_ganador && g && !g.con_existencia ? ' sinconfirmar' : '')
        + (c.es_ganador && g && g.es_unico ? ' unico' : '')
        + (c.estado === 'sin existencia' ? ' notiene' : '');
      punto.style.left = donde(c) + '%';
      punto.title = c.nombre + ' $' + c.precio
        + (c.estado === 'sin existencia' ? ' · no lo tiene' : '');
      punto.setAttribute('aria-label', punto.title);
      linea.append(punto);
    });
    const pie = document.createElement('div');
    pie.className = 'escala-pie';
    // El extremo de un proveedor que no lo tiene no se presenta como el
    // mínimo "bueno": tachado y en rojo, con su palabra en el `title`.
    const extremo = (c) => {
      const marca = document.createElement('span');
      marca.textContent = '$' + c.precio;
      if (c.estado === 'sin existencia') {
        marca.className = 'notiene';
        marca.title = c.nombre + ' · no lo tiene';
      }
      return marca;
    };
    pie.append(extremo(menor), total ? cuantosCorto : '', extremo(mayor));
    derecha.append(linea, pie);
  } else {
    derecha.classList.add('sola');
    if (total) derecha.append(cuantos);
  }
  caja.append(izquierda, derecha);

  // Los motivos de los huecos, en el `title` de la celda y enteros en el
  // detalle del renglón.
  const huecos = casillas
    .filter(c => !c.precio && c.motivo)
    .map(c => c.nombre + ': ' + (c.motivo_explicado || c.motivo));
  if (huecos.length) td.title = huecos.join(' · ');
  td.append(caja);
  return td;
};

// CÓMO SE COMPARAN LOS CUATRO EN LA FILA. Existen las dos variantes y conviven
// a propósito: el dueño probó la escala el 2026-09-30 y eligió la rejilla. La
// escala se queda, sin uso, para poder volver a probarla cambiando solo esta
// constante, sin reescribir nada.
//   'rejilla' cuatro columnas, una por proveedor, con su precio y su existencia.
//   'escala'  una columna: el ganador y una recta de más barato a más caro.
// El detalle del renglón no depende de esta elección: siempre trae los cuatro.
const COMPARACION_EN_LA_FILA = 'rejilla'; // o 'escala'
const EN_ESCALA = COMPARACION_EN_LA_FILA === 'escala';

const celdasDePrecio = (r) => EN_ESCALA ? [celdaDeEscala(r)] : celdasDeRejilla(r);

// EL DETALLE: cada proveedor en su línea, con lo que hay que saber de él. Lo
// que devuelve son tres piezas porque van en tres sitios del detalle: el
// cuerpo, cuándo se leyó (arriba a la derecha) y el botón de volver a
// consultar (abajo, con las demás acciones).
const preciosDelDetalle = (r, acciones) => {
  const cuerpo = document.createElement('div');
  cuerpo.className = 'precios-del-detalle';
  const precios = Array.isArray(r.precios) ? r.precios : [];
  const comparacion = r.comparacion || null;
  const consulta = r.consulta || null;
  // Las lecturas por clave, solo para colgar el `detalle` del motivo como
  // título. No es una regla: es el mismo dato que ya viajó, buscado por su
  // llave.
  const porClave = new Map(precios.map(p => [p.proveedor, p]));
  const casillas = (comparacion && comparacion.por_proveedor) || [];
  const porque = r.porque_no_hay_lectura;

  if (porque && !casillas.length) cuerpo.append(motivoSinLectura(porque, true));

  // A QUIÉN SE LE PIDE SE ELIGE AQUÍ desde la segunda versión del diseño
  // (2026-10-05): cada proveedor es un botón, y tocarlo es pedirle a ése. Con
  // la lista abierta y el renglón editable; si no, las mismas cajas se leen.
  // Se pueden elegir los cuatro, también el que no dio precio: hay razones
  // que el sistema no ve —mínimo de pedido, días de entrega, crédito— y el
  // renglón entra al pedido con la marca de precio desconocido (ticket 20).
  const eligiendo = !!(acciones.elegirProveedor && r.se_puede_editar);
  const elegido = r.eleccion && r.eleccion.hay ? r.eleccion.proveedor : null;

  if (casillas.length || eligiendo) {
    const lista = document.createElement('div');
    lista.className = 'precios-detalle';
    const porProveedor = new Map(casillas.map(c => [c.proveedor, c]));
    columnasDeProveedor(casillas).forEach(p => {
      const c = porProveedor.get(p.proveedor) || { nombre: p.nombre, estado: 'sin consultar' };
      const linea = document.createElement(eligiendo ? 'button' : 'div');
      linea.className = 'precio precio-detalle'
        + (c.es_ganador ? ' gana' : '')
        + (c.es_ganador && !comparacion.ganador.con_existencia ? ' sinconfirmar' : '')
        + (c.es_ganador && comparacion.ganador.es_unico ? ' unico' : '')
        + (p.proveedor === elegido ? ' elegido' : '');
      if (eligiendo) {
        linea.type = 'button';
        linea.setAttribute('aria-pressed', p.proveedor === elegido ? 'true' : 'false');
        linea.setAttribute('aria-label', 'Pedirle ' + r.descripcion + ' a ' + (c.nombre || p.nombre));
        linea.onclick = () => acciones.elegirProveedor(r, p.proveedor, linea);
      }

      // El círculo de la izquierda: lleno en el elegido. Es para el ojo; el
      // lector de pantalla tiene `aria-pressed`, y la fila "Se le pide a" y
      // las firmas lo dicen con el nombre.
      const radio = document.createElement('span');
      radio.className = 'radio';
      radio.setAttribute('aria-hidden', 'true');

      const quien = document.createElement('span');
      quien.className = 'quien';
      quien.append(puntoDeProveedor(p.proveedor), c.nombre || p.nombre);

      const cifraOhueco = document.createElement(c.precio ? 'b' : 'span');
      if (c.precio) {
        cifraOhueco.textContent = '$' + c.precio;
      } else {
        cifraOhueco.className = 'sindato';
        cifraOhueco.textContent = c.estado === 'sin consultar' ? 'sin consultar' : 'sin dato';
      }

      const nota = document.createElement('span');
      nota.className = 'nota-precio';

      // La marca del ganador va con PALABRA además de color: un verde más
      // oscuro no es una marca para quien no distingue verdes. LA FRASE VIENE
      // HECHA DEL SERVIDOR (`ganador.certeza`), y eso es el ticket 15: "el más
      // barato con existencia", "el único que contestó"… se deciden en
      // `comparacion.py`, con su tabla de casos.
      if (c.es_ganador) {
        const marca = document.createElement('span');
        marca.className = 'marca-gana'
          + (comparacion.ganador.con_existencia ? '' : ' sinconfirmar')
          + (comparacion.ganador.es_unico ? ' unico' : '');
        marca.textContent = '✔ ' + (comparacion.ganador.certeza || '');
        nota.append(marca);
      }

      // Cuánto más caro es que el ganador, ya restado en Python. Y puede ser
      // MÁS BARATO y no haber ganado: el ganador es el más barato de los que lo
      // tienen. El signo lo decide Python; aquí solo se elige la frase.
      if (c.diferencia) {
        const caro = document.createElement('span');
        caro.className = 'caro';
        caro.textContent = c.mas_barato_que_el_ganador
          ? c.diferencia_magnitud + ' más barato por pieza, pero no lo tiene'
          : '+$' + c.diferencia_magnitud + ' por pieza';
        nota.append(caro);
      }

      // LA EXISTENCIA, dicha: el más barato no sirve si no lo tiene.
      if (c.estado === 'con existencia' || c.estado === 'sin existencia'
          || c.estado === 'no dijo existencia') {
        const hay = document.createElement('span');
        hay.className = 'hay' + (c.estado === 'sin existencia' ? ' notiene'
          : c.estado === 'no dijo existencia' ? ' nodijo' : '');
        hay.textContent = c.estado === 'sin existencia'
          ? 'no lo tiene'
          : c.estado === 'no dijo existencia'
            ? 'no dijo cuántas tiene'
            : 'tiene ' + c.existencia_como_llego;
        if (c.estado === 'sin existencia') hay.setAttribute('aria-label', 'no lo tiene');
        nota.append(hay);
      }

      // El motivo DICHO PARA UNA PERSONA (ticket 15): el producto no está en
      // ese catálogo, el EAN dio varios resultados, el portal no contestó, la
      // sesión caducó. La cadena corta es la que se guarda y se cuenta; la
      // larga es la que se lee. Si el servidor no mandara la larga se escribe
      // la corta: dice menos, pero dice algo.
      if (c.motivo) {
        const motivo = document.createElement('span');
        motivo.className = 'precio-motivo';
        motivo.textContent = c.motivo_explicado || c.motivo;
        const lectura = porClave.get(c.proveedor);
        if (lectura && lectura.detalle) motivo.title = lectura.detalle;
        nota.append(motivo);
      }

      linea.append(radio, quien, cifraOhueco);
      if (nota.childNodes.length) linea.append(nota);
      lista.append(linea);
    });
    cuerpo.append(lista);
  }

  // EL VEREDICTO: contra cuántos se comparó, por qué no hay ganador si no lo
  // hay, y el ahorro contra NADRO.
  if (comparacion && comparacion.hay_lecturas) cuerpo.append(veredicto(comparacion));

  // CUÁNDO SE LEYÓ, a la vista. Sin esto, "$86.05 en NADRO" no dice si se leyó
  // hace una hora o hace tres semanas. Es el instante MÁS RECIENTE de las
  // lecturas que se comparan, calculado en Python.
  const leido = comparacion && comparacion.leido_en
    ? 'leído el ' + instanteEnPalabras(comparacion.leido_en)
      + (comparacion.instantes_distintos ? ' (hay lecturas de varios momentos)' : '')
    : '';

  if (consulta && consulta.en_curso) {
    const esperando = document.createElement('span');
    esperando.className = 'precio-cuando';
    // Se dice cuánto tarda. Una espera sin número se lee como "se colgó" a los
    // quince segundos, y ésta tarda nueve por proveedor en el mejor caso.
    esperando.textContent = 'Consultando a los cuatro proveedores… tarda un minuto.';
    cuerpo.append(esperando);
    return { cuerpo, leido, boton: null };
  }

  if (consulta && consulta.detalle && !precios.length) {
    // Doyle no contestó y no hay nada congelado: un hueco CON SU MOTIVO, nunca
    // una celda vacía. Vacío se lee "no tiene precio en ningún lado".
    const fallo = document.createElement('span');
    fallo.className = 'precio-motivo';
    fallo.textContent = consulta.detalle;
    cuerpo.append(fallo);
  }

  // Sin el botón cuando la lista ya no está abierta: los precios congelados
  // siguen viéndose —son la razón por la que se eligió un proveedor— pero
  // volver a consultar una lista cerrada sería molestar a cuatro portales para
  // cambiar un dato que ya no decide nada.
  let boton = null;
  if (acciones.editable) {
    boton = botonDeAccion(
      precios.length ? 'Volver a consultar' : 'Consultar precio',
      (b) => acciones.consultarPrecio(r, b));
    boton.title = precios.length
      ? 'Vuelve a preguntarle a Doyle. Lo de hoy se guarda al lado; nada se borra.'
      : 'Le pregunta a Doyle el precio en los cuatro proveedores. Tarda hasta un minuto.';
    boton.setAttribute('aria-label',
      'Consultar el precio de ' + r.descripcion + ' en los cuatro proveedores');
  }

  return { cuerpo, leido, boton };
};

const mayuscula = (texto) => texto.charAt(0).toUpperCase() + texto.slice(1);

// LAS MARCAS DE UN RENGLÓN: qué le pasa a ese producto. Una lista y no una
// cascada de `if` pintando en sitio: la misma marca se ve en dos lugares —como
// insignia en la fila y con su frase entera en el detalle— y escribirla dos
// veces sería la manera de que un día digan cosas distintas.
//
// **Las frases vienen hechas del servidor.** Lo que se escribe aquí es la
// etiqueta corta de la insignia, que repite una bandera que ya llegó resuelta
// —`esta_en_transito`, `esta_recibido`…—, y las pocas frases de reserva que ya
// estaban antes, para cuando el servidor no mandó la suya. `soloFila` marca lo
// que el detalle ya dice en otro bloque y no se repite ahí.
const marcasDe = (r) => {
  const marcas = [];
  const agrega = (clase, tono, etiqueta, frase, control, soloFila) =>
    marcas.push({ clase, tono, etiqueta, frase, control, soloFila });

  // AGOTADO: es el renglón más urgente de la lista y tiene que saltar a la
  // vista sin hacer aritmética. Lo que ya se pidió no es urgente aunque su
  // existencia sea cero.
  if (r.esta_agotado && !r.esta_en_transito) {
    agrega('marca agotada', 'rojo', 'Agotado', 'No queda ninguna pieza en existencia.');
  }

  if (!r.esta_en_el_catalogo) {
    agrega('marca hueco-catalogo', 'naranja', 'Fuera del catálogo',
      'No está en el catálogo: revísalo en SICAR.');
  }

  // La clasificación sale del RENGLÓN y no se vuelve a deducir aquí: la regla
  // —el anaquel le gana a la categoría— vive en un solo lugar probado, en
  // Python. Se marca solo lo que NO es medicamento: etiquetar nueve de cada
  // diez renglones de una farmacia es ruido que se deja de leer.
  if (r.clasificacion && r.clasificacion !== 'medicamento') {
    const sinAnaquel = r.clasificacion === 'sin clasificar';
    agrega('marca' + (sinAnaquel ? ' sin-clasificar' : ' tenue abarrote'), 'gris',
      mayuscula(r.clasificacion),
      sinAnaquel
        ? 'Sin clasificar: no tiene anaquel conocido. Se muestra igual para que no falte.'
        : 'Abarrote: no se le compra a un proveedor.');
  }

  // YA SE PIDIÓ (ticket 21). El renglón NO desaparece: sigue en la tabla, con
  // sus precios y su proveedor a la vista. Desde el ticket 24 la frase llega
  // HECHA de Python —"Pedido hoy a NADRO, sin recibir."—; lo de abajo es solo
  // lo que se dice cuando el servidor no la mandó.
  if (r.esta_en_transito) {
    agrega('marca tenue en-transito', 'gris', 'En tránsito', r.frase_del_transito
      || ('Ya se pidió: en tránsito. No se vuelve a proponer '
          + 'mientras esté así.'));
  }

  // ATRASADO (ticket 25). La frase es de Python y el botón hace lo mismo que
  // el de "En camino".
  if (r.frase_del_atraso) {
    agrega('marca atrasado', 'naranja', 'Atrasado', r.frase_del_atraso,
      r.se_puede_devolver
        ? botonDeAccion('Devolver a la lista',
            (boton) => devolverAtrasado(r.renglon_id, boton), 'tenida')
        : null);
  }

  // PROBABLEMENTE YA LLEGÓ (ticket 26): hay una compra que encaja, en "En
  // camino". Por eso el botón de devolver no se ofrece.
  if (r.frase_de_la_recepcion) {
    agrega('marca probable', 'acento', 'Probablemente llegó', r.frase_de_la_recepcion);
  }

  // YA LLEGÓ (ticket 26): con la firma de quien lo confirmó, hecha en Python.
  // Desde el 27 dice cuántas llegaron, y se puede CORREGIR la cifra —la
  // segunda factura, un error de captura—. La etiqueta viene de Python.
  if (r.esta_recibido && r.frase_de_lo_recibido) {
    agrega('marca tenue llego', 'verde', 'Recibido', r.frase_de_lo_recibido,
      r.se_puede_corregir && r.etiqueta_a_mano
        ? controlAMano(r.renglon_id, r.etiqueta_a_mano, r.descripcion, r.piezas_recibidas)
        : null);
  }

  // SE DEJÓ DE ESPERAR (ticket 25): NO vuelve a esta lista —ya se armó sin
  // él—: vuelve en la siguiente, y la frase de Python lo dice.
  if (r.esta_cancelado) {
    agrega('marca tenue vuelve', 'gris', 'Se dejó de esperar', r.frase_de_lo_cancelado
      || 'Se dejó de esperar: vuelve a proponerse en la siguiente lista.');
  }

  // LO QUE SE VENDIÓ MIENTRAS VENÍA EN CAMINO (ticket 24): sin decirlo, "pide
  // 4" en una lista de un día con una venta no se podría verificar.
  if (r.frase_de_la_ventana) {
    agrega('marca tenue ventana', 'gris', 'Cuenta desde otro día', r.frase_de_la_ventana);
  }

  // LO QUE FALTÓ Y ESTE RENGLÓN TRAE (ticket 27).
  if (r.frase_de_lo_que_falto) {
    agrega('marca tenue falto', 'morado', 'Faltante', r.frase_de_lo_que_falto);
  }

  // EL BORDE QUE LA MEMORIA NO ALCANZA (ticket 24): ya viene en camino desde
  // una lista enviada DESPUÉS de armar ésta. Y su par del 27: lo que faltó ya
  // llegó en otra factura. Lo guardado no se recalcula; se avisa.
  if (r.ya_viene_en_camino) {
    agrega('marca hay-que-mirar', 'naranja', 'Ya viene en camino', r.ya_viene_en_camino);
  }
  if (r.ya_no_falta) {
    agrega('marca hay-que-mirar', 'naranja', 'Ya no falta', r.ya_no_falta);
  }

  // Sin una sola lectura, y consultándose ahora: en la fila como insignia; en
  // el detalle lo dice el bloque de precios.
  const casillas = (r.comparacion && r.comparacion.por_proveedor) || [];
  if (r.porque_no_hay_lectura && !casillas.length) {
    agrega('marca sin-precio', 'naranja', 'Sin precio', r.porque_no_hay_lectura.explicacion, null, true);
  }
  if (r.consulta && r.consulta.en_curso) {
    agrega('marca consultando', 'acento', 'Consultando…', null, null, true);
  }

  return marcas;
};

const insigniaDeMarca = (m) => {
  const s = insignia(m.etiqueta, m.tono, m.clase);
  if (m.frase) s.title = m.frase;
  return s;
};

const renglon = (r, acciones) => {
  const tr = document.createElement('tr');
  tr.dataset.renglon = r.renglon_id;
  // Lo que el filtro de la lista compara: el nombre y la clave.
  tr.dataset.busqueda = r.descripcion + ' ' + (r.clave || '');
  // YA SE PIDIÓ (ticket 24, casilla 4): atenuado y no escondido. Y lo que se
  // dejó de esperar (ticket 25), igual: ya no se atiende en esta lista.
  // Y lo que ya llegó (ticket 26), igual: está en la lista, ya no se atiende.
  if (r.esta_en_transito || r.esta_cancelado || r.esta_recibido) tr.classList.add('transito');
  // AGOTADO Y ATRASADO (ticket 28): dos clases del renglón entero para que la
  // hoja de estilos les ponga su barra al borde —continua y doble—. No deciden
  // nada: repiten banderas que ya llegaron hechas del servidor.
  if (r.esta_agotado) tr.classList.add('agotado');
  if (r.frase_del_atraso) tr.classList.add('atrasado');
  // El renglón que el detalle está enseñando, marcado solo mientras el
  // detalle está abierto: marcar uno con el detalle cerrado se leería como
  // una selección que nadie hizo.
  if (r.renglon_id === RENGLON_ELEGIDO && DETALLE_ABIERTO) tr.classList.add('elegido');

  // EL NOMBRE ES UN BOTÓN: abre el detalle del renglón. Con el ratón basta
  // tocar cualquier parte de la fila que no sea un control; con el teclado,
  // éste es el que se enfoca.
  const producto = document.createElement('td');
  producto.className = 'producto';
  const nombre = document.createElement('button');
  nombre.type = 'button';
  nombre.className = 'ver-renglon';
  nombre.textContent = r.descripcion;
  nombre.title = r.descripcion;
  nombre.onclick = () => acciones.elegir(r, true);
  // Debajo del nombre, como el diseño: la clave, el anaquel —"GENERICO 3",
  // tal como llega del servidor— y las marcas. La clave y el anaquel son
  // texto chico y no insignias: identifican, no avisan.
  const insignias = document.createElement('span');
  insignias.className = 'insignias';
  [r.clave, r.anaquel].filter(Boolean).forEach(texto => {
    const dato = document.createElement('span');
    dato.className = 'identidad';
    dato.textContent = texto;
    insignias.append(dato);
  });
  insignias.append(...marcasDe(r).map(insigniaDeMarca));
  producto.append(nombre, insignias);

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

  // LO QUE SE PUEDE TOCAR ya no lo calcula este archivo (2026-09-22, paso 2 de
  // la revisión de arquitectura): `se_puede_editar` ya viene resuelto de
  // `transiciones.motivo_para_no_editar` —la misma decisión que el `WHERE` de
  // `_DESCARTAR`, `_AJUSTAR_LA_CANTIDAD` y `_ELEGIR_PROVEEDOR`, probada— y este
  // archivo solo la lee.
  const editable = r.se_puede_editar;

  const cantidad = celdaDeCantidad(r);

  // Descartar: UN CLIC y sin diálogo de confirmación. Lo que hace segura la
  // operación es que se puede deshacer —el renglón baja al bloque de
  // descartados con su botón para devolverlo—, no un "¿estás seguro?" que a la
  // tercera pantalla se cierra sin leer (ADR 0002). En la fila es una cruz,
  // como en el diseño; su nombre accesible dice qué hace y de cuál.
  const celdaAcciones = document.createElement('td');
  celdaAcciones.className = 'acciones';
  const quitar = botonDeAccion('Descartar', (boton) => acciones.descartar(r, boton));
  quitar.className = 'quitar';
  quitar.textContent = '×';
  // Apagado con la lista cerrada o vencida, igual que el campo de la cantidad y
  // el de proveedor. El servidor también lo rechaza -la condicion vive en el
  // `WHERE` de `_DESCARTAR`-, asi que esto es comodidad y no la garantia. Pero
  // un boton que se deja tocar para contestar 409 enseña a ignorar los avisos.
  quitar.disabled = !editable;
  quitar.title = editable
    ? 'Descartar: no se pide. Se puede devolver a la lista.'
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

  tr.append(producto, existencia, cobertura, cantidad,
            ...celdasDePrecio(r),
            celdaDeProveedor(r),
            celdaAcciones);

  // Un clic en la fila que no sea en un control la elige y abre su detalle:
  // es lo que pide el diseño, y no estorba a la cruz de descartar.
  tr.addEventListener('click', (evento) => {
    if (evento.target.closest('button, input, select, a, label')) return;
    acciones.elegir(r, true);
  });
  return tr;
};

// A QUIÉN SE LE PIDE ESTE RENGLÓN, con todas sus letras (ticket 20). Son dos
// cosas distintas y se dicen distinto: una sugerencia del sistema —con la
// certeza que viene hecha del servidor, "el más barato con existencia"— y una
// decisión de una persona, con su firma. El ticket 11 ya pagó por distinguir
// "nadie la tocó" de "alguien la confirmó" en la cantidad, y aquí vale lo mismo.
// Va en el `title` de la fila y en las firmas del detalle.
const eleccionEnPalabras = (e) => {
  if (!e) return '';
  if (!e.hay) {
    return (e.motivo || 'sin proveedor')
      + (e.nombres_empatados && e.nombres_empatados.length
         ? '. Igual de baratos: ' + e.nombres_empatados.join(' y ') + '.'
         : '');
  }
  if (e.es_decision) {
    return 'Lo eligió ' + (e.elegido_por || 'sin-identificar')
      + (e.difiere_de_la_sugerencia
          ? '. El sistema sugería ' + e.nombre_sugerido + '.'
          : '.');
  }
  return 'Lo sugiere el sistema' + (e.certeza ? ': ' + e.certeza + '.' : '.');
};

// A QUIÉN SE LE PIDE ESTE RENGLÓN (ticket 20), en la fila.
//
// Desde la segunda versión del diseño (decisión del dueño, 2026-10-05) la fila
// solo lo DICE: una píldora con el punto y el nombre del proveedor. Se elige en
// el detalle del renglón, donde se ven los cuatro precios con sus motivos
// (`preciosDelDetalle`). Hasta entonces era un desplegable en cada fila.
//
// **Cuál de las dos es —sugerencia o decisión— se dice debajo**: con una
// palabra ("sugerido", "elegido") y con todas sus letras en el `title` y en el
// detalle (`eleccionEnPalabras`).
//
// Ninguna regla vive en este archivo. Qué proveedor va, si eso es una decisión,
// si difiere de lo sugerido y qué frase le toca llegan resueltos en
// `r.eleccion`, de `particion.elegir` — que es una función pura con su tabla de
// casos. Elegir aquí el "más barato" habría metido la regla que decide a quién
// se le compra en el único archivo que ninguna prueba de Python mira.
const celdaDeProveedor = (r) => {
  const td = document.createElement('td');
  td.className = 'proveedor';
  td.dataset.etiqueta = 'Se le pide a';

  const e = r.eleccion || null;
  if (!e) return td;

  // Sin a quién pedirle NO se enseña el primero de la lista como si estuviera
  // elegido: eso sería exactamente inventar una decisión. Va la insignia de
  // "sin precio" y debajo por qué.
  if (e.hay) {
    const pildora = document.createElement('span');
    pildora.className = 'pildora-proveedor';
    pildora.append(puntoDeProveedor(e.proveedor), e.nombre);
    td.append(pildora);
  } else {
    td.append(insignia('Sin proveedor', 'gris'));
  }

  // LA PALABRA DE DEBAJO. Sin a quién pedirle NO es un error: o hay empate —y
  // el sistema no desempata, porque elegir por orden alfabético sería una
  // decisión que nadie tomó— o todavía no hay precios con los que sugerir.
  const quien = document.createElement('span');
  if (r.esta_en_transito) {
    quien.className = 'eleccion-de';
    quien.textContent = 'ya se le pidió';
  } else if (!e.hay) {
    quien.className = 'eleccion-sin';
    quien.textContent = e.nombres_empatados && e.nombres_empatados.length
      ? 'empate ' + e.nombres_empatados.join(' y ')
      : (e.motivo || 'sin proveedor');
  } else if (e.es_decision) {
    // Cuando la persona eligió DISTINTO de lo que el sistema sugería, se
    // marca: es el par que vuelve auditable la elección, igual que "el sistema
    // propuso 3" al lado de un 10.
    quien.className = 'eleccion-de' + (e.difiere_de_la_sugerencia ? ' distinta' : '');
    quien.textContent = e.difiere_de_la_sugerencia ? 'elegido a mano' : 'elegido';
  } else {
    quien.className = 'eleccion-de sugerida';
    quien.textContent = 'sugerido';
  }
  quien.title = eleccionEnPalabras(e);
  td.append(quien);

  return td;
};

// Un renglón ya descartado, en el bloque de abajo. Es una lista y no una tabla
// a propósito: de un renglón que no se va a pedir lo único que importa es cuál
// era, quién lo quitó y poder devolverlo. Repetir las cinco columnas daría el
// mismo peso visual a lo atendido que a lo pendiente.
const renglonDescartado = (r, alDevolver) => {
  const li = document.createElement('li');

  const nombre = document.createElement('span');
  nombre.textContent = r.descripcion;

  const devolver = botonDeAccion('Devolver a la lista', (boton) => alDevolver(r, boton));
  devolver.setAttribute('aria-label', 'Devolver ' + r.descripcion + ' a la lista');
  // Deshacer también es modificar, así que sigue la misma regla que descartar.
  // Apagarlo solo de un lado sería lo peor de los dos mundos: un renglón que
  // alguien quitó por error se quedaría fuera de una lista cerrada sin manera
  // de volver, y el botón estaría ahí prometiendo que sí.
  //
  // `r.se_puede_devolver_a_abierto` ya viene resuelto de
  // `transiciones.motivo_para_no_editar` (2026-09-22, paso 2): antes este
  // archivo recibía un solo `editable` de nivel de LISTA para todo el bloque
  // de descartados, que valía lo mismo que esto porque aquí solo llegan
  // renglones ya `descartado` — la bandera por renglón no cambia lo que se ve,
  // pero deja de recalcularlo sin prueba.
  devolver.disabled = !r.se_puede_devolver_a_abierto;
  devolver.title = r.se_puede_devolver_a_abierto
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
// El tono de la insignia del estado. Acompaña a la palabra, que es la que dice.
const TONOS_DEL_ESTADO = { abierto: 'verde', cerrado: 'gris', vencido: 'naranja' };

// Cuándo se armó la lista, que es lo que el ticket pide que se vea, y en qué
// estado está. Es distinto del corte: el corte dice DE QUÉ DÍA son las ventas
// y esto dice CUÁNDO SE HIZO la lista. Con el respaldo de SICAR llegando hasta
// 2.5 días tarde, confundirlos es exactamente lo que hay que poder evitar.
//
// Desde el diseño del 2026-09-30 son dos piezas: la insignia del estado en la
// barra del día, y la franja de debajo que dice cuándo se armó, quién la cerró
// y si alguien la reabrió.
const pintarCabecera = (datos) => {
  const estado = document.getElementById('pedido-estado');
  estado.className = 'insignia ' + (TONOS_DEL_ESTADO[datos.estado] || 'gris');
  estado.textContent = ESTADOS[datos.estado] || datos.estado || 'Sin guardar';
  estado.hidden = false;

  const armado = document.getElementById('armado');
  armado.replaceChildren();
  armado.className = 'armado ' + (datos.estado || '');

  if (datos.cerrado_en) {
    // Quién la cerró y cuándo, hecho en Python (migración 0013): "se cerró
    // sola" para el cierre automático, "lo firmó" para uno a mano. Sin la
    // firma —un cierre de antes de esa migración— se dice solo cuándo.
    const titular = document.createElement('b');
    // Sin punto después de `instanteEnPalabras`: ya termina en "p.m.", y el
    // punto extra salía "p.m.." (lo cazó el recorrido del navegador).
    titular.textContent = datos.frase_del_cierre || ('Se cerró el ' + instanteEnPalabras(datos.cerrado_en));
    armado.append(titular, ' Consideró las ventas ' +
      rangoEnPalabras(datos.ventas_consideradas_desde, datos.ventas_consideradas_hasta) +
      '. La siguiente lista arranca al día siguiente de ese corte.');
  } else if (datos.estado === 'vencido') {
    // Se dice con todas sus letras: una lista vencida no es un error del
    // sistema, es un día en que nadie la cerró, y lo que quedó sin atender
    // sigue ahí para verse.
    const titular = document.createElement('b');
    titular.textContent = 'Su día pasó y nadie la cerró.';
    armado.append(titular);
  } else if (datos.armado_en) {
    armado.append('Armada el ' + instanteEnPalabras(datos.armado_en));
  }
  if (datos.cerrado_en && datos.armado_en) {
    armado.append(' Se había armado el ' + instanteEnPalabras(datos.armado_en));
  }
  // La firma de la última reapertura (ADR 0016), hecha en Python con la hora
  // de la farmacia. Se queda aunque la lista se vuelva a cerrar.
  if (datos.frase_de_la_reapertura) armado.append(' ' + datos.frase_de_la_reapertura);
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

// LA FECHA DE HOY, tal como la ancla el servidor (`max(fecha)` del almacén,
// nunca el reloj). Se fija UNA vez, en la carga inicial —la única que pide
// `/api/pedido-sugerido` sin fecha, con permiso de armar el día—: las flechas
// siempre navegan con una fecha explícita de `vecinos` y nunca vuelven a
// pedirla. Sirve para que el contenedor de navegación pueda decir "(hoy)".
let FECHA_DE_HOY = null;

// LA FECHA QUE SE ESTÁ VIENDO AHORA, a diferencia de `FECHA_DE_HOY`: ésta SÍ
// cambia con cada navegación. Recibir una recepción probable, cancelar un
// pedido o devolver un atrasado (más abajo) vuelven a cargar la pantalla
// entera al terminar —cambia lo que viene en camino, que no se recalcula a
// mano—, y sin esto la recarga siempre volvía a "hoy" así se hubiera hecho el
// clic viendo un día de la bitácora: la persona perdía el lugar donde estaba.
let FECHA_ACTUAL = null;

// LO QUE SOLO PINTA UNA LISTA CON RENGLONES DE VERDAD (2026-09-27). Hasta la
// bitácora navegable, `cargarPedido` corría UNA vez por carga de página y
// nunca dejaba nada prendido de un día anterior. Navegar sí puede: un
// domingo, un festivo, el 404 de la bitácora o una falla pueden llegar
// DESPUÉS de que otro día ya encendió la tabla, el cierre o alguno de estos
// recuadros, y sin apagarlos se verían pegados de un día que ya no es éste.
const ocultarLoDeOtroDia = () => {
  ['pedido-tabla', 'armado', 'cierre', 'pedido-avisos', 'vistas', 'completar',
    'particion', 'descartados', 'pedido-corrida', 'pedido-sin-clasificar',
    'recepcion', 'en-camino', 'conciliacion',
    // Y las piezas del diseño del 2026-09-30: el estado, los pasos, la barra
    // de la lista, el detalle del renglón y el paso de captura.
    'pedido-estado', 'pasos', 'barra-lista', 'inspector', 'paso-repartir',
    'paso-capturar', 'pedido-sin-comparar'].forEach(id => {
    document.getElementById(id).hidden = true;
  });
  document.getElementById('cierre-detalle').textContent = '';
  document.getElementById('paso-revisar').hidden = false;
  pintarResumenDeAvisos();
  pintarLoQueVieneEnCaminoVacio();
};

// EL CONTENEDOR DE NAVEGACIÓN (decisión del dueño, 2026-09-27): la fecha al
// centro, una flecha a cada lado, y cada lista es un día. Vive aparte de
// `cargarPedido` porque las tres formas de respuesta que puede traer un día
// —la lista completa, "domingo o festivo" y el 404 de la bitácora que no
// sabe por qué— traen las tres sus `vecinos`, y las tres necesitan las
// mismas flechas.
//
// `vecinos` en `null` (o ausente) es "no se pudo saber" (regla 4 de
// `CLAUDE.md`): las dos flechas se esconden en vez de ofrecer una que
// podría 404ear o mentir sobre qué hay al lado. `vecinos.anterior` o
// `.siguiente` en `null` es un HECHO —no hay nada de ese lado— y se lee
// igual: la flecha no aparece.
const pintarNavegacion = (fecha, vecinos) => {
  const caja = document.getElementById('pedido-navegacion');
  if (!fecha) { caja.hidden = true; return; }
  const etiqueta = document.getElementById('pedido-navegacion-fecha');
  etiqueta.textContent = enPalabras(fecha) + (fecha === FECHA_DE_HOY ? ' (hoy)' : '');
  const anterior = document.getElementById('pedido-navegacion-anterior');
  const siguiente = document.getElementById('pedido-navegacion-siguiente');
  anterior.disabled = false;
  siguiente.disabled = false;
  anterior.hidden = !(vecinos && vecinos.anterior);
  siguiente.hidden = !(vecinos && vecinos.siguiente);
  if (vecinos && vecinos.anterior) anterior.onclick = () => cargarPedido(vecinos.anterior);
  if (vecinos && vecinos.siguiente) siguiente.onclick = () => cargarPedido(vecinos.siguiente);
  caja.hidden = false;
  // IR A HOY (diseño del 2026-09-30): desde un día de la bitácora, de un clic
  // y no a flechazos. Pide hoy SIN fecha, igual que la carga de la página: es
  // la única llamada con permiso de armar el día.
  const hoy = document.getElementById('ir-a-hoy');
  hoy.hidden = !FECHA_DE_HOY || fecha === FECHA_DE_HOY;
  hoy.onclick = () => cargarPedido();
};

// RECARGA LA FECHA QUE SE ESTÁ VIENDO, no siempre "hoy". La usan las cuatro
// acciones de recepción y tránsito de más abajo —confirmar o rechazar una
// recepción probable, recibir a mano, cancelar un pedido, devolver un
// atrasado—, que cambian lo que viene en camino y no pueden pintar su propio
// resultado porque ese bloque solo lo trae la carga completa. "Hoy" sigue
// pidiéndose sin fecha —con permiso de armar el día si hace falta—; un día
// de la bitácora se vuelve a leer por `GET .../dia/{fecha}`, que solo lee.
const recargarLoQueSeVe = () =>
  cargarPedido(FECHA_ACTUAL === FECHA_DE_HOY ? undefined : FECHA_ACTUAL);

// ------------------------------------- la vista del día (diseño 2026-09-30)

// LO QUE LA PANTALLA RECUERDA DE CÓMO SE ESTÁ MIRANDO EL DÍA. Es estado de la
// vista y no de los datos: en memoria, ni en el servidor ni en `localStorage`
// —si un renglón está elegido es de quien mira—. Cambiar de día lo reinicia;
// recargar el mismo día no.
//
// - `PASO`: revisar, repartir o capturar.
// - `PEDIDO_EN_CAPTURA`: cuál pedido se está capturando en el paso tres.
// - `RENGLON_ELEGIDO`: el que enseña el detalle de la derecha.
// - `DETALLE_ABIERTO`: el detalle flota encima de la tabla (segunda versión
//   del diseño, 2026-10-05) y solo se ve cuando alguien tocó un renglón.
let PASO = 'revisar';
let PEDIDO_EN_CAPTURA = null;
let RENGLON_ELEGIDO = null;
let DETALLE_ABIERTO = false;
let HAY_DETALLE = false;
// Si la franja de avisos está abierta. `null` es "que decida la pantalla":
// plegada, salvo que haya una falla (decisión del dueño, 2026-10-05). Se queda
// como la persona la deje... hasta que aparezca una falla que no estaba cuando
// la plegó: entonces vuelve a decidir la pantalla, y se abre. Plegarla no es
// decir "no me avises de las que vengan".
let AVISOS_ABIERTOS = null;
let FALLAS_EN_LOS_AVISOS = 0;
let FALLAS_AL_DECIDIR = 0;
// Lo que hacen los botones de los pasos. Lo pone `cargarPedido`, que es quien
// tiene la lista; antes de la primera carga no hace nada.
let IR_A_PASO = () => {};

const reiniciarLaVistaDelDia = () => {
  PASO = 'revisar';
  PEDIDO_EN_CAPTURA = null;
  RENGLON_ELEGIDO = null;
  DETALLE_ABIERTO = false;
};

// Las cuatro columnas de proveedor del encabezado, con los nombres que manda
// el servidor (`datos.puente`) y en su orden, que es el mismo de cada fila.
const pintarEncabezado = () => {
  const fila = document.getElementById('pedido-encabezado');
  fila.querySelectorAll('th.precio-celda, th.escala-celda').forEach(th => th.remove());
  const antes = document.getElementById('encabezado-proveedor');
  if (EN_ESCALA) {
    const th = document.createElement('th');
    th.className = 'escala-celda';
    th.scope = 'col';
    th.textContent = 'Precio · de más barato a más caro';
    fila.insertBefore(th, antes);
    return;
  }
  PROVEEDORES.forEach(p => {
    const th = document.createElement('th');
    th.className = 'precio-celda';
    th.scope = 'col';
    th.append(puntoDeProveedor(p.proveedor), p.nombre);
    fila.insertBefore(th, antes);
  });
};

// El detalle se ve si hay un renglón que enseñar y alguien lo abrió.
const ajustarElDetalle = () => {
  document.getElementById('inspector').hidden = !HAY_DETALLE || !DETALLE_ABIERTO;
};

// LAS FIRMAS DE UN RENGLÓN: quién decidió la cantidad y el proveedor, o que
// nadie lo hizo. Es una firma, no un permiso (regla 3 de CLAUDE.md), y se
// muestra porque es lo que permite preguntar "¿por qué pediste diez?" a la
// persona correcta.
const firmasDelRenglon = (r) => {
  const firma = (que, quien, clase) => {
    const li = document.createElement('li');
    const dice = document.createElement('span');
    dice.textContent = que;
    if (clase) dice.className = clase;
    const firmado = document.createElement('span');
    firmado.className = 'quien';
    firmado.textContent = quien;
    li.append(dice, firmado);
    return li;
  };
  const firmas = [];
  // LA CANTIDAD (ticket 11). Quién la cambió, a la vista. Aparece aunque la
  // cantidad haya quedado igual que la propuesta: confirmar el número del
  // sistema también es una decisión, y es la que dice que la reposición 1 a 1
  // acertó ese día. Las dos cifras se dicen cuando no son la misma: es lo que
  // hace evidente que la propuesta del sistema NO se sobreescribió.
  if (r.fue_ajustada) {
    firmas.push(firma('Cantidad: ' + r.cantidad_a_pedir
        + (r.difiere_de_la_propuesta
           ? ' (el sistema propuso ' + r.cantidad_propuesta + ')'
           : ', la misma que propuso el sistema'),
      'ajustada por ' + (r.ajustada_por || 'sin-identificar')
        + (r.ajustada_en ? ' · ' + instanteEnPalabras(r.ajustada_en) : '')));
  } else {
    firmas.push(firma('Cantidad: ' + r.cantidad_a_pedir + ', la que propuso el sistema',
      'Reposición 1 a 1 de lo vendido'));
  }
  // A QUIÉN (ticket 20): sugerencia o decisión, con todas sus letras.
  const e = r.eleccion;
  if (e) {
    firmas.push(firma(e.hay ? 'Proveedor: ' + e.nombre : 'Proveedor: sin elegir',
      eleccionEnPalabras(e), e.es_decision && e.difiere_de_la_sugerencia ? 'distinta' : ''));
  }
  return firmas;
};

// EL DETALLE DEL RENGLÓN ELEGIDO. Todo lo que la fila no alcanza a decir en
// una línea vive aquí: cada frase del servidor, cada motivo de cada hueco y
// quién decidió qué. Nada se calcula: se acomoda lo que el renglón ya trae.
const pintarDetalle = (r, acciones) => {
  HAY_DETALLE = !!r;
  if (!r) { ajustarElDetalle(); return; }
  const parte = (nombre) => document.getElementById('inspector-' + nombre);

  parte('nombre').textContent = r.descripcion;
  parte('clave').textContent = r.clave || '';
  parte('clase').textContent = [
    r.clave ? '' : 'Sin código de barras',
    // El anaquel viene del servidor ("GENERICO 3"); vacío o nulo no se escribe.
    r.anaquel || '',
    r.clasificacion ? mayuscula(r.clasificacion) : '',
  ].filter(Boolean).join(' · ');

  // Las tres cifras de la fila, grandes. `null` es "no se sabe", nunca un
  // cero: un cero aquí se leería "agotado".
  const hay = parte('hay');
  hay.className = r.esta_agotado ? 'urgente' : '';
  hay.textContent = r.existencia === null || r.existencia === undefined ? 'sin dato' : cifra(r.existencia);
  parte('vendidas').textContent = cifra(r.piezas_vendidas);
  // PEDIR, que desde la segunda versión del diseño se corrige AQUÍ y no en la
  // fila: con − y + y el campo en medio, si el renglón se puede tocar.
  const pedir = parte('pedir');
  pedir.replaceChildren(r.se_puede_editar && acciones.ajustar
    ? controlDeCantidad(r, acciones.ajustar)
    : String(r.cantidad_a_pedir));
  if (r.difiere_de_la_propuesta) {
    const propuesta = document.createElement('span');
    propuesta.className = 'propuesta';
    propuesta.textContent = 'el sistema propuso ' + r.cantidad_propuesta;
    pedir.append(propuesta);
  }

  // QUÉ PASA CON ESTE PRODUCTO: cada marca con su frase entera y, si la hay,
  // su acción —devolver lo atrasado, corregir lo recibido—.
  const marcas = marcasDe(r).filter(m => !m.soloFila && m.frase);
  parte('marcas').replaceChildren(...marcas.map(m => {
    const li = document.createElement('li');
    const frase = document.createElement('span');
    frase.className = 'frase';
    frase.textContent = m.frase;
    li.append(insigniaDeMarca(m), frase);
    if (m.control) li.append(m.control);
    return li;
  }));
  parte('marcas-bloque').hidden = !marcas.length;

  const precios = preciosDelDetalle(r, acciones);
  parte('precios').replaceChildren(precios.cuerpo);
  parte('leido').textContent = precios.leido;
  parte('ayuda').hidden = !(acciones.elegirProveedor && r.se_puede_editar);

  parte('firmas').replaceChildren(...firmasDelRenglon(r));

  // Las dos del diseño: descartar —en rojo, es la que saca el renglón— y
  // volver a consultar el precio, teñida.
  const botones = [];
  if (r.se_puede_editar) {
    const quitar = botonDeAccion('Descartar', (b) => acciones.descartar(r, b), 'peligro');
    quitar.setAttribute('aria-label', 'Descartar ' + r.descripcion);
    botones.push(quitar);
  }
  if (precios.boton) {
    precios.boton.classList.add('tenida');
    botones.push(precios.boton);
  }
  parte('acciones').replaceChildren(...botones);
  ajustarElDetalle();
};

// LOS TRES PASOS. Se enseñan con una lista abierta, o con una que ya tiene
// pedidos —lo que se pidió un día se tiene que poder ver aunque ya se haya
// cerrado—. Sin eso, la lista es solo la tabla.
const PASOS = ['revisar', 'repartir', 'capturar'];

const pintarPasos = (lista) => {
  const conPasos = !!(lista && lista.renglones && lista.renglones.length
    && (lista.estado === 'abierto' || (lista.pedidos && lista.pedidos.length)));
  if (!conPasos) PASO = 'revisar';
  document.getElementById('pasos').hidden = !conPasos;
  const actual = PASOS.indexOf(PASO);
  document.querySelectorAll('#pasos button').forEach(boton => {
    const i = PASOS.indexOf(boton.dataset.paso);
    if (i === actual) boton.setAttribute('aria-current', 'step');
    else boton.removeAttribute('aria-current');
    boton.classList.toggle('hecho', i < actual);
  });
  PASOS.forEach(p => { document.getElementById('paso-' + p).hidden = p !== PASO; });
};

// LA FRANJA DE AVISOS. Cada renglón es una de las notas de siempre; aquí solo
// se mira cuáles están a la vista y de qué tono las pintó su función, para
// decir arriba cuántas piden algo. No decide nada: lee lo que ya se pintó.
const nivelDeLaNota = (nota) => {
  const clases = nota.id === 'pedido-avisos'
    ? [...nota.children].map(hijo => hijo.className).join(' ')
    : nota.className;
  if (nota.id === 'completar') return /\bmal\b/.test(clases) ? 'mal' : 'aviso';
  if (/\bmal\b/.test(clases)) return 'mal';
  if (/\b(aviso|tope|espera)\b/.test(clases)) return 'aviso';
  if (/\bfalla\b/.test(clases)) return 'mal';
  if (/\b(todo|bien)\b/.test(clases)) return 'ok';
  return 'informa';
};

const pintarResumenDeAvisos = () => {
  const caja = document.getElementById('avisos');
  const lista = document.getElementById('avisos-lista');
  let visibles = 0;
  let fallas = 0;
  const porAtender = [];
  const enOrden = [];
  lista.querySelectorAll('.aviso-fila').forEach(fila => {
    const nota = fila.firstElementChild;
    const seVe = !nota.hidden && nota.textContent.trim() !== '';
    fila.hidden = !seVe;
    if (!seVe) return;
    visibles += 1;
    // La etiqueta del botón de completar dice qué trae: completar, abrir una
    // sesión, o las dos cosas.
    if (nota.id === 'completar') {
      const sesiones = !!nota.querySelector('.sesiones');
      const faltantes = !!nota.querySelector(':scope > b');
      fila.dataset.etiqueta = sesiones && !faltantes ? 'Sesión' : 'Completar';
    }
    const nivel = nivelDeLaNota(nota);
    fila.className = 'aviso-fila ' + nivel;
    if (nivel === 'mal' || nivel === 'aviso') porAtender.push(fila.dataset.etiqueta);
    else enOrden.push(fila.dataset.etiqueta);
    if (nivel === 'mal') fallas += 1;
  });
  caja.hidden = !visibles;
  if (!visibles) return;
  // La tarjeta se tiñe según lo que trae: rojo con una falla, ámbar con algo
  // por atender. Acompaña al punto y a la palabra del resumen.
  caja.className = 'avisos' + (fallas ? ' con-falla' : porAtender.length ? ' por-atender' : '');

  FALLAS_EN_LOS_AVISOS = fallas;
  if (fallas > FALLAS_AL_DECIDIR) AVISOS_ABIERTOS = null;
  const abierta = AVISOS_ABIERTOS === null ? fallas > 0 : AVISOS_ABIERTOS;
  lista.hidden = !abierta;
  const boton = document.getElementById('avisos-resumen');
  boton.setAttribute('aria-expanded', abierta ? 'true' : 'false');
  document.getElementById('avisos-ver').textContent = abierta ? 'Ocultar' : 'Ver';
  document.getElementById('avisos-punto').className =
    'punto' + (fallas ? ' mal' : porAtender.length ? ' aviso' : '');

  const texto = document.getElementById('avisos-texto');
  const titular = document.createElement('b');
  titular.textContent = porAtender.length
    ? plural(porAtender.length, 'cosa por atender', 'cosas por atender')
    : 'Nada que atender';
  const resto = document.createElement('span');
  resto.className = 'resto';
  resto.textContent = ' · ' + (porAtender.length ? porAtender : enOrden).join(' · ');
  texto.replaceChildren(titular, resto);
};

// EL FILTRO DE LA LISTA. Es de la persona y se ve: lo que esconde lo esconde
// porque alguien tecleó algo en el campo, y se dice cuántos quedaron a la
// vista. No es el sistema decidiendo qué renglón se ve —eso no pasa nunca
// (ADR 0002)—: es buscar con los ojos, más rápido.
const sinAcentos = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

const aplicarElFiltro = () => {
  const buscado = sinAcentos(document.getElementById('pedido-filtro').value.trim());
  const filas = document.querySelectorAll('#pedido-renglones tr');
  let aLaVista = 0;
  filas.forEach(tr => {
    tr.hidden = !!buscado && !sinAcentos(tr.dataset.busqueda || '').includes(buscado);
    if (!tr.hidden) aLaVista += 1;
  });
  const aviso = document.getElementById('pedido-filtrados');
  aviso.hidden = !buscado;
  aviso.textContent = buscado ? aLaVista + ' de ' + filas.length + ' a la vista' : '';
};

// LO QUE LA BARRA LATERAL CUENTA. Un número en una cápsula junto a cada
// sección; ninguno se calcula con una regla nueva: son las mismas banderas que
// ya llegaron del servidor, contadas.
const pintarCuenta = (nombre, cuantos, tono) => {
  const cuenta = document.getElementById('cuenta-' + nombre);
  cuenta.hidden = !cuantos;
  cuenta.textContent = cuantos ? String(cuantos) : '';
  cuenta.className = 'cuenta-pestana' + (tono ? ' ' + tono : '');
};

// Cuántos renglones de la lista de HOY quedan por atender. Un día de la
// bitácora no cambia el número de la barra: la barra dice cómo está hoy.
const pintarCuentaDeLaLista = (trabajables) => {
  if (!FECHA_DE_HOY || FECHA_ACTUAL !== FECHA_DE_HOY) return;
  pintarCuenta('pedido', trabajables.filter(r =>
    !r.esta_en_transito && !r.esta_cancelado && !r.esta_recibido).length, 'gris');
};

// LO QUE LA BARRA CUENTA CON CADA CARGA DE HOY. "En camino" cuenta lo que
// pide a una persona: lo que probablemente ya llegó y lo atrasado, en ámbar si
// hay algo atrasado. "Sesiones", las que una lectura encontró caducadas —la
// sección misma, al abrirse, le pregunta a Doyle y la pone al día—.
const pintarCuentasDeLaCarga = (datos) => {
  pintarLoQueVieneEnCaminoVacio();
  if (!FECHA_DE_HOY || FECHA_ACTUAL !== FECHA_DE_HOY) return;
  pintarCuenta('sesiones', (datos.sesiones_caducadas || []).length, 'rojo');
  const propuestas = ((datos.recepcion && datos.recepcion.propuestas) || []).length;
  const atrasados = ((datos.en_camino && datos.en_camino.renglones) || []).filter(v => v.atrasado).length;
  pintarCuenta('camino', propuestas + atrasados, atrasados ? 'naranja' : 'acento');
};

// "En camino" se lee junto con la lista del día: un día sin lista lo deja
// vacío, y se dice por qué en vez de enseñar una página en blanco.
const pintarLoQueVieneEnCaminoVacio = () => {
  document.getElementById('camino-sin-lista').hidden =
    !document.getElementById('recepcion').hidden || !document.getElementById('en-camino').hidden;
};

// LOS DATOS, en "Estado": el último día con ventas, cómo le fue al lote sobre
// la lista de hoy y cuándo se armó. Las frases largas viven en los avisos de
// la lista; aquí va lo corto.
const pintarEstadoDeLosDatos = (datos) => {
  if (!FECHA_DE_HOY || FECHA_ACTUAL !== FECHA_DE_HOY) return;
  const filas = [fila('Último día con ventas', true, enPalabras(datos.fecha_de_ventas))];
  if (datos.corrida) {
    filas.push(fila('Lote de anoche', !datos.corrida.se_interrumpio,
      datos.corrida.consultados + ' de ' + datos.corrida.en_la_lista + ' consultados'
        + (datos.corrida.se_corto_por_tiempo ? ' · se detuvo al tope' : '')));
  } else if (datos.corrida_ausente) {
    filas.push(fila('Lote de anoche', datos.corrida_ausente.nivel === 'falla' ? false : null,
      datos.corrida_ausente.frase));
  }
  if (datos.armado_en) {
    filas.push(fila('Lista del día', null, (ESTADOS[datos.estado] || datos.estado || '')
      + ' · armada el ' + instanteEnPalabras(datos.armado_en)));
  }
  pintar('estado-datos', filas);
  pintarEstadoLateral();
};

// LA TARJETA DE ESTADO DE LA BARRA LATERAL: si todo contesta, y hasta qué día
// hay ventas. Lo que dice sale de `/api/modulos` y de la lista de hoy.
let ESTADO_DE_LOS_MODULOS = null;

const unirNombres = (nombres) => nombres.length < 2
  ? nombres.join('')
  : nombres.slice(0, -1).join(', ') + ' y ' + nombres[nombres.length - 1];

const pintarEstadoLateral = () => {
  const punto = document.getElementById('estado-lateral-punto');
  const texto = document.getElementById('estado-lateral-texto');
  const detalle = document.getElementById('estado-lateral-detalle');
  const ventas = FECHA_DE_HOY ? 'Ventas hasta el ' + diaEnPalabras(FECHA_DE_HOY) + '.' : '';
  const modulos = ESTADO_DE_LOS_MODULOS;
  if (!modulos) { detalle.textContent = ventas; return; }
  if (modulos.falla) {
    punto.className = 'punto mal';
    texto.textContent = 'No se pudo consultar';
    detalle.textContent = modulos.falla;
    return;
  }
  const caidos = modulos.lista.filter(m => m.ok === false);
  punto.className = 'punto ' + (caidos.length ? 'mal' : 'ok');
  texto.textContent = caidos.length
    ? (caidos.length === 1 ? caidos[0].nombre + ' no responde' : caidos.length + ' módulos no responden')
    : 'Todo responde';
  detalle.textContent = (caidos.length ? '' : unirNombres(modulos.lista.map(m => m.nombre)) + '. ') + ventas;
};

// Los controles de la vista del día que están en el HTML desde el principio:
// los tres pasos, la franja de avisos, el filtro y la cruz del detalle.
const iniciarLaVistaDelDia = () => {
  document.querySelectorAll('#pasos button').forEach(boton => {
    boton.onclick = () => IR_A_PASO(boton.dataset.paso);
  });
  document.getElementById('avisos-resumen').onclick = () => {
    AVISOS_ABIERTOS = document.getElementById('avisos-lista').hidden;
    FALLAS_AL_DECIDIR = FALLAS_EN_LOS_AVISOS;
    pintarResumenDeAvisos();
  };
  document.getElementById('pedido-filtro').addEventListener('input', aplicarElFiltro);
  // Al cerrar el detalle, el foco vuelve al renglón que lo abrió: quien va con
  // el teclado no se queda parado en un panel que ya no está.
  const cerrarElDetalle = () => {
    DETALLE_ABIERTO = false;
    ajustarElDetalle();
    document.querySelectorAll('#pedido-renglones tr.elegido').forEach(tr => {
      tr.classList.remove('elegido');
      const nombre = tr.querySelector('.ver-renglon');
      if (nombre) nombre.focus();
    });
  };
  document.getElementById('inspector-cerrar').onclick = cerrarElDetalle;
  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && DETALLE_ABIERTO
        && !document.getElementById('confirmar-cierre').open
        && !document.getElementById('ventana-sesiones').open) cerrarElDetalle();
  });
};

// `fecha` (`AAAA-MM-DD`) es la que traen los `vecinos` de otro día: nunca la
// teclea nadie ni sale del reloj del navegador. Sin ella se pide **hoy**, que
// es la única llamada con permiso de armar el día si hace falta —decisión 1
// del dueño, "al abrir, siempre cae en el día de hoy"—; con ella se pide la
// bitácora navegable (`GET .../dia/{fecha}`), que **solo lee** (ADR 0020).
async function cargarPedido(fecha) {
  const corte = document.getElementById('corte');
  const tabla = document.getElementById('pedido-tabla');
  // Mientras la petición viaja, las flechas no invitan a un segundo clic que
  // se cruce con el primero en el aire; `pintarNavegacion` las reactiva ella
  // misma en cuanto llega la respuesta, por cualquiera de las salidas.
  document.getElementById('pedido-navegacion-anterior').disabled = true;
  document.getElementById('pedido-navegacion-siguiente').disabled = true;
  // OTRO DÍA, OTRA VISTA: el paso, el renglón elegido y su detalle vuelven a
  // empezar. Recargar el MISMO día (tras recibir, cancelar…) los conserva: la
  // persona no pierde el lugar donde estaba.
  if ((fecha || FECHA_DE_HOY) !== FECHA_ACTUAL) reiniciarLaVistaDelDia();
  const url = fecha ? '/api/pedido-sugerido/dia/' + fecha : '/api/pedido-sugerido';
  let datos = await respuestaDe(fetch(url));

  // UNA FALLA DE VERDAD: sin respuesta del servidor, o el servidor leyó y no
  // pudo (`fallas.que_hacer`, ticket 29). El 404 de la bitácora que "no sabe
  // por qué" —más abajo— no trae `que_hacer`, y por eso esta condición lo
  // deja pasar de largo: no es la misma falla y no se pinta igual.
  if (datos.ok === false && (datos.que_hacer || datos.sin_respuesta)) {
    // Si el servidor mandó su frase, ésa ya dice qué no se pudo armar: el
    // titular se esconde para no decirlo dos veces (recorrido del ticket 29).
    // Sin respuesta no hay frase, y el titular da el contexto.
    corte.hidden = false;
    corte.textContent = 'No se pudo armar el pedido sugerido.';
    corte.hidden = !!datos.frase;
    notaDeFalla('pedido-nota', datos);
    ocultarLoDeOtroDia();
    pintarNavegacion(fecha || null, datos.vecinos);
    return;
  }

  // LA BITÁCORA NAVEGABLE (ADR 0020): no hay lista para esa fecha y ni el
  // calendario dice por qué. Puede ser una fecha futura, de antes de que
  // Continental existiera, o un hueco real —el servidor ya dijo que no los
  // distingue, y aquí no se inventa una causa que los datos no dan (regla 4
  // de `CLAUDE.md`): se enseña su `detalle` tal cual, sin componer nada.
  if (datos.ok === false) {
    corte.hidden = true;
    ocultarLoDeOtroDia();
    nota('pedido-nota', datos.detalle || '', 'aviso');
    pintarNavegacion(fecha, datos.vecinos);
    return;
  }

  // Qué tan recientes son las ventas que SÍ se leyeron, dicho por el servidor
  // (ticket 29): un lunes por la mañana, la lista del viernes es lo normal, y
  // esto lo dice. Para un día cualquiera de la bitácora viaja en `null` a
  // propósito —no aplica ahí— y `pintarVentas` ya sabe esconderse con eso.
  pintarVentas(datos.ventas);

  // La fecha que se está mostrando, para la navegación: la de la lista, o la
  // del día sin lista por calendario. Las dos vienen del servidor y nunca de
  // lo que se pidió, que es la garantía que trae `Vecinos` (dos lecturas en
  // dos momentos no pueden discrepar). Si esta carga fue la de "hoy" —sin
  // fecha—, aquí queda fijada para el resto de la sesión.
  const fechaMostrada = datos.dia_sin_lista ? datos.dia_sin_lista.fecha : datos.fecha_de_ventas;
  if (!fecha && fechaMostrada) FECHA_DE_HOY = fechaMostrada;
  if (fechaMostrada) FECHA_ACTUAL = fechaMostrada;
  pintarNavegacion(fechaMostrada, datos.vecinos);

  // DOMINGO O FESTIVO (decisión del dueño, 2026-09-27): por calendario no se
  // arma lista ese día. Nunca una lista vacía sin decir por qué (regla 4):
  // la razón llega hecha de Python, con el nombre del evento si lo hay —esta
  // pantalla no compone la frase, solo la pinta.
  if (datos.dia_sin_lista) {
    corte.hidden = true;
    ocultarLoDeOtroDia();
    nota('pedido-nota', datos.dia_sin_lista.frase, 'aviso');
    return;
  }

  // Ni una venta en el almacén: el servidor lo AFIRMA —leyó y no había—, con
  // su frase en `ventas`. No se escribe nada más. Solo puede pasar en la
  // carga de "hoy": la bitácora navegable nunca trae esta forma (siempre hay
  // una lista, un día sin lista por calendario, o el 404 de arriba).
  if (!datos.fecha_de_ventas) {
    corte.hidden = true;
    pintarResumenDeAvisos();
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

  // Un día anterior pudo esconder este párrafo (domingo, 404, una falla): se
  // vuelve a enseñar aquí, con la lista de verdad que sí hay que mostrar.
  corte.hidden = false;
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
  // Lo que la barra lateral cuenta de "En camino", y el "Estado" de los datos:
  // solo con la lista de hoy, que es la que dice cómo está todo AHORA.
  pintarCuentasDeLaCarga(datos);
  pintarEstadoDeLosDatos(datos);
  // LA CONCILIACIÓN DIARIA (ADR 0021): aparte de las dos de arriba porque no
  // viaja en ESTA respuesta -es una lectura más cara que solo hace falta
  // cuando se abre este bloque- y por eso se pide sola, sin esperarla: no hay
  // razón para que una compra de hace tres días retrase pintar la lista de
  // hoy. `cargarConciliacion` se cuida sola de esconder el bloque si algo
  // sale mal, igual que `respuestaDe` nunca truena.
  cargarConciliacion(datos.pedido_sugerido_id);
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
    // Un día anterior con renglones pudo dejar la tabla y estos recuadros
    // prendidos: sin apagarlos aquí, esta lista vacía se vería con la de otro
    // día pegada debajo (armado, cierre, avisos y lo que viene en camino ya
    // se pintaron arriba con los datos de HOY, y esos sí se quedan).
    tabla.hidden = true;
    ['vistas', 'completar', 'particion', 'descartados', 'pedido-corrida',
      'pedido-sin-clasificar', 'pedido-sin-comparar', 'barra-lista', 'inspector',
      'pasos'].forEach(id => {
      document.getElementById(id).hidden = true;
    });
    pintarPasos(null);
    pintarCuentaDeLaLista([]);
    pintarResumenDeAvisos();
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
      elegir: elegirRenglon,
    };
    // Los renglones que se ven con la vista de ahora. El elegido —el que
    // enseña el detalle— tiene que estar entre ellos: si la vista lo escondió
    // o se descartó, se elige el primero, que es el más urgente.
    const visibles = vistas ? renglonesDe(trabajables, vistaActiva) : trabajables;
    if (!visibles.some(r => r.renglon_id === RENGLON_ELEGIDO)) {
      RENGLON_ELEGIDO = visibles.length ? visibles[0].renglon_id : null;
    }
    if (vistas) {
      // Los conteos del interruptor son de la lista DE TRABAJO: decir "18" en
      // una vista donde se ven 12 porque seis están descartados haría buscar
      // seis renglones que no están escondidos, sino atendidos.
      vistas.forEach(v => { v.cuantos = renglonesDe(trabajables, v).length; });
      pintarInterruptor(vistas, vistaActiva, mostrar);
      pintarRenglones(
        visibles,
        trabajables.length,
        vistas.find(v => v.clave !== vistaActiva.clave) || vistaActiva,
        datos.descartados,
        acciones);
    } else {
      pintarRenglones(visibles, trabajables.length, null, datos.descartados, acciones);
    }
    document.getElementById('barra-lista').hidden = false;
    aplicarElFiltro();
    pintarDetalle(datos.renglones.find(r => r.renglon_id === RENGLON_ELEGIDO), acciones);
    pintarCuentaDeLaLista(trabajables);
    // El bloque de descartados NO se filtra por vista, y es a propósito: la
    // vista de medicamentos esconde abarrotes de lo que falta por pedir, pero
    // un abarrote que alguien descartó por error tiene que poder devolverse sin
    // adivinar en qué vista aparece.
    pintarDescartados(
      datos.renglones.filter(r => r.estado === DESCARTADO),
      datos.descartados,
      devolver);
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
    // EL PASO TRES: la captura de un pedido a la vez, con su botón de enviar.
    pintarPasoCaptura(datos.pedidos, tacharRenglon, enviarPedido);
    pintarPasos(datos);
    pintarResumenDeAvisos();
    tabla.hidden = false;
  };

  // ELEGIR UN RENGLÓN: el que el detalle enseña. No se vuelve a pintar la
  // tabla —se perdería el foco del campo que se esté tocando—: se mueve la
  // marca de la fila y se pinta el detalle. `abrir` es el clic de una persona:
  // en pantalla angosta, donde el detalle flota encima, es lo que lo abre.
  function elegirRenglon(r, abrir) {
    RENGLON_ELEGIDO = r.renglon_id;
    if (abrir) DETALLE_ABIERTO = true;
    document.querySelectorAll('#pedido-renglones tr').forEach(tr => {
      tr.classList.toggle('elegido',
        DETALLE_ABIERTO && Number(tr.dataset.renglon) === r.renglon_id);
    });
    pintarDetalle(datos.renglones.find(x => x.renglon_id === r.renglon_id), {
      editable: datos.estado === 'abierto',
      descartar: descartar,
      ajustar: ajustar,
      elegirProveedor: elegirProveedor,
      consultarPrecio: consultarPrecio,
      elegir: elegirRenglon,
    });
    if (abrir) document.getElementById('inspector-cerrar').focus();
  }

  // Los tres pasos y "Capturar en NADRO" llevan aquí: cambia lo que se ve, no
  // los datos, y por eso basta con volver a pintar.
  IR_A_PASO = (paso, pedidoId) => {
    PASO = paso;
    if (pedidoId !== undefined) PEDIDO_EN_CAPTURA = pedidoId;
    repintar();
    document.getElementById('panel-pedido').scrollTop = 0;
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
  //
  // Desde la segunda versión del diseño se elige tocando un proveedor en el
  // detalle. Tocar el que ya es una DECISIÓN no se manda: movería la hora y la
  // firma de algo que ya estaba decidido —es la misma regla de `ajustar` con
  // la misma cifra—. Tocar el que solo era SUGERENCIA sí: es confirmarla.
  function elegirProveedor(r, proveedor, control) {
    if (!proveedor) return;
    if (r.eleccion && r.eleccion.es_decision && r.eleccion.proveedor === proveedor) return;
    moverRenglon(r.renglon_id, '/proveedor', control, aplicar, { proveedor });
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
    exito('Lista partida en ' + plural((datos.pedidos || []).length, 'pedido', 'pedidos')
      + '. Siguen en borrador: se pueden cambiar y volver a partir.');
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
    exito('Pedido a ' + nombre + ' marcado como enviado. Sus renglones pasaron a '
      + '«en tránsito», así que la lista de mañana ya no los va a volver a '
      + 'proponer. Recuerda: esto no se lo mandó a ' + nombre + ' — lo capturas '
      + 'tú en su portal.');
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
// LOS TÍTULOS DE LOS BLOQUES DE "EN CAMINO" (diseño del 2026-09-30). Son
// rótulos de sección, no afirmaciones: lo que dice qué pasó con cada renglón
// llega hecho de `transito.py` y de `recepcion.py`, y va debajo de cada título.
const ENCABEZADOS_DE_EN_CAMINO = {
  recepcion: 'Probablemente ya llegó',
  atrasados: 'Atrasado',
  faltaron: 'Llegó de menos',
  vuelven: 'Vuelve en la siguiente lista',
  pedidos: 'Pedidos en camino',
};

// Un bloque de "En camino": su título, cuántos trae —si se sabe— y debajo lo
// que se le pase.
const bloqueDeEnCamino = (clave, cuantos, ...piezas) => {
  const bloque = document.createElement('div');
  bloque.className = 'en-camino-bloque';
  const cabeza = document.createElement('div');
  cabeza.className = 'titulo-bloque';
  const titulo = document.createElement('h3');
  titulo.textContent = ENCABEZADOS_DE_EN_CAMINO[clave];
  cabeza.append(titulo);
  if (cuantos) cabeza.append(insignia(String(cuantos), clave === 'atrasados' ? 'naranja' : 'acento'));
  bloque.append(cabeza, ...piezas.filter(Boolean));
  return bloque;
};

// Un párrafo con una frase del servidor, o nada si no la mandó.
const parrafo = (clase, texto) => {
  if (!texto) return null;
  const p = document.createElement('p');
  p.className = clase;
  p.textContent = texto;
  return p;
};

// LO QUE VIENE EN CAMINO DE LISTAS ANTERIORES (ticket 24, casillas 2, 4 y 5).
//
// Ninguna frase se compone aquí: el encabezado, "Pedido el martes a NADRO, sin
// recibir.", lo vendido desde entonces y la advertencia de que esto solo sabe
// de lo que pasó por Continental llegan hechos de `transito.py`, con pruebas.
// Aquí se acomodan, desde el diseño del 2026-09-30 en cuatro bloques: lo
// atrasado, lo que llegó de menos, lo que vuelve en la siguiente lista, y los
// pedidos que vienen en camino con sus renglones.
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

  const advertencia = parrafo('advertencia', en_camino.advertencia);

  // QUÉ ES "ATRASADO" AQUÍ (ticket 25), con su número, o por qué no se sabe.
  // Las dos frases llegan hechas de Python; la de los atrasados solo si hay.
  // Una u otra, no las dos: la de los atrasados ya lleva el número.
  const umbral = parrafo('umbral' + (en_camino.umbral_del_atraso == null ? ' mal' : ''),
    en_camino.frase_de_los_atrasados || en_camino.frase_del_umbral || '');

  // Un renglón en camino, como tarjeta: qué es, cuántas, cuándo y a quién se
  // pidió, lo vendido desde entonces y la firma.
  const tarjetaEnCamino = (v) => {
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
    // `title`, que en una pantalla táctil no se ve nunca. Hecha en Python.
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
      const botones = document.createElement('div');
      botones.className = 'botones';
      const boton = botonDeAccion('Devolver a la lista',
        (b) => devolverAtrasado(v.renglon_id, b), 'tenida');
      boton.setAttribute('aria-label', 'Devolver a la lista ' + v.descripcion);
      botones.append(boton);
      li.append(botones);
    }
    return li;
  };

  const renglones = en_camino.renglones || [];
  const atrasados = renglones.filter(v => v.atrasado);
  const hayAtrasados = renglones.some(v => v.se_puede_devolver);

  // 1. LO ATRASADO, primero: es lo que hay que mirar.
  let bloqueAtrasados = null;
  if (atrasados.length) {
    const lista = document.createElement('ul');
    lista.append(...atrasados.map(tarjetaEnCamino));
    bloqueAtrasados = bloqueDeEnCamino('atrasados', atrasados.length, umbral,
      hayAtrasados ? parrafo('advertencia', en_camino.advertencia_al_devolver) : null, lista);
  }

  // 2. LO QUE LLEGÓ DE MENOS (ticket 27): lo que faltó vuelve en la siguiente
  // lista, y aquí se ve —con su firma— y se corrige si el resto llegó en otra
  // factura. Todas las frases y la etiqueta son de Python.
  let bloqueFaltaron = null;
  if ((en_camino.faltaron || []).length) {
    const faltaron = document.createElement('ul');
    faltaron.className = 'faltaron tarjeta-lista';
    en_camino.faltaron.forEach(f => {
      const li = document.createElement('li');
      const que = document.createElement('span');
      que.className = 'que';
      que.textContent = (f.clave ? f.clave + ' · ' : '') + f.descripcion;
      const explica = document.createElement('span');
      explica.className = 'explica';
      explica.textContent = f.frase;
      li.append(que,
        controlAMano(f.renglon_id, f.etiqueta_a_mano, f.descripcion, f.piezas_recibidas),
        explica);
      faltaron.append(li);
    });
    bloqueFaltaron = bloqueDeEnCamino('faltaron', null,
      parrafo('resumen', en_camino.frase_de_los_que_faltaron), faltaron);
  }

  // 3. LO QUE VUELVE EN LA SIGUIENTE LISTA (ticket 25): lo que se canceló o se
  // devolvió y ninguna lista ha vuelto a traer todavía. Se enseña para que el
  // número de mañana se pueda explicar hoy. El encabezado viene de Python.
  let bloqueVuelven = null;
  if ((en_camino.vuelven || []).length) {
    const vuelven = document.createElement('ul');
    vuelven.className = 'vuelven tarjeta-lista';
    en_camino.vuelven.forEach(v => {
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
    bloqueVuelven = bloqueDeEnCamino('vuelven', null,
      parrafo('resumen', en_camino.frase_de_los_que_vuelven), vuelven);
  }

  // 4. LOS PEDIDOS QUE VIENEN EN CAMINO, cada uno con sus renglones. Agrupar
  // por `pedido_id` es acomodar lo que ya llegó: cada renglón dice de qué
  // pedido es. Lo que no se encuentre en ningún pedido —un servidor viejo— se
  // pinta aparte, nunca se pierde.
  //
  // CANCELAR UN PEDIDO DE UNA LISTA ANTERIOR (ticket 25). Uno por pedido, con
  // lo que declara quien lo aprieta escrito AL LADO del botón — la misma
  // lección que el total dentro del botón de enviar: el diálogo de "¿seguro?"
  // se aprende a despachar sin leer; la frase junto al botón, no.
  const pedidos = document.createElement('ul');
  pedidos.className = 'pedidos-en-camino';
  const sinAtrasar = renglones.filter(v => !v.atrasado);
  const deCadaPedido = new Map();
  sinAtrasar.forEach(v => {
    if (!deCadaPedido.has(v.pedido_id)) deCadaPedido.set(v.pedido_id, []);
    deCadaPedido.get(v.pedido_id).push(v);
  });
  (en_camino.pedidos || []).forEach(p => {
    const li = document.createElement('li');
    const cabeza = document.createElement('div');
    cabeza.className = 'cabeza-pedido';
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = p.frase;
    cabeza.append(que);
    const explica = document.createElement('span');
    explica.className = 'explica';
    // Un pedido con algo ya recibido (ticket 26) sí se capturó: no se ofrece
    // cancelarlo, y se dice por qué en vez de pintar un botón que da 409.
    if (p.se_puede_cancelar === false) {
      explica.textContent = 'No se puede cancelar: ' + p.motivo_para_no_cancelar + '.';
    } else {
      explica.textContent = p.frase_para_cancelar;
      cabeza.append(botonDeAccion('Cancelar: no está en el portal de ' + p.nombre,
        (b) => cancelarPedido(p.pedido_id, b), 'plana'));
    }
    li.append(cabeza, explica);
    const suyos = deCadaPedido.get(p.pedido_id) || [];
    deCadaPedido.delete(p.pedido_id);
    if (suyos.length) {
      const lista = document.createElement('ul');
      lista.className = 'renglones-del-pedido';
      lista.append(...suyos.map(tarjetaEnCamino));
      li.append(lista);
    }
    pedidos.append(li);
  });
  const sueltos = [...deCadaPedido.values()].flat();
  if (sueltos.length) {
    const li = document.createElement('li');
    const lista = document.createElement('ul');
    lista.className = 'renglones-del-pedido';
    lista.append(...sueltos.map(tarjetaEnCamino));
    li.append(lista);
    pedidos.append(li);
  }
  const bloquePedidos = bloqueDeEnCamino('pedidos', null, resumen, advertencia,
    atrasados.length ? null : umbral,
    pedidos.children.length ? pedidos : null);

  caja.replaceChildren(...[bloqueAtrasados, bloqueFaltaron, bloquePedidos, bloqueVuelven].filter(Boolean));
  caja.hidden = false;
};

// LA RECEPCIÓN SUGERIDA (ticket 26, ADR 0014). Lo que seguramente ya llegó,
// con su evidencia —proveedor, fecha, piezas, folio— para que una persona la
// juzgue, y dos botones: confirmar (pasa a recibido, firmado) y rechazar
// (sigue en camino; esa compra ya no se le propone). NADA pasa a recibido
// solo.
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
    const botones = document.createElement('div');
    botones.className = 'botones';
    // Sin botón de confirmar cuando la evidencia no alcanza lo pedido: la
    // frase de la cantidad, que viene de Python, ya dice por qué.
    if (p.se_puede_confirmar) {
      const confirmar = botonDeAccion('Confirmar que llegó',
        (b) => recibirORechazar('confirmar', p.renglon_id, p.compras, b), 'llena');
      confirmar.setAttribute('aria-label', 'Confirmar que llegó ' + p.descripcion);
      botones.append(confirmar);
    }
    // Lo que trae de menos (ticket 27): la etiqueta, con sus números, viene
    // hecha de Python.
    if (p.se_puede_recibir_lo_que_trae && p.etiqueta_de_lo_que_trae) {
      botones.append(botonDeAccion(p.etiqueta_de_lo_que_trae,
        (b) => recibirParcial(p.renglon_id, p.compras, b), 'llena'));
    }
    const rechazar = botonDeAccion('Rechazar: no es este pedido',
      (b) => recibirORechazar('rechazar', p.renglon_id, p.compras, b));
    rechazar.setAttribute('aria-label', 'Rechazar la compra de ' + p.descripcion);
    botones.append(rechazar);
    // Y siempre a mano: la compra de 10 que surtió dos pedidos solo confirma
    // uno, y el otro se recibe así.
    if (p.etiqueta_a_mano) botones.append(controlAMano(p.renglon_id, p.etiqueta_a_mano, p.descripcion));
    li.append(botones);
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
    // Uno por renglón, cada uno con su salida a mano (ticket 27).
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
  caja.replaceChildren(bloqueDeEnCamino('recepcion', lista.children.length,
    resumen,
    ...(retraso.textContent ? [retraso] : []),
    ...(lista.children.length && advertencia.textContent ? [advertencia] : []),
    ...(hayRenglones && aMano.textContent ? [aMano] : []),
    ...(lista.children.length ? [lista] : []),
    ...(esperan.children.length ? [esperan] : [])));
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
  await recargarLoQueSeVe();
  exito(respuesta.frase);
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
  campo.placeholder = 'piezas';
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
  await recargarLoQueSeVe();
  exito(respuesta.frase);
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
  await recargarLoQueSeVe();
  exito(respuesta.frase);
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
  await recargarLoQueSeVe();
  exito(respuesta.frase);
};

// ============================== LA CONCILIACIÓN DIARIA (ADR 0021) ==============================
//
// Lo propuesto contra lo que de verdad se compró. Aparte de `datos` -no la
// trae la carga de la lista- porque es una lectura más cara que solo hace
// falta cuando se abre este bloque: el calendario del rango, las compras y
// lo ya recibido de toda la instalación, no solo de esta lista.

// Se pide con el id de la lista que YA se cargó. `null`/`undefined` esconde
// el bloque en vez de pedir nada: pasa en el instante entre que `cargarPedido`
// pinta un día sin lista (domingo, festivo, el 404 de la bitácora) y nadie le
// dio ningún id.
const cargarConciliacion = async (pedidoSugeridoId) => {
  const caja = document.getElementById('conciliacion');
  if (!pedidoSugeridoId) { caja.hidden = true; caja.replaceChildren(); return; }
  const datos = await respuestaDe(fetch('/api/pedido-sugerido/' + pedidoSugeridoId + '/conciliacion'));
  pintarConciliacion(datos);
};

const pintarConciliacion = (datos) => {
  const caja = document.getElementById('conciliacion');
  if (!datos) { caja.hidden = true; caja.replaceChildren(); return; }

  const resumen = document.createElement('p');
  resumen.className = 'resumen' + (datos.ok === false ? ' mal' : '');
  resumen.textContent = datos.frase
    + (datos.ok === false && datos.detalle ? ' (' + datos.detalle + ')' : '');
  const piezas = [resumen];

  (datos.avisos || []).forEach((aviso, i) => {
    const p = document.createElement('p');
    p.id = 'conciliacion-aviso-' + i;
    piezas.push(p);
    notaDeFalla(p.id, aviso);
  });

  // LO PROPUESTO QUE SÍ SE COMPRÓ (bloque 1): con a quién, cuánto y a qué
  // precio, y LO QUE PAGA EL MÓDULO ENTERO -la diferencia contra lo más
  // barato que ya sabíamos-. Las dos frases llegan hechas de Python.
  //
  // `marcadas` lleva qué renglones sigue queriendo confirmar la persona: nace
  // con TODOS los accionables adentro -el clic de lote parte de "confirma
  // todo"- y cada checkbox se puede destildar antes de apretar el botón.
  const marcadas = new Map();
  const coincidencias = document.createElement('ul');
  coincidencias.className = 'coincidencias';
  (datos.coincidencias || []).forEach(c => {
    const li = document.createElement('li');
    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = c.frase;
    li.append(que);
    if (c.frase_del_pago) {
      const pago = document.createElement('span');
      pago.className = 'pago' + (c.hubo_mas_barato ? ' hallazgo' : '');
      pago.textContent = c.frase_del_pago;
      li.append(pago);
    }
    if (c.accionable) {
      marcadas.set(c.renglon_id, c.compras);
      const etiqueta = document.createElement('label');
      etiqueta.className = 'lote';
      const marca = document.createElement('input');
      marca.type = 'checkbox';
      marca.checked = true;
      marca.addEventListener('change', () => {
        if (marca.checked) marcadas.set(c.renglon_id, c.compras);
        else marcadas.delete(c.renglon_id);
      });
      etiqueta.append(marca, ' Incluir en el lote');
      li.append(etiqueta);
    } else if (c.motivo_no_accionable) {
      // NUNCA se auto-confirma sin clave de Doyle: se cuenta como comprado,
      // pero no hay con qué armar el pedido retroactivo. Se revisa a mano
      // (ADR 0014, heredado por la conciliación).
      const explica = document.createElement('span');
      explica.className = 'explica';
      explica.textContent = c.motivo_no_accionable;
      li.append(explica);
    }
    coincidencias.append(li);
  });

  const botonDelLote = datos.coincidencias && datos.coincidencias.some(c => c.accionable)
    ? botonDeAccion('Confirmar el lote',
        (b) => confirmarLoteDeConciliacion(datos.pedido_sugerido_id, marcadas, b))
    : null;

  // LO PROPUESTO QUE NO SE COMPRÓ (bloque 2), agrupado por motivo y en el
  // orden de Python: lo que nunca se va a resolver solo primero, lo
  // definitivo al final. Los tres motivos NO se confunden entre sí (ADR
  // 0021) y por eso llegan ya distinguidos -esta pantalla no decide cuál es
  // cuál, solo pinta el grupo que Python ya armó.
  const sinComprar = document.createElement('ul');
  sinComprar.className = 'sin-comprar';
  (datos.sin_comprar || []).forEach(g => {
    const li = document.createElement('li');
    const cuales = document.createElement('ul');
    (g.renglones || []).forEach(r => {
      const fila = document.createElement('li');
      fila.textContent = r.frase;
      cuales.append(fila);
    });
    li.append(cuales);
    sinComprar.append(li);
  });

  // LO COMPRADO QUE NADIE PROPUSO (bloque 3): normal, y se dice así. Lo
  // descartado-y-comprado-de-todos-modos y lo ambiguo llevan su propia marca
  // -ninguno de los dos se auto-confirma nunca, y por eso este bloque no
  // trae ningún checkbox ni ningún `renglon_id` con el que armar uno.
  const sueltas = document.createElement('ul');
  sueltas.className = 'compradas-sin-proponer';
  (datos.compradas_sin_proponer || []).forEach(c => {
    const li = document.createElement('li');
    li.className = 'suelta'
      + (c.ambiguo ? ' ambiguo' : '') + (c.fue_descartado ? ' descartado' : '');
    li.textContent = c.frase;
    sueltas.append(li);
  });

  caja.replaceChildren(
    ...piezas,
    ...(coincidencias.children.length ? [coincidencias, ...(botonDelLote ? [botonDelLote] : [])] : []),
    ...(sinComprar.children.length ? [sinComprar] : []),
    ...(sueltas.children.length ? [sueltas] : []));
  caja.hidden = false;
};

// EL ÚNICO CLIC QUE ESCRIBE ALGO DE LA CONCILIACIÓN (ADR 0021): confirma en
// lote lo que sigue marcado. El servidor vuelve a conciliar antes de
// escribir y se salta lo que ya no sea exactamente lo que se vio -la misma
// garantía que confirmar o rechazar una recepción normal-, así que esto NO
// manda lo que la persona cree que va a pasar: manda lo que vio, y el
// servidor decide qué de eso sigue siendo cierto.
const confirmarLoteDeConciliacion = async (pedidoSugeridoId, marcadas, boton) => {
  boton.disabled = true;
  nota('pedido-accion', '');
  const renglones = [...marcadas.entries()].map(([renglon_id, compras]) => ({ renglon_id, compras }));
  const respuesta = await respuestaDe(fetch('/api/pedido-sugerido/' + pedidoSugeridoId
      + '/conciliacion/confirmar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ renglones }),
      }), 'al_guardar');
  if (!respuesta.ok) {
    boton.disabled = false;
    // Genérico a propósito (regla 5): el detalle está en la bitácora.
    notaDeFalla('pedido-accion', respuesta);
    return;
  }
  // Cambia el estado de los renglones confirmados -y quizá lo que se le
  // puede pedir a cada proveedor-, así que se recarga la pantalla entera,
  // igual que confirmar una recepción normal. Eso vuelve a pedir la
  // conciliación también: no hace falta repintar este bloque a mano.
  await recargarLoQueSeVe();
  exito(respuesta.frase);
};

const pintarRenglones = (visibles, total, otra, descartados, acciones) => {
  pintarEncabezado();
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
      (b) => acciones.completar(b), 'tenida');
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
      'EN LA VENTANA DEL VISOR que se abre sola al darle a «Abrir sesión». ' +
      'De una en una: mientras un portal esté esperando, los otros no abren.');
    caducadas.forEach(s => {
      const fila = document.createElement('div');
      fila.className = 'fila';
      const nombre = document.createElement('span');
      nombre.textContent = s.nombre;
      const abrir = botonDeAccion('Abrir sesión', (b) => acciones.abrirSesion(s, b), 'tenida');
      abrir.title = 'Le pide a Doyle que abra el navegador del portal y te '
        + 'abre el visor para que lo veas. Continental no abre navegadores: '
        + 'se lo pide a Doyle.';
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

// EL ARCHIVO DEL PEDIDO (ticket 23). La URL viene HECHA del servidor
// (`pedido.csv`): aquí no se arma nada, y `null` quiere decir que no hay qué
// exportar —un pedido vacío contestaría 409—. Un enlace y no un `fetch`: la
// descarga la hace el navegador con el `Content-Disposition` del servidor. En
// otra pestaña, para que un error se lea ahí sin tirar la pantalla de trabajo;
// y sin el atributo de descarga, que haría guardar el JSON de un error con
// nombre de CSV.
const enlaceCsv = (pedido, texto) => {
  if (!pedido.csv) return null;
  const enlace = document.createElement('a');
  enlace.className = 'exportar';
  enlace.href = pedido.csv;
  enlace.target = '_blank';
  enlace.rel = 'noopener';
  enlace.textContent = texto || 'Bajar este pedido en CSV (para Excel)';
  enlace.title = 'Se arma en este momento con lo que el pedido tiene ahora, y no '
    + 'se guarda en ninguna parte: cada vez que lo bajes sale al día.';
  return enlace;
};

// LA LISTA DE CAPTURA DE UN PEDIDO (ticket 22). Todo lo que dice viene HECHO
// del servidor. Aquí no se filtra ni se suma nada, por lo mismo que el conteo
// de descartados sale de Python desde el ticket 10: dos pestañas bastan para
// que un número que el navegador va llevando se separe de la verdad. Lo único
// que decide esta función es cómo se ve.
//
// Desde el diseño del 2026-09-30 ya no es un `<details>` debajo de su pedido:
// es la pantalla del paso tres, un pedido a la vez, y el avance y el botón de
// enviar van en el pie (`pintarPasoCaptura`).
const pintarCaptura = (pedido, alTachar) => {
  const captura = pedido.captura;
  const caja = document.createElement('div');
  caja.className = 'captura' + (captura.todo_capturado ? ' completa' : '');

  const lista = document.createElement('ol');
  captura.lineas.forEach(linea => {
    const li = document.createElement('li');
    li.className = linea.esta_capturado ? 'hecho' : '';

    // LA CASILLA (casilla 1). Se manda lo que quedó marcado y no un "alterna".
    // Solo un borrador se tacha: lo enviado ya está en el portal.
    const casilla = document.createElement('input');
    casilla.type = 'checkbox';
    casilla.id = 'captura-' + linea.renglon_id;
    casilla.checked = linea.esta_capturado;
    casilla.disabled = !pedido.es_borrador;
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
  return caja;
};

// EL TONO DE CADA ESTADO DE UN PEDIDO, para su insignia. La palabra es la del
// glosario y llega del servidor (`estado_a_la_vista`); el tono la acompaña.
const TONOS_DEL_PEDIDO = {
  borrador: 'gris', enviado: 'acento', cancelado: 'rojo',
  recibido: 'verde', 'recibido parcial': 'naranja',
};

const insigniaDelPedido = (pedido) => {
  const estado = pedido ? (pedido.estado_a_la_vista || pedido.estado) : null;
  return estado
    ? insignia(mayuscula(estado), TONOS_DEL_PEDIDO[estado] || 'gris')
    : insignia('Sin partir', 'gris');
};

// EN QUÉ SE PARTE LA LISTA (ticket 20): EL PASO DOS.
//
// Dos cosas distintas en el mismo paso, y se dicen por separado:
//
//   - la PARTICIÓN, que es el cálculo de ahora mismo: en cuántos pedidos
//     quedaría y cuánto sumaría cada uno si se apretara el botón;
//   - los PEDIDOS, que son las filas que ya existen, con su estado.
//
// Ningún número se calcula aquí. Los totales, el parcial, cuántas líneas van
// sin precio y cuáles proveedores no tiene SICAR llegan de `particion.partir`,
// que es puro y tiene su tabla de casos. Desde el diseño del 2026-09-30 cada
// pedido es una tarjeta, y la captura y el envío viven en el paso tres.
const pintarParticion = (particion, pedidos, editable, alPartir, alEnviar, alTachar) => {
  const caja = document.getElementById('particion');
  if (!particion) { caja.hidden = true; caja.replaceChildren(); return; }

  caja.replaceChildren();

  // LOS QUE YA NO ESTÁN EN LA PARTICIÓN, Y POR QUÉ HAY QUE PINTARLOS IGUAL
  // (ticket 21). Al enviar un pedido, sus renglones pasan a `en tránsito` y
  // dejan de contar como "por repartir": el pedido enviado desaparece de
  // `particion.pedidos`. Si esta función solo recorriera esa lista, **el pedido
  // recién enviado se borraría de la pantalla** — justo el que el encargado
  // acaba de crear y el único del que necesita ver la firma.
  //
  // Así que se pinta la UNIÓN: primero lo que se partiría ahora, y después los
  // pedidos guardados que ya no aparecen ahí.
  const guardados = new Map((pedidos || []).map(p => [p.proveedor, p]));
  const enLaParticion = new Set(particion.pedidos.map(p => p.proveedor));
  const fueraDeLaParticion = (pedidos || []).filter(p => !enLaParticion.has(p.proveedor));
  const enviados = (pedidos || []).filter(p => p.fue_enviado).length;
  const cancelados = (pedidos || []).filter(p => p.fue_cancelado).length;

  const cabeza = document.createElement('div');
  cabeza.className = 'particion-cabeza';
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

  const detalle = document.createElement('span');
  detalle.className = 'detalle';
  detalle.textContent = particion.hay
    ? 'Cada pedido se puede volver a armar mientras siga en borrador: cambia el '
      + 'proveedor de un renglón o su cantidad en el paso uno, y vuelve a partir.'
    // Con algo cancelado, la frase es de Python (ticket 25): la vieja decía
    // "todo lo que había se capturó en los portales", y no es verdad. Y desde
    // el 26 también con algo recibido. La de Python se usa SIEMPRE que llega:
    // dice cuántos van en camino, cuántos se cancelaron y cuántos llegaron, y
    // la de abajo queda de reserva.
    : (particion.sin_nada_por_repartir
       ? particion.sin_nada_por_repartir
       : (enviados
          ? 'No queda nada por repartir: todo lo que había se capturó en los '
            + 'portales y sus renglones están en tránsito. Ya se puede cerrar.'
          : 'Elige a quién se le pide cada renglón, o consulta los precios para '
            + 'que el sistema pueda sugerirlo.'));
  cabeza.append(titular, detalle);
  caja.append(cabeza);

  const grilla = document.createElement('div');
  grilla.className = 'pedidos-grilla';

  // El botón que lleva a capturar un pedido: al paso tres, con ése elegido.
  const botonDeCapturar = (g) => botonDeAccion('Capturar en ' + g.nombre,
    () => IR_A_PASO('capturar', g.pedido_id), 'tenida');

  // Un pedido por proveedor, con su total. El estado sale del pedido GUARDADO
  // cuando lo hay: "borrador" es un hecho de la tabla, no de este cálculo.
  particion.pedidos.forEach(p => {
    const tarjeta = document.createElement('div');
    tarjeta.className = 'pedido';
    const guardado = guardados.get(p.proveedor);

    const encabezado = document.createElement('div');
    encabezado.className = 'pedido-cabeza';
    const quien = document.createElement('span');
    quien.className = 'quien';
    quien.textContent = p.nombre;
    encabezado.append(quien, insigniaDelPedido(guardado));

    // EL TOTAL, O POR QUÉ NO SE SABE. `null` no se pinta como una cifra y
    // jamás como "$0.00": un cero ahí se leería "este pedido no cuesta nada",
    // que es lo contrario de lo que pasa. El parcial sí se enseña, con el
    // conteo de lo que le falta al lado — el dato que hay no se esconde.
    const cuanto = document.createElement('span');
    cuanto.className = 'total' + (p.hay_total ? '' : ' nose');
    cuanto.textContent = p.hay_total ? '$' + p.total_sin_iva : 'total sin saber';

    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = plural(p.renglones, 'renglón', 'renglones')
      + ' · ' + plural(p.piezas, 'pieza', 'piezas');
    tarjeta.append(encabezado, cuanto, que);

    if (!p.hay_total && p.renglones) {
      const marca = document.createElement('span');
      marca.className = 'marca';
      marca.textContent = plural(p.sin_precio, 'renglón va sin precio', 'renglones van sin precio')
        + ' de ' + p.nombre + ', así que el total no se puede sumar. Lo que sí '
        + 'se sabe suma $' + p.parcial_sin_iva + '. Se pide igual.';
      tarjeta.append(marca);
    }

    // SICAR NO LO CONOCE. Se dice y no se esconde: el pedido se arma igual,
    // con `proveedor_id` en NULL. Hoy es el caso de QuePharma.
    if (!p.tiene_puente) {
      const marca = document.createElement('span');
      marca.className = 'marca tenue';
      marca.textContent = p.nombre + ' ' + p.estado_del_puente
        + ': se le puede pedir igual, pero la compra no se va a poder cruzar '
        + 'sola con SICAR cuando llegue.';
      tarjeta.append(marca);
    }

    const acciones = document.createElement('div');
    acciones.className = 'acciones';
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
      tarjeta.append(marca);
      if (guardado.frase_de_la_recepcion) {
        const llegada = document.createElement('span');
        llegada.className = 'envio hecho';
        llegada.textContent = guardado.frase_de_la_recepcion;
        tarjeta.append(llegada);
      }

      // QUÉ SIGNIFICA ENVIAR, y ya lo dice el servidor (ticket 21). La frase
      // viene HECHA de `particion.frase_del_envio`: aquí no se elige entre dos
      // literales ni se compone nada. Es la frase que impide que alguien crea
      // que Continental le mandó el pedido a NADRO. En un borrador va en el
      // paso tres, junto al botón de enviar, que es donde se lee antes de
      // apretarlo; aquí solo la de lo ya enviado, que es la firma.
      if (!guardado.es_borrador) {
        const envio = document.createElement('span');
        envio.className = 'envio' + (guardado.fue_enviado ? ' hecho' : '');
        envio.textContent = guardado.frase_del_envio
          + (guardado.fue_enviado && guardado.enviado_en
             ? ' Fue ' + instanteEnPalabras(guardado.enviado_en)
             : '');
        tarjeta.append(envio);
      }

      // A CAPTURAR (ticket 22). Solo un BORRADOR se captura: `!fue_enviado`
      // era lo mismo hasta el ticket 25, y un cancelado le habría pintado
      // casillas a un pedido que ya no existe en ningún portal.
      if (guardado.es_borrador && guardado.captura && guardado.captura.cuantos) {
        acciones.append(botonDeCapturar(guardado));
      }
      // EL CSV (ticket 23), en borrador y en enviado: el primero sirve para
      // capturar o revisar, y el segundo es el respaldo de lo que se pidió.
      const archivo = enlaceCsv(guardado, 'CSV');
      if (archivo) acciones.append(archivo);
    }
    if (acciones.children.length) tarjeta.append(acciones);
    grilla.append(tarjeta);
  });

  // LOS PEDIDOS QUE YA NO ESTÁN EN LA PARTICIÓN. Son los enviados -sus
  // renglones ya no se reparten- y los que se quedaron vacíos. Se pintan desde
  // el pedido GUARDADO, que trae todo lo suyo. No hay vista previa que enseñar
  // porque no hay nada que volver a partir, y eso es lo correcto: un pedido
  // enviado ya no se edita.
  fueraDeLaParticion.forEach(g => {
    const tarjeta = document.createElement('div');
    tarjeta.className = 'pedido';

    const encabezado = document.createElement('div');
    encabezado.className = 'pedido-cabeza';
    const quien = document.createElement('span');
    quien.className = 'quien';
    quien.textContent = g.nombre;
    encabezado.append(quien, insigniaDelPedido(g));

    const cuanto = document.createElement('span');
    cuanto.className = 'total' + (g.hay_total ? '' : ' nose');
    cuanto.textContent = g.hay_total ? '$' + g.total_sin_iva : 'total sin saber';

    const que = document.createElement('span');
    que.className = 'que';
    que.textContent = plural(g.renglones, 'renglón', 'renglones');

    const marca = document.createElement('span');
    marca.className = 'marca tenue';
    marca.textContent = 'Pedido ' + g.pedido_id + ', ' + (g.estado_a_la_vista || g.estado)
      + ', armado ' + instanteEnPalabras(g.armado_en);
    tarjeta.append(encabezado, cuanto, que, marca);
    // LO QUE LLEGÓ (ticket 27): la frase del pedido recibido, de Python.
    if (g.frase_de_la_recepcion) {
      const llegada = document.createElement('span');
      llegada.className = 'envio hecho';
      llegada.textContent = g.frase_de_la_recepcion;
      tarjeta.append(llegada);
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
    tarjeta.append(envio);

    // Un pedido que se quedó SIN renglones también cae aquí, y sigue sin
    // poderse enviar: el motivo viene hecho de `particion.motivo_para_no_enviar`
    // y se escribe en vez de esconder la tarjeta. El rol no tiene DELETE, así
    // que ese pedido existe; esconderlo sería la falla silenciosa.
    if (g.es_borrador && g.motivo_para_no_enviar) {
      const porque = document.createElement('span');
      porque.className = 'marca';
      porque.textContent = g.motivo_para_no_enviar + '.';
      tarjeta.append(porque);
    }

    const acciones = document.createElement('div');
    acciones.className = 'acciones';
    // CANCELAR (ticket 25): solo un pedido enviado, y con lo que se declara
    // escrito junto al botón. La frase y la decisión son de Python; la
    // garantía es el `WHERE` de `_CANCELAR_EL_PEDIDO`.
    if (g.se_puede_cancelar && g.frase_para_cancelar) {
      acciones.append(botonDeAccion('Cancelar: no está en el portal de ' + g.nombre,
        (b) => cancelarPedido(g.pedido_id, b), 'plana'));
      const porque = document.createElement('span');
      porque.className = 'marca tenue';
      porque.textContent = g.frase_para_cancelar;
      tarjeta.append(porque);
    }
    // UN BORRADOR TAMBIÉN PUEDE CAER AQUÍ CON RENGLONES DENTRO, y ésa es la
    // trampa del ticket 22: la vista previa se recalcula con los precios de
    // este instante, y si llegó un LEVIC más barato ya no pone a NADRO... pero
    // el pedido GUARDADO de NADRO todavía los tiene. Se capturan igual: lo que
    // se captura es lo que al enviar pasa a `en tránsito`, y eso es `pedido_id`.
    if (g.es_borrador && g.captura && g.captura.cuantos) acciones.append(botonDeCapturar(g));
    // EL CSV también aquí, y sobre todo aquí: los enviados caen en este
    // recorrido, y son justo el pedido que más interesa respaldar.
    const archivo = enlaceCsv(g, 'CSV');
    if (archivo) acciones.append(archivo);
    if (acciones.children.length) tarjeta.append(acciones);
    grilla.append(tarjeta);
  });

  if (grilla.children.length) caja.append(grilla);

  // LOS QUE NO SE REPARTEN A NADIE. Se cuentan y se dicen: un renglón que se
  // cayera de la partición en silencio es mercancía que va a faltar sin que
  // nadie se entere, que es lo mismo que CONTEXT.md prohíbe para los productos
  // sin anaquel. "Resolver" lleva al paso uno, donde se elige.
  if (particion.cuantos_sin_proveedor) {
    const fila = document.createElement('div');
    fila.className = 'sin-decidir';
    const sin = document.createElement('span');
    sin.className = 'detalle';
    sin.textContent = plural(particion.cuantos_sin_proveedor,
      'renglón se queda fuera', 'renglones se quedan fuera')
      + ': todavía no hay a quién pedírselos. No se pierden — siguen en la '
      + 'lista y entran en cuanto alguien elija proveedor.';
    fila.append(insignia(plural(particion.cuantos_sin_proveedor, 'sin decidir', 'sin decidir'), 'naranja'),
      sin, botonDeAccion('Resolver', () => IR_A_PASO('revisar'), 'plana'));
    caja.append(fila);
  }

  // PARTIR, y después capturar. Partir se puede apretar cuantas veces haga
  // falta: la garantía de que no se dupliquen es de la BASE —uno por
  // proveedor dentro de la misma lista—. Con borradores ya armados, lo
  // principal es empezar a capturar; volver a partir queda al lado.
  const borradores = (pedidos || []).filter(g => g.es_borrador && g.captura && g.captura.cuantos);
  const pie = document.createElement('div');
  pie.className = 'particion-pie';
  if (particion.hay) {
    const boton = botonDeAccion(
      pedidos && pedidos.length ? 'Volver a partir' : 'Partir en pedidos',
      (b) => alPartir(b), borradores.length ? 'grande' : 'llena grande');
    boton.disabled = !editable;
    boton.title = 'Arma un pedido por proveedor con los renglones del paso uno. '
      + 'Se puede volver a hacer mientras los pedidos sigan en borrador.';
    pie.append(boton);
  }
  if (borradores.length) {
    pie.prepend(botonDeAccion('Empezar a capturar',
      () => IR_A_PASO('capturar', borradores[0].pedido_id), 'llena grande'));
  }
  if (particion.hay) {
    const cuantos = document.createElement('span');
    cuantos.className = 'detalle';
    cuantos.textContent = plural(particion.renglones_repartidos, 'renglón repartido', 'renglones repartidos') + '.';
    pie.append(cuantos);
  }
  if (pie.children.length) caja.append(pie);

  caja.hidden = false;
};

// CAPTURAR Y ENVIAR (tickets 21 y 22): EL PASO TRES. A la izquierda los
// pedidos de esta lista, cada uno con cuánto lleva tachado; a la derecha el
// elegido, renglón por renglón, y al pie su botón de enviar.
const pintarPasoCaptura = (pedidos, alTachar, alEnviar) => {
  const caja = document.getElementById('captura-panel');
  caja.replaceChildren();
  // Los que se capturan —borradores con algo dentro— y los que ya se
  // enviaron, para ver su firma. Los cancelados ya no existen en ningún
  // portal y no se enseñan aquí: siguen en el paso dos con su motivo.
  const deEstePaso = (pedidos || []).filter(g => g.es_borrador
    ? !!(g.captura && g.captura.cuantos)
    : g.fue_enviado);

  if (!deEstePaso.length) {
    const vacio = document.createElement('div');
    vacio.className = 'captura-trabajo';
    const frase = document.createElement('p');
    frase.className = 'nota';
    frase.textContent = 'Todavía no hay ningún pedido que capturar: la lista se parte en '
      + 'pedidos en el paso dos.';
    vacio.append(frase, botonDeAccion('Ir a repartir', () => IR_A_PASO('repartir'), 'tenida'));
    caja.append(vacio);
    return;
  }

  // El elegido: el que se pidió, o el primer borrador, o el primero.
  const guardado = deEstePaso.find(g => g.pedido_id === PEDIDO_EN_CAPTURA)
    || deEstePaso.find(g => g.es_borrador)
    || deEstePaso[0];
  PEDIDO_EN_CAPTURA = guardado.pedido_id;

  const lateral = document.createElement('nav');
  lateral.className = 'captura-pedidos';
  lateral.setAttribute('aria-label', 'Pedidos de esta lista');
  const titulo = document.createElement('h3');
  titulo.textContent = 'Pedidos de esta lista';
  lateral.append(titulo);
  deEstePaso.forEach(g => {
    const boton = document.createElement('button');
    boton.type = 'button';
    if (g.pedido_id === guardado.pedido_id) boton.setAttribute('aria-current', 'true');
    boton.onclick = () => IR_A_PASO('capturar', g.pedido_id);
    const fila = document.createElement('span');
    fila.className = 'fila-nombre';
    const nombre = document.createElement('b');
    nombre.textContent = g.nombre;
    const avance = document.createElement('span');
    const captura = g.captura || { capturados: 0, cuantos: 0 };
    avance.className = 'avance-corto' + (g.fue_enviado ? ' listo' : '');
    avance.textContent = g.fue_enviado ? 'Enviado' : captura.capturados + ' de ' + captura.cuantos;
    fila.append(nombre, avance);
    // Cuánto lleva tachado, en una barra: las dos cifras vienen del servidor
    // y aquí solo se dibujan. Lo enviado se ve lleno.
    const barra = document.createElement('span');
    barra.className = 'barra-avance' + (g.fue_enviado || captura.todo_capturado ? ' completa' : '');
    const relleno = document.createElement('span');
    relleno.style.width = (g.fue_enviado ? 100
      : captura.cuantos ? Math.round(captura.capturados * 100 / captura.cuantos) : 0) + '%';
    barra.append(relleno);
    boton.append(fila, barra);
    lateral.append(boton);
  });

  const trabajo = document.createElement('div');
  trabajo.className = 'captura-trabajo';
  const cabeza = document.createElement('div');
  cabeza.className = 'captura-cabeza';
  const texto = document.createElement('div');
  const h = document.createElement('h3');
  h.textContent = 'Captura en ' + guardado.nombre;
  const sub = document.createElement('p');
  sub.textContent = guardado.es_borrador
    ? 'Abre el portal en otra ventana, teclea cada renglón y táchalo aquí.'
    : 'Este pedido ya está en el portal: aquí queda lo que se capturó.';
  texto.append(h, sub);
  cabeza.append(texto);
  const archivo = enlaceCsv(guardado, 'Descargar CSV');
  if (archivo) cabeza.append(archivo);
  trabajo.append(cabeza);

  if (guardado.captura && guardado.captura.cuantos) trabajo.append(pintarCaptura(guardado, alTachar));

  // EL PIE: cuánto va, el botón de enviar y qué significa enviar.
  const pie = document.createElement('div');
  pie.className = 'captura-pie';
  const fila = document.createElement('div');
  fila.className = 'fila';
  const avance = document.createElement('span');
  const captura = guardado.captura;
  avance.className = 'avance' + (captura && captura.todo_capturado ? ' completa' : '');
  // La frase trae "faltan N" dentro (casilla 2) y viene hecha del servidor.
  avance.textContent = guardado.fue_enviado
    ? 'Pedido a ' + guardado.nombre + ' enviado'
    : (captura ? captura.frase : '');
  fila.append(avance);

  if (guardado.es_borrador) {
    // EL BOTÓN, CON EL TOTAL DENTRO (ticket 21): el total en pesos se ve ANTES
    // de enviar, y el sitio donde de verdad se ve es la etiqueta del botón que
    // se va a apretar. Cuando no se puede saber, dice eso — nunca "$0.00".
    // "Ya está en el portal" es lo que el botón firma: Continental no le manda
    // nada a nadie (ADR 0009).
    const boton = botonDeAccion(
      'Ya está en el portal — Enviar '
        + (guardado.hay_total ? '$' + guardado.total_sin_iva : '(total sin saber)'),
      (b) => alEnviar(guardado.pedido_id, guardado.nombre, b), 'llena grande');
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
    if (captura && captura.todo_capturado) boton.classList.add('listo');
    fila.append(boton);
  } else if (guardado.fue_enviado && guardado.enviado_en) {
    fila.append(insignia('Enviado · ' + horaEnPalabras(guardado.enviado_en), 'verde'));
  }
  pie.append(fila);

  if (guardado.es_borrador && guardado.motivo_para_no_enviar) {
    const porque = document.createElement('span');
    porque.className = 'marca';
    porque.textContent = guardado.motivo_para_no_enviar + '.';
    pie.append(porque);
  }
  // LLEVA A ENVIAR, SIN OBLIGAR (casilla 5). La frase viene hecha: con todo
  // tachado dice que el siguiente paso es enviar; a medias, que tachar no es
  // requisito. `null` cuando el botón está apagado por otra razón.
  if (guardado.es_borrador && captura && captura.invitacion) {
    const invitacion = document.createElement('p');
    invitacion.className = 'invitacion' + (captura.todo_capturado ? ' lista' : '');
    invitacion.textContent = captura.invitacion + '.';
    pie.append(invitacion);
  }
  // QUÉ SIGNIFICA ENVIAR, o quién lo capturó: la frase del servidor.
  const envio = document.createElement('p');
  envio.className = 'envio' + (guardado.fue_enviado ? ' hecho' : '');
  envio.textContent = guardado.frase_del_envio
    + (guardado.fue_enviado && guardado.enviado_en
       ? ' Fue ' + instanteEnPalabras(guardado.enviado_en)
       : '');
  pie.append(envio);
  trabajo.append(pie);

  caja.append(lateral, trabajo);
};

// Los descartados, aparte. El bloque se esconde entero cuando no hay ninguno:
// un "0 descartados" permanente es ruido en una pantalla que ya tiene dos
// avisos y un interruptor.
//
// `cuantos` viene del SERVIDOR y no de `renglones.length`, aunque hoy valgan
// lo mismo: es el número que el ADR 0002 va a mirar después de un mes, y un
// conteo que el navegador lleve a mano se separa de la verdad en cuanto hay
// dos pestañas abiertas en el mostrador.
const pintarDescartados = (renglones, cuantos, alDevolver) => {
  const caja = document.getElementById('descartados');
  document.getElementById('descartados-resumen').textContent =
    plural(cuantos, 'renglón descartado', 'renglones descartados') +
    ' de esta lista. Queda guardado quién y cuándo.';
  document.getElementById('descartados-lista').replaceChildren(
    ...renglones.map(r => renglonDescartado(r, alDevolver)));
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

// ------------------------------------------- las sesiones de los portales

// Viven FUERA de `cargarPedido` desde el 2026-09-28: la pestaña de Buscar
// ofrece los mismos dos botones cuando un portal le contesta que la sesión
// caducó. Son las mismas dos funciones y el mismo candado del servidor (ADR
// 0018: un portal esperando a la vez); lo único que cambia es la nota donde
// se escribe el resultado, `idNota`. Y la pestaña de Sesiones pasa
// `alTerminar` para volver a pintar sus tarjetas cuando el paso salió bien.

// ABRIR LA SESIÓN DE UN PROVEEDOR, en dos pasos y sin salir de aquí
// (ticket 19, tercera casilla).
//
// **Continental no abre el navegador y no podría** (regla 1 de CLAUDE.md):
// se lo pide a Doyle por HTTP, y Doyle lo abre en la máquina donde Doyle
// corre. Lo que esta pantalla evita es tener que ir a OTRA aplicación a
// disparar los dos pasos; lo que no puede evitar es que alguien tenga que
// teclear la contraseña en esa ventana, que es de lo que se trata.
async function abrirSesion(sesion, boton, idNota = 'pedido-accion', alTerminar = null) {
  boton.disabled = true;
  nota(idNota, '');

  const respuesta = await respuestaDe(fetch('/api/sesion/' + sesion.proveedor + '/abrir',
                                   { method: 'POST' }), 'al_guardar');

  boton.disabled = false;
  if (!respuesta.ok) {
    notaDeFalla(idNota, respuesta);
    return;
  }
  // LO QUE FALTA, DICHO, y por eso no se escribe "listo": lo que hay es una
  // ventana esperando. Un botón que contesta "listo" sobre una sesión que
  // sigue caducada es la falla silenciosa que la regla 4 prohíbe.
  const texto = respuesta.detalle + ' ' + respuesta.siguiente;

  // SIN VISOR CONFIGURADO no se inventa a dónde mandar a nadie. El texto
  // que arma el servidor ya dice qué falta en el YAML.
  if (!respuesta.visor) {
    nota(idNota, texto, 'aviso');
    if (alTerminar) alTerminar();
    return;
  }

  // EL POPUP, y el enlace detrás como seguro. `window.open` desde el
  // manejador de un clic es gesto de usuario legítimo, así que ningún
  // bloqueador razonable lo estorba; si aun así devuelve null —bloqueado, o
  // un navegador endurecido—, el enlace sigue ahí y la persona llega igual.
  //
  // Ventana aparte y no un iframe, a propósito: el visor vive en otro
  // origen y detrás de Cloudflare Access, que manda encabezados que impiden
  // embeberlo, y noVNC necesita el teclado en exclusiva —dentro de un
  // iframe se lo pelea con esta página, que es justo donde una contraseña
  // se escribe a medias en el lugar equivocado.
  //
  // El nombre de ventana es fijo: darle otra vez al botón reusa la misma
  // pestaña del visor en vez de sembrar copias.
  const ventana = window.open(respuesta.visor, 'visor-doyle');
  notaConEnlace(
    idNota,
    ventana ? texto : texto + ' El navegador bloqueó la ventana del visor.',
    respuesta.visor,
    ventana ? 'Volver a abrir el visor' : 'Abrir el visor',
    'aviso');
  if (alTerminar) alTerminar();
}

async function confirmarSesion(sesion, boton, idNota = 'pedido-accion', alTerminar = null) {
  boton.disabled = true;
  nota(idNota, '');

  const respuesta = await respuestaDe(fetch('/api/sesion/' + sesion.proveedor + '/confirmar',
                                   { method: 'POST' }), 'al_guardar');

  boton.disabled = false;
  if (!respuesta.ok) {
    notaDeFalla(idNota, respuesta);
    return;
  }
  // El aviso honesto de Doyle —"la página seguía viéndose como un login"— se
  // escribe en ámbar y no en verde: es la diferencia entre "ya está" y
  // "vuelve a intentarlo".
  nota(idNota, respuesta.detalle,
    respuesta.todavia_parece_login ? 'aviso' : '');
  if (alTerminar) alTerminar();
}

// ------------------------------------------------------------- las pestañas

// DOS PESTAÑAS, Pedido y Buscar (2026-09-28), con los nombres del glosario.
// La que se ve va en la URL (`#buscar`): recargar deja a la persona donde
// estaba, y un enlace puede mandar directo a Buscar. `replaceState` y no
// `location.hash =`: cambiar de pestaña no es navegar, y la flecha de "atrás"
// no debe ponerse a recorrer pestañas.
// Desde el diseño del 2026-09-30 son seis y van en la barra lateral: la lista
// del día y lo que viene en camino (el grupo "Pedido"), las tres de Doyle, y
// el estado. `#pedido` sigue siendo la lista del día: un enlace viejo no se
// rompe.
const PESTANAS = ['pedido', 'camino', 'buscar', 'vigilancia', 'sesiones', 'estado'];

// Un nombre que no es de ninguna pestaña —un `#loquesea` pegado a mano— cae
// en el pedido, que es la pantalla de siempre: nunca una página en blanco.
const mostrarPestana = (nombre, enfocar) => {
  const elegida = PESTANAS.includes(nombre) ? nombre : 'pedido';
  PESTANAS.forEach(p => {
    const activa = p === elegida;
    const boton = document.getElementById('pestana-' + p);
    boton.setAttribute('aria-selected', activa ? 'true' : 'false');
    boton.tabIndex = activa ? 0 : -1;
    document.getElementById('panel-' + p).hidden = !activa;
  });
  if (enfocar) document.getElementById('pestana-' + elegida).focus();
  // Las sesiones se leen al abrir su pestaña y no al cargar la página: son
  // una pregunta a Doyle que solo hace falta cuando alguien las va a mirar.
  if (elegida === 'sesiones') cargarSesiones();
  return elegida;
};

const iniciarPestanas = () => {
  PESTANAS.forEach((p, i) => {
    const boton = document.getElementById('pestana-' + p);
    boton.onclick = () => {
      mostrarPestana(p);
      history.replaceState(null, '', '#' + p);
      if (p === 'buscar') document.getElementById('buscar-termino').focus();
    };
    // Las flechas pasan de una pestaña a otra, como en cualquier lista de
    // pestañas: con el teclado se llega a la que no está a la vista sin
    // recorrer la página entera con Tab (la de fuera tiene `tabindex=-1`).
    // Arriba y abajo porque ahora van en vertical; izquierda y derecha
    // porque en el teléfono vuelven a ir en fila.
    boton.onkeydown = (e) => {
      const adelante = e.key === 'ArrowDown' || e.key === 'ArrowRight';
      if (!adelante && e.key !== 'ArrowUp' && e.key !== 'ArrowLeft') return;
      e.preventDefault();
      const paso = adelante ? 1 : PESTANAS.length - 1;
      const otra = PESTANAS[(i + paso) % PESTANAS.length];
      mostrarPestana(otra, true);
      history.replaceState(null, '', '#' + otra);
    };
  });
  // Un cambio de `#` sin recargar —un enlace a `#buscar`, o la URL editada a
  // mano— no vuelve a correr la carga: sin esto la dirección diría Buscar con
  // el pedido a la vista. Lo cazó el recorrido del navegador (2026-09-28).
  // `replaceState` no dispara este evento, así que los clics no pasan dos veces.
  window.addEventListener('hashchange', () => mostrarPestana(location.hash.slice(1)));
  mostrarPestana(location.hash.slice(1));
};

// ------------------------------------------------------------------ Buscar

// LA PESTAÑA QUE DOYLE TENÍA (2026-09-28). Se pide la búsqueda y se pregunta
// cómo va cada `sondeo_ms`, hasta que todos los portales terminan o pasa
// `tope_segundos`. Los dos números y la frase del tope llegan del servidor
// (`busqueda.py`), igual que cada frase de las tarjetas: aquí solo se pinta.
//
// Una búsqueda nueva deja huérfana a la anterior: `BUSQUEDA_ACTUAL` sube y el
// sondeo viejo lo ve y se detiene. Sin esto, dos sondeos pintarían las mismas
// tarjetas con resultados de dos términos distintos, alternándose.
let BUSQUEDA_ACTUAL = 0;

const esperar = (ms) => new Promise(listo => setTimeout(listo, ms));

// Un resultado de un portal. Las cifras llegan dichas —"Compra $86.05",
// "Existencia: NO DISPONIBLE"— y se juntan con un punto medio; ni un número
// se lee ni se convierte aquí. La clave es un botón que la copia, el mismo de
// la captura (ticket 22): es lo que se pega en el portal.
const filaDeResultado = (f) => {
  const li = document.createElement('li');
  if (f.sin_existencia) li.className = 'agotado';
  const descripcion = document.createElement('span');
  descripcion.className = 'descripcion';
  descripcion.textContent = f.descripcion;
  const clave = document.createElement('button');
  clave.type = 'button';
  clave.className = 'clave';
  clave.textContent = f.clave;
  clave.title = 'Copiar el código';
  clave.onclick = () => copiarClave(f.clave, clave);
  const cifras = document.createElement('span');
  cifras.className = 'cifras';
  cifras.textContent = f.cifras.join(' · ');
  li.append(descripcion, clave, cifras);
  if (f.advertencia) {
    const aviso = document.createElement('span');
    aviso.className = 'advertencia';
    aviso.textContent = f.advertencia;
    li.append(aviso);
  }
  // Lo nuestro se dice cuando se sabe; su ausencia NO se escribe como "no es
  // nuestro": QuePharma y VICMA muestran código interno y casi nunca empatan.
  if (f.nuestro) {
    const nuestro = document.createElement('span');
    nuestro.className = 'nuestro';
    nuestro.textContent = f.nuestro.frase;
    li.append(nuestro);
  }
  return li;
};

const tarjetaDePortal = (p) => {
  const tarjeta = document.createElement('article');
  tarjeta.className = 'portal' + (p.terminado ? '' : ' esperando') + (p.motivo ? ' sin-dato' : '');
  const titulo = document.createElement('h3');
  const estado = document.createElement('span');
  estado.className = 'estado-portal';
  estado.textContent = p.etiqueta;
  titulo.append(p.nombre, ' ', estado);
  tarjeta.append(titulo);

  if (p.que_paso) {
    const que = document.createElement('p');
    que.className = 'que-paso';
    que.textContent = p.que_paso;
    if (p.detalle) {
      const dijo = document.createElement('span');
      dijo.className = 'detalle';
      dijo.textContent = ' Doyle dijo: ' + p.detalle;
      que.append(dijo);
    }
    tarjeta.append(que);
  }
  // LA SESIÓN CADUCADA, con los mismos dos botones de la lista (ADR 0018).
  // Sale de un portal que mandó al login, nunca del `guardada` de Doyle.
  if (p.sesion_caducada) {
    const fila = document.createElement('div');
    fila.className = 'fila';
    fila.append(
      botonDeAccion('Abrir sesión', (b) => abrirSesion(p, b, 'buscar-accion'), 'tenida'),
      botonDeAccion('Ya entré', (b) => confirmarSesion(p, b, 'buscar-accion')));
    tarjeta.append(fila);
  }
  if (p.filas && p.filas.length) {
    const lista = document.createElement('ul');
    lista.className = 'resultados';
    lista.append(...p.filas.map(filaDeResultado));
    tarjeta.append(lista);
  }
  if (p.frase_del_total) {
    const total = document.createElement('p');
    total.className = 'detalle';
    total.textContent = p.frase_del_total;
    tarjeta.append(total);
  }
  return tarjeta;
};

const pintarBusqueda = (datos) => {
  nota('buscar-frase', datos.frase || '');
  nota('buscar-nuestro', datos.lo_buscado ? datos.lo_buscado.frase : '');
  // Sin catálogo los resultados se ven igual, y se dice que no se sabe qué es
  // nuestro: que ninguna fila lo diga no puede leerse como "nada es nuestro".
  if (datos.catalogo_sin_leer) notaDeFalla('buscar-catalogo', datos.catalogo_sin_leer);
  else nota('buscar-catalogo', '');
  const caja = document.getElementById('buscar-resultados');
  caja.replaceChildren(...(datos.proveedores || []).map(tarjetaDePortal));
  caja.hidden = false;
};

const buscar = async () => {
  const esta = ++BUSQUEDA_ACTUAL;
  const boton = document.getElementById('buscar-boton');
  nota('buscar-falla', '');
  nota('buscar-accion', '');
  boton.disabled = true;

  // El término va tal cual lo escribió la persona: limpiarlo y decidir si se
  // puede buscar es del servidor, que contesta con el motivo y qué hacer.
  const acuse = await respuestaDe(fetch('/api/buscar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ termino: document.getElementById('buscar-termino').value }),
  }));
  boton.disabled = false;
  if (esta !== BUSQUEDA_ACTUAL) return;
  if (!acuse.ok) {
    notaDeFalla('buscar-falla', acuse);
    return;
  }
  pintarBusqueda(acuse);

  const hasta = Date.now() + acuse.tope_segundos * 1000;
  for (;;) {
    await esperar(acuse.sondeo_ms);
    if (esta !== BUSQUEDA_ACTUAL) return;
    const datos = await respuestaDe(fetch('/api/buscar/' + encodeURIComponent(acuse.job_id)));
    if (esta !== BUSQUEDA_ACTUAL) return;
    // Una falla deja las tarjetas como estaban: lo que ya contestó sigue
    // siendo cierto, y lo que no, la nota lo dice con su qué hacer.
    if (!datos.ok) {
      notaDeFalla('buscar-falla', datos);
      return;
    }
    pintarBusqueda(datos);
    if (datos.terminada) return;
    if (Date.now() > hasta) {
      nota('buscar-falla', acuse.frase_al_tope, 'aviso');
      return;
    }
  }
};

const iniciarBuscar = () => {
  document.getElementById('buscar-forma').onsubmit = (e) => {
    e.preventDefault();
    buscar();
  };
};

// Desde otra pestaña: pone el término en el campo y busca. Lo usa Vigilancia,
// porque Doyle solo guarda SI ya hay y no EN CUÁL ni a cómo: eso lo contesta
// una búsqueda, con los cuatro portales a la vista.
const buscarDesdeOtraPestana = (termino) => {
  document.getElementById('buscar-termino').value = termino;
  mostrarPestana('buscar');
  history.replaceState(null, '', '#buscar');
  buscar();
};

// -------------------------------------------------------------- Vigilancia

// LA PESTAÑA DE VIGILANCIA DE DOYLE (su ADR 0007), dibujada aquí. La lista y
// el reloj de las 9:30 y 19:30 son de Doyle; lo que se ve llega hecho del
// servidor (`vigilancia.py`). Se carga también al abrir la página, aunque
// nadie abra la pestaña: el aviso de "ya hay" va arriba de las pestañas y es
// la mitad del punto de vigilar.
//
// «Revisar ahora» tarda minutos. El servidor contesta de inmediato y dice si
// sigue `en_curso`; mientras siga, esto vuelve a preguntar cada `sondeo_ms`
// —número del servidor—, con UN solo temporizador vivo a la vez.
let SONDEO_DE_LA_VIGILANCIA = null;

const pintarAvisosDeVigilancia = (frase) => {
  const p = document.getElementById('avisos-vigilancia');
  if (!frase) {
    p.hidden = true;
    p.replaceChildren();
    return;
  }
  const ver = botonDeAccion('Ver', () => {
    mostrarPestana('vigilancia');
    history.replaceState(null, '', '#vigilancia');
  }, 'plana');
  p.replaceChildren(frase + ' ', ver);
  p.hidden = false;
};

// Las casillas se pintan UNA vez: repintarlas en cada sondeo desmarcaría lo
// que la persona está eligiendo mientras Doyle revisa.
const pintarCasillas = (proveedores) => {
  const caja = document.getElementById('vigilancia-proveedores');
  if (caja.querySelector('input') || !proveedores) return;
  proveedores.forEach(p => {
    const etiqueta = document.createElement('label');
    const casilla = document.createElement('input');
    casilla.type = 'checkbox';
    casilla.value = p.proveedor;
    casilla.checked = true;
    etiqueta.append(casilla, ' ' + p.nombre);
    caja.append(etiqueta);
  });
};

const pintarRevision = (revision) => {
  const boton = document.getElementById('vigilancia-revisar');
  const detalle = document.getElementById('vigilancia-revision');
  boton.disabled = !!(revision && revision.en_curso);
  if (!revision) {
    detalle.textContent = '';
    return;
  }
  detalle.textContent = revision.ok === false ? fallaEnUnaLinea(revision) : revision.frase;
};

// Lo que pasa después de cualquier botón de la lista: si falló se dice, y si
// no, se vuelve a leer la lista entera. Nada se deduce aquí de lo que se
// apretó: la lista es de Doyle y lo que dice es lo que Doyle contestó.
const trasTocarLaVigilancia = async (peticion, boton) => {
  if (boton) boton.disabled = true;
  const datos = await peticion;
  if (boton) boton.disabled = false;
  if (!datos.ok) {
    notaDeFalla('vigilancia-falla', datos);
    return false;
  }
  await cargarVigilancia();
  return true;
};

const vigilado = (a) => {
  const li = document.createElement('li');
  if (a.disponible) li.className = 'disponible';
  const termino = document.createElement('b');
  termino.className = 'termino';
  termino.textContent = a.termino;
  const estado = document.createElement('span');
  estado.className = 'estado-vigilado';
  estado.textContent = a.etiqueta;
  const frase = document.createElement('span');
  frase.className = 'detalle';
  frase.textContent = a.frase;
  li.append(termino, ' ', estado, frase);
  if (a.error) {
    const error = document.createElement('span');
    error.className = 'error-vigilado';
    error.textContent = a.error;
    li.append(error);
  }
  const botones = document.createElement('div');
  botones.className = 'fila';
  if (a.aviso_pendiente) {
    botones.append(botonDeAccion('Ya lo vi', (b) => trasTocarLaVigilancia(
      respuestaDe(fetch('/api/vigilancia/' + a.articulo_id + '/visto', { method: 'POST' }), 'al_guardar'), b), 'tenida'));
  }
  botones.append(
    botonDeAccion('Buscarlo', () => buscarDesdeOtraPestana(a.termino), a.disponible ? 'tenida' : ''),
    botonDeAccion('Quitar', (b) => trasTocarLaVigilancia(
      respuestaDe(fetch('/api/vigilancia/' + a.articulo_id, { method: 'DELETE' }), 'al_guardar'), b), 'plana'));
  li.append(botones);
  return li;
};

const cargarVigilancia = async () => {
  clearTimeout(SONDEO_DE_LA_VIGILANCIA);
  const datos = await respuestaDe(fetch('/api/vigilancia'));
  pintarRevision(datos.revision);
  if (datos.revision && datos.revision.en_curso) {
    SONDEO_DE_LA_VIGILANCIA = setTimeout(cargarVigilancia, datos.revision.sondeo_ms);
  }
  if (!datos.ok) {
    notaDeFalla('vigilancia-falla', datos);
    pintarAvisosDeVigilancia(null);
    return;
  }
  nota('vigilancia-falla', '');
  pintarCasillas(datos.proveedores);
  nota('vigilancia-vacia', datos.frase || '');
  document.getElementById('vigilancia-lista').replaceChildren(...datos.articulos.map(vigilado));
  pintarAvisosDeVigilancia(datos.avisos);
  // La barra lateral cuenta los avisos que nadie ha visto todavía.
  pintarCuenta('vigilancia', datos.articulos.filter(a => a.aviso_pendiente).length, 'verde');
};

const iniciarVigilancia = () => {
  const campo = document.getElementById('vigilancia-termino');
  document.getElementById('vigilancia-forma').onsubmit = async (e) => {
    e.preventDefault();
    const casillas = [...document.querySelectorAll('#vigilancia-proveedores input')];
    const marcadas = casillas.filter(c => c.checked).map(c => c.value);
    // Todas marcadas se manda vacío, que para Doyle es "los cuatro": así la
    // frase del renglón dice "en los cuatro proveedores" y no la lista entera.
    const proveedores = marcadas.length === casillas.length ? [] : marcadas;
    const listo = await trasTocarLaVigilancia(respuestaDe(fetch('/api/vigilancia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ termino: campo.value, proveedores }),
    }), 'al_guardar'));
    if (listo) campo.value = '';
  };
  const revisar = document.getElementById('vigilancia-revisar');
  revisar.onclick = () => trasTocarLaVigilancia(
    respuestaDe(fetch('/api/vigilancia/revisar', { method: 'POST' }), 'al_guardar'), revisar);
  cargarVigilancia();
};

// ---------------------------------------------------------------- Sesiones

// EL «INICIO» DE DOYLE (2026-09-28), con una diferencia a propósito: la
// etiqueta de cada tarjeta NO es el `guardada` de Doyle —que sobrevive a que
// el portal caduque la sesión—, sino lo que vieron las consultas guardadas:
// caducada, sirvió o sin probar. Todo llega dicho del servidor (`sesiones.py`),
// incluido si el botón de abrir se puede apretar (un portal a la vez, ADR 0018).

async function cancelarSesion(sesion, boton, idNota, alTerminar) {
  boton.disabled = true;
  nota(idNota, '');
  const respuesta = await respuestaDe(fetch('/api/sesion/' + sesion.proveedor + '/cancelar',
                                   { method: 'POST' }), 'al_guardar');
  boton.disabled = false;
  if (!respuesta.ok) {
    notaDeFalla(idNota, respuesta);
    return;
  }
  nota(idNota, respuesta.detalle);
  if (alTerminar) alTerminar();
}

// PROBAR UNA SESIÓN (ADR 0024, decisión 3): el botón busca el término de prueba
// en ese portal y espera a que termine —unos segundos—. El servidor dice si la
// sesión `sirvió` (pasó del login) o está `caducada`, lo guarda, y aquí solo se
// pinta lo que contestó. Al terminar se avisa a quien pintó (`alTerminar`), que
// vuelve a leer las tarjetas: la etiqueta nueva sale sin recargar la página.
//
// **Si la prueba no terminó** —Doyle no responde, el portal no contestó— no se
// guardó nada y las tarjetas no cambian; el error se queda escrito en su nota,
// fijo, y no en el aviso pasajero (enmienda del 2026-10-05 al ADR 0023). Va con
// `al_guardar` porque, si la respuesta se pierde, la prueba pudo haberse
// guardado: se manda a mirar las tarjetas.
//
// UNA PRUEBA A LA VEZ (ADR 0024, decisión 8; ticket 03). El candado es del
// servidor —vale entre computadoras—: si otra prueba corre, contesta 409 con
// cuál, y esa frase se pinta tal cual. Aquí solo se adelanta lo que ESTA pestaña
// ya sabe sin preguntar: que acaba de lanzar una. Mientras `probandoAqui`, los
// botones de probar de los dos sitios se apagan y el aviso fijo del HTML
// (`data-texto-local`) dice por qué, sin esperar a que el servidor lo diga. Al
// terminar —bien o mal— se vuelve a leer: el servidor es quien dice qué botones
// se encienden, y un 409 puede traer una prueba ajena que hay que mostrar.
let probandoAqui = false;

const avisoDeLaPruebaLocal = () => {
  SITIOS_DE_SESIONES.forEach((ids) => {
    const aviso = document.getElementById(ids.corriendo);
    if (aviso && probandoAqui) nota(ids.corriendo, aviso.dataset.textoLocal);
  });
  // Los de cada tarjeta y los dos «Probar todas» (uno por sitio).
  document.querySelectorAll('button[data-probar], button[data-probar-todas]')
    .forEach((b) => { b.disabled = true; });
};

// `proveedores` lleva los portales a probar; **vacía quiere decir los cuatro**
// (el servidor los reparte en una sola búsqueda, ADR 0019, y salta al que espera
// en el visor). La lista vacía es lo que manda «Probar todas»: el cliente no
// enumera los portales.
async function probarSesiones(proveedores, boton, idNota, alTerminar) {
  probandoAqui = true;
  avisoDeLaPruebaLocal();
  boton.textContent = 'Probando…';
  nota(idNota, '');

  const respuesta = await respuestaDe(fetch('/api/sesiones/probar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proveedores: proveedores }),
  }), 'al_guardar');

  probandoAqui = false;
  if (!respuesta.ok) {
    notaDeFalla(idNota, respuesta);
  } else {
    // Si algún portal no terminó o se saltó, la frase del servidor dice cuál y
    // por qué, y va en ámbar.
    nota(idNota, respuesta.detalle,
      respuesta.algunos_sin_probar || respuesta.saltados.length ? 'aviso' : '');
  }
  if (alTerminar) alTerminar();
}

const probarSesion = (sesion, boton, idNota, alTerminar) =>
  probarSesiones([sesion.proveedor], boton, idNota, alTerminar);

// UN «SITIO» ES DONDE SE PINTAN LAS SESIONES: sus tarjetas y las dos notas que
// las acompañan (lo que dijo el último paso, y la falla de leerlas). Hay dos
// y son espejo, a propósito (ADR 0024): la pestaña Sesiones y la ventana que
// sale al abrir. Cada una con SUS notas, porque la de la pestaña queda
// escondida detrás de la ventana y un paso dado desde ahí tiene que decir su
// resultado donde se ve. Van los ids; `cargarSesiones` los resuelve.
const SITIOS_DE_SESIONES = [
  { caja: 'sesiones-tarjetas', accion: 'sesiones-accion', falla: 'sesiones-falla',
    corriendo: 'sesiones-corriendo', todas: 'sesiones-probar-todas' },
  { caja: 'ventana-sesiones-tarjetas', accion: 'ventana-sesiones-accion',
    falla: 'ventana-sesiones-falla', corriendo: 'ventana-sesiones-corriendo',
    todas: 'ventana-sesiones-probar-todas' },
];

// La tarjeta de UN portal. `alTerminar` es a quien se le avisa cuando un paso
// salió bien (abrir, «Ya entré», cancelar): quien pinta decide qué se vuelve a
// leer, y esta función no sabe cuál de los dos sitios la llamó.
const tarjetaDeSesion = (s, sitio, alTerminar) => {
  const tarjeta = document.createElement('article');
  // Tres aspectos y no tres tonos: la que espera a que alguien entre lleva un
  // anillo; la que hay que abrir, ámbar; la que sirve, verde. La palabra de la
  // insignia es la que lo dice.
  tarjeta.className = 'portal' + (s.se_puede_confirmar ? ' esperando-sesion'
    : s.hay_que_abrirla ? ' sin-dato' : ' sirve');
  const titulo = document.createElement('h3');
  const estado = document.createElement('span');
  estado.className = 'estado-portal';
  estado.textContent = s.etiqueta;
  titulo.append(s.nombre, ' ', estado);
  const frase = document.createElement('p');
  frase.className = 'que-paso';
  frase.textContent = s.frase;
  const botones = document.createElement('div');
  botones.className = 'fila';
  if (s.se_puede_confirmar) {
    botones.append(
      botonDeAccion('Ya entré', (b) => confirmarSesion(s, b, sitio.accion, alTerminar), 'llena'),
      botonDeAccion('Cancelar', (b) => cancelarSesion(s, b, sitio.accion, alTerminar)));
  } else {
    const abrir = botonDeAccion(s.rotulo_de_abrir,
      (b) => abrirSesion(s, b, sitio.accion, alTerminar), s.hay_que_abrirla ? 'tenida' : '');
    abrir.disabled = !s.se_puede_abrir;
    // «Probar» sale en cada tarjeta menos en la que espera en el visor (esa
    // ofrece «Ya entré» y «Cancelar», arriba). El servidor dice si se puede.
    const probar = botonDeAccion('Probar',
      (b) => probarSesion(s, b, sitio.accion, alTerminar));
    probar.dataset.probar = '1';
    // Apagado si el servidor dice que no (el del visor, una prueba corriendo) o
    // si esta pestaña ya lanzó una y todavía no vuelve.
    probar.disabled = !s.se_puede_probar || probandoAqui;
    if (s.por_que_no_se_prueba) probar.title = s.por_que_no_se_prueba;
    botones.append(abrir, probar);
  }
  tarjeta.append(titulo, frase, botones);
  if (s.por_que_no_se_abre) {
    const porQue = document.createElement('p');
    porQue.className = 'detalle';
    porQue.textContent = s.por_que_no_se_abre;
    tarjeta.append(porQue);
  }
  // El motivo de un «Probar» apagado se ve en la tarjeta, no solo en el título:
  // un botón apagado sin razón se lee como pantalla trabada.
  if (s.por_que_no_se_prueba) {
    const porQueNo = document.createElement('p');
    porQueNo.className = 'detalle';
    porQueNo.textContent = s.por_que_no_se_prueba;
    tarjeta.append(porQueNo);
  }
  return tarjeta;
};

// LA ÚNICA FUNCIÓN QUE PINTA LAS TARJETAS (ticket 05). La pestaña y la ventana
// pasan por aquí: dos copias se separan solas, y el dueño pidió una imagen
// espejo. Si Doyle no contesta se pinta el hueco con su motivo y el contenedor
// queda vacío —nunca tarjetas vacías—, también en la ventana.
const pintarSesiones = (sitio, datos, alTerminar) => {
  // «Probar todas» arriba de las tarjetas: el botón y su rótulo son texto fijo
  // del HTML; aquí solo se enciende, se apaga y se dice por qué. Sin sesiones
  // que leer no hay nada que probar, y queda apagado.
  const todas = document.getElementById(sitio.todas);
  const motivoDeTodas = document.getElementById(sitio.todas + '-motivo');
  todas.textContent = todas.dataset.rotulo;
  todas.onclick = () => probarSesiones([], todas, sitio.accion, alTerminar);
  todas.disabled = !datos.ok || !datos.probar_todas.se_puede || probandoAqui;
  motivoDeTodas.textContent = datos.ok && datos.probar_todas.por_que_no
    ? datos.probar_todas.por_que_no : '';
  motivoDeTodas.hidden = !motivoDeTodas.textContent;
  if (!datos.ok) {
    notaDeFalla(sitio.falla, datos);
    sitio.caja.replaceChildren();
    return;
  }
  if (datos.evidencia_sin_leer) notaDeFalla(sitio.falla, datos.evidencia_sin_leer);
  else nota(sitio.falla, '');
  // Que hay una prueba corriendo lo dice el servidor (puede ser de otra
  // computadora); si es de esta pestaña y todavía no se enteró, lo dice el HTML.
  const aviso = document.getElementById(sitio.corriendo);
  nota(sitio.corriendo, datos.prueba_en_curso ? datos.prueba_en_curso.detalle
    : probandoAqui ? aviso.dataset.textoLocal : '');
  sitio.caja.replaceChildren(...datos.sesiones.map((s) => tarjetaDeSesion(s, sitio, alTerminar)));
};

// Lee las sesiones una vez y repinta los dos sitios: lo que se hizo en la
// ventana se ve al abrir la pestaña, y al revés, sin una segunda pregunta a Doyle.
const cargarSesiones = async () => {
  const datos = await respuestaDe(fetch('/api/sesiones'));
  SITIOS_DE_SESIONES.forEach((ids) => pintarSesiones(
    { ...ids, caja: document.getElementById(ids.caja) }, datos, cargarSesiones));
  if (datos.ok) {
    pintarCuenta('sesiones', datos.sesiones.filter(x => x.hay_que_abrirla).length, 'rojo');
  }
};

// ------------------------------------------- la ventana de las sesiones

// LA VENTANA FLOTANTE (ADR 0024, decisiones 1 y 2): lo primero que se ve al
// abrir Continental, y otra vez tras una hora sin un clic ni una tecla. Es un
// <dialog> modal —foco atrapado, Esc, anunciado como diálogo— pero se cierra
// con un clic: mirar la lista de ayer no necesita portales.
const UNA_HORA_SIN_USO_MS = 60 * 60 * 1000;

// La hora se cuenta AQUÍ, en memoria: cada computadora y cada pestaña cuentan
// por separado (ADR 0024). Un almacenamiento del navegador las mezclaría, y
// quien trabaja en la torre le quitaría la ventana a quien vuelve a la PC de
// la farmacia.
let TEMPORIZADOR_DE_REPOSO = null;
let FOCO_ANTES_DE_LA_VENTANA = null;

const reiniciarElReposo = () => {
  clearTimeout(TEMPORIZADOR_DE_REPOSO);
  TEMPORIZADOR_DE_REPOSO = setTimeout(alVencerElReposo, UNA_HORA_SIN_USO_MS);
};

const abrirLaVentanaDeSesiones = () => {
  const ventana = document.getElementById('ventana-sesiones');
  // Ya abierta, o encima de la confirmación de cerrar la lista: no se apilan
  // dos ventanas, y quien está confirmando algo no se interrumpe.
  if (ventana.open || document.getElementById('confirmar-cierre').open) return false;
  FOCO_ANTES_DE_LA_VENTANA = document.activeElement;
  ventana.showModal();
  // Se abre ya y se llena al llegar la respuesta: si Doyle no contesta, el
  // hueco con su motivo sale en la misma ventana.
  cargarSesiones();
  return true;
};

const cerrarLaVentanaDeSesiones = () => {
  const ventana = document.getElementById('ventana-sesiones');
  if (ventana.open) ventana.close();
};

// Vence la hora sin uso. Si no pudo abrirse —hay otra ventana—, vuelve a
// contar en vez de esperar al siguiente clic para intentarlo.
const alVencerElReposo = () => {
  if (!abrirLaVentanaDeSesiones()) reiniciarElReposo();
};

const iniciarLaVentanaDeSesiones = () => {
  const ventana = document.getElementById('ventana-sesiones');
  document.getElementById('ventana-sesiones-continuar').onclick = cerrarLaVentanaDeSesiones;
  // Esc la cierra a ELLA: el <dialog> ya lo hace por su cuenta, pero el Esc
  // del detalle del renglón escucha en `document` y se enteraría también.
  ventana.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Escape') return;
    evento.preventDefault();
    // Sin esto, la ventana ya cerrada dejaría pasar el Esc hasta `document`,
    // que lo vería como «no hay ventana» y cerraría también el detalle.
    evento.stopPropagation();
    cerrarLaVentanaDeSesiones();
  });
  // Se cierre como se cierre (botón, Esc), el foco vuelve a donde estaba.
  ventana.addEventListener('close', () => {
    const antes = FOCO_ANTES_DE_LA_VENTANA;
    FOCO_ANTES_DE_LA_VENTANA = null;
    if (antes && antes.isConnected && typeof antes.focus === 'function') antes.focus();
  });
  // Cuentan los clics y las teclas, en captura para que ningún
  // `stopPropagation` de la pantalla los esconda.
  ['click', 'keydown'].forEach((evento) => {
    document.addEventListener(evento, reiniciarElReposo, true);
  });
  reiniciarElReposo();
  abrirLaVentanaDeSesiones();
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
    // Con qué correo se firma, abajo de la barra lateral.
    document.getElementById('firma-correo').textContent = salud.quien || 'sin-identificar';
    document.getElementById('firma-lateral').hidden = false;
  } else {
    // Hasta el ticket 29 un 500 pintaba "Continental undefined" en verde.
    pintar('estado', [fila('Continental no contesta', false, salud.detalle)]);
  }

  const respuesta = await respuestaDe(fetch('/api/modulos'));
  if (Array.isArray(respuesta.modulos)) {
    pintar('modulos', respuesta.modulos.length
      ? respuesta.modulos.map(m => fila(m.nombre, m.ok, m.detalle || m.url))
      : [fila('Ninguno configurado', null)]);
    ESTADO_DE_LOS_MODULOS = { lista: respuesta.modulos };
  } else {
    pintar('modulos', [fila('No se pudo consultar', false, respuesta.detalle)]);
    ESTADO_DE_LOS_MODULOS = { falla: respuesta.detalle || 'No se pudo consultar a los módulos.' };
  }
  // La tarjeta de abajo de la barra lateral: si todo contesta.
  pintarEstadoLateral();
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

iniciarApariencia();
iniciarPestanas();
iniciarLaVistaDelDia();
iniciarBuscar();
iniciarVigilancia();
iniciarLaVentanaDeSesiones();
cargarPedido();
revisarDoyle();
cargar();
