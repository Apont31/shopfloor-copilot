"""Assistant procédures : questions-réponses sur les documents, avec sources.

Principe du projet : une règle déterministe dès qu'elle existe, le LLM pour retrouver et rédiger, des sources
toujours citées.
1. Question sur une tolérance (pièce + caractéristique reconnues) : réponse lue dans le référentiel
   (tolerances.yaml), sans aucun appel au LLM.
2. Sinon : recherche de passages (RAG), puis le LLM répond uniquement à partir de ces passages. Sa réponse passe
   par un garde-fou (check_reponse, fonction pure) ; rejetée ou illisible, elle est remplacée par les meilleurs
   passages.
3. Contexte insuffisant (aucun passage assez proche, ou le LLM ne trouve pas) : refus explicite.
"""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shopfloor.agent.guard import GuardResult, affirme_conformite
from shopfloor.agent.nodes import Retriever
from shopfloor.errors import OLLAMA_INDISPONIBLE, RAG_INDISPONIBLE, OllamaUnavailableError
from shopfloor.llm.assistant_prompts import build_assistant_prompt, build_assistant_retry, reponse_json_schema
from shopfloor.llm.client import LLMClient, LLMError
from shopfloor.models import ToleranceSpec, ToleranceTable
from shopfloor.rag.retriever import RetrievedChunk
from shopfloor.ui.format import fmt_mesure, libelle_caracteristique

RETRIEVE_K = 8
EXTRAITS_K = 3  # passages affichés quand la réponse du LLM n'est pas fiable
MAX_LLM_CALLS = 2  # un appel, une relance au maximum (JSON invalide)
# Similarité cosinus minimale du meilleur passage : en dessous, la question est hors corpus et le LLM n'est pas
# appelé. Simple filet : avec nomic-embed-text, des questions hors corpus atteignent 0.78 et des questions du
# corpus descendent à 0.70 ; le refus principal vient donc du LLM (trouve = false).
SEUIL_SCORE = 0.6

REFUS = "Je ne trouve pas cette information dans les documents."
PAS_FIABLE = "Je n'ai pas pu formuler de réponse fiable ; voici les extraits pertinents."
SECTION_TOLERANCES = "Tolérances"  # section des procédures qui reprend le tableau du référentiel


class AssistantError(Exception):
    """Service indisponible (Ollama, index RAG) : le message dit quoi faire."""


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    section: str


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    texte: str
    sources: tuple[Source, ...] = ()
    origine: Literal["referentiel", "llm", "passages"]
    refus: bool = False
    passages: tuple[RetrievedChunk, ...] = ()  # extraits à afficher avec la réponse
    llm_calls: int = 0
    motifs: tuple[str, ...] = ()  # pourquoi la réponse du LLM a été écartée (origine « passages »)


