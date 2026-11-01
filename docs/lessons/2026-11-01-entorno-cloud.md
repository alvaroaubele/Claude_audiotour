Resumen: en el contenedor cloud de Claude Code, Overpass y edge-tts no funcionan; Piper, Valhalla, Nominatim y Wikidata SPARQL sí.

- Overpass (`overpass-api.de` y espejos) se corta en el proxy: la detección de POIs usa Wikidata SPARQL (`tour.py pois`), que además da una medida de notoriedad (sitelinks).
- `edge-tts` usa WebSocket y el proxy no lo soporta. Piper es el backend por defecto; ElevenLabs/OpenAI responden si hay clave.
- La consulta SPARQL con `wdt:P31/wdt:P279*` dentro de `wikibase:around` supera 2 minutos: el filtrado de tipos no-parada se hace en Python (`NON_STOP_TYPES`).
- HuggingFace sirve los modelos Piper con codificación gzip: descargar con `iter_content`, no con `r.raw`, o el JSON de configuración llega comprimido.
- Valhalla devuelve micro-maniobras sin nombre («gire hacia la calzada») y fragmentos en inglés («the crosswalk»): el guion de tramo debe fusionarlas.
- Wikipedia API puede responder «too many requests» desde la IP compartida del contenedor: WebFetch/WebSearch como alternativa.
