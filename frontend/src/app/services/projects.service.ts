import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Project, ImportResult } from '../models';

export interface JiraProject {
  key: string;
  name: string;
  lead?: string;
  type?: string;
}

@Injectable({
  providedIn: 'root',
})
export class ProjectsService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/projects`;

  getProjects(): Observable<Project[]> {
    return this.http.get<Project[]>(this.apiUrl);
  }

  getJiraProjects(): Observable<JiraProject[]> {
    return this.http.get<JiraProject[]>(`${this.apiUrl}/jira`);
  }

  importStories(projectKey: string): Observable<ImportResult> {
    return this.http.post<ImportResult>(`${this.apiUrl}/${projectKey}/import`, {});
  }
}