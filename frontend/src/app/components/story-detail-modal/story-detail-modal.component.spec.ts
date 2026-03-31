import { ComponentFixture, TestBed } from '@angular/core/testing';

import { StoryDetailModalComponent } from './story-detail-modal.component';

describe('StoryDetailModalComponent', () => {
  let component: StoryDetailModalComponent;
  let fixture: ComponentFixture<StoryDetailModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [StoryDetailModalComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(StoryDetailModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
