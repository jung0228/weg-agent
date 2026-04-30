#!/usr/bin/env python3
"""Shared baseline metadata for the transition-memory demos."""

from __future__ import annotations

from typing import Any


DEFAULT_BASELINE = "ours"

BASELINE_PROFILES: dict[str, dict[str, str]] = {
    "synapse": {
        "display_name": "Synapse",
        "family": "memory",
        "stored_unit": "trajectory_exemplar",
        "pipeline": [
            {
                "name": "State abstraction",
                "input": "Raw computer state such as HTML, screenshot, or DOM snapshot.",
                "output": "Concise task-relevant observation with less token cost and a trajectory anchor for retrieval.",
            },
            {
                "name": "Exemplar retrieval",
                "input": "Task metadata plus the abstracted state.",
                "output": "Retrieved exemplar trajectories from exemplar memory for the current action.",
            },
            {
                "name": "Trajectory-as-exemplar prompting",
                "input": "Current history together with retrieved exemplars.",
                "output": "Next action chosen from the TaE prompt together with a concrete memory-view justification.",
            },
            {
                "name": "Trajectory writeback",
                "input": "Chosen action plus the observed outcome.",
                "output": "Stored successful or failed trajectory exemplar for later reuse.",
            },
        ],
        "memory_view_instruction": (
            "summarize the retrieved past trajectory step that is most relevant "
            "to the current action, and make clear which exemplar should be reused later"
        ),
        "post_update": "append the successful or failed trajectory exemplar with its observed outcome",
    },
    "awm": {
        "display_name": "AWM",
        "family": "memory",
        "stored_unit": "workflow",
        "pipeline": [
            {
                "name": "Trajectory capture",
                "input": "Raw interaction trajectory and page history.",
                "output": "Cleaned step trace for workflow extraction.",
            },
            {
                "name": "Workflow abstraction",
                "input": "Trajectory trace plus page transitions.",
                "output": "Reusable workflow summary that generalizes across pages.",
            },
            {
                "name": "Workflow retrieval / use",
                "input": "Current page state and the workflow memory.",
                "output": "Workflow-guided next action or step.",
            },
        ],
        "memory_view_instruction": (
            "quote the reusable workflow step that applies to the current page state"
        ),
        "post_update": "refine the workflow abstraction or split the workflow if it conflicts",
    },
    "reasoningbank": {
        "display_name": "ReasoningBank",
        "family": "memory",
        "stored_unit": "reasoning_lesson",
        "pipeline": [
            {
                "name": "Episode mining",
                "input": "Success and failure trajectories from past tasks.",
                "output": "Candidate lessons, pitfalls, and strategies.",
            },
            {
                "name": "Reasoning distillation",
                "input": "Candidate lessons plus supporting episodes.",
                "output": "Reusable reasoning memory item.",
            },
            {
                "name": "Lesson retrieval / use",
                "input": "Current task state and retrieved reasoning memory.",
                "output": "Lesson-guided action choice.",
            },
        ],
        "memory_view_instruction": (
            "state the lesson, pitfall, or strategy distilled from previous success/failure"
        ),
        "post_update": "add a new lesson when the current attempt reveals a new pitfall",
    },
    "wma": {
        "display_name": "WMA",
        "family": "world_model",
        "stored_unit": "imagined_next_observation",
        "pipeline": [
            {
                "name": "Action proposal",
                "input": "Current observation, URL, objective, and previous action.",
                "output": "Sampled action candidates from the frozen policy model.",
            },
            {
                "name": "Next-state imagination",
                "input": "Current observation plus each candidate action.",
                "output": "Imagined next observation / transition delta for that candidate.",
            },
            {
                "name": "Value scoring and selection",
                "input": "Imagined next state, task objective, and current trajectory.",
                "output": "Candidate ranked by predicted utility; best action selected with argmax.",
            },
        ],
        "memory_view_instruction": (
            "describe the imagined next observation delta for each candidate action"
        ),
        "post_update": "no persistent memory writeback; the imagined transition is used immediately for ranking",
    },
    "webdreamer": {
        "display_name": "WebDreamer",
        "family": "world_model",
        "stored_unit": "imagined_page_change",
        "pipeline": [
            {
                "name": "Screenshot imagination",
                "input": "Webpage screenshot and a candidate action.",
                "output": "Imagined webpage change after the action.",
            },
            {
                "name": "Planning use",
                "input": "Simulated page changes for the candidate set.",
                "output": "Action choice guided by the imagined page aftermath.",
            },
            {
                "name": "Writeback",
                "input": "Most useful simulated page change.",
                "output": "Stored page-change memory for later planning.",
            },
        ],
        "memory_view_instruction": (
            "describe the imagined webpage change from the screenshot and candidate action"
        ),
        "post_update": "store the strongest simulated page change for later web look-ahead",
    },
    "rap": {
        "display_name": "RAP",
        "family": "world_model",
        "stored_unit": "imagined_rollout",
        "pipeline": [
            {
                "name": "Rollout imagination",
                "input": "Current state plus candidate action.",
                "output": "Imagined next state and reward signal.",
            },
            {
                "name": "Planning search",
                "input": "Rollouts across multiple candidate branches.",
                "output": "Search trace that supports the selected action.",
            },
            {
                "name": "Trace writeback",
                "input": "Best search trace after planning.",
                "output": "Stored rollout trace for reuse in later search.",
            },
        ],
        "memory_view_instruction": (
            "summarize the imagined rollout or planning trace and the implied reward"
        ),
        "post_update": "record the search trace that led to the chosen action",
    },
    "ours": {
        "display_name": "Ours",
        "family": "transition_memory",
        "stored_unit": "transition_memory",
        "pipeline": [
            {
                "name": "Transition capture",
                "input": "Observation plus each candidate action.",
                "output": "Explicit transition record O_t + A_i -> O*_{t+1}.",
            },
            {
                "name": "Transition use",
                "input": "Retrieved transition memory and the current task.",
                "output": "Memory-supported candidate choice with verification.",
            },
            {
                "name": "Conflict handling",
                "input": "Observed delta, failure signal, and conflict outcome.",
                "output": "Updated transition memory slot or conflict note.",
            },
        ],
        "memory_view_instruction": (
            "name the specific UI transition rule you want the agent to reuse later"
        ),
        "post_update": "store the observed delta, failure signal, and conflict outcome",
    },
}


