from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db.models import Sum
from decimal import Decimal


class Employee(models.Model):
    emp_id = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    address = models.TextField()
    designation = models.CharField(max_length=100)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    joining_date = models.DateField()
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active')
    deactivated_at = models.DateTimeField(null=True, blank=True)
    reactivated_at = models.DateTimeField(null=True, blank=True)
    photo = models.ImageField(upload_to='employee_photos/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.emp_id})"

    def clean(self):
        super().clean()
        if self.monthly_salary is not None and Decimal(str(self.monthly_salary)) < Decimal('0.00'):
            raise ValidationError("Monthly salary cannot be negative.")

    def save(self, *args, **kwargs):
        if self.monthly_salary is not None and Decimal(str(self.monthly_salary)) < Decimal('0.00'):
            raise ValidationError("Monthly salary cannot be negative.")
        # Sync status and is_active using database comparison if instance exists
        if self.pk:
            try:
                orig = Employee.objects.get(pk=self.pk)
                if orig.status == 'Active' and self.status == 'Inactive':
                    self.is_active = False
                elif orig.is_active and not self.is_active:
                    self.status = 'Inactive'
                elif orig.status == 'Inactive' and self.status == 'Active':
                    self.is_active = True
                elif not orig.is_active and self.is_active:
                    self.status = 'Active'
            except Employee.DoesNotExist:
                pass
        else:
            if self.status == 'Inactive':
                self.is_active = False
            elif not self.is_active:
                self.status = 'Inactive'

        if self.status == 'Active':
            self.is_active = True
            # If it was deactivated before, record reactivation
            if self.deactivated_at:
                from django.utils import timezone
                self.reactivated_at = timezone.now()
                self.deactivated_at = None
        else:
            self.is_active = False
            # If it was active before, record deactivation
            if not self.deactivated_at:
                from django.utils import timezone
                self.deactivated_at = timezone.now()
                self.reactivated_at = None

        if not self.emp_id:
            super().save(*args, **kwargs)
            self.emp_id = f"EMP{self.id:04d}"
            super().save(update_fields=['emp_id'])
        else:
            super().save(*args, **kwargs)

    @property
    def daily_rate(self):
        return (Decimal(str(self.monthly_salary)) / Decimal('26')).quantize(Decimal('0.01'))

    @property
    def hourly_rate(self):
        return (self.daily_rate / Decimal('12')).quantize(Decimal('0.01'))


class WorkHours(models.Model):
    HOURS_CHOICES = [(i, f"{i} hours") for i in range(0, 17)]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='work_hours')
    date = models.DateField()
    hours_worked = models.IntegerField(choices=HOURS_CHOICES, default=8)
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_date = self.date
        self._initial_employee_id = self.employee_id

    def __str__(self):
        return f"{self.employee.name} - {self.date} ({self.hours_worked} hrs)"

    @property
    def is_salary_paid(self):
        if self.date:
            return Salary.objects.filter(
                employee_id=self.employee_id,
                month=self.date.replace(day=1),
                is_paid=True
            ).exists()
        return False

    def clean(self):
        if self.hours_worked > 16:
            raise ValidationError("Maximum working hours per day is 16.")
        if self.hours_worked < 0:
            raise ValidationError("Minimum working hours per day is 0.")
        
        # Prevent logging work hours after the employee's deactivation date
        if self.employee.status == 'Inactive':
            if self.employee.deactivated_at and self.date > self.employee.deactivated_at.date():
                raise ValidationError("Cannot log work hours for a deactivated employee after their deactivation date.")

        if self.date:
            month_date = self.date.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot log or modify work hours for a month where salary is already marked as Paid.")
            
            if self.pk:
                orig_date = getattr(self, '_initial_date', None)
                orig_emp_id = getattr(self, '_initial_employee_id', None)
                if (orig_date and orig_date != self.date) or (orig_emp_id and orig_emp_id != self.employee_id):
                    orig_month = orig_date.replace(day=1)
                    if Salary.objects.filter(employee_id=orig_emp_id, month=orig_month, is_paid=True).exists():
                        raise ValidationError("Cannot modify work hours that belong to a month where salary is already marked as Paid.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.date:
            month_date = self.date.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot delete records for a month where salary is already marked as Paid.")
        super().delete(*args, **kwargs)


class MonthlyWorkHours(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='monthly_work_hours')
    month = models.DateField()  # Normalized to 1st of month, e.g. 2026-10-01
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='monthly_hours_marked')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'month')
        ordering = ['-month', 'employee__name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_month = self.month
        self._initial_employee_id = self.employee_id

    def __str__(self):
        return f"{self.employee.name} - {self.month.strftime('%B %Y')} ({self.total_hours} hrs)"

    @property
    def is_salary_paid(self):
        if self.month:
            return Salary.objects.filter(
                employee_id=self.employee_id,
                month=self.month.replace(day=1),
                is_paid=True
            ).exists()
        return False

    def clean(self):
        if self.total_hours is None or self.total_hours < 0:
            raise ValidationError("Total hours cannot be negative.")
        if self.total_hours > 744:
            raise ValidationError("Total hours cannot exceed 744 hours in a month.")

        # Prevent logging work hours after employee deactivation month
        if self.employee.status == 'Inactive' and self.employee.deactivated_at:
            if self.month and self.month > self.employee.deactivated_at.date().replace(day=1):
                raise ValidationError("Cannot log work hours for a deactivated employee after their deactivation month.")

        if self.month:
            month_date = self.month.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot log or modify work hours for a month where salary is already marked as Paid.")

            if self.pk:
                orig_month = getattr(self, '_initial_month', None)
                orig_emp_id = getattr(self, '_initial_employee_id', None)
                if (orig_month and orig_month != self.month) or (orig_emp_id and orig_emp_id != self.employee_id):
                    orig_month_date = orig_month.replace(day=1)
                    if Salary.objects.filter(employee_id=orig_emp_id, month=orig_month_date, is_paid=True).exists():
                        raise ValidationError("Cannot modify work hours that belong to a month where salary is already marked as Paid.")

    def save(self, *args, **kwargs):
        if self.month:
            self.month = self.month.replace(day=1)
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.month:
            month_date = self.month.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot delete records for a month where salary is already marked as Paid.")
        super().delete(*args, **kwargs)


class AdvancePayment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advances')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    given_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_date = self.date
        self._initial_employee_id = self.employee_id

    def __str__(self):
        return f"{self.employee.name} - ₹{self.amount} on {self.date}"

    @property
    def is_salary_paid(self):
        if self.date:
            return Salary.objects.filter(
                employee_id=self.employee_id,
                month=self.date.replace(day=1),
                is_paid=True
            ).exists()
        return False

    def clean(self):
        if self.amount is None or Decimal(str(self.amount)) <= Decimal('0.00'):
            raise ValidationError("Advance payment amount must be greater than zero.")

        # Prevent new advance payments to inactive employees
        if self.employee.status == 'Inactive' and not self.pk:
            raise ValidationError("Cannot create new advance payments for inactive employees.")

        if self.date:
            month_date = self.date.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot log or modify advance payments for a month where salary is already marked as Paid.")
            
            if self.pk:
                orig_date = getattr(self, '_initial_date', None)
                orig_emp_id = getattr(self, '_initial_employee_id', None)
                if (orig_date and orig_date != self.date) or (orig_emp_id and orig_emp_id != self.employee_id):
                    orig_month = orig_date.replace(day=1)
                    if Salary.objects.filter(employee_id=orig_emp_id, month=orig_month, is_paid=True).exists():
                        raise ValidationError("Cannot modify advance payments that belong to a month where salary is already marked as Paid.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.date:
            month_date = self.date.replace(day=1)
            if Salary.objects.filter(employee_id=self.employee_id, month=month_date, is_paid=True).exists():
                raise ValidationError("Cannot delete records for a month where salary is already marked as Paid.")
        super().delete(*args, **kwargs)


class Salary(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='salaries')
    month = models.DateField()  # Store as first day of month
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_advance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Restored database fields
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    final_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    remaining_advance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    is_paid = models.BooleanField(default=False)
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='salaries_paid')
    paid_at = models.DateTimeField(null=True, blank=True)
    unpaid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='salaries_unpaid')
    unpaid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'month')
        ordering = ['-month']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_is_paid = self.is_paid

    def __str__(self):
        return f"{self.employee.name} - {self.month.strftime('%B %Y')}"

    @property
    def daily_rate(self):
        return (Decimal(str(self.monthly_salary)) / Decimal('26')).quantize(Decimal('0.01'))

    @property
    def hourly_rate(self):
        return (self.daily_rate / Decimal('12')).quantize(Decimal('0.01'))

    def recalculate(self, force=False):
        from payroll.services import PayrollService
        updated = PayrollService.recalculate_salary(self.employee, self.month, force=force)
        self.monthly_salary = updated.monthly_salary
        self.total_hours = updated.total_hours
        self.total_advance = updated.total_advance
        self.gross_salary = updated.gross_salary
        self.final_salary = updated.final_salary
        self.remaining_advance = updated.remaining_advance
        self.is_paid = updated.is_paid

    def clean(self):
        super().clean()
        if getattr(self, '_force_recalculate', False):
            return

        if self.pk and getattr(self, '_initial_is_paid', False):
            try:
                original = Salary.objects.get(pk=self.pk)
                if original.is_paid:
                    # If this is an authorized payment status transition (e.g. marking as unpaid)
                    if getattr(self, '_allow_status_change', False):
                        financial_fields = ['employee', 'month', 'total_hours', 'total_advance', 'monthly_salary', 'gross_salary', 'final_salary', 'remaining_advance']
                        for field in financial_fields:
                            if getattr(self, field) != getattr(original, field):
                                raise ValidationError("Financial figures cannot be changed while toggling payment status.")
                        return

                    fields_to_check = ['employee', 'month', 'total_hours', 'total_advance', 'monthly_salary', 'gross_salary', 'final_salary', 'remaining_advance', 'is_paid', 'paid_by', 'paid_at']
                    for field in fields_to_check:
                        if getattr(self, field) != getattr(original, field):
                            raise ValidationError("Paid salary cannot be modified.")
            except Salary.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_paid:
            raise ValidationError("Paid salary cannot be deleted.")
        super().delete(*args, **kwargs)


