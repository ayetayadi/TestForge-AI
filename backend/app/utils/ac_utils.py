import re


def detect_story_type(story: str) -> str:
    s = story.lower()

    def match(keywords):
        return any(re.search(rf"\b{k}\b", s) for k in keywords)

    if match([
        "acheter", "payer", "paiement", "panier", "checkout",
        "buy", "purchase", "cart", "payment"
    ]):
        return "transaction"

    if match([
        "login", "connexion", "auth", "password", "mot de passe",
        "sign in", "sign up", "authenticate"
    ]):
        return "auth"

    if match([
        "statistique", "statistiques",
        "dashboard", "rapport", "report",
        "analytics", "metrics"
    ]):
        return "analytics"

    return "simple"


def get_ac_threshold(story_type: str) -> float:
    thresholds = {
        "transaction": 0.7,
        "auth":        0.65,
        "analytics":   0.6,
        "simple":      0.5,
    }
    return thresholds.get(story_type, 0.55)


def compute_ac_score(ac_list, is_testable_ac):
    if not ac_list:
        return 0.0

    strict_count = sum(1 for a in ac_list if is_testable_ac(a))

    lenient_count = 0
    for a in ac_list:
        if is_testable_ac(a):
            continue
        if (a and len(a.strip()) >= 10 and len(a.split()) >= 3
                and not any(p in a.lower() for p in ["something", "desired outcome", "works correctly"])):
            lenient_count += 1

    total = len(ac_list)
    effective = strict_count + (lenient_count * 0.5)

    if effective >= 5:
        quantity = 1.0
    elif effective >= 3:
        quantity = 0.8
    elif effective >= 1:
        quantity = 0.5
    else:
        quantity = 0.0

    quality = effective / max(total, 1)
    bonus = 0.1 if strict_count == total and strict_count >= 3 else 0.0
    score = 0.6 * quantity + 0.4 * quality + bonus

    return round(min(score, 1.0), 2)


# =========================
# CONCATENATED AC SPLITTER
# =========================
AC_STARTER_PATTERNS = [
    # ── French: Action nouns ──
    r'Affichage', r'Ajout', r'Archivage', r'Attribution',
    r'Authentification', r'Autorisation',
    r'Calcul', r'Chargement', r'Configuration',
    r'Confirmation', r'Connexion', r'Conversion',
    r'Création', r'Déconnexion',
    r'Envoi', r'Export',
    r'Filtrage',
    r'Génération', r'Gestion',
    r'Import', r'Intégration',
    r'Mapping', r'Migration', r'Mise\s+à\s+jour', r'Modification',
    r'Notification',
    r'Pagination',
    r'Recherche', r'Réception',
    r'Sauvegarde', r'Sélection', r'Suppression', r'Synchronisation',
    r'Téléchargement', r'Traitement',
    r'Validation', r'Vérification',

    # ── French: Subject/verb starters (common in Jira AC) ──
    r'Bouton', r'Le\s+bouton', r'Un\s+bouton',
    r'Redirection', r'La\s+redirection',
    r'Message', r'Le\s+message', r'Un\s+message',
    r'Fonctionne',
    r'Le\s+système', r"L['']utilisateur", r"L['']application",
    r'La\s+page', r'Le\s+formulaire', r'Le\s+champ',
    r'Les\s+données', r'La\s+liste', r'Le\s+tableau',
    r'Un\s+email', r'Un\s+mail', r'Une\s+notification',
    r'Une\s+erreur', r'Un\s+lien',
    r'Accès', r'Aucun', r'Aucune',
    r'Seuls?\s+les', r'Seul\s+le', r'Seule\s+la',
    r'Si\s+le', r'Si\s+la', r"Si\s+l['']",
    r'Lorsque', r"Lorsqu['']",
    r'Après', r'Avant',
    r'En\s+cas\s+de', r"En\s+cas\s+d['']",

    # ── English: Action nouns ──
    r'Archiving', r'Authentication', r'Authorization',
    r'Calculation', r'Configuration', r'Connection', r'Conversion', r'Creation',
    r'Deletion', r'Display', r'Download',
    r'Filter', r'Generation',
    r'Integration',
    r'Loading',
    r'Migration',
    r'Notification',
    r'Processing',
    r'Saving', r'Search', r'Selection', r'Sync',
    r'Update', r'Upload',
    r'Validation', r'Verification',

    # ── English: Subject/verb starters ──
    r'Button', r'The\s+button', r'A\s+button',
    r'Redirect', r'The\s+redirect',
    r'The\s+system', r'The\s+user', r'The\s+application',
    r'The\s+page', r'The\s+form', r'The\s+field',
    r'The\s+data', r'The\s+list', r'The\s+table',
    r'An?\s+email', r'An?\s+error', r'An?\s+message', r'An?\s+link',
    r'A\s+notification', r'A\s+confirmation',
    r'No\s+', r'Only\s+',
    r'If\s+the', r'When\s+the', r'When\s+a',
    r'After', r'Before',
    r'In\s+case\s+of',
    r'Works',
]


def _try_split_concatenated_ac(text: str) -> list:
    text = text.strip()
    if not text:
        return []

    if len(text.split()) < 6:
        return [text]
    sorted_patterns = sorted(AC_STARTER_PATTERNS, key=len, reverse=True)
    combined = '|'.join(rf'(?:{p})' for p in sorted_patterns)
    matches = []
    for m in re.finditer(combined, text):
        pos = m.start()
        if pos > 0 and (text[pos - 1] == ' ' or text[pos - 1] == '\n'):
            prefix = text[:pos]
            open_parens = prefix.count('(') - prefix.count(')')
            open_quotes = prefix.count('"') % 2
            open_smart = (prefix.count('\u201c') - prefix.count('\u201d')) % 2

            if open_parens == 0 and open_quotes == 0 and open_smart == 0:
                matches.append(m)

    if len(matches) == 0:
        return [text]
    parts = []
    first_split = matches[0].start()
    prefix = text[:first_split].strip()
    if prefix:
        parts.append(prefix)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        part = text[start:end].strip()
        if part:
            parts.append(part)

    return parts if len(parts) > 1 else [text]


def normalize_ac(ac_list):
    if not ac_list:
        return []

    result = []

    for ac in ac_list:
        items = ac if isinstance(ac, list) else [ac]

        for item in items:
            if isinstance(item, dict):
                parts = []
                for key in ["condition", "observable_output", "measurable_element"]:
                    if item.get(key):
                        parts.append(item[key])
                item = " → ".join(parts) if parts else str(item)

            if not isinstance(item, str):
                continue

            chunks = re.split(
                r'\n(?=\d+[\.\)]|\-|•)',
                item
            )

            buffer = ""

            for chunk in chunks:
                chunk = chunk.strip()
                if not chunk:
                    continue

                if chunk.endswith(":"):
                    buffer = chunk
                    continue

                if buffer:
                    combined = f"{buffer} {chunk}"
                    result.append(combined.strip())
                    buffer = ""
                else:
                    result.append(chunk)

    expanded = []
    for ac in result:
        split_result = _try_split_concatenated_ac(ac)
        expanded.extend(split_result)

    cleaned = []
    for ac in expanded:
        ac = ac.strip()
        ac = re.sub(r'^[\s]*[•●\-\*]\s*', '', ac)
        ac = re.sub(r'^[\s]*\d+[\.\)]\s*', '', ac)
        ac = ac.strip()
        if ac and len(ac) >= 5:
            cleaned.append(ac)

    seen = set()
    deduped = []
    for ac in cleaned:
        key = re.sub(r'\s+', ' ', ac.lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(ac)

    return deduped