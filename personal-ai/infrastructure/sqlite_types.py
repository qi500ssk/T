"""Dialect-aware UTC/vector types; SQLite remains available for rollback/tests."""
import json
import math
from datetime import timezone

from sqlalchemy import DateTime, Float, JSON, String, func, literal
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class VectorDistance(FunctionElement):
    type = Float()
    inherit_cache = True


@compiles(VectorDistance, "sqlite")
def sqlite_distance(element, compiler, **kw):
    left, right = list(element.clauses)
    return "vector_cosine_distance(" + compiler.process(left, **kw) + ", " + compiler.process(right, **kw) + ")"


@compiles(VectorDistance, "postgresql")
def postgres_distance(element, compiler, **kw):
    left, right = list(element.clauses)
    return "(" + compiler.process(left, **kw) + " <=> " + compiler.process(right, **kw) + ")"


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Vector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions=None):
        super().__init__(none_as_null=True)
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import VECTOR
            return dialect.type_descriptor(VECTOR(self.dimensions))
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_result_value(self, value, dialect):
        return [float(v) for v in value] if value is not None else None

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        values = [float(item) for item in value]
        # Keyword-only documents have no embedding; pgvector rejects [].
        if not values and dialect.name == "postgresql":
            return None
        if (self.dimensions is not None and len(values) != self.dimensions) or len(values) > 4096 or not all(math.isfinite(item) for item in values):
            raise ValueError("向量维度不匹配或包含非有限数值")
        return values

    class comparator_factory(JSON.Comparator):
        def cosine_distance(self, vector):
            return VectorDistance(self.expr, literal([float(v) for v in vector], type_=Vector()))


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
