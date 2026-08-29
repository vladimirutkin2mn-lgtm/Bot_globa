"""Database infrastructure.

Importing this package registers **every** mapped model with the declarative ``Base``,
and that completeness is a runtime requirement rather than a convenience.

SQLAlchemy resolves a foreign key to its target table lazily, on the first flush that
sorts the mapped tables. A process that writes a row whose table references a model it
never imported therefore fails while writing, not while starting: the billing worker
inserted ``credit_transactions``, whose ``reading_id`` points at ``readings``, without
ever importing the reading models, so every captured payment raised
``NoReferencedTableError`` and retried itself into ``manual_review`` with no credits
granted. A test process imports everything and never sees it.

Keep this list exhaustive. Any new module declaring a ``Base`` subclass belongs here.
"""

from app.db.analytics import AnalyticsEvent  # noqa: F401
from app.db.birth_profile_models import BirthProfile  # noqa: F401
from app.db.daily_horoscope_models import DailyHoroscopePreference  # noqa: F401
from app.db.followups import FollowUpQuestion
from app.db.fsm_models import TelegramFSMState  # noqa: F401
from app.db.memory_models import OracleMemoryItem  # noqa: F401
from app.db.models import User  # noqa: F401
from app.db.reading_followups import ReadingFollowUp  # noqa: F401
from app.db.reading_models import Reading  # noqa: F401
from app.db.refund_metadata import configure_refund_metadata
from app.db.release_gates import ReleaseGateAttestation
from app.db.subscription_models import SubscriptionPeriod  # noqa: F401
from app.db.telegram_models import TelegramUpdateInbox  # noqa: F401

configure_refund_metadata()

__all__ = ["FollowUpQuestion", "ReleaseGateAttestation"]
