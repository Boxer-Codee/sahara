from django.urls import path, include

urlpatterns = [
    path('', include('payroll.urls')),
]

handler500 = 'payroll.views.custom_500'
handler403 = 'payroll.views.custom_403'
handler404 = 'payroll.views.custom_404'
