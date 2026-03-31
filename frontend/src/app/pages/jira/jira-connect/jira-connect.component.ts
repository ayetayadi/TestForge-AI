import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MaterialModule } from 'src/app/material.module';
import { JiraService, JiraStatus, JiraProject, UserStory } from '../../../services/jira.service';
import { ActivatedRoute } from '@angular/router';

@Component({
  selector: 'app-jira-connect',
  standalone: true,
  imports: [CommonModule, MaterialModule, FormsModule],
  templateUrl: './jira-connect.component.html',
})
export class JiraConnectComponent implements OnInit {
  status: JiraStatus = { connected: false };

  // Projects
  projects: JiraProject[] = [];
  loadingProjects = false;
  selectedProject: JiraProject | null = null;

  // Stories
  stories: UserStory[] = [];
  loadingStories = false;
  selectedStories: UserStory[] = [];

  // UI state
  connecting = false;
  disconnecting = false;
  errorMessage = '';

  // Table columns
  displayedColumns = ['select', 'key', 'summary', 'status', 'priority', 'assignee'];

  constructor(
    private jiraService: JiraService,
    private route: ActivatedRoute,
  ) {}

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      if (params['error']) {
        this.errorMessage = 'Failed to connect to Jira. Please try again.';
      }
      this.checkStatus();
    });
  }

  checkStatus() {
    this.jiraService.getStatus().subscribe({
      next: (s) => {
        console.log('Jira status:', s);
        this.status = s;
        if (s.connected) this.loadProjects();
      },
      error: (err) => {
        console.error('checkStatus error:', err);
        this.errorMessage = 'Failed to check Jira status.';
      }
    });
  }

  loadProjects() {
    this.loadingProjects = true;
    this.errorMessage = '';

    this.jiraService.getProjects().subscribe({
      next: (p) => {
        console.log('Projects loaded:', p);
        this.projects = Array.isArray(p) ? p : [];
        this.loadingProjects = false;
      },
      error: (err) => {
        console.error('loadProjects error:', err);
        this.errorMessage = 'Failed to load Jira projects.';
        this.loadingProjects = false;
        this.projects = [];
      }
    });
  }

  onProjectChange(project: JiraProject) {
    this.selectedProject = project;
    this.stories = [];
    this.selectedStories = [];
    this.loadStories(project.key);
  }

  loadStories(projectKey: string) {
    this.loadingStories = true;
    this.errorMessage = '';

    this.jiraService.getUserStories(projectKey).subscribe({
      next: (s) => {
        const storiesArray = Array.isArray(s) ? s : [];
        this.stories = storiesArray.map(story => ({ ...story, selected: false }));
        this.loadingStories = false;
      },
      error: (err) => {
        console.error('Failed to fetch stories:', err);
        this.errorMessage = 'Failed to fetch user stories.';
        this.loadingStories = false;
        this.stories = [];
      }
    });
  }

  toggleStory(story: UserStory) {
    story.selected = !story.selected;
    this.selectedStories = this.stories.filter(s => s.selected);
  }

  toggleAll(checked: boolean) {
    this.stories.forEach(s => s.selected = checked);
    this.selectedStories = checked ? [...this.stories] : [];
  }

  get allSelected(): boolean {
    return this.stories.length > 0 && this.stories.every(s => s.selected);
  }

  get someSelected(): boolean {
    return this.stories.some(s => s.selected) && !this.allSelected;
  }

  connectJira() {
    this.connecting = true;
    this.jiraService.getAuthUrl().subscribe({
      next: (res) => {
        const popup = window.open(res.url, 'Connect Jira', 'width=600,height=700,scrollbars=yes');
        const timer = setInterval(() => {
          if (popup?.closed) {
            clearInterval(timer);
            this.connecting = false;
            this.checkStatus();
          }
        }, 500);
      },
      error: () => { this.connecting = false; }
    });
  }

  disconnect() {
    if (!confirm('Disconnect Jira?')) return;
    this.disconnecting = true;
    this.jiraService.disconnect().subscribe({
      next: () => {
        this.disconnecting = false;
        this.status = { connected: false };
        this.projects = [];
        this.stories = [];
        this.selectedProject = null;
      }
    });
  }

  generateTests() {
    // Will be implemented in next step
    console.log('Selected stories for generation:', this.selectedStories);
  }
  getStatusColor(status: string): string {
    const map: Record<string, string> = {
      'To Do': '#6b778c',
      'In Progress': '#0052cc',
      'Done': '#00875a',
      'In Review': '#ff8b00',
    };
    return map[status] || '#6b778c';
  }

  getPriorityColor(priority: string): string {
    const map: Record<string, string> = {
      'Highest': '#d04437',
      'High': '#e05a00',
      'Medium': '#f79232',
      'Low': '#2d8738',
      'Lowest': '#57a55a',
    };
    return map[priority] || '#6b778c';
  }

}

