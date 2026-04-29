#!/usr/bin/env python3
"""Run a tiny API-based transition-memory demo.

This intentionally avoids the OpenAI Python SDK so the only required setup is:

    export OPENAI_API_KEY=...
    export OPENAI_MODEL=...
    python3 research_note/web_transition/baselines/api_transition_demo.py flight

The point is not official reproduction. The point is to force every method into
the same output slots so the meeting can focus on what is missing.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


EXAMPLES = {
    "flight": {
        "task": "Book the cheapest flight to Tokyo.",
        "observation": {
            "page_type": "flight_results",
            "visible_regions": ["filter_sidebar", "result_list", "ad_banner", "sort_dropdown"],
            "salient_elements": [
                {"id": "e1", "role": "button", "text": "Select", "region": "result_list", "context": "Flight AA 123, $412, 1 stop"},
                {"id": "e2", "role": "button", "text": "View Deals", "region": "ad_banner", "context": "Sponsored hotel+flight package"},
                {"id": "e3", "role": "checkbox", "text": "1 stop", "region": "filter_sidebar"},
                {"id": "e4", "role": "combobox", "text": "Sort by", "region": "sort_dropdown"},
            ],
        },
        "candidate_actions": [
            {"id": "a1", "op": "click", "target": "e1", "surface": "Select"},
            {"id": "a2", "op": "click", "target": "e2", "surface": "View Deals"},
            {"id": "a3", "op": "click", "target": "e3", "surface": "1 stop"},
            {"id": "a4", "op": "click", "target": "e4", "surface": "Sort by"},
        ],
        "retrieved_transition_memory": [
            {
                "page_state": "flight_results",
                "action_affordance": "select_result_item",
                "expected_transition": "fare detail, booking modal, passenger-info step, or login/booking modal appears",
                "failure_signal": "selected element is ad/promo, disabled, or outside organic result list",
                "verification_rule": "accept modal or fare-detail panel as progress even if URL does not change",
            },
            {
                "page_state": "flight_results",
                "action_affordance": "click_promo_or_ad",
                "expected_transition": "sponsored promo/deal page opens",
                "failure_signal": "leaves flight-selection workflow",
                "verification_rule": "reject if the page becomes package/deal flow instead of flight booking",
            },
        ],
    },
    "shopping": {
        "task": "Buy black waterproof bluetooth speaker under $30.",
        "observation": {
            "page_type": "product_detail",
            "price": "$27.99",
            "visible_regions": ["variant_options", "warranty", "buy_box"],
        },
        "candidate_actions": [
            {"id": "b1", "op": "click", "target": "black option", "surface": "Black"},
            {"id": "b2", "op": "click", "target": "warranty checkbox", "surface": "Add warranty"},
            {"id": "b3", "op": "click", "target": "add to cart", "surface": "Add to Cart"},
        ],
        "retrieved_transition_memory": [
            {
                "page_state": "product_detail",
                "action_affordance": "commit_variant_option",
                "expected_transition": "selected option changes; price, stock, or buy button may update",
                "failure_signal": "option unavailable, price exceeds budget, or buy button disabled",
                "verification_rule": "re-read price and availability after selecting the variant",
            },
            {
                "page_state": "product_detail",
                "action_affordance": "add_warranty",
                "expected_transition": "warranty selected; total price increases",
                "failure_signal": "budget constraint violated",
                "verification_rule": "reject if total price exceeds $30",
            },
            {
                "page_state": "product_detail",
                "action_affordance": "add_to_cart",
                "expected_transition": "cart modal or cart page appears",
                "failure_signal": "required option missing, cart count unchanged, or validation error appears",
                "verification_rule": "accept cart modal as progress even without URL change",
            },
        ],
    },
}


def load_dotenv() -> None:
    """Load simple KEY=VALUE pairs from .env without adding a dependency."""
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def call_openai(payload: dict) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY")
    if not model:
        raise SystemExit("Missing OPENAI_MODEL")

    body = {
        "model": model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "Return JSON only. For each candidate action, fill exactly these fields: "
                    "expected_transition, failure_signal, verification_rule. Then select one action."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"OpenAI API error {exc.code}: {detail}") from exc


def extract_output_text(response: dict) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "\n".join(chunks).strip()


def main() -> None:
    load_dotenv()
    name = sys.argv[1] if len(sys.argv) > 1 else "flight"
    if name not in EXAMPLES:
        raise SystemExit(f"Unknown example '{name}'. Choose one of: {', '.join(EXAMPLES)}")

    response = call_openai(EXAMPLES[name])
    print(extract_output_text(response))


if __name__ == "__main__":
    main()

