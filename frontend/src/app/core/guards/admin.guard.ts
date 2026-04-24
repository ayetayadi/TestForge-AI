import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { jwtDecode } from 'jwt-decode';

export const adminGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  // Vérifier si l'utilisateur est connecté
  if (!auth.isLoggedIn()) {
    router.navigate(['/authentication/login']);
    return false;
  }

  const token = auth.getAccessToken();
  
  if (!token) {
    router.navigate(['/authentication/login']);
    return false;
  }

  try {
    const decoded: any = jwtDecode(token);
    // Vérifie via le token ET via le service
    if (decoded.is_admin && auth.getIsAdmin()) {
      return true;
    }
  } catch (error) {
    console.error('Invalid token in admin guard', error);
  }

  // Rediriger vers le dashboard user si pas admin
  router.navigate(['/user-dashboard']);
  return false;
};