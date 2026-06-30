# Paid Core image — registry pull-token contract (shint.tools dashboard)

Status: **TO IMPLEMENT on the dashboard (shint.tools).** Blocks the paid-Core
private-package migration. The launcher and the UE5/Unity plugin already call
this endpoint (behind a feature flag) but it does not exist yet.

## Why this exists

The free Core image (`ghcr.io/noctxas97dev/shinttools-core`) is a **public**
package — the Fab marketplace plugin pulls it anonymously on first install.

GHCR visibility is **per-package, not per-tag**: you cannot keep `:latest`
public while making `:paid` private inside the same package. So the paid edition
moves to its **own private package**:

```
ghcr.io/noctxas97dev/shinttools-core-paid      (PRIVATE)
```

A private package cannot be pulled anonymously. Paid clients therefore need a
short-lived credential. Rather than ship a static PAT in the launcher (a shared
secret), the dashboard — which already authenticates the license — mints a
read-only, expiring GHCR pull token per request. This keeps "the image is the
entitlement" true: no valid paid license → no token → no pull.

## Endpoint

```
POST /api/public/registry/pull-token
Content-Type: application/json
```

### Request

```json
{
  "license_key": "st_xxxxxxxxxxxxxxxx",
  "machine_id": "<hardware fingerprint, same value used by /license/validate>"
}
```

### Response — 200 (entitled)

```json
{
  "valid": true,
  "registry": "ghcr.io",
  "username": "shinttools-pull",
  "token": "<short-lived GHCR pull token>",
  "image": "ghcr.io/noctxas97dev/shinttools-core-paid",
  "expires_at": "2026-06-30T12:15:00Z"
}
```

* `username` — any non-empty string; `docker login` requires a username but the
  token is what authorizes. Use a stable bot handle.
* `token` — a credential that grants **`read:packages` on `shinttools-core-paid`
  only**. Two acceptable implementations:
  1. **GitHub App installation token** (preferred): an App installed on the
     `Noctxas97Dev` account with `packages: read`, minted per request via
     `POST /app/installations/{id}/access_tokens` with the repository/permission
     scoped down. ~1 h TTL, automatically expiring.
  2. **Fine-grained PAT** with `read:packages`, stored as a server secret and
     returned directly. Simpler, but it is long-lived — rotate on a schedule and
     prefer option 1 if feasible.
* `expires_at` — ISO-8601 UTC. The client treats the token as single-use per
  pull and does not cache it past this instant.

### Response — 403 (not entitled)

Return this for: unknown/invalid key, free-tier key, expired subscription, or a
key whose `machine_id` binding does not match the request (mirror the
`/license/validate` binding check — do not mint a token for a key bound to a
different machine).

```json
{ "valid": false, "error": "License is not on a paid tier." }
```

### Response — other

* `429` if you rate-limit (the client backs off and falls back to the bundled
  Core payload).
* `5xx` on internal error — the client treats any non-200 as "no token" and
  falls back, so a dashboard outage degrades to the bundled Core, never a hard
  install failure.

## Security notes

* Validate the license **server-side** exactly as `/license/validate` does
  (tier ∈ {indie, studio, enterprise} AND machine binding matches). The token is
  only as safe as this check.
* Scope the token to **read-only** and to the **paid package only**. It must not
  grant write, and must not grant read on unrelated private packages.
* Prefer the shortest workable TTL (≤ 1 h). The client logs in, pulls, logs out.
* Log issuance (key id, machine_id, timestamp) for audit + abuse detection. A
  single key minting tokens from many machine_ids is a leak signal.

## Client behaviour (already implemented, flag-gated)

1. Launcher / plugin resolves the paid tier (license key on disk).
2. Calls `POST /api/public/registry/pull-token`.
3. On 200: `docker login ghcr.io -u <username> -p <token>`, pulls
   `shinttools-core-paid:<tag>`, then `docker logout ghcr.io`.
4. On any failure: logs the reason and falls back to the bundled Core payload so
   the install still completes.

The migration does **not** cut over (workflow stays publishing paid to the old
public package, clients keep the flag off) until this endpoint is live in
production and smoke-tested. See the migration checklist in the PR description.
