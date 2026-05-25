import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface TestomatStatus {
  connected: boolean;
  api_key_preview?: string;
  connected_at?: string;
}

export interface PushResult {
  pushed_count: number;
  total_requested: number;
}

@Injectable({ providedIn: 'root' })
export class TestomatService {
  private base = `${environment.apiUrl}/api/testomat`;

  constructor(private http: HttpClient) {}

  getStatus(): Observable<TestomatStatus> {
    return this.http.get<TestomatStatus>(`${this.base}/status`);
  }

  connect(apiKey: string): Observable<TestomatStatus> {
    return this.http.post<TestomatStatus>(`${this.base}/connect`, { api_key: apiKey });
  }

  disconnect(): Observable<{ connected: boolean }> {
    return this.http.delete<{ connected: boolean }>(`${this.base}/disconnect`);
  }

  pushTestCases(testCaseIds: string[]): Observable<PushResult> {
    return this.http.post<PushResult>(`${this.base}/push`, { test_case_ids: testCaseIds });
  }
}
