#!/usr/bin/env python3
"""Print deterministic step-by-step IO for the meeting examples."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from baseline_profiles import baseline_choices, baseline_profile


def load_examples() -> dict:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    from api_transition_demo import EXAMPLES  # type: ignore

    return EXAMPLES


def action_summary(action: dict) -> str:
    return f"{action['id']}={action['op']} {action['surface']}"


def infer_affordance(action: dict) -> str:
    surface = action["surface"].lower()
    target = str(action.get("target", "")).lower()
    if "view deals" in surface or "promo" in target or "ad banner" in target:
        return "click_promo_or_ad"
    if "select" in surface:
        return "select_result_item"
    if "stop" in surface or "filter" in target:
        return "apply_filter"
    if "sort" in surface:
        return "open_sort_menu"
    if "black" in surface:
        return "commit_variant_option"
    if "warranty" in surface or "warranty" in target:
        return "add_warranty"
    if "cart" in surface:
        return "add_to_cart"
    return "unknown"


def transition_for_action(action: dict, memories: list[dict]) -> dict:
    affordance = infer_affordance(action)
    for memory in memories:
        if memory["action_affordance"] == affordance:
            return {
                "expected_transition": memory["expected_transition"],
                "failure_signal": memory["failure_signal"],
                "verification_rule": memory["verification_rule"],
            }

    fallback = {
        "apply_filter": {
            "expected_transition": "result list refreshes; URL may remain unchanged",
            "failure_signal": "no selected filter chip and no result-list change",
            "verification_rule": "check selected filter chip or changed result count, not only URL",
        },
        "open_sort_menu": {
            "expected_transition": "sort dropdown/menu expands",
            "failure_signal": "no menu appears or unrelated navigation happens",
            "verification_rule": "verify sort options are visible before selecting one",
        },
        "add_to_cart": {
            "expected_transition": "cart modal or cart page appears",
            "failure_signal": "required option missing, cart count unchanged, or validation error appears",
            "verification_rule": "accept cart modal as progress even without URL change",
        },
    }
    return fallback.get(
        affordance,
        {
            "expected_transition": "unknown",
            "failure_signal": "unknown",
            "verification_rule": "observe actual UI delta and update memory",
        },
    )


def memory_view_for_action(example: dict, action: dict, baseline: str) -> str:
    affordance = infer_affordance(action)
    profile = baseline_profile(baseline)
    if baseline == "synapse":
        return f"retrieved trajectory exemplar for {affordance}: {action['surface']} on a similar page"
    if baseline == "awm":
        return f"workflow step for {affordance}: follow the reusable page routine"
    if baseline == "reasoningbank":
        if affordance == "click_promo_or_ad":
            return "lesson: avoid sponsored detours when the user wants the core booking/shopping flow"
        return "lesson: prefer the organic result or valid variant path, then verify the UI delta"
    if baseline == "wma":
        predicted = transition_for_action(action, example["retrieved_transition_memory"])["expected_transition"]
        return f"imagined next observation: {predicted}"
    if baseline == "webdreamer":
        predicted = transition_for_action(action, example["retrieved_transition_memory"])["expected_transition"]
        return f"imagined webpage change from screenshot: {predicted}"
    if baseline == "rap":
        predicted = transition_for_action(action, example["retrieved_transition_memory"])["expected_transition"]
        return f"imagined rollout: {predicted}; planning trace should maximize task progress"
    if baseline == "ours":
        return f"transition rule: {transition_for_action(action, example['retrieved_transition_memory'])['verification_rule']}"
    return profile["memory_view_instruction"]


def render_baseline(example: dict, baseline: str) -> dict:
    profile = baseline_profile(baseline)
    actions = example["candidate_actions"]
    first_action = actions[0]["id"]
    memories = example["retrieved_transition_memory"]

    candidate_evaluations = []
    for action in actions:
        transition = transition_for_action(action, memories)
        candidate_evaluations.append(
            {
                "id": action["id"],
                "memory_view": memory_view_for_action(example, action, baseline),
                "expected_transition": transition["expected_transition"],
                "failure_signal": transition["failure_signal"],
                "verification_rule": transition["verification_rule"],
            }
        )

    return {
        "baseline": baseline,
        "method": profile["display_name"],
        "stored_unit": profile["stored_unit"],
        "inference_input": ["task", "O_t", "candidate_actions", "retrieved_transition_memory"],
        "candidate_evaluations": candidate_evaluations,
        "selected_action": first_action,
        "selection_reason": (
            "Choose the action that best advances the task while keeping the UI delta "
            "easy to verify against the retrieved memory."
        ),
        "post_action_update": [
            "compare actual_delta with expected_transition",
            "record success/failure signal",
            profile["post_update"],
        ],
    }


def render_suite(example: dict) -> dict:
    return {
        "baselines": [render_baseline(example, baseline) for baseline in baseline_choices()],
    }


def main() -> None:
    examples = load_examples()
    name = sys.argv[1] if len(sys.argv) > 1 else "flight"
    if name not in examples:
        raise SystemExit(f"Unknown example '{name}'. Choose one of: {', '.join(examples)}")

    example = examples[name]
    result = {
        "example": name,
        "task": example["task"],
        "candidate_actions": [action_summary(action) for action in example["candidate_actions"]],
        "baselines": render_suite(example)["baselines"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
