"""Conservative repairs for generated chapters; never invent memory evidence."""
import re
from copy import deepcopy
from pydantic import BaseModel, Field, ValidationError


def validation_message(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, item['loc'])) or '内容'}: {item['msg']}"
            for item in exc.errors(include_input=False, include_url=False)
        )[:2000]
    return str(exc)[:1000]


def normalize_chapter(data, characters):
    data = deepcopy(data)
    if not isinstance(data, dict):
        return data
    ids = {p['id'] for p in characters}
    names = {}
    for p in characters:
        names.setdefault(p['name'], []).append(p['id'])

    def identity(value):
        if not isinstance(value, str):
            return value
        if value in ids:
            return value
        matches = names.get(value, [])
        return matches[0] if len(matches) == 1 else value

    for event in data.get('events', []):
        if not isinstance(event, dict):
            continue
        event['participants'] = [identity(p) for p in event.get('participants', [])]
        text = event.get('text', '')
        for view in event.get('viewpoints', []):
            if not isinstance(view, dict):
                continue
            view['character_id'] = identity(view.get('character_id'))
            view['known_people'] = [identity(p) for p in view.get('known_people', [])]
            quote = view.get('quote', '')
            if isinstance(text, str) and isinstance(quote, str) and quote and quote not in text:
                # Only tolerate whitespace differences, preserving an exact source slice.
                compact = re.sub(r'\s', '', quote)
                positions = [i for i, char in enumerate(text) if not char.isspace()]
                start = ''.join(text[i] for i in positions).find(compact) if compact else -1
                if start >= 0:
                    exact = text[positions[start]:positions[start + len(compact) - 1] + 1]
                    if len(exact) <= 500:
                        view['quote'] = exact
    return data


class EvidenceChoice(BaseModel):
    event_id: str
    character_id: str
    evidence_id: int = Field(ge=0)
    memory: str = Field(min_length=1, max_length=1000)


class EvidenceRepairs(BaseModel):
    repairs: list[EvidenceChoice] = Field(default_factory=list, max_length=360)


def evidence_passages(text):
    """Index actual source slices so the model never has to reproduce quotations."""
    return [piece for match in re.finditer(r'[^。！？\n]+[。！？\n]*|[。！？\n]+', text)
            for start in range(match.start(), match.end(), 500)
            if (piece := text[start:min(start + 500, match.end())]).strip()]


async def repair_evidence(data, characters, ask):
    data = deepcopy(data)
    pending = {}
    for event in data['events']:
        for view in event['viewpoints']:
            if view['knowledge'] != 'unknown' and (not view['memory'] or not view['quote'] or view['quote'] not in event['text']):
                pending[(event['id'], view['character_id'])] = (event, view)
    if not pending:
        return data, []
    correction = ''
    for _ in range(2):
        requests = [{'event_id': event['id'], 'character_id': view['character_id'],
                     'viewpoint': view, 'evidence': dict(enumerate(evidence_passages(event['text'])))}
                    for event, view in pending.values()]
        for request in requests:
            try:
                result = EvidenceRepairs.model_validate(await ask('story_evidence.md', {
                    'characters': [{'id': p['id'], 'name': p['name']} for p in characters],
                    'requests': [request], 'schema': EvidenceRepairs.model_json_schema(), 'correction': correction}))
                for patch in result.repairs:
                    key = (patch.event_id, patch.character_id)
                    if key not in pending or key != (request['event_id'], request['character_id']):
                        continue
                    event, view = pending[key]
                    passages = evidence_passages(event['text'])
                    if patch.evidence_id >= len(passages):
                        continue
                    view['quote'] = passages[patch.evidence_id]
                    view['memory'] = patch.memory
                    del pending[key]
            except ValueError as exc:
                correction = validation_message(exc)
        if not pending:
            break
        correction = '仅修复仍列出的视角。证据编号必须来自对应事件；不支持该角色知情时不要返回修复条目。' + correction
    unresolved = []
    for event, view in pending.values():
        unresolved.append({'event_id': event['id'], 'character_id': view['character_id'],
                           'viewpoint': deepcopy(view), 'reason': '未找到可验证的角色记忆依据，未加入角色记忆'})
        event['viewpoints'].remove(view)
    return data, unresolved
