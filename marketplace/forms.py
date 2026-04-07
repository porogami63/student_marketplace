from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from .models import (
    Listing,
    Profile,
    ForumPost,
    ForumReply,
    Transaction,
    Category,
    ProfilePost,
    ProfilePostComment,
    School,
    UserReport,
    SchoolIDVerificationRequest,
    PUBLIC_UBELT_HUB_CHOICES,
    get_school_specific_meetup_choices,
)
import re

# Category-specific product attribute definitions
PRODUCT_ATTRIBUTES = {
    'textbooks': [
        {'field': 'author', 'label': 'Author', 'type': 'text', 'required': True},
        {'field': 'edition', 'label': 'Edition', 'type': 'text', 'required': False},
        {'field': 'isbn', 'label': 'ISBN (if available)', 'type': 'text', 'required': False},
        {'field': 'subject', 'label': 'Subject/Course', 'type': 'text', 'required': True},
    ],
    'electronics': [
        {'field': 'brand', 'label': 'Brand', 'type': 'text', 'required': True},
        {'field': 'model', 'label': 'Model', 'type': 'text', 'required': True},
        {'field': 'storage', 'label': 'Storage (e.g., 256GB, 8GB)', 'type': 'text', 'required': False},
        {'field': 'ram', 'label': 'RAM (if applicable)', 'type': 'text', 'required': False},
        {'field': 'color', 'label': 'Color', 'type': 'text', 'required': False},
        {'field': 'year_purchased', 'label': 'Year Purchased', 'type': 'number', 'required': False},
    ],
    'clothing': [
        {'field': 'school_college', 'label': 'School / College (if uniform)', 'type': 'text', 'required': False},
        {'field': 'uniform_type', 'label': 'Type (e.g., PE Uniform, Lab Coat, Formal)', 'type': 'text', 'required': False},
        {'field': 'gender', 'label': 'For', 'type': 'select', 'options': ['--', 'Male', 'Female', 'Unisex'], 'required': True},
        {'field': 'size', 'label': 'Size', 'type': 'text', 'required': True},
        {'field': 'material', 'label': 'Material (e.g., Cotton, Polyester)', 'type': 'text', 'required': False},
        {'field': 'brand', 'label': 'Brand (if applicable)', 'type': 'text', 'required': False},
    ],
    'supplies': [
        {'field': 'type', 'label': 'Type of Supply', 'type': 'text', 'required': True},
        {'field': 'quantity', 'label': 'Quantity', 'type': 'text', 'required': False},
        {'field': 'brand', 'label': 'Brand', 'type': 'text', 'required': False},
    ],
    'notes': [
        {'field': 'subject', 'label': 'Subject/Course', 'type': 'text', 'required': True},
        {'field': 'semester', 'label': 'Semester (e.g., 1st Sem AY 2024-25)', 'type': 'text', 'required': False},
        {'field': 'professor', 'label': 'Professor Name', 'type': 'text', 'required': False},
    ],
    'furniture': [
        {'field': 'item_type', 'label': 'Type of Furniture', 'type': 'text', 'required': True},
        {'field': 'material', 'label': 'Material', 'type': 'text', 'required': False},
        {'field': 'dimensions', 'label': 'Dimensions (approx)', 'type': 'text', 'required': False},
        {'field': 'delivery_available', 'label': 'Delivery Available', 'type': 'checkbox', 'required': False},
    ],
}


def _extract_choice_values(choices):
    values = set()
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            for grouped_value, _ in label:
                values.add(grouped_value)
        else:
            values.add(value)
    return values


def _build_grouped_meetup_choices(school):
    grouped_choices = []

    if school is not None:
        school_specific = get_school_specific_meetup_choices(
            short_name=getattr(school, 'short_name', ''),
            name=getattr(school, 'name', ''),
        )
        if school_specific:
            school_label = getattr(school, 'short_name', '') or getattr(school, 'name', 'Lister School')
            grouped_choices.append((f'Near {school_label}', list(school_specific)))

    grouped_choices.append(('Public hubs around U-Belt Manila', list(PUBLIC_UBELT_HUB_CHOICES)))
    return grouped_choices


