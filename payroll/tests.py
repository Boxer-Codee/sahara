from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User
import datetime
import json
from decimal import Decimal
from .models import Employee, WorkHours, AdvancePayment, Salary, MonthlyWorkHours, SalaryPaymentLog

class EmployeeSoftDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin', password='password')
        self.employee = Employee.objects.create(
            name="Tapan Mahapatra",
            phone="1234567890",
            address="Bhubaneswar, Odisha",
            designation="Software Engineer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 6, 1)
        )

    def test_default_status_is_active(self):
        """Verify new employees are created as Active and is_active=True."""
        self.assertEqual(self.employee.status, 'Active')
        self.assertTrue(self.employee.is_active)
        self.assertIsNone(self.employee.deactivated_at)
        self.assertIsNone(self.employee.reactivated_at)

    def test_deactivation_soft_deletes_employee(self):
        """Verify deactivation sets status to Inactive, sets deactivated_at, and is_active to False."""
        # Deactivate
        self.employee.status = 'Inactive'
        self.employee.save()

        self.assertFalse(self.employee.is_active)
        self.assertEqual(self.employee.status, 'Inactive')
        self.assertIsNotNone(self.employee.deactivated_at)
        self.assertIsNone(self.employee.reactivated_at)

    def test_reactivation_restores_status(self):
        """Verify reactivation restores status to Active and sets reactivated_at."""
        # Deactivate first
        self.employee.status = 'Inactive'
        self.employee.save()
        deactivation_time = self.employee.deactivated_at

        # Reactivate
        self.employee.status = 'Active'
        self.employee.save()

        self.assertTrue(self.employee.is_active)
        self.assertEqual(self.employee.status, 'Active')
        self.assertIsNone(self.employee.deactivated_at)
        self.assertIsNotNone(self.employee.reactivated_at)

    def test_cannot_log_work_hours_after_deactivation_date(self):
        """Verify validation blocks logging work hours for a date after employee's deactivation."""
        self.employee.status = 'Inactive'
        self.employee.save()

        # Try to log work hours on day after deactivation
        deactivation_date = self.employee.deactivated_at.date()
        future_date = deactivation_date + datetime.timedelta(days=1)

        wh = WorkHours(
            employee=self.employee,
            date=future_date,
            hours_worked=8,
            marked_by=self.user
        )

        with self.assertRaises(ValidationError) as context:
            wh.full_clean()
        self.assertIn("Cannot log work hours for a deactivated employee after their deactivation date", str(context.exception))

    def test_can_log_work_hours_on_or_before_deactivation_date(self):
        """Verify logging work hours on or before deactivation date is allowed."""
        # Set deactivation date manually in past to verify
        self.employee.status = 'Inactive'
        self.employee.save()

        deactivation_date = self.employee.deactivated_at.date()
        past_date = deactivation_date - datetime.timedelta(days=2)

        wh = WorkHours.objects.create(
            employee=self.employee,
            date=past_date,
            hours_worked=8,
            marked_by=self.user
        )
        # Should not raise ValidationError
        self.assertEqual(wh.hours_worked, 8)

    def test_cannot_create_new_advance_payment_for_inactive_employee(self):
        """Verify validation blocks creating new advances for deactivated employees."""
        self.employee.status = 'Inactive'
        self.employee.save()

        adv = AdvancePayment(
            employee=self.employee,
            amount=5000.00,
            given_by=self.user,
            date=timezone.now().date()
        )

        with self.assertRaises(ValidationError) as context:
            adv.full_clean()
        self.assertIn("Cannot create new advance payments for inactive employees", str(context.exception))

    def test_existing_advances_are_preserved(self):
        """Verify existing advances can still be retrieved/saved even if employee becomes inactive later."""
        # Create advance first while active
        adv = AdvancePayment.objects.create(
            employee=self.employee,
            amount=5000.00,
            given_by=self.user,
            date=timezone.now().date()
        )

        # Deactivate employee
        self.employee.status = 'Inactive'
        self.employee.save()

        # Refresh advance from database - should clean and save without issue since it has a PK
        adv.refresh_from_db()
        adv.full_clean()
        adv.save()
        self.assertEqual(adv.amount, 5000.00)


from unittest.mock import patch
from decimal import Decimal

class ProratedSalaryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_user', password='password', email='admin@example.com')
        self.manager = User.objects.create_user(username='manager_user', password='password', is_staff=True)

    def test_scenario_1_full_month_active_employee(self):
        """
        Scenario 1: Full-month active employee.
        Verifies normal monthly calculation based on logged hours.
        """
        employee = Employee.objects.create(
            name="Active Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 5, 1)
        )

        # Log work hours for 20 days in June 2026 (12 hours/day)
        for day in range(1, 21):
            WorkHours.objects.create(
                employee=employee,
                date=datetime.date(2026, 6, day),
                hours_worked=12,
                marked_by=self.manager
            )

        mock_now = timezone.make_aware(datetime.datetime(2026, 6, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now):
            salary, created = Salary.objects.get_or_create(employee=employee, month=datetime.date(2026, 6, 1))
            salary.recalculate()

        # Calculation checks:
        # daily_rate = 30000.00 / 26 = 1153.85
        # hourly_rate = 1153.85 / 12 = 96.15
        # total_hours = 240
        # gross_salary = 240 * 96.15 = 23076.00
        self.assertEqual(salary.total_hours, Decimal('240'))
        self.assertEqual(salary.daily_rate, Decimal('1153.85'))
        self.assertEqual(salary.hourly_rate, Decimal('96.15'))
        self.assertEqual(salary.gross_salary, Decimal('23076.00'))
        self.assertEqual(salary.final_salary, Decimal('23076.00'))

    def test_scenario_2_mid_month_deactivation(self):
        """
        Scenario 2: Mid-month deactivation.
        Verifies calculations are based purely on hours worked before deactivation.
        Also verifies advance deduction.
        """
        employee = Employee.objects.create(
            name="Deactivated Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 6, 1)
        )

        # Log work hours for 15 days in June 2026 (8 hours/day)
        for day in range(1, 16):
            WorkHours.objects.create(
                employee=employee,
                date=datetime.date(2026, 6, day),
                hours_worked=8,
                marked_by=self.manager
            )

        # Record advance while active
        AdvancePayment.objects.create(
            employee=employee,
            amount=2000.00,
            given_by=self.admin,
            date=datetime.date(2026, 6, 5)
        )

        # Deactivate employee on June 15
        employee.status = 'Inactive'
        employee.deactivated_at = timezone.make_aware(datetime.datetime(2026, 6, 15, 17, 0, 0))
        employee.is_active = False
        employee.save()

        # Recalculate
        mock_now = timezone.make_aware(datetime.datetime(2026, 6, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now):
            salary, created = Salary.objects.get_or_create(employee=employee, month=datetime.date(2026, 6, 1))
            salary.recalculate()

        # daily_rate = 30000.00 / 26 = 1153.85
        # hourly_rate = 96.15
        # total_hours = 120
        # gross_salary = 120 * 96.15 = 11538.00
        # final_salary = 11538.00 - 2000.00 = 9538.00
        self.assertEqual(salary.total_hours, Decimal('120'))
        self.assertEqual(salary.daily_rate, Decimal('1153.85'))
        self.assertEqual(salary.hourly_rate, Decimal('96.15'))
        self.assertEqual(salary.gross_salary, Decimal('11538.00'))
        self.assertEqual(salary.total_advance, Decimal('2000.00'))
        self.assertEqual(salary.final_salary, Decimal('9538.00'))

    def test_scenario_3_inactive_before_payroll_month(self):
        """
        Scenario 3: Employee inactive before payroll month.
        Verifies no payroll record is generated when displaying salary list.
        """
        # Create and deactivate in May 2026
        with patch('django.utils.timezone.now', return_value=timezone.make_aware(datetime.datetime(2026, 5, 25, 12, 0, 0))):
            employee = Employee.objects.create(
                name="Old Inactive Employee",
                phone="1234567890",
                address="Test address",
                designation="Developer",
                monthly_salary=30000.00,
                joining_date=datetime.date(2026, 4, 1)
            )

            # Deactivate in May 2026
            employee.status = 'Inactive'
            employee.deactivated_at = timezone.make_aware(datetime.datetime(2026, 5, 25, 12, 0, 0))
            employee.is_active = False
            employee.save()

        # Login and view June 2026 salary list
        self.client.login(username='admin_user', password='password')

        class MockDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2026, 6, 10)

        from django.test.signals import template_rendered

        with patch.object(template_rendered, 'send'), \
             patch('payroll.views.datetime.date', MockDate), \
             patch('django.utils.timezone.now', return_value=timezone.make_aware(datetime.datetime(2026, 6, 10, 12, 0, 0))):
            response = self.client.get('/salary/?month=2026-06')

        self.assertEqual(response.status_code, 200)

        # Verify no June salary was generated for this employee
        salary_exists = Salary.objects.filter(employee=employee, month=datetime.date(2026, 6, 1)).exists()
        self.assertFalse(salary_exists)

    def test_scenario_4_employee_reactivated_in_later_month(self):
        """
        Scenario 4: Employee reactivated in a later month.
        Verifies salary for reactivation month based on hours worked.
        """
        employee = Employee.objects.create(
            name="Reactivated Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 5, 1)
        )

        # Deactivate on June 15
        employee.status = 'Inactive'
        employee.deactivated_at = timezone.make_aware(datetime.datetime(2026, 6, 15, 12, 0, 0))
        employee.is_active = False
        employee.save()

        # Reactivate on July 10
        # Move state to Active, then manually adjust reactivated_at to represent July 10
        employee.status = 'Active'
        employee.save()
        employee.reactivated_at = timezone.make_aware(datetime.datetime(2026, 7, 10, 12, 0, 0))
        employee.save()

        # Log work hours for 11 days (July 10 to 20, 8 hours/day) = 88 hours
        for day in range(10, 21):
            WorkHours.objects.create(
                employee=employee,
                date=datetime.date(2026, 7, day),
                hours_worked=8,
                marked_by=self.manager
            )

        mock_now = timezone.make_aware(datetime.datetime(2026, 7, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now):
            salary_july, _ = Salary.objects.get_or_create(employee=employee, month=datetime.date(2026, 7, 1))
            salary_july.recalculate()

        # daily_rate = 30000 / 26 = 1153.85
        # hourly_rate = 96.15
        # 88 hours * 96.15 = 8461.20
        self.assertEqual(salary_july.total_hours, Decimal('88'))
        self.assertEqual(salary_july.gross_salary, Decimal('8461.20'))

        # Log work hours for August (full-month active, 240 hours)
        for day in range(1, 21):
            WorkHours.objects.create(
                employee=employee,
                date=datetime.date(2026, 8, day),
                hours_worked=12,
                marked_by=self.manager
            )

        mock_now_aug = timezone.make_aware(datetime.datetime(2026, 8, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now_aug):
            salary_aug, _ = Salary.objects.get_or_create(employee=employee, month=datetime.date(2026, 8, 1))
            salary_aug.recalculate()

        self.assertEqual(salary_aug.gross_salary, Decimal('23076.00'))

    def test_scenario_5_historical_payroll_integrity(self):
        """
        Scenario 5: Historical payroll integrity (immutability).
        Verifies that paid records are not modified by recalculation,
        and cannot be modified or deleted.
        Also verifies that unpaid past-month records ARE recalculated.
        """
        employee = Employee.objects.create(
            name="Immutable Test Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 5, 1)
        )

        # 1. Paid salary record
        # Create June 2026 salary record and set inputs manually, then mark as paid
        salary_paid, _ = Salary.objects.update_or_create(
            employee=employee,
            month=datetime.date(2026, 6, 1),
            defaults={
                'monthly_salary': Decimal('30000.00'),
                'total_hours': Decimal('240'),
                'total_advance': Decimal('2000.00'),
                'is_paid': True
            }
        )

        # Try to modify paid salary - should raise ValidationError
        salary_paid.total_hours = Decimal('250')
        with self.assertRaises(ValidationError):
            salary_paid.save()

        # Try to delete paid salary - should raise ValidationError
        with self.assertRaises(ValidationError):
            salary_paid.delete()

        # Refresh from DB to verify it remains unmodified
        salary_paid.refresh_from_db()
        self.assertEqual(salary_paid.total_hours, Decimal('240'))

        # Try to add work hours in the paid month - should raise ValidationError
        wh = WorkHours(
            employee=employee,
            date=datetime.date(2026, 6, 10),
            hours_worked=8,
            marked_by=self.manager
        )
        with self.assertRaises(ValidationError):
            wh.save()

        # Try to add advance payment in the paid month - should raise ValidationError
        adv = AdvancePayment(
            employee=employee,
            amount=500.00,
            given_by=self.admin,
            date=datetime.date(2026, 6, 15)
        )
        with self.assertRaises(ValidationError):
            adv.save()

        # 2. Past month unpaid salary record - should be recalculated
        # Create May 2026 salary record, not paid, with custom inputs
        salary_past, _ = Salary.objects.update_or_create(
            employee=employee,
            month=datetime.date(2026, 5, 1),
            defaults={
                'monthly_salary': Decimal('30000.00'),
                'total_hours': Decimal('200'),
                'total_advance': Decimal('1000.00'),
                'is_paid': False
            }
        )

        # Change monthly salary (updates employee)
        employee.monthly_salary = 40000.00
        employee.save()

        # Log work hours for May
        WorkHours.objects.create(
            employee=employee,
            date=datetime.date(2026, 5, 10),
            hours_worked=12,
            marked_by=self.manager
        )

        # Log advance for May
        AdvancePayment.objects.create(
            employee=employee,
            amount=500.00,
            given_by=self.admin,
            date=datetime.date(2026, 5, 15)
        )

        # Recalculate
        mock_now = timezone.make_aware(datetime.datetime(2026, 6, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now):
            salary_past.recalculate()

        # Values should be updated!
        # monthly_salary updated to employee's new salary (40000.00)
        self.assertEqual(salary_past.monthly_salary, Decimal('40000.00'))
        # total_hours updated to 12
        self.assertEqual(salary_past.total_hours, Decimal('12'))
        # total_advance updated to 500.00
        self.assertEqual(salary_past.total_advance, Decimal('500.00'))

    def test_max_hours_limit(self):
        """Verify that logging more than 16 hours is blocked by validation."""
        employee = Employee.objects.create(
            name="Hours Test Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 6, 1)
        )
        wh = WorkHours(
            employee=employee,
            date=datetime.date(2026, 6, 1),
            hours_worked=17,  # Invalid, max is 16
            marked_by=self.manager
        )
        with self.assertRaises(ValidationError) as context:
            wh.full_clean()
        self.assertIn("Maximum working hours per day is 16.", str(context.exception))

    def test_advance_exceeds_gross_salary(self):
        """Verify that if Advance > Gross Salary, final_salary = 0.00 and remaining_advance = Advance - Gross."""
        employee = Employee.objects.create(
            name="Advance Test Employee",
            phone="1234567890",
            address="Test address",
            designation="Developer",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 6, 1)
        )
        # Log 8 hours on June 1st (Gross Salary will be 8 * 96.15 = 769.20)
        WorkHours.objects.create(
            employee=employee,
            date=datetime.date(2026, 6, 1),
            hours_worked=8,
            marked_by=self.manager
        )
        # Advance payment of ₹2,000 (which exceeds Gross Salary)
        AdvancePayment.objects.create(
            employee=employee,
            amount=2000.00,
            given_by=self.admin,
            date=datetime.date(2026, 6, 5)
        )

        mock_now = timezone.make_aware(datetime.datetime(2026, 6, 25, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mock_now):
            salary, _ = Salary.objects.get_or_create(employee=employee, month=datetime.date(2026, 6, 1))
            salary.recalculate()

        self.assertEqual(salary.final_salary, Decimal('0.00'))
        self.assertEqual(salary.remaining_advance, Decimal('2000.00') - salary.gross_salary)
        self.assertTrue(salary.remaining_advance > 0)


class PayrollEngineRefinedTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_user', password='password', email='admin@example.com')
        self.manager = User.objects.create_user(username='manager_user', password='password', is_staff=True)
        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="1234567890",
            address="Test Address",
            designation="Developer",
            monthly_salary=26000.00,  # daily = 1000, hourly = 83.33
            joining_date=datetime.date(2026, 4, 1)
        )

    def test_workhours_signals_trigger_recalculation(self):
        """Test that creating, updating, and deleting WorkHours triggers auto-recalculations immediately."""
        # 1. Create WorkHours
        wh = WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 7, 5),
            hours_worked=12,
            marked_by=self.manager
        )
        salary = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        self.assertEqual(salary.total_hours, Decimal('12.00'))
        self.assertEqual(salary.gross_salary, Decimal('999.96'))

        # 2. Update WorkHours (change hours_worked)
        wh.hours_worked = 8
        wh.save()
        salary.refresh_from_db()
        self.assertEqual(salary.total_hours, Decimal('8.00'))
        self.assertEqual(salary.gross_salary, Decimal('666.64'))

        # 3. Update WorkHours (change date to a different month)
        wh.date = datetime.date(2026, 8, 5)
        wh.save()

        salary_july = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        salary_aug = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 8, 1))

        self.assertEqual(salary_july.total_hours, Decimal('0.00'))
        self.assertEqual(salary_july.gross_salary, Decimal('0.00'))
        self.assertEqual(salary_aug.total_hours, Decimal('8.00'))
        self.assertEqual(salary_aug.gross_salary, Decimal('666.64'))

        # 4. Delete WorkHours
        wh.delete()
        salary_aug.refresh_from_db()
        self.assertEqual(salary_aug.total_hours, Decimal('0.00'))
        self.assertEqual(salary_aug.gross_salary, Decimal('0.00'))

    def test_advance_signals_trigger_recalculation(self):
        """Test that creating, updating, and deleting AdvancePayment triggers auto-recalculations immediately."""
        WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 7, 5),
            hours_worked=12,
            marked_by=self.manager
        )

        # 1. Create AdvancePayment
        adv = AdvancePayment.objects.create(
            employee=self.employee,
            amount=500.00,
            given_by=self.admin,
            date=datetime.date(2026, 7, 10)
        )
        salary = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        self.assertEqual(salary.total_advance, Decimal('500.00'))
        self.assertEqual(salary.final_salary, Decimal('499.96'))

        # 2. Update AdvancePayment (change date to next month)
        adv.date = datetime.date(2026, 8, 10)
        adv.save()

        salary_july = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        salary_aug = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 8, 1))

        self.assertEqual(salary_july.total_advance, Decimal('0.00'))
        self.assertEqual(salary_july.final_salary, Decimal('999.96'))
        self.assertEqual(salary_aug.total_advance, Decimal('500.00'))

        # 3. Delete AdvancePayment
        adv.delete()
        salary_aug.refresh_from_db()
        self.assertEqual(salary_aug.total_advance, Decimal('0.00'))

    def test_employee_daily_rate_change_recalculates_unpaid_payroll(self):
        """Test that changing employee monthly salary / daily rate recalculates all unpaid salary records."""
        wh_july = WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 7, 5),
            hours_worked=12,
            marked_by=self.manager
        )
        wh_aug = WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 8, 5),
            hours_worked=12,
            marked_by=self.manager
        )

        salary_july = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        salary_aug = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 8, 1))
        self.assertEqual(salary_july.gross_salary, Decimal('999.96'))
        self.assertEqual(salary_aug.gross_salary, Decimal('999.96'))

        # Update employee's monthly salary
        self.employee.monthly_salary = 52000.00
        self.employee.save()

        salary_july.refresh_from_db()
        salary_aug.refresh_from_db()
        self.assertEqual(salary_july.gross_salary, Decimal('2000.04'))
        self.assertEqual(salary_aug.gross_salary, Decimal('2000.04'))

    def test_historical_recalculation_command_repairs_paid_payroll(self):
        """Test that the recalculate_payroll command repairs historical records while preserving paid status."""
        WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 4, 10),
            hours_worked=12,
            marked_by=self.manager
        )

        salary = Salary.objects.get(employee=self.employee, month=datetime.date(2026, 4, 1))

        # Bypassing protection to simulate corrupted data
        salary._force_recalculate = True
        salary.total_hours = Decimal('0.00')
        salary.gross_salary = Decimal('0.00')
        salary.final_salary = Decimal('0.00')
        salary.is_paid = True
        salary.save()

        # Verify it's corrupted in DB
        salary.refresh_from_db()
        self.assertEqual(salary.gross_salary, Decimal('0.00'))
        self.assertTrue(salary.is_paid)

        # Run management command for April 2026
        from django.core.management import call_command
        call_command('recalculate_payroll', months=['2026-04'])

        # Verify it got repaired but remains paid
        salary.refresh_from_db()
        self.assertEqual(salary.total_hours, Decimal('12.00'))
        self.assertEqual(salary.gross_salary, Decimal('999.96'))
        self.assertEqual(salary.final_salary, Decimal('999.96'))
        self.assertTrue(salary.is_paid)

    def test_payroll_engine_regression_bugs(self):
        """Regression tests for:
        - Current month WorkHours create/update/delete.
        - Current month Advance create/update/delete.
        - Advance greater than Gross Salary.
        - Gross Salary always equals TotalHours * (DailyRate / 12).
        - Final Salary never below zero.
        """
        # Create an active employee
        employee = Employee.objects.create(
            name="Regression Employee",
            phone="9876543210",
            address="Test Street",
            designation="Manager",
            monthly_salary=26000.00,  # daily_rate = 1000.00, hourly_rate = 83.33
            joining_date=datetime.date(2026, 7, 1)
        )

        # Current month is July 2026
        # 1. Create WorkHours
        wh = WorkHours.objects.create(
            employee=employee,
            date=datetime.date(2026, 7, 10),
            hours_worked=12,
            marked_by=self.manager
        )

        # Verify recalculation happened immediately
        salary = Salary.objects.get(employee=employee, month=datetime.date(2026, 7, 1))
        self.assertEqual(salary.total_hours, Decimal('12.00'))
        self.assertEqual(salary.gross_salary, Decimal('999.96'))  # 12 * 83.33
        self.assertEqual(salary.final_salary, Decimal('999.96'))

        # 2. Update WorkHours
        wh.hours_worked = 6
        wh.save()

        salary.refresh_from_db()
        self.assertEqual(salary.total_hours, Decimal('6.00'))
        self.assertEqual(salary.gross_salary, Decimal('499.98'))  # 6 * 83.33
        self.assertEqual(salary.final_salary, Decimal('499.98'))

        # 3. Create Advance Payment (less than Gross Salary)
        adv = AdvancePayment.objects.create(
            employee=employee,
            amount=200.00,
            given_by=self.admin,
            date=datetime.date(2026, 7, 15)
        )

        salary.refresh_from_db()
        self.assertEqual(salary.total_advance, Decimal('200.00'))
        self.assertEqual(salary.final_salary, Decimal('299.98'))  # 499.98 - 200.00

        # 4. Update Advance Payment (greater than Gross Salary)
        adv.amount = 600.00
        adv.save()

        salary.refresh_from_db()
        self.assertEqual(salary.total_advance, Decimal('600.00'))
        # Gross salary is 499.98, Advance is 600.00
        # Final Salary must never be below zero
        self.assertEqual(salary.final_salary, Decimal('0.00'))
        self.assertEqual(salary.remaining_advance, Decimal('100.02'))

        # 5. Delete Advance Payment
        adv.delete()

        salary.refresh_from_db()
        self.assertEqual(salary.total_advance, Decimal('0.00'))
        self.assertEqual(salary.final_salary, Decimal('499.98'))
        self.assertEqual(salary.remaining_advance, Decimal('0.00'))

        # 6. Delete WorkHours
        wh.delete()

        salary.refresh_from_db()
        self.assertEqual(salary.total_hours, Decimal('0.00'))
        self.assertEqual(salary.gross_salary, Decimal('0.00'))
        self.assertEqual(salary.final_salary, Decimal('0.00'))


class PageViewPerformanceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='admin_user', password='password', email='admin@test.com')
        self.client.login(username='admin_user', password='password')

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="1234567890",
            address="Address",
            designation="Tester",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 6, 1)
        )
        # Create work hours to trigger a Salary record creation via signals
        from payroll.models import WorkHours
        self.wh = WorkHours.objects.create(
            employee=self.employee,
            date=datetime.date(2026, 6, 10),
            hours_worked=8,
            marked_by=self.user
        )

    def test_page_loads_do_not_execute_writes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from django.test.signals import template_rendered
        from unittest.mock import patch

        urls = [
            '/dashboard/',
            '/salary/?month=2026-06',
            '/reports/?month=2026-06',
            f'/employee/{self.employee.id}/',
            '/reports/export/csv/?month=2026-06',
            '/reports/export/excel/?month=2026-06',
        ]

        for url in urls:
            with patch.object(template_rendered, 'send'):
                with CaptureQueriesContext(connection) as ctx:
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200, f"Failed loading {url}")

                    # Verify zero INSERT or UPDATE queries
                    for q in ctx.captured_queries:
                        sql = q['sql'].upper()
                        self.assertFalse(sql.startswith('INSERT ') or sql.startswith('"INSERT '), f"Insert executed in view {url}: {sql}")
                        self.assertFalse(sql.startswith('UPDATE ') or sql.startswith('"UPDATE '), f"Update executed in view {url}: {sql}")


class WorkHoursViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_superuser(username='test_manager', password='password', email='manager@test.com')
        self.client.login(username='test_manager', password='password')
        self.employee = Employee.objects.create(
            name="Alice Smith",
            phone="1234567890",
            address="Address Alice",
            designation="Developer",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 6, 1)
        )

    def test_load_monthly_workhours_page(self):
        # 1. Load monthly work hours page
        response = self.client.get('/workhours/?month=7&year=2026')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "Mark Work Hours")
        self.assertContains(response, "Total Monthly Hours")

    def test_add_monthly_work_hours(self):
        # 2. Save monthly work hours for employee
        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '240'
        })
        self.assertEqual(response.status_code, 302)
        mwh = MonthlyWorkHours.objects.filter(employee=self.employee, month=datetime.date(2026, 7, 1)).first()
        self.assertIsNotNone(mwh)
        self.assertEqual(mwh.total_hours, 240)

        # Verify salary recalculation
        salary = Salary.objects.filter(employee=self.employee, month=datetime.date(2026, 7, 1)).first()
        self.assertIsNotNone(salary)
        self.assertEqual(salary.total_hours, 240)
        self.assertEqual(salary.gross_salary, salary.final_salary)

    def test_update_existing_monthly_work_hours(self):
        # 3. Update existing monthly work hours (no duplicates)
        mwh = MonthlyWorkHours.objects.create(
            employee=self.employee,
            month=datetime.date(2026, 7, 1),
            total_hours=240,
            marked_by=self.manager
        )
        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '264'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MonthlyWorkHours.objects.filter(employee=self.employee, month=datetime.date(2026, 7, 1)).count(), 1)
        mwh.refresh_from_db()
        self.assertEqual(mwh.total_hours, 264)

    def test_valid_zero_monthly_hours(self):
        # 4. Valid zero hours allowed
        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '0'
        })
        self.assertEqual(response.status_code, 302)
        mwh = MonthlyWorkHours.objects.get(employee=self.employee, month=datetime.date(2026, 7, 1))
        self.assertEqual(mwh.total_hours, 0)

    def test_invalid_monthly_hours(self):
        from django.contrib.messages import get_messages
        # 5. Invalid hours (negative, non-numeric, > 744)
        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': 'invalid'
        })
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("Invalid hours format" in m for m in messages_list))

        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '-10'
        })
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("cannot be negative" in m for m in messages_list))

        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '800'
        })
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("cannot exceed 744" in m for m in messages_list))

    def test_bulk_save_via_ajax_json(self):
        # 6. Bulk save via AJAX JSON
        emp2 = Employee.objects.create(
            name="Bob Jones",
            phone="0987654321",
            address="Address Bob",
            designation="Tester",
            monthly_salary=20000.00,
            joining_date=datetime.date(2026, 6, 1)
        )
        import json
        payload = {
            'month': 7,
            'year': 2026,
            'entries': {
                str(self.employee.id): '252',
                str(emp2.id): '240'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 2)
        self.assertEqual(data['grand_total_hours'], 492.0)

    def test_cannot_modify_paid_salary_month(self):
        # 7. Paid salary locks month hours
        Salary.objects.create(
            employee=self.employee,
            month=datetime.date(2026, 7, 1),
            total_hours=240,
            monthly_salary=26000.00,
            gross_salary=20000.00,
            final_salary=20000.00,
            is_paid=True
        )
        response = self.client.post('/workhours/', {
            'month': '7',
            'year': '2026',
            f'hours_{self.employee.id}': '300'
        })
        self.assertEqual(response.status_code, 302)
        # Verify MonthlyWorkHours was not updated to 300
        mwh = MonthlyWorkHours.objects.filter(employee=self.employee, month=datetime.date(2026, 7, 1)).first()
        if mwh:
            self.assertNotEqual(mwh.total_hours, 300)

    def test_role_permissions(self):
        # 8. Test role permissions
        regular_user = User.objects.create_user(username='regular_user', password='password')
        self.client.login(username='regular_user', password='password')
        response = self.client.get('/workhours/')
        self.assertEqual(response.status_code, 403)

        response = self.client.post('/workhours/', {'month': 7, 'year': 2026})
        self.assertEqual(response.status_code, 403)

    def test_view_monthly_history(self):
        # 9. View monthly history
        MonthlyWorkHours.objects.create(
            employee=self.employee,
            month=datetime.date(2026, 7, 1),
            total_hours=250,
            marked_by=self.manager
        )
        response = self.client.get('/workhours/history/?month=7&year=2026')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "250")


class SalaryPaymentStatusTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_boss', password='password', email='admin@test.com')
        self.manager = User.objects.create_user(username='manager_bob', password='password', is_staff=True)
        self.unauthorized_user = User.objects.create_user(username='regular_joe', password='password', is_staff=False, is_superuser=False)
        self.employee = Employee.objects.create(
            name="Charlie Brown",
            phone="9876543210",
            address="123 Street",
            designation="Accountant",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 1, 1)
        )
        self.month = datetime.date(2026, 7, 1)
        self.salary = Salary.objects.create(
            employee=self.employee,
            month=self.month,
            monthly_salary=26000.00,
            total_hours=240,
            gross_salary=20000.00,
            final_salary=20000.00,
            is_paid=False
        )

    def test_admin_mark_unpaid_salary_as_paid(self):
        """1. Admin can mark an unpaid salary as Paid."""
        self.client.login(username='admin_boss', password='password')
        response = self.client.post(f'/salary/{self.salary.id}/mark-paid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)
        self.assertEqual(self.salary.paid_by, self.admin)
        self.assertIsNotNone(self.salary.paid_at)

        # Verify audit log
        log = SalaryPaymentLog.objects.filter(salary=self.salary, action='PAID').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.admin)
        self.assertEqual(log.previous_state, 'Unpaid')
        self.assertEqual(log.new_state, 'Paid')

    def test_admin_mark_paid_salary_as_unpaid(self):
        """2. Admin can mark a paid salary as Unpaid."""
        self.salary.is_paid = True
        self.salary.paid_by = self.admin
        self.salary.paid_at = timezone.now()
        self.salary._allow_status_change = True
        self.salary.save()

        self.client.login(username='admin_boss', password='password')
        response = self.client.post(f'/salary/{self.salary.id}/mark-unpaid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertFalse(self.salary.is_paid)
        self.assertEqual(self.salary.unpaid_by, self.admin)
        self.assertIsNotNone(self.salary.unpaid_at)
        # Previous payment metadata preserved
        self.assertIsNotNone(self.salary.paid_at)

        # Verify audit log
        log = SalaryPaymentLog.objects.filter(salary=self.salary, action='UNPAID').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.admin)
        self.assertEqual(log.previous_state, 'Paid')
        self.assertEqual(log.new_state, 'Unpaid')

    def test_manager_mark_unpaid_salary_as_paid(self):
        """3. Manager can mark an unpaid salary as Paid."""
        self.client.login(username='manager_bob', password='password')
        response = self.client.post(f'/salary/{self.salary.id}/mark-paid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)
        self.assertEqual(self.salary.paid_by, self.manager)
        self.assertIsNotNone(self.salary.paid_at)

        # Verify audit log
        log = SalaryPaymentLog.objects.filter(salary=self.salary, action='PAID').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.manager)

    def test_manager_mark_paid_salary_as_unpaid(self):
        """4. Manager can mark a paid salary as Unpaid."""
        self.salary.is_paid = True
        self.salary.paid_by = self.admin
        self.salary.paid_at = timezone.now()
        self.salary._allow_status_change = True
        self.salary.save()

        self.client.login(username='manager_bob', password='password')
        response = self.client.post(f'/salary/{self.salary.id}/mark-unpaid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertFalse(self.salary.is_paid)
        self.assertEqual(self.salary.unpaid_by, self.manager)
        self.assertIsNotNone(self.salary.unpaid_at)

        # Verify audit log
        log = SalaryPaymentLog.objects.filter(salary=self.salary, action='UNPAID').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.manager)

    def test_unauthorized_user_cannot_mark_paid_or_unpaid(self):
        """5. Unauthorized roles cannot perform these actions."""
        self.client.login(username='regular_joe', password='password')

        # Try mark paid
        response = self.client.post(f'/salary/{self.salary.id}/mark-paid/')
        self.assertEqual(response.status_code, 403)
        self.salary.refresh_from_db()
        self.assertFalse(self.salary.is_paid)

        # Set to paid and try mark unpaid
        self.salary.is_paid = True
        self.salary._allow_status_change = True
        self.salary.save()

        response = self.client.post(f'/salary/{self.salary.id}/mark-unpaid/')
        self.assertEqual(response.status_code, 403)
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)

    def test_duplicate_status_change_prevention(self):
        """6. Prevent invalid duplicate transitions."""
        self.client.login(username='manager_bob', password='password')

        # Salary is already unpaid, trying to mark unpaid should warn and redirect
        response = self.client.post(f'/salary/{self.salary.id}/mark-unpaid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertFalse(self.salary.is_paid)

        # Mark paid
        self.client.post(f'/salary/{self.salary.id}/mark-paid/')
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)

        # Try mark paid again
        response = self.client.post(f'/salary/{self.salary.id}/mark-paid/')
        self.assertEqual(response.status_code, 302)
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)

    def test_salary_page_ui_buttons_visibility(self):
        """7. Verify button visibility on Salary page for Manager vs Unauthorized."""
        # Unpaid state
        self.client.login(username='manager_bob', password='password')
        response = self.client.get('/salary/?month=2026-07')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mark Paid")
        self.assertNotContains(response, "Mark Unpaid")

        # Paid state
        self.salary.is_paid = True
        self.salary._allow_status_change = True
        self.salary.save()

        response = self.client.get('/salary/?month=2026-07')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mark Unpaid")

        # Unauthorized user
        self.client.login(username='regular_joe', password='password')
        response = self.client.get('/salary/?month=2026-07')
        self.assertEqual(response.status_code, 403)


class SecurityAndIntegrityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='sec_admin', password='password', email='sec_admin@test.com')
        self.manager = User.objects.create_user(username='sec_manager', password='password', is_staff=True, is_superuser=False)
        self.regular_user = User.objects.create_user(username='sec_regular', password='password', is_staff=False, is_superuser=False)
        self.employee = Employee.objects.create(
            name="John SecTester",
            phone="1122334455",
            address="Audit St",
            designation="QA Specialist",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 1, 1)
        )
        self.month = datetime.date(2026, 7, 1)
        self.salary = Salary.objects.create(
            employee=self.employee,
            month=self.month,
            monthly_salary=26000.00,
            total_hours=240,
            gross_salary=20000.00,
            final_salary=20000.00,
            is_paid=False
        )

    def test_http_method_not_allowed_for_get_on_salary_actions(self):
        """SEC-01: State-changing mark-paid and mark-unpaid MUST reject GET with 405 Method Not Allowed."""
        self.client.login(username='sec_admin', password='password')

        # GET on mark-paid
        response = self.client.get(f'/salary/{self.salary.id}/mark-paid/')
        self.assertEqual(response.status_code, 405)
        self.salary.refresh_from_db()
        self.assertFalse(self.salary.is_paid)

        # Mark paid via POST
        self.salary.is_paid = True
        self.salary._allow_status_change = True
        self.salary.save()

        # GET on mark-unpaid
        response = self.client.get(f'/salary/{self.salary.id}/mark-unpaid/')
        self.assertEqual(response.status_code, 405)
        self.salary.refresh_from_db()
        self.assertTrue(self.salary.is_paid)

    def test_unauthorized_user_access_control(self):
        """SEC-09: Unauthorized users cannot access protected views."""
        self.client.login(username='sec_regular', password='password')

        endpoints = [
            '/dashboard/',
            '/employees/',
            '/employees/add/',
            f'/employee/{self.employee.id}/',
            '/workhours/',
            '/workhours/history/',
            '/workhours/view/',
            '/advance/',
            '/salary/',
            '/reports/',
            '/reports/export/csv/',
            '/reports/export/excel/',
            '/managers/',
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, f"Endpoint {url} should return 403 for regular user")

    def test_vertical_privilege_escalation_blocked(self):
        """SEC-08: Manager cannot access admin-only manager management or delete employees."""
        self.client.login(username='sec_manager', password='password')

        # Managers cannot access manager management views
        for url in ['/managers/', '/managers/add/']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

        # Managers cannot delete employees
        response = self.client.post(f'/employees/{self.employee.id}/delete/')
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)

    def test_csv_injection_sanitization(self):
        """SEC-04: Formula prefixes (=, +, -, @) are sanitized with leading single quote."""
        malicious_employee = Employee.objects.create(
            name="=cmd|' /C calc'!A0",
            phone="9988776655",
            address="Test Addr",
            designation="@Supervisor",
            monthly_salary=30000.00,
            joining_date=datetime.date(2026, 1, 1)
        )
        Salary.objects.create(
            employee=malicious_employee,
            month=self.month,
            monthly_salary=30000.00,
            total_hours=200,
            gross_salary=20000.00,
            final_salary=20000.00
        )

        self.client.login(username='sec_admin', password='password')
        response = self.client.get(f'/reports/export/csv/?month=2026-07')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Ensure formula prefix is escaped with single quote
        self.assertIn("'=cmd|' /C calc'!A0", content)
        self.assertIn("'@Supervisor", content)
        self.assertNotIn("\n=cmd", content)

    def test_negative_and_zero_advance_payment_rejected(self):
        """SEC-05: Advance payment must be greater than zero."""
        adv_neg = AdvancePayment(
            employee=self.employee,
            amount=Decimal('-500.00'),
            given_by=self.admin,
            date=datetime.date(2026, 7, 5)
        )
        with self.assertRaises(ValidationError) as ctx:
            adv_neg.full_clean()
        self.assertIn("greater than zero", str(ctx.exception))

        adv_zero = AdvancePayment(
            employee=self.employee,
            amount=Decimal('0.00'),
            given_by=self.admin,
            date=datetime.date(2026, 7, 5)
        )
        with self.assertRaises(ValidationError) as ctx:
            adv_zero.full_clean()
        self.assertIn("greater than zero", str(ctx.exception))

    def test_negative_monthly_salary_rejected(self):
        """SEC-06: Employee monthly salary cannot be negative."""
        emp = Employee(
            name="Negative Salary Guy",
            phone="1231231234",
            address="Street",
            designation="Tester",
            monthly_salary=Decimal('-15000.00'),
            joining_date=datetime.date(2026, 1, 1)
        )
        with self.assertRaises(ValidationError) as ctx:
            emp.clean()
        self.assertIn("cannot be negative", str(ctx.exception))


class MonthlyBulkWorkHoursSaveTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='mgr_user',
            password='Password123!',
            is_staff=True
        )
        self.emp1 = Employee.objects.create(
            name="Alice Wonder",
            phone="1112223334",
            address="Street 1",
            designation="Developer",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 1, 1),
            status='Active'
        )
        self.emp2 = Employee.objects.create(
            name="Bob Builder",
            phone="2223334445",
            address="Street 2",
            designation="Designer",
            monthly_salary=26000.00,
            joining_date=datetime.date(2026, 1, 1),
            status='Active'
        )
        self.emp3 = Employee.objects.create(
            name="Charlie Chaplin",
            phone="3334445556",
            address="Street 3",
            designation="Developer",
            monthly_salary=39000.00,
            joining_date=datetime.date(2026, 1, 1),
            status='Active'
        )
        self.client.login(username='mgr_user', password='Password123!')

    def test_save_hours_single_employee_october_2026(self):
        """Save hours for one employee for October 2026 and verify persistence and payroll."""
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '180.00'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 1)
        self.assertIn("October 2026", data['message'])

        # Verify database record created for Oct 2026, NOT current month
        oct_date = datetime.date(2026, 10, 1)
        mwh = MonthlyWorkHours.objects.filter(employee=self.emp1, month=oct_date).first()
        self.assertIsNotNone(mwh)
        self.assertEqual(mwh.total_hours, Decimal('180.00'))
        self.assertEqual(mwh.marked_by, self.manager)

        # Verify salary recalculation for Oct 2026
        salary = Salary.objects.filter(employee=self.emp1, month=oct_date).first()
        self.assertIsNotNone(salary)
        self.assertEqual(salary.total_hours, Decimal('180.00'))
        # 26000 / 26 = 1000.00; 1000 / 12 = 83.33; 180 * 83.33 = 14999.40
        self.assertEqual(salary.gross_salary, Decimal('14999.40'))
        self.assertEqual(salary.final_salary, Decimal('14999.40'))

    def test_save_hours_multiple_selected_employees(self):
        """Save hours for multiple selected employees while leaving others unaffected."""
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '200',
                str(self.emp2.id): '240'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 2)

        oct_date = datetime.date(2026, 10, 1)
        self.assertEqual(MonthlyWorkHours.objects.get(employee=self.emp1, month=oct_date).total_hours, Decimal('200.00'))
        self.assertEqual(MonthlyWorkHours.objects.get(employee=self.emp2, month=oct_date).total_hours, Decimal('240.00'))
        # emp3 was not in entries, so no record for Oct 2026
        self.assertFalse(MonthlyWorkHours.objects.filter(employee=self.emp3, month=oct_date).exists())

    def test_save_hours_all_employees(self):
        """Save hours for all employees at once."""
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '240',
                str(self.emp2.id): '240',
                str(self.emp3.id): '264'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 3)
        self.assertEqual(data['grand_total_hours'], 744.0)

    def test_save_hours_zero_hours(self):
        """Save hours for an employee with zero hours (0)."""
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '0'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 1)

        oct_date = datetime.date(2026, 10, 1)
        mwh = MonthlyWorkHours.objects.get(employee=self.emp1, month=oct_date)
        self.assertEqual(mwh.total_hours, Decimal('0.00'))

        salary = Salary.objects.get(employee=self.emp1, month=oct_date)
        self.assertEqual(salary.total_hours, Decimal('0.00'))
        self.assertEqual(salary.gross_salary, Decimal('0.00'))
        self.assertEqual(salary.final_salary, Decimal('0.00'))

    def test_update_previously_saved_hours_no_duplicates(self):
        """Updating existing saved hours modifies the record and does not create duplicates."""
        oct_date = datetime.date(2026, 10, 1)
        MonthlyWorkHours.objects.create(
            employee=self.emp1,
            month=oct_date,
            total_hours=Decimal('150.00'),
            marked_by=self.manager
        )

        # Update to 210 hours
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '210'
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Check only 1 record exists
        count = MonthlyWorkHours.objects.filter(employee=self.emp1, month=oct_date).count()
        self.assertEqual(count, 1)

        mwh = MonthlyWorkHours.objects.get(employee=self.emp1, month=oct_date)
        self.assertEqual(mwh.total_hours, Decimal('210.00'))

    def test_reload_page_persisted_values(self):
        """Verify saved hours for October 2026 persist and are loaded on GET."""
        oct_date = datetime.date(2026, 10, 1)
        MonthlyWorkHours.objects.create(
            employee=self.emp1,
            month=oct_date,
            total_hours=Decimal('220.00'),
            marked_by=self.manager
        )

        response = self.client.get('/workhours/?month=10&year=2026')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Wonder")
        self.assertContains(response, 'value="220"')

    def test_atomic_transaction_rollback_on_error(self):
        """If one entry in bulk save has invalid hours, entire transaction is rolled back."""
        oct_date = datetime.date(2026, 10, 1)
        payload = {
            'month': 10,
            'year': 2026,
            'entries': {
                str(self.emp1.id): '200',
                str(self.emp2.id): '-50'  # Invalid!
            }
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("cannot be negative", data['error'])

        # Ensure emp1 was NOT saved due to atomic rollback
        self.assertFalse(MonthlyWorkHours.objects.filter(employee=self.emp1, month=oct_date).exists())
        self.assertFalse(MonthlyWorkHours.objects.filter(employee=self.emp2, month=oct_date).exists())

    def test_unauthorized_user_receives_403_json(self):
        """Non-manager/non-staff user submitting AJAX save receives a 403 JSON response, not HTML."""
        regular = User.objects.create_user(username='regular_staff', password='Password123!')
        self.client.login(username='regular_staff', password='Password123!')

        payload = {
            'month': 10,
            'year': 2026,
            'entries': {str(self.emp1.id): '100'}
        }
        response = self.client.post(
            '/workhours/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("Permission denied", data['error'])

    def test_malformed_json_returns_400_json(self):
        """Malformed JSON payload returns a 400 JSON response, not HTML."""
        response = self.client.post(
            '/workhours/',
            data='{invalid_json:',
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("Invalid JSON payload", data['error'])

    def test_csrf_failure_handler_returns_json_for_ajax(self):
        """Custom csrf_failure returns JSON for AJAX/JSON requests."""
        from django.test import RequestFactory
        from payroll.views import csrf_failure
        rf = RequestFactory()
        req = rf.post('/workhours/', data='{}', content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        response = csrf_failure(req, reason="CSRF token missing")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        import json as pyjson
        data = pyjson.loads(response.content.decode('utf-8'))
        self.assertFalse(data['success'])
        self.assertIn("CSRF verification failed", data['error'])
