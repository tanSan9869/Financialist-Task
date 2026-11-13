import json
import os
from groq import Groq

SCHEMA = ('{"sub_scores": {"skills": 0-100, "education": 0-100, "experience": 0-100, "projects": 0-100}, '
          '"recommendation": "Shortlist|Maybe|Reject", "reason": "1-3 sentences"}')
KEYS = ("skills", "education", "experience", "projects")
MAX_CV_CHARS = 12000


def recommend(total, th):
    if total >= th["shortlist_min"]:
        return "Shortlist"
    return "Maybe" if total >= th["maybe_min"] else "Reject"


def build_prompt(cfg, role, cv_text):
    r = cfg["roles"][role]
    return cfg["prompt_template"].format(
        role=role,
        criteria="\n".join(f"- {c}" for c in r["criteria"]),
        weights=json.dumps(r["weights"]),
        schema=SCHEMA,
        cv_text=cv_text[:MAX_CV_CHARS],
    )


def _parse(raw, weights, th):
    d = json.loads(raw)
    subs = {k: max(0.0, min(100.0, float(d["sub_scores"][k]))) for k in KEYS}
    wsum = sum(weights.get(k, 0) for k in KEYS) or 1
    total = round(sum(subs[k] * weights.get(k, 0) for k in KEYS) / wsum, 1)  # weights applied in code
    return {"total_score": total, "sub_scores": subs,
            "recommendation": recommend(total, th),  # always derived in code from config thresholds
            "reason": str(d.get("reason", ""))[:1000]}


def score(cfg, role, cv_text):
    """Returns (result | None, error). One retry at temperature 0 before failing."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    prompt = build_prompt(cfg, role, cv_text)
    last = ""
    for temp in (cfg["llm"].get("temperature", 0.2), 0.0):
        try:
            resp = client.chat.completions.create(
                model=cfg["llm"]["model"], temperature=temp,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
            return _parse(resp.choices[0].message.content, cfg["roles"][role]["weights"], cfg["thresholds"]), ""
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:300]
    return None, f"Scoring failed after retry: {last}"
