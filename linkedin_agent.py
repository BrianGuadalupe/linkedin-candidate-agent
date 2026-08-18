import os

from crewai import LLM, Agent, Crew, Process, Task
from crewai_tools import ApifyActorsTool
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(override=True)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. Configúrala antes de ejecutar el crew."
        )
    return value


# ===================== CONFIGURACIÓN =====================
LLM_PROVIDER = "gemini"  # Opciones: "claude" o "gemini"

if LLM_PROVIDER == "claude":
    _require_env("ANTHROPIC_API_KEY")
elif LLM_PROVIDER == "gemini":
    _require_env("GOOGLE_API_KEY")
else:
    raise ValueError("LLM_PROVIDER debe ser 'claude' o 'gemini'")

_require_env("APIFY_API_TOKEN")

# Selección del LLM (CrewAI usa litellm internamente; el modelo va con prefijo de provider)
if LLM_PROVIDER == "claude":
    llm = LLM(model="anthropic/claude-3-5-sonnet-20241022", temperature=0.1)
    print("🚀 Usando Claude 3.5 Sonnet")
elif LLM_PROVIDER == "gemini":
    llm = LLM(model="gemini/gemini-2.5-pro", temperature=0.1)
    print("🚀 Usando Gemini 2.5 Pro Preview")

# ===================== TOOLS =====================
# harvestapi/linkedin-profile-search ya devuelve perfiles enriquecidos
# (about, experience, skills, education, languages...) en una sola llamada,
# por eso no usamos un scraper adicional.
search_tool = ApifyActorsTool(actor_name="harvestapi/linkedin-profile-search")


# ===================== MODELOS =====================
class Candidate(BaseModel):
    name: str
    headline: str
    url: str
    score: int
    reasoning: str


# ===================== AGENTES =====================
jd_analyzer = Agent(
    role="Senior JD Analyst",
    goal="Extraer requisitos clave de una Job Description de forma estructurada",
    backstory="Eres un headhunter con 15 años de experiencia. Extraes información con precisión quirúrgica.",
    llm=llm,
    verbose=True,
)

search_generator = Agent(
    role="LinkedIn Boolean Search Expert",
    goal="Crear búsquedas ultra-efectivas en LinkedIn",
    backstory="Dominas las búsquedas booleanas avanzadas y filtros de LinkedIn.",
    llm=llm,
    tools=[search_tool],
    verbose=True,
)

ranker = Agent(
    role="Candidate Ranker",
    goal="Evaluar y rankear candidatos del 0 al 100 con razonamiento detallado",
    backstory="Eres extremadamente exigente y objetivo. Siempre explicas por qué un candidato encaja o no.",
    llm=llm,
    verbose=True,
)

reporter = Agent(
    role="Professional Recruiter Report Writer",
    goal="Generar reportes claros, accionables y profesionales",
    backstory="Creas reportes que los hiring managers aman leer.",
    llm=llm,
    verbose=True,
)


# ===================== TAREAS =====================
task1 = Task(
    description=(
        "Analiza la siguiente Job Description y devuelve SOLO un JSON con: "
        "title, must_have_skills (lista), nice_to_have (lista), min_years_experience, "
        "location, other_criteria.\n\n"
        "{job_description}"
    ),
    expected_output="JSON estructurado",
    agent=jd_analyzer,
)

task2 = Task(
    description=(
        "Usando el análisis anterior, genera 2-3 búsquedas booleanas óptimas y "
        "ejecútalas con la herramienta de Apify (harvestapi/linkedin-profile-search). "
        "Devuelve los perfiles ENRIQUECIDOS completos tal y como los entrega la "
        "herramienta, conservando los campos relevantes para el ranking: "
        "linkedinUrl, firstName, lastName, headline, location, about, currentPosition, "
        "experience, skills, education, languages.\n\n"
        "REGLA INVIOLABLE: si la herramienta de Apify devuelve un error (permisos, "
        "saldo, formato) o una lista vacía, NO INVENTES perfiles. Devuelve exactamente "
        "este texto: 'APIFY_SEARCH_FAILED: <razón>' donde <razón> es el mensaje de "
        "error literal que recibiste de la herramienta."
    ),
    expected_output=(
        "Lista de perfiles REALES enriquecidos (con about/experience/skills) "
        "tal y como vienen del actor harvestapi, o cadena "
        "'APIFY_SEARCH_FAILED: <razón>' si la herramienta falló."
    ),
    agent=search_generator,
)

