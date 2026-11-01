Resumen: el cupo de búsquedas web es por sesión y lo comparten todos los subagentes; con 15 investigadores en paralelo se agotó a mitad de la investigación.

- Síntoma: los stop-writers dejaron de poder buscar y verificaron leyendo URL ya localizadas. Varios datos quedaron con una sola fuente o con fuentes divulgativas.
- Mitigaciones para el próximo tour:
  - avisar en el brief desde el principio de que el cupo es compartido y que hay que priorizar fuentes primarias;
  - subir `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` antes de lanzar, si la configuración lo permite [verify];
  - lanzar los fact-checkers con el aviso de usar WebFetch sobre las URL del dossier cuando WebSearch falle (funcionó).
- Dominios útiles bloqueados o caídos desde el contenedor: web.archive.org, arquidiocesisdecartagena.org, Centro Virtual Cervantes (404), EcuRed (503) y Enciclopedia Banrepcultural (antibots, a veces).