class ReponseLLM(BaseModel):
    """Sortie attendue du LLM (schéma : shopfloor.llm.assistant_prompts.REPONSE_JSON_SCHEMA)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trouve: bool
    texte: str
    sources: tuple[Source, ...] = Field(default=())


@dataclass(frozen=True, kw_only=True)
class AssistantDeps:
    tolerances: ToleranceTable
    retriever: Retriever
    llm: LLMClient | None = None


# --- Normalisation ---------------------------------------------------------------------------------------------

_TIRETS = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_APOSTROPHES = dict.fromkeys(map(ord, "’‘`´"), "'")


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, tirets et apostrophes unifiés, espaces simples."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.translate(_TIRETS).translate(_APOSTROPHES).lower()
    return re.sub(r"\s+", " ", texte).strip()


# --- a. Tolérances : réponse déterministe lue dans le référentiel ---------------------------------------------

# Vocabulaire seulement (aucune valeur) : formulations normalisées -> code de caractéristique du référentiel.
# Le code lui-même (« angle_pli » ou « angle pli ») est toujours reconnu.
SYNONYMES: dict[str, tuple[str, ...]] = {
    "epaisseur": ("epaisseur", "epaisseurs", "epaisseur du panneau", "epaisseur de la piece"),
    "porosite": ("porosite", "porosites", "taux de porosite"),
    "temperature_cuisson": ("temperature de cuisson", "temperature", "temperatures"),
    "angle_pli": ("angle de pli", "angle de pliage", "angles de pli", "angle"),
    "longueur": ("longueur", "longueurs"),
    "planeite": ("planeite", "planite", "planarite", "platitude"),
    "epaisseur_film": ("epaisseur de film", "epaisseur du film", "epaisseur de film sec", "film sec",
                       "epaisseur de peinture", "epaisseur de poudre", "epaisseur de revetement", "epaisseur"),
    "adherence": ("adherence", "quadrillage"),
    "brillance": ("brillance", "brillant", "gloss"),
    "rugosite": ("rugosite",),
}
# Une question « vise une tolérance » si elle contient l'un de ces mots (sinon : RAG, par exemple « comment
# mesurer la porosité du CP-210 ? »).
_INTENTION = re.compile(
    r"\b(tolerances?|toleree?s?|max|maxi|maximum|maximale?s?|min|mini|minimum|minimale?s?|limites?|bornes?"
    r"|seuils?|plage|intervalle|nominale?s?|valeurs?|admissibles?|admise?s?|acceptables?|autorisee?s?|combien)\b"
)
# « hors tolérance » décrit un écart (historique de NC), pas une demande de bornes ; « pourquoi » et « comment »
# demandent une cause ou une méthode : ces questions vont au RAG.
_HORS_TOLERANCE = re.compile(r"\b(hors|en dehors des?|sorti\w* de( la)?) tolerances?\b")
_CAUSE_OU_METHODE = re.compile(r"^\W*(pourquoi|comment)\b")


def _motif_mot(forme: str) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(forme)}(?!\w)")


def _motif_piece(part_ref: str) -> re.Pattern:
    """« CP-210 » reconnu aussi en « cp 210 », « cp210 », « CP_210 »."""
    morceaux = [re.escape(m) for m in re.split(r"[-_\s]+", normaliser(part_ref)) if m]
    return re.compile(r"(?<![a-z0-9])" + r"[-_\s]?".join(morceaux) + r"(?![a-z0-9])")


def pieces_citees(question: str, table: ToleranceTable) -> list[str]:
    norm = normaliser(question)
    refs = dict.fromkeys(s.part_ref for s in table.specs)
    trouvees = [(m.start(), ref) for ref in refs if (m := _motif_piece(ref).search(norm))]
    return [ref for _, ref in sorted(trouvees)]


def caracteristiques_citees(question: str, table: ToleranceTable) -> list[tuple[str, ...]]:
    """Caractéristiques citées, dans l'ordre du texte : pour chaque mention, les codes possibles.

    La formulation la plus longue l'emporte : « épaisseur de film » donne (epaisseur_film,). Une formulation
    partagée garde tous ses codes, dans l'ordre de SYNONYMES : « épaisseur » donne (epaisseur, epaisseur_film),
    départagés ensuite par la pièce.
    """
    norm = normaliser(question)
    formes: dict[str, set[str]] = {code: set(f) for code, f in SYNONYMES.items()}
    for s in table.specs:
        formes.setdefault(s.caracteristique, set()).update({s.caracteristique, s.caracteristique.replace("_", " ")})
    spans: dict[tuple[int, int], list[str]] = {}
    for code, fs in formes.items():
        for f in fs:
            for m in _motif_mot(f).finditer(norm):
                codes = spans.setdefault(m.span(), [])
                if code not in codes:
                    codes.append(code)
    retenues: list[tuple[int, int]] = []
    for debut, fin in sorted(spans, key=lambda s: s[0] - s[1]):  # plus longues d'abord
        if all(fin <= d or debut >= f for d, f in retenues):
            retenues.append((debut, fin))
    return list(dict.fromkeys(tuple(spans[s]) for s in sorted(retenues)))


def _de(libelle: str) -> str:
    """« de porosité », « d'épaisseur », « d'angle de pli »."""
    return f"d'{libelle}" if normaliser(libelle[:1]) in "aeiouyh" else f"de {libelle}"


def vise_une_tolerance(question: str) -> bool:
    norm = normaliser(question)
    if _CAUSE_OU_METHODE.search(norm):
        return False
    return bool(_INTENTION.search(_HORS_TOLERANCE.sub(" ", norm)))


def _valeur(v: Decimal, unite: str) -> str:
    return f"classe {v}" if unite == "classe" else fmt_mesure(v, unite)


def bornes_lisibles(spec: ToleranceSpec) -> str:
    """« de 3.05 à 3.35 mm, nominal 3.20 mm », « au plus 2.0 % », « au moins 60 µm » : bornes incluses."""
    if spec.min is not None and spec.max is not None:
        min_txt = str(spec.min) if spec.unite != "classe" else _valeur(spec.min, spec.unite)
        texte = f"de {min_txt} à {_valeur(spec.max, spec.unite)}"
    elif spec.max is not None:
        texte = f"au plus {_valeur(spec.max, spec.unite)}"
    else:
        texte = f"au moins {_valeur(spec.min, spec.unite)}"
    if spec.nominal is not None:
        texte += f", nominal {_valeur(spec.nominal, spec.unite)}"
    return texte


def reponse_referentiel(question: str, table: ToleranceTable) -> Answer | None:
    """Réponse lue dans le référentiel si la question vise une tolérance d'une pièce connue, sinon None.

    Une caractéristique sans tolérance pour cette pièce est dite absente : rien n'est jamais déduit ni inventé.
    """
    if not vise_une_tolerance(question):
        return None
    pieces = pieces_citees(question, table)
    caracs = caracteristiques_citees(question, table)
    if not pieces or not caracs:
        return None
    lignes: list[str] = []
    sources: list[Source] = []
    for part_ref in pieces:
        for codes in caracs:
            spec = next((s for c in codes if (s := table.get(part_ref, c)) is not None), None)
            if spec is None:
                libelle = libelle_caracteristique(codes[0]).lower()
                lignes.append(f"Le référentiel ne définit aucune tolérance {_de(libelle)} pour la pièce {part_ref}.")
                continue
            libelle = libelle_caracteristique(spec.caracteristique)
            lignes.append(f"{libelle} de la pièce {part_ref} : {bornes_lisibles(spec)} (bornes incluses).")
            source = Source(doc_id=spec.source, section=SECTION_TOLERANCES)
            if source not in sources:
                sources.append(source)
    return Answer(texte="\n".join(lignes), sources=tuple(sources), origine="referentiel")


# --- c. Garde-fou de la réponse du LLM (fonction pure) --------------------------------------------------------

_NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")


def nombres(texte: str) -> set[Decimal]:
    """Nombres d'un texte, virgule ou point décimal : « 3,1 » et « 3.10 » donnent la même valeur."""
    out: set[Decimal] = set()
    for brut in _NOMBRE.findall(texte):
        try:
            out.add(Decimal(brut.replace(",", ".")).normalize())
        except InvalidOperation:  # pragma: no cover - le motif ne capture que des chiffres
            continue
    return out


