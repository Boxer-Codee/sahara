from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, HttpResponseNotAllowed
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
import datetime
import calendar
import csv
import io
import json
import logging

logger = logging.getLogger(__name__)
from decimal import Decimal

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from django.urls import reverse
from .models import Employee, WorkHours, AdvancePayment, Salary, MonthlyWorkHours, SalaryPaymentLog
from .forms import LoginForm, EmployeeForm, WorkHoursDateForm, AdvancePaymentForm, ManagerForm, WorkHoursForm


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────

def is_admin(user):
    return user.is_superuser

def is_manager_or_admin(user):
    return user.is_superuser or user.is_staff

def csrf_failure(request, reason=""):
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in (getattr(request, 'content_type', '') or '')
    )
    if is_ajax:
        return JsonResponse({
            'success': False,
            'error': f'CSRF verification failed: {reason}. Please refresh the page and try again.'
        }, status=403)
    from django.views.csrf import csrf_failure as default_csrf_failure
    return default_csrf_failure(request, reason=reason)

def custom_500(request):
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in (getattr(request, 'content_type', '') or '')
    )
    if is_ajax:
        return JsonResponse({
            'success': False,
            'error': 'Internal server error while processing request. Please contact the administrator.'
        }, status=500)
    from django.views.defaults import server_error
    return server_error(request)

def custom_403(request, exception=None):
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in (getattr(request, 'content_type', '') or '')
    )
    if is_ajax:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. You do not have access to perform this action.'
        }, status=403)
    from django.views.defaults import permission_denied
    return permission_denied(request, exception)

