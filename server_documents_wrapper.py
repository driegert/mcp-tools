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
REMOTE_MCP_URL = "http://lilbuddy:8011/mcp"


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


async def _call_remote_tool(remote_pdf_path: Path, force_ocr: bool) -> str:
    async with streamable_http_client(REMOTE_MCP_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "convert_pdf_to_md",
                {"file_path": str(remote_pdf_path), "force_ocr": force_ocr},
                read_timeout_seconds=timedelta(minutes=10),
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


@mcp.tool()
async def convert_pdf_to_md(file_path: str, force_ocr: bool = True) -> str:
    """
    Convert a PDF into markdown with extracted equations in LaTeX format, images, and a JSON metadata file.

    This tool uploads the PDF to a remote server, runs conversion, downloads the
    results, and cleans up. It blocks until the full pipeline completes, which
    typically takes 2-10 minutes depending on document size.

    IMPORTANT: This is a long-running tool. When using Claude Code, invoke this
    tool call in the background so you can continue other work while it processes.

    force_ocr defaults to True and is recommended for papers containing equations.
    Set force_ocr to False for faster processing of text-only documents.
    """
    local_pdf = Path(file_path).absolute()

    if not local_pdf.exists():
        return f"File does not exist at {local_pdf}."

    if not local_pdf.suffix.lower() == ".pdf":
        return f"File does not appear to be a PDF.\nExtension detected was: {local_pdf.suffix.lower()}"

    remote_pdf = await _scp_upload(local_pdf)
    await _call_remote_tool(remote_pdf, force_ocr)
    local_output_dir = await _scp_download_results(local_pdf, remote_pdf)
    await _cleanup_remote(remote_pdf)

    pdf_stem = local_pdf.stem
    output_md = local_output_dir / f"{pdf_stem}.md"
    output_meta = local_output_dir / f"{pdf_stem}_meta.json"

    return f"""PDF document converted to markdown successfully.
  Text file: {output_md}
  Metadata (JSON): {output_meta}
  Images located in: {local_output_dir}"""


if __name__ == "__main__":
    mcp.run(transport="stdio")
