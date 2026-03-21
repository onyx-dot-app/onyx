# Guia de principios de ingenieria, estilo y correccion

## Principios y colaboracion

- **Usa puertas de 1 via vs 2 vias.** Si una decision es reversible, avanza rapido e itera. Si es dificil de revertir, procede con mas cuidado.
- **La consistencia vale mas que "tener razon".** Prefiere patrones consistentes a lo largo del codebase. Si algo realmente esta mal, arreglalo en todos lados.
- **Arregla lo que tocas (con criterio).**
  - No hace falta corregir cada problema de buenas practicas que detectes.
  - No introduzcas nuevas malas practicas.
  - Si tu cambio toca codigo que ya viola buenas practicas, corrige eso dentro del mismo cambio cuando tenga sentido.
- **No pegues funcionalidades encima.** Cuando agregues algo nuevo, reestructura de forma logica si hace falta para no embarrar interfaces ni acumular deuda tecnica.

---

## Estilo y mantenibilidad

### Comentarios y legibilidad

Agrega comentarios claros:

- En limites logicos como interfaces, para que quien lea no tenga que saltar diez capas mas abajo.
- Donde haya supuestos implicitos o comportamiento poco obvio.
- En flujos o funciones complicadas.
- Siempre que ahorre tiempo real de comprension, por ejemplo con regex no triviales.

### Errores y excepciones

- **Falla de forma visible** en vez de omitir trabajo silenciosamente.
  - Ejemplo: lanza la excepcion y deja que propague, en vez de descartar un documento en silencio.
- **No abuses de `try/except`.**
  - Ubicalos en el nivel logico correcto.
  - No ocultes excepciones salvo que este claramente justificado.

### Tipado

- Todo debe quedar **lo mas estrictamente tipado posible**.
- Usa `cast` para interfaces incomodas o demasiado laxas (por ejemplo resultados de `run_functions_tuples_in_parallel`).
  - Solo usa `cast` cuando el type checker vea `Any` o los tipos sean demasiado flojos.
- Prefiere tipos faciles de leer.
  - Evita tipos densos como `dict[tuple[str, str], list[list[float]]]`.
  - Prefiere modelos del dominio, por ejemplo:
    - `EmbeddingModel(provider_name, model_name)` como modelo Pydantic
    - `dict[EmbeddingModel, list[EmbeddingVector]]`

### Estado, objetos y limites

- Manten **limites logicos claros** para contenedores de estado y objetos.
- Un objeto de **config** nunca deberia incluir cosas como `db_session`.
- Evita contenedores de estado:
  - demasiado anidados, o
  - enormes y planos al mismo tiempo.
- Prefiere **composicion y estilo funcional** sobre herencia / OOP cuando no haya una ventaja clara.
- Prefiere **no mutar** salvo que exista una razon fuerte.
- Los objetos de estado deben ser **intencionales y explicitos**, idealmente inmutables o con mutacion muy controlada.
- Usa interfaces u objetos para crear separaciones claras de responsabilidad.
- Prefiere soluciones simples cuando no haya una ganancia evidente.
  - Evita mecanismos demasiado complejos como semaforos.
  - Prefiere **hash maps (`dict`)** sobre estructuras de arbol salvo que exista una razon fuerte.

### Nombres

- Nombra variables con cuidado e intencion.
- Si dudas, elige nombres largos y explicitos.
- Evita variables de un solo caracter salvo en utilidades muy pequenas y autocontenidas.
- Manten el mismo objeto o nombre de forma consistente a lo largo del call stack y dentro de las funciones cuando sea razonable.
  - Bien: `for token in tokens:`
  - Mal: `for msg in tokens:` si estas iterando tokens
- Los nombres de funciones deberian inclinarse por ser **largos y descriptivos** para facilitar busqueda en el codebase.
  - IntelliSense puede perder referencias; la busqueda funciona mejor con nombres unicos.

### Correccion por construccion

- Prefiere que la correccion este encapsulada en el propio diseno.
  - No dependas de que quien llama "lo use bien" si puedes hacer dificil el mal uso.
- Evita redundancias:
  - Si una funcion recibe un argumento, no deberia recibir tambien un objeto de estado que contenga ese mismo valor.
- No dejes codigo muerto salvo que exista una razon muy fuerte.
- No dejes codigo comentado en ramas principales o de feature salvo que exista una razon muy fuerte.
- No dupliques logica:
  - No copies y pegues dentro de ramas cuando la logica compartida pueda vivir arriba del condicional.
  - Si te da miedo tocar la implementacion original, todavia no la entiendes lo suficiente.
  - Los LLM suelen crear logica duplicada sutil; revisa con cuidado y eliminala.
  - Evita objetos "casi identicos" que vuelvan confuso cuando usar cada uno.
