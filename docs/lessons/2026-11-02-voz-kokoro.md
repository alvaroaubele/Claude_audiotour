Resumen: Kokoro-82M (kokoro-onnx) sustituye a Piper como voz por defecto. Es más natural, pronuncia mejor y es viable en CPU; Chatterbox suena peor en español y es 17 veces más lento.

Comparativa del 2026-11-02 con el mismo párrafo del tour (90 palabras, con nombres propios y una cifra). Naturalidad estimada con UTMOS22-strong (SpeechMOS); errores con Whisper small en español (WER):

| Voz | UTMOS | WER | Velocidad en 4 CPU |
|---|---|---|---|
| Piper es_ES-davefx-medium (anterior) | 1,92 | 0,128 («poríntese», «tire») | ~10× tiempo real |
| Kokoro em_santa | 2,20 | 0,106 | ~3× |
| Chatterbox Multilingual (voz por defecto) | 2,69 | 0,191 («Guide la cabeza») | 0,2× (RTF 5,1) |
| Kokoro em_alex | 2,80 (2,66 a ritmo ×1,15) | 0,096 | ~3× |
| Kokoro ef_dora | 3,02 (2,98 a ritmo ×1,15) | 0,096 | ~4× |

- UTMOS está entrenado en inglés: los valores absolutos en español son bajos y solo cuenta el orden relativo. No sustituye a una escucha, pero sirve para descartar.
- El wheel de espeakng-loader lleva compilada la ruta de su CI (/home/runner/work/espeakng-loader/…); espeak-ng vuelve a ella aunque se configure otra ruta de datos. `KokoroBackend` crea un enlace simbólico en esa ruta hacia los datos del propio wheel.
- Chatterbox necesita `setuptools<81`, porque su marcador de agua Perth importa `pkg_resources`.
- `torch.hub` no puede descargar código de GitHub desde el contenedor (403); clonar con git y cargar con `source="local"` sí funciona, y los assets de releases de GitHub también se descargan.
- Velocidad: `meta.tts.speed` acelera la voz, pero los silencios de pausa son fijos. Para ×1,15 sobre 167 palabras por minuto hizo falta speed = 1,095 (medido: 191,6 ppm).
- Pendiente de probar con más CPU o GPU: Fish Audio S2 Pro y Qwen3-TTS, que una guía de 2026 sitúa por encima en español.
