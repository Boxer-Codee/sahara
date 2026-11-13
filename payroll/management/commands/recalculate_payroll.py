import datetime
from django.core.management.base import BaseCommand
from payroll.services import PayrollService

class Command(BaseCommand):
    help = 'Recalculates and repairs payroll for all employees for selected months (format: YYYY-MM)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--months',
            nargs='*',
            type=str,
            help='List of months to recalculate/repair in YYYY-MM format (e.g., 2026-04 2026-05 2026-06)'
        )

    def handle(self, *args, **options):
        months_input = options.get('months')

        # Default to historical months if none specified
        if not months_input:
            months_input = ['2026-04', '2026-05', '2026-06']

        self.stdout.write(self.style.WARNING(f"Starting payroll recalculation/repair for: {', '.join(months_input)}..."))

        for month_str in months_input:
            try:
                yr, mo = month_str.split('-')
                month_date = datetime.date(int(yr), int(mo), 1)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid month format: {month_str}. Must be YYYY-MM."))
                continue

            self.stdout.write(f"Processing {month_date.strftime('%B %Y')} (applying repair logic)...")

            # Force recalculation to repair historical values (including paid months) while preserving is_paid status
            salaries = PayrollService.recalculate_month(month_date, force=True)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully processed/repaired {len(salaries)} salary records for {month_date.strftime('%B %Y')}."
                )
            )

        self.stdout.write(self.style.SUCCESS("All recalculations and historical repairs complete!"))
