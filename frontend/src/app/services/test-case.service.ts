// services/test-case.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { environment } from 'src/environments/environment';
import { 
  TestCase, 
  TestCaseUI, 
  TestCaseFilters, 
  TestCaseFormData,
  PaginatedQueryParams,
  toTestCaseUI,
  Priority,
  TestCaseStatus
} from '../models/test-case.model';

@Injectable({ providedIn: 'root' })
export class TestCaseService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/test-cases`;

  /**
   * Récupère tous les test cases avec filtres
   */
  getTestCases(filters?: {
    project_id?: string;
    search?: string;
    status?: TestCaseStatus[];
    priority?: Priority[];
    tags?: string[];
    hasScript?: boolean;
  }): Observable<TestCase[]> {
    let params = new HttpParams();
    
    if (filters) {
      if (filters.project_id) params = params.set('project_id', filters.project_id);
      if (filters.search) params = params.set('search', filters.search);
      if (filters.hasScript !== undefined) params = params.set('has_script', filters.hasScript.toString());
      
      // Pour les tableaux, on les envoie plusieurs fois
      if (filters.status && filters.status.length > 0) {
        filters.status.forEach(status => {
          params = params.append('status', status);
        });
      }
      
      if (filters.priority && filters.priority.length > 0) {
        filters.priority.forEach(priority => {
          params = params.append('priority', priority);
        });
      }
      
      if (filters.tags && filters.tags.length > 0) {
        filters.tags.forEach(tag => {
          params = params.append('tags', tag);
        });
      }
    }
    
    // Le backend retourne directement un tableau, pas un objet avec pagination
    return this.http.get<TestCase[]>(this.apiUrl, { params });
  }

  /**
   * Récupère un test case par ID (GET /test-cases/{id})
   */
  getTestCaseById(id: string): Observable<TestCase> {
    return this.http.get<TestCase>(`${this.apiUrl}/${id}`);
  }

  /**
   * Récupère un test case par code (GET /test-cases/by-code/{tcCode})
   */
  getTestCaseByCode(tcCode: string): Observable<TestCase> {
    return this.http.get<TestCase>(`${this.apiUrl}/by-code/${tcCode}`);
  }

  /**
   * Récupère tous les test cases d'une user story (GET /test-cases/user-story/{userStoryId})
   */
  getTestCasesByUserStory(userStoryId: string): Observable<TestCase[]> {
    return this.http.get<TestCase[]>(`${this.apiUrl}/user-story/${userStoryId}`);
  }

  /**
   * Crée un test case (POST /test-cases)
   */
  createTestCase(data: TestCaseFormData): Observable<TestCase> {
    return this.http.post<TestCase>(this.apiUrl, data);
  }

  /**
   * Met à jour un test case (PUT /test-cases/{id})
   */
  updateTestCase(id: string, data: Partial<TestCaseFormData>): Observable<TestCase> {
    return this.http.put<TestCase>(`${this.apiUrl}/${id}`, data);
  }

  /**
   * Supprime (soft delete) un test case (DELETE /test-cases/{id})
   */
  deleteTestCase(id: string): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.apiUrl}/${id}`);
  }

  // ============================================================
  // MÉTHODES UTILITAIRES
  // ============================================================

  /**
   * Convertit un TestCase backend en TestCaseUI pour l'affichage
   */
  toUI(testCase: TestCase, extra?: Partial<TestCaseUI>): TestCaseUI {
    return toTestCaseUI(testCase, extra);
  }

  /**
   * Convertit une liste de TestCase en TestCaseUI
   */
  toUIList(testCases: TestCase[], extras?: Map<string, Partial<TestCaseUI>>): TestCaseUI[] {
    return testCases.map(tc => {
      const extra = extras?.get(tc.id);
      return this.toUI(tc, extra);
    });
  }

  /**
   * Extrait la priorité des tags
   */
  extractPriorityFromTags(tags: string[] | null): Priority {
    if (!tags) return Priority.MEDIUM;
    if (tags.includes('critical')) return Priority.CRITICAL;
    if (tags.includes('high')) return Priority.HIGH;
    if (tags.includes('low')) return Priority.LOW;
    return Priority.MEDIUM;
  }

  /**
   * Extrait le module du code TC (TC-AUTH-001 → AUTH)
   */
  extractModuleFromTcCode(tcCode: string): string | null {
    const match = tcCode.match(/TC-([A-Z]+)-\d+/);
    return match ? match[1] : null;
  }

  /**
   * Extrait un aperçu du scénario depuis gherkin_source
   */
  extractScenarioPreview(gherkinSource: string | null, maxLength: number = 100): string | null {
    if (!gherkinSource) return null;
    
    const lines = gherkinSource.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('Scenario:') || trimmed.startsWith('Feature:')) {
        let preview = trimmed.replace(/^(Scenario:|Feature:)/, '').trim();
        if (preview.length > maxLength) {
          preview = preview.substring(0, maxLength) + '...';
        }
        return preview;
      }
    }
    return null;
  }

  /**
   * Génère un code TC unique basé sur le module
   */
  generateTcCode(module: string, existingCodes: string[]): string {
    const prefix = `TC-${module.toUpperCase()}`;
    const existingNumbers = existingCodes
      .filter(code => code.startsWith(prefix))
      .map(code => {
        const match = code.match(/TC-[A-Z]+-(\d+)/);
        return match ? parseInt(match[1], 10) : 0;
      });
    
    const nextNumber = Math.max(0, ...existingNumbers) + 1;
    return `${prefix}-${nextNumber.toString().padStart(3, '0')}`;
  }

  /**
   * Valide un code TC
   */
  isValidTcCode(tcCode: string): boolean {
    return /^TC-[A-Z]+-\d{3}$/.test(tcCode);
  }
}