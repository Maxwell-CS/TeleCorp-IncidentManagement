# Módulo Azure — Especificación (Cliente e incidencias)

> Documento **interno** (se borra `docs/` antes de entregar: el enunciado anula a quien entregue un informe).
> Es el documento pilar del módulo Azure, equivalente a `docs/AWS.md` del módulo AWS. Si contradice a `contracts/`, manda `contracts/`; si contradice a `docs/global/`, manda este archivo para lo que es de Azure.
> Fuentes: `docs/global/REQUISITOS.md` (RF-AZ-01…33), `docs/global/PLAN.md` (v3), `docs/global/GCP.md` (contratos con GCP), `contracts/` (contratos con AWS y GCP).

## 0. Estado y decisiones adoptadas

**Estado (2026-11-15):** el backend, el frontend y los scripts están escritos y probados en local (41 pruebas). **Nada está desplegado.** Falta adaptar el código a los contratos compartidos (ver §9).

Decisiones del equipo que Azure asume (`docs/AWS.md` §0):

| Decisión | Valor | Efecto en Azure |
|---|---|---|
| IA generativa (Gemini) | Sí | Azure llama a `/ai/classify-report` y `/ai/summarize-incident` de GCP |
| Reportes relacionados | Misma zona + tiempo, **cualquier tipo** (tipo configurable) | El correlador cuenta por zona; el modo `ZONA_Y_CATEGORIA` es opcional |
| Tipos de evento de AWS | **7**: FALLA, SATURACION, DEGRADACION, RECUPERACION, PREVENTIVA, ESTRUCTURAL, PROLONGADA | Azure debe aceptar los 7 |
| Recurrencia | AWS la detecta y emite ESTRUCTURAL; GCP la analiza | Azure crea una incidencia `ESTRUCTURAL` al recibirla |

## 1. Alcance

Azure es el **plano de cliente e incidencias**: portal de usuario, reportes, detección de incidencias colectivas, correlación con eventos de antenas, priorización, ciclo de vida, notificaciones y API para la consola. Vive fuera del Lab de AWS para seguir funcionando si este se apaga (RNF-05).

**No hago:** telemetría, estado de antenas, Step Functions, predicciones (AWS) · modelos, analítica, IA generativa en sí (GCP).
**Consola de operación (SPA):** la construye P3 (RF-AZ-19). Azure le da los datos por API y el hosting. Mi consola actual es una base opcional.

**Principio:** nada de lo mío depende de AWS ni de GCP para funcionar. Si ellos caen, sigo registrando reportes, detectando colectivas y notificando (RF-AZ-29).

## 2. Requisitos y estado

✅ cumple en el código local · 🟡 parcial · ❌ falta · ➕ extra. "Cumple" = probado en local, sin desplegar.

### A. Reportes
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-01 Portal público | ✅ | `frontend/index.html` |
| RF-AZ-02 Campos del reporte | 🟡 | Falta coordenadas → zona (hoy el usuario elige la zona) |
| RF-AZ-03 ID único + idempotencia | ✅ | `report_id` determinista desde `idempotency_key` |
| RF-AZ-04 Consultar estado con dato de verificación | 🟡 | Falta el dato de verificación |
| RF-AZ-05 Estados + transiciones inválidas | ✅ | `409` y queda en el historial |
| RF-AZ-06 Historial inmutable con actor | ✅ | |
| RF-AZ-07 Validación y límite de abusos | 🟡 | Falta límite de tasa |

### B. Incidencias colectivas
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-08 Reportes relacionados | 🟡 | Hoy zona + grupo de problema; falta el modo `ZONA` (cualquier tipo) |
| RF-AZ-09 ≥10 usuarios distintos, ventana <24 h | ✅ | `user_key = sha256(documento\|teléfono)` |
| RF-AZ-10 Agrupar conservando relación | ✅ | |
| RF-AZ-11 Sin duplicar bajo concurrencia | ✅ | ID determinista + `create_item` (409) |
| RF-AZ-12 Reabrir | ✅ | Hasta 5 ciclos |
| RF-AZ-13 Cierre automático | ✅ | |

### C. Integración con infraestructura
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-14 Eventos idempotentes + proyección local | 🟡 | Falta el sobre común y orden por `occurred_at`/`detected_at` |
| RF-AZ-15 Correlación, origen y tiempo de detección | ✅ | `detected_by`, `detection_lag_s` |
| RF-AZ-16 Incidencias desde eventos | 🟡 | Falta crear incidencias PREVENTIVA y ESTRUCTURAL |
| RF-AZ-17 Reconciliar con `GET /antennas` | ❌ ➕ | |

