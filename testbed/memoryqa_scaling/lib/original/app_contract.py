"""Read the pinned app's relationship function without Django/DB/network setup.

Only the function and literal SLOTS table are compiled; imports and the rest of
the service module are never executed. Live parity tests also exercise the real
Django function, provider payloads, and description request.
"""
import ast
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace


def relationships(backend, family):
    source = Path(backend) / "apps/families/services.py"
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name == "relationship") or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SLOTS" for t in n.targets))]
    if len(nodes) != 2:
        raise ValueError("앱 관계 함수 구조가 바뀌었습니다. 어댑터를 다시 검증하세요.")
    namespace = {"Membership": SimpleNamespace(Slot=SimpleNamespace(OWNER="owner"))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    people = {m["key"]: SimpleNamespace(pk=i + 1, gender=m["gender"], slot=m["slot"])
              for i, m in enumerate(family["members"])}

    class Members:
        def filter(self, *, user):
            return SimpleNamespace(first=lambda: SimpleNamespace(slot=user.slot))

    room = SimpleNamespace(members=Members())
    return {viewer: {author: namespace["relationship"](v, a, room) for author, a in people.items()}
            for viewer, v in people.items()}


def model_defaults(backend):
    """Read explicit os.getenv defaults from the app, without reading .env."""
    names = {"OPENAI_MODEL", "POST_AI_MODEL", "POST_AI_SERVICE_TIER",
             "POST_AI_REASONING_EFFORT", "GRAPHITI_MODEL"}
    result = {}
    for node in ast.parse((Path(backend) / "configs/settings.py").read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    call = node.value
                    if (isinstance(call.func, ast.Attribute) and call.func.attr == "getenv"
                            and len(call.args) == 2 and ast.literal_eval(call.args[0]) == target.id):
                        result[target.id] = ast.literal_eval(call.args[1])
    if set(result) != names:
        raise ValueError("앱 모델 기본 설정 구조가 바뀌었습니다.")
    return result


def utc_time(value):
    from datetime import datetime
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()


def episode_body(author, description):
    # Exact construction_workers.construct format. Covered by a live-worker mock test.
    return f"작성자: {author}\n상세 설명: {description}"
