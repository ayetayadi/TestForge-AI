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

// ============================================
// INTERFACES POUR LES NOUVEAUX CHAMPS
// ============================================

export interface ApprovedVersion {
  id: string;
  version_number: number;
  decision_status: string;
  improved_story: string;
  final_score: number | null;
  testability_score: number | null;
  is_testable: boolean | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface StoryDetails {
  source: 'original' | 'approved' | null;
  version_number: number | null;
  story_text: string | null;
  acceptance_criteria: string[];
  has_approved_version: boolean;
  approved_version: ApprovedVersion | null;
}

export interface RiskInfo {
  id: string;
  description: string;
  mitigation: string | null;
  probability: number;
  impact: number;
  risk_score: number;
  level: 'critical' | 'high' | 'medium' | 'low';
  is_accepted: boolean | null;
  is_ai_generated: boolean;
  source: string | null;
  source_story_text: string | null;
  created_at: string | null;
}

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

// ✅ Interface alignée avec le backend (MISE À JOUR)
export interface TestCase {
  id: string;
  tc_code: string;
  title: string;
  description: string | null;
  priority: string | null;
  test_type: string | null;
  
  // Suite & Plan
  test_suite_id: string | null;     
  test_suite_title: string | null;
  test_plan_id: string | null;
  test_plan_title: string | null;
  project_id: string | null;
  
  // ✅ NOUVEAUX CHAMPS - Story & Risks
  story_details: StoryDetails | null;
  risks: RiskInfo[] | null;
  risks_count: number | null;
  
  // Contenu structuré
  tags: string[] | null;
  preconditions: string[] | null;
  postconditions: string[] | null;
  steps: TestStep[] | null;
  gherkin_source: string | null;
  test_data: Record<string, any> | null;
  expected_results: string[] | null;
  locators: Locator[] | null;
  execution_order: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  
  // Champs US enrichis côté frontend
  user_story_id?: string | null;
  issue_key?: string | null;
  user_story_title?: string | null;
  sprint?: string | null;
  epic_key?: string | null;
  epic_name?: string | null;
  project_name?: string | null;
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
  
  // Infos Suite & Plan
  testSuiteId?: string | null;
  testSuiteTitle?: string | null;
  testPlanId?: string | null;
  testPlanTitle?: string | null;
  
  // Infos Projet
  projectId?: string | null;
  
  // ✅ NOUVEAUX CHAMPS UI
  storyDetails?: StoryDetails | null;
  risks?: RiskInfo[] | null;
  risksCount?: number | null;
  
  // Ordre d'exécution
  executionOrder?: number | null;
  
  // Extrait du gherkin
  scenarioPreview?: string | null;
}

// Pour la création/mise à jour
export interface TestCaseFormData {
  tc_code?: string;
  title: string;
  user_story_id: string | null;
  test_suite_id?: string | null;
  description?: string | null;
  test_type?: string | null;
  priority?: string | null;
  gherkin_source?: string | null;
  test_data?: Record<string, any> | null;
  expected_results?: string[];
  tags?: string[];
  steps?: TestStep[];
  preconditions?: string[];
  postconditions?: string[];
  locators?: Locator[];
  execution_order?: number | null;
}

// Pour les requêtes paginées
export interface PaginatedQueryParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: TestCaseStatus[];
  priority?: Priority[];
  tags?: string[];
  test_suite_id?: string;
  test_plan_id?: string;
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
  
  const priorityFromField = testCase.priority 
    ? priorityMap[testCase.priority.toLowerCase()] 
    : null;
  
  const priorityTag = testCase.tags?.find(t => 
    ['critical', 'high', 'medium', 'low'].includes(t.toLowerCase())
  );
  
  const priority = priorityFromField || 
    (priorityTag ? priorityMap[priorityTag.toLowerCase()] : null) || 
    Priority.MEDIUM;
  
  // Extrait preview du scénario Gherkin
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
    description: scenarioPreview || testCase.description,
    status: testCase.is_active ? TestCaseStatus.ACTIVE : TestCaseStatus.ARCHIVED,
    priority: priority,
    tags: testCase.tags,
    hasScript: false,
    createdAt: testCase.created_at,
    updatedAt: testCase.updated_at,
    testSuiteId: testCase.test_suite_id,
    testSuiteTitle: testCase.test_suite_title,
    testPlanId: testCase.test_plan_id,
    testPlanTitle: testCase.test_plan_title,
    projectId: testCase.project_id,
    executionOrder: testCase.execution_order,
    scenarioPreview: scenarioPreview,
    
    // ✅ Nouveaux champs
    storyDetails: testCase.story_details,
    risks: testCase.risks,
    risksCount: testCase.risks_count,
    
    ...extra
  };
}