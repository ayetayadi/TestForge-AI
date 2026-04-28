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

export interface JiraEpic {
  key: string;
  summary: string;
  status?: string;
}

export interface JiraSprint {
  id: number;
  name: string;
  state: 'active' | 'closed' | 'future';
  start_date?: string;
  end_date?: string;
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
  selected?: boolean;
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

  getEpics(projectKey: string): Observable<JiraEpic[]> {
    return this.http.get<JiraEpic[]>(`${this.apiUrl}/epics/${projectKey}`);
  }

  getSprints(projectKey: string): Observable<JiraSprint[]> {
    return this.http.get<JiraSprint[]>(`${this.apiUrl}/sprints/${projectKey}`);
  }

  getUserStories(projectKey: string): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(`${this.apiUrl}/stories/${projectKey}`);
  }

  disconnect(): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/disconnect`);
  }
}