def _cle_source(doc_id: str, section: str) -> tuple[str, str]:
    return normaliser(doc_id), normaliser(section)


def check_reponse(reponse: ReponseLLM, passages: Iterable[RetrievedChunk]) -> GuardResult:
    """Rejette une réponse qui cite une source hors des passages fournis, contient un nombre absent des passages
    ou affirme qu'une pièce est conforme. Aucun LLM ni I/O."""
    passages = list(passages)
    motifs: list[str] = []

    connues = {_cle_source(c.doc_id, c.section) for c in passages}
    inventees = [f"{s.doc_id} ({s.section})" for s in reponse.sources if _cle_source(s.doc_id, s.section) not in connues]
    if inventees:
        motifs.append(f"source(s) absente(s) des passages retrouvés : {', '.join(inventees)}")

    if reponse.trouve:
        if not reponse.texte.strip():
            motifs.append("réponse vide")
        if not reponse.sources:
            motifs.append("réponse sans source")
        absents = nombres(reponse.texte) - set().union(*(nombres(c.text) for c in passages))
        if absents:
            motifs.append(f"nombre(s) absent(s) des passages : {', '.join(sorted(map(str, absents)))}")
        if affirme_conformite(reponse.texte):
            motifs.append("la réponse affirme qu'une pièce est conforme")

    return GuardResult(ok=not motifs, motifs=tuple(motifs))


