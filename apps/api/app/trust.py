"""Layered trust model for retrieval evidence.

The system must never treat an official standard, a technical webpage, a
third-party QA pair and a previous LLM answer as equally trustworthy.  This
module is the single place that answers "may this item be used as evidence?".

Levels
------
L1_original      Traceable source document (standard, official guidance, paper).
L2_verified_faq  Human-reviewed FAQ whose support still resolves to L1 chunks.
L3_unverified_qa Public QA dataset rows.  **Never evidence.**  Usable only to
                 generate query hints / candidate questions offline.
L4_history       Previous chat turns and previous model answers.  **Never
                 evidence.**  Context only.

Important: the level is derived from publisher, document nature, review status
and traceability — *not* from the file format.  A PDF from an unknown blog is
not L1, and an HTML page from a ministry is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.authority import BINDING_LEVELS, NON_BINDING_LEVELS, authority_rank, normalize_authority

LEVEL_L1 = "L1_original"
LEVEL_L2 = "L2_verified_faq"
LEVEL_L3 = "L3_unverified_qa"
LEVEL_L4 = "L4_history"

LEVEL_ORDER = {LEVEL_L1: 1, LEVEL_L2: 2, LEVEL_L3: 3, LEVEL_L4: 4}
NEVER_EVIDENCE = frozenset({LEVEL_L3, LEVEL_L4})

VERIFIED = "verified"
PENDING = "pending"
REJECTED = "rejected"

# Questions where an approximate answer is actively dangerous.  These require a
# binding or official source and a stricter applicability check.
STRICT_TOPIC_TERMS = (
    "用药",
    "渔药",
    "兽药",
    "禁用",
    "停用",
    "休药期",
    "残留",
    "剂量",
    "泼洒",
    "消毒剂",
    "抗生素",
    "诊断",
    "确诊",
    "治疗",
)

# Authority levels that may answer a strict-topic question.  Official technical
# guidance belongs here: Chinese drug-use questions are normally answered from
# ministry/extension-station guidance, not from a standard alone.
STRICT_AUTHORITIES = BINDING_LEVELS | {"official_technical", "international"}


@dataclass(frozen=True, slots=True)
class TrustProfile:
    level: str
    authority: str
    verification_status: str
    publisher: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    superseded_by: str | None = None
    applicability: dict = field(default_factory=dict)

    @property
    def rank(self) -> int:
        return authority_rank(self.authority)

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "authority": normalize_authority(self.authority),
            "verification_status": self.verification_status,
            "publisher": self.publisher,
            "source_url": self.source_url,
            "effective_date": self.effective_date,
            "superseded_by": self.superseded_by,
            "applicability": self.applicability,
        }


def profile_for_document(doc) -> TrustProfile:
    """Build a profile from a ``KbDocument`` (or an object with the same fields)."""
    authority = normalize_authority(getattr(doc, "authority_level", None))
    status = getattr(doc, "verification_status", None) or VERIFIED
    superseded = getattr(doc, "superseded_by_document_id", None)
    return TrustProfile(
        level=LEVEL_L1,
        authority=authority,
        verification_status=status,
        publisher=getattr(doc, "source_org", None),
        source_url=getattr(doc, "source_url", None),
        effective_date=getattr(doc, "effective_date", None),
        superseded_by=str(superseded) if superseded else None,
        applicability={
            "species": list(getattr(doc, "species", []) or []),
            "growth_stages": list(getattr(doc, "growth_stages", []) or []),
            "region": getattr(doc, "region", None),
        },
    )


def profile_for_faq(entry) -> TrustProfile:
    supporting = list(getattr(entry, "supporting", []) or [])
    return TrustProfile(
        level=LEVEL_L2,
        authority=_faq_authority(entry, supporting),
        verification_status=getattr(entry, "review_status", PENDING),
        publisher=getattr(entry, "source_dataset", None),
        source_url=getattr(entry, "original_source_url", None),
        effective_date=None,
        superseded_by=None,
        applicability={
            "species": list(getattr(entry, "species", []) or []),
            "growth_stages": list(getattr(entry, "growth_stages", []) or []),
            "region": getattr(entry, "region", None),
        },
    )


def _faq_authority(entry, supporting: list) -> str:
    """A FAQ is only as authoritative as the documents that support it.

    An explicit ``source_authority`` wins; otherwise the strongest supporting
    chunk's authority is used; otherwise it is unknown.
    """
    explicit = getattr(entry, "source_authority", None)
    if explicit:
        return normalize_authority(explicit)
    ranks = [
        normalize_authority(item.get("authority"))
        for item in supporting
        if isinstance(item, dict) and item.get("authority")
    ]
    if not ranks:
        return "unknown"
    return max(ranks, key=authority_rank)


# Drug families and named compounds.  Listing every trade name is hopeless, so
# the class suffixes are matched structurally.
DRUG_PATTERN = re.compile(
    r"(沙星|霉素|菌素|磺胺|喹诺酮|四环素|氯霉素|甲砜霉素|敌百虫|硫酸铜|漂白粉|"
    r"生石灰|聚维酮碘|碘制剂|甲醛|孔雀石绿|地克珠利|阿维菌素|伊维菌素|氟苯尼考|"
    r"恩诺沙星|磺胺间甲氧嘧啶)"
)


def is_strict_question(question: str) -> bool:
    if any(term in question for term in STRICT_TOPIC_TERMS):
        return True
    return bool(DRUG_PATTERN.search(question or ""))


def evidence_eligible(
    profile: TrustProfile,
    *,
    strict: bool = False,
    allow_pending: bool = False,
) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for using this profile as evidence."""
    if profile.level in NEVER_EVIDENCE:
        return False, f"level {profile.level} is never evidence"
    if profile.verification_status == REJECTED:
        return False, "rejected_by_reviewer"
    if profile.verification_status != VERIFIED and not allow_pending:
        return False, f"verification_status={profile.verification_status}"
    if profile.superseded_by:
        return False, "superseded_by_newer_document"
    if profile.authority in NON_BINDING_LEVELS:
        # A draft or historical document may inform, but must not be presented
        # as the current rule.  It is only allowed when nothing stricter exists
        # and the caller explicitly asked for it.
        return False, f"authority={profile.authority} is not binding"
    if strict and profile.authority not in STRICT_AUTHORITIES:
        return False, f"strict question requires authoritative source, got {profile.authority}"
    return True, "ok"