### D. Priorización y gestión
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-18 Prioridad explicable | 🟡 | Fórmula lista; falta leer pesos de `/config` y ajustar pesos al contrato (§6.2) |
| RF-AZ-19 Consola | 🟡 | La hace P3; mi base tiene bandeja, detalle y acciones |
| RF-AZ-20 Acciones del operador | ✅ | |
| RF-AZ-21 Solo operadores | ✅ | Token (plan: auth de Static Web Apps) |
| RF-AZ-22 Tiempo real | ❌ ➕ | Sondeo corto |

### E. Notificaciones
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-23 Tres etapas | ✅ | |
| RF-AZ-24 Correo + SMS con degradación | 🟡 | SMS siempre simulado; correo real si ACS se crea |
| RF-AZ-25 Uno por usuario y etapa | 🟡 | Falta limitar la tasa y mostrar el estado de entrega en el historial |
| RF-AZ-26 Texto por IA | ✅ ➕ | |

### F. Escala e integraciones
| ID | Estado | Nota |
|---|---|---|
| RF-AZ-27 Picos | 🟡 | Falta reintento explícito ante `429` de Cosmos |
| RF-AZ-28 Respaldo continuo | ❌ | Activar al desplegar |
| RF-AZ-29 Modo degradado | ✅ | |
| RF-AZ-30 IA por reporte | ❌ | Hoy solo enriquezco el incidente |
| RF-AZ-31 Resumen + causa probable | 🟡 | Falta `probable_cause` y `recommended_action` |
| RF-AZ-32 Exportar reportes e incidencias | 🟡 | Hoy solo incidentes |
| RF-AZ-33 Leer `GET /config` | ❌ | |

**Total:** 15 ✅ · 13 🟡 · 5 ❌ (RF-AZ-17 y 22 son extras).

## 3. Qué recibe Azure (APIs que Azure expone)

| # | Quién llama | Ruta | Autenticación | Contenido |
|---|---|---|---|---|
| 1 | Usuario | `POST /api/reports` | Pública, con validación de esquema y tope de 8 KB | Reporte |
| 2 | Usuario | `GET /api/reports/{id}` | El código (y dato de verificación) | Estado e historial, sin datos personales |
| 3 | **AWS** | `POST /events/infra` | **`X-API-Key`** (`azure_api_key`) | Sobre `antenna.event` |
| 4 | Operador / consola | `GET/PATCH /api/incidents…`, `PATCH /api/reports/{id}` | `x-operator-token` | Gestión |
| 5 | Operador | `GET /api/infra/events`, `POST /api/ops/redrive` | `x-operator-token` | Operación |

**La ruta 3 es el contrato con AWS.** AWS la llama desde su `outbox-azure` (`docs/AWS.md` §2). La URL base que AWS guarda en SSM (`/pulsored/endpoints/azure`) debe incluir el prefijo de la Function App (`https://<app>.azurewebsites.net/api`), o hay que quitar el prefijo `api` en `host.json`. Acordarlo con P1.

### 3.1 Reporte (portal → Azure)
```json
POST /api/reports
{
  "idempotency_key": "uuid-del-cliente",
  "user_document": "12345678", "phone": "+51999999999", "email": "usuario@correo.com",
  "zone_id": "LIM-SURCO",
  "location": {"lat": -12.145, "lng": -76.993},
  "occurred_at": "2026-11-15T14:30:00Z",
  "category": "SIN_INTERNET",
  "description": "No tengo internet desde las 2 pm"
}
```
Respuesta: `202 {"report_id":"REP-...","status":"REGISTRADA"}` · `200` con `duplicate:true` si se reenvía · `400` esquema inválido.
`zone_id` sale de `contracts/zones.json`; `category` de `contracts/enums.json` (`SIN_INTERNET`, `INTERNET_LENTO`, `SIN_SENAL`, `LLAMADAS`, `SMS`, `OTRO`).

