"""Ligne de commande.

python -m shopfloor.cli ingest
python -m shopfloor.cli search "requête" [--k 4] [--domaine composite]
python -m shopfloor.cli process <fiche> [--llm ollama|none] [--erp-url URL] [--valide-par NOM] [--decision approve|reject]
python -m shopfloor.cli run-inbox [--llm ollama|none] [--erp-url URL] [--inbox DOSSIER]
python -m shopfloor.cli pending
python -m shopfloor.cli decide <nc_id> approve|reject|edit [--action "..."] --valide-par NOM [--commentaire "..."]
python -m shopfloor.cli retry <nc_id>
python -m shopfloor.cli reset [--yes]
python -m shopfloor.cli ask "question"
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from chromadb.errors import NotFoundError

from shopfloor.agent.graph import Deps, build_graph, get_state, resume, start
from shopfloor.assistant import AssistantDeps, AssistantError, answer
from shopfloor.agent.state import AgentState, HumanDecision
from shopfloor.config import Settings
from shopfloor.erp.client import ErpClient, ErpError
from shopfloor.errors import RAG_INDISPONIBLE, OllamaUnavailableError
from shopfloor.llm.chrono import ChronoLLM
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import make_retriever, retrieve_similar
from shopfloor.service import Service, ServiceError, inbox_files
from shopfloor.ui.format import (
    LIBELLES_ORIGINE_ASSISTANT,
    fmt_mesure,
    libelle_caracteristique,
    libelle_procede,
    libelle_verdict,
)

ROOT = Path(__file__).resolve().parents[2]
TOLERANCES_PATH = ROOT / "config" / "tolerances.yaml"
INBOX_DIR = ROOT / "data" / "nc_inbox"

Decide = Callable[[dict], HumanDecision | dict]


# --- process : logique testable -------------------------------------------------------------------


def _fmt(v) -> str:
    return "-" if v is None else str(v)


# Affichage uniquement (libellés et unités : shopfloor.ui.format) : le YAML, les modèles et l'oracle gardent les codes.
def _print_oracle(state: AgentState) -> None:
    oracle = state.oracle
    print(f"Fiche {oracle.nc_id} - pièce {state.nc.part_ref}, procédé {libelle_procede(state.nc.procede)}")
    print(f"Verdict de l'oracle : {libelle_verdict(oracle.verdict.value)}")
    rows = [("Caractéristique", "Valeur", "Min", "Max", "Écart", "Statut")]
    rows += [
        (libelle_caracteristique(d.caracteristique), fmt_mesure(d.valeur, d.unite), _fmt(d.min), _fmt(d.max),
         fmt_mesure(d.ecart, d.unite), libelle_verdict(d.statut.value))
        for d in oracle.details
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip())


def _print_similar(state: AgentState) -> None:
    if not state.similar:
        print("\nDocuments similaires : aucun (pas de recherche pour ce verdict)")
        return
    print("\nDocuments similaires :")
    for c in state.similar:
        print(f"  {c.doc_id:<13} score={c.score:.3f}  ({c.section})")


def _print_proposal(state: AgentState, chrono: ChronoLLM | None) -> None:
    p = state.proposal
    print(f"\nProposition (origine : {p.origine})")
    print(f"  Résumé             : {p.resume}")
    print(f"  Cause probable     : {p.cause_probable}")
    print(f"  Action corrective  : {p.action_corrective}")
    print(f"  Décision suggérée  : {p.decision_suggeree}")
    print(f"  Sources            : {', '.join(p.sources) or 'aucune'}")
    if state.guard is not None and not state.guard.ok:
        print("\nALERTE garde-fou :")
        for m in state.guard.motifs:
            print(f"  - {m}")
    if chrono is None or not chrono.durations:
        print("\nAppel LLM : aucun")
    else:
        detail = " + ".join(f"{d:.1f} s" for d in chrono.durations)
        print(f"\nAppel LLM : {sum(chrono.durations):.1f} s ({len(chrono.durations)} appel(s) : {detail})")


def run_process(path: str | Path, deps: Deps, decide: Decide) -> int:
    """Traite une fiche de bout en bout. Renvoie le code de sortie : 0 succès, 1 erreur."""
    chrono = ChronoLLM(deps.llm) if deps.llm is not None else None
    graph = build_graph(replace(deps, llm=chrono) if chrono is not None else deps)
    config = start(graph, path)
    state = get_state(graph, config)

    if state.oracle is not None:
        _print_oracle(state)
    if state.error is None:
        _print_similar(state)
        _print_proposal(state, chrono)
        [pending] = graph.get_state(config).interrupts
        try:
            decision = decide(pending.value)
        except (EOFError, KeyboardInterrupt):
            print("\nERREUR : traitement interrompu sans décision, aucun ticket créé.")
            return 1
        resume(graph, config, decision)
        state = get_state(graph, config)

    if state.error is not None:
        message = state.error
        if message == "ERP indisponible":
            message += f" : serveur injoignable à {deps.erp.base_url} (lancez le serveur ERP)"
        print(f"\nERREUR : {message}")
        return 1
    if state.ticket is not None:
        print(f"\nTicket créé : {state.ticket.id}")
        return 0
    print("\nProposition rejetée : aucun ticket créé.")
    return 0


def ask_decision(payload: dict, valide_par: str | None = None, input_fn=input) -> HumanDecision:
    """Décision interactive : [a]pprouver / [m]odifier / [r]ejeter."""
    while not (valide_par and valide_par.strip()):
        valide_par = input_fn("Validé par : ")
    while True:
        choix = input_fn("[a]pprouver / [m]odifier / [r]ejeter ? ").strip().lower()
        if choix in ("a", "approuver"):
            return HumanDecision(decision="approve", valide_par=valide_par)
        if choix in ("m", "modifier"):
            action = input_fn("Nouvelle action corrective : ").strip()
            if action:
                return HumanDecision(decision="edit", action_corrective=action, valide_par=valide_par)
            print("Action vide : choix annulé.")
        elif choix in ("r", "rejeter"):
            commentaire = input_fn("Commentaire (facultatif) : ").strip() or None
            return HumanDecision(decision="reject", valide_par=valide_par, commentaire=commentaire)
        else:
            print("Choix invalide : tapez a, m ou r.")


# --- run-inbox, pending, decide : logique testable ------------------------------------------------


def _table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip())


def _fmt_ms(ms: int | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f} s"


def run_inbox(service: Service, inbox_dir: str | Path) -> int:
    """Traite toute la boîte de réception et affiche le récapitulatif. Code 1 si une fiche est en erreur."""
    total = len(inbox_files(inbox_dir))
    results = service.process_inbox(inbox_dir)
    print(f"Boîte de réception : {inbox_dir}")
    print(f"{total} fiche(s), {len(results)} traitée(s), {total - len(results)} déjà journalisée(s) ignorée(s)")
    if not results:
        return 0
    print()
    rows = [("Fiche", "Verdict", "Statut", "Origine", "LLM", "Détail")]
    rows += [(r.nc_id, libelle_verdict(r.verdict), r.statut, r.origine, _fmt_ms(r.llm_ms), r.erreur or "") for r in results]
    _table(rows)
    statuts: dict[str, int] = {}
    for r in results:
        statuts[r.statut] = statuts.get(r.statut, 0) + 1
    print("\nRécapitulatif : " + ", ".join(f"{n} {s}" for s, n in statuts.items()))
    llm_ms = [r.llm_ms for r in results if r.llm_ms is not None]
    print(f"Appels LLM : {_fmt_ms(sum(llm_ms)) if llm_ms else 'aucun'}")
    return 1 if "erreur" in statuts else 0


def print_pending(service: Service) -> int:
    items = service.list_pending()
    print(f"File de validation : {len(items)} fiche(s) en attente")
    for it in items:
        run = it.run
        print(f"\n{run.nc_id}  {libelle_verdict(it.verdict)}  - pièce {run.part_ref} "
              f"({libelle_procede(run.procede)}), {run.site}, traitée le {run.created_at:%Y-%m-%d %H:%M} UTC")
        for m in it.mesures:
            print(f"  Mesure      : {libelle_caracteristique(m['caracteristique'])} "
                  f"{fmt_mesure(m['valeur'], m['unite'])} (min {_fmt(m['min'])}, max {_fmt(m['max'])}) "
                  f"{libelle_verdict(m['statut'])}")
        p = it.proposition
        if p is None:
            print("  ERREUR : état de validation introuvable dans la base d'état")
            continue
        print(f"  Proposition : origine {p['origine']}, décision suggérée {p['decision_suggeree']}")
        print(f"  Action      : {p['action_corrective']}")
        print(f"  Sources     : {', '.join(it.sources) or 'aucune'}")
        if it.alerte_garde_fou:
            print("  ALERTE garde-fou :")
            for motif in it.alerte_garde_fou:
                print(f"    - {motif}")
    return 0


def run_decide(
    service: Service,
    nc_id: str,
    decision: str,
    valide_par: str,
    action: str | None = None,
    commentaire: str | None = None,
) -> int:
    try:
        run = service.decide(nc_id, decision, valide_par, action=action, commentaire=commentaire)
    except ServiceError as e:
        print(f"ERREUR : {e}")
        return 1
    except ErpError as e:  # ERP vérifié avant la reprise : la décision n'est pas enregistrée
        print(f"ERREUR : {nc_id} : {e}. La fiche reste en attente de validation.")
        return 1
    if run.statut == "erreur":
        print(f"ERREUR : {run.nc_id} : {run.erreur}")
        return 1
    if run.ticket_id is not None:
        print(f"{run.nc_id} : {run.statut} par {run.decided_by}, ticket créé : {run.ticket_id}")
    else:
        print(f"{run.nc_id} : {run.statut} par {run.decided_by}, aucun ticket créé")
    return 0


def run_retry(service: Service, nc_id: str) -> int:
    try:
        service.retry(nc_id)
    except ServiceError as e:
        print(f"ERREUR : {e}")
        return 1
    print(f"{nc_id} : sera traitée de nouveau au prochain run-inbox")
    return 0


# --- reset : logique testable ---------------------------------------------------------------------

FICHIERS_VERROUILLES = "Fermez l'interface et le serveur ERP, puis relancez reset"


def reset_targets(settings: Settings) -> list[Path]:
    """Bases ERP, journal et état, avec leurs fichiers -wal et -shm. Jamais l'index RAG ni data/."""
    return [Path(base + suffixe) for base in (settings.erp_db, settings.journal_db, settings.state_db)
            for suffixe in ("", "-wal", "-shm")]


