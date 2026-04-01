import { Component, inject, signal, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ProjectsService, ToastService } from '../../services';
import { JiraProject } from '../../services/projects.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { JiraService } from 'src/app/services/jira.service';

@Component({
  selector: 'app-import-modal',
  standalone: true,
  imports: [CommonModule,SpinnerComponent],
  templateUrl: './import-modal.component.html',
  styleUrl: './import-modal.component.scss',
})
export class ImportModalComponent {
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);
  private jiraService = inject(JiraService);

  closed = output<void>();
  imported = output<void>();

  visible = signal(false);
  loading = signal(false);
  importing = signal(false);
  jiraConnected = signal(false);

  jiraProjects = signal<JiraProject[]>([]);
  selectedProject = signal<JiraProject | null>(null);

  open(): void {
    this.visible.set(true);
    this.loading.set(false);
    this.importing.set(false);
    this.selectedProject.set(null);
    this.jiraProjects.set([]);
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
    this.selectedProject.set(project);
  }

  private checkJiraAndFetchProjects(): void {
    this.loading.set(true);

    this.jiraService.getStatus().subscribe({
      next: (status) => {
        this.jiraConnected.set(!!status?.connected);

        if (!status?.connected) {
          this.loading.set(false);
          this.toastService.info(
            'Jira not connected',
            'Please connect your Jira account first'
          );
          return;
        }

        this.fetchJiraProjects();
      },
      error: (err) => {
        this.loading.set(false);
        this.toastService.error(
          'Failed to check Jira connection',
          err?.error?.detail || err?.message || 'Could not verify Jira status'
        );
      },
    });
  }

  private fetchJiraProjects(): void {
    this.jiraService.getProjects().subscribe({
      next: (projects) => {
        this.jiraProjects.set(projects ?? []);
        this.loading.set(false);

        if (!projects || projects.length === 0) {
          this.toastService.info(
            'No Jira projects found',
            'No accessible Jira projects were returned for this account'
          );
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.toastService.error(
          'Failed to fetch Jira projects',
          err?.error?.detail || err?.message || 'Could not connect to Jira'
        );
      },
    });
  }

  confirmImport(): void {
    const project = this.selectedProject();
    if (!project || this.importing()) return;

    this.importing.set(true);

    this.projectsService.importStories(project.key).subscribe({
      next: (result) => {
        const imported = result?.result?.imported ?? 0;
        const skipped = result?.result?.skipped ?? 0;

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
        this.imported.emit();
      },
      error: (err) => {
        this.importing.set(false);
        this.toastService.error(
          'Import failed',
          err?.error?.detail || err?.message || 'Something went wrong'
        );
      },
    });
  }

}
