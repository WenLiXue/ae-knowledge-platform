"""Synchronous Worker bridge to cancellable async HTTP, with wall-clock budgets."""
import asyncio
import time

import httpx


def post(url, *, payload, headers, timeout):
    async def request():
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(url, json=payload, headers=headers)

    with asyncio.Runner() as runner:
        return runner.run(asyncio.wait_for(request(), timeout))


def stream_lines(url, *, payload, headers, timeout):
    async def lines():
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                yield response.status_code
                async for line in response.aiter_lines():
                    yield line

    deadline = time.monotonic() + timeout
    iterator = lines()
    with asyncio.Runner() as runner:
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Model deadline exceeded")
                try:
                    yield runner.run(asyncio.wait_for(anext(iterator), remaining))
                except StopAsyncIteration:
                    return
        finally:
            runner.run(iterator.aclose())