class SalaryPaymentLog(models.Model):
    salary = models.ForeignKey(Salary, on_delete=models.CASCADE, related_name='payment_logs')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    month = models.DateField()
    action = models.CharField(max_length=20)  # 'PAID', 'UNPAID'
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    previous_state = models.CharField(max_length=20, blank=True)
    new_state = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.employee.name} - {self.month.strftime('%B %Y')} - {self.action} by {self.performed_by}"


# --- Signals to auto-recalculate salary ---

import queue
import threading
from django.db import connection

_recalc_queue = queue.Queue()
_worker_thread = None
_queue_lock = threading.Lock()

def _bg_worker():
    while True:
        try:
            task = _recalc_queue.get()
            if task is None:
                break
            employee_id, month_date = task
            try:
                from payroll.models import Employee
                from payroll.services import PayrollService
                employee = Employee.objects.get(pk=employee_id)
                PayrollService.recalculate_salary(employee, month_date)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Background salary recalculation failed for employee %s on %s", employee_id, month_date)
            finally:
                _recalc_queue.task_done()
                connection.close()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Error in background worker thread")

def start_worker():
    global _worker_thread
    with _queue_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_bg_worker, name="SalaryRecalcWorker", daemon=True)
            _worker_thread.start()

def queue_recalculation(employee, month_date):
    start_worker()
    task = (employee.id, month_date.replace(day=1))
    _recalc_queue.put(task)


