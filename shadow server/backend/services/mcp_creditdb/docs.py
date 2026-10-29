from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
server=FastMCP('docs',host='127.0.0.1',port=8766)
@server.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False))
def read_policy() -> str:
    return 'Use the approved gateway for AI access. Fictional demo policy.'
if __name__=='__main__':
    server.run(transport='streamable-http')
