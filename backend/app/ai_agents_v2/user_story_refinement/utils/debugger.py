"""
Debug utilities for ReAct Agent.

✅ COMPLETE TRACING:
- LLM calls (input/output)
- Tool calls (name, args, result)
- Agent reasoning steps
- Errors with full context
- Save to JSON file for analysis
- Generate Mermaid diagram for visualization
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path


class ReActDebugger:
    """
    Debugger for ReAct Agent.
    
    ✅ Captures:
    - Every LLM call with full prompt and response
    - Every tool call with arguments and result
    - Agent reasoning steps
    - Final output
    - Errors with full stack trace
    
    ✅ Outputs:
    - Console (colored, readable)
    - JSON file (for deep analysis)
    - Mermaid diagram (for visualization)
    """
    
    def __init__(self, jira_id: str, enabled: bool = True):
        """
        Initialize debugger.
        
        Args:
            jira_id: Jira issue ID for file naming
            enabled: Enable/disable debugging
        """
        self.jira_id = jira_id
        self.enabled = enabled
        self.trace = {
            "jira_id": jira_id,
            "started_at": datetime.utcnow().isoformat(),
            "steps": [],
            "errors": [],
            "summary": {}
        }
        self.step_counter = 0
        
        # Créer le dossier traces s'il n'existe pas
        self.traces_dir = Path(__file__).parent.parent.parent.parent / "traces"
        self.traces_dir.mkdir(exist_ok=True)
        
        if self.enabled:
            print(f"\n{'🔍'*40}")
            print(f"[DEBUG] ReAct Agent Trace Started")
            print(f"[DEBUG] Jira ID: {jira_id}")
            print(f"[DEBUG] Trace file: {self._get_trace_filename()}")
            print(f"{'🔍'*40}\n")
    
    def _get_trace_filename(self) -> str:
        """Generate unique trace filename."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"trace_{self.jira_id}_{timestamp}.json"
    
    def _save_step(self, step_type: str, data: Dict[str, Any]):
        """Save a step to the trace."""
        if not self.enabled:
            return
        
        self.step_counter += 1
        step = {
            "step": self.step_counter,
            "timestamp": datetime.utcnow().isoformat(),
            "type": step_type,
            **data
        }
        self.trace["steps"].append(step)
    
    def log_input(self, story: str, acceptance_criteria: List[str], language: str):
        """Log the initial input."""
        if not self.enabled:
            return
        
        print(f"\n{'─'*80}")
        print(f"[📥 INPUT] Agent Received")
        print(f"{'─'*80}")
        print(f"[STORY] {story[:200]}...")
        print(f"[STORY LENGTH] {len(story)} chars")
        print(f"[AC COUNT] {len(acceptance_criteria)} items")
        if acceptance_criteria:
            for i, ac in enumerate(acceptance_criteria[:3], 1):
                print(f"  AC{i}: {ac[:100]}...")
        print(f"[LANGUAGE] {language}")
        print(f"{'─'*80}\n")
        
        self._save_step("input", {
            "story": story,
            "story_length": len(story),
            "acceptance_criteria": acceptance_criteria,
            "ac_count": len(acceptance_criteria),
            "language": language
        })
    
    def log_llm_call(self, messages: List[Any], model: str):
        """Log an LLM call."""
        if not self.enabled:
            return
        
        print(f"\n{'🤖'*40}")
        print(f"[🤖 LLM CALL] Step {self.step_counter + 1}")
        print(f"{'🤖'*40}")
        print(f"[MODEL] {model}")
        print(f"[MESSAGES] {len(messages)} messages")
        
        for i, msg in enumerate(messages):
            if isinstance(msg, tuple):
                role = msg[0]
                content = msg[1]
            else:
                role = getattr(msg, 'role', getattr(msg, 'type', 'unknown'))
                content = getattr(msg, 'content', str(msg))
            print(f"\n  [{role.upper()}]")
            print(f"  {content[:300]}...")
        
        print(f"{'─'*80}")
        
        self._save_step("llm_call", {
            "model": model,
            "messages_count": len(messages),
            "messages": [
                {
                    "role": m[0] if isinstance(m, tuple) else getattr(m, 'role', getattr(m, 'type', 'unknown')),
                    "content": m[1] if isinstance(m, tuple) else getattr(m, 'content', str(m))[:1000]
                }
                for m in messages
            ]
        })
    
    def log_llm_response(self, response: Any):
        """Log an LLM response."""
        if not self.enabled:
            return
        
        content = getattr(response, 'content', str(response))
        tool_calls = getattr(response, 'tool_calls', [])
        
        print(f"\n[✅ LLM RESPONSE]")
        print(f"[CONTENT] {content[:200] if content else '(no content)'}...")
        
        if tool_calls:
            print(f"\n[🔧 TOOL CALLS REQUESTED] {len(tool_calls)}")
            for tc in tool_calls:
                print(f"  → {tc.get('name', 'unknown')}")
                args = tc.get('args', {})
                print(f"     Args: {json.dumps(args, indent=2, ensure_ascii=False)[:300]}")
        
        print(f"{'─'*80}\n")
        
        self._save_step("llm_response", {
            "content": content,
            "has_content": bool(content),
            "tool_calls": [
                {
                    "name": tc.get('name'),
                    "args": tc.get('args')
                }
                for tc in tool_calls
            ],
            "tool_calls_count": len(tool_calls)
        })
    
    def log_tool_call(self, tool_name: str, args: Dict[str, Any]):
        """Log a tool call."""
        if not self.enabled:
            return
        
        print(f"\n{'🔨'*40}")
        print(f"[🔨 TOOL CALL] {tool_name}")
        print(f"{'🔨'*40}")
        print(f"[ARGS]")
        
        truncated_args = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 200:
                truncated_args[k] = v[:200] + "..."
            elif isinstance(v, list) and len(v) > 5:
                truncated_args[k] = v[:5] + [f"... ({len(v)-5} more items)"]
            else:
                truncated_args[k] = v
        
        print(json.dumps(truncated_args, indent=2, ensure_ascii=False))
    
    def log_tool_result(self, tool_name: str, result: Dict[str, Any], success: bool = True):
        """Log a tool result."""
        if not self.enabled:
            return
        
        status_icon = "✅" if success else "❌"
        print(f"\n[{status_icon} TOOL RESULT] {tool_name}")
        
        if success:
            if "final_score" in result:
                print(f"  → Final Score: {result.get('final_score', 'N/A')}")
            if "testability_score" in result:
                print(f"  → Testability: {result.get('testability_score', 'N/A')}")
            if "is_testable" in result:
                print(f"  → Is Testable: {result.get('is_testable', 'N/A')}")
            if "acceptance_criteria" in result:
                ac = result.get("acceptance_criteria", [])
                print(f"  → AC Extracted: {len(ac)} items")
            if "similarity" in result:
                print(f"  → Similarity: {result.get('similarity', 'N/A')}")
            if "violations" in result:
                violations = result.get("violations", [])
                if violations:
                    print(f"  → Violations: {violations}")
        else:
            print(f"  → Error: {result.get('error', 'Unknown error')}")
        
        print(f"{'─'*80}")
        
        self._save_step("tool_result", {
            "tool": tool_name,
            "success": success,
            "result": result
        })
    
    def log_agent_step(self, step_type: str, details: Dict[str, Any]):
        """Log an agent reasoning step."""
        if not self.enabled:
            return
        
        print(f"\n[🧠 AGENT] {step_type}")
        for k, v in details.items():
            print(f"  {k}: {v}")
        
        self._save_step("agent_reasoning", {
            "step_type": step_type,
            "details": details
        })
    
    def log_error(self, error: Exception, context: Dict[str, Any] = None):
        """Log an error with full context."""
        import traceback
        
        error_info = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
            "context": context or {}
        }
        
        self.trace["errors"].append(error_info)
        
        print(f"\n{'❌'*40}")
        print(f"[❌ ERROR] {type(error).__name__}")
        print(f"{'❌'*40}")
        print(f"[MESSAGE] {str(error)}")
        
        if context:
            print(f"\n[CONTEXT]")
            for k, v in context.items():
                print(f"  {k}: {v}")
        
        print(f"\n[TRACEBACK]")
        print(traceback.format_exc())
        print(f"{'❌'*40}\n")
        
        self._save_step("error", error_info)
    
    def log_final_result(self, result: Dict[str, Any]):
        """Log the final result."""
        if not self.enabled:
            return
        
        print(f"\n{'🎯'*40}")
        print(f"[🎯 FINAL RESULT]")
        print(f"{'🎯'*40}")
        
        key_fields = [
            "score", "testability_score", "is_improved", "valid",
            "language_consistent", "role_preserved", "iterations",
            "agent_status", "similarity"
        ]
        
        for field in key_fields:
            if field in result:
                value = result[field]
                if isinstance(value, float):
                    print(f"  {field}: {value:.3f}")
                else:
                    print(f"  {field}: {value}")
        
        print(f"{'🎯'*40}\n")
        
        self.trace["summary"] = {
            "score": result.get("score"),
            "testability_score": result.get("testability_score"),
            "is_improved": result.get("is_improved"),
            "valid": result.get("valid"),
            "iterations": result.get("iterations"),
            "agent_status": result.get("agent_status"),
            "has_error": result.get("error") is not None
        }
    
    def save(self):
        """Save the complete trace to a JSON file."""
        if not self.enabled:
            return
        
        self.trace["completed_at"] = datetime.utcnow().isoformat()
        self.trace["total_steps"] = self.step_counter
        self.trace["has_errors"] = len(self.trace["errors"]) > 0
        
        filename = self._get_trace_filename()
        filepath = self.traces_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.trace, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"\n{'📁'*40}")
        print(f"[📁 TRACE SAVED] {filepath}")
        print(f"{'📁'*40}\n")
        
        if self.trace["errors"]:
            print(f"\n{'⚠️'*40}")
            print(f"[⚠️ ERRORS DETECTED] {len(self.trace['errors'])} error(s)")
            for i, err in enumerate(self.trace["errors"], 1):
                print(f"  {i}. {err['type']}: {err['message'][:100]}")
            print(f"{'⚠️'*40}\n")
    
    # ============================================================
    # MERMAID DIAGRAM GENERATION
    # ============================================================
    
    def draw_mermaid(self) -> str:
        """
        Génère un diagramme Mermaid du workflow ReAct.
        
        Returns:
            Code Mermaid prêt à être rendu (format markdown)
        """
        if not self.enabled or not self.trace["steps"]:
            return ""
        
        mermaid = ["```mermaid", "graph TD"]
        mermaid.append("    %% Style definitions")
        mermaid.append("    classDef input fill:#e1f5fe,stroke:#01579b")
        mermaid.append("    classDef llm fill:#fff3e0,stroke:#e65100")
        mermaid.append("    classDef tool fill:#e8f5e9,stroke:#1b5e20")
        mermaid.append("    classDef result fill:#f3e5f5,stroke:#4a148c")
        mermaid.append("    classDef final fill:#c8e6c9,stroke:#2e7d32")
        mermaid.append("    classDef error fill:#ffcdd2,stroke:#b71c1c")
        mermaid.append("")
        
        nodes = {}
        edges = []
        last_node_id = None
        tool_call_nodes = {}  # Pour lier les appels aux résultats
        
        for step in self.trace["steps"]:
            step_num = step["step"]
            step_type = step["type"]
            
            if step_type == "input":
                node_id = f"N{step_num}"
                ac_count = step.get("ac_count", 0)
                label = f"[📥 INPUT]<br/>{ac_count} AC"
                nodes[node_id] = {"label": label, "class": "input"}
                last_node_id = node_id
            
            elif step_type == "llm_call":
                node_id = f"N{step_num}"
                model = step.get("model", "LLM")
                label = f"{{🤖 LLM CALL}}<br/>{model}"
                nodes[node_id] = {"label": label, "class": "llm"}
                if last_node_id:
                    edges.append(f"    {last_node_id} --> {node_id}")
                last_node_id = node_id
            
            elif step_type == "llm_response":
                node_id = f"N{step_num}"
                tool_calls = step.get("tool_calls", [])
                
                if tool_calls:
                    for tc in tool_calls:
                        tc_name = tc.get("name", "unknown")
                        tc_node_id = f"{node_id}_{tc_name}"
                        label = f"[🔧 {tc_name}]"
                        nodes[tc_node_id] = {"label": label, "class": "tool"}
                        edges.append(f"    {last_node_id} --> {tc_node_id}")
                        tool_call_nodes[tc_name] = tc_node_id
                        last_node_id = tc_node_id
                else:
                    content = step.get("content", "")
                    if content:
                        label = f"[📝 RESPONSE]"
                        nodes[node_id] = {"label": label, "class": "llm"}
                        edges.append(f"    {last_node_id} --> {node_id}")
                        last_node_id = node_id
            
            elif step_type == "tool_result":
                tool_name = step.get("tool", "unknown")
                result = step.get("result", {})
                node_id = f"N{step_num}"
                
                score = result.get("final_score", result.get("score"))
                if score is not None and isinstance(score, (int, float)):
                    label = f"[✅ {tool_name}]<br/>Score: {score:.2f}"
                elif "acceptance_criteria" in result:
                    ac_count = len(result.get("acceptance_criteria", []))
                    label = f"[✅ {tool_name}]<br/>{ac_count} AC"
                elif "similarity" in result:
                    sim = result.get("similarity", 0)
                    label = f"[✅ {tool_name}]<br/>Sim: {sim:.2f}"
                else:
                    label = f"[✅ {tool_name}]"
                
                nodes[node_id] = {"label": label, "class": "result"}
                
                if tool_name in tool_call_nodes:
                    edges.append(f"    {tool_call_nodes[tool_name]} --> {node_id}")
                
                last_node_id = node_id
            
            elif step_type == "error":
                node_id = f"N{step_num}"
                error_msg = step.get("message", "Error")[:30]
                label = f"[❌ ERROR]<br/>{error_msg}"
                nodes[node_id] = {"label": label, "class": "error"}
                if last_node_id:
                    edges.append(f"    {last_node_id} --> {node_id}")
                last_node_id = node_id
        
        # Ajouter le nœud final
        if self.trace.get("summary"):
            summary = self.trace["summary"]
            node_id = "FINAL"
            score = summary.get("score", 0)
            improved = "✅" if summary.get("is_improved") else "❌"
            label = f"[🎯 FINAL]<br/>Score: {score:.2f} {improved}"
            nodes[node_id] = {"label": label, "class": "final"}
            if last_node_id:
                edges.append(f"    {last_node_id} --> {node_id}")
        
        # Ajouter les définitions de nœuds
        for node_id, node_data in nodes.items():
            mermaid.append(f"    {node_id}{node_data['label']}:::{node_data['class']}")
        
        # Ajouter les arêtes
        mermaid.extend(edges)
        
        mermaid.append("```")
        return "\n".join(mermaid)
    
    def save_mermaid(self, filename: str = None) -> str:
        """
        Sauvegarde le diagramme Mermaid dans un fichier.
        
        Args:
            filename: Nom du fichier (défaut: trace_*.mmd)
            
        Returns:
            Chemin du fichier sauvegardé
        """
        mermaid_code = self.draw_mermaid()
        if not mermaid_code:
            return ""
        
        if filename is None:
            filename = self._get_trace_filename().replace(".json", ".mmd")
        
        filepath = self.traces_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(mermaid_code)
        
        print(f"\n{'📊'*40}")
        print(f"[📊 MERMAID] Diagram saved: {filepath}")
        print(f"{'📊'*40}\n")
        print(f"[TIP] Copy the content to https://mermaid.live to visualize!")
        
        return str(filepath)


# ============================================================
# UTILITY FUNCTION
# ============================================================

def create_debugger(jira_id: str, enabled: bool = None) -> ReActDebugger:
    """
    Create a debugger instance.
    
    Args:
        jira_id: Jira issue ID
        enabled: Enable/disable (default: from env DEBUG_ENABLED)
    
    Returns:
        ReActDebugger instance
    """
    if enabled is None:
        enabled = os.getenv("DEBUG_ENABLED", "false").lower() == "true"
    
    return ReActDebugger(jira_id=jira_id, enabled=enabled)