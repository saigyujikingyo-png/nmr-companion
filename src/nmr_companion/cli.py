import argparse
import os
import asyncio
from pathlib import Path
from .service import Service
from .errors import NmrError


def main():
    parser = argparse.ArgumentParser(description="NMR Companion local developer alpha")
    parser.add_argument(
        "--project",
        default=os.environ.get(
            "NMR_COMPANION_PROJECT", str(Path.home() / "NMR Companion" / "workspace.nmrproj")
        ),
        help="Local .nmrproj shared by workbench and MCP; defaults to NMR_COMPANION_PROJECT or the user workspace",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    create = sub.add_parser("create", help="Create a new empty project without overwriting")
    create.add_argument("--name", default="NMR project")
    web = sub.add_parser("web", help="Run the workbench explicitly on loopback")
    web.add_argument("--port", type=int, default=0)
    sub.add_parser("mcp", help="Run an MCP stdio frontend until EOF")
    export = sub.add_parser("export", help="Save an immutable revision bundle")
    export.add_argument("--revision", type=int, required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args()
    service = Service(args.project)
    try:
        if args.mode == "create":
            print(service.create(args.name).model_dump_json())
        elif args.mode == "web":
            from .web import run

            run(service, args.port)
        elif args.mode == "mcp":
            from .mcp_server import run

            asyncio.run(run(service))
        else:
            artifact = service.export(args.revision)
            _, data = service.store.artifact(artifact.id)
            with Path(args.output).open("xb") as handle:
                handle.write(data)
            print(artifact.model_dump_json())
    except NmrError as exc:
        parser.exit(2, f"{exc.code}: {exc.message}\n")