# --- b. RAG puis LLM ---------------------------------------------------------------------------------------------


def _decrire(e: ValueError) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'racine'} : {err['msg']}" for err in e.errors())
    return str(e)


def parse_reponse(raw: str) -> ReponseLLM:
    """JSON brut du LLM -> ReponseLLM. Lève ValueError si invalide."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("un objet JSON est attendu")
    return ReponseLLM.model_validate(data)


def _extraits(passages: list[RetrievedChunk], llm_calls: int, motifs: list[str]) -> Answer:
    top = passages[:EXTRAITS_K]
    return Answer(
        texte=PAS_FIABLE,
        sources=tuple(dict.fromkeys(Source(doc_id=c.doc_id, section=c.section) for c in top)),
        origine="passages",
        passages=tuple(top),
        llm_calls=llm_calls,
        motifs=tuple(motifs),
    )


def _refus(origine: Literal["llm", "passages"], llm_calls: int = 0) -> Answer:
    return Answer(texte=REFUS, origine=origine, refus=True, llm_calls=llm_calls)


def answer(question: str, deps: AssistantDeps, *, seuil: float = SEUIL_SCORE) -> Answer:
    """Répond à une question d'opérateur. Lève AssistantError si l'index RAG ou Ollama (embeddings) manque."""
    question = question.strip()
    if not question:
        raise ValueError("question vide")

    deterministe = reponse_referentiel(question, deps.tolerances)
    if deterministe is not None:
        return deterministe

    try:
        chunks = deps.retriever(question, None, RETRIEVE_K)
    except OllamaUnavailableError as e:
        raise AssistantError(OLLAMA_INDISPONIBLE) from e
    except Exception as e:  # index absent ou Chroma indisponible
        raise AssistantError(RAG_INDISPONIBLE) from e
    passages = sorted(chunks, key=lambda c: c.score, reverse=True)
    if not passages or passages[0].score < seuil:
        return _refus("passages")
    if deps.llm is None:
        return _extraits(passages, 0, ["aucun LLM configuré"])

    system, user = build_assistant_prompt(question, passages)
    schema = reponse_json_schema()
    prompt = user
    motifs: list[str] = []
    calls = 0
    while calls < MAX_LLM_CALLS:
        calls += 1
        try:
            raw = deps.llm.complete_json(system, prompt, schema)
        except LLMError as e:
            motifs.append(str(e) if isinstance(e, OllamaUnavailableError) else f"appel LLM en échec : {e}")
            break
        try:
            reponse = parse_reponse(raw)
        except ValueError as e:
            motifs.append(f"réponse LLM invalide (appel {calls}) : {_decrire(e)}")
            prompt = build_assistant_retry(user, _decrire(e))
            continue
        guard = check_reponse(reponse, passages)
        if not guard.ok:
            return _extraits(passages, calls, list(guard.motifs))
        if not reponse.trouve:
            return _refus("llm", calls)
        cles = {_cle_source(s.doc_id, s.section) for s in reponse.sources}
        # Sources réécrites avec l'orthographe exacte des passages (le garde-fou compare sans accents ni casse).
        sources = tuple(dict.fromkeys(
            Source(doc_id=c.doc_id, section=c.section) for c in passages if _cle_source(c.doc_id, c.section) in cles
        ))
        cites = tuple(c for c in passages if _cle_source(c.doc_id, c.section) in cles)
        return Answer(texte=reponse.texte.strip(), sources=sources, origine="llm", passages=cites, llm_calls=calls)
    return _extraits(passages, calls, motifs)
