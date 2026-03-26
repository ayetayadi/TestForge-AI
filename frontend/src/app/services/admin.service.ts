import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CreateUserPayload {
  email: string;
  username: string;
  password: string;
  is_admin: boolean;
}

export interface UserRead {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  jira_connected: boolean;
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  private apiUrl = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  createUser(payload: CreateUserPayload): Observable<UserRead> {
    return this.http.post<UserRead>(`${this.apiUrl}/admin/users`, payload);
  }

  getUsers(): Observable<UserRead[]> {
    return this.http.get<UserRead[]>(`${this.apiUrl}/admin/users`);
  }

  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/admin/users/${id}`);
  }
}
