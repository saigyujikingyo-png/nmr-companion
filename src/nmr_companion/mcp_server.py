import json
from urllib.parse import urlparse
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from . import __version__
from .api import SPECS, dispatch
from .service import Service


def make_server(service: Service):
    server = Server("nmr-companion", version=__version__)

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=input_model.model_json_schema(),
                outputSchema=output_model.model_json_schema(),
                annotations=types.ToolAnnotations(
                    readOnlyHint=name in {"nmr_project", "nmr_read", "nmr_request", "nmr_help"}
                    and name != "nmr_project",
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
            for name, (input_model, output_model, description) in SPECS.items()
        ]

    # Disable SDK input error shortcut: all failure branches must use our output contract.
    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        result = dispatch(service, name, arguments)
        content = [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        if name == "nmr_export" and result["ok"]:
            a = result["data"]
            content.append(
                types.ResourceLink(
                    type="resource_link",
                    uri=a["uri"],
                    name=a["name"],
                    mimeType=a["media_type"],
                    size=a["size"],
                )
            )
        return types.CallToolResult(
            content=content, structuredContent=result, isError=not result["ok"]
        )

    @server.list_resource_templates()
    async def list_templates():
        return [
            types.ResourceTemplate(
                uriTemplate="nmr://artifacts/{artifact_id}",
                name="Revision export",
                mimeType="application/zip",
            )
        ]

    @server.read_resource()
    async def read_resource(uri):
        parsed = urlparse(str(uri))
        if parsed.scheme != "nmr" or parsed.netloc != "artifacts":
            raise ValueError("Unknown resource.")
        metadata, data = service.store.artifact(parsed.path.lstrip("/"))
        return [ReadResourceContents(content=data, mime_type=metadata.media_type)]

    return server


async def run(service):
    server = make_server(service)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
