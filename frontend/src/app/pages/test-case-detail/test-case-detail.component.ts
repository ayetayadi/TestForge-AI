// test-case-detail.component.ts
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { TestCaseService } from '../../services/test-case.service';
import { ToastService } from '../../services/toast.service';
import { TestCase, TestStep, Priority, TestCaseStatus } from '../../models/test-case.model';
import { PlaywrightE2EService } from 'src/app/services/playwright-e2e.service';
import { ScriptListResponse } from 'src/app/models/playwright.models';
import { TestomatService } from '../../services/testomat.service';

@Component({
  selector: 'app-test-case-detail',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './test-case-detail.component.html',
  styleUrl: './test-case-detail.component.scss'
})
export class TestCaseDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private testCaseService = inject(TestCaseService);
  private toastService = inject(ToastService);
  private playwrightService = inject(PlaywrightE2EService);
  private fb = inject(FormBuilder);

  testCase: TestCase | null = null;
  isLoading = true;
  isEditing = false;
  isSaving = false;
  activeTab: 'steps' | 'scenario' | 'data' = 'steps';

  generatingIds = signal<Set<string>>(new Set());
  hasScripts = signal<boolean>(false);
  checkingScripts = signal<boolean>(false);
  isPushingToTestomat = signal(false);

  private testomatService = inject(TestomatService);

  editForm: FormGroup;

  constructor() {
    this.editForm = this.fb.group({
      title: ['', [Validators.required, Validators.minLength(3)]],
      description: [''],
      priority: ['medium'],
      preconditions: [[]],
      postconditions: [[]],
      steps: [[]],
      gherkin_source: [''],
      test_data: [null],
      expected_results: [[]],
      tags: [[]],
      locators: [[]],
      is_active: [true]
    });
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.loadTestCase(id);
      this.checkIfScriptsExist(id);
    } else {
      this.toastService.error('Error', 'Test case ID not found');
      this.router.navigate(['/test-cases']);
    }
  }

  loadTestCase(id: string): void {
    this.isLoading = true;
    this.testCaseService.getTestCaseById(id).subscribe({
      next: (testCase) => {
        this.testCase = testCase;
        this.initForm();
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Error loading test case:', error);
        this.toastService.error('Error', 'Failed to load test case');
        this.isLoading = false;
        this.router.navigate(['/test-cases']);
      }
    });
  }

initForm(): void {
  if (this.testCase) {
    this.editForm.patchValue({
      title: this.testCase.title,
      description: this.testCase.description || '',
      priority: this.testCase.priority || 'medium',
      preconditions: this.toJsonString(this.testCase.preconditions),
      postconditions: this.toJsonString(this.testCase.postconditions),
      steps: this.toJsonString(this.testCase.steps),
      gherkin_source: this.testCase.gherkin_source || '',
      test_data: this.toJsonString(this.testCase.test_data),
      expected_results: this.toJsonString(this.testCase.expected_results),
      tags: this.testCase.tags || [],
      locators: this.testCase.locators || [],
      is_active: this.testCase.is_active
    });
  }
}

private toJsonString(value: any): string {
  if (!value) return '';
  if (typeof value === 'string') {
    // Vérifier si c'est déjà un JSON string valide
    try {
      JSON.parse(value);
      return value; // C'est déjà du JSON
    } catch {
      return value; // C'est du texte simple (ex: gherkin)
    }
  }
  return JSON.stringify(value, null, 2);
}

  toggleEdit(): void {
    this.isEditing = !this.isEditing;
    if (!this.isEditing) {
      this.initForm();
    }
  }

saveChanges(): void {
  if (this.editForm.invalid) {
    this.toastService.warning('Warning', 'Please fill all required fields');
    return;
  }

  this.isSaving = true;
  const formValue = this.editForm.value;
  
  // S'assurer que les champs JSON sont bien des objets/tableaux
  const updatedData = {
    ...formValue,
    preconditions: this.ensureArray(formValue.preconditions),
    postconditions: this.ensureArray(formValue.postconditions),
    steps: this.ensureArray(formValue.steps),
    test_data: this.ensureObject(formValue.test_data),
    expected_results: this.ensureArray(formValue.expected_results),
  };
  
  this.testCaseService.updateTestCase(this.testCase!.id, updatedData).subscribe({
    next: (updatedTestCase) => {
      this.testCase = updatedTestCase;
      this.isEditing = false;
      this.isSaving = false;
      this.toastService.success('Success', 'Test case updated successfully');
    },
    error: (error) => {
      console.error('Error updating test case:', error);
      this.toastService.error('Error', 'Failed to update test case');
      this.isSaving = false;
    }
  });
}

private ensureArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

