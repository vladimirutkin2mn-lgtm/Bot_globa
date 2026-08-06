#!/usr/bin/env bash
set -euo pipefail

# These tests freeze the production-sensitive behavior that the oracle migration
# is allowed to reuse but not silently change. Keep this list intentionally
# small, explicit and independent from the future Reading domain.
pytest \
  tests/test_credits_repository_postgres.py::test_same_analysis_spend_and_refund_are_exactly_once \
  tests/test_credits_repository_postgres.py::test_different_spends_never_make_balance_negative \
  tests/test_credits_repository_postgres.py::test_cross_user_spend_never_exposes_or_refunds_owner_transaction \
  tests/test_credits_repository_postgres.py::test_public_unlock_and_refund_are_mutually_exclusive \
  tests/test_followup_service_postgres.py::test_concurrent_requests_make_one_llm_call_and_consume_once \
  tests/test_followup_service_postgres.py::test_technical_failure_releases_entitlement_for_retry \
  tests/test_followup_service_postgres.py::test_soft_delete_purges_encrypted_followup_history \
  tests/test_account_deletion_postgres.py::test_payment_completion_and_account_deletion_race_25_times \
  tests/test_account_deletion_postgres.py::test_complete_account_tombstone_preserves_immutable_ledger \
  tests/test_monetized_reading_postgres.py::test_paid_reading_unlock_is_exactly_once_under_concurrency \
    tests/test_monetized_reading_postgres.py::test_technical_failure_refunds_reading_spend_exactly_once \
    tests/test_shared_preview_entitlement_postgres.py::test_reading_preview_consumes_shared_entitlement_and_blocks_analysis \
    tests/test_shared_preview_entitlement_postgres.py::test_analysis_and_reading_reservations_are_mutually_exclusive \
    "$@"
