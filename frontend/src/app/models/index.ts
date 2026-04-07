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
// User Story (le problème Jira)
// ==============================
export interface UserStory {
  id: string;
  issue_key: string;
  jira_project_id?: string;

  // Contenu original
  title?: string;
  description?: string;
  acceptance_criteria?: string[] | string;

  // Métadonnées Jira
  issue_type?: string;
  status?: string;
  priority?: string;
  story_points?: number;

  // Personnes
  assignee?: string;
  reporter?: string;

  // Agile
  epic_key?: string;
  epic_name?: string;
  sprint?: string;
  labels?: string[];
  components?: string[];

  // Version Jira
  fix_version?: string;

  // Decision state
  decision_status?: 'pending' | 'approved' | 'rejected_keep' | 'rejected_relaunch';
  selected_version_id?: string | null;
  selected_version?: UserStoryVersion | null;
  latest_version?: UserStoryVersion | null;
}

// ==============================
// Version (résultat d'un job)
// ==============================
export interface UserStoryVersion {
  id: string;
  story_id: string;
  job_id: string;

  // Contenu amélioré
  improved_story: string;
  acceptance_criteria: string[];

  // Scores
  initial_score: number;
  final_score: number;
  score_delta: number;

  // Metadata
  iteration: number;
  created_at?: string;

  // Selection
  is_selected: boolean;
}

// ==============================
// Job (une exécution du pipeline)
// ==============================
export type JobStatus = 'processing' | 'completed' | 'failed';

export interface Job {
  job_id: string;
  issue_key: string;
  story_id?: string;
  status: JobStatus;
  phase?: 'analyzing' | 'refining' | 'evaluating' | 'completed';
  iteration?: number;
  created_at?: string;
}

// ==============================
// StoryJob (état runtime UI)
// ==============================
export interface StoryJob {
  job_id: string;
  issue_key: string;
}

// ==============================
// StoryWithJob (UI enrichie)
// ==============================
export interface StoryWithJob extends UserStory {
  // Job actif (runtime)
  job?: StoryJob;
  jobPhase?: 'analyzing' | 'refining' | 'evaluating' | 'completed' | 'failed';
  jobScore?: number;
  jobIteration?: number;

  // Versions
  versions?: UserStoryVersion[];
  selected_version?: UserStoryVersion | null;  // Version approuvée par l'utilisateur
  latest_version?: UserStoryVersion | null;    // Dernière version du dernier job
}

export type DecisionStatus =
  | 'approved'
  | 'rejected_keep'
  | 'rejected_relaunch'
  | null;


// ==============================
// JobState (réponse API détaillée)
// ==============================
export interface JobState {
  job_id: string;
  status: JobStatus | 'not_found';
  phase?: 'analyzing' | 'refining' | 'evaluating' | 'completed';
  iteration: number;

  // Story info
  story_id?: string;
  jira_id?: string;
  issue_key?: string;
  project_id?: string;
  project_name?: string;

  // Original content
  initial_story?: string;
  raw_story?: string;
  existing_ac?: string[] | string;

  // Improved content (from version)
  improved_story?: string;
  acceptance_criteria?: string[];

  // Scores
  initial_score?: number;
  final_score?: number;

  // Version reference
  version_id?: string;

  decision_status?: DecisionStatus;

  // Trace/history
  trace?: TraceEntry[];

  has_new_version?: boolean; // Indique s'il existe une version améliorée non encore sélectionnée
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
// Active Job (dashboard)
// ==============================
export interface ActiveJob {
  job_id: string;
  jira_id: string;
  issue_key: string;
  status: JobStatus;
  current_score?: number;
  final_score?: number;
  iteration: number;
}

// ==============================
// Running Job
// ==============================
export interface RunningJob {
  job_id: string;
  issue_key: string;
  status: JobStatus;
  current_step?: string;
  iteration: number;
}

// ==============================
// Pending Job (UI)
// ==============================
export interface PendingJob {
  job_id: string;
  issue_key: string;
  status: JobStatus;
  iteration: number;
  improved_story?: string;
  acceptance_criteria?: string[];
  final_score?: number;
}

// ==============================
// Decision
// ==============================
export type DecisionChoice = 'approve' | 'reject_keep' | 'reject_relaunch';

export interface DecisionResponse {
  status: 'ok' | 'error';
  message?: string;
  issue_key?: string;
  version_id?: string;
  new_job_id?: string;
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
  jobs: Job[];
}

// ==============================
// SSE Events
// ==============================
export type SSEEventType =
  | 'analyzing'
  | 'refining'
  | 'evaluating'
  | 'completed'
  | 'failed'
  | 'ping';

export interface SSEEvent {
  type: SSEEventType;
  data?: {
    iteration?: number;
    initial_score?: number;
    final_score?: number;
    improved_story?: string;
    acceptance_criteria?: string[];
    version_id?: string;
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