import asyncio
from datetime import timedelta
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

mcp = FastMCP(name="Document Processing (Wrapper)")

REMOTE_HOST = "lilbuddy"
REMOTE_USER = "dave"
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"
REMOTE_MCP_DIR = Path("/home/dave/mcp-documents")
REMOTE_MCP_URL = "http://lilbuddy:8020/mcp"

# Track active jobs: job_id -> {status, local_pdf, remote_pdf, error, result}
_jobs: dict[str, dict] = {}
_job_counter = 0


async def _run_cmd(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{stderr.decode()}")
    return stdout.decode()


async def _scp_upload(local_path: Path) -> Path:
    remote_dest = f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_MCP_DIR}/{local_path.name}"
    await _run_cmd(
        "ssh", "-i", str(SSH_KEY), f"{REMOTE_USER}@{REMOTE_HOST}",
        f"mkdir -p {REMOTE_MCP_DIR}"
    )
    await _run_cmd(
        "scp", "-i", str(SSH_KEY), str(local_path), remote_dest
    )
    return REMOTE_MCP_DIR / local_path.name


async def _call_remote_tool(remote_pdf_path: Path, force_ocr: bool, mode: str) -> str:
    async with streamable_http_client(REMOTE_MCP_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "convert_pdf_to_md",
                {"file_path": str(remote_pdf_path), "force_ocr": force_ocr, "mode": mode},
                read_timeout_seconds=timedelta(minutes=45),
            )
            if result.isError:
                error_text = " ".join(
                    c.text for c in result.content if hasattr(c, "text")
                )
                raise RuntimeError(f"Remote tool error: {error_text}")
            return " ".join(c.text for c in result.content if hasattr(c, "text"))


async def _scp_download_results(local_pdf_path: Path, remote_pdf_path: Path) -> Path:
    pdf_stem = remote_pdf_path.stem
    remote_output_dir = f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_MCP_DIR}/{pdf_stem}"
    local_output_dir = local_pdf_path.with_suffix("")
    await _run_cmd(
        "scp", "-i", str(SSH_KEY), "-r", remote_output_dir, str(local_output_dir)
    )
    return local_output_dir


async def _cleanup_remote(remote_pdf_path: Path):
    pdf_stem = remote_pdf_path.stem
    try:
        await _run_cmd(
            "ssh", "-i", str(SSH_KEY), f"{REMOTE_USER}@{REMOTE_HOST}",
            f"rm -rf {REMOTE_MCP_DIR}/{remote_pdf_path.name} {REMOTE_MCP_DIR}/{pdf_stem}"
        )
    except RuntimeError:
        pass


async def _process_job(job_id: str, local_pdf: Path, force_ocr: bool, mode: str):
    """Background task that handles upload, conversion, download, and cleanup."""
    job = _jobs[job_id]
    try:
        remote_pdf = await _scp_upload(local_pdf)
        job["remote_pdf"] = str(remote_pdf)
        job["status"] = "converting"

        await _call_remote_tool(remote_pdf, force_ocr, mode)
        job["status"] = "downloading"

        local_output_dir = await _scp_download_results(local_pdf, remote_pdf)
        await _cleanup_remote(remote_pdf)

        pdf_stem = local_pdf.stem
        output_md = local_output_dir / f"{pdf_stem}.md"
        output_meta = local_output_dir / f"{pdf_stem}_meta.json"

        job["status"] = "completed"
        job["result"] = f"""PDF document converted to markdown successfully.
  Text file: {output_md}
  Metadata (JSON): {output_meta}
  Images located in: {local_output_dir}"""

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


@mcp.tool()
async def convert_pdf_to_md(file_path: str, force_ocr: bool = True, mode: str = "fast") -> str:
    """
    Starts converting a PDF into markdown, with images and a JSON metadata file.

    This tool uploads the PDF to a remote server and begins conversion.
    It returns a job ID immediately. Use get_conversion_result with the job ID to check
    progress and retrieve the converted files once complete.

    mode controls processing depth:
      - "fast" (default): Extracts text, document structure, equation LaTeX, and tables.
        Skips all LLM-based processors.
      - "full": Full processing including LLM-based refinement
        and image extraction. Use when higher quality output is needed.

    force_ocr defaults to True and is recommended for papers containing equations.
    Set force_ocr to False for faster processing of text-only documents.
    Ignored when mode="fast" (always False).
    """
    global _job_counter

    if mode not in ("fast", "full"):
        return f"Invalid mode: {mode}. Must be 'fast' or 'full'."

    local_pdf = Path(file_path).absolute()

    if not local_pdf.exists():
        return f"File does not exist at {local_pdf}."

    if not local_pdf.suffix.lower() == ".pdf":
        return f"File does not appear to be a PDF.\nExtension detected was: {local_pdf.suffix.lower()}"

    _job_counter += 1
    job_id = str(_job_counter)
    _jobs[job_id] = {
        "status": "uploading",
        "local_pdf": str(local_pdf),
        "remote_pdf": None,
        "error": None,
        "result": None,
    }

    asyncio.create_task(_process_job(job_id, local_pdf, force_ocr, mode))

    return f"Conversion started. Job ID: {job_id}\nUse get_conversion_result with job_id=\"{job_id}\" to check progress."


@mcp.tool()
async def get_conversion_result(job_id: str) -> str:
    """
    Check the status of a PDF conversion job and retrieve results when complete.

    This tool waits up to 45 seconds for the job to finish before returning.
    If the job is still in progress after 45 seconds, call this tool again.

    When the job is complete, returns the file paths for the converted markdown,
    metadata, and images.
    """
    if job_id not in _jobs:
        available = ", ".join(_jobs.keys()) if _jobs else "none"
        return f"Unknown job ID: {job_id}. Active jobs: {available}"

    # Poll internally for up to 45 seconds to minimize tool call churn
    for _ in range(9):
        job = _jobs[job_id]
        status = job["status"]

        if status == "completed":
            result = job["result"]
            del _jobs[job_id]
            return result

        if status == "failed":
            error = job["error"]
            del _jobs[job_id]
            return f"Conversion failed: {error}"

        await asyncio.sleep(5)

    return f"Job {job_id} is still in progress. Current stage: {_jobs[job_id]['status']}. Call this tool again to continue waiting."


if __name__ == "__main__":
    mcp.run(transport="stdio")
