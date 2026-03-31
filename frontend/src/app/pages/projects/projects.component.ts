import { Component, OnInit, inject, signal, computed, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { ImportModalComponent } from '../../components/import-modal/import-modal.component';
import { ProjectsService, ToastService } from '../../services';
import { Project } from '../../models';

@Component({
  selector: 'app-projects',
  standalone: true,
  imports: [
    CommonModule,
    SpinnerComponent,
    SearchBarComponent,
    FilterBarComponent,
    PaginationComponent,
    ImportModalComponent,
  ],
  templateUrl: './projects.component.html',
  styleUrl: './projects.component.scss',
})
export class ProjectsComponent implements OnInit {
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);
  private router = inject(Router);

  @ViewChild('importModal') importModal!: ImportModalComponent;

  projects = signal<Project[]>([]);
  loading = signal(true);
  jiraConnected = signal(false);
  errorMessage = signal<string | null>(null);

  page = signal(1);
  pageSize = signal(12);

  private searchQuery = signal('');
  activeFilters = signal<ActiveFilters>({});

  filterGroups: FilterGroup[] = [
    {
      key: 'stories',
      label: 'Stories',
      multiple: false,
      options: [
        { value: 'has_stories', label: 'Has stories' },
        { value: 'empty', label: 'No stories' },
      ],
    },
  ];

  filteredProjects = computed(() => {
    let result = this.projects();
    const query = this.searchQuery().toLowerCase().trim();
    const filters = this.activeFilters();

    if (query) {
      result = result.filter(p =>
        p.name.toLowerCase().includes(query) ||
        p.project_key.toLowerCase().includes(query)
      );
    }

    if (filters['stories']?.length) {
      const wantHas = filters['stories'].includes('has_stories');
      const wantEmpty = filters['stories'].includes('empty');

      if (wantHas && !wantEmpty) {
        result = result.filter(p => (p.story_count ?? 0) > 0);
      } else if (wantEmpty && !wantHas) {
        result = result.filter(p => (p.story_count ?? 0) === 0);
      }
    }

    return result;
  });

  paginatedProjects = computed(() => {
    const all = this.filteredProjects();
    const start = (this.page() - 1) * this.pageSize();
    return all.slice(start, start + this.pageSize());
  });

  ngOnInit(): void {
    this.loadProjects();
    this.checkJiraStatus();
  }

  loadProjects(): void {
    this.loading.set(true);
    this.errorMessage.set(null);

    console.log('[ProjectsComponent] Fetching projects...');

    this.projectsService.getProjects().subscribe({
      next: (projects) => {
        console.log('[ProjectsComponent] Projects received:', projects);
        // ✅ Guard against null/undefined response from backend
        this.projects.set(Array.isArray(projects) ? projects : []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('[ProjectsComponent] Failed to load projects:', err);
        const msg = err?.error?.detail || err?.message || 'Unknown error';
        this.errorMessage.set(`Failed to load projects: ${msg}`);
        this.toastService.error('Failed to load projects', msg);
        this.loading.set(false);
      },
    });
  }

  private checkJiraStatus(): void {
    this.projectsService.getJiraStatus().subscribe({
      next: (status) => this.jiraConnected.set(status.connected),
      error: () => this.jiraConnected.set(false),
    });
  }

  onSearchChange(query: string): void {
    this.searchQuery.set(query);
    this.page.set(1);
  }

  onFiltersChange(filters: ActiveFilters): void {
    this.activeFilters.set(filters);
    this.page.set(1);
  }

  clearAllFilters(): void {
    this.searchQuery.set('');
    this.activeFilters.set({});
    this.page.set(1);
  }

  onPageChange(p: number): void {
    this.page.set(p);
  }

  onPageSizeChange(size: number): void {
    this.pageSize.set(size);
    this.page.set(1);
  }

  openImportModal(): void {
    this.importModal.open();
  }

  onImported(): void {
    this.loadProjects();
  }

  viewStories(project: Project): void {
    this.router.navigate(['/user-stories'], {
      queryParams: {
        projectId: project.id,
        projectKey: project.project_key,
        projectName: project.name,
        source: this.jiraConnected() ? 'jira' : 'local',
      },
    });
  }
}
