import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CoverageItem {
  label: string;
  value: number;
}

export interface PriorityItem {
  label: string;
  value: number;
  color_class: string;
}

export interface ActivityItem {
  message: string;
  time: string;
  kind: 'test_case' | 'user_story';
}

export interface DashboardStats {
  user_stories_count: number;
  user_stories_this_week: number;
  test_cases_count: number;
  test_cases_this_week: number;
  gherkin_coverage: number;
  quality_score: number;
  scored_stories_count: number;
  projects_count: number;
  has_data: boolean;
  test_type_coverage: CoverageItem[];
  priority_distribution: PriorityItem[];
  recent_activities: ActivityItem[];
}

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly base = 'http://localhost:8000/dashboard';

  constructor(private http: HttpClient) {}

  getStats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${this.base}/stats`);
  }
}
