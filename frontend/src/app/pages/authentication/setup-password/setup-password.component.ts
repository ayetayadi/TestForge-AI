import { Component, OnInit } from '@angular/core';
import { FormGroup, FormControl, Validators, ReactiveFormsModule, AbstractControl } from '@angular/forms';
import { Router, ActivatedRoute, RouterModule } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { HttpClient } from '@angular/common/http';

function passwordMatchValidator(control: AbstractControl) {
  const pw = control.get('password');
  const confirm = control.get('confirm_password');
  if (pw && confirm && pw.value !== confirm.value) {
    confirm.setErrors({ mismatch: true });
  } else {
    confirm?.setErrors(null);
  }
  return null;
}

@Component({
  selector: 'app-setup-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MaterialModule, RouterModule],
  templateUrl: './setup-password.component.html',
})
export class SetupPasswordComponent implements OnInit {
  token = '';
  loading = false;
  errorMessage = '';
  successMessage = '';
  invalidToken = false;

  form = new FormGroup({
    password: new FormControl('', [Validators.required, Validators.minLength(6)]),
    confirm_password: new FormControl('', [Validators.required]),
  }, { validators: passwordMatchValidator });

  get f() { return this.form.controls; }

  constructor(
    private http: HttpClient,
    private router: Router,
    private route: ActivatedRoute,
  ) {}

  ngOnInit() {
    this.token = this.route.snapshot.queryParams['token'] || '';
    if (!this.token) {
      this.invalidToken = true;
    }
  }

  submit() {
    if (this.form.invalid || !this.token) return;
    this.loading = true;
    this.errorMessage = '';

    this.http.post('http://localhost:8000/auth/setup-password', {
      token: this.token,
      password: this.f['password'].value,
    }).subscribe({
      next: () => {
        this.loading = false;
        this.successMessage = 'Password set! Redirecting to login...';
        setTimeout(() => this.router.navigate(['/authentication/login']), 2000);
      },
      error: (err) => {
        this.loading = false;
        this.errorMessage = err.error?.detail || 'Invalid or expired link';
      }
    });
  }
}
