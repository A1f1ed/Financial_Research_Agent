"""Explicit deployment migration, completed before API and workers start."""
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from src.infrastructure.loops import loop_factory
from src.persistence.checkpoints import checkpoint_saver


async def initialize_checkpoints():
    async with checkpoint_saver(setup=True):
        pass


def main():
    root = Path(__file__).resolve().parents[2]
    command.upgrade(Config(str(root / "alembic.ini")), "head")
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(initialize_checkpoints())
    print("PostgreSQL business and checkpoint schemas ready")


if __name__ == "__main__":
    main()
