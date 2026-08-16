"""link billing analytics to the same privacy-safe user subject

Revision ID: 20260816_33
Revises: 20260815_32
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_33"
down_revision: str | None = "20260815_32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PROJECT_WITH_SUBJECT = """
CREATE OR REPLACE FUNCTION project_billing_outbox_to_analytics() RETURNS trigger AS $$
DECLARE
    safe_properties jsonb;
    order_user_id text;
BEGIN
    IF NEW.event_type NOT IN ('checkout_started', 'purchase_completed', 'payment_failed') THEN
        RETURN NEW;
    END IF;

    SELECT user_id::text
    INTO order_user_id
    FROM payment_orders
    WHERE id = NEW.aggregate_id::uuid;

    safe_properties := jsonb_strip_nulls(jsonb_build_object(
        'order_id', NEW.aggregate_id,
        'product_code', NEW.payload ->> 'product_code',
        'product_version', NEW.payload ->> 'product_version',
        'provider', NEW.payload ->> 'provider',
        'market', NEW.payload ->> 'market',
        'currency', NEW.payload ->> 'currency',
        'credits', NEW.payload ->> 'credits',
        'failure_code', NEW.payload ->> 'failure_code',
        'mode', NEW.payload ->> 'mode'
    ));
    INSERT INTO analytics_events (
        id,
        event_name,
        subject_id,
        properties,
        idempotency_key,
        correlation_id
    ) VALUES (
        md5(NEW.id::text)::uuid,
        NEW.event_type,
        order_user_id,
        safe_properties,
        'billing_outbox:' || NEW.idempotency_key,
        NULL
    )
    ON CONFLICT (idempotency_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_PROJECT_WITHOUT_SUBJECT = """
CREATE OR REPLACE FUNCTION project_billing_outbox_to_analytics() RETURNS trigger AS $$
DECLARE
    safe_properties jsonb;
BEGIN
    IF NEW.event_type NOT IN ('checkout_started', 'purchase_completed', 'payment_failed') THEN
        RETURN NEW;
    END IF;
    safe_properties := jsonb_strip_nulls(jsonb_build_object(
        'order_id', NEW.aggregate_id,
        'product_code', NEW.payload ->> 'product_code',
        'provider', NEW.payload ->> 'provider',
        'market', NEW.payload ->> 'market',
        'currency', NEW.payload ->> 'currency',
        'credits', NEW.payload ->> 'credits',
        'failure_code', NEW.payload ->> 'failure_code'
    ));
    INSERT INTO analytics_events (
        id,
        event_name,
        subject_id,
        properties,
        idempotency_key,
        correlation_id
    ) VALUES (
        md5(NEW.id::text)::uuid,
        NEW.event_type,
        NULL,
        safe_properties,
        'billing_outbox:' || NEW.idempotency_key,
        NULL
    )
    ON CONFLICT (idempotency_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute(_PROJECT_WITH_SUBJECT)
    op.execute(
        """
        UPDATE analytics_events AS event
        SET subject_id = orders.user_id::text
        FROM payment_orders AS orders
        WHERE event.subject_id IS NULL
          AND event.event_name IN ('checkout_started', 'purchase_completed', 'payment_failed')
          AND event.properties ->> 'order_id' = orders.id::text
        """
    )
    op.create_index(
        "ix_analytics_events_subject_created",
        "analytics_events",
        ["subject_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_events_subject_created", table_name="analytics_events")
    op.execute(_PROJECT_WITHOUT_SUBJECT)
