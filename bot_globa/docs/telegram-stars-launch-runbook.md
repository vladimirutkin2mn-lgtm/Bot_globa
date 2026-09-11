# Numa — Telegram Stars launch runbook

Status: pre-live checklist for digital-goods payments inside Telegram.

This document closes the documentation requirement in task 07 of `numa-product-plan-2026-09-08.md`. It does **not** authorize production rollout, change current intentionally low test prices, enable a commercial price experiment or replace owner/legal approval of user-facing terms and support contacts.

## Source of truth

Before a live payment launch, re-check the current official Telegram documentation:

- Bot Payments API for Digital Goods and Services: https://core.telegram.org/bots/payments-stars
- Bot API payments objects and methods: https://core.telegram.org/bots/api

Telegram's current rule for digital goods/services sold inside Telegram is to use Telegram Stars with currency `XTR`.

## What the payment flow must do

For an in-Telegram digital purchase:

1. Create/send an invoice in `XTR`.
2. Receive `pre_checkout_query` and explicitly approve or reject it.
3. Do **not** grant the entitlement merely because pre-checkout was approved.
4. Wait for `successful_payment`.
5. Persist the payment identifiers needed for idempotency/reconciliation, including `telegram_payment_charge_id`.
6. Grant the purchased entitlement exactly once after confirmed success.
7. If delivery fails after payment, treat it as a delivery/recovery problem, not as a failed payment; reopening the already purchased result must not charge again.
8. Keep refund/reconciliation paths available. Telegram Stars refunds use `refundStarPayment(user_id, telegram_payment_charge_id)`.

Existing Numa ledger/idempotency, ownership, reconciliation and entitlement rules remain authoritative; this runbook must not create a parallel payment ledger.

## Pre-live checklist

### Product and pricing

- [ ] Current product codes and entitlements match the actual UI copy.
- [ ] Session copy states one complete reading plus up to three included follow-up questions within 24 hours after full unlock.
- [ ] Pack/subscription copy comes from real configuration rather than hard-coded marketing claims.
- [ ] Current intentionally low test prices remain unchanged until the owner explicitly approves commercial prices.
- [ ] No independent price experiment is running at the same time as another small-audience text/frequency experiment unless explicitly approved.

### Telegram Stars protocol

- [ ] Digital-goods invoices inside Telegram use `currency="XTR"`.
- [ ] `pre_checkout_query` is handled within Telegram's required response window.
- [ ] Entitlement is granted only after `successful_payment`.
- [ ] `telegram_payment_charge_id` is durably stored and tied to the internal transaction without exposing it to analytics.
- [ ] Repeated Telegram updates cannot duplicate a purchase or entitlement.
- [ ] A post-payment send failure cannot create a second charge on retry/reopen.
- [ ] Refund path is tested against a non-production/test transaction before live launch.
- [ ] Reconciliation can distinguish purchase, refund and recurring/renewal events where applicable.

### Terms, support and disputes — owner blockers

Telegram requires an easy way to access purchase terms and customer support before live operation and specifically requires bots selling digital goods/services to handle `/paysupport` for payment issues.

Do not invent these values in code. Before live launch the owner must approve:

- [ ] final Terms and Conditions text or URL;
- [ ] how the user accepts the terms before purchase;
- [ ] support contact/channel and response owner;
- [ ] `/support` (or equivalent clearly communicated support entry);
- [ ] `/paysupport` response and payment-dispute routing;
- [ ] refund/dispute operating procedure;
- [ ] statement that Telegram support cannot resolve purchases made from this bot on the merchant's behalf.

Until these items are approved and implemented, mark Stars payments as **not ready for unrestricted production launch**, even if the technical checkout flow works.

### Security and operations

- [ ] Two-step verification is enabled for the Telegram account controlling the bot.
- [ ] Production secrets are outside the repository and rotate through the existing secret-management path.
- [ ] Payment database backups and restore procedure are verified.
- [ ] Monitoring covers failed pre-checkout handling, successful payment without entitlement, duplicate updates, refund failures and post-payment delivery failures.
- [ ] Test identities/payments remain excludable from product analytics and economics.
- [ ] No questions, answers, birth data, Telegram IDs, charge IDs or payment payloads enter product analytics.

### Mobile acceptance before release

On a real Telegram mobile client verify at minimum:

- [ ] one-session Stars offer;
- [ ] invoice amount/currency and product wording;
- [ ] successful checkout;
- [ ] exact saved-result resume after payment;
- [ ] reopening without a second charge;
- [ ] failed/retried delivery behavior;
- [ ] terms/support accessibility;
- [ ] `/paysupport` route once owner-approved support details are configured;
- [ ] refund path in the intended test environment/process.

Record only privacy-safe pass/fail observations. Do not store screenshots containing private questions, answers, birth data, Telegram IDs, payment credentials or raw provider payloads in the repository.

## Go / no-go

A live launch is **GO** only when all of the following are true:

- Stars protocol checks pass;
- ledger/idempotency/reconciliation checks pass;
- real mobile payment/resume QA passes;
- owner-approved terms/support/dispute handling is available;
- production price/configuration changes, if any, were approved separately.

Any failed item above is **NO-GO** for unrestricted live payments. A NO-GO does not require changing existing test prices or disabling unrelated Numa functionality.
