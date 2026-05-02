import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import {
  TestPlan,
  TestPlanListResponse,
  TestPlanSummary,
  TestPlanUpdate,
  GenerateTestPlanRequest,
  GenerateTestPlanResponse,
  SendEmailRequest,
  GenerateEmailBodyRequest,
  GenerateEmailBodyResponse,
  SendEmailResponse,
  JiraNotificationRequest,
  JiraNotificationResponse,
} from '../models/test-plan.model';

@Injectable({ providedIn: 'root' })
export class TestPlanService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/test-plans`;

  // ============================================================
  // AI GENERATION
  // ============================================================

  generate(request: GenerateTestPlanRequest): Observable<GenerateTestPlanResponse> {
    return this.http.post<GenerateTestPlanResponse>(`${this.baseUrl}/generate`, request);
  }

  regenerate(planId: string): Observable<GenerateTestPlanResponse> {
    return this.http.post<GenerateTestPlanResponse>(
      `${this.baseUrl}/${planId}/regenerate`,
      {}
    );
  }

  // ============================================================
  // CRUD
  // ============================================================

  getById(planId: string): Observable<TestPlan> {
    return this.http.get<TestPlan>(`${this.baseUrl}/${planId}`);
  }

  /**
   * Récupère les Test Plans d'un projet avec filtres optionnels
   */
  getByProject(
    projectId: string,
    options?: {
      sprintIds?: string[];
      epicKeys?: string[];
      page?: number;
      pageSize?: number;
    },
  ): Observable<TestPlanListResponse> {
    let params = new HttpParams()
      .set('page', (options?.page || 1).toString())
      .set('page_size', (options?.pageSize || 20).toString());

    if (options?.sprintIds?.length) {
      params = params.set('sprint_ids', options.sprintIds.join(','));
    }
    if (options?.epicKeys?.length) {
      params = params.set('epic_keys', options.epicKeys.join(','));
    }

    return this.http.get<TestPlanListResponse>(
      `${this.baseUrl}/project/${projectId}`,
      { params },
    );
  }

  /**
   * Récupère TOUS les Test Plans avec filtres optionnels
   */
  getAll(options?: {
    projectId?: string;
    status?: string;
    page?: number;
    pageSize?: number;
  }): Observable<TestPlanListResponse> {
    let params = new HttpParams()
      .set('page', (options?.page || 1).toString())
      .set('page_size', (options?.pageSize || 20).toString());

    if (options?.projectId) {
      params = params.set('project_id', options.projectId);
    }
    if (options?.status) {
      params = params.set('status', options.status);
    }

    return this.http.get<TestPlanListResponse>(`${this.baseUrl}/all`, { params });
  }

  getSummaryByProject(projectId: string): Observable<TestPlanSummary> {
    return this.http.get<TestPlanSummary>(
      `${this.baseUrl}/project/${projectId}/summary`,
    );
  }

  update(planId: string, data: TestPlanUpdate): Observable<TestPlan> {
    return this.http.put<TestPlan>(`${this.baseUrl}/${planId}`, data);
  }

  delete(planId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${planId}`);
  }

  /**
   * Supprime TOUS les Test Plans d'un projet
   */
  deleteByProject(projectId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/project/${projectId}`);
  }

  // ============================================================
  // APPROVAL WORKFLOW
  // ============================================================

  approve(planId: string): Observable<TestPlan> {
    return this.http.post<TestPlan>(`${this.baseUrl}/${planId}/approve`, {});
  }

  reject(planId: string): Observable<TestPlan> {
    return this.http.post<TestPlan>(`${this.baseUrl}/${planId}/reject`, {});
  }

  // ============================================================
  // EXPORT
  // ============================================================

  exportPdf(planId: string): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/${planId}/export/pdf`, {
      responseType: 'blob',
    });
  }

  exportDocx(planId: string): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/${planId}/export/docx`, {
      responseType: 'blob',
    });
  }

  downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ============================================================
  // EMAIL SHARING
  // ============================================================

  generateEmailBody(
    planId: string,
    request: GenerateEmailBodyRequest,
  ): Observable<GenerateEmailBodyResponse> {
    return this.http.post<GenerateEmailBodyResponse>(
      `${this.baseUrl}/${planId}/email/generate-body`,
      request,
    );
  }

  sendEmail(
    planId: string,
    request: SendEmailRequest,
  ): Observable<SendEmailResponse> {
    return this.http.post<SendEmailResponse>(
      `${this.baseUrl}/${planId}/email/send`,
      request,
    );
  }

  // ============================================================
  // JIRA NOTIFICATION
  // ============================================================

  sendJiraNotification(
    planId: string,
    request: JiraNotificationRequest,
  ): Observable<JiraNotificationResponse> {
    return this.http.post<JiraNotificationResponse>(
      `${this.baseUrl}/${planId}/jira/notify`,
      request,
    );
  }
}