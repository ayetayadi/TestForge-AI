import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface ProjectRow {
  project_id: string;
  project_key: string;
  project_name: string;
  stories_count: number;
  refined_count: number;       // US raffinées par IA
  risks_count: number;         // risques analysés
  test_plans_count: number;
  test_suites_count: number;
  test_cases_count: number;
  executions_count: number;
  passed_count: number;
  failed_count: number;
}

export interface DashboardStats {
  projects_count: number;
  stories_count: number;
  refined_count: number;
  risks_count: number;
  test_plans_count: number;
  test_suites_count: number;
  test_cases_count: number;
  executions_count: number;
  passed_count: number;
  failed_count: number;
  has_data: boolean;
  projects: ProjectRow[];
}

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly base = 'http://localhost:8000/dashboard';

  constructor(private http: HttpClient) {}

  getStats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${this.base}/stats`);
  }
}
