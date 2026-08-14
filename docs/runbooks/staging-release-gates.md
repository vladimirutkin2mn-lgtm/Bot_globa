# Staging for the five live release gates

This environment exists only to produce the live evidence required by
[`production-readiness.md`](production-readiness.md) before limited production. It is not
a second production environment and must never receive production provider credentials,
production database state, or acquisition traffic.

## Isolation contract

Staging is a separate Compose project named `bot_globa_staging` with:

- its own PostgreSQL 17 volume (`staging_pgdata`);
- a server-side `.env.staging` that is never committed or synced over an existing copy;
- a separate Telegram bot when Telegram UI is used for the gate procedure;
- Stripe test credentials only (`sk_test_` / `rk_test_`);
- YooKassa test-shop credentials only;
- a staging OpenAI key/model and a deliberately small staging spend envelope;
- its own admin token;
- a stable proxy alias `bot-globa-staging-api` on the proxy-owned external `web` network.

The only infrastructure shared with production is the Docker `web` network used by the
host proxy. No staging service publishes a host port.

## One-time host setup

Create a dedicated directory and a staging environment file on the host:

```bash
mkdir -p /opt/bot_globa_staging
cp .env.staging.example /opt/bot_globa_staging/.env.staging
chmod 600 /opt/bot_globa_staging/.env.staging
```

Fill `.env.staging` on the host. Replace the example hostname with a dedicated staging
HTTPS hostname and configure only sandbox/test provider credentials. Do not copy
`.env.prod`.

Create a GitHub Environment named `staging` and configure only deployment access there:

- `DEPLOY_HOST`
- `DEPLOY_SSH_KEY`
- `DEPLOY_SSH_KNOWN_HOSTS`
- optional `DEPLOY_PATH` (defaults to `/opt/bot_globa_staging`)

Provider/API credentials stay in the host-side `.env.staging`, not in workflow inputs or
repository files.

## Bootstrap without a public route

Run the manual workflow **Bot Globa deploy staging** on the exact candidate ref. Leave
`public_staging_url` empty on the first bootstrap.

The deploy will:

1. sync source without overwriting `.env.staging`;
2. write a non-secret `.env.staging.release` containing the exact `github.sha` and
   checklist version;
3. refuse to create or replace the proxy-owned `web` network;
4. build the staging images;
5. start only the isolated staging database;
6. run `app.cli.release` under the migration advisory lock;
7. start the staging API and workers;
8. verify `bot-globa-staging-api` is actually attached to `web`;
9. run internal health, deployment verification and `/admin/release-readiness` checks.

The smoke refuses a release identity unless the readiness response reports
`app_env=staging`, a code SHA, a schema revision and a checklist version.

## Add the public staging route

After the first internal deploy is healthy, add a dedicated DNS/Caddy route in the proxy
owner's configuration. Example only — use the staging hostname you actually control:

```caddy
<staging-host> {
    encode zstd gzip
    reverse_proxy bot-globa-staging-api:8000
}
```

Then re-run **Bot Globa deploy staging** with `smoke_only=true` and
`public_staging_url=https://<staging-host>`.

The public smoke does not follow redirects. `/health/live` and `/health/ready` must each
return a direct HTTP 200 through DNS, TLS, Caddy and the staging upstream.

## Inspect release readiness

Keep the admin token in a shell environment variable rather than putting it into command
history:

```bash
export STAGING_URL=https://<staging-host>
read -rsp 'Staging admin token: ' ADMIN_API_TOKEN; echo
curl --fail --silent --show-error \
  -H "X-Admin-Token: ${ADMIN_API_TOKEN}" \
  "${STAGING_URL}/admin/release-readiness"
```

Before evidence is recorded, the five gates should be `missing`; configuration blockers
must be fixed rather than bypassed. The snapshot is bound to the exact deployed code SHA,
Alembic revision and checklist version.

## Execute and attest the five gates

The required gates are:

1. `stripe_subscription_sandbox`
2. `yookassa_subscription_sandbox`
3. `stripe_refund_sandbox`
4. `yookassa_refund_sandbox`
5. `openai_followup_staging`

Follow the live procedures tracked in issue #41. CI, mocks and local tests are not valid
substitutes for those five external-provider runs.

After a real gate succeeds, record only a non-secret evidence reference:

```bash
GATE=stripe_subscription_sandbox
EVIDENCE_REF=staging/stripe-subscription/<provider-test-object-id>

curl --fail --silent --show-error \
  -X POST \
  -H "X-Admin-Token: ${ADMIN_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"status\":\"passed\",\"evidence_ref\":\"${EVIDENCE_REF}\"}" \
  "${STAGING_URL}/admin/release-gates/${GATE}"
```

Repeat only after observing authoritative provider/application evidence for each gate. Do
not put credentials, receipt details, private user content or full webhook payloads in
`evidence_ref`.

`ready_for_limited_production=true` is expected only when all five attestations match the
current code/schema/checklist **and** the financial blocker counts are zero. A billing job,
outbox event, payment order or refund in manual review is a release blocker, not a reason
to edit the readiness check.

## Releasing a new candidate

Deploying a new commit changes `RELEASE_CODE_SHA`; old attestations automatically become
`stale`. A schema change does the same through the recorded Alembic revision. Re-run the
five gates for the exact candidate that will move to limited production.
