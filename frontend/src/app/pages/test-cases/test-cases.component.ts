// test-cases.component.ts
import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';

import { TestCaseService } from '../../services/test-case.service';
import { ProjectsService } from '../../services/projects.service';
import { ToastService } from '../../services/toast.service';
import { PlaywrightE2EService } from '../../services/playwright-e2e.service';
import { Project } from '../../models/user_story.model';
import { TestCaseStatus, Priority } from '../../models/test-case.model';

// Interface locale pour l'affichage des cartes
interface TestCaseDisplay {
  id: string;
  tc_code: string;
  title: string;
  issue_key: string | null;
  user_story_id: string | null;
  user_story_title: string | null;
  project_id: string | null;
  project_name: string | null;
  tags: string[] | null;
  priority: string | null;
  is_active: boolean;
}

@Component({
  selector: 'app-test-cases',
  standalone: true,
  imports: [
    CommonModule,
    FilterBarComponent,
    PaginationComponent,
    SearchBarComponent,
    SpinnerComponent,
  ],
  templateUrl: './test-cases.component.html',
  styleUrl: './test-cases.component.scss',
})
export class TestCasesComponent implements OnInit {
  private testCaseService = inject(TestCaseService);
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);
  private playwrightService = inject(PlaywrightE2EService);
  private router = inject(Router);

  // =========================
  // STATE
  // =========================
  
  allTestCases = signal<TestCaseDisplay[]>([]);
  projects = signal<Project[]>([]);
  loading = signal(false);
  
  // Pagination (frontend)
  page = signal(1);
  pageSize = signal(6);
  
  // Filters
  searchQuery = signal('');
  selectedProjectId = signal<string>('');
  selectedUserStoryId = signal<string>('');
  selectedStatus = signal<string>('all');
  selectedPriority = signal<string>('all');
  selectedPriorities = signal<string[]>([]);
  
  // Selection
  selectedTestCases = signal<Set<string>>(new Set());

  // Playwright generation tracking
  generatingIds = signal<Set<string>>(new Set());

  activeFilters = signal<ActiveFilters>({});

  viewMode = signal<'cards' | 'table'>('cards');

  // =========================
  // COMPUTED - FILTRAGE
  // =========================

  /** Unique user stories derived from the loaded test cases, optionally scoped to the selected project. */
  availableStories = computed(() => {
    const projectId = this.selectedProjectId();
    const seen = new Map<string, { id: string; label: string }>();

    for (const tc of this.allTestCases()) {
      if (!tc.user_story_id) continue;
      if (projectId && tc.project_id !== projectId) continue;
      if (!seen.has(tc.user_story_id)) {
        const key = tc.issue_key ?? tc.user_story_id;
        const title = tc.user_story_title ? ` – ${tc.user_story_title.substring(0, 45)}` : '';
        seen.set(tc.user_story_id, { id: tc.user_story_id, label: `${key}${title}` });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.label.localeCompare(b.label));
  });

  filteredTestCases = computed(() => {
    let items = this.allTestCases();
    
    // Filtre par recherche
    const search = this.searchQuery().toLowerCase();
    if (search) {
      items = items.filter(tc =>
        tc.tc_code.toLowerCase().includes(search) ||
        tc.title.toLowerCase().includes(search) ||
        (tc.issue_key && tc.issue_key.toLowerCase().includes(search))
      );
    }
    
    // Filtre par projet
    const projectId = this.selectedProjectId();
    if (projectId) {
      const project = this.projects().find(p => p.id === projectId);
      const projectName = project?.project_name;
      if (projectName) {
        items = items.filter(tc => tc.project_name === projectName);
      }
    }
    
    // Filtre par statut
    const status = this.selectedStatus();
    if (status !== 'all') {
      items = items.filter(tc => tc.is_active === (status === 'active'));
    }
    
    // Filtre par user story
    const userStoryId = this.selectedUserStoryId();
    if (userStoryId) {
      items = items.filter(tc => tc.user_story_id === userStoryId);
    }

    // Filtre par priorité
    const priorities = this.selectedPriorities();
    if (priorities.length > 0) {
      items = items.filter(tc => priorities.includes((tc.priority || 'medium').toLowerCase()));
    }

    return items;
  });

  paginatedTestCases = computed(() => {
    const start = (this.page() - 1) * this.pageSize();
    return this.filteredTestCases().slice(start, start + this.pageSize());
  });

  totalFiltered = computed(() => this.filteredTestCases().length);
  totalPages = computed(() => Math.ceil(this.totalFiltered() / this.pageSize()));

  selectedCount = computed(() => this.selectedTestCases().size);
  
  allSelected = computed(() => {
    const current = this.paginatedTestCases();
    return current.length > 0 && current.every(tc => this.selectedTestCases().has(tc.id));
  });
  
  someSelected = computed(() => {
    const current = this.paginatedTestCases();
    const selected = current.filter(tc => this.selectedTestCases().has(tc.id)).length;
    return selected > 0 && selected < current.length;
  });

  // =========================
  // LIFECYCLE
  // =========================
  
  ngOnInit(): void {
    this.loadProjects();
    this.loadTestCases();
  }

  // =========================
  // DATA LOADING
  // =========================
  
  loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: (projects) => {
        this.projects.set(projects);
      },
      error: (err) => {
        console.error('Failed to load projects:', err);
      },
    });
  }

  loadTestCases(): void {
    this.loading.set(true);
    
    // Construire les filtres pour l'API avec les bons types
    const filters: {
      project_id?: string;
      search?: string;
      status?: TestCaseStatus[];
      priority?: Priority[];
    } = {};
    
    if (this.selectedProjectId()) {
      filters.project_id = this.selectedProjectId();
    }
    
    if (this.searchQuery()) {
      filters.search = this.searchQuery();
    }
    
    // ✅ CORRECTION: Convertir string en TestCaseStatus
    if (this.selectedStatus() !== 'all') {
      filters.status = [this.selectedStatus() as TestCaseStatus];
    }
    
    // ✅ CORRECTION: Convertir string en Priority
    const priorities = this.selectedPriorities();
    if (priorities.length > 0) {
      filters.priority = priorities as Priority[];
    }
    
    this.testCaseService.getTestCases(filters).subscribe({
      next: (response: any[]) => {
        // Transformer les données pour l'affichage
        const testCases = response.map((tc: any) => ({
          id: tc.id,
          tc_code: tc.tc_code,
          title: tc.title,
          issue_key: tc.issue_key,
          user_story_id: tc.user_story_id ?? null,
          user_story_title: tc.user_story_title ?? null,
          project_id: tc.project_id ?? null,
          project_name: tc.project_name,
          tags: tc.tags,
          priority: (tc.priority || 'medium').toLowerCase(),
          is_active: tc.is_active,
        }));
        this.allTestCases.set(testCases);
        this.loading.set(false);
        this.page.set(1);
      },
      error: (error) => {
        console.error('Failed to load test cases:', error);
        this.toastService.error('Failed to load test cases', error.message);
        this.loading.set(false);
      },
    });
  }

  // =========================
  // FILTERS & SEARCH
  // =========================
  
  onProjectChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedProjectId.set(select.value);
    this.selectedUserStoryId.set('');  // reset story when project changes
    this.page.set(1);
    this.loadTestCases();
  }

  onUserStoryChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedUserStoryId.set(select.value);
    this.page.set(1);
  }

  onStatusChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedStatus.set(select.value);
    this.page.set(1);
    this.loadTestCases();
  }

  onPriorityChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedPriority.set(select.value);
    this.page.set(1);
    this.loadTestCases();
  }

  onSearchChange(query: string): void {
    this.searchQuery.set(query);
    this.page.set(1);
    this.loadTestCases();
  }

  filterGroups = computed<FilterGroup[]>(() => {
  const items = this.allTestCases();
  
  return [
    {
      key: 'status',
      label: 'Status',
      multiple: true,
      options: [
        { value: 'active', label: 'Active', count: items.filter(tc => tc.is_active).length },
        { value: 'archived', label: 'Archived', count: items.filter(tc => !tc.is_active).length },
      ],
    },
    {
      key: 'priority',
      label: 'Priority',
      multiple: true,
      options: [
        { value: 'critical', label: 'Critical', count: items.filter(tc => tc.priority === 'critical').length },
        { value: 'high', label: 'High', count: items.filter(tc => tc.priority === 'high').length },
        { value: 'medium', label: 'Medium', count: items.filter(tc => tc.priority === 'medium').length },
        { value: 'low', label: 'Low', count: items.filter(tc => tc.priority === 'low').length },
      ],
    },
  ];
});

