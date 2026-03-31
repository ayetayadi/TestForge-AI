import { Component, inject, signal, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ProjectsService, ToastService } from '../../services';

export interface JiraProject {
  key: string;
  name: string;
  lead?: string;
  type?: string;
}

@Component({
  selector: 'app-import-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './import-modal.component.html',
  styleUrl: './import-modal.component.scss',
})
export class ImportModalComponent {
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);

  closed = output<void>();
  imported = output<{ imported: number; skipped: number }>();

  visible = signal(false);
  loading = signal(false);
  importing = signal(false);
  jiraProjects = signal<JiraProject[]>([]);
  selectedProject = signal<JiraProject | null>(null);

  open(): void {
    this.visible.set(true);
    this.selectedProject.set(null);
    this.fetchJiraProjects();
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
    this.selectedProject.set(project);
  }

  fetchJiraProjects(): void {
    this.loading.set(true);
    this.projectsService.getJiraProjects().subscribe({
      next: (projects) => {
        this.jiraProjects.set(projects);
        this.loading.set(false);
      },
      error: (err) => {
        this.toastService.error(
          'Failed to fetch Jira projects',
          err?.error?.detail || err.message || 'Could not connect to Jira'
        );
        this.loading.set(false);
      },
    });
  }

  confirmImport(): void {
    const project = this.selectedProject();
    if (!project) return;

    this.importing.set(true);

    this.projectsService.importStories(project.key).subscribe({
      next: (result) => {
        const imported = result.result.imported;
        const skipped = result.result.skipped;

        if (imported > 0) {
          this.toastService.success(
            'Import completed',
            `${imported} stories imported, ${skipped} skipped`
          );
        } else if (skipped > 0) {
          this.toastService.info(
            'Nothing new to import',
            `All ${skipped} stories already exist`
          );
        } else {
          this.toastService.info(
            'No stories found',
            'This project has no user stories in Jira'
          );
        }

        this.importing.set(false);
        this.visible.set(false);
        this.imported.emit({ imported, skipped });
      },
      error: (err) => {
        this.toastService.error(
          'Import failed',
          err?.error?.detail || err.message || 'Something went wrong'
        );
        this.importing.set(false);
      },
    });
  }
}