"""Decision-grade Numa funnel report built only from privacy-safe analytics metadata."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_REPORT_SQL = text(
    """
    WITH typed AS (
        SELECT
            event_name,
            subject_id,
            created_at,
            properties,
            properties ->> 'source' AS source,
            properties ->> 'experiment_assignment' AS experiment_assignment,
            properties ->> 'flow' AS flow,
            properties ->> 'entity_id' AS entity_id
        FROM analytics_events
        WHERE created_at >= :start_at
          AND created_at < :end_at
          AND event_name LIKE 'numa_%'
          AND properties ->> 'test_traffic' = 'false'
    ),
    funnel AS (
        SELECT
            source,
            experiment_assignment,
            flow,
            count(*) FILTER (WHERE event_name = 'numa_entry') AS entries,
            count(DISTINCT subject_id) FILTER (WHERE event_name = 'numa_entry') AS entry_users,
            count(*) FILTER (WHERE event_name = 'numa_question_accepted') AS questions_accepted,
            count(*) FILTER (
                WHERE event_name = 'numa_free_answer_delivered'
            ) AS free_answers_delivered,
            count(*) FILTER (WHERE event_name = 'numa_paywall_shown') AS paywalls_shown,
            count(*) FILTER (WHERE event_name = 'numa_checkout_started') AS checkouts_started,
            count(*) FILTER (WHERE event_name = 'numa_purchase_confirmed') AS purchases,
            count(DISTINCT subject_id)
                FILTER (WHERE event_name = 'numa_purchase_confirmed') AS purchase_users,
            count(*) FILTER (WHERE event_name = 'numa_full_unlocked') AS full_unlocks,
            count(DISTINCT subject_id)
                FILTER (WHERE event_name = 'numa_repeat_activity') AS repeat_users,
            count(*) FILTER (WHERE event_name = 'numa_daily_delivered') AS daily_delivered,
            count(*) FILTER (WHERE event_name = 'numa_daily_action') AS daily_actions,
            count(*) FILTER (WHERE event_name = 'numa_share_intent') AS share_intents,
            count(*) FILTER (WHERE event_name = 'numa_recipient_entry') AS recipient_entries
        FROM typed
        GROUP BY source, experiment_assignment, flow
    ),
    feedback AS (
        SELECT
            q.source,
            q.experiment_assignment,
            q.flow,
            count(*) FILTER (
                WHERE f.properties ->> 'stage_code' = 'preview'
            ) AS preview_feedback,
            count(*) FILTER (
                WHERE f.properties ->> 'stage_code' = 'preview'
                  AND f.properties ->> 'reaction_code' = 'hit'
            ) AS preview_hits,
            count(*) FILTER (
                WHERE f.properties ->> 'stage_code' = 'full'
            ) AS full_feedback,
            count(*) FILTER (
                WHERE f.properties ->> 'stage_code' = 'full'
                  AND f.properties ->> 'reaction_code' = 'hit'
            ) AS full_hits
        FROM analytics_events AS f
        JOIN typed AS q
          ON q.event_name = 'numa_question_accepted'
         AND q.subject_id = f.subject_id
         AND q.entity_id = f.properties ->> 'reading_id'
        WHERE f.event_name = 'reading_feedback_submitted'
          AND f.created_at >= :start_at
          AND f.created_at < :end_at
        GROUP BY q.source, q.experiment_assignment, q.flow
    )
    SELECT
        funnel.source,
        funnel.experiment_assignment,
        funnel.flow,
        funnel.entries,
        funnel.entry_users,
        funnel.questions_accepted,
        funnel.free_answers_delivered,
        funnel.paywalls_shown,
        funnel.checkouts_started,
        funnel.purchases,
        funnel.purchase_users,
        funnel.full_unlocks,
        funnel.repeat_users,
        funnel.daily_delivered,
        funnel.daily_actions,
        funnel.share_intents,
        funnel.recipient_entries,
        coalesce(feedback.preview_feedback, 0) AS preview_feedback,
        coalesce(feedback.preview_hits, 0) AS preview_hits,
        coalesce(feedback.full_feedback, 0) AS full_feedback,
        coalesce(feedback.full_hits, 0) AS full_hits,
        CASE
            WHEN funnel.questions_accepted = 0 THEN NULL
            ELSE funnel.free_answers_delivered::double precision / funnel.questions_accepted
        END AS free_delivery_rate,
        CASE
            WHEN funnel.entry_users = 0 THEN NULL
            ELSE funnel.purchase_users::double precision / funnel.entry_users
        END AS purchase_user_rate,
        CASE
            WHEN funnel.entry_users = 0 THEN NULL
            ELSE funnel.repeat_users::double precision / funnel.entry_users
        END AS repeat_user_rate,
        CASE
            WHEN coalesce(feedback.preview_feedback, 0) = 0 THEN NULL
            ELSE feedback.preview_hits::double precision / feedback.preview_feedback
        END AS preview_hit_rate,
        CASE
            WHEN coalesce(feedback.full_feedback, 0) = 0 THEN NULL
            ELSE feedback.full_hits::double precision / feedback.full_feedback
        END AS full_hit_rate,
        CASE
            WHEN funnel.daily_delivered = 0 THEN NULL
            ELSE funnel.daily_actions::double precision / funnel.daily_delivered
        END AS daily_action_rate,
        CASE
            WHEN funnel.share_intents = 0 THEN NULL
            ELSE funnel.recipient_entries::double precision / funnel.share_intents
        END AS share_recipient_rate
    FROM funnel
    LEFT JOIN feedback
      USING (source, experiment_assignment, flow)
    ORDER BY funnel.source, funnel.experiment_assignment, funnel.flow
    """
)


@dataclass(frozen=True, slots=True)
class NumaDecisionReportRow:
    source: str
    experiment_assignment: str
    flow: str
    entries: int
    entry_users: int
    questions_accepted: int
    free_answers_delivered: int
    paywalls_shown: int
    checkouts_started: int
    purchases: int
    purchase_users: int
    full_unlocks: int
    repeat_users: int
    daily_delivered: int
    daily_actions: int
    share_intents: int
    recipient_entries: int
    preview_feedback: int
    preview_hits: int
    full_feedback: int
    full_hits: int
    free_delivery_rate: float | None
    purchase_user_rate: float | None
    repeat_user_rate: float | None
    preview_hit_rate: float | None
    full_hit_rate: float | None
    daily_action_rate: float | None
    share_recipient_rate: float | None


async def numa_decision_report(
    session: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
) -> tuple[NumaDecisionReportRow, ...]:
    """Return source/variant funnel metrics with configured test traffic excluded."""

    if start_at >= end_at:
        raise ValueError("report start must be before report end")
    result = await session.execute(_REPORT_SQL, {"start_at": start_at, "end_at": end_at})
    return tuple(NumaDecisionReportRow(**dict(row)) for row in result.mappings())
