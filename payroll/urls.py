from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('', views.login_view, name='login'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Employees
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/add/', views.employee_add, name='employee_add'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),
    path('employees/<int:pk>/reactivate/', views.employee_reactivate, name='employee_reactivate'),
    path('employee/<int:id>/', views.employee_detail, name='employee_detail'),

    # Work Hours
    path('workhours/', views.workhours_mark, name='workhours_mark'),
    path('workhours/history/', views.workhours_history, name='workhours_history'),
    path('workhours/view/', views.workhours_view, name='workhours_view'),
    path('workhours/<int:id>/edit/', views.workhours_edit, name='workhours_edit'),
    path('workhours/<int:id>/delete/', views.workhours_delete, name='workhours_delete'),

    # Advance Payment
    path('advance/', views.advance_list, name='advance_list'),
    path('advance/add/', views.advance_add, name='advance_add'),
    path('advance/<int:id>/delete/', views.advance_delete, name='advance_delete'),

    # Salary
    path('salary/', views.salary_list, name='salary_list'),
    path('salary/<int:pk>/mark-paid/', views.salary_mark_paid, name='salary_mark_paid'),
    path('salary/<int:pk>/mark-unpaid/', views.salary_mark_unpaid, name='salary_mark_unpaid'),

    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/export/csv/', views.export_csv, name='export_csv'),
    path('reports/export/excel/', views.export_excel, name='export_excel'),

    # Managers
    path('managers/', views.manager_list, name='manager_list'),
    path('managers/add/', views.manager_add, name='manager_add'),
    path('managers/<int:pk>/delete/', views.manager_delete, name='manager_delete'),
]
