// services/test-case.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import {
  TestCase,
  TestCaseUI,
  toTestCaseUI,
  Priority,
  TestCaseStatus
} from '../models/test-case.model';

// ─── Generation response shapes ──────────────────────────────────────────────

// 🆕 SIMPLIFIÉ : Pas de coverage dans TestCase
export interface WorkflowGenerationResponse {
  count: number;
  test_plan_id: string;
  test_suite_id: string | null;
  workflow_status: 'success' | 'error';
  feature_gherkin: string;
  test_cases: TestCase[];
  error?: string;
}

export interface AsyncJobResponse {
  job_id: string;
  test_plan_id: string;
  test_suite_id: string | null;
  status: string;
}

export interface WorkflowGenerationOptions {
  test_suite_id?: string;
  scenario_types?: string[];
  risk_level?: 'critical' | 'high' | 'medium' | 'low';
  risk_score?: number;
  risk_description?: string;
}

// SSE Event types for async generation
export interface TcGenerationEvent {
  event: 'tc_processing' | 'tc_generated' | 'tc_failed' | 'ping';
  data: {
    test_plan_id?: string;
    test_suite_id?: string | null;
    count?: number;
    total?: number;
    test_cases?: TestCase[];
    error?: string;
    message?: string;
  };
}

@Injectable({ providedIn: 'root' })
export class TestCaseService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/test-cases`;

  // ============================================================
  // READ (CRUD)
  // ============================================================

  getTestCases(filters?: {
    test_suite_id?: string;
    test_plan_id?: string;
    project_id?: string;
    search?: string;
    status?: TestCaseStatus[];
    priority?: Priority[];
    tags?: string[];
    order_by?: string;
    order_direction?: string;
    limit?: number;
    offset?: number;
  }): Observable<TestCase[]> {
    let params = new HttpParams();

    if (filters) {
      if (filters.test_suite_id) params = params.set('test_suite_id', filters.test_suite_id);
      if (filters.test_plan_id) params = params.set('test_plan_id', filters.test_plan_id);
      if (filters.project_id) params = params.set('project_id', filters.project_id);
      if (filters.search) params = params.set('search', filters.search);
      if (filters.order_by) params = params.set('order_by', filters.order_by);
      if (filters.order_direction) params = params.set('order_direction', filters.order_direction);
      if (filters.limit) params = params.set('limit', filters.limit.toString());
      if (filters.offset) params = params.set('offset', filters.offset.toString());

      if (filters.status?.length) {
        filters.status.forEach(s => { params = params.append('status', s); });
      }
      if (filters.priority?.length) {
        filters.priority.forEach(p => { params = params.append('priority', p); });
      }
      if (filters.tags?.length) {
        filters.tags.forEach(t => { params = params.append('tags', t); });
      }
    }

    return this.http.get<TestCase[]>(this.apiUrl, { params });
  }

  getTestCaseById(id: string): Observable<TestCase> {
    return this.http.get<TestCase>(`${this.apiUrl}/${id}`);
  }

  getTestCaseByCode(tcCode: string): Observable<TestCase> {
    return this.http.get<TestCase>(`${this.apiUrl}/by-code/${tcCode}`);
  }

  getTestCasesBySuite(testSuiteId: string): Observable<TestCase[]> {
    return this.http.get<TestCase[]>(`${this.apiUrl}/suite/${testSuiteId}`);
  }

  getTestCasesByPlan(testPlanId: string): Observable<TestCase[]> {
    return this.http.get<TestCase[]>(`${this.apiUrl}/plan/${testPlanId}`);
  }

  // ============================================================
  // WRITE (CRUD)
  // ============================================================

  createTestCase(data: any): Observable<TestCase> {
    return this.http.post<TestCase>(this.apiUrl, data);
  }

  updateTestCase(id: string, data: any): Observable<TestCase> {
    return this.http.put<TestCase>(`${this.apiUrl}/${id}`, data);
  }

  deleteTestCase(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }

  // ============================================================
  // AI GENERATION (ISTQB workflow pipeline)
  // ============================================================

  /**
   * Synchronous: generates TCs for a TestPlan.
   * POST /test-cases/generate/{testPlanId}?test_suite_id=...
   * 
   * Returns test cases WITHOUT coverage (coverage is in TestSuite).
   */
  generateWorkflow(
    testPlanId: string,
    opts: WorkflowGenerationOptions = {}
  ): Observable<WorkflowGenerationResponse> {
    let params = new HttpParams();
    if (opts.test_suite_id) params = params.set('test_suite_id', opts.test_suite_id);
    if (opts.risk_level) params = params.set('risk_level', opts.risk_level);
    if (opts.risk_score != null) params = params.set('risk_score', String(opts.risk_score));
    if (opts.risk_description) params = params.set('risk_description', opts.risk_description);

    return this.http.post<WorkflowGenerationResponse>(
      `${this.apiUrl}/generate/${testPlanId}`,
      null,
      { params }
    );
  }

  /**
   * Asynchronous: enqueues a TC generation job handled by the backend worker.
   * POST /test-cases/generate/{testPlanId}/async?test_suite_id=...
   */
  generateAsync(
    testPlanId: string,
    opts: WorkflowGenerationOptions = {}
  ): Observable<AsyncJobResponse> {
    let params = new HttpParams();
    if (opts.test_suite_id) params = params.set('test_suite_id', opts.test_suite_id);
    if (opts.scenario_types?.length) params = params.set('scenario_types', opts.scenario_types.join(','));
    if (opts.risk_level) params = params.set('risk_level', opts.risk_level);
    if (opts.risk_score != null) params = params.set('risk_score', String(opts.risk_score));
    if (opts.risk_description) params = params.set('risk_description', opts.risk_description);

    return this.http.post<AsyncJobResponse>(
      `${this.apiUrl}/generate/${testPlanId}/async`,
      null,
      { params }
    );
  }

  /**
   * URL of the SSE stream for a TC generation job.
   * GET /test-cases/generate/stream/{jobId}
   */
  getStreamUrl(jobId: string): string {
    return `${this.apiUrl}/generate/stream/${jobId}`;
  }

  /**
   * Creates an EventSource for SSE stream to receive real-time generation events.
   */
  createEventSource(jobId: string): EventSource {
    return new EventSource(this.getStreamUrl(jobId));
  }

  // ============================================================
  // UTILITIES
  // ============================================================

  toUI(testCase: TestCase, extra?: Partial<TestCaseUI>): TestCaseUI {
    return toTestCaseUI(testCase, extra);
  }

  toUIList(testCases: TestCase[], extras?: Map<string, Partial<TestCaseUI>>): TestCaseUI[] {
    return testCases.map(tc => this.toUI(tc, extras?.get(tc.id)));
  }

  extractPriorityFromTags(tags: string[] | null): Priority {
    if (!tags) return Priority.MEDIUM;
    if (tags.includes('critical')) return Priority.CRITICAL;
    if (tags.includes('high')) return Priority.HIGH;
    if (tags.includes('low')) return Priority.LOW;
    return Priority.MEDIUM;
  }

  extractScenarioPreview(gherkinSource: string | null, maxLength = 100): string | null {
    if (!gherkinSource) return null;
    for (const line of gherkinSource.split('\n')) {
      const trimmed = line.trim();
      if (trimmed.startsWith('Scenario:') || trimmed.startsWith('Feature:')) {
        let preview = trimmed.replace(/^(Scenario:|Feature:)/, '').trim();
        if (preview.length > maxLength) preview = preview.substring(0, maxLength) + '...';
        return preview;
      }
    }
    return null;
  }
}