class SchoolSelect(forms.Select):
    """Custom select widget that adds logo data attributes to school options."""
    
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        
        # Add logo_url as data attribute if school exists
        # value might be a ModelChoiceIteratorValue object, so we need to handle it carefully
        if value:
            try:
                # Try to convert to int - ModelChoiceIteratorValue can be converted
                school_id = int(value) if value else None
                if school_id:
                    school = School.objects.get(pk=school_id)
                    if school.logo_url:
                        option['attrs']['data-logo'] = school.logo_url
            except (TypeError, ValueError, School.DoesNotExist):
                # Silently skip if we can't get the school or convert the value
                pass
        
        return option


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your email',
        'autocomplete': 'email'
    }))

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add classes and validation attrs to fields
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Username (3-20 characters)',
            'minlength': '3',
            'maxlength': '20',
            'autocomplete': 'username',
            'pattern': '[a-zA-Z0-9_-]+'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password (min 8 characters)',
            'minlength': '8'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm password',
            'minlength': '8'
        })
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if len(username) < 3:
            raise forms.ValidationError('Username must be at least 3 characters long.')
        if len(username) > 20:
            raise forms.ValidationError('Username must be 20 characters or less.')
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            raise forms.ValidationError('Username can only contain letters, numbers, hyphens, and underscores.')
        return username
    
    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('This email address is already registered.')
        return email


class EmailTwoFactorVerifyForm(forms.Form):
    code = forms.CharField(
        label='Verification code',
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': 'Enter 6-digit code',
            'pattern': '[0-9]{6}',
        })
    )

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code.isdigit() or len(code) != 6:
            raise forms.ValidationError('Enter a valid 6-digit verification code.')
        return code


class ProfileRegistrationForm(forms.ModelForm):
    """Form for completing profile during registration."""
    
    class Meta:
        model = Profile
        fields = ['full_name', 'school', 'year_level', 'birthday', 'age', 'phone', 'address', 'contact_info']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'placeholder': 'Enter your full name',
                'class': 'form-control',
                'minlength': '2',
                'maxlength': '120',
                'required': True
            }),
            'school': SchoolSelect(attrs={
                'class': 'form-control',
                'required': True
            }),
            'year_level': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'birthday': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'age': forms.NumberInput(attrs={
                'placeholder': 'E.g., 18',
                'class': 'form-control',
                'min': '10',
                'max': '80'
            }),
            'phone': forms.TextInput(attrs={
                'placeholder': 'Mobile number (e.g., 09123456789)',
                'class': 'form-control',
                'pattern': r'^[0-9+\-\s()]{7,20}$',
                'title': 'Valid phone number',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'General meetup area or barangay',
                'class': 'form-control',
                'maxlength': '255',
            }),
            'contact_info': forms.TextInput(attrs={
                'placeholder': 'Social media handles or alternate contact',
                'class': 'form-control',
                'maxlength': '200',
            }),
        }
    
    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name', '').strip()
        if len(full_name) < 2:
            raise forms.ValidationError('Full name must be at least 2 characters long.')
        if len(full_name) > 120:
            raise forms.ValidationError('Full name must be 120 characters or less.')
        return full_name
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if phone and not re.match(r'^[0-9+\-\s()]{7,20}$', phone):
            raise forms.ValidationError('Enter a valid phone number (7-20 digits/symbols).')
        return phone
    
    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None:
            if age < 10:
                raise forms.ValidationError('You must be at least 10 years old.')
            if age > 80:
                raise forms.ValidationError('Please enter a valid age.')
        return age


