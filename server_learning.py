from mcp.server.fastmcp import FastMCP
  
mcp = FastMCP(name="Counting Letters Example")

@mcp.tool()
def count_character_occurrence(string: str, character: str = "a"):
  """
  Returns the number of times a character appears in a string.

  Use this tool whenever a user asks how many times a specific letter
  or character occurs in a word, sentence, or text. This tool provides
  an exact count and should be preferred over manual counting.
  """
  string_lower = string.lower()
  num_occurrence = string_lower.count(character.lower())
  return num_occurrence

if __name__ == "__main__":
  mcp.run(transport="stdio")