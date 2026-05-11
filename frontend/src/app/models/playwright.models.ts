export enum ScriptSource {
  V1_DRAFT = "v1_draft",
  V2_CORRECTED = "v2_corrected",
  MANUAL_EDIT = "manual_edit",
  AI_FIX = "ai_fix"
}

export enum ScriptValidationStatus {
  NOT_VALIDATED = "not_validated",
  VALID = "valid",
  INVALID = "invalid",
  DRAFT = "draft"
}

export enum TestRunStatus {
  RUNNING = "running",
  COMPLETED = "completed",
  FAILED = "failed",
  CANCELLED = "cancelled"
}

export enum TestResultStatus {
  PASSED = "passed",
  FAILED = "failed",
  ERROR = "error",
  SKIPPED = "skipped"
}

export enum StepType {
  THINK = "think",
  ACT = "act",
  OBSERVE = "observe"
}

export enum StepStatus {
  SUCCESS = "success",
  FAILED = "failed",
  PENDING = "pending",  
  RUNNING = "running"   
}

export type ExecutionStatus = 'passed' | 'failed' | 'completed' | 'error';

// ============================================================
// REQUEST MODELS
// ============================================================

export interface GenerateScriptRequest {
  test_case_id: string;
  app_url?: string;
}

export interface UpdateScriptRequest {
  script_content: string;
}

export interface UpdateScriptResponse {
  id: string;
  version_number: number;
  source: string;
  is_active: boolean;
  placeholder_count: number;
  validation_status: string;
  created_at: string | null;
}

export interface ExecuteScriptRequest {
  test_case_id: string;
  script_version_id?: string;
  app_url?: string;
  browser?: 'chromium' | 'firefox' | 'webkit';
  headless?: boolean;
}

export interface FullWorkflowRequest {
  test_case_id: string;
  app_url?: string;
  browser?: 'chromium' | 'firefox' | 'webkit';
  headless?: boolean;
}

// ============================================================
// RESPONSE MODELS
// ============================================================

export interface GenerateScriptResponse {
  status: 'generated' | 'error';
  script_v1: string;
  placeholder_count: number;
  model_used: string;
  script_version_id?: string;
  version_number?: number;
  warning?: string;
  error?: string;
}

export interface ExecuteScriptResponse {
  status: string;
  script_v2?: string;
  execution_status?: ExecutionStatus;
  steps_passed: number;
  steps_failed: number;
  remaining_placeholders: number;
  test_run_id?: string;
  script_version_id?: string;
  error?: string;
}

export interface FullWorkflowResponse {
  workflow_status: 'completed' | 'generation_failed' | 'execution_failed';
  generation: {
    status: string;
    placeholder_count: number;
    script_version_id?: string;
  };
  execution: {
    status?: string;
    steps_passed: number;
    steps_failed: number;
    remaining_placeholders: number;
    test_run_id?: string;
    script_version_id?: string;
  };
  summary: {
    total_steps: number;
    passed_steps: number;
    failed_steps: number;
    success_rate: number;
  };
}

export interface ScriptInfo {
  id: string;
  version_number: number;
  source: string;
  is_active: boolean;
  placeholder_count: number;
  validation_status: string;
  created_at: string;
}

export interface ScriptListResponse {
  test_case_id: string;
  active_script_id: string | null;
  scripts: ScriptInfo[];
}

export interface TestStepResult {
  order: number;
  type: StepType;
  content: string;
  tool_name?: string;
  status: StepStatus;
  duration?: number;
  error_message?: string;
  timestamp: string;
}

export interface TestResultDetails {
  id?: string;
  test_run_id?: string;
  status: TestResultStatus | null;
  justification?: string;
  error_message?: string;
  steps_passed?: number;
  steps_failed?: number;
  duration?: number;
  total_steps?: number;
  script_version_id?: string;
  script_v2?: string;
  created_at?: string;
  updated_at?: string;
}

export interface TestRunDetails {
  id: string;
  status: TestRunStatus;
  browser: string;
  headless: boolean;
  started_at: string;
  completed_at: string | null;
  duration?: number;
}

export interface TestRunDetailsResponse {
  test_run: TestRunDetails;
  result: TestResultDetails | null;
  steps: TestStepResult[];
}

export interface LastRunResponse {
  test_run?: TestRunDetails;
  result?: TestResultDetails;
  steps?: TestStepResult[];
  error?: string;
  message?: string;
}

export interface HealthCheckResponse {
  status: string;
  mcp_server_url: string;
  agents: {
    script_generator: string;
    react_agent: string;
  };
}

export interface AsyncStartResponse {
  status: string;
  test_case_id: string;
  message: string;
}

export type PlaywrightSSEEventType =
  | 'generation_started'
  | 'generation_completed'
  | 'generation_failed'
  | 'execution_started'
  | 'agent_step'
  | 'completed'
  | 'failed'
  | 'ping';

export interface PlaywrightSSEEvent {
  type: PlaywrightSSEEventType;
  data: Record<string, any>;
  timestamp: string;
}

// ============================================================
// UI MODELS (pour l'affichage)
// ============================================================

export type ExecutionStepStatus = 'success' | 'failed' | 'pending' | 'running';

export interface ExecutionStep {
  order: number;
  type: 'think' | 'act' | 'observe';
  content: string;
  toolName?: string;
  status: ExecutionStepStatus;
  duration?: number;
  locatorFound?: string;  // Pour l'affichage des locators découverts
  timestamp: Date;
}

export interface DiscoveredLocator {
  placeholder: string;
  selector: string;
  strategy: string;  // data-testid, css, xpath, etc.
  confidence: 'high' | 'medium' | 'low';
}

export interface ScriptVersionUI {
  id: string;
  versionNumber: number;
  isActive: boolean;
  source: string;
  validationStatus: string;
  placeholderCount: number;
  createdAt: Date;
  content?: string;
}