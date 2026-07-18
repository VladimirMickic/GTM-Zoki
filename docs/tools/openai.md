# OpenAI API (structured outputs) — Reference

Docs: https://developers.openai.com/api/docs/guides/structured-outputs

## 1. Install / Auth

```bash
pip install openai
```

Reads `OPENAI_API_KEY` from env automatically (`OpenAI()` with no args). We load `.env`
via python-dotenv — never print the key.

## 2. Our use: markdown → structured drone fields (gpt-4o-mini)

Structured outputs with a Pydantic model — the SDK converts it to a strict JSON schema
and parses the reply back:

```python
from openai import OpenAI
from pydantic import BaseModel

class Extraction(BaseModel):
    company: str
    drone_models: list[str]

client = OpenAI()
completion = client.chat.completions.parse(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Extract drone facts from this markdown."},
        {"role": "user", "content": markdown},
    ],
    response_format=Extraction,
)
parsed = completion.choices[0].message.parsed   # Extraction instance or None
usage = completion.usage                        # .prompt_tokens / .completion_tokens
```

`gpt-4o-mini` supports structured outputs (available "starting with GPT-4o";
gpt-4o-mini explicitly listed).

## 3. Pricing (for cost log)

gpt-4o-mini: $0.15 / 1M input tokens, $0.60 / 1M output tokens.

## 4. Gotchas

- **`parsed` can be None** — on refusal (`message.refusal` set) or truncation
  (`finish_reason == "length"`). Check both before trusting the result.
- **Strict schema limits**: all fields effectively required; use defaults/`Optional`
  in the Pydantic model, no `additionalProperties`. `.parse()` handles this for you.
- **Long markdown**: trim input (we cap at ~12k chars) — the page content, not the
  whole site, decides extraction quality.
- Old `platform.openai.com/docs` URLs 301-redirect to `developers.openai.com`.
