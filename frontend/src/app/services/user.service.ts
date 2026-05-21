import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';

export interface ProfileRead {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  jira_connected: boolean;
}

export interface ProfileUpdate {
  username: string;
  email: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface MessageResponse {
  message: string;
}

@Injectable({ providedIn: 'root' })
export class UserService {
  private apiUrl = `${environment.apiUrl}/users`;

  private profileSubject = new BehaviorSubject<ProfileRead | null>(null);
  profile$ = this.profileSubject.asObservable();

  get currentProfile() { return this.profileSubject.value; }

  constructor(private http: HttpClient) {}

  getMyProfile(): Observable<ProfileRead> {
    return this.http.get<ProfileRead>(`${this.apiUrl}/me`).pipe(
      tap(p => this.profileSubject.next(p))
    );
  }

  updateProfile(payload: ProfileUpdate): Observable<ProfileRead> {
    return this.http.patch<ProfileRead>(`${this.apiUrl}/me`, payload).pipe(
      tap(p => this.profileSubject.next(p))
    );
  }

  changePassword(payload: ChangePasswordRequest): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(
        `${this.apiUrl}/change-password`,
        payload
    );
  }
}
