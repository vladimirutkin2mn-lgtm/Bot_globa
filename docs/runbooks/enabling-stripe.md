# Enabling Stripe

YooKassa serves the RU market and is already live. Stripe serves the international market
in EUR and USD, and is off until the steps below are done.

Everything here is enforced by code: the event list, the setting names and the amount
floor are the ones the application actually checks.

## One API key, two products

The Stripe **secret key is account-wide and is meant to be shared**. Both products on this
host use the same `sk_live_…`; nothing here needs a second key, a second account or a
second Stripe subscription.

The one value that is *not* shared is `STRIPE_WEBHOOK_SECRET` — and that is not an API key.
Stripe generates a `whsec_…` for each webhook endpoint you register, and uses it to sign
the deliveries to that endpoint. A signature produced for the neighbouring product's URL
does not verify against this one, so copying its `whsec_…` would make every event return
`401`.

Registering a second endpoint on the same account costs nothing and creates no new
credential. That is the only manual step.

## 1. Create the webhook endpoint

In the Stripe dashboard, **Developers → Webhooks → Add endpoint**.

**URL**

```
https://predict.mypresence.ru/webhooks/stripe
```

**Events** — exactly these eight; the handler ignores anything else:

```
checkout.session.completed
checkout.session.async_payment_succeeded
checkout.session.async_payment_failed
checkout.session.expired
invoice.paid
invoice.payment_failed
customer.subscription.updated
customer.subscription.deleted
```

The last four are only exercised once subscriptions are enabled, but subscribing now
avoids a second dashboard trip.

Copy the endpoint's **signing secret** (`whsec_…`). It belongs to this endpoint only.

### One account, two products

Stripe delivers every subscribed event to **every** endpoint on the account, so the
neighbouring product's endpoint will also receive this service's events, and this
service's endpoint will receive theirs.

Nothing breaks. Every checkout this service creates carries `metadata.product =
bot_globa`, and the webhook drops a checkout without it before the event reaches the
durable inbox. In the other direction, that product's handler already treats an unknown
order as terminal — but it logs one at **error** level, so its error log will show this
service's payments. Decide whether to filter there or accept the noise.

## 2. There is no catalog to create

Prices are sent inline with each checkout as `price_data`, so no Product or Price object
has to exist in the dashboard — for one-time sales or for the monthly plan. The catalog
lives entirely in settings, in minor units:

```bash
STRIPE_AMOUNT_READING_SINGLE_EUR_MINOR=99
STRIPE_AMOUNT_READING_SINGLE_USD_MINOR=99
STRIPE_AMOUNT_READING_PACK_5_EUR_MINOR=449
STRIPE_AMOUNT_READING_PACK_5_USD_MINOR=449
STRIPE_AMOUNT_SUBSCRIPTION_MONTHLY_EUR_MINOR=699
STRIPE_AMOUNT_SUBSCRIPTION_MONTHLY_USD_MINOR=699
```

These are the defaults, so an unset value is not a misconfiguration — override one only to
change a price. Each is floored at **50**, because
[Stripe rejects any charge below 0.50 EUR or USD](https://docs.stripe.com/currencies)
to keep its own fee from exceeding the payment. A price below that is refused at startup
rather than failing at the till.

The two astrology SKUs are priced as a single reading until they get their own figures.

## 3. Fill the environment

On the server, in `/opt/bot_globa/.env.prod`:

```bash
STRIPE_ENABLED=true
STRIPE_SECRET_KEY=sk_live_…          # the account key, may be shared
STRIPE_WEBHOOK_SECRET=whsec_…        # THIS endpoint's secret, never shared
```

That is the whole Stripe configuration. Refunds stay behind their own switch:

```bash
REFUNDS_ENABLED=true
```

Subscriptions have a prerequisite of their own — see the last section.

## 4. Restart and verify

```bash
cd /opt/bot_globa
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  exec -T api python -m app.cli.verify_deployment
```

The endpoint must reject an unsigned request:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://predict.mypresence.ru/webhooks/stripe \
  -H 'Content-Type: application/json' -d '{}'
# 401
```

Then send a test event from the dashboard's **Send test webhook** and confirm it returns
`200` there. A test event carries no product marker, so the handler will answer `200` with
`{"status":"ignored"}` — that is the correct response and proves signature verification
works.

## 5. Prove it end to end before trusting it

A real purchase in test mode is the only thing that proves checkout, webhook and ledger
agree. Use a Stripe test key and card `4242 4242 4242 4242`, buy one reading, then check:

- the reading unlocked in the bot;
- exactly one `spend` row in `credit_transactions` for that reading;
- the order reached `completed`.

Then repeat the same purchase callback twice — the ledger must not move the second time.
That is the exactly-once property the protected invariants cover in CI, verified here
against the real provider.

## Do not enable subscriptions yet

`SUBSCRIPTIONS_ENABLED` must stay `false` until subscription credits expire at the end of
each paid period. Today credits never expire, so a monthly plan would sell 30 permanent
credits for the price of one month — a reading at a third of the single-purchase price,
forever, for anyone who subscribes once and cancels.

Expiry cannot be applied retroactively: the ledger is append-only and those credits were
sold as permanent. So the order is fixed — ship expiry first, enable the plan second.

## What this does not cover

Live Stripe credentials cannot record the release attestations: the readiness check
rejects a key that does not start with `sk_test_` or `rk_test_`, and requires
`APP_ENV=staging`. Those five attestations describe a staging exercise, not this
deployment — see [`production-readiness.md`](production-readiness.md).