def custom_404(request, exception=None):
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in (getattr(request, 'content_type', '') or '')
    )
    if is_ajax:
        return JsonResponse({
            'success': False,
            'error': 'The requested endpoint was not found (404).'
        }, status=404)
    from django.views.defaults import page_not_found
    return page_not_found(request, exception)


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'auth/login.html', {'form': form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@login_required
def dashboard(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden("Permission denied.")

    today = datetime.date.today()
    total_employees = Employee.objects.filter(is_active=True).count()
    hours_logged_today = WorkHours.objects.filter(date=today).count()

    current_month = today.replace(day=1)
    
    salaries_current_month = Salary.objects.filter(month=current_month).select_related('employee')

    month_salary = salaries_current_month.aggregate(total=Sum('final_salary'))['total'] or Decimal('0.00')

    recent_hours = WorkHours.objects.filter(date=today).select_related('employee')[:10]
    monthly_salaries = sorted(salaries_current_month, key=lambda s: s.final_salary, reverse=True)[:5]

    context = {
        'total_employees': total_employees,
        'hours_logged_today': hours_logged_today,
        'not_logged_today': total_employees - hours_logged_today,
        'month_salary': month_salary,
        'today': today,
        'recent_hours': recent_hours,
        'monthly_salaries': monthly_salaries,
    }
    return render(request, 'dashboard.html', context)


# ─────────────────────────────────────────────
# EMPLOYEES
# ─────────────────────────────────────────────

@login_required
def employee_list(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    query = request.GET.get('q', '')
    status = request.GET.get('status', 'all')

    if status == 'active':
        employees = Employee.objects.filter(is_active=True)
    elif status == 'inactive':
        employees = Employee.objects.filter(is_active=False)
    else:
        status = 'all'
        employees = Employee.objects.all()

    if query:
        employees = employees.filter(
            Q(name__icontains=query) |
            Q(emp_id__icontains=query) |
            Q(designation__icontains=query) |
            Q(phone__icontains=query)
        )

    paginator = Paginator(employees, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'employees/list.html', {
        'page_obj': page_obj,
        'query': query,
        'status': status,
        'total_count': employees.count(),
    })


@login_required
def employee_add(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Employee added successfully.')
                return redirect('employee_list')
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Failed to add employee")
                messages.error(request, "A database error occurred while saving the employee record. Please verify input values.")
        else:
            messages.error(request, 'Please fix the errors below.')
    return render(request, 'employees/form.html', {'form': form, 'title': 'Add Employee'})


@login_required
def employee_edit(request, pk):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == 'POST':
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f'{employee.name} updated successfully.')
                return redirect('employee_list')
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Failed to edit employee")
                messages.error(request, "A database error occurred while updating the employee record. Please verify input values.")
        else:
            messages.error(request, 'Please fix the errors below.')
    return render(request, 'employees/form.html', {'form': form, 'title': 'Edit Employee', 'employee': employee})


@login_required
@transaction.atomic
def employee_delete(request, pk):
    if not is_admin(request.user):
        if not is_manager_or_admin(request.user):
            return HttpResponseForbidden("Permission denied.")
        messages.error(request, 'Only admins can delete employees.')
        return redirect('employee_list')

    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        name = employee.name
        employee.status = 'Inactive'
        employee.is_active = False
        employee.deactivated_at = timezone.now()
        employee.reactivated_at = None
        employee.save()
        messages.success(request, f'{name} has been deactivated.')
        return redirect('employee_list')
    return render(request, 'employees/confirm_delete.html', {'employee': employee})


@login_required
@transaction.atomic
def employee_reactivate(request, pk):
    if not is_admin(request.user):
        if not is_manager_or_admin(request.user):
            return HttpResponseForbidden("Permission denied.")
        messages.error(request, 'Only admins can reactivate employees.')
        return redirect('employee_list')

    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        name = employee.name
        employee.status = 'Active'
        employee.is_active = True
        employee.deactivated_at = None
        employee.reactivated_at = timezone.now()
        employee.save()
        messages.success(request, f'{name} has been reactivated.')
        return redirect('employee_detail', id=employee.id)
    return render(request, 'employees/confirm_reactivate.html', {'employee': employee})


@login_required
def employee_detail(request, id):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    employee = get_object_or_404(Employee, id=id)

    # Retrieve current month salary if it exists
    today = datetime.date.today()
    current_month = today.replace(day=1)
    current_salary = Salary.objects.filter(employee=employee, month=current_month).first()

    att_month = request.GET.get('att_month', '')
    hours_qs = WorkHours.objects.filter(employee=employee).order_by('-date')
    if att_month:
        try:
            yr, mo = att_month.split('-')
            hours_qs = hours_qs.filter(date__year=yr, date__month=mo)
        except ValueError:
            pass

    att_paginator = Paginator(hours_qs, 20)
    att_page = att_paginator.get_page(request.GET.get('att_page'))

    salary_records = Salary.objects.filter(employee=employee).order_by('-month')
    advances = AdvancePayment.objects.filter(employee=employee).order_by('-date')[:10]
    monthly_hours_records = MonthlyWorkHours.objects.filter(employee=employee).order_by('-month')[:12]

    context = {
        'employee': employee,
        'att_page': att_page,
        'salary_records': salary_records,
        'advances': advances,
        'monthly_hours_records': monthly_hours_records,
        'att_month': att_month,
        'current_salary': current_salary,
        'base_monthly_salary': employee.monthly_salary,
    }
    return render(request, 'employees/detail.html', context)


# ─────────────────────────────────────────────
# WORK HOURS
# ─────────────────────────────────────────────

@ensure_csrf_cookie
@login_required
def workhours_mark(request):
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in (getattr(request, 'content_type', '') or '')
    )

    if not is_manager_or_admin(request.user):
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied. Only managers or administrators can manage monthly work hours.'
            }, status=403)
        return HttpResponseForbidden("Permission denied.")

    today = datetime.date.today()
    payload = {}

    if request.method == 'POST':
        if 'application/json' in (getattr(request, 'content_type', '') or ''):
            try:
                payload = json.loads(request.body.decode('utf-8') or '{}')
            except Exception as e:
                logger.warning("Invalid JSON payload in workhours_mark: %s", e)
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid JSON payload: {str(e)}'
                }, status=400)

        raw_month = payload.get('month') or request.POST.get('month') or request.GET.get('month', today.month)
        raw_year = payload.get('year') or request.POST.get('year') or request.GET.get('year', today.year)
        department = (payload.get('department') or request.POST.get('department') or request.GET.get('department', '')).strip()
        query = (payload.get('q') or request.POST.get('q') or request.GET.get('q', '')).strip()
    else:
        raw_month = request.GET.get('month', today.month)
        raw_year = request.GET.get('year', today.year)
        department = request.GET.get('department', '').strip()
        query = request.GET.get('q', '').strip()

    try:
        selected_month = int(raw_month)
        selected_year = int(raw_year)
        if not (1 <= selected_month <= 12):
            selected_month = today.month
        if not (2000 <= selected_year <= 2100):
            selected_year = today.year
    except (ValueError, TypeError):
        selected_month = today.month
        selected_year = today.year

    month_date = datetime.date(selected_year, selected_month, 1)
    num_days = calendar.monthrange(selected_year, selected_month)[1]
    month_end = datetime.date(selected_year, selected_month, num_days)

    # Eligible employees for this month:
    # 1. Joined on or before month end
    # 2. Status Active OR Inactive with deactivated_at on/after month start
    employees_qs = Employee.objects.filter(
        joining_date__lte=month_end
    ).filter(
        Q(status='Active') |
        Q(status='Inactive', deactivated_at__date__gte=month_date)
    )

    if department:
        employees_qs = employees_qs.filter(designation__iexact=department)

    if query:
        employees_qs = employees_qs.filter(
            Q(name__icontains=query) |
            Q(emp_id__icontains=query) |
            Q(designation__icontains=query)
        )

    employees = list(employees_qs.order_by('name'))
    emp_ids = [e.id for e in employees]

    # Handle POST submission (saving monthly hours)
    if request.method == 'POST':
        saved_count = 0
        errors = []

        try:
            # Collect entries to process
            entries_dict = {}
            if 'entries' in payload:
                entries_dict = payload.get('entries', {})
            else:
                for key, val in request.POST.items():
                    if key.startswith('hours_'):
                        emp_id_str = key.replace('hours_', '')
                        entries_dict[emp_id_str] = val

            with transaction.atomic():
                from payroll.services import PayrollService

                # Fetch submitted employees
                emp_pks = [int(eid) for eid in entries_dict.keys() if str(eid).isdigit()]
                target_employees = {
                    e.id: e for e in Employee.objects.filter(id__in=emp_pks)
                }

                # Check paid salaries in bulk to protect paid months
                paid_salaries = set(
                    Salary.objects.filter(
                        employee_id__in=emp_pks,
                        month=month_date,
                        is_paid=True
                    ).values_list('employee_id', flat=True)
                )

                for emp_id_str, val in entries_dict.items():
                    if not str(emp_id_str).isdigit():
                        continue
                    emp_id = int(emp_id_str)
                    emp = target_employees.get(emp_id)
                    if not emp:
                        continue

                    # Skip empty string or None (indicates input was left blank)
                    if val is None or str(val).strip() == '':
                        continue

                    val_str = str(val).strip()
                    try:
                        hours = Decimal(val_str)
                    except Exception:
                        errors.append(f"Invalid hours format for {emp.name}: '{val_str}'")
                        continue

                    if hours < 0:
                        errors.append(f"Hours cannot be negative for {emp.name}.")
                        continue
                    if hours > 744:
                        errors.append(f"Hours cannot exceed 744 in a month for {emp.name}.")
                        continue

                    # Validate eligibility for month
                    if emp.joining_date > month_end:
                        errors.append(f"{emp.name} joined after {month_date.strftime('%B %Y')}.")
                        continue
                    if emp.status == 'Inactive' and emp.deactivated_at and emp.deactivated_at.date() < month_date:
                        errors.append(f"Cannot log work hours for inactive employee {emp.name} after deactivation.")
                        continue

                    # Skip locked (Paid) salaries
                    if emp.id in paid_salaries:
                        continue

                    MonthlyWorkHours.objects.update_or_create(
                        employee=emp,
                        month=month_date,
                        defaults={
                            'total_hours': hours,
                            'marked_by': request.user,
                        }
                    )
                    PayrollService.recalculate_salary(emp, month_date)
                    saved_count += 1

                if errors:
                    raise ValidationError("; ".join(errors))

            # Recalculate grand total for the current view
            new_total = MonthlyWorkHours.objects.filter(
                employee_id__in=emp_ids,
                month=month_date
            ).aggregate(total=Sum('total_hours'))['total'] or Decimal('0.00')

            msg = f"Successfully saved monthly hours for {saved_count} employee(s) for {month_date.strftime('%B %Y')}."
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': msg,
                    'saved_count': saved_count,
                    'grand_total_hours': float(new_total)
                })
            else:
                messages.success(request, msg)
                redirect_url = f"/workhours/?month={selected_month}&year={selected_year}"
                if department:
                    redirect_url += f"&department={department}"
                return redirect(redirect_url)

        except ValidationError as ve:
            err_msg = ve.message if hasattr(ve, 'message') else str(ve)
            logger.warning("Validation error while saving monthly hours: %s", err_msg)
            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=400)
            messages.error(request, err_msg)
        except Exception as e:
            logger.exception("Failed to save monthly work hours: %s", e)
            err_msg = f"An error occurred while saving: {str(e)}"
            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=500)
            messages.error(request, err_msg)

    # Fetch existing MonthlyWorkHours records
    existing_monthly = {
        mwh.employee_id: mwh
        for mwh in MonthlyWorkHours.objects.filter(employee_id__in=emp_ids, month=month_date).select_related('marked_by')
    }

    # Fallback to daily hours sums if no MonthlyWorkHours record exists yet
    missing_emp_ids = [eid for eid in emp_ids if eid not in existing_monthly]
    daily_sums = {}
    if missing_emp_ids:
        daily_records = WorkHours.objects.filter(
            employee_id__in=missing_emp_ids,
            date__range=(month_date, month_end)
        ).values('employee_id').annotate(total=Sum('hours_worked'))
        for dr in daily_records:
            daily_sums[dr['employee_id']] = dr['total']

    # Check paid salaries for this month
    paid_salaries = set(
        Salary.objects.filter(
            employee_id__in=emp_ids,
            month=month_date,
            is_paid=True
        ).values_list('employee_id', flat=True)
    )

    hours_data = []
    grand_total_hours = Decimal('0.00')

    for emp in employees:
        mwh = existing_monthly.get(emp.id)
        if mwh is not None:
            hours_val = mwh.total_hours
            has_saved = True
            updated_at = mwh.updated_at
            marked_by = mwh.marked_by.username if mwh.marked_by else None
        elif emp.id in daily_sums:
            hours_val = Decimal(str(daily_sums[emp.id]))
            has_saved = False
            updated_at = None
            marked_by = None
        else:
            hours_val = None
            has_saved = False
            updated_at = None
            marked_by = None

        if hours_val is not None:
            grand_total_hours += Decimal(str(hours_val))

        is_paid = emp.id in paid_salaries

        hours_data.append({
            'employee': emp,
            'hours': hours_val if hours_val is not None else '',
            'hours_display': f"{hours_val:.2f}".rstrip('0').rstrip('.') if hours_val is not None else '',
            'is_salary_paid': is_paid,
            'has_saved': has_saved,
            'updated_at': updated_at,
            'marked_by': marked_by,
        })

    # Available designations for filter
    departments = sorted(list(set(
        Employee.objects.values_list('designation', flat=True).exclude(designation__isnull=True).exclude(designation__exact='')
    )))

    # Months and years lists
    month_names = [(i, calendar.month_name[i]) for i in range(1, 13)]
    current_year = today.year
    year_choices = list(range(current_year - 2, current_year + 3))

    context = {
        'hours_data': hours_data,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'selected_department': department,
        'query': query,
        'departments': departments,
        'month_names': month_names,
        'year_choices': year_choices,
        'grand_total_hours': grand_total_hours,
        'month_name': calendar.month_name[selected_month],
        'total_employees': len(employees),
        'month_date': month_date,
    }
    return render(request, 'workhours/mark.html', context)


