import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { ToastService } from 'src/app/services/toast.service';
import { UserService } from 'src/app/services/user.service';
import {
  JiraProject,
  JiraService,
  JiraStatus,
  UserStory,
} from '../../../services/jira.service';

function passwordMatchValidator(control: AbstractControl): ValidationErrors | null {
  const newPassword = control.get('new_password')?.value;
  const confirmPassword = control.get('confirm_password')?.value;

  if (newPassword && confirmPassword && newPassword !== confirmPassword) {
    return { passwordMismatch: true };
  }
  return null;
}

@Component({
  selector: 'app-jira-connect',
  standalone: true,
  templateUrl: './jira-connect.component.html',
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatButtonModule,
    MatChipsModule,
  ],
})
export class JiraConnectComponent implements OnInit {
  status: JiraStatus = { connected: false };

  projects: JiraProject[] = [];
  loadingProjects = false;
  selectedProject: JiraProject | null = null;

  stories: UserStory[] = [];
  loadingStories = false;
  selectedStories: UserStory[] = [];

  connecting = false;
  disconnecting = false;
  errorMessage = '';

  changePasswordForm!: FormGroup;
  changingPassword = false;

  hideCurrentPassword = true;
  hideNewPassword = true;
  hideConfirmPassword = true;

  constructor(
    private fb: FormBuilder,
    private jiraService: JiraService,
    private userService: UserService,
    private toastService: ToastService,
    private route: ActivatedRoute
  ) {}

  ngOnInit(): void {
    this.changePasswordForm = this.fb.group(
      {
        current_password: ['', Validators.required],
        new_password: ['', [Validators.required, Validators.minLength(8)]],
        confirm_password: ['', Validators.required],
      },
      { validators: passwordMatchValidator }
    );

    this.route.queryParams.subscribe((params) => {
      if (params['error']) {
        this.errorMessage = 'Failed to connect to Jira. Please try again.';
      }
      this.checkStatus();
    });
  }

  checkStatus(): void {
    this.jiraService.getStatus().subscribe({
      next: (s) => {
        this.status = s;
        if (s.connected) {
          this.loadProjects();
        }
      },
      error: (err) => {
        console.error('checkStatus error:', err);
        this.errorMessage = 'Failed to check Jira status.';
      },
    });
  }

  loadProjects(): void {
    this.loadingProjects = true;
    this.errorMessage = '';

    this.jiraService.getProjects().subscribe({
      next: (p) => {
        this.projects = Array.isArray(p) ? p : [];
        this.loadingProjects = false;
      },
      error: (err) => {
        console.error('loadProjects error:', err);
        this.errorMessage = 'Failed to load Jira projects.';
        this.loadingProjects = false;
        this.projects = [];
      },
    });
  }

  onProjectChange(project: JiraProject): void {
    this.selectedProject = project;
    this.stories = [];
    this.selectedStories = [];
    this.loadStories(project.key);
  }

  loadStories(projectKey: string): void {
    this.loadingStories = true;
    this.errorMessage = '';

    this.jiraService.getUserStories(projectKey).subscribe({
      next: (s) => {
        const storiesArray = Array.isArray(s) ? s : [];
        this.stories = storiesArray.map((story) => ({ ...story, selected: false }));
        this.loadingStories = false;
      },
      error: (err) => {
        console.error('Failed to fetch stories:', err);
        this.errorMessage = 'Failed to fetch user stories.';
        this.loadingStories = false;
        this.stories = [];
      },
    });
  }

  connectJira(): void {
    this.connecting = true;

    this.jiraService.getAuthUrl().subscribe({
      next: (res) => {
        const popup = window.open(
          res.url,
          'Connect Jira',
          'width=600,height=700,scrollbars=yes'
        );

        const timer = setInterval(() => {
          if (popup?.closed) {
            clearInterval(timer);
            this.connecting = false;
            this.checkStatus();
          }
        }, 500);
      },
      error: (err) => {
        console.error('connectJira error:', err);
        this.connecting = false;
        this.errorMessage = 'Failed to start Jira connection.';
      },
    });
  }

  disconnect(): void {
    if (!confirm('Disconnect Jira?')) return;

    this.disconnecting = true;

    this.jiraService.disconnect().subscribe({
      next: () => {
        this.disconnecting = false;
        this.status = { connected: false };
        this.projects = [];
        this.stories = [];
        this.selectedProject = null;
      },
      error: (err) => {
        console.error('disconnect error:', err);
        this.disconnecting = false;
        this.errorMessage = 'Failed to disconnect Jira.';
      },
    });
  }

  changePassword(): void {
    if (this.changePasswordForm.invalid) {
      this.changePasswordForm.markAllAsTouched();
      return;
    }

    const payload = {
      current_password: this.changePasswordForm.value.current_password,
      new_password: this.changePasswordForm.value.new_password,
    };

    this.changingPassword = true;

    this.userService.changePassword(payload).subscribe({
      next: (res) => {
        this.changingPassword = false;
        this.toastService.success(
          'Password changed',
          res?.message || 'Your password has been updated successfully'
        );
        this.changePasswordForm.reset();
      },
      error: (err) => {
        this.changingPassword = false;
        this.toastService.error(
          'Change password failed',
          err?.error?.detail || err?.message || 'Something went wrong'
        );
      },
    });
  }
}
