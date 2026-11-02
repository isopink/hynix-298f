"""
리스크 검증 Hook (PreToolUse, mcp__kiwoom__place_order 직전).

에이전트가 무엇을 판단했든, 이 검사를 통과하지 못한 주문은 나가지 않습니다.
검사 중 오류가 나도 주문을 막습니다 (fail closed).
"""
import json
import os
import sys

AGENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(AGENT, "src"))


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    sys.exit(0)


def main():
    event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if not event.get("tool_name", "").endswith("place_order"):
        return
    import broker
    import common as C
    import risk
    C.load_env()

    o = event.get("tool_input") or {}
    order = {"code": str(o.get("code", "")), "side": o.get("side"), "qty": o.get("qty"),
             "confidence": o.get("confidence"), "rule_exit": o.get("rule_exit", False),
             "today_change": broker.cached_change(str(o.get("code", "")))}
    acc = C.read_json(C.ACCOUNT)
    price = broker.cached_quote(order["code"])
    if not acc or not price:
        deny("리스크 검증 불가: 먼저 get_account 와 plan_order 로 계좌와 현재가를 확인하세요.")

    bad = risk.check(order, acc, price)
    if bad:
        name = order["code"]
        for rule, detail in bad:
            C.journal("block", code=order["code"], name=name, side=order["side"], rule=rule, detail=detail, by="hook")
        deny("리스크 규칙 위반으로 주문 차단: " + " / ".join(f"{a}({b})" for a, b in bad))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        deny(f"리스크 검증 오류로 주문 차단: {type(e).__name__}: {e}")
