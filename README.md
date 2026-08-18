# LinkedIn Candidate Agent

> **Demo técnica.** Automatiza la búsqueda de perfiles públicos de
> LinkedIn a través de un actor de terceros en Apify. El scraping de LinkedIn puede
> infringir sus Términos de Servicio, y los perfiles obtenidos son **datos personales**
> sujetos al RGPD. Quien ejecute este código es el único responsable del uso que le dé,
> de contar con base legal para tratar esos datos y de cumplir la normativa aplicable.

Agente multi-rol con [CrewAI](https://www.crewai.com/) que, dada una **Job Description**, busca candidatos en LinkedIn vía [Apify](https://apify.com/) (`harvestapi/linkedin-profile-search`), los puntúa con un LLM y genera un reporte ejecutivo en Markdown listo para hiring managers.

## Flujo

Entra una Job Description en texto plano, salen dos ficheros. Entre medias, cuatro
agentes en cadena: cada uno hace una sola cosa y recibe como entrada lo que produjo
el anterior.

```mermaid
flowchart TB
  JD[/"Job Description (texto plano)"/]
  T1["1 · JD Analyst<br/>lee la oferta"]
  T2["2 · Boolean Search Expert<br/>traduce a queries y busca"]
  T3["3 · Ranker<br/>puntúa contra la JD"]
  T4["4 · Reporter<br/>redacta el informe"]
  APIFY[["Apify<br/>harvestapi/linkedin-profile-search"]]
  JSON[("candidates_ranked.json")]
  MD[("TOP_CANDIDATES_REPORT.md")]

  JD --> T1
  T1 -- "requisitos en JSON" --> T2
  T2 <-- "queries · perfiles" --> APIFY
  T2 -- "perfiles enriquecidos" --> T3
  T3 -- "candidatos con score" --> T4
  T3 --> JSON
  T4 --> MD
  JD -. "se reinyecta" .-> T3
```

| # | Agente | Recibe | Produce |
|---|--------|--------|---------|
| 1 | JD Analyst | la JD en bruto | JSON con `title`, `must_have_skills`, `nice_to_have`, `min_years_experience`, `location`, `other_criteria` |
| 2 | Boolean Search Expert | ese JSON | búsquedas booleanas ejecutadas contra Apify; devuelve perfiles con `about`, `experience`, `skills`, `education` |
| 3 | Ranker | los perfiles **y la JD original** | cada candidato con `score` 0-100 y su razonamiento |
| 4 | Reporter | los candidatos puntuados | Top 10 con enlace y mensaje de outreach de 3-4 líneas |

Dos detalles del diseño que no se ven en el diagrama:

- `memory=False` y `Process.sequential`: ningún agente arrastra contexto más allá de lo
  que le entrega el anterior. Lo que no esté en ese traspaso, no existe.
- La JD original se **reinyecta** en el paso 3 en lugar de dejar que el ranking se apoye
  en el JSON del paso 1. Así se puntúa contra la oferta real y no contra un resumen que
  ya ha pasado por un LLM.

### Qué pasa cuando Apify falla

Un LLM al que le pides los diez mejores candidatos sin darle datos reales te los
inventa, y los inventa bien: nombres verosímiles y URLs con forma de
`linkedin.com/in/<slug>`. El fallo silencioso es el peor resultado posible aquí, porque
el reporte parece correcto.

Por eso las tareas 2, 3 y 4 llevan una regla explícita que **propaga el error hacia
abajo** en lugar de rellenar el hueco:

```mermaid
flowchart LR
  E["Apify devuelve error<br/>o lista vacía"]
  T2["Tarea 2<br/>APIFY_SEARCH_FAILED: razón"]
  T3["Tarea 3<br/>error + reason, sin candidatos"]
  T4["Tarea 4<br/>Reporte no generado"]

  E --> T2 --> T3 --> T4
```

El resultado es un fichero que dice por qué no hay reporte y qué revisar, en vez de diez
perfiles falsos.

## Stack

- **CrewAI** + provider Gemini nativo (`crewai.LLM`)
- **Apify Actors Tool** (`crewai_tools`)
- **Google Gemini 2.5 Pro** (configurable a Anthropic Claude)
- `python-dotenv` para gestión de secretos

> **Sobre los extras de `requirements.txt`:** CrewAI publica los providers de LLM y la
> integración de Apify como *extras* opcionales, no como dependencias base. Por eso el
> fichero pide `crewai[google-genai,anthropic]` y `crewai-tools[apify]`: sin ellos la
> instalación parece correcta pero el script falla al arrancar con un `ImportError`
> pidiendo `langchain-apify` o el provider nativo correspondiente.

## Requisitos

- Python 3.12
- Una API key de [Google AI Studio](https://aistudio.google.com/app/apikey) (formato `AIzaSy...`)
- Un token de [Apify](https://console.apify.com/settings/integrations) (formato `apify_api_...`)
- El actor [`harvestapi/linkedin-profile-search`](https://console.apify.com/store/harvestapi/linkedin-profile-search) autorizado en tu cuenta. Coste real observado: ~$0.30-0.50 por búsqueda completa.

## Setup

```bash
git clone <url-del-repo>
cd linkedin-candidate-agent

python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edita .env y rellena GOOGLE_API_KEY y APIFY_API_TOKEN
```

## Ejecutar

Edita el bloque `job_description` al final de [`linkedin_agent.py`](linkedin_agent.py) con la JD que quieras analizar y lanza:

```bash
python linkedin_agent.py
```

Salidas en la raíz del proyecto:

- `candidates_ranked.json` — lista de candidatos con score y razonamiento.
- `TOP_CANDIDATES_REPORT.md` — reporte ejecutivo con Top 10 + mensajes de outreach personalizados.

## Cambiar de proveedor LLM

En [`linkedin_agent.py`](linkedin_agent.py) cambia la primera constante:

```python
LLM_PROVIDER = "gemini"  # o "claude"
```

Si eliges `claude`, asegúrate de tener `ANTHROPIC_API_KEY` en `.env`.

## Estructura

```
linkedin-candidate-agent/
├── linkedin_agent.py       # Crew, agentes, tareas y entrypoint
├── requirements.txt
├── .env.example            # Plantilla; copiar a .env y rellenar
├── .gitignore              # Ignora .env, .venv/ y outputs con datos personales
├── LICENSE                 # MIT
└── README.md
```

## Notas de privacidad

Los archivos `TOP_CANDIDATES_REPORT.md` y `candidates_ranked.json` contienen **datos personales reales** scrapeados de LinkedIn (nombres, URLs, experiencia). Están en `.gitignore` deliberadamente para no incluirlos en el repo.

## Licencia

Distribuido bajo licencia [MIT](LICENSE). Se entrega "tal cual", sin garantías.
