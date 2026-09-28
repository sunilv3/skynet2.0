# 🔴 Skynet MCP
### Professional Cybersecurity Automation Interface for AI Agents

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastMCP](https://img.shields.io/badge/FastMCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)
[![Version](https://img.shields.io/badge/Version-7.0.0-orange.svg)](https://github.com/sunilv3/skynet)
[![Tools](https://img.shields.io/badge/Security%20Tools-150%2B-brightgreen.svg)](#-supported-security-tools)

**Skynet MCP** is a Model Context Protocol (MCP) framework that connects Large Language Models (OpenCode, Claude, Cursor, Copilot) to 150+ professional security assessment tools via a fast, local execution engine.

---

## 📋 Table of Contents
- [Overview](#-overview)
- [Step-by-Step Setup Guide](#-step-by-step-setup-guide)
  - [Step 1: Clone and Environment Setup](#step-1-clone-and-environment-setup)
  - [Step 2: Start the Skynet Server](#step-2-start-the-skynet-server)
  - [Step 3: Connect Your AI Client](#step-3-connect-your-ai-client)
    - [OpenCode](#1-opencode-recommended)
    - [Claude Desktop](#2-claude-desktop)
    - [Cursor](#3-cursor)
    - [VS Code (Cline / Roo Code / Copilot)](#4-vs-code-cline--roo-code--copilot)
  - [Step 4: Verify Connection](#step-4-verify-connection)
- [Configuration Reference](#-configuration-reference)
- [Troubleshooting & FAQs](#-troubleshooting--faqs)
- [Supported Security Tools](#-supported-security-tools)
- [Autonomous AI Agents & Workflows](#-autonomous-ai-agents--workflows)
- [Architecture](#-architecture)
- [Legal & Ethical Notice](#-legal--ethical-notice)
- [License](#-license)

---

## 🎯 Overview

Skynet MCP consists of two primary components:
1. **`skynet_server.py`**: A high-performance Python REST service running on port `8888`. It executes host security tools, sanitizes terminal outputs (stripping ANSI color codes and carriage returns), manages processes, and tracks execution timing.
2. **`skynet_mcp.py`**: A FastMCP-based client that bridges AI applications (OpenCode, Claude, Cursor) to `skynet_server.py` over standard JSON-RPC (`stdio`).

### Key Capabilities
- **Clean AI Context**: Strips ANSI escape sequences (`\033[...]`) and resolves carriage returns (`\r`), ensuring LLMs receive clean, parsable text without token bloat.
- **Accurate Timing Diagnostics**: Subprocess execution durations and sub-millisecond cache latency are accurately tracked and reported.
- **Finding-Aware Exit Codes**: Distinguishes fatal errors from intentional tool exit codes (e.g., Nikto, Grep, Dalfox, TruffleHog exiting `1` or `2` when vulnerabilities/findings exist).
- **Proactive Timeouts**: Synchronized timeout buffers prevent clients from dropping requests prematurely during intensive scans.

---

## 🚀 Step-by-Step Setup Guide

### Step 1: Clone and Environment Setup

Ensure you have **Python 3.10+** installed.

#### On Windows (PowerShell):
```powershell
# 1. Navigate to the project directory
cd c:\Users\support\Desktop\skynet2.0-main\skynet2.0-main

# 2. Create a virtual environment
python -m venv skynet-env

# 3. Activate the virtual environment
.\skynet-env\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt
```

#### On Linux / macOS (Bash):
```bash
# 1. Navigate to the project directory
cd /path/to/skynet2.0-main

# 2. Create a virtual environment
python3 -m venv skynet-env

# 3. Activate the virtual environment
source skynet-env/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

---

### Step 2: Start the Skynet Server

The backend server must be running before the MCP client connects.

```bash
# Default startup (127.0.0.1:8888, 300-second execution timeout)
python skynet_server.py

# Optional: customize port and command timeout (e.g., 600s = 10 minutes)
python skynet_server.py --port 8888 --timeout 600
```

Verify that the server is active by opening `http://127.0.0.1:8888/health` in your browser or running:
```bash
curl http://127.0.0.1:8888/health
```

---

### Step 3: Connect Your AI Client

Choose your AI environment below:

#### 1. OpenCode (Recommended)
This repository includes a pre-configured `opencode.json` file in the project root. When you open this workspace folder in OpenCode, the MCP server is recognized automatically.

The configuration in `opencode.json`:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "skynet": {
      "type": "local",
      "command": [
        "python",
        "skynet_mcp.py",
        "--server",
        "http://127.0.0.1:8888"
      ],
      "environment": {
        "SKYNET_SERVER": "http://127.0.0.1:8888",
        "SKYNET_TIMEOUT": "330"
      },
      "enabled": true,
      "timeout": 300000
    }
  }
}
```
> **Timing Note**: OpenCode timeouts are configured in **milliseconds**. `300000` ms = 5 minutes. The environment variable `SKYNET_TIMEOUT: "330"` provides a 30-second margin for safe process termination, output sanitization, and JSON serialization.

---

#### 2. Claude Desktop
Open your Claude Desktop configuration file:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

Add the following entry under `mcpServers`:
```json
{
  "mcpServers": {
    "skynet-mcp": {
      "command": "python",
      "args": [
        "c:\\Users\\support\\Desktop\\skynet2.0-main\\skynet2.0-main\\skynet_mcp.py",
        "--server",
        "http://127.0.0.1:8888",
        "--timeout",
        "330"
      ],
      "timeout": 330
    }
  }
}
```
*(Update the path to match the absolute location of your `skynet_mcp.py` file).*

---

#### 3. Cursor
1. In Cursor, open **Settings** (`Ctrl+,` or `Cmd+,`).
2. Navigate to **Features** > **MCP**.
3. Click **+ Add New MCP Server**.
4. Configure:
   - **Name**: `skynet-mcp`
   - **Type**: `command`
   - **Command**: `python c:/Users/support/Desktop/skynet2.0-main/skynet2.0-main/skynet_mcp.py --server http://127.0.0.1:8888`

---

#### 4. VS Code (Cline / Roo Code / Copilot)
In your workspace `.vscode/settings.json` or Cline MCP configuration:
```json
{
  "servers": {
    "skynet-mcp": {
      "type": "stdio",
      "command": "python",
      "args": [
        "${workspaceFolder}/skynet_mcp.py",
        "--server",
        "http://127.0.0.1:8888"
      ]
    }
  }
}
```

---

### Step 4: Verify Connection

1. Start `skynet_server.py` in your terminal.
2. Launch your AI client (OpenCode, Claude, Cursor).
3. Test tool execution with a prompt:
   > *"Run a health check using the Skynet MCP tools and list available security tools."*
   or
   > *"Execute the command `python --version` using `execute_command`."*
4. The AI should call the tool and display the sanitized output with accurate timing diagnostics.

---

## ⚙️ Configuration Reference

### Command Line Arguments

#### `skynet_server.py`
| Argument | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Host address to bind the API server |
| `--port` | `8888` | Port for the HTTP API server |
| `--timeout` | `300` | Subprocess execution timeout in seconds |
| `--debug` | `False` | Enable detailed debug logs |

#### `skynet_mcp.py`
| Argument | Default | Description |
|---|---|---|
| `--server` | `http://127.0.0.1:8888` | URL of the Skynet backend server |
| `--timeout` | `330` | Request timeout in seconds |
| `--debug` | `False` | Enable debug logging |

### Environment Variables
| Variable | Default | Component | Description |
|---|---|---|---|
| `SKYNET_SERVER` | `http://127.0.0.1:8888` | MCP Client | URL of the backend server |
| `SKYNET_TIMEOUT` | `330` / `300` | Both | Timeout threshold in seconds |
| `COMMAND_TIMEOUT` | `300` | Server | Subprocess execution limit in seconds |
| `SKYNET_PORT` | `8888` | Server | Listening port for the API server |
| `DEBUG_MODE` | `0` | Server | Set to `1` or `true` for debug logging |

---

## 🔍 Troubleshooting & FAQs

### 1. "Connection refused" or MCP fails to connect
- **Cause**: `skynet_server.py` is not running.
- **Fix**: Launch `python skynet_server.py --port 8888` in a separate terminal before starting your AI client.

### 2. OpenCode aborts scans after 30 seconds
- **Cause**: OpenCode configuration using default `timeout: 30000` (30 seconds).
- **Fix**: Verify your `opencode.json` has `"timeout": 300000` (5 minutes in milliseconds).

### 3. Output contains corrupted characters or broken JSON
- **Cause**: Raw terminal ANSI escapes interfering with model tokenizers.
- **Fix**: Skynet MCP automatically runs all outputs through `strip_ansi()` and `sanitize_output()`. Ensure you are running the latest `skynet_server.py` and `skynet_mcp.py`.

### 4. A security tool exited with code 1, but reported success
- **Explanation**: Tools like Nikto, Grep, Dalfox, and TruffleHog return exit code 1 or 2 when vulnerabilities or matches are found. Skynet MCP recognizes this as `completed_with_findings`.

---

## 🛠️ Supported Security Tools

Skynet MCP interacts directly with command-line security tools available on your system PATH or environment:

| Category | Representative Tools | Capabilities |
|---|---|---|
| **Network & Discovery** | `nmap`, `masscan`, `rustscan`, `arp-scan`, `nbtscan` | Port enumeration, service fingerprinting, host scanning |
| **Web Assessment** | `nuclei`, `sqlmap`, `ffuf`, `gobuster`, `nikto`, `wpscan` | CVE detection, injection testing, directory fuzzing |
| **Secrets & OSINT** | `trufflehog`, `amass`, `subfinder`, `sherlock`, `spiderfoot` | API key scanning, subdomain discovery, recon |
| **Authentication** | `hydra`, `john`, `hashcat`, `netexec`, `smbmap` | Password auditing, hash analysis, share enumeration |
| **Binary & Forensics** | `ghidra`, `radare2`, `gdb`, `binwalk`, `checksec` | Firmware extraction, ELF/PE analysis, exploit safety checks |
| **Cloud & Containers** | `prowler`, `trivy`, `scout-suite`, `pacu`, `checkov` | AWS/Azure auditing, container vulnerability scanning |

---

## 🧠 Autonomous AI Agents & Workflows

Beyond individual tool execution, Skynet MCP includes built-in autonomous intelligence engines that your AI client (OpenCode, Claude, Cursor) can orchestrate:

### 1. Strategic Planning Engine (Attacker Mindset v7.0)
- **Concept**: Models the adversary as an evolving finite state machine tracking discovered evidence, target defenses (WAFs), and attack phases.
- **Key MCP Tools**:
  - `initialize_strategic_engagement(target)`: Sets up a strategic mission tracking state.
  - `get_next_strategic_move(target)`: Recommends the highest-probability tool and parameters for the current attack surface.
  - `update_strategic_mindset(tool, output)`: Feeds scan results back into the engine to pivot attack vectors.
  - `set_aggressiveness_level(level)`: Configures intensity (`stealth`, `balanced`, `aggressive`, `blitz`).

### 2. Autonomous Reconnaissance & Assessment
- **Key MCP Tools**:
  - `ai_reconnaissance_workflow(target, depth)`: Automatically analyzes target tech stack, constructs a multi-step attack chain, and runs prioritized discovery tools (`surface`, `standard`, `deep`).
  - `ai_vulnerability_assessment(target, focus_areas)`: Chains web, network, and API security tools to produce a prioritized risk report with attack surface scoring.

### 3. Bug Bounty Hunting Workflows
- **Key MCP Tools**:
  - `bugbounty_reconnaissance_workflow(domain, scope, out_of_scope)`: Automates scoped asset discovery aligned with program Rules of Engagement (RoE).
  - `bugbounty_vulnerability_hunting(domain, priority_vulns)`: Prioritizes high-impact vectors (RCE, SQLi, SSRF, IDOR).
  - `file_upload_testing_workflow(url, endpoint, allowed_types)`: Systematically tests file upload endpoints for extension bypasses, MIME confusion, and execution vulnerabilities.

### 4. CTF Challenge Automator
- **Key MCP Tools**:
  - `ctf_analyze_challenge(challenge_name, category, description)`: Inspects binary protections (`NX`, `PIE`, `Canary`, `RELRO`) and web challenge patterns.
  - `ctf_solve_challenge(challenge_name, target_host, port)`: Automates exploitation scripts against challenge targets.

### 5. CVE Intelligence & Target Correlation
- **Key MCP Tools**:
  - `monitor_cve_feeds(hours, severity_filter)`: Streams recent high/critical vulnerability disclosures.
  - `correlate_cves_for_target(technologies, versions)`: Maps detected host technologies directly to known CVEs and public exploit advisories.

### 6. Headless Browser Automation Agent
- **Key MCP Tools**:
  - `browser_navigate(url)` / `browser_screenshot(output_path)`: Automates dynamic Single Page Application (SPA) analysis and captures visual evidence via headless Chrome.

---

## 🏗️ Architecture

```
[ AI Assistant: OpenCode / Claude / Cursor ]
                     │
              stdio (JSON-RPC)
                     │
                     ▼
          [ skynet_mcp.py (FastMCP) ]
                     │
               HTTP (Port 8888)
                     │
                     ▼
        [ skynet_server.py (Flask API) ]
          ├── Process Manager (psutil)
          ├── Output Sanitizer (ANSI stripping)
          ├── Result Cache (instant lookup)
          └── Subprocess Executor (timeout-controlled)
                     │
                     ▼
          [ Host Security Tooling ]
        (Nmap, Nuclei, Gobuster, etc.)
```

---

## ⚖️ Legal & Ethical Notice

Skynet MCP is designed exclusively for authorized penetration testing, security research, and educational laboratory environments (e.g., CTFs, TryHackMe, Hack The Box). Users must have explicit, written authorization before testing any target network or system. Unauthorized use is illegal.

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).
