import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface JiraStatus {
  connected: boolean;
  jira_url?: string;
  jira_email?: string;
}

export interface JiraProject {
  id: string;
  key: string;
  name: string;
  avatar?: string;
}

export interface UserStory {
  id: string;
  key: string;
  summary: string;
  description: string;
  status: string;
  priority: string;
  assignee: string;
  created: string;
  updated: string;
  selected?: boolean;   // for UI selection
}

@Injectable({ providedIn: 'root' })
export class JiraService {
  private apiUrl = `${environment.apiUrl}/jira`;

  constructor(private http: HttpClient) {}

  getAuthUrl(): Observable<{ url: string }> {
    return this.http.get<{ url: string }>(`${this.apiUrl}/auth-url`);
  }

  getStatus(): Observable<JiraStatus> {
    return this.http.get<JiraStatus>(`${this.apiUrl}/status`);
  }

  getProjects(): Observable<JiraProject[]> {

    return this.http.get<JiraProject[]>(`${this.apiUrl}/projects`);
  }

  getUserStories(projectKey: string): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(`${this.apiUrl}/stories/${projectKey}`);
  }

  disconnect(): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/disconnect`);
  }
}
