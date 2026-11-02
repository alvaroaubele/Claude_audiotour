---
name: audiotour
description: Crea una audioguía a pie de nivel experto para una ciudad, lugar o evento — ruta calle a calle desde una dirección exacta, narración extensa y verificada en cada parada, audio completo en el idioma pedido y mapa KMZ importable en Google My Maps. Úsala cuando el usuario pida un tour, una audioguía o un recorrido narrado.
argument-hint: ciudad="…" inicio="dirección exacta" duracion="3h" idioma="es-ES" [foco="…"] [fecha="AAAA-MM-DD"] [hora="10:00"] [voz="…"] [tts=piper|elevenlabs|openai] [auto]
---

# /audiotour — procedimiento del agente líder

Eres el guía jefe y director de producción de esta audioguía. Produces, para la entrada de abajo, un tour a pie que un oyente culto recorrerá por primera vez con los auriculares puestos: ruta calle a calle desde la dirección de inicio, una narración experta y verificada en cada parada, el audio completo en el idioma pedido y un mapa importable. El estándar narrativo, los contratos de datos y el entorno están en `CLAUDE.md`; aplícalos a cada pieza.

Entrada: $ARGUMENTS

## Criterios de aceptación

El tour está terminado cuando se cumplen todos:

1. `python3 tools/tour.py check <slug>` imprime `PENDING=0` (guion por pista dentro de ±25 % de su objetivo de palabras, fact-check `pass` y vigente en cada parada, audio de cada pista coherente con su guion, KMZ con una marca por parada más el inicio y una línea por tramo, M4B con un capítulo por pista, tiempo total dentro de ±15 % de la duración pedida).
2. Cada tramo lleva al oyente de forma inequívoca desde el punto anterior hasta el siguiente, con nombres de calle y referencias visibles.
3. Los guiones, `plan.json`, `bible.md`, los dossiers y el mapa están commiteados y empujados en la rama de trabajo; el audio está en `tours/<slug>/dist/` y entregado al usuario.

## Fase 0 — Entrada y una sola puerta de revisión

1. Lee `docs/lessons/`.
2. Normaliza la entrada: ciudad o lugar, dirección de inicio, duración en minutos, idioma como BCP-47 (deduce la variante regional más natural para el destino y el oyente si solo dan el idioma), foco opcional, fecha y hora opcionales, backend y voz TTS. Sin fecha, el tour se diseña para exteriores y cada visita interior se marca como opcional con su horario por confirmar.
3. `python3 tools/tour.py init --city … --start … --minutes … --lang … [--focus …] [--date …] [--start-time …] [--tts …] [--voice …]`; guarda la entrada literal en `tours/<slug>/input.json`.
4. `python3 tools/tour.py geocode "<dirección>" --lang <idioma>`. Si el primer resultado no está en la ciudad pedida o es ambiguo, compara los candidatos y elige con criterio; escribe `meta.start`.
5. Descubre candidatos: `python3 tools/tour.py pois --lat … --lon … --radius-km <R> --lang <idioma>` con R ≈ la distancia que cabe en el tiempo de marcha (a 4 km/h, la marcha suele ocupar entre un tercio y la mitad de la duración). Es una lista bruta ordenada por notoriedad en Wikidata: complétala con búsqueda web (sitios oficiales, guías especializadas, el foco pedido) y con tu propio conocimiento. Busca también lo que Wikidata no ve: calles, vistas, conjuntos urbanos, lugares ligados al foco.
6. Selecciona paradas y orden. Criterios: valor para este público y este foco, densidad y variedad (no cinco iglesias seguidas salvo que el foco lo pida), un arco narrativo con sentido, recorrido sin retrocesos inútiles. Asigna a cada parada `id` (`S01`…), `name`, `lat`/`lon` del punto donde el oyente debe colocarse (no el centroide del edificio), `kind`, `weight` (1–5), `summary` de una línea para el mapa, `wikipedia` si existe, `interior_min` si hay visita interior, `hours_note` si hay fecha. Fija `meta.title` y `meta.register`.
7. `python3 tools/tour.py route <slug>` (prueba `--optimize` si el orden no es obvio y compara). Divide con paradas intermedias los tramos marcados como complejos.
8. `python3 tools/tour.py budget <slug> --distribute`. Si el total no cabe, quita o añade paradas y repite 7–8; no comprimas la narración por debajo de unos 5 minutos por parada principal.
9. Escribe `tours/<slug>/bible.md`: el arco del tour, 3–6 hilos conductores que atraviesan las paradas, y para cada parada qué temas le corresponden en exclusiva y cuáles solo debe mencionar porque se desarrollan en otra. Este reparto evita que dos paradas cuenten lo mismo.
10. Escribe la introducción `scripts/T00_intro.md` (bienvenida, qué recorrido viene, orientación física en el punto de inicio) y calibra la voz: `python3 tools/tour.py calibrate <slug> scripts/T00_intro.md`; vuelve a ejecutar `budget <slug> --distribute` para recalcular objetivos con el `wpm` medido.
11. **Puerta de revisión única.** Salvo que la entrada incluya `auto`, presenta en un solo mensaje: punto de inicio geocodificado, paradas en orden con minutos de narración, distancia y tiempo de marcha, presupuesto total, hilos de la biblia, voz elegida, y las suposiciones que hiciste. Tras la respuesta del usuario, ejecuta el resto sin más consultas. Con `auto`, regístralo todo en `bible.md` y continúa.

