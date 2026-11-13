import datetime
import calendar
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q

class PayrollService:
    @staticmethod
    def recalculate_salary(employee, month_date, force=False):
        """
        Recalculates payroll for a single employee for a given month.
        month_date should be a datetime.date representing the month (usually 1st of the month).
        """
        from payroll.models import Salary, WorkHours, AdvancePayment, MonthlyWorkHours

        month_date = month_date.replace(day=1)

        with transaction.atomic():
            salary, created = Salary.objects.get_or_create(
                employee=employee,
                month=month_date
            )

            # If the salary is marked as paid, do not modify it unless force=True
            if salary.is_paid and not force:
                return salary

            # Handle force/repair flag to bypass validation
            if force:
                salary._force_recalculate = True

            # 1. Update basic information (handle missing monthly salary)
            salary.monthly_salary = Decimal(str(employee.monthly_salary or '0.00'))

            # 2. Compute date boundaries for the month
            num_days = calendar.monthrange(month_date.year, month_date.month)[1]
            start_date = month_date.replace(day=1)
            end_date = month_date.replace(day=num_days)

            # Sum work hours: Check MonthlyWorkHours first, fallback to daily WorkHours
            monthly_wh = MonthlyWorkHours.objects.filter(
                employee=employee,
                month=month_date
            ).first()

            if monthly_wh is not None:
                total_hours = monthly_wh.total_hours
            else:
                total_hours = WorkHours.objects.filter(
                    employee=employee,
                    date__range=(start_date, end_date)
                ).aggregate(total=Sum('hours_worked'))['total'] or 0

            salary.total_hours = Decimal(str(total_hours))

            # 3. Sum advances
            total_advance = AdvancePayment.objects.filter(
                employee=employee,
                date__range=(start_date, end_date)
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            salary.total_advance = Decimal(str(total_advance))

            # 4. Perform calculations (handle missing rate edge cases)
            if salary.monthly_salary > 0:
                daily_rate = (salary.monthly_salary / Decimal('26')).quantize(Decimal('0.01'))
                hourly_rate = (daily_rate / Decimal('12')).quantize(Decimal('0.01'))
            else:
                daily_rate = Decimal('0.00')
                hourly_rate = Decimal('0.00')

            gross_salary = (salary.total_hours * hourly_rate).quantize(Decimal('0.01'))

            # Final Salary must never be below zero
            salary.final_salary = max(Decimal('0.00'), (gross_salary - salary.total_advance).quantize(Decimal('0.01')))
            if gross_salary < salary.total_advance:
                salary.remaining_advance = (salary.total_advance - gross_salary).quantize(Decimal('0.01'))
            else:
                salary.remaining_advance = Decimal('0.00')

            salary.gross_salary = gross_salary

            print(f"[PAYROLL_RECALC_LOG] Employee ID: {employee.emp_id}, Month: {month_date}, "
                  f"Daily Rate: {daily_rate}, Hourly Rate: {hourly_rate}, Total Hours: {salary.total_hours}, "
                  f"Total Advance: {salary.total_advance}, Gross Salary: {salary.gross_salary}, Final Salary: {salary.final_salary}")

            salary.save()
            return salary

    @staticmethod
    def recalculate_month(month_date, force=False):
        """
        Recalculates payroll for all eligible employees for a given month.
        """
        from payroll.models import Employee

        month_date = month_date.replace(day=1)
        num_days = calendar.monthrange(month_date.year, month_date.month)[1]
        month_end = month_date.replace(day=num_days)

        # Get all employees eligible for this month:
        # 1. Employee joined on or before month end
        # 2. Employee is Active OR was Inactive but deactivated on or after month start
        eligible_employees = Employee.objects.filter(
            joining_date__lte=month_end
        ).filter(
            Q(status='Active') |
            Q(status='Inactive', deactivated_at__date__gte=month_date)
        )

        updated_salaries = []
        with transaction.atomic():
            for emp in eligible_employees:
                salary = PayrollService.recalculate_salary(emp, month_date, force=force)
                updated_salaries.append(salary)
        return updated_salaries

    @staticmethod
    def recalculate_for_employee(employee):
        """
        Recalculates all unpaid salary records for a given employee.
        """
        from payroll.models import Salary

        unpaid_salaries = Salary.objects.filter(employee=employee, is_paid=False)
        updated_salaries = []
        with transaction.atomic():
            for salary in unpaid_salaries:
                updated = PayrollService.recalculate_salary(employee, salary.month)
                updated_salaries.append(updated)
        return updated_salaries
