import { Component, OnInit, inject, signal, computed, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { ImportModalComponent } from '../../components/import-modal/import-modal.component';
import { ProjectsService, ToastService } from '../../services';
import { Project } from '../../models/user_story.model';
import { JiraService } from 'src/app/services/jira.service';
import { InAppNotificationService } from 'src/app/services/in-app-notification.service';

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
  private jiraService = inject(JiraService);
  private notifService = inject(InAppNotificationService);

  @ViewChild('importModal') importModal!: ImportModalComponent;

  projects = signal<Project[] | null>(null);
  loading = signal(true);
  jiraConnected = signal(false);
  errorMessage = signal<string | null>(null);

  page = signal(1);
  pageSize = signal(10);
  viewMode: 'grid' | 'list' = 'grid';

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
    let result = this.projects() ?? [];
    const query = this.searchQuery().toLowerCase().trim();
    const filters = this.activeFilters();

    if (query) {
      result = result.filter(p =>
        p.project_name.toLowerCase().includes(query) ||
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
    const all = this.filteredProjects() ?? [];
    const start = (this.page() - 1) * this.pageSize();
    return all.slice(start, start + this.pageSize());
  });

  ngOnInit(): void {
    const savedMode = localStorage.getItem('projectsViewMode') as 'grid' | 'list';
    if (savedMode) {
      this.viewMode = savedMode;
    }
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
        this.projects.set(Array.isArray(projects) ? projects : []);
        this.loading.set(false);
        
        // this.toastService.success('Projects loaded', `${projects.length} projects found`);
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
    this.jiraService.getStatus().subscribe({
      next: (status) => this.jiraConnected.set(status.connected),
      error: () => {
        this.jiraConnected.set(false);
        this.toastService.warning('Jira connection lost', 'Unable to connect to Jira');
      },
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
    this.toastService.info('Filters cleared', 'All filters have been reset');
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

  onImported(result: { imported: number; skipped: number; total: number } | null): void {
    if (result && result.imported > 0) {
      // this.toastService.success(
      //   'Import completed',
      //   `${result.imported} new stories imported, ${result.skipped} already existed`
      // );
    } else if (result && result.skipped > 0 && result.imported === 0) {
      this.toastService.info(
        'Already up to date',
        `All ${result.skipped} stories already exist`
      );
    } else if (result && result.imported === 0 && result.skipped === 0) {
      this.toastService.warning(
        'No stories found',
        'No stories were found in the selected project'
      );
    }
    this.loadProjects();
  }

  viewStories(project: Project): void {
    if (project.story_count === 0) {
      this.toastService.warning(
        'No stories',
        `Project "${project.project_name}" has no stories to view`
      );
      return;
    }

    this.notifService.connect(project.project_key);

    this.router.navigate(['/user-stories'], {
      queryParams: {
        projectId: project.id,
        projectKey: project.project_key,
        projectName: project.project_name,
        source: this.jiraConnected() ? 'jira' : 'local',
      },
    });
  }

  deleteProject(project: Project): void {
    if (!confirm(`Delete project "${project.project_name}" ?`)) {
      return;
    }

    this.projectsService.deleteProject(project.id).subscribe({
      next: () => {
        this.toastService.success('Project deleted', project.project_name);
        
        // Mise à jour locale
        this.projects.update(list =>
          (list ?? []).filter(p => p.id !== project.id)
        );
        
        // Ajuster la pagination si nécessaire
        if (this.paginatedProjects().length === 0 && this.page() > 1) {
          this.page.set(this.page() - 1);
        }
      },
      error: (err) => {
        console.error('[DELETE PROJECT ERROR]', err);
        const msg = err?.error?.detail || err?.message || 'Unknown error';
        this.toastService.error('Delete failed', msg);
      }
    });
  }

  toggleViewMode(mode: 'grid' | 'list'): void {
    this.viewMode = mode;
    localStorage.setItem('projectsViewMode', mode);
    this.toastService.info(`View changed`, `${mode === 'grid' ? 'Grid' : 'List'} view activated`);
  }
}