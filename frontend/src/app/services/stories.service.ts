import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { UserStory } from '../models/user_story.model';

@Injectable({
  providedIn: 'root'
})
export class StoriesService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/user-stories`;

  getAllStories(): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(this.apiUrl);
  }

  getStoryById(userStoryId: string): Observable<UserStory> {
    return this.http.get<UserStory>(`${this.apiUrl}/${userStoryId}`);
  }

  getStoriesByProject(projectId: string): Observable<UserStory[]> {
    return this.http.get<UserStory[]>(`${this.apiUrl}/by-project/${projectId}`);
  }

  getStoryByIssueKey(issueKey: string): Observable<UserStory> {
    return this.http.get<UserStory>(`${this.apiUrl}/by-issue-key/${issueKey}`);
  }

  deleteStory(userStoryId: string): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.apiUrl}/${userStoryId}`);
  }
}