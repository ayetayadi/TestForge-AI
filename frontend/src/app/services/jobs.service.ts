import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { JobState, DecisionChoice, ActiveJob, PendingJob, RunningJob } from '../models';

@Injectable({
  providedIn: 'root'
})
export class JobsService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}`;

  // =========================
  // GET JOB STATE
  // =========================
  getJob(jobId: string): Observable<JobState> {
    return this.http.get<JobState>(`${this.apiUrl}/jobs/${jobId}`);
  }

  // =========================
  // GET JOBS BY ISSUE KEYS
  // =========================
  getJobsByIssues(issueKeys: string[]): Observable<Record<string, any>> {
    return this.http.post<Record<string, any>>(
      `${this.apiUrl}/jobs/by-issues`,
      issueKeys
    );
  }

  // =========================
  // DECISION
  // =========================
  sendDecision(
  jobId: string,
  decision: DecisionChoice,
  versionId?: string
): Observable<any> {

  if (!versionId) {
    throw new Error('versionId is required');
  }

  const body = {
    decision,
    version_id: versionId
  };

  return this.http.post(
    `${this.apiUrl}/jobs/${jobId}/decision`,
    body
  );
}
}