import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { UserStory } from '../models';

@Injectable({
  providedIn: 'root'
})
export class StoriesService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/stories`;

  getAllStories(): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(this.apiUrl);
  }

  getStoriesByProject(projectId: string): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(`${this.apiUrl}/project/${projectId}`);
  }
}