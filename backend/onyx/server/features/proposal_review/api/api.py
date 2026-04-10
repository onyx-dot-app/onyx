"""Main router for Proposal Review (Argus).

Mounts all sub-routers under /proposal-review prefix.
"""

from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.server.features.proposal_review.configs import ENABLE_PROPOSAL_REVIEW

router = APIRouter(
    prefix="/proposal-review",
    dependencies=[Depends(require_permission(Permission.BASIC_ACCESS))],
)

if ENABLE_PROPOSAL_REVIEW:
    from onyx.server.features.proposal_review.api.config_api import (
        router as config_router,
    )
    from onyx.server.features.proposal_review.api.decisions_api import (
        router as decisions_router,
    )
    from onyx.server.features.proposal_review.api.proposals_api import (
        router as proposals_router,
    )
    from onyx.server.features.proposal_review.api.review_api import (
        router as review_router,
    )
    from onyx.server.features.proposal_review.api.rulesets_api import (
        router as rulesets_router,
    )

    router.include_router(rulesets_router, tags=["proposal-review"])
    router.include_router(proposals_router, tags=["proposal-review"])
    router.include_router(review_router, tags=["proposal-review"])
    router.include_router(decisions_router, tags=["proposal-review"])
    router.include_router(config_router, tags=["proposal-review"])
