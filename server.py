#!/usr/bin/env python3
"""
Qdrant Sync MCP Server

A dedicated MCP server for administering the Qdrant sync system between
local workstation (localhost:6335) and VPS (74.50.49.35:6333).

Tools:
- qdrant_sync_status: Check connectivity and collection counts on both instances
- qdrant_sync_all: Full sync of all collections (local → VPS)
- qdrant_sync_collection: Sync a single collection
- qdrant_sync_dry_run: Preview what would be synced
- qdrant_sync_logs: View recent sync logs
- qdrant_compare_collections: Compare collection stats between local and VPS

Author: Vanya + Claude
Created: November 23, 2025
"""

import asyncio
import json
import os
import subprocess
import glob
from datetime import datetime
from typing import Optional
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# =============================================================================
# Configuration
# =============================================================================

CONFIG_FILE = os.environ.get("QDRANT_SYNC_CONFIG", "/home/vanya/.config/qdrant-sync/config.env")
SYNC_SCRIPT = os.environ.get("QDRANT_SYNC_SCRIPT", "/home/vanya/scripts/sync-qdrant-to-vps.sh")
SYNC_SCRIPT_REVERSE = os.environ.get("QDRANT_SYNC_SCRIPT_REVERSE", "/home/vanya/scripts/sync-qdrant-from-vps.sh")
LOG_DIR = os.environ.get("QDRANT_SYNC_LOG_DIR", "/home/vanya/logs")

# Load config from env file
def load_config():
    """Load configuration from config.env file."""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove quotes and inline comments from value
                    value = value.strip().strip('"').strip("'")
                    # Remove inline comments (anything after # with preceding whitespace)
                    if '#' in value:
                        value = value.split('#')[0].strip().strip('"').strip("'")
                    config[key] = value
    return config

CONFIG = load_config()

# Default values if config not loaded
SOURCE_REST_URL = CONFIG.get("SOURCE_REST_URL", "http://localhost:6335")
TARGET_REST_URL = CONFIG.get("TARGET_REST_URL", "http://74.50.49.35:6333")
TARGET_API_KEY = CONFIG.get("TARGET_API_KEY", "")

# =============================================================================
# Helper Functions
# =============================================================================

async def check_qdrant_connectivity(url: str, api_key: Optional[str] = None) -> dict:
    """Check if a Qdrant instance is reachable and get basic info."""
    headers = {}
    if api_key:
        headers["api-key"] = api_key
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/collections", headers=headers)
            if response.status_code == 200:
                data = response.json()
                collections = data.get("result", {}).get("collections", [])
                return {
                    "status": "connected",
                    "url": url,
                    "collection_count": len(collections),
                    "collections": [c.get("name") for c in collections]
                }
            else:
                return {
                    "status": "error",
                    "url": url,
                    "error": f"HTTP {response.status_code}"
                }
    except Exception as e:
        return {
            "status": "unreachable",
            "url": url,
            "error": str(e)
        }


async def get_collection_info(url: str, name: str, api_key: Optional[str] = None) -> dict:
    """Get detailed info about a specific collection."""
    headers = {}
    if api_key:
        headers["api-key"] = api_key
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/collections/{name}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                result = data.get("result", {})
                return {
                    "name": name,
                    "status": result.get("status", "unknown"),
                    "points_count": result.get("points_count", 0),
                    "vectors_count": result.get("vectors_count", 0),
                    "indexed_vectors_count": result.get("indexed_vectors_count", 0)
                }
            else:
                return {"name": name, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"name": name, "error": str(e)}


async def get_all_collections_with_counts(url: str, api_key: Optional[str] = None) -> list:
    """Get all collections with their point counts."""
    conn = await check_qdrant_connectivity(url, api_key)
    if conn.get("status") != "connected":
        return []
    
    collections = []
    for name in conn.get("collections", []):
        info = await get_collection_info(url, name, api_key)
        collections.append(info)
    
    return sorted(collections, key=lambda x: x.get("name", ""))


