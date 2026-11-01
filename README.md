# Claude Audiotour

Audioguías a pie de nivel experto para cualquier ciudad, lugar o evento, producidas por Claude Code (Opus 5.5) con subagentes de investigación y verificación.

**Entrada:** ciudad/lugar/evento · dirección exacta de inicio · duración · idioma · (opcional) foco, fecha, hora, voz.
**Salida** en `tours/<slug>/dist/`: audiolibro `.m4b` con un capítulo por pista, una MP3 por pista con `playlist.m3u`, `tour.kmz` para Google My Maps, `tour.gpx` para apps de navegación offline y `links.md` con la navegación a pie de Google Maps por tramo. Guiones, dossiers con fuentes, fact-checks y `plan.json` se versionan en `tours/<slug>/`.

| Pieza | Archivo |
|---|---|
| Especificación compartida por todos los agentes (público, estándar narrativo, contratos, doctrina) | `CLAUDE.md` |
| Procedimiento del líder, plan de delegación y briefs | `.claude/skills/audiotour/SKILL.md` |
| Subagentes (Opus 5.5, effort high, hojas) | `.claude/agents/stop-writer.md`, `.claude/agents/fact-checker.md` |
| Fontanería determinista: geocodificación, POIs, ruta peatonal, presupuesto, mapa, TTS, ensamblado, check | `tools/tour.py` |
| Instrucción oficial de fin de turno para ejecuciones `-p` desatendidas | `prompts/unattended-append.md` |
| Notas de diseño y validación | `docs/DESIGN.md` |

## Crear un tour (sesión interactiva de Claude Code)

1. Abre una sesión de Claude Code sobre este repositorio (claude.ai/code o `claude` en un clon local). Resultado: el prompt de Claude Code está listo.
2. Escribe `/model opus` y pulsa Enter. Resultado: la sesión confirma Opus 5.5 (si tu proveedor resuelve `opus` a otra versión, usa `/model claude-opus-5-5`).
3. Escribe `/effort xhigh` y pulsa Enter. Resultado: la sesión muestra el nivel `xhigh` guardado para Opus 5.5.
4. Escribe, con tus datos:
   ```
   /audiotour ciudad="Madrid" inicio="Plaza Mayor, 28012 Madrid" duracion="4h" idioma="es-ES" foco="el Madrid de los Austrias y el Siglo de Oro" fecha="2026-11-14" hora="10:00"
   ```
   Resultado: el líder geocodifica, propone paradas, ruta, presupuesto de tiempo y voz, y se detiene una única vez para tu revisión.
5. Responde aprobando o ajustando (por ejemplo «quita la parada 4, añade el Teatro Real»). Resultado: el líder lanza la investigación en paralelo y ya no vuelve a preguntar hasta entregar.
6. Para marcharte mientras trabaja, escribe, con el slug que el líder mostró:
   ```
   /goal python3 tools/tour.py check tours/<slug> imprime PENDING=0 y los entregables se enviaron, o detente tras 250 turnos
   ```
   Resultado: la sesión sigue trabajando por turnos hasta cumplir la condición.
7. Al terminar, descarga los archivos que el líder envía (`.m4b`, `.kmz`, `.gpx`) e importa el mapa con los pasos que incluye su resumen final. Resultado: el audio se reproduce con capítulos y el mapa muestra paradas numeradas y la ruta.

Añadir `auto` a los argumentos del paso 4 salta la revisión del paso 5.

## Voz

- `tts=piper` (por defecto): voz neuronal offline; el pipeline elige la de mayor calidad del catálogo Piper para el locale (por ejemplo `es_ES-davefx-medium`, `es_MX-claude-high`, `en_US-ryan-high`, `de_DE-thorsten-high`). Probada en este repositorio.
- `tts=elevenlabs voz=<voice_id>`: máxima naturalidad; requiere `ELEVENLABS_API_KEY` en el entorno. **No probada aquí** (sin clave).
- `tts=openai voz=<onyx|…>`: `gpt-4o-mini-tts` con instrucciones de estilo; requiere `OPENAI_API_KEY`. **No probada aquí** (sin clave).
- `tts=edge`: voces neuronales de Microsoft Edge; solo en máquina local (WebSocket bloqueado en el contenedor cloud).

Para usar una clave en el entorno cloud:

1. En la sesión de claude.ai/code, abre el menú del entorno cloud en la barra de título y pulsa **Edit**. Resultado: se abre la configuración del entorno.
2. Añádela como **variable de entorno** con el nombre exacto `ELEVENLABS_API_KEY` (u `OPENAI_API_KEY`) y guarda. `tools/tour.py` lee la clave de esa variable; un secreto guardado en «Network secrets» no llega como variable de entorno al script [verify]. Resultado: el entorno muestra la variable guardada.
3. Inicia una sesión nueva sobre el repositorio. Resultado: `python3 -c "import os;print(bool(os.environ.get('ELEVENLABS_API_KEY')))"` imprime `True`.

Nunca pegues la clave en el chat.

## Uso directo de la CLI

```
pip install -r requirements.txt          # requiere ffmpeg/ffprobe en el PATH
python3 tools/tour.py -h
python3 tools/test_tour.py               # tests offline
```
