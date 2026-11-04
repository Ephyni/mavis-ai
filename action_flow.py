"""Single-action session state and explicit yes/no interpretation for MAVIS."""

import re

LEGACY_KEYS = (
    "pending_delete_task_id", "pending_delete_memory_id",
    "pending_memory_proposal_id", "pending_memory_delete_options",
    "pending_task_selection", "pending_task_options",
)
KINDS = {"save_memory", "delete_memory", "complete_task", "delete_task"}


def clear_pending(session):
    """Invalidate an unfinished action without modifying user data."""
    session.pop("pending_action", None)
    for key in LEGACY_KEYS:
        session.pop(key, None)


def set_pending(session, kind, stage, target_id=None, option_ids=()):
    """Keep exactly one next step using IDs, never copied memory content."""
    if kind not in KINDS or stage not in {"select", "confirm"}:
        raise ValueError("Unsupported pending action.")
    if stage == "confirm" and (type(target_id) is not int or target_id <= 0):
        raise ValueError("A deletion or save must identify one record.")
    clear_pending(session)
    session["pending_action"] = {
        "kind": kind,
        "stage": stage,
        "target_id": target_id if stage == "confirm" else None,
        "option_ids": [
            value for value in tuple(option_ids)[:4]
            if type(value) is int and value > 0
        ] if stage == "select" else [],
    }


def confirmation_answer(message):
    """Accept only explicit approvals/refusals, never a full new command."""
    answer = re.sub(r"[,.!?]+", " ", message.strip().casefold())
    answer = " ".join(answer.split())
    answer = re.sub(r"^(?:hey\s+)?mavis\s+", "", answer)
    if answer in {
        "yes", "yes please", "yes do it", "yes go ahead", "yep", "yeah",
        "yes save it", "yes please save it", "save it",
        "yes delete it", "yes please delete it", "delete it",
        "yes forget it", "yes please forget it", "forget it",
        "confirm", "confirm delete", "confirm deletion", "confirm save",
        "sure", "go ahead", "absolutely",
    }:
        return "yes"
    if answer in {
        "no", "no thanks", "no cancel", "no don't", "no do not",
        "no don't save it", "no do not save it",
        "no don't delete it", "no do not delete it",
        "don't delete it", "do not delete it",
        "don't save it", "do not save it",
        "cancel", "cancel deletion", "stop", "never mind", "nevermind",
        "reject",
    }:
        return "no"
    return None
