"""An asyncio loop compatible with psycopg's socket readiness integration."""
import asyncio
import sys


def loop_factory():
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
