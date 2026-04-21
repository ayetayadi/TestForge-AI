import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PlaywrightScriptDetailComponent } from './playwright-script-detail.component';

describe('PlaywrightScriptDetailComponent', () => {
  let component: PlaywrightScriptDetailComponent;
  let fixture: ComponentFixture<PlaywrightScriptDetailComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlaywrightScriptDetailComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(PlaywrightScriptDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
