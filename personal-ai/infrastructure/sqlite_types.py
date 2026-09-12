"""SQLite 向量 JSON 存储与 UTC 时间；不需要安装数据库扩展。"""
import json
import math
from datetime import timezone

from sqlalchemy import DateTime, Float, JSON, String, func, literal
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Vector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions=None):
        super().__init__(none_as_null=True)
        self.dimensions = dimensions

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        values = [float(item) for item in value]
        if (self.dimensions is not None and len(values) != self.dimensions) or len(values) > 4096 or not all(math.isfinite(item) for item in values):
            raise ValueError("向量维度不匹配或包含非有限数值")
        return values

    class comparator_factory(JSON.Comparator):
        def cosine_distance(self, vector):
            return func.vector_cosine_distance(self.expr, literal(json.dumps([float(v) for v in vector]), String), type_=Float)


def cosine_distance(left, right):
    if left is None or right is None:
        return None
    a, b = json.loads(left), json.loads(right)
    if len(a) != len(b):
        return 2.0
    denominator = math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))
    if not denominator:
        return 1.0
    similarity = sum(x*y for x, y in zip(a, b)) / denominator
    return 1.0 - max(-1.0, min(1.0, similarity))