def _protege(path: Path, settings: Settings) -> bool:
    cible = path.resolve()
    return any(cible.is_relative_to(Path(p).resolve()) for p in (settings.chroma_dir, ROOT / "data"))


def run_reset(settings: Settings, yes: bool = False, input_fn=None) -> int:
    """Supprime les bases locales après confirmation. Code 1 si refus, chemin protégé ou fichier verrouillé."""
    cibles = reset_targets(settings)
    proteges = [p for p in cibles if _protege(p, settings)]
    if proteges:
        print(f"ERREUR : chemin protégé (index RAG ou data/), reset refusé : {', '.join(map(str, proteges))}")
        return 1
    presents = [p for p in cibles if p.exists()]
    if not presents:
        print("Rien à supprimer : aucune base locale trouvée.")
        return 0
    print("Fichiers à supprimer :")
    for p in presents:
        print(f"  {p}")
    if not yes:
        try:
            reponse = (input_fn or input)("Confirmer la suppression ? [o/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            reponse = ""
        if reponse not in ("o", "oui"):
            print("Annulé : aucun fichier supprimé.")
            return 1
    supprimes = []
    code = 0
    for p in presents:
        try:
            p.unlink(missing_ok=True)
        except PermissionError:
            print(f"ERREUR : {p} est verrouillé. {FICHIERS_VERROUILLES}.")
            code = 1
            break
        except OSError as e:
            print(f"ERREUR : impossible de supprimer {p} : {e}")
            code = 1
            break
        supprimes.append(p)
    print(f"{len(supprimes)} fichier(s) supprimé(s)" + (" :" if supprimes else "."))
    for p in supprimes:
        print(f"  {p}")
    return code


# --- ask : logique testable -----------------------------------------------------------------------


def run_ask(question: str, deps: AssistantDeps) -> int:
    """Assistant procédures : réponse, origine et sources. Code 1 si Ollama ou l'index RAG manque."""
    chrono = ChronoLLM(deps.llm) if deps.llm is not None else None
    try:
        rep = answer(question, replace(deps, llm=chrono) if chrono is not None else deps)
    except (AssistantError, ValueError) as e:
        print(f"ERREUR : {e}")
        return 1
    print(f"Origine : {LIBELLES_ORIGINE_ASSISTANT[rep.origine]}" + (" (refus)" if rep.refus else ""))
    print("\nRéponse :")
    for ligne in rep.texte.splitlines():
        print(f"  {ligne}")
    if rep.origine == "passages" and rep.passages:
        print("\nExtraits :")
        for c in rep.passages:
            print(f"  {c.doc_id} ({c.section}) score={c.score:.3f}")
            for ligne in c.text.splitlines():
                print(f"    {ligne}")
    print(f"\nSources : {', '.join(f'{s.doc_id} ({s.section})' for s in rep.sources) or 'aucune'}")
    if rep.motifs:
        print("Réponse du LLM écartée :")
        for m in rep.motifs:
            print(f"  - {m}")
    if chrono is None or not chrono.durations:
        print("Appel LLM : aucun")
    else:
        print(f"Appel LLM : {sum(chrono.durations):.1f} s ({len(chrono.durations)} appel(s))")
    return 0


# --- CLI : couche fine ----------------------------------------------------------------------------


def main(argv: list[str] | None = None, embedder=None) -> int:
    parser = argparse.ArgumentParser(prog="shopfloor", description="ShopFloor Copilot (100 % local)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="indexe data/docs/ dans ChromaDB (collection recréée)")
    p_search = sub.add_parser("search", help="recherche des passages similaires")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=4)
    p_search.add_argument("--domaine", choices=["composite", "tolerie", "peinture", "qualite"])
    p_process = sub.add_parser("process", help="traite une fiche NC de bout en bout")
    p_process.add_argument("fiche")
    p_process.add_argument("--llm", choices=["ollama", "none"], default="ollama")
    p_process.add_argument("--erp-url", help="URL de l'API ERP (défaut : ERP_URL)")
    p_process.add_argument("--valide-par", help="nom du valideur (demandé si absent en mode interactif)")
    p_process.add_argument("--decision", choices=["approve", "reject"], help="sans cette option, la décision est demandée")
    p_inbox = sub.add_parser("run-inbox", help="traite toutes les nouvelles fiches et les met en file de validation")
    p_inbox.add_argument("--llm", choices=["ollama", "none"], default="ollama")
    p_inbox.add_argument("--erp-url", help="URL de l'API ERP (défaut : ERP_URL)")
    p_inbox.add_argument("--inbox", default=str(INBOX_DIR), help="dossier des fiches (défaut : data/nc_inbox)")
    sub.add_parser("pending", help="liste la file de validation")
    p_decide = sub.add_parser("decide", help="valide, modifie ou rejette une fiche en attente")
    p_decide.add_argument("nc_id")
    p_decide.add_argument("decision", choices=["approve", "reject", "edit"])
    p_decide.add_argument("--action", help="action corrective modifiée (obligatoire avec edit)")
    p_decide.add_argument("--valide-par", required=True, help="nom du valideur")
    p_decide.add_argument("--commentaire")
    p_decide.add_argument("--erp-url", help="URL de l'API ERP (défaut : ERP_URL)")
    p_retry = sub.add_parser("retry", help="rend une fiche en erreur traitable au prochain run-inbox")
    p_retry.add_argument("nc_id")
    p_reset = sub.add_parser("reset", help="supprime les bases ERP, journal et état (jamais l'index RAG ni data/)")
    p_reset.add_argument("--yes", action="store_true", help="sans demande de confirmation")
    p_ask = sub.add_parser("ask", help="assistant procédures : question sur les documents, réponse avec sources")
    p_ask.add_argument("question")
    args = parser.parse_args(argv)
    if args.command == "process" and args.decision and not args.valide_par:
        parser.error("--decision exige --valide-par")
    if args.command == "decide" and (args.decision == "edit") != (args.action is not None):
        parser.error("--action est obligatoire avec edit, et seulement avec edit")

    settings = Settings()
    if args.command == "reset":
        return run_reset(settings, yes=args.yes)
    embedder = embedder or OllamaEmbedder(settings)
    if args.command == "ingest":
        try:
            n = ingest(embedder)
        except OllamaUnavailableError as e:
            print(f"ERREUR : {e}")
            return 1
        print(f"{n} chunks indexés dans la collection shopfloor_docs")
        return 0

    if args.command == "ask":
        deps = AssistantDeps(
            tolerances=load_tolerances(TOLERANCES_PATH),
            retriever=make_retriever(settings.chroma_dir, embedder),
            llm=OllamaLLM(settings),
        )
        return run_ask(args.question, deps)

    if args.command == "process":
        if args.decision:
            decision = HumanDecision(decision=args.decision, valide_par=args.valide_par)

            def decide(payload: dict) -> HumanDecision:
                return decision
        else:

            def decide(payload: dict) -> HumanDecision:
                return ask_decision(payload, args.valide_par)

        with ErpClient(args.erp_url or settings.erp_url) as erp:
            deps = Deps(
                tolerances=load_tolerances(TOLERANCES_PATH),
                retriever=make_retriever(settings.chroma_dir, embedder),
                llm=OllamaLLM(settings) if args.llm == "ollama" else None,
                erp=erp,
            )
            return run_process(args.fiche, deps, decide)

    if args.command in ("run-inbox", "pending", "decide", "retry"):
        # pending, decide et retry n'appellent ni le LLM ni la recherche : le retriever reste inutilisé.
        llm = OllamaLLM(settings) if getattr(args, "llm", "none") == "ollama" else None
        with ErpClient(getattr(args, "erp_url", None) or settings.erp_url) as erp:
            deps = Deps(
                tolerances=load_tolerances(TOLERANCES_PATH),
                retriever=make_retriever(settings.chroma_dir, embedder),
                llm=llm,
                erp=erp,
            )
            with Service(deps, state_db=settings.state_db, journal_db=settings.journal_db) as service:
                if args.command == "run-inbox":
                    return run_inbox(service, args.inbox)
                if args.command == "pending":
                    return print_pending(service)
                if args.command == "retry":
                    return run_retry(service, args.nc_id)
                return run_decide(service, args.nc_id, args.decision, args.valide_par, args.action, args.commentaire)

    where = {"domaine": args.domaine} if args.domaine else None
    try:
        results = retrieve_similar(args.query, k=args.k, where=where, embedder=embedder)
    except OllamaUnavailableError as e:
        print(f"ERREUR : {e}")
        return 1
    except NotFoundError:
        print(f"ERREUR : {RAG_INDISPONIBLE}")
        return 1
    if not results:
        print("aucun résultat")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.doc_id:<13} {r.section:<20} score={r.score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
