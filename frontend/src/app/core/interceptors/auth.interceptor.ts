import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';

export const authInterceptor: HttpInterceptorFn = (req: HttpRequest<unknown>, next: HttpHandlerFn) => {
  const authService = inject(AuthService);
  const toast = inject(ToastService);
  const token = authService.getAccessToken();

  // Attach auth header + credentials to every request
  const cloned = token && !req.url.includes('/refresh')
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` }, withCredentials: true })
    : req.clone({ withCredentials: true });

  return next(cloned).pipe(
    catchError((error: HttpErrorResponse) => {
      // 401 — try to refresh, then retry the original request
      if (error.status === 401 && !req.url.includes('/refresh')) {
        return authService.refreshToken().pipe(
          switchMap((newToken: string) => {
            const retried = req.clone({
              setHeaders: { Authorization: `Bearer ${newToken}` },
              withCredentials: true,
            });
            return next(retried);
          }),
          catchError((refreshError) => {
            authService.logout();
            return throwError(() => refreshError);
          }),
        );
      }

      // 0 / network error — no response from server
      if (error.status === 0) {
        toast.error('Cannot reach the server. Check your connection.');
        return throwError(() => error);
      }

      // 429 — rate limited
      if (error.status === 429) {
        toast.error('Too many requests. Please wait a moment and try again.');
        return throwError(() => error);
      }

      // 500 / 502 / 503 — server errors (don't expose detail to the user)
      if (error.status >= 500) {
        toast.error('A server error occurred. Please try again later.');
        return throwError(() => error);
      }

      // All other errors (400, 403, 404…) — let individual components handle them
      return throwError(() => error);
    }),
  );
};
