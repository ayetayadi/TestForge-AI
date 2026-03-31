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
    """
    Score acceptance criteria quality.

    Two-tier scoring:
    - Strict ACs (full sentences with observable keywords) → full credit
    - Lenient ACs (3+ words, no bad patterns) → partial credit (0.5x weight)
    - Garbage ACs (< 3 words, bad patterns) → no credit
    """
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

# Capitalized phrases that typically start a new AC item (French + English).
# These must cover ALL common words that begin an AC line in Jira.
#
# FIX: Added many missing starters that caused concatenated ACs to stay
# unsplit. e.g. "Bouton", "Redirection", "Fonctionne", "Message" were
# all missing, so the logout story's 5 ACs stayed as 1 string.
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
    """
    Split a single string that contains multiple ACs concatenated without
    delimiters. This happens when Jira returns AC items joined into one string.

    Example input:
        'Bouton "Se déconnecter" visible dans la barre de navigation
         Suppression du token JWT côté client (localStorage/cookie)
         Redirection vers la page de connexion après déconnexion
         Fonctionne quel que soit le mode de connexion utilisé (email, Google, OTP)
         Message de confirmation "Vous êtes déconnecté"'
    Expected output:
        ['Bouton "Se déconnecter" visible dans la barre de navigation',
         'Suppression du token JWT côté client (localStorage/cookie)',
         'Redirection vers la page de connexion après déconnexion',
         'Fonctionne quel que soit le mode de connexion utilisé (email, Google, OTP)',
         'Message de confirmation "Vous êtes déconnecté"']
    """
    text = text.strip()
    if not text:
        return []

    # If it's already short, don't try to split
    if len(text.split()) < 6:
        return [text]

    # Build regex that matches AC starter words/phrases
    # Sort by length descending so longer patterns match first
    # (e.g. "Le système" before "Le")
    sorted_patterns = sorted(AC_STARTER_PATTERNS, key=len, reverse=True)
    combined = '|'.join(rf'(?:{p})' for p in sorted_patterns)

    # Find all matches — but skip the very first character position
    # (we don't want to "split" at the beginning of the string)
    matches = []
    for m in re.finditer(combined, text):
        # Only count as a split point if:
        # 1. It's not at position 0 (that's just the start of the text)
        # 2. The character before it is a space (word boundary)
        pos = m.start()
        if pos > 0 and (text[pos - 1] == ' ' or text[pos - 1] == '\n'):
            # Make sure we're not inside parentheses or quotes
            prefix = text[:pos]
            open_parens = prefix.count('(') - prefix.count(')')
            open_quotes = prefix.count('"') % 2
            # Also check smart quotes
            open_smart = (prefix.count('\u201c') - prefix.count('\u201d')) % 2

            if open_parens == 0 and open_quotes == 0 and open_smart == 0:
                matches.append(m)

    if len(matches) == 0:
        return [text]

    # Split at each match position
    parts = []

    # Text before the first split point
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

    # Only return split result if we got more items than we started with
    return parts if len(parts) > 1 else [text]


def normalize_ac(ac_list):
    """
    Normalize acceptance criteria into a flat list of clean strings.

    Handles:
    - Dict ACs with condition/observable_output/measurable_element keys
    - List-wrapped ACs
    - Numbered/bulleted lists within a single string
    - Concatenated ACs from Jira (multiple short ACs joined into one string)
    """
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

            # Split on list markers (numbered items, bullets) at line boundaries
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

    # Second pass: split any concatenated AC strings from Jira
    expanded = []
    for ac in result:
        split_result = _try_split_concatenated_ac(ac)
        expanded.extend(split_result)

    # Third pass: clean up each AC
    cleaned = []
    for ac in expanded:
        ac = ac.strip()
        # Strip leading bullets/numbers
        ac = re.sub(r'^[\s]*[•●\-\*]\s*', '', ac)
        ac = re.sub(r'^[\s]*\d+[\.\)]\s*', '', ac)
        ac = ac.strip()
        if ac and len(ac) >= 5:
            cleaned.append(ac)

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for ac in cleaned:
        key = re.sub(r'\s+', ' ', ac.lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(ac)

    return deduped