import {
  Component, OnInit, signal, computed, inject,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
import { TestPlanService } from '../../services/test-plan.service';
import { ToastService } from '../../services/toast.service';
import {
  TestPlan,
  TestPlanUpdate,
  EmailRecipient,
  SendEmailRequest,
  GenerateEmailBodyRequest,
  GenerateEmailBodyResponse,
  JiraNotificationRequest,
  TEST_PLAN_STATUS_CONFIG,
  RiskMappingEntry,
} from '../../models/test-plan.model';

type ActiveModal = null | 'share-email' | 'share-jira';

@Component({
  selector: 'app-test-plan-detail',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './test-plan-detail.component.html',
  styleUrl: './test-plan-detail.component.scss',
})
export class TestPlanDetailComponent implements OnInit {
  private service = inject(TestPlanService);
  private router  = inject(Router);
  private route   = inject(ActivatedRoute);
  private toast   = inject(ToastService);

  // ── Core data ─────────────────────────────────────────────────
  plan        = signal<TestPlan | null>(null);
  planId      = signal<string>('');
  isLoading   = signal(true);
  isEditMode  = signal(false);
  editForm    = signal<TestPlanUpdate>({});

  // ── Action states ─────────────────────────────────────────────
  isApproving    = signal(false);
  isRejecting    = signal(false);
  isRegenerating = signal(false);
  isExporting    = signal<'pdf' | 'docx' | null>(null);

  // ── Share modals ──────────────────────────────────────────────
  activeModal     = signal<ActiveModal>(null);

  // Email state (plain properties for ngModel binding)
  emailRecipients: EmailRecipient[] = [{ email: '', role: '', name: '' }];
  emailSubject      = '';
  emailBody         = '';
  additionalContext = '';
  isGeneratingBody  = signal(false);
  isSendingEmail    = signal(false);

  // Jira state (plain properties for ngModel binding)
  jiraProjectKey = '';
  jiraIssueType  = 'Task';
  jiraPriority   = 'Medium';
  jiraSummary    = '';
  jiraDescription = '';
  isSendingJira  = signal(false);


  isDragging = signal(false);
  attachedFiles = signal<File[]>([]);
  attachTestPlanPdf = true;

  // ── Computed ──────────────────────────────────────────────────
  statusConfig = computed(() => {
    const p = this.plan();
    if (!p) return TEST_PLAN_STATUS_CONFIG.draft;
    return TEST_PLAN_STATUS_CONFIG[p.status] ?? TEST_PLAN_STATUS_CONFIG.draft;
  });

  canApprove = computed(() => {
    const s = this.plan()?.status;
    return s === 'ai_proposed' || s === 'draft';
  });

  canRegenerate = computed(() => {
    const s = this.plan()?.status;
    return s === 'ai_proposed' || s === 'draft';
  });

  isApproved = computed(() => {
    const s = this.plan()?.status;
    return s === 'approved' || s === 'active';
  });

  readonly sections = [
    { key: 'description',   label: 'Description' },
    { key: 'objective',     label: 'Objective' },
    { key: 'in_scope',      label: 'In Scope' },
    { key: 'out_of_scope',  label: 'Out of Scope' },
    { key: 'entry_criteria', label: 'Entry Criteria' },
    { key: 'exit_criteria',  label: 'Exit Criteria' },
    { key: 'approach',       label: 'Test Approach' },
    { key: 'assumptions',    label: 'Assumptions' },
    { key: 'constraints',    label: 'Constraints' },
    { key: 'stakeholders',   label: 'Stakeholders & Responsibilities' },
    { key: 'communication',  label: 'Communication Plan' },
  ] as const;

  readonly jiraIssueTypes = ['Task', 'Story', 'Bug'];
  readonly jiraPriorities = ['Highest', 'High', 'Medium', 'Low'];

  // ── Lifecycle ─────────────────────────────────────────────────

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('planId') ?? '';
    this.planId.set(id);
    this.loadPlan(id);
  }

  // Getter pour les techniques triées par fréquence
get sortedTechniques(): { key: string; value: number }[] {
  const dist = this.plan()?.risk_analysis?.aggregated_recommendations?.technique_distribution;
  if (!dist) return [];
  return Object.entries(dist)
    .map(([key, value]) => ({ key, value: value as number }))
    .sort((a, b) => b.value - a.value);
}

// Getter pour scope_refs sécurisé
get scopeRefsDisplay(): string {
  return this.plan()?.scope_refs?.join(', ') || '—';
}

  // Pagination for risk mapping table
riskMappingPage = 1;
riskMappingPageSize = 5;

paginatedRiskMappings(): RiskMappingEntry[] {
  const mappings = this.plan()?.risk_analysis?.mapping_table ?? [];
  const start = (this.riskMappingPage - 1) * this.riskMappingPageSize;
  const end = start + this.riskMappingPageSize;
  return mappings.slice(start, end);
}
totalRiskMappingPages(): number {
  const total = this.plan()?.risk_analysis?.mapping_table?.length ?? 0;
  if (total === 0) return 0;  // ← Évite d'afficher "Page 1 of 1" pour une table vide
  return Math.ceil(total / this.riskMappingPageSize);
}

min(a: number, b: number): number {
  return Math.min(a, b);
}
  // ── Data loading ──────────────────────────────────────────────

  loadPlan(id: string): void {
    this.isLoading.set(true);
    this.riskMappingPage = 1;
    this.service.getById(id).subscribe({
      next: plan => {
        this.plan.set(plan);
        this.isLoading.set(false);
        this.initEditForm(plan);
      },
      error: () => {
        this.toast.error('Test plan not found');
        this.isLoading.set(false);
        this.router.navigate(['/test-plans']);
      },
    });
  }

  constructor(
    private cdr: ChangeDetectorRef 
  ) {}


  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isDragging.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragging.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragging.set(false);
    if (event.dataTransfer?.files) {
      this.addFiles(event.dataTransfer.files);
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) {
      this.addFiles(input.files);
    }
  }

  addFiles(fileList: FileList): void {
    const current = this.attachedFiles();
    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      // Vérifier la taille (max 10MB)
      if (file.size > 10 * 1024 * 1024) {
        this.toast.error(`${file.name} exceeds 10MB limit`);
        continue;
      }
      this.attachedFiles.set([...current, file]);
    }
  }

  removeFile(index: number): void {
    const files = this.attachedFiles();
    this.attachedFiles.set(files.filter((_, i) => i !== index));
  }

  getFileIcon(fileName: string): string {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'pdf': return '📄';
      case 'docx': case 'doc': return '📝';
      case 'xlsx': case 'csv': return '📊';
      case 'png': case 'jpg': case 'jpeg': return '🖼️';
      default: return '📎';
    }
  }

  formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  trackByFn(index: number, item: any): number {
    return index;
  }

  initEditForm(plan: TestPlan): void {
    this.editForm.set({
      title:          plan.title,
      description:    plan.description,
      objective:      plan.objective,
      scope_type:     plan.scope_type,
      scope_refs:     plan.scope_refs,
      in_scope:       plan.in_scope,
      out_of_scope:   plan.out_of_scope,
      test_types:     [...plan.test_types],
      test_levels:    [...plan.test_levels],
      environment:    plan.environment,
      start_date:     plan.start_date,
      end_date:       plan.end_date,
      entry_criteria: plan.entry_criteria,
      exit_criteria:  plan.exit_criteria,
      approach:       plan.approach,
      assumptions:    plan.assumptions,
      constraints:    plan.constraints,
      stakeholders:   plan.stakeholders,
      communication:  plan.communication,
    });
  }

  // ── Edit mode ─────────────────────────────────────────────────

  enterEditMode(): void {
    const plan = this.plan();
    if (plan) this.initEditForm(plan);
    this.isEditMode.set(true);
  }

  cancelEdit(): void {
    this.isEditMode.set(false);
  }

  saveEdit(): void {
    const id = this.planId();
    const form = this.editForm();
    this.service.update(id, form).subscribe({
      next: updated => {
        this.plan.set(updated);
        this.isEditMode.set(false);
        this.toast.success('Test plan updated successfully');
      },
      error: err => this.toast.error(err?.error?.detail || 'Update failed'),
    });
  }

  updateField(key: keyof TestPlanUpdate, value: any): void {
    this.editForm.update(f => ({ ...f, [key]: value }));
  }

  // ── Approval workflow ─────────────────────────────────────────

  approve(): void {
    if (!confirm('Approve this test plan? This will mark it as officially approved.')) return;
    this.isApproving.set(true);
    this.service.approve(this.planId()).subscribe({
      next: updated => {
        this.plan.set(updated);
        this.isApproving.set(false);
        this.toast.success('Test plan approved!');
      },
      error: err => {
        this.isApproving.set(false);
        this.toast.error(err?.error?.detail || 'Approval failed');
      },
    });
  }

  reject(): void {
    if (!confirm('Reject the AI draft? The plan will return to draft status.')) return;
    this.isRejecting.set(true);
    this.service.reject(this.planId()).subscribe({
      next: updated => {
        this.plan.set(updated);
        this.isRejecting.set(false);
        this.toast.success('Plan reset to draft');
      },
      error: err => {
        this.isRejecting.set(false);
        this.toast.error(err?.error?.detail || 'Rejection failed');
      },
    });
  }

  regenerate(): void {
    if (!confirm('Regenerate this test plan? The current AI draft will be replaced.')) return;
    this.isRegenerating.set(true);
    this.service.regenerate(this.planId()).subscribe({
      next: res => {
        this.isRegenerating.set(false);
        this.toast.success('New draft generated!');
        // navigate to new plan
        this.router.navigate(['/test-plans', res.test_plan.id]);
      },
      error: err => {
        this.isRegenerating.set(false);
        this.toast.error(err?.error?.detail || 'Regeneration failed');
      },
    });
  }

  // ── Export ────────────────────────────────────────────────────

  exportPdf(): void {
    this.isExporting.set('pdf');
    this.service.exportPdf(this.planId()).subscribe({
      next: blob => {
        this.service.downloadBlob(blob, `test_plan_${this.planId().slice(0, 8)}.pdf`);
        this.isExporting.set(null);
        this.toast.success('PDF downloaded');
      },
      error: () => {
        this.isExporting.set(null);
        this.toast.error('PDF export failed. Make sure reportlab is installed.');
      },
    });
  }

  exportDocx(): void {
    this.isExporting.set('docx');
    this.service.exportDocx(this.planId()).subscribe({
      next: blob => {
        this.service.downloadBlob(blob, `test_plan_${this.planId().slice(0, 8)}.docx`);
        this.isExporting.set(null);
        this.toast.success('DOCX downloaded');
      },
      error: () => {
        this.isExporting.set(null);
        this.toast.error('DOCX export failed. Make sure python-docx is installed.');
      },
    });
  }

  // ── Email sharing ─────────────────────────────────────────────

  openEmailModal(): void {
    this.emailRecipients = [{ email: '', role: '', name: '' }];
    this.emailSubject = '';
    this.emailBody = '';
    this.additionalContext = '';
    this.activeModal.set('share-email');
  }

  addRecipient(): void {
    this.emailRecipients.push({
      email: '',
      role: '',
      name: ''
    });
  }

  removeRecipient(i: number): void {
    this.emailRecipients = this.emailRecipients.filter((_: EmailRecipient, idx: number) => idx !== i);
  }

  updateRecipient(i: number, field: keyof EmailRecipient, value: string): void {
    const updated = [...this.emailRecipients];
    updated[i] = { ...updated[i], [field]: value };
    this.emailRecipients = updated;
  }

  generateEmailBody(): void {
    const valid = this.emailRecipients.filter((r: EmailRecipient) => r.email && r.role);
    if (!valid.length) {
      this.toast.error('Add at least one recipient with email and role');
      return;
    }

    this.isGeneratingBody.set(true);
    const req: GenerateEmailBodyRequest = {
      recipients: valid,
      additional_context: this.additionalContext || undefined,
    };

    this.service.generateEmailBody(this.planId(), req).subscribe({
      next: (res: GenerateEmailBodyResponse) => {
        this.emailSubject = res.subject;
        this.emailBody = res.body;
        this.isGeneratingBody.set(false);
      },
      error: () => {
        this.isGeneratingBody.set(false);
        this.toast.error('Body generation failed');
      },
    });
  }

  sendEmail(): void {
    const valid = this.emailRecipients.filter((r: EmailRecipient) => r.email && r.role);
    if (!valid.length) {
      this.toast.error('Add at least one valid recipient');
      return;
    }

    this.isSendingEmail.set(true);
    const req: SendEmailRequest = {
      recipients: valid,
      subject:       this.emailSubject || undefined,
      body:          this.emailBody || undefined,
      generate_body: !this.emailSubject && !this.emailBody,
    };

    this.service.sendEmail(this.planId(), req).subscribe({
      next: () => {
        this.isSendingEmail.set(false);
        this.activeModal.set(null);
        this.toast.success(`Email sent to ${valid.length} recipient(s)`);
      },
      error: err => {
        this.isSendingEmail.set(false);
        this.toast.error(err?.error?.detail || 'Email sending failed');
      },
    });
  }

  // ── Jira notification ─────────────────────────────────────────

  openJiraModal(): void {
    const plan = this.plan();
    this.jiraProjectKey = '';
    this.jiraIssueType = 'Task';
    this.jiraPriority = 'Medium';
    this.jiraSummary = plan ? `[Test Plan] ${plan.title}` : '';
    this.jiraDescription = '';
    this.activeModal.set('share-jira');
  }

  sendJiraNotification(): void {
    if (!this.jiraProjectKey) {
      this.toast.error('Please enter a Jira project key');
      return;
    }

    this.isSendingJira.set(true);
    const req: JiraNotificationRequest = {
      project_key:  this.jiraProjectKey,
      summary:      this.jiraSummary || undefined,
      description:  this.jiraDescription || undefined,
      issue_type:   this.jiraIssueType,
      priority:     this.jiraPriority,
    };

    this.service.sendJiraNotification(this.planId(), req).subscribe({
      next: res => {
        this.isSendingJira.set(false);
        this.activeModal.set(null);
        this.toast.success(`Jira ticket ${res.issue_key} created!`);
      },
      error: err => {
        this.isSendingJira.set(false);
        this.toast.error(err?.error?.detail || 'Jira ticket creation failed');
      },
    });
  }

  // ── Helpers ───────────────────────────────────────────────────

  closeModal(): void {
    this.activeModal.set(null);
  }

  goBack(): void {
    this.router.navigate(['/test-plans']);
  }

  getPlanValue(key: string): string {
    const p = this.plan() as any;
    return p ? (p[key] ?? '') : '';
  }

  getEditValue(key: string): string {
    return (this.editForm() as any)[key] ?? '';
  }

  formatDate(d?: string): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
    });
  }

  chipList(arr?: string[]): string {
    return arr?.join(', ') ?? '—';
  }

  
get aggregatedRecommendations() {
  return this.plan()?.risk_analysis?.aggregated_recommendations ?? null;
}

get testDepthDistribution() {
  return this.aggregatedRecommendations?.test_depth_distribution ?? {
    comprehensive: 0,
    thorough: 0,
    standard: 0,
    smoke: 0
  };
}

get effortBreakdown() {
  return this.aggregatedRecommendations?.effort_breakdown ?? {
    critical_effort: '0%',
    high_effort: '0%',
    medium_effort: '0%',
    low_effort: '0%'
  };
}
  
}
