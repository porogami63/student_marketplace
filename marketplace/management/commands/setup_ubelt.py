"""Populate University Belt schools and listing categories with official colors."""
from django.core.management.base import BaseCommand
from marketplace.models import School, Category


# (name, short_name, primary_color, secondary_color)
# Colors from official school motifs where known
UBELT_SCHOOLS = [
    ('University of Santo Tomas', 'UST', '#FFD700', '#FFFFFF'),      # Gold & White
    ('Far Eastern University', 'FEU', '#006633', '#FFD700'),          # Green & Gold
    ('University of the East', 'UE', '#C41E3A', '#FFFFFF'),           # Red & White
    ('San Beda University', 'San Beda', '#8B0000', '#FFFFFF'),        # Red & White (Red Lions)
    ('De La Salle University', 'DLSU', '#00843D', '#FFFFFF'),         # Green & White
    ('University of the Philippines Manila', 'UP Manila', '#800020', '#FFFFFF'),  # Maroon
    ('Pamantasan ng Lungsod ng Maynila', 'PLM', '#003366', '#FFFFFF'),
    ('Philippine Normal University', 'PNU', '#1E3A8A', '#FFFFFF'),
    ('Colegio de San Juan de Letran', 'Letran', '#002366', '#C41E3A'),  # Blue & Red
    ('Arellano University', 'Arellano', '#228B22', '#FFFFFF'),
    ('Universidad de Manila', 'UDM', '#1E40AF', '#FFFFFF'),
    ('Technological Institute of the Philippines Manila', 'TIP Manila', '#00529B', '#FFFFFF'),
    ('La Consolacion College Manila', 'LCCM', '#1E40AF', '#FFFFFF'),  # Blue Royals
    ('Centro Escolar University Manila', 'CEU Manila', '#8B0000', '#FFD700'),
    ('National Teachers College Manila', 'NTC Manila', '#2563EB', '#FFFFFF'),
]

CATEGORIES = [
    ('Textbooks', 'textbooks', 'book'),
    ('School Supplies', 'school-supplies', 'pencil'),
    ('Electronics', 'electronics', 'laptop'),
    ('Dorm & Living', 'dorm-living', 'house'),
    ('Clothing & Uniforms', 'clothing-uniforms', 'person-badge'),
    ('Study Materials', 'study-materials', 'journal'),
]


class Command(BaseCommand):
    help = 'Populate U-Belt schools and listing categories with colors'

    def handle(self, *args, **options):
        for name, short, primary, secondary in UBELT_SCHOOLS:
            obj, created = School.objects.update_or_create(
                name=name,
                defaults={'short_name': short, 'primary_color': primary, 'secondary_color': secondary}
            )
            if not created:
                obj.primary_color = primary
                obj.secondary_color = secondary
                obj.save()

        self.stdout.write(self.style.SUCCESS(f'Updated {len(UBELT_SCHOOLS)} schools with colors'))

        for name, slug, icon in CATEGORIES:
            Category.objects.get_or_create(slug=slug, defaults={'name': name, 'icon': icon})
        self.stdout.write(self.style.SUCCESS(f'Added {len(CATEGORIES)} categories'))