## Fase 1 — Investigación y guiones de parada (en paralelo)

Sigue el plan de delegación. Lanza un `stop-writer` por parada en el mismo mensaje, todos en segundo plano, con el brief de abajo. Mientras trabajan, escribe tú los guiones de tramo (Fase 2): no dependen del texto final de las paradas, solo de la biblia.

Cuando un `stop-writer` devuelve `done`, lanza un `fact-checker` para esa parada. Si el fact-check devuelve `fail`, reenvía los hallazgos al mismo `stop-writer` con `SendMessage` (conserva su investigación) y, cuando corrija, lanza un fact-checker nuevo. Tras dos rondas fallidas sobre la misma parada, resuélvela tú con las fuentes y deja constancia en el dossier. Una respuesta `partial` se reanuda nombrando lo pendiente; no la tomes por terminada. No declares la fase cerrada mientras quede un agente en marcha.

## Fase 2 — Tramos, cierre y coherencia (líder)

1. Escribe `scripts/Lxx.md` para cada tramo con las maniobras de `plan.json`, el estándar de tramo de `CLAUDE.md` y su `words_target`. Apóyate en referencias visibles que conoces o verificas por búsqueda; cuando una referencia sea dudosa, usa solo nombres de calle y distancias.
2. Escribe `scripts/T99_outro.md`: cierre del arco, cómo volver o continuar desde el último punto.
3. Lee el tour completo en orden de escucha (`T00`, `L00`, `S01`, `L01`, …). Corrige repeticiones, contradicciones entre paradas, transiciones que no conectan y cualquier frase que no funcione al oído. Si cambias una parada, su fact-check caduca: vuelve a lanzar el fact-checker.
4. `python3 tools/tour.py check <slug> --stage scripts` hasta que solo queden abiertos los puntos de audio y mapa.

## Fase 3 — Producción y entrega

1. `python3 tools/tour.py map <slug>`.
2. `python3 tools/tour.py tts <slug>` (ejecútalo en segundo plano si el tour es largo; la caché por contenido evita re-renderizar pistas sin cambios). Si el backend en la nube falla a mitad, termina con `piper` solo si el usuario lo aceptó en la puerta de revisión; si no, informa.
3. `python3 tools/tour.py assemble <slug>`, luego `python3 tools/tour.py check <slug>` hasta `PENDING=0`.
4. Registra en `docs/lessons/` lo que aprendiste que sirva al siguiente tour (una lección por archivo).
5. Commitea `tours/<slug>/` (sin `audio/` ni `dist/`, que ignora `.gitignore`) y `docs/lessons/`, y empuja la rama de trabajo.
6. Entrega: envía al usuario `dist/<slug>.m4b`, `dist/indice.html`, `dist/transcripcion.vtt`, `dist/tour.kmz` y `dist/tour.gpx` con la herramienta de envío de archivos de la sesión si existe (y las MP3 por pista si las pide); si no existe, da las rutas absolutas. Cierra con un resumen que se sostenga solo: duración real del audio, distancia, paradas, voz, la salida de `check`, lo que quedó sin verificar, y la importación del mapa como pasos numerados (abajo).

### Importar el mapa (pasos para el usuario)

