# Serper.dev Google Search API — Reference

Site: https://serper.dev/ (no dedicated docs.serper.dev site found; `docs.serper.dev` does not resolve)

## 1. Auth

Header: `X-API-KEY: <your key>`

Key comes from env var `SERPER_API_KEY`. Never print/log the key. Get one at https://serper.dev/api-keys.

A missing or wrong key returns `401`/`403`.

## 2. Our use: search query → organic results

Endpoint: `POST https://google.serper.dev/search`

Request: JSON body, `Content-Type: application/json`.

| field | notes |
|---|---|
| `q` | search query (required) |
| `gl` | country code, e.g. `"us"` |
| `hl` | language code, e.g. `"en"` |
| `num` | number of results |
| `page` | pagination |

```python
import os
import requests

def google_search(query: str, num: int = 10) -> list[dict]:
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={
            "X-API-KEY": os.environ["SERPER_API_KEY"],
            "Content-Type": "application/json",
        },
        json={"q": query, "num": num, "gl": "us", "hl": "en"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")}
        for r in data.get("organic", [])
    ]
```

## 3. Response shape

Top-level response includes `organic` plus optional `knowledgeGraph`, `answerBox`, `peopleAlsoAsk`, `relatedSearches`. Fields we care about, per item in `organic[]`:

- `title`
- `link`
- `snippet`
- `position`

## 4. Free tier

**2,500 free queries, no credit card required** — stated on the serper.dev homepage.

## 5. Useful operators for us

Pass these directly as/within `q`:

```python
google_search('site:linkedin.com/in "Head of Growth" "fintech"')
google_search('site:reddit.com "struggling with" cold email deliverability')
```

- `site:linkedin.com/in` — surface individual LinkedIn profiles matching a title/company/keyword for contact discovery.
- `site:reddit.com` — surface threads/comments where prospects discuss pain points, for signal-mining and voice-of-customer research.

## 6. Gotchas (per third-party pricing breakdown, coldiq.com — not verified on serper.dev directly since /pricing 404'd)

- Credits, not raw request counts, gate usage: **1 credit** for up to 10 results in a query, **2 credits** for 11–100 results — so requesting more than 10 results roughly doubles cost per query.
- This credit rule is documented as applying across all Serper endpoint types (search, images, news, maps, places, videos, shopping, scholar, patents, autocomplete), not just `/search`.
- Purchased credits expire **6 months** after purchase.
- Rate limits (queries/sec) are plan-dependent; only the Standard ($375) plan's **100 QPS** limit was found in sources — other tiers' QPS caps are unverified/not stated here.