private ensureObject(value: any): any {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : null;
    } catch {
      return null;
    }
  }
  return null;
}

  deleteTestCase(): void {
    if (confirm('Are you sure you want to delete this test case? This action cannot be undone.')) {
      this.testCaseService.deleteTestCase(this.testCase!.id).subscribe({
        next: () => {
          this.toastService.success('Deleted', 'Test case deleted successfully');
          this.router.navigate(['/test-cases']);
        },
        error: (error) => {
          console.error('Error deleting test case:', error);
          this.toastService.error('Error', 'Failed to delete test case');
        }
      });
    }
  }

  goBack(): void {
    this.router.navigate(['/test-cases']);
  }

  pushToTestomat(): void {
    if (!this.testCase) return;
    this.isPushingToTestomat.set(true);
    this.testomatService.pushTestCases([this.testCase.id]).subscribe({
      next: res => {
        this.isPushingToTestomat.set(false);
        this.toastService.success(
          'Pushed to Testomat',
          `${res.pushed_count} test case pushed successfully`
        );
      },
      error: err => {
        this.isPushingToTestomat.set(false);
        const detail = err?.error?.detail || 'Push failed';
        if (detail.includes('not connected')) {
          this.toastService.error('Not connected', 'Go to Integrations → Testomat.io to connect first');
        } else {
          this.toastService.error('Push failed', detail);
        }
      },
    });
  }

  
generatePlaywrightScript(): void {
  if (!this.testCase) return;

  // Ajouter l'ID à la liste des générations en cours
  const current = new Set(this.generatingIds());
  current.add(this.testCase.id);
  this.generatingIds.set(current);

  this.playwrightService.generateScript({ test_case_id: this.testCase.id }).subscribe({
    next: (res) => {
      const updated = new Set(this.generatingIds());
      updated.delete(this.testCase!.id);
      this.generatingIds.set(updated);

      if (res.status === 'generated') {
        this.toastService.success('Script generated', `v${res.version_number} ready`);
        this.router.navigate(['/playwright-scripts', this.testCase!.id]);
      } else {
        this.toastService.error('Generation failed', res.error ?? 'Unknown error');
      }
    },
    error: (err) => {
      const updated = new Set(this.generatingIds());
      updated.delete(this.testCase!.id);
      this.generatingIds.set(updated);
      this.toastService.error('Generation failed', err.message);
    },
  });
}

checkIfScriptsExist(testCaseId: string): void {
  this.checkingScripts.set(true);
  this.playwrightService.getScripts(testCaseId).subscribe({
    next: (response: ScriptListResponse) => {
      // response.scripts est le tableau de ScriptInfo
      this.hasScripts.set(response.scripts && response.scripts.length > 0);
      this.checkingScripts.set(false);
    },
    error: () => {
      this.hasScripts.set(false);
      this.checkingScripts.set(false);
    }
  });
}

viewScripts(): void {
  if (this.testCase) {
    this.router.navigate(['/playwright-scripts', this.testCase.id]);
  }
}

  getPriorityClass(priority: string | null): string {
    if (!priority) return 'priority-medium';
    const classes: Record<string, string> = {
      'critical': 'priority-critical',
      'high': 'priority-high',
      'medium': 'priority-medium',
      'low': 'priority-low'
    };
    return classes[priority] || 'priority-medium';
  }

  getStatusLabel(isActive: boolean): string {
    return isActive ? 'Active' : 'Archived';
  }

  formatJson(data: any): string {
    if (!data) return '';
    try {
      return JSON.stringify(data, null, 2);
    } catch {
      return String(data);
    }
  }

visibleStepsLimit: number = 3;

// Getter pour les steps visibles
get visibleSteps() {
  if (!this.testCase?.steps) return [];
  return this.testCase.steps.slice(0, this.visibleStepsLimit);
}

// Getter pour les steps cachées
get hiddenStepsCount() {
  if (!this.testCase?.steps) return 0;
  return this.testCase.steps.length - this.visibleStepsLimit;
}

// Getter pour savoir s'il y a des steps cachées
get hasHiddenSteps() {
  return this.hiddenStepsCount > 0;
}

// Fonction pour afficher plus
showMoreSteps() {
  this.visibleStepsLimit = this.testCase?.steps?.length || this.visibleStepsLimit;
}

// Fonction pour tout afficher
showAllSteps() {
  this.visibleStepsLimit = this.testCase?.steps?.length || this.visibleStepsLimit;
}

// (Optionnel) Fonction pour reset à 3
resetStepsView() {
  this.visibleStepsLimit = 3;
}

// Pour préconditions
visiblePreconditionsLimit: number = 3;

get visiblePreconditions() {
  return this.preconditions.slice(0, this.visiblePreconditionsLimit);
}

get hiddenPreconditionsCount() {
  return this.preconditions.length - this.visiblePreconditionsLimit;
}

get hasHiddenPreconditions() {
  return this.hiddenPreconditionsCount > 0;
}

showAllPreconditions() {
  this.visiblePreconditionsLimit = this.preconditions.length;
}

resetPreconditionsView() {
  this.visiblePreconditionsLimit = 3;
}

// Pour postconditions (même logique)
visiblePostconditionsLimit: number = 3;

