import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { RunPipelineRequest, PipelineResponse } from '../models';
@Injectable({
  providedIn: 'root'
})
export class PipelineService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/pipeline`;

  runPipeline(payload: RunPipelineRequest): Observable<PipelineResponse> {
    return this.http.post<PipelineResponse>(`${this.apiUrl}/run`, payload);
  }

  runPipelineByProject(projectId: string): Observable<PipelineResponse> {
    return this.runPipeline({
      project_id: projectId
    });
  }

  runPipelineByKeys(issueKeys: string[]): Observable<PipelineResponse> {
    return this.runPipeline({
      issue_keys: issueKeys
    });
  }
}