// Ajouter la méthode onFiltersChange
onFiltersChange(filters: ActiveFilters): void {
  // Mettre à jour les filtres actifs
  this.activeFilters.set(filters);
  
  // Appliquer les filtres
  const statusFilter = filters['status'];
  const priorityFilter = filters['priority'];
  
  // Mettre à jour les signaux de filtres
  if (statusFilter && statusFilter.length > 0) {
    // Prendre la première valeur pour le select simple
    this.selectedStatus.set(statusFilter[0]);
  } else {
    this.selectedStatus.set('all');
  }
  
  if (priorityFilter && priorityFilter.length > 0) {
    this.selectedPriorities.set(priorityFilter);
  } else {
    this.selectedPriorities.set([]);
  }
  
  this.page.set(1);
  this.loadTestCases();
}

  clearAllFilters(): void {
    this.searchQuery.set('');
    this.selectedProjectId.set('');
    this.selectedUserStoryId.set('');
    this.selectedStatus.set('all');
    this.selectedPriorities.set([]);
    this.activeFilters.set({});
    this.page.set(1);
    this.loadTestCases();
  }

  refresh(): void {
    this.loadTestCases();
  }

  // =========================
  // SELECTION ACTIONS
  // =========================
  
  toggleSelect(testCase: TestCaseDisplay): void {
    const current = new Set(this.selectedTestCases());
    if (current.has(testCase.id)) {
      current.delete(testCase.id);
    } else {
      current.add(testCase.id);
    }
    this.selectedTestCases.set(current);
  }

  toggleSelectAll(): void {
    if (this.allSelected()) {
      this.selectedTestCases.set(new Set());
    } else {
      const ids = this.paginatedTestCases().map(tc => tc.id);
      this.selectedTestCases.set(new Set(ids));
    }
  }

  bulkDelete(): void {
    const ids = Array.from(this.selectedTestCases());
    if (ids.length === 0) return;
    
    if (confirm(`Delete ${ids.length} test case(s)? This action cannot be undone.`)) {
      this.loading.set(true);
      
      Promise.all(ids.map(id => this.testCaseService.deleteTestCase(id).toPromise()))
        .then(() => {
          this.toastService.success('Deleted', `${ids.length} test case(s) deleted`);
          this.selectedTestCases.set(new Set());
          this.loadTestCases();
        })
        .catch(error => {
          this.toastService.error('Delete failed', error.message);
          this.loading.set(false);
        });
    }
  }

  // =========================
  // NAVIGATION
  // =========================
  
