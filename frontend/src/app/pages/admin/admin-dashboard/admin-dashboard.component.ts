import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AdminService, UserRead } from 'src/app/services/admin.service';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-dashboard.component.html',
  styleUrls: ['./admin-dashboard.component.scss']
})
export class AdminDashboardComponent implements OnInit {
  searchTerm = '';
  roleFilter = 'all';
  statusFilter = 'all';

  users: UserRead[] = [];
  loading = false;
  errorMessage = '';

  constructor(
    private adminService: AdminService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.loadUsers();
  }

  loadUsers(): void {
    this.loading = true;
    this.errorMessage = '';

    this.adminService.getUsers().subscribe({
      next: (data) => {
        this.users = data;
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        this.errorMessage = err.error?.detail || 'Failed to load users';
      }
    });
  }

  get totalUsers(): number {
    return this.users.length;
  }

  get activeUsers(): number {
    return this.users.filter(user => user.is_active).length;
  }

  get adminUsers(): number {
    return this.users.filter(user => user.is_admin).length;
  }

  get jiraConnectedUsers(): number {
    return this.users.filter(user => user.jira_connected).length;
  }

  get filteredUsers(): UserRead[] {
    return this.users.filter(user => {
      const matchesSearch =
        user.username.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
        user.email.toLowerCase().includes(this.searchTerm.toLowerCase());

      const matchesRole =
        this.roleFilter === 'all' ||
        (this.roleFilter === 'admin' && user.is_admin) ||
        (this.roleFilter === 'user' && !user.is_admin);

      const matchesStatus =
        this.statusFilter === 'all' ||
        (this.statusFilter === 'active' && user.is_active) ||
        (this.statusFilter === 'inactive' && !user.is_active);

      return matchesSearch && matchesRole && matchesStatus;
    });
  }

  createUser(): void {
    this.router.navigate(['/admin/users']);
  }


}