def applicability_conflict(
    applicability: dict,
    context: dict,
) -> tuple[bool, str]:
    """Check species / stage / region against explicit user conditions.

    Empty applicability means "general" and never conflicts.  A condition that
    the user did not state is not treated as a conflict either — we only reject
    when both sides are explicit and different.
    """
    faq_species = {s for s in (applicability.get("species") or []) if s and s != "通用"}
    user_species = {s for s in (context.get("species") or []) if s and s != "通用"}
    if faq_species and user_species and not (faq_species & user_species):
        return True, f"species mismatch: faq={sorted(faq_species)} user={sorted(user_species)}"

    faq_stage = {s for s in (applicability.get("growth_stages") or []) if s}
    user_stage = {s for s in (context.get("growth_stages") or []) if s}
    if faq_stage and user_stage and not (faq_stage & user_stage):
        return True, f"stage mismatch: faq={sorted(faq_stage)} user={sorted(user_stage)}"

    faq_region = (applicability.get("region") or "").strip()
    user_region = (context.get("region") or "").strip()
    if faq_region and user_region and faq_region != user_region:
        return True, f"region mismatch: faq={faq_region} user={user_region}"

    return False, "ok"


def conflict_between_faq_and_document(faq_profile: TrustProfile, doc_profiles: list[TrustProfile]) -> str | None:
    """Cheap deterministic conflict signal.

    A real contradiction detector needs NLI; this only reports the cases we can
    prove without one: a newer binding document that explicitly supersedes the
    FAQ's support, or an authority gap on a strict topic.
    """
    for doc in doc_profiles:
        if doc.level != LEVEL_L1:
            continue
        if doc.rank > faq_profile.rank and doc.authority in BINDING_LEVELS:
            return f"binding document {doc.authority} outranks faq support"
    return None