class ListingForm(forms.ModelForm):
    preferred_payment_methods = forms.MultipleChoiceField(
        choices=Listing.PREFERRED_PAYMENT_CHOICES,
        required=True,
        widget=forms.CheckboxSelectMultiple,
        label='Allowed Payment Methods',
        help_text='Buyers will only see these payment options during checkout.'
    )

    class Meta:
        model = Listing
        fields = [
            'listing_type', 'title', 'description', 'price', 'quantity_total', 'preferred_payment_methods', 'category', 'condition',
            'campus', 'image', 'school', 'contact_info'
        ]
        widgets = {
            'listing_type': forms.RadioSelect(choices=[
                ('wts', 'Want to Sell (WTS) - I have an item to sell'),
                ('wtb', 'Want to Buy (WTB) - I\'m looking for an item to purchase'),
            ], attrs={
                'class': 'form-check-input',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What are you selling?',
                'minlength': '5',
                'maxlength': '200',
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Describe the condition, features, and why you\'re selling it...',
                'maxlength': '2000',
                'minlength': '10'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '₱0.00',
                'min': '0',
                'max': '999999',
                'step': '0.01',
                'inputmode': 'decimal'
            }),
            'quantity_total': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '1',
                'min': '1',
                'max': '9999',
                'step': '1',
                'inputmode': 'numeric'
            }),
            'category': forms.Select(attrs={'class': 'form-control category-select', 'id': 'id_category'}),
            'condition': forms.Select(attrs={'class': 'form-control'}),
            'campus': forms.Select(attrs={'class': 'form-control'}),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'school': SchoolSelect(attrs={'class': 'form-control', 'id': 'id_school'}),
            'contact_info': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone, email, or social media (optional)',
                'maxlength': '200'
            }),
        }
        labels = {
            'campus': 'Preferred meetup location',
        }
        help_texts = {
            'campus': 'Choose a safe, public U-Belt meetup point (optional).',
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.product_attribute_fields = {}
        self._original_quantity_total = self.instance.quantity_total if self.instance and self.instance.pk else None

        preferred_methods = []
        if self.instance and self.instance.pk:
            preferred_methods = self.instance.preferred_payment_methods or []
        if not preferred_methods:
            preferred_methods = ['in_person']
        self.fields['preferred_payment_methods'].initial = preferred_methods

        lister_school = None
        if user is not None and getattr(user, 'is_authenticated', False):
            lister_profile = Profile.objects.select_related('school').filter(user=user).first()
            if lister_profile:
                lister_school = lister_profile.school
        if lister_school is None and self.instance and self.instance.school:
            lister_school = self.instance.school

        campus_choices = [('', 'No preferred meetup spot yet')]
        campus_choices.extend(_build_grouped_meetup_choices(lister_school))

        selected_campus = None
        if self.data:
            selected_campus = (self.data.get('campus') or '').strip() or None
        elif self.instance and self.instance.pk:
            selected_campus = self.instance.campus

        allowed_values = _extract_choice_values(campus_choices)
        if selected_campus and selected_campus not in allowed_values:
            label_lookup = dict(Listing.CAMPUS_CHOICES)
            saved_label = label_lookup.get(selected_campus, f'Saved location ({selected_campus})')
            campus_choices.append(('Saved location', [(selected_campus, saved_label)]))

        self.fields['campus'].choices = campus_choices
        
        # Determine listing type from data or instance
        listing_type = None
        if self.data:
            listing_type = self.data.get('listing_type', 'wts')
        elif self.instance and self.instance.listing_type:
            listing_type = self.instance.listing_type
        else:
            listing_type = 'wts'

        # Hide condition field for WTB listings since it's not applicable
        if listing_type == 'wtb':
            if 'condition' in self.fields:
                self.fields['condition'].widget = forms.HiddenInput()

        # Determine category from data or instance
        category = None
        if self.data:
            category_id = self.data.get('category')
            if category_id and (isinstance(category_id, int) or category_id.isdigit()):
                try:
                    category = Category.objects.get(id=category_id)
                except (Category.DoesNotExist, ValueError):
                    pass
        elif self.instance and self.instance.category:
            category = self.instance.category

        if category:
            self._add_product_fields(category.slug)
    
    def _add_product_fields(self, category_slug):
        """Dynamically add product attribute fields based on category."""
        attributes = PRODUCT_ATTRIBUTES.get(category_slug, [])
        existing_values = self.instance.product_details if self.instance.product_details else {}
        
        for attr in attributes:
            field_name = f"product_{attr['field']}"
            initial_value = existing_values.get(attr['field'], '')
            
            if attr['type'] == 'text':
                self.fields[field_name] = forms.CharField(
                    label=attr['label'],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.TextInput(attrs={
                        'class': 'form-control product-field',
                        'data-field': attr['field'],
                        'maxlength': '200'
                    })
                )
            elif attr['type'] == 'number':
                self.fields[field_name] = forms.IntegerField(
                    label=attr['label'],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control product-field',
                        'data-field': attr['field'],
                        'min': '1900',
                        'max': '2100'
                    })
                )
            elif attr['type'] == 'select':
                self.fields[field_name] = forms.ChoiceField(
                    label=attr['label'],
                    choices=[(x, x) for x in attr.get('options', [])],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.Select(attrs={'class': 'form-control product-field', 'data-field': attr['field']})
                )
            elif attr['type'] == 'checkbox':
                self.fields[field_name] = forms.BooleanField(
                    label=attr['label'],
                    required=False,
                    initial=existing_values.get(attr['field'], False) if self.data is None else self.data.get(field_name),
                    widget=forms.CheckboxInput(attrs={'class': 'product-field', 'data-field': attr['field']})
                )
            
            self.product_attribute_fields[field_name] = attr['field']
    
    def clean(self):
        """Extract product details from form fields."""
        cleaned_data = super().clean()
        product_details = {}
        
        # Collect all product_* fields
        for field_name, original_field in self.product_attribute_fields.items():
            value = cleaned_data.get(field_name)
            if value and value != '--':
                product_details[original_field] = str(value)
        
        # Store in a way we can access in save()
        self.product_details = product_details
        return cleaned_data
    
    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise forms.ValidationError('Title must be at least 5 characters long.')
        if len(title) > 200:
            raise forms.ValidationError('Title must be 200 characters or less.')
        return title
    
    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()
        if description and len(description) < 10:
            raise forms.ValidationError('Description must be at least 10 characters long.')
        if description and len(description) > 2000:
            raise forms.ValidationError('Description must be 2000 characters or less.')
        return description
    
    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None:
            if price < 0:
                raise forms.ValidationError('Price cannot be negative.')
            if price > 999999:
                raise forms.ValidationError('Price is too high. Maximum is ₱999,999.')
            if price == 0:
                raise forms.ValidationError('Price must be greater than zero.')
        return price

    def clean_quantity_total(self):
        quantity_total = self.cleaned_data.get('quantity_total')
        if quantity_total is None:
            return 1
        if quantity_total < 1:
            raise forms.ValidationError('Quantity must be at least 1.')
        if quantity_total > 9999:
            raise forms.ValidationError('Quantity is too high. Maximum is 9,999.')
        return quantity_total

    def clean_preferred_payment_methods(self):
        methods = self.cleaned_data.get('preferred_payment_methods') or []
        if not methods:
            raise forms.ValidationError('Select at least one payment method.')
        valid_codes = {choice[0] for choice in Listing.PREFERRED_PAYMENT_CHOICES}
        invalid = [m for m in methods if m not in valid_codes]
        if invalid:
            raise forms.ValidationError('One or more selected payment methods are invalid.')
        return methods
    
    def save(self, commit=True):
        """Save the listing with product details."""
        instance = super().save(commit=False)
        if hasattr(self, 'product_details'):
            instance.product_details = self.product_details

        methods = self.cleaned_data.get('preferred_payment_methods') or []
        instance.preferred_payment_methods = methods

        if instance.pk:
            original_total = self._original_quantity_total if self._original_quantity_total is not None else instance.quantity_total
            delta = instance.quantity_total - original_total
            instance.quantity_available = max(0, instance.quantity_available + delta)
            if instance.quantity_available > instance.quantity_total:
                instance.quantity_available = instance.quantity_total
        else:
            instance.quantity_available = instance.quantity_total

        instance.is_sold = instance.quantity_available == 0

        if commit:
            instance.save()
        return instance


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['full_name', 'school', 'year_level', 'age', 'birthday', 'phone', 'address', 'bio', 'avatar', 'header_image']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'minlength': '2',
                'maxlength': '120',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'e.g. Sampaloc, Manila or near LRT Legarda',
                'class': 'form-control',
                'maxlength': '255',
            }),
            'bio': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'maxlength': '500',
                'placeholder': 'Tell us about yourself (max 500 chars)'
            }),
            'school': SchoolSelect(attrs={'id': 'id_school', 'class': 'form-control'}),
            'birthday': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'age': forms.NumberInput(attrs=
                {'min': 10, 'max': 80, 'class': 'form-control'}),
            'phone': forms.TextInput(attrs={
                'placeholder': 'Mobile number',
                'class': 'form-control',
                'pattern': r'^[0-9+\-\s()]{7,20}$',
                'title': 'Valid phone number'
            }),

            'avatar': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'header_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'year_level': forms.Select(attrs={'class': 'form-control'})
        }
    
    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name', '').strip()
        if full_name and len(full_name) < 2:
            raise forms.ValidationError('Full name must be at least 2 characters long.')
        if full_name and len(full_name) > 120:
            raise forms.ValidationError('Full name must be 120 characters or less.')
        return full_name
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if phone and not re.match(r'^[0-9+\-\s()]{7,20}$', phone):
            raise forms.ValidationError('Enter a valid phone number.')
        return phone
    
    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None:
            if age < 10:
                raise forms.ValidationError('You must be at least 10 years old.')
            if age > 80:
                raise forms.ValidationError('Please enter a valid age.')
        return age
    
    def clean_bio(self):
        bio = self.cleaned_data.get('bio', '').strip()
        if bio and len(bio) > 500:
            raise forms.ValidationError('Bio must be 500 characters or less.')
        return bio


class MessageForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Type your message...'}))


class ForumPostForm(forms.ModelForm):
    class Meta:
        model = ForumPost
        fields = ['title', 'body', 'listing']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What do you want to discuss?',
                'minlength': '5',
                'maxlength': '200',
                'required': True
            }),
            'body': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Share your listing, ask questions, or chat with the community...',
                'class': 'form-control',
                'minlength': '10',
                'maxlength': '5000'
            }),
            'listing': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['listing'].queryset = Listing.objects.filter(seller=user, is_sold=False)
            self.fields['listing'].required = False
            self.fields['listing'].label = 'Link your listing (optional)'
            self.fields['listing'].empty_label = 'None - just a discussion'
    
    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise forms.ValidationError('Title must be at least 5 characters long.')
        if len(title) > 200:
            raise forms.ValidationError('Title must be 200 characters or less.')
        return title
    
    def clean_body(self):
        body = self.cleaned_data.get('body', '').strip()
        if len(body) < 10:
            raise forms.ValidationError('Post must be at least 10 characters long.')
        if len(body) > 5000:
            raise forms.ValidationError('Post must be 5000 characters or less.')
        return body
    
    def __str__(self):
        return "Forum Post"


class ForumReplyForm(forms.ModelForm):
    class Meta:
        model = ForumReply
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Write a reply...'}),
        }

