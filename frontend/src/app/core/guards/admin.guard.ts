import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { jwtDecode } from 'jwt-decode';

export const adminGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.getToken();

  if (!token) {
    router.navigate(['/authentication/login']);
    return false;
  }

  try {
    const decoded: any = jwtDecode(token);
    if (decoded.is_admin) return true;
  } catch {}

  router.navigate(['/dashboard']);
  return false;
};
