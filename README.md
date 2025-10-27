# LLM Summarizer Service

Un microservicio backend diseñado para generar resúmenes de texto utilizando modelos de lenguaje (LLM), priorizando latencia y confiabilidad.

## Características

- ✅ **Arquitectura SOLID**: Código limpio y mantenible
- ✅ **Múltiples proveedores LLM**: OpenAI, Anthropic, Azure OpenAI
- ✅ **Sistema de fallback**: Resumen extractivo con TextRank/TF-IDF
- ✅ **Resiliencia**: Timeouts, retries, circuit breakers
- ✅ **Caché inteligente**: Redis para optimizar latencia
- ✅ **Rate limiting**: Protección contra abuso
- ✅ **Logs estructurados**: JSON logging con seguridad
- ✅ **Documentación OpenAPI**: Disponible en `/docs`

## Arquitectura

```
Cliente → API (FastAPI) → LLM Provider
                    ↓
                Fallback: resumen extractivo
                    ↓
            Logs y métricas opcionales
```

### Componentes principales:

- **API Layer**: Validación, autenticación y endpoints
- **Service Layer**: Lógica de negocio y orquestación
- **Domain Layer**: Entidades e interfaces
- **Infrastructure**: Configuración, logging, cache

## Instalación y Configuración

### Prerrequisitos

- Python 3.9+
- Redis (opcional, para caché y rate limiting)
- Docker y Docker Compose (opcional)

### Instalación local

1. **Clonar el repositorio**:
```bash
git clone <repository-url>
cd test_LLM_macaque
```

2. **Crear entorno virtual**:
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

3. **Instalar dependencias**:
```bash
pip install -r requirements.txt
```

4. **Configurar variables de entorno**:
```bash
cp .env.example .env
# Editar .env con tus configuraciones
```

5. **Ejecutar el servicio**:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Instalación con Docker

**Desarrollo (solo Redis):**
```bash
# Iniciar Redis para desarrollo
docker-compose -f docker-compose.dev.yml up -d

# Ejecutar la aplicación localmente
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Producción (aplicación completa):**
```bash
# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus configuraciones

# Iniciar todos los servicios
docker-compose up -d
```

**Solo Redis (desarrollo local):**
```bash
# Solo Redis para desarrollo local
docker-compose -f docker-compose.dev.yml up redis-dev -d
```

## Configuración

### Variables de entorno principales:

| Variable | Descripción | Valor por defecto |
|----------|-------------|-------------------|
| `API_KEYS_ALLOWED` | Lista de API keys válidas | `[]` |
| `LLM_PROVIDER` | Proveedor LLM (openai/anthropic) | `openai` |
| `PROVIDER_API_KEY` | API key del proveedor LLM | - |
| `REDIS_URL` | URL de Redis (opcional) | `None` |
| `ENABLE_RATE_LIMIT` | Habilitar rate limiting | `false` |

Ver `.env.example` para la lista completa.

## API Endpoints

### POST /v1/summarize

Genera un resumen del texto proporcionado.

**Request:**
```json
{
  "text": "Texto a resumir...",
  "lang": "auto",
  "max_tokens": 100,
  "tone": "neutral"
}
```

**Response:**
```json
{
  "summary": "Resumen generado...",
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 40
  },
  "model": "gpt-3.5-turbo",
  "latency_ms": 900
}
```

### GET /v1/healthz

Verifica el estado del servicio y conectividad.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "version": "1.0.0",
  "checks": {
    "llm_provider": "ok",
    "redis": "ok"
  }
}
```

## Autenticación

El servicio requiere autenticación mediante API Key:

```bash
curl -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"text":"Texto a resumir"}' \
     http://localhost:8000/v1/summarize
```

## Estrategia de Resiliencia

### Timeouts
- Cliente: 10 segundos
- LLM Provider: 8 segundos

### Retries
- Hasta 2 reintentos en errores 429/5xx
- Backoff exponencial

### Fallback
- Resumen extractivo automático si LLM falla
- Algoritmos: TextRank y TF-IDF

### Circuit Breaker
- Protección contra proveedores no disponibles
- Recuperación automática

## Desarrollo

### Estructura del proyecto

```
app/
├── core/           # Configuración y utilidades base
├── domain/         # Entidades e interfaces
├── services/       # Lógica de negocio
├── api/           # Endpoints y middleware
└── utils/         # Utilidades auxiliares
```

### Principios SOLID aplicados

- **SRP**: Cada clase tiene una responsabilidad única
- **OCP**: Extensible sin modificar código existente
- **LSP**: Implementaciones intercambiables
- **ISP**: Interfaces específicas
- **DIP**: Inyección de dependencias

### Ejecutar tests

```bash
pytest tests/ -v --cov=app
```

### Formateo de código

```bash
black app/
isort app/
flake8 app/
```

## Monitoreo y Logs

### Logs estructurados (JSON)
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "level": "INFO",
  "service": "LLM Summarizer Service",
  "message": "Summary generated successfully",
  "request_id": "req-123",
  "latency_ms": 850
}
```

### Métricas disponibles
- Latencia de respuesta
- Tasa de éxito/error
- Uso de tokens
- Rate limiting

## Decisiones Técnicas

### Latencia
1. **Caché Redis**: Evita llamadas repetidas al LLM
2. **Timeouts optimizados**: Balance entre velocidad y confiabilidad
3. **Conexiones persistentes**: Reutilización de conexiones HTTP

### Confiabilidad
1. **Sistema de fallback**: Garantiza respuesta siempre
2. **Retries inteligentes**: Solo en errores recuperables
3. **Circuit breaker**: Protección contra cascading failures
4. **Validación estricta**: Prevención de errores

### Escalabilidad
1. **Arquitectura stateless**: Fácil escalado horizontal
2. **Inyección de dependencias**: Testeable y mantenible
3. **Configuración externa**: 12-factor app compliance

## Contribución

1. Fork el proyecto
2. Crear una rama feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit los cambios (`git commit -am 'Agregar nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crear un Pull Request

## Licencia

[Especificar licencia]
