"""PostgreSQL UTC 时间与可变维度 pgvector，保持向量的列表接口。"""
import math
from datetime import timezone

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Vector(TypeDecorator):
    impl = VECTOR
    cache_ok = True

    def __init__(self, dimensions=None):
        self.dimensions = dimensions
        super().__init__(dim=dimensions)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        values = [float(item) for item in value]
        if not values:
            return None
        if (self.dimensions is not None and len(values) != self.dimensions) or len(values) > 4096 or not all(math.isfinite(item) for item in values):
            raise ValueError("向量维度不匹配或包含非有限数值")
        return values

    def process_result_value(self, value, dialect):
        return [float(item) for item in value] if value is not None else None

    comparator_factory = VECTOR.comparator_factory