def baseline_choices() -> tuple[str, ...]:
    return tuple(BASELINE_PROFILES.keys())


def baseline_profile(name: str) -> dict[str, str]:
    try:
        return BASELINE_PROFILES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown baseline '{name}'. Choose one of: {', '.join(baseline_choices())}") from exc


def baseline_display_name(name: str) -> str:
    return baseline_profile(name)["display_name"]


def build_prompt_payload(example: dict[str, Any], baseline: str) -> dict[str, Any]:
    profile = baseline_profile(baseline)
    return {
        "baseline": baseline,
        "baseline_display_name": profile["display_name"],
        "baseline_family": profile["family"],
        "stored_unit": profile["stored_unit"],
        "task": example["task"],
        "observation": example["observation"],
        "candidate_actions": example["candidate_actions"],
        "retrieved_transition_memory": example["retrieved_transition_memory"],
    }


def build_system_prompt(baseline: str) -> str:
    profile = baseline_profile(baseline)
    return (
        f"You are evaluating the {profile['display_name']} baseline for a web-agent transition benchmark. "
        "Return JSON only. Use exactly this top-level schema: "
        "{"
        '"candidate_evaluations":[{"id":"...","memory_view":"...",'
        '"expected_transition":"...","failure_signal":"...","verification_rule":"..."}],'
        '"selected_action":"...","selection_reason":"..."'
        "}. "
        f"For {profile['display_name']}, memory_view should {profile['memory_view_instruction']}. "
        "Keep expected_transition concrete, keep failure_signal observable, and keep verification_rule tied to a visible UI check."
        " When retrieved_transition_memory directly supports a candidate that advances the task, prefer that memory-supported action over exploratory UI actions such as opening sort menus."
    )
