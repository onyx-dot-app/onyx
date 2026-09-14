"""Render visible evidence directly instead of nesting JSON inside JSON strings."""

import json


def source_card_context(context: str) -> str:
    try:
        payload = json.loads(context)
    except (ValueError, TypeError):
        return context
    if not isinstance(payload, dict):
        return context
    state = payload.get("current_turn_state", {})
    if not isinstance(state, dict):
        return context
    cards = []
    for result in state.get("results", []):
        preview = result.get("content_preview")
        if not isinstance(preview, str):
            continue
        try:
            evidence = json.loads(preview)
        except ValueError:
            # Preserve every visible character when the old preview cut a JSON body.
            cards.append(
                {"result_ref": result.get("result_ref"), "raw_visible_excerpt": preview}
            )
            continue
        if not isinstance(evidence, dict) or not isinstance(
            evidence.get("results"), list
        ):
            cards.append(
                {"result_ref": result.get("result_ref"), "raw_visible_excerpt": preview}
            )
            continue
        notes = {k: v for k, v in evidence.items() if k != "results"}
        if notes:
            cards.append(
                {"result_ref": result.get("result_ref"), "evidence_notes": notes}
            )
        cards.extend(
            {"result_ref": result.get("result_ref"), **passage}
            for passage in evidence["results"]
        )
    if not cards:
        return context
    # Keep control state and receipts, but eliminate the nested evidence serialization.
    state = {**state, "results": cards}
    return json.dumps({**payload, "current_turn_state": state}, ensure_ascii=False)
