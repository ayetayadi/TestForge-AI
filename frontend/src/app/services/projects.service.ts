import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Project } from '../models';
import { environment } from 'src/environments/environment';

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
  private apiUrl = `${environment.apiUrl}/projects`;

  getProjects(): Observable<Project[]> {
    return this.http.get<Project[]>(`${this.apiUrl}`);
  }

  importStories(projectKey: string): Observable<ImportStoriesResponse> {
    return this.http.post<ImportStoriesResponse>(
      `${this.apiUrl}/${projectKey}/import`,
      {}
    );
  }
}
