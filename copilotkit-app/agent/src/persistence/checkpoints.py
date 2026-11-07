"""PostgreSQL checkpoint pool owned by the current asyncio loop/process."""
import argparse
import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.infrastructure.config import Infrastructure
from src.infrastructure.loops import loop_factory


@asynccontextmanager
async def checkpoint_saver(*, setup=False):
    params = conninfo_to_dict(Infrastructure.read().checkpoint_url)
    params["options"] = "-c search_path=agent,public -c statement_timeout=15000"
    params["connect_timeout"] = "5"
    async with AsyncConnectionPool(make_conninfo(**params), min_size=1, max_size=5, timeout=10,
                                   kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=False) as pool:
        await pool.wait(timeout=10)
        saver = AsyncPostgresSaver(pool, serde=JsonPlusSerializer(allowed_msgpack_modules=[("ag_ui.core.types", "Context")]))
        if setup:
            await saver.setup()
        else:
            async with pool.connection() as connection:
                row = await (await connection.execute("SELECT to_regclass('agent.checkpoints') AS ready")).fetchone()
                if row["ready"] is None:
                    raise RuntimeError("Checkpoint schema missing; run the checkpoint setup/migration command before starting API")
        yield saver


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    async with checkpoint_saver(setup=args.setup):
        print("PostgreSQL checkpoint schema ready")


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(main())