def safe_recalculate_salary(employee, date):
    import sys
    from django.db import transaction

    if 'test' in sys.argv or 'pytest' in sys.argv:
        from payroll.services import PayrollService
        try:
            PayrollService.recalculate_salary(employee, date)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Salary recalculation failed for employee %s on date %s", employee, date)
    else:
        transaction.on_commit(lambda: queue_recalculation(employee, date))


def safe_recalculate_for_employee(employee):
    import sys
    from django.db import transaction

    if 'test' in sys.argv or 'pytest' in sys.argv:
        from payroll.services import PayrollService
        try:
            PayrollService.recalculate_for_employee(employee)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Salary recalculation failed for employee %s", employee)
    else:
        from payroll.models import Salary
        unpaid_salaries = Salary.objects.filter(employee=employee, is_paid=False)
        for s in unpaid_salaries:
            transaction.on_commit(lambda s_month=s.month: queue_recalculation(employee, s_month))


@receiver(pre_save, sender=WorkHours)
def track_workhours_changes(sender, instance, **kwargs):
    if instance.pk:
        instance._original_date = getattr(instance, '_initial_date', None)
        instance._original_employee_id = getattr(instance, '_initial_employee_id', None)

@receiver(post_save, sender=WorkHours)
def update_salary_on_workhours_save(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.date)
    
    orig_date = getattr(instance, '_original_date', None)
    orig_emp_id = getattr(instance, '_original_employee_id', None)
    
    if orig_date and orig_date != instance.date:
        safe_recalculate_salary(instance.employee, orig_date)
    if orig_emp_id and orig_emp_id != instance.employee_id:
        from payroll.models import Employee
        try:
            orig_emp = Employee.objects.get(pk=orig_emp_id)
            safe_recalculate_salary(orig_emp, orig_date or instance.date)
        except Employee.DoesNotExist:
            pass

