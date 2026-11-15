# TeleCorp-IncidentManagement (módulo Azure)

Módulo de **cliente e incidencias** de PulsoRed (Red TeleCorp): recibe los reportes de los usuarios, detecta incidencias colectivas, las cruza con los eventos de antenas de AWS, las prioriza, notifica a los afectados y envía datos a GCP.

100 % serverless: Azure Functions (Python 3.12) + Durable Functions, Cosmos DB, Service Bus, Communication Services, Key Vault, Static Web Apps. Región `westus2`.

| Nube | Contexto | Repo |
|---|---|---|
| **AWS** | Infraestructura y automatización: telemetría, eventos, Step Functions, predicciones, secretos y configuración global | `TeleCorp-InfraMonitoring` |
| **Azure** (este repo) | Cliente e incidencias: portal, reportes, correlación, priorización, ciclo de vida, notificaciones | `TeleCorp-IncidentManagement` |
| **GCP** | Inteligencia y analítica: predicción, IA generativa (Gemini), histórico y dashboards | `TeleCorp-DataAnalytics` |

Documento pilar: [`docs/AZURE.md`](docs/AZURE.md). Contratos compartidos con AWS y GCP: [`contracts/`](contracts/). Documentos del equipo: [`docs/global/`](docs/global/).

## Qué hace Azure

1. **Recibe reportes** (`POST /api/reports`): validación, idempotencia, `202`, guardado en Cosmos DB.
2. **Detecta incidencias colectivas**: ≥ 10 usuarios distintos (`sha256(documento|teléfono)`) en la misma zona dentro de una ventana deslizante < 24 h. Los reportes posteriores se enlazan a la incidencia abierta.
3. **Recibe eventos de AWS** (`POST /events/infra`, idempotente) y los correlaciona con los reportes: origen `ANTENA` / `USUARIOS` / `AMBOS` y tiempo de detección.
4. **Prioriza** con un puntaje explicable `40U + 25Z + 20A + 10D + 5R` → CRÍTICA ≥ 75, ALTA ≥ 50, MEDIA ≥ 25, BAJA.
5. **Orquesta el ciclo de vida** con Durable Functions: `REGISTRADA → EN_REVISION → EN_ATENCION → SOLUCIONADA → CERRADA`, con reapertura, escalamiento al operador y cierre automático.
6. **Notifica** a quienes reportaron en 3 etapas (evaluando → incidencia identificada → restablecido), un mensaje por usuario y etapa. Correo con Azure Communication Services; SMS simulado.
7. **Clasifica y resume con IA** (Gemini vía GCP) con degradación a reglas si GCP falla. Nunca se envían documento, teléfono ni correo.
8. **Exporta a GCP** reportes e incidencias, sin datos personales.
9. **Sirve a la consola de operación** (la construye P3) por API.

## APIs: qué recibe y qué envía Azure

### Recibe (APIs que Azure expone)
| Quién llama | Ruta | Autenticación | Contenido |
|---|---|---|---|
| Usuario | `POST /api/reports` | Pública (esquema + tope de tamaño) | Reporte |
| Usuario | `GET /api/reports/{id}` | Código del reporte | Estado e historial, sin datos personales |
| **AWS** | `POST /events/infra` | `X-API-Key` | Sobre común `antenna.event` con 7 tipos: FALLA, SATURACION, DEGRADACION, RECUPERACION, PREVENTIVA, ESTRUCTURAL, PROLONGADA |
| Operador / consola | `GET/PATCH /api/incidents…`, `PATCH /api/reports/{id}` | `x-operator-token` | Gestión |
| Operador | `GET /api/infra/events`, `POST /api/ops/redrive` | `x-operator-token` | Operación |

