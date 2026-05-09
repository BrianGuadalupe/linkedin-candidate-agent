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
    job_description = """
    Buscamos un Analista de Proyectos Web para unirse al equipo de Business Technology donde definirás y coordinarás la evolución técnica de nuestras plataformas, asegurando que sean escalables para soportar el crecimiento previsto.

Actuarás como el puente vital entre nuestros stakeholders de negocio y los equipos técnicos, traduciendo las estrategias comerciales en realidades técnicas. Tu alcance incluye nuestras plataformas de e-Commerce directo al consumidor (DTC), nuestros portales Mayoristas B2B y nuestros sistemas de Punto de Venta Minorista (POS).

Te centrarás en refinar los procesos internos, gestionar los requisitos y testear los desarrollos para garantizar que todos los entregables cumplan con los estándares de calidad y se alineen perfectamente con las necesidades del negocio.

## Funciones principales.

Gestión del Ciclo de Vida del Proyecto: Definir el alcance de los proyectos, gestionar las tareas de desarrollo y supervisar la implementación técnica de las soluciones. Serás responsable de la planificación, el enfoque técnico y los estándares de calidad del producto final.
Traducción de Negocio a Técnico: Recopilar requisitos con los stakeholders. Traducir estas necesidades en especificaciones técnicas claras para que los equipos de desarrollo las implementen.
Gestión de Stakeholders: Mantener canales de comunicación abiertos y fluidos con diversos equipos internos para garantizar que los nuevos procesos se adopten adecuadamente y se alineen con la estrategia de la empresa.
Diseño de Soluciones y Coordinación de Proveedores: Proponer soluciones técnicas escalables y coordinar con socios/agencias externos para su implementación.
Mantenimiento Operacional: Supervisarás el mantenimiento operativo y las actualizaciones evolutivas después del lanzamiento.
Garantía de Calidad (Quality Assurance): Asegurar que todos los entregables funcionen correctamente y resuelvan los problemas comerciales específicos identificados durante la fase de definición del alcance.

## Requisitos.

Experiencia: Experiencia demostrable en la conexión entre las necesidades del negocio y la ejecución técnica (p. ej., como Analista de software, Product Owner o gestor de Proyecto Técnico).
Fluidez Técnica: Conocimiento demostrable de tecnologías web (HTML, CSS, JS/React) y conceptos de backend (Java, SQL).
Habilidades Interpersonales (Soft Skills): Fuerte iniciativa, capacidad de aprendizaje autónomo y una mentalidad colaborativa de trabajo en equipo.
Idiomas/residencia: Se requiere un nivel profesional de inglés y español y residir en Mallorca.
Conocimiento de estrategias SEO/GEO.
Experiencia con sistemas ERP (específicamente SAP) o software de Punto de Venta Minorista (POS).
Proactividad y con experiencia en proyectos tecnológicos personales paralelos (side-projects).
    """

    print(f"🚀 Iniciando agente con {LLM_PROVIDER.upper()}...")
    result = crew.kickoff(inputs={"job_description": job_description})
    print("\n✅ ¡Reporte generado correctamente!")
    print("📁 Archivo: TOP_CANDIDATES_REPORT.md")
    print("📊 Datos rankeados: candidates_ranked.json")
