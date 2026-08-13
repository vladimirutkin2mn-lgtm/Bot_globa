# Telegram Stars payments

Telegram Stars are the Telegram-native production route for the bot's digital products. They
have the provider identity `telegram_stars`, market `TELEGRAM`, and currency `XTR`. The
implementation follows the official [Stars payments guide](https://core.telegram.org/bots/payments-stars)
and [Bot API](https://core.telegram.org/bots/api#payments).

When `TELEGRAM_STARS_ENABLED=true`, the Telegram payment screen exposes Stars together with the
configured YooKassa and Stripe routes. Each button starts its own checkout flow; enabling Stars
does not disable existing RUB, EUR, or USD callbacks.

Telegram's published policy says digital goods inside Telegram apps must use Stars exclusively.
The combined payment screen is an explicit product-owner decision and must be reconsidered if
Telegram enforcement or distribution requirements change.

## Commercial configuration

Stars are disabled and unpriced by default. Product owners must explicitly choose whole-Star
prices before rollout; the application will not silently derive them from RUB, EUR, or USD.
The approved production catalog is version-controlled in `production.public.env`, which Compose
loads after the secret `.env.prod` file:

```dotenv
BILLING_KILL_SWITCH=false
TELEGRAM_STARS_ENABLED=true
TELEGRAM_STARS_AMOUNT_READING_SINGLE=40
TELEGRAM_STARS_AMOUNT_READING_PACK_5=200
TELEGRAM_STARS_AMOUNT_SUBSCRIPTION_MONTHLY=280
SUBSCRIPTIONS_ENABLED=true
```

Every enabled price must be from 1 to 10,000 Stars. The bot returns clear terms and payment-support
instructions directly from `/terms` and `/paysupport`; these commands do not depend on external
pages or placeholder URLs. Checkout screens ask the user to read `/terms` before confirming.

## Payment lifecycle

1. The user chooses **Telegram Stars · ⭐**. The server creates or reuses one pending immutable
   `PaymentOrder` and encodes only its UUID in the invoice payload.
2. One-time products use `sendInvoice` with one `LabeledPrice`. The monthly product uses an
   invoice link with `subscription_period=2592000` (30 days).
3. In webhook mode, `pre_checkout_query` is validated and answered directly in the HTTP response,
   outside the durable queue, so the bot can meet Telegram's ten-second deadline. User identity,
   payload, order state, amount, and `XTR` currency must all match.
4. That answer is also the charge authorization. One order can back several invoice messages, and
   Telegram charges as soon as the answer is `ok`, so the order row is locked and
   `pre_checkout_query_id` / `pre_checkout_authorized_at` record the single in-flight
   authorization (revision `20260813_28`). A different query for the same order is refused for
   120 seconds; a Telegram retry of the same query id is idempotent, and an abandoned
   confirmation frees the order once the lease expires.
5. `successful_payment` remains a durable Telegram inbox update. Credits are granted only from
   that update, through the existing locked payment/subscription lifecycle.
6. `telegram_payment_charge_id` is the provider payment identity. Replays and concurrent workers
   produce one order completion and one append-only credit transaction. A second distinct charge
   against a completed order is never granted twice: it lands in `manual_review` with its own
   `provider_webhook_events` row so support can refund it.

The billing kill switch rejects new invoices and pre-checkout confirmation. It deliberately does
not discard successful-payment updates already issued by Telegram.

## Subscriptions

The monthly Stars invoice uses Telegram-managed 30-day renewal. The first payment charge ID is
the stable subscription identity used by `editUserStarSubscription`; each successful renewal has
its own charge ID and creates one new subscription period, payment order, and credit grant.

Telegram's `subscription` update drives cancellation, re-enable, and failed-renewal state; the
only understood states are `active`, `canceled` and `failed`, and anything else is logged rather
than silently dropped. A `failed` renewal moves the local subscription to `past_due` without
touching the already paid period — that transition is reserved for provider-managed schedules,
because Stripe and YooKassa report an exact period boundary and their own path owns it.

Stars subscriptions are excluded by name from merchant-scheduled renewal jobs because Telegram
owns the charge
schedule. Canceling preserves the current paid period and already granted credits.

## Refunds

The Bot API supports a full `refundStarPayment` against the original charge ID; partial Stars
refunds are not offered. The normal refund flow still reserves unused credits, executes provider
I/O in the billing worker, and appends a negative ledger entry only after success.

Telegram uses the original transaction ID for the outgoing refund. Internally the reversal gets
the distinct identity `stars-refund:{charge_id}` so it cannot collide with the original purchase
ledger row. If the network outcome is ambiguous, the worker searches recent `getStarTransactions`
pages before retrying. Configure the bounded search with `TELEGRAM_STARS_RECONCILIATION_PAGES`.

Refunding one subscription period does not cancel later renewals; the user must turn off
autorenewal separately.

## Staging acceptance

Stars have no sandbox: `refundStarPayment` and every invoice move real Stars even from a test bot,
and orders are always recorded with `provider_live_mode=true`. Run this checklist on a dedicated
staging bot with a funded account and expect the spend to be real.

- Confirm that zero-priced Stars fail startup; when Stars are disabled, no Stars button is shown.
- Enable Stars and verify the bot still shows every configured YooKassa and Stripe route alongside
  the Stars button; each callback must open the matching checkout flow.
- Buy every one-time SKU and verify the invoice shows the exact configured whole-Star amount.
- Replay the same `successful_payment` update and verify one completed order and one grant.
- Try a mismatched user, payload, currency, and amount in pre-checkout; each must be rejected.
- Tap **Buy** twice to get two invoice messages for the same order, then pay both: the second
  pre-checkout must be refused and no second charge may occur.
- Buy a monthly subscription, replay its first payment, then process one renewal; verify exactly
  two periods and two grants.
- Cancel and resume renewal; verify Telegram and local subscription state agree.
- Request a full refund with all credits unused; verify one reservation, one Bot API refund, one
  reversal, and a consumed reservation. Verify partial refund is unavailable.
- Force an ambiguous refund response and verify transaction reconciliation finds the existing
  refund without issuing a second ledger reversal.
- Test `/terms` and `/paysupport` from a fresh chat and confirm neither depends on an external URL.
- Run the deployment verifier and confirm `telegram_stars_configuration` reports
  `single=40, pack_5=200, monthly=280` from the live container environment.
