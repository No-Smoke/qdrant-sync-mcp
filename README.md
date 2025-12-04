# Qdrant Sync MCP Server

A dedicated MCP server for bidirectional sync between local Qdrant and VPS.

## Overview

**Local:** localhost:6335 (73 collections)  
**VPS:** 74.50.49.35:6333 (74 collections)

## Tools (9 total)

### Status & Comparison
| Tool | Description |
|------|-------------|
| `qdrant_sync_status` | Check connectivity to both instances |
| `qdrant_compare_collections` | Compare collection stats, identify differences |

### Local → VPS (Push)
| Tool | Description |
|------|-------------|
| `qdrant_sync_all` | Full sync all collections (requires confirm=true) |
| `qdrant_sync_collection` | Sync single collection by name |
| `qdrant_sync_dry_run` | Preview without syncing |

### VPS → Local (Pull)
| Tool | Description |
|------|-------------|
| `qdrant_sync_from_vps_all` | Pull all collections (requires confirm=true) |
| `qdrant_sync_from_vps_collection` | Pull single collection by name |
| `qdrant_sync_from_vps_dry_run` | Preview VPS state without syncing |

### Logs
| Tool | Description |
|------|-------------|
| `qdrant_sync_logs` | View recent sync logs |

## Installation

```bash
cd /home/vanya/3-Projects-Github/qdrant-sync-mcp
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Claude Desktop Config

```json
{
  "qdrant-sync": {
    "command": "/home/vanya/3-Projects-Github/qdrant-sync-mcp/venv/bin/python",
    "args": ["/home/vanya/3-Projects-Github/qdrant-sync-mcp/server.py"],
    "env": {
      "QDRANT_SYNC_CONFIG": "/home/vanya/.config/qdrant-sync/config.env",
      "QDRANT_SYNC_SCRIPT": "/home/vanya/scripts/sync-qdrant-to-vps.sh",
      "QDRANT_SYNC_SCRIPT_REVERSE": "/home/vanya/scripts/sync-qdrant-from-vps.sh",
      "QDRANT_SYNC_LOG_DIR": "/home/vanya/logs"
    }
  }
}
```

## Scripts

- `/home/vanya/scripts/sync-qdrant-to-vps.sh` - Local → VPS
- `/home/vanya/scripts/sync-qdrant-from-vps.sh` - VPS → Local

## Related Docs

`/home/vanya/hp-projects/3-Projects-Github/onesong-coachgrow-ebatt-shared-enhancement-and-alignment-project/04.docs/Qdrant-sync-system.md`

---
Created: November 23, 2025 | Author: Vanya + Claude
