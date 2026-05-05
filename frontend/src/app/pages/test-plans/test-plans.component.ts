import { Component, OnInit, signal, computed, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TestPlanService } from '../../services/test-plan.service';
import { ProjectsService } from '../../services/projects.service';
import { StoriesService } from '../../services/stories.service';
import { ToastService } from '../../services/toast.service';
import { ConfirmDialogComponent } from '../../components/confirm-dialog/confirm-dialog.component';
import {
  TestPlan,
  TestPlanStatus,
  TestPlanSummary,
  GenerateTestPlanRequest,
  TEST_PLAN_STATUS_CONFIG,
} from '../../models/test-plan.model';
import { Project, UserStory } from '../../models/user_story.model';
import { SpinnerComponent } from 'src/app/shared/spinner/spinner.component';

@Component({
  selector: 'app-test-plans',
  standalone: true,
  imports: [CommonModule, FormsModule, ConfirmDialogComponent],
  templateUrl: './test-plans.component.html',
  styleUrl: './test-plans.component.scss',
})
export class TestPlansComponent implements OnInit {
  private testPlanService = inject(TestPlanService);
  private projectsService = inject(ProjectsService);
  private storiesService = inject(StoriesService);
  private router = inject(Router);
  private toast = inject(ToastService);
  private cdr = inject(ChangeDetectorRef);

  // ── Data ─────────────────────────────────────────────────────
  projects = signal<Project[]>([]);
  testPlans = signal<TestPlan[]>([]);
  summary = signal<TestPlanSummary | null>(null);

  // Données locales
  sprints = signal<{ id: string; name: string }[]>([]);
  epics = signal<{ id: string; name: string; key: string }[]>([]);
  allStories = signal<UserStory[]>([]);
  isLoadingScopeRefs = signal(false);

  // ── Selection ─────────────────────────────────────────────────
  selectedProjectId = signal<string>('');
  activeTab = signal<TestPlanStatus | 'all'>('all');

  // ── Generation modal ──────────────────────────────────────────
  showGenerateModal = signal(false);
  modalProjectId = '';
  scopeType = 'manual';
  scopeRefs = '';
  environment = 'staging';
  limitRisks = 50;
  limitStories = 30;
  selectedScopeItems = signal<string[]>([]);

// ── Confirm Dialog ──────────────────────────────────────────
showConfirmDialog = signal(false);
confirmDialogData = signal<{
  title: string;
  message: string;
  icon: string;
  confirmText: string;
  cancelText: string;
  variant: 'primary' | 'danger' | 'warning' | 'success';
  onConfirm: () => void;
}>({
  title: '',
  message: '',
  icon: '🗑️',
  confirmText: 'Delete',
  cancelText: 'Cancel',
  variant: 'danger',
  onConfirm: () => {},
});

  selectedSprintIds = signal<string[]>([]);
  selectedEpicKeys = signal<string[]>([]);

  // ── UI state ─────────────────────────────────────────────────
  isLoading = signal(false);
  isGenerating = signal(false);
  page = signal(1);
  totalPages = signal(1);

  // ── Computed ──────────────────────────────────────────────────
  filteredPlans = computed(() => {
    const tab = this.activeTab();
    if (tab === 'all') return this.testPlans();
    return this.testPlans().filter(p => p.status === tab);
  });

  getScopeOptions(): { id: string; name: string; key?: string }[] {
    if (this.scopeType === 'sprint') {
      return this.sprints();
    }
    if (this.scopeType === 'epic') {
      return this.epics();
    }
    return [];
  }

  scopeOptionLabel = computed(() => {
    switch (this.scopeType) {
      case 'sprint': return 'Select Sprints';
      case 'epic': return 'Select Epics';
      default: return 'Manual References (comma-separated story IDs)';
    }
  });

  readonly statusConfig = TEST_PLAN_STATUS_CONFIG;
  readonly statusTabs: Array<TestPlanStatus | 'all'> = [
    'all', 'ai_proposed', 'draft', 'approved', 'active', 'archived',
  ];
  readonly scopeTypes = ['manual', 'epic', 'sprint'];
  readonly environments = ['dev', 'staging', 'prod', 'uat'];

  ngOnInit(): void {
    this.loadProjects();
    this.loadTestPlans();
  }

  // ── Data loading ──────────────────────────────────────────────

  loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: projects => {
        this.projects.set(projects);
      },
      error: () => this.toast.error('Failed to load projects'),
    });
  }

  loadTestPlans(): void {
    const projectId = this.selectedProjectId();
    this.isLoading.set(true);

    if (!projectId) {
      this.testPlanService.getAll({ page: this.page(), pageSize: 20 }).subscribe({
        next: res => {
          this.testPlans.set(res.items);
          this.totalPages.set(res.total_pages);
          this.isLoading.set(false);
        },
        error: () => {
          this.toast.error('Failed to load test plans');
          this.isLoading.set(false);
        },
      });
      this.summary.set(null);
      return;
    }

    this.testPlanService.getByProject(projectId, {
      page: this.page(),
      pageSize: 20,
      sprintIds: this.selectedSprintIds().length > 0 ? this.selectedSprintIds() : undefined,
      epicKeys: this.selectedEpicKeys().length > 0 ? this.selectedEpicKeys() : undefined,
    }).subscribe({
      next: res => {
        this.testPlans.set(res.items);
        this.totalPages.set(res.total_pages);
        this.isLoading.set(false);
      },
      error: () => {
        this.toast.error('Failed to load test plans');
        this.isLoading.set(false);
      },
    });

    this.testPlanService.getSummaryByProject(projectId).subscribe({
      next: s => this.summary.set(s),
      error: () => {},
    });
  }

  loadProjectMetadata(projectId: string): void {
    this.isLoadingScopeRefs.set(true);
    
    this.storiesService.getStoriesByProject(projectId).subscribe({
      next: (stories) => {
        this.allStories.set(stories);
        
        const sprintSet = new Map<string, string>();
        const epicMap = new Map<string, string>();
        
        for (const story of stories) {
          if (story.sprint) {
            sprintSet.set(story.sprint, story.sprint);
          }
          if (story.epic_key && story.epic_name) {
            epicMap.set(story.epic_key, story.epic_name);
          }
        }
        
        this.sprints.set(
          Array.from(sprintSet.entries()).map(([name]) => ({
            id: name,
            name: name,
          }))
        );
        
        this.epics.set(
          Array.from(epicMap.entries()).map(([key, name]) => ({
            id: key,
            name: name,
            key: key,
          }))
        );
        
        this.isLoadingScopeRefs.set(false);
      },
      error: (err) => {
        console.error('Failed to load project metadata:', err);
        this.toast.error('Failed to load project metadata');
        this.isLoadingScopeRefs.set(false);
      },
    });
  }

  onScopeTypeChange(type: string): void {
    this.scopeType = type;
    this.selectedScopeItems.set([]);
    this.scopeRefs = '';
    this.cdr.detectChanges();
    
    if (type === 'manual') {
      this.isLoadingScopeRefs.set(false);
      return;
    }

    const projectId = this.modalProjectId;
    if (!projectId) {
      this.toast.error('Please select a project first');
      return;
    }

    const hasData = type === 'sprint'
      ? this.sprints().length > 0
      : this.epics().length > 0;

    if (!hasData) {
      this.isLoadingScopeRefs.set(true);
      this.loadProjectMetadata(projectId);
    }
  }

  toggleScopeItem(itemId: string): void {
    const current = this.selectedScopeItems();
    if (current.includes(itemId)) {
      this.selectedScopeItems.set(current.filter(id => id !== itemId));
    } else {
      this.selectedScopeItems.set([...current, itemId]);
    }
  }

  // ── Project selection ─────────────────────────────────────────

  onProjectChange(projectId: string): void {
    this.selectedProjectId.set(projectId);
    this.page.set(1);
    this.selectedSprintIds.set([]);
    this.selectedEpicKeys.set([]);
    this.loadTestPlans();
    if (projectId) {
      this.loadProjectMetadata(projectId);
    }
  }

  // ── AI Generation ─────────────────────────────────────────────

  openGenerateModal(): void {
    this.modalProjectId = this.selectedProjectId();
    if (this.modalProjectId && this.sprints().length === 0 && this.epics().length === 0) {
      this.loadProjectMetadata(this.modalProjectId);
    }
    this.showGenerateModal.set(true);
  }

  onModalProjectChange(projectId: string): void {
    this.modalProjectId = projectId;
    this.selectedScopeItems.set([]);
    this.scopeRefs = '';
    this.sprints.set([]);
    this.epics.set([]);
    if (projectId && this.scopeType !== 'manual') {
      this.loadProjectMetadata(projectId);
    }
  }

  closeGenerateModal(): void {
    this.showGenerateModal.set(false);
    this.modalProjectId = '';
    this.scopeType = 'manual';
    this.scopeRefs = '';
    this.selectedScopeItems.set([]);
  }

  generatePlan(): void {
    const projectId = this.modalProjectId;
    if (!projectId) {
      this.toast.error('Please select a project first');
      return;
    }

    let scopeRefsArray: string[];
    if (this.scopeType === 'manual') {
      scopeRefsArray = this.scopeRefs
        .split(',')
        .map(s => s.trim())
        .filter(s => s.length > 0);
    } else {
      scopeRefsArray = this.selectedScopeItems();
    }

    if (scopeRefsArray.length === 0 && this.scopeType !== 'manual') {
      this.toast.error(`Please select at least one ${this.scopeType}`);
      return;
    }

    // ✅ Construction de la requête avec les filtres sprint/epic
    const request: GenerateTestPlanRequest = {
      project_id: projectId,
      scope_type: this.scopeType,
      scope_refs: scopeRefsArray,
      environment: this.environment,
      limit_risks: this.limitRisks,
      limit_stories: this.limitStories,
      // ✅ Ajout des filtres sprint/epic
      sprint_ids: this.scopeType === 'sprint' ? scopeRefsArray : undefined,
      epic_keys: this.scopeType === 'epic' ? scopeRefsArray : undefined,
    };

    this.isGenerating.set(true);
    this.testPlanService.generate(request).subscribe({
      next: res => {
        this.isGenerating.set(false);
        this.showGenerateModal.set(false);
        this.toast.success('Test plan draft generated successfully!');
        this.loadTestPlans();
        this.router.navigate(['/test-plans', res.test_plan.id]);
      },
      error: err => {
        this.isGenerating.set(false);
        this.toast.error(
          err?.error?.detail || 'AI generation failed. Make sure risk analysis has been run first.'
        );
      },
    });
  }



  deleteAllProjectPlans(): void {
  const projectId = this.selectedProjectId();
  if (!projectId) return;

  const count = this.testPlans().length;
  if (count === 0) {
    this.toast.info('Nothing to delete', 'No test plans found for this project.');
    return;
  }

  this.confirmDialogData.set({
    title: 'Delete All Test Plans',
    message: `🗑️ Delete ALL ${count} test plans for this project?\n\nThis action cannot be undone!`,
    icon: '⚠️',
    confirmText: 'Delete All',
    cancelText: 'Cancel',
    variant: 'danger',
    onConfirm: () => {
      this.testPlanService.deleteByProject(projectId).subscribe({
        next: () => {
          this.testPlans.set([]);
          this.summary.set(null);
          this.toast.success('All test plans deleted');
        },
        error: () => this.toast.error('Failed to delete test plans'),
      });
    }
  });
  this.showConfirmDialog.set(true);
}

  // ── Navigation ────────────────────────────────────────────────

  openPlan(plan: TestPlan): void {
    this.router.navigate(['/test-plans', plan.id]);
  }

  // ── Pagination ────────────────────────────────────────────────

  goToPage(p: number): void {
    this.page.set(p);
    this.loadTestPlans();
  }

  // ── Helpers ───────────────────────────────────────────────────

  getStatusConfig(status: TestPlanStatus) {
    return TEST_PLAN_STATUS_CONFIG[status] ?? TEST_PLAN_STATUS_CONFIG.draft;
  }

  tabLabel(tab: TestPlanStatus | 'all'): string {
    if (tab === 'all') return 'All';
    return TEST_PLAN_STATUS_CONFIG[tab]?.label ?? tab;
  }

  tabCount(tab: TestPlanStatus | 'all'): number {
    const s = this.summary();
    if (!s) return 0;
    if (tab === 'all') return s.total;
    return s.by_status[tab] ?? 0;
  }

  formatDate(dateStr?: string): string {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    });
  }



  deletePlan(planId: string, event: Event): void {
  event.stopPropagation();
  
  this.confirmDialogData.set({
    title: 'Delete Test Plan',
    message: '🗑️ Delete this test plan?\n\nThis action cannot be undone.',
    icon: '🗑️',
    confirmText: 'Delete',
    cancelText: 'Cancel',
    variant: 'danger',
    onConfirm: () => {
      this.testPlanService.delete(planId).subscribe({
        next: () => {
          this.testPlans.update(plans => plans.filter(p => p.id !== planId));
          this.toast.success('Test plan deleted');
          const projectId = this.selectedProjectId();
          if (projectId) {
            this.testPlanService.getSummaryByProject(projectId).subscribe({
              next: s => this.summary.set(s),
            });
          }
        },
        error: () => this.toast.error('Failed to delete test plan'),
      });
    }
  });
  this.showConfirmDialog.set(true);
}

}