class PurchaseForm(forms.ModelForm):
    """Form for initiating a purchase with exchange method and notes."""
    class Meta:
        model = Transaction
        fields = [
            'quantity',
            'exchange_method',
            'proposed_meetup_location',
            'proposed_meetup_datetime',
            'notes',
        ]
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1',
                'inputmode': 'numeric',
                'placeholder': 'How many units?'
            }),
            'exchange_method': forms.RadioSelect(choices=Transaction.EXCHANGE_METHOD_CHOICES),
            'proposed_meetup_location': forms.Select(attrs={
                'class': 'form-select',
            }),
            'proposed_meetup_datetime': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Add any notes for the seller (e.g., "Can meet at SM Mall" or "Available after 5pm")',
                'class': 'form-control'
            }),
        }
        labels = {
            'quantity': 'Quantity',
            'exchange_method': 'How would you like to exchange payment & goods?',
            'proposed_meetup_location': 'Proposed meetup location',
            'proposed_meetup_datetime': 'Proposed meetup date & time',
            'notes': 'Message to seller (optional)',
        }

    def __init__(self, *args, **kwargs):
        listing = kwargs.pop('listing', None)
        super().__init__(*args, **kwargs)

        min_schedule = timezone.localtime(timezone.now() + timedelta(minutes=30)).replace(second=0, microsecond=0)
        self.fields['proposed_meetup_datetime'].widget.attrs['min'] = min_schedule.strftime('%Y-%m-%dT%H:%M')

        lister_school = None
        if listing is not None:
            self.fields['quantity'].widget.attrs['max'] = str(max(1, listing.quantity_available))
            self.fields['quantity'].help_text = f'Available quantity: {listing.quantity_available}'

            lister_profile = Profile.objects.select_related('school').filter(user=listing.seller).first()
            if lister_profile:
                lister_school = lister_profile.school
            if lister_school is None:
                lister_school = listing.school

            if listing.campus and not self.initial.get('proposed_meetup_location'):
                self.fields['proposed_meetup_location'].initial = listing.campus

        meetup_choices = [('', 'Select a meetup location')]
        meetup_choices.extend(_build_grouped_meetup_choices(lister_school))

        selected_meetup = None
        if self.data:
            selected_meetup = (self.data.get('proposed_meetup_location') or '').strip() or None
        elif self.initial.get('proposed_meetup_location'):
            selected_meetup = self.initial.get('proposed_meetup_location')

        allowed_values = _extract_choice_values(meetup_choices)
        if selected_meetup and selected_meetup not in allowed_values:
            label_lookup = dict(Listing.CAMPUS_CHOICES)
            saved_label = label_lookup.get(selected_meetup, f'Saved location ({selected_meetup})')
            meetup_choices.append(('Saved location', [(selected_meetup, saved_label)]))

        self.fields['proposed_meetup_location'].choices = meetup_choices

        self.fields['proposed_meetup_location'].required = False
        self.fields['proposed_meetup_datetime'].required = False

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is None:
            quantity = 1
        if quantity < 1:
            raise forms.ValidationError('Quantity must be at least 1.')
        return quantity

    def clean_proposed_meetup_datetime(self):
        proposed_meetup_datetime = self.cleaned_data.get('proposed_meetup_datetime')
        if not proposed_meetup_datetime:
            return proposed_meetup_datetime

        if timezone.is_naive(proposed_meetup_datetime):
            proposed_meetup_datetime = timezone.make_aware(
                proposed_meetup_datetime,
                timezone.get_current_timezone(),
            )

        if proposed_meetup_datetime < timezone.now() - timedelta(minutes=1):
            raise forms.ValidationError('Please choose a future meetup date and time.')

        return proposed_meetup_datetime


