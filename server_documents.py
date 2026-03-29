import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from marker.config.parser import ConfigParser

mcp = FastMCP(name="Document Processing", host="127.0.0.1", port=8200)

_model_artifact_dict = None

def get_model_dict():
  global _model_artifact_dict
  if _model_artifact_dict is None:
    _model_artifact_dict = create_model_dict()
  return _model_artifact_dict


# Lightweight processors for fast mode: text extraction, structural analysis,
# equation LaTeX extraction, and table recognition. Skips all LLM* processors.
FAST_PROCESSORS = [
  "marker.processors.order.OrderProcessor",
  "marker.processors.block_relabel.BlockRelabelProcessor",
  "marker.processors.line_merge.LineMergeProcessor",
  "marker.processors.sectionheader.SectionHeaderProcessor",
  "marker.processors.equation.EquationProcessor",
  "marker.processors.table.TableProcessor",
  "marker.processors.list.ListProcessor",
  "marker.processors.code.CodeProcessor",
  "marker.processors.blockquote.BlockquoteProcessor",
  "marker.processors.footnote.FootnoteProcessor",
  "marker.processors.reference.ReferenceProcessor",
  "marker.processors.page_header.PageHeaderProcessor",
  "marker.processors.line_numbers.LineNumbersProcessor",
  "marker.processors.ignoretext.IgnoreTextProcessor",
  "marker.processors.document_toc.DocumentTOCProcessor",
  "marker.processors.blank_page.BlankPageProcessor",
  "marker.processors.text.TextProcessor",
]


@mcp.tool()
def convert_pdf_to_md(file_path: str, force_ocr: bool = True, mode: str = "fast"):
  """
  Converts a PDF into markdown, with images and a JSON metadata file.

  Returns the filepath for the markdown file, metadata file, and folder path for location of images.

  Use this tool every time the contents of a PDF are required.
  After conversion, read the .md file for the article content.
  Images extracted from the PDF will be saved in the same directory and referenced in the markdown.
  Use the describe_image tool to obtain context about any extracted images.

  mode controls processing depth:
    - "fast" (default): Extracts text, document structure, equation LaTeX, and tables.
      Skips all LLM-based processors.
      Automatically sets force_ocr=False and disables image extraction.
    - "full": Full processing including LLM-based refinement
      and image extraction. Use when higher quality output is needed.

  force_ocr defaults to True and is recommended for papers containing equations.
  Set force_ocr to False for faster processing of text-only documents.
  Ignored when mode="fast" (always False).
  """

  if mode not in ("fast", "full"):
    return f"Invalid mode: {mode}. Must be 'fast' or 'full'."

  pdf_path = Path(file_path).absolute()

  if not pdf_path.exists():
    return f"File does not exist at {pdf_path}."

  if not pdf_path.suffix.lower() == ".pdf":
    return f"File does not appear to be a PDF.\nExtension detected was: {pdf_path.suffix.lower()}"

  pdf_name = pdf_path.stem

  # create the output directory and images sub directory
  output_dir = pdf_path.with_suffix('')
  output_dir.mkdir(exist_ok=True)

  # Configure the marker converter
  if mode == "fast":
    marker_config = {
      "force_ocr": False,
      "output_format": "markdown",
      "disable_image_extraction": True,
    }
    marker_config_parser = ConfigParser(marker_config)
    processor_list = FAST_PROCESSORS
  else:
    marker_config = {
      "force_ocr": force_ocr,
      "output_format": "markdown",
    }
    marker_config_parser = ConfigParser(marker_config)
    processor_list = marker_config_parser.get_processors()

  converter = PdfConverter(
    artifact_dict=get_model_dict(),
    config=marker_config_parser.generate_config_dict(),
    processor_list=processor_list,
    renderer=marker_config_parser.get_renderer()
  )

  rendered = converter(str(pdf_path))

  # convert the PDF to text, metadata and images
  text, metadata, images = text_from_rendered(rendered)

  # write converted content to the output directory
  output_md = output_dir.joinpath(pdf_name).with_suffix('.md')
  output_meta = output_dir.joinpath(pdf_name + '_meta.json')

  output_md.write_text(text)
  output_meta.write_text(json.dumps(metadata, indent=2))

  for image_name, image_obj in images.items():
    image_obj.save(output_dir / image_name)

  mode_note = " (fast mode — no LLM refinement or images)" if mode == "fast" else ""
  return_info = f"""PDF document converted to markdown successfully{mode_note}.
  Text file: {output_md}
  Metadata (JSON): {output_meta}
  Images located in: {output_dir}"""

  return return_info


if __name__ == "__main__":
  mcp.run(transport="streamable-http")