@receiver(post_delete, sender=WorkHours)
def update_salary_on_workhours_delete(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.date)


@receiver(pre_save, sender=MonthlyWorkHours)
def track_monthly_workhours_changes(sender, instance, **kwargs):
    if instance.pk:
        instance._original_month = getattr(instance, '_initial_month', None)
        instance._original_employee_id = getattr(instance, '_initial_employee_id', None)

@receiver(post_save, sender=MonthlyWorkHours)
def update_salary_on_monthly_workhours_save(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.month)
    orig_month = getattr(instance, '_original_month', None)
    orig_emp_id = getattr(instance, '_original_employee_id', None)
    if orig_month and orig_month != instance.month:
        safe_recalculate_salary(instance.employee, orig_month)
    if orig_emp_id and orig_emp_id != instance.employee_id:
        from payroll.models import Employee
        try:
            orig_emp = Employee.objects.get(pk=orig_emp_id)
            safe_recalculate_salary(orig_emp, orig_month or instance.month)
        except Employee.DoesNotExist:
            pass

@receiver(post_delete, sender=MonthlyWorkHours)
def update_salary_on_monthly_workhours_delete(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.month)

@receiver(pre_save, sender=AdvancePayment)
def track_advance_changes(sender, instance, **kwargs):
    if instance.pk:
        instance._original_date = getattr(instance, '_initial_date', None)
        instance._original_employee_id = getattr(instance, '_initial_employee_id', None)

@receiver(post_save, sender=AdvancePayment)
def update_salary_on_advance_save(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.date)
    
    orig_date = getattr(instance, '_original_date', None)
    orig_emp_id = getattr(instance, '_original_employee_id', None)
    
    if orig_date and orig_date != instance.date:
        safe_recalculate_salary(instance.employee, orig_date)
    if orig_emp_id and orig_emp_id != instance.employee_id:
        from payroll.models import Employee
        try:
            orig_emp = Employee.objects.get(pk=orig_emp_id)
            safe_recalculate_salary(orig_emp, orig_date or instance.date)
        except Employee.DoesNotExist:
            pass

@receiver(post_delete, sender=AdvancePayment)
def update_salary_on_advance_delete(sender, instance, **kwargs):
    safe_recalculate_salary(instance.employee, instance.date)

@receiver(pre_save, sender=Employee)
def track_employee_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            original = Employee.objects.get(pk=instance.pk)
            instance._original_monthly_salary = original.monthly_salary
        except Employee.DoesNotExist:
            pass

@receiver(post_save, sender=Employee)
def update_salary_on_employee_change(sender, instance, created, **kwargs):
    if not created:
        orig_salary = getattr(instance, '_original_monthly_salary', None)
        if orig_salary is not None and orig_salary != instance.monthly_salary:
            safe_recalculate_for_employee(instance)

@receiver(post_save, sender=Salary)
def on_salary_create(sender, instance, created, **kwargs):
    if created:
        safe_recalculate_salary(instance.employee, instance.month)
