from pathlib import Path
from mcp.server.fastmcp import FastMCP
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from marker.config.parser import ConfigParser
  
mcp = FastMCP(name="Document Processing")

model_artifact_dict = create_model_dict()


@mcp.tool()
def convert_pdf_to_md(file_path: str, force_ocr: bool=True):
  """
  Converts a PDF into markdown with extracted equations in LaTeX format, images, and a JSON metadata file. 

  Returns the filepath for the markdown file, metadata file, and folder path for location of images.

  Use this tool every time the contents of a PDF are required.
  After conversion, read the .md file for the article content. 
  Images extracted from the PDF will be saved in the same directory and referenced in the markdown.
  Use the describe_image tool to obtain context about any extracted images.

  force_ocr defaults to True and is recommended for papers containing equations.
  Set force_ocr to False for faster processing of text-only documents.
  """

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
  marker_config = {
    "force_ocr": force_ocr,
    "output_format": "markdown"
  }
  marker_config_parser = ConfigParser(marker_config)

  converter = PdfConverter(
    artifact_dict=model_artifact_dict,
    config=marker_config_parser.generate_config_dict(),
    processor_list=marker_config_parser.get_processors(),
    renderer=marker_config_parser.get_renderer()
  )

  rendered = converter(str(pdf_path))

  # convert the PDF to text, metadata and images
  text, metadata, images = text_from_rendered(rendered)

  ## DEBUGGING: print out the metadata and image info
  print(f"Metadata extracted from PDF: {type(metadata)}")

  # write converted content to the output directory
  output_md = output_dir.joinpath(pdf_name).with_suffix('.md')
  output_meta = output_dir.joinpath(pdf_name + '_meta.json')

  output_md.write_text(text)
  output_meta.write_text(metadata)

  for image_name, image_obj in images.items():
    image_obj.save(output_dir / image_name)


  return_info = f"""PDF document converted to markdown successfully.
  Text file: {output_md}
  Metadata (JSON): {output_meta}
  Images located in: {output_dir}"""

  return return_info



if __name__ == "__main__":
  # mcp.run(transport="stdio")
  result = convert_pdf_to_md("/home/dave/school_lab/papers/reviews/eco-2025/TJES-2025-0014_Proof_hi.pdf", force_ocr=True)
  # result = convert_pdf_to_md("/home/dave/school_lab/conferences/ssp2018/latex/paper/DjtDlrSSP2018.pdf", force_ocr=True)
  print(result)