### Envía
| Destino | Llamada | Contenido |
|---|---|---|
| **GCP** | `POST /ai/classify-report` | Texto del reporte sin datos personales → categoría, urgencia, sitio crítico (timeout 4 s; si falla, reglas) |
| **GCP** | `POST /ai/summarize-incident` | Datos de la incidencia → resumen, causa probable, acción (timeout 8 s) |
| **GCP** | `POST /ingest/incidents` | `incident.upsert` y `report.upsert` en cada cambio, con `user_key` hash |
| **AWS** | `GET /config` | Configuración global, con caché y valores por defecto |
| **AWS** | `GET /antennas`, `GET /predictions` | Para la consola y la reconciliación (no es ruta crítica) |
| Usuarios | ACS Email (real) y SMS (simulado) | 3 etapas de notificación |

Todas las llamadas entre nubes usan el sobre común (`contracts/events/envelope.schema.json`), entrega al menos una vez y receptores idempotentes por `event_id`. Detalle y ejemplos en [`docs/AZURE.md`](docs/AZURE.md) §3 y §4.

## Estado

Backend, frontend y scripts de despliegue **escritos y probados en local (41 pruebas); nada desplegado todavía**. Falta adaptar el código a los contratos compartidos (zonas `LIM-*`, sobre común, 7 tipos de evento, categorías, endpoints de IA): lista en [`docs/AZURE.md`](docs/AZURE.md) §9. Requisitos RF-AZ-01…33 y su estado en §2 (15 cumplen, 13 parciales, 5 faltan).

## Estructura

```
backend/     Azure Functions (Python 3.12, modelo v2) + Durable Functions
  pulsored/    lógica de negocio (sin dependencias de Azure; testeable)
  blueprints/  http_api.py (REST) y triggers.py (change feed, Service Bus, Durable)
  tests/       41 pruebas
  scripts/     simulate_local.py · aws_simulator.py · load_test.py · seed_zones.py
frontend/    portal de usuario (index.html) y consola de operación base (consola.html), sin build
infra/       deploy.ps1 · smoke_test.ps1 · teardown.ps1
contracts/   contratos compartidos con AWS y GCP (copia de TeleCorp-InfraMonitoring)
docs/        AZURE.md (pilar) · AZURE.drawio · global/ (requisitos, plan y GCP del equipo)
```

## Probar en local (sin Azure)
```powershell
cd backend
py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt pytest
.\.venv\Scripts\python -m pytest -q                # 41 pruebas
.\.venv\Scripts\python scripts\simulate_local.py   # 10 reportes -> incidencia -> orquestación -> correos -> export
```

## Desplegar en Azure
```powershell
az login --use-device-code
.\infra\deploy.ps1          # crea todo, publica backend y frontend (idempotente)
.\infra\smoke_test.ps1
.\infra\teardown.ps1 -Yes   # borra todo
```
`deploy.ps1` escribe `infra\outputs.local.json` (contiene secretos; **no se versiona**). Restricciones de la cuenta (Azure for Students): regiones `westus2`, `canadacentral`, `brazilsouth`, `chilecentral`, `westus`; Cosmos free tier con respaldo a serverless; SMS siempre simulado.

## Configuración (app settings)
| Variable | Para qué | Sin ella |
|---|---|---|
| `COSMOS`, `SB` | Conexión a Cosmos y Service Bus | Memoria local (solo desarrollo) |
| `OPERATOR_TOKEN` | Header `x-operator-token` de la consola | Los endpoints de operador rechazan todo |
| `ACS_CONNECTION_STRING`, `ACS_SENDER` | Correo real | Correo **simulado** |
| `GCP_URL`, `GCP_KEY` | Endpoints de GCP | Exportación en modo **mock** |
| `AI_URL` | Endpoint de IA (Gemini) | IA por **reglas** (`ai_source=rules`) |
| `USERS_THRESHOLD` (10), `OPERATOR_WAIT_MIN` (120), `RECOVERY_POLL_MIN` (5), `COOLDOWN_MIN` (30) | Umbrales y tiempos | Valores entre paréntesis |

> `docs/` es interno y se borra antes de entregar (el enunciado anula a quien entregue un informe).
