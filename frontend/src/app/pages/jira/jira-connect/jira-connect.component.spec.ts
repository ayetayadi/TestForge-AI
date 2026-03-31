import { ComponentFixture, TestBed } from '@angular/core/testing';

import { JiraConnectComponent } from './jira-connect.component';

describe('JiraConnectComponent', () => {
  let component: JiraConnectComponent;
  let fixture: ComponentFixture<JiraConnectComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [JiraConnectComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(JiraConnectComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
