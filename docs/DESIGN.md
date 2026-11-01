# Diseño — Claude Audiotour

Construido con la skill prompt-architect para Opus 5.5 en Claude Code (versión 4.1). Fecha: 2026-11-01.

## Clasificación

Tarea de conocimiento con producción de artefactos, larga (de decenas de minutos a horas por tour), lanzada en interactivo con una única puerta de revisión y después desatendida. La salida se consume como entregable final (audio + mapa), no paso a paso.

## Componentes y por qué

- **`CLAUDE.md`**: lo único que necesitan todos los agentes: público, estándar narrativo, exactitud, escritura para el oído, diseño de tramos, contratos de datos, entorno, regla de entradas no confiables, lista de acciones que piden confirmación y bloque de doctrina. La orquestación del líder no está aquí porque los subagentes también cargan este archivo.
- **Skill `/audiotour`**: el prompt de lanzamiento del líder, con criterios de aceptación mecánicos, fases, `<delegation_plan>`, briefs y mecánica sin supervisión. Llega como instrucción y no como salida de herramienta.
- **`stop-writer`** (Opus 5.5, `high`, hoja): investiga y escribe juntos porque el guion necesita todo lo investigado; separarlos sería un traspaso con pérdidas.
- **`fact-checker`** (Opus 5.5, `high`, hoja, sin `Edit`): juicio independiente con contexto nuevo. Solo escribe su veredicto, y `factcheck-stamp` lo ata al hash del guion, así que cualquier edición posterior lo invalida.
- **`tools/tour.py`**: toda la parte determinista. El líder y los agentes deciden; la CLI ejecuta y comprueba. `check` es la puerta mecánica (`PENDING=<n>`) que puede leer `/goal`.

## Delegación

Unidades delegadas: dossier más guion por parada (mecanismos: amplitud y aislamiento de contexto) y fact-check por guion (mecanismo: juicio independiente). Se quedan en el líder la selección y la ruta (cadena secuencial), los tramos, el cierre y la pasada de coherencia (contexto compartido de todo el tour) y la producción (determinista). Todos los workers son Opus 5.5: no hay evidencia de paridad para otro modelo en investigación y redacción experta, y la regla de la skill es que, sin evidencia, se usa Opus 5.5. No se usa Workflow/ultracode por defecto: con entre 8 y 30 paradas, el esquema hub-and-spoke basta. Para un tour de un día entero con más de 40 paradas, la plantilla de workflow (mapa → reparto → verificación cruzada → convergencia) es la ampliación natural.

## Esfuerzo

Líder en `xhigh`: más de 30 minutos de trabajo agéntico y una orquestación de N subagentes. Workers en `high`: entregable crítico en exactitud. `max` no se recomienda sin una mejora medida.

## Guardas

`/goal` con una condición mecánica (`check` imprime `PENDING=0`) acotada por número de turnos; regla de progreso fundamentado; confirmación para acciones irreversibles (`CLAUDE.md` más `permissions.deny`). La instrucción oficial de fin de turno (texto literal de «Prompting Claude Opus 5.5 → Unattended agentic runs», obtenido el 2026-11-01) vive en `prompts/unattended-append.md` y solo se usa con `--append-system-prompt-file` en ejecuciones `-p` totalmente desatendidas; nunca va en `CLAUDE.md`.

Eliminado a propósito: recordatorios de «verifica dos veces», instrucciones de «piensa con cuidado», cualquier petición de escribir el razonamiento como salida (riesgo de rechazo por `reasoning_extraction`), y listas enumeradas de comportamiento.

## Decisiones técnicas verificadas en el contenedor (2026-11-01)

| Necesidad | Elección | Evidencia |
|---|---|---|
| Geocodificación | Nominatim | HTTP 200; «Plaza Mayor, Madrid» resuelta |
| POIs | Wikidata SPARQL `wikibase:around`, ordenado por sitelinks; tipos no-parada filtrados en Python | 33 candidatos en 0,8 km en 8 s; la variante `P279*` superó 120 s |
| Ruta peatonal paso a paso | Valhalla público, `pedestrian`, instrucciones en el idioma del tour, `optimized_route` para el orden | Tramos con nombres de calle en español; optimización con 4 puntos correcta |
| TTS | Piper offline por defecto; ElevenLabs y OpenAI con clave; edge-tts solo en local | Piper renderiza unas 10 veces más rápido que el tiempo real en CPU; edge-tts falla (WebSocket no soportado por el proxy) |
| Audio | Loudnorm −16 LUFS, MP3 96 kbps por pista, M4B AAC 64 kbps con capítulos, M3U | Prueba de humo: 6 pistas, 6 capítulos |
| Mapa | KML/KMZ con estilos y descripciones HTML, GPX, enlaces de Google Maps a pie por tramo | KML y GPX validados con lxml; la importación en My Maps no se probó desde el contenedor [verify] |

Límites de los proveedores de TTS en la nube que se usan para trocear el texto: OpenAI `gpt-4o-mini-tts` admite 2000 tokens de entrada (página oficial del modelo); ElevenLabs Multilingual v2 admite 10 000 caracteres por petición según fuentes secundarias [verify]. Los fragmentos se mantienen en 1200 y 2500 caracteres.

## Validación

Escenarios de prueba:

1. **Madrid, 4 h, es-ES, foco Siglo de Oro, con fecha.** Esperado: 10–14 paradas, horarios confirmados para las interiores, `check` en `PENDING=0`, M4B de unas 2,5 h de narración.
2. **Kioto, 3 h, en-GB, sin foco.** Esperado: voz Piper `en_GB-cori-high`; nombres japoneses glosados una vez; las referencias visibles de los tramos no dependen de rótulos en japonés.
3. **Evento (por ejemplo, una Bienal de Venecia), 2 h, it-IT.** Esperado: las paradas son pabellones u obras; si la fecha cae fuera del evento, el líder lo señala en la puerta de revisión.
4. **Dirección ambigua** («Calle Mayor 1» sin ciudad clara). Esperado: el líder compara los candidatos de Nominatim y explica su elección en la puerta de revisión.

Modos de fallo conocidos: tramos con micro-maniobras sin nombre (los mitigan la regla de fusión y las paradas intermedias); estrangulamiento de Wikipedia (alternativa WebFetch/WebSearch); voces Piper de calidad media en algunos idiomas (palanca: ElevenLabs); el `wpm` calibrado en la introducción puede variar en guiones con muchos nombres propios (`check` tolera ±40 % de diferencia entre audio y texto).

Palancas de iteración: `nav_fill` (densidad de los tramos), `weight` por parada (reparto del tiempo de narración) y `length_scale` de Piper (ritmo de la voz).

Señales en la primera ejecución: turnos que terminan con un informe de estado a mitad de tarea; workers que devuelven `partial`; fact-checks que fallan dos rondas seguidas (fuentes pobres para esa parada); un aviso de cambio de modelo en el transcript.
