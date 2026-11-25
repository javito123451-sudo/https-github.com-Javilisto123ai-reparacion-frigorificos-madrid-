# Evaluación

`cases.jsonl` contiene casos **SINTÉTICOS** (redactados a mano siguiendo patrones públicos de estafa y de comunicaciones
legítimas). Sirven como prueba de regresión y para medir falsos positivos/negativos **del modo reglas**, pero **no sustituyen
a datos reales**: los pesos del motor no se han calibrado con tráfico real. Ampliar con casos reales y anonimizados
(con permiso) es el siguiente paso. `python -m eval.run` imprime las métricas por categoría.
