Resumen: los tramos escritos antes que las paradas se desalinean; hay que reconciliarlos al terminar cada parada. `via` y `end` en tour.py resuelven los casos de ruta.

- Los stop-writers fijan la orientación exacta con OSM y a veces mueven al oyente dentro de la parada. En S09 hay un paseo de ida y vuelta; S14 termina a 40 m de S15. Cada movimiento cambia dónde empieza el tramo siguiente.
- Solución aplicada: comparar el principio y el final de cada parada con el principio y el final de los tramos vecinos (L01, L03, L10, L13 y L14 se reescribieron). En el próximo tour, escribir los tramos después de recibir las paradas, o dar a cada stop-writer las primeras y últimas líneas de los tramos que la rodean.
- `stop.via`: puntos de paso para que Valhalla no saque la ruta de la muralla por avenidas. `stop.end`: punto donde termina una parada que se camina, desde donde arranca el tramo siguiente.
- Error propio detectado por un fact-checker: suponer que dos calles con nombre continúan en línea recta (Portocarrero frente a calle del Colegio). Verificar con la geometría de OSM antes de escribir «siga recto».
- Valhalla da maniobras sin nombre y fragmentos en inglés; la geocodificación inversa de cada maniobra (scratch `annot.py`) da los nombres de calle que faltan. Merece convertirse en subcomando de tour.py.
