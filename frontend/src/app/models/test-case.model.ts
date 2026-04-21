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

export enum Priority {
  CRITICAL = "critical",
  HIGH = "high",
  MEDIUM = "medium",
  LOW = "low"
}

export enum TestCaseStatus {
  ACTIVE = "active",
  ARCHIVED = "archived"
}

export type ExecutionStatus = 'passed' | 'failed' | 'completed' | 'error';

export interface Locator {
  name: string;
  selector: string;
  reliability: 'high' | 'medium' | 'low';
}

export interface TestStep {
  order: number;
  action: string;
  expected?: string;
}

export interface TestCase {
  id: string;
  tc_code: string;
  title: string;
  description: string | null;
  priority: string | null;
  user_story_id: string | null;
  user_story_version_id: string | null;
  issue_key: string | null;
  user_story_title: string | null;
  project_id: string | null;
  project_name: string | null;
  tags: string[] | null;
  preconditions: string[] | null;
  postconditions: string[] | null;
  steps: TestStep[] | null;
  gherkin_source: string | null;
  test_data: Record<string, any> | null;
  expected_results: string[] | null;
  locators: Locator[] | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// Interface pour l'affichage UI (enrichie)
export interface TestCaseUI {
  id: string;
  tc_code: string;
  title: string;
  description: string | null;
  status: TestCaseStatus;
  priority: Priority;
  tags: string[] | null;
  hasScript: boolean;
  activeScriptId?: string;
  activeScriptVersion?: number;
  lastRunStatus?: TestResultStatus;
  lastRunAt?: string;
  createdAt: string;
  updatedAt: string;
  // Infos User Story
  userStoryId?: string | null;
  userStoryKey?: string | null;
  userStoryTitle?: string | null;
  // Infos Projet
  projectId?: string | null;
  projectName?: string | null;
  // Extrait du gherkin
  scenarioPreview?: string | null;
}

// Pour la création/mise à jour
export interface TestCaseFormData {
  tc_code: string;
  title: string;
  user_story_id?: string | null;
  user_story_version_id?: string | null;
  gherkin_source?: string | null;
  test_data?: Record<string, any> | null;
  expected_results?: string[];
  tags?: string[];
  locators?: Locator[];
}

// Pour les requêtes paginées
export interface PaginatedQueryParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: TestCaseStatus[];
  priority?: Priority[];
  tags?: string[];
  hasScript?: boolean;
  project_id?: string;
}

export interface TestCaseFilters extends PaginatedQueryParams {}

export interface TestCaseListResponse {
  items: TestCaseUI[];
  total: number;
  page: number;
  page_size: number;
}

// Fonction utilitaire pour convertir TestCase → TestCaseUI
export function toTestCaseUI(testCase: TestCase, extra?: Partial<TestCaseUI>): TestCaseUI {
  const priorityMap: Record<string, Priority> = {
    'critical': Priority.CRITICAL,
    'high': Priority.HIGH,
    'medium': Priority.MEDIUM,
    'low': Priority.LOW
  };
  
  const priorityTag = testCase.tags?.find(t => 
    ['critical', 'high', 'medium', 'low'].includes(t)
  );
  
  // Extraire un aperçu du scénario depuis gherkin_source
  let scenarioPreview: string | null = null;
  if (testCase.gherkin_source) {
    const lines = testCase.gherkin_source.split('\n');
    const firstLine = lines.find(line => {
      const trimmed = line.trim();
      return trimmed.startsWith('Scenario:') || trimmed.startsWith('Feature:');
    });
    if (firstLine) {
      scenarioPreview = firstLine.trim().replace(/^(Scenario:|Feature:)/, '').trim();
      if (scenarioPreview.length > 80) {
        scenarioPreview = scenarioPreview.substring(0, 80) + '...';
      }
    }
  }
  
  return {
    id: testCase.id,
    tc_code: testCase.tc_code,
    title: testCase.title,
    description: scenarioPreview,
    status: testCase.is_active ? TestCaseStatus.ACTIVE : TestCaseStatus.ARCHIVED,
    priority: priorityTag ? priorityMap[priorityTag] || Priority.MEDIUM : Priority.MEDIUM,
    tags: testCase.tags,
    hasScript: false,
    createdAt: testCase.created_at,
    updatedAt: testCase.updated_at,
    userStoryId: testCase.user_story_id,
    userStoryKey: testCase.issue_key,
    userStoryTitle: testCase.user_story_title,
    projectId: testCase.project_id,
    projectName: testCase.project_name,
    scenarioPreview: scenarioPreview,
    ...extra
  };
}