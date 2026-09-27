"""Human-confirmed identity rules. Source facts remain immutable projections."""
from copy import deepcopy
from infrastructure.database import PersonResolution


def rules_for(session, document_id):
    return [{"id": r.id, "name": r.name, "target": r.target, "decision": r.decision}
            for r in session.query(PersonResolution).filter(PersonResolution.document_id == document_id).order_by(PersonResolution.id)]


def aliases_for(rules):
    mapping = {}
    for r in rules:
        if r["name"] == r["target"]:
            raise ValueError("请选择两个不同称呼")
        if r["decision"] == "same":
            if r["name"] in mapping and mapping[r["name"]] != r["target"]:
                raise ValueError("该称呼已有其他归属，请先撤销旧规则")
            mapping[r["name"]] = r["target"]

    def resolve(name):
        seen = set()
        while name in mapping:
            if name in seen:
                raise ValueError("称呼归属形成循环，请先撤销旧规则")
            seen.add(name)
            name = mapping[name]
        return name

    aliases = {name: resolve(name) for name in mapping}
    for r in rules:
        if r["decision"] == "different" and resolve(r["name"]) == resolve(r["target"]):
            raise ValueError("与已确认的不同人物规则冲突，请先撤销冲突规则")
    return aliases


def project_graph(graph, aliases):
    result = deepcopy(graph or {})
    result["people"] = list(dict.fromkeys(aliases.get(n, n) for n in result.get("people", [])))
    for relation in result.get("relationships", []):
        for field in ("subject", "object"):
            relation[field] = aliases.get(relation[field], relation[field])
    return result
