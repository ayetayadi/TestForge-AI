import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TestPlanService } from '../../services/test-plan.service';
import { ProjectsService } from '../../services/projects.service';
import { ToastService } from '../../services/toast.service';
import {
  TestPlan,
  TestPlanStatus,
  TestPlanSummary,
  GenerateTestPlanRequest,
  TEST_PLAN_STATUS_CONFIG,
} from '../../models/test-plan.model';
import { Project } from '../../models/user_story.model';
import { JiraService } from 'src/app/services/jira.service';

@Component({
  selector: 'app-test-plans',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './test-plans.component.html',
  styleUrl: './test-plans.component.scss',
})
export class TestPlansComponent implements OnInit {
  private testPlanService = inject(TestPlanService);
  private projectsService = inject(ProjectsService);
  private router          = inject(Router);
  private toast           = inject(ToastService);
  private jiraService = inject(JiraService);

  // ── Data ─────────────────────────────────────────────────────
  projects     = signal<Project[]>([]);
  testPlans    = signal<TestPlan[]>([]);
  summary      = signal<TestPlanSummary | null>(null);

  sprints = signal<{ id: string; name: string }[]>([]);
  epics = signal<{ id: string; name: string; key: string }[]>([]);
  releases = signal<{ id: string; name: string }[]>([]);
  isLoadingScopeRefs = signal(false);

  // ── Selection ─────────────────────────────────────────────────
  selectedProjectId = signal<string>('');
  activeTab         = signal<TestPlanStatus | 'all'>('all');

  // ── Generation modal ──────────────────────────────────────────
  showGenerateModal = signal(false);
  scopeType         = 'manual';
  scopeRefs         = '';
  environment       = 'staging';
  limitRisks        = 50;
  limitStories      = 30;
  selectedScopeItems = signal<string[]>([]);

  // ── UI state ─────────────────────────────────────────────────
  isLoading     = signal(false);
  isGenerating  = signal(false);
  page          = signal(1);
  totalPages    = signal(1);

  // ── Computed ──────────────────────────────────────────────────
  filteredPlans = computed(() => {
    const tab = this.activeTab();
    if (tab === 'all') return this.testPlans();
    return this.testPlans().filter(p => p.status === tab);
  });

  scopeOptions = computed(() => {
    switch (this.scopeType) {
      case 'sprint': return this.sprints();
      case 'epic': return this.epics();
      case 'release': return this.releases();
      default: return [];
    }
  });


  scopeOptionLabel = computed(() => {
    switch (this.scopeType) {
      case 'sprint': return 'Select Sprints';
      case 'epic': return 'Select Epics';
      case 'release': return 'Select Releases';
      default: return 'Scope References';
    }
  });

  readonly statusConfig = TEST_PLAN_STATUS_CONFIG;
  readonly statusTabs: Array<TestPlanStatus | 'all'> = [
    'all', 'ai_proposed', 'draft', 'approved', 'active', 'archived',
  ];
  readonly scopeTypes = ['manual', 'epic', 'sprint', 'release'];
  readonly environments = ['dev', 'staging', 'prod', 'uat'];

  ngOnInit(): void {
    this.loadProjects();
  }

  // ── Data loading ──────────────────────────────────────────────

  loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: projects => {
        this.projects.set(projects);
        if (projects.length === 1) {
          this.selectedProjectId.set(projects[0].id);
          this.loadTestPlans();
        }
      },
      error: () => this.toast.error('Failed to load projects'),
    });
  }

  loadTestPlans(): void {
    const projectId = this.selectedProjectId();
    if (!projectId) return;

    this.isLoading.set(true);
    this.testPlanService.getByProject(projectId, this.page(), 20).subscribe({
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


  onScopeTypeChange(type: string): void {
    this.scopeType = type;
    this.selectedScopeItems.set([]);
    this.scopeRefs = '';

    if (type === 'manual') return;

    const projectKey = this.projects()
      .find(p => p.id === this.selectedProjectId())
      ?.project_key;

    if (!projectKey) return;

    this.isLoadingScopeRefs.set(true);

    switch (type) {
      case 'sprint':
        this.jiraService.getSprints(projectKey).subscribe({
          next: data => {
            this.sprints.set(data.map(s => ({
              id: String(s.id),
              name: s.name,
            })));
            this.isLoadingScopeRefs.set(false);
          },
        });
        break;
      case 'epic':
        this.jiraService.getEpics(projectKey).subscribe({
          next: data => {
            this.epics.set(data.map(e => ({
                id: e.key,
                name: e.summary,
                key: e.key,
              })));
              this.isLoadingScopeRefs.set(false);
            },
          error: () => {
            this.toast.error('Failed to load epics');
            this.isLoadingScopeRefs.set(false);
          },
        });
        break;
      // case 'release':
      //   this.jiraService.getReleases(projectKey).subscribe({
      //     next: data => {
      //       this.releases.set(data);
      //       this.isLoadingScopeRefs.set(false);
      //     },
      //     error: () => {
      //       this.toast.error('Failed to load releases');
      //       this.isLoadingScopeRefs.set(false);
      //     },
      //   });
        break;
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
    this.loadTestPlans();
  }

  // ── AI Generation ─────────────────────────────────────────────

  openGenerateModal(): void {
    if (!this.selectedProjectId()) {
      this.toast.error('Please select a project first');
      return;
    }
    this.showGenerateModal.set(true);
  }

  closeGenerateModal(): void {
    this.showGenerateModal.set(false);
  }

  generatePlan(): void {
    const projectId = this.selectedProjectId();
    if (!projectId) return;


    let scopeRefsArray: string[];
    if (this.scopeType === 'manual') {
      scopeRefsArray = this.scopeRefs
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
    }
    else {
      scopeRefsArray = this.selectedScopeItems();
    }
    const request: GenerateTestPlanRequest = {
      project_id: projectId,
      scope_type: this.scopeType,
      scope_refs: scopeRefsArray,
      environment: this.environment,
      limit_risks: this.limitRisks,
      limit_stories: this.limitStories,
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
}
