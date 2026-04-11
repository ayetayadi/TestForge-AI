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

  selected_version_id?: string | null;
}

// ==============================
// Version (résultat d'un job)
// ==============================
export interface UserStoryVersion {
  id: string;
  user_story_id: string;
  job_id?: string | null;

  improved_story: string;
  generated_acceptance_criteria: string[];

  initial_score: number;
  final_score: number;

  iteration: number;
  created_at?: string;

  decision_status: 'pending' | 'approved' | 'rejected';
}

// ==============================
// Job (une exécution du pipeline)
// ==============================
export type JobStatus = 'processing' | 'completed' | 'failed';

export interface Job {
  job_id: string;
  issue_key: string;
  user_story_id?: string;
  status: JobStatus;
  phase?: 'analyzing' | 'refining' | 'evaluating' | 'completed';
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
  // Job
  job?: {
    job_id: string;
    issue_key: string;
  };

  jobPhase?: 'analyzing' | 'refining' | 'evaluating' | 'completed';
  jobStatus?: 'processing' | 'completed' | 'failed';

  jobScore?: number;
  jobIteration?: number;

  // Versions
  versions?: UserStoryVersion[];

  // Backend truth
  selected_version?: UserStoryVersion | null;
  latest_version?: UserStoryVersion | null;
  display_version?: UserStoryVersion | null;
}

// ==============================
// Decision
// ==============================
export type DecisionChoice = 'approve' | 'reject_keep' | 'reject_relaunch';

export type DecisionStatus = 'pending' | 'approved' | 'rejected';

// ==============================
// JobState
// ==============================
export interface JobState {
  job_id: string;
  status: JobStatus | 'not_found';
  phase?: 'analyzing' | 'refining' | 'evaluating' | 'completed';
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

  // Version
  version_id?: string;

  decision_status?: DecisionStatus;

  // Trace
  trace?: TraceEntry[];

  has_new_version?: boolean;
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
    generated_acceptance_criteria?: string[];
    version_id?: string;
    error?: string;
    has_new_version?: boolean; 
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