class TransactionConfirmForm(forms.ModelForm):
    """Form for seller to confirm transaction with their notes."""
    class Meta:
        model = Transaction
        fields = ['seller_notes']
        widgets = {
            'seller_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Confirm availability, location, or other details (e.g., "Available Sat-Sun 2-5pm" or "My number: 09xxxxxxxxx")',
                'class': 'form-control'
            }),
        }
        labels = {
            'seller_notes': 'Your confirmation & meeting details (optional)',
        }


class SchoolIDVerificationRequestForm(forms.ModelForm):
    class Meta:
        model = SchoolIDVerificationRequest
        fields = ['id_image']
        widgets = {
            'id_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'id_image': 'Upload your school ID',
        }

    def clean_id_image(self):
        id_image = self.cleaned_data.get('id_image')
        if not id_image:
            raise forms.ValidationError('Please upload an image of your school ID.')

        max_size = 5 * 1024 * 1024
        if id_image.size > max_size:
            raise forms.ValidationError('Image is too large. Maximum allowed size is 5MB.')

        allowed_types = {'image/jpeg', 'image/png', 'image/webp'}
        content_type = getattr(id_image, 'content_type', '')
        if content_type and content_type.lower() not in allowed_types:
            raise forms.ValidationError('Only JPEG, PNG, or WEBP images are allowed.')

        return id_image


class ProfilePostForm(forms.ModelForm):
    """Form for creating profile posts with optional images."""
    class Meta:
        model = ProfilePost
        fields = ['content', 'image']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Share your thoughts, updates, or messages with visitors to your profile. Max 1000 characters.',
                'class': 'form-control',
                'maxlength': '1000',
                'minlength': '5'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'content': 'What\'s on your mind?',
            'image': 'Add an image (optional)',
        }
    
    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 5:
            raise forms.ValidationError('Post must be at least 5 characters long.')
        if len(content) > 1000:
            raise forms.ValidationError('Post must be 1000 characters or less.')
        return content


class ProfilePostCommentForm(forms.ModelForm):
    """Form for commenting on profile posts with optional images."""
    class Meta:
        model = ProfilePostComment
        fields = ['content', 'image']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Share a comment or reply... (max 500 characters)',
                'class': 'form-control',
                'maxlength': '500',
                'minlength': '2'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'content': 'Your comment',
            'image': 'Add an image (optional)',
        }
    
    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 2:
            raise forms.ValidationError('Comment must be at least 2 characters long.')
        if len(content) > 500:
            raise forms.ValidationError('Comment must be 500 characters or less.')
        return content


class ReportForm(forms.ModelForm):
    """Minimal report submission form."""

    class Meta:
        model = UserReport
        fields = ['reason', 'description']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Add context (optional but helpful). Include dates, what happened, and any screenshots/details you have.',
                'maxlength': '2000',
            }),
        }

    def clean_description(self):
        description = (self.cleaned_data.get('description') or '').strip()
        if len(description) > 2000:
            raise forms.ValidationError('Description is too long (max 2000 characters).')
        return description