@login_required
def workhours_history(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden("Permission denied.")

    today = datetime.date.today()
    try:
        selected_month = int(request.GET.get('month', today.month))
        selected_year = int(request.GET.get('year', today.year))
        if not (1 <= selected_month <= 12):
            selected_month = today.month
        if not (2000 <= selected_year <= 2100):
            selected_year = today.year
    except (ValueError, TypeError):
        selected_month = today.month
        selected_year = today.year

    month_date = datetime.date(selected_year, selected_month, 1)
    query = request.GET.get('q', '').strip()

    history_qs = MonthlyWorkHours.objects.filter(
        month=month_date
    ).select_related('employee', 'marked_by').order_by('employee__name')

    if query:
        history_qs = history_qs.filter(
            Q(employee__name__icontains=query) |
            Q(employee__emp_id__icontains=query) |
            Q(employee__designation__icontains=query)
        )

    # Check paid statuses
    paid_emp_ids = set(
        Salary.objects.filter(
            month=month_date,
            is_paid=True
        ).values_list('employee_id', flat=True)
    )

    records = []
    total_hours = Decimal('0.00')
    for mwh in history_qs:
        total_hours += mwh.total_hours
        records.append({
            'record': mwh,
            'is_salary_paid': mwh.employee_id in paid_emp_ids,
        })

    month_names = [(i, calendar.month_name[i]) for i in range(1, 13)]
    current_year = today.year
    year_choices = list(range(current_year - 2, current_year + 3))

    context = {
        'records': records,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'query': query,
        'total_hours': total_hours,
        'month_name': calendar.month_name[selected_month],
        'month_names': month_names,
        'year_choices': year_choices,
        'total_count': len(records),
        'month_date': month_date,
    }
    return render(request, 'workhours/history.html', context)


@login_required
def workhours_view(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    filter_date_str = request.GET.get('date', '')
    filter_employee = request.GET.get('employee', '')

    hours_qs = WorkHours.objects.all().select_related('employee', 'marked_by').order_by('-date', 'employee__name')

    if filter_date_str:
        try:
            filter_date = datetime.date.fromisoformat(filter_date_str)
            hours_qs = hours_qs.filter(date=filter_date)
        except ValueError:
            pass

    if filter_employee:
        hours_qs = hours_qs.filter(employee_id=filter_employee)

    total_hours = hours_qs.aggregate(total=Sum('hours_worked'))['total'] or 0

    employees = Employee.objects.all().order_by('-is_active', 'name')
    paginator = Paginator(hours_qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'workhours/view.html', {
        'page_obj': page_obj,
        'filter_date': filter_date_str,
        'filter_employee': filter_employee,
        'employees': employees,
        'total_hours': total_hours,
    })

@login_required
def workhours_edit(request, id):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()
    record = get_object_or_404(WorkHours, id=id)
    form = WorkHoursForm(request.POST or None, instance=record)
    if request.method == 'POST':
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                messages.success(request, 'Work hours updated successfully.')
                return redirect('workhours_view')
            except ValidationError as e:
                form.add_error(None, e)
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Failed to edit work hours")
                form.add_error(None, f"An error occurred while saving: {str(e)}")
    return render(request, 'workhours/form.html', {'form': form, 'title': 'Edit Work Hours'})

@login_required
def workhours_delete(request, id):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()
    record = get_object_or_404(WorkHours, id=id)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                record.delete()
            messages.success(request, 'Work hours deleted successfully.')
        except ValidationError as e:
            messages.error(request, e.message)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to delete work hours")
            messages.error(request, f"An error occurred while deleting: {str(e)}")
        return redirect('workhours_view')
    return render(request, 'workhours/confirm_delete.html', {'record': record})


# ─────────────────────────────────────────────
# ADVANCE PAYMENT
# ─────────────────────────────────────────────

@login_required
def advance_list(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    advances = AdvancePayment.objects.all().select_related('employee', 'given_by')
    paginator = Paginator(advances, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'advance/list.html', {'page_obj': page_obj})

@login_required
def advance_add(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    form = AdvancePaymentForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            advance = form.save(commit=False)
            advance.given_by = request.user
            advance.save()
            messages.success(request, 'Advance payment recorded successfully.')
            return redirect('advance_list')
        else:
            messages.error(request, 'Please fix the errors below.')
            
    return render(request, 'advance/form.html', {'form': form, 'title': 'Give Advance'})

@login_required
def advance_delete(request, id):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()
    record = get_object_or_404(AdvancePayment, id=id)
    if request.method == 'POST':
        try:
            record.delete()
            messages.success(request, 'Advance payment deleted successfully.')
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('advance_list')
    return render(request, 'advance/confirm_delete.html', {'record': record})


# ─────────────────────────────────────────────
# SALARY
# ─────────────────────────────────────────────

@login_required
def salary_list(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    filter_month = request.GET.get('month', datetime.date.today().strftime('%Y-%m'))
    try:
        yr, mo = filter_month.split('-')
        yr, mo = int(yr), int(mo)
    except Exception:
        today = datetime.date.today()
        yr, mo = today.year, today.month
        filter_month = f'{yr:04d}-{mo:02d}'

    month_date = datetime.date(yr, mo, 1)
    salaries = Salary.objects.filter(
        month=month_date
    ).select_related('employee', 'paid_by', 'unpaid_by').order_by('employee__name')

    totals = salaries.aggregate(
        total_gross=Sum('gross_salary'),
        total_final=Sum('final_salary'),
        total_advance=Sum('total_advance'),
    )
    total_gross = totals['total_gross'] or Decimal('0.00')
    total_final = totals['total_final'] or Decimal('0.00')
    total_advance = totals['total_advance'] or Decimal('0.00')
    paid_count = salaries.filter(is_paid=True).count()

    return render(request, 'salary/list.html', {
        'salaries': salaries,
        'filter_month': filter_month,
        'total_gross': total_gross,
        'total_final': total_final,
        'total_advance': total_advance,
        'paid_count': paid_count,
        'unpaid_count': salaries.count() - paid_count,
    })


@login_required
@transaction.atomic
def salary_mark_paid(request, pk):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden("Permission denied.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    salary = get_object_or_404(Salary.objects.select_for_update(), pk=pk)
    month_str = salary.month.strftime('%Y-%m')

    if salary.is_paid:
        messages.warning(request, f"{salary.employee.name}'s salary is already marked as paid.")
        return redirect(f"{reverse('salary_list')}?month={month_str}")

    salary.is_paid = True
    salary.paid_by = request.user
    salary.paid_at = timezone.now()
    salary._allow_status_change = True
    salary.save()

    SalaryPaymentLog.objects.create(
        salary=salary,
        employee=salary.employee,
        month=salary.month,
        action='PAID',
        performed_by=request.user,
        previous_state='Unpaid',
        new_state='Paid',
        notes=f"Marked as paid by {request.user.username}"
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"[AUDIT] Salary ID {salary.id} for employee {salary.employee.name} (EMP ID: {salary.employee.emp_id}, Month: {salary.month}) "
        f"marked as PAID by {request.user.username} (Role: {'Admin' if request.user.is_superuser else 'Manager'}) at {timezone.now()}."
    )

    messages.success(request, f"{salary.employee.name}'s salary for {salary.month.strftime('%B %Y')} marked as paid.")
    return redirect(f"{reverse('salary_list')}?month={month_str}")


@login_required
@transaction.atomic
def salary_mark_unpaid(request, pk):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden("Permission denied.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    salary = get_object_or_404(Salary.objects.select_for_update(), pk=pk)
    month_str = salary.month.strftime('%Y-%m')

    if not salary.is_paid:
        messages.warning(request, f"{salary.employee.name}'s salary is already marked as unpaid.")
        return redirect(f"{reverse('salary_list')}?month={month_str}")

    salary.is_paid = False
    salary.unpaid_by = request.user
    salary.unpaid_at = timezone.now()
    salary._allow_status_change = True
    salary.save()

    SalaryPaymentLog.objects.create(
        salary=salary,
        employee=salary.employee,
        month=salary.month,
        action='UNPAID',
        performed_by=request.user,
        previous_state='Paid',
        new_state='Unpaid',
        notes=f"Marked as unpaid by {request.user.username}"
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"[AUDIT] Salary ID {salary.id} for employee {salary.employee.name} (EMP ID: {salary.employee.emp_id}, Month: {salary.month}) "
        f"marked as UNPAID by {request.user.username} (Role: {'Admin' if request.user.is_superuser else 'Manager'}) at {timezone.now()}."
    )

    messages.success(request, f"{salary.employee.name}'s salary for {salary.month.strftime('%B %Y')} marked as unpaid.")
    return redirect(f"{reverse('salary_list')}?month={month_str}")


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────

@login_required
def reports(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    filter_month = request.GET.get('month', datetime.date.today().strftime('%Y-%m'))
    try:
        yr, mo = filter_month.split('-')
        yr, mo = int(yr), int(mo)
    except Exception:
        today = datetime.date.today()
        yr, mo = today.year, today.month
        filter_month = f'{yr:04d}-{mo:02d}'

    month_date = datetime.date(yr, mo, 1)
    salaries = Salary.objects.filter(
        month=month_date
    ).select_related('employee', 'paid_by').order_by('employee__name')

    totals = salaries.aggregate(
        total_salary=Sum('final_salary'),
        total_paid=Sum('final_salary', filter=Q(is_paid=True)),
        total_unpaid=Sum('final_salary', filter=Q(is_paid=False)),
    )
    total_salary = totals['total_salary'] or Decimal('0.00')
    total_paid = totals['total_paid'] or Decimal('0.00')
    total_unpaid = totals['total_unpaid'] or Decimal('0.00')

    return render(request, 'reports/report.html', {
        'salaries': salaries,
        'filter_month': filter_month,
        'total_salary': total_salary,
        'total_paid': total_paid,
        'total_unpaid': total_unpaid,
    })


def sanitize_csv_cell(val):
    if val is None:
        return ''
    s = str(val)
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{s}"
    return s


@login_required
def export_csv(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    filter_month = request.GET.get('month', datetime.date.today().strftime('%Y-%m'))
    try:
        yr, mo = filter_month.split('-')
        yr, mo = int(yr), int(mo)
    except Exception:
        today = datetime.date.today()
        yr, mo = today.year, today.month
        filter_month = f'{yr:04d}-{mo:02d}'

    month_date = datetime.date(yr, mo, 1)
    salaries = Salary.objects.filter(
        month=month_date
    ).select_related('employee', 'paid_by').order_by('employee__name')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="salary_report_{filter_month}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Employee ID', 'Name', 'Designation', 'Daily Rate', 'Total Hours',
                     'Gross Salary', 'Total Advance', 'Remaining Advance', 'Final Salary', 'Status', 'Paid By', 'Paid Date'])

    for s in salaries:
        writer.writerow([
            sanitize_csv_cell(s.employee.emp_id),
            sanitize_csv_cell(s.employee.name),
            sanitize_csv_cell(s.employee.designation),
            s.employee.daily_rate,
            s.total_hours,
            s.gross_salary,
            s.total_advance,
            s.remaining_advance,
            s.final_salary,
            'Paid' if s.is_paid else 'Unpaid',
            sanitize_csv_cell(s.paid_by.username if s.paid_by else '-'),
            s.paid_at.strftime('%d %b %Y %H:%M') if s.paid_at else '-',
        ])

    return response


@login_required
def export_excel(request):
    if not is_manager_or_admin(request.user):
        return HttpResponseForbidden()

    if not OPENPYXL_AVAILABLE:
        messages.error(request, 'openpyxl not installed. Please install it.')
        return redirect('reports')

    filter_month = request.GET.get('month', datetime.date.today().strftime('%Y-%m'))
    try:
        yr, mo = filter_month.split('-')
        yr, mo = int(yr), int(mo)
    except Exception:
        today = datetime.date.today()
        yr, mo = today.year, today.month
        filter_month = f'{yr:04d}-{mo:02d}'

    month_date = datetime.date(yr, mo, 1)
    salaries = Salary.objects.filter(
        month=month_date
    ).select_related('employee', 'paid_by').order_by('employee__name')

    wb = openpyxl.Workbook()
    ws = wb.active
    month_name = datetime.date(yr, mo, 1).strftime('%B %Y')
    ws.title = f"Salary {month_name}"

    header_fill = PatternFill(start_color="1a3c5e", end_color="1a3c5e", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    headers = ['Employee ID', 'Name', 'Designation', 'Daily Rate', 'Total Hours',
               'Gross Salary', 'Total Advance', 'Remaining Advance', 'Final Salary', 'Status', 'Paid By', 'Paid Date']

    ws.append([f'CodeCrafted Packaging - Salary Report - {month_name}'])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(headers)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    for s in salaries:
        ws.append([
            s.employee.emp_id,
            s.employee.name,
            s.employee.designation,
            float(s.employee.daily_rate),
            float(s.total_hours),
            float(s.gross_salary),
            float(s.total_advance),
            float(s.remaining_advance),
            float(s.final_salary),
            'Paid' if s.is_paid else 'Unpaid',
            s.paid_by.username if s.paid_by else '-',
            s.paid_at.strftime('%d %b %Y') if s.paid_at else '-',
        ])

    for column_cells in ws.columns:
        length = max(len(str(cell.value or '')) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = length + 4

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="salary_{filter_month}.xlsx"'
    return response


# ─────────────────────────────────────────────
# MANAGER MANAGEMENT (Admin only)
# ─────────────────────────────────────────────

@login_required
def manager_list(request):
    if not is_admin(request.user):
        return HttpResponseForbidden()
    managers = User.objects.filter(is_staff=True, is_superuser=False).order_by('username')
    return render(request, 'managers/list.html', {'managers': managers})


@login_required
def manager_add(request):
    if not is_admin(request.user):
        return HttpResponseForbidden()
    form = ManagerForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Manager account created.')
            return redirect('manager_list')
        else:
            messages.error(request, 'Please fix the errors.')
    return render(request, 'managers/form.html', {'form': form, 'title': 'Add Manager'})


@login_required
def manager_delete(request, pk):
    if not is_admin(request.user):
        return HttpResponseForbidden("Permission denied.")
    manager = get_object_or_404(User, pk=pk, is_staff=True, is_superuser=False)
    if manager.pk == request.user.pk:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('manager_list')
    if request.method == 'POST':
        manager.delete()
        messages.success(request, 'Manager deleted.')
        return redirect('manager_list')
    return render(request, 'managers/confirm_delete.html', {'manager': manager})