def run_sync_script(args: list = None, script_path: str = None) -> dict:
    """Run the sync script with given arguments."""
    script = script_path or SYNC_SCRIPT
    cmd = [script]
    if args:
        cmd.extend(args)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout for full sync
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Sync operation timed out after 30 minutes"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_recent_logs(count: int = 5) -> list:
    """Get the most recent sync log files."""
    pattern = os.path.join(LOG_DIR, "qdrant-sync-*.log")
    log_files = sorted(glob.glob(pattern), reverse=True)[:count]
    
    logs = []
    for log_file in log_files:
        try:
            with open(log_file, 'r') as f:
                content = f.read()
            
            # Parse log file name for timestamp
            basename = os.path.basename(log_file)
            timestamp = basename.replace("qdrant-sync-", "").replace(".log", "")
            
            logs.append({
                "file": log_file,
                "timestamp": timestamp,
                "size_bytes": os.path.getsize(log_file),
                "content": content
            })
        except Exception as e:
            logs.append({
                "file": log_file,
                "error": str(e)
            })
    
    return logs



# =============================================================================
# MCP Server Setup
# =============================================================================

server = Server("qdrant-sync")

# Define tools
TOOLS = [
    Tool(
        name="qdrant_sync_status",
        description="""Check connectivity and status of both Qdrant instances (local and VPS).
Returns connection status, collection counts, and list of collections for each instance.
Use this to verify both instances are reachable before syncing.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    Tool(
        name="qdrant_sync_all",
        description="""Execute a full sync of ALL collections from local Qdrant to VPS.
This runs the sync-qdrant-to-vps.sh script without arguments.
WARNING: This may take 5-10 minutes depending on the number of collections and data volume.
Returns the script output including success/failure status for each collection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Set to true to confirm you want to sync all collections"
                }
            },
            "required": ["confirm"]
        }
    ),
    Tool(
        name="qdrant_sync_collection",
        description="""Sync a single specific collection from local Qdrant to VPS.
Use this for targeted syncs after updating specific collections.
Faster than full sync - typically completes in 2-10 seconds per collection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to sync"
                }
            },
            "required": ["collection_name"]
        }
    ),
    Tool(
        name="qdrant_sync_dry_run",
        description="""Preview what would be synced without actually transferring data.
Lists all collections with their point counts.
Use this to verify the state before running a full sync.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    Tool(
        name="qdrant_sync_logs",
        description="""View recent sync operation logs.
Returns the content of recent log files from /home/vanya/logs/qdrant-sync-*.log
Useful for debugging failed syncs or reviewing sync history.""",
        inputSchema={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of recent log files to retrieve (default: 3, max: 10)",
                    "default": 3
                },
                "latest_only": {
                    "type": "boolean",
                    "description": "If true, only return the most recent log file",
                    "default": False
                }
            },
            "required": []
        }
    ),
    Tool(
        name="qdrant_compare_collections",
        description="""Compare collections between local and VPS instances.
Shows which collections exist on each instance, point counts, and identifies discrepancies.
Useful for verifying sync completeness or identifying missing collections.""",
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Optional: compare a specific collection only. If omitted, compares all collections."
                }
            },
            "required": []
        }
    ),
    Tool(
        name="qdrant_sync_from_vps_all",
        description="""Execute a full sync of ALL collections from VPS to local Qdrant.
This is the REVERSE direction: VPS → Local.
WARNING: This may take 5-10 minutes depending on the number of collections and data volume.
Returns the script output including success/failure status for each collection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Set to true to confirm you want to sync all collections from VPS to local"
                }
            },
            "required": ["confirm"]
        }
    ),
    Tool(
        name="qdrant_sync_from_vps_collection",
        description="""Sync a single specific collection from VPS to local Qdrant.
This is the REVERSE direction: VPS → Local.
Use this to pull updates from VPS after remote changes.
Faster than full sync - typically completes in 2-10 seconds per collection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to sync from VPS to local"
                }
            },
            "required": ["collection_name"]
        }
    ),
    Tool(
        name="qdrant_sync_from_vps_dry_run",
        description="""Preview what would be synced from VPS to local without actually transferring data.
Lists all VPS collections with their point counts.
Use this to verify VPS state before pulling to local.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
]


@server.list_tools()
async def list_tools():
    """Return the list of available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    
    if name == "qdrant_sync_status":
        # Check both instances
        local_status = await check_qdrant_connectivity(SOURCE_REST_URL)
        vps_status = await check_qdrant_connectivity(TARGET_REST_URL, TARGET_API_KEY)
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "local": local_status,
            "vps": vps_status,
            "sync_ready": local_status.get("status") == "connected" and vps_status.get("status") == "connected"
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_all":
        confirm = arguments.get("confirm", False)
        if not confirm:
            return [TextContent(type="text", text=json.dumps({
                "error": "Confirmation required. Set confirm=true to proceed with full sync.",
                "hint": "This will sync all collections from local to VPS and may take 5-10 minutes."
            }, indent=2))]
        
        result = run_sync_script()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_collection":
        collection_name = arguments.get("collection_name")
        if not collection_name:
            return [TextContent(type="text", text=json.dumps({
                "error": "collection_name is required"
            }, indent=2))]
        
        result = run_sync_script(["--collection", collection_name])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_dry_run":
        result = run_sync_script(["--dry-run"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_logs":
        count = min(arguments.get("count", 3), 10)
        latest_only = arguments.get("latest_only", False)
        
        if latest_only:
            count = 1
        
        logs = get_recent_logs(count)
        return [TextContent(type="text", text=json.dumps(logs, indent=2))]
    
    elif name == "qdrant_compare_collections":
        collection_name = arguments.get("collection_name")
        
        if collection_name:
            # Compare specific collection
            local_info = await get_collection_info(SOURCE_REST_URL, collection_name)
            vps_info = await get_collection_info(TARGET_REST_URL, collection_name, TARGET_API_KEY)
            
            local_points = local_info.get("points_count", 0)
            vps_points = vps_info.get("points_count", 0)
            
            result = {
                "collection": collection_name,
                "local": local_info,
                "vps": vps_info,
                "in_sync": local_points == vps_points,
                "difference": local_points - vps_points
            }
        else:
            # Compare all collections
            local_collections = await get_all_collections_with_counts(SOURCE_REST_URL)
            vps_collections = await get_all_collections_with_counts(TARGET_REST_URL, TARGET_API_KEY)
            
            # Create lookup dicts
            local_dict = {c["name"]: c for c in local_collections}
            vps_dict = {c["name"]: c for c in vps_collections}
            
            all_names = set(local_dict.keys()) | set(vps_dict.keys())
            
            comparison = []
            total_local_points = 0
            total_vps_points = 0
            out_of_sync = 0
            
            for name in sorted(all_names):
                local_info = local_dict.get(name, {"points_count": 0, "missing": True})
                vps_info = vps_dict.get(name, {"points_count": 0, "missing": True})
                
                local_points = local_info.get("points_count", 0)
                vps_points = vps_info.get("points_count", 0)
                
                total_local_points += local_points
                total_vps_points += vps_points
                
                in_sync = local_points == vps_points and not local_info.get("missing") and not vps_info.get("missing")
                if not in_sync:
                    out_of_sync += 1
                
                comparison.append({
                    "name": name,
                    "local_points": local_points,
                    "vps_points": vps_points,
                    "difference": local_points - vps_points,
                    "in_sync": in_sync,
                    "local_only": vps_info.get("missing", False),
                    "vps_only": local_info.get("missing", False)
                })
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_collections": len(all_names),
                    "local_collections": len(local_dict),
                    "vps_collections": len(vps_dict),
                    "out_of_sync": out_of_sync,
                    "total_local_points": total_local_points,
                    "total_vps_points": total_vps_points,
                    "total_difference": total_local_points - total_vps_points
                },
                "collections": comparison
            }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_from_vps_all":
        confirm = arguments.get("confirm", False)
        if not confirm:
            return [TextContent(type="text", text=json.dumps({
                "error": "Confirmation required. Set confirm=true to proceed with full sync from VPS.",
                "hint": "This will sync all collections from VPS to local and may take 5-10 minutes."
            }, indent=2))]
        
        result = run_sync_script([],  script_path=SYNC_SCRIPT_REVERSE)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_from_vps_collection":
        collection_name = arguments.get("collection_name")
        if not collection_name:
            return [TextContent(type="text", text=json.dumps({
                "error": "collection_name is required"
            }, indent=2))]
        
        result = run_sync_script(["--collection", collection_name], script_path=SYNC_SCRIPT_REVERSE)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "qdrant_sync_from_vps_dry_run":
        result = run_sync_script(["--dry-run"], script_path=SYNC_SCRIPT_REVERSE)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
