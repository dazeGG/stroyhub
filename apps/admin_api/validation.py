from typing import Annotated, Literal

from pydantic import StringConstraints

CanonicalProductStatus = Literal["active", "inactive"]
ShopIdentityStatus = Literal["active", "hold", "disabled", "out_of_scope"]
ShopCandidateStatus = Literal["pending", "stale", "hidden", "archived", "approved"]
ShopScrapeStatus = Literal[
    "new",
    "ok",
    "scheduled",
    "running",
    "success",
    "partial",
    "failed",
    "disabled",
]
ScrapeRunStatus = Literal["running", "success", "partial", "failed", "skipped"]

ActorName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ReasonText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
NonEmptyTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
NormalizedTitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
