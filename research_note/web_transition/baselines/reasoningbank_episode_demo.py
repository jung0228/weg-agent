#!/usr/bin/env python3
"""Create a concrete ReasoningBank-style episode trace for the flight task."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT = Path(
    "/Users/jhw/Desktop/web/hyeonwoo/eval_results/letsur/gemini-3-flash-preview/"
    "20260429_compare_flight/reasoningbank/taskflight_0"
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def memory_markdown(items: list[dict[str, str]]) -> str:
    blocks = []
    for idx, item in enumerate(items, start=1):
        blocks.append(
            "\n".join(
                [
                    f"# Memory Item {idx}",
                    f"## Title {item['title']}",
                    f"## Description {item['description']}",
                    f"## Content {item['content']}",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def build_episode() -> dict[str, Any]:
    initial_bank = [
        {
            "id": "M0-1",
            "title": "Prefer primary result cards over promotional surfaces",
            "description": "Use when a result page mixes organic items with ads, banners, or package promotions.",
            "content": (
                "For booking-style tasks, first choose the primary result card that matches the user goal. "
                "Avoid promotional tiles unless the task explicitly asks for a bundled deal."
            ),
        },
        {
            "id": "M0-2",
            "title": "Verify progress by page state, not only URL changes",
            "description": "Use when web apps open modals, side panels, or in-page checkout flows.",
            "content": (
                "Treat a fare-detail panel, checkout modal, or passenger-information form as progress even if the URL is unchanged. "
                "Use visible UI state as the verification signal."
            ),
        },
    ]

    steps = [
        {
            "step": 1,
            "label": "Step 1",
            "phase": "policy_action",
            "task": "Book the cheapest flight to Tokyo.",
            "observation": {
                "state_id": "flight_results",
                "summary": "Search results show a cheapest organic flight card, a sponsored deal banner, filters, and a sort control.",
                "visible_elements": [
                    "e1 Select - Flight AA 123, $412, 1 stop",
                    "e2 View Deals - sponsored hotel+flight package",
                    "e3 1 stop filter",
                    "e4 Sort by",
                ],
            },
            "retrieved_memory_ids": ["M0-1", "M0-2"],
            "candidate_actions": [
                {"id": "a1", "action": "click('e1')", "surface": "Select cheapest organic flight"},
                {"id": "a2", "action": "click('e2')", "surface": "Open sponsored deal"},
                {"id": "a3", "action": "click('e4')", "surface": "Open sort menu"},
            ],
            "llm_input_summary": "task + flight_results observation + retrieved memory M0-1/M0-2 + candidate actions",
            "llm_output": {
                "thought": (
                    "The cheapest organic result directly matches the task. The retrieved memory says to prefer primary result cards "
                    "and to accept in-page fare panels as progress."
                ),
                "selected_action": "a1",
                "action": "click('e1')",
                "memory_used": ["M0-1", "M0-2"],
            },
            "environment_result": {
                "next_state_id": "fare_detail_panel",
                "transition": "A fare-detail panel opens for Flight AA 123 at $412.",
                "verification": "Visible fare summary and Continue button confirm progress.",
            },
            "bank_delta": {
                "before": 2,
                "after": 2,
                "note": "No new memory is appended during the episode; the policy only reads retrieved memory.",
            },
        },
        {
            "step": 2,
            "label": "Step 2",
            "phase": "policy_action",
            "task": "Book the cheapest flight to Tokyo.",
            "observation": {
                "state_id": "fare_detail_panel",
                "summary": "The chosen $412 flight is shown in a fare-detail panel with Continue, baggage details, and close controls.",
                "visible_elements": [
                    "e5 Continue",
                    "e6 Baggage details",
                    "e7 Close panel",
                ],
            },
            "retrieved_memory_ids": ["M0-2"],
            "candidate_actions": [
                {"id": "a4", "action": "click('e5')", "surface": "Continue"},
                {"id": "a5", "action": "click('e6')", "surface": "Baggage details"},
                {"id": "a6", "action": "click('e7')", "surface": "Close panel"},
            ],
            "llm_input_summary": "task + fare_detail_panel observation + retrieved memory M0-2 + current trajectory",
            "llm_output": {
                "thought": (
                    "The selected fare is still the cheapest. Continuing advances the booking funnel, while baggage details and close controls "
                    "do not complete the user request."
                ),
                "selected_action": "a4",
                "action": "click('e5')",
                "memory_used": ["M0-2"],
            },
            "environment_result": {
                "next_state_id": "passenger_info",
                "transition": "Passenger information page appears for the selected $412 flight.",
                "verification": "Traveler form and flight summary are visible.",
            },
            "bank_delta": {
                "before": 2,
                "after": 2,
                "note": "Still no bank update; the trajectory is accumulating for later extraction.",
            },
        },
        {
            "step": 3,
            "label": "Step 3",
            "phase": "policy_action",
            "task": "Book the cheapest flight to Tokyo.",
            "observation": {
                "state_id": "passenger_info",
                "summary": "The traveler information form is visible with a selected-flight summary and checkout controls.",
                "visible_elements": [
                    "e8 Traveler details form",
                    "e9 Continue as guest",
                    "e10 Sign in",
                    "e11 Back to results",
                ],
            },
            "retrieved_memory_ids": ["M0-2"],
            "candidate_actions": [
                {"id": "a7", "action": "click('e9')", "surface": "Continue as guest"},
                {"id": "a8", "action": "click('e10')", "surface": "Sign in"},
                {"id": "a9", "action": "click('e11')", "surface": "Back to results"},
            ],
            "llm_input_summary": "task + passenger_info observation + retrieved memory M0-2 + current trajectory",
            "llm_output": {
                "thought": (
                    "The task is satisfied up to the booking form without entering personal or payment data. The correct stopping point is to report "
                    "that the cheapest flight has been selected and the booking form is ready."
                ),
                "selected_action": "finish",
                "action": "send_msg_to_user('Selected the $412 flight to Tokyo and reached the traveler information step.')",
                "memory_used": ["M0-2"],
            },
            "environment_result": {
                "next_state_id": "episode_success",
                "transition": "The episode stops before entering personal or payment information.",
                "verification": "Selected-flight summary remains visible on the traveler information page.",
            },
            "bank_delta": {
                "before": 2,
                "after": 2,
                "note": "The bank will be updated after the full trajectory is judged and distilled.",
            },
        },
    ]

    extracted_items = [
        {
            "id": "M1",
            "title": "Advance booking tasks through the primary result funnel",
            "description": "Use when a booking task starts from a results page containing both organic results and promotional detours.",
            "content": (
                "Select the relevant organic result first, then follow the visible Continue or checkout control. "
                "Avoid ad banners, package deals, and exploratory controls when the user asks to book a specific cheapest option."
            ),
            "source_steps": ["Step 1", "Step 2"],
        },
        {
            "id": "M2",
            "title": "Stop before private checkout fields when no user data is provided",
            "description": "Use when a task reaches forms that require personal, account, or payment information.",
            "content": (
                "Treat arrival at the correct traveler or checkout form as the completion boundary unless the user has supplied the required private data. "
                "Report the selected item and current state instead of fabricating form values."
            ),
            "source_steps": ["Step 3"],
        },
    ]

    return {
        "task": "Book the cheapest flight to Tokyo.",
        "success_criterion": "Select the cheapest organic flight and reach the traveler information step without entering private data.",
        "initial_bank": initial_bank,
        "steps": steps,
        "judge": {
            "input": "task + full trajectory + final observation",
            "output": "SUCCESS",
            "reason": "The agent selected the cheapest visible organic fare and reached the booking form boundary.",
        },
        "extraction": {
            "input": "query + <think>/<action> trajectory + correctness signal",
            "output_format": "Markdown memory items with Title / Description / Content",
            "items": extracted_items,
        },
        "consolidation": {
            "bank_before_count": len(initial_bank),
            "appended_count": len(extracted_items),
            "bank_after_count": len(initial_bank) + len(extracted_items),
        },
        "final_bank": initial_bank + extracted_items,
    }


def write_episode(task_dir: Path) -> None:
    episode = build_episode()
    write_json(task_dir / "reasoningbank_episode_trace.json", episode)
    write_json(
        task_dir / "metadata.json",
        {
            "provider": "local",
            "model": "reasoningbank-episode-demo",
            "run_id": "20260429_compare_flight",
            "baseline": "reasoningbank",
            "example_name": "flight",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "episode_trace": "reasoningbank_episode_trace.json",
        },
    )
    write_json(
        task_dir / "result.json",
        {
            "task": episode["task"],
            "selected_action": episode["steps"][-1]["llm_output"]["selected_action"],
            "selection_reason": episode["judge"]["reason"],
            "success_criterion": episode["success_criterion"],
            "trajectory_steps": len(episode["steps"]),
            "memory_items_extracted": len(episode["extraction"]["items"]),
            "bank_before_count": episode["consolidation"]["bank_before_count"],
            "bank_after_count": episode["consolidation"]["bank_after_count"],
        },
    )
    write_json(
        task_dir / "interact_messages.json",
        [
            {"role": "system", "content": "ReasoningBank episode demo with retrieved memory and post-episode memory extraction."},
            {"role": "user", "content": episode["task"]},
            {"role": "assistant", "content": json.dumps(episode["steps"], ensure_ascii=False)},
        ],
    )
    write_text(task_dir / "system_prompt.txt", "ReasoningBank policy prompt with retrieved memory items injected before each action.\n")
    write_text(task_dir / "user_prompt.txt", json.dumps({"task": episode["task"], "initial_bank": episode["initial_bank"]}, ensure_ascii=False, indent=2))
    write_text(task_dir / "assistant_output.txt", json.dumps(episode, ensure_ascii=False, indent=2))
    write_text(task_dir / "reasoningbank_memory_items.md", memory_markdown(episode["extraction"]["items"]))

    for step in episode["steps"]:
        step_dir = task_dir / f"S{step['step']}"
        write_text(
            step_dir / "system_prompt.txt",
            "Below are some memory items accumulated from past interactions. Use them when relevant, then output the next action.\n",
        )
        write_json(
            step_dir / "user_prompt.txt",
            {
                "task": episode["task"],
                "observation": step["observation"],
                "retrieved_memory": [
                    item for item in episode["initial_bank"] if item["id"] in step["retrieved_memory_ids"]
                ],
                "candidate_actions": step["candidate_actions"],
                "trajectory_so_far": [
                    {
                        "step": prev["step"],
                        "action": prev["llm_output"]["action"],
                        "next_state": prev["environment_result"]["next_state_id"],
                    }
                    for prev in episode["steps"]
                    if prev["step"] < step["step"]
                ],
            },
        )
        write_json(
            step_dir / "metadata.json",
            {
                "step": step["step"],
                "phase": step["phase"],
                "state_id": step["observation"]["state_id"],
                "selected_action": step["llm_output"]["selected_action"],
                "bank_before": step["bank_delta"]["before"],
                "bank_after": step["bank_delta"]["after"],
                "baseline": "reasoningbank",
            },
        )
        write_json(step_dir / "llm_output.json", step["llm_output"])
        write_text(
            step_dir / "acc_tree.txt",
            "\n".join(
                [
                    f"task: {episode['task']}",
                    f"state: {step['observation']['state_id']}",
                    f"retrieved_memory: {', '.join(step['retrieved_memory_ids'])}",
                    f"selected_action: {step['llm_output']['action']}",
                    f"transition: {step['environment_result']['transition']}",
                    f"verification: {step['environment_result']['verification']}",
                    f"bank_delta: {step['bank_delta']['before']} -> {step['bank_delta']['after']}",
                ]
            )
            + "\n",
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    write_episode(Path(args.out))
    print(Path(args.out) / "reasoningbank_episode_trace.json")


if __name__ == "__main__":
    main()
