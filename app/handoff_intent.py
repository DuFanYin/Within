"""Rule-based companion routing for Cactus cloud handoff."""

from __future__ import annotations

import re

# Never route these to cloud — stay on-device with crisis copy in the companion prompt.
_CRISIS = re.compile(
    r"\b("
    r"suicid|kill myself|end my life|want to die|self[- ]?harm|hurt myself|"
    r"don't want to live|overdose"
    r")\b",
    re.I,
)

# Generic coping / skills asks — safe to send only the user's question (+ coarse mood), not journal RAG.
_SKILLS = re.compile(
    r"(?i)"
    r"("
    r"how (?:can|do|should|could) i (?:cope|deal with|manage|handle|calm)|"
    r"coping (?:strateg|skill|tip|technique)|"
    r"(?:give|share) (?:me )?(?:some )?(?:tips|ideas|strategies)|"
    r"grounding exercise|breathing exercise|"
    r"help me (?:calm|relax|reset|regulate)|"
    r"ways to (?:manage|reduce|handle) (?:my )?(?:stress|anxiety|overwhelm)|"
    r"what (?:can|should) i do when (?:i'm|im) (?:stressed|anxious|overwhelmed)"
    r")",
)


def route_mode(text: str, *, cloud_configured: bool) -> str:
    """One of: crisis | skills_cloud | local."""
    t = (text or "").strip()
    if not t:
        return "local"
    if _CRISIS.search(t):
        return "crisis"
    if cloud_configured and _SKILLS.search(t):
        return "skills_cloud"
    return "local"
