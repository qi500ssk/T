"""把旧 PostgreSQL 的只读快照导入全新 SQLite 文件；绝不覆盖现有文件。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", type=Path, required=True, help="包含旧 DATABASE_URL 的本地 .env 文件")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    if destination.exists():
        parser.error("目标文件已存在；请指定一个新文件，导入不会覆盖数据")
    from dotenv import dotenv_values
    source_url = dotenv_values(args.source_env).get("DATABASE_URL", "")
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    if make_url(source_url).get_backend_name() != "postgresql":
        parser.error("来源必须是 PostgreSQL")
    # 在导入应用模块之前设置目标，避免读取旧 .env 时连接到错误数据库。
    os.environ["DATABASE_URL"] = "sqlite:///" + destination.as_posix()
    from infrastructure.database import Base, engine, init_db
    from infrastructure.sqlite_types import UTCDateTime
    source = create_engine(source_url, connect_args={"connect_timeout": 5})
    counts = {}
    try:
        with source.connect().execution_options(isolation_level="REPEATABLE READ") as origin:
            origin.execute(text("SET TRANSACTION READ ONLY"))
            tables = set(inspect(origin).get_table_names())
            if not {"conversations", "messages", "admin_accounts"}.issubset(tables):
                raise RuntimeError("来源不是受支持的 Personal AI 数据库，未导入")
            if "agent_runs" in tables and origin.execute(text("SELECT count(*) FROM agent_runs WHERE status = 'running'")).scalar():
                raise RuntimeError("旧数据库仍有运行中的任务，请先停止应用后再迁移")
            init_db()
            with engine.connect() as target:
                target.exec_driver_sql("BEGIN IMMEDIATE")
                # 自引用记忆修订可能不按父子顺序排列；事务结束时统一校验。
                target.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
                for table in Base.metadata.sorted_tables:
                    if table.name not in tables or table.name == "login_sessions":
                        continue
                    quoted = origin.dialect.identifier_preparer.quote(table.name)
                    result = origin.execute(text(f"SELECT to_jsonb(row) FROM {quoted} AS row"))
                    count = 0
                    for batch in result.partitions(250):
                        rows = []
                        for source_row in batch:
                            data = source_row[0]
                            row = {}
                            for column in table.columns:
                                if column.name not in data:
                                    continue
                                value = data[column.name]
                                if value is not None and isinstance(column.type, UTCDateTime):
                                    value = datetime.fromisoformat(value)
                                elif column.name == "embedding" and isinstance(value, str):
                                    value = json.loads(value)
                                row[column.name] = value
                            rows.append(row)
                        if rows:
                            target.execute(table.insert(), rows)
                        count += len(rows)
                    actual = target.execute(text(f'SELECT count(*) FROM "{table.name}"')).scalar()
                    if actual != count:
                        raise RuntimeError(f"导入行数校验失败：{table.name}")
                    counts[table.name] = count
                if target.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("来源存在不完整的关联数据，导入已回滚")
                target.commit()
                assert target.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        print(json.dumps({"database": str(destination), "rows": counts, "login_sessions": "需要重新登录"}, ensure_ascii=False))
    finally:
        source.dispose()
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # 驱动异常可能包含整条 INSERT 参数（消息/密码摘要），不回显。
        print(f"导入失败（{type(error).__name__}）。源数据库未修改；目标可能为空，请检查配置与 schema 后选择新目标重试。", file=sys.stderr)
        sys.exit(1)
