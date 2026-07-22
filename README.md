# ShintTools Core

Docker image that powers the ShintTools plugins for **Unreal Engine 5** and
**Unity 6** — code validation, asset optimization, and QA automation for
game studios.

The plugins connect to this image; it is not meant to be used standalone.

---

## Pull

```bash
docker pull ghcr.io/shinttools/shinttools-core:latest
```

## Run

```bash
docker run -p 18200:18200 ghcr.io/shinttools/shinttools-core:latest
```

Health check:

```bash
curl http://localhost:18200/health
# {"status":"ok",...}
```

## Tags

| Tag | Edition |
|---|---|
| `latest` | Free |
| `paid` | Indie / Studio (requires a license key) |

---

Plans, license keys, and plugin downloads: **[shint.tools](https://shint.tools)**
