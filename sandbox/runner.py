"""Изолированный runner: принимает Python-код, выполняет с жёсткими лимитами."""
import asyncio
import resource
import tempfile

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Gennady Sandbox Runner")

WALL_TIMEOUT_MAX = 60  # инвариант: httpx-таймаут клиента (70с) > WALL_TIMEOUT_MAX + 5
OUTPUT_LIMIT = 10_000
CODE_LIMIT = 100_000


class RunRequest(BaseModel):
    code: str = Field(max_length=CODE_LIMIT)
    timeout: float = 30


def _apply_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (5 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/run")
async def run(req: RunRequest) -> dict:
    with tempfile.TemporaryDirectory() as workdir:
        proc = await asyncio.create_subprocess_exec(
            "python", "-I", "-c", req.code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            preexec_fn=_apply_limits,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": workdir},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=min(req.timeout, WALL_TIMEOUT_MAX)
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"exit_code": -1, "stdout": "", "stderr": "Превышен таймаут выполнения"}

    return {
        "exit_code": proc.returncode,
        "stdout": stdout[-OUTPUT_LIMIT:].decode(errors="replace"),
        "stderr": stderr[-OUTPUT_LIMIT:].decode(errors="replace"),
    }