task4 = Task(
    description=(
        "Rankea cada candidato del 0-100 según la Job Description original reproducida "
        "abajo (no inventes criterios que no estén en ella). Devuelve lista ordenada "
        "con score y razonamiento detallado.\n\n"
        "REGLA INVIOLABLE: si la entrada empieza por 'APIFY_SEARCH_FAILED:' o no hay "
        "perfiles reales, NO INVENTES candidatos. Devuelve un JSON: "
        "{'error': 'APIFY_SEARCH_FAILED', 'reason': '<razón>'}.\n\n"
        "{job_description}"
    ),
    expected_output=(
        "Lista de candidatos REALES con score y explicación, "
        "o JSON con error si no hubo datos."
    ),
    agent=ranker,
    output_json_file="candidates_ranked.json",
)

task5 = Task(
    description=(
        "Crea un reporte Markdown profesional con los Top 10 candidatos. Incluye: "
        "nombre, headline, score, por qué encaja, enlace LinkedIn (URL real "
        "linkedin.com/in/<slug>) y mensaje de outreach personalizado (máximo 3-4 líneas).\n\n"
        "REGLA INVIOLABLE: si la entrada contiene 'APIFY_SEARCH_FAILED' o no hay "
        "candidatos REALES con URLs reales de linkedin.com, NO INVENTES candidatos. "
        "En ese caso devuelve EXACTAMENTE este Markdown:\n\n"
        "# Reporte no generado\n\n"
        "**Motivo:** la herramienta de Apify no devolvió perfiles reales.\n\n"
        "**Detalle del error:** <razón propagada desde tareas anteriores>\n\n"
        "**Acción requerida:** revisar permisos y saldo de los actores en "
        "https://console.apify.com/store y volver a lanzar."
    ),
    expected_output=(
        "Reporte Markdown con candidatos REALES, "
        "o el Markdown de 'Reporte no generado' si la búsqueda falló."
    ),
    agent=reporter,
    output_file="TOP_CANDIDATES_REPORT.md",
)

# ===================== CREW =====================
crew = Crew(
    agents=[jd_analyzer, search_generator, ranker, reporter],
    tasks=[task1, task2, task4, task5],
    process=Process.sequential,
    verbose=True,
    memory=False,
)


# ===================== EJECUCIÓN =====================
if __name__ == "__main__":
    # JD de ejemplo (ficticia). Sustitúyela por la oferta que quieras analizar.
    job_description = """
    Buscamos un/a Analista de Proyectos Web para el equipo de Business Technology.
    Definirás y coordinarás la evolución técnica de nuestras plataformas digitales,
    asegurando que escalen con el crecimiento del negocio.

    Actuarás como puente entre los stakeholders de negocio y los equipos técnicos,
    traduciendo estrategia comercial en especificaciones implementables. El alcance
    cubre e-Commerce B2C, portales mayoristas B2B y sistemas de punto de venta (POS).

    ## Funciones principales

    - Gestión del ciclo de vida del proyecto: definir alcance, coordinar tareas de
      desarrollo y supervisar la implementación técnica.
    - Traducción de negocio a técnico: recopilar requisitos y convertirlos en
      especificaciones claras para los equipos de desarrollo.
    - Gestión de stakeholders: mantener comunicación fluida con equipos internos y
      garantizar la adopción de nuevos procesos.
    - Diseño de soluciones y coordinación con proveedores y agencias externas.
    - Mantenimiento operativo y evolutivos posteriores al lanzamiento.
    - Quality Assurance: validar que cada entregable resuelve el problema definido.

    ## Requisitos

    - Experiencia demostrable conectando necesidades de negocio con ejecución técnica
      (Analista funcional, Product Owner o Technical Project Manager).
    - Fluidez técnica: tecnologías web (HTML, CSS, JS/React) y conceptos de backend
      (Java, SQL).
    - Iniciativa, aprendizaje autónomo y mentalidad colaborativa.
    - Nivel profesional de inglés y español.
    - Valorable: estrategias SEO, sistemas ERP (SAP) o software POS, y side-projects
      técnicos propios.
    """

    print(f"🚀 Iniciando agente con {LLM_PROVIDER.upper()}...")
    result = crew.kickoff(inputs={"job_description": job_description})
    print("\n✅ ¡Reporte generado correctamente!")
    print("📁 Archivo: TOP_CANDIDATES_REPORT.md")
    print("📊 Datos rankeados: candidates_ranked.json")
