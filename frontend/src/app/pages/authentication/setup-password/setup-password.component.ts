import { Component, OnInit } from '@angular/core';
import {
  FormGroup,
  FormControl,
  Validators,
  ReactiveFormsModule,
  AbstractControl,
  ValidationErrors
} from '@angular/forms';
import { Router, ActivatedRoute, RouterModule } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { HttpClient } from '@angular/common/http';

/**
 * ✅ Validator propre (ne casse pas les autres erreurs)
 */
function passwordMatchValidator(group: AbstractControl): ValidationErrors | null {
  const password = group.get('password')?.value;
  const confirm = group.get('confirm_password');

  if (!confirm) return null;

  if (password !== confirm.value) {
    confirm.setErrors({
      ...confirm.errors,
      mismatch: true
    });
  } else {
    if (confirm.errors) {
      delete confirm.errors['mismatch'];
      if (Object.keys(confirm.errors).length === 0) {
        confirm.setErrors(null);
      }
    }
  }

  return null;
}

@Component({
  selector: 'app-setup-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MaterialModule, RouterModule],
  templateUrl: './setup-password.component.html',
  styleUrl: './setup-password.component.scss'
})
export class SetupPasswordComponent implements OnInit {

  token = '';
  loading = false;
  errorMessage = '';
  successMessage = '';
  invalidToken = false;

  // 👁 toggle
  hidePassword = true;
  hideConfirmPassword = true;

  form = new FormGroup({
    password: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(6)]
    }),
    confirm_password: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required]
    }),
  }, { validators: passwordMatchValidator });

  constructor(
    private http: HttpClient,
    private router: Router,
    private route: ActivatedRoute,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParams['token'] || '';

    if (!this.token) {
      this.invalidToken = true;
    }
  }

  get f() {
    return this.form.controls;
  }

  submit(): void {
    if (this.form.invalid || !this.token) return;

    this.loading = true;
    this.errorMessage = '';

    this.http.post('http://localhost:8000/auth/setup-password', {
      token: this.token,
      password: this.f.password.value,
    }).subscribe({
      next: () => {
        this.loading = false;
        this.successMessage = 'Password set! Redirecting to login...';

        setTimeout(() => {
          this.router.navigate(['/authentication/login']);
        }, 2000);
      },
      error: (err) => {
        this.loading = false;
        this.errorMessage =
          err?.error?.detail || 'Invalid or expired link';
      }
    });
  }
}