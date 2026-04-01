import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Project } from '../models';

export interface JiraStatusResponse {
  connected: boolean;
  jira_url?: string;
  jira_email?: string;
}

export interface JiraProject {
  id?: string;
  key: string;
  name: string;
  avatar?: string;
  lead?: string;
  type?: string;
}

export interface ImportStoriesResponse {
  message: string;
  project: {
    key: string;
    name: string;
  };
  result: {
    imported: number;
    skipped: number;
  };
}

@Injectable({ providedIn: 'root' })
export class ProjectsService {
  private http = inject(HttpClient);
  private apiUrl = 'http://127.0.0.1:8000';

  getProjects(): Observable<Project[]> {
    return this.http.get<Project[]>(`${this.apiUrl}/projects/`);
  }

  getJiraStatus(): Observable<JiraStatusResponse> {
    return this.http.get<JiraStatusResponse>(`${this.apiUrl}/jira/status`);
  }

  getJiraProjects(): Observable<JiraProject[]> {
    return this.http.get<JiraProject[]>(`${this.apiUrl}/jira/projects`);
  }

  importStories(projectKey: string): Observable<ImportStoriesResponse> {
    return this.http.post<ImportStoriesResponse>(
      `${this.apiUrl}/projects/${projectKey}/import`,
      {}
    );
  }
}