### 3.2 Evento de AWS → Azure (`type: antenna.event`)
Sobre común (`contracts/events/envelope.schema.json`) con el payload de `contracts/events/antenna-event.schema.json`:
```json
POST /events/infra          (header: X-API-Key)
{
  "event_id": "uuid determinista (uuid5)", "type": "antenna.event", "schema_version": "1.0",
  "source": "aws", "occurred_at": "2026-11-20T15:04:00Z", "correlation_id": "c1f0a9b2-...",
  "payload": {
    "antenna_id": "ANT-LIM-004", "zone_id": "LIM-SURCO", "episode_id": "EP-ANT-LIM-004-1763650860",
    "event_type": "FALLA | SATURACION | DEGRADACION | RECUPERACION | PREVENTIVA | ESTRUCTURAL | PROLONGADA",
    "severity": "INFO | BAJA | MEDIA | ALTA | CRITICA",
    "previous_state": "NORMAL", "new_state": "CAIDA", "gb_per_min": 41.2,
    "first_anomaly_at": "2026-11-20T15:01:00Z", "detected_at": "2026-11-20T15:03:00Z",
    "prediction": {"probability": 0.82, "predicted_state": "CAIDA", "horizon_minutes": 60, "valid_until": "...", "model_version": "..."},
    "recurrence": {"episodes_7d": 3, "episodes_30d": 5},
    "elapsed_minutes": 95
  }
}
```
`prediction` solo en PREVENTIVA · `recurrence` solo en ESTRUCTURAL · `elapsed_minutes` solo en PROLONGADA.
Respuestas: `202` aceptado · `200 {"status":"duplicate"}` · `400` inválido (**AWS no reintenta**) · `401` clave inválida · `5xx` (AWS reintenta con su outbox y DLQ).
Idempotencia: `create_item` con `id = event_id`; un `409` de Cosmos es un duplicado.

## 4. Qué envía Azure

| # | Destino | Llamada | Autenticación | Contenido | Si falla |
|---|---|---|---|---|---|
| 1 | **GCP** | `POST /ai/classify-report` (sincrónica, **después** de guardar; timeout 4 s) | `X-API-Key` | Texto del reporte, categoría declarada y tipo de zona. **Sin documento, teléfono ni correo** | `503` o timeout → reglas, `source=reglas` |
| 2 | **GCP** | `POST /ai/summarize-incident` (timeout 8 s) | `X-API-Key` | Zona, usuarios, evidencia de antenas, hasta 10 textos sin datos personales | Sin resumen |
| 3 | **GCP** | `POST /ingest/incidents` (`incident.upsert` y `report.upsert`) | `X-API-Key` | Incidencias y reportes, en cada cambio. `user_key` es un hash | Reintento por cola de Service Bus y DLQ |
| 4 | **AWS** | `GET /config` | `X-API-Key` (clave `azure`) | Configuración global versionada | Caché y valores por defecto |
| 5 | **AWS** | `GET /antennas`, `GET /predictions` | `X-API-Key` (clave `azure`) | Para la consola y la reconciliación (no es ruta crítica) | Se muestra el último dato conocido |
| 6 | Usuarios | ACS Email (real) y SMS (simulado) | — | 3 etapas: evaluando → incidencia identificada → restablecido | Reintentos y DLQ |

Los cuerpos de GCP van en el sobre común (`source: "azure"`). Formato exacto de los payloads en `docs/global/GCP.md` §4.2.

**Respuesta esperada de `classify-report`:** `{category, urgency, critical_site{mentioned,kind}, confidence, model_version, source}`.
**Respuesta de `summarize-incident`:** `{summary, probable_cause, recommended_action, model_version}`.

## 5. Arquitectura en Azure

Región `westus2` (la única cercana a AWS `us-east-1` que permite la política de la suscripción).

| Componente | Uso |
|---|---|
| Functions (Python 3.12, consumo, modelo v2) | API HTTP, correlador, enlazador de infraestructura, notificador, exportador |
| Durable Functions | Orquestador `incident_lifecycle` (ciclo de vida, escalamiento, reapertura) |
| Cosmos DB (free tier, con respaldo a serverless) | Reportes, incidencias, historial, eventos, notificaciones |
| Service Bus Basic | Colas `notifications` y `analytics-export`, con DLQ |
| Communication Services Email | Correo real (si se puede automatizar el dominio administrado) |
| Key Vault | Secretos, referenciados desde la Function App |
| Static Web Apps (Free) | Portal y consola |
| Application Insights | Logs y trazas |

