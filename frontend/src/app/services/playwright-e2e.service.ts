// services/playwright-e2e.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, BehaviorSubject, Subscription, forkJoin } from 'rxjs';
import { catchError, tap, map, switchMap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';

// Imports corrigés
import {
  GenerateScriptRequest,
  GenerateScriptResponse,
  ExecuteScriptRequest,
  AsyncStartResponse,
  FullWorkflowRequest,
  ScriptListResponse,
  TestRunDetailsResponse,
  LastRunResponse,
  HealthCheckResponse,
  PlaywrightSSEEvent,
  ScriptInfo,
  ScriptVersionUI,
  ExecutionStep,
  DiscoveredLocator,
  UpdateScriptRequest,
  UpdateScriptResponse,
  TestExecutionListResponse,
  TestExecutionDetail,
  TestCaseResultDetail,
} from '../models/playwright.models';

import { SseService } from './sse.service';

export interface ExecutionReport {
  status: 'passed' | 'failed' | 'partial';
  totalSteps: number;
  passedSteps: number;
  failedSteps: number;
  successRate: number;
  duration: number;
  steps: {
    order: number;
    type: string;
    description: string;
    status: 'success' | 'failed';
    error?: string;
    duration: number;
  }[];
  placeholdersResolved: { placeholder: string; value: string }[];
  recommendations: string[];
}

export interface FullExecutionReport {
  tc_result: {
    id: string;
    execution_id: string;
    status: string;
    duration: number | null;
    screenshot_b64: string | null;
    justification: string | null;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
    steps_passed: number;
    steps_failed: number;
  };
  execution: {
    id: string;
    suite_id: string;
    app_url: string;
    browser: string;
    headless: boolean;
    started_at: string | null;
  } | null;
  test_case: {
    id: string;
    tc_code: string;
    title: string;
    description: string | null;
    risk_level: string | null;
    test_type: string | null;
    steps: any[];
    expected_results: string[];
    user_story_id: string | null;
  } | null;
  script_version: {
    id: string;
    version_number: number;
    source: string;
    placeholder_count: number;
  } | null;
  steps: {
    order: number;
    type: string;
    tool_name: string | null;
    content: string;
    status: string;
    duration: number | null;
    screenshot_b64: string | null;
  }[];
  llm_reasoning: string;
  error_summary: string | null;
  defect: {
    id: string;
    title: string;
    description: string | null;
    severity: string;
    status: string;
    reproduction_steps: string[];
    jira_issue_key: string | null;
    jira_project_key: string | null;
    created_at: string | null;
  } | null;
  stats: {
    total_steps: number;
    think_steps: number;
    act_steps: number;
    failed_steps: number;
    success_rate: number;
  };
  generated_at: string;
}

export interface RunHistoryItem {
  id: string;
  status: string;
  browser: string;
  duration: number | null;
  started_at: string | null;
  completed_at: string | null;
  result_status: string | null;
  result_step_count: number;
  script_version_number: number | null;
}

export interface SuiteSmartRunRequest {
  app_url: string;
  browser?: string;
  headless?: boolean;
  stop_on_failure?: boolean;
  model_id?: string;
}

export interface AvailableModel {
  id: string;
  label: string;
  provider: string;
  description: string;
  is_default: boolean;
}

export interface SuiteSSEEvent {
  type: string;
  data: Record<string, any>;
  timestamp: string;
}

export interface SuiteScriptStatus {
  tc_id: string;
  tc_code: string;
  title: string;
  has_script: boolean;
  script_id?: string;
  version_number?: number;
  placeholder_count?: number;
  source?: string;
}

@Injectable({
  providedIn: 'root'
})
export class PlaywrightE2EService {
  
  private http = inject(HttpClient);
  private sseService = inject(SseService);
  
  private apiUrl = `${environment.apiUrl}/playwright`;
  
  // ============================================================
  // Subjects pour la communication temps réel
  // ============================================================
  private executionStepsSubject = new BehaviorSubject<ExecutionStep[]>([]);
  public executionSteps$ = this.executionStepsSubject.asObservable();
  
  private discoveredLocatorsSubject = new BehaviorSubject<DiscoveredLocator[]>([]);
  public discoveredLocators$ = this.discoveredLocatorsSubject.asObservable();
  
  private isExecutingSubject = new BehaviorSubject<boolean>(false);
  public isExecuting$ = this.isExecutingSubject.asObservable();
    
  private readonly PLAYWRIGHT_SSE_EVENTS: string[] = [
    'generation_started', 'generation_completed', 'generation_failed',
    'execution_started', 'agent_step', 'completed', 'failed', 'ping',
  ];

  private activeSseSubscription: Subscription | null = null;
  private activeTestCaseId: string | null = null;

  private currentScriptSubject = new BehaviorSubject<string | null>(null);
  public currentScript$ = this.currentScriptSubject.asObservable();
  
  private scriptV2Subject = new BehaviorSubject<{content: string, versionId: string} | null>(null); // MODIFIER pour inclure l'ID
  public scriptV2$ = this.scriptV2Subject.asObservable();
  
  private executionReportSubject = new BehaviorSubject<ExecutionReport | null>(null);
  public executionReport$ = this.executionReportSubject.asObservable();

  // ============================================================
  // API ENDPOINTS
  // ============================================================
  
  /**
   * Génère un script Playwright v1 (avec placeholders)
   * POST /playwright/generate-script
   */
  generateScript(request: GenerateScriptRequest): Observable<GenerateScriptResponse> {
    return this.http.post<GenerateScriptResponse>(
      `${this.apiUrl}/generate-script`,
      request
    ).pipe(
      tap(response => {
        if (response.status === 'generated') {
          console.log(`✅ Script généré: ${response.placeholder_count} placeholders`);
          this.currentScriptSubject.next(response.script_v1);
        } else {
          console.error(`❌ Génération échouée: ${response.error}`);
        }
      }),
      catchError(this.handleError)
    );
  }
  
  /**
   * Lance l'exécution en arrière-plan et retourne immédiatement.
   * POST /playwright/execute-script
   */
  executeScript(request: ExecuteScriptRequest): Observable<AsyncStartResponse> {
    this.isExecutingSubject.next(true);
    this.executionStepsSubject.next([]);
    this.discoveredLocatorsSubject.next([]);

    return this.http.post<AsyncStartResponse>(
      `${this.apiUrl}/execute-script`,
      request
    ).pipe(
      catchError((error) => {
        this.isExecutingSubject.next(false);
        return this.handleError(error);
      })
    );
  }

  /**
   * Lance le workflow complet (génération + exécution) en arrière-plan.
   * POST /playwright/full-workflow
   */
  runFullWorkflow(request: FullWorkflowRequest): Observable<AsyncStartResponse> {
    this.isExecutingSubject.next(true);
    this.executionStepsSubject.next([]);
    this.discoveredLocatorsSubject.next([]);

    return this.http.post<AsyncStartResponse>(
      `${this.apiUrl}/full-workflow`,
      request
    ).pipe(
      catchError((error) => {
        this.isExecutingSubject.next(false);
        return this.handleError(error);
      })
    );
  }

  /**
   * Lance le workflow ET ouvre le stream SSE en un seul appel.
   */
  runFullWorkflowWithStream(request: FullWorkflowRequest): void {
    this.stopStreaming();

    this.activeTestCaseId = request.test_case_id;
    const url = `${this.apiUrl}/test-case/${request.test_case_id}/stream`;

    this.activeSseSubscription = this.sseService
      .connectToStream<PlaywrightSSEEvent>(url, `playwright_${request.test_case_id}`, this.PLAYWRIGHT_SSE_EVENTS)
      .pipe(tap(event => this.handleSSEEvent(event)))
      .subscribe({
        error: (err) => {
          console.error('SSE error:', err);
          this.isExecutingSubject.next(false);
        },
        complete: () => {
          this.activeSseSubscription = null;
        },
      });

    this.runFullWorkflow(request).subscribe({
      error: (err) => {
        console.error('Workflow error:', err);
        this.isExecutingSubject.next(false);
      }
    });
  }

  /**
   * Exécute un script avec stream SSE
   */
  executeScriptWithStream(request: ExecuteScriptRequest): void {
    this.stopStreaming();

    this.activeTestCaseId = request.test_case_id;
    const url = `${this.apiUrl}/test-case/${request.test_case_id}/stream`;

    this.activeSseSubscription = this.sseService
      .connectToStream<PlaywrightSSEEvent>(url, `playwright_${request.test_case_id}`, this.PLAYWRIGHT_SSE_EVENTS)
      .pipe(tap(event => this.handleSSEEvent(event)))
      .subscribe({
        error: (err) => {
          console.error('SSE error:', err);
          this.isExecutingSubject.next(false);
        },
        complete: () => {
          this.activeSseSubscription = null;
        },
      });

    this.executeScript(request).subscribe({
      error: (err) => {
        console.error('Execution error:', err);
        this.isExecutingSubject.next(false);
      }
    });
  }

  /**
   * Ferme la connexion SSE active.
   */
  stopStreaming(): void {
    if (this.activeSseSubscription) {
      this.activeSseSubscription.unsubscribe();
      this.activeSseSubscription = null;
    }
    if (this.activeTestCaseId) {
      this.sseService.disconnect(`playwright_${this.activeTestCaseId}`);
      this.activeTestCaseId = null;
    }
  }
  
  /**
   * Récupère tous les scripts d'un test case
   * GET /playwright/test-case/{test_case_id}/scripts
   */
  getScripts(testCaseId: string): Observable<ScriptListResponse> {
    return this.http.get<ScriptListResponse>(
      `${this.apiUrl}/test-case/${testCaseId}/scripts`
    ).pipe(
      tap(response => {
        console.log(`📜 ${response.scripts.length} scripts trouvés pour ${testCaseId}`);
      }),
      catchError(this.handleError)
    );
  }

  deleteScript(scriptVersionId: string): Observable<{
    deleted: boolean;
    test_case_id: string;
    was_active: boolean;
    new_active_script_id: string | null;
  }> {
    return this.http.delete<any>(
      `${this.apiUrl}/script/${scriptVersionId}`
    ).pipe(catchError(this.handleError));
  }

  deleteAllScripts(testCaseId: string): Observable<{
    deleted: boolean;
    count: number;
    test_case_id: string;
  }> {
    return this.http.delete<any>(
      `${this.apiUrl}/test-case/${testCaseId}/scripts`
    ).pipe(catchError(this.handleError));
  }
  
  /**
   * Récupère les infos de script simplifiées pour un test case
   */
  getScriptInfo(testCaseId: string): Observable<{ 
    hasScript: boolean; 
    activeScriptId?: string; 
    activeScriptVersion?: number;
    scripts: ScriptInfo[];
  }> {
    return this.getScripts(testCaseId).pipe(
      map(response => ({
        hasScript: response.active_script_id !== null,
        activeScriptId: response.active_script_id || undefined,
        activeScriptVersion: response.scripts.find(s => s.is_active)?.version_number,
        scripts: response.scripts
      }))
    );
  }

  /**
   * Récupère le contenu d'un script spécifique
   * GET /playwright/script/{script_version_id}
   */
  getScriptContent(scriptVersionId: string): Observable<{ content: string }> {
    return this.http.get<{ content: string }>(
      `${this.apiUrl}/script/${scriptVersionId}`
    ).pipe(
      catchError(this.handleError)
    );
  }

  /**
   * Save a manual edit as a new script version.
   * PATCH /playwright/script/{script_version_id}
   */
  updateScript(scriptVersionId: string, scriptContent: string): Observable<UpdateScriptResponse> {
    const body: UpdateScriptRequest = { script_content: scriptContent };
    return this.http.patch<UpdateScriptResponse>(
      `${this.apiUrl}/script/${scriptVersionId}`,
      body
    ).pipe(
      catchError(this.handleError)
    );
  }

  /**
   * Récupère les infos de script pour plusieurs test cases (batch)
   */
  getScriptsInfoBatch(testCaseIds: string[]): Observable<Map<string, { 
    id: string; 
    version: number; 
    lastRun?: { status: string; at: string } 
  }>> {
    if (testCaseIds.length === 0) {
      return new Observable(subscriber => {
        subscriber.next(new Map());
        subscriber.complete();
      });
    }

    const requests = testCaseIds.map(id => 
      this.getScriptInfo(id).pipe(
        map(info => ({ id, info }))
      )
    );
    
    return forkJoin(requests).pipe(
      map(results => {
        const map = new Map();
        results.forEach(({ id, info }) => {
          if (info.hasScript && info.activeScriptId && info.activeScriptVersion) {
            map.set(id, {
              id: info.activeScriptId,
              version: info.activeScriptVersion
            });
          }
        });
        return map;
      })
    );
  }
  
  /**
   * Détails complets d'un TestCaseResult (steps JSON, screenshot, etc.)
   * GET /playwright/tc-result/{tc_result_id}
   */
  getTestRunDetails(tcResultId: string): Observable<any> {
    return this.http.get<any>(
      `${this.apiUrl}/tc-result/${tcResultId}`
    ).pipe(
      catchError(this.handleError)
    );
  }

  /**
   * Dernier TestCaseResult pour un TC (toutes exécutions)
   * GET /playwright/test-case/{test_case_id}/last-result
   */
  getLastRun(testCaseId: string): Observable<LastRunResponse> {
    return this.http.get<LastRunResponse>(
      `${this.apiUrl}/test-case/${testCaseId}/last-result`
    ).pipe(
      catchError(this.handleError)
    );
  }
  
  /**
   * Vérifie l'état du service
   * GET /playwright/health
   */
  healthCheck(): Observable<HealthCheckResponse> {
    return this.http.get<HealthCheckResponse>(
      `${this.apiUrl}/health`
    ).pipe(
      catchError(this.handleError)
    );
  }

  /**
   * Returns the list of LLM models available for script generation and execution.
   * GET /playwright/models
   */
  getAvailableModels(): Observable<{ models: AvailableModel[] }> {
    return this.http.get<{ models: AvailableModel[] }>(
      `${this.apiUrl}/models`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Full report for a failed TC result.
   * GET /playwright/tc-result/{id}/report
   */
  getFullReport(tcResultId: string): Observable<any> {
    return this.http.get<any>(
      `${this.apiUrl}/tc-result/${tcResultId}/report`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Send execution report by email.
   * POST /playwright/tc-result/{id}/send-email
   */
  sendReportEmail(tcResultId: string, recipients: string[]): Observable<{ status: string; recipients: string[] }> {
    return this.http.post<{ status: string; recipients: string[] }>(
      `${this.apiUrl}/tc-result/${tcResultId}/send-email`,
      { recipients }
    ).pipe(catchError(this.handleError));
  }

  /**
   * Create a Jira ticket from a defect.
   * POST /playwright/defect/{defect_id}/create-jira
   */
  createJiraIssue(defectId: string, projectKey: string, priority: string = 'High'): Observable<{ key: string; id: string }> {
    return this.http.post<{ key: string; id: string }>(
      `${this.apiUrl}/defect/${defectId}/create-jira`,
      { defect_id: defectId, project_key: projectKey, priority }
    ).pipe(catchError(this.handleError));
  }

  /**
   * Manually create a defect from a TC result.
   * POST /playwright/tc-result/{id}/create-defect
   */
  createDefectFromRun(tcResultId: string, testCaseId: string): Observable<any> {
    return this.http.post<any>(
      `${this.apiUrl}/tc-result/${tcResultId}/create-defect`,
      { test_case_id: testCaseId }
    ).pipe(catchError(this.handleError));
  }

  /**
   * List all TestExecutions with global stats.
   * GET /playwright/test-executions
   */
  listTestExecutions(options: {
    limit?: number; offset?: number; suiteId?: string; status?: string;
  } = {}): Observable<TestExecutionListResponse> {
    const { limit = 50, offset = 0, suiteId, status } = options;
    let url = `${this.apiUrl}/test-executions?limit=${limit}&offset=${offset}`;
    if (suiteId) url += `&suite_id=${suiteId}`;
    if (status)  url += `&status=${status}`;
    return this.http.get<TestExecutionListResponse>(url).pipe(catchError(this.handleError));
  }

  /**
   * Delete a TestExecution permanently.
   * DELETE /playwright/test-executions/{id}
   */
  deleteExecution(executionId: string): Observable<{ deleted: boolean }> {
    return this.http.delete<{ deleted: boolean }>(
      `${this.apiUrl}/test-executions/${executionId}`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Full detail of a TestExecution with all TCResults + steps.
   * GET /playwright/test-executions/{id}
   */
  getTestExecutionDetail(executionId: string): Observable<TestExecutionDetail> {
    return this.http.get<TestExecutionDetail>(
      `${this.apiUrl}/test-executions/${executionId}`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Download a styled PDF log report for an execution (all steps + reasoning).
   * GET /playwright/test-executions/{id}/export/pdf
   */
  exportExecutionReportPdf(executionId: string): Observable<Blob> {
    return this.http.get(
      `${this.apiUrl}/test-executions/${executionId}/export/pdf`,
      { responseType: 'blob' },
    ).pipe(catchError(this.handleError));
  }

  /**
   * Send a full execution report to the developer (email and/or Jira).
   * POST /playwright/test-executions/{id}/notify-developer
   */
  notifyDeveloper(executionId: string, payload: {
    recipients?: string[];
    method: 'email' | 'jira' | 'both';
    include_passed?: boolean;
    include_steps?: boolean;
    include_screenshots?: boolean;
    jira_project_key?: string;
    jira_priority?: string;
  }): Observable<{
    status: string;
    execution_id: string;
    tc_count: number;
    emails_sent: number;
    jira_issues: string[];
    errors: string[];
    method: string;
  }> {
    return this.http.post<any>(
      `${this.apiUrl}/test-executions/${executionId}/notify-developer`,
      payload,
    ).pipe(catchError(this.handleError));
  }

  /**
   * Close a TestExecution (persisted in DB).
   * POST /playwright/test-executions/{id}/close
   */
  closeExecution(executionId: string): Observable<{ is_closed: boolean; closed_at: string | null }> {
    return this.http.post<any>(
      `${this.apiUrl}/test-executions/${executionId}/close`, {}
    ).pipe(catchError(this.handleError));
  }

  /**
   * Reopen a closed TestExecution.
   * POST /playwright/test-executions/{id}/reopen
   */
  reopenExecution(executionId: string): Observable<{ is_closed: boolean }> {
    return this.http.post<any>(
      `${this.apiUrl}/test-executions/${executionId}/reopen`, {}
    ).pipe(catchError(this.handleError));
  }

  /**
   * History of TC results for a test case.
   * GET /playwright/test-case/{test_case_id}/results
   */
  getRunsForTestCase(testCaseId: string, limit = 20): Observable<{ results: any[]; total: number }> {
    return this.http.get<{ results: any[]; total: number }>(
      `${this.apiUrl}/test-case/${testCaseId}/results?limit=${limit}`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Smart-run for a whole suite (generates + executes each TC).
   * POST /playwright/suite/{suite_id}/execute-smart
   */
  executeSuiteSmart(suiteId: string, request: SuiteSmartRunRequest): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      `${this.apiUrl}/suite/${suiteId}/execute-smart`,
      request
    ).pipe(catchError(this.handleError));
  }

  /**
   * Script status for each TC of a suite.
   * GET /playwright/suite/{suite_id}/scripts-status
   */
  getSuiteScriptsStatus(suiteId: string): Observable<{ suite_id: string; test_cases: SuiteScriptStatus[]; total: number }> {
    return this.http.get<{ suite_id: string; test_cases: SuiteScriptStatus[]; total: number }>(
      `${this.apiUrl}/suite/${suiteId}/scripts-status`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Ouvre le stream SSE pour suivre l'exécution d'une suite
   * GET /playwright/suite/{suite_id}/stream
   */
  connectSuiteStream(suiteId: string): Observable<SuiteSSEEvent> {
    const url = `${this.apiUrl}/suite/${suiteId}/stream`;
    return this.sseService.connectToStream<SuiteSSEEvent>(
      url, `suite_${suiteId}`,
      ['suite_started', 'tc_started', 'tc_event', 'tc_completed', 'completed']
    );
  }
  
  // ============================================================
  // MÉTHODES UTILITAIRES
  // ============================================================
private handleSSEEvent(event: PlaywrightSSEEvent): void {
  const timestamp = new Date(event.timestamp);
  
  switch (event.type) {
    case 'generation_started':
      this.isExecutingSubject.next(true);
      this.addExecutionStep({ 
        order: 0, 
        type: 'think', 
        content: 'Retrieving Playwright TypeScript script...', 
        status: 'running', 
        timestamp 
      });
      break;

    case 'generation_completed':
      this.addExecutionStep({
        order: 1, 
        type: 'observe',
        content: `Script v1 generated — ${event.data['placeholder_count']} placeholders`,
        status: 'success', 
        timestamp,
      });
      break;

    case 'generation_failed':
      this.addExecutionStep({ 
        order: 1, 
        type: 'observe', 
        content: `Generation failed: ${event.data['error']}`, 
        status: 'failed', 
        timestamp 
      });
      this.isExecutingSubject.next(false);
      
      // Ajouter un rapport d'échec
      this.executionReportSubject.next({
        status: 'failed',
        totalSteps: 0,
        passedSteps: 0,
        failedSteps: 1,
        successRate: 0,
        duration: 0,
        steps: [],
        placeholdersResolved: [],
        recommendations: ['Generation failed. Check the error message above.']
      });
      break;

    case 'execution_started':
      this.addExecutionStep({
        order: 2,
        type: 'think',
        content: 'Executing ReAct agent...',
        status: 'running',
        timestamp
      });
      break;

    case 'agent_step': {
      const currentSteps = this.executionStepsSubject.value;
      this.executionStepsSubject.next([...currentSteps, {
        order: currentSteps.length,
        type: (event.data['step_type'] ?? 'act') as 'think' | 'act' | 'observe',
        content: event.data['content'] ?? '',
        toolName: event.data['tool'],
        status: (event.data['status'] ?? 'success') as any,
        timestamp: event.data['timestamp'] ? new Date(event.data['timestamp']) : timestamp,
      }]);
      break;
    }

    case 'completed':
      this.addExecutionStep({
        order: 3, 
        type: 'observe',
        content: `Completed — ${event.data['steps_passed'] || 0} passed / ${event.data['steps_failed'] || 0} failed`,
        status: event.data['execution_status'] === 'passed' ? 'success' : 'failed',
        timestamp,
      });
      this.isExecutingSubject.next(false);
      
      // Émettre le script v2 s'il existe
      if (event.data['script_v2']) {
        this.scriptV2Subject.next({
          content: event.data['script_v2'],
          versionId: event.data['script_v2_id'] || null
        });
      }
      
      // Construire et émettre le rapport d'exécution
      const report = this.buildExecutionReport(event.data);
      this.executionReportSubject.next(report);
      break;

    case 'failed':
      this.addExecutionStep({ 
        order: 3, 
        type: 'observe', 
        content: `Error: ${event.data['error']}`, 
        status: 'failed', 
        timestamp 
      });
      this.isExecutingSubject.next(false);
      
      // Émettre un rapport d'échec
      this.executionReportSubject.next({
        status: 'failed',
        totalSteps: 0,
        passedSteps: 0,
        failedSteps: 1,
        successRate: 0,
        duration: 0,
        steps: [],
        placeholdersResolved: [],
        recommendations: [`Execution failed: ${event.data['error'] || 'Unknown error'}`]
      });
      break;
      
    case 'ping':
      // Heartbeat event - ignore
      break;
  }
}
  /**
   * Convertit les scripts DB en format UI
   */
  convertToScriptVersionUI(scripts: ScriptListResponse): ScriptVersionUI[] {
    return scripts.scripts.map(s => ({
      id: s.id,
      versionNumber: s.version_number,
      isActive: s.is_active,
      source: s.source,
      validationStatus: s.validation_status,
      placeholderCount: s.placeholder_count,
      createdAt: new Date(s.created_at)
    }));
  }
  
  /**
   * Extrait les placeholders d'un script
   */
  extractPlaceholders(scriptContent: string): string[] {
    const regex = /\[TESTFORGEAI:([^\]]+)\]/g;
    const placeholders: string[] = [];
    let match;
    
    while ((match = regex.exec(scriptContent)) !== null) {
      placeholders.push(match[1]);
    }
    
    return [...new Set(placeholders)];
  }
  
  /**
   * Compte les placeholders dans un script
   */
  countPlaceholders(scriptContent: string): number {
    const matches = scriptContent.match(/\[TESTFORGEAI:[^\]]+\]/g);
    return matches ? matches.length : 0;
  }
  
  /**
   * Parse un script pour extraire les steps (affichage UI)
   */
  parseScriptToSteps(scriptContent: string): ExecutionStep[] {
    const steps: ExecutionStep[] = [];
    const lines = scriptContent.split('\n');
    let order = 0;
    
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      
      if (trimmed.includes('await page.goto')) {
        steps.push({
          order: order++,
          type: 'act',
          content: `Navigation: ${trimmed.substring(0, 100)}`,
          status: 'success',
          timestamp: new Date()
        });
      } else if (trimmed.includes('await page.fill')) {
        steps.push({
          order: order++,
          type: 'act',
          content: `Remplir champ: ${trimmed.substring(0, 100)}`,
          status: 'success',
          timestamp: new Date()
        });
      } else if (trimmed.includes('await page.click')) {
        steps.push({
          order: order++,
          type: 'act',
          content: `Cliquer: ${trimmed.substring(0, 100)}`,
          status: 'success',
          timestamp: new Date()
        });
      } else if (trimmed.includes('await page.locator')) {
        steps.push({
          order: order++,
          type: 'act',
          content: `Locator: ${trimmed.substring(0, 100)}`,
          status: 'success',
          timestamp: new Date()
        });
      } else if (trimmed.includes('expect(')) {
        steps.push({
          order: order++,
          type: 'observe',
          content: `Assertion: ${trimmed.substring(0, 100)}`,
          status: 'success',
          timestamp: new Date()
        });
      }
    }
    
    return steps;
  }
  
  /**
   * Ajoute un step d'exécution
   */
  addExecutionStep(step: ExecutionStep): void {
    const currentSteps = this.executionStepsSubject.value;
    this.executionStepsSubject.next([...currentSteps, step]);
  }
  

  /**
 * Construit un rapport d'exécution détaillé
 */
private buildExecutionReport(data: any): ExecutionReport {
  const passedSteps = data.steps_passed || 0;
  const failedSteps = data.steps_failed || 0;
  const totalSteps = passedSteps + failedSteps;
  const executionStatus = data.execution_status;

  let status: 'passed' | 'failed' | 'partial';
  if (executionStatus === 'passed') {
    status = 'passed';
  } else if (executionStatus === 'failed') {
    status = passedSteps > 0 ? 'partial' : 'failed';
  } else {
    status = failedSteps === 0 && passedSteps > 0 ? 'passed' : (passedSteps > 0 ? 'partial' : 'failed');
  }

  return {
    status,
    totalSteps,
    passedSteps,
    failedSteps,
    successRate: totalSteps > 0 ? (passedSteps / totalSteps) * 100 : 0,
    duration: data.duration || 0,
    steps: [],
    placeholdersResolved: data.placeholders_resolved || [],
    recommendations: this.generateRecommendations(passedSteps, failedSteps, data)
  };
}

/**
 * Génère des recommandations basées sur les résultats
 */
private generateRecommendations(passedSteps: number, failedSteps: number, data: any): string[] {
  const recommendations: string[] = [];

  if (failedSteps > 0) {
    recommendations.push(`🔧 Fix ${failedSteps} failed step(s) before re-running`);
  }

  if (passedSteps === 0 && failedSteps === 0) {
    recommendations.push('📝 No steps were executed - check script generation');
  }

  if (data.placeholders_resolved && data.placeholders_resolved.length > 0) {
    recommendations.push(`✅ ${data.placeholders_resolved.length} placeholder(s) resolved successfully`);
  }

  if (data.script_v2) {
    recommendations.push('✨ A corrected script v2 has been generated - check the Script tab');
  }

  return recommendations;
}

/**
 * Réinitialise tous les états (y compris le rapport)
 */
reset(): void {
  this.executionStepsSubject.next([]);
  this.discoveredLocatorsSubject.next([]);
  this.isExecutingSubject.next(false);
  this.currentScriptSubject.next(null);
  this.scriptV2Subject.next(null);
  this.executionReportSubject.next(null);
  this.stopStreaming();
}

  /**
   * Met à jour tous les steps (remplacement)
   */
  setExecutionSteps(steps: ExecutionStep[]): void {
    this.executionStepsSubject.next(steps);
  }
  
  /**
   * Ajoute un locator découvert
   */
  addDiscoveredLocator(locator: DiscoveredLocator): void {
    const currentLocators = this.discoveredLocatorsSubject.value;
    const exists = currentLocators.some(l => l.placeholder === locator.placeholder);
    if (!exists) {
      this.discoveredLocatorsSubject.next([...currentLocators, locator]);
    }
  }

  
  // ============================================================
  // GESTION DES ERREURS
  // ============================================================
  
  private handleError(error: HttpErrorResponse) {
    let errorMessage = 'Une erreur est survenue';
    
    if (error.error instanceof ErrorEvent) {
      errorMessage = `Erreur: ${error.error.message}`;
    } else {
      errorMessage = `Code ${error.status}: ${error.error?.detail || error.message}`;
    }
    
    console.error('PlaywrightE2EService error:', errorMessage);
    
    return throwError(() => new Error(errorMessage));
  }
}