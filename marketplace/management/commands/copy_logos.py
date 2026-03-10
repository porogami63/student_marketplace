from django.core.management.base import BaseCommand
from pathlib import Path
import shutil
import os

class Command(BaseCommand):
    help = 'Copy university logos from media to static files'

    def handle(self, *args, **options):
        # Define source and destination paths
        source_dir = Path('media/UNIV LOGOS')
        dest_dir = Path('static/images/university-logos')
        
        # Create destination directory if it doesn't exist
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        if not source_dir.exists():
            self.stdout.write(
                self.style.WARNING(f'Source directory not found: {source_dir}')
            )
            return
        
        # Copy all PNG files from source to destination
        copied_count = 0
        try:
            for logo_file in source_dir.glob('*.png'):
                dest_file = dest_dir / logo_file.name
                shutil.copy2(logo_file, dest_file)
                copied_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully copied {copied_count} university logos to static files')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error copying logos: {str(e)}')
            )
