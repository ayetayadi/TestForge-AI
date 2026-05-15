import { Component } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-branding',
  standalone: true,
  template: `
    <a (click)="goToDashboard()" class="brand-link">
      <div class="brand-container">
        <div class="logo-title-wrapper">
          <div class="logo-wrapper">
            <img
              src="./assets/images/logos/logo-testforge-ai.png"
              alt="TestForge"
              class="brand-logo" />
          </div>
          <div class="title-wrapper">
            <span class="brand-name">TestForge</span>
            <span class="brand-ai">AI</span>
          </div>
        </div>
        <p class="brand-subtitle">AUTOMATION E2E TEST INTELLIGENT</p>
      </div>
    </a>
  `,
  styles: [`
    .brand-link {
      display: block;
      cursor: pointer;
      text-decoration: none;
      outline: none;
      margin-top: 20px;
    }

    .brand-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      gap: 0px;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .brand-container:hover {
      transform: translateY(-2px);
    }

    /* Wrapper qui contient logo + titre alignés horizontalement */
    .logo-title-wrapper {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
    }

    /* Logo */
    .logo-wrapper {
      position: relative;
      display: inline-block;
    }

    .brand-logo {
      width: 48px;
      height: 48px;
      object-fit: contain;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      filter: drop-shadow(0 4px 12px rgba(79, 70, 229, 0.2));
    }

    .brand-container:hover .brand-logo {
      transform: scale(1.05);
    }

    /* Titre principal - agrandi */
    .title-wrapper {
      display: flex;
      align-items: baseline;
      gap: 2px;
    }

    .brand-name {
      font-size: 1.3rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #1f2937 0%, #374151 100%);
      background-clip: text;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      transition: all 0.3s ease;
    }

    .brand-ai {
      font-size: 1.1rem;
      font-weight: 800;
      background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
      background-clip: text;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      position: relative;
      padding: 2px 8px;
      border-radius: 20px;
    }

    .brand-ai::before {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(79, 70, 229, 0.1) 0%, rgba(67, 56, 202, 0.1) 100%);
      border-radius: 20px;
      opacity: 0;
      transition: opacity 0.3s ease;
    }

    .brand-container:hover .brand-ai::before {
      opacity: 1;
    }

    /* Subtitle - agrandi et en majuscules comme votre image */
    .brand-subtitle {
      font-size: 0.65rem;
      font-weight: 600;
      letter-spacing: 1px;
      color: #6b7280;
      margin: 0;
      padding: 0;
      text-transform: uppercase;
      transition: all 0.3s ease;
    }

    .brand-container:hover .brand-subtitle {
      letter-spacing: 1.5px;
      color: #4f46e5;
    }

    /* Animation d'entrée */
    @keyframes fadeInUp {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .brand-container {
      animation: fadeInUp 0.4s ease-out;
    }

    /* Responsive */
    @media (max-width: 768px) {
      .brand-logo {
        width: 40px;
        height: 40px;
      }
      
      .brand-name {
        font-size: 1.5rem;
      }
      
      .brand-ai {
        font-size: 1.25rem;
      }
      
      .brand-subtitle {
        font-size: 0.65rem;
      }
      
      .logo-title-wrapper {
        gap: 10px;
      }
    }

    @media (max-width: 480px) {
      .brand-logo {
        width: 34px;
        height: 34px;
      }
      
      .brand-name {
        font-size: 1.25rem;
      }
      
      .brand-ai {
        font-size: 1rem;
      }
      
      .brand-subtitle {
        font-size: 0.55rem;
        letter-spacing: 0.8px;
      }
      
      .logo-title-wrapper {
        gap: 8px;
      }
    }

    /* Focus state pour accessibilité */
    .brand-link:focus-visible {
      outline: 2px solid #4f46e5;
      outline-offset: 4px;
      border-radius: 16px;
    }

    /* Reduced motion */
    @media (prefers-reduced-motion: reduce) {
      .brand-container,
      .brand-logo,
      .brand-name,
      .brand-ai,
      .brand-subtitle {
        animation: none;
        transition: none;
      }
      
      .brand-container:hover {
        transform: none;
      }
      
      .brand-container:hover .brand-logo {
        transform: none;
      }
    }
  `]
})
export class BrandingComponent {
  constructor(private router: Router) {}

  goToDashboard() {
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    this.router.navigate([isAdmin ? '/admin-dashboard' : '/user-dashboard']);
  }
}