viewTestCase(id: string, event?: Event): void {
  // Empêcher la propagation si un event est passé (pour éviter les conflits avec d'autres clics)
  if (event) {
    event.stopPropagation();
  }
  
  // Navigation vers la page de détail du test case
  this.router.navigate(['/test-cases', id]);
}


  createTestCase(): void {
    this.router.navigate(['/test-cases/create']);
  }

  deleteTestCase(id: string, event: Event): void {
    event.stopPropagation();
    if (confirm('Delete this test case?')) {
      this.testCaseService.deleteTestCase(id).subscribe({
        next: () => {
          this.toastService.success('Deleted', 'Test case deleted');
          this.loadTestCases();
        },
        error: (error) => this.toastService.error('Delete failed', error.message),
      });
    }
  }

  generateScript(id: string, event: Event): void {
    event.stopPropagation();
    const current = new Set(this.generatingIds());
    current.add(id);
    this.generatingIds.set(current);

    this.playwrightService.generateScript({ test_case_id: id }).subscribe({
      next: (res) => {
        const updated = new Set(this.generatingIds());
        updated.delete(id);
        this.generatingIds.set(updated);
        if (res.status === 'generated') {
          this.toastService.success('Script generated', `v${res.version_number} ready`);
          this.router.navigate(['/playwright-scripts']);
        } else {
          this.toastService.error('Generation failed', res.error ?? 'Unknown error');
        }
      },
      error: (err) => {
        const updated = new Set(this.generatingIds());
        updated.delete(id);
        this.generatingIds.set(updated);
        this.toastService.error('Generation failed', err.message);
      },
    });
  }

  // =========================
  // PAGINATION
  // =========================
  
  onPageChange(page: number): void {
    this.page.set(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onPageSizeChange(size: number): void {
    this.pageSize.set(size);
    this.page.set(1);
  }

  // =========================
  // UTILITAIRES
  // =========================
  
getPriorityClass(priority: string | null): string {
  const priorityValue = priority || 'medium';
  const classes: Record<string, string> = {
    'critical': 'priority-critical',
    'high': 'priority-high',
    'medium': 'priority-medium',
    'low': 'priority-low',
  };
  return classes[priorityValue] || 'priority-medium';
}


  getStatusLabel(isActive: boolean): string {
    return isActive ? 'Active' : 'Archived';
  }

  setViewMode(mode: 'cards' | 'table'): void {
    this.viewMode.set(mode);
  }

  getTagClass(tag: string): string {
    const classes: Record<string, string> = {
      'positive': 'tag-positive',
      'smoke': 'tag-smoke',
      'regression': 'tag-regression',
      'negative': 'tag-negative',
    };
    return classes[tag] || 'tag-default';
  }
}