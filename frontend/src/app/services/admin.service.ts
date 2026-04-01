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
}

export interface UpdateUserPayload {
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
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

}
