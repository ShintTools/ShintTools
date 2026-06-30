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

---

# Appendix A — Implementing Option A (GitHub App installation token)

The `token` returned to the client MUST be a credential GHCR accepts. GHCR's
`docker login` does a basic-auth → token-exchange, so the password has to be a
real GitHub credential (`ghs_…` App token or `github_pat_…` fine-grained PAT) —
an opaque/custom token is rejected with `denied: denied`.

Option A mints a **short-lived (~1 h) GitHub App installation token** per
request from an App private key held only on the server. Nothing is pre-shared
with the client.

## A.1 Create the GitHub App
1. Go to **https://github.com/settings/apps/new** (signed in as the account that
   owns the package — `Noctxas97Dev`).
2. **GitHub App name:** `ShintTools Core Pull` · **Homepage URL:** `https://shint.tools`
3. **Webhook:** uncheck **Active** (none needed).
4. **Permissions → Repository permissions → Packages: Read-only.** (Leave
   everything else "No access".)
5. **Where can this GitHub App be installed?** → **Only on this account.**
6. **Create GitHub App.** On the App's **General** page, note the **App ID**.

## A.2 Generate the private key
On the App's **General** page → **Private keys** → **Generate a private key** →
downloads a `.pem`. This is the server secret — never commit it, never send it
to a client.

## A.3 Install the App + confirm package access
1. App page → **Install App** → install on **Noctxas97Dev**.
2. "Only select repositories" → select **ShintTools** (the repo whose Actions
   publish the package). Confirm.
3. Get the **Installation ID** from the URL after install:
   `https://github.com/settings/installations/{INSTALLATION_ID}`
   (or `GET /app/installations` with an App JWT).
4. The package `shinttools-core-paid` is published by the ShintTools repo's
   workflow, so it's owned by `Noctxas97Dev` and reachable by an installation
   with `packages: read`. (If you ever down-scope by `repositories`, the package
   must be linked to that repo: Package → settings → "Repository access".)

## A.4 Store server secrets (dashboard env)
```
GH_APP_ID                = <App ID>
GH_APP_INSTALLATION_ID   = <Installation ID>
GH_APP_PRIVATE_KEY       = <full PEM contents, real newlines>
```
> ⚠️ The #1 cause of a 500 here is PEM newlines. If your host stores the key
> with literal `\n`, convert back to real newlines before signing:
> `privateKey.replace(/\\n/g, "\n")`.

## A.5 Mint logic (inside the already-validated handler)
After the paid + machine-binding check passes:
1. Build a JWT (RS256) signed with the private key: `iss = App ID`,
   `iat = now-60`, `exp = now+600` (≤ 10 min).
2. `POST https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens`
   with `Authorization: Bearer <JWT>`, `Accept: application/vnd.github+json`,
   body `{"permissions": {"packages": "read"}}`.
3. The response is `{"token": "ghs_…", "expires_at": "…"}`.
4. Return the contract shape (see §Response — 200).

### Node.js (recommended — `@octokit/auth-app` handles JWT + exchange + cache)
```js
import { createAppAuth } from "@octokit/auth-app";

const auth = createAppAuth({
  appId:          process.env.GH_APP_ID,
  privateKey:     process.env.GH_APP_PRIVATE_KEY,        // real newlines
  installationId: process.env.GH_APP_INSTALLATION_ID,
});

// in the POST /api/public/registry/pull-token handler, AFTER license validation:
const { token, expiresAt } = await auth({
  type: "installation",
  permissions: { packages: "read" },
});

return res.json({
  valid:      true,
  registry:   "ghcr.io",
  username:   "x-access-token",                          // any non-empty string
  token,                                                 // ghs_…
  image:      "ghcr.io/noctxas97dev/shinttools-core-paid",
  expires_at: expiresAt,                                 // ISO-8601
});
```

### Python (PyJWT + requests)
```python
import time, jwt, requests   # PyJWT, with cryptography installed for RS256

def installation_token():
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": GH_APP_ID},
        GH_APP_PRIVATE_KEY, algorithm="RS256")
    r = requests.post(
        f"https://api.github.com/app/installations/{GH_APP_INSTALLATION_ID}/access_tokens",
        headers={"Authorization": f"Bearer {assertion}",
                 "Accept": "application/vnd.github+json"},
        json={"permissions": {"packages": "read"}}, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d["token"], d["expires_at"]      # ghs_…, ISO-8601
```
Then return `{valid, registry:"ghcr.io", username:"x-access-token", token,
image:"ghcr.io/noctxas97dev/shinttools-core-paid", expires_at}`.

> `username` is ignored by GHCR for token auth — any non-empty string works.

