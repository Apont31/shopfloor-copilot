"""Indicateurs de pilotage (étape 10) : fonctions pures sur des lignes de journal construites à la main."""

import datetime

import pytest

from shopfloor.journal import Run
from shopfloor.kpis import Groupe, compute_kpis, estimate_time_saved

T0 = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.timezone.utc)


def run(nc_id, statut, *, site="Site Alpha", procede="composite", verdict="NON_CONFORME", origine="llm",
        llm_ms=None) -> Run:
    if statut in ("erreur", "doublon") and origine == "llm":
        origine = "aucune"
    decide = statut in ("approuve", "modifie", "rejete")
    return Run(
        nc_id=nc_id, fichier=f"{nc_id}.md", site=site, procede=procede, part_ref="CP-210", verdict=verdict,
        origine=origine, guard_ok=True if origine == "llm" else None,
        llm_ms=llm_ms if origine == "llm" else None, statut=statut,
        ticket_id="TCK-0001" if statut in ("approuve", "modifie") else None, erreur=None,
        created_at=T0, decided_at=T0 if decide else None, decided_by="Valideur fictif" if decide else None,
    )


@pytest.fixture
def mixte() -> list[Run]:
    """10 fiches : 6 décidées (3 approuvées, 1 modifiée, 2 rejetées), 2 en attente, 1 erreur, 1 doublon."""
    return [
        run("NC-1", "approuve", llm_ms=4000),
        run("NC-2", "approuve", llm_ms=6000, site="Site Beta"),
        run("NC-3", "approuve", verdict="CONFORME", origine="deterministe", procede="peinture"),
        run("NC-4", "modifie", llm_ms=5000, site="Site Beta", procede="tolerie"),
        run("NC-5", "rejete", verdict="INDETERMINE", origine="deterministe", site="Site Beta"),
        run("NC-6", "rejete", llm_ms=8000, site="Site Gamma", procede="tolerie"),
        run("NC-7", "en_attente", llm_ms=7000),
        run("NC-8", "en_attente", verdict="CONFORME", origine="deterministe", site="Site Gamma"),
        run("NC-9", "erreur", verdict=None, site=None, procede=None),
        run("NC-10", "doublon", verdict=None, site="Site Gamma"),
    ]


def test_journal_vide_sans_division_par_zero():
    k = compute_kpis([])
    assert (k.traitees, k.analysees, k.en_attente, k.decidees, k.erreurs, k.doublons) == (0, 0, 0, 0, 0, 0)
    assert (k.taux_approuvees, k.taux_modifiees, k.taux_rejetees) == (None, None, None)
    assert (k.nb_llm, k.nb_deterministe) == (0, 0)
    assert (k.part_llm, k.part_deterministe, k.duree_llm_moyenne_s) == (None, None, None)
    assert k.verdicts == {"NON_CONFORME": 0, "CONFORME": 0, "INDETERMINE": 0}
    assert k.par_site == {} and k.par_procede == {}
    assert estimate_time_saved(k, 30, 10) == 0


def test_journal_mixte_compteurs(mixte):
    k = compute_kpis(mixte)
    assert (k.traitees, k.analysees, k.en_attente, k.decidees, k.erreurs, k.doublons) == (10, 8, 2, 6, 1, 1)
    assert k.verdicts == {"NON_CONFORME": 5, "CONFORME": 2, "INDETERMINE": 1}


def test_taux_exacts(mixte):
    k = compute_kpis(mixte)
    assert k.taux_approuvees == pytest.approx(3 / 6)
    assert k.taux_modifiees == pytest.approx(1 / 6)
    assert k.taux_rejetees == pytest.approx(2 / 6)
    assert k.taux_approuvees + k.taux_modifiees + k.taux_rejetees == pytest.approx(1)
    # Part LLM sur les 8 fiches analysées (erreur et doublon exclus) : 5 LLM, 3 déterministes.
    assert (k.nb_llm, k.nb_deterministe) == (5, 3)
    assert (k.part_llm, k.part_deterministe) == (pytest.approx(5 / 8), pytest.approx(3 / 8))
    assert k.duree_llm_moyenne_s == pytest.approx((4 + 6 + 5 + 8 + 7) / 5)


def test_par_site(mixte):
    k = compute_kpis(mixte)
    assert k.par_site == {
        "Site Alpha": Groupe(nb=3, decidees=2, taux_acceptation=1.0),  # NC-1, NC-3 ; NC-7 en attente
        "Site Beta": Groupe(nb=3, decidees=3, taux_acceptation=pytest.approx(2 / 3)),
        "Site Gamma": Groupe(nb=3, decidees=1, taux_acceptation=0.0),
    }
    assert list(k.par_site) == sorted(k.par_site)
    assert sum(g.nb for g in k.par_site.values()) == 9  # la fiche illisible n'a pas de site


def test_par_procede(mixte):
    k = compute_kpis(mixte)
    assert k.par_procede == {
        "composite": Groupe(nb=6, decidees=3, taux_acceptation=pytest.approx(2 / 3)),
        "peinture": Groupe(nb=1, decidees=1, taux_acceptation=1.0),
        "tolerie": Groupe(nb=2, decidees=2, taux_acceptation=0.5),
    }


def test_groupe_sans_decision_taux_none():
    k = compute_kpis([run("NC-1", "en_attente")])
    assert k.par_site["Site Alpha"] == Groupe(nb=1, decidees=0, taux_acceptation=None)
    assert k.taux_approuvees is None and k.part_llm == 1.0


def test_estimation_du_temps(mixte):
    k = compute_kpis(mixte)
    assert estimate_time_saved(k, 45, 15) == pytest.approx(8 * 30 / 60)  # 8 fiches analysées, 30 min chacune
    assert estimate_time_saved(k, 20, 20) == 0
    assert estimate_time_saved(k, 10, 25) == pytest.approx(-2.0)  # hypothèse défavorable : pas de gain


@pytest.mark.parametrize("manuel, copilote", [(-1, 10), (30, -5)])
def test_estimation_durees_negatives_refusees(mixte, manuel, copilote):
    with pytest.raises(ValueError, match="positives ou nulles"):
        estimate_time_saved(compute_kpis(mixte), manuel, copilote)