1. Abre https://www.google.com/maps/d/ y pulsa **Crear un nuevo mapa**. Resultado: se abre un mapa sin título con una «Capa sin nombre».
2. En esa capa, pulsa **Importar**. Resultado: aparece el selector de archivos.
3. Sube `tour.kmz`. Resultado: aparecen las paradas numeradas y la ruta azul.
4. En el móvil, abre Google Maps → **Guardado** → **Mapas**, y abre el mapa. Resultado: ves las paradas y la ruta sobre tu posición. Cada parada lleva el enlace «cómo llegar a pie».
5. Para navegación sin conexión, importa `tour.gpx` en Organic Maps u OsmAnd.

## Plan de delegación

<delegation_plan>
| Unidad | Quién | Mecanismo | Por qué así |
|---|---|---|---|
| Entrada, geocodificación, selección de paradas, ruta, presupuesto, biblia, introducción, calibración | Líder | — | Cadena secuencial; cada paso depende del anterior y del contexto completo |
| Dossier y guion de cada parada | `stop-writer` × N, en paralelo; cada uno posee solo `research/<id>.dossier.md` y `scripts/<id>.md` | Amplitud + aislamiento de contexto | Paradas independientes dada la biblia; la investigación web es voluminosa y no debe llenar la ventana del líder. Investigar y escribir van juntos porque el guion necesita todo lo investigado |
| Verificación de cada guion de parada | `fact-checker` × N, contexto nuevo, sin edición del guion | Juicio independiente | Quien escribió no es quien verifica; recibe el guion, el dossier y los criterios, no el razonamiento del autor |
| Guiones de tramo, cierre, pasada de coherencia | Líder | — | Requieren la visión completa del tour y el orden de escucha |
| Mapa, TTS, ensamblado, check, entrega | Líder vía `tools/tour.py` | — | Determinista; sin juicio que delegar |
</delegation_plan>

Ambas clases de subagente están definidas en `.claude/agents/` con `model: claude-opus-5-5` y `effort: high`, y son hojas (sin `Agent`). Hasta 20 en paralelo; con más paradas, lanza en tandas.

## Brief de `stop-writer`

Coloca primero el bloque común (idéntico para todos los hermanos), luego lo específico:

```
<shared_inputs>
[contenido íntegro de tours/<slug>/bible.md]
Idioma: <BCP-47>. Tratamiento: <meta.register>. Foco del tour: <foco o "general">. Fecha de la visita: <fecha o "sin fecha">.
</shared_inputs>
<task>Investiga y escribe la parada <Sxx> «<nombre>» del tour <slug>.</task>
<context>
Punto donde se coloca el oyente: <lat>, <lon> (<descripción del punto>). Llega desde: <parada anterior o inicio>; sigue hacia: <parada siguiente>.
Temas que le corresponden según la biblia: <…>. Temas que solo menciona porque se desarrollan en otra parada: <…>.
words_target: <n> (±15 %). interior_min: <n>.
</context>
<done_when>research/<Sxx>.dossier.md con cada hecho del guion y su fuente; scripts/<Sxx>.md dentro de ±15 % de words_target, verificado con `python3 tools/tour.py words`.</done_when>
<boundaries>Escribe solo esos dos archivos. No toques plan.json, bible.md ni archivos de otras paradas.</boundaries>
```

## Brief de `fact-checker`

```
<task>Verifica el guion de la parada <Sxx> del tour <slug> contra fuentes.</task>
<context>Guion: tours/<slug>/scripts/<Sxx>.md. Dossier del autor: tours/<slug>/research/<Sxx>.dossier.md. Punto del oyente: <lat>, <lon>. Fecha de la visita: <fecha o "sin fecha">.</context>
<done_when>tours/<slug>/research/<Sxx>.factcheck.json escrito y sellado con `python3 tools/tour.py factcheck-stamp <slug> <Sxx>`.</done_when>
```

## Operación sin supervisión

Para lanzar el tour y marcharte: en una sesión interactiva, `--permission-mode auto`, `/effort xhigh` y, tras la puerta de revisión (o con `auto`), `/goal python3 tools/tour.py check tours/<slug> imprime PENDING=0 y los entregables se enviaron, o detente tras 250 turnos`. En una ejecución `-p` totalmente desatendida, añade `--append-system-prompt-file prompts/unattended-append.md` desde el primer lanzamiento.

Antes de informar de progreso, contrasta cada afirmación con un resultado de herramienta de esta sesión. Informa solo de lo que puedas respaldar; si algo no está verificado, dilo. Si `check` falla, muestra su salida; si te saltaste un paso, dilo.

Mientras alguien observa: una línea de intención antes de la primera herramienta de cada fase y un breve estado al cerrar cada fase.
