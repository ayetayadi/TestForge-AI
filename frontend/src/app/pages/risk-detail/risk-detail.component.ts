import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
import { RiskService } from '../../services/risk.service';
import { StoriesService } from '../../services/stories.service';
import { ToastService } from '../../services/toast.service';
import { Risk, RiskLevel, RISK_LEVEL_CONFIG, classifyLevel } from '../../models/risk.model';
import { UserStory } from '../../models/user_story.model';

@Component({
  selector: 'app-risk-detail',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './risk-detail.component.html',
  styleUrls: ['./risk-detail.component.scss']
})
export class RiskDetailComponent implements OnInit {
  private riskService = inject(RiskService);
  private storiesService = inject(StoriesService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private toast = inject(ToastService);

  // ── Data ─────────────────────────────────────────────────
  risk = signal<Risk | null>(null);
  allStories = signal<UserStory[]>([]);
  loading = signal(true);
  notFound = signal(false);
  
  // ── Edition ──────────────────────────────────────────────
  editingMitigation = signal(false);
  mitigationDraft = '';
  saving = signal(false);
  
  editingFormula = signal(false);
  probabilityDraft = 3;
  impactDraft = 3;
  savingFormula = signal(false);

  // ── Configuration ────────────────────────────────────────
  readonly levelConfig = RISK_LEVEL_CONFIG;

  // ── Computed ─────────────────────────────────────────────
  storyMap = computed((): Map<string, UserStory> => {
    const map = new Map<string, UserStory>();
    for (const story of this.allStories()) {
      map.set(story.id, story);
    }
    return map;
  });

  mitigationSteps = computed((): string[] => {
    const mitigation = this.risk()?.mitigation;
    if (!mitigation) return [];
    return mitigation.split('\n').filter(step => step.trim().length > 0);
  });

  // ✅ Source checks
  isFromApprovedVersion = computed((): boolean => {
    return this.risk()?.source === 'approved_version';
  });

  isFromLLM = computed((): boolean => {
    return this.risk()?.source === 'llm';
  });

  isHumanModified = computed((): boolean => {
    return this.risk()?.source === 'human_modified';
  });

  isManual = computed((): boolean => {
    return this.risk()?.source === 'manual';
  });

  canModify = computed((): boolean => {
    return true;
  });

  projectId = computed((): string | null => {
    const risk = this.risk();
    if (!risk?.user_story_id) return null;
    return this.storyMap().get(risk.user_story_id)?.project_id || null;
  });

  computedScoreDraft = computed((): number => {
    return this.probabilityDraft * this.impactDraft;
  });

  computedLevelDraft = computed((): RiskLevel => {
    return classifyLevel(this.computedScoreDraft());
  });

  // ✅ Test recommendations
  testRecommendations = computed(() => {
    const level = this.risk()?.level || 'medium';
    return this.getTestRecommendations(level);
  });

  // ── Lifecycle ────────────────────────────────────────────
  ngOnInit(): void {
    this.loadRisk();
    this.loadAllStories();
  }

  loadRisk(): void {
    const riskId = this.route.snapshot.paramMap.get('riskId');
    if (!riskId) {
      this.notFound.set(true);
      this.loading.set(false);
      return;
    }
    this.riskService.getRiskById(riskId).subscribe({
      next: (risk) => {
        this.risk.set(risk);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Failed to load risk:', err);
        this.notFound.set(true);
        this.loading.set(false);
        this.toast.error('Failed to load risk');
      }
    });
  }

  loadAllStories(): void {
    this.storiesService.getAllStories().subscribe({
      next: (stories) => this.allStories.set(stories),
      error: (err) => console.error('Failed to load stories:', err)
    });
  }

  // ── User Story Helpers ───────────────────────────────────
  getStoryDescription(): string | null {
    const risk = this.risk();
    if (!risk) return null;

    if (risk.source_story_text) {
      return risk.source_story_text;
    }

    if (!risk.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    return story?.description || null;
  }

  getStoryAcceptanceCriteria(): string[] | null {
    const risk = this.risk();
    if (!risk) return null;

    if (risk.source_acceptance_criteria) {
      try {
        const parsed = JSON.parse(risk.source_acceptance_criteria);
        if (Array.isArray(parsed)) {
          return parsed.filter((c: string) => c && c.trim().length > 0);
        }
      } catch {
        console.warn('Failed to parse source_acceptance_criteria JSON');
      }
    }

    if (!risk.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    const criteria = story?.acceptance_criteria;
    if (!criteria || !Array.isArray(criteria)) return null;
    return criteria.filter((c: string) => c && c.trim().length > 0);
  }

  usLabel(): string {
    const risk = this.risk();
    if (!risk) return '—';
    return risk.user_story_key ?? 
           this.storyMap().get(risk.user_story_id || '')?.issue_key ?? 
           '—';
  }

  usTitle(): string | null {
    const risk = this.risk();
    if (!risk?.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    return story?.title || null;
  }

  // ── Mitigation Editing ───────────────────────────────────
  startEditMitigation(): void {
    this.mitigationDraft = this.risk()?.mitigation || '';
    this.editingMitigation.set(true);
  }

  cancelEdit(): void {
    this.editingMitigation.set(false);
    this.mitigationDraft = '';
  }

  saveMitigation(): void {
    const risk = this.risk();
    if (!risk) return;

    this.saving.set(true);
    this.riskService.updateMitigation(risk.id, this.mitigationDraft).subscribe({
      next: (updatedRisk) => {
        this.risk.set(updatedRisk);
        this.editingMitigation.set(false);
        this.mitigationDraft = '';
        this.saving.set(false);
        this.toast.success('Mitigation saved');
      },
      error: () => {
        this.saving.set(false);
        this.toast.error('Failed to save mitigation');
      }
    });
  }

  // ── Formula Editing (P/I Correction) ─────────────────────
  startEditFormula(): void {
    const risk = this.risk();
    if (!risk) return;
    this.probabilityDraft = risk.probability;
    this.impactDraft = risk.impact;
    this.editingFormula.set(true);
  }

  cancelEditFormula(): void {
    this.editingFormula.set(false);
  }

  onProbabilityChange(value: number): void {
    this.probabilityDraft = Math.min(5, Math.max(1, Math.round(value)));
  }

  onImpactChange(value: number): void {
    this.impactDraft = Math.min(5, Math.max(1, Math.round(value)));
  }

  probBandLabelDraft(): string {
    const labels = ['Rare', 'Unlikely', 'Possible', 'Likely', 'Almost Certain'];
    return labels[this.probabilityDraft - 1] || 'Unknown';
  }

  impactLabelDraft(): string {
    const labels = ['Negligible', 'Minor', 'Moderate', 'Major', 'Critical'];
    return labels[this.impactDraft - 1] || 'Unknown';
  }

  // ✅ Utilise humanCorrectRisk() au lieu de updateRisk()
  saveFormula(): void {
    const risk = this.risk();
    if (!risk) return;

    this.savingFormula.set(true);
    this.riskService.humanCorrectRisk(risk.id, {
      probability: this.probabilityDraft,
      impact: this.impactDraft,
      comment: `Manual correction: P${risk.probability}→${this.probabilityDraft}, I${risk.impact}→${this.impactDraft}`
    }).subscribe({
      next: (updatedRisk) => {
        this.risk.set(updatedRisk);
        this.editingFormula.set(false);
        this.savingFormula.set(false);
        this.toast.success('Risk score updated');
      },
      error: () => {
        this.savingFormula.set(false);
        this.toast.error('Failed to update risk score');
      }
    });
  }

  // ── Risk Decision ────────────────────────────────────────
  acceptRisk(accepted: boolean): void {
    const risk = this.risk();
    if (!risk) return;
    
    this.riskService.acceptRisk(risk.id, accepted).subscribe({
      next: (updatedRisk) => {
        this.risk.set(updatedRisk);
        const action = accepted ? 'accepted' : 'rejected';
        this.toast.success(`Risk ${action} successfully!`);
        setTimeout(() => {
          const projectId = this.projectId();
          this.router.navigate(['/risk-analysis'], {
            queryParams: projectId ? { project: projectId } : {}
          });
        }, 1000);
      },
      error: () => {
        this.toast.error('Failed to update risk status');
      }
    });
  }

  // ── Navigation ───────────────────────────────────────────
  goBack(): void {
    const projectId = this.projectId();
    this.router.navigate(['/risk-analysis'], {
      queryParams: projectId ? { project: projectId } : {}
    });
  }

  // ── UI Helpers ───────────────────────────────────────────
  formatScore(score: number): string {
    return score.toString();
  }

  probPercent(p: number): number {
    return Math.round(p / 5 * 100);
  }

  // ✅ Labels corrigés (document original)
  probBandLabel(): string {
    const labels = ['Rare', 'Unlikely', 'Possible', 'Likely', 'Almost Certain'];
    return labels[(this.risk()?.probability ?? 1) - 1] || 'Unknown';
  }

  impactLabel(): string {
    const impact = this.risk()?.impact ?? 0;
    const labels = ['Negligible', 'Minor', 'Moderate', 'Major', 'Critical'];
    return labels[impact - 1] || 'Unknown';
  }

  acceptanceLabel(val: boolean | null): string {
    if (val === true) return 'Accepted';
    if (val === false) return 'Rejected';
    return 'Pending Review';
  }

  scoreBarPosition(score: number): number {
    return (score / 25) * 100;
  }

  // ✅ Test recommendations (document original)
  getTestRecommendations(level: string): { techniques: string[]; effort: string } {
    const config: Record<string, { techniques: string[]; effort: string }> = {
      critical: { techniques: ['unit', 'integration', 'e2e', 'performance', 'security'], effort: '60%'},
      high:     { techniques: ['unit', 'integration', 'e2e'], effort: '25%' },
      medium:   { techniques: ['unit', 'integration'], effort: '10%' },
      low:      { techniques: ['smoke'], effort: '5%' },
    };
    return config[level] || config['medium'];
  }
}