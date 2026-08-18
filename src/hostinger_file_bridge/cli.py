from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .sftp import SFTPBridge


def main():
    parser = argparse.ArgumentParser(
        prog="hostinger-upload",
        description="Securely upload/list/extract files beneath a configured Hostinger SFTP root.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    p_list = sub.add_parser("list")
    p_list.add_argument("relative_dir", nargs="?", default="")

    p_up = sub.add_parser("upload")
    p_up.add_argument("local_path")
    p_up.add_argument("relative_path")
    p_up.add_argument("--overwrite", action="store_true")

    p_mkdir = sub.add_parser("mkdir")
    p_mkdir.add_argument("relative_dir")

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("relative_zip")
    p_extract.add_argument("relative_destination")
    p_extract.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()
    bridge = SFTPBridge(Settings())

    if args.cmd == "status":
        result = bridge.status()
    elif args.cmd == "list":
        result = bridge.list(args.relative_dir)
    elif args.cmd == "upload":
        result = bridge.upload_file(
            Path(args.local_path), args.relative_path, overwrite=args.overwrite
        )
    elif args.cmd == "mkdir":
        result = bridge.mkdir(args.relative_dir)
    elif args.cmd == "extract":
        result = bridge.extract_zip(
            args.relative_zip,
            args.relative_destination,
            overwrite=args.overwrite,
        )
    else:
        raise SystemExit(2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
