"""Ligne de commande : python -m shopfloor.cli ingest | search "requête" [--k 4] [--domaine composite]."""

import argparse
import sys

from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import retrieve_similar


def main(argv: list[str] | None = None, embedder=None) -> int:
    parser = argparse.ArgumentParser(prog="shopfloor", description="ShopFloor Copilot (100 % local)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="indexe data/docs/ dans ChromaDB (collection recréée)")
    p_search = sub.add_parser("search", help="recherche des passages similaires")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=4)
    p_search.add_argument("--domaine", choices=["composite", "tolerie", "peinture", "qualite"])
    args = parser.parse_args(argv)

    embedder = embedder or OllamaEmbedder()
    if args.command == "ingest":
        n = ingest(embedder)
        print(f"{n} chunks indexés dans la collection shopfloor_docs")
        return 0

    where = {"domaine": args.domaine} if args.domaine else None
    results = retrieve_similar(args.query, k=args.k, where=where, embedder=embedder)
    if not results:
        print("aucun résultat")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.doc_id:<13} {r.section:<20} score={r.score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
