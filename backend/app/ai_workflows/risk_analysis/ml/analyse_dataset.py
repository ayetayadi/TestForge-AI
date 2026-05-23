"""
Analyse du dataset pour diagnostiquer les problèmes de labels.

Usage :
    python -m app.ai_workflows.risk_analysis.ml.analyse_dataset
"""

import re
import sys
import os
import pandas as pd
import numpy as np
from collections import Counter

DATASET_PATH = "data/risk_dataset.xlsx"

COLUMN_ALIASES = {
    "user_story":          ["user story", "user_story", "us", "story", "histoire utilisateur"],
    "acceptance_criteria": ["acceptance criteria", "acceptance_criteria", "ac", "critères d'acceptation", "criteres_acceptation", "critères_acceptation"],
    "probability":         ["probability", "probabilité", "probabilite", "prob", "p"],
    "impact":              ["impact", "i"],
}


def _normalize_columns(df):
    rename = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if col.strip().lower() in aliases and canonical not in df.columns:
                rename[col] = canonical
                break
    return df.rename(columns=rename)


def main():
    if not os.path.exists(DATASET_PATH):
        print(f"Dataset introuvable : {DATASET_PATH}")
        sys.exit(1)

    df = pd.read_excel(DATASET_PATH)
    df = _normalize_columns(df)

    print(f"\n{'='*55}")
    print(f"DATASET : {len(df)} exemples | colonnes : {list(df.columns)}")
    print(f"{'='*55}")

    y_P = df["probability"].astype(int)
    y_I = df["impact"].astype(int)

    # ── Distribution ──────────────────────────────────────────
    print("\n── Distribution P (probabilité) ──")
    for v, c in sorted(Counter(y_P).items()):
        bar = "█" * (c // 2)
        print(f"  P={v} : {c:>4} exemples  {bar}")

    print("\n── Distribution I (impact) ──")
    for v, c in sorted(Counter(y_I).items()):
        bar = "█" * (c // 2)
        print(f"  I={v} : {c:>4} exemples  {bar}")

    # ── Combinaisons P×I ──────────────────────────────────────
    print("\n── Combinaisons P × I (classes rares = problème) ──")
    combo = Counter(zip(y_P, y_I))
    for (p, i), c in sorted(combo.items()):
        flag = "  ← RARE (<10)" if c < 10 else ""
        print(f"  P={p} I={i} : {c:>4} exemples{flag}")

    # ── Longueur des textes ───────────────────────────────────
    if "user_story" in df.columns:
        lengths = df["user_story"].astype(str).apply(len)
        print(f"\n── Longueur user stories ──")
        print(f"  Min    : {lengths.min()} caractères")
        print(f"  Max    : {lengths.max()} caractères")
        print(f"  Moyenne: {lengths.mean():.0f} caractères")
        print(f"  Trop courtes (<50 chars) : {(lengths < 50).sum()}")

    # ── Doublons ─────────────────────────────────────────────
    if "user_story" in df.columns:
        dupes = df["user_story"].astype(str).duplicated().sum()
        print(f"\n── Doublons user_story : {dupes}")

    # ── Incohérences : même US, labels différents ─────────────
    if "user_story" in df.columns:
        groups = df.groupby("user_story")[["probability", "impact"]].nunique()
        incoherent = groups[(groups["probability"] > 1) | (groups["impact"] > 1)]
        print(f"\n── US avec labels incohérents : {len(incoherent)}")
        if len(incoherent) > 0:
            print("  (même texte, plusieurs valeurs P ou I différentes)")

    # ── Recommandation ────────────────────────────────────────
    print(f"\n{'='*55}")
    min_class_P = min(Counter(y_P).values())
    min_class_I = min(Counter(y_I).values())
    print("RECOMMANDATION :")
    if min_class_P < 30:
        print(f"  → Classe P la plus rare a {min_class_P} exemples (<30) : regrouper en 3 classes")
    if min_class_I < 30:
        print(f"  → Classe I la plus rare a {min_class_I} exemples (<30) : regrouper en 3 classes")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