get visiblePostconditions() {
  return (this.testCase?.postconditions || []).slice(0, this.visiblePostconditionsLimit);
}

get hiddenPostconditionsCount() {
  return (this.testCase?.postconditions || []).length - this.visiblePostconditionsLimit;
}

get hasHiddenPostconditions() {
  return this.hiddenPostconditionsCount > 0;
}

showAllPostconditions() {
  this.visiblePostconditionsLimit = this.testCase?.postconditions?.length || 3;
}

resetPostconditionsView() {
  this.visiblePostconditionsLimit = 3;
}

parseJson(event: Event, field: string): void {
  const textarea = event.target as HTMLTextAreaElement;
  const value = textarea.value.trim();
  
  if (!value) {
    this.editForm.patchValue({ [field]: value });
    return;
  }
  
  try {
    const parsed = JSON.parse(value);
    // Si c'est un tableau ou objet valide, le stocker comme tel
    if (typeof parsed === 'object') {
      this.editForm.patchValue({ [field]: parsed }, { emitEvent: false });
    } else {
      this.editForm.patchValue({ [field]: value }, { emitEvent: false });
    }
  } catch (e) {
    // Si ce n'est pas du JSON valide, garder la string telle quelle (ex: gherkin)
    this.editForm.patchValue({ [field]: value }, { emitEvent: false });
  }
}
  getPriorityString(priority: string | null): string {
    return priority || 'medium';
  }

  // ── Gherkin parsing ──────────────────────────────────────────────────────

  getGherkinLines(): { type: string; text: string }[] {
    if (!this.testCase?.gherkin_source) return [];
    return this.testCase.gherkin_source.split('\n').map(line => {
      const t = line.trim();
      if (t.startsWith('@'))                         return { type: 'tag',      text: line };
      if (/^Feature:/i.test(t))                      return { type: 'feature',  text: line };
      if (/^Scenario( Outline)?:/i.test(t))          return { type: 'scenario', text: line };
      if (/^(Given|When|Then|And|But)\b/i.test(t))  return { type: 'step',     text: line };
      if (t.startsWith('|'))                         return { type: 'table',    text: line };
      if (t.startsWith('#'))                         return { type: 'comment',  text: line };
      return { type: 'other', text: line };
    });
  }

  get preconditions(): string[] {
    return this.testCase?.preconditions || [];
  }

  get testDataEntries(): { key: string; value: string }[] {
    if (!this.testCase?.test_data) return [];
    return Object.entries(this.testCase.test_data).map(([key, value]) => ({
      key,
      value: String(value),
    }));
  }

  getTestTypeClass(testType: string | null): string {
    const map: Record<string, string> = {
      positive:  'type-positive',
      negative:  'type-negative',
      boundary:  'type-boundary',
      edge:      'type-edge',
      edge_case: 'type-edge',
      smoke:     'type-smoke',
    };
    return map[testType?.toLowerCase() ?? ''] ?? 'type-default';
  }

  getTagClass(tag: string): string {
    const t = tag.toLowerCase();
    if (t.includes('positive') || t === 'smoke') return 'tag-positive';
    if (t.includes('negative'))                  return 'tag-negative';
    if (t.includes('regression'))                return 'tag-regression';
    if (t.includes('boundary') || t.includes('edge')) return 'tag-boundary';
    if (['critical','high','medium','low'].includes(t)) return 'tag-priority';
    return 'tag-default';
  }



  // Dans test-case-detail.component.ts

// ── Copy to clipboard ─────────────────────────────────────────────────
async copyToClipboard(content: string, label: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(
      typeof content === 'string' ? content : JSON.stringify(content, null, 2)
    );
    this.toastService.success('Copied', `${label} copied to clipboard`);
  } catch (err) {
    // Fallback pour les navigateurs plus anciens
    const textarea = document.createElement('textarea');
    textarea.value = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    this.toastService.success('Copied', `${label} copied to clipboard`);
  }
}

// Méthodes spécifiques pour chaque section
copyPreconditions(): void {
  const content = this.testCase?.preconditions || [];
  this.copyToClipboard(JSON.stringify(content, null, 2), 'Preconditions');
}

copySteps(): void {
  const content = this.testCase?.steps || [];
  this.copyToClipboard(JSON.stringify(content, null, 2), 'Test Steps');
}

copyPostconditions(): void {
  const content = this.testCase?.postconditions || [];
  this.copyToClipboard(JSON.stringify(content, null, 2), 'Postconditions');
}

copyGherkin(): void {
  const content = this.testCase?.gherkin_source || '';
  this.copyToClipboard(content, 'Gherkin Scenario');
}

copyTestData(): void {
  const content = this.testCase?.test_data || {};
  this.copyToClipboard(JSON.stringify(content, null, 2), 'Test Data');
}

copyExpectedResults(): void {
  const content = this.testCase?.expected_results || [];
  this.copyToClipboard(JSON.stringify(content, null, 2), 'Expected Results');
}
}