import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import {switchMap, tap} from 'rxjs/operators';
import { Observable } from 'rxjs';

export interface LoginPayload {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export interface UserRead {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  jira_connected: boolean;
}

export interface ForgotPasswordPayload {
  email: string;
}

export interface ResetPasswordPayload {
  token: string;
  new_password: string;
  confirm_password: string;
}

export interface MessageResponse {
  message: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private apiUrl = 'http://localhost:8000';

  constructor(private http: HttpClient, private router: Router) {}

  login(payload: LoginPayload): Observable<any> {
    return this.http.post<TokenResponse>(`${this.apiUrl}/auth/login`, payload).pipe(
      tap((res) => {
        localStorage.setItem('access_token', res.access_token);
      }),
      switchMap(() => this.getCurrentUser()),
      tap((user) => {
        localStorage.setItem('is_admin', String(user.is_admin));

        if (user.is_admin) {
          this.router.navigate(['/admin-dashboard']);
        } else {
          this.router.navigate(['/user-dashboard']);
        }
      })
    );
  }

  logout(): void {
    localStorage.removeItem('access_token');
    this.router.navigate(['/authentication/login']);
  }

  getToken(): string | null {
    return localStorage.getItem('access_token');
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  forgotPassword(payload: ForgotPasswordPayload): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(
      `${this.apiUrl}/auth/forgot-password`, payload
    );
  }

  resetPassword(payload: ResetPasswordPayload): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(
      `${this.apiUrl}/auth/reset-password`, payload
    );
  }
  getCurrentUser(): Observable<UserRead> {
    return this.http.get<UserRead>(`${this.apiUrl}/users/me`);
  }

}
