"""The single enforcement point.

Every tool routes every section and every field through `decide(...)`. Nothing else
in the system grants access. Two axes are enforced here and only here:

  1. Brand (tenancy): the requested brand must equal the brand the run is bound to.
  2. Visibility (field/section access): the data's visibility tag must be in the
     bound role's `can_see` list from entitlements.json.

`decide` is data-driven: it reads each field's own visibility tag and the role's
can_see list. It never hardcodes which fields are sensitive, because the tags differ
per brand (e.g. Brand C's `exclusivity` is operational, Brand C has `volume_rebate`
where Brand A has `margin_floor`). Hardcoding a field list would leak the moment the
data changed.

The function fails closed: an unknown role, an unknown brand binding, or a visibility
tag outside the known set all deny. Access is granted only on an explicit match.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config

# Decision codes. The audit log categorizes every access by one of these, so a
# withheld field and a cross-brand block read differently in the evidence trail.
SERVED = "served"
WITHHELD = "withheld"
CROSS_BRAND_BLOCK = "cross_brand_block"
DENIED_UNKNOWN_ROLE = "denied_unknown_role"
DENIED_UNKNOWN_VISIBILITY = "denied_unknown_visibility"


@dataclass(frozen=True)
class Principal:
    """The identity a run is bound to at launch.

    Frozen on purpose: there is no setter, no tool, and no model output that can
    change `brand` or `role` after construction. Self-escalation is impossible
    because the type makes it unrepresentable, not because a prompt asks nicely.
    """

    brand: str
    role: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str       # one of the constants above; drives audit categorization
    reason: str     # human-readable, written verbatim into the audit log


def decide(principal: Principal, requested_brand: str, visibility: str,
           entitlements: dict) -> Decision:
    """Decide whether `principal` may see data of `visibility` for `requested_brand`.

    Order matters and is deliberately fail-closed:
      role known -> brand matches -> visibility tag known -> tag in can_see.
    The first failing gate denies; only passing all of them serves.
    """
    roles = entitlements.get("roles", {})

    # Gate 1: the bound role must exist in the entitlements config.
    role_cfg = roles.get(principal.role)
    if role_cfg is None:
        return Decision(False, DENIED_UNKNOWN_ROLE,
                        f"role {principal.role!r} is not in entitlements; denied")

    # Gate 2: tenancy. A run bound to one brand can never reach another brand's
    # data, regardless of role — including power_user, which is cross-brand across
    # SEPARATE runs but never within one. This is the cross-brand block.
    if requested_brand != principal.brand:
        return Decision(False, CROSS_BRAND_BLOCK,
                        f"run is bound to brand {principal.brand!r}; "
                        f"requested {requested_brand!r}; cross-brand access refused")

    # Gate 3: the visibility tag must be one we recognize, or we fail closed. This
    # stops a typo'd tag in the data from being served by default.
    if visibility not in config.VISIBILITY_LEVELS:
        return Decision(False, DENIED_UNKNOWN_VISIBILITY,
                        f"visibility {visibility!r} is not a known level; denied")

    # Gate 4: field/section access. Served only if the tag is in the role's can_see.
    can_see = role_cfg.get("can_see", [])
    if visibility in can_see:
        return Decision(True, SERVED,
                        f"{principal.role} may see {visibility} data")
    return Decision(False, WITHHELD,
                    f"{visibility} data is withheld at the {principal.role} "
                    f"access level")
