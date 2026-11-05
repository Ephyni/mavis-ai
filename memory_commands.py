"""Deterministic memory-save commands and safeguards for unverified chat replies."""

import re


def extract_memory_fact(message):
    """Extract an explicit save request without changing persistent state.

    Return None for other intents, or an empty string if no fact was supplied.
    """
    if not isinstance(message, str):
        return None

    command = " ".join(message.strip().split())
    command = re.sub(
        r"^(?:(?:hey|hi|okay|ok)[,\s]+)+", "", command, flags=re.IGNORECASE
    )
    command = re.sub(r"^mavis[,\s]+", "", command, flags=re.IGNORECASE)
    command = re.sub(
        r"^(?:(?:please|can you|could you|would you|will you|"
        r"i want you to|i need you to)\s+)+",
        "", command, flags=re.IGNORECASE,
    )

    # Preserve reminder and task execution paths, and respect negations.
    if re.match(
        r"^(?:(?:don't|do not|never)\s+(?:remember|save|store)|"
        r"remember\s+(?:to|when|what|where|who|why|how)|"
        r"(?:don't|do not)\s+forget\s+to|"
        r"(?:save|store)\s+(?:(?:my|a|the|this)\s+)?(?:task|to-?do))\b",
        command, flags=re.IGNORECASE,
    ):
        return None

    patterns = (
        r"^(?:don't|do not)\s+forget\b(?P<fact>.*)$",
        r"^remember\b(?P<fact>.*)$",
        r"^(?:save|store)\b(?P<fact>.*)$",
        r"^make\s+a\s+note(?:\s+of)?\b(?P<fact>.*)$",
        r"^keep\s+in\s+mind\b(?P<fact>.*)$",
    )
    for pattern in patterns:
        match = re.match(pattern, command, flags=re.IGNORECASE)
        if match is None:
            continue
        fact = match.group("fact").strip(" \t:,.-")
        fact = re.sub(
            r"^(?:the\s+fact\s+that|that)\b\s*",
            "", fact, flags=re.IGNORECASE,
        )
        fact = re.sub(
            r"^(?:this|it)(?:\s+(?:for\s+later|in\s+(?:your\s+)?memory|"
            r"memory))?\b[\s:,-]*",
            "", fact, flags=re.IGNORECASE,
        )
        fact = re.sub(r"\s+for\s+later\.?$", "", fact, flags=re.IGNORECASE)
        return fact.strip(" \t:,.-!?")
    return None


_UNVERIFIED_MEMORY_CLAIM = re.compile(
    r"\b(?:"
    r"i(?:'ll| will)\s+(?:remember|save|store|memorize|never\s+forget)\b"
    r"|i(?:'ve| have)\s+(?:saved|stored|memorized|remembered)\b"
    r"|i(?:'ll| will)\s+keep\s+(?:that|this|it)\s+in\s+mind\b"
    r"|(?:it|that|this)\s+(?:is|has\s+been)\s+(?:saved|stored)"
    r"\s+(?:in\s+)?memory\b"
    r"|consider\s+it\s+(?:saved|stored)\b"
    r")",
    flags=re.IGNORECASE,
)


def makes_unverified_memory_claim(reply):
    """Catch model-only persistence promises that have not been executed."""
    return (
        isinstance(reply, str)
        and _UNVERIFIED_MEMORY_CLAIM.search(reply.replace("’", "'")) is not None
    )
