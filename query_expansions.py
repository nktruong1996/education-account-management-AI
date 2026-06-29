import re

QUERY_EXPANSIONS = {
    # Abbreviations
    "fas": [
        "Financial Assistance Scheme",
        "SFS Financial Assistance Scheme",
    ],
    "jc": [
        "Junior College",
    ],
    "ci": [
        "Centralised Institute",
    ],
    "au": [
        "Autonomous University",
    ],
    "poly": [
        "Polytechnic",
    ],
    "cpf": [
        "Central Provident Fund",
    ],
    "oa": [
        "CPF Ordinary Account",
    ],
    "ghi": [
        "Gross Household Income",
    ],
    "pci": [
        "Per Capita Income",
    ],
    "psea": [
        "Post-Secondary Education Account",
    ],

    # User wording
    "balance": [
        "Education credit balance",
    ],
    "payments": [
        "Transaction History",
    ],
    "spending": [
        "Transaction History",
    ],
    "topup": [
        "Top-up",
    ],
    "top up": [
        "Top-up",
    ],
    "excel": [
        "CSV",
    ],
    "student account": [
        "Education Account",
    ],
    "tuition loan": [
        "Tuition Fee Loan Scheme",
    ],
}

def get_expansions_for_text(text: str) -> set[str]:
    text_lower = text.lower()
    additions = set()

    for term, expansions in QUERY_EXPANSIONS.items():
        if re.search(rf"\b{re.escape(term)}\b", text_lower):
            for expansion in expansions:
                if expansion.lower() not in text_lower:
                    additions.add(expansion)

    return additions


def build_expanded_query(parts: list[str]) -> str:
    """
    Build one retrieval query from multiple user-message parts.
    Keeps original user wording, then appends deduplicated expansion terms once.
    """
    cleaned_parts = [p.strip() for p in parts if p and p.strip()]
    base_query = " ".join(cleaned_parts)

    if not base_query:
        return ""

    additions = set()
    base_lower = base_query.lower()

    for part in cleaned_parts:
        additions.update(get_expansions_for_text(part))

    deduped_additions = [
        item for item in sorted(additions)
        if item.lower() not in base_lower
    ]

    if not deduped_additions:
        return base_query

    return base_query + " " + " ".join(deduped_additions)