| Función | Disparador | Qué hace |
|---|---|---|
| `intake-report` | HTTP POST | Valida, guarda con idempotencia, `202` |
| `reports-api`, `incidents-api` | HTTP | Consultas y acciones del operador |
| `ingest-infra-event` | HTTP POST | Valida el sobre, guarda con `create_item` |
| `infra-linker` | Change feed de `infra_events` | Enlaza eventos con incidentes de la zona, recalcula prioridad |
| `correlator` | Change feed de `reports` | Cuenta usuarios distintos y abre o enlaza incidentes |
| `incident-lifecycle` | Durable | EN_REVISION → EN_ATENCION → SOLUCIONADA → CERRADA, con reapertura |
| `notifier` | Service Bus | Un mensaje por usuario y etapa |
| `exporter` | Service Bus | `POST` a GCP |

**Diferencia con `docs/global/PLAN.md`:** el plan usa Storage Queue, un `report-processor` y un `sweeper` con temporizador, y descarta Durable Functions. Yo implementé Durable Functions y Service Bus. Se mantiene salvo que el equipo decida lo contrario.

**Por qué el change feed:** la partición por `zone_id` procesa los reportes de una zona en orden y de a uno por lease, lo que evita incidencias duplicadas sin bloqueos. Guardar y reaccionar es atómico.

## 6. Reglas de dominio

### 6.1 Incidente colectivo y estados
- Se abre con **≥ 10 usuarios distintos** en la misma zona dentro de una ventana deslizante **< 24 h**. Varios reportes del mismo usuario cuentan uno. Los reportes posteriores se enlazan al incidente abierto.
- Estados: `REGISTRADA → EN_REVISION → EN_ATENCION → SOLUCIONADA → CERRADA`, con reapertura `SOLUCIONADA → EN_REVISION`. Etiquetas de la interfaz (`contracts/enums.json`): Registrada, En revisión, **Siendo atendida**, Solucionada, Cerrada.
- Tipos de incidencia: `COLECTIVA`, `INFRAESTRUCTURA`, `PREVENTIVA`, `ESTRUCTURAL`.
- `detected_by`: `ANTENA`, `USUARIOS` o `AMBOS`. `detection_lag_s = first_report_at − first_anomaly_at` (positivo = la antena detectó antes).

### 6.2 Prioridad
`score = 40·U + 25·Z + 20·A + 10·D + 5·R`
- **U** = `min(1, log10(usuarios)/4)` · **Z** = tipo de zona (SALUD/CRITICA 1.0, EDUCATIVA 0.8, INDUSTRIAL 0.7, COMERCIAL 0.5, RESIDENCIAL 0.4; +0.2 si la IA detecta un sitio crítico) · **D** = `min(1, horas/6)` · **R** = `min(1, incidentes de la antena en 30 días / 5)`.
- **A** (evidencia de antena): FALLA con `new_state` INHABILITADA 1.0, FALLA con CAIDA 0.7, SATURACION 0.5, ninguna 0 ("verificar en campo"). **PREVENTIVA no confirma.** DEGRADACION: por definir con el equipo.
- Niveles: **CRÍTICA ≥ 75 · ALTA 50–74 · MEDIA 25–49 · BAJA < 25**. Los pesos vivirán en `/config`.
- Las incidencias PREVENTIVA y ESTRUCTURAL **no notifican a usuarios**, porque no tienen usuarios asociados.

### 6.3 Notificaciones
Tres etapas, una por usuario y etapa. Clave de idempotencia: `incidente|usuario|etapa|ciclo`. Los mensajes de la cola no llevan datos de contacto; se leen del reporte solo al enviar. SMS simulado.

## 7. Modelo de datos (Cosmos DB, base `pulsored`)

| Contenedor | Partición | `id` | Notas |
|---|---|---|---|
| `reports` | `/zone_id` | `report_id` | PII (`user_document`, `phone`, `email`) **solo aquí** |
| `incidents` | `/zone_id` | `incident_id` | tipo, origen, prioridad y factores, `detected_by`, tiempos, `ai` |
| `incident_users` | `/incident_id` | `user_key` | Conteo exacto de usuarios distintos |
| `history` | `/entity_id` | `entity\|ts#seq` | Solo se agrega; actor SISTEMA / IA / OPERADOR / USUARIO |
| `infra_events` | `/zone_id` | `event_id` | TTL 30 días; base de la proyección de antenas |
| `notifications` | `/incident_id` | `incidente\|usuario\|etapa\|ciclo` | Estado de entrega |
| `zones` | `/id` | `zone_id` | Catálogo (`contracts/zones.json`) |
| `leases-*` | — | — | Control del change feed |

