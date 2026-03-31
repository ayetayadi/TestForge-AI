// Project
export interface Project {
  id: string;
  project_key: string;
  name: string;
  story_count: number;
}

export interface ImportResult {
  message: string;
  result: {
    imported: number;
    skipped: number;
  };
}

// User Story
export interface UserStory {
  id: string;
  issue_key: string;
  jira_project_id?: string;
 
  // Contenu
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
 
  // Version
  fix_version?: string;
 
  // Pipeline result
  final?: UserStoryFinal | null;
}

// User Story Final
export interface UserStoryFinal {
  improved_story: string;
  acceptance_criteria: string[] | string;
  score_before: number;
  score_after: number;
  delta: number;
  iteration: number;
  outcome: string;
  human_choice: string;
  job_id: string;
}
 
// Job & Pipeline
export type JobStatus = 'queued' | 'running' | 'awaiting_decision' | 'completed' | 'failed' | 'not_found';
export interface TraceEntry {
  iteration: number;
  score: number;
  feedback?: string;
}

export interface Job {
  job_id: string;
  issue_key: string;
  status: JobStatus;
}

export interface JobState {
  job_id: string;
  jira_id: string;
  iteration: number;
  
  status: JobStatus;

  // Scores
  initial_score: number;
  final_score: number;
  best_score: number;
  delta: number;

  // Stories
  raw_story: string;
  initial_story: string;
  improved_story: string;

  // Acceptance Criteria
  existing_ac?: string[] | string;
  acceptance_criteria?: string[] | string;

  // Trace & Details
  trace: any[];
  llm_score: number;
  rule_score: number;
  nlp_score: number;
  llm_issues: string[];
  llm_suggestions: string[];
  timing: Record<string, number>;

  project_id: string;
  project_name: string;
}
export interface TraceEntry {
  iteration: number;
  score: number;
  feedback?: string;
}

export type DecisionChoice = 'approve' | 'reject_keep' | 'reject_relaunch';

// Pipeline Request
export interface RunByProject {
  type: 'project';
  project_id: string;
}

export interface RunByKeys {
  type: 'keys';
  issue_keys: string[];
}

export type RunPipelineRequest = RunByProject | RunByKeys;

export interface PipelineResponse {
  status: string;
  jobs: Job[];
}

// SSE Events
export type SSEEventType =
  | 'job_started'
  | 'analysis_started'
  | 'analysis_completed'
  | 'refinement_started'
  | 'refinement_completed'
  | 'score_update'
  | 'rescoring'
  | 'skipped'
  | 'job_completed'
  | 'job_failed'
  | 'ping';

export interface SSEEvent {
  type: SSEEventType;
  data?: any;
  timestamp: string;
}

// UI Types
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
}