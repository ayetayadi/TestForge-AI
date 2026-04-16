// ==============================
// Project
// ==============================
export interface Project {
  id: string;
  project_key: string;
  project_name: string;
  story_count: number;
}

export interface ImportResult {
  message: string;
  result: {
    imported: number;
    skipped: number;
  };
}

// ==============================
// User Story
// ==============================
export interface UserStory {
  id: string;
  issue_key: string;
  project_id: string;

  title?: string;
  description?: string;
  acceptance_criteria?: string[];

  issue_type?: string;
  jira_status?: string;
  priority?: string;
  story_points?: number;

  assignee?: string;
  reporter?: string;

  epic_key?: string;
  sprint?: string;
  labels?: string[];
  components?: string[];

  fix_version?: string;

  current_score?: number;  // ← AJOUTÉ (dernier score)
  selected_version_id?: string | null;
}

// ==============================
// Version (résultat d'une exécution IA)
// ==============================
export type AgentStatus = 'processing' | 'completed' | 'failed' | 'idle';

export interface UserStoryVersion {
  id: string;
  user_story_id: string;

  improved_story: string;
  generated_acceptance_criteria: string[];

  initial_score: number;
  final_score: number;
 
  testability_score?: number;
  is_testable?: boolean;
  testability_issues?: string[];

  llm_calls: number;  // ← RENOMMÉ (était iteration)
  duration?: number;
  model_used?: string;
  prompt_tokens?: number;
  completion_tokens?: number;

  agent_status: AgentStatus;  // ← AJOUTÉ
  decision_status: 'pending' | 'approved' | 'rejected';

  started_at?: string;  // ← AJOUTÉ
  completed_at?: string;  // ← AJOUTÉ
  created_at?: string;
}

// ==============================
// Version (état runtime UI)
// ==============================
export interface StoryVersion {
  version_id: string;
  issue_key: string;
  status: AgentStatus;
  started_at?: string;
}

// ==============================
// StoryWithVersion (UI enrichie)
// ==============================
export interface StoryWithVersion extends UserStory {
  // Version en cours
  version?: {
    version_id: string;
    issue_key: string;
  };

  agentStatus?: AgentStatus;
  versionStatus?: AgentStatus;
  
  versionScore?: number;
  versionIteration?: number;

  // Versions
  versions?: UserStoryVersion[];

  // Backend truth
  selected_version?: UserStoryVersion | null;
  latest_version?: UserStoryVersion | null;
  display_version?: UserStoryVersion | null;
  processing_version?: UserStoryVersion | null;  // ← AJOUTÉ
  has_processing?: boolean;  // ← AJOUTÉ
  versions_count?: number;  // ← AJOUTÉ
}

// ==============================
// Decision
// ==============================
export type DecisionChoice = 'approve' | 'reject_keep' | 'reject_relaunch';

export type DecisionStatus = 'pending' | 'approved' | 'rejected';

// ==============================
// VersionState (remplace JobState)
// ==============================
export interface VersionState {
  version_id: string;
  agent_status: AgentStatus | 'not_found';
  iteration: number;

  // Story info
  user_story_id?: string;
  jira_id?: string;
  issue_key?: string;
  project_id?: string;
  project_name?: string;

  // Original content
  initial_story?: string;
  raw_story?: string;
  existing_ac?: string[];

  // Improved content
  improved_story?: string;
  generated_acceptance_criteria?: string[];

  // Scores
  initial_score?: number;
  final_score?: number;
  score_delta?: number;

  // Testability
  testability_score?: number;
  is_testable?: boolean;
  testability_issues?: string[];

  // LLM Metrics
  model_used?: string;
  llm_calls?: number;
  duration?: number;

  // Decision
  decision_status?: DecisionStatus;

  // Dates
  started_at?: string;
  completed_at?: string;

  // Trace
  trace?: TraceEntry[];

  has_new_version?: boolean;
  versions_count?: number;
}

export interface TraceEntry {
  step?: string;
  iteration?: number;
  feedback?: string;
  data?: {
    final?: number;
    current_score?: number;
    delta?: number;
    justification?: string;
  };
}

// ==============================
// Active Version (dashboard)
// ==============================
export interface ActiveVersion {
  version_id: string;
  jira_id: string;
  issue_key: string;
  agent_status: AgentStatus;
  current_score?: number;
  final_score?: number;
  iteration: number;
  started_at?: string;
}

// ==============================
// Running Version
// ==============================
export interface RunningVersion {
  version_id: string;
  issue_key: string;
  agent_status: AgentStatus;
  current_step?: string;
  iteration: number;
}

// ==============================
// Pending Version (UI)
// ==============================
export interface PendingVersion {
  version_id: string;
  issue_key: string;
  agent_status: AgentStatus;
  iteration: number;
  improved_story?: string;
  generated_acceptance_criteria?: string[];
  final_score?: number;
}

// ==============================
// Decision Response
// ==============================
export interface DecisionResponse {
  status: 'ok' | 'error';
  message?: string;
  issue_key?: string;
  version_id?: string;
  new_version_id?: string;
  previous_version_id?: string;
  final_score?: number;
}

// ==============================
// Pipeline Request
// ==============================
export interface RunByProject {
  project_id: string;
}

export interface RunByKeys {
  issue_keys: string[];
}

export type RunPipelineRequest = RunByProject | RunByKeys;

export interface PipelineResponse {
  message: string;
  total_requests: number;
  total_versions: number;
  skipped: Array<{
    issue_key: string;
    reason: string;
  }>;
  versions: Array<{
    version_id: string;
    issue_key: string;
  }>;
}

// ==============================
// SSE Events
// ==============================
export type SSEEventType =
  | 'processing'      // ✅ Agent tourne
  | 'completed'       // ✅ Succès
  | 'failed'          // ✅ Erreur
  | 'ping'          // ✅ Keepalive
  | 'version_created'
  | 'version_updated'

export interface SSEEvent {
  type: SSEEventType;
  data?: {
    message?: string;           // "Analyzing story...", etc.
    status?: AgentStatus;
    jira_id?: string;
    thread_id?: string;
    version_id?: string;        // ← AJOUTÉ
    
    // Au completion
    final_score?: number;
    initial_score?: number;
    score_delta?: number;
    improved_story?: string;
    generated_acceptance_criteria?: string[];
    iteration?: number;
    testability_score?: number;
    is_testable?: boolean;
    has_new_version?: boolean;
    versions_count?: number;
    
    // Au failure
    error?: string;
  };
  timestamp: string;
}

// ==============================
// UI Types
// ==============================
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
}

// ==============================
// HELPER TYPES
// ==============================

// Pour convertir une réponse API en StoryWithVersion
export interface ApiStoryResponse {
  id: string;
  issue_key: string;
  project_id: string;
  title?: string;
  description?: string;
  acceptance_criteria?: string[];
  current_score?: number;
  selected_version?: UserStoryVersion | null;
  latest_version?: UserStoryVersion | null;
  display_version?: UserStoryVersion | null;
  processing_version?: UserStoryVersion | null;
  has_processing?: boolean;
  versions_count?: number;
  versions?: UserStoryVersion[];
}

// Pour la requête de décision
export interface DecisionApiRequest {
  decision: DecisionChoice;
  version_id?: string;
}