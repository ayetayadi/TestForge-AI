import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { switchMap, tap, catchError, map, filter, take } from 'rxjs/operators';
import { Observable, BehaviorSubject, throwError, of } from 'rxjs';
import { timeout } from 'rxjs/operators';
import { jwtDecode } from 'jwt-decode';
import { environment } from 'src/environments/environment';
import { UserService } from './user.service';

export interface LoginPayload {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  must_change_password?: boolean;
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
  private apiUrl = `${environment.apiUrl}/auth`;
  private isRefreshing = false;
  private refreshTokenSubject = new BehaviorSubject<string | null>(null);

  constructor(
    private http: HttpClient, 
    private router: Router, 
    private userService: UserService
  ) {}

  login(payload: LoginPayload): Observable<any> {
    return this.http.post<TokenResponse>(`${this.apiUrl}/login`, payload, {
      withCredentials: true
    }).pipe(
      tap((res) => {
        this.setAccessToken(res.access_token);
      }),
      switchMap(() => this.userService.getMyProfile()),
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

  refreshToken(): Observable<string> {
    if (this.isRefreshing) {
      return this.refreshTokenSubject.pipe(
        filter(token => token !== null),
        take(1)
      );
    }

    this.isRefreshing = true;
    this.refreshTokenSubject.next(null);

    return this.http.post<TokenResponse>(
      `${this.apiUrl}/refresh`, 
      {},
      { withCredentials: true }
    ).pipe(
      timeout(5000),
      // ⚠️ ATTENTION: L'ordre est important !
      map((res: TokenResponse) => {
        this.setAccessToken(res.access_token);
        this.refreshTokenSubject.next(res.access_token);
        this.isRefreshing = false;
        return res.access_token;  // ← retourne la string
      }),
      catchError((error) => {
        this.isRefreshing = false;
        this.refreshTokenSubject.next(null);
        return throwError(() => error);
      })
    );
  }

  logout(): void {
    this.http.post(`${this.apiUrl}/logout`, {}, { withCredentials: true }).subscribe({
      next: () => {
        this.clearLocalData();
        this.router.navigate(['/authentication/login']);
      },
      error: () => {
        this.clearLocalData();
        this.router.navigate(['/authentication/login']);
      }
    });
  }

  private clearLocalData(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('is_admin');
  }

  getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  }

  getIsAdmin(): boolean {
    return localStorage.getItem('is_admin') === 'true';
  }

  isLoggedIn(): boolean {
    const token = this.getAccessToken();
    if (!token) return false;

    try {
      const decoded: any = jwtDecode(token);
      const now = Math.floor(Date.now() / 1000);
      if (decoded.exp && decoded.exp < now) {
        this.clearLocalData();
        return false;
      }
      return true;
    } catch {
      this.clearLocalData();
      return false;
    }
  }

  private setAccessToken(token: string): void {
    localStorage.setItem('access_token', token);
  }

  tryAutoLogin(): Observable<boolean> {
    if (this.isLoggedIn()) {
      return of(true);
    }

    return this.http.post<TokenResponse>(
      `${this.apiUrl}/refresh`,
      {},
      { withCredentials: true }
    ).pipe(
      map((res: TokenResponse) => {
        this.setAccessToken(res.access_token);
        try {
          const decoded: any = jwtDecode(res.access_token);
          localStorage.setItem('is_admin', String(decoded.is_admin ?? false));
        } catch {}
        return true;
      }),
      catchError(() => of(false))
    );
  }

  forgotPassword(payload: ForgotPasswordPayload): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(`${this.apiUrl}/forgot-password`, payload);
  }

  resetPassword(payload: ResetPasswordPayload): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(`${this.apiUrl}/reset-password`, payload);
  }
}