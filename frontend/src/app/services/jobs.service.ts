import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { JobState, DecisionChoice } from '../models';

export interface PendingJob {
  job_id: string;
  issue_key: string;
  status: string;
  score_before: number;
  score_after: number;
  delta: number;
  iteration: number;
}

@Injectable({
  providedIn: 'root'
})
export class JobsService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/jobs`;

  getJob(jobId: string): Observable<JobState> {
    return this.http.get<JobState>(`${this.apiUrl}/${jobId}`);
  }

  getStreamUrl(jobId: string): string {
    return `${this.apiUrl}/${jobId}/stream`;
  }

  sendDecision(jobId: string, choice: DecisionChoice): Observable<any> {
    return this.http.post(`${this.apiUrl}/${jobId}/decision`, null, { params: { choice } });
  }

  getPendingJobs(): Observable<Record<string, PendingJob>> {
    return this.http.get<Record<string, PendingJob>>(`${this.apiUrl}/pending`);
  }
}