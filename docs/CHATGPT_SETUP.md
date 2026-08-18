# ChatGPT / MCP Setup

## Architecture

Deploy this bridge somewhere that can maintain an outbound SSH connection to Hostinger.

ChatGPT's custom MCP path is remote HTTP, not local stdio.

```text
ChatGPT
  ↓ HTTPS MCP
files-mcp.avatararts.org/mcp
  ↓ private credential boundary
Hostinger SFTP :65002
```

For a private deployment, use OpenAI's supported Secure MCP Tunnel where available
instead of exposing the MCP server publicly.

## Tool archetype

This is intentionally a **tool-only app**. A rich widget is not required to manage
remote files.

Large binary uploads use a separate browser drop page because binary file transfer should
not travel through tool-call JSON.

## Recommended ChatGPT prompt

```text
Use Hostinger File Bridge to upload my CreativeOS release.
First check remote status, then create a browser upload ticket for:
releases/AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip
Do not overwrite an existing file without asking me.
After upload, list the releases directory and verify the final size/hash.
```

## Write-action safety

The MCP tools are annotated so:
- list/status are read-only
- upload/mkdir/extract are mutating
- delete is destructive

ChatGPT may require confirmation before mutating operations depending on the current
product/workspace permissions.

## Current availability

Product capabilities evolve. Verify current ChatGPT custom-app / MCP workspace settings before assuming write tools are enabled.
