import random
import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.models import User
from payroll.models import Employee, WorkHours, AdvancePayment, Salary

class Command(BaseCommand):
    help = 'Seeds the database with test employees, work hours, and advance data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding database...')

        employees = [
            {'name': 'John Doe', 'phone': '9876543210', 'designation': 'Manager', 'monthly_salary': 26000.00, 'address': '123 Main St'},
            {'name': 'Jane Smith', 'phone': '9876543211', 'designation': 'Packer', 'monthly_salary': 13000.00, 'address': '456 Oak Ave'},
            {'name': 'Mike Johnson', 'phone': '9876543212', 'designation': 'Supervisor', 'monthly_salary': 20800.00, 'address': '789 Pine Rd'},
            {'name': 'Sarah Williams', 'phone': '9876543213', 'designation': 'Packer', 'monthly_salary': 13000.00, 'address': '321 Elm St'},
            {'name': 'David Brown', 'phone': '9876543214', 'designation': 'Driver', 'monthly_salary': 15600.00, 'address': '654 Maple Dr'},
        ]

        today = datetime.date.today()
        first_day_of_month = today.replace(day=1)
        
        # Create employees
        db_employees = []
        for emp_data in employees:
            emp = Employee.objects.create(
                name=emp_data['name'],
                phone=emp_data['phone'],
                address=emp_data['address'],
                designation=emp_data['designation'],
                monthly_salary=emp_data['monthly_salary'],
                joining_date=today.replace(year=today.year - 1)
            )
            db_employees.append(emp)
            self.stdout.write(self.style.SUCCESS(f'Created employee {emp.name} ({emp.emp_id})'))

        # Create work hours for current month up to today
        current_date = first_day_of_month
        while current_date <= today:
            if current_date.weekday() != 6:  # Skip Sundays
                for emp in db_employees:
                    if random.random() > 0.1:  # 90% chance to work
                        hours = random.choice([8, 10, 12, 12, 12])
                        WorkHours.objects.update_or_create(
                            employee=emp,
                            date=current_date,
                            defaults={'hours_worked': hours}
                        )
            current_date += datetime.timedelta(days=1)
            
        self.stdout.write(self.style.SUCCESS('Successfully seeded work hours data'))
        
        # Ensure a default admin user exists
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'is_staff': True,
                'is_superuser': True,
                'email': 'admin@example.com'
            }
        )
        if created:
            admin_user.set_password('admin@123')
            admin_user.save()

        # Give some advance payments
        for emp in db_employees:
            if random.random() > 0.3:
                advance = random.choice([500, 1000, 2000])
                AdvancePayment.objects.create(
                    employee=emp,
                    amount=advance,
                    given_by=admin_user,
                    date=first_day_of_month + datetime.timedelta(days=random.randint(5, 15))
                )
            
        self.stdout.write(self.style.SUCCESS('Successfully recorded advances and auto-calculated salaries via signals'))
        self.stdout.write(self.style.SUCCESS('Database seeding complete!'))
