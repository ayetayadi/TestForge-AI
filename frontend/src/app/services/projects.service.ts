import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Project } from '../models/user_story.model';
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
    total: number;
  };
}

@Injectable({ providedIn: 'root' })
export class ProjectsService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/projects`;

  getProjects(): Observable<Project[]> {
    return this.http.get<Project[]>(this.apiUrl);
  }

importStories(
  projectKey: string,
  epicKey?: string | null,
  sprintName?: string | null,
  useOr?: boolean
): Observable<ImportStoriesResponse> {
  let params = new HttpParams();
  
  if (epicKey) params = params.set('epic_key', epicKey);
  if (sprintName) params = params.set('sprint_name', sprintName);
  if (useOr) params = params.set('use_or', 'true');
  
  return this.http.post<ImportStoriesResponse>(
    `${this.apiUrl}/${projectKey}/import`,
    {},
    { params }
  );
}

  deleteProject(projectId: string) {
  return this.http.delete<void>(`${this.apiUrl}/${projectId}`);
}
}
