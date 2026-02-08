import mcp
import httpx

max_filesize = 10 * 1024 * 1024  # 10 MB
ollama_endpoint = "http://lilripper:11434/v1"
default_summarizer = "qwen3-4b-instruct"
default_detail = "standard"
default_focus = "all"

detail_options = ["brief", "standard", "detailed"]
excluded_files = ["c", "cpp", "R", "f", "f90", "py", "xls", "xlsx", "csv", "tsv", "RData", "rds"]

mcp = MCPServer("Tool Server")

@mcp.tool()
def summarize_document(file: str, focus: str = "all", detail: str = "standard", model: str = "qwen3-4b-instruct"):
  # check if file is one of our excluded file types
  
  # check if file exists

  # check file size

  print("hullooo")

