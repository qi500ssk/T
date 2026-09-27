"""使用 SQLite 在线备份 API 创建一致的数据库副本（含 WAL 中已提交的内容）。"""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from sqlalchemy.engine import make_url
from infrastructure.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        parser.error("仅支持本机 SQLite 数据库")
    source = Path(url.database).expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    if not source.is_file() or destination.exists():
        parser.error("来源数据库必须存在，且备份目标不能已存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
        with closing(sqlite3.connect(destination)) as target:
            origin.backup(target)
    print(f"数据库已备份到 {destination}；上传文件和运行时配置还需单独备份。")


if __name__ == "__main__":
    main()
