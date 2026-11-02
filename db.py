"""
.env 的 POSTGRES_* -> 連線字串。沒有進入點，只被 import：

    api.py      -> 開 pool
    pipeline.py -> 開一條用完就關的連線（rejudge.py、prune_closed.py 也走這條）

測試不走這裡，連線寫死在 tests/conftest.py。
"""

import os
import sys

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo


def conninfo() -> str:
    load_dotenv()
    try:
        return make_conninfo(
            host="127.0.0.1",
            port=os.environ["POSTGRES_PORT"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ["POSTGRES_DB"],
        )
    except KeyError as err:
        sys.exit(f".env 少了 {err.args[0]}，docker-compose.yml 要的那四個都得有。")
