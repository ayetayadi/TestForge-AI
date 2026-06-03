import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface CreateUserPayload {
  email: string;
  username: string;
  is_admin: boolean;
}

export interface UserRead {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  jira_connected: boolean;
  created_at?: string;
}

export interface UpdateUserPayload {
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
}

// ── Analytics ───────────────────────────────────────────────────
export interface ProjectMetrics {
  id: string;
  project_key: string;
  project_name: string;
  story_count: number;
  test_case_count: number;
  test_plan_count: number;
  risk_count: number;
}

export interface TesterMetrics {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  jira_connected: boolean;
  project_count: number;
  total_stories: number;
  total_test_cases: number;
  total_test_plans: number;
  total_risks: number;
  projects: ProjectMetrics[];
}

export interface GlobalMetrics {
  total_testers: number;
  total_projects: number;
  total_stories: number;
  total_test_cases: number;
  total_test_plans: number;
  total_risks: number;
}

export interface AdminAnalytics {
  global: GlobalMetrics;
  testers: TesterMetrics[];
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  private apiUrl = `${environment.apiUrl}/admin`;

  constructor(private http: HttpClient) {}

  createUser(payload: CreateUserPayload): Observable<UserRead> {
    return this.http.post<UserRead>(`${this.apiUrl}/users`, payload);
  }

  getUsers(): Observable<UserRead[]> {
    return this.http.get<UserRead[]>(`${this.apiUrl}/users`);
  }

  updateUser(id: string, payload: UpdateUserPayload): Observable<UserRead> {
    return this.http.put<UserRead>(`${this.apiUrl}/users/${id}`, payload);
  }

  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/users/${id}`);
  }

  getAnalytics(): Observable<AdminAnalytics> {
    return this.http.get<AdminAnalytics>(`${this.apiUrl}/analytics`);
  }
}
