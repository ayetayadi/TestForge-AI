import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import { 
  TestSuiteListResponse, 
  TestSuiteDetail, 
  GenerateTestSuitesRequest, 
  GenerateTestSuitesResponse,
  UpdateTestSuiteRequest,
  TraceabilityMatrix,
  DependencyGraph
} from '../models/test-suite.model';

@Injectable({ providedIn: 'root' })
export class TestSuiteService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/test-suites`;

  /**
   * Récupère toutes les suites de test avec filtres optionnels
   */
  getAll(filters?: {
    plan_id?: string;
    project_id?: string;
    suite_type?: string;
    status?: string;
  }): Observable<TestSuiteListResponse> {
    let params = new HttpParams();
    if (filters?.plan_id)     params = params.set('plan_id', filters.plan_id);
    if (filters?.project_id)  params = params.set('project_id', filters.project_id);
    if (filters?.suite_type)  params = params.set('suite_type', filters.suite_type);
    if (filters?.status)      params = params.set('status', filters.status);
    return this.http.get<TestSuiteListResponse>(this.baseUrl, { params });
  }

  /**
   * Récupère le détail complet d'une suite (avec matrice, graphe, risques)
   */
  getById(suiteId: string): Observable<TestSuiteDetail> {
    return this.http.get<TestSuiteDetail>(`${this.baseUrl}/${suiteId}`);
  }

  /**
   * Génère des suites de test via l'IA
   */
  generate(req: GenerateTestSuitesRequest): Observable<GenerateTestSuitesResponse> {
    return this.http.post<GenerateTestSuitesResponse>(
      `${this.baseUrl}/generate`, req
    );
  }

  /**
   * Assigne un test case à une suite
   */
  assignTestCase(suiteId: string, testCaseId: string): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      `${this.baseUrl}/${suiteId}/assign`, 
      { test_case_id: testCaseId, suite_id: suiteId }
    );
  }

  /**
   * Désassigne un test case de sa suite
   */
  unassignTestCase(suiteId: string, testCaseId: string): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      `${this.baseUrl}/${suiteId}/unassign`, 
      { test_case_id: testCaseId }
    );
  }

  /**
   * Met à jour une suite de test
   */
  update(suiteId: string, data: UpdateTestSuiteRequest): Observable<TestSuiteDetail> {
    return this.http.put<TestSuiteDetail>(
      `${this.baseUrl}/${suiteId}`, data
    );
  }

  /**
   * Supprime une suite de test (les TCs deviennent orphelins)
   */
  delete(suiteId: string): Observable<{ status: string; message: string }> {
    return this.http.delete<{ status: string; message: string }>(
      `${this.baseUrl}/${suiteId}`
    );
  }

  /**
   * Récupère la matrice de traçabilité pour un plan
   */
  getTraceabilityMatrix(planId: string): Observable<TraceabilityMatrix> {
    return this.http.get<TraceabilityMatrix>(
      `${this.baseUrl}/traceability/${planId}`
    );
  }

  /**
   * Récupère le graphe de dépendances pour un plan
   */
  getDependencyGraph(planId: string): Observable<DependencyGraph> {
    return this.http.get<DependencyGraph>(
      `${this.baseUrl}/dependencies/${planId}`
    );
  }
}