## A.6 Verify
```
echo <token> | docker login ghcr.io -u x-access-token --password-stdin   # Login Succeeded
docker pull ghcr.io/noctxas97dev/shinttools-core-paid:latest
docker logout ghcr.io
```
A correct token starts with `ghs_`. (Then ping the launcher dev to re-run the
client verification: token → login → manifest.)

## A.7 500 troubleshooting
| Symptom | Cause |
|---|---|
| 500, "error:0909006C" / PEM/ASN.1 parse | `GH_APP_PRIVATE_KEY` newlines mangled — un-escape `\n` |
| 401 from `/access_tokens` ("integration not found" / bad JWT) | wrong App ID, JWT `exp` > 10 min, or clock skew |
| 404 from `/access_tokens` | wrong Installation ID |
| 403 / 422 from `/access_tokens` | App lacks `packages: read`, not installed, or `repositories[]` names a repo outside the install |
| 200 token but GHCR `denied` | token isn't `ghs_…` (still returning the opaque token) |
| 200 + `ghs_` token, `docker login` OK, but `pull` = **403 Forbidden** | the package is **user-account-owned**. GitHub App / fine-grained package access only works for **org-owned** packages — see Appendix B |

---

# Appendix B — Move the paid package to an organization

**Why:** a GitHub App installation token authenticates fine against a
**user-account**-owned GHCR package (`docker login` succeeds) but GHCR returns
**403** on pull — fine-grained package access (Apps, fine-grained PATs) is only
honored for **org-owned** packages. So the paid package must live under an org:
```
ghcr.io/<ORG>/shinttools-core-paid     (PRIVATE, org-owned)
```
The **free** package stays where it is (`ghcr.io/noctxas97dev/shinttools-core`,
public, user-owned, GITHUB_TOKEN-published) — only paid moves.

## B.1 GitHub side (you)

**1. Create / pick the org**
- github.com → **+** → **New organization** (Free plan is fine for private
  packages). Choose a slug → this is `<ORG>`.

**2. Install the GitHub App on the org**
- The existing **ShintTools Core Pull** App is installed on the *user* account;
  it must also be installed on **`<ORG>`**.
- App settings → **Install App** → install on `<ORG>` (any repo selection).
- Get the **org installation ID**: `GET /app/installations` (with an App JWT)
  → the entry whose `account.login == <ORG>`; or the URL
  `https://github.com/organizations/<ORG>/settings/installations/{ID}`.
- **Update the dashboard secret `GH_APP_INSTALLATION_ID`** to this org
  installation ID. (`GH_APP_ID` + `GH_APP_PRIVATE_KEY` stay the same — same App.)

**3. Create the workflow publish token**
- An org **owner** creates a PAT that can write to the org's GHCR:
  - classic PAT with **`write:packages`** (+ `read:packages`), **or**
  - fine-grained PAT, resource owner **`<ORG>`**, **Packages: Read and write**.
- Add it to `Noctxas97Dev/ShintTools` → Settings → Secrets and variables →
  Actions → **New repository secret**, name **`GHCR_ORG_TOKEN`**, value = the PAT.
- CI-only secret; never shipped to clients.

**4. After the first publish — grant the App + confirm private**
- `https://github.com/orgs/<ORG>/packages/container/shinttools-core-paid/settings`
- Visibility = **Private**.
- **Manage Actions access / Package access → add the GitHub App** ("ShintTools
  Core Pull") with **Read**. *(This is the step user-owned packages don't allow
  and is what fixes the 403.)*

## B.2 Code side (I do once you give me `<ORG>`)
- `publish-core.yml` — before the **paid** build-push, log in to ghcr.io with
  `GHCR_ORG_TOKEN`; paid image namespace → `ghcr.io/<ORG>/shinttools-core-paid`;
  point the assert-private step at the org package. Free push + free public
  marking stay on `GITHUB_TOKEN`, unchanged.
- launcher `app/constants.py` — `CORE_IMAGE_REMOTE_PAID_PRIVATE` →
  `ghcr.io/<ORG>/shinttools-core-paid:latest` (`requires_registry_auth` still
  matches the `shinttools-core-paid` substring).
- this doc + the dashboard's returned `image` field → org namespace (the client
  pulls the constants ref, so `image` is informational, but keep it consistent).

## B.3 Re-publish + verify
- Bump `CORE_VERSION` → 2.0.8, tag `v2.0.8` → workflow publishes
  `ghcr.io/<ORG>/shinttools-core-paid`.
- After B.1 step 4 (grant the App), re-run the client check: token →
  `docker login` → **pull** must now succeed.

## B.4 Then the rest of the cutover
- Launcher: flip `SHINTTOOLS_PAID_PRIVATE` default on, merge `develop`→`main`, release.
- Plugin: merge `develop-paid`→`main`.
- Delete the legacy public `:paid` / `*-paid` tags from `shinttools-core`.