- Evita funciones excesivamente largas con logica encadenada:
  - Encapsula pasos en helpers para mejorar legibilidad, aunque no se reutilicen.
  - Expresiones "pythonicas" de varios pasos estan bien con moderacion; no sacrifiques claridad por ingenio.

---

## Rendimiento y correccion

- Evita retener recursos por periodos largos:
  - sesiones de BD
  - locks / semaforos
- Valida objetos:
  - al crearlos, y
  - justo antes de usarlos.
- Codigo de conectores (datos -> documentos indexados de la aplicacion):
  - Cualquier estructura en memoria que pueda crecer sin limite en funcion de la entrada debe revisarse periodicamente por tamano.
  - Si un conector esta causando OOM (a menudo se ve como "missing celery tasks"), este es de los primeros puntos para revisar.
- Async y event loops:
  - No introduzcas nuevo codigo async / event loop en Python y, cuando tenga sentido, intenta volver sincrono el codigo async existente.
  - Escribir async sin entender al 100% el flujo ni tener una razon concreta suele introducir bugs sin aportar ganancias reales.

---

## Convenciones del repositorio: donde vive cada cosa

- Modelos Pydantic y modelos de datos: archivos `models.py`.
- Funciones de acceso a BD (excepto lazy loading): directorio `db/`.
- Prompts de LLM: directorio `prompts/`, mas o menos espejado con el layout del codigo que los usa.
- Rutas de API: directorio `server/`.

---

## Reglas de Pydantic y modelado

- Prefiere **Pydantic** por encima de dataclasses.
- Si de verdad hace falta, usa `allow_arbitrary_types`.

---

## Convenciones de datos

- Prefiere `None` explicito sobre strings vacios usados como sentinel, salvo que la intencion requiera otra cosa.
- Prefiere identificadores explicitos:
  - Usa enums de string en vez de codigos enteros.
- Evita numeros magicos. **Evita siempre strings magicos.**

---

## Logging

- Registra los mensajes donde se crean.
- No pases mensajes de log de un lado a otro solo para loguearlos en otro sitio.

---

## Encapsulacion

- No uses atributos, metodos o propiedades privadas de otras clases o modulos.
- "Private" significa privado: respeta ese limite.

---

## Guia de SQLAlchemy

- El lazy loading suele ser problematico a escala, especialmente a traves de varias relaciones tipo lista.
- Ten cuidado al acceder a atributos de objetos SQLAlchemy:
  - puede evitar consultas redundantes,
  - pero tambien puede fallar fuera de una sesion activa,
  - y el lazy loading puede introducir dependencias ocultas de base de datos en funciones aparentemente simples.
- Referencia: https://www.reddit.com/r/SQLAlchemy/comments/138f248/joinedload_vs_selectinload/

---

## Trunk-based development y banderas de funcionalidad

- **Los PRs no deberian superar 500 lineas de cambio real.**
- **Haz merge a main con frecuencia.** Evita ramas largas de feature: generan conflictos y dolor de integracion.
- **Usa banderas de funcionalidad para rollout incremental.**
  - Las funcionalidades grandes deberian mergearse en incrementos pequenos y desplegables detras de una bandera.
  - Eso permite integracion continua sin exponer funcionalidad incompleta.
- **Haz que las banderas vivan poco tiempo.** Cuando una funcionalidad ya este totalmente desplegada, elimina la bandera y el codigo muerto asociado.
- **Coloca la bandera en el nivel correcto.** Prefiere ponerla en el punto de entrada de API o UI, no profundamente en la logica de negocio.
- **Prueba ambos estados de la bandera.** Asegura que el codebase funciona bien con la bandera activada y desactivada.

---

## Misc

- Cualquier `TODO` que agregues al codigo debe incluir el nombre o usuario responsable, o el numero de un issue asociado a ese trabajo.
- Evita logica a nivel de modulo que se ejecute al importar, porque genera efectos laterales al momento del import.
  - Casi toda logica importante deberia vivir dentro de una funcion que se invoque explicitamente.
  - Excepciones aceptables pueden incluir cargar variables de entorno o configurar loggers.
- Si necesitas algo asi, probablemente esa logica deberia vivir en un archivo pensado para ejecucion manual (con `if __name__ == "__main__":`) y no ser importado desde otros modulos.
- No mezcles scripts de Python pensados para ejecutarse desde linea de comandos (con `if __name__ == "__main__":`) con modulos pensados para ser importados.
  - Si por alguna razon rara tienen que ser el mismo archivo, toda logica especifica de ejecucion, incluyendo imports, debe quedar dentro del bloque `if __name__ == "__main__":`.
  - En general esos archivos ejecutables viven en `backend/scripts/`.
