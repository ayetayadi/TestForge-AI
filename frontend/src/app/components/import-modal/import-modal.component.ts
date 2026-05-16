import { Component, inject, signal, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ProjectsService, ToastService } from '../../services';
import { JiraProject, ImportStoriesResponse } from '../../services/projects.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { JiraService, JiraEpic, JiraSprint } from '../../services/jira.service';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

@Component({
  selector: 'app-import-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, SpinnerComponent],
  templateUrl: './import-modal.component.html',
  styleUrl: './import-modal.component.scss',
})
export class ImportModalComponent {
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);
  private jiraService = inject(JiraService);

  closed = output<void>();
  imported = output<{ imported: number; skipped: number; total: number } | null>();

  visible = signal(false);
  loading = signal(false);
  importing = signal(false);
  jiraConnected = signal(false);
  filtersLoading = signal(false);

  jiraProjects = signal<JiraProject[]>([]);
  selectedProject = signal<JiraProject | null>(null);

  epics = signal<JiraEpic[]>([]);
  sprints = signal<JiraSprint[]>([]);
  selectedEpicKey = signal<string>('');
  selectedSprintName = signal<string>('');
  useOrMode = signal(false);

  open(): void {
    this.visible.set(true);
    this.loading.set(false);
    this.importing.set(false);
    this.selectedProject.set(null);
    this.jiraProjects.set([]);
    this.epics.set([]);
    this.sprints.set([]);
    this.selectedEpicKey.set('');
    this.selectedSprintName.set('');
    this.checkJiraAndFetchProjects();
  }

  close(): void {
    if (this.importing()) return;
    this.visible.set(false);
    this.closed.emit();
  }

  onBackdropClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('modal-backdrop')) {
      this.close();
    }
  }

  selectProject(project: JiraProject): void {
    if (this.importing()) return;
    const isSame = this.selectedProject()?.key === project.key;
    this.selectedProject.set(project);
    this.selectedEpicKey.set('');
    this.selectedSprintName.set('');
    if (!isSame) {
      this.loadFilters(project.key);
    }
  }

  private checkJiraAndFetchProjects(): void {
    this.loading.set(true);

    this.jiraService.getStatus().subscribe({
      next: (status) => {
        this.jiraConnected.set(!!status?.connected);
        if (!status?.connected) {
          this.loading.set(false);
          this.toastService.info('Jira not connected', 'Please connect your Jira account first');
          return;
        }
        this.fetchJiraProjects();
      },
      error: (err) => {
        this.loading.set(false);
        this.toastService.error('Failed to check Jira connection', err?.error?.detail || err?.message || 'Could not verify Jira status');
      },
    });
  }

  private fetchJiraProjects(): void {
    this.jiraService.getProjects().subscribe({
      next: (projects) => {
        this.jiraProjects.set(projects ?? []);
        this.loading.set(false);
        if (!projects || projects.length === 0) {
          this.toastService.info('No Jira projects found', 'No accessible Jira projects were returned for this account');
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.toastService.error('Failed to fetch Jira projects', err?.error?.detail || err?.message || 'Could not connect to Jira');
      },
    });
  }

  private loadFilters(projectKey: string): void {
    this.filtersLoading.set(true);
    this.epics.set([]);
    this.sprints.set([]);

    forkJoin({
      epics: this.jiraService.getEpics(projectKey).pipe(catchError(() => of([]))),
      sprints: this.jiraService.getSprints(projectKey).pipe(catchError(() => of([]))),
    }).subscribe({
      next: ({ epics, sprints }) => {
        this.epics.set(epics);
        this.sprints.set(sprints);
        this.filtersLoading.set(false);
      },
      error: () => this.filtersLoading.set(false),
    });
  }

  confirmImport(): void {
    const project = this.selectedProject();
    if (!project || this.importing()) return;

    this.importing.set(true);

    const epicKey = this.selectedEpicKey() || null;
    const sprintName = this.selectedSprintName() || null;
    const useOr = this.useOrMode();

    this.projectsService.importStories(project.key, epicKey, sprintName, useOr).subscribe({
      next: (response: ImportStoriesResponse) => {
        const imported = response?.result?.imported ?? 0;
        const skipped = response?.result?.skipped ?? 0;
        const total = response?.result?.total ?? 0;

        if (imported > 0) {
          this.toastService.success('Import completed', `${imported} new stories imported, ${skipped} already existed`);
        } else if (skipped > 0 && total > 0) {
          this.toastService.info('Already up to date', `All ${skipped} stories from "${project.name}" are already in your library`);
        } else if (total === 0) {
          this.toastService.info('No user stories found', `The project "${project.name}" has no user stories in Jira`);
        } else {
          this.toastService.info('Nothing to import', `No new stories found in "${project.name}"`);
        }

        this.importing.set(false);
        this.visible.set(false);
        this.imported.emit(response?.result ?? null);
      },
      error: (err) => {
        this.importing.set(false);
        this.toastService.error('Import failed', err?.error?.detail || err?.message || 'Something went wrong');
        this.imported.emit(null);
      },
    });
  }
}