El documento y el teléfono nunca salen a GCP ni a las colas.

## 8. Picos, fallos y recuperación

| Situación | Manejo |
|---|---|
| Pico de reportes | Functions escalan; el frontend reintenta con backoff y el mismo `idempotency_key`; Cosmos con reintentos ante `429` |
| AWS reenvía un evento | `create_item` → `200 duplicate` |
| Azure caído | AWS acumula en su outbox y reenvía (RF-AWS-12) |
| GCP caído | `ai_enrich` cae a reglas; el `exporter` reintenta y manda a DLQ; `POST /api/ops/redrive` lo reprocesa |
| ACS falla | Reintentos y DLQ; la idempotencia evita duplicados |
| AWS apagado (Lab) | Sigo registrando, detectando y notificando; la consola muestra "infra desactualizada" |

## 9. Brechas entre el código y los contratos

Lo que hay que adaptar en el código para conectar bien (orden de prioridad):

1. **Zonas:** usar `contracts/zones.json` (`LIM-SURCO`, `ANT-LIM-001`). Mi `zone_id` acepta hasta 8 caracteres y mi `report_id` se parsea cortando por guiones; ambos fallan con los IDs reales.
2. **Evento de AWS:** ruta `/events/infra`, header `X-API-Key`, sobre común, los 7 tipos y `new_state` para la evidencia. Hoy acepto 5 tipos en inglés y campos planos.
3. **Categorías:** usar las de `enums.json`.
4. **IA:** separar `classify-report` (por reporte) y `summarize-incident`, con los campos y timeouts de §4.
5. **Exportación:** sobre común con `incident.upsert` y `report.upsert`; incluir reportes.
6. **IDs:** adoptar `REP-…` e `INC-…`, sin depender de la zona dentro del ID.
7. **`GET /config`, `/antennas`, `/predictions`** de AWS, con caché.
8. **Incidencias PREVENTIVA y ESTRUCTURAL** desde sus eventos.
9. **Modo de reportes relacionados `ZONA`** (cualquier tipo) por defecto.
10. Resto de pendientes de §2: límite de tasa, dato de verificación, coordenadas → zona, estado de entrega en el historial, respaldo continuo.

## 10. Despliegue y restricciones de la cuenta

Azure for Students: regiones permitidas `westus2`, `canadacentral`, `brazilsouth`, `chilecentral`, `westus`. Cosmos free tier con respaldo a serverless; SMS siempre simulado; correo real solo si ACS se puede crear por CLI.

```powershell
az login --use-device-code
.\infra\deploy.ps1        # crea todo, publica backend y frontend
.\infra\smoke_test.ps1
.\infra\teardown.ps1 -Yes
```
`deploy.ps1` escribe `infra\outputs.local.json` (secretos; **no se versiona**). Riesgos no verificables hasta desplegar: free tier de Cosmos, automatización de ACS, referencias a Key Vault y los triggers reales de Cosmos, Service Bus y Durable.

## 11. Qué necesito de los demás y qué doy

| De quién | Qué | Para |
|---|---|---|
| **P1 (AWS)** | URL base de API Gateway y la clave `azure` | `GET /config`, `/antennas`, `/predictions` |
| **P1 (AWS)** | Confirmar ruta `/events/infra`, `X-API-Key` y la URL base con o sin `/api` | `outbox-azure` |
| **P3 (GCP)** | URL base de Cloud Run y la clave de Azure | `/ai/*` e `/ingest/incidents` |
| **P3 (GCP)** | Quién hace la consola y desde qué fecha | RF-AZ-19 |
| **Todos** | `contracts/enums.json` y `zones.json` fijados | Mismo idioma entre las tres nubes |

**Yo les doy:** URL de la Function App, la `azure_api_key` para que AWS la guarde en Secrets Manager (por canal privado), el endpoint de lectura para la consola y el portal de usuario.

## 12. Pruebas

Las 41 pruebas locales cubren: ventana de 24 h, 9 y 10 usuarios, dos zonas, idempotencia de reportes y eventos, transiciones inválidas, prioridad, PII fuera de GCP y de las colas, notificador idempotente, exportación sin PII, caída de IA → reglas, reapertura y escalamiento al operador.
```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts\simulate_local.py
```
Tras adaptar los contratos hay que sumar pruebas con los esquemas de `contracts/events/*.json` (RNF-10).
